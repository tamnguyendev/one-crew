"""W47 audit counter-examples (T47): the requirement of a proposal check is bound, not caller-chosen.

p3 (a hide flag for 'delete permanently') is refused against the full requirement; re-checking the SAME proposal against a requirement
without A2 must not record ok and must not release the approval hold. A new revision of a plan whose destructive proposal was checked but
which has no check of its own stays held.
"""
import copy

from onecrew.ledger import LedgerError
from onecrew.v2 import plan as plans, step0
from tests.test_v2_l3 import Step0, step0_json
from tests.test_wf_r01_step0_proposal import REQUIREMENT, sample

WITHOUT_A2 = {'acceptance': [REQUIREMENT['acceptance'][0]], 'constraints': REQUIREMENT['constraints'], 'dependencies': []}


class RequirementBindingTests(Step0):
    def setUp(self):
        super().setUp()
        for relative in ('routes.py', 'api.py', 'menu.js', 'reports_new.py', 'data/old_report.json'):
            path = self.root / relative; path.parent.mkdir(parents=True, exist_ok=True); path.write_text('x\n')
        self.propose('P1', step0_json(size='S'))

    def results(self):
        return [p['result'] for k, p in self.events('P1') if k == 'proposal.checked']

    def test_dropping_a2_from_the_requirement_does_not_release_the_hold(self):
        self.assertEqual(step0.review_proposal(self.ledger, 'P1', REQUIREMENT, sample('p3'))['result'], 'refused')
        again = step0.review_proposal(self.ledger, 'P1', WITHOUT_A2, sample('p3'))
        self.assertFalse(again['ok']); self.assertIn('requirement_changed', [c for c, _ in again['reasons']])
        self.assertEqual(self.results(), ['refused', 'refused'])
        with self.assertRaises(LedgerError) as caught: plans.approve(self.ledger, 'P1', 'owner', 'said yes')
        self.assertIn('proposal_refused', str(caught.exception)); self.assertNotIn('plan.approved', self.kinds('P1'))

    def test_a_fixed_proposal_against_the_same_requirement_still_releases(self):
        """Counter-example: the bound requirement does not block the legitimate path (p3 refused, p1 ok, approve)."""
        step0.review_proposal(self.ledger, 'P1', REQUIREMENT, sample('p3'))
        reordered = copy.deepcopy(REQUIREMENT); reordered['dependencies'] = []
        self.assertTrue(step0.review_proposal(self.ledger, 'P1', reordered, sample('p1'))['ok'])
        self.assertEqual(plans.approve(self.ledger, 'P1', 'owner', 'said yes')['status'], 'approved')

    def test_a_new_revision_without_a_check_after_a_destructive_check_stays_held(self):
        step0.review_proposal(self.ledger, 'P1', REQUIREMENT, sample('p3'))
        plans.amend(self.ledger, 'P1', step0_json(size='S', title='Sample 2'), 'reword', 'codex')
        with self.assertRaises(LedgerError) as caught: plans.approve(self.ledger, 'P1', 'owner', 'said yes')
        self.assertIn('proposal_refused', str(caught.exception))
        step0.review_proposal(self.ledger, 'P1', REQUIREMENT, sample('p1'))       # a check of the new revision releases it
        self.assertEqual(plans.approve(self.ledger, 'P1', 'owner', 'said yes')['status'], 'approved')
