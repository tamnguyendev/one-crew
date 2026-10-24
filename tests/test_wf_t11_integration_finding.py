"""T11 (W21 with W19/W17/W18, R05): unit pass, integration fail.

N1 and N2 are verified at node level; the integration node I depends on every node (`requires: verified`) but integrates only what it
reads (a.txt from N1, b.txt from N2); X writes x.txt that I never reads. When I's check
fails, the shared register gets ONE finding attached to I whose scope is {N1, N2} by dependency edges ([E1]); the root is not verified and no
handoff happens while I is red ([E2], [E4]); the repair targets N1 inside the finding scope, the rerun list is I's failed check first and then
the checks of N1, N2 - smaller than the whole suite ([E3], [E5]); I passing on the repaired generation closes the finding through the register.
Counter-rules: X (outside the scope) is not held; a root without the finding-register capability records no finding (the other engine fixtures).
"""
import os

from onecrew.control_core import Control, migrate
from onecrew.ledger import LedgerError
from onecrew.snapshots import Snapshots
from onecrew.v2 import engine, findings, internal_plan, plan, repair_tasks
from tests.test_v2_l1 import Fixture, milestone, plan_json
from tests.test_wf_engine import EngineFixture, node


class IntegrationFindingTests(EngineFixture):
    def setUp(self):
        Fixture.setUp(self)
        self.engine, self.ip = engine, internal_plan
        raw = plan_json(milestones=[milestone()], scope={'owned': ['a.txt', 'b.txt', 'x.txt']},
                        authority={'edit': True, 'commands': True, 'self_decide': ['Q1', 'Q2', 'Q3', 'Q4', 'Q8', 'Q9', 'Q12']})
        caps = ['namespaced-storage', 'finding-register', 'root-budget', 'internal-plan', 'sequential-engine']
        self.root_view = plan.propose(self.ledger, 'P1', raw, 'codex', workflow=True, capabilities=caps)
        plan.approve(self.ledger, 'P1', 'owner', 'temporary fixture grant')
        self.store = Snapshots(self.ledger.state_root); migrate(self.ledger); self.control = Control(self.ledger)
        os.environ['ONECREW_ACTOR'] = 'codex'
        n1 = node('N1'); n2 = node('N2', write=('b.txt',)); n2['read'] = ['b.txt']
        x = node('X', write=('x.txt',)); x['read'] = ['x.txt']
        integration = node('I', ['N1', 'N2', 'X'], integration=True, write=()); integration['read'] = ['a.txt', 'b.txt']   # integrates a.txt/b.txt; X only feeds it
        self.revise([n1, n2, x, integration])

    def red(self, item, artifact):
        return {'artifact': artifact, 'checks': [{'id': c['id'], 'result': 'fail', 'evidence': self.store.blob(b'integration: a.txt and b.txt disagree')}
                                                 for c in item['checks']]}

    def run_units(self):
        for nid in ('N1', 'N2', 'X'):
            self.assertEqual(self.step()['node'], nid); self.verify(nid)
        self.assertEqual(self.step()['node'], 'I')

    def register_events(self):
        return len([k for k in self.kinds() if k == findings.KIND])

    def test_e1_e2_e4_integration_red_opens_one_dependency_scoped_finding_and_holds_the_root(self):
        self.run_units()
        self.assertEqual(self.register_events(), 0, 'three green units: no register event')
        before = self.kinds()
        result = self.verify('I', self.red)
        self.assertEqual(result['result'], 'fail')
        self.assertEqual(len(result['findings']['opened']), 1)
        [finding] = findings.list_findings(self.ledger, 'P1', open_only=True)
        self.assertEqual((finding['node'], finding['criterion'], finding['scope_nodes']), ('I', 'check-I', ['N1', 'N2']))   # [E1]
        self.assertEqual(finding['scope'], {'read': ['a.txt', 'b.txt'], 'write': ['a.txt', 'b.txt']})
        self.assertTrue(finding['internal'])
        view = self.engine.state(self.ledger, 'P1')
        self.assertEqual(set(view['finding_blockers']), {'N1', 'N2', 'I'})                                      # X is outside the scope
        self.assertFalse(self.engine.verification_ready(self.ledger, 'P1')); self.assertFalse(self.engine.root_ready(self.ledger, 'P1'))   # [E2]
        self.assertEqual(plan.show(self.ledger, 'P1')['status'], 'approved')
        since = self.kinds()[len(before):]
        self.assertEqual([k for k in since if k in ('workflow.handoff', 'plan.accepted')], [])                      # [E4]

    def test_e3_e5_repair_inside_the_scope_reruns_the_failed_check_first_then_the_scope_not_the_suite(self):
        self.run_units()
        self.verify('I', self.red)
        [finding] = findings.list_findings(self.ledger, 'P1', open_only=True)
        receipt = self.engine.state(self.ledger, 'P1')['nodes']['I']['verification_receipt']
        order = repair_tasks.rerun_order(self.ledger, 'P1', finding['id'])
        self.assertEqual(order['ordered'], ['check-I', 'check-N1', 'check-N2'])                                      # [E3] failed first, then the scope
        self.assertTrue(order['smaller_than_suite']); self.assertEqual(len(order['whole_suite']), 4)                 # [E5] X is not rerun
        repair = repair_tasks.prepare(self.ledger, 'P1', 'N1', 'I', reason='a.txt must agree with b.txt', evidence=[receipt])
        target_writes = next(n for n in self.engine.state(self.ledger, 'P1')['definition']['nodes'] if n['id'] == 'N1')['write']
        self.assertTrue(set(target_writes) <= set(finding['scope']['write']))                                          # [E3] repair writes inside the finding scope
        self.assertEqual(repair['affected_nodes'], ['I', 'N1'])
        with self.assertRaises(LedgerError):
            repair_tasks.prepare(self.ledger, 'P1', 'X', 'I', reason='outside the scope', evidence=[receipt])      # X is not in I's dependency scope
        # the repaired generation: N1 again, then I passes -> the register closes the finding (the engine only reports it)
        held = self.engine.state(self.ledger, 'P1')['finding_blockers']
        self.assertEqual(held, {'N2': [finding['id']]}, 'the repair re-issues N1 and I: only N2 of the scope stays held, the finding stays open')
        self.assertEqual(self.step()['node'], 'N1'); self.verify('N1')
        self.assertEqual(findings.list_findings(self.ledger, 'P1', open_only=True)[0]['id'], finding['id'])
        self.assertEqual(self.step()['node'], 'I')
        result = self.verify('I')
        self.assertEqual(result['result'], 'pass'); self.assertEqual(result['findings']['closed'], [finding['id']])
        self.assertEqual(findings.list_findings(self.ledger, 'P1', open_only=True), [])
        self.assertEqual(self.engine.state(self.ledger, 'P1')['finding_blockers'], {})
        self.assertTrue(self.engine.verification_ready(self.ledger, 'P1'))
        closed = [f for f in findings.list_findings(self.ledger, 'P1') if f['id'] == finding['id']][0]
        self.assertEqual(closed['status'], 'resolved')

    def test_the_same_red_receipt_twice_merges_and_writes_no_second_register_event(self):
        self.run_units()
        self.verify('I', self.red)
        count = self.register_events()
        receipt = self.engine.state(self.ledger, 'P1')['nodes']['I']['verification_receipt']
        again = findings.record_node_verification(self.ledger, 'P1', 'I', receipt, definition=self.engine.state(self.ledger, 'P1')['definition']['nodes'])
        self.assertEqual(again['opened'], []); self.assertEqual(len(again['merged']), 1)
        self.assertEqual(self.register_events(), count)
