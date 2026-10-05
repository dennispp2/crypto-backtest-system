import hashlib
import base64
from urllib.parse import parse_qs, urlsplit
import pytest

from ai_shadow.auth.chatgpt_auth import AuthorizationAttempt
from ai_shadow.errors import AIError


def test_oauth_pkce():
    attempt = AuthorizationAttempt("urn:uuid:test", "http://127.0.0.1:8888/auth/callback")
    params = parse_qs(urlsplit(attempt.url()).query)
    expected = base64.urlsafe_b64encode(hashlib.sha256(attempt.verifier.encode()).digest()).decode().rstrip("=")
    assert params["code_challenge"] == [expected]
    assert params["code_challenge_method"] == ["S256"]
    assert params["client_id"] == ["dynamic_agent_client"]


def test_oauth_state_validation():
    attempt = AuthorizationAttempt("urn:uuid:test", "http://127.0.0.1:8888/auth/callback")
    with pytest.raises(AIError, match="OAUTH_STATE_INVALID"):
        attempt.callback({"state": "wrong", "code": "not-a-real-code", "client_id": "oaiapp_test"})
