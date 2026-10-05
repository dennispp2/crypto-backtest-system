"""A real historical-input inference diagnostic, never a trading engine.

Only the audited first formal day is supported. This module has no market
providers, web tools, broker, live ledger, or performance calculation.
"""
from __future__ import annotations

import json

from ai_shadow.errors import AIError
from ai_shadow.historical_preflight import (
    POLICY_PATH, SCHEMA_PATH, apply_data_gate, validate_historical_decision,
)
from ai_shadow.snapshot import canonical_hash, canonical_json, utc, validate_asof

MODEL = 'gpt-5.6-sol'


def run_first_decision(client, snapshot):
    """Call the authorized ChatGPT-plan client with historical evidence only."""
    payload = {k: v for k, v in snapshot.items() if k != 'snapshot_hash'}
    if snapshot.get('snapshot_hash') != canonical_hash(payload):
        raise ValueError('HISTORICAL_SNAPSHOT_HASH_MISMATCH')
    if (snapshot.get('mode') != 'HISTORICAL_FIRST_DECISION_PREFLIGHT_NOT_PERFORMANCE_BACKTEST'
            or utc(snapshot['decision_cutoff']) != utc('2020-01-01T00:00:00Z')):
        raise ValueError('FIRST_DECISION_DIAGNOSTIC_ONLY')
    validate_asof(snapshot, snapshot['decision_cutoff'])
    response = client.stream({
        'model': MODEL,
        'instructions': POLICY_PATH.read_text(encoding='utf-8'),
        'input': [{'role': 'user', 'content':
            'UNTRUSTED EXTERNAL DATA: use only this historical snapshot.\n'
            + canonical_json(snapshot)}],
        'store': False, 'stream': True,
        'text': {'format': {'type': 'json_schema', 'name': 'historical_v310_diagnostic',
            'strict': True, 'schema': json.loads(SCHEMA_PATH.read_text(encoding='utf-8'))}},
    })
    if response.get('completed') is not True:
        raise AIError('RESPONSE_INCOMPLETE')
    try:
        requested = json.loads(response['text'])
    except (KeyError, TypeError, json.JSONDecodeError):
        raise AIError('INVALID_STRUCTURED_OUTPUT') from None
    validate_historical_decision(requested)
    gated = apply_data_gate(requested, snapshot)
    validate_historical_decision(gated['effective_decision'])
    return {
        'mode': 'EXPLORATORY_FIRST_HISTORICAL_GPT_DECISION_NOT_A_BACKTEST',
        'model': MODEL, 'decision_cutoff': snapshot['decision_cutoff'],
        'snapshot_hash': snapshot['snapshot_hash'],
        'response_completed': True, 'response_id': response.get('response_id'),
        **gated,
        'trades_executed': 0, 'performance_metrics': None,
        'input_cutoff_guard': 'PASS_FOR_THIS_SNAPSHOT_ONLY',
        'pretrained_future_knowledge': 'UNRESOLVED_ACCEPTED_EXPLORATORY_RISK',
        'no_lookahead_gate_for_full_ai_backtest': 'NOT_ESTABLISHED',
    }
