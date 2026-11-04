"""T38b [E4], [E7], [E8] (W23a): the handover tells three task states apart, each from its own evidence.

One approved plan with three command milestones: A passes (valid receipt on the current artifact) -> `đã-kiểm`; B fails -> `phải kiểm lại`;
C is specified in the contract but never ran -> `testcase-đã-đặc-tả` (a missing receipt is NOT reported as a missing testcase). B and C
are never `đã-kiểm` ([E7]); the output C covers is never `đạt` ([E8]). The same words appear on `plan present`.
"""
import sys

from onecrew.v2 import plan as plans, report, verdict
from tests.test_v2_l1 import Fixture, plan_json, milestone, BAD

OK_CMD = [sys.executable, '-c', 'print("ok")']


class TaskStateTests(Fixture):
    def setUp(self):
        super().setUp()
        value = plan_json(output=['A done', 'B done', 'C done'],
                          milestones=[milestone('M1', argv=OK_CMD, covers=['O1']), milestone('M2', argv=BAD, covers=['O2'], max_repairs=1),
                                      milestone('M3', argv=OK_CMD, covers=['O3'])])          # M1 = A (passes), M2 = B (fails), M3 = C (never runs)
        plans.propose(self.ledger, 'P1', value, 'codex'); plans.approve(self.ledger, 'P1', 'owner', 'fixture')
        verdict.run(self.ledger, 'P1', 'M1', self.root)
        verdict.run(self.ledger, 'P1', 'M2', self.root)                                  # fails (B keeps a repair left, so C is not reached)

    def test_e4_e7_e8_three_states_with_their_sources(self):
        f = report._lookup(self.ledger.state_root, 'P1', project_id=self.ledger.project_id)
        states = {v['id']: report.task_state(f, v) for v in f['views']}
        self.assertEqual(states['M1'][0], report.CHECKED); self.assertIn('biên nhận', states['M1'][1])                 # [E4] A with its receipt
        self.assertEqual(states['M2'][0], report.RECHECK_TASK); self.assertIn('verdict gần nhất fail', states['M2'][1])
        self.assertEqual(states['M3'][0], report.SPECIFIED); self.assertIn('testcase có trong hợp đồng', states['M3'][1])   # not "no testcase"
        self.assertNotEqual(states['M2'][0], report.CHECKED); self.assertNotEqual(states['M3'][0], report.CHECKED)       # [E7]
        handover = report.render_handover(self.ledger.state_root, 'P1', project_id=self.ledger.project_id)
        present = report.render_present(self.ledger.state_root, 'P1', project_id=self.ledger.project_id)
        for page in (handover, present):
            self.assertIn('M1 đã-kiểm', page); self.assertIn('M2 phải kiểm lại', page); self.assertIn('M3 testcase-đã-đặc-tả', page)
        o3 = [line for line in handover.splitlines() if line.strip().startswith('O3 ')]
        self.assertEqual(len(o3), 1); self.assertNotIn(' đạt ', o3[0]); self.assertIn('chưa có', o3[0])                # [E8]
        self.assertIn('testcase có trong hợp đồng', handover)
        a = [line for line in handover.splitlines() if line.strip().startswith('O1 ')][0]
        self.assertIn(' đạt ', a)
