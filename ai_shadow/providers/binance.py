from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import urlencode

from ai_shadow.providers.base import ExternalProvider, evidence, missing, public_get
from ai_shadow.snapshot import utc
from ai_shadow.technical import indicators, relative_strength

SPOT = 'https://api.binance.com'
FUTURES = 'https://fapi.binance.com'


def ms_time(value):
    return datetime.fromtimestamp(int(value)/1000, timezone.utc)


class BinanceSpotProvider:
    def __init__(self, getter=public_get, clock=utc):
        self.get, self.clock = getter, clock

    def quotes(self):
        quotes = {}
        for asset in ('BTC', 'ETH'):
            url = SPOT + '/api/v3/ticker/bookTicker?' + urlencode({'symbol': asset+'USDT'})
            started = self.clock()
            row = self.get(url)
            fetched = self.clock()
            quotes[asset] = {'bid': float(row['bidPrice']), 'ask': float(row['askPrice']),
                             'requested_at': started.isoformat(), 'quote_time': fetched.isoformat(),
                             'timestamp_basis': 'local_retrieval_no_exchange_timestamp', 'source': url}
        return quotes

    def technical(self):
        cutoff = min(ms_time(self.get(SPOT+'/api/v3/time')['serverTime']), self.clock())
        result = {}
        for asset in ('BTC', 'ETH'):
            url = SPOT + '/api/v3/klines?' + urlencode({'symbol': asset+'USDT', 'interval': '1d', 'limit': 400,
                                                       'endTime': int(cutoff.timestamp()*1000)})
            rows = self.get(url)
            value = indicators(rows, cutoff)
            fetched = self.clock()
            value.update({'source': url, 'source_timestamp': value['indicator_asof'], 'fetched_at': fetched.isoformat(),
                          'status': 'PASS' if (fetched-utc(value['indicator_asof'])).total_seconds() <= 36*3600 else 'STALE'})
            result[asset] = value
        result['relative_strength'] = relative_strength(result['BTC'], result['ETH'])
        quotes = self.quotes()
        for asset in ('BTC', 'ETH'):
            quote = quotes[asset]
            result[asset].update({'spot_now': (quote['bid']+quote['ask'])/2, 'spot_asof': quote['quote_time'],
                                 'spot_source': quote['source']})
        return result


class BinanceDerivativesProvider(ExternalProvider):
    category = 'derivatives'

    def __init__(self, getter=public_get, clock=utc, max_age_seconds=12*3600):
        self.get, self.clock, self.max_age = getter, clock, max_age_seconds

    def fetch(self):
        result = {}
        endpoints = {
            'funding': ('/fapi/v1/fundingRate', {'limit': 10}, 'fundingTime', 'fundingRate'),
            'open_interest': ('/futures/data/openInterestHist', {'period': '4h', 'limit': 8}, 'timestamp', 'sumOpenInterestValue'),
            'long_short_ratio': ('/futures/data/globalLongShortAccountRatio', {'period': '4h', 'limit': 8}, 'timestamp', 'longShortRatio'),
            'taker_buy_sell': ('/futures/data/takerlongshortRatio', {'period': '4h', 'limit': 8}, 'timestamp', 'buySellRatio'),
            'basis': ('/futures/data/basis', {'period': '4h', 'limit': 8, 'contractType': 'PERPETUAL'}, 'timestamp', 'basisRate'),
        }
        for asset in ('BTC', 'ETH'):
            result[asset] = {}
            for name, (path, params, time_key, value_key) in endpoints.items():
                params = {**params, 'pair' if name == 'basis' else 'symbol': asset+'USDT'}
                url = FUTURES + path+'?'+urlencode(params)
                try:
                    rows = self.get(url)
                    fetched = self.clock()
                    # Start-labelled aggregated endpoints need their full period to finish.
                    delay = 4*3600 if name in {'basis', 'taker_buy_sell'} else 0
                    usable = [r for r in rows if int(r[time_key])/1000+delay <= fetched.timestamp()]
                    row = max(usable, key=lambda r: int(r[time_key]))
                    val = float(row[value_key])
                    item = evidence(val, url, ms_time(int(row[time_key])+delay*1000), fetched, self.max_age)
                    if name == 'open_interest' and len(usable) > 1:
                        old = sorted(usable, key=lambda r: int(r[time_key]))[0]
                        item['change_over_available_window'] = val/float(old[value_key])-1
                    result[asset][name] = item
                except Exception:
                    result[asset][name] = missing(url, status='ERROR', reason='PUBLIC_DERIVATIVES_UNAVAILABLE')
            result[asset]['liquidations'] = missing('Binance', reason='No complete public historical liquidation aggregate')
        return result
