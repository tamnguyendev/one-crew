from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import json
import sqlite3
import threading
import time
import unittest

import test_workflow as fixtures
from onecrew.control import migrate
from onecrew.ledger import LedgerError
from onecrew.parallel import ready_batch
from onecrew.workflow import Workflow


def dag():
    return {'summary': 'A then independent B/C then D.', 'tasks': [
        {'id': name, 'title': name, 'depends_on': deps, 'owned': [name+'.txt'], 'acceptance': ['AC-'+name]}
        for name,deps in [('A',[]),('B',['A']),('C',['A']),('D',['B','C'])]]}


def profile():
    value=fixtures.profile()
    value.update(context=[n+'.txt' for n in 'ABCD'],owned=[n+'.txt' for n in 'ABCD'],parallel=True,
                 acceptance=[{'id':'AC-'+n,'description':'File '+n} for n in 'ABCD'],
                 checks=[{'id':'CHECK-'+n,'acceptance':['AC-'+n],'kind':'text_equal','path':n+'.txt','expected':n} for n in 'ABCD'])
    return value


class DagWorker(fixtures.FixtureWorker):
    def __init__(self,ledger):
        super().__init__(ledger,[])
        self.barrier=threading.Barrier(2)
        self.hold_c=threading.Event()
        self.guard=threading.Lock()
        self.peak=0
        self.bad_b=False

    def run(self,attempt,prompt,schema,profile):
        stage=json.loads(attempt['operation'])['stage']
        with self.guard:
            self.calls.append(stage)
        self.control.launched(attempt['id'],attempt['generation'],{'fixture':stage})
        if stage in ('B','C'):
            self.barrier.wait(timeout=5)
            with self.guard:
                count=sum(a['status']=='running' for a in self.control.status(attempt['task_id'])['attempts'])
                self.peak=max(self.peak,count)
            if stage=='C' and not self.hold_c.wait(timeout=8):
                raise AssertionError('Test did not release C.')
        value=dag() if stage=='plan' else fixtures.artifact(stage+'.txt',stage)
        if stage=='B' and self.bad_b:
            value=fixtures.artifact('D.txt','outside B ownership')
        self.control.finish(attempt['id'],attempt['generation'],{'fixture':value})


class ParallelTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.WorkflowTests()
        self.f.setUp()
        self.worker=DagWorker(self.f.ledger)
        self.workflow=Workflow(self.f.ledger,self.worker)
        self.workflow.enable(self.f.task['id'],self.f.task['revision'],profile())

    def tearDown(self):
        self.worker.hold_c.set()
        self.f.tearDown()

    def test_dag_two_workers_shared_budget_and_review_b_while_c_runs(self):
        with ThreadPoolExecutor(max_workers=1) as pool:
            future=pool.submit(self.workflow.run,self.f.task['id'])
            try:
                end=time.monotonic()+7
                card=None
                while time.monotonic()<end:
                    output=self.workflow.outputs(self.f.task['id'])
                    card=next((r for r in output['outputs'] if r['stage']=='B'),None)
                    if card: break
                    if future.done(): self.fail(str(future.result()))
                    time.sleep(.02)
                self.assertIsNotNone(card)
                self.assertNotIn('D',self.worker.calls)
                self.workflow.review(self.f.task['id'],card['revision'],'feedback','B reviewed while C runs.')
            finally:
                self.worker.hold_c.set()
            state=future.result(timeout=8)
        self.assertEqual(state['phase'],'completed')
        self.assertEqual(self.worker.peak,2)
        self.assertEqual(set(state['done']),set('ABCD'))
        self.assertEqual(self.worker.calls[-1],'D')
        self.assertEqual(self.workflow.control.status(self.f.task['id'])['used_calls'],5)
        self.assertEqual(len(self.workflow.outputs(self.f.task['id'])['reviews']),1)

    def test_overlap_is_not_selected_for_parallel_batch(self):
        value=dag(); value['tasks'][2]['owned']=['B.txt']
        self.assertEqual([r['id'] for r in ready_batch({'plan':value,'done':['A']})],['B'])

    def test_valid_sibling_output_survives_an_invalid_parallel_branch(self):
        self.worker.bad_b=True
        self.worker.hold_c.set()
        state=self.workflow.run(self.f.task['id'])
        self.assertEqual(state['phase'],'waiting_branches')
        self.assertIn('C',state['done'])
        self.assertNotIn('B',state['done'])
        self.assertNotIn('D',self.worker.calls)
        self.assertEqual(self.workflow.control.status(self.f.task['id'])['used_calls'],4)

    def test_operator_plan_is_revision_bound_and_avoids_planning_call(self):
        from onecrew.ledger import content_hash
        _,state=self.workflow.state(self.f.task['id'])
        revision=content_hash(state)
        self.workflow.set_plan(self.f.task['id'],revision,dag())
        with self.assertRaises(LedgerError):
            self.workflow.set_plan(self.f.task['id'],revision,dag())
        self.worker.hold_c.set()
        self.assertEqual(self.workflow.run(self.f.task['id'])['phase'],'completed')
        self.assertNotIn('plan',self.worker.calls)
        self.assertEqual(self.workflow.control.status(self.f.task['id'])['used_calls'],4)

    def test_v2_migration_preserves_unknown_reservation_and_budget(self):
        control=self.workflow.control
        config=control.status(self.f.task['id'])
        attempt=control.reserve(self.f.task['id'],config['revision'],'before-upgrade',{'stage':'fixture'})
        control.unknown(attempt['id'],'fixture')
        with self.f.ledger.transaction(write=True) as conn:
            conn.execute('DROP INDEX one_active_attempt_per_unit')
            conn.execute("CREATE UNIQUE INDEX one_active_attempt_per_task ON attempts(task_id) WHERE status IN ('reserved','running','unknown')")
            conn.execute('PRAGMA user_version=2')
        result=migrate(self.f.ledger)
        self.assertEqual(result['schema_version'],3)
        with closing(sqlite3.connect(result['backup'])) as conn:
            self.assertEqual(conn.execute('PRAGMA user_version').fetchone()[0],2)
        current=control.status(self.f.task['id'])
        self.assertEqual(current['reserved_calls'],1)
        self.assertEqual(current['attempts'][0]['status'],'unknown')
        with self.assertRaises(LedgerError):
            control.reserve(self.f.task['id'],config['revision'],'parallel',{'unit':'task:B'})


if __name__=='__main__':
    unittest.main()
