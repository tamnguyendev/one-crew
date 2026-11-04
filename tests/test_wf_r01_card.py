"""T50b (W30a) - one decision-card schema; step 0 shows the owner only the important choices, in exactly one card.

Sample (05 T50): a business choice (keep or delete the old CSV export) plus two technical choices that are inside the granted
authority. The card has the six fields (problem, options, recommendation, evidence, scope, decide_by); the two technical choices are
decided and written as HD-05 decision records (decisions.record, W03), never asked; the same decision never gets a second card.
The same schema renders as a REQ question, a CREQ text and a contract `decisions` entry. Nothing here calls a model.
"""
import contextlib
import io
import json
import os
import unittest
from unittest.mock import patch

from onecrew.ledger import LedgerError
from onecrew.v2 import authority, cards, contract as contracts, plan as plans
from tests.test_v2_l3 import Step0, step0_json

SUBJECT = {'component': 'step0', 'model': 'claude-sonnet-5-5'}
AUTH = {'grant_id': 'G-01', 'revision': 'rev-1'}


def option(oid, label):
    return {'id': oid, 'label': label}


def csv_choice(**extra):
    return dict({'id': 'B1', 'class': 'business', 'problem': 'Keep or delete the old CSV export once the report is removed?',
                 'options': [option('keep', 'Keep the CSV export'), option('delete', 'Delete the CSV export')], 'recommendation': 'keep',
                 'evidence': ['x/y.py:1'], 'scope': 'plan P1: old report removal', 'decide_by': 'before_approve'}, **extra)


def technical(cid, **extra):
    return dict({'id': cid, 'class': 'technical', 'problem': f'Which helper style for {cid}?',
                 'options': [option('a', 'Inline helper'), option('b', 'Shared module')], 'recommendation': 'a',
                 'evidence': ['x/y.py:2'], 'scope': 'plan P1: code style', 'decide_by': 'before_start', 'authority': AUTH}, **extra)


class CardTests(Step0):
    def setUp(self):
        super().setUp()
        # W30a: a technical choice is decided silently only on the APPROVED root's own grant, so the fixture approves a root that
        # declares an authority and the technical choices cite its grant (AUTH, a made-up grant, is replaced by it in present()).
        self.propose('P1', step0_json(size='S', authority={'edit': True}))
        plans.approve(self.ledger, 'P1', 'owner', 'said yes')
        self.task = self.anchor()
        with self.ledger.transaction() as conn:
            state = plans.derive(self.ledger, conn, 'P1')
        contract, _ = plans.load(self.ledger, state, state['approved']['revision'])
        self.grant = authority.grant_ref(state['selector'], contract, state['approved']['sha'])

    def anchor(self):
        with self.ledger.transaction() as conn:
            return plans.derive(self.ledger, conn, 'P1')['task_id']

    def cards_on_plan(self):
        return [r for r in self.ledger.requests(self.task) if r['question']['action']['type'] == cards.KIND]

    def decisions(self):
        return [p for k, p in self.events('P1') if k == 'decision.recorded']

    def present(self, choices, **kw):
        return cards.present(self.ledger, 'P1', self.real(choices), SUBJECT, **kw)

    def real(self, choices):
        return [dict(c, authority=self.grant) if c.get('authority') == AUTH else c for c in choices]

    # [E7] only the business choice is shown, in exactly one card with all six fields; two technical choices are decided and recorded (HD-05)
    def test_e7_one_card_with_six_fields_and_two_technical_choices_recorded(self):
        out = self.present([csv_choice(), technical('T1'), technical('T2', recommendation='b')])
        shown = self.cards_on_plan()
        self.assertEqual(len(shown), 1)                                         # [E11] cards = 1
        card = shown[0]['question']['action']['parameters']['card']
        for field in cards.CARD_FIELDS:
            self.assertTrue(card[field], field)                                 # six fields, none empty
        self.assertEqual([p['id'] for p in card['parts']], ['B1'])              # only the business choice
        card_json = json.dumps([r['question'] for r in shown])                  # the card as shown, not the row timestamps (ISO '...T1x:..' hours)
        self.assertNotIn('T1', card_json); self.assertNotIn('T2', card_json)
        self.assertEqual(out['request']['id'], shown[0]['id'])
        records = self.decisions()
        self.assertEqual(len(records), 2)                                       # HD-05 record per technical choice
        for record in records:
            self.assertEqual(record['subject'], SUBJECT); self.assertEqual(record['authority'], self.grant)
            self.assertTrue(record['evidence']); self.assertNotEqual(record['actor'], 'owner')
        self.assertEqual({d['choice']: d['chosen'] for d in out['decisions']}, {'T1': 'a', 'T2': 'b'})

    # [E11] questions asked for a technical choice = 0, also when only technical choices exist (then there is no card at all)
    def test_e11_no_question_for_a_technical_choice(self):
        out = self.present([technical('T1'), technical('T2')])
        self.assertIsNone(out['card']); self.assertIsNone(out['request'])
        self.assertEqual(len(self.ledger.requests(self.task)), 0); self.assertEqual(len(self.decisions()), 2)

    def test_a_technical_choice_outside_the_authority_is_not_decided_silently(self):
        loose = technical('T3'); del loose['authority']
        out = self.present([csv_choice(), loose])
        self.assertEqual(self.decisions(), []); self.assertEqual(out['escalated'], ['T3'])
        card = self.cards_on_plan()[0]['question']['action']['parameters']['card']
        self.assertEqual([p['id'] for p in card['parts']], ['B1', 'T3']); self.assertEqual(len(self.cards_on_plan()), 1)

    # [E11] the same decision never gets a second card
    def test_e11_the_same_decision_is_never_two_cards(self):
        first = self.present([csv_choice()])
        again = self.present([csv_choice()])
        self.assertEqual(again['request']['id'], first['request']['id']); self.assertEqual(len(self.cards_on_plan()), 1)
        changed = self.present([csv_choice(recommendation='delete')])               # new content, same decision: the card is revised
        self.assertEqual(changed['request']['id'], first['request']['id']); self.assertNotEqual(changed['request']['revision'], first['request']['revision'])
        self.assertEqual(len(self.cards_on_plan()), 1)
        other = csv_choice(id='B2', problem='Also keep the PDF export?')
        with self.assertRaises(LedgerError) as caught: self.present([csv_choice(), other])
        self.assertIn('B1', str(caught.exception)); self.assertEqual(len(self.cards_on_plan()), 1)     # B1 already has its card: no second one

    def test_two_important_choices_are_merged_into_one_card(self):
        other = csv_choice(id='B2', problem='Keep the PDF export?', options=[option('yes', 'Keep'), option('no', 'Drop')], recommendation='no', decide_by='before_start')
        self.present([csv_choice(), other])
        shown = self.cards_on_plan(); self.assertEqual(len(shown), 1)
        card = shown[0]['question']['action']['parameters']['card']
        self.assertEqual([p['id'] for p in card['parts']], ['B1', 'B2'])
        self.assertEqual([o['id'] for o in card['options']], ['B1.keep', 'B1.delete', 'B2.yes', 'B2.no'])
        self.assertEqual(card['recommendation'], ['B1.keep', 'B2.no']); self.assertEqual(card['decide_by'], 'before_start')   # the earliest moment

    # the six fields are required and checked; a refusal writes nothing (no card, no decision)
    def test_every_field_is_required_and_nothing_is_written_on_refusal(self):
        for field, bad in (('problem', ''), ('options', [option('keep', 'one')]), ('recommendation', 'nope'), ('evidence', []),
                           ('scope', ''), ('decide_by', 'someday')):
            choice = csv_choice(); choice[field] = bad
            with self.assertRaises(LedgerError, msg=field): self.present([technical('T1'), choice])
        choice = csv_choice(); del choice['evidence']
        with self.assertRaises(LedgerError): self.present([technical('T1'), choice])
        self.assertEqual(self.ledger.requests(self.task), []); self.assertEqual(self.decisions(), [])

    def test_evidence_must_resolve(self):
        with self.assertRaises(LedgerError) as caught: self.present([csv_choice(evidence=['x/y.py:999'])])
        self.assertIn('evidence', str(caught.exception)); self.assertEqual(self.ledger.requests(self.task), [])

    def test_an_owner_actor_cannot_be_recorded_by_an_ai_session(self):
        with patch.dict(os.environ, {'CLAUDE_CODE_CHILD_SESSION': '1', 'ONECREW_ACTOR': 'owner'}):
            self.present([technical('T1')])
        self.assertNotEqual(self.decisions()[0]['actor'], 'owner')

    # one schema, three renderings: REQ (ledger question), CREQ (conversation text), contract `decisions` entry
    def test_the_same_schema_renders_as_req_creq_and_a_contract_decision(self):
        card = cards.validate_card(cards.build_card([csv_choice()]), self.ledger)
        question = cards.to_request(card)
        self.assertEqual(question['action']['type'], cards.KIND); self.assertEqual(question['recommendation'], 'keep')
        creq = cards.to_creq(card)
        for needle in (card['problem'], 'Keep the CSV export', card['scope'], card['decide_by'], 'x/y.py:1'): self.assertIn(needle, creq['text'])
        self.assertLessEqual(len(creq['text']), 1500)
        entry = cards.to_decision(card, 'D1', 'keep')
        value = step0_json(size='S'); value['decisions'] = [entry]
        self.assertEqual(contracts.validate(value)['decisions'][0]['id'], 'D1')

    def test_cli_presents_the_card(self):
        path = self.root.parent / 'choices.json'
        path.write_text(json.dumps({'choices': self.real([csv_choice(), technical('T1')])}), encoding='utf-8')
        code, out = self.cli('plan', 'card', 'present', 'P1', '--file', str(path), '--model', 'claude-sonnet-5-5')
        self.assertEqual(code, 0, out)
        body = json.loads(out); self.assertEqual(body['request']['id'], self.cards_on_plan()[0]['id']); self.assertEqual(len(body['decisions']), 1)
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):          # --model is required: an unnamed model is not a subject
            self.cli('plan', 'card', 'present', 'P1', '--file', str(path))


if __name__ == '__main__':
    unittest.main()
