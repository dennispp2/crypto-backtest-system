from ai_shadow.providers.base import ExternalProvider, evidence, missing, public_get
from ai_shadow.snapshot import utc


class StablecoinProvider(ExternalProvider):
    category = 'liquidity'
    URL = 'https://stablecoins.llama.fi/stablecoincharts/all'

    def __init__(self, getter=public_get, clock=utc, max_age_seconds=72*3600):
        self.get, self.clock, self.max_age = getter, clock, max_age_seconds

    def fetch(self):
        from ai_shadow.providers.binance import ms_time
        rows = self.get(self.URL)
        fetched = self.clock()
        rows = [r for r in rows if int(r['date']) <= fetched.timestamp()]
        latest = rows[-1]
        value = sum(float(v) for v in latest['totalCirculatingUSD'].values())
        result = {'stablecoin_supply_usd': evidence(value, self.URL, ms_time(int(latest['date'])*1000), fetched, self.max_age)}
        for days in (7, 30):
            old = [r for r in rows if int(r['date']) <= int(latest['date'])-days*86400]
            if old:
                total = sum(float(v) for v in old[-1]['totalCirculatingUSD'].values())
                result['stablecoin_supply_usd'][f'change_{days}d'] = value/total-1 if total else None
        result['exchange_flows'] = missing('onchain', reason='No reliable public complete exchange-flow feed configured')
        return result
