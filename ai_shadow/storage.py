"""Append-only authoritative SQLite journal and recoverable file projections.

One transaction commits a decision, fills, cash flows, state and benchmark.
JSON/CSV files are derived views: a crash cannot cause a second paper fill.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import sqlite3
import tempfile
from contextlib import contextmanager
from pathlib import Path

from ai_shadow.audit import chain_record, redact
from ai_shadow.snapshot import canonical_hash, canonical_json


def atomic_text(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=".shadow-", suffix=".tmp")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


@contextmanager
def process_lock(path: Path):
    """OS-held nonblocking lock; automatically released on process termination."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise RuntimeError("AI_RUN_IN_PROGRESS") from None
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def reject_credentials(value):
    if isinstance(value, dict):
        if any(k.lower() in {"access_token", "refresh_token", "id_token", "authorization",
                             "code_verifier", "api_key", "password"} for k in value):
            raise ValueError("CREDENTIAL_IN_JOURNAL")
        for child in value.values():
            reject_credentials(child)
    elif isinstance(value, list):
        for child in value:
            reject_credentials(child)
    elif isinstance(value, str) and redact(value) != value:
        raise ValueError('CREDENTIAL_TEXT_IN_JOURNAL')


class ShadowStorage:
    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.database = self.root / "journal.sqlite3"
        self.export_warning = None
        with self._connect() as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS events (
                    sequence INTEGER PRIMARY KEY, kind TEXT NOT NULL,
                    identity TEXT UNIQUE NOT NULL, day TEXT UNIQUE,
                    record TEXT NOT NULL
                );
                CREATE TRIGGER IF NOT EXISTS prevent_update BEFORE UPDATE ON events
                    BEGIN SELECT RAISE(ABORT, 'APPEND_ONLY'); END;
                CREATE TRIGGER IF NOT EXISTS prevent_delete BEFORE DELETE ON events
                    BEGIN SELECT RAISE(ABORT, 'APPEND_ONLY'); END;
            """)

    @contextmanager
    def _connect(self):
        connection = sqlite3.connect(self.database, timeout=10)
        try:
            connection.execute("PRAGMA synchronous=FULL")
            with connection:
                yield connection
        finally:
            # sqlite3.Connection.__exit__ commits, but does NOT close a handle.
            # Explicit close is important for Windows and frequent UI refresh.
            connection.close()

    def records(self):
        with self._connect() as connection:
            return [json.loads(r[0]) for r in connection.execute("SELECT record FROM events ORDER BY sequence")]

    def verify_chain(self):
        previous = "GENESIS"
        for record in self.records():
            body = {k: v for k, v in record.items() if k != "record_hash"}
            if body["previous_record_hash"] != previous or canonical_hash(body) != record["record_hash"]:
                return False
            previous = record["record_hash"]
        return True

    def _append(self, kind, identity, payload, day=None):
        reject_credentials(payload)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if not self.verify_chain():
                raise ValueError("AI_AUDIT_CHAIN_INVALID")
            if connection.execute("SELECT 1 FROM events WHERE identity=? OR (day IS NOT NULL AND day=?)", (identity, day)).fetchone():
                return False
            latest = connection.execute("SELECT record FROM events ORDER BY sequence DESC LIMIT 1").fetchone()
            previous = json.loads(latest[0])["record_hash"] if latest else "GENESIS"
            record = chain_record({"kind": kind, "payload": payload}, previous)
            connection.execute("INSERT INTO events(kind,identity,day,record) VALUES(?,?,?,?)",
                               (kind, identity, day, canonical_json(record)))
        return True

    def create_genesis(self, payload):
        if not self._append("GENESIS", "GENESIS", payload):
            raise ValueError("GENESIS_ALREADY_EXISTS")
        self._safe_export()

    def genesis(self):
        return next((r["payload"] for r in self.records() if r["kind"] == "GENESIS"), None)

    def cycles(self):
        return [r["payload"] for r in self.records() if r["kind"] == "CYCLE"]

    def state(self):
        states = [r['payload']['state'] for r in self.records() if r['payload'].get('state')]
        return states[-1] if states else None

    def commit_receipts(self, payload):
        committed = self._append('RECEIPTS', 'CASH:'+payload['state']['source_cursor_hash'], payload)
        if committed:
            self._safe_export()
        return committed

    def completed_day(self, day):
        return any(r.get("day") == day for r in self.cycles())

    def commit_cycle(self, payload):
        if self.genesis() is None:
            raise ValueError("GENESIS_REQUIRED")
        committed = self._append("CYCLE", payload["decision_id"], payload, payload["day"])
        if committed:
            self._safe_export()
        return committed

    def error(self, code, timestamp, details=None):
        from uuid import uuid4
        self._append("ERROR", str(uuid4()), {"code": code, "timestamp": timestamp, 'details': details or {}})
        self._safe_export()

    def _safe_export(self):
        try:
            self.export()
            self.export_warning = None
        except OSError:
            # The durable transaction already succeeded. Never repeat a fill.
            self.export_warning = 'AUDIT_EXPORT_PENDING'

    def projection_warning(self):
        """Read-only, durable detection even after restart or a failed export."""
        try:
            manifest = json.loads((self.root / 'export_manifest.json').read_text(encoding='utf-8'))
            records = self.records()
            if manifest['journal_head'] != (records[-1]['record_hash'] if records else 'GENESIS'):
                return 'AUDIT_EXPORT_PENDING'
            for name, digest in manifest['files'].items():
                path = (self.root / name).resolve()
                if self.root not in path.parents or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                    return 'AUDIT_EXPORT_PENDING'
        except (OSError, ValueError, KeyError):
            return 'AUDIT_EXPORT_PENDING'
        return None

    def export(self):
        records, cycles = self.records(), self.cycles()
        files = {}
        def write(name, content):
            atomic_text(self.root / name, content)
            files[name] = hashlib.sha256(content.encode('utf-8')).hexdigest()

        accounting = [r['payload'] for r in records if r['kind'] in {'CYCLE', 'RECEIPTS'}]
        genesis = self.genesis()
        if genesis:
            write('genesis.json', canonical_json(genesis) + "\n")
        if genesis and genesis.get("state"):
            write('ai_state.json', canonical_json(self.state()) + "\n")
        for name, kind in (("ai_decisions.jsonl", "CYCLE"), ("ai_errors.jsonl", "ERROR")):
            write(name, "".join(canonical_json(r) + "\n" for r in records if r["kind"] == kind))
        write('ai_research.jsonl', "".join(canonical_json(r.get("research", {})) + "\n" for r in cycles))
        for cycle in cycles:
            if 'decision' not in cycle:
                continue
            identity = cycle['decision_id']
            if not identity or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-' for c in identity):
                raise ValueError('DECISION_ID_INVALID')
            write('snapshots/' + identity + '.json', canonical_json(cycle['snapshot']) + '\n')
            decision, gateway = cycle['decision'], cycle['risk_gateway']
            lines = ['# AI Shadow 決策紀錄', '', 'PAPER ONLY；外部摘要不是指令。', '',
                     'Decision ID: ' + identity, '時間：' + cycle['decision_time'],
                     '模型：' + cycle['model_slug'], '請求：' + decision['action'],
                     '批准：' + gateway['action'] + ' / ' + gateway['status'],
                     '信心：' + str(decision['confidence']), '', '## 研究論點', '']
            lines.extend(decision['thesis'])
            lines.extend(['', '## 紙上成交', '', canonical_json(cycle['orders']), '',
                          '## 資料與稽核', '', 'Snapshot SHA256: ' + cycle['snapshot_hash'],
                          'Policy SHA256: ' + cycle['policy_hash'],
                          'Research SHA256: ' + cycle.get('research_hash', canonical_hash(cycle['research']))])
            write('decision_journal/' + identity + '.md', '\n'.join(lines) + '\n')
        views = {
            "ai_orders.csv": [o for r in cycles for o in r.get("orders", [])],
            "ai_contributions.csv": [o for r in accounting for o in r.get("contributions", [])],
            "ai_portfolio.csv": ([genesis['state']] if genesis and genesis.get('state') else []) + [r["state"] for r in accounting if "state" in r],
            "ai_daily_metrics.csv": [r["metrics"] for r in cycles if "metrics" in r],
            "ai_benchmark.csv": [r["benchmark"] for r in cycles if "benchmark" in r],
        }
        for name, rows in views.items():
            fields = list(dict.fromkeys(k for row in rows for k in row)) or ["timestamp"]
            buffer = io.StringIO(newline="")
            writer = csv.DictWriter(buffer, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
            write(name, buffer.getvalue())
        # Written LAST. A partial write leaves an old head and is recoverable.
        atomic_text(self.root / 'export_manifest.json', canonical_json({
            'journal_head':records[-1]['record_hash'] if records else 'GENESIS', 'files':files}) + '\n')
