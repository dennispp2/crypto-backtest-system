from copy import deepcopy

import pytest

from ai_shadow.clients.mock import hold_decision
from ai_shadow.combined import primary_constraints, combined_paper_execution, render_combined_result
from ai_shadow.orchestrator import AIResult
from ai_shadow.paper_broker import BrokerConfig
from ai_shadow.risk_gateway import RiskConfig, RiskResult
from ai_shadow.snapshot import utc
from ai_shadow.tests.test_paper import state, row, quotes, NOW, DONE


def requested(action,exposure,ratio=.625):
    return RiskResult('ALLOW',action,exposure,{'BTC':exposure*ratio,'ETH':exposure*(1-ratio),'Cash':1-exposure},
                      action,exposure,[])


@pytest.mark.parametrize('quant',[{'crash':'YES','v310_stage':0},{'crash':'NO','v310_stage':4}])
def test_primary_crash_and_stage4_veto_ai_additions(quant):
    current = {'BTC':.5,'ETH':.2,'Cash':.3}
    result = primary_constraints(requested('ADD',.9),current,quant,hard_floor=.2)
    assert result.action == 'HOLD' and result.weights == current
    assert result.reasons == ['V310_CRASH_STAGE4_PRIORITY']


def test_primary_floor_and_no_forced_buys():
    current = {'BTC':.15,'ETH':.10,'Cash':.75}
    result = primary_constraints(requested('EXIT',0),current,{'crash':'NO','v310_stage':0},hard_floor=.2)
    assert result.exposure == .2
    assert result.weights['BTC'] == pytest.approx(.12)
    assert result.status == 'CLAMP'
    small = {'BTC':.08,'ETH':.02,'Cash':.9}
    assert primary_constraints(requested('EXIT',0),small,{},hard_floor=.2).weights == small


def test_combined_trial_cannot_spend_cash_reserved_for_quant():
    decision = hold_decision(.9)
    decision['action'] = 'ADD'
    current = state()
    before = deepcopy(current)
    approved,end,orders = combined_paper_execution(current,decision,{'crash':'NO','v310_stage':0},
        row(normal_cash='1000',tactical_bear_cash='5000'),quotes(),'test',NOW,
        risk_config=RiskConfig(),broker_config=BrokerConfig(),hard_floor=.2,clock=lambda:utc(DONE),frozen_hash_pass=True)
    assert approved.action == 'HOLD'
    assert approved.reasons[-1] == 'V310_PROTECTED_CASH_UNAVAILABLE'
    assert current == before
    assert (end['btc_units'],end['eth_units'],end['cash']) == (current['btc_units'],current['eth_units'],current['cash'])
    assert not orders


def test_joint_report_does_not_display_old_cycle_after_failed_or_mismatched_decision():
    quant = {'v310_state':'BULL','v310_stage':0,'target_exposure':.95,'actual_exposure':.8}
    view = {'cycle':{'decision_id':'old'}}
    for result in (AIResult('GPT_TIMEOUT'),AIResult('AI_COMPLETED',True,'new')):
        text = render_combined_result(quant,result,view)
        assert '未取得本次完整' in text
        assert '綜合帳本總資產' not in text


def test_hybrid_policy_requires_new_ledger_and_keeps_existing_capital(tmp_path):
    from ai_shadow.tests.test_orchestrator import setup
    app,client = setup(tmp_path)
    independent = app.storage()
    original = independent.state()
    original_policy = independent.genesis()['policy_hash']
    app.configure(strategy_mode='v310_hybrid')
    assert app.run().outcome == 'EXPERIMENT_VERSION_MISMATCH'
    payload = app.initialize('mock-model')
    assert payload['policy_hash'] != original_policy
    assert payload['strategy_mode'] == 'v310_hybrid'
    assert payload['state']['btc_units'] == original['btc_units']
    assert payload['state']['eth_units'] == original['eth_units']
    assert payload['state']['cash'] == original['cash']
    assert app.run().outcome == 'AI_COMPLETED'
    assert app.run().outcome == 'TODAY_AI_ALREADY_COMPLETED'
    assert client.calls.count('decide') == 1
    assert independent.state() == original
    assert independent.verify_chain() and app.storage().verify_chain()
