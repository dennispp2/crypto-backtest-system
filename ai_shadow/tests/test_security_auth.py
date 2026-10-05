import json
import time
from unittest.mock import patch

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from ai_shadow.audit import redact
from ai_shadow.auth.chatgpt_auth import AuthorizationAttempt, ChatGPTAuth
from ai_shadow.auth.oidc import OIDCValidator
from ai_shadow.auth.token_store import MemoryTokenStore, WindowsTokenStore
from ai_shadow.errors import AIError
from ai_shadow.storage import process_lock, ShadowStorage


class FakeHTTP:
    def __init__(self, response=None):
        self.response, self.calls = response, []
    def request(self, url, **kwargs):
        self.calls.append((url,kwargs))
        if 'openid-configuration' in url:
            return {'issuer':'https://auth.openai.com', 'jwks_uri':'https://auth.openai.com/keys',
                    'revocation_endpoint':'https://auth.openai.com/revoke'}
        return self.response or {}


@pytest.fixture
def identity():
    key = rsa.generate_private_key(public_exponent=65537,key_size=2048)
    validator = OIDCValidator(FakeHTTP(),key_resolver=lambda _:key.public_key())
    def token(**changes):
        claims = {'iss':'https://auth.openai.com','aud':'issued-client','sub':'user-1',
                  'nonce':'expected','exp':int(time.time())+60,**changes}
        return jwt.encode(claims,key,algorithm='RS256')
    return validator, token


def test_id_token_signature_validation(identity):
    validator, token = identity
    assert validator.validate(token(),'issued-client','expected')['sub']=='user-1'
    wrong_key = rsa.generate_private_key(public_exponent=65537,key_size=2048)
    with pytest.raises(AIError):
        validator.validate(jwt.encode({'sub':'x'},wrong_key,algorithm='RS256'),'issued-client')


@pytest.mark.parametrize('changes,nonce,subject,code', [({'aud':'wrong'},'expected',None,'ID_TOKEN_VALIDATION_FAILED'),
    ({'exp':0},'expected',None,'ID_TOKEN_VALIDATION_FAILED'), ({'iss':'https://wrong'},'expected',None,'ID_TOKEN_VALIDATION_FAILED'),
    ({},'wrong',None,'OAUTH_NONCE_INVALID'), ({},'expected','wrong','OAUTH_SUBJECT_MISMATCH')])
def test_wrong_identity_rejected(identity,changes,nonce,subject,code):
    validator, token = identity
    with pytest.raises(AIError,match=code):
        validator.validate(token(**changes),'issued-client',nonce,subject)


def configured_auth(tmp_path, **bundle):
    vault = MemoryTokenStore()
    http = FakeHTTP({'access_token':'new-test-only','refresh_token':'rotated-test-only', 'expires_in':1000,
                     'scope':'chatgpt.tokens.use.direct'})
    auth = ChatGPTAuth(tmp_path,vault=vault,http=http,clock=lambda:1000)
    meta = auth.metadata()
    meta.update(active='registration',accounts={'registration':{'client_id':'issued-client','subject':'user-1',
                                                               'registration':'registration','plan_authorized':True}})
    auth.save_metadata(meta)
    vault.replace('registration',{'client_id':'issued-client','subject':'user-1','access_token':'old-test-only',
        'refresh_token':'old-refresh-test-only','expires_at':999,'earliest_refresh_at':0,
        'scopes':['chatgpt.tokens.use.direct'],**bundle})
    return auth,vault,http


def test_missing_direct_scope_disables_ai(tmp_path):
    auth,_,http = configured_auth(tmp_path,scopes=[])
    with pytest.raises(AIError,match='PLAN_USAGE_NOT_AUTHORIZED'):
        auth.access_token()
    assert not http.calls


def test_refresh_rotation_no_scope_resubmission(tmp_path):
    auth,vault,http = configured_auth(tmp_path)
    assert auth.access_token()=='new-test-only'
    assert vault.load('registration')['refresh_token']=='rotated-test-only'
    assert 'scope' not in http.calls[0][1]['data']
    assert auth.access_token()=='new-test-only' and len(http.calls)==1
    assert not any('token' in k for k in json.loads(auth.metadata_path.read_text())['accounts']['registration'])


def test_refresh_lock(tmp_path):
    auth,_,http = configured_auth(tmp_path)
    with process_lock(tmp_path/'registration.lock'):
        with pytest.raises(RuntimeError,match='AI_RUN_IN_PROGRESS'):
            auth.access_token()
    assert not http.calls


def test_earliest_refresh_is_honored(tmp_path):
    auth,_,http = configured_auth(tmp_path,expires_at=1200,earliest_refresh_at=1300)
    assert auth.access_token()=='old-test-only'
    assert not http.calls


def test_logout_revocation(tmp_path):
    auth,vault,http = configured_auth(tmp_path)
    assert auth.logout()
    assert vault.load('registration') is None
    assert any(c[1].get('data',{}).get('token_type_hint')=='refresh_token' for c in http.calls)
    assert not auth.active_account()['plan_authorized']


def test_account_bundle_mismatch(tmp_path):
    auth,_,http = configured_auth(tmp_path,subject='other-user')
    with pytest.raises(AIError,match='OAUTH_REGISTRATION_MISMATCH'):
        auth.access_token()
    assert not http.calls


def test_tokens_redacted_and_never_journalled(tmp_path):
    synthetic = 'Bearer test-only-credential refresh_token="test-only-refresh"'
    assert 'test-only-credential' not in redact(synthetic)
    store = ShadowStorage(tmp_path)
    with pytest.raises(ValueError,match='CREDENTIAL'):
        store.error('FAIL','2026-10-05T00:00:00+00:00',{'message':synthetic})
    assert not store.records()


def test_dynamic_callback_requires_issued_client_id():
    attempt = AuthorizationAttempt('host','http://127.0.0.1:8000/auth/callback')
    with pytest.raises(AIError,match='REGISTRATION_INCOMPLETE'):
        attempt.callback({'state':attempt.state,'code':'fake-test-code'})
    assert attempt.callback({'state':attempt.state,'code':'fake-test-code','client_id':'issued-client'})[0]=='issued-client'


def test_vault_large_bundle_and_atomic_rotation():
    class Backend:
        def __init__(self): self.data={}; self.fail=False
        def get_password(self,service,user): return self.data.get(service)
        def set_password(self,service,user,value):
            assert len(value.encode('utf-16-le')) < 2560
            if self.fail: raise OSError('mock write failure')
            self.data[service]=value
        def delete_password(self,service,user): self.data.pop(service,None)
    vault = object.__new__(WindowsTokenStore)
    vault.backend=Backend()
    bundle={'access_token':'fake-test-'*700,'refresh_token':'fake-refresh-'*400}
    vault.replace('unit-test',bundle)
    assert vault.load('unit-test')==bundle
    vault.backend.fail=True
    with pytest.raises(AIError): vault.replace('unit-test',{'access_token':'replacement'})
    assert vault.load('unit-test')==bundle
