"""Run from repository root: python examples/demo.py. Uses a disposable copy."""
import json
from pathlib import Path
import shutil
import tempfile
from sourceledger.core import accept, check, history
from sourceledger.cli import render_text, render_html, render_history, render_discovery, configure_output

from sourceledger.discovery import discover

configure_output()

with tempfile.TemporaryDirectory(prefix="sourceledger-demo-") as directory:
    root = Path(directory) / "handbook"
    shutil.copytree(Path(__file__).parent / "handbook", root, ignore=shutil.ignore_patterns(".sourceledger"))
    manifest_before = (root / "sourceledger.json").read_bytes()
    print(render_discovery(discover(root, ["onboarding.md"])))
    assert not (root / ".sourceledger").exists(), "Discovery must not create baseline storage"
    assert (root / "sourceledger.json").read_bytes() == manifest_before
    initial = check(root)
    accept(root, initial["review_token"])
    policy = root / "policy.md"
    policy.write_text(policy.read_text().replace("30 days", "14 days"), encoding="utf-8")
    report = check(root)
    print(render_text(report))
    print(render_history(history(root)))
    target = Path("demo-report.html")
    with target.open("x", encoding="utf-8") as handle:
        handle.write(render_html(report))
    print(f"Open {target} to inspect the static report. Demo data was temporary.")
