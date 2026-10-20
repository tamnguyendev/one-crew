"""OneCrew v2, slice L3: step 0 is enforced by code. One test per gate, each proving the way around it does not work.

Gates: low confidence / open unknown / assumption without evidence / options not chosen / red precondition / bad target each
refuse `plan approve`, and the refusal lists EVERY reason; `chosen` is the owner's alone; an unknown is closed only by the ledger
event; an output criterion without a milestone is refused at propose; size S skips options but never preconditions.
"""
import contextlib
import io
import json
import os
import sys
import unittest

from onecrew import cli
from onecrew.ledger import LedgerError
from onecrew.snapshots import Snapshots
from onecrew.v2 import contract as contracts, plan as plans, step0, verdict
from tests.test_v2_l1 import BAD, OK, PY, Fixture, milestone, plan_json

DOC = 'onecrew/conversations.py:167'


def option(oid, evidence=('x/y.py:1',), **extra):
    return dict({'id': oid, 'summary': f'Option {oid}', 'evidence': list(evidence), 'strengths': ['simple'], 'weaknesses': ['slow'],
                 'unknowns': [], 'cost': '3 calls', 'risk': 'low'}, **extra)


def options(*ids, recommended=None):
    return {'recommended': recommended or ids[0], 'reason': 'cheapest that works', 'items': [option(i) for i in ids]}


def step0_json(size='M', unknowns=(), assumptions=(('the file is text', 'a.txt:1'),), confidence='high', opts='default', pre=None, **extra):
    value = plan_json(size=size)
    value['understanding'] = {'restated_goal': 'Prove the sample.', 'target': {'repo': '.', 'ref': 'HEAD', 'paths': ['a.txt']},
                              'assumptions': [{'text': t, 'evidence': e} for t, e in assumptions], 'confidence': confidence,
                              'unknowns': [{'id': u, 'question': f'What about {u}?', 'status': 'open', 'closed_by': None, 'evidence': None} for u in unknowns]}
    if size != 'S' and not unknowns:      # 2.2.0.dev2: size M/L with no unknowns says what was checked (unknowns_missing)
        value['understanding']['no_unknowns_because'] = 'read a.txt:1 and the sample has one path; nothing is open'
    value['options'] = options('A', 'B') if opts == 'default' and size != 'S' else (None if opts == 'default' else opts)
    if value['options'] is None: del value['options']
    value['preconditions'] = pre or value['preconditions']
    return dict(value, **extra)


def reasons(error):
    return [line.split(']')[0].split('[')[1] for line in str(error).splitlines() if line.startswith(' - [')]


class Step0(Fixture):
    def setUp(self):
        super().setUp()
        for relative, lines in (('x/y.py', 3), ('onecrew/conversations.py', 170)):                              # C12: the pointers the fixtures cite must resolve
            path = self.root / relative; path.parent.mkdir(parents=True, exist_ok=True); path.write_text('x = 1\n' * lines)

    def refused(self, value, name='P1', **kw):
        self.propose(name, value)
        with self.assertRaises(LedgerError) as caught: plans.approve(self.ledger, name, 'owner', 'ref', **kw)
        self.assertNotIn('plan.approved', self.kinds(name))
        return caught.exception

    def approve_ok(self, value, name='P1', **kw):
        self.propose(name, value)
        return plans.approve(self.ledger, name, 'owner', 'ref', **kw)

    def cli(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli.main(['--project', str(self.root), '--state-root', str(self.ledger.state_root), *argv])
        return code, out.getvalue()


class SixRefusals(Step0):
    def test_low_confidence_refuses_approve(self):
        self.assertEqual(reasons(self.refused(step0_json(confidence='low'), choose=None)), ['confidence_low', 'options_not_chosen'])

    def test_an_open_unknown_refuses_approve(self):
        self.assertEqual(reasons(self.refused(step0_json(size='S', unknowns=['U1']))), ['unknown_open'])

    def test_an_assumption_without_evidence_refuses_approve(self):
        self.assertEqual(reasons(self.refused(step0_json(size='S', assumptions=[('the base builds', None)]))), ['assumption_no_evidence'])

    def test_options_without_the_owners_choice_refuse_approve(self):
        error = self.refused(step0_json())
        self.assertEqual(reasons(error), ['options_not_chosen'])
        self.assertIn('--choose', str(error))

    def test_a_red_precondition_refuses_approve_and_leaves_an_event_and_a_receipt(self):
        pre = [{'id': 'P1', 'check': 'path_exists', 'args': {'path': 'missing.txt'}, 'why': 'the file must be there'}]
        error = self.refused(step0_json(size='S', pre=pre))
        self.assertEqual(reasons(error), ['precondition_red'])
        recorded = [p for k, p in self.events() if k == 'precondition.recorded']
        self.assertEqual(len(recorded), 1)
        self.assertFalse(recorded[0]['ok']); self.assertEqual(recorded[0]['phase'], 'approve')
        body = json.loads(Snapshots(self.ledger.state_root).read_blob(recorded[0]['receipt']))
        self.assertFalse(body['results'][0]['ok'])

    def test_a_target_that_does_not_exist_refuses_approve(self):
        for repo, ref, paths, code in (('nowhere', 'HEAD', [], 'target_repo'), ('.', 'no-such-branch', [], 'target_ref'),
                                       ('.', 'HEAD', ['gone.txt'], 'target_path')):
            value = step0_json(size='S')
            value['understanding']['target'] = {'repo': repo, 'ref': ref, 'paths': paths}
            name = 'T' + code
            self.assertEqual(reasons(self.refused(value, name)), [code])

    def test_a_project_directory_inside_the_repository_is_a_valid_target(self):
        # qc_intake.locate walks up to the repository; a directory that exists but is in no repository is not a target
        (self.root / 'plain').mkdir(); (self.root / 'plain' / 'f.txt').write_text('x')
        value = step0_json(size='S'); value['understanding']['target'] = {'repo': 'plain', 'ref': 'HEAD', 'paths': ['f.txt']}
        self.assertEqual(self.approve_ok(value)['status'], 'approved')


class AllReasons(Step0):
    def test_the_refusal_lists_every_reason_not_only_the_first(self):
        pre = [{'id': 'P1', 'check': 'path_exists', 'args': {'path': 'missing.txt'}, 'why': 'w'},
               {'id': 'P2', 'check': 'command_ok', 'args': {'argv': BAD}, 'why': 'w'}]
        value = step0_json(confidence='low', unknowns=['U1', 'U2'], assumptions=[('a', None)], pre=pre)
        error = self.refused(value)
        self.assertEqual(reasons(error), ['confidence_low', 'unknown_open', 'unknown_open', 'assumption_no_evidence', 'options_not_chosen',
                                          'precondition_red', 'precondition_red'])
        self.assertIn('7 reasons', str(error))


class Preconditions(Step0):
    def test_a_command_over_its_minute_cap_is_red(self):
        pre = [{'id': 'P1', 'check': 'command_ok', 'args': {'argv': [PY, '-c', 'import time; time.sleep(30)'], 'max_minutes': 0.02}, 'why': 'w'}]
        error = self.refused(step0_json(size='S', pre=pre))
        self.assertIn('exceeded', str(error))
        self.assertEqual(reasons(error), ['precondition_red'])

    def test_green_commands_and_sdk_version_let_approve_through_and_close_step_0(self):
        pre = [{'id': 'P1', 'check': 'command_ok', 'args': {'argv': OK}, 'why': 'the base builds'},
               {'id': 'P2', 'check': 'sdk_version', 'args': {'argv': [PY, '--version'], 'pattern': r'Python 3\.\d+'}, 'why': 'right interpreter'},
               {'id': 'P3', 'check': 'ref_resolves', 'args': {'ref': 'HEAD'}, 'why': 'w'}, {'id': 'P4', 'check': 'repo_exists', 'args': {'path': '.'}, 'why': 'w'}]
        view = self.approve_ok(step0_json(size='S', pre=pre))
        self.assertEqual(view['status'], 'approved'); self.assertTrue(view['step0']['closed'])
        self.assertTrue(view['step0']['preconditions']['ok'])
        self.assertIn('plan.step0_closed', self.kinds())

    def test_sdk_version_with_the_wrong_output_is_red(self):
        pre = [{'id': 'P1', 'check': 'sdk_version', 'args': {'argv': OK, 'pattern': r'Flutter 3\.'}, 'why': 'w'}]
        self.assertEqual(reasons(self.refused(step0_json(size='S', pre=pre))), ['precondition_red'])

    def test_a_bad_check_name_or_argument_is_refused_at_propose(self):
        for pre in ([{'id': 'P1', 'check': 'rm_rf', 'args': {}, 'why': 'w'}],
                    [{'id': 'P1', 'check': 'command_ok', 'args': {'argv': OK, 'max_minutes': 0}, 'why': 'w'}],
                    [{'id': 'P1', 'check': 'command_ok', 'args': {'argv': OK, 'max_minutes': 61}, 'why': 'w'}],
                    [{'id': 'P1', 'check': 'path_exists', 'args': {'path': '../x'}, 'why': 'w'}]):
            with self.assertRaises(LedgerError): contracts.validate(step0_json(size='S', pre=pre))

    def test_precheck_runs_without_approving_and_prints_a_green_red_table(self):
        pre = [{'id': 'P1', 'check': 'path_exists', 'args': {'path': 'a.txt'}, 'why': 'w'}, {'id': 'P2', 'check': 'command_ok', 'args': {'argv': BAD}, 'why': 'w'}]
        self.propose('P1', step0_json(size='S', pre=pre))
        code, text = self.cli('plan', 'precheck', 'P1')
        self.assertEqual(code, 0)
        self.assertIn('GREEN P1 path_exists', text); self.assertIn('RED   P2 command_ok', text); self.assertIn('0 AI calls', text)
        self.assertNotIn('plan.approved', self.kinds()); self.assertIn('precondition.recorded', self.kinds())
        with self.ledger.transaction() as conn:   # no job was created for it: only the anchor task exists
            self.assertEqual(conn.execute('SELECT count(*) FROM tasks').fetchone()[0], 1)


class Echo(Step0):
    def test_an_output_criterion_no_milestone_covers_is_refused_at_propose(self):
        value = step0_json(size='S', output=['The sample exists', 'Documented'])   # milestone() covers only O1
        with self.assertRaises(LedgerError) as caught: plans.propose(self.ledger, 'P1', value, 'claude')
        self.assertIn('O2', str(caught.exception))
        value = step0_json(size='S'); value['milestones'][0]['covers'] = ['O1', 'O9']
        with self.assertRaises(LedgerError): contracts.validate(value)

    def test_the_example_contract_for_this_slice_is_valid(self):
        from pathlib import Path
        path = Path(__file__).resolve().parent.parent / 'examples' / 'v2-plan-l3.json'
        contracts.validate(json.loads(path.read_text(encoding='utf-8')))


class Choice(Step0):
    def test_the_ai_cannot_set_chosen(self):
        for place in ('top', 'options'):
            value = step0_json()
            if place == 'top': value['chosen'] = 'A'
            else: value['options']['chosen'] = 'A'
            with self.assertRaises(LedgerError): plans.propose(self.ledger, 'P-' + place, value, 'claude')
        self.propose('P1', step0_json())
        with self.assertRaises(LedgerError): plans.approve(self.ledger, 'P1', 'ai', 'r', choose='A')
        os.environ['ONECREW_ACTOR'] = 'claude'
        with self.assertRaises(LedgerError): plans.approve(self.ledger, 'P1', 'owner', 'r', choose='A')   # an AI shell claiming to be the owner
        self.assertNotIn('plan.approved', self.kinds())

    def test_the_owner_chooses_once_and_the_choice_is_in_the_approval_event(self):
        view = self.approve_ok(step0_json(), choose='B')
        self.assertEqual(view['step0']['chosen'], 'B')
        approved = [p for k, p in self.events() if k == 'plan.approved'][0]
        self.assertEqual(approved['chosen'], 'B')
        self.assertIn('"chosen"', json.dumps([p for k, p in self.events() if k == 'plan.step0_closed']))
        self.assertEqual(plans.approve(self.ledger, 'P1', 'owner', 'again', choose='B')['status'], 'approved')   # repeating the same choice is a no-op

    def test_choosing_again_after_approve_is_refused_only_amend_can_change_it(self):
        self.approve_ok(step0_json(), choose='A')
        with self.assertRaises(LedgerError) as caught: plans.approve(self.ledger, 'P1', 'owner', 'again', choose='B')
        self.assertIn('plan amend', str(caught.exception))
        self.assertEqual(plans.show(self.ledger, 'P1')['step0']['chosen'], 'A')
        changed = step0_json(); changed['options']['items'][0]['summary'] = 'Option A, reworked'
        plans.amend(self.ledger, 'P1', changed, 'CREQ-1 rework A', 'claude')
        self.assertEqual(plans.approve(self.ledger, 'P1', 'owner', 'new revision', choose='B')['step0']['chosen'], 'B')

    def test_a_choice_must_name_an_option_with_evidence_and_not_exist_without_options(self):
        self.assertEqual(reasons(self.refused(step0_json(), 'P1', choose='Z')), ['choose_unknown'])
        bare = step0_json(opts={'recommended': 'A', 'reason': 'r', 'items': [option('A', evidence=()), option('B')]})
        self.assertEqual(reasons(self.refused(bare, 'P2', choose='A')), ['option_no_evidence'])
        self.assertEqual(reasons(self.refused(step0_json(size='S'), 'P3', choose='A')), ['choose_without_options'])

    def test_the_brainstorm_table_is_at_most_30_lines(self):
        value = step0_json(opts=options('A', 'B', 'C', 'D', 'E', recommended='C'))
        self.propose('P1', value)
        code, text = self.cli('plan', 'brainstorm', 'table', 'P1')
        self.assertEqual(code, 0)
        self.assertLessEqual(len(text.rstrip().splitlines()), 30)
        self.assertIn('(recommended)', text)
        with self.assertRaises(LedgerError): contracts.validate(step0_json(opts=options('A', 'B', 'C', 'D', 'E', 'F')))   # capped at 5


class Sizes(Step0):
    def test_size_s_may_omit_options_but_not_preconditions(self):
        self.assertEqual(self.approve_ok(step0_json(size='S'))['status'], 'approved')
        value = step0_json(size='S'); value['preconditions'] = []
        with self.assertRaises(LedgerError): contracts.validate(value)
        del value['preconditions']
        with self.assertRaises(LedgerError): contracts.validate(value)

    def test_size_m_and_l_need_options_and_assumptions(self):
        for size in ('M', 'L'):
            with self.assertRaises(LedgerError) as caught: contracts.validate(step0_json(size=size, opts=None))
            self.assertIn('options', str(caught.exception))
            with self.assertRaises(LedgerError): contracts.validate(step0_json(size=size, assumptions=[]))
        with self.assertRaises(LedgerError): contracts.validate(dict(step0_json(size='S'), size='XL'))
        with self.assertRaises(LedgerError): contracts.validate({k: v for k, v in step0_json(size='S').items() if k != 'size'})


class Unknowns(Step0):
    def test_closing_by_doc_makes_a_revision_and_an_event_and_approve_then_passes(self):
        self.propose('P1', step0_json(size='S', unknowns=['U1']))
        with self.assertRaises(LedgerError): plans.approve(self.ledger, 'P1', 'owner', 'r')
        view = step0.close_unknown(self.ledger, 'P1', 'U1', 'doc', DOC)
        self.assertEqual(view['latest_revision'], 2)
        self.assertEqual(view['revisions'][-1]['reason'], 'unknown U1 closed')
        closed = [p for k, p in self.events() if k == 'unknown.closed']
        self.assertEqual((closed[0]['unknown'], closed[0]['by'], closed[0]['evidence_kind'], closed[0]['revision']), ('U1', 'doc', 'file_line', 2))
        self.assertEqual(plans.approve(self.ledger, 'P1', 'owner', 'r')['status'], 'approved')
        done = [p for k, p in self.events() if k == 'plan.step0_closed'][0]
        self.assertEqual(done['unknowns'], [{'id': 'U1', 'closed_by': 'doc', 'evidence': DOC}])

    def test_a_contract_file_that_says_closed_is_not_believed(self):
        value = step0_json(size='S', unknowns=['U1'])
        value['understanding']['unknowns'][0].update(status='closed', closed_by='doc', evidence=DOC)
        self.assertEqual(reasons(self.refused(value)), ['unknown_unrecorded'])

    def test_evidence_must_point_somewhere(self):
        self.propose('P1', step0_json(size='S', unknowns=['U1']))
        for bad in ('I checked, trust me', 'a' * 64):   # prose; a blob key that is not in the store
            with self.assertRaises(LedgerError): step0.close_unknown(self.ledger, 'P1', 'U1', 'doc', bad)
        blob = Snapshots(self.ledger.state_root).blob(b'notes')
        self.assertEqual(step0.close_unknown(self.ledger, 'P1', 'U1', 'doc', blob)['latest_revision'], 2)
        with self.assertRaises(LedgerError): step0.close_unknown(self.ledger, 'P1', 'U1', 'doc', DOC)   # already closed
        with self.assertRaises(LedgerError): step0.close_unknown(self.ledger, 'P1', 'U9', 'doc', DOC)   # no such unknown

    def test_only_the_owner_closes_as_owner(self):
        self.propose('P1', step0_json(size='S', unknowns=['U1']))
        os.environ['ONECREW_ACTOR'] = 'claude'
        with self.assertRaises(LedgerError): step0.close_unknown(self.ledger, 'P1', 'U1', 'owner', 'I decided so, the owner')
        del os.environ['ONECREW_ACTOR']
        self.assertEqual(step0.close_unknown(self.ledger, 'P1', 'U1', 'owner', 'the owner decided in chat')['latest_revision'], 2)

    def test_closing_an_unknown_makes_the_old_verdicts_void(self):
        self.approved('P1', step0_json(size='S'))
        verdict.run(self.ledger, 'P1', 'M1', self.root)
        self.assertEqual(plans.show(self.ledger, 'P1')['milestones'][0]['state'], 'passed')
        plans.amend(self.ledger, 'P1', step0_json(size='S', unknowns=['U2']), 'new question', 'claude')   # revision 2, unknown open
        self.assertEqual(plans.show(self.ledger, 'P1')['status'], 'proposed')
        view = step0.close_unknown(self.ledger, 'P1', 'U2', 'doc', DOC)                                   # revision 3
        self.assertEqual((view['latest_revision'], view['status'], view['milestones'][0]['state']), (3, 'proposed', 'pending'))
        with self.assertRaises(LedgerError): plans.accept(self.ledger, 'P1', 'owner', 'r', self.tree())

    def test_cli_close_and_approve_choose(self):
        self.propose('P1', step0_json(unknowns=['U1']))
        code, text = self.cli('plan', 'approve', 'P1', '--by', 'owner', '--reference', 'r', '--choose', 'A')
        self.assertEqual(code, 2); self.assertIn('unknown_open', text)
        code, text = self.cli('plan', 'unknown', 'close', 'P1', 'U1', '--by', 'doc', '--evidence', DOC)
        self.assertEqual((code, json.loads(text)['latest_revision']), (0, 2))
        code, text = self.cli('plan', 'approve', 'P1', '--by', 'owner', '--reference', 'r', '--choose', 'A')
        self.assertEqual((code, json.loads(text)['step0']['chosen']), (0, 'A'))


class Poc(Step0):
    def evidence_file(self, text='the probe ran and printed 3'):
        path = os.path.join(self.temp.name, 'poc.txt')
        with open(path, 'w', encoding='utf-8') as stream: stream.write(text)
        return path

    def test_a_poc_records_its_answer_and_closes_the_unknown_with_the_evidence_blob(self):
        self.propose('P1', step0_json(size='S', unknowns=['U1']))
        view = step0.poc_record(self.ledger, 'P1', 'U1', 'yes, it works', self.evidence_file(), 'high')
        self.assertEqual(view['latest_revision'], 2)
        answered = [p for k, p in self.events() if k == 'poc.answered'][0]
        self.assertEqual((answered['unknown'], answered['confidence']), ('U1', 'high'))
        self.assertEqual(Snapshots(self.ledger.state_root).read_blob(answered['evidence']), b'the probe ran and printed 3')
        self.assertEqual(view['contract']['understanding']['unknowns'][0]['closed_by'], 'poc')
        self.assertEqual(plans.approve(self.ledger, 'P1', 'owner', 'r')['status'], 'approved')

    def test_a_poc_that_could_apply_to_the_project_is_refused(self):
        self.propose('P1', step0_json(size='S', unknowns=['U1']))
        for authority in ({'apply_to_project': True, 'edit': True}, {'local_branches': ['x']}, {'push': True}):
            with self.assertRaises(LedgerError): step0.poc_record(self.ledger, 'P1', 'U1', 'a', self.evidence_file(), 'high', {'authority': authority})
        self.assertNotIn('poc.answered', self.kinds())
        step0.poc_record(self.ledger, 'P1', 'U1', 'a', self.evidence_file(), 'high', {'authority': {'edit': True}})

    def test_a_low_confidence_poc_is_recorded_but_does_not_close_the_unknown(self):
        self.propose('P1', step0_json(size='S', unknowns=['U1']))
        out = step0.poc_record(self.ledger, 'P1', 'U1', 'maybe', self.evidence_file(), 'low')
        self.assertIn('still open', out['status']); self.assertIn('poc.answered', self.kinds())
        self.assertEqual(plans.show(self.ledger, 'P1')['latest_revision'], 1)
        self.assertEqual(reasons(self.refused_again()), ['unknown_open'])

    def refused_again(self):
        with self.assertRaises(LedgerError) as caught: plans.approve(self.ledger, 'P1', 'owner', 'r')
        return caught.exception


if __name__ == '__main__':
    unittest.main()
