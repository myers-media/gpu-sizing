"""Cost model: demand, GPU sizing, local TCO simulation, cloud spend, break-even.

Mirrors the math structure of the AMD tokenomics calculator:
  perUserFit:    service_seconds = in_daily/in_tps + out_daily/out_tps
                 capacity_seconds = hours*3600 ; feasible if service <= capacity
  local TCO:     cohort purchases, lifetime, residual value, terminal value, NPV
  cloud:         monthly tokens * $/Mtok * adjustment factors
  break-even:    first month cumulative local <= cumulative cloud
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace


# ---------------------------------------------------------------- demand


@dataclass(frozen=True)
class Demand:
    """Workload demand, expressed per user per day plus fleet size."""

    users: int
    input_tpd_per_user: float      # input tokens / user / day
    output_tpd_per_user: float     # output tokens / user / day
    workdays_per_month: float      # active days per calendar month
    growth_pct_per_month: float    # month-over-month growth in demand

    @property
    def in_daily(self) -> float:
        return self.users * self.input_tpd_per_user

    @property
    def out_daily(self) -> float:
        return self.users * self.output_tpd_per_user

    def growth_factor(self, month: int) -> float:
        return (1.0 + self.growth_pct_per_month / 100.0) ** (month - 1)

    def monthly_tokens(self, month: int) -> tuple[float, float]:
        """Total input/output tokens for a month (1-indexed)."""
        gf = self.growth_factor(month)
        base = self.workdays_per_month
        return self.in_daily * base * gf, self.out_daily * base * gf


# ---------------------------------------------------------------- pricing


@dataclass(frozen=True)
class CloudPricing:
    """Cloud API pricing per 1M tokens plus cost adjustments."""

    input_price: float             # $ / 1M input tokens
    output_price: float            # $ / 1M output tokens
    cache_hit_pct: float = 0.0     # fraction of input tokens served from cache
    cache_read_mult: float = 0.10  # cached reads billed at ~10% of base
    batch_discount_pct: float = 0.0
    overhead_pct: float = 0.0      # e.g. platform/data-transfer overhead
    fixed_monthly: float = 0.0     # fixed $/month fees (egress tiers, seats)

    def input_factor(self) -> float:
        h = min(max(self.cache_hit_pct, 0.0), 100.0) / 100.0
        return 1.0 - h + h * self.cache_read_mult

    def common_factor(self) -> float:
        batch = 1.0 - min(max(self.batch_discount_pct, 0.0), 100.0) / 100.0
        return batch * (1.0 + self.overhead_pct / 100.0)

    def monthly_cost(self, tokens_in: float, tokens_out: float) -> dict:
        f_in = self.input_factor()
        f = self.common_factor()
        c_in = tokens_in / 1e6 * self.input_price * f_in * f
        c_out = tokens_out / 1e6 * self.output_price * f
        return {
            "input": c_in,
            "output": c_out,
            "total": c_in + c_out + self.fixed_monthly,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
        }


# ---------------------------------------------------------------- hardware


@dataclass(frozen=True)
class GpuSpec:
    key: str
    label: str
    price: float                   # $ per unit (capex)
    watts: float                   # sustained power draw
    in_tps: float                  # sustained input tokens/sec per GPU
    out_tps: float                 # sustained output tokens/sec per GPU

    def service_seconds_per_day(self, in_daily: float, out_daily: float) -> float:
        if self.in_tps <= 0 or self.out_tps <= 0:
            return math.inf
        return in_daily / self.in_tps + out_daily / self.out_tps


@dataclass(frozen=True)
class Ownership:
    """Capex/lifecycle and power assumptions for the local fleet."""

    duty_hours_per_day: float = 24.0
    power_days_per_month: float = 30.0
    pue: float = 1.2
    elec_rate: float = 0.15        # $ / kWh
    hosting_per_gpu_month: float = 50.0   # maintenance/hosting $ per GPU-month
    target_utilization_pct: float = 70.0  # sizing headroom
    hardware_life_months: int = 36
    residual_pct: float = 20.0     # resale value at end of life
    discount_rate_pct: float = 8.0  # annual, for NPV

    def capacity_seconds(self) -> float:
        return self.duty_hours_per_day * 3600.0 * (
            self.target_utilization_pct / 100.0
        )

    def energy_cost_per_gpu_month(self, gpu: GpuSpec) -> float:
        kwh = (gpu.watts / 1000.0) * self.duty_hours_per_day \
            * self.power_days_per_month * self.pue
        return kwh * self.elec_rate


# ---------------------------------------------------------------- sizing


def required_gpus(
    in_daily: float,
    out_daily: float,
    gpu: GpuSpec,
    own: Ownership,
) -> int:
    """GPUs needed so daily service time fits duty hours at target utilization."""
    if in_daily <= 0 and out_daily <= 0:
        return 0
    service = gpu.service_seconds_per_day(in_daily, out_daily)
    if math.isinf(service):
        return math.inf
    cap = own.capacity_seconds()
    if cap <= 0:
        return math.inf
    return max(1, math.ceil(service / cap - 1e-9))


def utilization(in_daily: float, out_daily: float,
                gpu: GpuSpec, n_gpus: int, own: Ownership) -> float:
    if n_gpus <= 0:
        return math.inf
    service = gpu.service_seconds_per_day(in_daily, out_daily)
    return service / (n_gpus * own.duty_hours_per_day * 3600.0)


# ---------------------------------------------------------------- simulation


def simulate(
    demand: Demand,
    pricing: CloudPricing,
    gpu: GpuSpec,
    own: Ownership,
    months: int,
    local_share: float,
) -> dict:
    """Run all three paths (all-cloud, all-local, hybrid) over `months`.

    local_share: fraction of workload served by local GPUs (0..1).
    Returns monthly series + summary metrics.
    """
    months = max(1, int(months))
    local_share = min(max(local_share, 0.0), 1.0)
    life = max(1, int(own.hardware_life_months))
    residual = min(max(own.residual_pct, 0.0), 100.0) / 100.0
    d = own.discount_rate_pct / 100.0

    # ---- cloud path (serves the share NOT covered locally) ----
    cloud_monthly, cloud_cum = [], 0.0
    for m in range(1, months + 1):
        ti, to = demand.monthly_tokens(m)
        c = pricing.monthly_cost(ti * (1.0 - local_share), to * (1.0 - local_share))
        cloud_cum += c["total"]
        cloud_monthly.append(c["total"])

    # ---- local fleet path (cohort simulation, AMD-style) ----
    cohorts: list[tuple[int, int]] = []  # (count, purchase_month)
    local_monthly, local_opex, local_capex, units_series = [], [], [], []
    cum = 0.0
    gross_purchases = 0.0
    retirement_credits = 0.0
    for m in range(1, months + 1):
        # retire cohorts past their life; credit residual value
        capex_cash = 0.0
        kept = []
        for count, purchased in cohorts:
            if m - purchased >= life:
                credit = count * gpu.price * residual
                capex_cash -= credit
                retirement_credits += credit
            else:
                kept.append((count, purchased))
        cohorts = kept
        active = sum(c for c, _ in cohorts)

        # buy what this month's demand needs (grow-as-you-go); sizing on DAILY tokens
        gf = demand.growth_factor(m)
        need = required_gpus(
            demand.in_daily * gf * local_share,
            demand.out_daily * gf * local_share, gpu, own,
        )
        if need and need > active:
            buy = need - active
            cohorts.append((buy, m))
            capex_cash += buy * gpu.price
            gross_purchases += buy * gpu.price
            active = need

        energy = active * own.energy_cost_per_gpu_month(gpu)
        opex = energy + active * own.hosting_per_gpu_month
        month_cash = capex_cash + opex
        cum += month_cash
        local_monthly.append(month_cash)
        local_opex.append(opex)
        local_capex.append(capex_cash)
        units_series.append(active)

    peak_units = max(units_series, default=0)

    # terminal value of remaining fleet at horizon end
    terminal = 0.0
    for count, purchased in cohorts:
        age = months - purchased + 1
        remaining = min(max(1.0 - age / life, 0.0), 1.0)
        terminal += count * gpu.price * (residual + (1.0 - residual) * remaining)

    local_tco = sum(local_monthly) - terminal
    npv = 0.0
    for i, v in enumerate(local_monthly, start=1):
        npv += v / (1.0 + d) ** (i / 12.0)
    npv -= terminal / (1.0 + d) ** (months / 12.0)

    # ---- reference paths for the comparison chart ----
    def cloud_full() -> list[float]:
        cumv, out = 0.0, []
        for m in range(1, months + 1):
            ti, to = demand.monthly_tokens(m)
            c = pricing.monthly_cost(ti, to)
            cumv += c["total"]
            out.append(c["total"])
        return out

    def local_full() -> tuple[list[float], list[int]]:
        c2: list[tuple[int, int]] = []
        cumv, out, us = 0.0, [], []
        for m in range(1, months + 1):
            capex_cash = 0.0
            kept = []
            for count, purchased in c2:
                if m - purchased >= life:
                    capex_cash -= count * gpu.price * residual
                else:
                    kept.append((count, purchased))
            c2 = kept
            active = sum(c for c, _ in c2)
            gf = demand.growth_factor(m)
            need = required_gpus(
                demand.in_daily * gf, demand.out_daily * gf, gpu, own,
            )
            if need and need > active:
                c2.append((need - active, m))
                capex_cash += (need - active) * gpu.price
                active = need
            energy = active * own.energy_cost_per_gpu_month(gpu)
            opex = energy + active * own.hosting_per_gpu_month
            month_cash = capex_cash + opex
            cumv += month_cash
            out.append(month_cash)
            us.append(active)
        return out, us

    cloud_full_series = cloud_full()
    local_full_series, local_full_units = local_full()

    # cumulative series
    def cumulative(xs):
        out, s = [], 0.0
        for x in xs:
            s += x
            out.append(s)
        return out

    cum_cloud_full = cumulative(cloud_full_series)
    cum_local_full = cumulative(local_full_series)
    cum_local = cumulative(local_monthly)
    cum_cloud = cumulative(cloud_monthly)

    # ---- break-even: first month hybrid cumulative <= all-cloud cumulative ----
    be_month = None
    for i in range(months):
        if cum_local[i] <= cum_cloud_full[i] + 1e-9:
            be_month = i + 1
            break

    # all-local break-even vs all-cloud
    be_local_month = None
    for i in range(months):
        if cum_local_full[i] <= cum_cloud_full[i] + 1e-9:
            be_local_month = i + 1
            break

    # last-month detail for display
    last_ti, last_to = demand.monthly_tokens(months)
    cloud_last = pricing.monthly_cost(last_ti * (1.0 - local_share),
                                      last_to * (1.0 - local_share))

    return {
        "months": months,
        "local_share": local_share,
        # monthly
        "cloud_full": cloud_full_series,
        "local_full": local_full_series,
        "hybrid_cloud": cloud_monthly,
        "hybrid_local": local_monthly,
        "hybrid_opex": local_opex,
        "hybrid_capex": local_capex,
        "hybrid_units": units_series,
        # cumulative
        "cum_cloud_full": cum_cloud_full,
        "cum_local_full": cum_local_full,
        "cum_hybrid": cum_local_full if local_share >= 1.0
        else [a + b for a, b in zip(cum_local, cum_cloud)],
        # sizing
        "peak_units": peak_units,
        "units_month1": units_series[0] if units_series else 0,
        "peak_utilization": utilization(
            demand.in_daily * demand.growth_factor(months) * local_share,
            demand.out_daily * demand.growth_factor(months) * local_share,
            gpu, peak_units, own,
        ) if peak_units else 0.0,
        "energy_per_gpu_month": own.energy_cost_per_gpu_month(gpu),
        # money
        "tco": local_tco,
        "npv": npv,
        "gross_purchases": gross_purchases,
        "retirement_credits": retirement_credits,
        "terminal_value": terminal,
        "opex_total": sum(local_opex),
        "cloud_total": sum(cloud_monthly),
        "cloud_full_total": sum(cloud_full_series),
        "local_full_total": sum(local_full_series),
        "hybrid_total": (cum_local[-1] + cum_cloud[-1]) if months else 0.0,
        # headline
        "cloud_last": cloud_last,
        "break_even_month": be_month,
        "break_even_local_month": be_local_month,
        "savings": cum_cloud_full[-1] - (cum_local[-1] + cum_cloud[-1])
        if months else 0.0,
        "savings_pct": (
            (cum_cloud_full[-1] - (cum_local[-1] + cum_cloud[-1]))
            / cum_cloud_full[-1] * 100.0
            if cum_cloud_full and cum_cloud_full[-1] > 0 else 0.0
        ),
    }


def sensitivity(res_base: dict, demand: Demand, pricing: CloudPricing,
                gpu: GpuSpec, own: Ownership, months: int,
                local_share: float) -> list[dict]:
    """Break-even under three scenarios (conservative / base / aggressive)."""

    def be_of(g, p, d):
        r = simulate(d, p, g, own, months, local_share)
        return r["break_even_month"]

    conservative = {
        "label": "Conservative",
        "note": "GPU throughput -25%, cloud prices +25%, growth +2 pt/mo",
        "break_even": be_of(
            replace(gpu, in_tps=gpu.in_tps * 0.75, out_tps=gpu.out_tps * 0.75),
            replace(pricing, input_price=pricing.input_price * 1.25,
                    output_price=pricing.output_price * 1.25),
            replace(demand, growth_pct_per_month=demand.growth_pct_per_month + 2.0),
        ),
    }
    aggressive = {
        "label": "Aggressive",
        "note": "GPU throughput +25%, cloud prices -25%, growth -2 pt/mo",
        "break_even": be_of(
            replace(gpu, in_tps=gpu.in_tps * 1.25, out_tps=gpu.out_tps * 1.25),
            replace(pricing, input_price=pricing.input_price * 0.75,
                    output_price=pricing.output_price * 0.75),
            replace(demand, growth_pct_per_month=max(
                demand.growth_pct_per_month - 2.0, -10.0)),
        ),
    }
    return [
        conservative,
        {"label": "Base", "note": "as configured",
         "break_even": res_base["break_even_month"]},
        aggressive,
    ]
