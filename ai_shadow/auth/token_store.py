import json
import os
import hashlib
from uuid import uuid4

from ai_shadow.errors import AIError


class WindowsTokenStore:
    """Windows-only vault, chunked below CredWrite's blob size limit.

    A small atomic manifest selects a complete version. Rotation writes all new
    chunks BEFORE replacing that manifest, so a crash cannot expose half a bundle.
    Tokens and the manifest live only in Windows Credential Manager.
    """
    service = "CryptoForwardMonitor.ChatGPT.OAuth"

    def __init__(self):
        if os.name != "nt":
            raise AIError("SECURE_CREDENTIAL_STORAGE_UNAVAILABLE")
        # Explicit backend: never fall back to plaintext keyring plugins.
        from keyring.backends.Windows import WinVaultKeyring
        self.backend = WinVaultKeyring()
        self.backend.persist = 'local machine'

    def load(self, registration):
        try:
            service = self.service+'.'+registration
            value = self.backend.get_password(service, registration)
            if not value:
                return None
            manifest = json.loads(value)
            raw = ''.join(self.backend.get_password(service+'.'+manifest['version']+'.'+str(i), registration) or ''
                          for i in range(manifest['count']))
            if hashlib.sha256(raw.encode()).hexdigest() != manifest['sha256']:
                raise ValueError('TOKEN_BUNDLE_INCOMPLETE')
            return json.loads(raw)
        except Exception:
            raise AIError("SECURE_CREDENTIAL_STORAGE_UNAVAILABLE") from None

    def replace(self, registration, bundle):
        try:
            service, version = self.service+'.'+registration, str(uuid4())
            old_value = self.backend.get_password(service, registration)
            old = json.loads(old_value) if old_value else None
            raw = json.dumps(bundle, ensure_ascii=True)
            chunks = [raw[i:i+900] for i in range(0,len(raw),900)]
            for i, chunk in enumerate(chunks):
                self.backend.set_password(service+'.'+version+'.'+str(i), registration, chunk)
            self.backend.set_password(service, registration, json.dumps({'version':version, 'count':len(chunks),
                                        'sha256':hashlib.sha256(raw.encode()).hexdigest()}))
            if old:
                for i in range(old['count']):
                    try:
                        self.backend.delete_password(service+'.'+old['version']+'.'+str(i), registration)
                    except Exception:
                        pass  # An orphan remains protected; active pointer is complete.
        except Exception:
            raise AIError("SECURE_CREDENTIAL_STORAGE_UNAVAILABLE") from None

    def clear(self, registration):
        try:
            service = self.service+'.'+registration
            value = self.backend.get_password(service, registration)
            if value:
                manifest = json.loads(value)
                self.backend.delete_password(service, registration)
                for i in range(manifest['count']):
                    self.backend.delete_password(service+'.'+manifest['version']+'.'+str(i), registration)
            # Remove protected orphan chunks after a crash during rotation too.
            if os.name == 'nt':
                from keyring.backends.Windows import win32cred, pywintypes
                try:
                    entries = win32cred.CredEnumerate(service+'*', 0)
                except pywintypes.error as exc:
                    if exc.winerror != 1168:  # ERROR_NOT_FOUND
                        raise
                    entries = []
                for entry in entries:
                    win32cred.CredDelete(entry['TargetName'], entry['Type'], 0)
        except Exception:
            raise AIError("SECURE_CREDENTIAL_STORAGE_UNAVAILABLE") from None


class MemoryTokenStore:
    """Explicit test-only vault, not a production fallback."""
    def __init__(self):
        self.entries = {}

    def load(self, registration):
        import copy
        return copy.deepcopy(self.entries.get(registration))

    def replace(self, registration, bundle):
        import copy
        self.entries[registration] = copy.deepcopy(bundle)

    def clear(self, registration):
        self.entries.pop(registration, None)
