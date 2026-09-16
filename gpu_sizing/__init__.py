"""GPU sizing & cloud savings calculator engine.

Adapted from the cost model of AMD's AI Cost Calculator (tokenomics.amd.com):
- demand from per-user token intensity
- cloud spend from $/Mtok input/output pricing with adjustments
- hardware fit via service-seconds vs capacity-seconds
- local TCO via cohort capex simulation with residual/terminal value
- break-even = first month cumulative local <= cumulative cloud
"""

__version__ = "1.0.0"
