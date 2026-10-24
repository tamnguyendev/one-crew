"""T08a fault injection after the Codex review of 9aca8be (P1 W37a): the hold on a run of unknown outcome must survive a crash at every
write boundary, and a reconcile must never let X run again without a recorded release.

Fixture of tests/test_wf_t08a_reconcile (temporary ledger, X = a fixture command that appends one line to a marker file). Crashes are
injected by making the ledger write raise at a chosen event kind (a real exception between two writes); "restart" = calling `verdict.run`
again in a fresh call.
  (i)  crash after `verdict.run_reconciled(unknown)` and before the hold is durable  -> restart: still held, X count unchanged;
  (ii) crash after the receipt of a finished run was issued and before its verdict was recorded -> restart: recorded from that receipt,
       no second run, X count unchanged;
  (iii) reconcile twice: no duplicate event, no second receipt;
  (iv) the plan moves to a new approved revision while a run of the old revision is of unknown outcome -> still held for that milestone;
  (v)  only a recorded release lets X run again, and it is counted (marker 2 lines).
"""
import json
from pathlib import Path
from unittest.mock import patch

from onecrew.ledger import LedgerError
from onecrew.v2 import plan as plans, verdict
from tests.test_v2_l1 import plan_json, milestone
import tests.test_wf_t08a_reconcile as t08a


class Crash(Exception):
    pass


def crash_on(kind):
    """A plans.emit that raises when asked to write `kind` (the process dies between two writes)."""
    original = plans.emit
    def emit(ledger, conn, task_id, event_kind, payload):
        if event_kind == kind: raise Crash(kind)
        return original(ledger, conn, task_id, event_kind, payload)
    return patch.object(plans, 'emit', side_effect=emit)


class FaultTests(t08a.ReconcileTests):
    for _name in [n for n in dir(t08a.ReconcileTests) if n.startswith('test_')]:
        locals()[_name] = None
    del _name

    def unknown_run(self, run_id='r-u'):
        self.fabricate_run(run_id, pid=2 ** 22 + 31, minutes=10)
        verdict._mark(self.ledger, run_id, 'dispatched', {'plan': 'P1', 'revision': 1, 'milestone': 'M1', 'kind': 'command', 'at': 'fixture'})

    def test_i_crash_between_reconciled_unknown_and_hold_keeps_the_hold(self):
        self.plan_with(self.x(then_sleep=False))
        self.unknown_run()
        with crash_on('verdict.run_held'):
            with self.assertRaises(Crash):
                verdict.run(self.ledger, 'P1', 'M1', self.root)                       # the process dies right after/around the reconcile write
        self.assertEqual(self.lines(), 0)
        with self.assertRaises(LedgerError) as held:                                 # restart
            verdict.run(self.ledger, 'P1', 'M1', self.root)
        self.assertIn('unknown outcome', str(held.exception))
        self.assertEqual(self.lines(), 0)                                             # X never dispatched
        self.assertEqual(len(self.payloads('verdict.run_started')), 1)
        self.assertEqual(verdict.status(self.ledger, 'P1')['held'], ['r-u'])

    def test_ii_crash_after_receipt_issued_before_verdict_recorded_completes_without_a_second_run(self):
        from onecrew.v2.verifiers import command
        self.plan_with(self.x(then_sleep=False))
        with self.ledger.transaction() as conn:
            state = plans.anchor_events(self.ledger, conn, 'P1')
            contract, sha = plans.load(self.ledger, state, 1)
        blob, receipt = command.run(self.ledger, 'P1', 1, sha, contract['milestones'][0], self.root)   # X ran once, receipt on disk
        self.assertEqual(self.lines(), 1)
        self.fabricate_run('r-c', pid=2 ** 22 + 32, minutes=10)
        verdict._mark(self.ledger, 'r-c', 'dispatched', {'plan': 'P1', 'revision': 1, 'milestone': 'M1', 'kind': 'command', 'at': 'fixture'})
        verdict._mark(self.ledger, 'r-c', 'receipt', {'blob': blob, 'receipt': receipt, 'integrity': None, 'cwd': str(self.root)})
        with crash_on('verdict.recorded'):
            with self.assertRaises(Crash):
                verdict.run(self.ledger, 'P1', 'M1', self.root)                       # receipt issued, verdict not recorded
        self.assertEqual([p['run_id'] for p in self.payloads('verdict.receipt_issued')], ['r-c'])
        self.assertEqual(self.payloads('verdict.recorded'), [])
        shown = verdict.run(self.ledger, 'P1', 'M1', self.root)                       # restart
        self.assertEqual(shown['milestones'][0]['state'], 'passed')
        self.assertEqual(self.lines(), 1)                                             # X did not run again
        self.assertEqual(len(self.payloads('verdict.run_started')), 1)
        self.assertEqual([p['receipt'] for p in self.payloads('verdict.recorded')], [blob])
        self.assertEqual(len(self.payloads('verdict.receipt_issued')), 1)

    def test_iii_reconcile_twice_writes_nothing_twice(self):
        self.plan_with(self.x(then_sleep=False))
        self.unknown_run()
        for _ in range(3):
            with self.assertRaises(LedgerError):
                verdict.run(self.ledger, 'P1', 'M1', self.root)
        self.assertEqual(len(self.payloads('verdict.run_reconciled')), 1)
        self.assertEqual(len(self.payloads('verdict.run_held')), 1)
        self.assertEqual(self.lines(), 0)

    def test_iv_a_new_approved_revision_does_not_forget_the_unknown_run(self):
        self.plan_with(self.x(then_sleep=False))
        self.unknown_run()
        plans.amend(self.ledger, 'P1', plan_json(milestones=[milestone(argv=self.x(then_sleep=False), max_repairs=2)]), 'one more repair', 'codex')
        plans.approve(self.ledger, 'P1', 'owner', 'approved the amendment')
        self.assertEqual(plans.show(self.ledger, 'P1')['status'], 'approved')
        with self.assertRaises(LedgerError) as held:
            verdict.run(self.ledger, 'P1', 'M1', self.root)                            # revision 2, same milestone: the old run is still unknown
        self.assertIn('unknown outcome', str(held.exception))
        self.assertEqual(self.lines(), 0)

    def test_v_only_a_recorded_release_lets_x_run_again_and_it_is_counted(self):
        self.plan_with(self.x(then_sleep=False))
        self.unknown_run()
        with self.assertRaises(LedgerError):
            verdict.run(self.ledger, 'P1', 'M1', self.root)
        with self.assertRaises(LedgerError):
            verdict.release_run(self.ledger, 'P1', 'r-u', '')                          # a release needs a reason
        verdict.release_run(self.ledger, 'P1', 'r-u', 'checked: no effect found')
        self.assertEqual(verdict.run(self.ledger, 'P1', 'M1', self.root)['milestones'][0]['state'], 'passed')
        self.assertEqual(self.lines(), 1)
        released = self.payloads('verdict.run_released')[0]
        self.assertEqual(released['run_id'], 'r-u'); self.assertTrue(released['reason'])
