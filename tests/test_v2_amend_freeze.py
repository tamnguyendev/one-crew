"""v2.1 job 11a, item 4: while an amendment waits for the owner, `verdict run` may still run a milestone whose title and verifier are the
same in both revisions, on the APPROVED revision; a changed milestone is refused until the new revision is approved."""
from unittest.mock import patch

from onecrew.ledger import LedgerError
from onecrew.v2 import plan as plans, verdict
from onecrew.v2.verifiers import command
from tests.test_v2_l1 import OK, PY, Fixture, milestone, plan_json

OTHER = [PY, '-c', 'print("a different check")']


class AmendFreezeTests(Fixture):
    def setUp(self):
        super().setUp()
        clock = patch.object(command, 'MIN_SECONDS', 0.0); clock.start(); self.addCleanup(clock.stop)
        self.approved('P1', plan_json(milestones=[milestone('M1'), milestone('M2')]))

    def amend(self, m2=None, m1=None, reason='change M2'):
        return plans.amend(self.ledger, 'P1', plan_json(milestones=[m1 or milestone('M1'), m2 or milestone('M2')]), reason, 'claude')

    def test_show_names_the_frozen_and_the_runnable_milestones(self):
        self.assertNotIn('frozen', plans.show(self.ledger, 'P1'))                       # no amendment, nothing frozen
        shown = self.amend(milestone('M2', OTHER))
        self.assertEqual(shown['status'], 'proposed')
        self.assertEqual(shown['frozen'], {'approved_revision': 1, 'pending_revision': 2, 'frozen': ['M2'], 'runnable': ['M1']})
        self.assertEqual([(m['id'], m['frozen']) for m in shown['milestones']], [('M1', False), ('M2', True)])

    def test_an_unchanged_milestone_runs_on_the_approved_revision_while_the_amendment_waits(self):
        self.amend(milestone('M2', OTHER))
        view = verdict.run(self.ledger, 'P1', 'M1', self.root)
        last = view['milestones'][0]['last_verdict']
        self.assertEqual(last['result'], 'pass')
        with self.ledger.transaction() as conn: state = plans.derive(self.ledger, conn, 'P1')
        self.assertEqual([(v['revision'], v['milestone'], v['result']) for v in state['verdicts']], [(1, 'M1', 'pass')])
        self.assertEqual((state['approved']['revision'], state['latest'], state['status']), (1, 2, 'proposed'))   # nothing was approved by running

    def test_a_changed_milestone_is_refused_with_a_reason_naming_it(self):
        self.amend(milestone('M2', OTHER))
        with self.assertRaises(LedgerError) as caught: verdict.run(self.ledger, 'P1', 'M2', self.root)
        self.assertIn('M2', str(caught.exception)); self.assertIn('frozen', str(caught.exception)); self.assertIn('M1', str(caught.exception))
        self.assertNotIn('verdict.receipt_issued', self.kinds())                            # refused before anything ran

    def test_a_changed_title_freezes_the_milestone_too(self):
        shown = self.amend(m1=milestone('M1', title='Another title'))
        self.assertEqual((shown['frozen']['frozen'], shown['frozen']['runnable']), (['M1'], ['M2']))
        with self.assertRaises(LedgerError) as caught: verdict.run(self.ledger, 'P1', 'M1', self.root)
        self.assertIn('frozen', str(caught.exception))

    def test_milestones_still_go_in_order_on_the_approved_revision(self):
        self.amend(m1=milestone('M1', OTHER))
        with self.assertRaises(LedgerError) as caught: verdict.run(self.ledger, 'P1', 'M2', self.root)
        self.assertIn('M1', str(caught.exception))

    def test_approving_the_amendment_unfreezes_and_runs_on_the_new_revision(self):
        self.amend(milestone('M2', OTHER))
        plans.approve(self.ledger, 'P1', 'owner', 'ok')
        self.assertNotIn('frozen', plans.show(self.ledger, 'P1'))
        verdict.run(self.ledger, 'P1', 'M1', self.root)
        view = verdict.run(self.ledger, 'P1', 'M2', self.root)
        with self.ledger.transaction() as conn: state = plans.derive(self.ledger, conn, 'P1')
        self.assertEqual({v['revision'] for v in state['verdicts']}, {2}); self.assertEqual(view['status'], 'approved')

    def test_nothing_runs_without_an_approved_revision(self):
        self.propose('P2', plan_json(milestones=[milestone('M1')]))
        with self.assertRaises(LedgerError) as caught: verdict.run(self.ledger, 'P2', 'M1', self.root)
        self.assertIn('nothing to verify', str(caught.exception))
        plans.amend(self.ledger, 'P2', plan_json(milestones=[milestone('M1', OTHER)]), 'amend before any approval', 'claude')
        with self.assertRaises(LedgerError): verdict.run(self.ledger, 'P2', 'M1', self.root)         # a pending revision is not an approval

    def test_a_stopped_approved_revision_does_not_run_either(self):
        value = plan_json(milestones=[milestone('M1', [PY, '-c', 'raise SystemExit(3)'], max_repairs=0), milestone('M2')])
        self.propose('P3', value); plans.approve(self.ledger, 'P3', 'owner', 'ok')
        self.assertEqual(verdict.run(self.ledger, 'P3', 'M1', self.root)['status'], 'stopped_with_report')
        plans.amend(self.ledger, 'P3', plan_json(milestones=[milestone('M1', [PY, '-c', 'raise SystemExit(3)'], max_repairs=0), milestone('M2', OTHER)]), 'x', 'claude')
        with self.assertRaises(LedgerError): verdict.run(self.ledger, 'P3', 'M1', self.root)
