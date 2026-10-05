"""Chronological macro coverage audit; no inference or strategy evaluation."""
from __future__ import annotations

from copy import deepcopy

from ai_shadow.historical_sources import attach_historical_macro, iso, timestamp


def macro_coverage_calendar(template, records, cutoffs, *, monthly_publication_freshness=False):
    """Advance available revisions in time without scanning the full archive daily."""
    times = [timestamp(c) for c in cutoffs]
    if any(left >= right for left, right in zip(times, times[1:])):
        raise ValueError('COVERAGE_CUTOFFS_MUST_INCREASE')
    timeline = []
    duplicates = {}
    for record in records:
        if (record.get('pit_status') not in {'VINTAGE_VERIFIED', 'PUBLICATION_VERIFIED'}
                or not record.get('available_at')):
            continue
        available, observed = timestamp(record['available_at']), timestamp(record['observation_time'])
        key = (record['field'], observed, available)
        if key in duplicates and duplicates[key] != record['value']:
            raise ValueError('CONFLICTING_ASOF_VALUE')
        duplicates[key] = record['value']
        timeline.append((max(available, observed), observed, available, record))
    timeline.sort(key=lambda item: (item[0], item[1], item[2], item[3]['field']))
    cursor, latest = 0, {}
    result = []
    for cutoff in times:
        while cursor < len(timeline) and timeline[cursor][0] <= cutoff:
            _, observed, available, record = timeline[cursor]
            previous = latest.get(record['field'])
            if previous is None or (observed, available) > (
                    timestamp(previous['observation_time']), timestamp(previous['available_at'])):
                latest[record['field']] = record
            cursor += 1
        base = deepcopy(template)
        base['decision_cutoff'] = iso(cutoff)
        attached = attach_historical_macro(base, list(latest.values()),
                                          monthly_publication_freshness=monthly_publication_freshness)
        missing = attached['input_coverage']['missing_required']
        result.append({
            'decision_cutoff': iso(cutoff),
            'available_macro_fields': [k for k, v in attached['external']['macro'].items()
                                       if v['status'] == 'PASS'],
            'missing_required': missing, 'missing_required_count': len(missing),
            'input_coverage': attached['input_coverage']['status'],
        })
    return result
