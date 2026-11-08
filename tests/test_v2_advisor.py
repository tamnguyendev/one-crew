"""OneCrew v2.1 (job 9): origin + decisions + item sources in the contract, the approve gate that asks for them, the advisor (the model call is
replaced by a stub: no test spends a call) and the owner-rules file."""
import contextlib
import io
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from onecrew.ledger import LedgerError
from onecrew.snapshots import Snapshots
from onecrew.v2 import contract as contracts, plan as plans, plan_cli
from onecrew.v2.verifiers import advisor
from test_v2_l1 import Fixture, plan_json
from test_v2_l2 import HookFixture
from test_v2_l3 import option, reasons, step0_json

ORIGIN = {'by': 'owner', 'at': '2026-10-19', 'quote': 'Add the sample file and prove it works.'}
DECISION = {'id': 'D1', 'choice': 'Plain text file', 'alternative': 'JSON file', 'cost': 'None'}
AUTHOR = 'claude-fable-5-1'


def sourced(value, source='origin', **extra):
    """`value` with an origin and every item pointing at `source` (plus any extra fields)."""
    value = dict(value, origin=dict(ORIGIN), **extra)
    value['items'] = [dict(i, source=source) for i in value['items']]
    return value


def size_m():
    """A size M contract that passes the rest of step 0 (options whose evidence is a real file)."""
    return step0_json(size='M', opts={'recommended': 'A', 'reason': 'cheapest', 'items': [option('A', evidence=('a.txt:1',)), option('B', evidence=('a.txt:1',))]})


def answers(*verdicts, note='fine'):
    return json.dumps({'answers': [{'id': f'Q{n}', 'verdict': v, 'note': note} for n, v in enumerate(verdicts or ('ok', 'ok', 'ok'), 1)]})


def check_reasons(test, value, **kw):
    with test.assertRaises(LedgerError) as caught:
        plans.approve(test.ledger, 'P1', 'owner', 'said yes', **kw)
    return reasons(caught.exception)


class ValidationTests(Fixture):
    def test_a_contract_without_the_new_fields_validates_unchanged(self):
        value = contracts.validate(plan_json())
        self.assertFalse({'origin', 'decisions', 'presentation'} & set(value))
        self.assertTrue(all('source' not in i for i in value['items']))

    def test_the_new_fields_are_accepted_and_kept(self):
        value = sourced(plan_json(), decisions=[DECISION], presentation={
            'request': 'Add it', 'user_sees': ['a file'], 'acceptance_steps': ['open it'], 'not_doing': 'nothing else', 'risk': ['none'], 'guard': 'test'})
        value['items'][1]['source'] = 'D1'
        out = contracts.validate(value)
        self.assertEqual(out['origin'], ORIGIN)
        self.assertEqual(out['decisions'], [DECISION])
        self.assertEqual([i['source'] for i in out['items']], ['origin', 'D1', 'origin'])
        self.assertEqual(out['presentation']['user_sees'], ['a file'])
        self.assertEqual(contracts.validate(sourced(plan_json(), decisions=[]))['decisions'], [])      # 0 decisions is allowed

    def test_origin_is_typed(self):
        for bad in ({'by': 'owner', 'at': 'x'}, dict(ORIGIN, quote='q' * 501), dict(ORIGIN, extra=1), dict(ORIGIN, by=''), 'text', dict(ORIGIN, quote=3)):
            with self.subTest(bad=bad), self.assertRaises(LedgerError): contracts.validate(dict(plan_json(), origin=bad))

    def test_decisions_are_typed(self):
        many = [dict(DECISION, id=f'D{n}') for n in range(1, 12)]
        self.assertEqual(len(contracts.validate(dict(plan_json(), decisions=many[:10]))['decisions']), 10)
        for bad in (many, [DECISION, DECISION], [dict(DECISION, id='X1')], [dict(DECISION, cost='')], [{'id': 'D1', 'choice': 'a'}], 'D1',
                    [dict(DECISION, extra=1)]):
            with self.subTest(bad=bad), self.assertRaises(LedgerError): contracts.validate(dict(plan_json(), decisions=bad))

    def test_item_source_is_origin_or_a_decision_id(self):
        for bad in ('owner', 'd1', '', 3, 'D'):
            value = plan_json(); value['items'][0]['source'] = bad
            with self.subTest(bad=bad), self.assertRaises(LedgerError): contracts.validate(value)

    def test_presentation_is_typed(self):
        for bad in ({'unknown': 'x'}, {'user_sees': 'not a list'}, {'risk': [3]}, {'request': ''}, {'user_sees': ['x'] * 11}, 'text'):
            with self.subTest(bad=bad), self.assertRaises(LedgerError): contracts.validate(dict(plan_json(), presentation=bad))
        self.assertEqual(contracts.validate(dict(plan_json(), presentation={}))['presentation'], {})

    def test_unknown_fields_are_still_refused(self):
        with self.assertRaises(LedgerError): contracts.validate(dict(plan_json(), status='approved'))


class ApproveGateTests(Fixture):
    def setUp(self):
        super().setUp()
        # dev11: propose refuses these form reasons first (tests/test_dev11_propose_form.py). This class tests approve's own gate, which still
        # holds for a plan recorded before that check or changed by plan amend, so the plans here are written as before dev11.
        guard = patch('onecrew.v2.plan.refuse_form'); guard.start(); self.addCleanup(guard.stop)

    def advice_event(self, revision=1, usable=True, sha=None):
        with self.ledger.transaction() as conn:
            state = plans.derive(self.ledger, conn, 'P1')
        with self.ledger.transaction(write=True) as conn:
            plans.emit(self.ledger, conn, state['task_id'], 'plan.advised', {
                'plan': 'P1', 'revision': revision, 'sha': sha or state['revisions'][revision]['sha'], 'model': 'claude-opus-5-5', 'independence': 'same_vendor_other_model',
                'answers': [], 'usable': usable, 'problems': [], 'note': None, 'receipt': 'x' * 64})

    def rules(self):
        advisor.init_rules(self.ledger)

    def test_origin_missing(self):
        value = plan_json(); value['items'] = [dict(i, source='origin') for i in value['items']]
        self.propose(value=value)
        self.assertEqual(check_reasons(self, value), ['origin_missing'])         # item sources alone opt the contract in

    def test_item_without_source(self):
        value = sourced(plan_json()); del value['items'][1]['source']
        self.propose(value=value)
        out = check_reasons(self, value)
        self.assertEqual(out, ['item_without_source'])
        with self.assertRaises(LedgerError) as caught: plans.approve(self.ledger, 'P1', 'owner', 'said yes')
        self.assertIn('S1', str(caught.exception))

    def test_unknown_decision(self):
        value = sourced(plan_json(), decisions=[DECISION]); value['items'][1]['source'] = 'D2'
        self.propose(value=value); self.advice_event()
        self.assertEqual(check_reasons(self, value), ['unknown_decision'])

    def test_unknown_decision_is_refused_without_decisions_too(self):
        value = sourced(plan_json()); value['items'][1]['source'] = 'D1'
        self.propose(value=value)
        self.assertEqual(check_reasons(self, value), ['unknown_decision'])

    def test_advice_missing_when_decisions_are_not_empty(self):
        value = sourced(plan_json(), decisions=[DECISION]); value['items'][1]['source'] = 'D1'
        self.propose(value=value)
        self.assertEqual(check_reasons(self, value), ['advice_missing'])

    def test_advice_missing_for_size_m_once_the_owner_rules_exist(self):
        value = sourced(size_m())
        self.propose(value=value); self.rules()
        self.assertEqual(check_reasons(self, value, choose='A'), ['advice_missing'])

    def test_unusable_advice_does_not_count(self):
        value = sourced(plan_json(), decisions=[DECISION]); value['items'][1]['source'] = 'D1'
        self.propose(value=value); self.advice_event(usable=False)
        self.assertEqual(check_reasons(self, value), ['advice_missing'])

    def test_advice_of_another_revision_does_not_count(self):
        value = sourced(plan_json(), decisions=[DECISION]); value['items'][1]['source'] = 'D1'
        self.propose(value=value); self.advice_event()
        plans.amend(self.ledger, 'P1', dict(value, title='Sample 2'), 'new title', AUTHOR)
        self.assertEqual(check_reasons(self, value), ['advice_missing'])

    def test_size_s_without_decisions_needs_no_advice(self):
        self.rules()                                                              # even with the owner rules in force
        self.propose(value=sourced(plan_json()))
        self.assertEqual(plans.approve(self.ledger, 'P1', 'owner', 'said yes')['status'], 'approved')

    def test_advice_with_objections_does_not_block(self):
        value = sourced(plan_json(), decisions=[DECISION]); value['items'][1]['source'] = 'D1'
        self.propose(value=value); self.advice_event()
        self.assertEqual(plans.approve(self.ledger, 'P1', 'owner', 'said yes')['status'], 'approved')

    def test_an_empty_new_field_still_opts_the_contract_in(self):
        for extra in ({'decisions': []}, {'presentation': {}}):
            with self.subTest(extra=extra):
                self.propose('P' + next(iter(extra)), plan_json(**extra))
                with self.assertRaises(LedgerError) as caught: plans.approve(self.ledger, 'P' + next(iter(extra)), 'owner', 'said yes')
                self.assertEqual(reasons(caught.exception), ['origin_missing', 'item_without_source'])

    def test_advice_missing_for_size_l_once_the_owner_rules_exist(self):
        value = sourced(size_m(), size='L')
        self.propose(value=value); self.rules()
        self.assertEqual(check_reasons(self, value, choose='A'), ['advice_missing'])

    def test_decision_ids_start_at_d1(self):
        for bad in ('D0', 'D00', 'D100'):
            with self.subTest(bad=bad), self.assertRaises(LedgerError): contracts.validate(dict(plan_json(), decisions=[dict(DECISION, id=bad)]))

    def test_size_m_with_advice_is_approved(self):
        self.propose(value=sourced(size_m())); self.rules(); self.advice_event()
        self.assertEqual(plans.approve(self.ledger, 'P1', 'owner', 'said yes', choose='A')['status'], 'approved')

    def test_the_owner_rules_make_every_contract_strict(self):
        self.propose(value=plan_json())
        self.assertEqual(plans.approve(self.ledger, 'P1', 'owner', 'said yes')['status'], 'approved')      # no rules file: the old contract still goes through
        self.propose('P2', plan_json()); self.rules()
        with self.assertRaises(LedgerError) as caught: plans.approve(self.ledger, 'P2', 'owner', 'said yes')
        self.assertEqual(reasons(caught.exception), ['origin_missing', 'item_without_source'])

    def test_every_reason_is_reported_together(self):
        value = plan_json(decisions=[DECISION]); value['items'][0]['source'] = 'D9'
        self.propose(value=value)
        self.assertEqual(check_reasons(self, value), ['origin_missing', 'item_without_source', 'unknown_decision', 'advice_missing'])

    def test_only_the_owner_approves(self):
        self.propose(value=sourced(plan_json()))
        with self.assertRaises(LedgerError): plans.approve(self.ledger, 'P1', 'claude', 'said yes')


class AdvisorFixture(Fixture):
    def setUp(self):
        super().setUp()
        self.prompts = []
        self.reply = answers()

    def stub(self):
        def fake(prompt, model, env, scratch, limit):
            self.prompts.append((prompt, model, scratch))
            return self.reply, {'num_turns': 1}, None, False, b'RAW-OUTPUT'
        patcher = patch.object(advisor, 'call', fake); patcher.start(); self.addCleanup(patcher.stop)

    def start(self, author=AUTHOR, rules=True, **extra):
        self.stub()
        if rules: advisor.init_rules(self.ledger)
        plans.propose(self.ledger, 'P1', sourced(plan_json(), decisions=[DECISION], **extra), author)

    def advice(self):
        with self.ledger.transaction() as conn:
            return plans.derive(self.ledger, conn, 'P1')['advice'].get(1)


class AdvisorTests(AdvisorFixture):
    def test_records_plan_advised_with_a_receipt(self):
        self.start()
        view = advisor.advise(self.ledger, 'P1')
        event = self.advice()
        self.assertEqual((event['model'], event['independence'], event['usable']), ('claude-opus-5-5', 'same_vendor_other_model', True))
        self.assertEqual([a['id'] for a in event['answers']], ['Q1', 'Q2', 'Q3'])
        self.assertEqual(view['advice']['answers'], event['answers'])
        self.assertTrue(view['advice']['current'])
        receipt = json.loads(Snapshots(self.ledger.state_root).read_blob(event['receipt']))
        self.assertEqual((receipt['kind'], receipt['answers'], receipt['calls']), ('advisor-receipt', event['answers'], 1))
        self.assertEqual(Snapshots(self.ledger.state_root).read_blob(receipt['raw']), b'RAW-OUTPUT')
        self.assertEqual(Snapshots(self.ledger.state_root).read_blob(receipt['answer']).decode(), self.reply)
        self.assertEqual(len(self.prompts), 1)

    def test_the_prompt_has_the_origin_the_rules_and_the_three_questions_and_runs_in_an_empty_directory(self):
        self.start()
        advisor.advise(self.ledger, 'P1', 'claude-opus-5-5')
        prompt, model, scratch = self.prompts[0]
        self.assertEqual(model, 'claude-opus-5-5')
        for text in (ORIGIN['quote'], 'R6.', 'Plain text file', 'Q1', 'Q2', 'Q3', 'Milestone M1'): self.assertIn(text, prompt)
        self.assertFalse(Path(scratch).exists())                                  # a scratch directory made for the call and removed after it

    def test_the_model_call_is_the_reviewers_headless_call(self):
        from onecrew.v2.verifiers import reviewer
        seen = []
        with patch.object(reviewer, 'call', lambda prompt, config, env, scratch, limit: (seen.append((config, scratch)) or (answers(), {}, None, False, b'r'))):
            advisor.init_rules(self.ledger)
            plans.propose(self.ledger, 'P1', sourced(plan_json(), decisions=[DECISION]), AUTHOR)
            advisor.advise(self.ledger, 'P1')
        self.assertEqual(seen[0][0], {'model': 'claude-opus-5-5'})

    def test_objections_are_recorded_shown_and_do_not_block(self):
        self.start(); self.reply = answers('objection', 'ok', 'objection', note='R1: release before trial')
        view = advisor.advise(self.ledger, 'P1')
        self.assertEqual([a['verdict'] for a in view['advice']['answers']], ['objection', 'ok', 'objection'])
        self.assertTrue(view['advice']['usable'])
        self.assertEqual(plans.approve(self.ledger, 'P1', 'owner', 'said yes')['status'], 'approved')      # decisions need advice, not good advice

    def test_the_same_model_as_the_author_is_refused_before_any_call(self):
        self.start(author='claude-opus-5-5')
        with self.assertRaises(LedgerError) as caught: advisor.advise(self.ledger, 'P1')
        self.assertIn('would be the author', str(caught.exception))
        self.assertEqual(self.prompts, []); self.assertIsNone(self.advice())

    def test_an_author_with_an_unknown_model_is_refused(self):
        self.start(author='claude')
        with self.assertRaises(LedgerError): advisor.advise(self.ledger, 'P1')
        self.assertEqual(self.prompts, [])

    def test_another_model_is_accepted(self):
        self.start(author='claude-opus-5-5')
        advisor.advise(self.ledger, 'P1', 'claude-sonnet-5-5')
        self.assertEqual(self.advice()['model'], 'claude-sonnet-5-5')

    def test_a_missing_rules_file_records_inconclusive_advice_that_does_not_count(self):
        self.start(rules=False)
        view = advisor.advise(self.ledger, 'P1')
        event = self.advice()
        self.assertEqual(self.prompts, [])
        self.assertEqual({a['verdict'] for a in event['answers']}, {'inconclusive'})
        self.assertEqual({a['note'] for a in event['answers']}, {'no owner-rules file'})
        self.assertFalse(event['usable'])
        self.assertEqual(event['note'], 'no owner-rules file')
        self.assertTrue(event['receipt'])
        self.assertFalse(view['advice']['usable'])
        with self.assertRaises(LedgerError) as caught: plans.approve(self.ledger, 'P1', 'owner', 'said yes')
        self.assertEqual(reasons(caught.exception), ['advice_missing'])

    def test_a_garbled_answer_is_inconclusive_never_ok(self):
        self.start()
        for reply in ('not json', json.dumps({'answers': []}), json.dumps({'nothing': 1}), '[]',
                      answers('ok', 'ok'),                                          # only two answers
                      json.dumps({'answers': [{'id': 'Q1', 'verdict': 'ok', 'note': 'x'}, {'id': 'Q2', 'verdict': 'pass', 'note': 'x'}, {'id': 'Q3', 'verdict': 'ok', 'note': 'x'}]}),
                      answers('ok', 'ok', 'ok', note='n' * 301)):
            with self.subTest(reply=reply[:40]):
                self.reply = reply
                advisor.advise(self.ledger, 'P1')
                event = self.advice()
                self.assertFalse(event['usable']); self.assertTrue(event['problems'])
                self.assertIn('inconclusive', {a['verdict'] for a in event['answers']})

    def test_a_fenced_answer_and_a_trimmed_note_are_read(self):
        self.start(); self.reply = '```json\n' + answers('ok', 'objection', 'ok', note='  R2  ') + '\n```'
        advisor.advise(self.ledger, 'P1')
        self.assertEqual([(a['verdict'], a['note']) for a in self.advice()['answers']], [('ok', 'R2'), ('objection', 'R2'), ('ok', 'R2')])

    def test_a_call_error_or_timeout_records_inconclusive_advice(self):
        self.start()
        for result in (('', {}, 'CLI reported an error', False, b''), ('', {}, None, True, b''), ('', {}, None, False, b'')):
            with self.subTest(result=result), patch.object(advisor, 'call', lambda *a, result=result: result):
                advisor.advise(self.ledger, 'P1')
                self.assertFalse(self.advice()['usable'])
                self.assertEqual({a['verdict'] for a in self.advice()['answers']}, {'inconclusive'})

    def test_an_amendment_while_the_advisor_answers_records_nothing(self):
        self.start()
        value = sourced(plan_json(), decisions=[DECISION], title='Changed meanwhile')
        with patch.object(advisor, 'call', lambda *a: (plans.amend(self.ledger, 'P1', value, 'changed', AUTHOR), (answers(), {}, None, False, b'r'))[1]):
            with self.assertRaises(LedgerError) as caught: advisor.advise(self.ledger, 'P1')
        self.assertIn('changed while the advisor', str(caught.exception))
        self.assertIsNone(self.advice())

    def test_plan_show_without_advice_has_none(self):
        self.start()
        view = plans.show(self.ledger, 'P1')
        self.assertIsNone(view['advice']); self.assertEqual(view['origin'], ORIGIN); self.assertEqual(view['decisions'], [DECISION])
        self.assertEqual([i['source'] for i in view['contract']['items']], ['origin'] * 3)

    def test_a_bad_model_id_is_refused(self):
        self.start()
        with self.assertRaises(LedgerError): advisor.advise(self.ledger, 'P1', '--model x')


class RulesTests(AdvisorFixture):
    def target(self):
        return Path(self.ledger.state_root) / 'plans' / 'owner-rules.md'

    def test_init_copies_the_template_once_and_never_overwrites(self):
        first = advisor.init_rules(self.ledger)
        self.assertTrue(first['created']); self.assertEqual(Path(first['path']), self.target())
        template = (Path(__file__).resolve().parents[1] / 'examples' / 'owner-rules.vi.md').read_bytes()
        self.assertEqual(self.target().read_bytes(), template)
        self.target().write_text('R1. my own rule\n', encoding='utf-8')
        second = advisor.init_rules(self.ledger)
        self.assertFalse(second['created'])
        self.assertEqual(self.target().read_text(encoding='utf-8'), 'R1. my own rule\n')
        self.assertEqual(advisor.show_rules(self.ledger), 'R1. my own rule\n')

    def test_the_template_has_the_six_rules_and_the_five_item_message(self):
        text = (Path(__file__).resolve().parents[1] / 'examples' / 'owner-rules.vi.md').read_text(encoding='utf-8')
        for rule in ('R1.', 'R2.', 'R3.', 'R4.', 'R5.', 'R6.'): self.assertEqual(len([l for l in text.splitlines() if l.startswith(rule)]), 1)
        for item in ('Yêu cầu', 'Người dùng sẽ thấy', 'Cách bạn nghiệm thu', 'Không làm', 'Rủi ro', 'Quyết định của tôi mà bạn chưa yêu cầu'): self.assertIn(item, text)

    def test_show_without_a_file_says_how_to_create_it(self):
        with self.assertRaises(LedgerError) as caught: advisor.show_rules(self.ledger)
        self.assertIn('plan rules init', str(caught.exception))

    def cli(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = plan_cli.main(['--project', str(self.root), '--state-root', str(self.ledger.state_root), 'plan', *argv])
        return code, out.getvalue()

    def test_the_cli_init_show_and_advise(self):
        code, out = self.cli('rules', 'init')
        self.assertEqual((code, json.loads(out)['created']), (0, True))
        self.assertEqual(json.loads(self.cli('rules', 'init')[1])['created'], False)
        self.assertIn('R6.', self.cli('rules', 'show')[1])
        self.stub()
        plans.propose(self.ledger, 'P1', sourced(plan_json(), decisions=[DECISION]), AUTHOR)
        code, out = self.cli('advise', 'P1')
        self.assertEqual(code, 0); self.assertEqual(json.loads(out)['advice']['model'], 'claude-opus-5-5')
        self.assertEqual(self.prompts[0][1], 'claude-opus-5-5')
        self.cli('advise', 'P1', '--model', 'claude-sonnet-5-5')
        self.assertEqual(self.prompts[1][1], 'claude-sonnet-5-5')

    def test_the_cli_refuses_the_authors_model_with_exit_2(self):
        self.cli('rules', 'init'); self.stub()
        plans.propose(self.ledger, 'P1', sourced(plan_json()), 'claude-opus-5-5')
        code, out = self.cli('advise', 'P1')
        self.assertEqual(code, 2); self.assertIn('author', json.loads(out)['error'])
        self.assertEqual(self.prompts, [])


class PromptHookTests(HookFixture):
    def context(self, prompt):
        code, out, _ = self.run_hook('prompt', {'session_id': 's1', 'cwd': str(self.root), 'hook_event_name': 'UserPromptSubmit', 'prompt': prompt})
        self.assertEqual(code, 0)
        return json.loads(out)['hookSpecificOutput']['additionalContext'] if out.strip() else None

    def test_the_hook_names_the_rules_file_only_when_it_exists(self):
        self.enforce()
        self.assertIsNone(self.context('please add the function'))
        advisor.init_rules(self.ledger)
        rules = str(Path(self.ledger.state_root) / 'plans' / 'owner-rules.md')
        self.assertIn(rules, self.context('please add the function'))
        both = self.context('nhanh lên, bỏ test đi')                              # a keyword reminder keeps its text and gains the line
        self.assertIn('Contract v1', both); self.assertIn(rules, both)


if __name__ == '__main__':
    unittest.main()
