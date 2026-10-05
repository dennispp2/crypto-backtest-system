"""Resumable, sequential V3.10 + gpt-5.6-sol limited-information backtest.

Never writes frozen outputs or live paper ledgers. The full comparator and a
full-period no-op identity gate run before any real GPT request. Saved decisions
are replayed by input hash on resume; missing core data means no AI intervention.
"""
from __future__ import annotations

import argparse
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT/'src'))

import pandas as pd

from ai_shadow.audit import frozen_ok
from ai_shadow.auth.chatgpt_auth import ChatGPTAuth
from ai_shadow.clients.chatgpt_plan import ChatGPTPlanClient
from ai_shadow.errors import AIError
from ai_shadow.historical_coverage import macro_coverage_calendar
from ai_shadow.historical_limited import (
    CORE_MACRO, LIMITED_POLICY, HistoricalLimitedInputs, limited_decision, validate_limited_decision,
)
from ai_shadow.historical_overlay import execute_ai_overlay, load_frozen_inputs, run_overlay_engine
from ai_shadow.snapshot import canonical_hash, utc
from crypto_backtest.v31_engine import _portfolio_value, _exposure, _temp_cash, run_v31_backtest
from crypto_backtest.v310_engine import run_v310_backtest
from run_backtest_v3_10 import make_scenario
from scripts.collect_historical_external import write_json
from scripts.run_historical_gpt_diagnostic import verified_snapshot

BASE = ROOT/'artifacts/ai_shadow_local/historical_v310_gpt_limited_v2'
CODE_FILES = (
    'scripts/backtest_v310_gpt_limited.py', 'ai_shadow/historical_overlay.py',
    'ai_shadow/historical_limited.py', 'ai_shadow/historical_sources.py',
    'ai_shadow/historical_coverage.py',
    'ai_shadow/historical_preflight.py', 'ai_shadow/technical.py', 'ai_shadow/snapshot.py',
    'ai_shadow/clients/chatgpt_plan.py', 'ai_shadow/http.py', 'ai_shadow/paper_broker.py',
    'ai_shadow/risk_gateway.py', 'ai_shadow/portfolio.py',
    'ai_shadow/policy/historical_v310_limited_v2.md',
    'ai_shadow/schemas/historical_decision_v1.schema.json',
)


def safe_value(value):
    if isinstance(value, dict):
        return {k: safe_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [safe_value(v) for v in value]
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, float) and pd.isna(value):
        return None
    if hasattr(value, 'item'):
        return safe_value(value.item())
    return value


def code_hashes():
    return {name: hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in CODE_FILES}


class SequentialReplay:
    def __init__(self, output, inputs, client, rules, code_digest, receipt):
        self.output, self.inputs, self.client = output, inputs, client
        self.rules, self.code_digest, self.receipt = rules, code_digest, receipt
        self.pending = None
        self.history = []
        self.decisions = []
        self.started = utc()
        self.policy_hash = hashlib.sha256(LIMITED_POLICY.read_bytes()).hexdigest()

    def save_progress(self, status='RUNNING'):
        self.receipt.update(status=status, updated_at=utc().isoformat(),
            daily_decisions_recorded=len(self.decisions),
            gpt_decisions_completed=sum(d.get('response_completed') is True for d in self.decisions),
            missing_core_no_ai_days=sum(d.get('status') == 'MISSING_CORE_NO_AI_INTERVENTION' for d in self.decisions),
            ai_asset_fills=sum(d.get('execution', {}).get('executed_asset_trades', 0) for d in self.decisions),
            last_decision_cutoff=self.decisions[-1]['decision_cutoff'] if self.decisions else None,
            full_period_completed=False, performance_metrics=None,
            frozen_integrity='PASS' if frozen_ok(ROOT) else 'FAIL')
        write_json(self.output/'run_receipt.json', self.receipt)
        if self.history:
            pd.DataFrame(self.history).to_csv(self.output/'progress_history_4h.csv', index=False)

    def __call__(self, context):
        timestamp, state, prices = context['timestamp'], context['state'], context['prices']
        if context['prior_history'] is not None:
            self.history.append(context['prior_history'])
        if self.pending is not None and timestamp >= self.pending['execute_at']:
            saved = self.pending['saved']
            execution = execute_ai_overlay(context, saved['decision'], saved['decision_cutoff'],
                                           saved['decision_id'], self.rules)
            saved['execution'] = execution
            write_json(self.pending['path'], saved)
            self.pending = None
            self.save_progress()
        if timestamp.hour != 0:
            return
        if not frozen_ok(ROOT) or code_hashes() != self.code_digest:
            raise ValueError('FROZEN_OR_EXPERIMENT_CODE_CHANGED')
        row = context['row']
        nav = _portfolio_value(state, prices)
        unit = context['previous_unit_nav']*nav/(context['previous_value']+context['external_flow'])
        drawdown = unit/max(context['previous_peak_nav'], unit)-1
        flag = lambda x: bool(x) if pd.notna(x) else False
        quant = {
            'state': state.macro_state, 'stage': state.stage, 'target_exposure': state.active_target,
            'actual_exposure': _exposure(state, prices), 'drawdown': drawdown,
            'signal_date': pd.Timestamp(row['signal_date']).isoformat(),
            'status_available_at': pd.Timestamp(row['signal_available_at']).isoformat(),
            'stage3_candidate': context['candidate_active'], 'stage3_eligible': context['stage3_eligible'],
            'stage3_confirmation_count': context['candidate_count'],
            'crash_level1_raw': flag(row['crash_level1_raw']),
            'crash_level2_raw': flag(row['crash_level2_market_raw']),
            'crash_level1_active': state.crash_level1_days_remaining > 0,
            'tactical_action': '|'.join(context['actions']) or 'NONE',
            'basis': 'Original V3.10 rules on this isolated combined portfolio, after current-open primary actions',
        }
        portfolio = {
            'nav': nav, 'btc_weight': state.qty['BTC']*prices['BTC']/nav,
            'eth_weight': state.qty['ETH']*prices['ETH']/nav,
            'cash_weight': 1-_exposure(state, prices),
            'btc_units': state.qty['BTC'], 'eth_units': state.qty['ETH'],
            'normal_cash_usd': state.normal_cash,
            'protected_cash_usd': sum(state.pending.values())+state.tactical_bear_cash+_temp_cash(state),
            'spot_asof': timestamp.isoformat(), 'basis': 'Current 4H open mark; current bar close is not visible',
        }
        snapshot = self.inputs.snapshot(timestamp, quant, portfolio)
        day = timestamp.strftime('%Y%m%d')
        path = self.output/'decisions'/f'{day}.json'
        snapshot_path = self.output/'inputs'/f'{day}.json'
        if path.exists():
            saved = json.loads(path.read_text(encoding='utf-8'))
            if saved['snapshot_hash'] != snapshot['snapshot_hash'] or saved['policy_hash'] != self.policy_hash:
                raise ValueError('RESUME_INPUT_OR_POLICY_MISMATCH')
            if saved.get('decision') is not None:
                validate_limited_decision(saved['decision'])
        else:
            write_json(snapshot_path, snapshot)
            saved = {'decision_cutoff': timestamp.isoformat(), 'snapshot_hash': snapshot['snapshot_hash'],
                     'policy_hash': self.policy_hash, 'decision_id': canonical_hash({
                         'input': snapshot['snapshot_hash'], 'policy': self.policy_hash, 'model': 'gpt-5.6-sol'}),
                     'model': 'gpt-5.6-sol', 'decision': None, 'response_completed': False}
            if snapshot['input_coverage']['status'] != 'PASS':
                saved.update(status='MISSING_CORE_NO_AI_INTERVENTION',
                             missing_required=snapshot['input_coverage']['missing_required'])
            else:
                self.receipt.update(active_decision_cutoff=timestamp.isoformat(),
                    inference_requests_started_this_process=self.receipt.get('inference_requests_started_this_process', 0)+1)
                self.save_progress('WAITING_FOR_GPT')
                saved.update(limited_decision(self.client, snapshot), status='GPT_COMPLETED')
            write_json(path, saved)
        self.decisions.append(saved)
        if saved.get('decision') is not None:
            self.pending = {'saved': saved, 'path': path, 'execute_at': timestamp+pd.Timedelta(hours=4)}
        self.save_progress()
        print(json.dumps({'status': 'DAY_RECORDED', 'cutoff': timestamp.isoformat(),
            'days': len(self.decisions), 'gpt_completed': self.receipt['gpt_decisions_completed'],
            'action': (saved.get('decision') or {}).get('action', 'NO_AI_CORE_DATA_MISSING')}, ensure_ascii=False), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-audit', required=True)
    parser.add_argument('--accept-model-memory-risk', required=True, action='store_true')
    parser.add_argument('--user-approved-limited-data', required=True, action='store_true')
    parser.add_argument('--resume')
    parser.add_argument('--verify-only', action='store_true')
    args = parser.parse_args()
    source, _, verified = verified_snapshot(args.source_audit)
    records = json.loads((source/'data/processed/macro_vintages.json').read_text(encoding='utf-8'))
    frame, rules = load_frozen_inputs(ROOT)
    digest = code_hashes()
    if args.resume:
        output = Path(args.resume).resolve()
        if output.parent != BASE.resolve():
            raise ValueError('RESUME_PATH_UNSAFE')
        contract = json.loads((output/'experiment_contract.json').read_text(encoding='utf-8'))
        if contract['code_sha256'] != digest or contract['source_audit'] != str(source):
            raise ValueError('RESUME_CONTRACT_CHANGED')
    else:
        output = BASE/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        output.mkdir(parents=True, exist_ok=False)
        contract = {
            'model': 'gpt-5.6-sol', 'provider': 'EXISTING_CHATGPT_PLAN_OAUTH', 'paid_api_fallback': False,
            'start': frame.iloc[0].open_time.isoformat(), 'end_4h_open': frame.iloc[-1].open_time.isoformat(),
            'initial_capital': 20000, 'initial_cash_fraction': .3, 'crypto_btc_eth_ratio': [.625, .375],
            'contribution_usd_per_4h': 2, 'costs': rules['costs'], 'minimum_notional': rules['modeled_min_notional_usdt'],
            'required_macro': list(CORE_MACRO), 'missing_optional_cannot_support_decision': True,
            'input_revision': 'LIMITED_INFORMATION_V2_MONTHLY_PUBLICATION_FRESHNESS',
            'monthly_freshness': {'known_vintage_availability_age_days_max': 45,
                                  'statistical_period_age_days_max': 100},
            'daily_macro_observation_age_days_max': 7,
            'missing_core': 'NO_AI_INTERVENTION_V310_CONTINUES',
            'user_accepted_model_memory_risk': True, 'user_approved_limited_information': True,
            'ai_execution': 'NEXT_4H_OPEN_AFTER_DAILY_UTC00_DECISION_AFTER_V310_PRIMARY_ACTIONS',
            'max_ai_exposure': .95, 'max_ai_change_pp': 20, 'minimum_ai_confidence': .65,
            'v310_floor': rules['hard_floor'], 'protected_cash_not_spendable_by_ai': True,
            'crash_stage4_priority_over_ai_additions': True, 'web_tools': False,
            'source_audit': str(source), 'source_files_reverified': verified,
            'macro_file_sha256': hashlib.sha256((source/'data/processed/macro_vintages.json').read_bytes()).hexdigest(),
            'code_sha256': digest, 'frozen_at': utc().isoformat(),
            'limitations': ['Pretrained future knowledge unresolved', 'Limited information, not full external coverage',
                           'Historical bar-open surrogate, no historical spread reconstruction'],
        }
        write_json(output/'experiment_contract.json', contract)
        for name in CODE_FILES:
            target = output/'code'/name
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open('xb') as stream:
                stream.write((ROOT/name).read_bytes())
    if contract['macro_file_sha256'] != hashlib.sha256((source/'data/processed/macro_vintages.json').read_bytes()).hexdigest():
        raise ValueError('RESUME_SOURCE_ARCHIVE_CHANGED')
    receipt = {'status': 'VERIFYING_FULL_PERIOD_NOOP_IDENTITY', 'output_directory': str(output),
               'full_period_completed': False, 'performance_metrics': None,
               'no_lookahead_full_ai': 'NOT_CERTIFIED_MODEL_MEMORY_RISK', 'gpt_decisions_completed': 0,
               'total_daily_decision_dates': int(frame.open_time.dt.hour.eq(0).sum()),
               'inference_requests_started_this_process': 0}
    write_json(output/'run_receipt.json', receipt)
    replay = None
    try:
        inputs = HistoricalLimitedInputs(ROOT, records)
        calendar = macro_coverage_calendar(
            {'external': inputs.external,
             'input_coverage': {'status': 'INSUFFICIENT',
                                'missing_required': ['macro.'+k for k in CORE_MACRO]}},
            records, frame.loc[frame.open_time.dt.hour.eq(0), 'open_time'],
            monthly_publication_freshness=True)
        write_json(output/'macro_coverage_calendar.json', calendar)
        receipt.update(macro_core_available_days=sum(d['input_coverage'] == 'PASS' for d in calendar),
                       macro_core_missing_days=sum(d['input_coverage'] != 'PASS' for d in calendar))
        a = run_v31_backtest(frame, rules, make_scenario('A', rules))
        b = run_v31_backtest(frame, rules, make_scenario('B', rules), model_a=a)
        q = run_v310_backtest(frame, rules, make_scenario('Q', rules), model_a=a, shadow_v31=b)
        noop = run_overlay_engine(ROOT, frame, rules, make_scenario('Q', rules), a, b, lambda _: None)
        pd.testing.assert_frame_equal(noop.history, q.history)
        pd.testing.assert_frame_equal(noop.trades, q.trades)
        pd.testing.assert_frame_equal(noop.signals, q.signals)
        stored = pd.read_csv(ROOT/'v3_10/results/summary_v3_10.csv')
        expected = float(stored.loc[stored.model.eq('Q'), 'final_portfolio_value'].iloc[0])
        if abs(q.summary['final_portfolio_value']-expected) > .01:
            raise ValueError('V310_STORED_CHAMPION_REPRODUCTION_FAILED')
        q.history.to_csv(output/'v310_comparator_history_4h.csv', index=False)
        q.trades.to_csv(output/'v310_comparator_trades.csv', index=False)
        write_json(output/'v310_comparator_summary.json', safe_value(q.summary))
        receipt.update(full_period_noop_row_identity='PASS', pure_v310_reproduction='PASS',
                       pure_v310_final_value=q.summary['final_portfolio_value'])
        if args.verify_only:
            receipt.update(status='VERIFIED_ONLY_NO_GPT_CALLS', frozen_integrity='PASS' if frozen_ok(ROOT) else 'FAIL')
            write_json(output/'run_receipt.json', receipt)
            print(json.dumps(receipt, ensure_ascii=False), flush=True)
            return 0
        auth = ChatGPTAuth(ROOT/'ai_shadow/data/auth')
        client = ChatGPTPlanClient(auth, registration=(auth.active_account() or {}).get('registration'))
        if 'gpt-5.6-sol' not in [m['slug'] for m in client.list_models()]:
            raise AIError('MODEL_NOT_AVAILABLE')
        replay = SequentialReplay(output, inputs, client, rules, digest, receipt)
        scenario = replace(make_scenario('Q', rules), name='V3.10 + GPT limited-information exploratory portfolio')
        result = run_overlay_engine(ROOT, frame, rules, scenario, a, b, replay)
        if not frozen_ok(ROOT) or code_hashes() != digest:
            raise ValueError('FROZEN_OR_EXPERIMENT_CODE_CHANGED')
        result.history.to_csv(output/'combined_history_4h.csv', index=False)
        result.trades.to_csv(output/'combined_trades.csv', index=False)
        result.signals.to_csv(output/'combined_quant_signals.csv', index=False)
        write_json(output/'combined_summary.json', safe_value(result.summary))
        receipt.update(status='COMPLETED_EXPLORATORY_FULL_PERIOD', full_period_completed=True,
                       performance_metrics=safe_value(result.summary),
                       daily_decisions_recorded=len(replay.decisions),
                       ai_asset_fills=sum(d.get('execution', {}).get('executed_asset_trades', 0) for d in replay.decisions),
                       frozen_integrity='PASS' if frozen_ok(ROOT) else 'FAIL', finished_at=utc().isoformat())
        write_json(output/'run_receipt.json', receipt)
        print(json.dumps({'status': receipt['status'], 'output_directory': str(output),
                          'gpt_completed': receipt['gpt_decisions_completed'],
                          'final_value': result.summary['final_portfolio_value']}, ensure_ascii=False), flush=True)
        return 0
    except Exception as exc:
        if replay:
            replay.save_progress('STOPPED_INCOMPLETE')
        local_codes = {'FROZEN_OR_EXPERIMENT_CODE_CHANGED', 'RESUME_INPUT_OR_POLICY_MISMATCH',
                       'V310_STORED_CHAMPION_REPRODUCTION_FAILED'}
        error_code = exc.code if isinstance(exc, AIError) else (
            str(exc) if isinstance(exc, ValueError) and str(exc) in local_codes else type(exc).__name__)
        receipt.update(status='STOPPED_INCOMPLETE', full_period_completed=False, performance_metrics=None,
                       error_code=error_code,
                       http_status=exc.http_status if isinstance(exc, AIError) else None,
                       stopped_at=utc().isoformat(), frozen_integrity='PASS' if frozen_ok(ROOT) else 'FAIL')
        write_json(output/'run_receipt.json', receipt)
        print(json.dumps(receipt, ensure_ascii=False), flush=True)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
