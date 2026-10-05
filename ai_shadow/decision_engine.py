from pathlib import Path

from ai_shadow.decision_models import DECISION_SCHEMA, validate_decision
from ai_shadow.errors import AIError
from ai_shadow.snapshot import canonical_hash, utc, validate_asof

POLICY_FILE = Path(__file__).resolve().parent / "policy/decision_policy_v1.md"


class DecisionEngine:
    def __init__(self, client, model, *, clock=utc, policy_file=POLICY_FILE):
        self.client = client
        self.model = model
        self.clock = clock
        self.policy = Path(policy_file).read_text(encoding="utf-8")
        self.policy_hash = canonical_hash({"policy": self.policy})

    def run(self, snapshot):
        if self.model not in {m["slug"] for m in self.client.list_models()}:
            raise AIError("MODEL_NOT_AVAILABLE")
        try:
            research = self.client.research(self.model, snapshot)
        except AIError as exc:
            if exc.code != "WEB_SEARCH_UNAVAILABLE":
                raise
            research = {"status": "WEB_SEARCH_UNAVAILABLE", "brief": "Provider-only analysis", "sources": []}
        decision_time = self.clock().isoformat()
        validate_asof(research, decision_time)
        context = {**snapshot, "decision_time": decision_time, "research_brief": research}
        validate_asof(context, decision_time)
        decision = validate_decision(self.client.decide(self.model, context, self.policy, DECISION_SCHEMA))
        return decision, research, decision_time
