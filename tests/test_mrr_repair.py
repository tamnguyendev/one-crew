"""Focused MR-R boundary tests with real Git, fixture files and no provider calls."""
import tempfile
import unittest
from pathlib import Path

from onecrew.ledger import Ledger
from onecrew.v2 import source_repos as sr
from tests.test_mrr_sources import REPO_A, changed, fingerprint, git, make_repo, write


class SourceBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.project = self.base / 'coord'
        self.project.mkdir()
        self.root = self.project / 'repo'
        make_repo(self.root, REPO_A)
        self.ledger = Ledger(self.project, self.base / 'state')

    def pin(self, read=None):
        before = fingerprint(self.root)
        result = sr.pin_repo(self.ledger, 'core', 'repo', read)
        self.assertEqual(changed(before, fingerprint(self.root)), [], 'pin wrote to source metadata or files')
        return result

    def test_dirty_capture_does_not_copy_ungranted_or_secret_bytes(self):
        write(self.root, {'src/alpha.py': b'ALPHA = 9\n', 'outside.txt': b'NEVER-COPY-PRIVATE-CONTENT\n'})
        pin = self.pin(['src/**'])
        self.assertEqual(pin.get('state'), 'outside_scope_changes', pin)
        self.assertFalse(sr.private_dir(self.ledger, self.root).exists())
        (self.root / 'outside.txt').unlink()
        write(self.root, {'src/.env.local': b'PASSWORD=NEW-SECRET-BYTES\n'})
        pin = self.pin(['src/**'])
        self.assertEqual(pin.get('state'), 'outside_scope_changes', pin)
        self.assertNotIn('.env.local', pin['reason'])
        self.assertFalse(sr.private_dir(self.ledger, self.root).exists())

    def test_scope_capture_keeps_unchanged_head_entries_without_hashing_them(self):
        write(self.root, {'src/alpha.py': b'ALPHA = 9\n'})
        pin = self.pin(['src/**'])
        self.assertEqual((pin['kind'], pin['dirty']), ('git-tree', True), pin)
        store = sr.private_dir(self.ledger, self.root)
        forbidden = git(self.root, 'rev-parse', 'HEAD:src/.env.local')
        self.assertFalse((store / forbidden[:2] / forbidden[2:]).exists())
        reader = sr.reader(self.ledger, 'core', pin)
        self.assertEqual(reader.blobs([reader.entries()['src/alpha.py']['blob']]),
                         {reader.entries()['src/alpha.py']['blob']: b'ALPHA = 9\n'})

    def test_publication_checks_worktree_bytes_after_clean_and_dirty_pins(self):
        for initial in (None, b'ALPHA = 8\n'):
            if initial is not None: write(self.root, {'src/alpha.py': initial})
            pin = self.pin(['src/**'])
            reader = sr.reader(self.ledger, 'core', pin)
            expected = reader.entries()['src/alpha.py']['blob']
            self.assertEqual(sr.current_blob(self.root, 'src/alpha.py'), expected)
            write(self.root, {'src/alpha.py': b'ALPHA = 7\n'})
            self.assertNotEqual(sr.current_blob(self.root, 'src/alpha.py'), expected)


if __name__ == '__main__':
    unittest.main()
