import contextlib
import io
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import os
import tempfile
import unittest
from unittest.mock import patch
from sourceledger.core import LedgerError, accept, check, connect, extract, sections
from sourceledger.cli import main, render_html, diff


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.write('note.md', '# Note\nReview me.\n')
        self.write('source.md', '# Policy\n## Access\n30 days.\n## Equipment\nKeyboard.\n')
        self.manifest([{'note': 'note.md', 'source': 'source.md', 'heading': 'Access'}])

    def write(self, name, content):
        (self.root / name).write_text(content, encoding='utf-8')

    def manifest(self, dependencies):
        self.write('sourceledger.json', json.dumps({'version': 1, 'dependencies': dependencies}))

    def baseline(self):
        accept(self.root, check(self.root)['review_token'])

    def test_cli_invalid_roots_are_operation_errors(self):
        loop = self.root / 'loop'
        roots = [self.root / 'absent', self.root / 'note.md']
        try:
            loop.symlink_to('loop', target_is_directory=True)
        except (OSError, NotImplementedError):
            pass  # Missing and regular-file roots are still checked everywhere.
        else:
            roots.append(loop)
        for root in roots:
            with self.subTest(root=root):
                result = subprocess.run(
                    [sys.executable, '-m', 'sourceledger', '--root', str(root), 'check'],
                    capture_output=True, text=True, encoding='utf-8')
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn('sourceledger:', result.stderr)
                self.assertNotIn('Traceback', result.stderr)
                self.assertEqual(result.stdout, '')
        self.assertFalse((self.root / '.sourceledger').exists())

    def test_cli_root_resolution_exceptions_are_controlled(self):
        for error in (RuntimeError('Symlink loop'), OSError('Access denied')):
            with self.subTest(error=error), patch.object(Path, 'resolve', side_effect=error):
                with contextlib.redirect_stderr(io.StringIO()) as output:
                    self.assertEqual(main(['--root', str(self.root), 'check']), 2)
                self.assertIn('sourceledger:', output.getvalue())
        self.assertFalse((self.root / '.sourceledger').exists())

    def test_accept_persists_exact_reviewed_note_hash(self):
        from sourceledger import core
        token = check(self.root)['review_token']
        original = core.inspect
        def inspect_then_edit(*args, **kwargs):
            report = original(*args, **kwargs)
            self.write('note.md', 'Concurrent note edit')
            return report
        with patch.object(core, 'inspect', side_effect=inspect_then_edit):
            accept(self.root, token)
        self.assertTrue(check(self.root)['dependencies'][0]['note_changed'])

    def test_empty_heading_closing_hashes(self):
        self.assertEqual(sections('# ###\n')[0]['heading'], '')
        self.assertEqual(extract('# ###\nbody\n', ''), '# ###\nbody\n')

    def test_html_includes_note_edit_warning(self):
        self.baseline()
        self.write('note.md', 'Edited note')
        self.assertIn('Note edited since acceptance', render_html(check(self.root)))

    def test_corrupt_database_is_controlled_cli_error(self):
        (self.root / '.sourceledger').mkdir()
        (self.root / '.sourceledger/state.sqlite3').write_bytes(b'not a database')
        with contextlib.redirect_stderr(io.StringIO()) as output:
            self.assertEqual(main(['--root', str(self.root), 'check']), 2)
        self.assertIn('sourceledger:', output.getvalue())

    def test_database_closed_when_schema_initialization_fails(self):
        fake = unittest.mock.MagicMock()
        fake.execute.side_effect = sqlite3.DatabaseError('bad schema')
        with patch('sourceledger.core.sqlite3.connect', return_value=fake):
            with self.assertRaises(sqlite3.DatabaseError):
                connect(self.root)
        fake.close.assert_called_once()

    def test_diff_without_final_newline_has_separate_lines(self):
        output = diff({'before': 'old', 'after': 'new'})
        self.assertIn('-old\n\\ No newline at end of file\n+new\n', output)
        self.assertNotIn('-old+new', output)
        self.assertIn('\\ No newline at end of file', diff({'before': 'same\n', 'after': 'same'}))

    def test_cli_redirected_output_is_utf8_under_legacy_encoding(self):
        result = subprocess.run([sys.executable, '-m', 'sourceledger', '--root', str(self.root), 'check'], capture_output=True, env={**os.environ, 'PYTHONIOENCODING': 'cp1252'})
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn('←', result.stdout.decode('utf-8'))

    def test_initial_check_does_not_accept(self):
        self.assertEqual(check(self.root)['summary']['new'], 1)
        self.assertEqual(check(self.root)['summary']['new'], 1)
        self.baseline()
        self.assertEqual(check(self.root)['summary']['current'], 1)

    def test_changed_section_is_impacted_with_before_after(self):
        self.baseline()
        self.write('source.md', '# Policy\n## Access\n14 days.\n## Equipment\nKeyboard.\n')
        row = check(self.root)['dependencies'][0]
        self.assertEqual(row['status'], 'changed')
        self.assertIn('30 days', row['before'])
        self.assertIn('14 days', row['after'])

    def test_unrelated_section_does_not_invalidate(self):
        self.baseline()
        self.write('source.md', '# Policy\n## Access\n30 days.\n## Equipment\nMouse.\n')
        self.assertEqual(check(self.root)['summary']['current'], 1)

    def test_missing_source_and_section_and_note(self):
        self.baseline()
        (self.root / 'source.md').rename(self.root / 'renamed.md')
        self.assertEqual(check(self.root)['summary']['error'], 1)
        self.write('source.md', 'No heading')
        self.assertIn('Missing ATX heading', check(self.root)['dependencies'][0]['error'])
        (self.root / 'note.md').unlink()
        self.assertEqual(check(self.root)['summary']['error'], 1)

    def test_duplicate_headings_are_explicit(self):
        text = '# A\none\n## Child\nchild\n# A\ntwo\n'
        self.assertEqual(extract(text, 'A', 2), '# A\ntwo\n')
        self.assertIn('child', extract(text, 'A', 1))
        with self.assertRaises(LedgerError):
            extract(text, 'A', 3)

    def test_fenced_fake_headings_ignored(self):
        text = '```md\n# Fake\n```\n# Real ###\nyes\n~~~\n# Fake\n~~~\n'
        self.assertEqual([item['heading'] for item in sections(text)], ['Real'])

    def test_stale_token_on_source_note_and_baseline(self):
        token = check(self.root)['review_token']
        self.write('note.md', '# Note\nEdited\n')
        with self.assertRaises(LedgerError):
            accept(self.root, token)
        token = check(self.root)['review_token']
        accept(self.root, token)
        with self.assertRaises(LedgerError):
            accept(self.root, token)
        token = check(self.root)['review_token']
        self.write('source.md', '## Access\nnew')
        with self.assertRaises(LedgerError):
            accept(self.root, token)

    def test_accept_error_leaves_all_baselines_untouched(self):
        self.manifest([{'note': 'note.md', 'source': 'source.md'}, {'note': 'note.md', 'source': 'missing.md'}])
        report = check(self.root)
        with self.assertRaises(LedgerError):
            accept(self.root, report['review_token'])
        with contextlib.closing(connect(self.root)) as db, db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM baselines').fetchone()[0], 0)

    def test_sql_failure_rolls_back_entire_batch(self):
        self.write('other.md', 'Other')
        self.manifest([{'note': 'note.md', 'source': 'source.md'}, {'note': 'note.md', 'source': 'other.md'}])
        report = check(self.root)
        with contextlib.closing(connect(self.root)) as db, db:
            db.execute("CREATE TRIGGER reject_second BEFORE INSERT ON baselines WHEN (SELECT COUNT(*) FROM baselines) > 0 BEGIN SELECT RAISE(ABORT,'test failure'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            accept(self.root, report['review_token'])
        with contextlib.closing(connect(self.root)) as db, db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM baselines').fetchone()[0], 0)

    def test_selected_note_acceptance(self):
        self.write('second.md', 'Second note')
        self.manifest([{'note': 'note.md', 'source': 'source.md'}, {'note': 'second.md', 'source': 'source.md'}])
        accept(self.root, check(self.root, 'note.md')['review_token'], 'note.md')
        self.assertEqual(check(self.root)['summary'], {'new': 1, 'changed': 0, 'current': 1, 'error': 0})

    def test_path_escape_rejected(self):
        self.manifest([{'note': 'note.md', 'source': '../outside.md'}])
        with self.assertRaises(LedgerError):
            check(self.root)

    def test_symlink_escape_rejected(self):
        try:
            (self.root / 'escape').symlink_to(self.root.parent, target_is_directory=True)
        except OSError:
            self.skipTest('Symlink creation unavailable')
        self.manifest([{'note': 'note.md', 'source': 'escape/outside.md'}])
        with self.assertRaises(LedgerError):
            check(self.root)

    def test_normalized_newlines(self):
        self.baseline()
        path = self.root / 'source.md'
        path.write_bytes(path.read_bytes().replace(b'\r\n', b'\n').replace(b'\n', b'\r\n'))
        self.assertEqual(check(self.root)['summary']['current'], 1)

    def test_html_escapes_source_content(self):
        self.write('source.md', '## Access\n<script>alert(1)</script>')
        rendered = render_html(check(self.root))
        self.assertNotIn('<script>', rendered)
        self.assertIn('&lt;script&gt;', rendered)
        self.assertIn("default-src 'none'", rendered)

    def test_cli_exit_codes_and_output_guard(self):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main(['--root', str(self.root), 'check']), 1)
            self.baseline()
            self.assertEqual(main(['--root', str(self.root), 'check']), 0)
            target = self.root / 'report.json'
            args = ['--root', str(self.root), 'check', '--format', 'json', '--output', str(target)]
            self.assertEqual(main(args), 0)
            self.assertEqual(main(args), 2)
            (self.root / 'source.md').unlink()
            self.assertEqual(main(['--root', str(self.root), 'check']), 2)

    def test_malformed_manifest_and_duplicate_validation(self):
        for deps in [[{'note': 'note.md', 'source': 'source.md', 'occurrence': True}], [{'note': 'note.md', 'source': 'source.md'}] * 2]:
            self.manifest(deps)
            with self.assertRaises(LedgerError):
                check(self.root)

    def test_whole_file_change_and_note_edit_signal(self):
        self.manifest([{'note': 'note.md', 'source': 'source.md'}])
        self.baseline()
        self.write('note.md', 'Edited note')
        self.write('source.md', 'Edited source')
        row = check(self.root)['dependencies'][0]
        self.assertTrue(row['note_changed'])
        self.assertEqual(row['status'], 'changed')


if __name__ == '__main__':
    unittest.main()
