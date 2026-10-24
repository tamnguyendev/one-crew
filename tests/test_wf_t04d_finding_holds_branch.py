"""T04d (W14b with W18/W21) [E11], [E12]: a finding on one parallel branch holds that branch and its consumer, nothing else.

Two independent nodes E1, E2 run in two real Control slots (isolated fixture executor); F consumes E1 (`requires: verified`); I integrates.
E1's check fails -> the register (W21) opens a finding on E1; the engine holds E1, F and I ([E11]); E2 is verified and finishes, and no
`node.held` is written for E2 or for the root ([E12]). Counter-rule: a hold on E2 or on all running nodes would show as a held event / blocker.
"""
import threading

from onecrew.control_core import Control, migrate
from onecrew.snapshots import Snapshots
from onecrew.v2 import engine, findings, internal_plan, plan
from tests.test_v2_l1 import Fixture, plan_json
from tests.test_wf_engine import node
from tests.test_wf_parallel_engine import ParallelFixture


class FindingHoldsBranchTests(ParallelFixture):
    def setUp(self):
        Fixture.setUp(self)
        self.engine, self.ip = engine, internal_plan
        self.engine_caps = ['namespaced-storage', 'finding-register', 'root-budget', 'internal-plan', 'sequential-engine', 'parallel-engine']
        raw = plan_json(scope={'owned': ['a.txt', 'b.txt']}, authority={'edit': True, 'commands': True, 'self_decide': ['Q1', 'Q2', 'Q3', 'Q4', 'Q9', 'Q12']})
        self.root_view = plan.propose(self.ledger, 'P1', raw, 'codex', workflow=True, capabilities=self.engine_caps)
        plan.approve(self.ledger, 'P1', 'owner', 'bounded temporary parallel fixture')
        import os
        os.environ['ONECREW_ACTOR'] = 'codex'
        self.store = Snapshots(self.ledger.state_root); migrate(self.ledger); self.control = Control(self.ledger)
        e2 = node('E2', write=('b.txt',)); e2['read'] = ['b.txt']
        consumer = node('F', ['E1'], write=()); consumer['read'] = ['a.txt']
        integration = node('I', ['E1', 'E2', 'F'], integration=True, write=()); integration['read'] = []
        self.revise([node('E1'), e2, consumer, integration])

    def test_e11_e12_finding_on_e1_holds_f_not_e2_and_not_the_root(self):
        barrier = threading.Barrier(2); started = []; lock = threading.Lock()
        def together(ledger, control, task, item, attempt):
            control.launched(attempt['id'], attempt['generation'], {'fixture': True})
            with lock: started.append(item['id'])
            barrier.wait(5)
            result = {'artifact': self.store.blob(('isolated-' + item['id']).encode()), 'receipt': self.store.blob(b'fixture isolated result')}
            control.finish(attempt['id'], attempt['generation'], result)
            return result
        results = engine.run_batch(self.ledger, 'P1', self.isolated(together), slots=2)
        self.assertEqual(set(started), {'E1', 'E2'})                                                 # both ran in one window [E10]
        self.assertEqual({r['node'] for r in results['results']}, {'E1', 'E2'})
        def red(item, artifact):
            return {'artifact': artifact, 'checks': [{'id': c['id'], 'result': 'fail', 'evidence': self.store.blob(b'E1 check failed')} for c in item['checks']]}
        failed = self.verify('E1', red)
        self.assertEqual(len(failed['findings']['opened']), 1)
        [finding] = findings.list_findings(self.ledger, 'P1', open_only=True)
        held = self.engine.state(self.ledger, 'P1')['finding_blockers']
        self.assertEqual(set(held), {'E1', 'F', 'I'})                                                # [E11] the branch and its consumer
        self.assertNotIn('E2', held)                                                                   # [E12] not the independent branch
        self.assertEqual(self.verify('E2')['result'], 'pass')                                          # [E11] E2 finishes
        view = self.engine.state(self.ledger, 'P1')
        self.assertEqual(view['nodes']['E2']['state'], 'verified')
        self.assertEqual(view['nodes']['F']['state'], None); self.assertEqual([n['id'] for n in self.engine.ready(self.ledger, 'P1')], [])
        held_events = [p for k, p in self.events() if k == 'node.held']
        self.assertEqual([p['node'] for p in held_events if p['node'] in ('E2',)], [])                 # [E12] no hold written for E2
        self.assertEqual(plan.show(self.ledger, 'P1')['status'], 'approved')                           # [E12] the root is not held/stopped
        self.assertFalse(self.engine.root_ready(self.ledger, 'P1'))
        self.assertEqual(finding['node'], 'E1')
