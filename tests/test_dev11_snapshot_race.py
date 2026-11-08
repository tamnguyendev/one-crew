"""2.5.0.dev11: the cause of the test_a_r13 hold (seen once on MR-R, reproduced 08/11 under load: round 19 of a 12-process stress run).

Two engine doors capture the same source at once, so they save the SAME content-addressed manifest. `Snapshots.save` rewrote it every time,
and on Windows `os.replace` onto a file another thread has open (here: `load()` reading that manifest) raises PermissionError; the five
retries of `durable_write` cover about 0.2 s, less than a read takes under load. The door's exception then held the node:
`[Errno 13] Permission denied: ...\\snapshots\\manifests\\<sha>.json`, classification unknown.

The tests hold the file open for real (no mock of os.replace): red on Windows before the fix.
"""
import os
import tempfile
import unittest
from pathlib import Path

from onecrew.ledger import content_hash
from onecrew.snapshots import Snapshots, durable_write

WINDOWS = os.name == 'nt'


class SnapshotRaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.store = Snapshots(self.temp.name)

    def manifest(self):
        blob = self.store.blob(b'one\n')
        return {'version': 1, 'files': {'a.txt': {'working': blob, 'index': []}}}

    @unittest.skipUnless(WINDOWS, 'the replace-onto-an-open-file refusal is Windows behaviour')
    def test_saving_a_manifest_another_thread_is_reading_succeeds(self):
        manifest = self.manifest()
        key = self.store.save(manifest)
        path = self.store.root / 'manifests' / (key + '.json')
        with open(path, 'rb'):                                          # a concurrent load() holds the file
            self.assertEqual(self.store.save(manifest), key)
        self.assertEqual(content_hash(self.store.load(key)), key)

    @unittest.skipUnless(WINDOWS, 'the replace-onto-an-open-file refusal is Windows behaviour')
    def test_durable_write_of_the_same_bytes_onto_an_open_file_succeeds_and_different_bytes_still_fail(self):
        target = Path(self.temp.name) / 'x.json'
        durable_write(target, b'same')
        with open(target, 'rb'):
            durable_write(target, b'same')                              # the destination already holds exactly these bytes
            with self.assertRaises(PermissionError):
                durable_write(target, b'different')                     # never reported as written when it was not
        self.assertEqual(target.read_bytes(), b'same')
        self.assertEqual([p.name for p in target.parent.glob('.oc-*.tmp')], [])

    def test_a_damaged_manifest_is_rewritten_not_trusted(self):
        manifest = self.manifest()
        key = self.store.save(manifest)
        path = self.store.root / 'manifests' / (key + '.json')
        path.write_text('{"version": 1, "files": {}}', encoding='utf-8')
        self.assertEqual(self.store.save(manifest), key)
        self.assertEqual(content_hash(self.store.load(key)), key)


if __name__ == '__main__':
    unittest.main()
