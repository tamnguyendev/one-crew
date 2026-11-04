"""W26 evidence for T16c E9: every decision of the optional-review path has its HD-05 record and the contract revision never moves.

Real engine on a temporary ledger (the light-policy fixture of tests.test_wf_review_dispatch): a SKIP by the approved light policy (Q6), then
a HOLD because a local runtime unknown is open on the node (Q8). Neither creates a request.
"""
from unittest.mock import Mock

from onecrew.v2 import plan, runtime_unknowns
import tests.test_wf_review_dispatch as base


class T16cDecisionRecords(base.ReviewDispatchTests):
    for _name in [n for n in dir(base.ReviewDispatchTests) if n.startswith('test_')]:
        locals()[_name] = None
    del _name

    def contract_facts(self):
        view = plan.show(self.ledger, 'P1')
        amended = [k for k in self.kinds() if k == 'plan.amended']
        return view['revision'], view['sha'], len(amended)

    def policy_records(self):
        return [p for k, p in self.events() if k == 'decision.recorded' and p['subject']['component'] == 'review_policy']

    def test_t16c_e9_skip_and_unknown_hold_each_have_an_hd05_record_and_no_request(self):
        """W26 / T16c E9: the Q6 SKIP and the Q8 unknown HOLD each leave one HD-05 decision.recorded (rule subject, grant, basis, scope,
        validity), 0 requests are created, and the contract revision/hash and plan.amended count do not change."""
        self.step()
        contract_before = self.contract_facts()
        requests_before = len(self.ledger.requests())
        checker = Mock(side_effect=AssertionError('neither SKIP nor HOLD may call a reviewer'))

        skipped = self.optional(checker)
        self.assertEqual((skipped['status'], skipped['decision']['action']), ('skipped', 'SKIP'))
        runtime_unknowns.open_unknown(self.ledger, 'P1', 'U-q8', question='Which format is required?',
                                      affected=['C'], required_by=['C'], resolver='doc', evidence=['a.txt:1'])
        held = self.optional(checker)
        self.assertEqual((held['status'], held['decision']['action']), ('held', 'HOLD'))

        records = {p['validity']['action']: p for p in self.policy_records()}
        self.assertEqual(set(records), {'SKIP', 'HOLD'})
        self.assertNotEqual(records['SKIP']['key'], records['HOLD']['key'])
        for action, record in records.items():
            with self.subTest(action=action):
                self.assertEqual(record['subject'], {'component': 'review_policy', 'model': 'rules'})
                self.assertTrue(record['authority']['grant_id'].startswith('approved-contract:'))
                self.assertTrue(record['basis'])
                self.assertEqual(record['scope'], 'extra')
                self.assertTrue(record['validity'].get('policy_sha'))
                self.assertTrue(record['evidence'])
        self.assertEqual(held['decision']['record']['key'], records['HOLD']['key'])
        self.assertIn('U-q8', records['HOLD']['basis'] + ' ' + held['decision']['reason'])
        self.assertEqual(checker.call_count, 0)
        self.assertEqual(len(self.ledger.requests()), requests_before)
        self.assertEqual(self.ledger.requests(), [])
        self.assertEqual(self.contract_facts(), contract_before)
        self.assertEqual(plan.show(self.ledger, 'P1')['status'], 'approved')
