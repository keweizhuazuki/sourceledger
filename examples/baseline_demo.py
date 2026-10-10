"""Portable baseline CI workflow using synthetic, disposable data only."""
from pathlib import Path
import shutil
import tempfile

from sourceledger.cli import configure_output, render_text
from sourceledger.core import accept, canonical, check
from sourceledger.snapshots import export_baseline, check_baseline

configure_output()
with tempfile.TemporaryDirectory(prefix='sourceledger-baseline-') as temp:
    workspace = Path(temp)
    author = workspace / 'author'
    shutil.copytree(Path(__file__).parent / 'handbook', author)
    accept(author, check(author)['review_token'])
    snapshot = workspace / 'reviewed-baseline.json'
    snapshot.write_text(canonical(export_baseline(author)) + '\n', encoding='utf-8')
    ci = workspace / 'ci'
    shutil.copytree(author, ci, ignore=shutil.ignore_patterns('.sourceledger'))
    assert check_baseline(ci, snapshot)['summary']['current'] == 2
    source = ci / 'policy.md'
    source.write_text(source.read_text(encoding='utf-8').replace('30 days', '14 days'), encoding='utf-8')
    report = check_baseline(ci, snapshot)
    assert report['summary']['changed'] == 1
    assert 'review_token' not in report
    assert not (ci / '.sourceledger').exists()
    print(render_text(report))
    print('Verified: fresh CI copy, accepted snapshot, changed source; no local database or acceptance token.')
