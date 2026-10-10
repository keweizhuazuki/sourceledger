"""Reviewed, all-or-nothing transfer of portable baselines into an empty ledger."""
from __future__ import annotations

import os
from pathlib import Path
import sqlite3
import stat
from contextlib import closing
from datetime import datetime, timezone

from .core import LedgerError, canonical, connect, dependency_key, digest, load_manifest, safe_path
from .snapshots import _read_snapshot


_STATE_TABLES = ("baselines", "acceptance_batches", "acceptance_entries", "baseline_imports")
_INSTRUCTIONS = (
    "Import transfers trust in the exact reviewed snapshot into an empty local ledger. "
    "It does not accept or verify current working files, establish the original reviewer's "
    "identity, or recover original acceptance timestamps. Review every dependency, accepted "
    "excerpt and hash before applying with the import token."
)


def _require_empty(db):
    """Check every known state table, including orphaned history or provenance."""
    version = db.execute("PRAGMA user_version").fetchone()[0]
    if version > 2:
        raise LedgerError(f"Database schema {version} is newer than this SourceLedger supports")
    if version not in (0, 1, 2):
        raise LedgerError(f"Unsupported database schema: {version}")
    objects = dict(db.execute("SELECT name,type FROM sqlite_master WHERE type IN ('table','view')"))
    required = _STATE_TABLES[:3] if version == 1 else _STATE_TABLES if version == 2 else ()
    for table in _STATE_TABLES:
        if table not in objects:
            if table in required:
                raise LedgerError(f"Database schema {version} is missing required table: {table}")
            continue
        if objects[table] != "table":
            raise LedgerError(f"Expected a database table for import state: {table}")
        # Table names come exclusively from the fixed list above, never input.
        if db.execute(f"SELECT 1 FROM {table} LIMIT 1").fetchone() is not None:
            raise LedgerError(
                "Baseline import requires an empty ledger with no baselines, acceptance "
                "history or prior import provenance; existing state is never overwritten"
            )


def _read_empty_state(root):
    """Inspect SQLite without creating a database, directory, migration or sidecar."""
    db_path = safe_path(root, ".sourceledger/state.sqlite3")
    try:
        try:
            descriptor = os.open(db_path, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_BINARY", 0))
        except FileNotFoundError:
            return
        try:
            if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                raise LedgerError("Baseline import requires a regular local database file")
            with os.fdopen(descriptor, "rb") as stream:
                descriptor = None
                header = stream.read(100)
        finally:
            if descriptor is not None:
                os.close(descriptor)
        # SQLite mode=ro may create WAL/SHM files. Never use immutable=1: it
        # could hide committed rows in WAL and falsely claim the ledger is empty.
        if len(header) >= 20 and (header[18] == 2 or header[19] == 2):
            raise LedgerError(
                "Baseline import preview does not support WAL-mode databases because a "
                "read-only connection can create WAL/SHM files; use a rollback-journal database"
            )
        with closing(sqlite3.connect(db_path.as_uri() + "?mode=ro", uri=True, timeout=10)) as db:
            db.execute("BEGIN")
            _require_empty(db)
    except (sqlite3.Error, OSError, ValueError) as exc:
        raise LedgerError(f"Cannot inspect local ledger for baseline import: {exc}") from exc


def _prepare(root, path):
    """Read the entire import scope without consulting current source/note text."""
    payload, entries = _read_snapshot(root, path)
    manifest = load_manifest(root)
    if set(entries) != {dependency_key(dep) for dep in manifest}:
        raise LedgerError(
            "Baseline snapshot dependencies must exactly match the entire current manifest; "
            "missing, extra or changed dependency identities cannot be imported"
        )
    snapshot_json = canonical(payload)
    snapshot_digest = digest(snapshot_json)
    token = digest(canonical({
        "kind": "sourceledger-reviewed-baseline-import",
        "version": 1,
        "snapshot_digest": snapshot_digest,
        "manifest": {"version": 1, "dependencies": manifest},
        # Absent stores and empty schema 0/1/2 stores represent the same state.
        # This lets normal migration leave an otherwise valid token unchanged.
        "ledger_state": {table: 0 for table in _STATE_TABLES},
    }))
    return payload, entries, snapshot_json, snapshot_digest, token


def preview_import(root, path):
    """Return exact import evidence and a token; never write local ledger state."""
    root = Path(root)
    payload, _entries, _snapshot_json, snapshot_digest, token = _prepare(root, path)
    _read_empty_state(root)
    return {
        "kind": "sourceledger-baseline-import",
        "version": 1,
        "import_token": token,
        "snapshot_digest": snapshot_digest,
        "dependency_count": len(payload["dependencies"]),
        "dependencies": payload["dependencies"],
        "scope": "all manifest dependencies",
        "instructions": _INSTRUCTIONS,
    }


def apply_import(root, path, token):
    """Apply a reviewed snapshot exactly once, with separate durable provenance."""
    root = Path(root)
    # Preflight is strictly read-only. An incorrect/stale token cannot create
    # storage or migrate an existing database just by attempting an import.
    report = preview_import(root, path)
    if token != report["import_token"]:
        raise LedgerError("Import token is stale or incorrect. Preview and review the snapshot again")
    with closing(connect(root)) as db, db:
        db.execute("BEGIN IMMEDIATE")
        # Re-read after locking: neither a stale preview nor a concurrent import
        # or acceptance may install a different snapshot or overwrite state.
        _payload, entries, snapshot_json, snapshot_digest, current_token = _prepare(root, path)
        _require_empty(db)
        if token != current_token:
            raise LedgerError("Import token is stale or incorrect. Preview and review the snapshot again")
        for key, entry in sorted(entries.items()):
            db.execute("INSERT INTO baselines(key,content,note_hash,revision) VALUES (?,?,?,1)",
                       (key, entry["accepted"], entry["note_hash"]))
        db.execute(
            "INSERT INTO baseline_imports(imported_at,snapshot_digest,import_token,snapshot_json) VALUES (?,?,?,?)",
            (datetime.now(timezone.utc).isoformat(timespec="microseconds"), snapshot_digest, token, snapshot_json),
        )
    return len(entries)
