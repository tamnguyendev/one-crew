"""T40a (W43, release RP): reviewer and advisor by provider (`claude`, `codex`, `kiro`) through a read-only CLI.

Every CLI here is a FAKE: one Python script (tests/ writes it into a temp dir) that records its argv, working directory and stdin, and answers in the
format of the provider it stands for. A fake proves the interface and the rules (what is called, with what, what the receipt says, what is refused
before a call); it proves nothing about the real CLIs (T40b / W45). No test calls a real provider.

Acceptance (05 ## T40, part T40a): E1 provider is one contract field, E2 read-only command shapes, E3 receipt carries provider and model, E4 independence by
vendor, E5 quota -> inconclusive with a reason and no switch, E6 owner-manual unchanged, E7 not a decider, E17 contract/lint, E19 six cells;
forbidden: E12 switch on quota, E13 code change to change provider, E14 receipt without provider/model, E15 write permission.
Run with tests/ on the path (the suite's convention): PYTHONPATH=<worktree>;<worktree>\\tests
"""
import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from onecrew.ledger import LedgerError
from onecrew.snapshots import Snapshots
from onecrew.v2 import contract as contracts, lint, plan as plans, providers, verdict
from onecrew.v2.verifiers import advisor, reviewer
from test_v2_advisor import DECISION, answers as advisor_answers, sourced
from test_v2_l1 import Fixture, plan_json
from test_v2_reviewer import CRITERIA, answer as reviewer_answer, reviewer_milestone, row

AUTHOR = 'claude-sonnet-5-5'
# provider -> a model id for it that is another model than AUTHOR (kiro serves claude models here: same vendor, other model)
MODELS = {'claude': 'claude-haiku-5-5', 'codex': 'gpt-5-codex', 'kiro': 'claude-haiku-4.5'}
ADVISOR_MODELS = {'claude': 'claude-opus-5-5', 'codex': 'gpt-5-codex', 'kiro': 'claude-haiku-4.5'}
QUOTA_TEXT = "You've hit your usage limit. Try again later."

FAKE = r'''import json, os, sys
from pathlib import Path
here = Path(__file__).parent
tag, args = sys.argv[1], sys.argv[2:]
if args == ['--version']:
    print('fake-%s 0.0.1' % tag); sys.exit(0)
stdin = sys.stdin.read()
with (here / 'calls.jsonl').open('a', encoding='utf-8') as log:
    log.write(json.dumps({'provider': tag, 'args': args, 'cwd': os.getcwd(), 'stdin': stdin, 'listing': sorted(os.listdir('.'))}) + '\n')
mode = (here / 'mode.txt').read_text().strip() if (here / 'mode.txt').exists() else 'ok'
answer = (here / 'answer.txt').read_text(encoding='utf-8') if (here / 'answer.txt').exists() else ''
quota = "You've hit your usage limit. Try again later."
def emit(*events):
    for event in events: print(json.dumps(event))
if mode == 'tooloutput': print('this is not json at all'); sys.exit(0)
if tag == 'claude':
    if mode == 'quota': print(json.dumps({'type': 'result', 'is_error': True, 'result': quota})); sys.exit(1)
    print(json.dumps({'type': 'result', 'is_error': False, 'result': answer, 'usage': {'input_tokens': 1, 'output_tokens': 1}}))
elif tag == 'codex':
    if mode == 'quota': emit({'type': 'turn.failed', 'error': {'message': quota}}); sys.exit(1)
    if mode == 'filechange': emit({'type': 'item.completed', 'item': {'type': 'file_change', 'changes': []}})
    emit({'type': 'item.completed', 'item': {'type': 'agent_message', 'text': answer}}, {'type': 'turn.completed', 'usage': {'output_tokens': 1}})
else:
    chunk = {'type': 'update', 'data': {'update': {'sessionUpdate': 'agent_message_chunk', 'content': {'type': 'text', 'text': answer}}}}
    if mode == 'quota': emit({'type': 'runFinished', 'data': {'status': 'error', 'error': quota}}); sys.exit(1)
    emit(chunk, {'type': 'runFinished', 'data': {'status': 'success', 'stopReason': 'end_turn', 'finalTextTruncated': False}})
'''


class ProviderFixture(Fixture):
    """A project, a state root, and three fake CLIs (claude, codex, kiro) that log every call into one file."""
    def setUp(self):
        super().setUp()
        self.fake = Path(self.temp.name) / 'fake'; self.fake.mkdir()
        script = self.fake / 'fake_cli.py'
        script.write_text(FAKE, encoding='utf-8')
        env = patch.dict(os.environ, {providers.CLI_ENV[p]: json.dumps([sys.executable, str(script), p]) for p in ('codex', 'kiro')})
        env.start(); self.addCleanup(env.stop)
        patcher = patch.object(reviewer, 'cli_argv', lambda env: [sys.executable, str(script), 'claude'])
        patcher.start(); self.addCleanup(patcher.stop)
        self.mode('ok')

    def mode(self, value):
        (self.fake / 'mode.txt').write_text(value)

    def reply(self, text):
        (self.fake / 'answer.txt').write_text(text, encoding='utf-8')

    def calls(self):
        path = self.fake / 'calls.jsonl'
        return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()] if path.exists() else []

    def events_of(self, kind):
        return [p for k, p in self.events() if k == kind]

    def blob(self, key):
        return json.loads(Snapshots(self.ledger.state_root).read_blob(key))

    # -- reviewer
    def start_review(self, provider, model=None, author=AUTHOR, **config):
        value = plan_json(milestones=[reviewer_milestone(model or MODELS[provider], provider=provider, **config)])
        plans.propose(self.ledger, 'P1', value, author)
        plans.approve(self.ledger, 'P1', 'owner', 'said yes in chat')
        (self.root / 'a.txt').write_text('one\ntwo\n')

    def review(self, provider, text=None, **kw):
        self.start_review(provider, **kw)
        self.reply(text if text is not None else reviewer_answer(row('R1'), row('R2')))
        return verdict.run(self.ledger, 'P1', 'M1', self.root)

    def review_receipt(self):
        recorded = self.events_of('verdict.recorded')[-1]
        return recorded, self.blob(recorded['receipt'])

    # -- advisor
    def start_advice(self, provider, model=None, author='claude-fable-5-1'):
        advisor.init_rules(self.ledger)
        value = sourced(plan_json(), decisions=[DECISION], advisor={'provider': provider, 'model': model or ADVISOR_MODELS[provider]})
        plans.propose(self.ledger, 'P1', value, author)

    def advice(self):
        with self.ledger.transaction() as conn:
            return plans.derive(self.ledger, conn, 'P1')['advice'].get(1)


# ---- E17: the contract ------------------------------------------------------------------------------------------------------

class ContractTests(Fixture):
    def test_e17_the_three_providers_with_a_model_are_accepted_for_reviewer_and_advisor(self):
        for provider, model in MODELS.items():
            with self.subTest(provider):
                value = plan_json(milestones=[reviewer_milestone(model, provider=provider)], advisor={'provider': provider, 'model': model})
                out = contracts.validate(value)
                config = out['milestones'][0]['verifier']['config']
                self.assertEqual((config['provider'], config['model']), (provider, model))
                self.assertEqual(out['advisor'], {'provider': provider, 'model': model})
                self.assertEqual(lint.lint(self.ledger, value), [])

    def test_e17_another_provider_or_a_missing_model_is_refused_by_lint(self):
        no_model = reviewer_milestone(); del no_model['verifier']['config']['model']
        bad = {
            'reviewer provider outside the three': plan_json(milestones=[reviewer_milestone(provider='gemini')]),
            'reviewer without model': plan_json(milestones=[no_model]),
            'reviewer codex without model': plan_json(milestones=[dict(no_model, verifier={'type': 'reviewer', 'config': dict(no_model['verifier']['config'], provider='codex')})]),
            'advisor provider outside the three': plan_json(advisor={'provider': 'gemini', 'model': 'gemini-2.5-pro'}),
            'advisor without model': plan_json(advisor={'provider': 'codex'}),
            'advisor bad model': plan_json(advisor={'provider': 'kiro', 'model': '--trust-all-tools'}),
            'advisor extra key': plan_json(advisor={'provider': 'claude', 'model': 'claude-opus-5-5', 'tools': 'all'}),
        }
        for label, value in bad.items():
            with self.subTest(label):
                with self.assertRaises(LedgerError): contracts.validate(value)
                found = lint.lint(self.ledger, value)
                self.assertTrue(found and found[0][0] == 'schema', found)

    def test_a_contract_without_an_advisor_stays_as_before(self):
        self.assertNotIn('advisor', contracts.validate(plan_json()))


# ---- E2, E15: the command is read-only -------------------------------------------------------------------------------------------

WRITE_FLAGS = ('--full-auto', '--dangerously-bypass-approvals-and-sandbox', 'workspace-write', 'danger-full-access', '--yolo', '--trust-all-tools',
               '--trust-tools=fs_write', '--trust-tools=execute_bash')


class CommandShapeTests(unittest.TestCase):
    def test_e2_codex_is_exec_read_only(self):
        argv, stdin = providers.build_argv('codex', ['codex'], 'gpt-5-codex', 'PROMPT')
        self.assertEqual(argv[:4], ['codex', 'exec', '-s', 'read-only'])
        self.assertEqual(argv[argv.index('-m') + 1], 'gpt-5-codex')
        self.assertEqual(stdin, 'PROMPT')                                   # on stdin, never in the command line
        self.assertFalse([flag for flag in WRITE_FLAGS if flag in argv])

    def test_e2_kiro_trusts_only_fs_read(self):
        argv, _ = providers.build_argv('kiro', ['kiro-cli'], 'claude-haiku-4.5', 'PROMPT')
        self.assertEqual(argv[:4], ['kiro-cli', 'chat', '--no-interactive', '--trust-tools=fs_read'])
        self.assertEqual(argv[argv.index('--model') + 1], 'claude-haiku-4.5')
        self.assertEqual([a for a in argv if a.startswith('--trust')], ['--trust-tools=fs_read'])
        self.assertFalse([flag for flag in WRITE_FLAGS if flag in argv])
        self.assertEqual(argv[-1], 'PROMPT')                                # a short prompt is the argument the v1 adapter verified

    def test_a_long_kiro_prompt_goes_on_stdin_not_in_the_command_line(self):
        argv, stdin = providers.build_argv('kiro', ['kiro-cli'], 'm', 'x' * (providers.KIRO_ARG_CAP + 1))
        self.assertEqual(stdin, 'x' * (providers.KIRO_ARG_CAP + 1))
        self.assertTrue(all(len(a) < 200 for a in argv))

    def test_a_missing_cli_names_the_places_searched_and_does_not_fall_back(self):
        for provider in ('codex', 'kiro'):
            with self.assertRaises(LedgerError) as caught:
                providers.cli_prefix(provider, {'PATH': ''}, config_env={}, which=lambda *a, **k: None, exists=lambda p: False)
            self.assertIn(providers.PROGRAM[provider], str(caught.exception))
            self.assertIn(providers.CLI_ENV[provider], str(caught.exception))

    def test_a_configured_command_is_a_path_or_a_json_prefix(self):
        self.assertEqual(providers.cli_prefix('codex', {}, config_env={'ONECREW_CODEX_CLI': r'C:\x\codex.exe'}), [r'C:\x\codex.exe'])
        self.assertEqual(providers.cli_prefix('codex', {}, config_env={'ONECREW_CODEX_CLI': '["py", "fake.py"]'}), ['py', 'fake.py'])
        with self.assertRaises(LedgerError): providers.cli_prefix('codex', {}, config_env={'ONECREW_CODEX_CLI': '[1]'})


# ---- E4: independence by vendor ---------------------------------------------------------------------------------------------------

class IndependenceTests(ProviderFixture):
    def refused_before_the_call(self, provider, model, author=AUTHOR):
        self.start_review(provider, model, author)
        self.reply(reviewer_answer(row('R1'), row('R2')))
        with self.assertRaises(LedgerError) as caught: verdict.run(self.ledger, 'P1', 'M1', self.root)
        self.assertEqual(self.calls(), [], 'a refused reviewer must cost no call')
        self.assertNotIn('verdict.recorded', self.kinds())
        return str(caught.exception)

    def test_e4_codex_is_another_vendor_than_a_claude_author(self):
        self.review('codex')
        self.assertEqual(self.review_receipt()[0]['independence'], 'cross_vendor')

    def test_e4_claude_with_the_authors_own_model_is_refused_before_the_call(self):
        self.assertIn('would be the author', self.refused_before_the_call('claude', AUTHOR))

    def test_e4_kiro_is_judged_by_the_model_it_runs(self):
        self.assertIn('would be the author', self.refused_before_the_call('kiro', AUTHOR))                    # same vendor, same model (dotted spelling too)
        self.setUp()
        self.assertIn('would be the author', self.refused_before_the_call('kiro', 'claude-sonnet-5.5'))
        self.setUp()
        self.review('kiro', model='claude-haiku-4.5')                                                           # same vendor, another model
        self.assertEqual(self.review_receipt()[0]['independence'], 'same_vendor_other_model')
        self.setUp()
        self.review('kiro', model='gemini-2.5-pro')                                                             # another vendor
        self.assertEqual(self.review_receipt()[0]['independence'], 'cross_vendor')

    def test_e4_same_vendor_with_an_unknown_author_model_is_refused(self):
        self.assertIn('author model', self.refused_before_the_call('kiro', 'claude-haiku-4.5', author='claude'))

    def test_e4_a_codex_author_is_not_independent_of_a_codex_reviewer_of_the_same_model(self):
        self.assertIn('would be the author', self.refused_before_the_call('codex', 'gpt-5-codex', author='gpt-5-codex'))

    def test_e4_the_advisor_follows_the_same_rule(self):
        self.start_advice('kiro', 'claude-fable-5-1')                                                           # the author's own model
        self.reply(advisor_answers())
        with self.assertRaises(LedgerError): advisor.advise(self.ledger, 'P1')
        self.assertEqual(self.calls(), [])
        self.assertNotIn('plan.advised', self.kinds())


# ---- E1, E3, E19: the six cells; changing provider is a field -----------------------------------------------------------------------------

class MatrixTests(ProviderFixture):
    def test_e19_e3_each_provider_as_reviewer_runs_through_its_cli_with_a_receipt_of_provider_and_model(self):
        for provider in providers.PROVIDERS:
            with self.subTest(provider):
                self.setUp()
                view = self.review(provider)
                self.assertEqual(view['milestones'][0]['state'], 'passed')
                recorded, receipt = self.review_receipt()
                self.assertEqual((recorded['provider'], recorded['model'], recorded['result'], recorded['calls']), (provider, MODELS[provider], 'pass', 1))
                self.assertEqual((receipt['provider'], receipt['model'], receipt['role']), (provider, MODELS[provider], 'reviewer'))
                self.assertEqual((receipt['config']['provider'], receipt['config']['model']), (provider, MODELS[provider]))
                call, = self.calls()
                self.assertEqual(call['provider'], provider)
                self.assertNotEqual(Path(call['cwd']).resolve(), self.root.resolve(), 'the CLI runs in an empty scratch directory, not the project')
                self.assertEqual(call['listing'], [])
                self.assertIn('+two', call['stdin'] + ' '.join(call['args']))                                      # the diff reached the model, by stdin or argument

    def test_e19_e3_each_provider_as_advisor_runs_through_its_cli_with_a_receipt_of_provider_and_model(self):
        for provider in providers.PROVIDERS:
            with self.subTest(provider):
                self.setUp()
                self.start_advice(provider)
                self.reply(advisor_answers())
                advisor.advise(self.ledger, 'P1')
                event = self.advice()
                self.assertEqual((event['provider'], event['model'], event['usable'], event['provider_error']), (provider, ADVISOR_MODELS[provider], True, None))
                receipt = self.blob(event['receipt'])
                self.assertEqual((receipt['provider'], receipt['model'], receipt['role'], receipt['calls']), (provider, ADVISOR_MODELS[provider], 'advisor', 1))
                call, = self.calls()
                self.assertEqual(call['provider'], provider)
                self.assertEqual(call['listing'], [])

    def test_e1_e13_two_contracts_that_differ_only_in_the_provider_and_model_fields_both_run(self):
        """The same contract text with two values in the same two fields; nothing else is edited. (E13: no code change is needed.)"""
        def contract(provider):
            return plan_json(milestones=[reviewer_milestone(MODELS[provider], provider=provider)])
        a, b = contract('claude'), contract('codex')
        flat = lambda value: json.dumps(value, sort_keys=True).replace('claude-haiku-5-5', 'M').replace('gpt-5-codex', 'M').replace('"claude"', '"P"').replace('"codex"', '"P"')
        self.assertEqual(flat(a), flat(b))
        for provider in ('claude', 'codex'):
            self.setUp()
            self.assertEqual(self.review(provider)['milestones'][0]['state'], 'passed')

    def test_e1_the_advisor_provider_is_also_one_field(self):
        for provider in ('claude', 'codex'):
            self.setUp()
            self.start_advice(provider)
            self.reply(advisor_answers())
            advisor.advise(self.ledger, 'P1')              # no flag: the contract's advisor decides
            self.assertEqual(self.advice()['provider'], provider)
            self.assertEqual([c['provider'] for c in self.calls()], [provider])

    def test_the_command_line_can_name_the_advisor_provider_for_a_contract_without_one(self):
        advisor.init_rules(self.ledger)
        plans.propose(self.ledger, 'P1', sourced(plan_json(), decisions=[DECISION]), 'claude-fable-5-1')
        self.reply(advisor_answers())
        advisor.advise(self.ledger, 'P1', 'gpt-5-codex', 'codex')
        self.assertEqual((self.advice()['provider'], self.advice()['model']), ('codex', 'gpt-5-codex'))
        with self.assertRaises(LedgerError): advisor.advise(self.ledger, 'P1', None, 'kiro')                 # no model for it anywhere: asked, not guessed

    def test_the_old_default_is_kept_a_contract_without_advisor_asks_claude_with_the_default_model(self):
        advisor.init_rules(self.ledger)
        plans.propose(self.ledger, 'P1', sourced(plan_json(), decisions=[DECISION]), 'claude-fable-5-1')
        self.reply(advisor_answers())
        advisor.advise(self.ledger, 'P1')
        self.assertEqual((self.advice()['provider'], self.advice()['model']), ('claude', 'claude-opus-5-5'))


# ---- E5, E12: a usage limit is inconclusive and the provider is not switched -----------------------------------------------------------------

class QuotaTests(ProviderFixture):
    def test_e5_e12_reviewer_quota_is_inconclusive_with_a_reason_and_no_other_provider_is_tried(self):
        for provider in providers.PROVIDERS:
            with self.subTest(provider):
                self.setUp()
                self.mode('quota')
                view = self.review(provider)
                self.assertNotEqual(view['milestones'][0]['state'], 'passed')
                recorded, receipt = self.review_receipt()
                self.assertEqual((recorded['result'], recorded['provider'], recorded['provider_error']), ('inconclusive', provider, 'quota_exhausted'))
                self.assertEqual(receipt['provider_error'], 'quota_exhausted')
                self.assertIn('usage limit', receipt['error'])
                self.assertIn(provider, receipt['error'])
                self.assertEqual([c['provider'] for c in self.calls()], [provider], 'exactly one call, to the pinned provider')
                self.assertEqual(self.events_of('verdict.recorded')[-1]['model'], MODELS[provider])

    def test_e5_e12_advisor_quota_is_typed_inconclusive_and_reported_and_does_not_block_approval(self):
        for provider in providers.PROVIDERS:
            with self.subTest(provider):
                self.setUp()
                self.start_advice(provider)
                self.mode('quota')
                advisor.advise(self.ledger, 'P1')
                event = self.advice()
                self.assertEqual((event['provider_error'], event['usable'], event['provider']), ('quota_exhausted', False, provider))
                self.assertTrue(all(a['verdict'] == 'inconclusive' for a in event['answers']))
                self.assertIn('usage limit', event['answers'][0]['note'])
                self.assertEqual([c['provider'] for c in self.calls()], [provider])
                self.assertEqual(plans.approve(self.ledger, 'P1', 'owner', 'said yes')['status'], 'approved')      # T09a: provider errors do not block
                self.assertEqual(self.advice()['provider'], provider)                                              # and the pin did not move

    def test_a_missing_cli_is_inconclusive_too_not_a_switch(self):
        with patch.dict(os.environ, {'ONECREW_CODEX_CLI': json.dumps([str(self.fake / 'no-such-codex')])}):
            self.review('codex')
        recorded, receipt = self.review_receipt()
        self.assertEqual((recorded['result'], receipt['provider_error']), ('inconclusive', 'provider_unavailable'))
        self.assertEqual(self.calls(), [])

    def test_garbage_output_is_inconclusive_never_a_pass(self):
        for provider in providers.PROVIDERS:
            with self.subTest(provider):
                self.setUp()
                self.mode('tooloutput')
                self.review(provider)
                self.assertEqual(self.review_receipt()[0]['result'], 'inconclusive')


# ---- E15: a provider that tries to change something is not an answer --------------------------------------------------------------------------

class ReadOnlyTests(ProviderFixture):
    def test_e15_a_codex_file_change_is_an_error_not_a_pass(self):
        self.mode('filechange')
        self.review('codex')
        recorded, receipt = self.review_receipt()
        self.assertEqual(recorded['result'], 'inconclusive')
        self.assertIn('file_change', receipt['error'])

    def test_e15_nothing_is_written_in_the_project_by_any_provider(self):
        for provider in providers.PROVIDERS:
            with self.subTest(provider):
                self.setUp()
                self.start_review(provider)
                self.reply(reviewer_answer(row('R1'), row('R2')))
                before = self.git('status', '--porcelain')
                verdict.run(self.ledger, 'P1', 'M1', self.root)
                self.assertEqual(self.git('status', '--porcelain'), before)

    def test_a_kiro_prompt_over_the_command_line_cap_still_reaches_the_cli_on_stdin(self):
        self.start_review('kiro')
        (self.root / 'a.txt').write_text('one\ntwo\n' + ''.join(f'line {n} of padding to make the diff long\n' for n in range(500)))
        self.reply(reviewer_answer(row('R1'), row('R2')))
        verdict.run(self.ledger, 'P1', 'M1', self.root)
        call, = self.calls()
        self.assertGreater(len(call['stdin']), providers.KIRO_ARG_CAP)
        self.assertTrue(all(len(a) < 200 for a in call['args']))


# ---- E6, E7 -----------------------------------------------------------------------------------------------------------------------------------

class OwnerManualAndNotDeciderTests(ProviderFixture):
    def test_e6_the_owner_manual_milestone_runs_as_before_next_to_a_codex_reviewer(self):
        manual = {'id': 'M1', 'title': 'Looks right', 'verifier': {'type': 'owner-manual'}, 'covers': ['O1']}
        review = reviewer_milestone(MODELS['codex'], provider='codex'); review['id'] = 'M2'
        plans.propose(self.ledger, 'P1', plan_json(milestones=[manual, review]), AUTHOR)
        plans.approve(self.ledger, 'P1', 'owner', 'said yes in chat')
        (self.root / 'a.txt').write_text('one\ntwo\n')                                # the work first: both verdicts are about this tree
        blob = Snapshots(self.ledger.state_root).blob('Checked on the device by the owner.\n'.encode())
        for by in ('claude', 'codex', 'reviewer'):                                    # nobody but the owner records an owner-manual verdict
            with self.assertRaises(LedgerError): verdict.record(self.ledger, 'P1', 'M1', 'pass', by, blob, self.tree())
        self.assertEqual(self.calls(), [])
        self.assertEqual(verdict.record(self.ledger, 'P1', 'M1', 'pass', 'owner', blob, self.tree())['milestones'][0]['state'], 'passed')
        self.reply(reviewer_answer(row('R1'), row('R2')))
        view = verdict.run(self.ledger, 'P1', 'M2', self.root)
        self.assertEqual([m['state'] for m in view['milestones']], ['passed', 'passed'])
        self.assertEqual([c['provider'] for c in self.calls()], ['codex'])

    def test_e7_a_stray_field_such_as_skip_is_not_a_decision(self):
        for provider in providers.PROVIDERS:
            with self.subTest(provider):
                self.setUp()
                stray = json.loads(reviewer_answer(row('R1'), row('R2')))
                stray.update({'SKIP': True, 'decision': {'kind': 'SKIP', 'reason': 'trivial'}, 'REVIEW': 'later', 'HOLD': True})
                self.review(provider, json.dumps(stray))
                self.assertEqual(self.review_receipt()[0]['result'], 'pass')
                kinds = set(self.kinds())
                self.assertFalse({k for k in kinds if 'decision' in k or 'skip' in k.lower()}, kinds)
                self.assertTrue(set(self.events_of('verdict.recorded')[-1]) .isdisjoint({'SKIP', 'decision', 'REVIEW', 'HOLD'}))

    def test_e7_a_verdict_word_that_is_not_pass_fail_inconclusive_is_inconclusive(self):
        for word in ('SKIP', 'DEFER', 'REVIEW', 'HOLD'):
            with self.subTest(word):
                self.setUp()
                self.review('codex', reviewer_answer(row('R1', word), row('R2')))
                self.assertEqual(self.review_receipt()[0]['result'], 'inconclusive')
                self.assertFalse([k for k in self.kinds() if 'decision' in k])

    def test_e7_the_advisor_answers_ok_or_objection_and_a_stray_verdict_is_inconclusive(self):
        self.start_advice('codex')
        stray = json.loads(advisor_answers())
        stray['SKIP'] = True
        stray['answers'][0]['verdict'] = 'SKIP'
        self.reply(json.dumps(stray))
        advisor.advise(self.ledger, 'P1')
        self.assertEqual([a['verdict'] for a in self.advice()['answers']][0], 'inconclusive')
        self.assertFalse(self.advice()['usable'])
        self.assertFalse([k for k in self.kinds() if 'decision' in k])


# ---- what W45 will record about a real CLI -----------------------------------------------------------------------------------------------------

class IdentityTests(ProviderFixture):
    def test_unreadable_execution_alias_is_explicitly_unverified(self):
        with patch.object(providers, 'sha256_file', side_effect=OSError(22, 'execution alias')):
            identity = providers.cli_identity('codex', dict(os.environ))
        self.assertIsNone(identity['sha256'])
        self.assertEqual(identity['files'], {})
        self.assertTrue(identity['identity_errors'])
        self.assertEqual(identity['version'], 'fake-codex 0.0.1')

    def test_cli_identity_names_the_executable_by_sha256_and_version(self):
        identity = providers.cli_identity('codex', dict(os.environ))
        script = str(self.fake / 'fake_cli.py')
        self.assertEqual(identity['provider'], 'codex')
        self.assertEqual(identity['version'], 'fake-codex 0.0.1')
        self.assertEqual(identity['sha256'], providers.sha256_file(sys.executable))
        self.assertEqual(identity['files'][script], providers.sha256_file(script))
        self.assertEqual(self.calls(), [], '--version is not a review call')


if __name__ == '__main__':
    unittest.main()
