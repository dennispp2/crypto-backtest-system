"""ALLOW / CLAMP / BLOCK only. Never forecast or create a trading signal."""
from dataclasses import asdict, dataclass

from ai_shadow.decision_models import validate_decision
from ai_shadow.errors import AIError


@dataclass(frozen=True)
class RiskConfig:
    max_total_crypto_exposure: float = 0.95
    max_single_cycle_exposure_change: float = 0.20
    minimum_confidence_to_change_position: float = 0.65
    no_leverage: bool = True
    no_short: bool = True
    spot_only: bool = True

    def __post_init__(self):
        if not 0 < self.max_total_crypto_exposure <= 0.95 or not 0 < self.max_single_cycle_exposure_change <= 0.20:
            raise ValueError("RISK_CONFIG_UNSAFE")
        if not 0.65 <= self.minimum_confidence_to_change_position <= 1 or not all((self.no_leverage, self.no_short, self.spot_only)):
            raise ValueError("RISK_CONFIG_UNSAFE")


@dataclass(frozen=True)
class RiskResult:
    status: str
    action: str
    exposure: float
    weights: dict
    requested_action: str
    requested_exposure: float | None
    reasons: list[str]

    def to_dict(self):
        return asdict(self)


class RiskGateway:
    def __init__(self, config=None):
        self.config = config or RiskConfig()

    def evaluate(self, decision, current_weights, *, critical_ok=True, frozen_hash_pass=True, duplicate=False):
        current = current_weights["BTC"] + current_weights["ETH"]

        def hold(reason, blocked=True):
            return RiskResult("BLOCK" if blocked else "ALLOW", "HOLD", current,
                              dict(current_weights), str(decision.get("action", "INVALID")),
                              decision.get("target_total_exposure"), [reason])

        try:
            validate_decision(decision)
        except AIError:
            return hold("INVALID_STRUCTURED_OUTPUT")
        if not critical_ok:
            return hold("CRITICAL_DATA_STALE")
        if duplicate:
            return hold("DUPLICATE_DECISION_ID")
        if decision["data_quality"] == "POOR":
            return hold("DATA_QUALITY_POOR")
        if decision["confidence"] < self.config.minimum_confidence_to_change_position:
            return hold("LOW_CONFIDENCE", False)
        action, requested = decision["action"], decision["target_total_exposure"]
        if action == "HOLD":
            return hold("REQUESTED_HOLD", False)
        if action in {"ADD", "STRONG_ADD"} and (decision["risk_veto"] or requested < current - 1e-8):
            return hold("RISK_VETO" if decision["risk_veto"] else "ACTION_DIRECTION_CONFLICT")
        if action in {"REDUCE", "EXIT"} and requested > current + 1e-8:
            return hold("ACTION_DIRECTION_CONFLICT")
        if action == "EXIT" and requested > 1e-8:
            return hold("EXIT_WEIGHT_CONFLICT")
        if not frozen_hash_pass and requested > current + 1e-8:
            return hold("FROZEN_HASH_FAIL")
        reasons = []
        approved = min(requested, self.config.max_total_crypto_exposure)
        if approved != requested:
            reasons.append("MAX_EXPOSURE_CLAMP")
        limit = self.config.max_single_cycle_exposure_change
        clamped = min(max(approved, max(0.0, current - limit)), current + limit)
        if abs(clamped - approved) > 1e-10:
            reasons.append("EXPOSURE_CHANGE_CLAMP")
        # For a clamped EXIT, retain existing BTC:ETH rather than invent a tilt.
        denominator = requested or current
        btc_ratio = (decision["target_btc_weight"] if requested else current_weights["BTC"]) / denominator if denominator else 0.625
        weights = {"BTC": clamped * btc_ratio, "ETH": clamped * (1 - btc_ratio), "Cash": 1 - clamped}
        return RiskResult("CLAMP" if reasons else "ALLOW", action, clamped, weights, action, requested, reasons)
