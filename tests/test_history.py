import contextlib
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from sourceledger.core import LedgerError, accept, check, connect, dependency_key, digest, history
from sourceledger.cli import main, render_history


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.dep = {'note': 'note.md', 'source': 'source.md', 'heading': 'Access'}
        self.write('note.md', 'Reviewed note')
        self.write('source.md', '## Access\n30 days.\n')
        self.write('sourceledger.json', json.dumps({'version': 1, 'dependencies': [self.dep]}))

    def write(self, name, text):
        (self.root / name).write_text(text, encoding='utf-8')

    def accept(self, note=None):
        accept(self.root, check(self.root, note)['review_token'], note)

    def test_concurrent_acceptance_consumes_token_only_once(self):
        token = check(self.root)['review_token']
        def try_accept():
            try:
                accept(self.root, token)
                return 'accepted'
            except LedgerError:
                return 'stale'
        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = list(executor.map(lambda _: try_accept(), range(2)))
        self.assertEqual(sorted(outcomes), ['accepted', 'stale'])
        self.assertEqual(len(history(self.root)['batches']), 1)

    def test_failed_migration_rolls_back_schema_and_preserves_legacy_data(self):
        directory = self.root / '.sourceledger'
        directory.mkdir()
        path = directory / 'state.sqlite3'
        with contextlib.closing(sqlite3.connect(path)) as db, db:
            db.execute('CREATE TABLE baselines (key TEXT PRIMARY KEY, content TEXT NOT NULL, note_hash TEXT NOT NULL, revision INTEGER NOT NULL)')
            db.execute('INSERT INTO baselines VALUES (?,?,?,?)', (dependency_key(self.dep), 'saved source', 'saved note hash', 7))
        original = sqlite3.connect
        def guarded_connect(*args, **kwargs):
            db = original(*args, **kwargs)
            db.set_authorizer(lambda action, name, *_: sqlite3.SQLITE_DENY if action == sqlite3.SQLITE_CREATE_TABLE and name == 'acceptance_entries' else sqlite3.SQLITE_OK)
            return db
        with patch('sourceledger.core.sqlite3.connect', side_effect=guarded_connect):
            with self.assertRaises(sqlite3.DatabaseError):
                connect(self.root)
        with contextlib.closing(original(path)) as db:
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall(), [('baselines',)])
            self.assertEqual(db.execute('SELECT content,note_hash,revision FROM baselines').fetchone(), ('saved source', 'saved note hash', 7))

    def test_success_records_timestamp_scope_revision_and_exact_snapshot(self):
        self.accept('note.md')
        batch = history(self.root)['batches'][0]
        self.assertEqual(batch['scope_note'], 'note.md')
        self.assertIsNotNone(datetime.fromisoformat(batch['accepted_at']).tzinfo)
        entry = batch['dependencies'][0]
        self.assertEqual(entry['revision'], 1)
        self.assertIsNone(entry['before'])
        self.assertEqual(entry['accepted'], '## Access\n30 days.\n')
        self.assertEqual(entry['source_hash'], digest(entry['accepted']))
        self.assertEqual(entry['note_hash'], digest('Reviewed note'))

    def test_subsequent_acceptance_preserves_old_snapshot(self):
        self.accept()
        self.write('source.md', '## Access\n14 days.\n')
        self.accept()
        batches = history(self.root)['batches']
        self.assertEqual([batch['id'] for batch in batches], [2, 1])
        self.assertEqual(batches[0]['dependencies'][0]['before'], batches[1]['dependencies'][0]['accepted'])
        self.assertEqual(batches[0]['dependencies'][0]['revision'], 2)

    def test_stale_or_missing_source_acceptance_creates_no_history(self):
        with self.assertRaises(LedgerError):
            accept(self.root, 'incorrect')
        self.assertEqual(history(self.root)['batches'], [])
        (self.root / 'source.md').unlink()
        with self.assertRaises(LedgerError):
            accept(self.root, check(self.root)['review_token'])
        self.assertEqual(history(self.root)['batches'], [])

    def test_history_insert_failure_rolls_back_baseline_and_batch(self):
        self.accept()
        previous = history(self.root)
        self.write('source.md', '## Access\n14 days.\n')
        token = check(self.root)['review_token']
        with contextlib.closing(connect(self.root)) as db, db:
            db.execute("CREATE TRIGGER reject_history BEFORE INSERT ON acceptance_entries BEGIN SELECT RAISE(ABORT,'test history failure'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            accept(self.root, token)
        self.assertEqual(history(self.root), previous)
        self.assertEqual(check(self.root)['review_token'], token)

    def test_baseline_insert_failure_creates_no_batch(self):
        with contextlib.closing(connect(self.root)) as db, db:
            db.execute("CREATE TRIGGER reject_baseline BEFORE INSERT ON baselines BEGIN SELECT RAISE(ABORT,'test baseline failure'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            self.accept()
        self.assertEqual(history(self.root)['batches'], [])

    def test_migrate_legacy_database_without_inventing_history(self):
        directory = self.root / '.sourceledger'
        directory.mkdir()
        with contextlib.closing(sqlite3.connect(directory / 'state.sqlite3')) as db, db:
            db.execute('CREATE TABLE baselines (key TEXT PRIMARY KEY, content TEXT NOT NULL, note_hash TEXT NOT NULL, revision INTEGER NOT NULL)')
            db.execute('INSERT INTO baselines VALUES (?,?,?,?)', (dependency_key(self.dep), '## Access\n30 days.\n', digest('Reviewed note'), 7))
        self.assertEqual(check(self.root)['summary']['current'], 1)
        self.assertEqual(history(self.root)['batches'], [])
        self.accept()
        self.assertEqual(history(self.root)['batches'][0]['dependencies'][0]['revision'], 8)
        with contextlib.closing(connect(self.root)) as db:
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 1)

    def test_history_survives_removed_manifest_notes_and_sources(self):
        self.accept()
        for name in ('sourceledger.json', 'note.md', 'source.md'):
            (self.root / name).unlink()
        self.assertEqual(len(history(self.root, 'note.md')['batches']), 1)
        self.assertEqual(history(self.root, 'untracked.md')['batches'], [])

    def test_filter_and_stable_keyset_pagination(self):
        self.write('second.md', 'Another note')
        other = {**self.dep, 'note': 'second.md'}
        self.write('sourceledger.json', json.dumps({'version': 1, 'dependencies': [self.dep, other]}))
        self.accept()
        self.accept('second.md')
        self.accept('note.md')
        first = history(self.root, 'note.md', limit=1)
        self.assertEqual(first['batches'][0]['id'], 3)
        self.assertEqual(first['next_before'], 3)
        self.accept('note.md')
        second = history(self.root, 'note.md', limit=1, before=first['next_before'])
        self.assertEqual(second['batches'][0]['id'], 1)
        self.assertEqual(len(second['batches'][0]['dependencies']), 1)
        self.assertIsNone(second['next_before'])

    def test_invalid_pagination_rejected(self):
        for limit in (0, 101, True):
            with self.assertRaises(LedgerError):
                history(self.root, limit=limit)
        for before in (0, 9223372036854775808):
            with self.assertRaises(LedgerError):
                history(self.root, before=before)
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main(['--root', str(self.root), 'history', '--before', '9223372036854775808']), 2)

    def test_future_schema_is_rejected_without_mutation(self):
        with contextlib.closing(connect(self.root)) as db, db:
            db.execute('PRAGMA user_version=999')
        with self.assertRaises(LedgerError):
            history(self.root)
        with contextlib.closing(sqlite3.connect(self.root / '.sourceledger/state.sqlite3')) as db:
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 999)

    def test_history_cli_and_read_do_not_change_review_token(self):
        self.accept()
        token = check(self.root)['review_token']
        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main(['--root', str(self.root), 'history', '--format', 'json']), 0)
        self.assertEqual(len(json.loads(output.getvalue())['batches']), 1)
        self.assertEqual(check(self.root)['review_token'], token)
        self.assertIn('revision 1', render_history(history(self.root)))


if __name__ == '__main__':
    unittest.main()
