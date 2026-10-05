"""Strict server contract plus independent local semantic validation."""
import json
import math
from pathlib import Path

from jsonschema import Draft202012Validator

from ai_shadow.errors import AIError

PACKAGE_DIR = Path(__file__).resolve().parent
DECISION_SCHEMA = json.loads((PACKAGE_DIR / "schemas/ai_decision.schema.json").read_text(encoding="utf-8"))


def validate_decision(value):
    def finite(item):
        if isinstance(item, float) and not math.isfinite(item):
            return False
        if isinstance(item, dict):
            return all(finite(v) for v in item.values())
        if isinstance(item, list):
            return all(finite(v) for v in item)
        return True
    if not finite(value):
        raise AIError('INVALID_STRUCTURED_OUTPUT')
    errors = list(Draft202012Validator(DECISION_SCHEMA).iter_errors(value))
    if errors:
        raise AIError("INVALID_STRUCTURED_OUTPUT")
    if abs(sum(value[k] for k in ("bull_probability", "base_probability", "bear_probability")) - 1) > 1e-6:
        raise AIError("INVALID_STRUCTURED_OUTPUT")
    if abs(sum(value[k] for k in ("target_btc_weight", "target_eth_weight", "target_cash_weight")) - 1) > 1e-6:
        raise AIError("INVALID_STRUCTURED_OUTPUT")
    if abs(value["target_btc_weight"] + value["target_eth_weight"] - value["target_total_exposure"]) > 1e-6:
        raise AIError("INVALID_STRUCTURED_OUTPUT")
    return value
