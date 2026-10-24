"""T38c repair focus and generations using authentic engine check receipts."""
import copy
from unittest.mock import patch

from onecrew import dependency_core
from onecrew.ledger import LedgerError
from onecrew.v2 import repair_tasks
from tests.test_wf_engine import EngineFixture, node


class RepairTasksTests(EngineFixture):
    def setUp(self):
        super().setUp()
        changed = node('C')
        changed['checks'] = [{'id': cid, 'spec': 'Mandatory ' + cid} for cid in ['A1', 'F1', 'A2']]
        independent = node('B', write=['b.txt']); independent['read'] = ['b.txt']
        integration = node('I', ['C', 'B'], integration=True, write=()); integration['read'] = []
        self.revise([changed, independent, integration])

    def failure(self, item, artifact):
        return {'artifact': artifact, 'checks': [{'id': c['id'], 'result': 'fail' if c['id'] == 'F1' else 'pass',
                'evidence': self.store.blob(('actual check ' + c['id']).encode())} for c in item['checks']]}

    def prepare_failure(self):
        self.step(); self.verify('C', self.failure)
        self.step(); self.verify('B')
        self.before = self.engine.state(self.ledger, 'P1')
        self.old_receipt = self.before['nodes']['C']['verification_receipt']

    def test_focused_repair_preserves_unrelated_generation_and_failed_case_runs_first(self):
        self.prepare_failure()
        with patch.object(dependency_core, 'affected_tasks', wraps=dependency_core.affected_tasks) as affected:
            plan = repair_tasks.prepare(self.ledger, 'P1', 'C', 'C', reason='Fix the actual F1 failure', evidence=[self.old_receipt])
            self.assertGreater(affected.call_count, 0)
        self.assertEqual(plan['affected_nodes'], ['C', 'I'])
        after = self.engine.state(self.ledger, 'P1')
        self.assertEqual(after['nodes']['C']['generation'], self.before['nodes']['C']['generation'] + 1)
        self.assertEqual(after['nodes']['I']['generation'], self.before['nodes']['I']['generation'] + 1)
        # B is untouched by the repair: same generation, artifact, receipts and state. The only change is that the new internal
        # revision is added to the revisions B's result stays valid for (a late result of an unchanged node is never discarded).
        unchanged = {k: v for k, v in after['nodes']['B'].items() if k != 'valid_internal_revisions'}
        self.assertEqual(unchanged, {k: v for k, v in self.before['nodes']['B'].items() if k != 'valid_internal_revisions'})
        self.assertEqual(after['nodes']['B']['valid_internal_revisions'], self.before['nodes']['B']['valid_internal_revisions'] + [after['internal_revision']])
        self.assertEqual(after['nodes']['B']['state'], 'verified')
        configured = next(n for n in after['definition']['nodes'] if n['id'] == 'C')['checks']
        order = repair_tasks.verification_order(self.ledger, 'P1', 'C', configured)
        self.assertEqual(order['ordered'], ['F1', 'A1', 'A2']); self.assertEqual(order['failed_first'], ['F1'])
        self.assertTrue(order['stop_on_failed_prerequisite'])
        self.step()
        calls = []
        def repaired(item, artifact):
            ranked = repair_tasks.verification_order(self.ledger, 'P1', item['id'], item['checks'])
            rows = []
            for cid in ranked['ordered']:
                calls.append(cid)
                rows.append({'id': cid, 'result': 'pass', 'evidence': self.store.blob(('repair check ' + cid).encode())})
            return {'artifact': artifact, 'checks': rows}
        self.verify('C', repaired)
        self.assertEqual(calls, ['F1', 'A1', 'A2'])
        all_checks = [c['id'] for n in after['definition']['nodes'] for c in n['checks']]
        self.assertLess(len(calls), len(all_checks), 'unrelated node/suite checks were retained, not rerun')
        self.store.read_blob(self.old_receipt)
        self.assertFalse(self.engine.verification_ready(self.ledger, 'P1'), 'mandatory integration remains unchecked')

    def test_still_failing_prerequisite_blocks_later_checks_and_never_verifies_node(self):
        self.prepare_failure()
        repair_tasks.prepare(self.ledger, 'P1', 'C', 'C', reason='Repair actual failed case', evidence=[self.old_receipt])
        self.step()
        calls = []
        def still_red(item, artifact):
            order = repair_tasks.verification_order(self.ledger, 'P1', item['id'], item['checks'])
            rows = []
            for cid in order['ordered']:
                if rows:
                    rows.append({'id': cid, 'result': 'blocked', 'evidence': self.store.blob(b'F1 prerequisite remains red')})
                else:
                    calls.append(cid); rows.append({'id': cid, 'result': 'fail', 'evidence': self.store.blob(b'actual F1 failed')})
            return {'artifact': artifact, 'checks': rows}
        self.verify('C', still_red)
        self.assertEqual(calls, ['F1'])
        self.assertEqual(self.engine.state(self.ledger, 'P1')['nodes']['C']['state'], 'produced')

    def test_stale_forged_unknown_failures_and_unrelated_target_are_refused(self):
        self.prepare_failure()
        with self.assertRaises(LedgerError):
            repair_tasks.prepare(self.ledger, 'P1', 'C', 'C', reason='forged', evidence=['x'], receipt='0' * 64)
        with self.assertRaises(LedgerError):
            repair_tasks.prepare(self.ledger, 'P1', 'B', 'C', reason='unrelated', evidence=['x'])
        self.verify('C')
        with self.assertRaises(LedgerError):
            repair_tasks.prepare(self.ledger, 'P1', 'C', 'C', reason='superseded failure', evidence=['x'], receipt=self.old_receipt)
        with self.assertRaises(LedgerError):
            repair_tasks.prepare(self.ledger, 'P1', 'C', 'C', reason='no actual failed check', evidence=['x'])
        with self.assertRaises(LedgerError):
            repair_tasks.verification_order(self.ledger, 'P1', 'C', ['F1'])

    def test_old_generation_green_cannot_publish_after_repair_reissues_owner(self):
        self.prepare_failure()
        def late(item, artifact):
            repair_tasks.prepare(self.ledger, 'P1', 'C', 'C', reason='Reissue from the recorded actual failure', evidence=[self.old_receipt])
            return self.checker(item, artifact)
        with self.assertRaisesRegex(LedgerError, 'retained without verification'):
            self.verify('C', late)
        current = self.engine.state(self.ledger, 'P1')['nodes']['C']
        self.assertEqual(current['generation'], self.before['nodes']['C']['generation'] + 1)
        self.assertIsNone(current['state']); self.assertEqual(current['phase'], 'pending')
        self.assertIn('node.result_retained', self.kinds())
