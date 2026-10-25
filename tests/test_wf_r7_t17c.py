"""T17c (R05, round 7): see tests/test_wf_r7_t17b.py for the shared fixture and the scenario."""
import os
from unittest.mock import patch

from onecrew.v2 import questions
from tests.test_wf_r7_t17b import HeldBranchFixture, U2_ACTION


class T17cOneCardTests(HeldBranchFixture):
    def reply(self, request, choice):
        with patch.dict(os.environ, {'ONECREW_ACTOR': ''}):
            return questions.answer(self.ledger, request['id'], request['revision'], choice, 'owner decision fixture')

    def test_e4_e9_one_card_for_b1_with_problem_options_recommendation_and_scope(self):
        self.hold()
        self.engine.request_action(self.ledger, 'P1', 'A', dict(U2_ACTION))                       # asked again: the same card
        cards = questions.list_for_plan(self.ledger, 'P1')
        self.assertEqual(len(cards), 1)                                                           # [E4] [E9] one card
        self.assertEqual(self.kinds().count('request.created'), 1)
        card = cards[0]['question']
        self.assertTrue(card['question'].strip())                                                 # problem
        self.assertGreaterEqual(len(card['options']), 2)                                          # options
        self.assertIn(card['recommendation'], [o['id'] for o in card['options']])                 # recommendation
        parameters = card['action']['parameters']
        self.assertEqual(parameters['affected'], ['A', 'I'])                                      # scope
        self.assertIn('A, I', card['impact'])
        self.assertEqual(parameters['reason_class'], 'U2')

    def test_e5_after_continue_the_request_is_closed_and_b1_runs_next(self):
        self.hold()
        request = questions.list_for_plan(self.ledger, 'P1', pending=True)[0]
        effect = self.reply(request, 'continue')['controller_effect']
        self.assertEqual(effect['effect'], 'continued_within_grant')
        self.assertEqual(questions.list_for_plan(self.ledger, 'P1', pending=True), [])            # [E5] request closed
        closed = self.ledger.request(request['id'])
        self.assertNotEqual(closed['state'], 'pending')
        self.assertEqual(closed['answer']['choice'], 'continue')
        self.assertIn('request.applied', self.kinds())
        self.assertEqual(self.step()['node'], 'A')                                                # B1's next action matches the answer
        self.assertFalse((self.root / 'outside.txt').exists())


if __name__ == '__main__':
    import unittest
    unittest.main()
