"""Portable accepted baselines: synthetic fixtures only."""
import contextlib
import io
import json
import runpy
import sqlite3
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from sourceledger.core import LedgerError, accept, canonical, check, digest
from sourceledger.cli import main, render_html, render_text
from sourceledger.snapshots import export_baseline, check_baseline


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.dep = {'note': 'note.md', 'source': 'source.md', 'heading': 'Access'}
        self.write('note.md', '# Note\n')
        self.write('source.md', '# Policy\n## Access\n30 days.\n## Other\nOld.\n')
        self.manifest([self.dep])
        accept(self.root, check(self.root)['review_token'])
        self.snapshot = export_baseline(self.root)
        self.file = self.root / 'baseline.json'
        self.save(self.snapshot)

    def write(self, name, text):
        (self.root / name).write_text(text, encoding='utf-8')

    def manifest(self, dependencies):
        self.write('sourceledger.json', json.dumps({'version': 1, 'dependencies': dependencies}))

    def save(self, snapshot):
        self.file.write_text(json.dumps(snapshot, ensure_ascii=False), encoding='utf-8')

    def report(self):
        return check_baseline(self.root, self.file)

    def test_runnable_synthetic_demo(self):
        with contextlib.redirect_stdout(io.StringIO()) as output:
            runpy.run_path(str(Path(__file__).resolve().parents[1] / 'examples/baseline_demo.py'))
        self.assertIn('no local database or acceptance token', output.getvalue())

    def test_export_accepted_data_only_and_deterministic(self):
        before = (self.root / '.sourceledger/state.sqlite3').read_bytes()
        self.write('source.md', '# Policy\n## Access\nUNACCEPTED\n')
        self.write('note.md', 'UNACCEPTED NOTE')
        self.assertEqual(export_baseline(self.root), self.snapshot)
        (self.root / 'source.md').unlink()
        (self.root / 'note.md').unlink()
        self.assertEqual(export_baseline(self.root), self.snapshot)
        self.assertNotIn('UNACCEPTED', canonical(self.snapshot))
        self.assertEqual((self.root / '.sourceledger/state.sqlite3').read_bytes(), before)

    def test_export_missing_store_does_not_create_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'sourceledger.json').write_text(json.dumps({'version': 1, 'dependencies': [self.dep]}))
            with self.assertRaises(LedgerError):
                export_baseline(root)
            self.assertFalse((root / '.sourceledger').exists())

    def test_export_incomplete_coverage_refuses(self):
        self.manifest([self.dep, {'note': 'new.md', 'source': 'new-source.md'}])
        with self.assertRaises(LedgerError):
            export_baseline(self.root)

    def test_snapshot_mode_never_opens_sqlite_or_accepts(self):
        db = self.root / '.sourceledger/state.sqlite3'
        db.write_bytes(b'broken local database must not be read')
        with patch('sqlite3.connect', side_effect=AssertionError('Database access forbidden')):
            report = self.report()
        self.assertEqual(report['summary']['current'], 1)
        self.assertNotIn('review_token', report)
        self.assertEqual(report['baseline_mode'], 'snapshot')
        self.assertIn('no local acceptance token', render_text(report))
        self.assertIn('no local acceptance token', render_html(report))
        self.assertNotIn('Review token:', render_html(report))
        self.assertEqual(db.read_bytes(), b'broken local database must not be read')

    def test_fresh_root_snapshot_check_does_not_create_storage(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ['sourceledger.json', 'source.md', 'note.md']:
                (root / name).write_bytes((self.root / name).read_bytes())
            self.assertEqual(check_baseline(root, self.file)['summary']['current'], 1)
            self.assertFalse((root / '.sourceledger').exists())

    def test_changed_unrelated_note_missing_and_duplicate_heading(self):
        self.write('source.md', '# Policy\n## Access\n30 days.\n## Other\nChanged.\n')
        self.assertEqual(self.report()['summary']['current'], 1)
        self.write('note.md', 'Edited note')
        self.assertTrue(self.report()['dependencies'][0]['note_changed'])
        self.write('source.md', '# Policy\n## Access\n14 days.\n## Access\n30 days.\n')
        self.assertEqual(self.report()['summary']['changed'], 1)
        self.write('source.md', '# Policy\n## Missing\n14 days.\n')
        self.assertEqual(self.report()['summary']['error'], 1)
        (self.root / 'source.md').unlink()
        self.assertEqual(self.report()['summary']['error'], 1)

    def test_manifest_additions_and_removals_are_visible(self):
        new = {'note': 'note.md', 'source': 'new.md'}
        self.write('new.md', 'new source')
        self.manifest([new])
        report = self.report()
        self.assertEqual(report['summary']['new'], 1)
        self.assertEqual(len(report['removed_dependencies']), 1)
        self.assertIn('No longer tracked:', render_text(report))
        self.assertIn('No longer tracked:', render_html(report))
        self.assertEqual(check_baseline(self.root, self.file, 'note.md')['summary']['new'], 1)

    def test_cli_exit_codes_and_exclusive_export(self):
        out = self.root / 'export.json'
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            args = ['--root', str(self.root)]
            self.assertEqual(main(args + ['export-baseline', '--output', str(out)]), 0)
            before = out.read_bytes()
            self.assertEqual(before, (canonical(self.snapshot) + '\n').encode('utf-8'))
            self.assertEqual(main(args + ['export-baseline', '--output', str(out)]), 2)
            self.assertEqual(out.read_bytes(), before)
            self.assertEqual(main(args + ['check', '--baseline', str(out)]), 0)
            self.write('source.md', '# Policy\n## Access\n14 days.\n')
            for fmt in ['text', 'json', 'html']:
                self.assertEqual(main(args + ['check', '--baseline', str(out), '--format', fmt]), 1)
            (self.root / 'source.md').unlink()
            self.assertEqual(main(args + ['check', '--baseline', str(out)]), 2)

    def test_strict_format_rejects_bad_types_hashes_and_duplicates(self):
        mutations = [
            lambda d: d.update(version=True), lambda d: d.update(version=999),
            lambda d: d.update(kind='sourceledger-discovery'), lambda d: d.update(extra='field'),
            lambda d: d.update(dependencies='wrong'),
            lambda d: d['dependencies'].append(d['dependencies'][0]),
            lambda d: d['dependencies'][0].update(source_hash='0' * 64),
            lambda d: d['dependencies'][0].update(note_hash='not-a-hash'),
            lambda d: d['dependencies'][0].update(accepted=42),
            lambda d: d['dependencies'][0]['dependency'].update(source='../outside.md'),
            lambda d: d['dependencies'][0]['dependency'].update(occurrence=True),
        ]
        for mutate in mutations:
            data = json.loads(json.dumps(self.snapshot))
            mutate(data)
            self.save(data)
            with self.subTest(data=data), self.assertRaises(LedgerError):
                self.report()
        self.file.write_text('{"kind":"sourceledger-baseline","version":1,"version":1,"dependencies":[]}')
        with self.assertRaises(LedgerError):
            self.report()

    def test_oversized_and_non_utf8_files_are_rejected(self):
        self.file.write_bytes(b'x' * (8 * 1024 * 1024 + 1))
        with self.assertRaises(LedgerError):
            self.report()
        self.file.write_bytes(b'\xff')
        with self.assertRaises(LedgerError):
            self.report()

    def test_export_size_bound_includes_output_newline(self):
        size = len(canonical(self.snapshot).encode('utf-8')) + 1
        with patch('sourceledger.snapshots.MAX_SNAPSHOT_BYTES', size):
            self.assertEqual(export_baseline(self.root), self.snapshot)
        with patch('sourceledger.snapshots.MAX_SNAPSHOT_BYTES', size - 1):
            with self.assertRaises(LedgerError):
                export_baseline(self.root)

    def test_export_rejects_wal_without_creating_sidecars(self):
        dbpath = self.root / '.sourceledger/state.sqlite3'
        with contextlib.closing(sqlite3.connect(dbpath)) as db:
            self.assertEqual(db.execute('PRAGMA journal_mode=WAL').fetchone()[0], 'wal')
        before = {p.name: p.read_bytes() for p in dbpath.parent.iterdir()}
        with self.assertRaisesRegex(LedgerError, 'WAL'):
            export_baseline(self.root)
        self.assertEqual({p.name: p.read_bytes() for p in dbpath.parent.iterdir()}, before)

    def test_legacy_export_does_not_migrate_or_fabricate_history(self):
        dbpath = self.root / '.sourceledger/state.sqlite3'
        with contextlib.closing(sqlite3.connect(dbpath)) as db:
            db.executescript('DROP TABLE acceptance_entries; DROP TABLE acceptance_batches; PRAGMA user_version=0;')
        before = dbpath.read_bytes()
        self.assertEqual(export_baseline(self.root), self.snapshot)
        self.assertEqual(dbpath.read_bytes(), before)

    def test_export_rejects_future_schema_without_mutation(self):
        dbpath = self.root / '.sourceledger/state.sqlite3'
        with contextlib.closing(sqlite3.connect(dbpath)) as db:
            db.execute('PRAGMA user_version=99')
        before = dbpath.read_bytes()
        with self.assertRaises(LedgerError):
            export_baseline(self.root)
        self.assertEqual(dbpath.read_bytes(), before)

    def test_invalid_nested_unicode_and_entry_bounds(self):
        for raw in ['[' * 2000 + ']' * 2000,
                    '{"kind":"sourceledger-baseline","version":1,"dependencies":[]}']:
            self.file.write_text(raw, encoding='utf-8')
            with self.assertRaises(LedgerError):
                self.report()
        for text in ['\ud800', 'x' * (2 * 1024 * 1024 + 1)]:
            data = json.loads(json.dumps(self.snapshot))
            data['dependencies'][0]['accepted'] = text
            self.file.write_text(json.dumps(data), encoding='utf-8')
            with self.assertRaises(LedgerError):
                self.report()
        self.save(self.snapshot)
        with patch('sourceledger.snapshots.MAX_ENTRIES', 0):
            with self.assertRaises(LedgerError):
                self.report()

    def test_hashes_are_integrity_not_authentication(self):
        row = self.snapshot['dependencies'][0]
        row['accepted'] = 'Deliberately changed snapshot'
        row['source_hash'] = digest(row['accepted'])
        self.save(self.snapshot)
        # A self-consistent modified snapshot is valid: trust must come from its provenance.
        self.assertEqual(self.report()['summary']['changed'], 1)


if __name__ == '__main__':
    unittest.main()
