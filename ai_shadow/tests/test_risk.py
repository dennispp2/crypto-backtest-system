from ai_shadow.clients.mock import hold_decision
from ai_shadow.risk_gateway import RiskGateway


def test_low_confidence_hold():
    decision = hold_decision(0.9)
    decision.update(action="ADD", confidence=0.4)
    result = RiskGateway().evaluate(decision, {"BTC": 0.4, "ETH": 0.3, "Cash": 0.3})
    assert result.action == "HOLD"
    assert result.weights == {"BTC": 0.4, "ETH": 0.3, "Cash": 0.3}


def test_max_exposure_change_clamp():
    decision = hold_decision(0.9)
    decision["action"] = "ADD"
    result = RiskGateway().evaluate(decision, {"BTC": 0.1, "ETH": 0.1, "Cash": 0.8})
    assert abs(result.exposure - 0.4) < 1e-12
    assert "EXPOSURE_CHANGE_CLAMP" in result.reasons
