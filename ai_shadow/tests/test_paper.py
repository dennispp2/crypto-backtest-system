import pytest

from ai_shadow.clients.mock import hold_decision
from ai_shadow.paper_broker import PaperBroker
from ai_shadow.portfolio import genesis_payload, sync_contributions, weights
from ai_shadow.risk_gateway import RiskGateway
from ai_shadow.snapshot import utc

NOW = '2026-10-05T12:00:00+00:00'
DONE = '2026-10-05T12:01:00+00:00'


def row(timestamp='2026-10-05T08:00:00+00:00', **updates):
    return {'timestamp': timestamp, 'record_id': timestamp, 'record_hash': 'abc',
            'btc_value': '10000', 'eth_value': '4000', 'BTC_close': '100', 'ETH_close': '10',
            'normal_cash': '6000', 'pending_dca_cash': '0', 'tactical_bear_cash': '0',
            'temporary_hedge_cash': '0', 'portfolio_value': '20000', 'unit_nav': '1',
            'external_flow': '0', **updates}


def state():
    return genesis_payload(row(), 'filehash', NOW, 'model', 'policy', 'test')['state']


def quotes():
    return {a: {'bid': p, 'ask': p, 'requested_at': DONE, 'quote_time': DONE, 'source': 'test'}
            for a, p in [('BTC', 100), ('ETH', 10)]}


def broker():
    return PaperBroker(clock=lambda: utc(DONE))


def test_sell_before_buy_rebalance_fee_slippage():
    current = state()
    decision = hold_decision(.7)
    decision.update(action='REDUCE', target_btc_weight=.3, target_eth_weight=.4)
    approved = RiskGateway().evaluate(decision, weights(current, {'BTC':100, 'ETH':10}))
    end, orders = broker().execute(current, approved, quotes(), 'id', NOW)
    assert [o['side'] for o in orders if o['status']=='FILLED'] == ['SELL', 'BUY']
    assert all(o['fee'] == pytest.approx(o['notional']*.001) for o in orders)
    assert all(o['slippage'] > 0 for o in orders)
    assert end['cash'] >= 0 and end['btc_units'] >= 0 and end['eth_units'] >= 0
    assert sum(o['fee']+o['slippage'] for o in orders) == pytest.approx(20000-end['nav'])


def test_stale_predecision_quote_blocks_all_fills():
    q = quotes()
    q['ETH']['requested_at'] = '2026-10-05T11:00:00+00:00'
    decision = hold_decision(.9)
    decision['action'] = 'ADD'
    approved = RiskGateway().evaluate(decision, weights(state(), {'BTC':100, 'ETH':10}))
    with pytest.raises(ValueError, match='QUOTE_BEFORE_DECISION'):
        broker().execute(state(), approved, q, 'id', NOW)


def test_min_notional_skip():
    decision = hold_decision(.70001)
    decision.update(action='ADD', target_btc_weight=.500005, target_eth_weight=.200005)
    approved = RiskGateway().evaluate(decision, weights(state(), {'BTC':100, 'ETH':10}))
    _, orders = broker().execute(state(), approved, quotes(), 'id', NOW)
    assert any(o['status']=='SKIPPED' and o['reason']=='MIN_NOTIONAL' for o in orders)


def test_external_cash_flow_not_return():
    start = state()
    next_row = row('2026-10-05T12:00:00+00:00', external_flow='2')
    result, flows = sync_contributions(start, [row(), next_row], '2026-10-05T16:01:00+00:00')
    assert result['nav'] == 20002
    assert result['unit_nav'] == pytest.approx(1)
    assert flows[0]['amount'] == 2
    again, flows2 = sync_contributions(result, [row(), next_row], '2026-10-05T16:02:00+00:00')
    assert not flows2 and again == result


def test_clamped_exit_does_not_exceed_twenty_percentage_points():
    decision = hold_decision(0)
    decision['action']='EXIT'
    approved=RiskGateway().evaluate(decision,weights(state(),{'BTC':100,'ETH':10}))
    end, orders=broker().execute(state(),approved,quotes(),'exit-id',NOW)
    exposure=(end['btc_value']+end['eth_value'])/end['nav']
    assert exposure == pytest.approx(.5)
    assert len(orders)==2
