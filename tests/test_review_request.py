"""2.5-A request identity: local data only, never reviewer or policy authority."""
import copy
import json
import unittest

from onecrew.ledger import LedgerError, content_hash
from onecrew.v2 import review_request, review_dispatch, review_policy
from tests import test_wf_engine as fixtures


def execution(method='adapter'):
    value = {'method': method, 'implementation': 'fixture-checker-v1',
             'configuration': {'checks': ['M1']}, 'environment': {'tool': 'fixture-1'},
             'provenance': {'source': 'test-only'}}
    if method in ('reviewer', 'investigation'):
        value.update(provider='fixture-provider', model='fixture-model')
    return value


def arguments():
    return {'root': {'project_id': 'project-one', 'task_id': 'root-one'},
            'contract_revision': 1, 'contract_sha': 'a' * 64, 'review_id': 'extra', 'required': False,
            'facts': {'node': 'C', 'contract_sha': 'a' * 64, 'internal_revision': 1,
                      'generation': 1, 'artifact': 'b' * 64, 'inputs': {'D': {'artifact': 'c' * 64, 'generation': 1}},
                      'checks_sha': content_hash([{'id': 'M1', 'spec': 'Expected output'}]),
                      'state': 'produced', 'phase': 'ready', 'unknowns': [], 'findings': []},
            'scope': {'read': ['a.txt', 'b.txt'], 'write': ['out.txt'], 'acceptance': ['O1']},
            'criteria': [{'id': 'M1', 'spec': 'Expected output'}],
            'policy': {'depth': 'deep', 'optional_reviews': ['extra']},
            'authority': {'edit': False, 'commands': False}, 'budget': {'max_calls': 5, 'time': 120},
            'execution': execution()}


class RequestIdentity(unittest.TestCase):
    def test_stable_detached_request_and_unordered_mapping_and_scope(self):
        args = arguments(); before = copy.deepcopy(args)
        first = review_request.build(**args)
        args['scope']['read'].reverse()
        args['execution']['configuration'] = dict(reversed(list(args['execution']['configuration'].items())))
        second = review_request.build(**args)
        self.assertEqual(first, second)
        self.assertTrue(first['execution_complete'])
        self.assertEqual(review_request.applicability(first, second),
                         {'applicable': True, 'reusable': True, 'reasons': []})
        args['facts']['inputs'].clear()
        self.assertEqual(first, review_request.build(**before))
        self.assertEqual(first, json.loads(json.dumps(first)))

    def test_each_semantic_dimension_changes_request_and_rejects_reuse(self):
        base = arguments(); first = review_request.build(**base)
        mutations = [
            lambda a: a['root'].update(project_id='other-project'),
            lambda a: a['root'].update(task_id='other-root'),
            lambda a: a.update(contract_revision=2),
            lambda a: (a.update(contract_sha='d'*64), a['facts'].update(contract_sha='d'*64)),
            lambda a: a.update(review_id='other-review'), lambda a: a.update(required=True),
            lambda a: a['facts'].update(node='I'), lambda a: a['facts'].update(generation=2),
            lambda a: a['facts'].update(internal_revision=2), lambda a: a['facts'].update(artifact='e'*64),
            lambda a: a['facts']['inputs']['D'].update(generation=2),
            lambda a: a['facts'].update(state='verified'), lambda a: a['facts'].update(phase='held'),
            lambda a: a['facts']['unknowns'].append('U1'), lambda a: a['facts']['findings'].append('F1'),
            lambda a: a['scope']['read'].append('c.txt'), lambda a: a['scope']['acceptance'].append('O2'),
            lambda a: (a.update(criteria=[{'id':'M1','spec':'Different output'}]),
                       a['facts'].update(checks_sha=content_hash([{'id':'M1','spec':'Different output'}]))),
            lambda a: a['policy'].update(depth='light'), lambda a: a['authority'].update(commands=True),
            lambda a: a['budget'].update(max_calls=6),
            lambda a: a['execution'].update(implementation='fixture-checker-v2'),
            lambda a: a['execution']['configuration'].update(threshold=2),
            lambda a: a['execution']['environment'].update(tool='fixture-2'),
            lambda a: a['execution']['provenance'].update(source='other-source'),
        ]
        for change in mutations:
            args = copy.deepcopy(base); change(args)
            with self.subTest(args=args):
                other = review_request.build(**args)
                self.assertNotEqual(first['id'], other['id'])
                assessment = review_request.applicability(first, other)
                self.assertFalse(assessment['applicable']); self.assertFalse(assessment['reusable'])
                self.assertTrue(assessment['reasons'])

    def test_method_and_actual_provider_model_do_not_collapse(self):
        args = arguments(); args['execution'] = execution('reviewer')
        first = review_request.build(**args)
        for field, value in [('method', 'investigation'), ('provider', 'other'), ('model', 'other')]:
            other = copy.deepcopy(args); other['execution'][field] = value
            self.assertNotEqual(first['id'], review_request.build(**other)['id'])

    def test_unknown_execution_can_be_observed_but_cannot_be_reused(self):
        for metadata in (None, {}, {'method': 'reviewer'}, dict(execution('reviewer'), model=None)):
            args = arguments(); args['execution'] = metadata
            request = review_request.build(**args)
            self.assertFalse(request['execution_complete']); self.assertTrue(request['missing'])
            same = review_request.applicability(request, request)
            self.assertTrue(same['applicable']); self.assertFalse(same['reusable']); self.assertTrue(same['reasons'])

    def test_execution_unknown_sentinels_ignore_surrounding_whitespace_and_case(self):
        for key in ('method', 'implementation', 'provider', 'model'):
            for sentinel in (' unknown ', '\tUnKnOwN\n', ' UNVERIFIED ', '\nunVerified\t'):
                args = arguments(); args['execution'] = execution('reviewer'); args['execution'][key] = sentinel
                with self.subTest(key=key, sentinel=sentinel):
                    request = review_request.build(**args)
                    self.assertFalse(request['execution_complete'])
                    self.assertIn('execution.' + key, request['missing'])
                    self.assertFalse(review_request.applicability(request, request)['reusable'])

    def test_actual_execution_identifiers_trim_outer_whitespace_but_preserve_case(self):
        args = arguments(); args['execution'] = execution('reviewer')
        original = review_request.build(**args)
        for key in ('method', 'implementation', 'provider', 'model'):
            args['execution'][key] = ' \t' + args['execution'][key] + '\n '
        self.assertEqual(review_request.build(**args), original)
        args['execution']['model'] = 'Fixture-Model'
        self.assertNotEqual(review_request.build(**args)['id'], original['id'])

    def test_sensitive_execution_details_are_only_fingerprints(self):
        args = arguments(); args['execution']['configuration']['secret'] = 'private-value-not-for-receipt'
        args['execution']['environment']['TOKEN'] = 'private-env-not-for-receipt'
        args['execution']['provenance']['internal'] = 'private-provenance-not-for-receipt'
        request = review_request.build(**args)
        for secret in ('private-value-not-for-receipt', 'private-env-not-for-receipt', 'private-provenance-not-for-receipt'):
            self.assertNotIn(secret, json.dumps(request))

    def test_invalid_and_inconsistent_input_refused_not_silently_dropped(self):
        mutations = [lambda a: a.update(required=1), lambda a: a.update(contract_revision=True),
                     lambda a: a['root'].update(task_id=''), lambda a: a['facts'].update(node=None),
                     lambda a: a['facts'].update(contract_sha='wrong'), lambda a: a['facts'].update(checks_sha='wrong'),
                     lambda a: a['facts'].update(inputs=[]), lambda a: a['facts'].update(artifact=None),
                     lambda a: a['scope']['read'].append('a.txt'), lambda a: a['criteria'].append(a['criteria'][0]),
                     lambda a: a['execution'].update(configuration=[]), lambda a: a['execution'].update(method='auto'),
                     lambda a: a['execution'].update(environment={'bad': float('nan')}),
                     lambda a: a['budget'].update(remaining_seconds=100)]
        for change in mutations:
            args = arguments(); change(args)
            with self.subTest(args=args), self.assertRaises(LedgerError): review_request.build(**args)

    def test_forged_or_legacy_descriptor_never_gets_applicable_or_reusable(self):
        request = review_request.build(**arguments())
        forged = copy.deepcopy(request); forged['identity']['required'] = True
        unknown_args = arguments(); unknown_args['execution'] = None
        forged_complete = review_request.build(**unknown_args); forged_complete['execution_complete'] = True
        for previous in (None, {}, {'id': request['id']}, forged, forged_complete):
            result = review_request.applicability(previous, request)
            self.assertFalse(result['applicable']); self.assertFalse(result['reusable'])

    def test_recomputed_hash_does_not_make_malformed_descriptor_valid(self):
        for alter in (lambda r: r['identity'].update(required=1),
                      lambda r: r['identity']['root'].update(task_id=''),
                      lambda r: r['identity']['execution'].update(method='made-up'),
                      lambda r: r['identity']['execution'].update(environment=content_hash({})),
                      lambda r: r['identity']['execution'].update(implementation='unknown'),
                      lambda r: r['identity']['execution'].update(implementation=' UnKnOwN '),
                      lambda r: r['identity']['execution'].update(provider=' unknown '),
                      lambda r: r['identity']['execution'].update(model=' UNVERIFIED ')):
            request = review_request.build(**arguments()); alter(request)
            request['id'] = 'review-' + content_hash({'version': 1, 'identity': request['identity']})
            self.assertFalse(review_request.applicability(request, request)['applicable'])

    def test_first_generation_zero_valid_and_live_usage_is_not_request_budget(self):
        args = arguments(); args['facts']['generation'] = 0
        self.assertTrue(review_request.build(**args)['execution_complete'])
        for key in ('remaining_seconds', 'remaining_calls', 'used_calls', 'used_seconds', 'spent', 'usage'):
            changed = copy.deepcopy(args); changed['budget'][key] = 1
            with self.subTest(key=key), self.assertRaises(LedgerError): review_request.build(**changed)


class ActualReviewContext(fixtures.EngineFixture):
    def test_real_context_changes_and_request_build_does_not_write_ledger(self):
        self.revise([fixtures.node('C'), fixtures.node('I', ['C'], integration=True, write=())]); self.step()
        root, contract, item, facts = review_dispatch._context(self.ledger, 'P1', 'C')
        before = self.events()
        request = review_request.build(root={'project_id': self.ledger.project_id, 'task_id': root['task_id']},
            contract_revision=root['approved']['revision'], contract_sha=root['approved']['sha'],
            review_id='extra', required=False, facts=facts,
            scope={key: item[key] for key in ('read','write','acceptance')}, criteria=item['checks'],
            policy=review_policy.normalize(contract.get('review_policy', review_policy.DEFAULT)),
            authority=contract.get('authority', {}), budget=contract['budget'], execution=execution())
        self.assertTrue(request['execution_complete']); self.assertEqual(before, self.events())
        self.assertEqual(facts['state'], 'produced')
        self.assertFalse(any(k == 'node.verification' for k, _ in self.events()))
        with self.ledger.transaction(write=True) as conn:
            view = self.engine.state(self.ledger, 'P1', conn)
            self.engine._event(self.ledger, conn, view, 'C', 'node.held', reason='New uncertainty', classification='unknown')
        root2, contract2, item2, facts2 = review_dispatch._context(self.ledger, 'P1', 'C')
        current = review_request.build(root={'project_id': self.ledger.project_id, 'task_id': root2['task_id']},
            contract_revision=root2['approved']['revision'], contract_sha=root2['approved']['sha'],
            review_id='extra', required=False, facts=facts2,
            scope={key: item2[key] for key in ('read','write','acceptance')}, criteria=item2['checks'],
            policy=review_policy.normalize(contract2.get('review_policy', review_policy.DEFAULT)),
            authority=contract2.get('authority', {}), budget=contract2['budget'], execution=execution())
        self.assertEqual(facts2['artifact'], facts['artifact'])
        self.assertEqual(facts2['generation'], facts['generation'])
        self.assertFalse(review_request.applicability(request, current)['applicable'])


if __name__ == '__main__': unittest.main()
