"""RD-A1: fake Jev responses never alter policy or invoke a reviewer."""
import copy
import io
import json
import unittest
from unittest.mock import patch

from onecrew.ledger import LedgerError, content_hash
from onecrew.v2 import review_advice

KEY = 'synthetic-test-credential-only'


class Client:
    def __init__(self, result=None, error=None):
        self.result, self.error, self.requests = result, error, []

    def open(self, request, timeout):
        self.requests.append(request)
        if self.error:
            raise self.error
        assert timeout == 15
        assert request.get_header('Authorization') == 'Bearer ' + KEY
        return io.BytesIO(json.dumps(self.result).encode())


class AdviceTests(unittest.TestCase):
    def setUp(self):
        self.policy = {'depth': 'standard', 'optional_reviews': ['extra']}
        self.options = [
            {'id': 'mechanical', 'label': 'Run the supplied check', 'action': 'REVIEW', 'method': 'command', 'checkpoint': 'output-ready'},
            {'id': 'inspect', 'label': 'Inspect the supplied evidence', 'action': 'REVIEW', 'method': 'bounded_review', 'checkpoint': 'output-ready'},
        ]
        self.validity = {'revision': 1, 'contract_sha': 'a' * 64, 'input_sha': 'b' * 64,
                         'policy_sha': content_hash(self.policy), 'budget_revision': 'grant-1'}
        self.args = dict(policy=self.policy, node='extra', evidence=['artifact:a', 'criterion:C1'], validity=self.validity,
                         configured=True, permitted=True, remaining_calls=1, key=KEY)

    def response(self, choice='option1', confidence=.9):
        return {'model': 'jev-test-1', 'answers': {'workflow': {'type': 'choice', 'choice': choice, 'confidence': confidence,
            'probabilities': {x: confidence if x == choice else (1 - confidence) / 2 for x in ('option0', 'option1', 'abstain')}}},
            'usage': {'input_tokens': 30, 'output_tokens': 2}}

    def suggest(self, client=None, **changes):
        args = dict(self.args, **changes)
        return review_advice.suggest('Check the supplied result.', self.options, opener=client or Client(self.response()), **args)

    def test_same_path_for_code_and_document_proposes_without_changing_baseline(self):
        for brief, stage in [('Check arithmetic output.', 'review'), ('Choose checks for the edited document.', 'step0')]:
            client = Client(self.response())
            before = copy.deepcopy((self.options, self.args))
            out = review_advice.suggest(brief, self.options, opener=client, stage=stage, **self.args)
            self.assertEqual(out['status'], 'proposal')
            self.assertEqual(out['proposal']['option']['id'], 'inspect')
            self.assertEqual(out['baseline']['action'], 'REVIEW')
            self.assertEqual(out['effective_action'], 'REVIEW')
            self.assertFalse(out['automatic_application'])
            self.assertFalse(out['dispatch_enabled'])
            self.assertFalse(out['quality_calibrated'])
            self.assertEqual(out['authority'], 'proposal_only')
            self.assertEqual(out['validity'], self.validity)
            self.assertEqual(len(client.requests), 1)
            self.assertEqual((self.options, self.args), before)
            body = json.loads(client.requests[0].data)
            self.assertEqual(body['state']['stage'], stage)
            self.assertNotIn(KEY, json.dumps(out))

    def test_no_permission_configuration_budget_or_choice_never_reads_credentials_or_calls(self):
        for changed in ({'permitted': False}, {'configured': False}, {'remaining_calls': 0}):
            client = Client(self.response())
            with patch('onecrew.decision_client_core.load_key', side_effect=AssertionError('must not read credentials')):
                out = self.suggest(client, key=None, **changed)
            self.assertEqual(out['calls'], 0)
            self.assertEqual(out['effective_action'], 'REVIEW')
            self.assertEqual(client.requests, [])
        self.options = self.options[:1]
        client = Client(self.response())
        out = self.suggest(client)
        self.assertEqual(out['calls'], 0)
        self.assertEqual(client.requests, [])

    def test_unknowns_findings_and_not_ready_keep_policy_and_do_not_call(self):
        for changed, expected in (({'unknowns': ['U1']}, 'HOLD'), ({'findings': ['F1']}, 'HOLD'), ({'ready': False}, 'DEFER')):
            client = Client(self.response())
            out = self.suggest(client, **changed)
            self.assertEqual(out['effective_action'], expected)
            self.assertEqual(out['calls'], 0)
            self.assertEqual(client.requests, [])

    def test_mandatory_and_standard_policy_exclude_skip_before_network(self):
        self.options.append({'id': 'skip', 'label': 'Do not review', 'action': 'SKIP', 'method': 'command', 'checkpoint': 'now'})
        for mandatory in (True, False):
            client = Client(self.response())
            out = self.suggest(client, mandatory=mandatory)
            self.assertEqual(out['effective_action'], 'REVIEW')
            self.assertNotIn('skip', json.dumps(json.loads(client.requests[0].data)['questions']['workflow']['criteria']).lower())
        bad = self.response('option2')
        bad['answers']['workflow']['probabilities'] = {'option0': .05, 'option1': .05, 'option2': .9}
        out = self.suggest(Client(bad), mandatory=True)
        self.assertEqual(out['status'], 'fallback')
        self.assertEqual(out['effective_action'], 'REVIEW')

    def test_light_optional_may_propose_review_but_never_apply_it(self):
        self.policy['depth'] = 'light'
        self.validity['policy_sha'] = content_hash(self.policy)
        out = self.suggest()
        self.assertEqual(out['baseline']['action'], 'SKIP')
        self.assertEqual(out['proposal']['option']['action'], 'REVIEW')
        self.assertEqual(out['effective_action'], 'SKIP')

    def test_single_attempt_fallback_for_timeout_auth_and_invalid_output(self):
        from urllib.error import HTTPError
        clients = [Client(error=TimeoutError(KEY)), Client(error=HTTPError('https://invalid', 401, KEY, {}, None)), Client({'model': 'bad'})]
        for client in clients:
            out = self.suggest(client)
            self.assertEqual(out['status'], 'fallback')
            self.assertEqual(out['calls'], 1)
            self.assertEqual(out['effective_action'], 'REVIEW')
            self.assertEqual(len(client.requests), 1)
            self.assertNotIn(KEY, json.dumps(out))

    def test_missing_credential_fallback_has_zero_network_calls(self):
        from onecrew.decision_client_core import JevError
        client = Client(self.response())
        with patch('onecrew.decision_client_core.load_key', side_effect=JevError(KEY)):
            out = self.suggest(client, key=None)
        self.assertEqual(out['status'], 'fallback')
        self.assertEqual(out['calls'], 0)
        self.assertEqual(client.requests, [])
        self.assertNotIn(KEY, json.dumps(out))

    def test_abstain_and_low_confidence_remain_proposals_not_effects(self):
        out = self.suggest(Client(self.response('abstain')))
        self.assertEqual(out['status'], 'abstain')
        self.assertIsNone(out['proposal'])
        self.assertEqual(out['effective_action'], 'REVIEW')
        out = self.suggest(Client(self.response(confidence=.6)))
        self.assertTrue(out['proposal']['requires_review'])
        self.assertFalse(out['automatic_application'])

    def test_invalid_context_source_validity_and_flags_refused_before_call(self):
        bad_args = [dict(evidence=[]), dict(evidence=['']), dict(permitted='yes'), dict(configured=1),
                    dict(remaining_calls=True), dict(remaining_calls=-1), dict(stage='poll'),
                    dict(validity=dict(self.validity, policy_sha='c' * 64)),
                    dict(validity=dict(self.validity, revision=True)), dict(validity={})]
        for changes in bad_args:
            with self.subTest(changes=changes), self.assertRaises(LedgerError):
                self.suggest(Client(error=AssertionError('network')), **changes)

    def test_secret_and_oversized_context_are_refused_before_network(self):
        for brief in ('x' * 2001, 'Authorization: Bearer sk-' + 'a' * 45):
            with self.assertRaises(LedgerError):
                review_advice.suggest(brief, self.options, opener=Client(error=AssertionError('network')), **self.args)
        self.options[0]['label'] = 'Authorization: Bearer sk-' + 'b' * 45
        with self.assertRaises(LedgerError):
            self.suggest(Client(error=AssertionError('network')))

    def test_no_unsupported_option_fields_or_invented_actions(self):
        for field, value in (('provider', 'other'), ('action', 'PASS'), ('method', 'grant-authority')):
            options = copy.deepcopy(self.options)
            options[0][field] = value
            with self.assertRaises(LedgerError):
                review_advice.suggest('Check.', options, opener=Client(error=AssertionError('network')), **self.args)


if __name__ == '__main__':
    unittest.main()
