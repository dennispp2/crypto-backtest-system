import hashlib
import json

import pytest


def test_failed_macro_normalization_remains_quarantined_during_reparse(tmp_path,monkeypatch):
    from scripts import backtest_v310_gpt_month as runner
    output, source = tmp_path/'output',tmp_path/'prior'
    (output/'data/raw').mkdir(parents=True)
    (output/'data/processed').mkdir(parents=True)
    (source/'data/processed').mkdir(parents=True)
    raw = b'An invalid ALFRED ZIP; collector excluded this series'
    (output/'data/raw/VIXCLS_vintages_1.zip').write_bytes(raw)
    processed = output/'data/processed/macro_vintages.json'
    processed.write_text('[]',encoding='utf-8')
    (source/'data/processed/macro_vintages.json').write_text('[]',encoding='utf-8')
    (output/'source_manifest.json').write_text(json.dumps({
        'processed_macro_sha256':hashlib.sha256(processed.read_bytes()).hexdigest(),
        'sources':[{'status':'DOWNLOADED','raw_file':'VIXCLS_vintages_1.zip',
                    'sha256':hashlib.sha256(raw).hexdigest()},
                   {'status':'NORMALIZATION_FAILED','series':'VIXCLS'}]}),encoding='utf-8')
    def forbidden(*_):
        pytest.fail('Quarantined records must not be reparsed as eligible input')
    monkeypatch.setattr(runner,'parse_alfred_zip',forbidden)
    assert runner.verify_month_sources(output,source) == []
