from pathlib import Path

import pytest

from ai_shadow.benchmark_costs import frozen_costs, read_chain
from ai_shadow.portfolio import genesis_payload
from ai_shadow.snapshot import read_frozen_portfolio, utc

ROOT = Path(__file__).resolve().parents[2]


def test_post_genesis_costs_do_not_include_earlier_trades():
    rows, digest = read_frozen_portfolio(ROOT/'v3_10_forward/forward_v310_portfolio.csv')
    genesis = genesis_payload(rows[-1],digest,utc(),'test','test','test')
    costs = frozen_costs(ROOT,genesis,utc().isoformat())
    assert costs['total_fees']==0 and costs['tactical_turnover']==0
    assert costs['total_asset_trade_count'] is None and costs['status']=='PARTIAL'


def test_cost_chain_detects_tampering(tmp_path):
    path = tmp_path/'trades.csv'
    raw = (ROOT/'v3_10_forward/forward_trade_log_v310.csv').read_text(encoding='utf-8')
    path.write_text(raw.replace('BUY','SELL',1),encoding='utf-8')
    with pytest.raises(ValueError,match='BENCHMARK_COST_CHAIN_INVALID'):
        read_chain(path)
