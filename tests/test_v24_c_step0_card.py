"""2.4-C (T24-C): step 0 short enough to act on, with an investigation stop point (ROADMAP-DESIGN 20261026 §2.1, §2.9, §7 row 2.4-C).

The card is a derived, read-only view of the W47 proposal check (proposal.checked) and the plan's step-0 surveys. Three optional proposal
fields opt into the card rules (preserve, investigation, estimate); a proposal without them is checked exactly as before. Fixtures (sample
proposals, a fake survey worker and clock) prove the rules and the record, not the quality of a real model's proposal.
"""
import copy
import json

from onecrew.ledger import LedgerError
from onecrew.v2 import plan as plans, proposal, step0, survey
from tests.test_v2_l3 import Step0, step0_json
from tests.test_wf_r01_step0_proposal import KEEP, REQUIREMENT, change, sample
from tests.test_wf_r01_step0_survey import Clock
from tests.test_wf_engine import EngineFixture, node

PRESERVE = [{'id': 'K1', 'text': 'The new report and its API stay unchanged'}]
ESTIMATE = {'range': [600, 1800], 'evidence': ['routes.py:1']}
INVESTIGATION = {'cap': {'minutes': 4, 'calls': 4}, 'paths': ['x', 'onecrew'], 'stop_when': 'an answer citing file:line, or the cap'}
BLOCKING = {'id': 'U1', 'question': 'Is the old report data used by another job?', 'affected': ['A2', 'X4'], 'required_by': 'option_choice',
            'status': 'open'}


def card_sample(name='p1', **fields):
    value = sample(name)
    value.update({'preserve': PRESERVE, 'estimate': ESTIMATE}, **fields)
    return value


def codes(result):
    return [code for code, _ in result['reasons']]


class CardFixture(Step0):
    def setUp(self):
        super().setUp()
        for relative in ('routes.py', 'api.py', 'menu.js', 'reports_new.py', 'data/old_report.json'):
            path = self.root / relative; path.parent.mkdir(parents=True, exist_ok=True); path.write_text('x\n')
        self.propose('P1', step0_json(size='S'))

    def check(self, value, **kw):
        return proposal.check(self.ledger, REQUIREMENT, value, **kw)

    def review(self, value):
        return step0.review_proposal(self.ledger, 'P1', REQUIREMENT, value)

    def show(self):
        return step0.show_card(self.ledger, 'P1')

    def without(self, rule):
        return tuple(r for r in proposal.RULES if r is not rule)


class EnoughToAct(CardFixture):
    def test_a_clear_small_in_grant_request_is_enough_with_no_options_no_request_and_one_approval(self):
        before = len(self.ledger.requests())
        out = self.review(card_sample())
        self.assertTrue(out['ok'], out['reasons']); self.assertEqual(out['owner_requests'], 0)
        view = out['card']
        self.assertTrue(view['enough'], view['not_enough'])
        self.assertEqual((view['before'], view['after'], view['preferred']), (sample('p1')['preferred']['before'], sample('p1')['preferred']['after'], 'P1'))
        self.assertTrue(view['why'] and view['summary'])
        self.assertEqual(view['preserve'], PRESERVE); self.assertEqual([a['id'] for a in view['acceptance']], ['A1', 'A2'])
        self.assertEqual(view['estimate'], {'range': [600, 1800], 'evidence': ['routes.py:1'], 'source': 'proposal'})
        self.assertEqual(view['unknowns_open'], [])
        self.assertEqual(len(self.ledger.requests()), before)                       # no question to the owner
        event = [p for k, p in self.events('P1') if k == 'proposal.checked'][-1]
        self.assertEqual(event['card_sha'], out['card_sha']); self.assertTrue(event['card']['enough'])
        self.assertEqual(plans.approve(self.ledger, 'P1', 'owner', 'said yes')['status'], 'approved')   # the one existing approval
        self.assertEqual(self.kinds('P1').count('plan.approved'), 1)
        baseline = [p for k, p in self.events('P1') if k == 'estimate.baseline'][-1]
        self.assertIsNone(baseline['execution_seconds']); self.assertEqual(baseline['source'], 'not_supplied')   # the card range is no budget

    def test_without_the_card_fields_the_check_and_its_record_are_unchanged(self):
        out = self.review(sample('p1'))
        self.assertTrue(out['ok']); self.assertNotIn('card_fields', out); self.assertNotIn('card', out)
        event = [p for k, p in self.events('P1') if k == 'proposal.checked'][-1]
        self.assertFalse({'card', 'card_sha', 'card_fields'} & set(event))
        for name in ('p2', 'p3', 'p4', 'p6'):
            self.assertEqual(codes(self.check(sample(name))), codes(self.check(sample(name), rules=proposal.RULES[:8])))
        view = self.show()
        self.assertEqual(view['estimate']['status'], step0.NOT_ENOUGH_DATA)          # never an invented range


class TooLittleStaysRefused(CardFixture):
    # the W47 counterexamples hold with the card fields: hiding a menu does not forbid access; a hide flag is not a deletion
    def test_hide_menu_versus_forbid_access_and_hide_flag_versus_delete(self):
        for name, code in (('p2', 'destructive_semantics'), ('p3', 'not_permanent')):
            out = self.review(card_sample(name))
            self.assertFalse(out['ok']); self.assertIn(code, codes(out))
            self.assertFalse(out['card']['enough']); self.assertIn(code, out['card']['not_enough'])
            with self.assertRaises(LedgerError) as caught: plans.approve(self.ledger, 'P1', 'owner', 'said yes')
            self.assertIn('proposal_refused', str(caught.exception))


class Preserve(CardFixture):
    def test_a_modify_or_delete_without_what_stays_unchanged_is_refused(self):
        bare = card_sample(); del bare['preserve']
        self.assertEqual(codes(self.check(bare)), ['preserve_missing'])
        self.assertTrue(self.check(bare, rules=self.without(proposal.rule_preserve))['ok'])      # counter-proof
        only_new = card_sample(); only_new['preferred']['changes'] = [change('X9', 'hide', ['menu'], ['K1'], 'menu.js')]
        del only_new['preserve']
        self.assertNotIn('preserve_missing', codes(self.check(only_new)))                       # a hide alone changes nothing kept
        self.assertTrue(self.check(card_sample())['ok'])


class Estimate(CardFixture):
    def test_no_estimate_is_said_as_not_enough_data_never_a_range(self):
        bare = card_sample(); del bare['estimate']
        self.assertEqual(codes(self.check(bare)), ['estimate_missing'])
        self.assertTrue(self.check(bare, rules=self.without(proposal.rule_estimate))['ok'])      # counter-proof
        stated = card_sample(estimate={'status': 'not_enough_data', 'missing': 'no earlier export removal was timed'})
        out = self.review(stated)
        self.assertTrue(out['ok'], out['reasons'])
        self.assertEqual(out['card']['estimate'], {'status': step0.NOT_ENOUGH_DATA, 'missing': 'no earlier export removal was timed'})
        self.assertNotIn('range', out['card']['estimate'])

    def test_zero_a_bare_number_or_an_unsourced_range_is_refused(self):
        for value, code in ((0, 'estimate_unsourced'), (900, 'estimate_unsourced'), ({'range': [0, 60], 'evidence': ['routes.py:1']}, 'estimate_zero'),
                            ({'range': [60, 120], 'evidence': []}, 'estimate_unsourced'), ({'range': [60, 120], 'evidence': ['trust me']}, 'estimate_unsourced'),
                            ({'range': [120, 60], 'evidence': ['routes.py:1']}, 'estimate_unsourced'),
                            ({'status': 'not_enough_data'}, 'estimate_unsourced')):
            self.assertEqual(codes(self.check(card_sample(estimate=value))), [code], value)
        waiting = card_sample(unknowns=[dict(BLOCKING, id='U2', required_by='estimate')])
        self.assertIn('estimate_unsourced', codes(self.check(waiting)))                         # the estimate waits for an open unknown


class Investigation(CardFixture):
    def test_the_whole_project_is_not_an_investigation_scope(self):
        whole = card_sample(investigation=dict(INVESTIGATION, paths=['.']))
        self.assertEqual(codes(self.check(whole)), ['investigation_unscoped'])
        self.assertTrue(self.check(whole, rules=self.without(proposal.rule_investigation))['ok'])   # counter-proof
        self.assertTrue(self.check(card_sample(investigation=INVESTIGATION))['ok'])
        self.assertEqual(codes(self.check(card_sample(investigation=INVESTIGATION), spent={'seconds': 300, 'calls': 1})), ['investigation_over_cap'])
        blocked_without = card_sample(unknowns=[BLOCKING]); blocked_without['preferred'] = None
        self.assertIn('investigation_missing', codes(self.check(blocked_without)))

    def test_surveys_read_only_the_investigation_paths_and_stop_at_its_cap(self):
        value = card_sample(unknowns=[BLOCKING], investigation=INVESTIGATION); value['preferred'] = None
        out = self.review(value)
        self.assertEqual(out['result'], 'survey_first')
        opened = survey.show(self.ledger, 'P1')['surveys']
        self.assertEqual(len(opened), 1)
        self.assertEqual(opened[0]['scope'], {'mode': 'read_only', 'paths': ['x', 'onecrew']})
        self.assertEqual(opened[0]['cap'], {'minutes': 4, 'calls': 4})                          # the default cap shrunk to the room left
        clock = Clock()
        def slow(context):
            clock.advance(4 * 60 + 1); context.read('x/y.py')
        finished = survey.run(self.ledger, 'P1', opened[0]['id'], slow, clock=clock)
        self.assertEqual(finished['status'], 'blocked'); self.assertEqual(finished['blocker']['reason'], 'cap_reached')
        again = self.review(value)                                                             # the investigation stops: no second survey
        self.assertIn('investigation_cap_spent', codes(again)); self.assertEqual(len(survey.show(self.ledger, 'P1')['surveys']), 1)
        view = self.show()
        self.assertFalse(view['enough'])
        self.assertEqual([u['id'] for u in view['unknowns_open']], ['U1'])                     # still open, never closed by default
        self.assertIn(view['investigation']['stopped_because'], ('survey_blocked', 'cap_spent'))
        self.assertEqual(view['investigation']['spent'], {'seconds': 240, 'calls': 0})
        self.assertLessEqual(view['investigation']['spent']['seconds'], INVESTIGATION['cap']['minutes'] * 60)
        with self.assertRaises(LedgerError) as refused: plans.approve(self.ledger, 'P1', 'owner', 'said yes')
        self.assertIn('proposal_refused', str(refused.exception))

    def test_an_explicit_survey_over_the_room_left_is_refused_and_nothing_is_written(self):
        self.review(card_sample(investigation=dict(INVESTIGATION, cap={'minutes': 3, 'calls': 3})))
        kinds = len(self.kinds('P1'))
        with self.ledger.transaction(write=True) as conn:
            state = plans.anchor_events(self.ledger, conn, 'P1')
            with self.assertRaises(survey.InvestigationCapReached):
                survey.open_in(self.ledger, conn, state, BLOCKING, {'cap': {'minutes': 5, 'calls': 1}})
            with self.assertRaisesRegex(LedgerError, 'inside the investigation paths'):       # a question cannot widen the read scope
                survey.open_in(self.ledger, conn, state, BLOCKING, {'cap': {'minutes': 1, 'calls': 1},
                                                                    'scope': {'mode': 'read_only', 'paths': ['routes.py']}})
        self.assertEqual(len(self.kinds('P1')), kinds)


class UnknownScope(CardFixture):
    def test_an_unrelated_unknown_does_not_widen_scope_or_hold_the_choice(self):
        unrelated = {'id': 'U7', 'question': 'Should the new report also get a CSV export?', 'affected': ['K1'], 'required_by': 'milestone:M9', 'status': 'open'}
        out = self.review(card_sample(unknowns=[unrelated]))
        self.assertTrue(out['ok'], out['reasons']); self.assertEqual(out['survey_required'], [])
        self.assertEqual(out['card']['unknowns_open'], [])                                      # not a decision-changing unknown
        self.assertEqual(survey.show(self.ledger, 'P1')['surveys'], [])
        bare = card_sample(unknowns=[{'id': 'U8', 'question': 'Anything else?', 'status': 'open'}])
        self.assertIn('unknown_unscoped', codes(self.check(bare)))

    def test_an_open_unknown_the_approval_waits_for_holds_it(self):
        waiting = card_sample(unknowns=[dict(BLOCKING, id='U3', required_by='approval')])
        out = self.review(waiting)
        self.assertEqual(codes(out), ['unknown_open'])
        self.assertTrue(self.check(waiting, rules=self.without(proposal.rule_open_for_approval))['ok'])   # counter-proof
        self.assertEqual([u['id'] for u in out['card']['unknowns_open']], ['U3'])
        with self.assertRaises(LedgerError): plans.approve(self.ledger, 'P1', 'owner', 'said yes')


class Cli(CardFixture):
    def test_plan_step0_show_is_read_only_text_and_json(self):
        self.review(card_sample())
        before = self.kinds('P1')
        code, text = self.cli('plan', 'step0', 'show', 'P1')
        self.assertEqual(code, 0, text)
        for needle in ('BƯỚC 0 P1', 'đủ để làm: có', 'Giữ nguyên: K1', 'Ước lượng: 600–1800 giây', 'Nghiệm thu: A1'):
            self.assertIn(needle, text)
        code, raw = self.cli('plan', 'step0', 'show', 'P1', '--json')
        self.assertEqual(code, 0, raw); self.assertTrue(json.loads(raw)['enough'])
        self.assertEqual(self.kinds('P1'), before)                                              # nothing written


class RuntimeUnknownHold(EngineFixture):
    """An open high-risk unknown found after approval holds the nodes that need it (required_by), and only them."""
    def test_open_unknown_holds_its_dependent_node_only(self):
        from onecrew.v2 import engine, runtime_unknowns
        fixture = self
        fixture.revise([node('C'), node('D', write=('b.txt',)), node('I', ['C', 'D'], integration=True, write=())])
        runtime_unknowns.open_unknown(fixture.ledger, 'P1', 'risk', question='Does C break the export contract?', affected=['C', 'I'],
                                      required_by=['C'], resolver='doc', evidence=['a.txt:1'])
        self.assertEqual([c['id'] for c in engine.ready(fixture.ledger, 'P1')], ['D'])
        self.assertEqual(fixture.step()['node'], 'D')
        self.assertNotIn('C', [p['node'] for k, p in fixture.events() if k == 'node.started'])


if __name__ == '__main__':
    import unittest
    unittest.main()
