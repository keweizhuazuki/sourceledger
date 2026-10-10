"""Reviewed baseline import using only disposable synthetic data."""
from pathlib import Path
import shutil
import tempfile

from sourceledger.cli import configure_output, render_history, render_text
from sourceledger.core import accept, canonical, check, history
from sourceledger.imports import preview_import, apply_import
from sourceledger.snapshots import export_baseline

configure_output()
with tempfile.TemporaryDirectory(prefix='sourceledger-import-') as temp:
    base = Path(temp)
    author = base / 'author'
    shutil.copytree(Path(__file__).parent / 'handbook', author)
    accept(author, check(author)['review_token'])
    snapshot = base / 'reviewed.json'
    snapshot.write_text(canonical(export_baseline(author)), encoding='utf-8')
    destination = base / 'destination'
    shutil.copytree(author, destination, ignore=shutil.ignore_patterns('.sourceledger'))
    policy = destination / 'policy.md'
    policy.write_text(policy.read_text(encoding='utf-8').replace('30 days', '14 days'), encoding='utf-8')
    preview = preview_import(destination, snapshot)
    assert not (destination / '.sourceledger').exists()
    print(f"Preview: {preview['dependency_count']} imported dependencies; no database created.")
    # This synthetic demo trusts the snapshot it just created. Real users must
    # inspect the CLI preview and verify the snapshot's trusted provenance.
    apply_import(destination, snapshot, preview['import_token'])
    imported = history(destination)
    assert not imported['batches'] and len(imported['imports']) == 1
    print(render_history(imported))
    report = check(destination)
    assert report['summary']['changed'] == 1
    print(render_text(report))
    print('Verified: import recorded separately; current edits still need local review.')
