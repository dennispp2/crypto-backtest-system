"""Run the ORIGINAL frozen historical runner into a NEW local evidence folder.

No strategy/config edits, downloads, search or original output overwrites. Only
the runner's five OUTPUT directory variables are redirected in this process.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
os.environ['MPLBACKEND'] = 'Agg'

from ai_shadow.storage import atomic_text


def protected_hashes():
    paths = [p for name in ('config','v3_10','v3_10_forward') for p in (ROOT/name).rglob('*') if p.is_file()]
    paths += list((ROOT/'src/crypto_backtest').glob('*.py'))
    paths += [ROOT/'run_backtest_v3_10.py',ROOT/'run_forward_v3_10.py']
    return {p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


def main():
    tag = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S_%fZ')
    output = ROOT/'artifacts/ai_shadow_local'/('historical_replay_'+tag)
    output.mkdir(parents=True,exist_ok=False)
    before = protected_hashes()
    receipt = {'output':str(output), 'started_at':datetime.now(timezone.utc).isoformat(),
               'mode':'ORIGINAL_FROZEN_V310_HISTORICAL_REPLAY',
               'gpt_historical_backtest':'NOT_RUN_NO_POINT_IN_TIME_EXTERNAL_ARCHIVE',
               'protected_before':before}
    atomic_text(output/'replay_receipt.json',json.dumps(receipt,ensure_ascii=False,indent=2))
    import run_backtest_v3_10 as runner
    runner.OUTPUT_DIR = output
    runner.RESULTS_DIR,runner.ARTIFACTS_DIR = output/'results',output/'artifacts'
    runner.FIGURES_DIR,runner.REPORT_DIR = output/'figures',output/'report'
    try:
        code = runner.main()
        receipt.update(exit_code=code, status='PASS' if code==0 else 'FAIL')
    except Exception as exc:
        receipt.update(exit_code=1,status='FAIL',exception_type=type(exc).__name__,error=str(exc))
        code = 1
    finally:
        after = protected_hashes()
        changed = sorted(p for p in set(before)|set(after) if before.get(p)!=after.get(p))
        receipt.update(finished_at=datetime.now(timezone.utc).isoformat(),protected_after=after,
                       protected_unchanged=not changed,changed_protected_files=changed)
        atomic_text(output/'replay_receipt.json',json.dumps(receipt,ensure_ascii=False,indent=2))
        if changed:
            code = 1
    print(json.dumps({'output':str(output),'status':receipt['status'],'protected_unchanged':not changed},ensure_ascii=False))
    return code


if __name__=='__main__':
    raise SystemExit(main())
