"""Generic work contracts (13/10/2026): the user controls goal, scope, invariants, acceptance and authority; OneCrew
chooses how. Regressions for the rigid points found in the survey (c3a35dc): exact-name branch at a pinned HEAD, edits and
host commands in an isolated workspace, independent verification, preserved user repository, durable effects, no
provider change, provider-sized prompts. Each test drives the public runtime with a scripted worker (no model call)."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from onecrew.ledger import Ledger, LedgerError
from onecrew.owned import Owned
from onecrew.owned_intake import submit
from tests.test_workflow import FixtureWorker


def action(_name, **args):
    return {'plan': 'Survey, act within the contract, verify, report.', 'action': _name, 'arguments': json.dumps(args)}


ACCEPT = {'accepted': True, 'feedback': 'Every acceptance item is backed by receipts.', 'evidence_requests': []}


def python():
    from onecrew.work_tools import which
    try: return str(which('python', os.environ.get('PATH', '')))
    except LedgerError: return None


class WorkFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        self.root = base / 'project'; self.root.mkdir()
        self.ledger = Ledger(self.root, base / 'state')
        os.environ['ONECREW_WORK_ROOT'] = str(base / 'w'); self.addCleanup(os.environ.pop, 'ONECREW_WORK_ROOT', None)
        (self.root / 'calc.py').write_text('def add(a, b):\n    return a - b\n')
        (self.root / 'test_calc.py').write_text('import unittest\nfrom calc import add\n\n\nclass T(unittest.TestCase):\n'
                                                '    def test_add(self):\n        self.assertEqual(add(2, 3), 5)\n')
        self.git('init', '-q'); self.git('config', 'user.name', 'Fixture'); self.git('config', 'user.email', 'f@localhost')
        self.git('add', '.'); self.git('commit', '-q', '-m', 'baseline')
        self.head = self.git('rev-parse', 'HEAD').strip()
        # The user's own state that must be preserved: a dirty file, an untracked file and a stash entry.
        (self.root / 'notes.txt').write_text('stash me\n'); self.git('add', 'notes.txt'); self.git('stash', '-q')
        (self.root / 'calc.py').write_text('def add(a, b):\n    return a - b  # user is editing\n')
        (self.root / 'scratch.txt').write_text('untracked\n')

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.root), *args], stderr=subprocess.PIPE).decode()

    def contract(self, **authority):
        value = {'schema_version': 1, 'goal': 'Fixture goal', 'acceptance': ['The requested outcome exists and is verified.'],
                 'preserve': ['checkout, uncommitted source and stash'],
                 'authority': authority, 'authorized_by': {'source': 'user', 'reference': 'fixture'}}
        return value

    def job(self, contract, responses, provider='kiro', model='claude-sonnet-5', key='work'):
        task = submit(self.ledger, None, key, mode='work', provider=provider, model=model, contract=contract)
        worker = FixtureWorker(self.ledger, responses)
        runtime = Owned(self.ledger, worker); runtime.enable(task['id'])
        return runtime, task['id'], worker

    def snapshot(self):
        return {'status': self.git('status', '--porcelain=v1', '--untracked-files=all'), 'head': self.git('rev-parse', 'HEAD'),
                'branch': self.git('symbolic-ref', '--short', 'HEAD'), 'stash': self.git('stash', 'list'),
                'calc': (self.root / 'calc.py').read_bytes(), 'index': (self.root / '.git' / 'index').read_bytes()}


class ContractTests(WorkFixture):
    def test_contract_rejects_push_unknown_fields_bad_names_and_missing_authorization(self):
        from onecrew.work_contract import validate
        good = self.contract(local_branches=['production'])
        self.assertEqual(validate(good, self.root)['authority']['local_branches'], ['production'])
        for bad in (dict(good, extra=1), dict(good, authority={'push': True}), dict(good, authority={'local_branches': ['a..b']}),
                    dict(good, authority={'local_branches': ['HEAD']}), {k: v for k, v in good.items() if k != 'authorized_by'},
                    dict(good, acceptance=[]), dict(good, checks=[{'kind': 'command', 'argv': ['x']}])):
            with self.assertRaises(LedgerError): validate(bad, self.root)

    def test_work_job_is_admitted_without_a_separate_solution_and_keeps_the_pinned_provider(self):
        runtime, task, _ = self.job(self.contract(local_branches=['production']), [])
        record = self.ledger.task(task, full=True)
        self.assertEqual(record['handoff']['owned_execution']['provider'], 'kiro')
        self.assertNotIn('fallbacks', record['handoff']['owned_execution'])
        self.assertEqual(record['handoff']['grant']['permissions'], ['discover', 'report', 'git.branch'])
        state = runtime.state(task)[1]
        self.assertEqual(state['work']['pins']['head'], self.head.strip())
        self.assertIsNone(state['work']['workspace'])  # branch-only contract: no workspace, nothing cloned

    def test_legacy_branch_mode_is_unchanged(self):
        with self.assertRaises(LedgerError): submit(self.ledger, 'x', 'legacy', mode='branch', branch='production')


class BranchTests(WorkFixture):
    def test_exact_name_branch_at_pinned_head_preserves_checkout_source_stash_and_index(self):
        before = self.snapshot()
        contract = dict(self.contract(local_branches=['production']), checks=[{'kind': 'ref', 'name': 'production', 'equals': 'pinned_head'}])
        runtime, task, worker = self.job(contract, [action('git_status'), action('create_branch', name='production'),
                                                    action('finish', report='Created local branch production at the pinned HEAD; receipt 1.'), ACCEPT])
        state = runtime.run(task)
        self.assertEqual(state['phase'], 'completed', state['message'])
        self.assertEqual(self.git('rev-parse', 'refs/heads/production').strip(), self.head.strip())
        self.assertEqual(self.snapshot(), before, 'RED-GX-BRANCH: the user checkout/source/stash/index changed')
        self.assertEqual(state['work']['verification']['findings'], [])
        receipt = state['work']['branches'][0]['receipt']
        self.assertEqual((receipt['status'], receipt['result']['executor']), ('verified', 'onecrew-core'))
        self.assertTrue(Path(state['work']['handover']['summary']).is_file())
        self.assertEqual(worker.calls, ['owned', 'owned', 'owned', 'owned_review'])

    def test_existing_ref_is_reported_never_overwritten_and_unauthorized_names_or_commits_refused(self):
        self.git('branch', 'production', self.head.strip() + '~0')
        (self.root / 'x.txt').write_text('x'); old = self.git('rev-parse', 'refs/heads/production')
        runtime, task, _ = self.job(self.contract(local_branches=['production', 'staging']), [])
        state = runtime.state(task)[1]
        from onecrew import work_tools as wt
        contract = runtime.control.status(task)['configuration']['profile']['contract']
        self.assertEqual(wt.create_branch(runtime, task, state, contract, {'name': 'production'})['status'], 'exists')
        self.assertEqual(self.git('rev-parse', 'refs/heads/production'), old)
        for args in ({'name': 'main2'}, {'name': 'staging', 'commit': '0' * 40}):
            with self.assertRaises(LedgerError): wt.create_branch(runtime, task, state, contract, args)

    def test_lost_ack_is_reconciled_without_a_second_update_ref(self):
        runtime, task, _ = self.job(self.contract(local_branches=['production']), [])
        state = runtime.state(task)[1]
        from onecrew import work_tools as wt
        contract = runtime.control.status(task)['configuration']['profile']['contract']
        wt.create_branch(runtime, task, state, contract, {'name': 'production'})
        with self.ledger.transaction(write=True) as conn:
            conn.execute("UPDATE actions SET status='unknown',receipt=NULL WHERE task_id=?", (task,))
        with patch('onecrew.work_tools.git', wraps=wt.git) as calls:
            receipt = wt.create_branch(runtime, task, dict(state, work=dict(state['work'], branches=[])), contract, {'name': 'production'})
        self.assertTrue(receipt.get('reconciled'))
        self.assertFalse(any('update-ref' in c.args for c in calls.call_args_list))


@unittest.skipIf(python() is None, 'needs a real Python interpreter on PATH')
class WorkspaceTests(WorkFixture):
    def fix_flow(self, verification, extra=()):
        py = python()
        responses = [action('read', path='calc.py'), *extra]
        return py, responses

    def test_edit_run_verify_handover_in_workspace_without_touching_the_project(self):
        py = python(); before = self.snapshot()
        contract = self.contract(edit=True, commands=True)
        runtime, task, worker = self.job(contract, [])
        state = runtime.state(task)[1]
        workspace = Path(state['work']['workspace']['path'])
        source = (workspace / 'calc.py').read_bytes()
        import hashlib
        worker.responses = [
            action('run', argv=[py, '-m', 'unittest', '-v']),
            action('edit', path='calc.py', expected_sha256=hashlib.sha256(source).hexdigest(), old='a - b', new='a + b'),
            action('write', path='test_add.py', expected_sha256=None,
                   text='import unittest\nfrom calc import add\n\n\nclass A(unittest.TestCase):\n    def test_add(self):\n        self.assertEqual(add(2, 3), 5)\n'),
            action('run', argv=[py, '-m', 'unittest', '-v']),
            action('finish', report='Fixed add (receipt 1), added test_add (2); unittest 4 tests pass (3).',
                   verification=[{'argv': [py, '-m', 'unittest', '-v'], 'cwd': ''}]), ACCEPT]
        state = runtime.run(task)
        self.assertEqual(state['phase'], 'completed', state['message'])
        commands = state['work']['verification']['commands']
        self.assertTrue(commands[0]['passed']); self.assertEqual(commands[0]['tests']['passed_or_run'], 2)
        self.assertEqual(self.snapshot(), before, 'RED-GX-WS: the project changed although apply was not granted')
        patch_text = Path(state['work']['handover']['patch']).read_text()
        self.assertIn('+    return a + b', patch_text); self.assertIn('test_add.py', patch_text)
        with self.ledger.transaction() as conn:
            facts = [json.loads(r['payload']) for r in conn.execute("SELECT payload FROM events WHERE kind='project.fact'")]
        self.assertEqual(facts[0]['argv'], [py, '-m', 'unittest', '-v'])

    def test_independent_verification_rejects_false_claims_without_a_review_call(self):
        py = python()
        runtime, task, worker = self.job(self.contract(edit=True, commands=True), [
            action('finish', report='All tests pass and the bug is fixed (claimed without evidence).',
                   verification=[{'argv': [py, '-m', 'unittest', '-v'], 'cwd': ''}])])
        state = runtime.run(task, steps=1)
        self.assertNotEqual(state['phase'], 'completed')
        self.assertEqual(worker.calls, ['owned'], 'RED-GX-VERIFY: a failing re-run still reached the model review')
        self.assertTrue(any('core re-run failed' in f for f in state['work']['verification']['findings']))

    def test_deleted_modified_or_skipped_tests_and_zero_tests_are_findings(self):
        py = python()
        runtime, task, _ = self.job(self.contract(edit=True, commands=True), [])
        state = runtime.state(task)[1]
        workspace = Path(state['work']['workspace']['path'])
        contract = runtime.control.status(task)['configuration']['profile']['contract']
        from onecrew import work_tools as wt
        with self.assertRaises(LedgerError):  # existing tests are immutable under this contract
            wt.write(state, contract, {'path': 'test_calc.py', 'expected_sha256': None, 'text': ''})
        (workspace / 'test_calc.py').unlink()
        (workspace / 'test_new.py').write_text('import unittest\n\n@unittest.skip("later")\nclass S(unittest.TestCase):\n    def test_x(self):\n        pass\n')
        result = wt.verify(runtime, task, state, contract, {'verification': [{'argv': [py, '-m', 'unittest', 'test_new', '-v']}]}, lambda: None)
        text = ' | '.join(result['findings'])
        self.assertIn('existing test file deleted: test_calc.py', text)
        self.assertIn('skip/only marker added', text)
        self.assertIn('all tests skipped', text)

    def test_project_changed_during_the_job_is_not_reported_as_preserved(self):
        runtime, task, _ = self.job(self.contract(edit=True), [])
        state = runtime.state(task)[1]
        contract = runtime.control.status(task)['configuration']['profile']['contract']
        (self.root / 'scratch.txt').write_text('someone edited it')
        from onecrew import work_tools as wt
        result = wt.verify(runtime, task, state, contract, {}, lambda: None)
        self.assertTrue(any('uncommitted source changed' in f for f in result['findings']))

    def test_authority_is_enforced_by_the_core(self):
        py = python()
        runtime, task, worker = self.job(self.contract(edit=True), [
            action('run', argv=[py, '-c', 'print(1)']), action('run', argv=[py, '-c', 'print(2)'])])
        state = runtime.run(task, steps=2)
        self.assertEqual(state['phase'], 'blocked'); self.assertEqual(state['recovery']['kind'], 'permission')
        runtime2, task2, _ = self.job(self.contract(edit=True, commands=True), [], key='w2')
        state2 = runtime2.state(task2)[1]
        contract = runtime2.control.status(task2)['configuration']['profile']['contract']
        from onecrew import work_tools as wt
        for argv in ([py, '-c', 'print(1)', str(self.root / 'calc.py')], ['git', 'push', 'origin', 'HEAD'],
                     ['git', 'config', '--global', 'user.name', 'x']):
            with self.assertRaises(LedgerError): wt.run(runtime2, task2, state2, contract, {'argv': argv}, lambda: None)
        scoped = dict(contract, scope={'repository': '', 'paths': ['src']})
        with self.assertRaises(LedgerError): wt.write(state2, scoped, {'path': 'calc2.py', 'expected_sha256': None, 'text': 'x'})

    def test_background_process_is_contained_and_stopped(self):
        py = python()
        runtime, task, _ = self.job(self.contract(commands=True), [])
        state = runtime.state(task)[1]
        contract = runtime.control.status(task)['configuration']['profile']['contract']
        from onecrew import work_tools as wt
        started = wt.run(runtime, task, state, contract, {'argv': [py, '-c', 'import time; time.sleep(60)'], 'background': True}, lambda: None)
        self.assertEqual(wt.process(runtime, task, state, {'id': started['id']})['status'], 'running')
        self.assertEqual(wt.process(runtime, task, state, {'id': started['id'], 'op': 'stop'})['status'], 'stopped')

    def test_apply_and_export_need_authority_and_never_overwrite_user_edits(self):
        py = python()
        (self.root / 'calc.py').write_text('def add(a, b):\n    return a - b\n')  # user reverts their edit
        runtime, task, _ = self.job(self.contract(edit=True, commands=True, apply_to_project=True, local_branches=['fix/add']), [])
        state = runtime.state(task)[1]
        contract = runtime.control.status(task)['configuration']['profile']['contract']
        workspace = Path(state['work']['workspace']['path'])
        (workspace / 'calc.py').write_text('def add(a, b):\n    return a + b\n')
        from onecrew import work_tools as wt
        wt.workspace_commit(state, contract, {'message': 'Fix add'})
        exported = wt.export_branch(runtime, task, state, contract, {'name': 'fix/add'})
        self.assertEqual(exported['status'], 'verified')
        self.assertEqual(self.git('symbolic-ref', '--short', 'HEAD').strip(), 'master' if 'master' in self.git('branch') else self.git('symbolic-ref', '--short', 'HEAD').strip())
        receipt = wt.apply(runtime, task, state, contract, {})
        self.assertEqual(receipt['status'], 'verified')
        self.assertIn('a + b', (self.root / 'calc.py').read_text())
        runtime2, task2, _ = self.job(self.contract(edit=True, apply_to_project=True), [], key='w3')
        state2 = runtime2.state(task2)[1]
        contract2 = runtime2.control.status(task2)['configuration']['profile']['contract']
        (Path(state2['work']['workspace']['path']) / 'calc.py').write_text('changed in workspace\n')
        with self.assertRaises(LedgerError): wt.apply(runtime2, task2, state2, contract2, {})  # project calc.py differs from the pin


class DurabilityTests(WorkFixture):
    def test_coordinator_restart_continues_without_repeating_effects_or_calls(self):
        responses = [action('git_status'), action('create_branch', name='production'),
                     action('finish', report='Created local branch production at the pinned HEAD; receipt 1.'), ACCEPT]
        runtime, task, worker = self.job(dict(self.contract(local_branches=['production']),
                                              checks=[{'kind': 'ref', 'name': 'production', 'equals': 'pinned_head'}]), responses)
        state = runtime.run(task, steps=2)  # the coordinator dies after the branch was created
        self.assertEqual(state['work']['branches'][0]['receipt']['status'], 'verified')
        restarted = Owned(self.ledger, worker)  # a new coordinator process: nothing carried in memory
        state = restarted.run(task)
        self.assertEqual(state['phase'], 'completed', state['message'])
        with self.ledger.transaction() as conn:
            actions = conn.execute("SELECT COUNT(*) FROM actions WHERE task_id=?", (task,)).fetchone()[0]
        self.assertEqual(actions, 1, 'RED-GX-RESTART: the branch effect was proposed twice')
        self.assertEqual(worker.calls, ['owned', 'owned', 'owned', 'owned_review'])

    @unittest.skipIf(python() is None, 'needs a real Python interpreter on PATH')
    def test_verified_commands_of_a_completed_job_are_offered_to_the_next_job_as_hints(self):
        py = python()
        runtime, task, worker = self.job(self.contract(commands=True), [
            action('finish', report='Survey only: the unit tests run with python -m unittest (receipt 0).',
                   verification=[{'argv': [py, '-m', 'unittest', 'test_calc', '-v'], 'cwd': ''}])], key='first')
        state = runtime.run(task, steps=1)
        self.assertNotEqual(state['phase'], 'completed')  # the baseline test fails: verification keeps it open
        (self.root / 'test_ok.py').write_text('import unittest\n\n\nclass O(unittest.TestCase):\n    def test_ok(self):\n        self.assertTrue(True)\n')
        self.git('add', 'test_ok.py'); self.git('commit', '-q', '-m', 'ok test')
        runtime2, task2, worker2 = self.job(self.contract(commands=True), [
            action('finish', report='Survey only: test_ok runs with python -m unittest test_ok (receipt 0).',
                   verification=[{'argv': [py, '-m', 'unittest', 'test_ok', '-v'], 'cwd': ''}]), ACCEPT], key='second')
        self.assertEqual(runtime2.run(task2)['phase'], 'completed')
        runtime3, task3, _ = self.job(self.contract(commands=True), [], key='third')
        state3 = runtime3.state(task3)[1]
        profile = runtime3.control.status(task3)['configuration']['profile']
        from onecrew.owned import contract
        tool_prompt, schema, _ = contract(profile)
        prompt = runtime3._work_prompt(task3, state3, profile, runtime3.control.status(task3), tool_prompt, schema, [])
        self.assertIn('verified_project_commands_untrusted_hints', prompt); self.assertIn('test_ok', prompt)

    def test_kiro_reply_with_prose_around_the_json_is_parsed_and_a_reply_without_json_is_refused(self):
        from onecrew.providers import kiro_stream
        def stream(text):
            chunk = {'type': 'sessionUpdate', 'data': {'update': {'sessionUpdate': 'agent_message_chunk', 'content': {'type': 'text', 'text': text}}}}
            done = {'type': 'runFinished', 'data': {'status': 'success', 'stopReason': 'end_turn', 'finalTextTruncated': False}}
            return json.dumps(chunk) + '\n' + json.dumps(done)
        answer = {'plan': 'Read report.py', 'action': 'read', 'arguments': '{"path":"report.py"}'}
        for text in ('I need to see report.py first.\n\n```json\n' + json.dumps(answer) + '\n```',   # A5-r1 attempt 3
                     'I have not read report.py yet.\n\n' + json.dumps(answer),                        # A5-r1 attempt 4
                     json.dumps(answer), '```json\n' + json.dumps(answer) + '\n```'):
            self.assertEqual(kiro_stream(stream(text))[0], answer, 'RED-GX-A5: ' + text[:40])
        with self.assertRaises(LedgerError): kiro_stream(stream('No JSON here, only prose.'))
        with self.assertRaises(LedgerError): kiro_stream(stream(json.dumps(answer) + '\nand then more prose'))

    def test_unverified_kiro_version_stays_unavailable(self):
        from onecrew import providers
        class Done:
            returncode = 0; stdout = b''; stderr = b''
        with patch('onecrew.providers.executable', return_value='C:/kiro-cli.exe'), \
                patch('onecrew.providers.subprocess.check_output', return_value=b'kiro-cli-chat 9.9.9'), \
                patch('onecrew.providers.subprocess.run', return_value=Done()):
            result = providers.doctor('kiro')
        self.assertFalse(result['available']); self.assertIn('verify_kiro_cli', result['reason'])


class PromptTests(WorkFixture):
    def test_finish_offers_verification_commands_only_with_the_commands_authority(self):
        from onecrew.owned import contract
        from onecrew.work_contract import validate
        plain = contract({'mode': 'work', 'contract': validate(self.contract(local_branches=['production']), self.root)})[0]
        full = contract({'mode': 'work', 'contract': validate(self.contract(commands=True), self.root)})[0]
        finish_plain = next(l for l in plain.splitlines() if l.startswith('finish:'))
        finish_full = next(l for l in full.splitlines() if l.startswith('finish:'))
        self.assertNotIn('verification:[', finish_plain, 'RED-GX-A2: finish offered commands the contract does not grant')
        self.assertIn('verification:[', finish_full)

    def test_kiro_prompt_keeps_the_contract_within_the_verified_cap(self):
        runtime, task, worker = self.job(self.contract(edit=True), [])
        state = runtime.state(task)[1]
        big = runtime.store.blob(json.dumps({'action': 'read', 'result': {'path': 'x', 'text': 'y' * 30000}}).encode())
        state['receipts'] = [{'index': i, 'action': 'read', 'blob': big, 'successful': True} for i in range(5)]
        profile = runtime.control.status(task)['configuration']['profile']
        from onecrew.owned import contract
        tool_prompt, schema, _ = contract(profile)
        prompt = runtime._work_prompt(task, state, dict(profile, provider='kiro'), runtime.control.status(task), tool_prompt, schema, [])
        self.assertLessEqual(len(prompt) + len(json.dumps(schema)), 16000)
        self.assertIn('Fixture goal', prompt)
        longer = runtime._work_prompt(task, state, dict(profile, provider='claude'), runtime.control.status(task), tool_prompt, schema, [])
        self.assertGreater(len(longer), len(prompt))


if __name__ == '__main__':
    unittest.main()
