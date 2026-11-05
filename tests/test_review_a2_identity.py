"""2.5-A cycle 2: build_check identity and evidence_status (pure, no ledger).

Counterexamples: changed criteria / candidate / env / config fingerprint, missing or 'unknown' execution metadata, a stored v1
descriptor, a neutral candidate change with and without a basis, and raw secrets that must never be stored.
"""
import copy
import json
import unittest

from onecrew.ledger import LedgerError, content_hash
from onecrew.v2 import review_request as rr
from onecrew.v2 import verification_evidence as ev
from tests.test_review_request import arguments as node_arguments

# A descriptor exactly as the cycle-1 `build` stored it (generated on base 01b10e1 from tests.test_review_request.arguments()).
V1_STORED = json.loads('{"version": 1, "id": "review-79190e2521624b5d07e77f92211439757bdfe137a1dcec121da655d4840cf527", "identity": {"root": {"project_id": "project-one", "task_id": "root-one"}, "contract_revision": 1, "contract_sha": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "review_id": "extra", "required": false, "facts": "80fe6d1b4fbfa2bff97c98ef12348008a1bc4e0b137689af41714c9cfc84133f", "scope": "a69d8828e35e5944878f7294d0e7e606a3c04cc670af1eacaad3faf90d7a942d", "criteria": "c0e0a2138cfb1cb89b1b302d5d32d1324789336cf7edfa86a5197105476c017a", "policy": "db12190895c34854cf82ef92f6da2f61f1cf1936967ed55cddb45ae230612cda", "authority": "e508494cac4a6b80fd0c9b3f3a4c64c6b6cc6a2241f8ec6f11b965367ad89958", "budget": "e7dd029b30c7b76c5f3f9a203b15da0cdc3b01d1cb5f024bc12aa459f833d244", "execution": {"method": "adapter", "implementation": "fixture-checker-v1", "provider": null, "model": null, "configuration": "f57d13ae3235b3dd17bba7ade882ce383cb49c88d1ecfde98229157dc8724e26", "environment": "a5557aa1d167c6950ea5f6bd64a15bf0cb53a1c4771f518d41ad42ca7ddb3f1f", "provenance": "f68d6c397383b27fa84719880e812bb7d95c55d9b32811016524bcf62e7c6b72", "complete": true, "missing": []}}, "execution_complete": true, "missing": []}')

CAND_A, CAND_B = 'a1' * 20, 'b2' * 20


def execution(**changes):
    value = {'method': 'command', 'implementation': 'command-verifier-v1', 'configuration': {'cmd': ['pytest', '-q']},
             'environment': {'python': '3.13'}, 'provenance': {'source': 'runtime'}}
    value.update(changes)
    return value


def raw_inputs(candidate=CAND_A, **changes):
    value = dict(artifact=candidate, revision=2, acceptance={'O1': 'works'}, inputs={'src': 'tree-1'},
                 configuration={'verifier': 'command'}, environment={'python': '3.13', 'TOKEN': 'sekret-value-123'}, checks=['M1', 'M2'])
    value.update(changes)
    return value


def milestone(candidate=CAND_A, inputs=None, **changes):
    args = {'kind': 'milestone', 'root': {'project_id': 'p', 'task_id': 'r'}, 'contract_revision': 2, 'contract_sha': 'c' * 64,
            'subject': {'plan': 'P1', 'milestone': 'M', 'candidate': candidate, 'plan_sha': 'd' * 64}, 'required': True,
            'criteria': [{'id': 'M1', 'spec': 'one'}, {'id': 'M2', 'spec': 'two'}],
            'scope': {'read': ['a', 'b'], 'write': ['c'], 'acceptance': ['O1']}, 'policy': {'depth': 'deep'},
            'authority': {'edit': False}, 'budget': {'max_calls': 5},
            'inputs': inputs if inputs is not None else raw_inputs(candidate), 'execution': execution()}
    args.update(changes)
    return args


def binding(candidate=CAND_A, **changes):
    return ev.bind(**raw_inputs(candidate, **changes))


class BuildCheck(unittest.TestCase):
    def test_node_without_inputs_is_exactly_the_v1_build_and_stored_v1_stays_valid(self):
        args = node_arguments()
        v1 = rr.build(**args)
        self.assertEqual(v1, V1_STORED, 'the v1 id must not move when 2.5-A adds new kinds')
        again = rr.build_check(kind='node', root=args['root'], contract_revision=1, contract_sha=args['contract_sha'],
                               subject=args['facts'], required=False, criteria=args['criteria'], scope=args['scope'],
                               policy=args['policy'], authority=args['authority'], budget=args['budget'], inputs=None,
                               execution=args['execution'], review_id=args['review_id'])
        self.assertEqual(again, V1_STORED)
        self.assertEqual(rr.kind_of(V1_STORED), 'node')
        self.assertEqual(rr.applicability(V1_STORED, copy.deepcopy(V1_STORED)), {'applicable': True, 'reusable': True, 'reasons': []})
        self.assertEqual(rr.evidence_status(V1_STORED, copy.deepcopy(V1_STORED))['status'], 'applies')

    def test_milestone_identity_is_stable_detached_and_secret_free(self):
        first = rr.build_check(**milestone())
        args = milestone(); args['scope']['read'].reverse()
        self.assertEqual(first, rr.build_check(**args))
        self.assertEqual(first['version'], 2); self.assertEqual(first['identity']['kind'], 'milestone')
        self.assertEqual(set(first), {'version', 'id', 'identity', 'execution_complete', 'missing'})
        self.assertEqual(rr.kind_of(first), 'milestone')
        self.assertTrue(first['execution_complete'])
        self.assertEqual(first, json.loads(json.dumps(first)))
        self.assertNotIn('sekret-value-123', json.dumps(first))
        self.assertEqual(first['identity']['evidence']['candidate'], CAND_A)

    def test_secret_in_execution_metadata_is_fingerprinted_not_stored(self):
        args = milestone(execution=execution(environment={'API_KEY': 'topsecret-xyz'}, configuration={'token': 'abc-secret'}))
        self.assertNotIn('topsecret-xyz', json.dumps(rr.build_check(**args)))
        self.assertNotIn('abc-secret', json.dumps(rr.build_check(**args)))

    def test_every_dimension_moves_the_id_and_is_named(self):
        base = rr.build_check(**milestone())
        cases = {
            'criteria': lambda a: a.update(criteria=[{'id': 'M1', 'spec': 'CHANGED'}, {'id': 'M2', 'spec': 'two'}]),
            'candidate': lambda a: a.update(subject=dict(a['subject'], candidate=CAND_B), inputs=raw_inputs(CAND_B)),
            'evidence.inputs': lambda a: a['inputs'].update(inputs={'src': 'tree-2'}),
            'evidence.environment': lambda a: a['inputs']['environment'].update(python='3.14'),
            'evidence.configuration': lambda a: a['inputs'].update(configuration={'verifier': 'reviewer'}),
            'evidence.acceptance': lambda a: a['inputs'].update(acceptance={'O1': 'other'}),
            'policy': lambda a: a['policy'].update(depth='light'), 'scope': lambda a: a['scope']['write'].append('d'),
            'authority': lambda a: a['authority'].update(edit=True), 'budget': lambda a: a['budget'].update(max_calls=9),
            'execution': lambda a: a['execution'].update(implementation='command-verifier-v2'),
            'facts': lambda a: a['subject'].update(milestone='M-other'),
            'review_id': lambda a: a.update(review_id='other'),
        }
        for name, change in cases.items():
            args = milestone(); change(args)
            with self.subTest(name):
                other = rr.build_check(**args)
                self.assertNotEqual(base['id'], other['id'])
                status = rr.evidence_status(base, other)
                self.assertFalse(status['reusable'], status)
                self.assertIn(status['status'], ('recheck', 'insufficient'))

    def test_milestone_refusals(self):
        for name, change in {
            'candidate differs from the evidence binding': lambda a: a.update(inputs=raw_inputs(CAND_B)),
            'binding for another contract revision': lambda a: a['inputs'].update(revision=3),
            'binding names other checks': lambda a: a['inputs'].update(checks=['M1']),
            'zero candidate': lambda a: a['subject'].update(candidate='0' * 40),
            'unknown subject key': lambda a: a['subject'].update(extra='x'),
            'no evidence inputs': lambda a: a.update(inputs=None),
            'live budget key': lambda a: a['budget'].update(remaining_calls=3),
            'duplicate criterion ids': lambda a: a.update(criteria=[{'id': 'M1'}, {'id': 'M1'}]),
            'bad plan_sha': lambda a: a['subject'].update(plan_sha='nothex'),
            'unknown kind': lambda a: a.update(kind='other'),
        }.items():
            args = milestone(); change(args)
            with self.subTest(name), self.assertRaises(LedgerError):
                rr.build_check(**args)

    def test_node_with_inputs_is_v2_and_candidate_must_match_facts(self):
        a = node_arguments()
        node_inputs = raw_inputs('b' * 64, revision=1, checks=['M1'])
        v2 = rr.build_check(kind='node', root=a['root'], contract_revision=1, contract_sha=a['contract_sha'], subject=a['facts'],
                            required=False, criteria=a['criteria'], scope=a['scope'], policy=a['policy'], authority=a['authority'],
                            budget=a['budget'], inputs=node_inputs, execution=a['execution'], review_id=a['review_id'])
        self.assertEqual(v2['version'], 2); self.assertNotEqual(v2['id'], V1_STORED['id'])
        self.assertEqual(rr.kind_of(v2), 'node')
        with self.assertRaises(LedgerError):
            rr.build_check(kind='node', root=a['root'], contract_revision=1, contract_sha=a['contract_sha'], subject=a['facts'],
                           required=False, criteria=a['criteria'], scope=a['scope'], policy=a['policy'], authority=a['authority'],
                           budget=a['budget'], inputs=raw_inputs('c' * 64, revision=1, checks=['M1']), execution=a['execution'])

    def test_tampered_v2_descriptors_are_invalid(self):
        good = rr.build_check(**milestone())
        for name, change in {
            'kind swapped': lambda d: d['identity'].update(kind='node'),
            'extra identity key': lambda d: d['identity'].update(extra=1),
        }.items():
            bad = copy.deepcopy(good); change(bad)
            bad['id'] = 'review-' + content_hash({'version': 2, 'identity': bad['identity']})   # forged with a recomputed id
            with self.subTest(name):
                self.assertFalse(rr.applicability(bad, bad)['applicable'])
                self.assertEqual(rr.evidence_status(good, bad)['status'], 'insufficient')


    def test_forged_but_self_consistent_descriptors_are_just_another_request(self):
        good = rr.build_check(**milestone())
        for name, change in {'candidate': lambda d: d['identity']['evidence'].update(candidate=CAND_B),
                             'criteria ids': lambda d: d['identity']['target'].update(criteria_ids=['M1'])}.items():
            forged = copy.deepcopy(good); change(forged)
            forged['id'] = 'review-' + content_hash({'version': 2, 'identity': forged['identity']})
            with self.subTest(name):   # authenticity comes from where a descriptor is stored; a different one is never 'applies'
                status = rr.evidence_status(good, forged)
                self.assertNotEqual(status['status'], 'applies'); self.assertFalse(status['reusable'])


class EvidenceStatus(unittest.TestCase):
    def test_equal_complete_identity_applies(self):
        a, b = rr.build_check(**milestone()), rr.build_check(**milestone())
        status = rr.evidence_status(a, b)
        self.assertEqual((status['status'], status['reusable'], status['reasons'], status['changed']), ('applies', True, [], []))

    def test_changed_criteria_environment_config_execution_force_recheck(self):
        base = rr.build_check(**milestone())
        for dim, change in {
            'criteria': lambda a: a.update(criteria=[{'id': 'M1', 'spec': 'x'}, {'id': 'M2', 'spec': 'two'}]),
            'evidence.environment': lambda a: a['inputs']['environment'].update(python='3.99'),
            'evidence.configuration': lambda a: a['inputs'].update(configuration={'verifier': 'new'}),
            'execution': lambda a: a['execution']['environment'].update(python='3.99'),
        }.items():
            args = milestone(); change(args)
            status = rr.evidence_status(base, rr.build_check(**args))
            with self.subTest(dim):
                self.assertEqual(status['status'], 'recheck'); self.assertFalse(status['reusable']); self.assertIn(dim, status['changed'])

    def test_missing_execution_metadata_and_unknown_sentinels_are_insufficient_never_applies(self):
        for exec_value in (None, {}, execution(implementation='unknown'), execution(implementation=' Unverified '),
                           execution(environment={}), {'method': 'reviewer', 'implementation': 'r', 'environment': {'a': 'b'}, 'provenance': {'a': 'b'}}):
            complete = rr.build_check(**milestone())
            partial = rr.build_check(**milestone(execution=exec_value))
            self.assertFalse(partial['execution_complete'])
            with self.subTest(exec_value=exec_value):
                same = rr.evidence_status(partial, partial)
                self.assertEqual(same['status'], 'insufficient'); self.assertFalse(same['reusable'])
                self.assertEqual(rr.evidence_status(complete, partial)['status'], 'recheck')   # execution changed AND incomplete: recheck names both
                self.assertTrue(any('incomplete' in r for r in rr.evidence_status(complete, partial)['reasons']))

    def test_legacy_malformed_and_cross_version_are_insufficient(self):
        v2 = rr.build_check(**milestone())
        for prev, cur in ((V1_STORED, v2), (v2, V1_STORED), (None, v2), (v2, {}), ({'version': 1}, V1_STORED)):
            status = rr.evidence_status(prev, cur)
            self.assertEqual(status['status'], 'insufficient'); self.assertFalse(status['reusable'])

    def test_candidate_change_without_basis_is_insufficient_and_never_reuses(self):
        old = rr.build_check(**milestone(CAND_A)); new = rr.build_check(**milestone(CAND_B))
        self.assertEqual(rr.evidence_status(old, new)['status'], 'insufficient')           # no bindings
        status = rr.evidence_status(old, new, binding_previous=binding(CAND_A), binding_current=binding(CAND_B))
        self.assertEqual(status['status'], 'insufficient'); self.assertIn('impact unknown', ' '.join(status['reasons']))
        status = rr.evidence_status(old, new, binding_previous=binding(CAND_A), binding_current=binding(CAND_B),
                                    changed_paths=['docs/readme.md'], basis={'neutral': []})
        self.assertFalse(status['reusable'])
        for basis in ({'assertion': {'kind': 'path', 'path': 'docs/readme.md'}}, {'assertion': {'kind': 'behavioral', 'evidence': []}}):
            status = rr.evidence_status(old, new, binding_previous=binding(CAND_A), binding_current=binding(CAND_B),
                                        changed_paths=['docs/readme.md'], basis=basis)
            self.assertEqual(status['status'], 'insufficient', basis)

    def test_candidate_change_inside_declared_neutral_scope_applies_with_the_basis_but_outside_is_recheck(self):
        old = rr.build_check(**milestone(CAND_A)); new = rr.build_check(**milestone(CAND_B))
        bp, bc = binding(CAND_A), binding(CAND_B)
        ok = rr.evidence_status(old, new, binding_previous=bp, binding_current=bc, changed_paths=['docs/readme.md'],
                                basis={'neutral': ['docs/**']})
        self.assertEqual(ok['status'], 'applies'); self.assertTrue(ok['reusable'])
        self.assertEqual(ok['reuse_basis']['kind'], 'scope.neutral'); self.assertTrue(ok['requires_record'])
        self.assertEqual(ok['changed'], ['evidence.candidate'])
        out = rr.evidence_status(old, new, binding_previous=bp, binding_current=bc, changed_paths=['src/app.py'],
                                 basis={'neutral': ['docs/**']})
        self.assertEqual(out['status'], 'recheck'); self.assertFalse(out['reusable'])
        # a non-command verifier is never neutral
        rev = rr.evidence_status(old, new, binding_previous=bp, binding_current=bc, changed_paths=['docs/readme.md'],
                                 basis={'neutral': ['docs/**'], 'kind': 'reviewer'})
        self.assertEqual(rev['status'], 'recheck')

    def test_bindings_that_do_not_belong_to_the_requests_are_refused(self):
        old = rr.build_check(**milestone(CAND_A)); new = rr.build_check(**milestone(CAND_B))
        for bp, bc in ((binding(CAND_A, inputs={'src': 'tampered'}), binding(CAND_B)), (binding(CAND_B), binding(CAND_A))):
            status = rr.evidence_status(old, new, binding_previous=bp, binding_current=bc, changed_paths=['docs/readme.md'],
                                        basis={'neutral': ['docs/**']})
            self.assertEqual(status['status'], 'insufficient'); self.assertFalse(status['reusable'])

    def test_neutral_candidate_change_with_other_dimension_changed_is_recheck(self):
        old = rr.build_check(**milestone(CAND_A))
        args = milestone(CAND_B); args['policy'] = {'depth': 'light'}
        status = rr.evidence_status(old, rr.build_check(**args), binding_previous=binding(CAND_A), binding_current=binding(CAND_B),
                                    changed_paths=['docs/readme.md'], basis={'neutral': ['docs/**']})
        self.assertEqual(status['status'], 'recheck'); self.assertIn('policy', status['changed'])

    def test_node_v2_workflow_churn_is_not_a_change_but_candidate_and_dependencies_are(self):
        a = node_arguments()
        def make(artifact='b' * 64, **facts):
            f = dict(a['facts'], artifact=artifact, **facts)
            return rr.build_check(kind='node', root=a['root'], contract_revision=1, contract_sha=a['contract_sha'], subject=f,
                                  required=False, criteria=a['criteria'], scope=a['scope'], policy=a['policy'], authority=a['authority'],
                                  budget=a['budget'], inputs=raw_inputs(artifact, revision=1, checks=['M1'], inputs={'src': artifact}),
                                  execution=a['execution'], review_id=a['review_id'])
        base = make()
        for churn in ({'internal_revision': 9}, {'generation': 4}, {'state': 'verified'}, {'phase': 'held'}, {'findings': ['RF1']}):
            self.assertEqual(rr.evidence_status(base, make(**churn))['status'], 'applies', churn)
        for real in ({'inputs': {'D': {'artifact': 'e' * 64, 'generation': 1}}}, {'unknowns': ['U1']}):
            status = rr.evidence_status(base, make(**real))
            self.assertEqual(status['status'], 'recheck', real); self.assertIn('facts', status['changed'])
        moved = make('c' * 64)                                  # new candidate (and the input tree that contains it)
        self.assertEqual(rr.evidence_status(base, moved)['status'], 'recheck')


if __name__ == '__main__':
    unittest.main()
