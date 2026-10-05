import io
import json
import pytest

from ai_shadow.clients.chatgpt_plan import ChatGPTPlanClient
from ai_shadow.errors import AIError


class Auth:
    def access_token(self):
        return "test-credential-never-real"


class HTTP:
    def __init__(self, events):
        self.events = events
        self.requests = []

    def request(self, url, **kwargs):
        self.requests.append((url, kwargs))
        return io.BytesIO(b"".join(b"data: " + json.dumps(event).encode() + b"\n\n" for event in self.events))


def test_stream_requires_response_completed():
    client = ChatGPTPlanClient(Auth(), HTTP([{"type": "response.output_text.delta", "delta": "{}"}]))
    with pytest.raises(AIError, match="STREAM_INTERRUPTED"):
        client.stream({"model": "mock", "input": [], "store": False, "stream": True})


def test_response_failed_no_trade():
    client = ChatGPTPlanClient(Auth(), HTTP([{"type": "response.failed", "response": {"error": {"code": "subscription_sharing_usage_limit_exceeded"}}}]))
    with pytest.raises(AIError, match="USAGE_LIMIT_EXCEEDED"):
        client.stream({"model": "mock", "input": [], "store": False, "stream": True})
