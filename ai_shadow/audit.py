from pathlib import Path
import hashlib
import re

from ai_shadow.snapshot import canonical_hash

FROZEN_HASHES = {
    "run_forward_v3_10.py": "ad1cc0c5d024909128da0ea2196978dd2e25375b61337d35d0752426c74aacad",
    "src/crypto_backtest/v310_engine.py": "7caaf9dfdaccf3d0d1c2c9fc9dcbadc808acfad27b45ff5d876f46d643507289",
    "src/crypto_backtest/v310_forward.py": "b1293cdeac5a3597a97d8ba21d76ed2f0f14dd97edb22d60c0f434f3225e7875",
    "src/crypto_backtest/v31_engine.py": "ea91309e5821431210998cf2289965adad8991cc97005105cceab9037aeae2a1",
    "config/config_frozen_v3_10.json": "a0a7db91f1c93782f01a158a807370dd80acc0f3378ce74c39d38186c6cf7e64",
    "config/config_frozen_v3_10_forward.json": "d30fff5b54f7a7e9d9eea6cce08912e08ccc8ec8b7e984f3c8893145de3b209d",
    "config/config_frozen_v3_1.json": "50adc23c620d068087842ca574f8d4f87a8b6de3d96ebca0392184c43574bc84",
}


def frozen_audit(root: Path):
    return {p: {"before": expected,
                "after": hashlib.sha256((root / p).read_bytes()).hexdigest() if (root / p).is_file() else "MISSING"}
            for p, expected in FROZEN_HASHES.items()}


def frozen_ok(root):
    return all(v["before"] == v["after"] for v in frozen_audit(root).values())


def redact(text):
    result = re.sub(r"(?i)(?:Bearer\s+|(?:access_token|refresh_token|id_token|code_verifier|authorization|api_key|password)[\"']?\s*[:=]\s*[\"']?)[^\s\"',}]+", "[REDACTED]", str(text))
    result = re.sub(r"\beyJ[A-Za-z0-9_.-]+", "[REDACTED]", result)
    result = re.sub(r"\bsk-[A-Za-z0-9_-]+", "[REDACTED]", result)
    return re.sub(r"([?&](?:code|id_token_hint|code_verifier)=)[^&\s]+", r"\1[REDACTED]", result)


def chain_record(payload, previous):
    record = {**payload, "previous_record_hash": previous}
    return {**record, "record_hash": canonical_hash(record)}
