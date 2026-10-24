"""T04c: acceptance test preparation uses the actual one-slot engine."""
from unittest.mock import patch
import os

from onecrew import dependency_core
from onecrew.ledger import LedgerError
from onecrew.v2 import test_preparation
from onecrew.v2 import plan as plans
from tests.test_v2_l1 import plan_json
from tests.test_wf_engine import EngineFixture, node


class TestPreparationTests(EngineFixture):
    def add_preparation(self):
        return test_preparation.prepare(self.ledger, 'P1', 'C', 'P', write=['b.txt'],
            checks=[{'id': 'check-P', 'spec': 'Prepared acceptance cases exist; future implementation may still be red.'}],
            estimate_seconds=[1, 2], execution_cap_seconds=60, budget_calls=1,
            reason='Prepare acceptance cases before implementation', evidence=['a.txt:1'])

    def test_preparation_finishes_before_any_implementation_artifact(self):
        code = node('C'); code['executor'] = {'role': 'worker', 'provider': 'codex', 'model': 'fixture-model'}
        self.revise([code, node('I', ['C'], integration=True, write=())])
        self.add_preparation()
        definition = self.ip.current(self.ledger, 'P1')['definition']['nodes']
        preparation = next(n for n in definition if n['id'] == 'P')
        self.assertEqual(preparation['depends'], [])
        self.assertEqual(preparation['input'], ['acceptance:O1'])
        self.assertEqual(preparation['executor'], code['executor'], 'the generated node preserves the actual worker pin')
        self.assertIn({'node': 'P', 'requires': 'verified'}, next(n for n in definition if n['id'] == 'C')['depends'])
        with patch.object(dependency_core, 'ready_batch', wraps=dependency_core.ready_batch) as ready:
            self.assertEqual([n['id'] for n in self.engine.ready(self.ledger, 'P1')], ['P'])
            self.assertEqual(self.step()['node'], 'P')
            self.assertEqual(self.engine.ready(self.ledger, 'P1'), [], 'code still needs preparation verification')
            self.verify('P')
            self.assertEqual(self.step()['node'], 'C')
            self.assertGreaterEqual(ready.call_count, 4)
        events = self.events()
        prep_verified = next(i for i, (kind, payload) in enumerate(events) if kind == 'node.verification' and payload['node'] == 'P')
        code_produced = next(i for i, (kind, payload) in enumerate(events) if kind == 'node.produced' and payload['node'] == 'C')
        self.assertLess(prep_verified, code_produced)
        self.assertFalse(any(kind == 'node.held' and payload['node'] == 'P' for kind, payload in events))
        intent = [p for kind, p in events if kind == 'decision.recorded' and p.get('scope') == 'acceptance-test-preparation']
        self.assertEqual(intent[-1]['validity']['node'], 'P')
        self.assertEqual(intent[-1]['validity']['checks'], ['check-P'])

    def test_preparation_cannot_expand_test_write_grant_or_target_integration(self):
        self.revise([node('C'), node('I', ['C'], integration=True, write=())])
        with self.assertRaises(LedgerError):
            test_preparation.prepare(self.ledger, 'P1', 'I', 'P', write=['b.txt'], checks=[{'id': 'p', 'spec': 'prepare'}],
                estimate_seconds=[1, 2], execution_cap_seconds=60, budget_calls=1, reason='prepare', evidence=['a.txt:1'])
        with self.assertRaises(LedgerError):
            test_preparation.prepare(self.ledger, 'P1', 'C', 'P', write=['outside.txt'], checks=[{'id': 'p', 'spec': 'prepare'}],
                estimate_seconds=[1, 2], execution_cap_seconds=60, budget_calls=1, reason='prepare', evidence=['a.txt:1'])
        self.assertEqual(self.ip.current(self.ledger, 'P1')['internal_revision'], 1)

    def test_preparation_requires_the_existing_test_edit_grant(self):
        value = plan_json(scope={'owned': ['a.txt', 'b.txt']}, authority={'edit': True, 'commands': True,
                          'edit_tests': False, 'self_decide': ['Q1', 'Q4']})
        plans.propose(self.ledger, 'NoTests', value, 'codex', workflow=True, capabilities=self.engine_caps)
        with patch.dict(os.environ, {'ONECREW_ACTOR': 'owner'}):
            plans.approve(self.ledger, 'NoTests', 'owner', 'fixture grants production editing only')
        self.ip.revise(self.ledger, 'NoTests', [node('C'), node('I', ['C'], integration=True, write=())],
                       reason='Existing implementation decomposition', evidence=['a.txt:1'])
        with self.assertRaisesRegex(LedgerError, 'edit_tests'):
            test_preparation.prepare(self.ledger, 'NoTests', 'C', 'P', write=['b.txt'], checks=[{'id': 'p', 'spec': 'prepare'}],
                estimate_seconds=[1, 2], execution_cap_seconds=60, budget_calls=1, reason='prepare', evidence=['a.txt:1'])
        self.assertEqual(self.ip.current(self.ledger, 'NoTests')['internal_revision'], 1)
