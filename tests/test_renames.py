import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from sourceledger.core import LedgerError, accept, check, digest, safe_path
from sourceledger.renames import git_read, staged_entries, suggest_renames
from sourceledger.cli import main


@unittest.skipUnless(shutil.which('git'), 'Git is unavailable')
class RenameTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.env = {key: value for key, value in os.environ.items() if not key.startswith('GIT_')}
        self.env.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM='1',
                        GIT_AUTHOR_NAME='zhukewei', GIT_AUTHOR_EMAIL='kewei.zhu@outlook.com',
                        GIT_COMMITTER_NAME='zhukewei', GIT_COMMITTER_EMAIL='kewei.zhu@outlook.com')
        self.git('init', '-q')
        self.write('note.md', 'See policy.md')
        self.write('policy.md', '## Access\n30 days\n')
        self.write('sourceledger.json', json.dumps({'version': 1, 'dependencies': [{'note': 'note.md', 'source': 'policy.md', 'heading': 'Access'}]}))
        self.git('add', 'note.md', 'policy.md', 'sourceledger.json')
        self.git('commit', '-qm', 'fixture')

    def write(self, name, text):
        (self.root / name).write_text(text, encoding='utf-8')

    def git(self, *args):
        return subprocess.run(['git', '-c', 'core.fsmonitor=false', '-c', 'core.hooksPath=' + os.devnull, '-c', 'core.autocrlf=false', *args], cwd=self.root, env=self.env, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout

    def files(self, directory):
        return {path.relative_to(directory).as_posix(): path.read_bytes() for path in directory.rglob('*') if path.is_file()}

    def test_staged_source_rename_is_suggested_without_any_state_change(self):
        accept(self.root, check(self.root)['review_token'])
        self.git('mv', 'policy.md', 'access-policy.md')
        before = self.files(self.root)
        report = suggest_renames(self.root)
        self.assertEqual(report['suggestions'][0]['candidates'][0]['path'], 'access-policy.md')
        self.assertFalse(report['suggestions'][0]['ambiguous'])
        self.assertEqual(self.files(self.root), before)
        self.assertEqual(check(self.root)['summary']['error'], 1)

    def test_missing_note_and_source_are_reported_independently(self):
        self.git('mv', 'policy.md', 'new-policy.md')
        self.git('mv', 'note.md', 'new-note.md')
        report = suggest_renames(self.root)
        self.assertEqual({item['missing_path'] for item in report['suggestions']}, {'note.md', 'policy.md'})
        self.assertTrue(all(len(item['candidates']) == 1 for item in report['suggestions']))
        self.assertFalse((self.root / '.sourceledger').exists())

    def test_identical_added_files_are_all_ambiguous_candidates(self):
        self.git('mv', 'policy.md', 'first.md')
        shutil.copyfile(self.root / 'first.md', self.root / 'second.md')
        self.git('add', 'second.md')
        item = suggest_renames(self.root)['suggestions'][0]
        self.assertEqual([row['path'] for row in item['candidates']], ['first.md', 'second.md'])
        self.assertTrue(item['ambiguous'])

    def test_multiple_deleted_copies_make_one_destination_ambiguous(self):
        shutil.copyfile(self.root / 'policy.md', self.root / 'copy.md')
        self.git('add', 'copy.md'); self.git('commit', '-qm', 'add identical source')
        self.git('mv', 'policy.md', 'new.md'); self.git('rm', '-q', 'copy.md')
        self.assertTrue(suggest_renames(self.root)['suggestions'][0]['ambiguous'])

    def test_edited_staged_move_and_untracked_move_are_not_guessed(self):
        (self.root / 'policy.md').rename(self.root / 'new.md')
        self.assertEqual(suggest_renames(self.root)['suggestions'][0]['candidates'], [])
        self.write('new.md', '## Access\n14 days\n')
        self.git('add', '-A')
        self.assertEqual(suggest_renames(self.root)['suggestions'][0]['candidates'], [])

    def test_committed_move_is_explicitly_out_of_scope(self):
        self.git('mv', 'policy.md', 'new.md'); self.git('commit', '-qm', 'move source')
        item = suggest_renames(self.root)['suggestions'][0]
        self.assertEqual(item['candidates'], [])
        self.assertIn('not a staged', item['reason'])

    def test_current_missing_section_is_not_suggested(self):
        self.git('mv', 'policy.md', 'new.md')
        self.write('new.md', '# Something else\n')
        item = suggest_renames(self.root)['suggestions'][0]
        self.assertEqual(item['candidates'], [])
        self.assertIn('Missing ATX', item['skipped_candidates'][0]['reason'])

    def test_unstaged_destination_edits_are_not_claimed_as_staged_content(self):
        self.git('mv', 'policy.md', 'new.md')
        original = suggest_renames(self.root)['suggestions'][0]['candidates'][0]
        self.write('new.md', '## Access\n14 days\n')
        edited = suggest_renames(self.root)['suggestions'][0]['candidates'][0]
        self.assertEqual(edited['staged_blob'], original['staged_blob'])
        self.assertEqual(edited['working_text_sha256'], digest('## Access\n14 days\n'))
        self.assertNotEqual(edited['working_text_sha256'], original['working_text_sha256'])
        (self.root / 'new.md').unlink()
        self.assertEqual(suggest_renames(self.root)['suggestions'][0]['candidates'], [])

    def test_staged_symlink_destination_is_not_a_regular_file_candidate(self):
        self.git('mv', 'policy.md', 'new.md')
        (self.root / 'new.md').unlink()
        try:
            (self.root / 'new.md').symlink_to('note.md')
        except OSError:
            self.skipTest('Symlink creation unavailable')
        self.git('add', 'new.md')
        self.assertEqual(suggest_renames(self.root)['suggestions'][0]['candidates'], [])

    def test_sha256_repository_blob_identity(self):
        self.root = self.root / 'sha256'
        self.root.mkdir()
        try:
            self.git('init', '-q', '--object-format=sha256')
        except subprocess.CalledProcessError:
            self.skipTest('Installed Git lacks SHA-256 repository support')
        self.write('note.md', 'Note')
        self.write('policy.md', 'Source')
        self.write('sourceledger.json', json.dumps({'version': 1, 'dependencies': [{'note': 'note.md', 'source': 'policy.md'}]}))
        self.git('add', 'note.md', 'policy.md', 'sourceledger.json')
        self.git('commit', '-qm', 'SHA-256 fixture')
        self.git('mv', 'policy.md', 'new.md')
        report = suggest_renames(self.root)
        self.assertEqual(len(report['head']), 64)
        self.assertEqual(len(report['suggestions'][0]['candidates'][0]['staged_blob']), 64)

    def test_existing_paths_are_not_rename_suggestions(self):
        self.assertEqual(suggest_renames(self.root)['suggestions'], [])

    def test_diff_relative_configuration_cannot_change_path_base(self):
        (self.root / 'kb').mkdir()
        for name in ('note.md', 'policy.md', 'sourceledger.json'):
            self.git('mv', name, 'kb/' + name)
        self.git('commit', '-qm', 'place knowledge base in folder')
        self.git('mv', 'kb/policy.md', 'kb/new.md')
        self.git('config', 'diff.relative', 'true')
        item = suggest_renames(self.root / 'kb')['suggestions'][0]
        self.assertEqual(item['candidates'][0]['path'], 'new.md')

    def test_symlink_parent_path_keeps_original_manifest_semantics(self):
        (self.root / 'a/nested').mkdir(parents=True)
        self.write('a/policy.md', '## Access\nExisting real source\n')
        try:
            (self.root / 'alias').symlink_to(self.root / 'a/nested', target_is_directory=True)
        except OSError:
            self.skipTest('Symlink creation unavailable')
        self.write('sourceledger.json', json.dumps({'version': 1, 'dependencies': [{'note': 'note.md', 'source': 'alias/../policy.md', 'heading': 'Access'}]}))
        self.git('mv', 'policy.md', 'new.md')
        report = suggest_renames(self.root)
        if safe_path(self.root, 'alias/../policy.md').exists():
            self.assertEqual(report['suggestions'], [])
        else:
            # Windows may normalize '..' before following the junction/symlink.
            self.assertEqual(report['suggestions'][0]['candidates'], [])
            self.assertIn('symlinks', report['suggestions'][0]['reason'])

    def test_missing_symlink_based_path_is_not_reinterpreted_as_git_path(self):
        (self.root / 'a/nested').mkdir(parents=True)
        try:
            (self.root / 'alias').symlink_to(self.root / 'a/nested', target_is_directory=True)
        except OSError:
            self.skipTest('Symlink creation unavailable')
        self.write('sourceledger.json', json.dumps({'version': 1, 'dependencies': [{'note': 'note.md', 'source': 'alias/../policy.md', 'heading': 'Access'}]}))
        self.git('mv', 'policy.md', 'new.md')
        item = suggest_renames(self.root)['suggestions'][0]
        self.assertEqual(item['missing_path'], 'alias/../policy.md')
        self.assertEqual(item['candidates'], [])
        self.assertIn('symlinks', item['reason'])

    def test_subdirectory_root_does_not_expose_outside_candidates(self):
        (self.root / 'kb').mkdir()
        for name in ('note.md', 'policy.md', 'sourceledger.json'):
            self.git('mv', name, 'kb/' + name)
        self.git('commit', '-qm', 'place knowledge base in folder')
        self.git('mv', 'kb/policy.md', 'outside.md')
        report = suggest_renames(self.root / 'kb')
        self.assertEqual(report['suggestions'][0]['candidates'], [])
        self.assertNotIn('outside.md', json.dumps(report))

    def test_unicode_spaces_and_pathspec_characters(self):
        self.git('mv', 'policy.md', '政策 [old].md')
        self.assertEqual(suggest_renames(self.root)['suggestions'][0]['candidates'][0]['path'], '政策 [old].md')

    def test_git_extension_hooks_are_disabled(self):
        marker = self.root / 'hook-ran'
        hook = self.root / 'trap.sh'
        hook.write_text('#!/bin/sh\ntouch "' + marker.as_posix() + '"\n', encoding='utf-8')
        hook.chmod(0o755)
        self.git('config', 'core.fsmonitor', str(hook))
        self.git('config', 'diff.external', str(hook))
        self.git('config', 'diff.trap.textconv', str(hook))
        self.write('.gitattributes', '*.md diff=trap\n')
        self.git('mv', 'policy.md', 'new.md')
        self.assertFalse(marker.exists())
        suggest_renames(self.root)
        self.assertFalse(marker.exists())

    def test_cli_json_and_non_repository_failure(self):
        self.git('mv', 'policy.md', 'new.md')
        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main(['--root', str(self.root), 'suggest-renames', '--format', 'json']), 0)
        self.assertEqual(json.loads(output.getvalue())['kind'], 'sourceledger-rename-suggestions')
        with tempfile.TemporaryDirectory() as other:
            root = Path(other)
            (root / 'sourceledger.json').write_text((self.root / 'sourceledger.json').read_text(), encoding='utf-8')
            with self.assertRaises(LedgerError):
                suggest_renames(root)


class GitSafetyTests(unittest.TestCase):
    def test_child_environment_disables_network_optional_writes_and_inherited_overrides(self):
        result = subprocess.CompletedProcess([], 0, b'ok', b'')
        with patch.dict(os.environ, {'GIT_EXTERNAL_DIFF': 'unexpected', 'GIT_TRACE': '/tmp/unwanted-trace'}), patch('sourceledger.renames.subprocess.run', return_value=result) as run:
            self.assertEqual(git_read(Path('.'), 'rev-parse', '--verify', 'HEAD'), b'ok')
        command = run.call_args.args[0]
        env = run.call_args.kwargs['env']
        self.assertIn('core.fsmonitor=false', command)
        self.assertEqual(env['GIT_OPTIONAL_LOCKS'], '0')
        self.assertEqual(env['GIT_NO_LAZY_FETCH'], '1')
        self.assertEqual(env['GIT_ALLOW_PROTOCOL'], '')
        self.assertNotIn('GIT_EXTERNAL_DIFF', env)
        self.assertNotIn('GIT_TRACE', env)
        self.assertEqual(run.call_args.kwargs['timeout'], 10)

    def test_missing_git_and_timeout_are_controlled_errors(self):
        for error in (FileNotFoundError('missing git'), subprocess.TimeoutExpired('git', 10)):
            with patch('sourceledger.renames.subprocess.run', side_effect=error), self.assertRaises(LedgerError):
                git_read(Path('.'), 'rev-parse', 'HEAD')

    def test_raw_diff_parser_handles_sha256_and_rejects_malformed_data(self):
        raw = (':100644 000000 ' + 'a' * 64 + ' ' + '0' * 64 + ' D').encode() + b'\0file.md\0'
        self.assertEqual(staged_entries(raw)[0]['old_blob'], 'a' * 64)
        for malformed in (b'not terminated', b'header\0', b'bad\0path\0'):
            with self.assertRaises(LedgerError):
                staged_entries(malformed)


if __name__ == '__main__':
    unittest.main()
