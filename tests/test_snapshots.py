import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from onecrew.ledger import LedgerError
from onecrew.snapshots import Snapshots, scoped_path, scope_list

ROOT = Path(__file__).resolve().parents[1] / '.onecrew/snapshot-tests'


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        ROOT.mkdir(parents=True, exist_ok=True)
        self.base = Path(tempfile.mkdtemp(dir=ROOT)).resolve()
        self.project = self.base / 'project'
        self.project.mkdir()
        self.store = Snapshots(self.base / 'state')

    def tearDown(self):
        self.assertTrue(self.base.is_relative_to(ROOT.resolve()))
        def writable(function, path, error):
            os.chmod(path, 0o700)
            function(path)
        shutil.rmtree(self.base, onexc=writable)

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.project), *args], stderr=subprocess.DEVNULL)

    def test_dirty_staged_untracked_deleted_binary_restore_without_mutating_source(self):
        self.git('init')
        self.git('config', 'user.name', 'Fixture')
        self.git('config', 'user.email', 'fixture@example.invalid')
        self.git('config', 'core.autocrlf', 'false')
        (self.project / 'a.txt').write_bytes(b'base\n')
        (self.project / 'gone.bin').write_bytes(b'\x00\xffbase')
        self.git('add', '.')
        self.git('commit', '-m', 'base')
        (self.project / 'a.txt').write_bytes(b'staged\n')
        self.git('add', 'a.txt')
        (self.project / 'a.txt').write_bytes(b'unstaged\n')
        (self.project / 'gone.bin').unlink()
        (self.project / 'new.bin').write_bytes(b'\x00\xfeuntracked')
        index = (self.project / '.git/index').read_bytes()
        key = self.store.capture(self.project, ['a.txt', 'gone.bin', 'new.bin'])
        self.store.materialize(key, self.base / 'working')
        self.store.materialize(key, self.base / 'staged', staged=True)
        self.assertEqual((self.base/'working/a.txt').read_bytes(), b'unstaged\n')
        self.assertEqual((self.base/'staged/a.txt').read_bytes(), b'staged\n')
        self.assertFalse((self.base/'working/gone.bin').exists())
        self.assertEqual((self.base/'staged/gone.bin').read_bytes(), b'\x00\xffbase')
        self.assertEqual((self.base/'working/new.bin').read_bytes(), b'\x00\xfeuntracked')
        self.assertEqual((self.project/'.git/index').read_bytes(), index)
        self.assertEqual(self.store.capture(self.project, ['new.bin', 'gone.bin', 'a.txt']), key)

    def test_overlay_scope_deletion_and_review_diff_are_immutable(self):
        (self.project/'a.txt').write_bytes(b'old\n')
        key = self.store.capture(self.project, ['a.txt', 'b.txt'])
        changed = self.store.overlay(key, {'a.txt': b'new\n', 'b.txt': b'added\n'}, ['a.txt', 'b.txt'])
        self.assertEqual(self.store.context(key)['a.txt'], 'old\n')
        self.assertIn('+new', self.store.diff(key, changed))
        self.assertEqual((self.project/'a.txt').read_bytes(), b'old\n')
        with self.assertRaises(LedgerError):
            self.store.overlay(key, {'outside': b'oops'}, ['a.txt'])
        deleted = self.store.overlay(changed, {'a.txt': None}, ['a.txt'])
        self.assertIsNone(self.store.context(deleted)['a.txt'])

    def test_corrupt_blob_or_manifest_never_materializes(self):
        (self.project/'a.txt').write_bytes(b'hello')
        key = self.store.capture(self.project, ['a.txt'])
        blob = self.store.load(key)['files']['a.txt']['working']
        (self.store.root/'blobs'/blob).write_bytes(b'corrupted')
        with self.assertRaises(LedgerError):
            self.store.materialize(key, self.base/'output')
        self.assertFalse((self.base/'output').exists())
        path = self.store.root/'manifests'/(key+'.json')
        value = json.loads(path.read_text())
        value['head'] = 'tamper'
        path.write_text(json.dumps(value))
        with self.assertRaises(LedgerError):
            self.store.load(key)

    def test_failed_disk_commit_publishes_no_manifest(self):
        (self.project/'a.txt').write_bytes(b'hello')
        with patch('onecrew.snapshots.os.replace', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                self.store.capture(self.project, ['a.txt'])
        self.assertFalse(list(self.store.root.glob('manifests/*.json')))
        self.assertEqual((self.project/'a.txt').read_bytes(), b'hello')

    def test_source_change_during_capture_is_rejected(self):
        (self.project/'a.txt').write_bytes(b'hello')
        original = self.store._working
        calls = 0

        def race(*args):
            nonlocal calls
            calls += 1
            if calls == 2:
                (self.project/'a.txt').write_bytes(b'concurrent user edit')
            return original(*args)

        with patch.object(self.store, '_working', side_effect=race):
            with self.assertRaises(LedgerError):
                self.store.capture(self.project, ['a.txt'])
        self.assertFalse(list(self.store.root.glob('manifests/*.json')))

    def test_unsafe_paths_case_collision_and_existing_destination_rejected(self):
        for path in ('../x', '/x', 'C:/x', 'a\\b', 'nul.py', 'x.', '.git/config', '.env', 'a:ads'):
            with self.subTest(path=path), self.assertRaises(LedgerError):
                scoped_path(path)
        for paths in (['a', 'A'], ['a', 'a/b'], []):
            with self.assertRaises(LedgerError):
                scope_list(paths)
        key = self.store.capture(self.project, ['new.txt'])
        with self.assertRaises(FileExistsError):
            self.store.materialize(key, self.project)


if __name__ == '__main__':
    unittest.main()
