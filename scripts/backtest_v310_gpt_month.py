"""Isolated first-30-day V3.10 + real GPT replay from the saved forward seed.

Never resets or writes live holdings. No current web/news enters historical
decisions. Uses the previously approved limited-information contract and
existing ChatGPT-plan OAuth, with no paid fallback or parameter search.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
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
from ai_shadow.historical_sources import alfred_download_batches, parse_alfred_zip
from ai_shadow.month_replay import MonthInputs, load_month, run_seeded_overlay, period_metrics
from ai_shadow.snapshot import utc
from scripts.backtest_v310_gpt_limited import SequentialReplay, code_hashes, safe_value
from scripts.collect_historical_external import MACRO, download, write_json
from scripts.replay_frozen_v310 import protected_hashes
from scripts.run_historical_gpt_diagnostic import verified_snapshot
from crypto_backtest.v310_forward import run_resumed_oos, state_from_dict, state_value, verify_hash_chain
from run_forward_v3_10 import portfolio_ledger

BASE = ROOT/'artifacts/ai_shadow_local/v310_gpt_first_month'
MONTH_CODE = ('scripts/backtest_v310_gpt_month.py', 'ai_shadow/month_replay.py')


def month_digest():
    return {n:hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in MONTH_CODE}


def fetch_recent_macro(output, item, end):
    series, field = item
    url = 'https://alfred.stlouisfed.org/series/downloaddata?seid='+series
    raw, receipt = download(output, series+'_form.html', url)
    receipts, records = [receipt], []
    if raw is None:
        return records, receipts
    try:
        # Narrow vintage interval, but retain earlier observation levels for
        # causal month/year changes. The prior audited archive supplies older vintages.
        batches = alfred_download_batches(raw.decode('utf-8'), '2026-08-01', end)
        complete = True
        for i, fields in enumerate(batches, 1):
            fields = [(k, '2018-01-01' if k == 'form[obs_start_date]' else v) for k,v in fields]
            data, proof = download(output, f'{series}_vintages_{i}.zip', url, fields)
            receipts.append(proof)
            if data is None:
                complete = False
            else:
                records.extend(parse_alfred_zip(data, series, field))
        if not complete:
            records = []  # Incomplete exports cannot establish revision coverage.
    except (ValueError, KeyError, UnicodeError) as exc:
        records = []
        receipts.append({'status':'NORMALIZATION_FAILED', 'series':series,
                         'error_type':type(exc).__name__})
    print(json.dumps({'macro_series':series, 'records':len(records)}, ensure_ascii=False), flush=True)
    return records, receipts


def collect_month_macro(output, source, end):
    prior = json.loads((source/'data/processed/macro_vintages.json').read_text(encoding='utf-8'))
    # Keep collector concurrency bounded; GPT decisions remain sequential.
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda item:fetch_recent_macro(output, item, end), MACRO.items()))
    additions = [r for records,_ in results for r in records]
    receipts = [r for _,proofs in results for r in proofs]
    identities = {}
    for row in prior+additions:
        key = (row['field'], row['observation_time'], row['available_at'])
        if key in identities and identities[key]['value'] != row['value']:
            raise ValueError('MACRO_SOURCE_CONFLICT')
        identities[key] = row
    path = output/'data/processed/macro_vintages.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, list(identities.values()))
    write_json(output/'source_manifest.json', {'sources':receipts, 'prior_audited_source':str(source),
               'processed_macro_sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
    return list(identities.values())


def verify_month_sources(output, source):
    # Independently reparse every downloaded ZIP rather than trusting the
    # collector's processed JSON or provenance prose.
    manifest = json.loads((output/'source_manifest.json').read_text(encoding='utf-8'))
    path = output/'data/processed/macro_vintages.json'
    if hashlib.sha256(path.read_bytes()).hexdigest() != manifest['processed_macro_sha256']:
        raise ValueError('MONTH_SOURCE_HASH_MISMATCH')
    parsed = {}
    failed_series = {
        p.get('series') or p.get('url','').split('seid=')[-1]
        for p in manifest['sources'] if p['status'] != 'DOWNLOADED'
    }
    for proof in manifest['sources']:
        if proof['status'] != 'DOWNLOADED':
            continue
        raw = output/'data/raw'/proof['raw_file']
        if hashlib.sha256(raw.read_bytes()).hexdigest() != proof['sha256']:
            raise ValueError('MONTH_RAW_HASH_MISMATCH')
        if '_vintages_' in raw.name:
            series = raw.name.split('_')[0]
            if series in failed_series:
                continue
            for row in parse_alfred_zip(raw.read_bytes(), series, MACRO[series]):
                parsed[(row['field'],row['observation_time'],row['available_at'])] = row
    for series in failed_series:
        if series in MACRO:
            parsed = {k:v for k,v in parsed.items() if v['series_id'] != series}
    prior = json.loads((source/'data/processed/macro_vintages.json').read_text(encoding='utf-8'))
    for row in prior:
        key = (row['field'],row['observation_time'],row['available_at'])
        if key in parsed and parsed[key]['value'] != row['value']:
            raise ValueError('MONTH_MACRO_REPARSE_CONFLICT')
        parsed[key] = row
    if safe_value(sorted(parsed.values(), key=lambda r:(r['field'],r['observation_time'],r['available_at']))) != safe_value(
            sorted(json.loads(path.read_text(encoding='utf-8')), key=lambda r:(r['field'],r['observation_time'],r['available_at']))):
        raise ValueError('MONTH_MACRO_REPARSE_MISMATCH')
    return list(parsed.values())


class MonthReplay(SequentialReplay):
    def __init__(self, *args, extra_digest, **kwargs):
        super().__init__(*args, **kwargs)
        self.extra_digest = extra_digest

    def __call__(self, context):
        if context['timestamp'].hour == 0 and month_digest() != self.extra_digest:
            raise ValueError('MONTH_CODE_CHANGED')
        super().__call__(context)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-audit', required=True)
    parser.add_argument('--resume')
    parser.add_argument('--verify-only', action='store_true')
    parser.add_argument('--accept-model-memory-risk', action='store_true', required=True)
    parser.add_argument('--user-approved-limited-data', action='store_true', required=True)
    args = parser.parse_args()
    source,_,verified = verified_snapshot(args.source_audit)
    before = protected_hashes()
    frame,rules,seed,candles,source_contract,existing_evaluation = load_month(ROOT)
    digest, extra = code_hashes(), month_digest()
    initial = state_value(state_from_dict(seed['Q']['state']), seed['cutoff_prices'])
    end = frame.iloc[-1].open_time+pd.Timedelta(hours=4)
    if args.resume:
        output = Path(args.resume).resolve()
        if output.parent != BASE.resolve():
            raise ValueError('MONTH_RESUME_PATH_UNSAFE')
        contract = json.loads((output/'experiment_contract.json').read_text(encoding='utf-8'))
        if (contract['code_sha256'] != {**digest,**extra} or contract['source_audit'] != str(source)
                or contract['seed_sha256'] != before['v3_10_forward/forward_config_frozen.json']):
            raise ValueError('MONTH_RESUME_CONTRACT_CHANGED')
        records = verify_month_sources(output, source)
    else:
        output = BASE/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        output.mkdir(parents=True, exist_ok=False)
        write_json(output/'protected_before.json', before)
        records = collect_month_macro(output, source, end.date().isoformat())
        records = verify_month_sources(output, source)
        contract = {'model':'gpt-5.6-sol', 'provider':'EXISTING_CHATGPT_PLAN_OAUTH', 'paid_api_fallback':False,
            'mode':'FIRST_30_DAY_FORWARD_SEED_REPLAY_EXPLORATORY', 'days':30,
            'start_4h_open':frame.iloc[0].open_time.isoformat(), 'end_exclusive':end.isoformat(),
            'first_decision_cutoff':frame.loc[frame.open_time.dt.hour.eq(0),'open_time'].iloc[0].isoformat(),
            'initial_value':initial, 'initial_holdings':seed['Q']['state']['qty'],
            'capital_continuity':'Saved 2026-09-03 forward anchor. No reset, no today holdings backdated.',
            'seed_sha256':before['v3_10_forward/forward_config_frozen.json'],
            'costs':rules['costs'], 'contribution_usd_per_4h':2, 'ai_execution':'NEXT_4H_OPEN',
            'existing_live_evaluation':existing_evaluation,
            'ai_policy':'historical_v310_limited_v2', 'source_audit':str(source),
            'source_files_reverified':verified, 'code_sha256':{**digest,**extra},
            'source_contract':source_contract, 'web_tools':False,
            'user_accepted_model_memory_risk':True, 'user_approved_limited_information':True,
            'limitations':['Pretrained future knowledge unresolved', 'Missing news/ETF/derivatives/onchain not inferred',
                           'Historical open surrogate, no bid/ask archive', '30 days cannot establish long-run AI edge'],
            'frozen_at':utc().isoformat()}
        write_json(output/'experiment_contract.json', safe_value(contract))
        for name in contract['code_sha256']:
            target = output/'code'/name
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open('xb') as stream:
                stream.write((ROOT/name).read_bytes())
    receipt = {'status':'VERIFYING_MONTH_NOOP_IDENTITY', 'output_directory':str(output),
               'full_period_completed':False, 'test_window_completed':False, 'performance_metrics':None,
               'no_lookahead_full_ai':'NOT_CERTIFIED_MODEL_MEMORY_RISK', 'gpt_decisions_completed':0,
               'total_daily_decision_dates':int(frame.open_time.dt.hour.eq(0).sum()),
               'inference_requests_started_this_process':0}
    write_json(output/'run_receipt.json', receipt)
    replay = None
    try:
        pure,_ = run_resumed_oos(frame, rules, seed)
        a,b,q = pure['A'],pure['B'],pure['Q']
        noop = run_seeded_overlay(ROOT, frame, rules, seed, a,b,lambda _:None)
        for attr in ('history','trades','signals'):
            pd.testing.assert_frame_equal(getattr(noop,attr), getattr(q,attr))
        source_ledger = ROOT/'v3_10_forward/forward_v310_portfolio.csv'
        if not verify_hash_chain(source_ledger):
            raise ValueError('FORWARD_CHAIN_INVALID')
        expected = pd.read_csv(source_ledger).head(len(frame)+1)
        actual = portfolio_ledger('Q',q,seed)
        if list(pd.to_datetime(actual.timestamp,utc=True)) != list(pd.to_datetime(expected.timestamp,utc=True)):
            raise ValueError('FORWARD_MONTH_TIMESTAMP_IDENTITY_FAIL')
        for column in ('macro_state','sell_stage'):
            if actual[column].astype(str).tolist() != expected[column].astype(str).tolist():
                raise ValueError('FORWARD_MONTH_ROW_IDENTITY_FAIL')
        import numpy as np
        for column in ('portfolio_value','btc_value','eth_value','normal_cash','pending_dca_cash',
                       'tactical_bear_cash','temporary_hedge_cash','external_flow','unit_nav'):
            if not np.allclose(actual[column].astype(float),expected[column].astype(float),atol=1e-7,rtol=1e-11):
                raise ValueError('FORWARD_MONTH_ROW_IDENTITY_FAIL')
        q.history.to_csv(output/'v310_comparator_history_4h.csv', index=False)
        q.trades.to_csv(output/'v310_comparator_trades.csv', index=False)
        inputs = MonthInputs(ROOT, records, candles)
        calendar = macro_coverage_calendar(
            {'external':inputs.external,'input_coverage':{'status':'INSUFFICIENT',
             'missing_required':['macro.'+n for n in ('us_2y_yield','us_10y_yield','fed_rate','cpi','pce','nonfarm_payrolls')]}},
            records,frame.loc[frame.open_time.dt.hour.eq(0),'open_time'],monthly_publication_freshness=True)
        write_json(output/'macro_coverage_calendar.json',calendar)
        receipt.update(full_period_noop_row_identity='PASS', forward_month_row_identity='PASS',
                       macro_core_available_days=sum(r['input_coverage']=='PASS' for r in calendar),
                       macro_core_missing_days=sum(r['input_coverage']!='PASS' for r in calendar),
                       pure_v310_metrics=period_metrics(q.history,q.trades,initial))
        if args.verify_only:
            receipt.update(status='VERIFIED_ONLY_NO_GPT_CALLS')
        else:
            auth = ChatGPTAuth(ROOT/'ai_shadow/data/auth')
            client = ChatGPTPlanClient(auth,registration=(auth.active_account() or {}).get('registration'))
            if 'gpt-5.6-sol' not in [m['slug'] for m in client.list_models()]:
                raise AIError('MODEL_NOT_AVAILABLE')
            replay = MonthReplay(output,inputs,client,rules,digest,receipt,extra_digest=extra)
            combined = run_seeded_overlay(ROOT,frame,rules,seed,a,b,replay)
            combined.history.to_csv(output/'combined_history_4h.csv',index=False)
            combined.trades.to_csv(output/'combined_trades.csv',index=False)
            combined.signals.to_csv(output/'combined_quant_signals.csv',index=False)
            metrics = {'pure_v310':receipt['pure_v310_metrics'],
                       'v310_plus_ai':period_metrics(combined.history,combined.trades,initial)}
            write_json(output/'period_metrics.json',metrics)
            receipt.update(status='COMPLETED_EXPLORATORY_MONTH',test_window_completed=True,
                           performance_metrics=metrics,active_decision_cutoff=None,finished_at=utc().isoformat())
            pd.DataFrame([{**d['decision'],'decision_cutoff':d['decision_cutoff'],
                           'execution':json.dumps(d.get('execution',{}),ensure_ascii=False)}
                          for d in replay.decisions if d.get('decision')]).to_csv(output/'daily_ai_decisions.csv',index=False)
    except Exception as exc:
        if replay:
            replay.save_progress('STOPPED_INCOMPLETE')
        receipt.update(status='STOPPED_INCOMPLETE',test_window_completed=False,performance_metrics=None,
                       error_code=exc.code if isinstance(exc,AIError) else type(exc).__name__,
                       error_message=str(exc) if isinstance(exc,(ValueError,AssertionError)) else None,
                       http_status=exc.http_status if isinstance(exc,AIError) else None,stopped_at=utc().isoformat())
    finally:
        after = protected_hashes()
        changed = sorted(n for n in before.keys()|after.keys() if before.get(n)!=after.get(n))
        receipt.update(frozen_integrity='PASS' if frozen_ok(ROOT) else 'FAIL',
                       live_and_frozen_files_unchanged=not changed,changed_protected_files=changed)
        if changed or not frozen_ok(ROOT):
            receipt.update(status='INTEGRITY_FAIL',test_window_completed=False,performance_metrics=None)
        write_json(output/'run_receipt.json',safe_value(receipt))
        print(json.dumps(safe_value(receipt),ensure_ascii=False),flush=True)
    return 0 if receipt['status'] in {'VERIFIED_ONLY_NO_GPT_CALLS','COMPLETED_EXPLORATORY_MONTH'} else 1


if __name__ == '__main__':
    raise SystemExit(main())
