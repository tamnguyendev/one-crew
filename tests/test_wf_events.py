"""T13a (W11a) — the event-type ledger and the old-version comparator (R00).

Two halves:
  1) The event-class ledger (onecrew/v2/compat.py): every kind the new code writes on a `plan:` anchor is class 0 or A; the class
     check is NOT derive()'s KINDS tuple (E1, E13). A class-B kind or a changed class-0 payload on a `plan:` anchor is refused.
  2) The old-version comparator against the REAL rollback binary (archive of ee46539, unmodified, via git archive + PYTHONPATH):
     R0 vs R0+A keep the same S/G/C (E11); R0+B reads wrong / is class B (E12, E14); R0+P crashes the old reader (E6, a B4 read block).

The archive-binary half is skipped only if git/archive is unavailable; on this machine it runs (EV-J/EV-K proved the method).
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from onecrew.ledger import LedgerError
from onecrew.v2 import compat, plan as plans
import tests.wf_oldversion as ov

REPO = str(Path(__file__).resolve().parents[1])
BASELINE = 'ee46539'                                  # the rollback target: 2.2.0.dev3, this worktree's own base commit


class EventClassLedgerTests(unittest.TestCase):
    """The class ledger, no old binary needed."""

    # E1: every kind the new code writes on a plan: anchor has a declared class 0 or A (never unknown, never B).
    def test_e1_every_written_kind_is_class_0_or_A(self):
        # the kinds the new code emits on an anchor (derive's KINDS + the hook/request/step0 kinds the old version writes + class A)
        written = set(plans.KINDS) | {'task.submitted', 'plan.step0_closed', 'precondition.recorded', 'unknown.closed', 'poc.answered',
                                      'hook.blocked', 'hook.logged', 'hook.reminded', 'hook.stop_blocked',
                                      'request.created', 'request.revised', 'request.deferred', 'request.answered'}
        written.discard('dispatch.refused_no_plan')    # written on the blocked job's task, not the anchor
        for kind in written:
            self.assertIn(compat.event_class(kind), ('0', 'A'), f'{kind} must be class 0 or A on a plan: anchor')

    # E13 / counter: task.submitted is NOT in derive().KINDS, yet it is class 0 and must pass. A KINDS-as-allow-list check goes red on it.
    def test_e13_task_submitted_is_class0_though_outside_KINDS(self):
        self.assertNotIn('task.submitted', plans.KINDS)            # the projector filter does not list it
        self.assertEqual(compat.event_class('task.submitted'), '0')
        # the real check accepts it on a plan: anchor
        self.assertIsNone(compat.check_write('task.submitted', {'title': 'x'}, 'plan:r1'))
        # the counter-example (KINDS as allow-list) would reject it:
        kinds_allowlist = lambda k: k in plans.KINDS
        self.assertFalse(kinds_allowlist('task.submitted'), 'a KINDS allow-list wrongly rejects task.submitted (the bug T13a forbids)')

    # E12: a class-B kind (plan.revoked) on a plan: anchor is refused (B2 continue-block).
    def test_e12_class_B_on_plan_anchor_is_refused(self):
        self.assertEqual(compat.event_class('plan.revoked'), 'B')
        with self.assertRaises(LedgerError) as c:
            compat.check_write('plan.revoked', {'plan': 'r1', 'revision': 1}, 'plan:r1')
        self.assertIn('B', str(c.exception))
        # but it is allowed on a plan-ns: root the old version cannot see
        self.assertIsNone(compat.check_write('plan.revoked', {'plan': 'r1', 'revision': 1}, 'plan-ns:r1'))

    # E14: an intent event with an unknown result is class B -> refused on a plan: anchor.
    def test_e14_intent_class_B_refused(self):
        # action.* with unknown result is class B per 00 §6.1; it is not class 0/A
        self.assertNotIn(compat.event_class('decision.hold'), ('0', 'A'))
        with self.assertRaises(LedgerError):
            compat.check_write('decision.hold', {}, 'plan:r1')

    # E6: a class-0 payload that drops a field the old reader needs is refused (B4 read-block).
    def test_e6_class0_missing_field_is_read_block(self):
        self.assertEqual(compat.event_class('plan.accepted'), '0')
        self.assertIsNone(compat.check_write('plan.accepted', {'plan': 'r1', 'revision': 1}, 'plan:r1'))   # full payload ok
        with self.assertRaises(LedgerError) as c:
            compat.check_write('plan.accepted', {'plan': 'r1', 'sha': 'x', 'by': 'owner'}, 'plan:r1')      # revision dropped
        self.assertIn('revision', str(c.exception))

    # counter: a kind with no declared class cannot be written on a plan: anchor (closed boundary).
    def test_unknown_kind_on_plan_anchor_is_refused(self):
        self.assertIsNone(compat.event_class('something.invented'))
        with self.assertRaises(LedgerError):
            compat.check_write('something.invented', {}, 'plan:r1')
        self.assertIsNone(compat.check_write('something.invented', {}, 'plan-ns:r1'))  # outside old reach: allowed


def _have_git():
    try:
        return subprocess.run(['git', '--version'], capture_output=True).returncode == 0
    except OSError:
        return False


@unittest.skipUnless(_have_git(), 'git is required to archive the old version')
class OldVersionComparatorTests(unittest.TestCase):
    """The real rollback binary (archive of ee46539) on temp state roots. No owner verbs; states built by inserted events."""

    @classmethod
    def setUpClass(cls):
        cls.runs = ov._short_runs()
        cls.old = ov.OldVersion(ov.archive(BASELINE, REPO, cls.runs))
        cls.proj = ov.git_project(cls.runs, 'P1')
        # R0: propose r1 with the old binary, then approve by inserted event; this is the baseline root.
        cls.cfile = cls.runs / 'c.json'; cls.cfile.write_text(json.dumps(ov.contract('R0')), encoding='utf-8')
        cls.cfile_b = cls.runs / 'c_b.json'; cls.cfile_b.write_text(json.dumps(ov.contract('R0 b', 'R0 goal b')), encoding='utf-8')
        cls.s0 = cls.runs / 'state0'
        code, out = cls.old.run(cls.proj, cls.s0, 'plan', 'propose', 'r1', '--file', str(cls.cfile), '--author', 'claude-probe')
        assert code == 0, out
        cls.pid = ov.project_id(cls.s0, cls.proj)
        cls.task = ov.anchor_id(cls.s0, cls.pid, 'plan:r1')
        ov.make_approved(cls.s0, cls.task, 'r1')

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.runs, ignore_errors=True)

    def _copy(self, tag):
        s = self.runs / tag
        shutil.copytree(self.s0, s)
        return s, ov.anchor_id(s, self.pid, 'plan:r1')

    def test_e13_old_binary_reads_anchor_with_task_submitted(self):
        # the control anchor carries task.submitted; the old binary reads it without any violation
        self.assertIn('task.submitted', ov.kinds_on(self.s0, self.task))
        r = ov.read(self.old, self.proj, self.s0, 'r1')
        self.assertFalse(r['read_blocked'])
        self.assertEqual(r['S']['status'], 'approved')

    def test_e11_class_A_events_keep_S_G_C(self):
        base = ov.read(self.old, self.proj, self.s0, 'r1')
        sA, tA = self._copy('R0plusA')
        outcome = {'version': 1, 'task': 'ANCHOR', 'task_revision': 1, 'spec_revision': 'x' * 64, 'phase': 'completed',
                   'mode': 'plan', 'provider': None, 'model': None, 'verification': 'passed', 'acceptance': 'accepted',
                   'snapshot': None, 'timing': {'wall_seconds': 60}, 'managed_calls': 0, 'id': 'probe-outcome'}
        for kind, payload in (('learning.outcome', outcome),
                              ('verdict.run_started', {'plan': 'r1', 'revision': 1, 'milestone': 'M1', 'pid': 1}),
                              ('control.intervention', {'actor': 'claude', 'channel': 'cli', 'command': 'probe', 'reason': 'probe'}),
                              ('decision.recorded', {'actor': 'claude', 'subject': {'component': 'c', 'model': 'm'},
                                                     'authority': {'grant_id': 'G', 'revision': 'r'}, 'evidence': [{'id': 'e'}], 'basis': 'b'})):
            self.assertIn(compat.event_class(kind), ('A',), kind)   # all class A
            ov.insert_event(sA, tA, kind, payload)
        after = ov.read(self.old, self.proj, sA, 'r1')
        diff = ov.compare(base, after)
        self.assertTrue(diff['S'], f"S changed: {base['S']} vs {after['S']}")
        self.assertTrue(diff['G'], 'G changed by a class-A event')
        self.assertTrue(diff['C'], 'C changed by a class-A event')
        self.assertFalse(after['read_blocked'])

    def test_e12_class_B_plan_revoked_old_still_reads_approved(self):
        sB, tB = self._copy('R0plusB1')
        ov.insert_event(sB, tB, 'plan.revoked', {'plan': 'r1', 'revision': 1, 'reason': 'probe'})
        r = ov.read(self.old, self.proj, sB, 'r1')
        # the old binary cannot see the revocation: it still reads approved (reads wrong) -> this is why class B is forbidden on plan:
        self.assertEqual(r['S']['status'], 'approved')
        self.assertEqual(compat.event_class('plan.revoked'), 'B')

    def test_e6_class0_changed_payload_crashes_old_reader(self):
        sP, tP = self._copy('R0plusP')
        # plan.accepted missing 'revision' (a class-0 payload dropped a field the old reader needs): B4 read block.
        ov.insert_event(sP, tP, 'plan.accepted', {'plan': 'r1', 'sha': 'x', 'by': 'owner'})
        show_code, _ = self.old.run(self.proj, sP, 'plan', 'show', 'r1')
        digest_code, _ = self.old.run(self.proj, sP, 'plan', 'digest')
        self.assertNotEqual(show_code, 0, 'old show should crash on the malformed class-0 payload')
        self.assertNotEqual(digest_code, 0, 'old digest of the whole state root should crash (EV-K)')


if __name__ == '__main__':
    unittest.main()
