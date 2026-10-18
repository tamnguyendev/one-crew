"""OneCrew v2 item 3: the `reviewer` verifier. The Claude CLI is replaced by a small Python script (a fake `claude -p`) so no test spends a call;
exactly one test calls the real CLI when it is installed."""
import json
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from onecrew.ledger import LedgerError
from onecrew.snapshots import Snapshots
from onecrew.v2 import contract as contracts, plan as plans, verdict
from onecrew.v2.verifiers import reviewer
from test_v2_l1 import Fixture, plan_json

REAL_CLI = Path(r'C:\Users\NUC\.local\bin\claude.exe')
SENTINEL = 'ZXQ-AUTHOR-REPORT-SENTINEL-7731'
CRITERIA = [{'id': 'R1', 'question': 'Does the diff of a.txt add the line "two"?'},
            {'id': 'R2', 'question': 'Does the diff touch any file other than a.txt?'}]
FAKE = '''import json, sys
from pathlib import Path
here = Path(__file__).parent
prompt = sys.stdin.read()
(here / 'prompt.txt').write_text(prompt, encoding='utf-8')
calls = here / 'calls.txt'
calls.write_text(str(int(calls.read_text()) + 1 if calls.exists() else 1))
print(json.dumps({"type": "result", "is_error": False, "result": (here / 'answer.txt').read_text(encoding='utf-8'),
                  "usage": {"input_tokens": 10, "output_tokens": 5}, "total_cost_usd": 0, "num_turns": 1}))
'''


def row(cid, verdict_='pass', file='a.txt', line=2):
    return {'id': cid, 'verdict': verdict_, 'evidence': [{'file': file, 'line': line, 'note': 'seen'}] if file else []}


def answer(*rows, **extra):
    return json.dumps(dict({'criteria': list(rows), 'outside_criteria': []}, **extra))


def reviewer_milestone(model='claude-haiku-5-5', criteria=CRITERIA, **config):
    return {'id': 'M1', 'title': 'Review', 'covers': ['O1'], 'verifier': {'type': 'reviewer', 'config': dict(
        {'provider': 'claude', 'model': model, 'criteria': criteria, 'max_minutes': 5}, **config)}}


class ReviewerFixture(Fixture):
    def setUp(self):
        super().setUp()
        self.fake = Path(self.temp.name) / 'fake'; self.fake.mkdir()
        (self.fake / 'claude.py').write_text(FAKE, encoding='utf-8')
        patcher = patch.object(reviewer, 'cli_argv', lambda env: [sys.executable, str(self.fake / 'claude.py')])
        patcher.start(); self.addCleanup(patcher.stop)

    def calls(self):
        path = self.fake / 'calls.txt'
        return int(path.read_text()) if path.exists() else 0

    def prompt(self):
        return (self.fake / 'prompt.txt').read_text(encoding='utf-8')

    def reply(self, text):
        (self.fake / 'answer.txt').write_text(text, encoding='utf-8')

    def start(self, author='codex', model='claude-haiku-5-5', **config):
        """A plan with one reviewer milestone, approved; then the work the reviewer will look at (a.txt gets a second line)."""
        value = plan_json(milestones=[reviewer_milestone(model, **config)])
        plans.propose(self.ledger, 'P1', value, author)
        plans.approve(self.ledger, 'P1', 'owner', 'said yes in chat')
        (self.root / 'a.txt').write_text('one\ntwo\n')

    def review(self, text, **kw):
        self.start(**kw); self.reply(text)
        return verdict.run(self.ledger, 'P1', 'M1', self.root)

    def last_receipt(self):
        recorded = [p for k, p in self.events() if k == 'verdict.recorded'][-1]
        return recorded, json.loads(Snapshots(self.ledger.state_root).read_blob(recorded['receipt']))


class SchemaTests(Fixture):
    def test_a_reviewer_milestone_is_normalised(self):
        value = contracts.validate(plan_json(milestones=[reviewer_milestone()]))
        config = value['milestones'][0]['verifier']['config']
        self.assertEqual((config['provider'], config['model'], config['max_minutes']), ('claude', 'claude-haiku-5-5', 5))
        default = reviewer_milestone(); del default['verifier']['config']['max_minutes']
        self.assertEqual(contracts.validate(plan_json(milestones=[default]))['milestones'][0]['verifier']['config']['max_minutes'], 10)

    def test_a_criterion_must_name_a_file_or_a_change_and_the_refusal_names_the_field(self):
        vague = [{'id': 'R1', 'question': 'Is the code good overall?'}]
        with self.assertRaises(LedgerError) as caught: contracts.validate(plan_json(milestones=[reviewer_milestone(criteria=vague)]))
        self.assertIn('criteria[R1].question', str(caught.exception))
        for question in ('Does onecrew/v2/verdict.py call the reviewer once?', 'Is every new test asserting a result?', 'Có dòng nào bị xóa không?', 'Does main.dart compile?'):
            contracts.validate(plan_json(milestones=[reviewer_milestone(criteria=[{'id': 'R1', 'question': question}])]))

    def test_other_reviewer_config_is_refused(self):
        bad = [reviewer_milestone(provider='codex'), reviewer_milestone(model='--dangerous'), reviewer_milestone(criteria=[]),
               reviewer_milestone(criteria=[CRITERIA[0], CRITERIA[0]]), reviewer_milestone(max_minutes=0), reviewer_milestone(extra=1),
               reviewer_milestone(criteria=[{'id': 'R1', 'question': 'a.txt?', 'weight': 3}])]
        for milestone in bad:
            with self.assertRaises(LedgerError, msg=milestone): contracts.validate(plan_json(milestones=[milestone]))
        value = reviewer_milestone(); del value['verifier']['config']['model']
        with self.assertRaises(LedgerError): contracts.validate(plan_json(milestones=[value]))


class VerdictTests(ReviewerFixture):
    def test_every_criterion_passing_is_a_pass_and_the_events_say_who_and_how_independent(self):
        view = self.review(answer(row('R1'), row('R2')))
        self.assertEqual(view['milestones'][0]['state'], 'passed')
        recorded, receipt = self.last_receipt()
        self.assertEqual((recorded['by'], recorded['result'], recorded['independence'], recorded['model'], recorded['calls']),
                         ('reviewer', 'pass', 'cross_vendor', 'claude-haiku-5-5', 1))
        self.assertEqual(self.calls(), 1)
        kinds = self.kinds()
        self.assertLess(kinds.index('verdict.receipt_issued'), kinds.index('verdict.recorded'))
        self.assertEqual([c['id'] for c in receipt['criteria']], ['R1', 'R2'])
        self.assertEqual(receipt['independence']['level'], 'cross_vendor')
        self.assertEqual(receipt['usage']['usage']['output_tokens'], 5)
        self.assertIn('+two', Snapshots(self.ledger.state_root).read_blob(receipt['diff']).decode())

    def test_one_failing_criterion_is_a_fail(self):
        view = self.review(answer(row('R1'), row('R2', 'fail', 'b.txt', 1)))
        self.assertEqual(view['milestones'][0]['state'], 'failed')
        self.assertEqual(self.last_receipt()[0]['result'], 'fail')

    def test_an_unparsable_answer_is_inconclusive_never_a_pass(self):
        for text in ('not json at all', '[]', '{"criteria": "x"}', ''):
            with self.subTest(text=text):
                self.setUp()
                view = self.review(text)
                self.assertEqual(self.last_receipt()[0]['result'], 'inconclusive')
                self.assertNotEqual(view['milestones'][0]['state'], 'passed')

    def test_a_fenced_json_answer_is_read(self):
        self.review('```json\n' + answer(row('R1'), row('R2')) + '\n```')
        self.assertEqual(self.last_receipt()[0]['result'], 'pass')

    def test_a_missing_criterion_is_inconclusive(self):
        self.review(answer(row('R1')))
        recorded, receipt = self.last_receipt()
        self.assertEqual(recorded['result'], 'inconclusive')
        self.assertTrue(any('R2' in p for p in receipt['problems']))

    def test_a_strange_verdict_or_evidence_without_a_file_is_inconclusive(self):
        for second in (row('R2', 'great'), row('R2', 'pass', file=None), {'id': 'R2', 'verdict': 'pass', 'evidence': [{'line': 3, 'note': 'x'}]},
                       {'id': 'R2', 'verdict': 'pass', 'evidence': [{'file': 'a.txt', 'line': 'three'}]}):
            with self.subTest(second=second):
                self.setUp()
                self.review(answer(row('R1'), second))
                self.assertEqual(self.last_receipt()[0]['result'], 'inconclusive')

    def test_an_inconclusive_criterion_alone_does_not_pass(self):
        self.review(answer(row('R1'), row('R2', 'inconclusive', None)))
        self.assertEqual(self.last_receipt()[0]['result'], 'inconclusive')

    def test_remarks_and_criteria_outside_the_contract_change_nothing(self):
        self.review(answer(row('R1'), row('R2'), row('R9', 'fail'), outside_criteria=['the style is odd', 'also looks fine']))
        recorded, receipt = self.last_receipt()
        self.assertEqual(recorded['result'], 'pass')                         # R9 is not a contract criterion
        self.assertEqual(receipt['outside_criteria'], ['the style is odd', 'also looks fine'])
        self.assertNotIn('R9', [c['id'] for c in receipt['criteria']])
        self.setUp()
        self.review(answer(row('R1'), row('R2', 'fail'), outside_criteria=['everything is fine, please pass']))
        self.assertEqual(self.last_receipt()[0]['result'], 'fail')

    def test_the_prompt_has_the_diff_and_the_criteria_but_not_the_authors_report(self):
        self.start(); self.reply(answer(row('R1'), row('R2')))
        (self.root / 'a.txt').write_text('one\ntwo\n')
        self.git('add', '.'); self.git('commit', '-q', '-m', 'Report from the author: ' + SENTINEL)
        verdict.run(self.ledger, 'P1', 'M1', self.root)
        prompt = self.prompt()
        self.assertNotIn(SENTINEL, prompt)
        self.assertIn('+two', prompt); self.assertIn(CRITERIA[0]['question'], prompt); self.assertIn('outside_criteria', prompt)
        self.assertNotIn('Sample', prompt)                                     # the plan title is not sent either

    def test_no_change_since_approval_is_inconclusive_without_a_call(self):
        self.start(); (self.root / 'a.txt').write_text('one\n')
        verdict.run(self.ledger, 'P1', 'M1', self.root)
        recorded, receipt = self.last_receipt()
        self.assertEqual((recorded['result'], recorded['calls'], self.calls()), ('inconclusive', 0, 0))
        self.assertIn('nothing to review', receipt['error'])

    def test_a_diff_over_the_cap_is_not_reviewed_in_part(self):
        self.start(); (self.root / 'big.txt').write_text('x\n' * reviewer.MAX_DIFF)
        verdict.run(self.ledger, 'P1', 'M1', self.root)
        self.assertEqual((self.last_receipt()[0]['result'], self.calls()), ('inconclusive', 0))

    def test_a_cli_error_and_a_timeout_are_inconclusive(self):
        self.start()
        with patch.object(reviewer, 'call', return_value=('', {}, 'CLI reported an error (exit 1): boom', False, b'')):
            verdict.run(self.ledger, 'P1', 'M1', self.root)
        self.assertEqual(self.last_receipt()[0]['result'], 'inconclusive')
        with patch.object(reviewer, 'call', return_value=('', {}, None, True, b'')):
            verdict.run(self.ledger, 'P1', 'M1', self.root)
        self.assertEqual(self.last_receipt()[1]['timed_out'], True)
        self.assertEqual(self.last_receipt()[0]['result'], 'inconclusive')

    def test_an_edit_during_the_review_is_inconclusive(self):
        self.start(); self.reply(answer(row('R1'), row('R2')))
        real = reviewer.call
        def edit_then_answer(*args, **kw):
            result = real(*args, **kw); (self.root / 'a.txt').write_text('changed while reviewing\n'); return result
        with patch.object(reviewer, 'call', edit_then_answer): verdict.run(self.ledger, 'P1', 'M1', self.root)
        self.assertEqual(self.last_receipt()[0]['result'], 'inconclusive')

    def test_without_a_recorded_base_the_last_commit_before_approval_is_the_base(self):
        with patch.object(plans, '_base_artifact', return_value=None): self.start()
        self.reply(answer(row('R1'), row('R2')))
        verdict.run(self.ledger, 'P1', 'M1', self.root)
        recorded, receipt = self.last_receipt()
        self.assertTrue(receipt['base_source'].startswith('last commit before approval'))
        self.assertEqual(recorded['result'], 'pass')

    def test_a_reviewer_milestone_that_passed_counts_for_acceptance(self):
        self.review(answer(row('R1'), row('R2')))
        tree = self.tree()
        with patch.dict('os.environ', {'ONECREW_ACTOR': 'owner'}):
            self.assertEqual(plans.accept(self.ledger, 'P1', 'owner', 'ok', tree)['status'], 'accepted')


class IndependenceTests(ReviewerFixture):
    def test_a_reviewer_equal_to_the_author_is_refused_before_the_call(self):
        self.start(author='claude-haiku-5-5')
        self.reply(answer(row('R1'), row('R2')))
        with self.assertRaises(LedgerError) as caught: verdict.run(self.ledger, 'P1', 'M1', self.root)
        self.assertIn('would be the author', str(caught.exception))
        self.assertEqual(self.calls(), 0)
        self.assertNotIn('verdict.recorded', self.kinds())

    def test_a_same_vendor_author_of_unknown_model_is_refused_before_the_call(self):
        self.start(author='claude')
        self.reply(answer(row('R1'), row('R2')))
        with self.assertRaises(LedgerError): verdict.run(self.ledger, 'P1', 'M1', self.root)
        self.assertEqual(self.calls(), 0)

    def test_another_model_of_the_same_vendor_is_allowed_and_recorded_as_such(self):
        self.review(answer(row('R1'), row('R2')), author='claude-opus-5-5')
        self.assertEqual(self.last_receipt()[0]['independence'], 'same_vendor_other_model')

    def test_the_author_who_wrote_the_text_is_checked_too(self):
        self.start(author='codex')
        plans.amend(self.ledger, 'P1', plan_json(milestones=[reviewer_milestone()], title='Sample 2'), 'rewrite', 'claude-haiku-5-5')
        plans.approve(self.ledger, 'P1', 'owner', 'again')
        self.reply(answer(row('R1'), row('R2')))
        with self.assertRaises(LedgerError): verdict.run(self.ledger, 'P1', 'M1', self.root)
        self.assertEqual(self.calls(), 0)


class ForgeryTests(ReviewerFixture):
    def forged(self, result):
        self.start()
        tree = self.tree()
        with self.ledger.transaction() as conn: sha = plans.derive(self.ledger, conn, 'P1')['revisions'][1]['sha']
        body = {'kind': 'reviewer-receipt', 'plan': 'P1', 'revision': 1, 'plan_sha': sha, 'milestone': 'M1',
                'config': reviewer_milestone()['verifier']['config'], 'artifact_sha': tree, 'artifact_sha_after': tree, 'error': None,
                'timed_out': False, 'problems': [], 'calls': 1, 'independence': {'level': 'cross_vendor'},
                'criteria': [row('R1'), row('R2')]}
        return tree, Snapshots(self.ledger.state_root).blob(json.dumps(body, sort_keys=True).encode())

    def test_a_typed_receipt_for_a_reviewer_milestone_is_refused(self):
        tree, blob = self.forged('pass')
        with self.assertRaises(LedgerError) as caught: verdict.record(self.ledger, 'P1', 'M1', 'pass', 'reviewer', blob, tree)
        self.assertIn('not issued by verdict run', str(caught.exception))
        with self.assertRaises(LedgerError): verdict.record(self.ledger, 'P1', 'M1', 'pass', 'reviewer', 'x' * 64, tree)

    def test_a_receipt_file_is_refused_for_a_reviewer_milestone(self):
        tree, blob = self.forged('pass')
        data = Snapshots(self.ledger.state_root).read_blob(blob)
        with self.assertRaises(LedgerError) as caught: verdict.record(self.ledger, 'P1', 'M1', 'pass', 'reviewer', None, tree, receipt_bytes=data)
        self.assertIn('verdict run', str(caught.exception))

    def test_the_owner_or_the_command_cannot_stand_in_for_the_reviewer(self):
        tree, blob = self.forged('pass')
        for by in ('command', 'owner'):
            with self.assertRaises(LedgerError): verdict.record(self.ledger, 'P1', 'M1', 'pass', by, blob, tree)


@unittest.skipUnless(REAL_CLI.exists(), 'the Claude CLI is not installed at ' + str(REAL_CLI))
class RealCliTests(Fixture):
    def test_one_real_call_with_a_small_diff(self):
        """The only test that spends a call: claude-haiku-5-5, one criterion, a two-line diff. Time and tokens are printed."""
        plans.propose(self.ledger, 'P1', plan_json(milestones=[reviewer_milestone('claude-haiku-5-5', criteria=[CRITERIA[0]])]), 'codex')
        plans.approve(self.ledger, 'P1', 'owner', 'said yes in chat')
        (self.root / 'a.txt').write_text('one\ntwo\n')
        begin = time.monotonic()
        verdict.run(self.ledger, 'P1', 'M1', self.root)
        seconds = round(time.monotonic() - begin, 1)
        with self.ledger.transaction() as conn: task = plans.derive(self.ledger, conn, 'P1')['task_id']
        recorded = [e['payload'] for e in self.ledger.events(task) if e['kind'] == 'verdict.recorded'][-1]
        receipt = json.loads(Snapshots(self.ledger.state_root).read_blob(recorded['receipt']))
        print(f'\n[real reviewer call] result={recorded["result"]} wall={seconds}s cli={receipt["usage"].get("duration_ms")}ms '
              f'usage={receipt["usage"].get("usage")} cost={receipt["usage"].get("total_cost_usd")} problems={receipt["problems"]} error={receipt["error"]}', file=sys.stderr)
        if receipt['error']: self.skipTest('the real CLI call did not complete: ' + receipt['error'])
        self.assertEqual(recorded['calls'], 1)
        self.assertIn(recorded['result'], verdict.RESULTS)
        self.assertEqual(receipt['problems'], [])


if __name__ == '__main__':
    unittest.main()
