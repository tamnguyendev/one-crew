"""T17c (R05, round 7): see tests/test_wf_r7_t17b.py for the shared fixture and the scenario."""
import datetime as dt
import json
import os
from unittest.mock import patch

from onecrew.snapshots import Snapshots
from onecrew.v2 import cards, internal_plan, plan, questions, step0
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

    def test_e4_the_one_hold_card_carries_evidence_scope_and_a_decide_by_deadline_inside_the_root_deadline(self):
        # Round 7 D (GAP 1): the card of the U2 hold carries all six HD-08 card fields (cards.CARD_FIELDS), its evidence resolves to
        # what produced the hold, and its decide-by moment is a deadline that is never later than the root's sealed deadline.
        self.hold()
        self.engine.request_action(self.ledger, 'P1', 'A', dict(U2_ACTION))                       # asked again: still one card
        [request] = questions.list_for_plan(self.ledger, 'P1')
        parameters = request['question']['action']['parameters']
        self.assertIn('card', parameters, 'the workflow hold request carries no decision card (evidence, scope, decide_by)')
        card = parameters['card']
        self.assertEqual(cards.validate_card(card, self.ledger), card)                           # the one card schema, evidence resolves
        for field in cards.CARD_FIELDS:
            with self.subTest(field=field):
                self.assertTrue(card[field])
        self.assertEqual(card['problem'], request['question']['question'])
        self.assertEqual(card['options'], request['question']['options'])
        self.assertEqual(card['recommendation'], [request['question']['recommendation']])
        self.assertIn('A, I', card['scope'])
        self.assertEqual(card['decide_by'], 'milestone:A')
        # evidence: the hold-evidence blob names the requested action, its HD-05 decision and the node.held events of the hold
        store = Snapshots(self.ledger.state_root)
        for ref in card['evidence']:
            self.assertEqual(step0.evidence_kind(self.ledger, ref), 'blob')
        body = json.loads(store.read_blob(card['evidence'][0]))
        self.assertEqual(body['kind'], 'workflow-hold-evidence')
        self.assertEqual((body['node'], body['reason_class'], body['requested_action']), ('A', 'U2', dict(U2_ACTION, nodes=['A'])))
        self.assertEqual(body['decision']['validity']['outcome'], 'out_of_authority')
        self.assertEqual(body['decision']['validity']['class'], 'U2')
        seqs = self.event_seqs()
        self.assertEqual(sorted(body['hold_events']), ['A', 'I'])
        for target, seq in body['hold_events'].items():
            kind, payload = seqs[seq]
            self.assertEqual((kind, payload['node'], payload['classification']), ('node.held', target, 'U2'))
        # decide-by deadline: derived from the sealed root deadline and never later than it
        deadline = parameters['decide_by_deadline']
        with self.ledger.transaction() as conn:
            root = plan.anchor_events(self.ledger, conn, 'P1')
            ceiling = internal_plan.ceilings(self.ledger, conn, root)
        self.assertEqual(deadline['root_deadline'], ceiling['deadline'])
        self.assertLessEqual(dt.datetime.fromisoformat(deadline['at']), dt.datetime.fromisoformat(ceiling['deadline']))
        self.assertGreaterEqual(deadline['reserved_execution_seconds'], 0)
        self.assertTrue(deadline['basis'])

    def event_seqs(self):
        with self.ledger.transaction() as conn:
            task = plan.show(self.ledger, 'P1')['anchor_task']
            return {row['seq']: (row['kind'], json.loads(row['payload']))
                    for row in conn.execute('SELECT seq, kind, payload FROM events WHERE task_id=?', (task,))}

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
