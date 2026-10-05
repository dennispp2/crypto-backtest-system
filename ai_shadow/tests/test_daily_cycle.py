from types import SimpleNamespace

import pytest

from ai_shadow.daily_cycle import DailyCycleOrchestrator
from ai_shadow.orchestrator import AIResult


@pytest.mark.parametrize('outcome,completed,expected', [('SUCCESS',True,True),
    ('TODAY_ALREADY_COMPLETED',False,True), ('MODEL_EXECUTION_FAILED',False,False)])
def test_daily_cycle_calls_v310_then_ai(outcome, completed, expected):
    calls = []
    v310 = SimpleNamespace(outcome=outcome, completed=completed)
    def quant(**kwargs):
        calls.append('v310')
        return v310
    class AI:
        def run(self):
            calls.append('ai')
            return AIResult('GPT_FAILED')
    result = DailyCycleOrchestrator(quant, AI()).run()
    assert calls == ['v310','ai'] if expected else calls == ['v310']
    assert result.v310 is v310
    if expected:
        assert result.ai.outcome == 'GPT_FAILED'


def test_v310_success_gpt_exception_preserves_v310():
    class AI:
        def run(self):
            raise RuntimeError('secret')
    v310 = SimpleNamespace(outcome='SUCCESS', completed=True)
    result = DailyCycleOrchestrator(lambda **kwargs:v310, AI()).run()
    assert result.v310.completed and result.ai.outcome == 'AI_INTERNAL_ERROR'
