"""Adversarial examples: period labels and later revisions are not availability."""
import io
import zipfile

import pytest

from ai_shadow.historical_sources import (
    alfred_download_fields, alfred_download_batches, parse_alfred_zip, asof_records, parse_funding_zip,
)


def zipped(name, text):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w') as archive:
        archive.writestr(name, text)
    return stream.getvalue()


def test_download_selects_all_relevant_vintages_not_only_latest():
    html = '<option value="2019-12-11">a</option><option value="2020-01-14">b</option><option value="2026-09-11">future</option>'
    fields = alfred_download_fields(html, '2018-01-01', '2026-09-03')
    selected = [v for k, v in fields if k == 'form[selected_vintage_dates][]']
    assert selected == ['2019-12-11', '2020-01-14']
    assert ('form[units]', 'lin') in fields
    assert ('form[file_type]', '1') in fields


def test_download_respects_provider_last_available_observation():
    html = ('<option value="2026-08-12">a</option>'
            '<input name="form[obs_end_date]" value="2026-08-01">')
    fields = alfred_download_fields(html, '2018-01-01', '2026-09-03')
    assert ('form[obs_end_date]', '2026-08-01') in fields
    assert ('form[entered_vintage_dates]', '2018-01-01 2026-09-03') in fields


def test_daily_exports_are_batched_below_observed_450_vintage_limit():
    from datetime import date, timedelta
    dates = [(date(2019, 1, 1)+timedelta(days=d)).isoformat() for d in range(901)]
    html = ''.join('<option value="'+d+'">a</option>' for d in dates)
    batches = alfred_download_batches(html, '2018-01-01', '2026-09-03')
    assert len(batches) == 3
    selected = [v for batch in batches for k, v in batch if k == 'form[selected_vintage_dates][]']
    assert selected == dates
    assert all(sum(k == 'form[selected_vintage_dates][]' for k, _ in b)+2 <= 450 for b in batches)


def test_macro_date_label_cannot_make_a_future_release_available():
    raw = zipped('obs._by_real-time_period.csv',
                 'period_start_date,CPIAUCSL,realtime_start_date,realtime_end_date\n'
                 '2019-11-01,257.936,2019-12-11,2020-02-10\n'
                 '2019-11-01,257.824,2020-02-11,.\n'
                 '2019-12-01,258.444,2020-01-14,.\n')
    records = parse_alfred_zip(raw, 'CPIAUCSL', 'macro.cpi')
    snapshot = asof_records(records, '2020-01-01T00:00:00Z')
    assert len(snapshot) == 1
    assert snapshot[0]['value'] == 257.936
    assert 'realtime_end_date' not in snapshot[0]  # Later revision timing is hidden.
    assert 'retrieved_at' not in snapshot[0]  # Retrieval is not publication.


def test_vintage_day_has_explicit_conservative_availability_delay():
    raw = zipped('obs._by_real-time_period.csv',
                 'period_start_date,PAYEMS,realtime_start_date,realtime_end_date\n'
                 '2019-11-01,152000,2019-12-06,.\n')
    records = parse_alfred_zip(raw, 'PAYEMS', 'macro.nonfarm_payrolls')
    assert asof_records(records, '2019-12-07T23:59:59Z') == []
    assert len(asof_records(records, '2019-12-08T00:00:00Z')) == 1


def test_future_revision_perturbation_cannot_change_earlier_input():
    records = [
        {'field': 'macro.cpi', 'observation_time': '2019-11-01T00:00:00Z',
         'available_at': '2019-12-13T00:00:00Z', 'value': 257.936, 'pit_status': 'VINTAGE_VERIFIED'},
        {'field': 'macro.cpi', 'observation_time': '2019-11-01T00:00:00Z',
         'available_at': '2020-02-13T00:00:00Z', 'value': 999999, 'pit_status': 'VINTAGE_VERIFIED'},
    ]
    assert asof_records(records, '2020-01-01T00:00:00Z')[0]['value'] == 257.936
    assert asof_records(records, '2020-02-14T00:00:00Z')[0]['value'] == 999999


def test_unverified_or_missing_availability_is_excluded():
    records = [{'field': 'liquidity.stablecoins', 'observation_time': '2019-12-31T00:00:00Z',
                'available_at': None, 'value': 123, 'pit_status': 'REVISION_HISTORY_UNVERIFIED'}]
    assert asof_records(records, '2020-01-01T00:00:00Z') == []


def test_latest_released_missing_value_does_not_resurrect_old_revision():
    raw = zipped('obs._by_real-time_period.csv',
                 'period_start_date,CPIAUCSL,realtime_start_date,realtime_end_date\n'
                 '2019-11-01,257.936,2019-12-11,2020-02-10\n'
                 '2019-11-01,.,2020-02-11,.\n')
    selected = asof_records(parse_alfred_zip(raw, 'CPIAUCSL', 'macro.cpi'), '2020-02-14T00:00:00Z')
    assert selected[0]['value'] is None


def test_duplicate_revision_conflict_fails_closed():
    raw = zipped('obs._by_real-time_period.csv',
                 'period_start_date,PAYEMS,realtime_start_date,realtime_end_date\n'
                 '2019-11-01,152000,2019-12-06,.\n'
                 '2019-11-01,999999,2019-12-06,.\n')
    with pytest.raises(ValueError, match='CONFLICTING_VINTAGE'):
        parse_alfred_zip(raw, 'PAYEMS', 'macro.nonfarm_payrolls')


def test_funding_archive_is_not_falsely_certified_as_vintage_data():
    raw = zipped('BTCUSDT-fundingRate-2020-01.csv',
                 'calc_time,funding_interval_hours,last_funding_rate\n1577836800000,8,0.0001\n')
    records = parse_funding_zip(raw, 'BTC')
    assert records[0]['value'] == .0001
    assert records[0]['pit_status'] == 'EVENT_TIME_ONLY_REVISION_UNVERIFIED'
    assert asof_records(records, '2020-01-02T00:00:00Z') == []


def test_macro_attachment_uses_original_vintage_and_leaves_other_gaps():
    from pathlib import Path
    from ai_shadow.historical_preflight import historical_snapshot
    from ai_shadow.historical_sources import attach_historical_macro
    snapshot = historical_snapshot(Path(__file__).resolve().parents[2], '2020-01-01T00:00:00Z')
    raw = zipped('obs._by_real-time_period.csv',
                 'period_start_date,CPIAUCSL,realtime_start_date,realtime_end_date\n'
                 '2019-11-01,257.936,2019-12-11,2020-02-10\n'
                 '2019-11-01,257.824,2020-02-11,.\n')
    result = attach_historical_macro(snapshot, parse_alfred_zip(raw, 'CPIAUCSL', 'macro.cpi'))
    assert result['external']['macro']['cpi']['value'] == 257.936
    assert 'macro.cpi' not in result['input_coverage']['missing_required']
    assert 'macro.dxy' in result['input_coverage']['missing_required']
    assert result['input_coverage']['status'] == 'INSUFFICIENT'
    assert snapshot['external']['macro']['cpi']['value'] is None
    assert result['snapshot_hash'] != snapshot['snapshot_hash']


def test_snapshot_validator_rejects_future_availability_keys():
    from ai_shadow.snapshot import validate_asof
    with pytest.raises(ValueError, match='FUTURE_EVIDENCE'):
        validate_asof({'available_at': '2020-01-02T00:00:00Z'}, '2020-01-01T00:00:00Z')


def test_monthly_freshness_uses_publication_not_the_statistical_month_start():
    from ai_shadow.historical_sources import attach_historical_macro
    snapshot = {'decision_cutoff': '2020-01-15T00:00:00Z',
        'external': {'macro': {'pce': {'status': 'MISSING', 'value': None}}},
        'input_coverage': {'missing_required': ['macro.pce'], 'status': 'INSUFFICIENT'}}
    records = [{'field': 'macro.pce', 'value': 110, 'pit_status': 'VINTAGE_VERIFIED',
                'observation_time': '2019-11-01T00:00:00Z',
                'available_at': '2019-12-22T00:00:00Z'}]
    # It is 75 days since the statistical period began, but only 24 since release.
    actual = attach_historical_macro(snapshot, records, monthly_publication_freshness=True)
    assert actual['external']['macro']['pce']['status'] == 'PASS'
    assert actual['external']['macro']['pce']['publication_age_days'] == 24
    assert actual['input_coverage']['status'] == 'PASS'


def test_recent_revision_cannot_make_an_obsolete_statistical_period_fresh():
    from ai_shadow.historical_sources import attach_historical_macro
    snapshot = {'decision_cutoff': '2020-05-01T00:00:00Z',
        'external': {'macro': {'pce': {'status': 'MISSING', 'value': None}}},
        'input_coverage': {'missing_required': ['macro.pce'], 'status': 'INSUFFICIENT'}}
    records = [{'field': 'macro.pce', 'value': 110, 'pit_status': 'VINTAGE_VERIFIED',
                'observation_time': '2019-11-01T00:00:00Z',
                'available_at': '2020-04-30T00:00:00Z'}]
    actual = attach_historical_macro(snapshot, records, monthly_publication_freshness=True)
    assert actual['input_coverage']['status'] == 'INSUFFICIENT'


def test_new_monthly_contract_rejects_an_old_publication_and_preserves_legacy():
    from ai_shadow.historical_sources import attach_historical_macro
    snapshot = {'decision_cutoff': '2020-01-15T00:00:00Z',
        'external': {'macro': {'pce': {'status': 'MISSING', 'value': None}}},
        'input_coverage': {'missing_required': ['macro.pce'], 'status': 'INSUFFICIENT'}}
    record = {'field': 'macro.pce', 'value': 110, 'pit_status': 'VINTAGE_VERIFIED',
              'observation_time': '2019-11-01T00:00:00Z',
              'available_at': '2019-12-22T00:00:00Z'}
    assert attach_historical_macro(snapshot, [record])['input_coverage']['status'] == 'INSUFFICIENT'
    record['available_at'] = '2019-11-29T00:00:00Z'
    assert attach_historical_macro(snapshot, [record], monthly_publication_freshness=True)[
        'input_coverage']['status'] == 'INSUFFICIENT'
