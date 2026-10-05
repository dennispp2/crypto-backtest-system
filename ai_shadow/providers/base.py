from __future__ import annotations

import json
import math
from concurrent.futures import ThreadPoolExecutor
from urllib.request import Request, urlopen

from ai_shadow.snapshot import utc


class ExternalProvider:
    category: str

    def fetch(self):
        raise NotImplementedError


def public_get(url, *, as_json=True):
    # Public GET only; never attaches a token/cookie. Each response is bounded.
    with urlopen(Request(url, headers={'User-Agent': 'CryptoForwardMonitor/AI_SHADOW_V1'}), timeout=10) as response:
        raw = response.read(8_000_001)
    if len(raw) > 8_000_000:
        raise ValueError('PROVIDER_RESPONSE_TOO_LARGE')
    return json.loads(raw) if as_json else raw.decode('utf-8-sig')


def missing(source, *, status='MISSING', reason='Public source unavailable'):
    return {'value': None, 'source': source, 'source_timestamp': None, 'fetched_at': utc().isoformat(),
            'freshness': {'age_seconds': None, 'max_age_seconds': None}, 'status': status, 'reason': reason}


def evidence(value, source, source_time, fetched_at, max_age_seconds, **extra):
    age = (utc(fetched_at)-utc(source_time)).total_seconds()
    if age < 0:
        raise ValueError('PROVIDER_FUTURE_EVIDENCE')
    if isinstance(value, (float, int)) and not math.isfinite(value):
        raise ValueError('PROVIDER_INVALID_VALUE')
    return {'value': value, 'source': source, 'source_timestamp': utc(source_time).isoformat(),
            'fetched_at': utc(fetched_at).isoformat(),
            'freshness': {'age_seconds': age, 'max_age_seconds': max_age_seconds},
            'status': 'PASS' if age <= max_age_seconds else 'STALE', **extra}


class MissingProvider(ExternalProvider):
    def __init__(self, category, reason):
        self.category, self.reason = category, reason

    def fetch(self):
        return missing(self.category, reason=self.reason)


def collect_providers(providers):
    def safe(provider):
        try:
            return provider.category, provider.fetch()
        except Exception:
            return provider.category, missing(provider.category, status='ERROR', reason='PROVIDER_FETCH_FAILED')
    with ThreadPoolExecutor(max_workers=4) as pool:
        return dict(pool.map(safe, providers))
