"""Bounded HTTPS transport; failures expose safe codes, never credential bodies."""
import json
import urllib.error
import urllib.parse
import urllib.request

from ai_shadow.errors import AIError

ERROR_CODES = {
    "subscription_sharing_user_not_eligible": "USER_NOT_ELIGIBLE",
    "subscription_sharing_usage_limit_exceeded": "USAGE_LIMIT_EXCEEDED",
    "subscription_sharing_usage_unavailable": "USAGE_UNAVAILABLE",
    "invalid_grant": "REAUTH_REQUIRED",
    "model_not_found": "MODEL_NOT_AVAILABLE",
}


def api_error(status, payload, request_id=None):
    error = payload.get("error", {}) if isinstance(payload, dict) else {}
    code = error.get("code") if isinstance(error, dict) else error
    mapped = ERROR_CODES.get(code, "AUTH_REQUIRED" if status == 401 else "PLAN_USAGE_NOT_AUTHORIZED" if status == 403 else "USAGE_LIMIT_EXCEEDED" if status == 429 else "GPT_FAILED")
    # detail strings and unknown error text are never forwarded to journal/UI.
    return AIError(mapped, http_status=status, request_id=request_id)


class HTTPClient:
    def __init__(self, timeout=10, opener=None):
        self.timeout = timeout
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                raise AIError('UNEXPECTED_AUTH_REDIRECT')
        self.opener = opener or urllib.request.build_opener(NoRedirect()).open

    def request(self, url, *, method="GET", data=None, token=None, form=False, stream=False):
        headers = {"Accept": "text/event-stream" if stream else "application/json",
                   "User-Agent": "CryptoForwardMonitor-AIShadow/1"}
        encoded = None
        if data is not None:
            encoded = (urllib.parse.urlencode(data).encode() if form else json.dumps(data, allow_nan=False).encode())
            headers["Content-Type"] = "application/x-www-form-urlencoded" if form else "application/json"
        if token:
            headers["Authorization"] = "Bearer " + token
        request = urllib.request.Request(url, data=encoded, method=method, headers=headers)
        try:
            response = self.opener(request, timeout=self.timeout)
            if stream:
                return response
            with response:
                body = response.read(10_000_001)
                if len(body) > 10_000_000:
                    raise AIError("RESPONSE_TOO_LARGE")
                return json.loads(body) if body else {}
        except urllib.error.HTTPError as exc:
            try:
                payload = json.loads(exc.read(32768))
            except Exception:
                payload = {}
            raise api_error(exc.code, payload, exc.headers.get("x-request-id")) from None
        except AIError:
            raise
        except Exception:
            raise AIError("NETWORK_UNAVAILABLE") from None
