"""QC MVP-1 state machine on the native path: candidate from a Git ref -> scope -> install -> fixed gate -> one independent
review -> verified_technical_only / rejected. No worker call writes anything; nothing is applied to the project."""
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests import test_owned as fixtures
from onecrew.ledger import LedgerError
from onecrew.owned import Owned
from onecrew.owned_intake import submit
from onecrew import qc_gate
from tests.test_workflow import FixtureWorker

BASE_MAIN = 'int add(int a,int b)=>a-b;\n'
GOOD_MAIN = 'int add(int a,int b)=>a+b;\n'
GOOD_TEST = '// regression test for add\n'


def git(repo, *args):
    env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
    env.update(GIT_AUTHOR_NAME='t', GIT_AUTHOR_EMAIL='t@example.invalid', GIT_COMMITTER_NAME='t', GIT_COMMITTER_EMAIL='t@example.invalid')
    done = subprocess.run(['git', '-c', 'core.autocrlf=false', '-C', str(repo), *args], capture_output=True, env=env, check=True)
    return done.stdout.decode().strip()


class QcFixture(unittest.TestCase):
    author = 'claude-code'

    def setUp(self):
        self.f = fixtures.OwnedTests(); self.f.setUp(); self.addCleanup(self.f.doCleanups)
        self.root = self.f.root
        app = self.root / 'app'
        (app / 'lib').mkdir(parents=True); (app / 'test').mkdir(); (app / '.dart_tool').mkdir()
        (app / 'lib/main.dart').write_text(BASE_MAIN)
        (app / 'lib/other.dart').write_text('int two()=>2;\n')
        (app / 'test/main_test.dart').write_text('// base test\n')
        (app / 'pubspec.yaml').write_text('name: app\n')
        (app / '.dart_tool/package_config.json').write_text(json.dumps(
            {'configVersion': 2, 'packages': [{'name': 'app', 'rootUri': '../', 'packageUri': 'lib/'}]}))
        (app / '.dart_tool/package_graph.json').write_text(json.dumps(
            {'configVersion': 1, 'roots': ['app'], 'packages': [{'name': 'app', 'version': '1.0.0', 'dependencies': []}]}))
        (self.root / '.gitignore').write_text('.dart_tool/\n')
        git(self.root, 'init', '-q', '-b', 'master'); git(self.root, 'add', '-A'); git(self.root, 'commit', '-q', '-m', 'base')
        self.base = git(self.root, 'rev-parse', 'HEAD')
        self.recipe = dict(source_roots=['app'], owned=['app/lib/main.dart', 'app/test/main_test.dart'], extra_sources={},
            package='app', flutter_root=str(Path(self.f.temp.name) / 'flutter'), tests=['app/test/main_test.dart'],
            reference='QC fixture', trusted_native=True)
        self.report = Path(self.f.temp.name) / 'report.md'
        self.report.write_text('Fixed add and added a regression test. All tests passed on my machine.\n', encoding='utf-8')

    def candidate(self, name, files, parent=None):
        """Commit `files` on branch `name` in a throw-away worktree so the project checkout is never touched."""
        tree = Path(self.f.temp.name) / ('wt-' + name)
        git(self.root, 'worktree', 'add', '-q', '-b', name, str(tree), parent or self.base)
        for path, data in files.items():
            target = tree / path; target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data if isinstance(data, bytes) else data.encode())
        git(tree, 'add', '-A'); git(tree, 'commit', '-q', '-m', name)
        head = git(tree, 'rev-parse', 'HEAD')
        git(self.root, 'worktree', 'remove', '--force', str(tree))
        return head

    def good(self, name='cand'):
        return self.candidate(name, {'app/lib/main.dart': GOOD_MAIN, 'app/test/main_test.dart': GOOD_TEST})

    def task(self, ref='cand', responses=(), provider='claude', model='sonnet', author_model=None, key='qc-1', **extra):
        qc = qc_gate.make(self.root, ref, self.recipe, report=self.report, author=self.author, author_model=author_model,
                          reviewer_provider=provider, reviewer_model=model, **extra)
        from tests.test_solution_gate import approve_fixture
        self.binding = getattr(self, 'binding', None) or approve_fixture(self.f.ledger)
        task = submit(self.f.ledger, 'QC of ' + ref, key, mode='change', provider=provider, model=model,
                      native_change=self.recipe, qc=qc, max_calls=6, **self.binding)
        self.worker = FixtureWorker(self.f.ledger, list(responses))
        self.prompts = []
        original = self.worker.run
        def spy(attempt, prompt, schema, profile):
            self.prompts.append(prompt); return original(attempt, prompt, schema, profile)
        self.worker.run = spy
        self.run = Owned(self.f.ledger, self.worker); self.run.enable(task['id'])
        self.task_id = task['id']
        return task['id']

    def drive(self, patched=None, limit=12):
        """Run one step at a time (as the runner would) until the task settles; `patched` replaces the fixed gate."""
        state = None
        for _ in range(limit):
            if patched is not None:
                with patch('onecrew.native_change.verify', side_effect=patched):
                    state = self.run.run(self.task_id, steps=1)
            else:
                state = self.run.run(self.task_id, steps=1)
            if state['phase'] in ('completed', 'blocked', 'failed', 'cancelled'):
                return state
        self.fail('did not settle: ' + str(state['phase']) + ' ' + str(state.get('message')))

    def passing_gate(self, runtime, task_id, state, recipe):
        return {'passed': True, 'detail': 'All tests passed!', 'failure_kind': None,
                'evidence': {'snapshot': state['snapshot'], 'exit_code': 0, 'stdout': 'blob-out', 'stderr': 'blob-err', 'argv': ['dart', 'test']}}

    def failing_gate(self, runtime, task_id, state, recipe):
        return {'passed': False, 'detail': 'Expected: 5 Actual: 4 (main_test.dart)', 'failure_kind': 'test',
                'evidence': {'snapshot': state['snapshot'], 'exit_code': 1, 'stdout': 'blob-out', 'stderr': 'blob-err', 'argv': ['dart', 'test']}}

    def project_unchanged(self):
        self.assertEqual((self.root / 'app/lib/main.dart').read_text(), BASE_MAIN)
        self.assertEqual(git(self.root, 'rev-parse', 'HEAD'), self.base)
        self.assertEqual(git(self.root, 'status', '--porcelain=v1'), '')


class VerifiedPathTests(QcFixture):
    def test_good_candidate_is_verified_technical_only_with_one_review_call_and_no_apply(self):
        head = self.good()
        self.task(responses=[{'accepted': True, 'feedback': 'Regression test exercises add.'}])
        with patch('onecrew.native_change.apply', side_effect=AssertionError('QC must never apply')):
            state = self.drive(self.passing_gate)
        self.assertEqual(state['phase'], 'completed')
        self.assertEqual(state['verification'], 'passed')
        self.assertEqual(state['acceptance'], 'not_requested')
        qc = state['qc']
        self.assertEqual(qc['verdict'], 'verified_technical_only')
        self.assertEqual(qc['reasons'], [])
        self.assertEqual((qc['head'], qc['base'], qc['author'], qc['branch']), (head, self.base, 'claude-code', 'cand'))
        self.assertIsNone(qc['plan'])
        self.assertEqual(qc['review_index'], 0)
        self.assertEqual(qc['gate_receipt']['exit_code'], 0)
        self.assertEqual(qc['independence']['level'], 'same_vendor_unknown_model')
        self.assertEqual(len(qc['report_sha']), 64)
        self.assertEqual(self.worker.calls, ['native_change_review'])  # the only model call; no worker call at all
        self.assertEqual(self.run.control.status(self.task_id)['used_calls'], 1)
        self.assertFalse(state.get('workspace_applied'))
        self.assertEqual(state['native_change']['stage'], 'completed')
        self.project_unchanged()

    def test_candidate_bytes_come_from_the_ref_into_the_gate_workspace(self):
        self.good()
        self.task(responses=[{'accepted': True, 'feedback': 'ok'}])
        seen = {}
        def gate(runtime, task_id, state, recipe):
            work = Path(state['native_change']['workspace'])
            seen['main'] = (work / 'app/lib/main.dart').read_text(); seen['test'] = (work / 'app/test/main_test.dart').read_text()
            return self.passing_gate(runtime, task_id, state, recipe)
        self.drive(gate)
        self.assertEqual((seen['main'], seen['test']), (GOOD_MAIN, GOOD_TEST))

    def test_agent_report_does_not_decide_the_gate_and_is_marked_untrusted_for_the_reviewer(self):
        self.good()
        self.task(responses=[{'accepted': False, 'feedback': 'The test asserts nothing.'}])
        state = self.drive(self.passing_gate)  # report says "All tests passed"; the reviewer still decides
        self.assertEqual(state['qc']['verdict'], 'rejected')
        prompt = self.prompts[0]
        self.assertIn('outside OneCrew', prompt)
        self.assertIn('claude-code', prompt)
        self.assertIn('untrusted', prompt.lower())


class RejectedPathTests(QcFixture):
    def test_scope_rejection_costs_no_call_and_lists_every_reason(self):
        self.candidate('cand', {'app/lib/other.dart': 'int two()=>22;\n'})
        self.task()
        state = self.drive()
        self.assertEqual(state['phase'], 'completed')
        self.assertEqual(state['verification'], 'rejected')
        self.assertEqual(state['qc']['verdict'], 'rejected')
        codes = sorted(r['code'] for r in state['qc']['reasons'])
        self.assertEqual(codes, ['no_production_change', 'no_test_change', 'path_outside_owned'])
        self.assertEqual(state['qc']['stage'], 'scope')
        self.assertEqual(self.worker.calls, [])
        self.assertEqual(self.run.control.status(self.task_id)['used_calls'], 0)
        self.assertNotIn('native_change', state)  # nothing was even captured
        self.project_unchanged()

    def test_gate_failure_rejects_without_repair_or_review(self):
        self.good()
        self.task()
        state = self.drive(self.failing_gate)
        self.assertEqual(state['phase'], 'completed')
        self.assertEqual(state['verification'], 'rejected')
        self.assertEqual(state['qc']['stage'], 'gate')
        self.assertEqual([r['code'] for r in state['qc']['reasons']], ['gate_failed'])
        self.assertIn('Expected: 5', state['qc']['reasons'][0]['detail'])
        self.assertEqual(state['qc']['gate_receipt']['exit_code'], 1)
        self.assertEqual(state['native_change']['repairs'], 0)
        self.assertEqual(self.worker.calls, [])
        self.project_unchanged()

    def test_review_rejection_ends_the_task_instead_of_starting_a_repair_loop(self):
        self.good()
        self.task(responses=[{'accepted': False, 'feedback': 'Test only checks its own helper.'}])
        state = self.drive(self.passing_gate)
        self.assertEqual(state['phase'], 'completed')
        self.assertEqual(state['verification'], 'rejected')
        self.assertEqual(state['qc']['stage'], 'review')
        self.assertEqual(state['qc']['reasons'][0]['code'], 'review_rejected')
        self.assertIn('own helper', state['qc']['reasons'][0]['detail'])
        self.assertEqual(state['qc']['review_index'], 0)
        self.assertEqual(state['native_change']['repairs'], 0)
        self.assertEqual(self.worker.calls, ['native_change_review'])
        self.project_unchanged()

    def test_content_the_policy_refuses_is_a_rejection_not_a_repair(self):
        self.candidate('cand', {'app/lib/main.dart': "password = 'long-fixture-value';\n", 'app/test/main_test.dart': GOOD_TEST})
        self.task()
        state = self.drive(self.passing_gate)
        self.assertEqual(state['verification'], 'rejected')
        self.assertEqual(state['qc']['stage'], 'install')
        self.assertEqual(state['qc']['reasons'][0]['code'], 'install_rejected')
        self.assertNotIn('long-fixture-value', json.dumps(state['qc']))
        self.assertEqual(state['native_change']['repairs'], 0)
        self.assertEqual(self.worker.calls, [])

    def test_project_head_moved_since_submit_is_a_rejection(self):
        self.good()
        self.task()
        (self.root / 'app/lib/other.dart').write_text('int two()=>3;\n')
        git(self.root, 'commit', '-q', '-am', 'project moved on')
        state = self.drive(self.passing_gate)
        self.assertEqual(state['verification'], 'rejected')
        self.assertEqual([r['code'] for r in state['qc']['reasons']], ['base_moved'])
        self.assertEqual(self.worker.calls, [])

    def test_environment_failure_of_the_gate_blocks_it_is_not_a_verdict(self):
        self.good()
        self.task()
        def environment(runtime, task_id, state, recipe):
            return {'passed': False, 'detail': 'Flutter dependency cache incomplete', 'failure_kind': 'environment',
                    'evidence': {'snapshot': state['snapshot'], 'exit_code': 1}}
        state = self.drive(environment)
        self.assertEqual(state['phase'], 'blocked')
        self.assertNotIn('verdict', state.get('qc', {}))
        self.assertEqual(self.worker.calls, [])


class OtherReadersTests(QcFixture):
    def test_the_new_rejected_value_is_accepted_by_the_places_that_read_verification(self):
        self.candidate('cand', {'app/lib/other.dart': 'int two()=>22;\n'})
        self.task()
        state = self.drive()
        self.assertEqual(state['verification'], 'rejected')
        task = self.f.ledger.task(self.task_id, full=True)
        self.assertEqual(task['verification'], 'rejected')
        from onecrew.entry import connect
        packet = connect(self.f.ledger, self.task_id)
        self.assertEqual(packet['outputs']['items'][-1]['verification'], 'rejected')
        from onecrew.budget_policy import recommend
        self.assertEqual(recommend(self.f.ledger, 'QC of cand', 'change', 'claude', 'sonnet')['classification'], 'insufficient_history')
        from onecrew.learning import outcomes
        self.assertEqual([o['verification'] for o in outcomes(self.f.ledger, 5)], ['rejected'])
        from onecrew import desktop_notifications
        items = desktop_notifications.snapshots(self.f.ledger, task=self.task_id)
        self.assertTrue(items)
        text = desktop_notifications.text_report(items[-1])
        self.assertIn('QC verdict: rejected', text)
        self.assertIn('path_outside_owned', text)
        from onecrew.eval_scorecard import completion_level
        level, gaps = completion_level({'phase': 'completed', 'verification': 'rejected', 'metrics': {}})
        self.assertEqual(level, 'partial')
        self.assertEqual(gaps, ['verification_rejected'])


class IndependenceTests(unittest.TestCase):
    def test_other_vendor_is_cross_vendor(self):
        got = qc_gate.independence('codex-cli', None, None, 'claude', 'sonnet')
        self.assertEqual(got['level'], 'cross_vendor')
        self.assertEqual(qc_gate.independence('x', 'kiro', None, 'claude', 'sonnet')['level'], 'cross_vendor')

    def test_same_vendor_other_model_is_labelled_with_the_reason(self):
        got = qc_gate.independence('claude-code', 'claude', 'opus', 'claude', 'sonnet')
        self.assertEqual(got['level'], 'same_vendor_other_model')
        self.assertIn('native', got['note'])

    def test_same_provider_and_model_is_refused(self):
        with self.assertRaises(LedgerError):
            qc_gate.independence('claude-code', 'claude', 'sonnet', 'claude', 'sonnet')

    def test_vendor_comes_from_the_author_name_when_not_given(self):
        self.assertEqual(qc_gate.independence('claude-code', None, 'sonnet', 'claude', 'opus')['level'], 'same_vendor_other_model')
        self.assertEqual(qc_gate.independence('Claude Code', None, None, 'claude', 'opus')['level'], 'same_vendor_unknown_model')
        self.assertEqual(qc_gate.independence('some-tool', None, None, 'claude', 'opus')['level'], 'unknown_author_vendor')

    def test_only_a_native_capable_reviewer_provider_is_accepted(self):
        with self.assertRaises(LedgerError):
            qc_gate.independence('claude-code', None, None, 'codex', 'gpt')


class SubmitValidationTests(QcFixture):
    def test_qc_needs_a_native_change_recipe_and_a_matching_reviewer(self):
        self.good()
        qc = qc_gate.make(self.root, 'cand', self.recipe, report=self.report, author='claude-code',
                          reviewer_provider='claude', reviewer_model='sonnet')
        from tests.test_solution_gate import approve_fixture
        with self.assertRaises(LedgerError):
            submit(self.f.ledger, 'x', 'k1', mode='change', provider='claude', model='sonnet', qc=qc, image='sha256:' + 'a' * 64,
                   **approve_fixture(self.f.ledger))
        with self.assertRaises(LedgerError):  # the recorded reviewer is not the profile that will run the review
            submit(self.f.ledger, 'x', 'k2', mode='change', provider='claude', model='opus', native_change=self.recipe, qc=qc,
                   **approve_fixture(self.f.ledger, 'sol2'))

    def test_replay_with_the_same_key_returns_the_same_task(self):
        self.good()
        first = self.task(key='same')
        again = self.task(key='same')
        self.assertEqual(first, again)

    def test_make_records_supersedes_and_report_hash_without_raising_on_scope_failure(self):
        self.candidate('cand', {'app/lib/other.dart': 'x\n'})
        qc = qc_gate.make(self.root, 'cand', self.recipe, report=self.report, author='claude-code',
                          reviewer_provider='claude', reviewer_model='sonnet', supersedes='TASK-old')
        self.assertEqual(qc['supersedes'], 'TASK-old')
        self.assertTrue(qc['reasons'])
        self.assertEqual(len(qc['report_sha']), 64)


if __name__ == '__main__':
    unittest.main()
