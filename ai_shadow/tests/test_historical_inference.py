"""Historical GPT connection diagnostics through the HTTP/SSE boundary."""
import io
import json
import pytest

from ai_shadow.clients.chatgpt_plan import ChatGPTPlanClient
from ai_shadow.snapshot import canonical_hash


class TestAuth:
    def access_token(self):
        return 'test-only-credential'


class CompletedHTTP:
    def __init__(self, decision):
        self.decision = decision
        self.requests = []

    def request(self, url, **kwargs):
        self.requests.append((url, kwargs))
        event = {'type': 'response.completed', 'response': {
            'id': 'test-response-1', 'status': 'completed', 'output': [
                {'type': 'message', 'content': [
                    {'type': 'output_text', 'text': json.dumps(self.decision)}]}]}}
        return io.BytesIO(('data: '+json.dumps(event)+'\n\n').encode())


def snapshot():
    payload = {
        'mode': 'HISTORICAL_FIRST_DECISION_PREFLIGHT_NOT_PERFORMANCE_BACKTEST',
        'decision_cutoff': '2020-01-01T00:00:00+00:00',
        'input_coverage': {'status': 'INSUFFICIENT', 'missing_required': ['macro.dxy']},
        'portfolio': {'btc_weight': .4375, 'eth_weight': .2625, 'cash_weight': .3},
    }
    return {**payload, 'snapshot_hash': canonical_hash(payload)}


def decision():
    return {
        'action': 'ADD', 'confidence': None, 'market_health': None,
        'bull_probability': None, 'base_probability': None, 'bear_probability': None,
        'target_total_exposure': .9, 'target_btc_weight': .6,
        'target_eth_weight': .3, 'target_cash_weight': .1,
        'thesis': ['測試用，不是真實模型輸出'], 'key_positive_factors': [],
        'key_risks': ['資料缺漏'], 'invalidation_conditions': [],
        'data_quality': 'POOR', 'missing_inputs': ['macro.dxy'],
    }


def test_completed_diagnostic_is_not_a_backtest_and_cannot_trade_on_missing_data():
    from ai_shadow.historical_inference import run_first_decision
    http = CompletedHTTP(decision())
    result = run_first_decision(ChatGPTPlanClient(TestAuth(), http), snapshot())
    assert result['response_completed'] is True
    assert result['response_id'] == 'test-response-1'
    assert result['requested_decision']['action'] == 'ADD'
    assert result['effective_decision']['action'] == 'HOLD'
    assert result['effective_decision']['target_btc_weight'] == .4375
    assert result['performance_metrics'] is None
    assert result['trades_executed'] == 0
    request = http.requests[0][1]['data']
    assert request['model'] == 'gpt-5.6-sol'
    assert request['store'] is False
    assert request['stream'] is True
    assert 'tools' not in request
    assert 'previous_response_id' not in request


def test_future_evidence_is_rejected_before_any_http_request():
    from ai_shadow.historical_inference import run_first_decision
    future = snapshot()
    future['external'] = {'available_at': '2020-01-02T00:00:00Z', 'value': 1}
    future['snapshot_hash'] = canonical_hash({k: v for k, v in future.items() if k != 'snapshot_hash'})
    http = CompletedHTTP(decision())
    with pytest.raises(ValueError, match='FUTURE_EVIDENCE'):
        run_first_decision(ChatGPTPlanClient(TestAuth(), http), future)
    assert http.requests == []


def test_modified_snapshot_is_rejected_before_any_http_request():
    from ai_shadow.historical_inference import run_first_decision
    modified = snapshot()
    modified['portfolio']['btc_weight'] = .5
    http = CompletedHTTP(decision())
    with pytest.raises(ValueError, match='HISTORICAL_SNAPSHOT_HASH_MISMATCH'):
        run_first_decision(ChatGPTPlanClient(TestAuth(), http), modified)
    assert http.requests == []
