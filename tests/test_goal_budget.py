from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import datetime as dt
import time
import unittest
from unittest.mock import patch

import test_workflow as fixtures
from onecrew.control import Control
from onecrew.goal_budget import create
from onecrew.ledger import Ledger, LedgerError, content_hash
from onecrew.specs import Project
from onecrew.workflow import Workflow


class GoalBudgetTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.WorkflowTests()
        self.f.setUp()
        self.f.enable()
        project = self.f.base/'other-project'
        (project/'specs').mkdir(parents=True)
        (project/'specs/SPEC-001-duyet-spec.md').write_text(fixtures.SAMPLE,encoding='utf-8')
        self.other = Ledger(project,self.f.ledger.state_root)
        grant = {'schema_version':1,'permissions':['artifact.generate'],'limits':{'max_calls':6,'max_seconds':300},'source':'fixture'}
        self.task = self.other.submit('SPEC-001',Project(project).find('SPEC-001').revision,'other',grant)
        self.worker = fixtures.FixtureWorker(self.other,[])
        self.workflow = Workflow(self.other,self.worker)
        self.workflow.enable(self.task['id'],self.task['revision'],fixtures.profile())
        self.proposal = {'members':[
            {'task_id':self.f.task['id'],'project':str(self.f.project),'workflow_revision':content_hash(self.f.workflow.state(self.f.task['id'])[1])},
            {'task_id':self.task['id'],'project':str(project),'workflow_revision':content_hash(self.workflow.state(self.task['id'])[1])}],
            'max_calls':2,'deadline':self.f.task['deadline'],'reason':'Two repositories for one feature.'}

    def tearDown(self):
        self.f.tearDown()

    def group(self, proposal=None):
        return create(self.f.workflow,self.f.task['id'],self.proposal['members'][0]['workflow_revision'],proposal or self.proposal)

    def reserve(self, control, task, key):
        return control.reserve(task['id'],control.status(task['id'])['revision'],key,{'stage':'fixture'})

    def test_shared_cap_across_repos_is_atomic_and_restart_does_not_reset(self):
        self.proposal['max_calls'] = 1
        self.group()
        def invoke(pair):
            control, task = pair
            try:
                return self.reserve(control,task,'one')
            except LedgerError as error:
                return str(error)
        pairs = [(self.f.workflow.control,self.f.task),(self.workflow.control,self.task)]
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(invoke,pairs))
        self.assertEqual(sum(isinstance(r,dict) for r in results),1)
        self.assertIn('Shared goal',next(r for r in results if isinstance(r,str)))
        winner = next(r for r in results if isinstance(r,dict))
        control, task = next(p for p in pairs if p[1]['id'] == winner['task_id'])
        control.finish(winner['id'],winner['generation'],{'stopped':True})
        restart = Control(Ledger(self.other.project,self.f.ledger.state_root))
        shared = restart.status(self.task['id'])['budget']['goal']
        self.assertEqual((shared['used_calls'],shared['reserved_calls'],shared['remaining_calls']),(1,0,0))
        self.assertEqual(self.other.task(self.task['id'])['root_task_id'],self.f.task['id'])
        with self.assertRaisesRegex(LedgerError,'Shared goal'):
            self.reserve(restart,self.task,'after-restart')

    def test_prior_calls_and_unknown_reservations_remain_counted(self):
        row = self.reserve(self.workflow.control,self.task,'before-group')
        self.workflow.control.finish(row['id'],row['generation'],{'stopped':True})
        result = self.group()
        self.assertEqual(result['calls_already_used'],1)
        row = self.reserve(self.f.workflow.control,self.f.task,'ambiguous')
        self.f.workflow.control.unknown(row['id'],'launch acknowledgement lost')
        with self.assertRaisesRegex(LedgerError,'Shared goal'):
            self.reserve(self.workflow.control,self.task,'extra')
        self.assertEqual(self.group()['reserved_calls'],1)

    def test_no_group_reset_or_stale_members_or_extra_authority(self):
        stale = deepcopy(self.proposal)
        stale['members'][1]['workflow_revision'] = '0'*64
        with self.assertRaisesRegex(LedgerError,'stale member'):
            self.group(stale)
        too_big = deepcopy(self.proposal)
        too_big['max_calls'] = 7
        with self.assertRaisesRegex(LedgerError,'owner grant'):
            self.group(too_big)
        result = self.group()
        self.assertEqual(self.group()['revision'],result['revision'])
        changed = deepcopy(self.proposal)
        changed['max_calls'] = 3
        with self.assertRaisesRegex(LedgerError,'immutable'):
            self.group(changed)
        with self.assertRaisesRegex(LedgerError,'already belongs'):
            create(self.workflow,self.task['id'],self.proposal['members'][1]['workflow_revision'],self.proposal)

    def test_group_deadline_applies_to_both_dispatch_and_launch(self):
        end = dt.datetime.now(dt.timezone.utc)+dt.timedelta(seconds=10)
        self.proposal['deadline'] = end.isoformat()
        self.group()
        row = self.reserve(self.workflow.control,self.task,'first')
        self.workflow.control.clock = lambda:end+dt.timedelta(seconds=1)
        with self.assertRaisesRegex(LedgerError,'deadline'):
            self.workflow.control.launched(row['id'],row['generation'],{'fixture':True})
        self.workflow.control.finish(row['id'],row['generation'],{'not_started':True},not_started=True)
        with self.assertRaisesRegex(LedgerError,'deadline'):
            self.reserve(self.workflow.control,self.task,'later')
        self.assertEqual(self.workflow.control.status(self.task['id'])['used_calls'],0)

    def test_active_members_and_wrong_project_rejected_and_failed_write_rolls_back(self):
        row = self.reserve(self.workflow.control,self.task,'active')
        with self.assertRaisesRegex(LedgerError,'Stop/reconcile'):
            self.group()
        self.workflow.control.finish(row['id'],row['generation'],{'not_started':True},not_started=True)
        wrong = deepcopy(self.proposal)
        wrong['members'][1]['project'] = str(self.f.project)
        with self.assertRaisesRegex(LedgerError,'Unknown task'):
            self.group(wrong)
        with patch.object(self.f.ledger,'_event',side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                self.group()
        self.assertNotIn('goal',self.workflow.control.status(self.task['id'])['budget'])
        self.assertEqual(self.group()['used_calls'],0)

    def test_local_extension_cannot_reset_shared_cap_and_triage_does_not_offer_retry(self):
        self.proposal['max_calls'] = 1
        self.group()
        row = self.reserve(self.workflow.control,self.task,'spent')
        self.workflow.control.finish(row['id'],row['generation'],{'stopped':True})
        before = self.f.workflow.control.status(self.f.task['id'])
        from onecrew.budget import extend
        extend(self.f.workflow.control,self.f.task['id'],before['budget']['revision'],'more-local',7,
               (dt.datetime.fromisoformat(self.f.task['created_at'])+dt.timedelta(hours=1)).isoformat(),'Local only')
        after = self.f.workflow.control.status(self.f.task['id'])
        self.assertEqual(after['deadline'],self.proposal['deadline'])
        self.assertEqual(after['budget']['goal']['remaining_calls'],0)
        blocked = self.f.workflow.run(self.f.task['id'])
        self.assertEqual(blocked['phase'],'blocked')
        self.assertEqual(len(self.f.worker.calls),0)
        from onecrew.triage import ensure_request
        question = ensure_request(self.f.workflow,self.f.task['id'])
        self.assertEqual(question['question']['recommendation'],'inspect')
        self.assertIn('0 lượt',question['question']['impact'])

    def test_owner_cancel_reaches_other_repo_and_waits_for_unknown_across_restart(self):
        self.group()
        row = self.reserve(self.workflow.control,self.task,'unknown')
        self.workflow.control.unknown(row['id'],'lost acknowledgement')
        self.f.workflow.control.cancel(self.f.task['id'])
        root = Control(Ledger(self.f.project,self.f.ledger.state_root))
        self.assertEqual(root.status(self.f.task['id'])['status'],'cancelling')
        self.assertEqual(self.f.ledger.task(self.f.task['id'])['execution'],'cancelling')
        self.assertTrue(self.workflow.control.status(self.task['id'])['cancel_requested'])
        self.assertEqual(root.status(self.f.task['id'])['budget']['goal']['unknown_attempts'],1)
        from onecrew.runner import loop
        with patch('onecrew.runner.Workflow',return_value=self.f.workflow):
            self.assertEqual(loop(self.f.ledger,self.f.task['id']),'cancelling')
        with self.assertRaises(LedgerError):
            self.reserve(self.workflow.control,self.task,'after-cancel')
        root.cancel(self.f.task['id'])  # repeat does not release uncertain calls
        self.assertEqual(root.status(self.f.task['id'])['budget']['goal']['reserved_calls'],1)
        self.workflow.control.finish(row['id'],row['generation'],{'confirmed_stopped':True})
        self.assertEqual(root.status(self.f.task['id'])['status'],'cancelled')
        self.assertEqual(self.f.ledger.task(self.f.task['id'])['execution'],'cancelled')
        self.assertEqual(root.status(self.f.task['id'])['budget']['goal']['used_calls'],1)

    def test_child_cancel_stays_local_and_group_write_failure_rolls_back(self):
        self.group()
        with patch.object(self.f.ledger,'_event',side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                self.f.workflow.control.cancel(self.f.task['id'])
        self.assertFalse(self.f.workflow.control.status(self.f.task['id'])['cancel_requested'])
        self.assertFalse(self.workflow.control.status(self.task['id'])['cancel_requested'])
        self.workflow.control.cancel(self.task['id'])
        self.assertFalse(self.f.workflow.control.status(self.f.task['id'])['cancel_requested'])
        self.assertEqual(self.workflow.control.status(self.task['id'])['status'],'cancelled')
        row = self.reserve(self.f.workflow.control,self.f.task,'independent')
        self.f.workflow.control.finish(row['id'],row['generation'],{'not_started':True},not_started=True)

    def test_owner_cancel_stops_native_worker_in_other_project(self):
        from onecrew.supervisor import Supervisor, native_python
        self.group()
        row = self.reserve(self.workflow.control,self.task,'native')
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(Supervisor(self.workflow.control).run,row,
                                 [native_python(),'-c','import time; time.sleep(30)'],
                                 cwd=self.other.project,timeout=10)
            try:
                end = time.monotonic()+8
                while time.monotonic() < end:
                    if self.workflow.control.attempt(row['id'])['status'] == 'running':
                        break
                    time.sleep(.02)
                self.assertEqual(self.workflow.control.attempt(row['id'])['status'],'running')
                self.f.workflow.control.cancel(self.f.task['id'])
                future.result(timeout=8)
                self.assertEqual(self.workflow.control.attempt(row['id'])['status'],'settled')
                self.assertEqual(self.f.workflow.control.status(self.f.task['id'])['status'],'cancelled')
                self.assertEqual(self.f.workflow.control.status(self.f.task['id'])['budget']['goal']['active_attempts'],0)
            finally:
                self.f.workflow.control.cancel(self.f.task['id'])

    def test_work_cancel_cli_reports_group_status(self):
        from contextlib import redirect_stdout
        import io
        import json
        from onecrew.workflow_cli import main
        self.group()
        with redirect_stdout(io.StringIO()) as stream:
            code = main(['--project',str(self.f.project),'--state-root',str(self.f.ledger.state_root),
                         'work','cancel',self.f.task['id'],'--json'])
        self.assertEqual(code,0)
        self.assertEqual(json.loads(stream.getvalue())['status'],'cancelled')
        self.assertTrue(self.workflow.control.status(self.task['id'])['cancel_requested'])


if __name__ == '__main__':
    unittest.main()
