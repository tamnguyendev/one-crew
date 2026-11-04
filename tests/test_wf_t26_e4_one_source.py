"""T26 [E4] (W12b, round 6, decided 25/10 under delegated authority): "cùng việc" is the SOL-linked work.

Source: 05 T26 — Tiền điều kiện "cùng một việc có SOL v1 đã duyệt"; Fixture "một SOL v1 đã duyệt, và một root v2 cho cùng việc"; [E4] evidence
"thử tạo bản duyệt thứ hai cho cùng việc: bị từ chối, lý do nêu root v2 hiện có; đếm nguồn quyền cho việc = 1"; 00 HD-07 "v1 và v2 không là hai
nguồn duyệt độc lập cho cùng việc. Bản ghi v1 (SOL, envelope) liên kết vào root v2 qua adapter." The work's identity is its SOL conversation
(solution_link); scope overlap alone is not "the same work" (T32 [E3] keeps several roots legitimate), so the live-writer rule of
root_writer.check_approval/guard stays as defence (T32 [E4]) and is not widened.

Every route to a second approval of the same SOL work is refused naming the existing root, and the authority sources for the work stay 1:
  (1) a second root proposed with the same SOL ref;
  (2) a second root proposed with a successor SOL revision of the same conversation;
  (3) a second root proposed UNLINKED, then amended to link the same SOL, then approved;
  (4) an unlinked second root proposed BEFORE the first root linked, then amended to link.
"""
from onecrew import conversations, solution_gate
from onecrew.ledger import LedgerError
from onecrew.v2 import plan, solution_link
from tests.test_conversations import solution
from tests.test_v2_l1 import Fixture, plan_json
from tests import test_wf_solution_link as base


class SecondApprovalForTheSameWorkIsRefused(Fixture):
    linked_root, job = base.SolutionLinkTests.linked_root, base.SolutionLinkTests.job     # same SOL/root fixture; base cases not re-run here

    def setUp(self):
        super().setUp()
        self.cid = conversations.create(self.ledger, 'Existing SOL work', 'fixture', 'user')['id']
        self.sol = conversations.propose(self.ledger, self.cid, 'source', solution(), 'codex')
        conversations.decide(self.ledger, self.sol['id'], self.sol['revision'], 'approve', 'user', 'temporary fixture approval')
        self.ref = {key: self.sol[key] for key in ('id', 'revision')}
        self.contract = plan_json(solution_ref=self.ref, authority={'edit': True, 'commands': True})

    def sources(self):
        """Authority sources for this SOL work: roots linked to its conversation, approved, plus any SOL grant (always none)."""
        with self.ledger.transaction() as conn:
            rows = [row for row in solution_link._links(self.ledger, conn) if row['conversation'] == self.cid]
            roots = {row['root_task_id'] for row in rows}
            approved = {r for r in roots if plan.anchor_events(self.ledger, conn, next(x['selector'] for x in rows if x['root_task_id'] == r))['approved']}
            sol_grants = [row for row in rows if row.get('grants_authority')]
        return len(approved) + len(sol_grants)

    def assert_names_first(self, raised, root):
        self.assertIn(root['anchor_task'], str(raised.exception))
        self.assertIn('plan-ns:P1', str(raised.exception))

    def test_e4_same_sol_second_root_refused_and_one_source(self):
        root = self.linked_root()
        self.assertEqual(self.sources(), 1)
        with self.assertRaises(LedgerError) as raised:
            plan.propose(self.ledger, 'P2', self.contract, 'codex', workflow=True)                  # (1)
        self.assert_names_first(raised, root)
        successor = conversations.propose(self.ledger, self.cid, 'next', dict(solution(), detail='Revised source'), 'codex', self.sol['id'])
        conversations.decide(self.ledger, successor['id'], successor['revision'], 'approve', 'user', 'temporary fixture approval')
        changed = dict(self.contract, solution_ref={key: successor[key] for key in ('id', 'revision')})
        with self.assertRaises(LedgerError) as raised:
            plan.propose(self.ledger, 'P2', changed, 'codex', workflow=True)                         # (2)
        self.assert_names_first(raised, root)
        self.assertEqual(self.sources(), 1)
        task = self.job()
        allowed = solution_gate.check(self.ledger, task['id'])
        self.assertEqual((allowed['authority'], allowed['root']['task_id'], allowed['solution_authority']), ('root', root['anchor_task'], 'none'))

    def test_e4_unlinked_second_root_cannot_be_amended_into_the_same_work(self):
        root = self.linked_root()
        unlinked = {key: value for key, value in self.contract.items() if key != 'solution_ref'}
        plan.propose(self.ledger, 'P2', unlinked, 'codex', workflow=True)
        plan.approve(self.ledger, 'P2', 'owner', 'temporary unrelated root')                           # legitimate: not the SOL work
        with self.assertRaises(LedgerError) as raised:
            plan.amend(self.ledger, 'P2', self.contract, 'link the same SOL', 'codex')                # (3)
        self.assert_names_first(raised, root)
        with self.ledger.transaction() as conn:
            state = plan.anchor_events(self.ledger, conn, 'P2')
        self.assertEqual(state['latest'], 1)                                                           # nothing recorded
        self.assertEqual(self.sources(), 1)

    def test_e4_root_proposed_before_the_link_cannot_take_the_work_later(self):
        unlinked = {key: value for key, value in self.contract.items() if key != 'solution_ref'}
        plan.propose(self.ledger, 'P2', unlinked, 'codex', workflow=True)                             # (4) exists first, unlinked
        root = self.linked_root()
        with self.assertRaises(LedgerError) as raised:
            plan.amend(self.ledger, 'P2', self.contract, 'link the same SOL', 'codex')
        self.assert_names_first(raised, root)
        with self.assertRaises(LedgerError):
            plan.approve(self.ledger, 'P2', 'owner', 'try a second approval', revision=2)
        self.assertEqual(self.sources(), 1)



if __name__ == '__main__':
    import unittest
    unittest.main()
