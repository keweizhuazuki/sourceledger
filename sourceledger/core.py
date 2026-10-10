"""Deterministic local snapshots and transactional review baselines."""
from __future__ import annotations
import hashlib
import json
import re
import sqlite3
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
    path = (root / candidate).resolve()
    if not path.is_relative_to(root.resolve()):
        raise LedgerError(f"Path escapes the knowledge base: {name}")
    return path


def read_text(root, name):
    path = safe_path(root, name)
    try:
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
            title = re.sub(r"[ \t]+#+[ \t]*$", "", match[2] or "").strip()
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
    db.execute("CREATE TABLE IF NOT EXISTS baselines (key TEXT PRIMARY KEY, content TEXT NOT NULL, note_hash TEXT NOT NULL, revision INTEGER NOT NULL)")
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
                          note_changed=bool(baseline and baseline[1] != note_hash))
            evidence.append([key, digest(content), note_hash, baseline])
        except LedgerError as exc:
            record.update(status="error", error=str(exc))
            evidence.append([key, "error", str(exc), baseline])
        records.append(record)
    return {"version": 1, "review_token": digest(canonical(evidence)), "dependencies": records,
            "summary": {status: sum(row["status"] == status for row in records) for status in ("new", "changed", "current", "error")}}


def check(root, note=None):
    with connect(root) as db:
        return inspect(root, db, note)


def accept(root, token, note=None):
    with connect(root) as db:
        db.execute("BEGIN IMMEDIATE")
        report = inspect(root, db, note)
        if report["summary"]["error"]:
            raise LedgerError("Cannot accept while a tracked note/source/section is missing or unreadable")
        if token != report["review_token"]:
            raise LedgerError("Review token is stale or incorrect. Run check and review the new report")
        for dep in report["dependencies"]:
            key = dependency_key(dep)
            db.execute("INSERT INTO baselines VALUES (?,?,?,1) ON CONFLICT(key) DO UPDATE SET content=excluded.content,note_hash=excluded.note_hash,revision=baselines.revision+1",
                       (key, dep["after"], digest(read_text(root, dep["note"]))))
        return len(report["dependencies"])
