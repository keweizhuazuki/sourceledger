"""Dependency-free command line and portable HTML reports."""
from __future__ import annotations
import argparse
import difflib
import html
import json
import sys
import sqlite3
from pathlib import Path
from .core import LedgerError, accept, check, read_text, sections


def diff(row):
    lines = difflib.unified_diff(row.get("before", "").splitlines(keepends=True), row.get("after", "").splitlines(keepends=True), fromfile="accepted", tofile="current")
    return "".join(line if line.endswith("\n") else line + "\n\\ No newline at end of file\n" for line in lines)


def render_text(report):
    lines = ["SourceLedger | local source review", ", ".join(f"{count} {status}" for status, count in report["summary"].items())]
    for row in report["dependencies"]:
        label = row["source"] + (f" → {row['heading']} [{row.get('occurrence', 1)}]" if "heading" in row else "")
        lines.append(f"\n[{row['status'].upper()}] {row['note']} ← {label}")
        if row.get("note_changed"):
            lines.append("  Note edited since acceptance; content accuracy still needs human review.")
        if row["status"] == "error":
            lines.append(row["error"])
        elif row["status"] != "current":
            lines.append(diff(row))
    lines.extend(["", "Review token: " + report["review_token"], "Checking does not accept changes. Use accept --token TOKEN only after reviewing."])
    return "\n".join(lines) + "\n"


def render_html(report):
    esc = html.escape
    cards = []
    for row in report["dependencies"]:
        detail = row.get("error") or (diff(row) if row["status"] != "current" else "Source unchanged since acceptance.")
        if row.get("note_changed"):
            detail = "Note edited since acceptance; content accuracy still needs human review.\n\n" + detail
        cards.append(f'<article><span class="status {esc(row["status"])}">{esc(row["status"])}</span><h2>{esc(row["note"])}</h2><p>{esc(row["source"])} · {esc(row.get("heading", "whole file"))} · occurrence {row.get("occurrence", 1)}</p><pre>{esc(detail)}</pre></article>')
    summary = " · ".join(f"{count} {status}" for status, count in report["summary"].items())
    return f'''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'"><title>SourceLedger review</title><style>body{{font:16px system-ui;max-width:1000px;margin:40px auto;padding:0 20px;background:#f2f5f8;color:#192e40}}header,article{{background:white;padding:24px;border-radius:12px;margin:16px 0;border:1px solid #d8e1ea}}h1{{font-size:36px;margin:8px 0}}h2{{font-size:20px}}pre{{white-space:pre-wrap;overflow-wrap:anywhere;background:#f5f7fa;padding:16px;border-radius:8px}}.status{{text-transform:uppercase;font-size:12px;font-weight:700;padding:5px 9px;border-radius:20px;background:#dfe8f1}}.changed,.new{{background:#ffedb3}}.error{{background:#ffcfcd}}.current{{background:#cbeedd}}code{{overflow-wrap:anywhere}}</style><header><small>LOCAL KNOWLEDGE · HUMAN REVIEW</small><h1>SourceLedger</h1><p>{esc(summary)}</p><p>Source changes identify notes to review. They do not prove a note is wrong or correct.</p></header>{''.join(cards)}<footer><p>Review token: <code>{report['review_token']}</code></p><p>This static report never accepts changes or loads external resources. Run the CLI accept command after review.</p></footer></html>'''


def configure_output():
    """Use UTF-8 for redirected output as well as modern Windows terminals."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")


def main(argv=None):
    configure_output()
    parser = argparse.ArgumentParser(description="Review local source changes that affect your Markdown notes")
    parser.add_argument("--root", type=Path, default=Path("."), help="knowledge-base folder (default: current directory)")
    sub = parser.add_subparsers(dest="command", required=True)
    show = sub.add_parser("check", help="inspect without changing accepted baselines; exit 1 if review needed")
    show.add_argument("--note", help="review one exact note path")
    show.add_argument("--format", choices=["text", "json", "html"], default="text")
    show.add_argument("--output", type=Path, help="write report to a NEW file; existing files are never overwritten")
    approve = sub.add_parser("accept", help="explicitly accept the exact inspected snapshot")
    approve.add_argument("--token", required=True)
    approve.add_argument("--note")
    headings = sub.add_parser("headings", help="list exact ATX heading names and duplicate occurrences")
    headings.add_argument("source")
    sub.add_parser("init", help="create an editable starter manifest without overwriting existing files")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    try:
        if not root.is_dir():
            raise LedgerError(f"Knowledge-base folder does not exist: {root}")
        if args.command == "init":
            with (root / "sourceledger.json").open("x", encoding="utf-8") as handle:
                json.dump({"version": 1, "dependencies": [{"note": "notes/onboarding.md", "source": "sources/policy.md", "heading": "Access", "occurrence": 1}]}, handle, indent=2)
                handle.write("\n")
            print("Created sourceledger.json. Edit the paths before running check.")
            return 0
        if args.command == "headings":
            print(json.dumps(sections(read_text(root, args.source)), ensure_ascii=False, indent=2))
            return 0
        if args.command == "accept":
            count = accept(root, args.token, args.note)
            print(f"Accepted {count} dependencies. Notes and sources were not edited.")
            return 0
        report = check(root, args.note)
        output = json.dumps(report, ensure_ascii=False, indent=2) + "\n" if args.format == "json" else render_html(report) if args.format == "html" else render_text(report)
        if args.output:
            with args.output.open("x", encoding="utf-8") as handle:
                handle.write(output)
            print(f"Report written to {args.output}")
        else:
            sys.stdout.write(output)
        return 2 if report["summary"]["error"] else 1 if report["summary"]["new"] + report["summary"]["changed"] else 0
    except (LedgerError, OSError, ValueError, sqlite3.Error) as exc:
        print(f"sourceledger: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
