"""W04/W06/W14a foundation, specified before implementation.

Real temporary ledger, Git and Control attempts. Executors/checkers are explicit
fixtures: they prove the engine interface and rights, not external provider work.
"""
import copy
import json
import os
from pathlib import Path
from unittest.mock import patch

from onecrew import dependency_core
from onecrew.control import Control, migrate
from onecrew.ledger import LedgerError, content_hash
from onecrew.snapshots import Snapshots
from onecrew.v2 import contract as contracts, estimates, namespaces, plan as plans
from tests.test_v2_l1 import Fixture, plan_json


def node(nid, dependencies=(), requires='verified', integration=False, write=('a.txt',)):
    return {'id': nid, 'goal': 'Produce evidence for O1', 'input': [], 'output': ['Evidence for O1'],
            'acceptance': ['O1'], 'depends': [{'node': upstream, 'requires': requires} for upstream in dependencies],
            'read': ['a.txt'], 'write': list(write), 'resources': [], 'estimate_seconds': [1, 2],
            'execution_cap_seconds': 60, 'budget_calls': 1,
            'checks': [{'id': 'check-' + nid, 'spec': 'Check the declared O1 output of ' + nid}], 'integration': integration}


class EngineFixture(Fixture):
    def setUp(self):
        super().setUp()
        from onecrew.v2 import internal_plan, engine
        self.ip, self.engine = internal_plan, engine
        self.engine_caps = ['namespaced-storage', 'root-budget', 'internal-plan', 'sequential-engine']
        value = plan_json(scope={'owned': ['a.txt', 'b.txt']}, authority={
            'edit': True, 'commands': True, 'edit_tests': True, 'self_decide': ['Q1', 'Q2', 'Q3', 'Q4', 'Q5', 'Q9', 'Q12']})   # round 8 G: Q5 delegated, the fixtures repair
        self.root_view = plans.propose(self.ledger, 'P1', value, 'codex', workflow=True, capabilities=self.engine_caps)
        plans.approve(self.ledger, 'P1', 'owner', 'fixture engine approval')
        os.environ['ONECREW_ACTOR'] = 'codex'
        self.store = Snapshots(self.ledger.state_root)
        migrate(self.ledger)
        self.control = Control(self.ledger)

    def step(self, executor=None):
        return self.engine.step(self.ledger, 'P1', executor or self.execute, control=self.control)

    def revise(self, nodes, reason='Split work inside the approved scope'):
        return self.ip.revise(self.ledger, 'P1', nodes, reason=reason, evidence=['a.txt:1'])

    def execute(self, ledger, control, task, item, attempt):
        control.launched(attempt['id'], attempt['generation'], {'fixture': True})
        artifact = self.store.blob(('artifact-' + item['id']).encode())
        receipt = self.store.blob(('executor-' + item['id']).encode())
        control.finish(attempt['id'], attempt['generation'], {'fixture': True, 'artifact': artifact})
        return {'artifact': artifact, 'receipt': receipt}

    def checker(self, item, artifact):
        return {'artifact': artifact, 'checks': [{'id': check['id'], 'result': 'pass',
                                                'evidence': self.store.blob(b'fixture check passed')}
                                               for check in item['checks']]}

    def verify(self, nid, checker=None):
        return self.engine.verify(self.ledger, 'P1', nid, checker or self.checker)


class EngineTests(EngineFixture):
    def test_unknown_arriving_during_execution_retains_then_releases_without_a_second_call(self):
        from onecrew.v2 import runtime_unknowns
        self.revise([node('C'), node('I', ['C'], integration=True, write=())])
        calls = []
        def late_fact(ledger, control, task, item, attempt):
            calls.append(item['id'])
            candidate = self.execute(ledger, control, task, item, attempt)
            runtime_unknowns.open_unknown(ledger, 'P1', 'late-fact', question='Which input is required?',
                affected=['C','I'], required_by=['C'], resolver='doc', evidence=['a.txt:1'])
            return candidate
        result = self.step(late_fact)
        self.assertEqual(result['state'], 'retained')
        self.assertNotIn('node.produced', self.kinds())
        self.assertEqual(self.engine.ready(self.ledger, 'P1'), [])
        runtime_unknowns.resolve(self.ledger, 'P1', 'late-fact', by='doc', evidence='a.txt:1', answer='Existing text format confirmed')
        released = self.step(late_fact)
        self.assertTrue(released['released_retained'])
        self.assertEqual(released['artifact'], result['artifact'])
        self.assertEqual(calls, ['C'])
        self.verify('C')

    def close_root(self):
        with self.ledger.transaction(write=True) as conn:
            root = plans.anchor_events(self.ledger, conn, 'P1')
            plans.emit(self.ledger, conn, root['task_id'], 'plan.closed',
                       {'revision': root['approved']['revision'], 'reason': 'owner stopped during fixture'})

    def test_stopped_root_retains_late_executor_evidence_without_candidate_publication(self):
        self.revise([node('C'), node('I', ['C'], integration=True, write=())])
        def late(ledger, control, task, item, attempt):
            result = self.execute(ledger, control, task, item, attempt)
            self.close_root()
            return result
        result = self.step(late)
        self.assertEqual(result['state'], 'retained')
        self.assertEqual(plans.show(self.ledger, 'P1')['status'], 'closed')
        self.assertNotIn('node.produced', self.kinds())
        retained = [payload for kind, payload in self.events() if kind == 'node.result_retained']
        self.assertEqual(retained[0]['candidate']['artifact'], result['artifact'])
        self.assertFalse(retained[0]['grants_delivery'])
        self.store.read_blob(retained[0]['candidate']['receipt'])
        self.assertEqual(self.engine.ready(self.ledger, 'P1'), [])
        self.assertFalse(self.engine.verification_ready(self.ledger, 'P1'))

    def test_stopped_root_cannot_publish_late_checker_pass(self):
        self.revise([node('C'), node('I', ['C'], integration=True, write=())])
        self.step()
        def late(item, artifact):
            result = self.checker(item, artifact)
            self.close_root()
            return result
        with self.assertRaisesRegex(LedgerError, 'retained without verification'):
            self.verify('C', late)
        self.assertNotIn('node.verification', self.kinds())
        self.assertIn('node.result_retained', self.kinds())
        self.assertEqual(self.engine.state(self.ledger, 'P1')['nodes']['C']['state'], 'produced')
        self.assertFalse(self.engine.root_ready(self.ledger, 'P1'))

    def test_internal_revision_preserves_contract_acceptance_budget_and_decision_provenance(self):
        before = contracts.revision_path(self.ledger, 'P1', 1).read_bytes()
        initial = [node('C'), node('I', ['C'], integration=True, write=())]
        first = self.revise(initial)
        split = copy.deepcopy(initial[0]); split['id'] = 'C1'
        revised = [split, node('C2', write=('b.txt',)), node('I', ['C1', 'C2'], integration=True, write=())]
        second = self.revise(revised)
        self.assertEqual((first['internal_revision'], second['internal_revision']), (1, 2))
        self.assertEqual(contracts.revision_path(self.ledger, 'P1', 1).read_bytes(), before)
        shown = plans.show(self.ledger, 'P1')
        self.assertEqual((shown['revision'], shown['status']), (1, 'approved'))
        self.assertNotIn('plan.amended', self.kinds())
        self.assertEqual(self.kinds().count('plan.revised'), 2)
        self.assertEqual(self.ledger.requests(self.root_view['anchor_task']), [])
        decisions = [payload for kind, payload in self.events() if kind == 'decision.recorded']
        self.assertTrue(decisions)
        for decision in decisions:
            self.assertNotEqual(decision['actor'], 'owner')
            self.assertTrue(all(decision.get(field) for field in ('subject', 'authority', 'evidence', 'scope', 'validity')))
        self.assertIsNotNone(estimates.read(self.ledger, 'P1')['baseline'])

    def test_acceptance_loss_check_weakening_or_scope_expansion_is_refused_without_revision(self):
        definition = [node('C'), node('I', ['C'], integration=True, write=())]
        self.revise(definition)
        for mutation, expected in ((lambda rows: rows[0].update(write=['outside.txt']), 'U2'),
                                   (lambda rows: rows[0].update(acceptance=['O99']), 'U1'),
                                   (lambda rows: rows[0].update(checks=[]), 'U1')):
            changed = copy.deepcopy(definition); mutation(changed)
            with self.assertRaisesRegex(LedgerError, expected):
                self.revise(changed)
            self.assertEqual(self.ip.current(self.ledger, 'P1')['internal_revision'], 1)
        self.assertEqual(self.ledger.requests(self.root_view['anchor_task']), [])

    def test_three_states_bounded_advance_and_reused_ready_batch_drive_real_one_slot_engine(self):
        early = node('Early', ['C'], requires='produced', write=('b.txt',))
        early['depends'][0]['advance'] = {'limit': 1, 'discard_on_failure': True}
        definition = [node('C'), node('D', ['C']), early,
                      node('AcceptedConsumer', ['C'], requires='accepted', write=('b.txt',)),
                      node('I', ['C', 'D', 'Early', 'AcceptedConsumer'], integration=True, write=())]
        self.revise(definition)
        with patch.object(dependency_core, 'ready_batch', wraps=dependency_core.ready_batch) as reused:
            self.assertEqual(self.step()['node'], 'C')
            state = self.engine.state(self.ledger, 'P1')
            eligible = self.engine.eligible(state, 'D')
            self.assertFalse(eligible['ready']); self.assertIn('verified', eligible['reason'])
            self.assertEqual([item['id'] for item in self.engine.ready(self.ledger, 'P1')], ['Early'])
            self.step()
            self.verify('Early')
            self.assertFalse(self.engine.eligible(self.engine.state(self.ledger, 'P1'), 'Early')['ready'])
            repeated = self.engine.state(self.ledger, 'P1')
            repeated['nodes']['Early'].update(phase='pending', state=None)
            bounded = self.engine.eligible(repeated, 'Early')
            self.assertFalse(bounded['ready']); self.assertIn('advance', bounded['reason'])
            self.verify('C')
            self.assertFalse(self.engine.eligible(self.engine.state(self.ledger, 'P1'), 'AcceptedConsumer')['ready'])
            self.engine.accept_node(self.ledger, 'P1', 'C')
            self.assertTrue(self.engine.eligible(self.engine.state(self.ledger, 'P1'), 'AcceptedConsumer')['ready'])
            self.assertGreaterEqual(reused.call_count, 3)
        self.assertEqual(self.engine.state(self.ledger, 'P1')['nodes']['C']['state'], 'accepted')
        self.assertEqual(plans.show(self.ledger, 'P1')['status'], 'approved')

    def test_mandatory_integration_and_bound_checker_evidence_gate_verified_not_root_acceptance(self):
        self.revise([node('C'), node('I', ['C'], integration=True, write=())])
        self.step()
        self.verify('C')
        self.assertFalse(self.engine.root_ready(self.ledger, 'P1'))
        self.step()
        self.assertFalse(self.engine.root_ready(self.ledger, 'P1'))
        def wrong(item, artifact):
            result = self.checker(item, artifact); result['artifact'] = 'a' * 64
            return result
        self.verify('I', wrong)
        self.assertFalse(self.engine.root_ready(self.ledger, 'P1'))
        self.verify('I')
        self.assertTrue(self.engine.verification_ready(self.ledger, 'P1'))
        self.assertFalse(self.engine.root_ready(self.ledger, 'P1'), 'candidate verification is not an authorized delivered-tree handoff')
        self.assertEqual(plans.show(self.ledger, 'P1')['status'], 'approved')
        self.assertNotIn('plan.accepted', self.kinds())

    def test_single_slot_unknown_attempt_is_retained_and_never_reinvoked(self):
        self.revise([node('A'), node('B', write=('b.txt',)), node('I', ['A', 'B'], integration=True, write=())])
        calls = []
        def unsettled(ledger, control, task, item, attempt):
            calls.append(item['id'])
            return {'artifact': self.store.blob(b'unsettled output'), 'receipt': self.store.blob(b'not settled')}
        self.step(unsettled)
        state = self.engine.state(self.ledger, 'P1')
        self.assertEqual(state['nodes']['A']['phase'], 'held')
        self.assertEqual(self.engine.ready(self.ledger, 'P1'), [])
        self.step(unsettled)
        self.assertEqual(calls, ['A'])
        self.assertFalse(self.engine.root_ready(self.ledger, 'P1'))

    def test_u2_holds_actual_dependency_closure_while_independent_node_runs(self):
        self.revise([node('A'), node('Consumer', ['A']), node('B', write=('b.txt',)),
                     node('I', ['A', 'Consumer', 'B'], integration=True, write=())])
        result = self.engine.request_action(self.ledger, 'P1', 'A', {'kind': 'write', 'paths': ['outside.txt']})
        self.assertEqual(result['class'], 'U2')
        state = self.engine.state(self.ledger, 'P1')
        self.assertEqual({nid for nid, item in state['nodes'].items() if item['phase'] == 'held'}, {'A', 'Consumer', 'I'})
        self.assertEqual(self.step()['node'], 'B')
        self.assertEqual(plans.show(self.ledger, 'P1')['status'], 'approved')

    def test_no_internal_plan_capability_on_default_schema2_and_missing_self_decide_is_refused(self):
        # Immutable root declarations, never the storage anchor alone, opt in.
        raw = plan_json(authority={'edit': True, 'self_decide': []})
        os.environ.pop('ONECREW_ACTOR', None)
        plans.propose(self.ledger, 'plain', raw, 'codex')
        plans.approve(self.ledger, 'plain', 'owner', 'fixture old semantics')
        with self.assertRaisesRegex(LedgerError, 'capability'):
            self.ip.revise(self.ledger, 'plain', [node('C'), node('I', ['C'], integration=True, write=())], reason='split', evidence=['a.txt:1'])
        plans.propose(self.ledger, 'undelegated', raw, 'codex', workflow=True, capabilities=self.engine_caps)
        plans.approve(self.ledger, 'undelegated', 'owner', 'fixture no self-decision')
        with self.assertRaises(LedgerError):
            self.ip.revise(self.ledger, 'undelegated', [node('C'), node('I', ['C'], integration=True, write=())], reason='split', evidence=['a.txt:1'])
