"""`onecrew qc submit|status` against a throw-away project and ledger; the model is a fixture, nothing is spawned."""
import contextlib
import io
import json
import os
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.test_qc_machine import QcFixture, GOOD_MAIN, BASE_MAIN
from tests.test_solution_gate import approve_fixture
from tests.test_workflow import FixtureWorker
from onecrew import qc_cli
from onecrew.owned import Owned


class QcCliFixture(QcFixture):
    def setUp(self):
        super().setUp()
        self.recipe_file = Path(self.f.temp.name) / 'native-change.json'
        self.recipe_file.write_text(json.dumps(self.recipe), encoding='utf-8')
        self.binding = approve_fixture(self.f.ledger)

    def cli(self, *argv, env=None):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), patch.dict(os.environ, env or {}):
            code = qc_cli.main(['--project', str(self.root), '--state-root', str(self.f.ledger.state_root), 'qc', *argv])
        return code, json.loads(out.getvalue())

    def submit(self, ref='cand', key='cli-1', *extra):
        return self.cli('submit', '--key', key, '--branch', ref, '--report', str(self.report), '--recipe', str(self.recipe_file),
                        '--solution-id', self.binding['solution_id'], '--solution-revision', self.binding['solution_revision'],
                        '--author', 'claude-code', '--author-model', 'opus', *extra)

    def run_to_end(self, task_id, responses=(), gate=None, steps=10):
        worker = FixtureWorker(self.f.ledger, list(responses))
        runtime = Owned(self.f.ledger, worker); runtime.enable(task_id)
        state = None
        for _ in range(steps):
            if gate:
                with patch('onecrew.native_change.verify', side_effect=gate):
                    state = runtime.run(task_id, steps=1)
            else:
                state = runtime.run(task_id, steps=1)
            if state['phase'] in ('completed', 'blocked'): break
        return state, worker


class SubmitTests(QcCliFixture):
    def test_submit_creates_a_task_that_carries_the_pinned_candidate(self):
        head = self.good()
        code, out = self.submit()
        self.assertEqual(code, 0, out)
        self.assertTrue(out['id'].startswith('TASK-'))
        self.assertEqual(out['qc']['head'], head)
        self.assertEqual(out['qc']['scope_reasons'], [])
        self.assertEqual(out['qc']['independence']['level'], 'same_vendor_other_model')
        self.assertEqual(out['qc']['reviewer'], {'provider': 'claude', 'model': 'sonnet'})
        stored = self.f.ledger.task(out['id'], full=True)['handoff']['owned_execution']
        self.assertEqual(stored['qc']['head'], head)
        self.assertEqual(stored['native_change']['owned'], self.recipe['owned'])
        self.assertEqual(stored['mode'], 'change')
        self.project_unchanged()

    def test_submit_records_a_control_intervention_with_the_actor(self):
        self.good()
        code, out = self.cli('submit', '--key', 'cli-act', '--branch', 'cand', '--report', str(self.report), '--recipe', str(self.recipe_file),
                             '--solution-id', self.binding['solution_id'], '--solution-revision', self.binding['solution_revision'],
                             '--author', 'claude-code', '--author-model', 'opus', env={'ONECREW_ACTOR': 'claude'})
        self.assertEqual(code, 0, out)
        with self.f.ledger.transaction() as conn:
            rows = [json.loads(r['payload']) for r in conn.execute(
                "SELECT payload FROM events WHERE task_id=? AND kind='control.intervention'", (out['id'],))]
        self.assertEqual([(r['command'], r['actor']) for r in rows], [('qc.submit', 'claude')])
        self.assertEqual(rows[0]['details']['branch'], 'cand')

    def test_a_scope_failure_still_creates_the_task_and_shows_the_reasons_at_once(self):
        self.candidate('cand', {'app/lib/other.dart': 'int two()=>22;\n'})
        code, out = self.submit()
        self.assertEqual(code, 0, out)
        self.assertEqual(sorted(r['code'] for r in out['qc']['scope_reasons']),
                         ['no_production_change', 'no_test_change', 'path_outside_owned'])
        state, worker = self.run_to_end(out['id'])
        self.assertEqual(state['qc']['verdict'], 'rejected')
        self.assertEqual(worker.calls, [])

    def test_unknown_branch_becomes_a_rejection_not_a_crash(self):
        code, out = self.submit('no-such-branch')
        self.assertEqual(code, 0, out)
        self.assertEqual([r['code'] for r in out['qc']['scope_reasons']], ['ref_unresolved'])
        state, _ = self.run_to_end(out['id'])
        self.assertEqual((state['verification'], state['qc']['verdict']), ('rejected', 'rejected'))

    def test_reviewer_equal_to_the_author_is_refused_and_no_task_is_created(self):
        self.good()
        code, out = self.submit('cand', 'cli-self', '--author-provider', 'claude', '--author-model', 'sonnet')
        self.assertEqual(code, 2)
        self.assertIn('reviewer would be the author', out['error'])
        with self.f.ledger.transaction() as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM tasks').fetchone()[0], 0)

    def test_claude_author_without_a_model_is_refused_and_no_task_is_created(self):
        self.good()
        for extra in ([], ['--author-provider', 'claude']):
            with self.subTest(extra=extra):
                code, out = self.cli('submit', '--key', 'cli-nomodel', '--branch', 'cand', '--report', str(self.report),
                                     '--recipe', str(self.recipe_file), '--solution-id', self.binding['solution_id'],
                                     '--solution-revision', self.binding['solution_revision'], '--author', 'claude-code', *extra)
                self.assertEqual(code, 2)
                self.assertIn('--author-model', out['error'])
                self.assertIn('independent', out['error'])
        with self.f.ledger.transaction() as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM tasks').fetchone()[0], 0)

    def test_an_author_of_unknown_vendor_is_still_accepted_and_labelled(self):
        self.good()
        code, out = self.cli('submit', '--key', 'cli-unknown', '--branch', 'cand', '--report', str(self.report),
                             '--recipe', str(self.recipe_file), '--solution-id', self.binding['solution_id'],
                             '--solution-revision', self.binding['solution_revision'], '--author', 'some-script')
        self.assertEqual(code, 0, out)
        self.assertEqual(out['qc']['independence']['level'], 'unknown_author_vendor')

    def test_other_reviewer_model_than_the_author_is_recorded(self):
        self.good()
        code, out = self.submit('cand', 'cli-other', '--author-provider', 'claude', '--author-model', 'opus')
        self.assertEqual(code, 0, out)
        self.assertEqual(out['qc']['independence']['level'], 'same_vendor_other_model')

    def test_non_native_reviewer_provider_is_refused(self):
        self.good()
        code, out = self.submit('cand', 'cli-codex', '--provider', 'codex', '--model', 'gpt-6-luna')
        self.assertEqual(code, 2)
        self.assertIn('Claude only', out['error'])

    def test_the_verdict_cannot_be_set_from_the_command_line(self):
        self.good()
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            self.submit('cand', 'cli-flag', '--verdict', 'verified')

    def test_start_enables_and_dispatches_the_runner_exactly_as_job_start_does(self):
        self.good()
        with patch('onecrew.owned.Owned.enable') as enable, patch('onecrew.runner.start', return_value={'status': 'alive'}) as start:
            code, out = self.submit('cand', 'cli-start', '--start')
        self.assertEqual(code, 0, out)
        enable.assert_called_once_with(out['id'])
        start.assert_called_once()
        self.assertEqual(out['runner'], {'status': 'alive'})

    def test_replay_with_the_same_key_returns_the_same_task(self):
        self.good()
        first = self.submit('cand', 'cli-same')[1]['id']
        self.assertEqual(self.submit('cand', 'cli-same')[1]['id'], first)


class StatusTests(QcCliFixture):
    def test_status_of_a_verified_task_shows_verdict_independence_and_evidence(self):
        self.good()
        task = self.submit()[1]['id']
        before = self.cli('status', task)[1]
        self.assertEqual((before['verdict'], before['phase']), ('pending', 'queued'))
        state, worker = self.run_to_end(task, [{'accepted': True, 'feedback': 'Test exercises add.'}], gate=self.passing_gate)
        code, out = self.cli('status', task)
        self.assertEqual(code, 0, out)
        self.assertEqual(out['verdict'], 'verified_technical_only')
        self.assertEqual(out['phase'], 'completed')
        self.assertEqual(out['reasons'], [])
        self.assertEqual(out['independence']['level'], 'same_vendor_other_model')
        self.assertEqual(out['gate_receipt']['exit_code'], 0)
        self.assertEqual(out['review']['feedback'], 'Test exercises add.')
        self.assertEqual(out['author'], 'claude-code')
        self.assertIn('state_root', out['evidence'])
        self.assertEqual(out['calls'], 1)

    def test_status_of_a_rejected_task_lists_the_reasons(self):
        self.good()
        task = self.submit()[1]['id']
        self.run_to_end(task, [{'accepted': False, 'feedback': 'Vacuous test.'}], gate=self.passing_gate)
        out = self.cli('status', task)[1]
        self.assertEqual(out['verdict'], 'rejected')
        self.assertEqual(out['stage'], 'review')
        self.assertEqual(out['reasons'][0]['code'], 'review_rejected')

    def test_status_refuses_a_task_that_is_not_a_qc_task(self):
        from onecrew.owned_intake import submit
        plain = submit(self.f.ledger, 'plain audit', 'plain')
        code, out = self.cli('status', plain['id'])
        self.assertEqual(code, 2)
        self.assertIn('not a QC task', out['error'])


class ParentOfRepositoryTests(QcCliFixture):
    """cts-port/app layout: the project root is the PARENT of the Git repository, which is the Flutter package itself."""
    def setUp(self):
        from tests import test_owned as fixtures
        from tests.test_qc_machine import git as run_git
        self.f = fixtures.OwnedTests(); self.f.setUp(); self.addCleanup(self.f.doCleanups)
        self.root = self.f.root
        self.repo = self.root / 'flutter_vimes'
        (self.repo / 'lib').mkdir(parents=True); (self.repo / 'test').mkdir(); (self.repo / '.dart_tool').mkdir()
        (self.repo / 'lib/main.dart').write_text(BASE_MAIN)
        (self.repo / 'test/main_test.dart').write_text('// base test\n')
        (self.repo / 'pubspec.yaml').write_text('name: flutter_vimes\n')
        (self.repo / '.gitignore').write_text('.dart_tool/\n')
        (self.repo / '.dart_tool/package_config.json').write_text(json.dumps(
            {'configVersion': 2, 'packages': [{'name': 'flutter_vimes', 'rootUri': '../', 'packageUri': 'lib/'}]}))
        (self.repo / '.dart_tool/package_graph.json').write_text(json.dumps(
            {'configVersion': 1, 'roots': ['flutter_vimes'], 'packages': [{'name': 'flutter_vimes', 'version': '1.0.0', 'dependencies': []}]}))
        run_git(self.repo, 'init', '-q', '-b', 'master'); run_git(self.repo, 'add', '-A'); run_git(self.repo, 'commit', '-q', '-m', 'base')
        self.base = run_git(self.repo, 'rev-parse', 'HEAD')
        run_git(self.repo, 'checkout', '-q', '-b', 'cand')
        (self.repo / 'lib/main.dart').write_text(GOOD_MAIN); (self.repo / 'test/main_test.dart').write_text('// regression test for add\n')
        run_git(self.repo, 'commit', '-q', '-am', 'cand'); self.head = run_git(self.repo, 'rev-parse', 'HEAD')
        run_git(self.repo, 'checkout', '-q', 'master')
        self.recipe = dict(source_roots=['flutter_vimes'], owned=['flutter_vimes/lib/main.dart', 'flutter_vimes/test/main_test.dart'],
            extra_sources={}, package='flutter_vimes', flutter_root=str(Path(self.f.temp.name) / 'flutter'),
            tests=['flutter_vimes/test/main_test.dart'], reference='QC fixture', trusted_native=True)
        self.report = Path(self.f.temp.name) / 'report.md'; self.report.write_text('Fixed add and added a test.\n', encoding='utf-8')
        self.recipe_file = Path(self.f.temp.name) / 'native-change.json'
        self.recipe_file.write_text(json.dumps(self.recipe), encoding='utf-8')
        self.binding = approve_fixture(self.f.ledger)

    def test_submit_resolves_the_repository_below_the_project_and_passes_the_scope_check(self):
        code, out = self.submit()
        self.assertEqual(code, 0, out)
        self.assertEqual(out['qc']['scope_reasons'], [])
        self.assertEqual((out['qc']['head'], out['qc']['base']), (self.head, self.base))

    def test_the_candidate_runs_to_a_verdict_and_the_project_is_untouched(self):
        task = self.submit()[1]['id']
        state, worker = self.run_to_end(task, [{'accepted': True, 'feedback': 'Test exercises add.'}], gate=self.passing_gate)
        self.assertEqual(state['qc']['verdict'], 'verified_technical_only')
        self.assertEqual(worker.calls, ['native_change_review'])
        self.assertEqual((self.repo / 'lib/main.dart').read_text(), BASE_MAIN)

    def test_a_scope_failure_names_the_project_relative_path(self):
        from tests.test_qc_machine import git as run_git
        run_git(self.repo, 'checkout', '-q', '-b', 'wide', self.base)
        (self.repo / 'lib/other.dart').write_text('int two()=>2;\n'); run_git(self.repo, 'add', '-A'); run_git(self.repo, 'commit', '-q', '-m', 'wide')
        run_git(self.repo, 'checkout', '-q', 'master')
        out = self.submit('wide', 'cli-wide')[1]
        paths = [r['path'] for r in out['qc']['scope_reasons'] if r['code'] == 'path_outside_owned']
        self.assertEqual(paths, ['flutter_vimes/lib/other.dart'])


class RouterTests(QcCliFixture):
    def test_the_main_cli_routes_the_qc_group(self):
        from onecrew import cli
        with patch('onecrew.qc_cli.main', return_value=0) as main:
            self.assertEqual(cli.main(['--project', str(self.root), 'qc', 'status', 'TASK-x']), 0)
        main.assert_called_once_with(['--project', str(self.root), 'qc', 'status', 'TASK-x'])


if __name__ == '__main__':
    unittest.main()
