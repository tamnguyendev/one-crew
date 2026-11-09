"""2.5.0.dev17 — sixth independent review (Kiro CLI, 09/11; BAO-CAO-REVIEW-dev16.md, verdict FAIL) on 5d7c289. Red on 5d7c289: 3 of the 4 tests
here; the fourth (a milestone added after every approved one stays routine) is a control.

P1 (#9)  a new milestone inserted before an approved one ([M1] -> [M0, M1]) was routine, though M1 now waits for M0.
P2 (#2)  the metered reviewer's steps after admission and before the model call (task, reservation, the deadline check) did not say the
         model had not been called; an elapsed deadline left the attempt of unknown outcome instead of settling it as not started.
"""
import datetime as dt
import os
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))          # test_v2_reviewer imports test_v2_l1 by its plain name

from onecrew import budget_core
from onecrew.ledger import LedgerError
from onecrew.v2 import acceptance_diff as ad, metered_verifier, plan as plans
from onecrew.v2.metered_verifier import ProviderCall
from tests.test_v2_l1 import Fixture, plan_json, milestone
from tests.test_v2_reviewer import reviewer_milestone


class MilestoneInserted(Fixture):
    def contract(self, *ids):
        made = {'M0': dict(reviewer_milestone(), id='M0'), 'M1': milestone(), 'M2': dict(reviewer_milestone(), id='M2')}
        return plan_json(milestones=[made[i] for i in ids])

    def test_a_milestone_inserted_before_an_approved_one_is_acceptance(self):
        result = ad.classify_contract(self.contract('M1'), self.contract('M0', 'M1'))
        self.assertTrue(result['acceptance_changed'], result)
        self.assertNotEqual(result['summary'], 'wording or added checks only')

    def test_a_milestone_added_after_every_approved_one_stays_routine(self):
        result = ad.classify_contract(self.contract('M1'), self.contract('M1', 'M2'))
        self.assertFalse(result['acceptance_changed'], result); self.assertEqual([c['kind'] for c in result['changes']], ['added_check'])


class MeteredStepsBeforeTheModel(Fixture):
    def setUp(self):
        super().setUp()
        plans.propose(self.ledger, 'P1', plan_json(milestones=[reviewer_milestone()], budget={'max_calls': 3, 'time': 1}), 'codex', workflow=True)
        plans.approve(self.ledger, 'P1', 'owner', 'bounded temporary fixture')
        os.environ['ONECREW_ACTOR'] = 'codex'
        self.called = []

    def call(self):
        return ProviderCall(self.ledger, 'P1', 'M1', call=lambda *a: self.called.append(1))

    def counters(self):
        with self.ledger.transaction() as conn:
            return budget_core.group(conn, plans.anchor_events(self.ledger, conn, 'P1')['task_id'])

    def test_a_deadline_elapsed_before_dispatch_is_not_a_start_and_charges_nothing(self):
        late = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=1)).isoformat()
        with patch.object(metered_verifier, 'utcnow', return_value=late), self.assertRaises(LedgerError) as caught:
            self.call()('prompt', {'provider': 'codex', 'model': 'fixture'}, {}, self.root.parent, 1)
        self.assertIn('deadline elapsed', str(caught.exception))
        self.assertIs(getattr(caught.exception, 'verifier_started', None), False)
        self.assertEqual(self.called, [])
        budget = self.counters()
        self.assertEqual((budget['used_calls'], budget['unknown_attempts']), (0, 0))

    def test_a_failure_while_setting_up_the_call_is_not_a_start(self):
        with patch.object(metered_verifier, 'submit', side_effect=OSError(28, 'No space left on device')), self.assertRaises(OSError) as caught:
            self.call()('prompt', {'provider': 'codex', 'model': 'fixture'}, {}, self.root.parent, 1)
        self.assertIs(getattr(caught.exception, 'verifier_started', None), False)
        self.assertEqual(self.called, [])
