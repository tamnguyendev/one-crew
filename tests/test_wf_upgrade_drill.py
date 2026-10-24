"""Actual offline installations on generated fixtures; not a release/pilot."""
import json
import contextlib
import hashlib
from pathlib import Path
import sqlite3
import tempfile
import unittest

from onecrew.ledger import LedgerError
from onecrew.v2 import compat_scan
from tests import wf_rollback
from wfkit.upgrade_drill import Drill, guard_swap


class UpgradeDrillTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory(prefix='wf-upgrade-test-')
        cls.out=Path(cls.temp.name)/'drill'
        cls.runner=Drill(cls.out)
        cls.result=cls.runner.execute()

    @classmethod
    def tearDownClass(cls): cls.temp.cleanup()

    def test_real_installs_preserve_state_refuse_then_roll_back_and_reconcile(self):
        result=self.result
        self.assertEqual([row['artifact'] for row in result['installs']],['previous','current','previous','current'])
        self.assertEqual(result['result'],'pass')
        self.assertFalse(result['release_gate']); self.assertFalse(result['owner_acceptance'])
        self.assertIn('not claimed nearest',result['baseline_selection'])
        self.assertFalse(result['rejected']['switched']); self.assertGreater(result['rejected']['scan']['blocking']['total'],0)
        self.assertTrue(result['allowed']['switched']); self.assertEqual(result['allowed']['scan']['blocking']['total'],0)
        self.assertTrue(result['source_unchanged'])
        self.assertTrue(all(row['boundary_violations']==[] and row['loaded'] for row in result['observations']))
        for row in result['observations']:
            self.assertEqual(hashlib.sha256(Path(row['script']).read_bytes()).hexdigest(),row['script_sha256'])
            self.assertEqual(hashlib.sha256(Path(row['log']).read_bytes()).hexdigest(),row['log_sha256'])
        hidden=next(row for row in result['observations'] if row['label']=='rolled-back-hidden-root')
        self.assertEqual(hidden['exit_code'],2)
        self.assertLess(result['reconcile']['reconcile_seq'],result['reconcile']['continued_seq'])
        self.assertEqual(result['reconcile']['effect_replays_before_reconcile'],0)
        self.assertEqual(result['reconcile']['marker'],'once,after-reconcile')
        self.assertTrue(result['upgrade_preserved']['tables']['attempts'])
        self.assertEqual(json.loads((self.out/'receipt.json').read_text())['result'],'pass')

    def test_stale_scan_is_rejected_before_any_install_swap(self):
        state=wf_rollback.copy_ledger(self.out/'copy-state',Path(self.temp.name)/'stale-copy')
        observed=compat_scan.scan(state); self.assertEqual(observed['blocking']['total'],0)
        with contextlib.closing(sqlite3.connect(state/'ledger.sqlite3')) as conn, conn:
            task=conn.execute('SELECT id FROM tasks LIMIT 1').fetchone()[0]
            conn.execute('INSERT INTO events(task_id,kind,payload,created_at) VALUES(?,?,?,?)',
                         (task,'control.intervention','{"fixture":"late state change"}','2026-10-24T12:00:00Z'))
        with self.assertRaisesRegex(LedgerError,'changed after scan'): guard_swap(state,observed)
        self.assertEqual(len(self.runner.installs),4)


class UpgradeSafetyTests(unittest.TestCase):
    def test_existing_directory_cannot_be_treated_as_disposable_state(self):
        with tempfile.TemporaryDirectory() as directory:
            marker=Path(directory)/'keep'; marker.write_text('untouched')
            with self.assertRaisesRegex(LedgerError,'NEW directory'): Drill(directory)
            self.assertEqual(marker.read_text(),'untouched')
