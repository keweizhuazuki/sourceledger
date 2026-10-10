"""Portable accepted baselines that can be checked without a local database."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import sqlite3
import stat
from contextlib import closing

from .core import (
    MAX_BYTES,
    LedgerError,
    canonical,
    dependency_key,
    digest,
    inspect,
    load_manifest,
    safe_path,
)


SNAPSHOT_KIND = "sourceledger-baseline"
SNAPSHOT_VERSION = 1
MAX_SNAPSHOT_BYTES = 8 * 1024 * 1024
MAX_ENTRIES = 10000
_HASH = re.compile(r"[0-9a-f]{64}")
_BASELINE_QUERY = "SELECT content,note_hash,revision FROM baselines WHERE key=?"


def _text(value, field):
    if not isinstance(value, str):
        raise LedgerError(f"Baseline snapshot {field} must be a string")
    try:
        size = len(value.encode("utf-8"))
    except UnicodeError as exc:
        raise LedgerError(f"Baseline snapshot {field} must be valid UTF-8 text") from exc
    if size > MAX_BYTES:
        raise LedgerError(f"Baseline snapshot {field} exceeds the 2 MiB text limit")


def _dependency(root, dep):
    if (
        not isinstance(dep, dict)
        or not {"note", "source"} <= set(dep)
        or set(dep) - {"note", "source", "heading", "occurrence"}
    ):
        raise LedgerError("Baseline dependency needs note/source and optional heading/occurrence")
    for field in ("note", "source"):
        _text(dep[field], field)
        safe_path(root, dep[field])
    if "heading" in dep:
        _text(dep["heading"], "heading")
    if type(dep.get("occurrence", 1)) is not int or dep.get("occurrence", 1) < 1:
        raise LedgerError("Baseline dependency occurrence must be a positive integer")
    if "occurrence" in dep and "heading" not in dep:
        raise LedgerError("Baseline dependency occurrence requires heading")


def _entry(root, entry):
    if not isinstance(entry, dict) or set(entry) != {
        "dependency", "accepted", "note_hash", "source_hash"
    }:
        raise LedgerError("Baseline entry requires dependency, accepted, note_hash and source_hash")
    _dependency(root, entry["dependency"])
    _text(entry["accepted"], "accepted content")
    for field in ("note_hash", "source_hash"):
        if not isinstance(entry[field], str) or _HASH.fullmatch(entry[field]) is None:
            raise LedgerError(f"Baseline snapshot {field} must be a lowercase SHA-256 hash")
    if digest(entry["accepted"]) != entry["source_hash"]:
        raise LedgerError("Baseline snapshot source_hash does not match accepted content")


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise LedgerError(f"Duplicate JSON field in baseline snapshot: {key!r}")
        result[key] = value
    return result


def _invalid_constant(value):
    raise LedgerError(f"Invalid JSON constant in baseline snapshot: {value}")


def _read_snapshot(root, path):
    """Read a bounded external input, never resolving it relative to the KB."""
    try:
        # O_NONBLOCK lets us reject FIFOs without hanging on open. Validate the
        # opened descriptor, rather than trusting a separate, racy path stat.
        descriptor = os.open(
            path, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_BINARY", 0)
        )
        try:
            if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                raise LedgerError(f"Not a regular UTF-8 baseline snapshot: {path}")
            with os.fdopen(descriptor, "rb") as stream:
                descriptor = None
                raw = stream.read(MAX_SNAPSHOT_BYTES + 1)
        finally:
            if descriptor is not None:
                os.close(descriptor)
        if len(raw) > MAX_SNAPSHOT_BYTES:
            raise LedgerError("Baseline snapshot exceeds the 8 MiB size limit")
        payload = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_unique_object,
            parse_constant=_invalid_constant,
        )
    except (OSError, UnicodeError, ValueError, TypeError, RecursionError) as exc:
        raise LedgerError(f"Cannot read UTF-8 baseline snapshot {path}: {exc}") from exc
    if (
        not isinstance(payload, dict)
        or set(payload) != {"kind", "version", "dependencies"}
        or payload["kind"] != SNAPSHOT_KIND
        or type(payload["version"]) is not int
        or payload["version"] != SNAPSHOT_VERSION
    ):
        raise LedgerError("Baseline snapshot requires kind sourceledger-baseline, version 1 and dependencies")
    entries = payload["dependencies"]
    if not isinstance(entries, list) or not entries or len(entries) > MAX_ENTRIES:
        raise LedgerError("Baseline snapshot dependencies must be a nonempty list of at most 10000 entries")
    lookup = {}
    for entry in entries:
        _entry(root, entry)
        key = dependency_key(entry["dependency"])
        if key in lookup:
            raise LedgerError("Duplicate dependency in baseline snapshot")
        lookup[key] = entry
    return payload, lookup


def export_baseline(root):
    """Return accepted data for every current dependency without changing state.

    Current source/note contents are deliberately not read. The manifest chooses
    the identities to export; a single SQLite read transaction supplies their
    previously accepted contents and note hashes, including legacy schema 0.
    """
    root = Path(root)
    dependencies = load_manifest(root)
    if len(dependencies) > MAX_ENTRIES:
        raise LedgerError("Baseline snapshot supports at most 10000 dependencies")
    payload = {"kind": SNAPSHOT_KIND, "version": SNAPSHOT_VERSION, "dependencies": []}
    # Reserve the newline emitted by the command-line JSON writer as well.
    serialized_size = len(canonical(payload).encode("utf-8")) + 1
    db_path = safe_path(root, ".sourceledger/state.sqlite3")
    try:
        if not stat.S_ISREG(db_path.stat().st_mode):
            raise LedgerError("No regular accepted baseline database is available to export")
        # SQLite mode=ro can still create WAL/SHM sidecars. Reject WAL before
        # opening SQLite instead of using immutable=1, which could silently
        # ignore accepted commits that have not yet been checkpointed.
        with db_path.open("rb") as stream:
            header = stream.read(100)
        if len(header) >= 20 and (header[18] == 2 or header[19] == 2):
            raise LedgerError(
                "Baseline export does not support WAL-mode databases because a read-only "
                "connection can create WAL/SHM files; use a rollback-journal database"
            )
        with closing(sqlite3.connect(db_path.as_uri() + "?mode=ro", uri=True, timeout=10)) as db:
            db.execute("BEGIN")
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version > 2:
                raise LedgerError(f"Database schema {version} is newer than this SourceLedger supports")
            if version not in (0, 1, 2):
                raise LedgerError(f"Unsupported database schema: {version}")
            for dep in sorted(dependencies, key=dependency_key):
                # Do not read revisions, history, timestamps or current files.
                row = db.execute(
                    "SELECT content,note_hash FROM baselines WHERE key=?", (dependency_key(dep),)
                ).fetchone()
                if row is None:
                    raise LedgerError(
                        f"No accepted baseline for {dep['note']} <- {dep['source']}; "
                        "review and accept every current dependency before exporting"
                    )
                content, note_hash = row
                _text(content, "accepted content")
                entry = {
                    "dependency": dict(dep),
                    "accepted": content,
                    "note_hash": note_hash,
                    "source_hash": digest(content),
                }
                _entry(root, entry)
                serialized_size += len(canonical(entry).encode("utf-8")) + bool(payload["dependencies"])
                if serialized_size > MAX_SNAPSHOT_BYTES:
                    raise LedgerError("Baseline snapshot export exceeds the 8 MiB size limit")
                payload["dependencies"].append(entry)
    except (sqlite3.Error, OSError, UnicodeError, ValueError) as exc:
        raise LedgerError(f"Cannot read accepted baseline database: {exc}") from exc
    return payload


class _BaselineRow:
    def __init__(self, entry):
        self.entry = entry

    def fetchone(self):
        if self.entry is None:
            return None
        # The revision is only used in inspect's local review token, which is
        # discarded. A portable snapshot cannot authorize local acceptance.
        return self.entry["accepted"], self.entry["note_hash"], 0


class _BaselineLookup:
    """The one read-only lookup inspect needs, backed entirely by memory."""

    def __init__(self, entries):
        self.entries = entries

    def execute(self, query, parameters):
        if query != _BASELINE_QUERY or len(parameters) != 1:
            raise LedgerError("Unsupported portable baseline lookup")
        return _BaselineRow(self.entries.get(parameters[0]))


def check_baseline(root, path, note=None):
    """Compare working files against a snapshot without opening any database."""
    root = Path(root)
    payload, entries = _read_snapshot(root, path)
    report = inspect(root, _BaselineLookup(entries), note)
    report.pop("review_token", None)
    current = {dependency_key(dep) for dep in report["dependencies"]}
    report.update(
        baseline_mode="snapshot",
        snapshot_digest=digest(canonical(payload)),
        removed_dependencies=[
            dict(entry["dependency"])
            for key, entry in sorted(entries.items())
            if key not in current and (note is None or entry["dependency"]["note"] == note)
        ],
    )
    return report
