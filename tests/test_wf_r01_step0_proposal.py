"""T50a (W47) - a just-enough proposal at step 0: not too little, not too much. No model is called.

Sample request (05 T50): "remove the old report export". A1 no user can export the old report by any path (menu, URL, API); A2 the old
report data is permanently deleted; constraint K1 keep the new report. The temp repo has the menu entry, the URL route and the API handler.
Six sample proposals (fixtures, not model output) prove the CHECK, not the quality of a real model's proposal:
  p1 enough and least impact  p2 too little: menu hidden, URL/API still work  p3 too little: a hide flag instead of deleting the data
  p4 too much: a rewrite tied to nothing  p5 enough, but three options and a mockup for something already clear  p6 no kind/entry declared.
Each rule has a counter-proof: with that rule removed, the sample it should catch goes through (so the test would be red without it).
"""
import copy
import json
import os
import unittest
from unittest.mock import patch

from onecrew.ledger import LedgerError
from onecrew.v2 import compat, plan as plans, proposal, step0
from tests.test_v2_l3 import Step0, step0_json

REQUIREMENT = {
    'acceptance': [
        {'id': 'A1', 'text': 'No user can export the old report by any path (menu, URL, API)', 'semantic': {'unreachable_via': ['menu', 'url', 'api']}},
        {'id': 'A2', 'text': 'The old report data is deleted permanently', 'semantic': {'removal': 'permanent'}}],
    'constraints': [{'id': 'K1', 'text': 'Keep the new report'}],
    'dependencies': []}


def change(cid, kind, entries, links, target, **extra):
    return dict({'id': cid, 'title': f'{kind} {target}', 'kind': kind, 'entries': entries, 'links': links, 'target': target}, **extra)


ROUTE = change('X1', 'delete', ['url'], ['A1'], 'routes.py')
HANDLER = change('X2', 'delete', ['api'], ['A1'], 'api.py')
MENU = change('X3', 'delete', ['menu'], ['A1'], 'menu.js')
DATA = change('X4', 'delete', ['storage'], ['A2'], 'data/old_report.json')
KEEP = change('X5', 'modify', ['api'], ['K1'], 'reports_new.py')


def preferred(*changes, **extra):
    return dict({'id': 'P1', 'summary': 'Remove the old report route, handler, menu entry and data; leave the new report alone',
                 'before': 'The old report can be exported from the menu, by URL and by API; its data is stored.',
                 'after': 'No path exports the old report; its data is gone; the new report is unchanged.',
                 'rationale': 'Deleting the three entries and the data meets A1 and A2 and touches nothing else; a rewrite would add risk for no acceptance.',
                 'changes': copy.deepcopy(list(changes))}, **extra)


def sample(name):
    base = {'preferred': preferred(ROUTE, HANDLER, MENU, DATA, KEEP), 'covers': ['A1', 'A2'], 'in_authority': True,
            'backlog': [{'id': 'B1', 'title': 'Rename a variable in the report module (optional improvement)'}]}
    if name == 'p1':
        base['preferred']['changes'].append(change('X6', 'modify', ['api'], [], 'reports_new.py', optional=True, title='Rename a variable'))
        return base
    if name == 'p2': base['preferred'] = preferred(change('X3', 'hide', ['menu'], ['A1', 'A2'], 'menu.js'), KEEP)
    elif name == 'p3': base['preferred'] = preferred(ROUTE, HANDLER, MENU, change('X4', 'hide', ['storage'], ['A2'], 'data/old_report.json'), KEEP)
    elif name == 'p4': base['preferred'] = preferred(ROUTE, HANDLER, MENU, DATA, KEEP, change('X7', 'modify', ['api'], [], 'reports_new.py', title='Rewrite the report module'))
    elif name == 'p5':
        base['alternatives'] = [{'id': 'P2', 'summary': 'Soft remove'}, {'id': 'P3', 'summary': 'Archive then remove'}]
        base['mockups'] = [{'id': 'M1', 'title': 'Screen without the export button'}]
    elif name == 'p6':
        base['preferred'] = preferred(*[{k: v for k, v in c.items() if k not in ('kind', 'entries')} for c in (ROUTE, HANDLER, MENU, DATA, KEEP)])
    return base


def codes(result):
    return [code for code, _ in result['reasons']]


class ProposalCheckTests(Step0):
    def setUp(self):
        super().setUp()
        for relative in ('routes.py', 'api.py', 'menu.js', 'reports_new.py', 'data/old_report.json'):
            path = self.root / relative; path.parent.mkdir(parents=True, exist_ok=True); path.write_text('x\n')
        self.propose('P1', step0_json(size='S'))

    def check(self, name_or_value, **kw):
        value = sample(name_or_value) if isinstance(name_or_value, str) else name_or_value
        return proposal.check(self.ledger, REQUIREMENT, value, **kw)

    # [E1] p1 passes: one preferred option, before/after, the reason it is the least that is enough, every change tied to A1/A2/K1,
    # the optional improvement in the backlog and not in the plan
    def test_e1_p1_passes_with_a_table_and_the_optional_in_the_backlog(self):
        result = self.check('p1')
        self.assertTrue(result['ok'], result['reasons'])
        self.assertEqual([r['change'] for r in result['table']], ['X1', 'X2', 'X3', 'X4', 'X5'])
        for row in result['table']: self.assertTrue(set(row['links']) <= {'A1', 'A2', 'K1'} and row['links'], row)
        self.assertIn('B1', [b['id'] for b in result['backlog']]); self.assertIn('X6', [b['id'] for b in result['backlog']])
        self.assertNotIn('X6', [r['change'] for r in result['table']])
        self.assertEqual(result['preferred'], 'P1'); self.assertTrue(result['before'] and result['after'] and result['rationale'])

    # [E2] p2: hiding the menu does not meet A1 while the URL and the API still work
    def test_e2_p2_hidden_menu_is_not_enough(self):
        result = self.check('p2')
        self.assertFalse(result['ok']); self.assertIn('destructive_semantics', codes(result))
        text = ' '.join(t for c, t in result['reasons'] if c == 'destructive_semantics')
        for needle in ('A1', 'api, url still work'): self.assertIn(needle, text)      # the menu is the one path the hide did close; url and api are open

    # [E3] [E10] p3: a hide flag on the data is not a permanent deletion
    def test_e3_p3_a_hide_flag_is_not_a_permanent_deletion(self):
        result = self.check('p3')
        self.assertFalse(result['ok']); self.assertIn('not_permanent', codes(result))
        text = ' '.join(t for c, t in result['reasons'] if c == 'not_permanent')
        self.assertIn('A2', text); self.assertIn('hide is not permanent deletion', text)

    # [E4] [E9] p4: a change tied to no acceptance, constraint or dependency is caught, named, and is not in the plan
    def test_e4_p4_a_change_tied_to_nothing_is_caught_and_named(self):
        result = self.check('p4')
        self.assertFalse(result['ok']); self.assertEqual(codes(result), ['change_not_linked'])
        self.assertIn('X7', result['reasons'][0][1]); self.assertIn('Rewrite the report module', result['reasons'][0][1])

    # [E5] p5: clear and inside the authority - done, no demand for three options or a mockup, and no new request to the owner
    def test_e5_p5_clear_work_in_authority_needs_no_options_and_asks_nothing(self):
        before = len(self.ledger.requests())
        out = step0.review_proposal(self.ledger, 'P1', REQUIREMENT, sample('p5'))
        self.assertTrue(out['ok'], out['reasons']); self.assertEqual(out['extras'], {'alternatives': 2, 'mockups': 1})
        self.assertEqual(out['owner_requests'], 0); self.assertEqual(len(self.ledger.requests()), before)
        bare = sample('p5'); del bare['alternatives']; del bare['mockups']
        self.assertTrue(self.check(bare)['ok'])                  # and it is not asked for either

    # [E13] p6: kind and entry not declared -> refused with that reason; the semantic rule is NOT applied by guessing from text
    def test_e13_p6_missing_declaration_is_refused(self):
        result = self.check('p6')
        self.assertFalse(result['ok']); self.assertEqual(codes(result), ['missing_declaration'])
        self.assertIn('missing declaration of change kind and entry path', result['reasons'][0][1])
        self.assertIn('thiếu khai báo loại thay đổi và đường vào', result['reasons'][0][1])

    # [E8] a proposal that drops an acceptance but says it is enough: refused
    def test_e8_dropping_or_loosening_an_acceptance_is_refused(self):
        dropped = sample('p1'); dropped['preferred']['changes'] = [c for c in dropped['preferred']['changes'] if c['id'] != 'X4']
        result = self.check(dropped)
        self.assertFalse(result['ok']); self.assertIn('acceptance_dropped', codes(result)); self.assertIn('A2', result['reasons'][0][1])
        narrow = sample('p1'); narrow['covers'] = ['A1']
        self.assertIn('acceptance_dropped', codes(self.check(narrow)))
        loosened = sample('p1'); loosened['acceptance'] = [dict(REQUIREMENT['acceptance'][0], semantic={'unreachable_via': ['menu']}), REQUIREMENT['acceptance'][1]]
        self.assertIn('acceptance_changed', codes(self.check(loosened)))
        self.assertTrue(self.check(dict(sample('p1'), acceptance=REQUIREMENT['acceptance']))['ok'])      # the same restated acceptance is fine

    def test_a_change_must_point_at_a_real_target_and_the_preferred_needs_a_reason(self):
        ghost = sample('p1'); ghost['preferred']['changes'][0] = change('X1', 'delete', ['url'], ['A1'], 'nowhere.py')
        self.assertIn('target_missing', codes(self.check(ghost)))
        mute = sample('p1'); mute['preferred']['rationale'] = 'short'
        self.assertIn('missing_rationale', codes(self.check(mute)))
        for field in ('before', 'after'):
            blank = sample('p1'); blank['preferred'][field] = ''
            with self.assertRaises(LedgerError): self.check(blank)
        crowd = sample('p1'); crowd['preferred'] = [crowd['preferred'], dict(crowd['preferred'], id='P2')]
        with self.assertRaises(LedgerError) as caught: self.check(crowd)             # one preferred option, not a list
        self.assertIn('one', str(caught.exception))
        unlinked = sample('p1'); unlinked['preferred']['changes'][0]['links'] = ['A9']
        self.assertIn('unknown_link', codes(self.check(unlinked)))

    # every rule has a counter-proof: without it the sample goes through, so these tests are red if the rule is missing
    def test_counter_proofs_the_samples_pass_when_their_rule_is_removed(self):
        for sample_name, rule in (('p2', proposal.rule_semantics), ('p3', proposal.rule_semantics), ('p4', proposal.rule_linkage), ('p6', proposal.rule_declaration)):
            without = tuple(r for r in proposal.RULES if r is not rule)
            self.assertTrue(self.check(sample_name, rules=without)['ok'], f'{sample_name} must pass once {rule.__name__} is removed')
        dropped = sample('p1'); dropped['preferred']['changes'] = [c for c in dropped['preferred']['changes'] if c['id'] != 'X4']
        self.assertTrue(self.check(dropped, rules=tuple(r for r in proposal.RULES if r is not proposal.rule_acceptance and r is not proposal.rule_semantics))['ok'])
        # p3 with "hide counts as delete" (the counter-proof of E10): the flag passes as a deletion
        with patch.dict(proposal.CLOSES, {'hide': lambda entries: set(entries)}), patch.object(proposal, 'DELETES', ('delete', 'hide')):
            self.assertTrue(self.check('p3')['ok'])

    # [E6] the second request: an unknown that blocks the choice is written with affected + required_by, and the choice waits for a survey
    def test_e6_a_blocking_unknown_is_scoped_and_blocks_the_choice(self):
        second = {'unknowns': [{'id': 'U1', 'question': 'Is the old report data used by another job?', 'affected': ['A2', 'X4'],
                                'required_by': 'option_choice', 'status': 'open'}]}
        out = step0.review_proposal(self.ledger, 'P1', REQUIREMENT, second)
        self.assertFalse(out['ok']); self.assertEqual(out['result'], 'survey_first'); self.assertEqual(out['survey_required'], ['U1'])
        event = [p for k, p in self.events('P1') if k == 'proposal.checked'][-1]
        self.assertEqual(event['unknowns'][0]['affected'], ['A2', 'X4']); self.assertEqual(event['unknowns'][0]['required_by'], 'option_choice')
        self.assertNotIn('ok', [p['result'] for k, p in self.events('P1') if k == 'proposal.checked'])
        bare = {'unknowns': [{'id': 'U1', 'question': 'Is it used elsewhere?', 'status': 'open'}]}
        result = self.check(bare)
        self.assertIn('unknown_unscoped', codes(result))
        self.assertIn('affected', result['reasons'][0][1]); self.assertIn('required_by', result['reasons'][0][1])

    # [E12] the check calls no model and starts no process
    def test_e12_no_model_call(self):
        calls = []
        with patch('subprocess.Popen', side_effect=lambda *a, **k: calls.append(a)), patch('subprocess.run', side_effect=lambda *a, **k: calls.append(a)):
            for name in ('p1', 'p2', 'p3', 'p4', 'p5', 'p6'): self.check(name)
        self.assertEqual(calls, [])
        with open(proposal.__file__, encoding='utf-8') as stream: source = stream.read()
        for forbidden in ('claude_cli', 'advisor', 'subprocess', 'urllib'): self.assertNotIn(forbidden, source)

    # the result is written to the ledger (class A), and a refused proposal blocks approval until a check passes
    def test_the_check_is_recorded_as_a_neutral_event_and_gates_approval(self):
        self.assertEqual(compat.event_class('proposal.checked'), 'A')
        step0.review_proposal(self.ledger, 'P1', REQUIREMENT, sample('p2'))
        with self.assertRaises(LedgerError) as caught: plans.approve(self.ledger, 'P1', 'owner', 'said yes')
        self.assertIn('proposal_refused', str(caught.exception)); self.assertNotIn('plan.approved', self.kinds('P1'))
        step0.review_proposal(self.ledger, 'P1', REQUIREMENT, sample('p1'))
        self.assertEqual(plans.approve(self.ledger, 'P1', 'owner', 'said yes')['status'], 'approved')
        results = [p['result'] for k, p in self.events('P1') if k == 'proposal.checked']
        self.assertEqual(results, ['refused', 'ok'])

    def test_a_plan_with_no_proposal_check_is_not_held_by_it(self):
        self.assertEqual(plans.approve(self.ledger, 'P1', 'owner', 'said yes')['status'], 'approved')

    def test_cli_checks_a_proposal(self):
        path = self.root.parent / 'p.json'
        path.write_text(json.dumps({'requirement': REQUIREMENT, 'proposal': sample('p1')}), encoding='utf-8')
        code, out = self.cli('plan', 'proposal', 'check', 'P1', '--file', str(path))
        self.assertEqual(code, 0, out); self.assertTrue(json.loads(out)['ok'])
        path.write_text(json.dumps({'requirement': REQUIREMENT, 'proposal': sample('p2')}), encoding='utf-8')
        code, out = self.cli('plan', 'proposal', 'check', 'P1', '--file', str(path))
        self.assertEqual(code, 2); self.assertIn('destructive_semantics', out)


if __name__ == '__main__':
    unittest.main()
