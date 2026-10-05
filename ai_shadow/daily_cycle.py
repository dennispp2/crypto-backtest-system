"""Coordinate results without changing the frozen runner's contract."""
from dataclasses import dataclass

from ai_shadow.orchestrator import AIResult


@dataclass(frozen=True)
class DailyCycleResult:
    v310: object
    ai: AIResult


class DailyCycleOrchestrator:
    def __init__(self, run_v310, ai, progress=None):
        self.run_v310, self.ai = run_v310, ai
        self.progress = progress or (lambda _: None)

    def run(self, *, force=False):
        self.progress('執行 Frozen V3.10')
        result = self.run_v310(force=force)
        if not result.completed and result.outcome != 'TODAY_ALREADY_COMPLETED':
            return DailyCycleResult(result, AIResult('V310_FAILED_AI_BLOCKED'))
        try:
            ai_result = self.ai.run() if self.ai else AIResult('AI_DISABLED')
        except Exception:
            ai_result = AIResult('AI_INTERNAL_ERROR')
        return DailyCycleResult(result, ai_result)
