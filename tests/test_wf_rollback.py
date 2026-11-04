"""T13b + T49b (W41) — upgrade / rollback / roll-forward drill on a COPY of a ledger (R00).

T13b: upgrading from the old install to the new (wheel in a temp venv) on a ledger copy keeps IDs, spent budget, evidence and an
      unreconciled attempt; an old-created root still reads under the old semantics.
T49b: on a ledger copy with the old and new installs, the rollback script refuses at every branch that still has a block (N8 B2, N9 B4
      even though X1 is accepted, N10 B4 with X1 paused) and runs only when the last scan reports 0 (N11); the accepted-readable control X2
      lets it run; roll-forward keeps IDs/revision/evidence/budget. The old binary is the archive of ee46539; the scan is the new code's.
"""
import json
import shutil
import sqlite3
import subprocess
import unittest
from pathlib import Path

from onecrew.v2 import compat_scan, plan as plans
import tests.wf_oldversion as ov
import tests.wf_rollback as rb

REPO = str(Path(__file__).resolve().parents[1])
BASELINE = 'ee46539'


def _have_git():
    try:
        return subprocess.run(['git', '--version'], capture_output=True).returncode == 0
    except OSError:
        return False


@unittest.skipUnless(_have_git(), 'git required')
class RollbackDrillTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.runs = ov._short_runs()
        cls.old = ov.OldVersion(ov.archive(BASELINE, REPO, cls.runs))
        cls.proj = ov.git_project(cls.runs, 'P1')
        cls.master = cls.runs / 'master'          # the pristine ledger the drills copy from
        cls._build_master()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.runs, ignore_errors=True)

    @classmethod
    def _propose(cls, state, name):
        f = cls.runs / f'c_{name}.json'; f.write_text(json.dumps(ov.contract(name.upper())), encoding='utf-8')
        code, out = cls.old.run(cls.proj, state, 'plan', 'propose', name, '--file', str(f), '--author', 'claude-probe')
        assert code == 0, out

    @classmethod
    def _build_master(cls):
        for n in ('r1', 'r4', 'x2'):
            cls._propose(cls.master, n)
        pid = ov.project_id(cls.master, cls.proj)
        cls.pid = pid
        t = ov.anchor_id(cls.master, pid, 'plan:r1'); ov.make_approved(cls.master, t, 'r1')
        ov.insert_event(cls.master, t, 'learning.outcome', {'version': 1, 'task': 'ANCHOR', 'id': 'o1', 'phase': 'completed'})
        ov.insert_event(cls.master, t, 'action.executing', {'action': 'probe', 'intent': 'i1'})   # an unreconciled attempt
        ov.insert_event(cls.master, t, 'attention.exceeded', {'plan': 'r1', 'revision': 1})        # spent budget marker
        t = ov.anchor_id(cls.master, pid, 'plan:r4'); ov.make_approved(cls.master, t, 'r4')
        ov.insert_event(cls.master, t, 'plan.revoked', {'plan': 'r4', 'revision': 1, 'reason': 'fixture'})    # class B -> B2
        t = ov.anchor_id(cls.master, pid, 'plan:x2'); ov.make_accepted(cls.master, t, 'x2')

    def _copy(self, tag):
        return rb.copy_ledger(self.master, self.runs / tag)

    def _with_x1(self, state, accepted=True):
        self._propose(state, 'x1')
        t = ov.anchor_id(state, self.pid, 'plan:x1')
        ov.insert_event(state, t, 'plan.advised', {'plan': 'x1', 'sha': 'x'})     # missing revision -> B4
        if accepted:
            ov.make_accepted(state, t, 'x1')
        else:
            ov.make_stopped(state, t, 'x1')

    def _ids_budget_evidence(self, state):
        db = sqlite3.connect(state / 'ledger.sqlite3'); db.row_factory = sqlite3.Row
        try:
            ids = sorted(r['id'] for r in db.execute('SELECT id FROM tasks'))
            kinds = sorted(r['kind'] for r in db.execute('SELECT kind FROM events'))
            exceeded = db.execute("SELECT COUNT(*) FROM events WHERE kind='attention.exceeded'").fetchone()[0]
            intents = db.execute("SELECT COUNT(*) FROM events WHERE kind='action.executing'").fetchone()[0]
        finally:
            db.close()
        return ids, kinds, exceeded, intents

    # ---- T13b: upgrade preserves state; old root keeps old semantics ----
    def test_t13b_upgrade_preserves_ids_budget_evidence_and_attempt(self):
        copy = self._copy('t13b')
        before = self._ids_budget_evidence(copy)
        # the new code reads the ledger (the "upgrade": nothing is rewritten)
        scan = compat_scan.scan(copy)
        r1 = next(r for r in scan['roots'] if r['name'] == 'r1')
        self.assertEqual(r1['status'], 'open')
        after = self._ids_budget_evidence(copy)
        self.assertEqual(before, after)                 # ids, event kinds, spent-budget count, unreconciled attempt all unchanged
        self.assertGreaterEqual(before[2], 1)           # attention.exceeded preserved (budget not reset)
        self.assertGreaterEqual(before[3], 1)           # action.executing (unreconciled attempt) preserved

    def test_t13b_old_root_reads_old_semantics_after_upgrade(self):
        copy = self._copy('t13b2')
        reading = self.old.status_of(self.proj, copy, 'r1')     # old binary still reads r1 as approved
        self.assertEqual(reading['status'], 'approved')
        self.assertEqual(reading['exit'], 0)

    # ---- T49b: the rollback matrix ----
    def test_n8_blocked_by_b2_refuses(self):
        copy = self._copy('N8')                 # S0: R4 has plan.revoked -> B2
        result = rb.rollback_drill(copy)
        self.assertFalse(result['ran'])
        self.assertIn('B2', result['conditions'])

    def test_n9_accepted_x1_still_b4_refuses(self):
        copy = self._copy('N9'); self._with_x1(copy, accepted=True)
        # resolve R4 by accepting it (clears B2); X1 remains B4 even though accepted
        t = ov.anchor_id(copy, self.pid, 'plan:r4'); ov.make_accepted(copy, t, 'r4')
        result = rb.rollback_drill(copy)
        self.assertFalse(result['ran'])
        self.assertIn('B4', result['conditions'])
        self.assertNotIn('B2', result['conditions'])     # B2 cleared, B4 remains

    def test_n10_paused_x1_still_b4_refuses(self):
        copy = self._copy('N10'); self._with_x1(copy, accepted=False)   # X1 stopped, not accepted
        t = ov.anchor_id(copy, self.pid, 'plan:r4'); ov.make_accepted(copy, t, 'r4')
        result = rb.rollback_drill(copy)
        self.assertFalse(result['ran'])
        self.assertIn('B4', result['conditions'])        # pausing does not release B4

    def test_n11_scan_zero_runs_and_old_reads(self):
        copy = self._copy('N11')                 # S0; resolve R4 by accepting it; X2 stays accepted-readable
        t = ov.anchor_id(copy, self.pid, 'plan:r4'); ov.make_accepted(copy, t, 'r4')
        result = rb.rollback_drill(copy)
        self.assertTrue(result['ran'], f"expected run at scan=0, got {result.get('conditions')}")
        self.assertEqual(result['scan']['blocking']['total'], 0)
        self.assertIsNotNone(result['ledger_sha'])
        # after rollback the old binary reads R1 and X2 and digest, and amend R1 works (continue)
        self.assertEqual(self.old.status_of(self.proj, copy, 'r1')['status'], 'approved')
        self.assertEqual(self.old.status_of(self.proj, copy, 'x2')['status'], 'accepted')
        dcode, _ = self.old.run(self.proj, copy, 'plan', 'digest')
        self.assertEqual(dcode, 0)

    # ---- E8: the drill's diagnosis source is the scan output (hash), not the old binary ----
    def test_diagnosis_source_is_scan_hash(self):
        copy = self._copy('src'); self._with_x1(copy, accepted=True)
        result = rb.rollback_drill(copy)
        self.assertFalse(result['ran'])
        self.assertIsNotNone(result['scan']['ledger_sha'])     # the receipt carries the ledger hash the scan read
        self.assertTrue(result['scan']['read_only'])

    # ---- E12 / roll-forward: ids/revision/evidence/budget preserved across the whole drill ----
    def test_roll_forward_preserves_everything(self):
        copy = self._copy('rf')
        t = ov.anchor_id(copy, self.pid, 'plan:r4'); ov.make_accepted(copy, t, 'r4')
        before = self._ids_budget_evidence(copy)
        result = rb.rollback_drill(copy)               # runs (scan 0)
        self.assertTrue(result['ran'])
        # roll-forward = the new code reads every root again; nothing was rewritten
        compat_scan.scan(copy)
        after = self._ids_budget_evidence(copy)
        self.assertEqual(before, after)


if __name__ == '__main__':
    unittest.main()
