"""T17b / T17c (R05, round 7): the out-of-authority branch B1 is held with reason U2, the independent B2 finishes during the hold,
B1's decision is one card, and after the owner's answer the request is closed and B1's next action matches the answer.

Real engine, ledger, Git and request table; the worker/checker are the engine fixtures and the owner terminal is simulated through
questions.answer (interface only, as the testcase allows). B1 = node A (asks to write outside.txt, outside `scope`), B2 = node B.
T17c [E4]/[E9] are proven for the count (one card, asking again returns the same card) and for the card fields the product carries
(problem, options, recommendation, scope); the request has no evidence pointer and no decide-by moment (recorded as uncovered).
"""
import os
from unittest.mock import patch

from onecrew.v2 import plan, questions
from tests.test_wf_answer_atomicity import assert_no_answered_without_effect
from tests.test_wf_engine import EngineFixture, node

U2_ACTION = {'kind': 'write', 'paths': ['outside.txt']}


class HeldBranchFixture(EngineFixture):
    def tearDown(self):
        assert_no_answered_without_effect(self.ledger, plan.show(self.ledger, 'P1')['anchor_task'])

    def hold(self):
        self.revise([node('A'), node('B', write=('b.txt',)), node('I', ['A', 'B'], integration=True, write=())])
        self.grant = plan.show(self.ledger, 'P1')
        return self.engine.request_action(self.ledger, 'P1', 'A', dict(U2_ACTION))

    def node_events(self, kind, nid):
        return [i for i, (k, p) in enumerate(self.events()) if k == kind and p.get('node') == nid]


class T17bHeldBranchTests(HeldBranchFixture):
    def test_e2_e3_e8_b1_held_for_u2_and_b2_finishes_inside_the_hold_without_a_hold_event(self):
        result = self.hold()
        self.assertEqual((result['in_authority'], result['class']), (False, 'U2'))
        held = [p for k, p in self.events() if k == 'node.held' and p['node'] == 'A']
        self.assertEqual(len(held), 1)                                                            # [E2]
        self.assertEqual(held[0]['classification'], 'U2'); self.assertTrue(held[0]['reason'])
        self.assertEqual(self.step()['node'], 'B')
        self.verify('B')
        state = self.engine.state(self.ledger, 'P1')
        self.assertEqual(state['nodes']['B']['state'], 'verified')                                # [E3] B2 done ...
        self.assertEqual(state['nodes']['A']['phase'], 'held')                                    # ... while B1 is still held
        held_at = self.node_events('node.held', 'A')[0]
        self.assertTrue(all(i > held_at for i in self.node_events('node.verification', 'B')))
        self.assertEqual(self.node_events('node.resumed', 'A'), [])
        self.assertEqual(self.node_events('node.held', 'B'), [])                                  # [E8]
        self.assertFalse((self.root / 'outside.txt').exists())
        self.assertEqual(self.engine.ready(self.ledger, 'P1'), [], 'only the held B1 closure remains')


if __name__ == '__main__':
    import unittest
    unittest.main()
