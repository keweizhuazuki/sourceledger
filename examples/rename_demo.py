"""Reproduce a missing source after git mv in a disposable Git repository."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from sourceledger.core import accept, check
from sourceledger.renames import suggest_renames
from sourceledger.cli import configure_output, render_renames

configure_output()
with tempfile.TemporaryDirectory(prefix='sourceledger-rename-demo-') as directory:
    root = Path(directory) / 'handbook'
    shutil.copytree(Path(__file__).parent / 'handbook', root, ignore=shutil.ignore_patterns('.sourceledger'))
    env = {key: value for key, value in os.environ.items() if not key.startswith('GIT_')}
    env.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM='1', GIT_ALLOW_PROTOCOL='',
               GIT_AUTHOR_NAME='zhukewei', GIT_AUTHOR_EMAIL='kewei.zhu@outlook.com',
               GIT_COMMITTER_NAME='zhukewei', GIT_COMMITTER_EMAIL='kewei.zhu@outlook.com')
    def fixture_git(*args):
        subprocess.run(['git', '-c', 'core.hooksPath=' + os.devnull, '-c', 'core.fsmonitor=false',
                        '-c', 'core.autocrlf=false', *args], cwd=root, env=env,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
    fixture_git('init', '-q')
    fixture_git('add', 'onboarding.md', 'policy.md', 'support.md', 'sourceledger.json')
    fixture_git('commit', '-qm', 'Create disposable handbook fixture')
    accept(root, check(root)['review_token'])
    fixture_git('mv', 'policy.md', 'access-policy.md')
    print('After git mv, check reports:', check(root)['summary'])
    watched = [root / 'sourceledger.json', root / '.git/index', root / '.sourceledger/state.sqlite3']
    before = [path.read_bytes() for path in watched]
    print(render_renames(suggest_renames(root)))
    assert [path.read_bytes() for path in watched] == before, 'Suggestion changed persistent state'
    print('Verified manifest, Git index and baseline database stayed byte-identical. All fixture files were temporary.')
