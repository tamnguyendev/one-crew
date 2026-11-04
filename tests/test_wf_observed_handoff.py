"""Existing verified output can be handed over without inventing a project write."""
import json
import os

from onecrew.common_executor import NativeExecutor
from onecrew.common_handoff import handoff
from onecrew.common_verification import CandidateChecker
from onecrew.ledger import LedgerError, canonical
from onecrew.snapshots import Snapshots
from onecrew.v2 import engine, internal_plan, plan, verdict, tracking
from unittest.mock import patch
from tests.test_v2_l1 import Fixture, plan_json
from tests.test_wf_engine import node


class ObservedHandoffTests(Fixture):
    def setUp(self):
        super().setUp()
        value = plan_json(authority={'commands': True, 'unconfined_commands': True,
            'apply_to_project': False, 'edit': True, 'self_decide': ['Q1','Q2','Q4','Q9']})
        plan.propose(self.ledger, 'P1', value, 'codex', workflow=True,
            capabilities=['namespaced-storage','root-budget','internal-plan','sequential-engine'])
        plan.approve(self.ledger, 'P1', 'owner', 'fixture verifies existing output only')
        os.environ['ONECREW_ACTOR'] = 'codex'
        nodes = [node('C'), node('I', ['C'], integration=True, write=())]
        for item in nodes:
            item['executor'] = {'role': 'worker', 'provider': 'codex', 'model': 'fixture-model'}
            item['checks'] = [{'id': 'M1', 'spec': 'Run the original approved check'}]
        internal_plan.revise(self.ledger, 'P1', nodes, reason='Verify existing output without changes', evidence=['a.txt:1'])
        self.calls = 0
        def factory(control, provider):
            case = self
            class Worker:
                def capability(self): return {'provider': provider, 'mode': 'fixture-no-tools'}
                def run(self, attempt, prompt, schema, profile):
                    case.calls += 1
                    control.launched(attempt['id'], attempt['generation'], {'fixture': True})
                    control.finish(attempt['id'], attempt['generation'], {'exit_code': 0})
                def result(self, attempt):
                    return ({'summary': 'Already correct', 'files': [{'path': 'a.txt', 'content': 'one\n'}], 'backlog': []}
                            if case.calls == 1 else {'summary': 'Existing source checked', 'evidence': []}), []
            return Worker()
        self.executor = NativeExecutor(self.ledger, worker_factory=factory)
        engine.step(self.ledger, 'P1', self.executor)
        engine.verify(self.ledger, 'P1', 'C', CandidateChecker(self.ledger, 'P1'))
        engine.step(self.ledger, 'P1', self.executor)
        engine.verify(self.ledger, 'P1', 'I', CandidateChecker(self.ledger, 'P1'))

    def test_real_observation_needs_no_apply_grant_and_is_idempotent(self):
        before = (self.root / 'a.txt').read_bytes(); index = self.git('write-tree')
        result = handoff(self.ledger, 'P1')
        self.assertTrue(engine.root_ready(self.ledger, 'P1', result['artifact']))
        again = handoff(self.ledger, 'P1')
        self.assertTrue(again['idempotent']); self.assertEqual(self.calls, 2)
        self.assertEqual(((self.root / 'a.txt').read_bytes(), self.git('write-tree')), (before, index))
        proof = json.loads(Snapshots(self.ledger.state_root).read_blob(result['receipt']))
        self.assertEqual(proof['method'], 'observed-existing-tree'); self.assertNotIn('apply_receipt', proof)
        with self.ledger.transaction() as conn:
            actions = [json.loads(r['payload'])['kind'] for r in conn.execute('SELECT payload FROM actions')]
        self.assertEqual(actions, ['observe_verified_tree'])
        verdict.run(self.ledger, 'P1', 'M1')
        with patch('onecrew.v2.verifiers.command.artifact_sha', side_effect=AssertionError('viewer must not hash project')):
            shown = tracking.detail(self.ledger.state_root, 'P1')
        self.assertTrue(shown['acceptance']['ready'], shown['acceptance'])
        self.assertEqual(shown['acceptance']['artifact'], result['artifact'])
        self.assertEqual([n['kind'] for n in shown['needs_user']], ['accept'])
        os.environ.pop('ONECREW_ACTOR')
        self.assertEqual(plan.accept(self.ledger, 'P1', 'owner', 'fixture existing output accepted', result['artifact'])['status'], 'accepted')

    def test_forged_observation_without_durable_action_is_not_delivery(self):
        result = handoff(self.ledger, 'P1')
        with self.ledger.transaction(write=True) as conn:
            conn.execute('DELETE FROM actions')  # adversarial fixture: the alleged proof has no authentic action
        self.assertFalse(engine.root_ready(self.ledger, 'P1', result['artifact']))
        verdict.run(self.ledger, 'P1', 'M1')
        shown = tracking.detail(self.ledger.state_root, 'P1')
        self.assertFalse(shown['acceptance']['ready'])
        self.assertNotIn('accept', [n['kind'] for n in shown['needs_user']])

    def test_user_change_before_observation_is_never_reported_delivered(self):
        (self.root / 'a.txt').write_text('user edit\n')
        with self.assertRaises(LedgerError): handoff(self.ledger, 'P1')
        self.assertEqual((self.root / 'a.txt').read_text(), 'user edit\n')
        self.assertFalse(engine.root_ready(self.ledger, 'P1'))
