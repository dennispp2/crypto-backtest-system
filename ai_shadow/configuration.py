"""Conservative defaults. Changing these requires a NEW shadow experiment."""
from dataclasses import dataclass


@dataclass(frozen=True)
class FreshnessPolicy:
    quant_max_age_seconds: int = 8*3600
    daily_max_age_seconds: int = 36*3600
    spot_max_age_seconds: int = 60
    derivatives_max_age_seconds: int = 12*3600
    liquidity_max_age_seconds: int = 72*3600

    def __post_init__(self):
        if min(vars(self).values()) <= 0:
            raise ValueError('FRESHNESS_CONFIG_INVALID')
