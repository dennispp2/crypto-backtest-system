"""Forward-only FRED retrieval; observation dates are NOT release dates.

Current revised data may be used only at this retrieval time. No historical
point-in-time claim, nor synthetic market-calendar freshness, is made.
"""
from __future__ import annotations

import csv
import io
from datetime import datetime, timezone

from ai_shadow.providers.base import ExternalProvider, evidence, missing, public_get
from ai_shadow.snapshot import utc


class FredProvider(ExternalProvider):
    category = 'macro'
    SERIES = {'broad_usd_proxy_not_ice_dxy': ('DTWEXBGS', 7), 'us_2y_yield': ('DGS2', 7),
              'us_10y_yield': ('DGS10', 7), 'vix': ('VIXCLS', 7),
              'sp500_proxy_not_spy': ('SP500', 7), 'nasdaq_composite_proxy_not_qqq': ('NASDAQCOM', 7),
              'gold': ('GOLDAMGBD228NLBM', 7), 'wti': ('DCOILWTICO', 7),
              'fed_funds': ('DFF', 7), 'cpi': ('CPIAUCSL', 65), 'pce': ('PCEPI', 65),
              'nonfarm_payrolls': ('PAYEMS', 65), 'unemployment': ('UNRATE', 65)}

    def __init__(self, getter=public_get, clock=utc, max_age_overrides=None):
        self.get, self.clock, self.overrides = getter, clock, max_age_overrides or {}

    def fetch(self):
        result = {}
        for name, (series, days) in self.SERIES.items():
            url = 'https://fred.stlouisfed.org/graph/?g=chart&cosd=2025-01-01'  # Provenance landing graph below.
            url = 'https://fred.stlouisfed.org/graph/fredgraph.csv?id='+series
            try:
                rows = list(csv.DictReader(io.StringIO(self.get(url, as_json=False))))
                fetched = self.clock()
                usable = [r for r in rows if r.get(series) not in {None, '.', ''} and
                          datetime.fromisoformat(next(iter(r.values()))).replace(tzinfo=timezone.utc) <= fetched]
                row = usable[-1]
                observed = datetime.fromisoformat(next(iter(row.values()))).replace(tzinfo=timezone.utc)
                observation_age = (fetched-observed).total_seconds()
                maximum = self.overrides.get(name, days*86400)
                item = evidence(float(row[series]), url, fetched, fetched, maximum,
                                observation_date=observed.date().isoformat(), observation_age_seconds=observation_age,
                                timestamp_basis='available_at_retrieval_release_date_unknown', release_timestamp=None)
                if observation_age > maximum:
                    item['status'] = 'STALE'
                result[name] = item
            except Exception:
                result[name] = missing(url, status='ERROR', reason='PUBLIC_FRED_UNAVAILABLE')
        return result
