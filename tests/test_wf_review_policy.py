"""T29: deterministic optional-review policy cannot waive contract milestones."""
import copy
import unittest
from unittest.mock import patch

from onecrew import routing
from onecrew.ledger import LedgerError
from onecrew.v2 import plan as plans, review_policy as policy, verdict
from test_v2_l1 import Fixture, plan_json


class PurePolicyTests(unittest.TestCase):
    def setUp(self):
        self.policy = {'depth': 'light', 'optional_reviews': ['optional', 'M1']}

    def test_all_four_actions_use_shared_validator(self):
        for facts, expected in (({}, 'SKIP'), ({'mandatory': True}, 'REVIEW'),
                                ({'ready': False}, 'DEFER'), ({'unknowns': ['U1']}, 'HOLD')):
            with self.subTest(expected), patch.object(routing, 'validate_decision', wraps=routing.validate_decision) as validator:
                out = policy.evaluate(self.policy, **dict({'node': 'optional', 'mandatory': False, 'evidence': ['E1']}, **facts))
                self.assertEqual(out['action'], expected)
                self.assertEqual(validator.call_count, 1)

    def test_mandatory_wins_over_optional_policy_membership(self):
        out = policy.evaluate(self.policy, node='M1', mandatory=True, evidence=['E1'])
        self.assertEqual(out['action'], 'REVIEW')
        self.assertNotIn('requires_review', out)

    def test_standard_and_deep_keep_optional_review(self):
        for depth in ('standard', 'deep'):
            out = policy.evaluate(dict(self.policy, depth=depth), node='optional', mandatory=False, evidence=['E1'])
            self.assertEqual(out['action'], 'REVIEW')

    def test_unknown_scope_and_empty_evidence_refused(self):
        with self.assertRaises(LedgerError):
            policy.evaluate(self.policy, node='outside', mandatory=False, evidence=['E1'])
        with self.assertRaises(LedgerError):
            policy.evaluate(self.policy, node='optional', mandatory=False, evidence=[])

    def test_invalid_policy_and_bool_claims_refused(self):
        for value in ({'depth': 'light', 'optional_reviews': ['x', 'x']},
                      {'depth': 'skip-everything', 'optional_reviews': []},
                      dict(self.policy, model='anything')):
            with self.assertRaises(LedgerError): policy.normalize(value)
        with self.assertRaises(LedgerError):
            policy.evaluate(self.policy, node='optional', mandatory='false', evidence=['E1'])

    def test_insufficient_validator_mutant_is_detectable(self):
        with patch.object(routing, 'validate_decision', side_effect=LedgerError('mutant validation refused')):
            with self.assertRaisesRegex(LedgerError, 'mutant validation'):
                policy.evaluate(self.policy, node='optional', mandatory=False, evidence=['E1'])


class PolicyRuntimeTests(Fixture):
    def setUp(self):
        super().setUp()
        self.contract = plan_json(review_policy={'depth': 'light', 'optional_reviews': ['optional', 'M1']})

    def choose(self, node='optional', **kw):
        return policy.decide(self.ledger, 'P1', node, artifact_sha=self.tree(), evidence=['file:a.txt:1'], **kw)

    def test_skip_has_audit_but_mandatory_command_still_runs_and_no_request(self):
        self.approved(value=self.contract)
        anchor = plans.show(self.ledger, 'P1')['anchor_task']
        before = self.ledger.requests(anchor)
        with patch.object(routing, 'validate_decision', wraps=routing.validate_decision) as validate:
            self.assertEqual(self.choose()['action'], 'SKIP')
            self.assertEqual(self.choose('M1')['action'], 'REVIEW')
            self.assertEqual(validate.call_count, 2)
        self.assertEqual(plans.show(self.ledger, 'P1')['milestones'][0]['state'], 'pending')
        done = verdict.run(self.ledger, 'P1', 'M1')
        self.assertEqual(done['milestones'][0]['state'], 'passed')
        self.assertEqual(self.ledger.requests(anchor), before)
        recorded = [p for k, p in self.events() if k == 'decision.recorded']
        self.assertEqual(len(recorded), 2)
        self.assertTrue(all(p['subject'] == {'component': 'review_policy', 'model': 'rules'} for p in recorded))
        self.assertEqual(recorded[0]['validity']['depth'], 'light')
        self.assertTrue(recorded[0]['validity']['contract_sha'])

    def test_no_approval_no_optional_skip(self):
        self.propose(value=self.contract)
        with self.assertRaises(LedgerError): self.choose()
        self.assertNotIn('decision.recorded', self.kinds())

    def test_policy_absent_never_skips_unlisted_optional(self):
        self.approved()
        self.assertEqual(self.choose('M1')['action'], 'REVIEW')
        with self.assertRaises(LedgerError): self.choose()

    def test_cache_binds_input_policy_revision_and_artifact(self):
        self.approved(value=self.contract)
        first = self.choose()
        second = self.choose()
        self.assertFalse(first['cached']); self.assertTrue(second['cached'])
        self.assertEqual(first['validity'], second['validity'])
        self.assertEqual(self.choose(unknowns=['U1'])['action'], 'HOLD')
        self.assertEqual(self.choose(ready=False)['action'], 'DEFER')
        (self.root / 'a.txt').write_text('changed\n')
        changed = self.choose()
        self.assertFalse(changed['cached'])
        self.assertNotEqual(first['validity']['artifact_sha'], changed['validity']['artifact_sha'])
        new = copy.deepcopy(self.contract)
        new['review_policy']['depth'] = 'deep'
        plans.amend(self.ledger, 'P1', new, 'deeper policy', 'claude')
        with self.assertRaises(LedgerError): self.choose()
        plans.approve(self.ledger, 'P1', 'owner', 'fixture approval')
        current = self.choose()
        self.assertFalse(current['cached']); self.assertEqual(current['action'], 'REVIEW')
        self.assertNotEqual(current['validity']['policy_sha'], first['validity']['policy_sha'])

    def test_plan_changed_during_record_cannot_return_usable_decision(self):
        self.approved(value=self.contract)
        real_record = policy.decisions.record
        def change(*args, **kw):
            result = real_record(*args, **kw)
            newer = copy.deepcopy(self.contract); newer['title'] = 'Changed plan'
            plans.amend(self.ledger, 'P1', newer, 'changed concurrently', 'claude')
            return result
        with patch.object(policy.decisions, 'record', side_effect=change):
            with self.assertRaisesRegex(LedgerError, 'changed while deciding'):
                self.choose()


if __name__ == '__main__':
    unittest.main()
