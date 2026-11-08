"""RD-A2 access points: the step-0 card/advice view and the `review advise` verb. Fake provider only."""
import contextlib
import io
import json
import os
import unittest

from onecrew.v2 import cli, review_advice, step0
from tests.test_review_rda2_lifecycle import AdviceRoot, KEY, Provider


def run(argv, **kwargs):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = review_advice.main(argv, **kwargs) if kwargs else cli.main(argv)
    return code, json.loads(out.getvalue())


class Surface(AdviceRoot):
    def base(self):
        return ['--project', str(self.root), '--state-root', str(self.ledger.state_root)]

    def test_step0_advice_is_recorded_and_shown_on_the_card_without_changing_the_card_rules(self):
        before = step0.show_card(self.ledger, 'P1')
        self.assertNotIn('advice', before)                               # no advice asked: the card is exactly as before
        provider = Provider()
        advice = step0.advise_checks(self.ledger, 'P1', key=KEY, opener=provider)
        self.assertEqual((advice['status'], advice['stage'], provider.calls), ('proposal', 'step0', 1))
        card = step0.show_card(self.ledger, 'P1')
        self.assertEqual(card['advice']['status'], 'proposal')
        self.assertTrue(card['advice']['current'])
        for field in ('enough', 'not_enough', 'result', 'in_authority'):
            self.assertEqual(card[field], before[field])                 # advice never changes what step 0 says is enough
        self.assertIn('Gợi ý cách kiểm', step0.render_card(card))

    def test_card_marks_old_advice_after_the_contract_changes(self):
        step0.advise_checks(self.ledger, 'P1', key=KEY, opener=Provider())
        self.amend_root()
        card = step0.show_card(self.ledger, 'P1')
        self.assertFalse(card['advice']['current'])
        self.assertIn('contract', card['advice']['stale_because'])
        self.assertIn('đã cũ', step0.render_card(card))

    def test_review_advise_show_goes_through_the_router_and_is_read_only(self):
        self.advise()
        before = len(self.advice_events())
        code, shown = run(self.base() + ['review', 'advise', 'show', '--plan', 'P1'])
        self.assertEqual(code, 0)
        self.assertEqual([r['status'] for r in shown['records']], ['proposal'])
        self.assertFalse(shown['records'][0]['grants_authority'])
        self.assertEqual(len(self.advice_events()), before)

    def test_review_advise_request_step0_spends_one_call_and_a_repeat_none(self):
        provider = Provider()
        argv = self.base() + ['review', 'advise', 'request', '--plan', 'P1', '--stage', 'step0']
        code, first = run(argv, opener=provider, key=KEY)
        self.assertEqual((code, first['status'], provider.calls), (0, 'proposal', 1))
        code, again = run(argv, opener=provider, key=KEY)
        self.assertEqual((code, again['cache'], provider.calls), (0, 'hit', 1))

    def test_review_stage_needs_the_facts_and_refuses_politely(self):
        code, out = run(self.base() + ['review', 'advise', 'request', '--plan', 'P1', '--stage', 'review'], opener=Provider(), key=KEY)
        self.assertEqual(code, 2)
        self.assertIn('--facts-file', out['error'])

    def test_review_advise_request_for_review_stage_reads_facts_file(self):
        facts = self.root.parent / 'facts.json'
        facts.write_text(json.dumps(self.facts), encoding='utf-8')
        provider = Provider()
        code, out = run(self.base() + ['review', 'advise', 'request', '--plan', 'P1', '--stage', 'review', '--node', 'C',
                                       '--review-id', 'extra', '--facts-file', str(facts)], opener=provider, key=KEY)
        self.assertEqual((code, out['status'], out['effective_action'], provider.calls), (0, 'proposal', 'REVIEW', 1))

    def test_review_is_a_known_group_and_not_an_owner_verb(self):
        self.assertIn('review', cli.GROUPS)
        from onecrew.v2 import ownership
        self.assertIsNone(ownership.refuse_argv(['review', 'advise', 'request', '--plan', 'P1', '--stage', 'step0']))


if __name__ == '__main__':
    unittest.main()
