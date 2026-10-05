"""Loopback PKCE OAuth and locked, rotating ChatGPT token lifecycle."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import math
import secrets
import threading
import time
import webbrowser
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit
from uuid import uuid4

from ai_shadow.auth.oidc import OIDCValidator
from ai_shadow.auth.token_store import WindowsTokenStore
from ai_shadow.errors import AIError
from ai_shadow.http import HTTPClient
from ai_shadow.snapshot import utc
from ai_shadow.storage import atomic_text, process_lock

RESOURCE = "https://api.openai.com/v1"
AUTHORIZE = "https://auth.openai.com/api/accounts/authorize"
TOKEN_ENDPOINT = "https://auth.openai.com/api/accounts/oauth/token"
SCOPES = "openid profile email offline_access resource.invoke chatgpt.tokens.use.direct"


@dataclass(repr=False)
class AuthorizationAttempt:
    host_id: str
    redirect_uri: str
    client_id: str = "dynamic_agent_client"
    state: str = field(default_factory=lambda: secrets.token_urlsafe(32))
    nonce: str = field(default_factory=lambda: secrets.token_urlsafe(32))
    verifier: str = field(default_factory=lambda: secrets.token_urlsafe(64))

    def url(self, id_token_hint=None, login_hint=None):
        challenge = base64.urlsafe_b64encode(hashlib.sha256(self.verifier.encode()).digest()).decode().rstrip("=")
        query = {"client_id": self.client_id, "ext_agent_host_id": self.host_id,
                 "response_type": "code", "redirect_uri": self.redirect_uri,
                 "scope": SCOPES, "resource": RESOURCE, "state": self.state,
                 "nonce": self.nonce, "code_challenge_method": "S256", "code_challenge": challenge}
        if self.client_id == "dynamic_agent_client":
            query["agent_name_hint"] = "Crypto Forward Monitor"
        if id_token_hint:
            query["id_token_hint"] = id_token_hint
        if login_hint:
            query["login_hint"] = login_hint
        return AUTHORIZE + "?" + urlencode(query)

    def callback(self, parameters):
        if not hmac.compare_digest(str(parameters.get("state", "")), self.state):
            raise AIError("OAUTH_STATE_INVALID")
        if parameters.get("error"):
            raise AIError("OAUTH_ACCESS_DENIED")
        issued = parameters.get("client_id", "")
        if self.client_id == "dynamic_agent_client":
            if not issued or issued == "dynamic_agent_client":
                raise AIError("OAUTH_REGISTRATION_INCOMPLETE")
        elif issued and issued != self.client_id:
            raise AIError("OAUTH_CLIENT_MISMATCH")
        if not parameters.get("code"):
            raise AIError("OAUTH_CODE_MISSING")
        return issued or self.client_id, parameters["code"]


class ChatGPTAuth:
    def __init__(self, root: Path, *, vault=None, http=None, validator=None, clock=None, browser=None):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.vault = vault  # Lazy: no vault access or network on read-only refresh.
        self.http = http or HTTPClient()
        self.validator = validator or OIDCValidator(self.http)
        self.clock = clock or time.time
        self.browser = browser or webbrowser.open
        self.metadata_path = self.root / "accounts.json"
        with process_lock(self.root / "accounts.lock"):
            if not self.metadata_path.exists():
                self.save_metadata({"host_id": "urn:uuid:" + str(uuid4()), "accounts": {}, "active": None})

    def token_store(self):
        if self.vault is None:
            self.vault = WindowsTokenStore()
        return self.vault

    def metadata(self):
        return json.loads(self.metadata_path.read_text(encoding="utf-8"))

    def save_metadata(self, metadata):
        atomic_text(self.metadata_path, json.dumps(metadata, ensure_ascii=False, indent=2))

    def active_account(self):
        metadata = self.metadata()
        return metadata["accounts"].get(metadata.get("active"))

    def select(self, registration):
        with process_lock(self.root / "accounts.lock"):
            metadata = self.metadata()
            if registration not in metadata["accounts"]:
                raise AIError("AUTH_REQUIRED")
            metadata["active"] = registration
            self.save_metadata(metadata)

    def _bundle(self, response, client, identity, old=None):
        old = old or {}
        if not response.get("access_token") or not response.get("refresh_token"):
            raise AIError("OAUTH_TOKEN_RESPONSE_INVALID")
        lifetime = response.get("expires_in")
        if not isinstance(lifetime, (int, float)) or not math.isfinite(lifetime) or lifetime <= 0:
            raise AIError("OAUTH_TOKEN_RESPONSE_INVALID")
        earliest = response.get("earliest_refresh_at", 0)
        if isinstance(earliest, str):
            earliest = utc(earliest).timestamp()
        if not isinstance(earliest, (int, float)) or not math.isfinite(earliest) or earliest < 0:
            raise AIError('OAUTH_TOKEN_RESPONSE_INVALID')
        return {"client_id": client, "subject": identity["sub"],
                "access_token": response["access_token"], "refresh_token": response["refresh_token"],
                "id_token": response.get("id_token", old.get("id_token")),
                "scopes": response["scope"].split() if "scope" in response else old.get("scopes", []),
                "expires_at": self.clock() + lifetime, "earliest_refresh_at": earliest}

    def complete(self, attempt, parameters, registration=None):
        client, code = attempt.callback(parameters)
        selected = self.metadata()["accounts"].get(registration) if registration else None
        # Retain the issued ID even if this short-lived code exchange fails.
        with process_lock(self.root / "accounts.lock"):
            metadata = self.metadata()
            metadata["pending_client_id"] = client
            self.save_metadata(metadata)
        response = self.http.request(TOKEN_ENDPOINT, method="POST", form=True, data={
            "grant_type": "authorization_code", "client_id": client, "code": code,
            "code_verifier": attempt.verifier, "redirect_uri": attempt.redirect_uri, "resource": RESOURCE})
        if not response.get("id_token"):
            raise AIError("ID_TOKEN_VALIDATION_FAILED")
        identity = self.validator.validate(response["id_token"], client, attempt.nonce,
                                           selected["subject"] if selected else None)
        registration = registration or hashlib.sha256((client + "|" + identity["sub"]).encode()).hexdigest()
        bundle = self._bundle(response, client, identity)
        with process_lock(self.root / (registration + ".lock")):
            self.token_store().replace(registration, bundle)
        account = {"registration": registration, "client_id": client, "subject": identity["sub"],
                   "email": identity.get("email", ""), "plan_authorized": "chatgpt.tokens.use.direct" in bundle["scopes"]}
        with process_lock(self.root / "accounts.lock"):
            metadata = self.metadata()
            metadata["accounts"][registration] = account
            metadata["active"] = registration
            metadata.pop("pending_client_id", None)
            self.save_metadata(metadata)
        return account

    def sign_in(self, registration=None, timeout=180):
        metadata = self.metadata()
        selected = metadata["accounts"].get(registration) if registration else None
        result, done = {}, threading.Event()
        attempt = None

        class CallbackHandler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass  # Authorization URLs and codes must never enter logs.

            def do_GET(handler):
                if urlsplit(handler.path).path != "/auth/callback":
                    handler.send_error(404)
                    return
                if done.is_set():
                    handler.send_error(409)
                    return
                try:
                    query = parse_qs(urlsplit(handler.path).query)
                    if any(len(v) != 1 for v in query.values()):
                        raise AIError("OAUTH_CALLBACK_INVALID")
                    result["parameters"] = {k: v[0] for k, v in query.items()}
                    attempt.callback(result["parameters"])
                except AIError as exc:
                    result["error"] = exc
                handler.send_response(200)
                handler.send_header("Content-Type", "text/html; charset=utf-8")
                handler.end_headers()
                handler.wfile.write("<p>Authorization received. Return to Crypto Forward Monitor.</p>".encode())
                done.set()

        server = HTTPServer(("127.0.0.1", 0), CallbackHandler)
        callback = f"http://127.0.0.1:{server.server_port}/auth/callback"
        attempt = AuthorizationAttempt(metadata["host_id"], callback,
            selected["client_id"] if selected else metadata.get("pending_client_id", "dynamic_agent_client"))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()  # Listener is live before the system browser opens.
        try:
            previous = self.token_store().load(registration) if registration else None
            self.browser(attempt.url(previous.get("id_token") if previous else None,
                                     selected.get("email") if selected else None))
            if not done.wait(timeout):
                raise AIError("OAUTH_TIMEOUT")
            if "error" in result:
                raise result["error"]
            return self.complete(attempt, result["parameters"], registration)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
            result.clear()  # Drop callback code and PKCE material after the attempt.

    def access_token(self, registration=None):
        account = self.active_account() if registration is None else self.metadata()["accounts"].get(registration)
        if not account:
            raise AIError("AUTH_REQUIRED")
        registration = account["registration"]
        with process_lock(self.root / (registration + ".lock")):
            bundle = self.token_store().load(registration)
            if not bundle:
                raise AIError("AUTH_REQUIRED")
            if bundle["client_id"] != account["client_id"] or bundle["subject"] != account["subject"]:
                raise AIError("OAUTH_REGISTRATION_MISMATCH")
            if "chatgpt.tokens.use.direct" not in bundle["scopes"]:
                raise AIError("PLAN_USAGE_NOT_AUTHORIZED")
            now = self.clock()
            if now >= bundle["expires_at"] - 60 and now >= bundle["earliest_refresh_at"]:
                response = self.http.request(TOKEN_ENDPOINT, method="POST", form=True, data={
                    "grant_type": "refresh_token", "client_id": account["client_id"],
                    "refresh_token": bundle["refresh_token"], "resource": RESOURCE})
                identity = {"sub": account["subject"]}
                if response.get("id_token"):
                    identity = self.validator.validate(response["id_token"], account["client_id"], subject=account["subject"])
                bundle = self._bundle(response, account["client_id"], identity, bundle)
                self.token_store().replace(registration, bundle)
            if now >= bundle["expires_at"]:
                raise AIError("TOKEN_EXPIRED")
            if "chatgpt.tokens.use.direct" not in bundle["scopes"]:
                raise AIError("PLAN_USAGE_NOT_AUTHORIZED")
            return bundle["access_token"]

    def logout(self, registration=None):
        account = self.active_account() if registration is None else self.metadata()["accounts"].get(registration)
        if not account:
            return True
        confirmed = False
        with process_lock(self.root / (account["registration"] + ".lock")):
            bundle = self.token_store().load(account["registration"])
            if bundle:
                for attempt_number in range(2):
                    try:
                        endpoint = self.validator.metadata()["revocation_endpoint"]
                        self.http.request(endpoint, method="POST", form=True, data={"token": bundle["refresh_token"],
                                          "token_type_hint": "refresh_token", "client_id": account["client_id"]})
                        confirmed = True
                        break
                    except AIError:
                        if attempt_number == 0:
                            time.sleep(0.2)
                self.token_store().clear(account["registration"])
        with process_lock(self.root / "accounts.lock"):
            metadata = self.metadata()
            metadata["accounts"][account["registration"]]["plan_authorized"] = False
            self.save_metadata(metadata)
        return confirmed
