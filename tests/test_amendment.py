import copy
import json
import unittest
from unittest.mock import patch

import test_workflow as fixtures
import test_parallel as dag_fixtures
from onecrew.amendment import apply, affected_tasks, spec_for
from onecrew.ledger import LedgerError, content_hash
from onecrew.specs import Project
from onecrew.workflow import Workflow


class Worker(fixtures.FixtureWorker):
    def __init__(self, ledger):
        super().__init__(ledger, [])
        self.prompts = []

    def run(self, attempt, prompt, schema, profile):
        stage = json.loads(attempt['operation'])['stage']
        self.calls.append(stage)
        self.prompts.append(prompt)
        self.control.launched(attempt['id'], attempt['generation'], {'fixture': True})
        check = next(c for c in profile['checks'] if c['id'] == 'CHECK-'+stage)
        self.control.finish(attempt['id'], attempt['generation'], {'fixture': fixtures.artifact(stage+'.txt', check['expected'])})


class AmendmentTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.WorkflowTests()
        self.f.setUp()
        self.worker = Worker(self.f.ledger)
        self.workflow = Workflow(self.f.ledger, self.worker)
        self.profile = dag_fixtures.profile()
        self.profile.pop('parallel')
        self.profile['context'].append('contract.json')
        (self.f.project/'contract.json').write_text('{"version":1}', encoding='utf-8')
        state = self.workflow.enable(self.f.task['id'], self.f.task['revision'], self.profile)
        self.plan = dag_fixtures.dag()
        self.workflow.set_plan(self.f.task['id'], content_hash(state), self.plan)
        self.workflow.run(self.f.task['id'], steps=3)  # A B C, D not yet run
        self.spec_path = self.f.project/'specs/SPEC-001-duyet-spec.md'
        self.spec_path.write_text(self.spec_path.read_text(encoding='utf-8')+'\nApproved change: B becomes B2.\n', encoding='utf-8')

    def tearDown(self):
        self.f.tearDown()

    def amend(self, profile=None, selected=None, revision=None):
        _, state = self.workflow.state(self.f.task['id'])
        return apply(self.workflow, self.f.task['id'], revision or content_hash(state),
                     Project(self.f.project).find('SPEC-001').revision, profile or self.profile,
                     selected or ['B'], 'Explicit local operator requirement update')

    def test_only_affected_branch_and_descendants_rerun_with_same_budget(self):
        before = self.workflow.control.status(self.f.task['id'])
        old = self.workflow.state(self.f.task['id'])[1]
        changed = copy.deepcopy(self.profile)
        changed['checks'][1]['expected'] = 'B2'
        result = self.amend(changed)
        self.assertEqual(result['invalidated_tasks'], ['B', 'D'])
        self.assertEqual(result['preserved_tasks'], ['A', 'C'])
        context = self.workflow.store.context(result['snapshot'])
        self.assertEqual((context['A.txt'], context['C.txt'], context['B.txt']), ('A', 'C', None))
        self.assertEqual(result['used_calls'], 3)
        self.assertEqual(result['deadline'], before['deadline'])
        with self.assertRaisesRegex(LedgerError, 'Stale'):
            self.workflow.reorder(self.f.task['id'], content_hash(old['plan']), ['B','D'])
        final = self.workflow.run(self.f.task['id'])
        self.assertEqual(final['phase'], 'completed')
        self.assertEqual(self.worker.calls, ['A', 'B', 'C', 'B', 'D'])
        self.assertIn('Approved change: B becomes B2.', self.worker.prompts[-1])
        self.assertEqual(self.workflow.control.status(self.f.task['id'])['used_calls'], 5)
        self.assertEqual(self.workflow.store.context(final['snapshot'])['B.txt'], 'B2')
        self.assertEqual(self.workflow.store.context(old['snapshot'])['B.txt'], 'B')
        self.assertIn('accepted_amendment', self.f.ledger.task(self.f.task['id'], full=True))
        self.assertFalse(any((self.f.project/(x+'.txt')).exists() for x in 'ABCD'))
        with self.assertRaises(LedgerError):
            self.workflow.review(self.f.task['id'], old['snapshot'], 'accept', 'Stale')

    def test_changed_checks_invalidate_omitted_related_task_and_overlap(self):
        changed = copy.deepcopy(self.profile)
        changed['checks'][1]['expected'] = 'B2'
        result = self.amend(changed, selected=['D'])
        self.assertEqual(result['invalidated_tasks'], ['B', 'D'])
        plan = copy.deepcopy(self.plan)
        plan['tasks'][2]['owned'] = ['B.txt']
        self.assertEqual(affected_tasks(plan, ['B']), {'B', 'C', 'D'})

    def test_stale_running_scope_and_user_source_changes_are_rejected(self):
        bad = copy.deepcopy(self.profile)
        bad['context'].append('extra.txt')
        with self.assertRaisesRegex(LedgerError, 'scope'):
            self.amend(bad)
        with self.assertRaisesRegex(LedgerError, 'Stale workflow'):
            self.amend(revision='0'*64)
        (self.f.project/'B.txt').write_text('New user change', encoding='utf-8')
        with self.assertRaisesRegex(LedgerError, 'source/index changed'):
            self.amend()
        (self.f.project/'B.txt').unlink()
        control = self.workflow.control
        attempt = control.reserve(self.f.task['id'], control.status(self.f.task['id'])['revision'], 'live', {'stage': 'fixture'})
        with self.assertRaisesRegex(LedgerError, 'reconcile'):
            self.amend()
        control.finish(attempt['id'], attempt['generation'], {}, not_started=True)

    def test_failed_checkpoint_does_not_publish_amendment(self):
        old = self.workflow.state(self.f.task['id'])
        with patch.object(self.f.ledger, '_event', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                self.amend()
        self.assertEqual(self.workflow.state(self.f.task['id']), old)
        self.assertEqual(self.workflow.control.status(self.f.task['id'])['used_calls'], 3)

    def test_operator_readonly_context_refresh_keeps_independent_candidate(self):
        (self.f.project/'contract.json').write_text('{"version":2}', encoding='utf-8')
        result = self.amend()
        context = self.workflow.store.context(result['snapshot'])
        self.assertEqual(context['contract.json'], '{"version":2}')
        self.assertEqual(context['C.txt'], 'C')
        state = self.workflow.state(self.f.task['id'])[1]
        self.assertEqual(state['base'], self.workflow.store.capture(self.f.project, self.profile['context']))


if __name__ == '__main__':
    unittest.main()
