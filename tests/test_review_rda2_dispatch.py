"""RD-A2 call site: advice drives the way `review_dispatch.optional` would call it (REVIEW decided, review not yet opened).

The wiring line (done by the main session at integration, not here because review_dispatch.py belongs to 2.5-B) is mirrored by
`optional_with_advice`. These tests prove the exposed function against the real engine facts and the real optional lifecycle; they do
not prove the dispatcher edit itself.
"""
import copy
import json
from unittest.mock import Mock, patch

from onecrew import budget_core
from onecrew.v2 import plan, review_advice, review_dispatch
from tests import test_wf_engine as engine_fixtures
from tests.test_review_rda2_lifecycle import KEY, Provider
from tests.test_v2_l1 import plan_json

EXECUTION = {'method': 'adapter', 'implementation': 'fixture-checker-v1', 'configuration': {},
             'environment': {'fixture': 'local'}, 'provenance': {'adapter': 'test_review_rda2_dispatch'}}


class DispatchWiring(engine_fixtures.EngineFixture):
    def setUp(self):
        def make(**kw):
            kw['authority'] = dict(kw['authority'], granted_actions=['review_advice:suggest'])
            return plan_json(review_policy={'depth': 'deep', 'optional_reviews': ['extra']}, **kw)
        with patch.object(engine_fixtures, 'plan_json', side_effect=make):
            super().setUp()
        self.nodes = [engine_fixtures.node('C'), engine_fixtures.node('I', ['C'], integration=True, write=())]
        self.revise(self.nodes)
        self.step()

    def artifact(self):
        return self.engine.state(self.ledger, 'P1')['nodes']['C']['artifact']

    def optional_with_advice(self, checker, provider):
        """What review_dispatch.optional does after _decide() == REVIEW, with the one added call (advice never alters the flow)."""
        _, _, _, facts = review_dispatch._context(self.ledger, 'P1', 'C')
        advice = review_advice.advise_optional(self.ledger, 'P1', 'C', 'extra', facts=facts, key=KEY, opener=provider)
        result = review_dispatch.optional(self.ledger, 'P1', 'C', 'extra', checker, self.artifact(), execution=EXECUTION)
        return dict(result, advice=review_advice.compact(advice)), advice

    def advice_kinds(self):
        return [k for k in self.kinds() if k.startswith('review.advice')]

    def used(self):
        with self.ledger.transaction() as conn:
            return budget_core.group(conn, plan.anchor_events(self.ledger, conn, 'P1')['task_id'])['used_calls']

    def test_advice_before_open_then_the_review_runs_exactly_as_without_it(self):
        provider, checker = Provider(), Mock(return_value={'result': 'pass', 'artifact': self.artifact()})
        before = self.used()
        result, advice = self.optional_with_advice(checker, provider)
        self.assertEqual((advice['status'], provider.calls), ('proposal', 1))
        self.assertEqual(self.used(), before + 1)
        self.assertEqual((result['status'], result['executed'], checker.call_count), ('observed', True, 1))
        self.assertEqual(result['decision']['action'], 'REVIEW')
        self.assertEqual(result['advice']['effective_action'], 'REVIEW')
        self.assertFalse(result['advice']['grants_authority'])
        self.assertEqual(self.advice_kinds(), ['review.advice_started', 'review.advice'])
        self.assertNotIn('node.verification', self.kinds())               # advice and the optional observation complete nothing
        self.assertEqual(self.engine.state(self.ledger, 'P1')['nodes']['C']['state'], 'produced')

    def test_a_failing_provider_leaves_the_review_to_the_dispatcher(self):
        provider, checker = Provider('error'), Mock(return_value={'result': 'pass', 'artifact': self.artifact()})
        result, advice = self.optional_with_advice(checker, provider)
        self.assertEqual(advice['status'], 'fallback')
        self.assertEqual((result['status'], checker.call_count), ('observed', 1))

    def test_unusable_advice_arguments_never_stop_the_dispatcher(self):
        checker = Mock(return_value={'result': 'pass', 'artifact': self.artifact()})
        advice = review_advice.advise_optional(self.ledger, 'P1', 'C', 'extra', facts='not a mapping', key=KEY, opener=Provider())
        self.assertEqual((advice['status'], advice['reason']), ('fallback', 'advice_error'))
        result = review_dispatch.optional(self.ledger, 'P1', 'C', 'extra', checker, self.artifact(), execution=EXECUTION)
        self.assertEqual((result['status'], checker.call_count), ('observed', 1))

    def test_second_boundary_with_the_same_engine_facts_reuses_the_record_and_a_changed_node_asks_again(self):
        provider = Provider()
        self.optional_with_advice(Mock(return_value={'result': 'pass', 'artifact': self.artifact()}), provider)
        again, advice = self.optional_with_advice(Mock(side_effect=AssertionError('cached observation must not dispatch')), provider)
        self.assertEqual((advice['cache'], provider.calls, again['status']), ('hit', 1, 'observed'))
        changed = copy.deepcopy(self.nodes); changed[0]['goal'] = 'Changed after the first advice'
        self.revise(changed)
        self.step()
        fresh = review_advice.advise_optional(self.ledger, 'P1', 'C', 'extra', key=KEY, opener=provider,
                                              facts=review_dispatch._context(self.ledger, 'P1', 'C')[3])
        self.assertEqual((fresh['cache'], provider.calls), ('miss', 2))
        stale = [r for r in review_advice.show(self.ledger, 'P1')['records'] if not r['current']]
        self.assertEqual(len(stale), 1)
        self.assertIn('input', stale[0]['stale_because'])

    def test_mandatory_engine_check_id_is_never_given_a_skip_choice(self):
        provider = Provider()
        _, _, item, facts = review_dispatch._context(self.ledger, 'P1', 'C')
        advice = review_advice.advise(self.ledger, 'P1', stage='review', node='C', review_id='check-C', mandatory=True,
                                      brief='Choose how to run the required check.', facts=facts, key=KEY, opener=provider)
        self.assertEqual((advice['status'], advice['effective_action']), ('proposal', 'REVIEW'))
        self.assertNotIn('SKIP', json.dumps(provider.bodies[0]))
