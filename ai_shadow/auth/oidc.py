import hmac
from urllib.parse import urlsplit

import jwt

from ai_shadow.errors import AIError
from ai_shadow.http import HTTPClient

DISCOVERY = "https://auth.openai.com/.well-known/openid-configuration"


class OIDCValidator:
    def __init__(self, http=None, key_resolver=None):
        self.http = http or HTTPClient()
        self.key_resolver = key_resolver

    def metadata(self):
        metadata = self.http.request(DISCOVERY)
        if metadata.get("issuer") != "https://auth.openai.com":
            raise AIError("OIDC_ISSUER_INVALID")
        for key in ("jwks_uri", "revocation_endpoint"):
            url = urlsplit(metadata.get(key, ""))
            if url.scheme != "https" or url.hostname != "auth.openai.com":
                raise AIError("OIDC_ENDPOINT_INVALID")
        return metadata

    def validate(self, token, client_id, nonce=None, subject=None):
        try:
            metadata = self.metadata()
            key = (self.key_resolver(token) if self.key_resolver else
                   jwt.PyJWKClient(metadata["jwks_uri"], timeout=10).get_signing_key_from_jwt(token).key)
            identity = jwt.decode(token, key, algorithms=["RS256", "ES256"],
                                  audience=client_id, issuer=metadata["issuer"],
                                  options={"require": ["exp", "iss", "aud", "sub"]})
            if nonce is not None and not hmac.compare_digest(str(identity.get("nonce", "")), nonce):
                raise AIError("OAUTH_NONCE_INVALID")
            if subject and identity["sub"] != subject:
                raise AIError("OAUTH_SUBJECT_MISMATCH")
            return identity
        except AIError:
            raise
        except Exception:
            raise AIError("ID_TOKEN_VALIDATION_FAILED") from None
