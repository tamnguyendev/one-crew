"""T06/T22: immutable input/config/environment bindings and recorded reuse."""
import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from onecrew.ledger import Ledger, LedgerError
from onecrew.snapshots import Snapshots
from onecrew.v2 import plan, verdict, namespaces
from onecrew.v2 import verification_evidence as evidence
from onecrew.v2.verifiers import command, reviewer
from tests.test_v2_l1 import Fixture, plan_json


class BindingPolicyTests(unittest.TestCase):
    def baseline(self, **changes):
        data = dict(artifact='a' * 40, revision=1, acceptance={'O1': 'Required output'},
                    inputs={'I1': 'interface-A', 'I2': 'source-A'}, configuration={'checker': 'v1'},
                    environment={'V': 'runtime-A'}, checks=['C1', 'C2'])
        data.update(changes)
        return evidence.bind(**data)

    def test_each_changed_dimension_is_named_and_original_checks_are_retained(self):
        old = self.baseline()
        for changes, reason in (({'inputs': {'I1': 'interface-B', 'I2': 'source-A'}}, 'input changed: I1'),
                                ({'configuration': {'checker': 'v2'}}, 'checker configuration changed'),
                                ({'environment': {'V': 'runtime-B'}}, 'checker environment changed: V'),
                                ({'acceptance': {'O1': 'Different output'}}, 'acceptance changed')):
            out = evidence.assess(old, self.baseline(**changes))
            self.assertFalse(out['reusable'])
            self.assertIn(reason, out['reasons'])
            self.assertTrue(set(old['checks']) <= set(out['checks_to_rerun']))

    def test_artifact_change_outside_inputs_is_not_implicitly_neutral(self):
        old, current = self.baseline(), self.baseline(artifact='b' * 40)
        for basis, text in ((None, 'without a recorded valid reuse basis'),
                            ({'kind': 'path', 'path': 'docs/readme.md'}, 'path-only'),
                            ({'kind': 'behavioral', 'evidence': []}, 'lacks evidence')):
            result = evidence.assess(old, current, changed_paths=['docs/readme.md'], basis=basis)
            self.assertFalse(result['reusable'])
            self.assertIn(text, '; '.join(result['reasons']))
            self.assertEqual(result['checks_to_rerun'], ['C1', 'C2'])

    def test_neutral_reuse_requires_declared_matching_paths_and_record(self):
        old, current = self.baseline(), self.baseline(artifact='b' * 40, revision=2)
        result = evidence.assess(old, current, neutral=['docs/**'], changed_paths=['docs/readme.md'])
        self.assertTrue(result['reusable'])
        self.assertTrue(result['requires_record'])
        self.assertEqual(result['reuse_basis'], {'kind': 'scope.neutral', 'contract_revision': 2,
            'from_artifact': 'a' * 40, 'to_artifact': 'b' * 40, 'changed_paths': ['docs/readme.md'],
            'matching_globs': {'docs/readme.md': ['docs/**']}})
        for extra in ({'changed_paths': ['src/main.py']}, {'submodule_changed': True}, {'kind': 'reviewer'}):
            args = dict(neutral=['docs/**'], changed_paths=['docs/readme.md']); args.update(extra)
            self.assertFalse(evidence.assess(old, current, **args)['reusable'])

    def test_malformed_binding_and_null_artifact_are_never_reused(self):
        old = self.baseline()
        for changes in ({'version': True}, {'artifact': '0' * 40}, {'inputs': {}}, {'configuration': None}, {'checks': []}):
            broken = dict(old, **changes)
            self.assertFalse(evidence.assess(broken, old)['reusable'])
        with self.assertRaises(LedgerError): self.baseline(artifact='0' * 40)


class BoundReceiptTests(Fixture):
    def start(self):
        (self.root / 'interface.txt').write_text('interface A')
        self.git('add', '.'); self.git('commit', '-qm', 'interface')
        value = plan_json(scope={'owned': ['a.txt'], 'neutral': ['docs/**']})
        value['understanding']['target']['paths'] = ['a.txt', 'interface.txt']
        plan.propose(self.ledger, 'P1', value, 'fixture', workflow=True, capabilities=list(namespaces.CAPABILITIES))
        plan.approve(self.ledger, 'P1', 'owner', 'temporary fixture')
        out = verdict.run(self.ledger, 'P1', 'M1')
        self.receipt_ref = out['milestones'][0]['last_verdict']['receipt']
        self.body = json.loads(Snapshots(self.ledger.state_root).read_blob(self.receipt_ref))
        self.assertIn('evidence_binding', self.body)
        with self.ledger.transaction() as conn:
            self.state = plan.derive(self.ledger, conn, 'P1')
        self.contract = plan.load(self.ledger, self.state, 1)[0]
        self.milestone = self.contract['milestones'][0]

    def assess(self, contract=None, milestone=None):
        return evidence.receipt_assessment(self.ledger, contract or self.contract, milestone or self.milestone,
            1, self.receipt_ref, self.tree(), task_id=self.state['task_id'])

    def test_actual_run_binds_inputs_configuration_environment_and_readonly_stale_reasons(self):
        self.start()
        binding = self.body['evidence_binding']
        self.assertEqual(set(binding['inputs']), {'a.txt', 'interface.txt'})
        self.assertEqual(binding['artifact'], self.tree())
        self.assertTrue(binding['environment_observed']['python'])
        before = self.events()
        changed = copy.deepcopy(self.milestone)
        changed['verifier']['config']['argv'][-1] = 'print("different checker")'
        self.assertIn('checker configuration changed', self.assess(milestone=changed)['reasons'])
        with patch.dict(os.environ, LANG='fixture-changed-environment'):
            result = self.assess()
            self.assertIn('checker environment changed: variables', result['reasons'])
            self.assertTrue(plan.show(self.ledger, 'P1')['milestones'][0]['stale'])
        (self.root / 'interface.txt').write_text('interface B')
        result = self.assess()
        self.assertIn('input changed: interface.txt', result['reasons'])
        self.assertTrue(plan.show(self.ledger, 'P1')['milestones'][0]['stale'])
        self.assertEqual(self.events(), before)

    def test_neutral_basis_is_persisted_idempotently_and_never_changes_original_receipt(self):
        self.start()
        original = Snapshots(self.ledger.state_root).read_blob(self.receipt_ref)
        (self.root / 'docs').mkdir(); (self.root / 'docs' / 'note.md').write_text('Neutral note')
        self.git('add', '.'); self.git('commit', '-qm', 'neutral')
        decision = self.assess()
        self.assertTrue(decision['reusable']); self.assertFalse(decision['recorded'])
        first = evidence.record_reuse(self.ledger, 'P1', 'M1', self.receipt_ref, self.tree())
        second = evidence.record_reuse(self.ledger, 'P1', 'M1', self.receipt_ref, self.tree())
        self.assertEqual(first, second)
        self.assertEqual(self.kinds().count('evidence.reuse'), 1)
        self.assertEqual(first['basis']['matching_globs'], {'docs/note.md': ['docs/**']})
        self.assertTrue(self.assess()['recorded'])
        self.assertEqual(plan.show(self.ledger, 'P1')['milestones'][0]['state'], 'passed')
        self.assertEqual(Snapshots(self.ledger.state_root).read_blob(self.receipt_ref), original)
        self.assertEqual(self.body['artifact_sha'], self.body['evidence_binding']['artifact'])

    def test_outside_input_unrelated_path_and_forged_receipt_cannot_reuse(self):
        self.start()
        (self.root / 'unrelated.txt').write_text('not an input')
        out = self.assess()
        self.assertFalse(out['reusable'])
        self.assertIn('artifact changed outside declared scope.neutral', '; '.join(out['reasons']))
        self.assertTrue(set(self.body['evidence_binding']['checks']) <= set(out['checks_to_rerun']))
        with self.assertRaises(LedgerError): evidence.record_reuse(self.ledger, 'P1', 'M1', self.receipt_ref, self.tree())
        forged = Snapshots(self.ledger.state_root).blob(b'{"evidence_binding":{}}')
        with self.assertRaisesRegex(LedgerError, 'authentic passing receipt'):
            evidence.record_reuse(self.ledger, 'P1', 'M1', forged, self.tree())
        self.assertNotIn('evidence.reuse', self.kinds())

    def test_malformed_and_missing_receipt_assessment_is_a_precise_stale_result(self):
        self.start()
        for raw in (b'[]', b'not-json', b'{"evidence_binding": true}'):
            receipt = Snapshots(self.ledger.state_root).blob(raw)
            out = evidence.receipt_assessment(self.ledger, self.contract, self.milestone, 1, receipt, self.tree())
            self.assertFalse(out['reusable'])
            self.assertTrue(out['reasons'])
        out = evidence.receipt_assessment(self.ledger, self.contract, self.milestone, 1, 'f' * 64, self.tree())
        self.assertIn('receipt missing or malformed', out['reasons'][0])

    def test_opt_in_root_cannot_publish_new_unbound_or_mismatched_binding_pass(self):
        self.start()
        (self.root / 'a.txt').write_text('new output')
        ref, body = command.run(self.ledger, 'P1', 1, self.state['revisions'][1]['sha'], self.milestone, self.root)
        for bad in (body, dict(body, evidence_binding=dict(self.body['evidence_binding'], artifact='b' * 40))):
            ref = Snapshots(self.ledger.state_root).blob(json.dumps(bad).encode())
            self.issue(ref)
            with self.assertRaisesRegex(LedgerError, 'Required evidence binding'):
                verdict.record(self.ledger, 'P1', 'M1', 'pass', 'command', ref, body['artifact_sha'])
        self.assertEqual(self.kinds().count('verdict.recorded'), 1)

    def test_reuse_record_is_visible_in_same_transaction_and_rolls_back_atomically(self):
        self.start()
        (self.root / 'docs').mkdir(); (self.root / 'docs' / 'note.md').write_text('Neutral note')
        current = self.tree()
        with self.assertRaisesRegex(RuntimeError, 'fixture rollback'):
            with self.ledger.transaction(write=True) as conn:
                evidence.record_reuse(self.ledger, 'P1', 'M1', self.receipt_ref, current, conn=conn)
                out = evidence.receipt_assessment(self.ledger, self.contract, self.milestone, 1, self.receipt_ref,
                    current, task_id=self.state['task_id'], conn=conn, require_bound=True)
                self.assertTrue(out['recorded'])
                raise RuntimeError('fixture rollback')
        self.assertNotIn('evidence.reuse', self.kinds())
        self.assertFalse(self.assess()['recorded'])

    def test_reviewer_receipt_binds_effective_environment_with_fake_provider_only(self):
        value = plan_json()
        value['milestones'][0]['verifier'] = {'type': 'reviewer', 'config': {'provider': 'claude',
            'model': 'claude-haiku-5-5', 'criteria': [{'id': 'R1', 'question': 'Does a.txt add the required line?'}]}}
        plan.propose(self.ledger, 'P1', value, 'codex', workflow=True, capabilities=list(namespaces.CAPABILITIES))
        plan.approve(self.ledger, 'P1', 'owner', 'temporary fixture')
        (self.root / 'a.txt').write_text('one\ntwo\n')
        answer = json.dumps({'criteria': [{'id': 'R1', 'verdict': 'pass', 'evidence': [
            {'file': 'a.txt', 'line': 2, 'note': 'Fixture evidence for interface only'}]}], 'outside_criteria': []})
        with patch.object(reviewer, 'call', return_value=(answer, {}, None, False, b'fake-provider')) as call:
            result = verdict.run(self.ledger, 'P1', 'M1')
        self.assertEqual(call.call_count, 1)
        self.assertEqual(result['milestones'][0]['state'], 'passed')
        ref = result['milestones'][0]['last_verdict']['receipt']
        body = json.loads(Snapshots(self.ledger.state_root).read_blob(ref))
        self.assertEqual(body['evidence_binding']['checks'], ['R1'])
        self.assertTrue(body['evidence_binding']['environment_observed']['variables'])


class NonGitBoundReceiptTests(unittest.TestCase):
    def test_real_doc_snapshot_binding_and_new_unretained_input_are_readonly(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ):
            for key in ('ONECREW_ACTOR', 'CLAUDECODE', 'CLAUDE_CODE_CHILD_SESSION'): os.environ.pop(key, None)
            root = Path(temp) / 'source'; root.mkdir(); (root / 'guide.md').write_text('# Guide\n')
            ledger = Ledger(root, Path(temp) / 'state')
            value = plan_json()
            value['understanding']['target'] = {'repo': '.', 'ref': 'snapshot', 'paths': ['guide.md']}
            value['scope']['owned'] = ['guide.md']
            value['preconditions'][0]['args']['path'] = 'guide.md'
            value['milestones'][0]['verifier'] = {'type': 'doc', 'config': {'docs': ['guide.md']}}
            plan.propose(ledger, 'DOC', value, 'fixture', workflow=True, capabilities=list(namespaces.CAPABILITIES))
            plan.approve(ledger, 'DOC', 'owner', 'temporary fixture')
            verified = verdict.run(ledger, 'DOC', 'M1')
            self.assertEqual(verified['milestones'][0]['state'], 'passed')
            receipt = verified['milestones'][0]['last_verdict']['receipt']
            body = json.loads(Snapshots(ledger.state_root).read_blob(receipt))
            self.assertEqual(set(body['evidence_binding']['inputs']), {'guide.md'})
            before = set(p.relative_to(ledger.state_root).as_posix() for p in ledger.state_root.rglob('*') if p.is_file())
            (root / 'guide.md').write_text('# Changed interface\n')
            view = plan.show(ledger, 'DOC')['milestones'][0]
            self.assertTrue(view['stale'])
            self.assertIn('input changed: guide.md', view['stale_reasons'])
            after = set(p.relative_to(ledger.state_root).as_posix() for p in ledger.state_root.rglob('*') if p.is_file())
            self.assertEqual(before, after)
            # A damaged retained proof is not silently replaced by a live read.
            (root / 'guide.md').write_text('# Guide\n')
            store = Snapshots(ledger.state_root)
            manifest = store.load(body['artifact_sha'])
            (store.root / 'blobs' / manifest['files']['guide.md']['working']).write_bytes(b'corrupted')
            view = plan.show(ledger, 'DOC')['milestones'][0]
            self.assertTrue(view['stale'])
            self.assertIn('hash', '; '.join(view['stale_reasons']).lower())
