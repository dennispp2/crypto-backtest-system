"""Offline re-audit of immutable downloads and a first-decision input.

No web requests, GPT calls, trades, live ledgers, or performance claims.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ai_shadow.audit import frozen_audit, frozen_ok
from ai_shadow.historical_preflight import historical_snapshot
from ai_shadow.historical_sources import attach_historical_macro, parse_alfred_zip, parse_funding_zip, timestamp
from scripts.collect_historical_external import MACRO, END, profile, write_json


def read_and_verify(run):
    base = (ROOT/'artifacts/ai_shadow_local/historical_external_data_v1').resolve()
    run = Path(run).resolve()
    if run.parent != base:
        raise ValueError('SOURCE_RUN_OUTSIDE_HISTORICAL_ARCHIVE')
    manifest = json.loads((run/'source_manifest.json').read_text(encoding='utf-8'))
    verified = []
    for receipt in manifest['sources']:
        if receipt.get('status') != 'DOWNLOADED':
            continue
        path = (run/'data/raw'/receipt['raw_file']).resolve()
        if path.parent != (run/'data/raw').resolve():
            raise ValueError('SOURCE_FILE_OUTSIDE_RAW_ARCHIVE')
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != receipt['sha256']:
            raise ValueError('SOURCE_HASH_MISMATCH')
        verified.append({**receipt, 'run_directory': str(run)})
    return run, manifest, verified


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--macro-run', required=True)
    parser.add_argument('--funding-run', required=True)
    args = parser.parse_args()
    if not frozen_ok(ROOT):
        raise SystemExit('FROZEN_INTEGRITY_FAILED')
    macro_run, macro_manifest, macro_files = read_and_verify(args.macro_run)
    funding_run, _, funding_files = read_and_verify(args.funding_run)
    records, excluded = [], {}
    for series, field in MACRO.items():
        failures = [r for r in macro_manifest['sources']
                    if r['url'].endswith('seid='+series) and r['status'] not in {'DOWNLOADED'}]
        if failures:
            excluded[series] = [r.get('error_code') or r['status'] for r in failures]
            continue
        merged = {}
        for receipt in macro_files:
            if not receipt['raw_file'].startswith(series+'_vintages_part'):
                continue
            for r in parse_alfred_zip((macro_run/'data/raw'/receipt['raw_file']).read_bytes(), series, field):
                key = (r['observation_time'], r['vintage_date'])
                if key in merged and merged[key]['value'] != r['value']:
                    raise ValueError('CONFLICTING_SOURCE_EXPORTS')
                merged[key] = r
        records.extend(merged.values())
    funding = []
    for receipt in funding_files:
        if receipt['raw_file'].endswith('.zip') and receipt.get('checksum_match'):
            asset = receipt['raw_file'][:3]
            raw = (funding_run/'data/raw'/receipt['raw_file']).read_bytes()
            funding.extend(r for r in parse_funding_zip(raw, asset)
                           if timestamp(r['observation_time']) <= timestamp(END))
    snapshot = attach_historical_macro(historical_snapshot(ROOT, '2020-01-01T00:00:00Z'), records)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    output = ROOT/'artifacts/ai_shadow_local/historical_external_data_v1'/('audit_'+stamp)
    output.mkdir(parents=True, exist_ok=False)
    code_files = ('scripts/audit_collected_history.py', 'scripts/collect_historical_external.py',
                  'ai_shadow/historical_sources.py', 'ai_shadow/historical_preflight.py',
                  'ai_shadow/snapshot.py', 'ai_shadow/technical.py',
                  'ai_shadow/policy/historical_v310_preflight_v1.md',
                  'ai_shadow/schemas/historical_decision_v1.schema.json')
    code_hashes = {}
    for name in code_files:
        raw = (ROOT/name).read_bytes()
        target = output/'code'/name
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open('xb') as stream:
            stream.write(raw)
        code_hashes[name] = hashlib.sha256(raw).hexdigest()
    write_json(output/'data/processed/macro_vintages.json', records)
    write_json(output/'data/processed/funding_quarantined.json', funding)
    write_json(output/'data/processed/first_decision_snapshot.json', snapshot)
    write_json(output/'source_manifest.json', {'verified_downloads': macro_files+funding_files,
                                              'source_runs': [str(macro_run), str(funding_run)],
                                              'code_sha256': code_hashes})
    report = {'mode': 'OFFLINE_HISTORICAL_INPUT_AUDIT_NOT_FULL_AI_BACKTEST',
              'download_hash_integrity': 'PASS', 'source_files_verified': len(macro_files)+len(funding_files),
              'macro_profiles': {s: profile([r for r in records if r['series_id'] == s]) for s in MACRO},
              'excluded_series': excluded, 'funding_profile': profile(funding),
              'macro_fields_attached': [k for k, v in snapshot['external']['macro'].items() if v['status'] == 'PASS'],
              'remaining_required_inputs': snapshot['input_coverage']['missing_required'],
              'input_coverage': snapshot['input_coverage']['status'],
              'input_cutoff_guard': 'PASS_FOR_THIS_FIRST_DECISION_SNAPSHOT_ONLY',
              'full_period_input_audit': 'NOT_RUN', 'pretrained_future_knowledge': 'UNRESOLVED',
              'no_lookahead_gate_for_full_ai_backtest': 'NOT_ESTABLISHED',
              'gpt_calls': 0, 'performance_metrics': None,
              'frozen_files': frozen_audit(ROOT), 'frozen_integrity': 'PASS' if frozen_ok(ROOT) else 'FAIL'}
    write_json(output/'audit_receipt.json', report)
    print(json.dumps({'output_directory': str(output), 'macro_records': len(records),
                      'funding_records_quarantined': len(funding), 'input_coverage': report['input_coverage'],
                      'gpt_calls': 0, 'frozen_integrity': report['frozen_integrity']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
