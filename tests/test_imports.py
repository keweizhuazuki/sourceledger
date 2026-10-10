"""Explicit imports preserve provenance without inventing acceptances."""
import contextlib
from concurrent.futures import ThreadPoolExecutor
import io
import json
import runpy
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from sourceledger.core import LedgerError, accept, check, connect, history
from sourceledger.snapshots import export_baseline, check_baseline
from sourceledger.imports import preview_import, apply_import
from sourceledger.cli import main, render_history


class ImportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.author = self.base / 'author'
        self.author.mkdir()
        self.dep = {'note': 'note.md', 'source': 'source.md'}
        for name, value in [('note.md', 'Reviewed note'), ('source.md', 'Accepted source'),
                            ('sourceledger.json', json.dumps({'version': 1, 'dependencies': [self.dep]}))]:
            (self.author / name).write_text(value, encoding='utf-8')
        accept(self.author, check(self.author)['review_token'])
        self.payload = export_baseline(self.author)
        self.snapshot = self.base / 'baseline.json'
        self.snapshot.write_text(json.dumps(self.payload), encoding='utf-8')
        self.root = self.base / 'destination'
        shutil.copytree(self.author, self.root, ignore=shutil.ignore_patterns('.sourceledger'))

    def token(self):
        return preview_import(self.root, self.snapshot)['import_token']

    def rows(self):
        with contextlib.closing(sqlite3.connect(self.root / '.sourceledger/state.sqlite3')) as db:
            return {name: db.execute('SELECT count(*) FROM ' + name).fetchone()[0]
                    for name in ['baselines', 'acceptance_batches', 'acceptance_entries', 'baseline_imports']}

    def test_runnable_import_demo(self):
        with contextlib.redirect_stdout(io.StringIO()) as output:
            runpy.run_path(str(Path(__file__).resolve().parents[1] / 'examples/import_demo.py'))
        self.assertIn('current edits still need local review', output.getvalue())

    def test_revalidation_after_preflight_rejects_snapshot_change(self):
        from sourceledger import imports
        token = self.token()
        original = imports.connect
        def changed_connect(root):
            data = json.loads(self.snapshot.read_text())
            data['dependencies'][0]['note_hash'] = '0' * 64
            self.snapshot.write_text(json.dumps(data))
            return original(root)
        with patch('sourceledger.imports.connect', side_effect=changed_connect):
            with self.assertRaises(LedgerError):
                apply_import(self.root, self.snapshot, token)
        self.assertEqual(set(self.rows().values()), {0})

    def test_failed_schema_two_migration_preserves_schema_one(self):
        accept(self.root, check(self.root)['review_token'])
        old = history(self.root)['batches']
        with contextlib.closing(connect(self.root)) as db, db:
            db.execute('DROP TABLE baseline_imports')
            db.execute('PRAGMA user_version=1')
        original = sqlite3.connect
        def guarded(*args, **kwargs):
            db = original(*args, **kwargs)
            db.set_authorizer(lambda action, name, *_: sqlite3.SQLITE_DENY if action == sqlite3.SQLITE_CREATE_TABLE and name == 'baseline_imports' else sqlite3.SQLITE_OK)
            return db
        with patch('sourceledger.core.sqlite3.connect', side_effect=guarded):
            with self.assertRaises(sqlite3.DatabaseError):
                connect(self.root)
        with contextlib.closing(original(self.root / '.sourceledger/state.sqlite3')) as db:
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 1)
            self.assertEqual(db.execute('SELECT count(*) FROM acceptance_batches').fetchone()[0], 1)
        self.assertEqual(history(self.root)['batches'], old)

    def test_preview_no_writes_and_exact_source_evidence(self):
        before = {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        report = preview_import(self.root, self.snapshot)
        self.assertEqual(report['dependencies'], self.payload['dependencies'])
        self.assertEqual(report['dependency_count'], 1)
        self.assertNotIn('review_token', report)
        self.assertEqual({p.relative_to(self.root): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}, before)
        self.assertFalse((self.root / '.sourceledger').exists())

    def test_invalid_token_does_not_create_storage(self):
        with self.assertRaises(LedgerError):
            apply_import(self.root, self.snapshot, 'incorrect')
        self.assertFalse((self.root / '.sourceledger').exists())

    def test_success_records_import_not_acceptance_and_later_acceptance_is_real(self):
        token = self.token()
        self.assertEqual(apply_import(self.root, self.snapshot, token), 1)
        self.assertEqual(self.rows(), {'baselines': 1, 'acceptance_batches': 0, 'acceptance_entries': 0, 'baseline_imports': 1})
        report = history(self.root)
        self.assertEqual(report['batches'], [])
        imported = report['imports'][0]
        self.assertEqual(imported['dependencies'], self.payload['dependencies'])
        self.assertIn('not an original acceptance time', render_history(report))
        self.assertEqual(check(self.root)['summary']['current'], 1)
        (self.root / 'source.md').write_text('Later source', encoding='utf-8')
        accept(self.root, check(self.root)['review_token'])
        report = history(self.root)
        self.assertEqual(report['imports'][0], imported)
        self.assertEqual(report['batches'][0]['dependencies'][0]['before'], 'Accepted source')
        self.assertEqual(report['batches'][0]['dependencies'][0]['revision'], 2)
        self.assertEqual(export_baseline(self.root)['dependencies'][0]['accepted'], 'Later source')

    def test_import_does_not_accept_current_edits_or_need_current_files(self):
        token = self.token()
        (self.root / 'source.md').write_text('Unaccepted current source', encoding='utf-8')
        (self.root / 'note.md').unlink()
        apply_import(self.root, self.snapshot, token)
        self.assertEqual(check(self.root)['summary']['error'], 1)
        (self.root / 'note.md').write_text('Different note', encoding='utf-8')
        report = check(self.root)
        self.assertEqual(report['summary']['changed'], 1)
        self.assertTrue(report['dependencies'][0]['note_changed'])

    def test_snapshot_or_manifest_change_invalidates_preview(self):
        token = self.token()
        changed = json.loads(json.dumps(self.payload))
        changed['dependencies'][0]['note_hash'] = '0' * 64
        self.snapshot.write_text(json.dumps(changed))
        with self.assertRaises(LedgerError):
            apply_import(self.root, self.snapshot, token)
        self.assertFalse((self.root / '.sourceledger').exists())
        self.snapshot.write_text(json.dumps(self.payload))
        (self.root / 'sourceledger.json').write_text(json.dumps({'version': 1, 'dependencies': [self.dep, {'note':'extra.md','source':'extra-source.md'}]}))
        with self.assertRaises(LedgerError):
            apply_import(self.root, self.snapshot, token)
        self.assertFalse((self.root / '.sourceledger').exists())

    def test_nonempty_existing_baselines_and_history_never_replaced(self):
        token = self.token()
        accept(self.root, check(self.root)['review_token'])
        before = history(self.root)
        with self.assertRaises(LedgerError):
            apply_import(self.root, self.snapshot, token)
        with self.assertRaises(LedgerError):
            preview_import(self.root, self.snapshot)
        self.assertEqual(history(self.root), before)

    def test_history_only_ledger_is_not_empty(self):
        accept(self.root, check(self.root)['review_token'])
        with contextlib.closing(connect(self.root)) as db, db:
            db.execute('DELETE FROM baselines')
        with self.assertRaises(LedgerError):
            preview_import(self.root, self.snapshot)

    def test_failed_provenance_insert_rolls_back_every_row(self):
        with contextlib.closing(connect(self.root)) as db, db:
            db.execute("CREATE TRIGGER reject_import BEFORE INSERT ON baseline_imports BEGIN SELECT RAISE(ABORT,'test failure'); END")
        token = self.token()
        with self.assertRaises((LedgerError, sqlite3.Error)):
            apply_import(self.root, self.snapshot, token)
        self.assertEqual(set(self.rows().values()), {0})

    def test_concurrent_import_applies_once(self):
        token = self.token()
        def attempt(_):
            try:
                apply_import(self.root, self.snapshot, token)
                return 'imported'
            except LedgerError:
                return 'rejected'
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(attempt, range(2)))
        self.assertEqual(sorted(results), ['imported', 'rejected'])
        self.assertEqual(self.rows()['baseline_imports'], 1)
        self.assertEqual(self.rows()['acceptance_batches'], 0)

    def test_cli_preview_then_apply_and_no_snapshot_mode_regression(self):
        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main(['--root', str(self.root), 'import-baseline', str(self.snapshot), '--format', 'json']), 0)
        token = json.loads(output.getvalue())['import_token']
        self.assertFalse((self.root / '.sourceledger').exists())
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(['--root', str(self.root), 'import-baseline', str(self.snapshot), '--token', token]), 0)
        with patch('sqlite3.connect', side_effect=AssertionError('No SQLite in snapshot checks')):
            self.assertNotIn('review_token', check_baseline(self.root, self.snapshot))

    def test_import_provenance_filter_survives_removed_files(self):
        apply_import(self.root, self.snapshot, self.token())
        for name in ['sourceledger.json', 'source.md', 'note.md']:
            (self.root / name).unlink()
        self.assertEqual(len(history(self.root, 'note.md')['imports']), 1)
        self.assertEqual(history(self.root, 'other.md')['imports'], [])

    def test_preview_empty_legacy_database_does_not_migrate(self):
        directory = self.root / '.sourceledger'; directory.mkdir()
        dbpath = directory / 'state.sqlite3'
        with contextlib.closing(sqlite3.connect(dbpath)) as db:
            db.execute('CREATE TABLE baselines (key TEXT PRIMARY KEY, content TEXT NOT NULL, note_hash TEXT NOT NULL, revision INTEGER NOT NULL)')
        before = dbpath.read_bytes()
        self.token()
        self.assertEqual(dbpath.read_bytes(), before)
        apply_import(self.root, self.snapshot, self.token())
        self.assertEqual(self.rows()['baseline_imports'], 1)

    def test_filtered_import_provenance_repeats_outside_batch_pagination(self):
        other = {'note': 'other.md', 'source': 'source.md'}
        for root in (self.author, self.root):
            (root / 'other.md').write_text('Another note')
            (root / 'sourceledger.json').write_text(json.dumps({'version': 1, 'dependencies': [self.dep, other]}))
        accept(self.author, check(self.author)['review_token'])
        self.snapshot.write_text(json.dumps(export_baseline(self.author)))
        apply_import(self.root, self.snapshot, self.token())
        for _ in range(2):
            accept(self.root, check(self.root)['review_token'])
        first = history(self.root, 'other.md', limit=1)
        second = history(self.root, 'other.md', limit=1, before=first['next_before'])
        self.assertEqual(first['imports'], second['imports'])
        self.assertEqual(first['imports'][0]['dependency_count'], 2)
        self.assertEqual(len(first['imports'][0]['dependencies']), 1)
        self.assertEqual(first['imports'][0]['dependencies'][0]['dependency']['note'], 'other.md')

    def test_preview_wal_rejected_without_sidecar_creation(self):
        with contextlib.closing(connect(self.root)) as db:
            db.execute('PRAGMA journal_mode=WAL')
        directory = self.root / '.sourceledger'
        before = {p.name: p.read_bytes() for p in directory.iterdir()}
        with self.assertRaisesRegex(LedgerError, 'WAL'):
            self.token()
        self.assertEqual({p.name: p.read_bytes() for p in directory.iterdir()}, before)

    def test_previous_import_provenance_alone_prevents_reimport(self):
        apply_import(self.root, self.snapshot, self.token())
        with contextlib.closing(connect(self.root)) as db, db:
            db.execute('DELETE FROM baselines')
        with self.assertRaises(LedgerError):
            self.token()
        self.assertEqual(len(history(self.root)['imports']), 1)

    def test_existing_schema_one_preview_does_not_migrate(self):
        with contextlib.closing(connect(self.root)) as db, db:
            db.execute('DROP TABLE baseline_imports')
            db.execute('PRAGMA user_version=1')
        path = self.root / '.sourceledger/state.sqlite3'
        before = path.read_bytes()
        self.token()
        self.assertEqual(path.read_bytes(), before)

    def test_schema_one_migration_preserves_all_records(self):
        accept(self.root, check(self.root)['review_token'])
        before = history(self.root)['batches']
        with contextlib.closing(connect(self.root)) as db, db:
            db.execute('DROP TABLE baseline_imports')
            db.execute('PRAGMA user_version=1')
        self.assertEqual(history(self.root)['batches'], before)
        self.assertEqual(history(self.root)['imports'], [])


if __name__ == '__main__':
    unittest.main()
