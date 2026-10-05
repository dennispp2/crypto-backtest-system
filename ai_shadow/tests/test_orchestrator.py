from copy import deepcopy
from pathlib import Path

from ai_shadow.clients.mock import MockAIClient
from ai_shadow.orchestrator import AIOrchestrator
from ai_shadow.portfolio import genesis_payload
from ai_shadow.snapshot import utc
from ai_shadow.storage import ShadowStorage
from ai_shadow.tests.test_paper import row
from ai_shadow.tests.test_technical import candles
from ai_shadow.technical import indicators

NOW = '2026-10-05T12:01:00+00:00'


class Auth:
    def active_account(self):
        return {'registration':'test', 'plan_authorized':True}


class Market:
    def technical(self):
        technical = indicators(candles(), utc(NOW))
        return {a: {**technical, 'status':'PASS', 'indicator_asof':'2026-10-04T23:59:59+00:00',
                    'spot_asof':NOW, 'spot_now':p, 'source':'test', 'source_timestamp':NOW, 'fetched_at':NOW}
                for a,p in [('BTC',100), ('ETH',10)]}
    def quotes(self):
        return {a: {'bid':p, 'ask':p, 'requested_at':NOW, 'quote_time':NOW, 'source':'test'}
                for a,p in [('BTC',100), ('ETH',10)]}


def setup(tmp_path, client=None):
    client = client or MockAIClient()
    latest = row()
    quant = {'status_date':latest['timestamp'], 'frozen_hash_status':'PASS', 'v310_state':'BULL', 'v310_stage':0,
             'target_exposure':.95,'actual_exposure':.7,'drawdown':0.,'stage3_candidate':'NO','crash':'NO',
             'ahr999':None,'tactical_action':'NONE'}
    read = lambda: (quant, [deepcopy(latest)], 'hash')
    app = AIOrchestrator(Path('.'), tmp_path, read, auth=Auth(), market=Market(), providers=[],
                         client_factory=lambda:client, clock=lambda:utc(NOW), frozen_checker=lambda:True)
    app.initialize('mock-model')
    return app, client


def test_ai_already_completed_is_idempotent(tmp_path):
    app, client = setup(tmp_path)
    assert app.run().outcome == 'AI_COMPLETED'
    assert app.run().outcome == 'TODAY_AI_ALREADY_COMPLETED'
    assert client.calls.count('decide') == 1
    assert app.storage().verify_chain()


def test_gpt_failure_no_paper_fill(tmp_path):
    app, client = setup(tmp_path, MockAIClient(failure='USAGE_LIMIT_EXCEEDED'))
    initial = app.storage().state()
    assert app.run().outcome == 'USAGE_LIMIT_EXCEEDED'
    assert app.storage().state() == initial
    assert not app.storage().completed_day('2026-10-05')


def test_auto_refresh_view_never_calls_gpt_or_provider(tmp_path):
    app, client = setup(tmp_path)
    before = app.storage().state()
    app.view()
    app.view()
    assert not client.calls and app.storage().state() == before


def test_model_change_requires_new_experiment(tmp_path):
    app, client = setup(tmp_path)
    app.configure(model='different-model')
    assert app.run().outcome == 'EXPERIMENT_VERSION_MISMATCH'
    assert not client.calls


def test_failed_combined_genesis_does_not_switch_existing_policy(tmp_path):
    import pytest
    from ai_shadow.errors import AIError
    app, client = setup(tmp_path)
    settings_before = app.settings()
    state_before = app.storage().state()
    app.frozen_checker = lambda: False
    with pytest.raises(AIError, match='FROZEN_HASH_FAIL'):
        app.initialize('mock-model', strategy_mode='v310_hybrid')
    assert app.settings() == settings_before
    assert app.storage().state() == state_before
