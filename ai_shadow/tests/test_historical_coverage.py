"""Daily source-coverage checks are not a strategy or parameter search."""
from ai_shadow.historical_sources import attach_historical_macro


def record(observed, available, value):
    return {'field': 'macro.us_2y_yield', 'observation_time': observed,
            'available_at': available, 'value': value, 'pit_status': 'VINTAGE_VERIFIED'}


def test_coverage_calendar_never_uses_a_future_revision_or_resurrects_a_null():
    from ai_shadow.historical_coverage import macro_coverage_calendar
    records = [record('2020-01-01T00:00:00Z', '2020-01-03T00:00:00Z', 2.0),
               record('2020-01-01T00:00:00Z', '2020-01-05T00:00:00Z', 3.0),
               record('2020-01-04T00:00:00Z', '2020-01-06T00:00:00Z', None)]
    template = {'external': {'macro': {'us_2y_yield': {'value': None, 'status': 'MISSING'}}},
                'input_coverage': {'status': 'INSUFFICIENT', 'missing_required': ['macro.us_2y_yield']}}
    cutoffs = ['2020-01-02T00:00:00Z', '2020-01-04T00:00:00Z',
               '2020-01-05T00:00:00Z', '2020-01-06T00:00:00Z']
    result = macro_coverage_calendar(template, records, cutoffs)
    assert [r['available_macro_fields'] for r in result] == [[], ['us_2y_yield'], ['us_2y_yield'], []]
    assert [r['missing_required_count'] for r in result] == [1, 0, 0, 1]
    # Compare the optimized timeline to the existing audited public as-of path.
    for row, cutoff in zip(result, cutoffs):
        reference = attach_historical_macro({**template, 'decision_cutoff': cutoff}, records)
        assert row['missing_required'] == reference['input_coverage']['missing_required']


def test_coverage_calendar_explicitly_uses_the_new_monthly_input_contract():
    from ai_shadow.historical_coverage import macro_coverage_calendar
    template = {'external': {'macro': {'pce': {'value': None, 'status': 'MISSING'}}},
                'input_coverage': {'status': 'INSUFFICIENT', 'missing_required': ['macro.pce']}}
    records = [{'field': 'macro.pce', 'observation_time': '2019-11-01T00:00:00Z',
                'available_at': '2019-12-22T00:00:00Z', 'value': 110, 'pit_status': 'VINTAGE_VERIFIED'}]
    cutoffs = ['2020-01-15T00:00:00Z', '2020-02-15T00:00:00Z']
    actual = macro_coverage_calendar(template, records, cutoffs, monthly_publication_freshness=True)
    assert [r['input_coverage'] for r in actual] == ['PASS', 'INSUFFICIENT']
    for row, cutoff in zip(actual, cutoffs):
        reference = attach_historical_macro({**template, 'decision_cutoff': cutoff}, records,
                                             monthly_publication_freshness=True)
        assert row['missing_required'] == reference['input_coverage']['missing_required']
