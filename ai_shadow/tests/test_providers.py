from datetime import datetime, timezone, timedelta

from ai_shadow.providers.base import ExternalProvider, collect_providers, evidence


def test_one_provider_failure_is_not_global_failure():
    class Broken(ExternalProvider):
        category = 'etf_flow'
        def fetch(self):
            raise RuntimeError('private error must not leak')
    class Good(ExternalProvider):
        category = 'macro'
        def fetch(self):
            now = datetime.now(timezone.utc)
            return {'vix': evidence(20, 'https://fred.stlouisfed.org', now, now, 604800)}
    result = collect_providers([Broken(), Good()])
    assert result['macro']['vix']['status'] == 'PASS'
    assert result['etf_flow']['status'] == 'ERROR'
    assert 'private' not in str(result)


def test_stale_evidence_preserves_provenance():
    now = datetime.now(timezone.utc)
    result = evidence(20, 'source', now-timedelta(days=9), now, 604800)
    assert result['status'] == 'STALE'
    assert result['freshness']['age_seconds'] == 9*86400
