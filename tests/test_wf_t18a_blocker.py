"""T18a (W20, R05) [E2], [E4]-[E7]: when the bounded repair loop ends, the blocker carries evidence and reaches the owner through the report.

Same fixture as tests/test_wf_recovery_policy (node A always fails; one bounded repair, one materially different replan, then blocked). The
third decision is `blocked` with the red check ids, the list of the three failed verification receipts and what the root spent against its
sealed ceilings; `plan report` and the handover print it; no owner request is created in the loop ([E7]); the ceilings in the ledger are
unchanged ([E6]); A never has a passing receipt ([E4]); the check configuration hash is unchanged ([E5]). The budget cap itself ([E3]) is
enforced by the root budget (tests/test_wf_task_caps, metered_verifier); here it is only reported.
"""
import copy

from onecrew.ledger import content_hash
from onecrew.v2 import plan, repair_tasks, report
from tests.test_wf_recovery_policy import RecoveryPolicyTests


class BlockerEvidenceTests(RecoveryPolicyTests):
    def test_e2_blocked_decision_lists_red_checks_attempts_and_spend_and_the_report_shows_it(self):
        task = self.root_view['anchor_task']
        checks_before = content_hash(self.ip.current(self.ledger, 'P1')['definition']['nodes'][0]['checks'])
        with self.ledger.transaction() as conn:
            from onecrew import budget_core
            ceiling_before = budget_core.group(conn, task)['max_calls']
        self.fail(); first = self.recovery.assess(self.ledger, 'P1', 'A')
        self.assertEqual(first['disposition'], 'repair'); self.assertEqual(len(first['diagnosis']['attempts']), 1)
        repair_tasks.prepare(self.ledger, 'P1', 'A', 'A', reason='First bounded repair.', evidence=[first['source_receipt']])
        self.fail(); second = self.recovery.assess(self.ledger, 'P1', 'A')
        self.assertEqual(second['disposition'], 'diagnose'); self.assertEqual(len(second['diagnosis']['attempts']), 2)
        definition = copy.deepcopy(self.ip.current(self.ledger, 'P1')['definition']['nodes'])
        definition[0]['goal'] = 'Investigate a different supported cause using the retained failing test.'
        self.recovery.replan(self.ledger, 'P1', 'A', definition, reason='Different diagnosis on the actual failed receipt.', evidence=[second['source_receipt']])
        self.fail(); third = self.recovery.assess(self.ledger, 'P1', 'A')
        self.assertEqual(third['disposition'], 'blocked')
        d = third['diagnosis']
        self.assertEqual(d['failed_checks'], ['check-A'])                                                      # [E2] the red case id
        self.assertEqual(len(d['attempts']), 3)                                                                # [E2] every attempt, with its receipt
        receipts = [a['receipt'] for a in d['attempts']]
        self.assertEqual(len(set(receipts)), 3); self.assertEqual(receipts[-1], third['source_receipt'])
        self.assertEqual([a['generation'] for a in d['attempts']], [0, 1, 2])
        spent = d['spent']
        self.assertEqual(spent['max_calls'], ceiling_before); self.assertIsNotNone(spent['used_calls']); self.assertTrue(spent['deadline'])   # [E2] cost
        self.assertLessEqual(spent['used_calls'], spent['max_calls'])
        self.assertFalse(third['resets_budget']); self.assertFalse(third['creates_owner_request'])
        # the owner sees it
        text = report.render_report(self.ledger.state_root, 'P1', project_id=self.ledger.project_id)
        handover = report.render_handover(self.ledger.state_root, 'P1', project_id=self.ledger.project_id)
        for page in (text, handover):
            self.assertIn('Blocker node A', page); self.assertIn('check-A', page); self.assertIn('3 lần thử', page)
            self.assertIn(f'{spent["used_calls"]}/{spent["max_calls"]} lời gọi', page)
        # [E4] no pass for A; [E5] checks unchanged; [E6] ceiling unchanged; [E7] no request in the loop
        self.assertFalse(any(k == 'node.verification' and p['result'] == 'pass' for k, p in self.events()))
        self.assertEqual(content_hash(self.ip.current(self.ledger, 'P1')['definition']['nodes'][0]['checks']), checks_before)
        with self.ledger.transaction() as conn:
            self.assertEqual(budget_core.group(conn, task)['max_calls'], ceiling_before)
        self.assertEqual(self.ledger.requests(task), [])
        self.assertEqual(plan.show(self.ledger, 'P1')['status'], 'approved')

    def test_a_repair_disposition_is_not_shown_as_a_blocker(self):
        self.fail(); self.recovery.assess(self.ledger, 'P1', 'A')
        text = report.render_report(self.ledger.state_root, 'P1', project_id=self.ledger.project_id)
        self.assertNotIn('Blocker node', text); self.assertNotIn('Cần chẩn đoán', text)
