"""Only explicitly injected in tests; never selected by production defaults."""
import copy

from ai_shadow.errors import AIError


def hold_decision(exposure=0.7):
    result = {k + "_health": 50 for k in ("market", "macro", "liquidity", "etf_flow",
                                         "derivatives", "onchain", "technical", "event", "post_entry")}
    return {**result, "action": "HOLD", "confidence": 0.8, "market_regime": "NEUTRAL",
            "risk_veto": False, "risk_veto_reasons": [], "bull_probability": 0.3,
            "base_probability": 0.4, "bear_probability": 0.3,
            "target_total_exposure": exposure, "target_btc_weight": exposure * 0.625,
            "target_eth_weight": exposure * 0.375, "target_cash_weight": 1 - exposure,
            "v310_view": "PARTIAL_AGREE", "thesis": ["測試用固定回覆"],
            "key_positive_factors": [], "key_risks": [], "invalidation_conditions": [],
            "data_quality": "PARTIAL", "thesis_status": "Still Valid"}


class MockAIClient:
    def __init__(self, decision=None, failure=None, research_supported=False):
        self.decision = decision or hold_decision()
        self.failure = failure
        self.research_supported = research_supported
        self.calls = []

    def list_models(self):
        return [{"slug": "mock-model", "display_name": "Offline Mock"}]

    def research(self, model, snapshot):
        self.calls.append("research")
        if not self.research_supported:
            raise AIError("WEB_SEARCH_UNAVAILABLE")
        return {"status": "PASS", "brief": "Network-free test research", "sources": []}

    def decide(self, model, snapshot, policy, schema):
        self.calls.append("decide")
        if self.failure:
            raise AIError(self.failure)
        return copy.deepcopy(self.decision)
