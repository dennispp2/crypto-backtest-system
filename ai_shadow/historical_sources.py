"""Point-in-time source normalization, isolated from all frozen trading rules.

Observation time is not publication time. Modern downloads with historical
date labels are quarantined unless their vintage or publication is verified.
"""
from __future__ import annotations

import csv
from copy import deepcopy
import io
import math
import re
import zipfile
from datetime import datetime, timedelta, timezone


def timestamp(value):
    result = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    if result.tzinfo is None:
        result = result.replace(tzinfo=timezone.utc)
    return result.astimezone(timezone.utc)


def iso(value):
    return timestamp(value).isoformat().replace('+00:00', 'Z')


def alfred_download_fields(html, start, end):
    """Use the provider's observed form contract and every relevant vintage."""
    vintages = sorted(set(re.findall(r'<option value="(\d{4}-\d{2}-\d{2})"', html)))
    if not vintages:
        raise ValueError('ALFRED_VINTAGE_LIST_MISSING')
    selected = [d for d in vintages if start <= d <= end]
    observed_end = re.search(r'<input[^>]*name="form\[obs_end_date\]"[^>]*value="(\d{4}-\d{2}-\d{2})"', html)
    observation_end = min(end, observed_end.group(1)) if observed_end else end
    return [
        ('form[units]', 'lin'), ('form[obs_start_date]', start),
        ('form[obs_end_date]', observation_end), ('form[entered_vintage_dates]', start+' '+end),
        ('form[file_type]', '1'), ('form[file_format]', 'csv'),
        ('form[download_data]', 'Download data'),
        *[('form[selected_vintage_dates][]', d) for d in selected],
    ]


def alfred_download_batches(html, start, end):
    fields = alfred_download_fields(html, start, end)
    base = [(k, v) for k, v in fields if k != 'form[selected_vintage_dates][]']
    selected = [(k, v) for k, v in fields if k == 'form[selected_vintage_dates][]']
    # Observed official validation: max 450 daily vintages per export. Leave
    # room for the two explicitly entered boundary dates.
    return [base+selected[i:i+440] for i in range(0, max(len(selected), 1), 440)]


def _csv_zip(raw, expected_name=None):
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        names = [n for n in archive.namelist() if n.endswith('.csv')]
        if expected_name is not None:
            names = [n for n in names if n == expected_name]
        if len(names) != 1 or archive.getinfo(names[0]).file_size > 30_000_000:
            raise ValueError('ARCHIVE_SCHEMA_OR_SIZE_INVALID')
        return csv.DictReader(io.StringIO(archive.read(names[0]).decode('utf-8-sig')))


def parse_alfred_zip(raw, series_id, field):
    reader = _csv_zip(raw, 'obs._by_real-time_period.csv')
    required = {'period_start_date', series_id, 'realtime_start_date', 'realtime_end_date'}
    if set(reader.fieldnames or []) != required:
        raise ValueError('ALFRED_SCHEMA_DRIFT')
    records, identities = [], {}
    for row in reader:
        observation = timestamp(row['period_start_date'])
        vintage = timestamp(row['realtime_start_date'])
        if vintage < observation:
            raise ValueError('VINTAGE_BEFORE_OBSERVATION')
        value = None if row[series_id] in {'.', '', 'NA'} else float(row[series_id])
        if value is not None and not math.isfinite(value):
            raise ValueError('NONFINITE_SOURCE_VALUE')
        key = (iso(observation), iso(vintage))
        if key in identities:
            if identities[key] != value:
                raise ValueError('CONFLICTING_VINTAGE')
            continue
        identities[key] = value
        records.append({
            'field': field, 'series_id': series_id, 'observation_time': iso(observation),
            'vintage_date': row['realtime_start_date'],
            # ALFRED supplies a DATE, not an intraday timestamp. Waiting two UTC
            # dates avoids treating 00:00 UTC as the U.S. publication instant.
            'available_at': iso(vintage+timedelta(days=2)),
            'availability_basis': 'ALFRED vintage date + 2 calendar days at 00:00 UTC; conservative lag, not exact release time',
            'publication_timestamp': None, 'value': value,
            'pit_status': 'VINTAGE_VERIFIED',
            'source_url': 'https://alfred.stlouisfed.org/series?seid='+series_id,
        })
        # realtime_end_date intentionally discarded: a later revision's date
        # is not evidence that may be shown at the earlier decision cutoff.
    return sorted(records, key=lambda r: (r['available_at'], r['observation_time']))


def parse_funding_zip(raw, asset):
    reader = _csv_zip(raw)
    if set(reader.fieldnames or []) != {'calc_time', 'funding_interval_hours', 'last_funding_rate'}:
        raise ValueError('FUNDING_SCHEMA_DRIFT')
    records = []
    for row in reader:
        event = datetime.fromtimestamp(int(row['calc_time'])/1000, timezone.utc)
        value = float(row['last_funding_rate'])
        if not math.isfinite(value):
            raise ValueError('NONFINITE_SOURCE_VALUE')
        records.append({
            'field': 'derivatives.'+asset+'.funding', 'observation_time': iso(event),
            'available_at': None, 'value': value,
            'funding_interval_hours': float(row['funding_interval_hours']),
            'pit_status': 'EVENT_TIME_ONLY_REVISION_UNVERIFIED',
            'reason': 'Provider documents possible archive corrections; checksum proves this download, not the original vintage',
        })
    return records


def asof_records(records, cutoff):
    """Return only legally available revisions with a fixed safe projection."""
    cutoff = timestamp(cutoff)
    selected = {}
    for record in records:
        if record.get('pit_status') not in {'VINTAGE_VERIFIED', 'PUBLICATION_VERIFIED'}:
            continue
        if not record.get('available_at'):
            continue
        available = timestamp(record['available_at'])
        observed = timestamp(record['observation_time'])
        if available > cutoff or observed > cutoff:
            continue
        key = (record['field'], iso(observed))
        previous = selected.get(key)
        if previous is None or timestamp(previous['available_at']) < available:
            selected[key] = record
        elif timestamp(previous['available_at']) == available and previous['value'] != record['value']:
            raise ValueError('CONFLICTING_ASOF_VALUE')
    allowed = ('field', 'series_id', 'observation_time', 'vintage_date', 'available_at',
               'availability_basis', 'publication_timestamp', 'value', 'pit_status', 'source_url')
    return [{k: r[k] for k in allowed if k in r}
            for _, r in sorted(selected.items())]


def attach_historical_macro(snapshot, records, *, monthly_publication_freshness=False):
    """Populate verified macro fields without changing legacy experiment inputs.

    Monthly statistical dates label a period, not a release. The explicitly
    versioned limited-data experiment measures freshness from known vintage
    availability, with a separate obsolete-period guard. No future revision
    or publication is usable under either contract.
    """
    from ai_shadow.snapshot import canonical_hash, validate_asof
    result = deepcopy(snapshot)
    result.pop('snapshot_hash', None)
    cutoff = result['decision_cutoff']
    selected = asof_records(records, cutoff)
    latest = {}
    for record in selected:
        previous = latest.get(record['field'])
        if previous is None or timestamp(record['observation_time']) > timestamp(previous['observation_time']):
            latest[record['field']] = record
    macro = result['external']['macro']
    max_age_days = {'cpi': 62, 'pce': 62, 'nonfarm_payrolls': 62}
    for name in macro:
        record = latest.get('macro.'+name)
        if record is None or record['value'] is None:
            continue
        age_days = (timestamp(cutoff)-timestamp(record['observation_time'])).total_seconds()/86400
        publication_age = (timestamp(cutoff)-timestamp(record['available_at'])).total_seconds()/86400
        monthly = name in max_age_days
        if monthly and monthly_publication_freshness:
            stale = publication_age > 45 or age_days > 100
        else:
            stale = age_days > max_age_days.get(name, 7)
        if stale:
            continue
        macro[name] = {**record, 'status': 'PASS', 'required': True,
                       'source_timestamp': record['available_at'], 'observation_age_days': age_days,
                       'units_basis': 'Raw provider level; no unverified surprise or consensus estimate'}
        if monthly and monthly_publication_freshness:
            macro[name].update(publication_age_days=publication_age,
                freshness_basis='Known vintage availability <=45 days; statistical period age <=100 days')
    lower, upper = (latest.get('macro.fed_target_'+side) for side in ('lower', 'upper'))
    if (lower is not None and upper is not None and lower['value'] is not None
            and upper['value'] is not None and lower['value'] <= upper['value']
            and lower['observation_time'] == upper['observation_time']
            and (timestamp(cutoff)-timestamp(lower['observation_time'])).total_seconds() <= 7*86400):
        available = max(lower['available_at'], upper['available_at'])
        macro['fed_rate'] = {'value': {'lower_percent': lower['value'], 'upper_percent': upper['value']},
                             'status': 'PASS', 'required': True, 'source_timestamp': available,
                             'publication_timestamp': None, 'available_at': available,
                             'observation_time': lower['observation_time'],
                             'basis': 'Fed policy target range, not effective overnight DFF',
                             'sources': [lower, upper]}
    missing = [path for path in result['input_coverage']['missing_required']
               if not (path.startswith('macro.') and macro[path.split('.')[1]]['status'] == 'PASS')]
    result['input_coverage']['missing_required'] = missing
    result['input_coverage']['status'] = 'INSUFFICIENT' if missing else 'PASS'
    validate_asof(result, cutoff)
    return {**result, 'snapshot_hash': canonical_hash(result)}
