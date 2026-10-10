"""Run from repository root: python examples/demo.py. Uses a disposable copy."""
import json
from pathlib import Path
import shutil
import tempfile
from sourceledger.core import accept, check
from sourceledger.cli import render_text, render_html

with tempfile.TemporaryDirectory(prefix="sourceledger-demo-") as directory:
    root = Path(directory) / "handbook"
    shutil.copytree(Path(__file__).parent / "handbook", root, ignore=shutil.ignore_patterns(".sourceledger"))
    initial = check(root)
    accept(root, initial["review_token"])
    policy = root / "policy.md"
    policy.write_text(policy.read_text().replace("30 days", "14 days"), encoding="utf-8")
    report = check(root)
    print(render_text(report))
    target = Path("demo-report.html")
    with target.open("x", encoding="utf-8") as handle:
        handle.write(render_html(report))
    print(f"Open {target.resolve()} to inspect the static report. Demo data was temporary.")
