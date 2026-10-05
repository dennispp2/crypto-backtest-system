"""One real gpt-5.6-sol historical-input call using the existing ChatGPT plan.

This is a connection/decision diagnostic, NOT a portfolio backtest. It never
changes V3.10, its paper ledger, AI Shadow holdings, or credentials outside
the existing OAuth refresh lifecycle. No API key fallback or current web tool.
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
from ai_shadow.auth.chatgpt_auth import ChatGPTAuth
from ai_shadow.clients.chatgpt_plan import ChatGPTPlanClient
from ai_shadow.errors import AIError
from ai_shadow.historical_inference import MODEL, run_first_decision
from ai_shadow.snapshot import canonical_hash, utc, validate_asof
from scripts.collect_historical_external import write_json
from scripts.replay_frozen_v310 import protected_hashes


def verified_snapshot(source_audit):
    """Recheck source files and frozen audit code before exposing any evidence."""
    base = (ROOT/'artifacts/ai_shadow_local/historical_external_data_v1').resolve()
    source = Path(source_audit).resolve()
    if source.parent != base or not source.name.startswith('audit_'):
        raise ValueError('SOURCE_AUDIT_OUTSIDE_HISTORICAL_ARCHIVE')
    report = json.loads((source/'audit_receipt.json').read_text(encoding='utf-8'))
    if report.get('download_hash_integrity') != 'PASS' or report.get('frozen_integrity') != 'PASS':
        raise ValueError('SOURCE_AUDIT_NOT_PASS')
    manifest = json.loads((source/'source_manifest.json').read_text(encoding='utf-8'))
    for name, digest in manifest['code_sha256'].items():
        code = (source/'code'/name).resolve()
        if (source/'code').resolve() not in code.parents:
            raise ValueError('SOURCE_CODE_PATH_UNSAFE')
        if hashlib.sha256(code.read_bytes()).hexdigest() != digest:
            raise ValueError('SOURCE_CODE_HASH_MISMATCH')
    verified = 0
    for receipt in manifest['verified_downloads']:
        source_run = Path(receipt['run_directory']).resolve()
        if source_run.parent != base:
            raise ValueError('SOURCE_RUN_PATH_UNSAFE')
        raw = (source_run/'data/raw'/receipt['raw_file']).resolve()
        if raw.parent != (source_run/'data/raw').resolve():
            raise ValueError('SOURCE_FILE_PATH_UNSAFE')
        if hashlib.sha256(raw.read_bytes()).hexdigest() != receipt['sha256']:
            raise ValueError('SOURCE_DOWNLOAD_HASH_MISMATCH')
        verified += 1
    snapshot = json.loads((source/'data/processed/first_decision_snapshot.json').read_text(encoding='utf-8'))
    if snapshot['snapshot_hash'] != canonical_hash({k: v for k, v in snapshot.items() if k != 'snapshot_hash'}):
        raise ValueError('HISTORICAL_SNAPSHOT_HASH_MISMATCH')
    validate_asof(snapshot, snapshot['decision_cutoff'])
    return source, snapshot, verified


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-audit', required=True)
    parser.add_argument('--accept-model-memory-risk', action='store_true', required=True)
    args = parser.parse_args()
    if not frozen_ok(ROOT):
        raise SystemExit('FROZEN_INTEGRITY_FAILED')
    source, snapshot, verified = verified_snapshot(args.source_audit)
    before = protected_hashes()
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    output = ROOT/'artifacts/ai_shadow_local/historical_gpt_diagnostic_v1'/stamp
    output.mkdir(parents=True, exist_ok=False)
    code_files = ('scripts/run_historical_gpt_diagnostic.py', 'ai_shadow/historical_inference.py',
                  'ai_shadow/historical_preflight.py', 'ai_shadow/snapshot.py',
                  'ai_shadow/clients/chatgpt_plan.py', 'ai_shadow/http.py',
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
    contract = {
        'mode': 'EXPLORATORY_FIRST_HISTORICAL_GPT_DECISION_NOT_A_BACKTEST',
        'model': MODEL, 'provider': 'EXISTING_CHATGPT_PLAN_OAUTH', 'paid_api_fallback': False,
        'historical_cutoff': snapshot['decision_cutoff'],
        'user_accepted_model_memory_risk': True,
        'pretrained_future_knowledge': 'UNRESOLVED',
        'data_gate': 'INSUFFICIENT_REQUIRED_INPUTS_FORCE_HOLD_NO_TRADES',
        'source_audit': str(source), 'source_files_reverified': verified,
        'snapshot_hash': snapshot['snapshot_hash'], 'code_sha256': code_hashes,
        'frozen_before': frozen_audit(ROOT),
        'created_at': utc().isoformat(), 'web_tools_enabled': False,
    }
    write_json(output/'experiment_contract.json', contract)
    write_json(output/'historical_snapshot.json', snapshot)
    receipt = {
        'status': 'NOT_STARTED', 'inference_requests_started': 0, 'gpt_decisions_completed': 0,
        'trades_executed': 0, 'full_historical_backtest': 'NOT_RUN',
        'performance_metrics': None, 'output_directory': str(output),
    }
    write_json(output/'run_receipt.json', receipt)
    exit_code = 1
    try:
        auth = ChatGPTAuth(ROOT/'ai_shadow/data/auth')
        account = auth.active_account()
        if not account or not account.get('plan_authorized'):
            raise AIError('PLAN_USAGE_NOT_AUTHORIZED')
        client = ChatGPTPlanClient(auth, registration=account['registration'])
        models = [m['slug'] for m in client.list_models()]
        write_json(output/'available_model_slugs.json', models)
        if MODEL not in models:
            raise AIError('MODEL_NOT_AVAILABLE')
        receipt.update(status='INFERENCE_STARTED', inference_requests_started=1, started_at=utc().isoformat())
        write_json(output/'run_receipt.json', receipt)
        result = run_first_decision(client, snapshot)
        write_json(output/'first_decision.json', result)
        receipt.update(status='COMPLETED_DIAGNOSTIC_ONLY', gpt_decisions_completed=1,
                       action=result['effective_decision']['action'], data_gate=result['gate'],
                       response_completed=True, response_id=result['response_id'])
        exit_code = 0
    except AIError as exc:
        receipt.update(status='FAILED', error_code=exc.code, http_status=exc.http_status,
                       request_id=exc.request_id)
    except Exception as exc:
        # Never persist exception details: provider/auth exceptions may contain secrets.
        receipt.update(status='FAILED_LOCAL_VALIDATION', exception_type=type(exc).__name__)
    finally:
        after = protected_hashes()
        changed = sorted(p for p in set(before) | set(after) if before.get(p) != after.get(p))
        receipt.update(finished_at=utc().isoformat(), frozen_integrity='PASS' if frozen_ok(ROOT) else 'FAIL',
                       protected_unchanged=not changed, changed_protected_files=changed)
        if changed or not frozen_ok(ROOT):
            receipt['status'] = 'FROZEN_INTEGRITY_FAILED'
            exit_code = 1
        write_json(output/'run_receipt.json', receipt)
    print(json.dumps(receipt, ensure_ascii=False))
    return exit_code


if __name__ == '__main__':
    raise SystemExit(main())
