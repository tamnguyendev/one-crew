import copy
from pathlib import Path
import tempfile
import unittest

from onecrew.ledger import LedgerError
from onecrew.snapshots import Snapshots, MAX_FILE, MAX_EVIDENCE


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.store=Snapshots(Path(self.temp.name))
        self.data=('Kiểm kê source\n'*200000).encode()

    def test_large_utf8_roundtrip_and_original_source_cap(self):
        reference=self.store.evidence(self.data)
        self.assertEqual(self.store.read_evidence(reference),self.data)
        self.assertTrue(all(p.stat().st_size<=MAX_FILE for p in (self.store.root/'blobs').iterdir()))
        with self.assertRaises(LedgerError):self.store.blob(self.data)
        with self.assertRaises(LedgerError):self.store.read_blob(reference)

    def test_legacy_small_reference_and_total_bound(self):
        reference=self.store.blob(b'legacy')
        self.assertEqual(self.store.read_evidence(reference),b'legacy')
        self.assertEqual(self.store.evidence(b'legacy'),reference)
        with self.assertRaises(LedgerError):self.store.evidence(b'x'*(MAX_EVIDENCE+1))

    def test_tampered_missing_or_reordered_chunks_never_read_as_valid(self):
        reference=self.store.evidence(self.data)
        wrong=copy.deepcopy(reference);wrong['chunks'].reverse()
        with self.assertRaises(LedgerError):self.store.read_evidence(wrong)
        wrong=copy.deepcopy(reference);wrong['chunks'].pop()
        with self.assertRaises(LedgerError):self.store.read_evidence(wrong)
        wrong=copy.deepcopy(reference);wrong['bytes']=MAX_EVIDENCE+1
        with self.assertRaises(LedgerError):self.store.read_evidence(wrong)
        path=self.store.root/'blobs'/reference['chunks'][0]
        path.write_bytes(b'tampered')
        with self.assertRaises(LedgerError):self.store.read_evidence(reference)

