"""T16b (R05, round 7): one root run on one temporary ledger, decision classes Q1, Q2, Q3, Q4, Q5, Q8, Q9, Q10.

Real ledger, real Git, real engine, real register and repair plan; the worker and the checkers are the engine fixtures (interface
only, as the testcase allows). The run: split the work (Q1), add an acceptance test-preparation node (Q4), let the engine choose each
eligible node (Q2), the fixture worker works inside its write scope (Q3), the integration check fails and the open finding holds the
scoped branch (Q8), the repair is prepared and run (Q5), every node reaches `verified` (Q9), the root is ended and its outcome is
written (Q10).

[E5]/[E12]: the request count of the whole ledger is 0 before and after the run, and the root contract stays approved at revision 1
with unchanged bytes (no `plan.proposed`/`plan.amended` after approval). [E7]: the internal plan revision rises after the split and
after the repair while the contract revision and hash do not change. [E6] is only partly provable: Q1, Q2, Q4, Q9 leave HD-05
records with a OneCrew subject; Q5, Q8 and Q10 leave no decision record in the product (recorded as uncovered, not asserted here).
"""
import os

from onecrew.control_core import Control, migrate
from onecrew.snapshots import Snapshots
from onecrew.v2 import contract as contracts, engine, findings, internal_plan, outcome, plan, repair_tasks, test_preparation
from tests.test_v2_l1 import Fixture, milestone, plan_json
from tests.test_wf_engine import EngineFixture, node

DELEGATED = ['Q1', 'Q2', 'Q3', 'Q4', 'Q5', 'Q8', 'Q9', 'Q10', 'Q12']
HD05 = ('subject', 'authority', 'evidence', 'scope', 'validity')


class T16bRootRunTests(EngineFixture):
    def setUp(self):
        Fixture.setUp(self)
        self.engine, self.ip = engine, internal_plan
        raw = plan_json(milestones=[milestone()], scope={'owned': ['a.txt', 'b.txt', 'p.txt']},
                        authority={'edit': True, 'commands': True, 'edit_tests': True, 'self_decide': list(DELEGATED)})
        caps = ['namespaced-storage', 'finding-register', 'root-budget', 'internal-plan', 'sequential-engine']
        self.root_view = plan.propose(self.ledger, 'P1', raw, 'codex', workflow=True, capabilities=caps)
        plan.approve(self.ledger, 'P1', 'owner', 'temporary fixture grant')
        self.store = Snapshots(self.ledger.state_root); migrate(self.ledger); self.control = Control(self.ledger)
        os.environ['ONECREW_ACTOR'] = 'codex'

    def all_requests(self):
        with self.ledger.transaction() as conn:
            return conn.execute('SELECT count(*) AS n FROM requests').fetchone()['n']

    def red(self, item, artifact):
        return {'artifact': artifact, 'checks': [{'id': c['id'], 'result': 'fail', 'evidence': self.store.blob(b'integration: a.txt and b.txt disagree')}
                                                 for c in item['checks']]}

    def written(self, ledger, control, task, item, attempt):
        # Q3: the fixture worker's own choice of how to work, inside the node's declared write scope.
        self.assertTrue(set(item['write']) <= {'a.txt', 'b.txt', 'p.txt'})
        return self.execute(ledger, control, task, item, attempt)

    def run_root(self):
        contract_bytes = contracts.revision_path(self.ledger, 'P1', 1).read_bytes()
        requests_before = self.all_requests()
        approval_seq = len(self.events())
        revisions = []
        # Q1: split the root's work into two tasks plus the integration node.
        self.revise([node('C'), node('I', ['C'], integration=True, write=())])
        c = node('C'); d = node('D', write=('b.txt',)); d['read'] = ['b.txt']
        integration = node('I', ['C', 'D'], integration=True, write=()); integration['read'] = ['a.txt', 'b.txt']
        revisions.append(self.revise([c, d, integration])['internal_revision'])
        # Q4: an acceptance test-preparation node before C.
        test_preparation.prepare(self.ledger, 'P1', 'C', 'P', write=['p.txt'],
            checks=[{'id': 'check-P', 'spec': 'Prepared acceptance cases exist for O1.'}], estimate_seconds=[1, 2],
            execution_cap_seconds=60, budget_calls=1, reason='Prepare acceptance cases before implementation', evidence=['a.txt:1'])
        revisions.append(self.ip.current(self.ledger, 'P1')['internal_revision'])
        # Q2 (the engine picks each eligible node), Q3 (worker inside its scope), Q9 (verified).
        for nid in ('P', 'C', 'D'):
            self.assertEqual(self.step(self.written)['node'], nid); self.verify(nid)
        self.assertEqual(self.step(self.written)['node'], 'I')
        self.assertEqual(self.verify('I', self.red)['result'], 'fail')
        [finding] = findings.list_findings(self.ledger, 'P1', open_only=True)
        held = self.engine.state(self.ledger, 'P1')['finding_blockers']                                     # Q8: the finding holds its scope
        self.assertEqual(set(held), {'C', 'D', 'I'})
        receipt = self.engine.state(self.ledger, 'P1')['nodes']['I']['verification_receipt']
        # Q5: the repair inside the finding scope.
        repair = repair_tasks.prepare(self.ledger, 'P1', 'C', 'I', reason='a.txt must agree with b.txt', evidence=[receipt])
        revisions.append(self.ip.current(self.ledger, 'P1')['internal_revision'])
        self.assertEqual(self.step(self.written)['node'], 'C'); self.verify('C')
        self.assertEqual(self.step(self.written)['node'], 'I')
        self.assertEqual(self.verify('I')['result'], 'pass')
        self.assertEqual(findings.list_findings(self.ledger, 'P1', open_only=True), [])
        self.assertTrue(self.engine.verification_ready(self.ledger, 'P1'))
        # Q10: end the root (a simulated owner stop, as the engine fixtures do) and write its outcome.
        with self.ledger.transaction(write=True) as conn:
            root = plan.anchor_events(self.ledger, conn, 'P1')
            plan.emit(self.ledger, conn, root['task_id'], 'plan.closed',
                      {'revision': root['approved']['revision'], 'reason': 'owner stopped the fixture after verification'})
        written = outcome.record(self.ledger, 'P1')
        return dict(contract_bytes=contract_bytes, requests_before=requests_before,
                    approval_seq=approval_seq, revisions=revisions, repair=repair, outcome=written, finding=finding)

    def test_e5_e7_e12_one_root_run_over_q1_q2_q3_q4_q5_q8_q9_q10_creates_no_request_and_keeps_the_contract(self):
        run = self.run_root()
        self.assertTrue(run['outcome']['recorded'], run['outcome'])
        self.assertIn('learning.outcome', self.kinds())
        # [E5] [E12]: no request or question anywhere in the ledger across the whole run.
        self.assertEqual(run['requests_before'], 0)
        self.assertEqual(self.all_requests(), 0)
        self.assertEqual(self.ledger.requests(self.root_view['anchor_task']), [])
        after = self.kinds()[run['approval_seq']:]
        self.assertFalse([k for k in after if k.startswith('request.')], after)
        # [E7] [E12]: internal revision 1 -> split 2 -> preparation 3 -> repair 4; the contract never moves back to proposed.
        self.assertEqual(run['revisions'], [2, 3, 4])
        self.assertEqual(run['repair']['internal_revision'], 4)
        self.assertEqual(contracts.revision_path(self.ledger, 'P1', 1).read_bytes(), run['contract_bytes'])
        self.assertFalse(contracts.revision_path(self.ledger, 'P1', 2).exists())
        self.assertEqual([k for k in after if k in ('plan.proposed', 'plan.amended', 'plan.approved')], [])
        self.assertGreaterEqual(after.count('plan.revised'), 4)
        shown = plan.show(self.ledger, 'P1')
        self.assertEqual(shown['revision'], 1)
        self.assertNotEqual(shown['status'], 'proposed')

    def test_e6_recorded_classes_carry_hd05_fields_and_a_onecrew_subject(self):
        self.run_root()
        decisions = [p for k, p in self.events() if k == 'decision.recorded']
        by_class = {}
        for decision in decisions:
            by_class.setdefault(decision['basis'].split(':', 1)[0], []).append(decision)
        for q in ('Q1', 'Q2', 'Q4', 'Q9'):
            with self.subTest(q=q):
                self.assertIn(q, by_class)
                for decision in by_class[q]:
                    self.assertTrue(all(decision.get(f) for f in HD05), decision)
                    self.assertTrue(decision['subject']['component'].startswith('onecrew.'), decision['subject'])
                    self.assertNotIn(decision['actor'], ('owner', 'user'))
                    self.assertEqual(decision['validity']['outcome'], 'in_authority')
        for decision in decisions:                               # no record in the run is signed by the owner
            self.assertNotIn(decision['actor'], ('owner', 'user'))


if __name__ == '__main__':
    import unittest
    unittest.main()
