"""Round 10 D6 (2.2/L0, W21/W19 obligations): a node finding must stay repairable across a valid internal-plan revise.

Reproduced defect (SDK trial 26/10, ledger seq 2028-2043): `engine verify` fails -> finding RF1 (internal, node N1) opens and holds every
node in its scope; a valid `engine revise` (changed node goal, checks unchanged) moves N1's generation and drops its
`verification_receipt` -> `repair_tasks.prepare` refuses ("Repair requires the latest node verification receipt.") and `findings resolve`
needs a newer passing receipt that can never come because RF1 holds N1: a permanent deadlock. The only way out was a punctuation-only
change of the check spec, which made `findings._refresh` mark RF1 stale (a wording trick, not a fix).

Required: verify fail -> finding open -> valid revise -> repair on the new generation -> resolve with the matching passing receipt (same
node, same criterion, newer seq). A wording-only spec change keeps the finding OPEN; only a real check change (classify_text 'changed' /
'threshold' / removed check) marks it stale. Old receipts / other nodes cannot close it; a replan does not deadlock; an independent node
keeps running; a restart (re-read from the ledger) keeps the finding and no bypass appears.
"""
import copy
import os

from onecrew.control_core import Control, migrate
from onecrew.ledger import Ledger, LedgerError
from onecrew.snapshots import Snapshots
from onecrew.v2 import engine, findings, internal_plan, plan, recovery_policy, repair_tasks
from tests.test_v2_l1 import Fixture, milestone, plan_json
from tests.test_wf_engine import EngineFixture, node


class D6Fixture(EngineFixture):
    def setUp(self):
        Fixture.setUp(self)
        self.engine, self.ip = engine, internal_plan
        raw = plan_json(milestones=[milestone()], scope={'owned': ['a.txt', 'b.txt', 'x.txt']},
                        authority={'edit': True, 'commands': True, 'self_decide': ['Q1', 'Q2', 'Q3', 'Q4', 'Q5', 'Q8', 'Q9', 'Q12']})
        caps = ['namespaced-storage', 'finding-register', 'root-budget', 'internal-plan', 'sequential-engine']
        self.root_view = plan.propose(self.ledger, 'P1', raw, 'codex', workflow=True, capabilities=caps)
        plan.approve(self.ledger, 'P1', 'owner', 'temporary fixture grant')
        self.store = Snapshots(self.ledger.state_root); migrate(self.ledger); self.control = Control(self.ledger)
        os.environ['ONECREW_ACTOR'] = 'codex'
        n1 = node('N1'); n2 = node('N2', write=('b.txt',)); n2['read'] = ['b.txt']
        x = node('X', write=('x.txt',)); x['read'] = ['x.txt']
        integration = node('I', ['N1', 'N2', 'X'], integration=True, write=()); integration['read'] = ['a.txt', 'b.txt']
        self.nodes = [n1, n2, x, integration]
        self.revise(self.nodes)

    def red(self, item, artifact):
        return {'artifact': artifact, 'checks': [{'id': c['id'], 'result': 'fail', 'evidence': self.store.blob(b'M1: publish.yml:32 does not exist')}
                                                 for c in item['checks']]}

    def fail_n1_and_run_independent(self):
        self.assertEqual(self.step()['node'], 'N1')
        result = self.verify('N1', self.red)
        self.assertEqual(result['result'], 'fail')
        [finding] = findings.list_findings(self.ledger, 'P1', open_only=True)
        self.assertEqual((finding['node'], finding['criterion']), ('N1', 'check-N1'))
        failed = self.engine.state(self.ledger, 'P1')['nodes']['N1']['verification_receipt']
        # (e) independent branches keep running while the finding holds N1 and I
        self.assertEqual(self.step()['node'], 'N2'); self.verify('N2')
        self.assertEqual(self.step()['node'], 'X'); self.verify('X')
        return finding, failed

    def revised(self, change):
        nodes = copy.deepcopy(self.nodes)
        change(next(n for n in nodes if n['id'] == 'N1'))
        self.revise(nodes, reason='Coordinator clarified the N1 instruction (full path, as keyed in the source)')
        self.nodes = nodes
        return self.engine.state(self.ledger, 'P1')

    def goal_change(self, item):
        item['goal'] = 'Produce evidence for O1 using the full path exactly as keyed in the source'

    def repair_and_close(self, finding, failed):
        repair = repair_tasks.prepare(self.ledger, 'P1', 'N1', 'N1', reason='Use the full path key', evidence=[failed])
        self.assertEqual(repair['source_receipt'], failed)
        self.assertEqual(repair['failed_checks'], ['check-N1'])
        view = self.engine.state(self.ledger, 'P1')
        self.assertNotIn('N1', view['finding_blockers'])                     # the repair re-issues N1 from RF1
        self.assertEqual(findings.list_findings(self.ledger, 'P1', open_only=True)[0]['id'], finding['id'])
        self.assertEqual(self.step()['node'], 'N1')
        result = self.verify('N1')
        self.assertEqual(result['result'], 'pass')
        self.assertEqual(result['findings']['closed'], [finding['id']])
        closed = next(f for f in findings.list_findings(self.ledger, 'P1') if f['id'] == finding['id'])
        self.assertEqual(closed['status'], 'resolved')
        record = self.engine.state(self.ledger, 'P1')['nodes']['N1']
        self.assertEqual(closed['resolution']['receipt'], record['verification_receipt'])
        self.assertEqual(closed['resolution']['generation'], record['generation'])
        self.assertGreater(record['generation'], finding['generation'])
        self.assertEqual(closed['source']['receipt'], failed)                 # origin and fail receipt are kept
        self.assertEqual(self.step()['node'], 'I'); self.verify('I')
        self.assertTrue(self.engine.verification_ready(self.ledger, 'P1'))


class D6Tests(D6Fixture):
    def test_a_revise_with_changed_goal_keeps_the_finding_repairable_and_a_pass_closes_it(self):
        finding, failed = self.fail_n1_and_run_independent()
        view = self.revised(self.goal_change)
        self.assertIsNone(view['nodes']['N1'].get('verification_receipt'))
        self.assertIn('N1', view['finding_blockers'])                        # still held: no bypass by the revise
        self.assertEqual(findings.list_findings(self.ledger, 'P1', open_only=True)[0]['status'], 'open')
        self.assertEqual(self.step()['state'], 'waiting')                    # nothing runs N1 while RF1 holds it
        self.repair_and_close(finding, failed)

    def test_b_wording_only_spec_change_keeps_the_finding_open_and_does_not_close_it(self):
        finding, failed = self.fail_n1_and_run_independent()
        def punctuation(item):
            item['checks'][0]['spec'] = item['checks'][0]['spec'] + '.'
        self.revised(punctuation)
        [still] = findings.list_findings(self.ledger, 'P1', open_only=True)
        self.assertEqual((still['id'], still['status']), (finding['id'], 'open'))
        self.assertIn('N1', self.engine.state(self.ledger, 'P1')['finding_blockers'])
        self.repair_and_close(finding, failed)

    def test_b_a_real_check_change_marks_the_finding_stale_wording_does_not(self):
        finding, _ = self.fail_n1_and_run_independent()
        with self.ledger.transaction() as conn:
            root, _, _, contract = findings._context(self.ledger, conn, 'P1')
            value = findings._read(self.ledger, conn, root['id'])
        base = copy.deepcopy(self.nodes)
        cases = {'wording': ('Check, the declared O1 output of N1!', 'open'),
                 'changed': ('Check the declared O2 output of N1 and its schema', 'stale'),
                 'threshold': (None, 'stale'), 'removed': (None, 'stale')}
        for kind, (spec, expected) in cases.items():
            with self.subTest(kind=kind):
                nodes = copy.deepcopy(base)
                n1 = nodes[0]
                if kind == 'threshold':
                    n1['checks'][0]['spec'] = 'Check at least 3 rows of N1'
                    original = copy.deepcopy(value)
                    original['findings'][0]['check'] = {'id': 'check-N1', 'spec': 'Check at least 2 rows of N1'}
                    original['findings'][0]['criterion_sha'] = 'x'
                elif kind == 'removed':
                    n1['checks'] = [{'id': 'other', 'spec': 'Something else'}]
                    original = copy.deepcopy(value)
                else:
                    n1['checks'][0]['spec'] = spec
                    original = copy.deepcopy(value)
                findings._refresh(original, contract, nodes)
                self.assertEqual(original['findings'][0]['status'], expected)

    def test_c_old_receipt_other_node_or_wrong_receipt_cannot_close_or_repair(self):
        finding, failed = self.fail_n1_and_run_independent()
        n2_pass = self.engine.state(self.ledger, 'P1')['nodes']['N2']['verification_receipt']
        artifact = self.engine.state(self.ledger, 'P1')['nodes']['N1']['artifact']
        self.revised(self.goal_change)
        old = findings.resolve(self.ledger, 'P1', finding['id'], failed, reason='old', artifact_sha=artifact)
        self.assertEqual(old['closed'], [])
        other = findings.resolve(self.ledger, 'P1', finding['id'], n2_pass, reason='other node', artifact_sha=artifact)
        self.assertEqual(other['closed'], [])
        with self.assertRaises(LedgerError):
            repair_tasks.prepare(self.ledger, 'P1', 'N1', 'N1', reason='wrong receipt', evidence=[n2_pass], receipt=n2_pass)
        self.assertEqual(findings.list_findings(self.ledger, 'P1', open_only=True)[0]['id'], finding['id'])
        self.assertIn('N1', self.engine.state(self.ledger, 'P1')['finding_blockers'])

    def test_d_recovery_assessment_after_revise_does_not_deadlock(self):
        finding, failed = self.fail_n1_and_run_independent()
        self.revised(self.goal_change)
        decision = recovery_policy.assess(self.ledger, 'P1', 'N1')
        self.assertEqual(decision['source_receipt'], failed)
        self.assertFalse(decision['grants_authority']); self.assertFalse(decision['resets_budget'])

    def test_g_a_second_failure_after_the_repair_is_repairable_again(self):
        finding, failed = self.fail_n1_and_run_independent()
        self.revised(self.goal_change)
        repair_tasks.prepare(self.ledger, 'P1', 'N1', 'N1', reason='first repair', evidence=[failed])
        self.assertEqual(self.step()['node'], 'N1')
        again = self.verify('N1', self.red)
        self.assertEqual((again['findings']['opened'], again['findings']['merged']), ([], [finding['id']]))   # no duplicate finding
        second = self.engine.state(self.ledger, 'P1')['nodes']['N1']['verification_receipt']
        repair_tasks.prepare(self.ledger, 'P1', 'N1', 'N1', reason='second repair', evidence=[second])
        self.assertNotIn('N1', self.engine.state(self.ledger, 'P1')['finding_blockers'])
        self.assertEqual(self.step()['node'], 'N1')
        self.assertEqual(self.verify('N1')['findings']['closed'], [finding['id']])

    def test_f_restart_keeps_the_finding_and_no_bypass_then_repairs(self):
        finding, failed = self.fail_n1_and_run_independent()
        self.revised(self.goal_change)
        self.ledger = Ledger(self.root, self.ledger.state_root)            # re-read every state from the ledger
        self.control = Control(self.ledger)
        self.store = Snapshots(self.ledger.state_root)
        self.assertEqual([f['id'] for f in findings.list_findings(self.ledger, 'P1', open_only=True)], [finding['id']])
        self.assertFalse(self.engine.eligible(self.engine.state(self.ledger, 'P1'), 'N1')['ready'])
        self.assertEqual(self.step()['state'], 'waiting')
        self.repair_and_close(finding, failed)


if __name__ == '__main__':
    import unittest
    unittest.main()
