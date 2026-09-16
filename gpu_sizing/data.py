"""Preset data: cloud model pricing, usage intensity tiers, GPU SKUs.

Token prices are list prices in $ per 1M tokens (2026).
GPU tokens/sec figures are order-of-magnitude sustained single-GPU
throughputs serving a ~7-14B parameter model via vLLM. Calibrate to
your own benchmarks -- this is the single biggest sensitivity in the calc.
"""

CLOUD_MODELS = [
    {"key": "sonnet", "label": "Claude Sonnet", "input": 3.0, "output": 15.0},
    {"key": "opus", "label": "Claude Opus", "input": 5.0, "output": 25.0},
    {"key": "gpt55", "label": "GPT 5.5", "input": 5.0, "output": 30.0},
    {"key": "gemini", "label": "Gemini Pro", "input": 2.0, "output": 12.0},
    {"key": "custom", "label": "Custom", "input": 3.0, "output": 15.0},
]

# Per-user daily token volumes. Based on the AMD tokenomics source workload
# tiers (light = 10% of source, moderate = medium, heavy = full source).
INTENSITY_PRESETS = {
    "light": {
        "label": "Light — casual use (a few prompts/day)",
        "in": 573_713,
        "out": 57_371,
    },
    "moderate": {
        "label": "Moderate — daily professional use",
        "in": 5_737_132,
        "out": 573_713,
    },
    "heavy": {
        "label": "Heavy — power user / all-day LLM work",
        "in": 16_703_089,
        "out": 1_670_309,
    },
    "custom": {
        "label": "Custom — set exact token volumes",
        "in": 1_000_000,
        "out": 100_000,
    },
}

# price: $ per unit (hardware), watts: sustained draw,
# in_tps/out_tps: sustained tokens/sec per GPU (prefill / decode)
GPU_PRESETS = [
    {
        "key": "gb10",
        "label": "NVIDIA GB10 — DGX Spark (128 GB unified)",
        "price": 3999.0,
        "watts": 240.0,
        "in_tps": 350.0,
        "out_tps": 35.0,
    },
    {
        "key": "rpro6k",
        "label": "NVIDIA RTX PRO 6000 Blackwell (96 GB)",
        "price": 8500.0,
        "watts": 600.0,
        "in_tps": 900.0,
        "out_tps": 90.0,
    },
    {
        "key": "h100",
        "label": "NVIDIA H100 SXM (80 GB)",
        "price": 25000.0,
        "watts": 700.0,
        "in_tps": 1600.0,
        "out_tps": 160.0,
    },
    {
        "key": "b200",
        "label": "NVIDIA B200 SXM (192 GB)",
        "price": 35000.0,
        "watts": 1000.0,
        "in_tps": 2800.0,
        "out_tps": 280.0,
    },
    {
        "key": "l40s",
        "label": "NVIDIA L40S (48 GB)",
        "price": 10000.0,
        "watts": 350.0,
        "in_tps": 600.0,
        "out_tps": 60.0,
    },
    {
        "key": "a100",
        "label": "NVIDIA A100 SXM (80 GB)",
        "price": 12000.0,
        "watts": 400.0,
        "in_tps": 750.0,
        "out_tps": 75.0,
    },
    {
        "key": "custom",
        "label": "Custom GPU",
        "price": 5000.0,
        "watts": 300.0,
        "in_tps": 400.0,
        "out_tps": 40.0,
    },
]
