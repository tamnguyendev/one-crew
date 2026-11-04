"""RD-A2: advice through the root lifecycle (budget, idempotency, cache, authority). Fake provider only.

A fake provider proves the wiring and the refusals, not the quality of a real model's suggestions.
"""
import copy
import io
import json
import os
import threading
import time
import unittest
from unittest.mock import patch

from onecrew import budget_core
from onecrew.ledger import LedgerError
from onecrew.snapshots import Snapshots
from onecrew.v2 import plan, review_advice
from tests.test_v2_l1 import Fixture, plan_json

KEY = 'synthetic-test-credential-only'
GRANT = {'edit': True, 'commands': True, 'granted_actions': ['review_advice:suggest']}


class Crash(BaseException):
    pass


class Provider:
    """Scripted Jev: mode good|wrong|malformed|error|skip|slow|crash."""
    def __init__(self, mode='good', delay=0.0, hold=None, entered=None):
        self.mode, self.delay, self.hold, self.entered = mode, delay, hold, entered
        self.calls, self.bodies = 0, []

    def open(self, request, timeout):
        self.calls += 1
        self.bodies.append(json.loads(request.data))
        if self.entered: self.entered.set()
        if self.hold and not self.hold.wait(20): raise RuntimeError('fixture release missing')
        if self.delay: time.sleep(self.delay)
        if self.mode == 'error': raise TimeoutError(KEY)
        if self.mode == 'crash': raise Crash()
        if self.mode == 'malformed': return io.BytesIO(b'{"nope": 1}')
        choices = list(self.bodies[-1]['questions']['workflow']['criteria'])
        names = sorted(c for c in choices if c != 'abstain')       # option0, option1, ...: the request body is key-sorted
        pick = {'good': names[min(1, len(names) - 1)], 'wrong': names[0], 'skip': 'skip'}.get(self.mode, names[0])
        probs = {c: (.9 if c == pick else .1 / max(1, len(choices) - 1)) for c in choices}
        if pick not in probs: probs = {c: 1 / len(choices) for c in choices}
        return io.BytesIO(json.dumps({'model': 'jev-fixture', 'usage': {'input_tokens': 10, 'output_tokens': 2},
            'answers': {'workflow': {'type': 'choice', 'choice': pick, 'confidence': .9, 'probabilities': probs}}}).encode())


class AdviceRoot(Fixture):
    authority = GRANT
    budget = {'max_calls': 10, 'time': 30}
    depth = 'standard'

    def setUp(self):
        super().setUp()
        plan.propose(self.ledger, 'P1', plan_json(review_policy={'depth': self.depth, 'optional_reviews': ['extra']},
            authority=self.authority, budget=self.budget), 'codex', workflow=True)
        plan.approve(self.ledger, 'P1', 'owner', 'fixture approval')
        os.environ['ONECREW_ACTOR'] = 'codex'
        self.facts = {'node': 'C', 'artifact': 'a' * 8, 'generation': 1}

    def advise(self, provider=None, **changes):
        provider = provider or Provider()
        args = dict(stage='review', node='C', review_id='extra', brief='Pick the check for the produced output.',
                    facts=self.facts, key=KEY, opener=provider)
        args.update(changes)
        return review_advice.advise(self.ledger, 'P1', **args), provider

    def group(self):
        with self.ledger.transaction() as conn:
            root = plan.anchor_events(self.ledger, conn, 'P1')
            return budget_core.group(conn, root['task_id'])

    def advice_events(self):
        with self.ledger.transaction() as conn:
            root = plan.anchor_events(self.ledger, conn, 'P1')
        return [(e['kind'], e['payload']) for e in self.ledger.events(root['task_id']) if e['kind'].startswith('review.advice')]

    def amend_root(self):
        with self.ledger.transaction() as conn:
            root = plan.anchor_events(self.ledger, conn, 'P1')
            contract, _ = plan.load(self.ledger, root, root['approved']['revision'])
        contract['title'] = 'Amended root'
        plan.amend(self.ledger, 'P1', contract, 'fixture amendment', 'codex')
        with patch.dict(os.environ, {'ONECREW_ACTOR': 'user'}):
            plan.approve(self.ledger, 'P1', 'owner', 'fixture reapproval')


class LifecycleTests(AdviceRoot):
    def test_first_call_charges_root_budget_and_records_a_neutral_event_with_receipt(self):
        before = self.group()['used_calls']
        result, provider = self.advise()
        self.assertEqual((result['status'], provider.calls, result['calls']), ('proposal', 1, 1))
        self.assertEqual(self.group()['used_calls'], before + 1)
        self.assertEqual(result['effective_action'], 'REVIEW')
        self.assertFalse(result['automatic_application'])
        self.assertFalse(result['grants_authority'])
        kinds = [k for k, _ in self.advice_events()]
        self.assertEqual(kinds, ['review.advice_started', 'review.advice'])
        recorded = self.advice_events()[1][1]
        self.assertEqual(recorded['receipt'], result['receipt'])
        self.assertTrue(recorded['explain'])
        body = json.loads(Snapshots(self.ledger.state_root).read_blob(result['receipt']))
        self.assertEqual(body['kind'], 'review-advice')
        for field in ('revision', 'contract_sha', 'policy_sha', 'input_sha', 'budget_revision'):
            self.assertIn(field, body['provenance'])
        self.assertNotIn(KEY, json.dumps(body))

    def test_same_input_returns_the_record_without_a_call_or_charge(self):
        first, provider = self.advise()
        used = self.group()['used_calls']
        again, _ = self.advise(provider)
        self.assertEqual((again['cache'], again['calls'], provider.calls), ('hit', 0, 1))
        self.assertEqual(again['receipt'], first['receipt'])
        self.assertEqual(again['proposal'], first['proposal'])
        self.assertEqual(self.group()['used_calls'], used)
        self.assertEqual(len(self.advice_events()), 2)

    def test_changed_input_is_a_new_call_and_the_old_record_is_stale_not_reused(self):
        first, provider = self.advise()
        self.facts = dict(self.facts, artifact='b' * 8)
        second, _ = self.advise(provider)
        self.assertEqual((second['cache'], provider.calls), ('miss', 2))
        self.assertNotEqual(first['key'], second['key'])
        shown = review_advice.show(self.ledger, 'P1')
        flags = {r['receipt']: r['current'] for r in shown['records']}
        self.assertEqual(flags, {first['receipt']: False, second['receipt']: True})
        self.assertIn('input', next(r for r in shown['records'] if not r['current'])['stale_because'])

    def test_contract_revision_change_is_never_served_from_the_old_record(self):
        first, provider = self.advise()
        self.amend_root()
        second, _ = self.advise(provider)
        self.assertEqual(provider.calls, 2)
        self.assertEqual(second['cache'], 'miss')
        stale = [r for r in review_advice.show(self.ledger, 'P1')['records'] if r['receipt'] == first['receipt']][0]
        self.assertFalse(stale['current'])
        self.assertTrue({'revision', 'contract'} & set(stale['stale_because']))

    def test_receipt_with_a_wrong_hash_is_not_used_and_nothing_is_replayed(self):
        first, provider = self.advise()
        with patch.object(Snapshots, 'read_blob', return_value=b'{"tampered": true}'):
            again, _ = self.advise(provider)
        self.assertEqual((again['status'], again['reason'], provider.calls), ('fallback', 'record_unreadable', 1))
        self.assertEqual(again['effective_action'], 'REVIEW')

    def test_mandatory_node_never_offers_skip_and_the_record_says_why(self):
        options = review_advice.default_options()
        result, provider = self.advise(review_id='M1', mandatory=True, options=options)
        sent = json.dumps(provider.bodies[0])
        self.assertNotIn('"action":"SKIP"', sent.replace(' ', ''))
        self.assertIn('skip', [w['id'] for w in result['withheld']])
        self.assertEqual(result['effective_action'], 'REVIEW')

    def test_standard_policy_optional_review_never_offers_skip_either(self):
        result, provider = self.advise()
        self.assertNotIn('SKIP', json.dumps(provider.bodies[0]))
        self.assertIn('skip', [w['id'] for w in result['withheld']])

    def test_provider_cannot_choose_a_skip_it_was_never_offered(self):
        result, provider = self.advise(Provider('skip'))
        self.assertEqual((result['status'], result['effective_action']), ('fallback', 'REVIEW'))
        self.assertIsNone(result['proposal'])

    def test_option_with_provider_model_or_pass_field_is_refused(self):
        for extra in ({'provider': 'codex'}, {'model': 'x'}, {'verdict': 'PASS'}):
            options = review_advice.default_options()
            options[0] = dict(options[0], **extra)
            provider = Provider()
            with self.assertRaises(LedgerError):
                self.advise(provider, options=options)
            self.assertEqual(provider.calls, 0)

    def test_pass_action_is_not_an_option_action(self):
        options = review_advice.default_options()
        options[0] = dict(options[0], action='PASS')
        with self.assertRaises(LedgerError):
            self.advise(options=options)

    def test_ledger_has_no_event_for_a_call_that_was_never_made(self):
        result, provider = self.advise(options=review_advice.default_options()[:1])
        self.assertEqual((result['status'], result['reason'], provider.calls), ('skipped', 'no_useful_choice', 0))
        self.assertEqual(self.advice_events(), [])
        self.assertEqual(self.group()['used_calls'], 0)


class StatelessLeaf(unittest.TestCase):
    def test_suggest_alone_has_no_memory_so_only_the_lifecycle_makes_one_call(self):
        """Behaviour of the RD-A1 leaf on the old base too: two identical requests are two provider calls and leave nothing behind."""
        from onecrew.ledger import content_hash
        policy = {'depth': 'standard', 'optional_reviews': ['extra']}
        validity = {'revision': 1, 'contract_sha': 'a' * 64, 'input_sha': 'b' * 64, 'policy_sha': content_hash(policy), 'budget_revision': 'g'}
        provider = Provider()
        for _ in range(2):
            review_advice.suggest('Check it.', review_advice.default_options()[:2], policy=policy, node='extra', evidence=['artifact:a'],
                                  validity=validity, configured=True, permitted=True, remaining_calls=5, key=KEY, opener=provider)
        self.assertEqual(provider.calls, 2)


class NoCommandGrant(AdviceRoot):
    authority = {'edit': True, 'commands': False, 'granted_actions': ['review_advice:suggest']}

    def test_option_beyond_the_root_grant_is_withheld_before_sending(self):
        result, provider = self.advise()
        self.assertEqual(provider.calls, 0)             # only 'bounded' remains: no useful choice, no call, no charge
        ids = {w['id']: w['reason'] for w in result['withheld']}
        self.assertEqual(ids['mechanical'], 'not_granted:commands')
        self.assertEqual(self.group()['used_calls'], 0)

    def test_two_granted_options_still_get_advice_and_never_the_withheld_one(self):
        options = review_advice.default_options()
        options.append({'id': 'bounded2', 'label': 'Second bounded look', 'action': 'REVIEW', 'method': 'bounded_review', 'checkpoint': 'after-output'})
        result, provider = self.advise(options=options)
        self.assertEqual(provider.calls, 1)
        self.assertNotIn('mechanical', json.dumps(provider.bodies[0]))
        self.assertNotEqual((result['proposal'] or {}).get('option', {}).get('id'), 'mechanical')


class NoAdviceGrant(AdviceRoot):
    authority = {'edit': True, 'commands': True}

    def test_without_the_named_grant_no_call_no_event_no_charge(self):
        result, provider = self.advise()
        self.assertEqual((result['status'], result['reason'], provider.calls), ('skipped', 'not_permitted', 0))
        self.assertEqual(self.advice_events(), [])
        self.assertEqual(self.group()['used_calls'], 0)
        self.assertEqual(result['effective_action'], 'REVIEW')


class TightBudget(AdviceRoot):
    budget = {'max_calls': 1, 'time': 30}

    def test_the_last_call_is_kept_for_real_work(self):
        result, provider = self.advise()
        self.assertEqual((result['status'], result['reason'], provider.calls), ('skipped', 'no_call_budget', 0))
        self.assertEqual(self.group()['used_calls'], 0)


class FailureTests(AdviceRoot):
    def test_error_falls_back_charges_one_attempt_and_never_retries_by_itself(self):
        result, provider = self.advise(Provider('error'))
        self.assertEqual((result['status'], result['calls'], result['effective_action']), ('fallback', 1, 'REVIEW'))
        self.assertNotIn(KEY, json.dumps(result))
        self.assertEqual(self.group()['used_calls'], 1)
        again, _ = self.advise(provider)
        self.assertEqual((again['cache'], provider.calls), ('hit', 1))
        self.assertEqual(again['status'], 'fallback')
        self.assertEqual(self.group()['used_calls'], 1)

    def test_malformed_response_is_a_fallback_too_and_refresh_is_the_only_way_to_call_again(self):
        result, provider = self.advise(Provider('malformed'))
        self.assertEqual(result['status'], 'fallback')
        provider.mode = 'good'
        refreshed, _ = self.advise(provider, refresh=True)
        self.assertEqual((refreshed['status'], provider.calls), ('proposal', 2))
        self.assertEqual(self.group()['used_calls'], 2)

    def test_crash_during_the_call_leaves_an_unknown_that_is_never_replayed(self):
        provider = Provider('crash')
        with self.assertRaises(Crash):
            self.advise(provider)
        again, _ = self.advise(provider)
        self.assertEqual((again['status'], provider.calls), ('unknown', 1))
        self.assertEqual(again['effective_action'], 'REVIEW')
        refreshed, _ = self.advise(provider, refresh=True)
        self.assertEqual((refreshed['status'], provider.calls), ('unknown', 1))
        self.assertEqual(self.group()['used_calls'], 1)

    def test_a_start_without_a_result_from_a_dead_process_is_unknown_not_pending(self):
        provider = Provider('good')
        with patch.object(review_advice, '_record', side_effect=Crash()):
            with self.assertRaises(Crash):
                self.advise(provider)
        with patch('onecrew.v2.verdict.process_alive', return_value=True):
            pending, _ = self.advise(provider)
        self.assertEqual(pending['status'], 'pending')
        with patch('onecrew.v2.verdict.process_alive', return_value=False):
            unknown, _ = self.advise(provider)
        self.assertEqual((unknown['status'], provider.calls), ('unknown', 1))

    def test_concurrent_callers_with_the_same_input_make_one_call(self):
        entered, release = threading.Event(), threading.Event()
        provider = Provider(hold=release, entered=entered)
        out = {}
        worker = threading.Thread(target=lambda: out.update(first=self.advise(provider)[0]))
        worker.start()
        try:
            self.assertTrue(entered.wait(20))
            second, _ = self.advise(provider)
            self.assertEqual((second['status'], second['calls']), ('pending', 0))
        finally:
            release.set(); worker.join(20)
        self.assertEqual((out['first']['status'], provider.calls), ('proposal', 1))

    def test_root_changed_while_the_call_ran_marks_the_record_not_current(self):
        provider = Provider()
        original = provider.open
        def changing(request, timeout):
            response = original(request, timeout)
            self.amend_root()
            return response
        provider.open = changing
        result, _ = self.advise(provider)
        self.assertEqual(result['status'], 'proposal')
        self.assertFalse(result['current'])
        self.assertFalse(result['reusable'])
        again, _ = self.advise(provider)
        self.assertEqual(provider.calls, 2)             # the old record is not reused for the new revision


class OperationalSafety(AdviceRoot):
    def test_advise_optional_never_raises_for_operational_failures(self):
        provider = Provider('error')
        out = review_advice.advise_optional(self.ledger, 'P1', 'C', 'extra', facts=self.facts, key=KEY, opener=provider)
        self.assertEqual(out['status'], 'fallback')
        self.assertEqual(out['effective_action'], 'REVIEW')
        missing = review_advice.advise_optional(self.ledger, 'NOPE', 'C', 'extra', facts=self.facts, key=KEY, opener=provider)
        self.assertEqual((missing['status'], missing['effective_action']), ('fallback', None))

    def test_unapproved_root_has_no_budget_so_step0_advice_is_skipped_with_a_reason(self):
        plan.propose(self.ledger, 'P2', plan_json(authority=GRANT), 'codex')
        provider = Provider()
        out = review_advice.advise_step0(self.ledger, 'P2', key=KEY, opener=provider)
        self.assertEqual((out['status'], out['reason'], provider.calls), ('skipped', 'root_not_approved', 0))

    def test_step0_on_an_approved_root_is_mandatory_so_it_never_offers_skip(self):
        provider = Provider()
        out = review_advice.advise_step0(self.ledger, 'P1', key=KEY, opener=provider)
        self.assertEqual((out['status'], out['stage']), ('proposal', 'step0'))
        self.assertNotIn('SKIP', json.dumps(provider.bodies[0]))
        self.assertEqual(out['effective_action'], 'REVIEW')


if __name__ == '__main__':
    unittest.main()
