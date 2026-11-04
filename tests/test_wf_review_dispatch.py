"""T29 actual engine consumers; checker callbacks are explicit local fixtures."""
import copy
import json
from unittest.mock import Mock, patch

from onecrew import routing
from onecrew.ledger import LedgerError
from onecrew.v2 import review_dispatch, review_policy, plan
from tests import test_wf_engine as fixtures
from tests.test_v2_l1 import plan_json


class ReviewDispatchTests(fixtures.EngineFixture):
    depth = 'light'

    def setUp(self):
        with patch.object(fixtures, 'plan_json', side_effect=lambda **kw: plan_json(
                review_policy={'depth': self.depth, 'optional_reviews': ['extra', 'C', 'M1', 'check-I']}, **kw)):
            super().setUp()
        self.nodes = [fixtures.node('C'), fixtures.node('I', ['C'], integration=True, write=())]
        self.revise(self.nodes)

    def optional(self, checker=None, review='extra'):
        artifact = self.engine.state(self.ledger, 'P1')['nodes']['C']['artifact']
        return review_dispatch.optional(self.ledger, 'P1', 'C', review, checker, artifact,
            execution={'method': 'adapter', 'implementation': 'fixture-checker-v1', 'configuration': {},
                       'environment': {'fixture': 'local'}, 'provenance': {'adapter': 'test_wf_review_dispatch'}})

    def test_light_optional_skip_does_not_complete_node_and_required_engine_checker_runs(self):
        self.step()
        checker = Mock(side_effect=AssertionError('optional reviewer must not run'))
        before = self.ledger.requests()
        with patch.object(routing, 'validate_decision', wraps=routing.validate_decision) as validate:
            result = self.optional(checker)
            self.assertEqual(result['status'], 'skipped')
            self.assertEqual(self.engine.state(self.ledger, 'P1')['nodes']['C']['state'], 'produced')
            required_checker = Mock(wraps=self.checker)
            verified = self.verify('C', required_checker)
            self.assertEqual(verified['result'], 'pass')
            self.assertEqual(required_checker.call_count, 1)
            self.assertGreaterEqual(validate.call_count, 2)
        self.assertEqual(checker.call_count, 0)
        self.assertEqual(self.ledger.requests(), before)
        rules = [p for k, p in self.events() if k == 'decision.recorded' and p['subject']['component'] == 'review_policy']
        self.assertEqual({p['validity']['action'] for p in rules}, {'SKIP', 'REVIEW'})
        self.assertTrue(all(p['subject']['model'] == 'rules' for p in rules))
        self.assertFalse(any(p['scope'] == 'C' and p['validity']['action'] == 'SKIP' for p in rules))

    def test_required_subset_and_mutant_skip_are_refused_before_checker(self):
        self.step()
        with self.assertRaisesRegex(LedgerError, 'every configured'):
            review_dispatch.required(self.ledger, 'P1', 'C', [])
        checker = Mock(wraps=self.checker)
        with patch.object(review_policy, 'decide', return_value={'action': 'SKIP'}):
            with self.assertRaisesRegex(LedgerError, 'cannot be skipped'):
                self.verify('C', checker)
        self.assertEqual(checker.call_count, 0)
        self.assertEqual(self.engine.state(self.ledger, 'P1')['nodes']['C']['state'], 'produced')

    def test_unproduced_defer_and_held_hold_do_not_call_or_create_request(self):
        checker = Mock(side_effect=AssertionError('not ready'))
        self.assertEqual(self.optional(checker)['decision']['action'], 'DEFER')
        self.step()
        with self.ledger.transaction(write=True) as conn:
            view = self.engine.state(self.ledger, 'P1', conn)
            self.engine._event(self.ledger, conn, view, 'C', 'node.held', reason='fixture unresolved input', classification='unknown')
        self.assertEqual(self.optional(checker)['decision']['action'], 'HOLD')
        self.assertEqual(checker.call_count, 0)
        self.assertEqual(self.ledger.requests(), [])

    def test_only_approved_optional_ids_and_no_required_gate_alias(self):
        self.step()
        checker = Mock()
        for name in ('unapproved-review', 'C', 'M1', 'check-I'):
            with self.assertRaises(LedgerError): self.optional(checker, name)
        self.assertEqual(checker.call_count, 0)

    def test_reapproval_requires_internal_rebase_before_review(self):
        self.step()
        with self.ledger.transaction() as conn:
            root = plan.anchor_events(self.ledger, conn, 'P1')
            contract, _ = plan.load(self.ledger, root, root['approved']['revision'])
        contract['title'] = 'Reapproved contract'
        plan.amend(self.ledger, 'P1', contract, 'Fixture changed root terms', 'codex')
        with patch.dict('os.environ', {'ONECREW_ACTOR': 'user'}):
            plan.approve(self.ledger, 'P1', 'owner', 'Temporary fixture reapproval')
        checker = Mock(wraps=self.checker)
        with self.assertRaisesRegex(LedgerError, 'Revise the internal plan'):
            self.optional(checker)
        with self.assertRaisesRegex(LedgerError, 'Revise the internal plan'):
            self.verify('C', checker)
        self.assertEqual(checker.call_count, 0)

    def test_change_during_required_decision_refuses_spend_on_captured_old_node(self):
        self.step()
        original = review_dispatch.required
        def changing(*args):
            decision = original(*args)
            changed = copy.deepcopy(self.nodes); changed[0]['goal'] = 'Changed before checker dispatch'
            self.revise(changed)
            return decision
        checker = Mock(wraps=self.checker)
        with patch.object(review_dispatch, 'required', side_effect=changing):
            with self.assertRaises(LedgerError): self.verify('C', checker)
        self.assertEqual(checker.call_count, 0)
        self.assertNotIn('node.verification', self.kinds())

    def test_runtime_unknown_holds_optional_and_required_review_before_spend(self):
        from onecrew.v2 import runtime_unknowns
        self.step()
        runtime_unknowns.open_unknown(self.ledger, 'P1', 'U-review', question='Which format is required?',
            affected=['C'], required_by=['C'], resolver='doc', evidence=['a.txt:1'])
        checker = Mock(wraps=self.checker)
        self.assertEqual(self.optional(checker)['status'], 'held')
        self.assertEqual(review_dispatch.required(self.ledger, 'P1', 'C', ['check-C'])['action'], 'HOLD')
        with self.assertRaises(LedgerError): self.verify('C', checker)
        self.assertEqual(checker.call_count, 0)
        self.assertEqual(self.ledger.requests(), [])


class DeepReviewDispatchTests(ReviewDispatchTests):
    depth = 'deep'

    # These tests use the same real engine fixture with deep optional policy.
    test_light_optional_skip_does_not_complete_node_and_required_engine_checker_runs = None

    def test_provider_output_action_is_only_observation_and_cached_per_engine_inputs(self):
        self.step()
        checker = Mock(side_effect=lambda item, artifact: {'artifact': artifact, 'action': 'SKIP', 'HOLD': True, 'result': 'pass'})
        first = self.optional(checker)
        self.assertEqual(first['decision']['action'], 'REVIEW')
        self.assertEqual(first['status'], 'observed')
        self.assertTrue(first['executed'])
        self.assertEqual(self.engine.state(self.ledger, 'P1')['nodes']['C']['state'], 'produced')
        second = self.optional(checker)
        self.assertTrue(second['cached_observation']); self.assertEqual(checker.call_count, 1)
        self.assertEqual(first['receipt'], second['receipt'])
        body = json.loads(self.store.read_blob(first['receipt']))
        self.assertEqual(body['authority'], 'none')
        self.assertEqual(body['observed']['action'], 'SKIP')
        rules = [p for k, p in self.events() if k == 'decision.recorded' and p['subject']['component'] == 'review_policy']
        self.assertEqual({p['validity']['action'] for p in rules}, {'REVIEW'})
        changed = copy.deepcopy(self.nodes); changed[0]['goal'] = 'Revised internal decomposition'
        self.revise(changed)
        deferred = self.optional(checker)
        self.assertEqual(deferred['decision']['action'], 'DEFER')
        self.assertNotEqual(first['decision']['validity']['input_sha'], deferred['decision']['validity']['input_sha'])
        self.assertEqual(checker.call_count, 1)

    def test_late_optional_output_after_replan_is_retained_without_verification(self):
        self.step()
        def late(item, artifact):
            changed = copy.deepcopy(self.nodes); changed[0]['goal'] = 'Changed during optional review'
            self.revise(changed)
            return {'artifact': artifact, 'result': 'pass', 'action': 'REVIEW'}
        out = self.optional(late)
        self.assertEqual(out['status'], 'stale_observation')
        self.assertEqual(self.kinds().count('review.observed'), 1)
        self.assertNotIn('node.verification', self.kinds())
        self.assertIsNone(self.engine.state(self.ledger, 'P1')['nodes']['C']['state'])
