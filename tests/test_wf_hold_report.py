"""W33a (T15b [E1], [E3], [E4], [E9]): the hold of a running node is recorded and reported from the executor's DECLARATION.

Finding-scope fixture (real register, data verifier on a.txt). A hook-style attempt (Control attempt, no `executor.managed` history) is running on
Nw when the finding opens: `hold_views` records the hold as "withdraw write permission" (no pause command exists), `plan report` / handover say
"đã ngừng cấp quyền ghi" and never "đã dừng", the ledger holds no "paused" state and no managed event. A managed history (patched) turns the same
row into "pause requested (not confirmed)". Counter-example (E9): `hold_for_findings` sends nothing to the hook attempt.
"""
from unittest.mock import patch

from onecrew.v2 import executors, managed_executor, report
from tests.test_wf_finding_scope import FindingScopeTests


class HoldReportTests(FindingScopeTests):
    def run_hook_attempt(self, inside):
        seen = {}
        def external(ledger, control, task, item, attempt):
            control.launched(attempt['id'], attempt['generation'], {'fixture': True})
            seen.update(inside(attempt))
            artifact = self.store.blob(b'external candidate'); receipt = self.store.blob(b'external receipt')
            control.finish(attempt['id'], attempt['generation'], {'fixture': True, 'artifact': artifact})
            return {'artifact': artifact, 'receipt': receipt}
        self.engine.step(self.ledger, 'P1', external, control=self.control)
        return seen

    def test_e1_e3_e4_a_hook_attempt_is_held_by_withdrawing_write_permission_and_the_report_says_so(self):
        def inside(attempt):
            ident = self.open_finding()
            rows = managed_executor.hold_views(self.ledger, 'P1')
            text = report.render_report(self.ledger.state_root, 'P1', project_id=self.ledger.project_id)
            handover = report.render_handover(self.ledger.state_root, 'P1', project_id=self.ledger.project_id)
            return {'ident': ident, 'rows': rows, 'report': text, 'handover': handover, 'sent': managed_executor.hold_for_findings(self.ledger, 'P1'),
                    'attempt': attempt['id']}
        seen = self.run_hook_attempt(inside)
        [row] = [r for r in seen['rows'] if r['node'] == 'Nw']
        self.assertEqual(row['plan'], executors.hold_plan(executors.HookAdapter.declaration))                        # [E1] the record
        self.assertEqual((row['plan']['action'], row['plan']['command'], row['plan']['state']), ('revoke_write', None, 'write_revoked'))
        self.assertEqual(row['findings'], [seen['ident']]); self.assertEqual(row['attempt'], seen['attempt'])
        self.assertFalse(row['requested']); self.assertFalse(row['confirmed'])
        self.assertEqual(seen['sent'], [])                                                                            # [E9] no pause to a hook
        for text in (seen['report'], seen['handover']):
            self.assertIn('Giữ node Nw', text); self.assertIn('đã ngừng cấp quyền ghi', text)                        # [E3]
            self.assertNotIn('đã dừng', text.replace('không dừng', '')); self.assertNotIn('paused', text)
        with self.ledger.transaction() as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM events WHERE kind=?', (managed_executor.KIND,)).fetchone()[0], 0)   # [E4]
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM events WHERE kind='node.paused'").fetchone()[0], 0)
        # once nothing runs, the report has no hold line
        self.assertNotIn('Giữ node', report.render_report(self.ledger.state_root, 'P1', project_id=self.ledger.project_id))

    def test_a_managed_history_turns_the_same_row_into_a_requested_pause_that_is_not_confirmed(self):
        def inside(attempt):
            self.open_finding()
            with patch.object(managed_executor.ManagedExecutor, '_history', return_value=[{'phase': 'prepared'}, {'phase': 'pause_requested'}]):
                rows = managed_executor.hold_views(self.ledger, 'P1')
                text = report.render_report(self.ledger.state_root, 'P1', project_id=self.ledger.project_id)
            return {'rows': rows, 'report': text}
        seen = self.run_hook_attempt(inside)
        [row] = [r for r in seen['rows'] if r['node'] == 'Nw']
        self.assertEqual(row['plan'], executors.hold_plan(managed_executor.ManagedExecutor.declaration))
        self.assertEqual(row['plan']['state'], 'pause_requested'); self.assertTrue(row['requested']); self.assertFalse(row['confirmed'])
        self.assertIn('đã yêu cầu dừng tại điểm an toàn (chưa xác nhận) — đã gửi yêu cầu', seen['report'])
        self.assertNotIn('đã ngừng cấp quyền ghi', seen['report'])
