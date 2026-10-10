"""Deterministic local snapshots and transactional review baselines."""
from __future__ import annotations
import hashlib
import json
import re
import sqlite3
import stat
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

MAX_BYTES = 2 * 1024 * 1024


class LedgerError(Exception):
    """An actionable configuration or review error."""


def digest(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def safe_path(root, name):
    if not isinstance(name, str) or not name or "\\" in name:
        raise LedgerError("Paths must be nonempty, forward-slash relative paths")
    candidate = Path(name)
    if candidate.is_absolute() or re.match(r"^[A-Za-z]:", name):
        raise LedgerError(f"Absolute paths are not allowed: {name}")
    try:
        path = (root / candidate).resolve()
    except (RuntimeError, OSError, ValueError) as exc:
        raise LedgerError(f"Cannot resolve local path {name}: {exc}") from exc
    if not path.is_relative_to(root.resolve()):
        raise LedgerError(f"Path escapes the knowledge base: {name}")
    return path


def read_text(root, name):
    path = safe_path(root, name)
    try:
        if not stat.S_ISREG(path.stat().st_mode):
            raise LedgerError(f"Not a regular UTF-8 file: {name}")
        with path.open("rb") as stream:
            raw = stream.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise LedgerError(f"File exceeds 2 MiB limit: {name}")
        return raw.decode("utf-8-sig").replace("\r\n", "\n").replace("\r", "\n")
    except (OSError, UnicodeError) as exc:
        raise LedgerError(f"Cannot read UTF-8 file {name}: {exc}") from exc


def sections(text):
    """ATX headings outside fenced code; repeated titles have 1-based occurrences."""
    found, counts, fence = [], {}, None
    for index, line in enumerate(text.splitlines(keepends=True)):
        marker = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", line)
        if marker:
            run, tail = marker.groups()
            if fence:
                if run[0] == fence[0] and len(run) >= len(fence) and not tail.strip():
                    fence = None
            elif run[0] != "`" or "`" not in tail:
                fence = run
            continue
        if fence:
            continue
        match = re.match(r"^ {0,3}(#{1,6})(?:[ \t]+(.*?)|[ \t]*)$", line.rstrip("\n"))
        if match:
            title = re.sub(r"(?:^|[ \t]+)#+[ \t]*$", "", match[2] or "").strip()
            counts[title] = counts.get(title, 0) + 1
            found.append({"heading": title, "occurrence": counts[title], "level": len(match[1]), "line": index})
    return found


def extract(text, heading=None, occurrence=1):
    if heading is None:
        return text
    headings = sections(text)
    for pos, item in enumerate(headings):
        if item["heading"] == heading and item["occurrence"] == occurrence:
            end = next((entry["line"] for entry in headings[pos + 1:] if entry["level"] <= item["level"]), None)
            return "".join(text.splitlines(keepends=True)[item["line"]:end])
    raise LedgerError(f"Missing ATX heading {heading!r}, occurrence {occurrence}")


def load_manifest(root):
    try:
        data = json.loads(read_text(root, "sourceledger.json"))
    except json.JSONDecodeError as exc:
        raise LedgerError(f"Invalid sourceledger.json: {exc}") from exc
    if not isinstance(data, dict) or set(data) != {"version", "dependencies"} or data["version"] != 1:
        raise LedgerError("Manifest requires version: 1 and dependencies")
    if not isinstance(data["dependencies"], list) or not data["dependencies"]:
        raise LedgerError("Manifest must contain at least one dependency")
    keys = set()
    for dep in data["dependencies"]:
        if not isinstance(dep, dict) or set(dep) - {"note", "source", "heading", "occurrence"} or not {"note", "source"} <= set(dep):
            raise LedgerError("Each dependency needs note/source and optional heading/occurrence")
        safe_path(root, dep["note"])
        safe_path(root, dep["source"])
        if "heading" in dep and not isinstance(dep["heading"], str):
            raise LedgerError("heading must be a string")
        if type(dep.get("occurrence", 1)) is not int or dep.get("occurrence", 1) < 1:
            raise LedgerError("occurrence must be a positive integer")
        if "occurrence" in dep and "heading" not in dep:
            raise LedgerError("occurrence requires heading")
        key = dependency_key(dep)
        if key in keys:
            raise LedgerError("Duplicate dependency in manifest")
        keys.add(key)
    return data["dependencies"]


def dependency_key(dep):
    return canonical({"note": dep["note"], "source": dep["source"], "heading": dep.get("heading"), "occurrence": dep.get("occurrence", 1)})


def connect(root):
    directory = safe_path(root, ".sourceledger")
    directory.mkdir(exist_ok=True)
    db = sqlite3.connect(safe_path(root, ".sourceledger/state.sqlite3"), timeout=10)
    try:
        version = db.execute("PRAGMA user_version").fetchone()[0]
        if version > 2:
            raise LedgerError(f"Database schema {version} is newer than this SourceLedger supports")
        if version not in (0, 1, 2):
            raise LedgerError(f"Unsupported database schema: {version}")
        if version < 2:
            with db:
                db.execute("BEGIN IMMEDIATE")
                # Another connection may have migrated while we waited for the
                # write lock. Read the schema again inside the transaction.
                version = db.execute("PRAGMA user_version").fetchone()[0]
                if version > 2:
                    raise LedgerError(f"Database schema {version} is newer than this SourceLedger supports")
                if version not in (0, 1, 2):
                    raise LedgerError(f"Unsupported database schema: {version}")
                if version == 0:
                    # Preserve legacy baselines without inventing acceptances.
                    db.execute("CREATE TABLE IF NOT EXISTS baselines (key TEXT PRIMARY KEY, content TEXT NOT NULL, note_hash TEXT NOT NULL, revision INTEGER NOT NULL)")
                    db.execute("CREATE TABLE IF NOT EXISTS acceptance_batches (id INTEGER PRIMARY KEY, accepted_at TEXT NOT NULL, review_token TEXT NOT NULL, scope_note TEXT)")
                    db.execute("CREATE TABLE IF NOT EXISTS acceptance_entries (batch_id INTEGER NOT NULL REFERENCES acceptance_batches(id), key TEXT NOT NULL, note TEXT NOT NULL, revision INTEGER NOT NULL, before_content TEXT, content TEXT NOT NULL, note_hash TEXT NOT NULL, PRIMARY KEY(batch_id,key))")
                    db.execute("CREATE INDEX IF NOT EXISTS history_note ON acceptance_entries(note,batch_id)")
                if version < 2:
                    # Import provenance is separate from local acceptance. Keep
                    # the entire snapshot so later acceptance cannot rewrite it.
                    db.execute("CREATE TABLE IF NOT EXISTS baseline_imports (id INTEGER PRIMARY KEY, imported_at TEXT NOT NULL, snapshot_digest TEXT NOT NULL, import_token TEXT NOT NULL, snapshot_json TEXT NOT NULL)")
                    db.execute("PRAGMA user_version=2")
    except (sqlite3.Error, LedgerError):
        db.close()
        raise
    return db


def inspect(root, db, note=None):
    dependencies = load_manifest(root)
    if note is not None:
        dependencies = [dep for dep in dependencies if dep["note"] == note]
        if not dependencies:
            raise LedgerError(f"No tracked dependencies for note: {note}")
    records, evidence = [], []
    for dep in sorted(dependencies, key=dependency_key):
        key = dependency_key(dep)
        baseline = db.execute("SELECT content,note_hash,revision FROM baselines WHERE key=?", (key,)).fetchone()
        record = dict(dep)
        try:
            note_hash = digest(read_text(root, dep["note"]))
            content = extract(read_text(root, dep["source"]), dep.get("heading"), dep.get("occurrence", 1))
            status = "new" if baseline is None else "changed" if baseline[0] != content else "current"
            record.update(status=status, before=baseline[0] if baseline else "", after=content,
                          note_changed=bool(baseline and baseline[1] != note_hash), note_hash=note_hash)
            evidence.append([key, digest(content), note_hash, baseline])
        except LedgerError as exc:
            record.update(status="error", error=str(exc))
            evidence.append([key, "error", str(exc), baseline])
        records.append(record)
    return {"version": 1, "review_token": digest(canonical(evidence)), "dependencies": records,
            "summary": {status: sum(row["status"] == status for row in records) for status in ("new", "changed", "current", "error")}}


def check(root, note=None):
    with closing(connect(root)) as db, db:
        return inspect(root, db, note)


def accept(root, token, note=None):
    with closing(connect(root)) as db, db:
        db.execute("BEGIN IMMEDIATE")
        report = inspect(root, db, note)
        if report["summary"]["error"]:
            raise LedgerError("Cannot accept while a tracked note/source/section is missing or unreadable")
        if token != report["review_token"]:
            raise LedgerError("Review token is stale or incorrect. Run check and review the new report")
        batch = db.execute("INSERT INTO acceptance_batches(accepted_at,review_token,scope_note) VALUES (?,?,?)",
                           (datetime.now(timezone.utc).isoformat(timespec="microseconds"), token, note)).lastrowid
        for dep in report["dependencies"]:
            key = dependency_key(dep)
            previous = db.execute("SELECT content FROM baselines WHERE key=?", (key,)).fetchone()
            db.execute("INSERT INTO baselines VALUES (?,?,?,1) ON CONFLICT(key) DO UPDATE SET content=excluded.content,note_hash=excluded.note_hash,revision=baselines.revision+1",
                       (key, dep["after"], dep["note_hash"]))
            revision = db.execute("SELECT revision FROM baselines WHERE key=?", (key,)).fetchone()[0]
            db.execute("INSERT INTO acceptance_entries VALUES (?,?,?,?,?,?,?)",
                       (batch, key, dep["note"], revision, previous[0] if previous else None, dep["after"], dep["note_hash"]))
        return len(report["dependencies"])


def history(root, note=None, limit=20, before=None):
    """Read acceptance and import evidence even if current files vanished.

    Acceptance batches retain their own pagination. Import provenance is a
    separate, unpaginated list included on every page and filtered by note.
    """
    if type(limit) is not int or not 1 <= limit <= 100:
        raise LedgerError("History limit must be an integer between 1 and 100")
    if before is not None and (type(before) is not int or not 1 <= before <= 9223372036854775807):
        raise LedgerError("History before must be a positive signed 64-bit batch ID")
    with closing(connect(root)) as db, db:
        # Keep batch selection and entry retrieval in one SQLite read snapshot.
        db.execute("BEGIN")
        batches = db.execute("""SELECT id,accepted_at,review_token,scope_note FROM acceptance_batches
            WHERE (? IS NULL OR id < ?) AND (? IS NULL OR EXISTS
                (SELECT 1 FROM acceptance_entries WHERE batch_id=acceptance_batches.id AND note=?))
            ORDER BY id DESC LIMIT ?""", (before, before, note, note, limit + 1)).fetchall()
        more = len(batches) > limit
        results = []
        for batch_id, timestamp, token, scope in batches[:limit]:
            rows = db.execute("""SELECT key,revision,before_content,content,note_hash FROM acceptance_entries
                WHERE batch_id=? AND (? IS NULL OR note=?) ORDER BY key""", (batch_id, note, note)).fetchall()
            dependencies = []
            for key, revision, previous, content, note_hash in rows:
                dependencies.append({**json.loads(key), "revision": revision, "before": previous,
                                     "accepted": content, "source_hash": digest(content), "note_hash": note_hash})
            results.append({"id": batch_id, "accepted_at": timestamp, "review_token": token,
                            "scope_note": scope, "dependencies": dependencies})
        imports = []
        for import_id, timestamp, snapshot_digest, token, snapshot_json in db.execute(
            "SELECT id,imported_at,snapshot_digest,import_token,snapshot_json FROM baseline_imports ORDER BY id DESC"
        ):
            entries = json.loads(snapshot_json)["dependencies"]
            selected = [entry for entry in entries if note is None or entry["dependency"]["note"] == note]
            if selected:
                imports.append({"id": import_id, "imported_at": timestamp,
                                "snapshot_digest": snapshot_digest, "import_token": token,
                                "dependency_count": len(entries), "dependencies": selected})
        return {"version": 1, "batches": results, "imports": imports,
                "next_before": results[-1]["id"] if more else None}
