"""Collect public historical evidence without calling GPT or modifying V3.10.

Outputs go to an ignored, uniquely named local archive. Ineligible modern
backfills remain research candidates; they are NEVER silently fed to GPT.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import urllib.error
import urllib.parse
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ai_shadow.audit import frozen_audit, frozen_ok
from ai_shadow.historical_sources import (
    alfred_download_batches, asof_records, parse_alfred_zip, parse_funding_zip, timestamp,
)
from ai_shadow.snapshot import canonical_hash
from ai_shadow.storage import atomic_text

END = '2026-09-03T04:00:00Z'
MACRO = {
    'DGS2': 'macro.us_2y_yield', 'DGS10': 'macro.us_10y_yield',
    'VIXCLS': 'macro.vix', 'DFEDTARU': 'macro.fed_target_upper',
    'DFEDTARL': 'macro.fed_target_lower', 'CPIAUCSL': 'macro.cpi',
    'PCEPI': 'macro.pce', 'PAYEMS': 'macro.nonfarm_payrolls',
}


def write_json(path, value):
    atomic_text(path, json.dumps(value, ensure_ascii=False, indent=2)+'\n')


def download(directory, name, url, fields=None):
    data = None if fields is None else urllib.parse.urlencode(fields).encode('utf-8')
    # Use urllib's standard public-download request. ALFRED's export service
    # timed out with a custom app agent but succeeded with the standard client.
    request = urllib.request.Request(url, data=data)
    receipt = {'url': url, 'method': 'GET' if data is None else 'POST',
               'request_fields': fields, 'retrieved_at': datetime.now(timezone.utc).isoformat()}
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read(12_000_001)
            if len(raw) > 12_000_000:
                raise ValueError('SOURCE_TOO_LARGE')
            receipt.update(http_status=response.status, bytes=len(raw),
                           sha256=hashlib.sha256(raw).hexdigest(), raw_file=name)
        path = directory/'data/raw'/name
        path.parent.mkdir(parents=True, exist_ok=True)
        # Each run directory is new; never overwrite a prior source snapshot.
        with path.open('xb') as stream:
            stream.write(raw)
        receipt['status'] = 'DOWNLOADED'
        return raw, receipt
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as error:
        receipt.update(status='UNAVAILABLE', error_type=type(error).__name__,
                       http_status=getattr(error, 'code', None))
        return None, receipt


def collect_macro(directory, item):
    series, field = item
    url = 'https://alfred.stlouisfed.org/series/downloaddata?seid='+series
    form, first = download(directory, series+'_download_form.html', url)
    receipts = [first]
    records = []
    if form is not None:
        try:
            batches = alfred_download_batches(form.decode('utf-8'), '2018-01-01', END[:10])
            all_records, complete = {}, True
            for part, fields in enumerate(batches, 1):
                raw, second = download(directory, series+'_vintages_part'+str(part)+'.zip', url, fields)
                receipts.append(second)
                if raw is None:
                    complete = False
                    continue
                for record in parse_alfred_zip(raw, series, field):
                    key = (record['observation_time'], record['vintage_date'])
                    if key in all_records and all_records[key]['value'] != record['value']:
                        raise ValueError('CONFLICTING_EXPORT_BATCHES')
                    all_records[key] = record
            # A missing vintage batch could hide an intervening revision.
            # Never label the surviving, older values as complete as-of data.
            if complete:
                records = list(all_records.values())
            else:
                receipts.append({'url': url, 'status': 'INCOMPLETE_VINTAGE_EXPORT_EXCLUDED'})
        except (ValueError, KeyError, UnicodeError, zipfile.BadZipFile, csv.Error) as error:
            # Record schema/export failures without reinterpreting HTML as CSV.
            receipts.append({'url': url, 'status': 'NORMALIZATION_FAILED',
                             'error_type': type(error).__name__,
                             'error_code': str(error) if isinstance(error, ValueError) else None})
    print(series+': '+str(len(records))+' vintage records', flush=True)
    return {'series': series, 'field': field, 'records': records, 'receipts': receipts}


def collect_funding(directory, job):
    asset, month = job
    filename = asset+'USDT-fundingRate-'+month+'.zip'
    url = 'https://data.binance.vision/data/futures/um/monthly/fundingRate/'+asset+'USDT/'+filename
    raw, receipt = download(directory, filename, url)
    receipts, records = [receipt], []
    if raw is not None:
        checksum, proof = download(directory, filename+'.CHECKSUM', url+'.CHECKSUM')
        receipts.append(proof)
        if checksum is None or checksum.decode('utf-8').split()[0].lower() != receipt['sha256']:
            receipts.append({'url': url, 'status': 'CHECKSUM_FAILED'})
        else:
            try:
                records = parse_funding_zip(raw, asset)
                receipt['checksum_match'] = True
            except (ValueError, UnicodeError) as error:
                receipts.append({'url': url, 'status': 'NORMALIZATION_FAILED',
                                 'error_type': type(error).__name__})
    return {'asset': asset, 'month': month, 'records': records, 'receipts': receipts}


def profile(records):
    if not records:
        return {'rows': 0}
    observations = [r['observation_time'] for r in records]
    availability = [r['available_at'] for r in records if r.get('available_at')]
    keys = [(r['field'], r['observation_time'], r.get('available_at')) for r in records]
    return {'rows': len(records), 'min_observation': min(observations),
            'max_observation': max(observations),
            'min_available_at': min(availability) if availability else None,
            'max_available_at': max(availability) if availability else None,
            'missing_values': sum(r['value'] is None for r in records),
            'duplicate_keys': len(keys)-len(set(keys)),
            'pit_statuses': sorted(set(r['pit_status'] for r in records))}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--include-funding', action='store_true')
    args = parser.parse_args()
    if not frozen_ok(ROOT):
        raise SystemExit('FROZEN_INTEGRITY_FAILED')
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    directory = ROOT/'artifacts/ai_shadow_local/historical_external_data_v1'/stamp
    directory.mkdir(parents=True, exist_ok=False)
    contract = {
        'mode': 'HISTORICAL_EXTERNAL_DATA_COLLECTION_NOT_A_PERFORMANCE_BACKTEST',
        'formal_start': '2020-01-01T00:00:00Z', 'formal_end': END,
        'technical_warmup_start': '2019-01-01', 'macro_observation_start': '2018-01-01',
        'macro_sources': MACRO, 'macro_availability': 'ALFRED vintage day + 2 calendar days at 00:00 UTC',
        'macro_units': 'Provider raw levels, no unverified consensus forecasts or surprises',
        'dxy': 'ICE DXY only; FRED broad USD is not an equivalent substitute',
        'modern_backfills': 'Quarantined unless publication/revision history is verified',
        'news': 'No current web search results enter historical decision snapshots',
        'gpt_calls': 0, 'source_code_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'normalizer_sha256': hashlib.sha256((ROOT/'ai_shadow/historical_sources.py').read_bytes()).hexdigest(),
        'frozen_before': frozen_audit(ROOT),
        'unresolved_model_lookahead': 'A current GPT can have pretrained knowledge of later history; input filtering cannot prove absence',
    }
    write_json(directory/'collection_contract.json', {**contract, 'contract_hash': canonical_hash(contract)})
    for name in ('scripts/collect_historical_external.py', 'ai_shadow/historical_sources.py'):
        target = directory/'code'/name
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open('xb') as stream:
            stream.write((ROOT/name).read_bytes())
    receipts, macro_records, funding_records = [], [], []
    with ThreadPoolExecutor(max_workers=3) as executor:
        for result in executor.map(lambda item: collect_macro(directory, item), MACRO.items()):
            receipts.extend(result['receipts'])
            macro_records.extend(result['records'])
    write_json(directory/'data/processed/macro_vintages.json', macro_records)
    if args.include_funding:
        months = [f'{year}-{month:02d}' for year in range(2020, 2027)
                  for month in range(1, 13) if f'{year}-{month:02d}' <= '2026-09']
        jobs = [(asset, month) for asset in ('BTC', 'ETH') for month in months]
        with ThreadPoolExecutor(max_workers=4) as executor:
            for number, result in enumerate(executor.map(lambda job: collect_funding(directory, job), jobs), 1):
                receipts.extend(result['receipts'])
                funding_records.extend(r for r in result['records'] if timestamp(r['observation_time']) <= timestamp(END))
                if number % 20 == 0 or number == len(jobs):
                    print('Funding archives: '+str(number)+' / '+str(len(jobs)), flush=True)
        # Also retrieve the first decision's preceding settlement records.
        for asset in ('BTC', 'ETH'):
            url = 'https://fapi.binance.com/fapi/v1/fundingRate?'+urllib.parse.urlencode({
                'symbol': asset+'USDT', 'startTime': 1575158400000,
                'endTime': 1577836799999, 'limit': 1000})
            _, receipt = download(directory, asset+'_funding_2019_12_rest.json', url)
            receipts.append(receipt)
        write_json(directory/'data/processed/funding_quarantined.json', funding_records)
    candidates = [
        ('stablecoin_supply_current_backfill.json', 'https://stablecoins.llama.fi/stablecoincharts/all'),
        ('btc_etf_flow_current_backfill.html', 'https://farside.co.uk/bitcoin-etf-flow-all-data/'),
        ('eth_etf_flow_current_backfill.html', 'https://farside.co.uk/ethereum-etf-flow-all-data/'),
        ('fomc_2019_12_statement.html', 'https://www.federalreserve.gov/newsevents/pressreleases/monetary20191211a.htm'),
        ('cpi_2019_11_release.html', 'https://www.bls.gov/news.release/archives/cpi_12112019.htm'),
        ('payroll_2019_11_release.html', 'https://www.bls.gov/news.release/archives/empsit_12062019.htm'),
        ('pce_2019_11_release.html', 'https://www.bea.gov/news/2019/personal-income-and-outlays-november-2019'),
    ]
    for name, url in candidates:
        _, receipt = download(directory, name, url)
        receipt['historical_eligibility'] = 'QUARANTINED_PENDING_DOCUMENT_LEVEL_PUBLICATION_REVISION_AUDIT'
        receipts.append(receipt)
    first = asof_records(macro_records, '2020-01-01T00:00:00Z')
    write_json(directory/'data/processed/first_decision_macro_asof.json', first)
    per_series = {series: profile([r for r in macro_records if r['series_id'] == series]) for series in MACRO}
    report = {
        'status': 'PARTIAL_HISTORY_COLLECTED_FULL_AI_BACKTEST_NOT_RUN',
        'formal_period': [contract['formal_start'], END], 'macro_profiles': per_series,
        'funding_profile': profile(funding_records),
        'first_decision_macro_records': len(first),
        'first_decision_fields': sorted(set(r['field'] for r in first if r['value'] is not None)),
        'strict_historical_input_filter': 'Only verified vintages at available_at <= decision cutoff',
        'unresolved': ['ICE DXY licensed/public historical export not acquired',
                       'Complete 2020-2026 derivative OI/basis/long-short/liquidation publication history missing',
                       'Modern funding/ETF/stablecoin backfills are not certified original vintages',
                       'Exchange/holder classification can be retrospectively relabeled',
                       'Complete dated unrevised news corpus not collected',
                       'Pretrained model future-knowledge contamination cannot be ruled out'],
        'gpt_calls': 0, 'performance_metrics': None,
        'frozen_after': frozen_audit(ROOT), 'frozen_integrity': 'PASS' if frozen_ok(ROOT) else 'FAIL',
    }
    write_json(directory/'source_manifest.json', {'sources': receipts})
    write_json(directory/'coverage_audit.json', report)
    print(json.dumps({'output_directory': str(directory), 'status': report['status'],
                      'macro_rows': len(macro_records), 'funding_rows': len(funding_records),
                      'frozen_integrity': report['frozen_integrity'], 'gpt_calls': 0}, ensure_ascii=False), flush=True)
    return 0 if report['frozen_integrity'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
