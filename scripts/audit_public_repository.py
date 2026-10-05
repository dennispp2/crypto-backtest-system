"""Read-only, redacted Git-history inventory; never print matching content.

This is a bounded pattern audit, not a claim that arbitrary binary files or
encoded secrets are safe. No third-party scanner is installed by this script.
"""
import hashlib
import json
import re
import subprocess
from pathlib import Path


PATTERNS = {
    "openai_key": re.compile(r"\bsk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{32,}"),
    "github_token": re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})"),
    "private_key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "jwt": re.compile(r"\beyJ[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{15,}"),
    "credential_assignment": re.compile(r'''(?i)(?:access_token|refresh_token|api_key|password|session_cookie)\s*["']?\s*[:=]\s*["']([A-Za-z0-9_./+\-=]{24,})["']'''),
}
FROZEN_PATHS = (
    "run_forward_v3_10.py", "src/crypto_backtest/v310_engine.py",
    "src/crypto_backtest/v310_forward.py", "src/crypto_backtest/v31_engine.py",
    "config/config_frozen_v3_10.json", "config/config_frozen_v3_10_forward.json",
    "config/config_frozen_v3_1.json",
)


def git(*args):
    return subprocess.check_output(["git", *args])


def audit():
    commits = git("rev-list", "--all").decode().splitlines()
    seen, findings, skipped, personal_paths = set(), [], 0, set()
    blobs = []
    for commit in commits:
        for entry in git("ls-tree", "-rz", commit).split(b"\0"):
            if not entry:
                continue
            metadata, filename = entry.split(b"\t", 1)
            _, kind, oid = metadata.split()
            if kind != b"blob" or oid in seen:
                continue
            seen.add(oid)
            path = filename.decode("utf-8", errors="replace")
            blobs.append((oid, path, commit))
    # One Git process avoids hundreds of Windows process startups.
    process = subprocess.Popen(['git','cat-file','--batch'], stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    try:
        for oid,path,commit in blobs:
            process.stdin.write(oid+b'\n')
            process.stdin.flush()
            header = process.stdout.readline().split()
            content = process.stdout.read(int(header[2]))
            process.stdout.read(1)
            if b"\0" in content:
                skipped += 1
                continue
            text = content.decode("utf-8", errors="replace")
            if re.search(r"(?:[A-Za-z]:[/\\]Users[/\\]|[\w.+-]+@[\w.-]+\.[A-Za-z]{2,})", text):
                personal_paths.add(path)
            for name, pattern in PATTERNS.items():
                for match in pattern.finditer(text):
                    findings.append({"commit": commit, "path": path, "kind": name,
                                     "line": text.count("\n", 0, match.start()) + 1})
    finally:
        process.stdin.close()
        process.stdout.close()
        process.wait()
    tracked = git("ls-files").decode().splitlines()
    working_files = git('ls-files','--cached','--others','--exclude-standard','-z').decode().split('\0')
    current_findings = []
    for relative in working_files:
        if not relative or not Path(relative).is_file():
            continue
        content = Path(relative).read_bytes()
        if b'\0' in content:
            continue
        text = content.decode('utf-8',errors='replace')
        for name,pattern in PATTERNS.items():
            for match in pattern.finditer(text):
                current_findings.append({'path':relative,'kind':name,'line':text.count('\n',0,match.start())+1})
    return {
        "commits_scanned": len(commits), "unique_blobs_scanned": len(seen),
        "binary_blobs_not_content_scanned": skipped, "secret_candidates": findings,
        'working_tree_secret_candidates':current_findings,
        "personal_path_or_email_files": sorted(personal_paths),
        "credential_filename_candidates": [p for p in tracked if re.search(r"(?:^|/)(?:\.env(?:\.|$)|auth\.json$|credentials?\.|cookies?\.|.*\.pem$|.*\.key$)", p, re.I)],
        "license_present": any(Path(name).is_file() for name in ("LICENSE", "LICENSE.md", "LICENSE.txt")),
        "frozen_sha256": {p: hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in FROZEN_PATHS},
        "scope": "Git-reachable text blobs; binary/encoded secrets require separate review",
    }


if __name__ == "__main__":
    print(json.dumps(audit(), ensure_ascii=False, indent=2))
