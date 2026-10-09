import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from onecrew.control import Control
from onecrew.ledger import Ledger, LedgerError, content_hash
from onecrew.specs import Project
from onecrew.workflow import Workflow, validate_plan, validate_profile, task_lock

ROOT = Path(__file__).resolve().parents[1]
TEMP = ROOT / '.onecrew/workflow-tests'
SAMPLE = (ROOT/'specs/SPEC-001-duyet-spec.md').read_text(encoding='utf-8')


class FixtureWorker:
    def __init__(self, ledger, responses):
        self.control = Control(ledger)
        self.responses = responses
        self.calls = []

    def capability(self):
        return {'provider': 'fixture', 'mode': 'test-only'}

    def run(self, attempt, prompt, schema, profile):
        self.calls.append(json.loads(attempt['operation'])['stage'])
        value = self.responses[len(self.calls)-1]
        self.control.launched(attempt['id'], attempt['generation'], {'fixture': True})
        self.control.finish(attempt['id'], attempt['generation'], {'fixture': value})

    def result(self, attempt):
        return json.loads(attempt['result'])['fixture'], []


def profile():
    return {'version': 1, 'context': ['settings.json', 'README.txt'],
            'owned': ['settings.json', 'README.txt'],
            'acceptance': [{'id': 'AC-CONFIG', 'description': 'Enabled with maximum two workers.'},
                           {'id': 'AC-DOC', 'description': 'Document how to start.'}],
            'checks': [{'id': 'config', 'acceptance': ['AC-CONFIG'], 'kind': 'json_equal',
                        'path': 'settings.json', 'expected': {'enabled': True, 'workers': 2}},
                       {'id': 'doc', 'acceptance': ['AC-DOC'], 'kind': 'text_equal',
                        'path': 'README.txt', 'expected': 'Start OneCrew.\n'}],
            'max_repairs': 1, 'model': 'fixture', 'step_seconds': 30}


def plan():
    return {'summary': 'Configuration then instructions.', 'tasks': [
        {'id': 'config', 'title': 'Configure', 'depends_on': [], 'owned': ['settings.json'], 'acceptance': ['AC-CONFIG']},
        {'id': 'doc', 'title': 'Document', 'depends_on': ['config'], 'owned': ['README.txt'], 'acceptance': ['AC-DOC']}]}


def artifact(path, content):
    return {'summary': 'Implemented assigned file.', 'files': [{'path': path, 'content': content}], 'backlog': []}


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        TEMP.mkdir(parents=True, exist_ok=True)
        self.base = Path(tempfile.mkdtemp(dir=TEMP)).resolve()
        self.project = self.base/'project'
        (self.project/'specs').mkdir(parents=True)
        (self.project/'specs/SPEC-001-duyet-spec.md').write_text(SAMPLE, encoding='utf-8')
        self.ledger = Ledger(self.project, self.base/'state')
        grant = {'schema_version': 1, 'permissions': ['artifact.generate'],
                 'limits': {'max_calls': 6, 'max_seconds': 300}, 'source': 'fixture'}
        self.task = self.ledger.submit('SPEC-001', Project(self.project).find('SPEC-001').revision, 'fixture', grant)
        self.worker = FixtureWorker(self.ledger, [plan(), artifact('settings.json', '{"enabled":true,"workers":2}'),
                                                  artifact('README.txt', 'Start OneCrew.\n')])
        self.workflow = Workflow(self.ledger, self.worker)

    def tearDown(self):
        self.assertTrue(self.base.is_relative_to(TEMP.resolve()))
        shutil.rmtree(self.base)

    def enable(self):
        return self.workflow.enable(self.task['id'], self.task['revision'], profile())

    def test_general_plan_partial_output_and_final_review_survive_restart(self):
        self.enable()
        first = self.workflow.run(self.task['id'], steps=2)
        self.assertEqual(first['done'], ['config'])
        card = self.workflow.outputs(self.task['id'])['outputs'][0]
        self.assertIn('enabled', card['diff'])
        with task_lock(self.ledger, self.task['id']):
            self.workflow.review(self.task['id'], card['revision'], 'feedback', 'Continue documentation.')
        self.assertEqual(len(self.workflow.outputs(self.task['id'])['reviews']), 1)
        self.workflow = Workflow(Ledger(self.project, self.base/'state'), self.worker)
        done = self.workflow.run(self.task['id'])
        self.assertEqual(done['phase'], 'completed')
        self.assertEqual(done['acceptance'], 'pending')
        self.assertFalse((self.project/'settings.json').exists())
        self.assertEqual(self.worker.calls, ['plan', 'config', 'doc'])
        self.assertEqual(self.workflow.control.status(self.task['id'])['used_calls'], 3)
        self.workflow.run(self.task['id'])
        self.assertEqual(len(self.worker.calls), 3)
        with self.assertRaises(LedgerError):
            self.workflow.review(self.task['id'], card['revision'], 'accept', 'Old output')
        self.workflow.review(self.task['id'], done['snapshot'], 'accept', 'Reviewed configured checks.')
        self.assertEqual(self.ledger.task(self.task['id'])['acceptance'], 'accepted')

    def test_crash_after_worker_receipt_reuses_output_without_another_call(self):
        self.enable()
        with patch.object(self.worker, 'result', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.workflow.run(self.task['id'])
        self.assertEqual(len(self.worker.calls), 1)
        self.workflow = Workflow(self.ledger, self.worker)
        self.assertEqual(self.workflow.run(self.task['id'])['phase'], 'completed')
        self.assertEqual(len(self.worker.calls), 3)

    def test_parse_scope_failure_keeps_source_and_snapshot_then_bounded_retry(self):
        initial = self.enable()
        self.worker.responses[1] = artifact('../outside', 'unsafe')
        failed = self.workflow.run(self.task['id'])
        self.assertEqual(failed['phase'], 'blocked')
        self.assertEqual(failed['snapshot'], initial['snapshot'])
        self.assertEqual(self.workflow.control.status(self.task['id'])['used_calls'], 2)
        self.workflow.resume(self.task['id'])
        self.worker.responses[2] = artifact('settings.json', '{"enabled":true,"workers":2}')
        self.worker.responses.append(artifact('README.txt', 'Start OneCrew.\n'))
        self.assertEqual(self.workflow.run(self.task['id'])['phase'], 'completed')
        self.assertEqual(self.workflow.control.status(self.task['id'])['used_calls'], 4)

    def test_repair_is_bounded_and_no_progress_does_not_loop(self):
        self.enable()
        self.worker.responses[1] = artifact('settings.json', '{"enabled":false,"workers":2}')
        self.worker.responses.append(artifact('settings.json', '{"enabled":false,"workers":2}'))
        failed = self.workflow.run(self.task['id'])
        self.assertEqual(failed['phase'], 'blocked')
        self.assertIn('No source progress', failed['message'])
        self.assertEqual(len(self.worker.calls), 4)

    def test_true_is_not_numeric_one_and_repair_changes_only_owned_files(self):
        self.enable()
        self.worker.responses[1] = artifact('settings.json', '{"enabled":1,"workers":2}')
        self.worker.responses.append(artifact('settings.json', '{"enabled":true,"workers":2}'))
        result = self.workflow.run(self.task['id'])
        self.assertEqual(result['phase'], 'completed')
        self.assertEqual(result['repairs'], 1)
        self.assertEqual(self.worker.calls[-1], 'repair')

    def test_pause_resume_reorder_preserves_dependencies_and_budget(self):
        self.enable()
        state = self.workflow.run(self.task['id'], steps=1)
        before = self.workflow.control.status(self.task['id'])
        revision = content_hash(state['plan'])
        self.workflow.reorder(self.task['id'], revision, ['doc', 'config'])
        with self.assertRaises(LedgerError):
            self.workflow.reorder(self.task['id'], revision, ['config', 'doc'])
        self.workflow.control.pause(self.task['id'])
        self.workflow.run(self.task['id'])
        self.assertEqual(len(self.worker.calls), 1)
        self.workflow.resume(self.task['id'])
        self.workflow.run(self.task['id'])
        self.assertEqual(self.worker.calls, ['plan', 'config', 'doc'])
        self.assertEqual(self.workflow.control.status(self.task['id'])['deadline'], before['deadline'])

    def test_checkpoint_disk_failure_never_publishes_completed(self):
        self.enable()
        with patch.object(self.workflow.store, 'overlay', side_effect=OSError('disk full')):
            failed = self.workflow.run(self.task['id'])
        self.assertEqual(failed['phase'], 'blocked')
        self.assertEqual(failed['outputs'], [])
        self.assertEqual(self.ledger.task(self.task['id'])['verification'], 'pending')

    def test_controller_lock_rejects_duplicate_runner(self):
        self.enable()
        with task_lock(self.ledger, self.task['id']):
            with self.assertRaises(LedgerError):
                self.workflow.run(self.task['id'])

    def test_strict_profile_plan_schema_and_no_scope_expansion(self):
        bad = profile()
        bad['max_repairs'] = True
        with self.assertRaises(LedgerError):
            validate_profile(bad)
        bad = plan()
        bad['tasks'][0]['depends_on'] = ['doc']
        with self.assertRaises(LedgerError):
            validate_plan(bad, profile())
        bad = plan()
        bad['tasks'][0]['owned'] = ['outside']
        with self.assertRaises(LedgerError):
            validate_plan(bad, profile())
        bad = profile()
        bad['checks'][0]['kind'] = 'shell'
        with self.assertRaises(LedgerError):
            validate_profile(bad)

    def test_invalid_planner_response_retries_once_under_root_budget(self):
        self.enable()
        bad = plan()
        bad['tasks'][0]['acceptance'] = ['AC-CONFIG: description is not an ID']
        self.worker.responses.insert(0, bad)
        state = self.workflow.run(self.task['id'])
        self.assertEqual(state['phase'], 'completed')
        self.assertEqual(self.worker.calls, ['plan', 'plan', 'config', 'doc'])
        self.assertEqual(state['failed_calls'], 1)
        self.assertEqual(len(state['usage']), 4)

    def test_crash_after_enable_configuration_preserves_original_snapshot(self):
        (self.project/'README.txt').write_text('original')
        with patch.object(self.workflow, 'persist', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.enable()
        (self.project/'README.txt').write_text('changed by user')
        state = self.enable()
        self.assertEqual(self.workflow.store.context(state['base'])['README.txt'], 'original')
        self.assertEqual((self.project/'README.txt').read_text(), 'changed by user')

    def test_switch_requires_current_checkpoint_and_keeps_root_counters(self):
        self.enable()
        state = self.workflow.run(self.task['id'], steps=2)
        before = self.workflow.control.status(self.task['id'])
        with patch('onecrew.providers.make_worker', return_value=self.worker):
            receipt = self.workflow.switch(self.task['id'], content_hash(state), 'kiro', 'fixture-next')
            with self.assertRaises(LedgerError):
                self.workflow.switch(self.task['id'], content_hash(state), 'codex', 'fixture')
        self.assertEqual(receipt['used_calls'], before['used_calls'])
        self.assertEqual(receipt['deadline'], before['deadline'])
        after = self.workflow.run(self.task['id'])
        self.assertEqual(after['phase'], 'completed')
        self.assertEqual(after['handoffs'][0]['snapshot'], state['snapshot'])
        self.assertEqual(self.workflow.control.status(self.task['id'])['used_calls'], 3)

    def test_switch_rejects_unreconciled_attempt(self):
        self.enable()
        with patch.object(self.worker, 'run', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.workflow.run(self.task['id'])
        _, state = self.workflow.state(self.task['id'])
        with self.assertRaises(LedgerError):
            self.workflow.switch(self.task['id'], content_hash(state), 'kiro', 'anything')

    def test_global_two_worker_pressure_queues_without_calls_then_continues(self):
        self.enable()
        handoff = self.ledger.task(self.task['id'], full=True)['handoff']
        held = []
        for number in range(2):
            task = self.ledger.submit('SPEC-001', handoff['spec_revision'], 'occupied-'+str(number), handoff['grant'])
            config = self.workflow.control.configure(task['id'], task['revision'], {'fixture': True})
            held.append(self.workflow.control.reserve(task['id'], config['revision'], 'occupied', {'test': True}))
        waiting = self.workflow.run(self.task['id'])
        self.assertEqual(waiting['waiting_reason'], 'capacity')
        self.assertEqual(self.worker.calls, [])
        self.assertEqual(self.ledger.task(self.task['id'])['execution'], 'waiting')
        for attempt in held:
            self.workflow.control.finish(attempt['id'], attempt['generation'], {'not_started': True}, not_started=True)
        self.assertEqual(self.workflow.run(self.task['id'])['phase'], 'completed')


if __name__ == '__main__':
    unittest.main()
