"""Read-only live public-provider probe and protected-file acceptance receipt.

Never signs in, calls GPT, runs the forward engine, or changes its ledger.
Evidence is written under ignored artifacts/ai_shadow_local only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

from ai_shadow.audit import frozen_audit
from ai_shadow.providers.base import collect_providers
from ai_shadow.providers.binance import BinanceDerivativesProvider, BinanceSpotProvider
from ai_shadow.providers.liquidity import StablecoinProvider
from ai_shadow.providers.macro import FredProvider
from ai_shadow.snapshot import read_frozen_portfolio, utc
from ai_shadow.storage import atomic_text
from audit_public_repository import audit


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--public-sources',action='store_true')
    parser.add_argument('--public-sources-only',action='store_true',
                        help='Probe providers only; do not repeat the independent Git history audit')
    args = parser.parse_args()
    receipt = {'checked_at':utc().isoformat(),'frozen_sha256':frozen_audit(ROOT),
               'security':{'status':'NOT_REPEATED','reference':'acceptance_receipt.json'} if args.public_sources_only else audit(),
               'live_oauth':'NOT_RUN_USER_LOGIN_REQUIRED','live_gpt':'NOT_RUN_NO_USAGE_CONSUMED'}
    forward = ROOT/'v3_10_forward'
    receipt['protected_forward_files'] = {p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
                                          for p in forward.iterdir() if p.is_file()}
    rows, digest = read_frozen_portfolio(forward/'forward_v310_portfolio.csv')
    receipt['frozen_ledger'] = {'verified_rows':len(rows),'file_sha256':digest,'latest_timestamp':rows[-1]['timestamp']}
    if args.public_sources or args.public_sources_only:
        try:
            receipt['technical'] = BinanceSpotProvider().technical()
        except Exception:
            receipt['technical'] = {'status':'ERROR'}
        receipt['external'] = collect_providers([FredProvider(),BinanceDerivativesProvider(),StablecoinProvider()])
    # Keep the live provider evidence separate from later code-only audits.
    name = 'public_source_receipt.json' if args.public_sources or args.public_sources_only else 'acceptance_receipt.json'
    path = ROOT/'artifacts/ai_shadow_local'/name
    atomic_text(path,json.dumps(receipt,ensure_ascii=False,indent=2))
    print(json.dumps({'receipt':str(path),'frozen_pass':all(v['before']==v['after'] for v in receipt['frozen_sha256'].values()),
                      'secret_candidates':None if args.public_sources_only else len(receipt['security']['secret_candidates'])+len(receipt['security']['working_tree_secret_candidates']),
                      'verified_forward_rows':len(rows),'live_gpt':'NOT_RUN'},ensure_ascii=False))


if __name__=='__main__':
    main()
