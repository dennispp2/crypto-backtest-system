from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[2]


def test_seeded_noop_matches_saved_forward_portfolio_and_does_not_reset_holdings():
    from ai_shadow.month_replay import load_month, run_seeded_overlay
    frame,rules,seed,_,_,_ = load_month(ROOT)
    from crypto_backtest.v310_forward import run_resumed_oos
    from run_forward_v3_10 import portfolio_ledger
    frame = frame.head(18)
    expected,_ = run_resumed_oos(frame,rules,seed)
    observed = []
    result = run_seeded_overlay(ROOT,frame,rules,seed,expected['A'],expected['B'],observed.append)
    pd.testing.assert_frame_equal(result.history,expected['Q'].history)
    pd.testing.assert_frame_equal(result.trades,expected['Q'].trades)
    source = pd.read_csv(ROOT/'v3_10_forward/forward_v310_portfolio.csv').head(19)
    actual = portfolio_ledger('Q',result,seed)
    assert actual.portfolio_value.to_numpy() == pytest.approx(source.portfolio_value.to_numpy())
    assert not result.trades.action.eq('INITIAL_ALLOCATION').any()
    assert 'BTC_close' not in observed[0]['row']


def test_month_inputs_exclude_future_candle_when_archive_is_extended():
    from ai_shadow.month_replay import MonthInputs, load_month
    from ai_shadow.snapshot import validate_asof
    _,_,_,candles,_,_ = load_month(ROOT)
    cutoff = '2026-09-04T00:00:00Z'
    quant = {'status_available_at':cutoff,'state':'NEW_BULL','stage':0,'target_exposure':.95}
    portfolio = {'nav':20000,'btc_weight':.44,'eth_weight':.26,'cash_weight':.3}
    base = MonthInputs(ROOT,[],candles).snapshot(cutoff,quant,portfolio)
    modified = {a:d.copy() for a,d in candles.items()}
    for daily in modified.values():
        future = pd.to_datetime(daily.open_time,utc=True) >= pd.Timestamp(cutoff)
        daily.loc[future,['open','high','low','close','volume']] *= 100
    other = MonthInputs(ROOT,[],modified).snapshot(cutoff,quant,portfolio)
    assert base == other
    assert base['technical']['BTC']['indicator_asof'].startswith('2026-09-03T23:59:59')
    validate_asof(base,cutoff)


def test_metrics_do_not_count_contributions_as_returns_or_annualize_one_month():
    from ai_shadow.month_replay import period_metrics
    h = pd.DataFrame({'portfolio_value':[1100,1210],'external_flow':[100,0],
                      'unit_nav':[1,1.1]})
    metrics = period_metrics(h,pd.DataFrame(),1000)
    assert metrics['net_profit'] == pytest.approx(110)
    assert metrics['twr_return'] == pytest.approx(.1)
    assert metrics['contributions'] == 100
    assert metrics['max_drawdown'] == 0
    assert metrics['annualized_metrics'].startswith('NOT_REPORTED')


def test_metrics_include_anchor_in_drawdown_and_reject_incorrect_twr():
    from ai_shadow.month_replay import period_metrics
    h = pd.DataFrame({'portfolio_value':[900,950],'external_flow':[0,0],
                      'unit_nav':[.9,.95]})
    assert period_metrics(h,pd.DataFrame(),1000)['max_drawdown'] == pytest.approx(-.1)
    h.loc[1,'unit_nav'] = 1.5
    with pytest.raises(ValueError,match='INDEPENDENT_TWR'):
        period_metrics(h,pd.DataFrame(),1000)
