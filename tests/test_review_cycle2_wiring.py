"""Cycle 2 integration: the REAL `review_dispatch.optional` call site of RD-A, and what a Jev call is recorded as.

`test_review_rda2_dispatch` mirrors the call site by hand; these drive the dispatcher itself.
"""
import json
from unittest.mock import Mock, patch

from onecrew import budget_core, task_intake
from onecrew.ledger import LedgerError
from onecrew.v2 import plan, review_advice, review_dispatch
from tests import test_wf_engine as engine_fixtures
from tests.test_review_rda2_lifecycle import KEY, Provider
from tests.test_v2_l1 import plan_json

EXECUTION = {'method': 'adapter', 'implementation': 'fixture-checker-v1', 'configuration': {},
             'environment': {'fixture': 'local'}, 'provenance': {'adapter': 'test_review_cycle2_wiring'}}


class RealDispatcher(engine_fixtures.EngineFixture):
    grant = ['review_advice:suggest']

    def setUp(self):
        def make(**kw):
            kw['authority'] = dict(kw['authority'], granted_actions=list(self.grant))
            return plan_json(review_policy={'depth': 'deep', 'optional_reviews': ['extra']}, **kw)
        with patch.object(engine_fixtures, 'plan_json', side_effect=make):
            super().setUp()
        self.revise([engine_fixtures.node('C'), engine_fixtures.node('I', ['C'], integration=True, write=())])
        self.step()
        self.artifact = self.engine.state(self.ledger, 'P1')['nodes']['C']['artifact']
        self.checker = Mock(return_value={'result': 'pass', 'artifact': self.artifact})

    def optional(self, provider=None):
        original = review_advice.advise_optional
        def wired(*args, **kw):
            return original(*args, key=KEY, opener=provider, **kw) if provider else original(*args, **kw)
        with patch.object(review_advice, 'advise_optional', wired):
            return review_dispatch.optional(self.ledger, 'P1', 'C', 'extra', self.checker, self.artifact, execution=EXECUTION)

    def used(self):
        with self.ledger.transaction() as conn:
            return budget_core.group(conn, plan.anchor_events(self.ledger, conn, 'P1')['task_id'])['used_calls']

    def advice_tasks(self):
        with self.ledger.transaction() as conn:
            rows = conn.execute('SELECT payload FROM tasks').fetchall()
        return [json.loads(r['payload']) for r in rows if 'advice:' in r['payload']]

    def test_the_dispatcher_shows_a_proposal_and_keeps_its_decision(self):
        provider, before = Provider(), self.used()
        result = self.optional(provider)
        self.assertEqual((provider.calls, self.used()), (1, before + 1))
        self.assertEqual(result['advice']['status'], 'proposal')
        self.assertEqual(result['decision']['action'], 'REVIEW')
        self.assertEqual(result['advice']['effective_action'], 'REVIEW')
        self.assertFalse(result['advice']['grants_authority'])
        self.assertEqual((result['status'], result['executed'], self.checker.call_count), ('observed', True, 1))
        self.assertEqual(self.engine.state(self.ledger, 'P1')['nodes']['C']['state'], 'produced')

    def test_a_jev_call_is_recorded_as_jev_not_as_a_claude_call(self):
        self.optional(Provider())
        tasks = self.advice_tasks()
        self.assertEqual(len(tasks), 1)
        text = json.dumps(tasks[0])
        self.assertIn('"jev"', text)
        self.assertNotIn('"claude"', text)
        with self.ledger.transaction() as conn:
            launched = [r['identity'] for r in conn.execute('SELECT identity FROM attempts').fetchall() if r['identity'] and 'verifier-controller' in r['identity']]
        self.assertEqual([json.loads(item)['provider'] for item in launched][-1:], ['jev'])

    def test_a_second_call_on_the_same_input_makes_no_second_jev_call(self):
        provider = Provider()
        self.optional(provider)
        before = self.used()
        self.optional(provider)
        self.assertEqual((provider.calls, self.used()), (1, before))

    def test_a_failing_provider_changes_nothing_in_the_review(self):
        result = self.optional(Provider('error'))
        self.assertEqual(result['advice']['status'], 'fallback')
        self.assertEqual((result['status'], self.checker.call_count), ('observed', 1))

    def test_an_exception_inside_advice_never_reaches_the_review(self):
        with patch.object(review_advice, 'advise', side_effect=RuntimeError('boom')):
            result = review_dispatch.optional(self.ledger, 'P1', 'C', 'extra', self.checker, self.artifact, execution=EXECUTION)
        self.assertEqual((result['status'], self.checker.call_count), ('observed', 1))

    def test_skip_decision_makes_no_advice_call(self):
        provider = Provider()
        with patch.object(review_dispatch, '_decide', return_value={'action': 'SKIP', 'record': {'key': 'k'}}):
            result = self.optional(provider)
        self.assertEqual((result['status'], provider.calls, self.checker.call_count), ('skipped', 0, 0))
        self.assertNotIn('advice', result)


class NoGrant(RealDispatcher):
    grant = []

    def test_the_dispatcher_shows_a_proposal_and_keeps_its_decision(self):
        provider, before = Provider(), self.used()
        result = self.optional(provider)
        self.assertEqual((provider.calls, self.used()), (0, before))
        self.assertNotEqual(result['advice']['status'], 'proposal')
        self.assertEqual((result['status'], self.checker.call_count), ('observed', 1))

    test_a_jev_call_is_recorded_as_jev_not_as_a_claude_call = None
    test_a_second_call_on_the_same_input_makes_no_second_jev_call = None
    test_a_failing_provider_changes_nothing_in_the_review = None


class IntakeLabel(engine_fixtures.EngineFixture):
    def test_jev_stays_refused_for_every_other_submission(self):
        with self.assertRaises(LedgerError):
            task_intake.submit(self.ledger, 'a job', 'plain-jev-job', provider='jev', model='jev-latest')
