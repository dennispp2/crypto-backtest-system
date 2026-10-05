"""Isolated in-memory extension of the hash-locked V3.10 engine.

The frozen file and module remain untouched. An AST insertion adds one callback
after original FSM, crash, recovery and DCA actions, before the current 4H bar's
closing valuation. A no-op callback must reproduce every original output row.
"""
from __future__ import annotations

import ast
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
import types

import pandas as pd

from ai_shadow.audit import FROZEN_HASHES, frozen_ok

ROW_FIELDS = (
    'open_time', 'signal_date', 'signal_available_at', 'BTC_open', 'ETH_open',
    'BTC_daily_close', 'stage3_confirmed', 'crash_level1_raw', 'crash_level2_market_raw',
)


def load_frozen_inputs(root):
    """Rebuild original causal features, excluding original ML outcome columns."""
    root = Path(root)
    if not frozen_ok(root):
        raise ValueError('FROZEN_INTEGRITY_FAILED')
    if str(root/'src') not in sys.path:
        sys.path.insert(0, str(root/'src'))
    from crypto_backtest.data import build_common_4h_frame, read_csv_gz, sha256_file
    from crypto_backtest.v31_indicators import build_v31_daily, merge_v31_features_to_bars
    rules = json.loads((root/'config/config_frozen_v3_1.json').read_text(encoding='utf-8'))
    base = json.loads((root/'config/frozen_rules.json').read_text(encoding='utf-8'))
    manifest = pd.read_csv(root/'v3_1/artifacts/source_manifest_v3_1.csv')
    for row in manifest.itertuples():
        path = (root/row.path).resolve()
        if root.resolve() not in path.parents or sha256_file(path) != str(row.sha256).lower():
            raise ValueError('FROZEN_SOURCE_HASH_MISMATCH')
    raw = root/'v3_1/data/raw'
    bars = {a: read_csv_gz(raw/f'binance_{a}USDT_4h.csv.gz') for a in ('BTC', 'ETH')}
    common, _ = build_common_4h_frame(bars)
    daily, _ = build_v31_daily(read_csv_gz(raw/'bitstamp_BTCUSD_1d.csv.gz'),
                              read_csv_gz(raw/'binance_BTCUSDT_1d.csv.gz'), base, rules)
    frame = merge_v31_features_to_bars(common, daily)
    frame = frame.loc[(frame.open_time >= pd.Timestamp('2020-01-01T00:00:00Z'))
                      & (frame.open_time <= pd.Timestamp('2026-09-03T04:00:00Z'))].reset_index(drop=True)
    if (frame.empty or frame.iloc[0].open_time != pd.Timestamp('2020-01-01T00:00:00Z')
            or frame.iloc[-1].open_time != pd.Timestamp('2026-09-03T04:00:00Z')
            or frame.open_time.duplicated().any()
            or (frame.signal_available_at > frame.open_time).any()):
        raise ValueError('HISTORICAL_FRAME_TIME_CONTRACT_FAILED')
    return frame, rules


def _runtime_engine(root):
    path = Path(root)/'src/crypto_backtest/v310_engine.py'
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != FROZEN_HASHES['src/crypto_backtest/v310_engine.py']:
        raise ValueError('FROZEN_ENGINE_HASH_MISMATCH')
    tree = ast.parse(raw.decode('utf-8'))
    function = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
                    and n.name == 'run_v310_backtest')
    function.args.kwonlyargs.append(ast.arg(arg='overlay_callback'))
    function.args.kw_defaults.append(ast.Constant(None))
    loop = next(n for n in function.body if isinstance(n, ast.For)
                and isinstance(n.iter, ast.Call) and isinstance(n.iter.func, ast.Attribute)
                and n.iter.func.attr == 'iterrows')
    anchors = [i for i, n in enumerate(loop.body) if isinstance(n, ast.Assign)
               and any(isinstance(t, ast.Name) and t.id == 'end_value' for t in n.targets)]
    if len(anchors) != 1:
        raise ValueError('FROZEN_ENGINE_OVERLAY_ANCHOR_CHANGED')
    hook = ast.parse('''if overlay_callback is not None:
    overlay_callback(_overlay_context(state, row, prices_open, external_flow,
        previous_value, unit_nav, peak_nav, actions, stage3_eligible, candidate,
        trades, histories, scenario))''').body[0]
    loop.body.insert(anchors[0], hook)
    ast.fix_missing_locations(tree)
    name = 'crypto_backtest._historical_overlay_runtime'
    module = types.ModuleType(name)
    module.__file__, module.__package__ = str(path), 'crypto_backtest'
    module._overlay_context = _context
    sys.modules[name] = module  # Required by the original dataclass annotations.
    exec(compile(tree, str(path), 'exec'), module.__dict__)
    return module.run_v310_backtest


def _context(state, row, prices, flow, previous, unit_nav, peak, actions,
             eligible, candidate, trades, histories, scenario):
    # The callback never receives the current bar close/high/low or labels.
    safe = {k: row.get(k) for k in ROW_FIELDS}
    return {'state': state, 'row': safe, 'timestamp': pd.Timestamp(row['open_time']),
            'prices': dict(prices), 'external_flow': flow, 'previous_value': previous,
            'previous_unit_nav': unit_nav, 'previous_peak_nav': peak,
            'actions': list(actions), 'stage3_eligible': eligible,
            'candidate_active': candidate is not None,
            'candidate_count': int(candidate['confirmation_count']) if candidate else 0,
            'trades': trades, 'prior_history': deepcopy(histories[-1]) if histories else None,
            'scenario': scenario}


def run_overlay_engine(root, frame, rules, scenario, model_a, shadow_v31, callback):
    runner = _runtime_engine(root)
    try:
        return runner(frame, rules, scenario, model_a=model_a,
                      shadow_v31=shadow_v31, overlay_callback=callback)
    finally:
        sys.modules.pop('crypto_backtest._historical_overlay_runtime', None)


def execute_ai_overlay(context, decision, decision_cutoff, decision_id, rules):
    """Next-bar AI adjustment, reusing the tested broker and existing risk caps.

    Original DCA/bear/temporary cash buckets are not spendable by AI. AI sell
    proceeds enter normal cash. The modeled quote is explicitly a bar-open
    surrogate with zero modeled spread, not a historical order-book quote.
    """
    from ai_shadow.historical_limited import validate_limited_decision
    from ai_shadow.paper_broker import BrokerConfig, PaperBroker
    from ai_shadow.risk_gateway import RiskConfig, RiskResult
    from ai_shadow.snapshot import utc
    from crypto_backtest.v31_engine import _cash_snapshot, _portfolio_value, _exposure, _temp_cash

    validate_limited_decision(decision)
    timestamp = context['timestamp']
    if utc(timestamp) < utc(decision_cutoff)+pd.Timedelta(hours=4):
        raise ValueError('AI_EXECUTION_NOT_NEXT_BAR')
    state, prices = context['state'], context['prices']
    exposure = _exposure(state, prices)
    receipt = {'requested_action': decision['action'], 'requested_exposure': decision['target_total_exposure'],
               'gateway_status': 'BLOCK', 'gateway_reasons': [], 'executed_asset_trades': 0,
               'execution_timestamp': timestamp.isoformat(), 'exposure_before': exposure,
               'exposure_after': exposure}

    def hold(reason):
        receipt['gateway_reasons'] = [reason]
        return receipt

    if decision['action'] == 'HOLD':
        receipt['gateway_status'] = 'ALLOW'
        return hold('REQUESTED_HOLD_NO_AI_INTERVENTION')
    risk = RiskConfig()
    if decision['data_quality'] == 'POOR':
        return hold('DATA_QUALITY_POOR')
    if decision['confidence'] is None or decision['confidence'] < risk.minimum_confidence_to_change_position:
        return hold('LOW_OR_UNKNOWN_CONFIDENCE')
    action, requested = decision['action'], decision['target_total_exposure']
    addition = action in {'ADD', 'STRONG_ADD'}
    if (addition and requested < exposure-1e-8) or (not addition and requested > exposure+1e-8):
        return hold('ACTION_DIRECTION_CONFLICT')
    if action == 'EXIT' and requested > 1e-8:
        return hold('EXIT_WEIGHT_CONFLICT')
    if addition and (state.stage == 4 or state.crash_level1_days_remaining > 0
                     or bool(context['row'].get('crash_level1_raw'))
                     or bool(context['row'].get('crash_level2_market_raw'))):
        return hold('V310_CRASH_STAGE4_PRIORITY')
    approved = min(max(requested, float(rules['hard_floor'])), risk.max_total_crypto_exposure)
    reasons = []
    if approved != requested:
        reasons.append('V310_FLOOR_OR_MAX_EXPOSURE_CLAMP')
    clamped = min(max(approved, max(0., exposure-risk.max_single_cycle_exposure_change)),
                  exposure+risk.max_single_cycle_exposure_change)
    if abs(clamped-approved) > 1e-10:
        reasons.append('EXPOSURE_CHANGE_CLAMP')
    if not addition and clamped > exposure+1e-8:
        return hold('ALREADY_BELOW_V310_FLOOR_NO_FORCED_BUY')
    nav = _portfolio_value(state, prices)
    btc_ratio = (decision['target_btc_weight']/requested if requested else
                 state.qty['BTC']*prices['BTC']/(exposure*nav) if exposure else .625)
    weights = {'BTC': clamped*btc_ratio, 'ETH': clamped*(1-btc_ratio), 'Cash': 1-clamped}
    approved_result = RiskResult('CLAMP' if reasons else 'ALLOW', action, clamped, weights,
                                action, requested, reasons)
    protected = sum(state.pending.values())+state.tactical_bear_cash+_temp_cash(state)
    broker_state = {
        'btc_units': state.qty['BTC'], 'eth_units': state.qty['ETH'],
        'cash': state.normal_cash+protected, 'fund_units': nav, 'initial_nav': nav,
        'btc_cost_basis': state.qty['BTC']*prices['BTC'],
        'eth_cost_basis': state.qty['ETH']*prices['ETH'],
        'fees': 0., 'slippage': 0., 'turnover_notional': 0., 'trade_count': 0,
        'realized_pnl': 0., 'timestamp': timestamp.isoformat(),
    }
    quotes = {a: {'bid': price, 'ask': price, 'requested_at': timestamp.isoformat(),
                  'quote_time': timestamp.isoformat(), 'source': 'HISTORICAL_4H_OPEN_SURROGATE_NO_SPREAD_DATA'}
              for a, price in prices.items()}
    broker = PaperBroker(BrokerConfig(fee_bps=float(rules['costs']['fee'])*10000,
        slippage_bps=float(rules['costs']['slippage'])*10000,
        min_notional_usd=max(rules['modeled_min_notional_usdt'].values())), clock=lambda: utc(timestamp))
    filled, orders = broker.execute(broker_state, approved_result, quotes, decision_id, decision_cutoff)
    if filled['cash'] < protected-1e-8:
        return hold('PROTECTED_V310_CASH_UNAVAILABLE_TO_AI')
    state.qty.update(BTC=filled['btc_units'], ETH=filled['eth_units'])
    state.normal_cash = max(0., filled['cash']-protected)
    for order in orders:
        if order['status'] != 'FILLED':
            continue
        context['trades'].append({
            'timestamp': timestamp, 'strategy': context['scenario'].name, 'model': 'Q',
            'action': 'AI_OVERLAY_'+action, 'side': order['side'], 'asset': order['asset'],
            'quantity': order['quantity'], 'raw_open_price': order['reference_price'],
            'effective_price': order['fill_price'],
            'gross_notional_usd': order['quantity']*order['reference_price'],
            'cash_change_usd': order['net_cash_change'], 'fee_usd': order['fee'],
            'slippage_usd': order['slippage'], 'cost_usd': order['fee']+order['slippage'],
            'ledger': 'normal', 'reason': '|'.join(decision['thesis']),
            'signal_date': pd.Timestamp(decision_cutoff)-pd.Timedelta(days=1),
            'fsm_state': state.macro_state, 'fsm_stage': state.stage,
            'cycle_id': state.active_cycle_id, 'tactical_event_id': 0, 'temporary_lot_id': '',
            'before_crypto_exposure': exposure, 'target_crypto_exposure': clamped,
            'after_crypto_exposure': _exposure(state, prices), **_cash_snapshot(state),
            'ai_decision_id': decision_id,
        })
    receipt.update(gateway_status=approved_result.status, gateway_reasons=reasons,
                   executed_asset_trades=sum(o['status'] == 'FILLED' for o in orders),
                   exposure_after=_exposure(state, prices))
    return receipt
