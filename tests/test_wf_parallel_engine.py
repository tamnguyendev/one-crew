"""W14b: two actual Control slots, one shared ready_batch, isolated fixture workers."""
import os
import threading
from unittest.mock import patch

from onecrew import dependency_core
from onecrew.budget_core import group
from onecrew.control_core import Control, migrate
from onecrew.ledger import LedgerError, Ledger
from onecrew.snapshots import Snapshots
from onecrew.v2 import engine, executors, internal_plan, plan
from tests.test_v2_l1 import Fixture, plan_json
from tests.test_wf_engine import EngineFixture, node


class ParallelFixture(EngineFixture):
    def setUp(self):
        Fixture.setUp(self)
        self.engine,self.ip=engine,internal_plan
        self.engine_caps=['namespaced-storage','root-budget','internal-plan','sequential-engine','parallel-engine']
        raw=plan_json(scope={'owned':['a.txt','b.txt']},authority={'edit':True,'commands':True,'self_decide':['Q1','Q2','Q3','Q4','Q9','Q12']})
        self.root_view=plan.propose(self.ledger,'P1',raw,'codex',workflow=True,capabilities=self.engine_caps)
        plan.approve(self.ledger,'P1','owner','bounded temporary parallel fixture')
        os.environ['ONECREW_ACTOR']='codex'
        self.store=Snapshots(self.ledger.state_root);migrate(self.ledger);self.control=Control(self.ledger)

    def isolated(self, callback=None):
        case=self
        class Isolated(executors.Executor):
            declaration=executors.Declaration('fixture-isolated-artifact','managed',('start','isolate'))
            control=case.control
            def start(self,*args): return (callback or case.execute)(*args)
            def isolate(self,attempt_id): return {'attempt':attempt_id,'writes':'scoped candidate only'}
        return Isolated()


class ParallelEngineTests(ParallelFixture):
    def test_disjoint_workers_overlap_and_reuse_actual_scheduler_and_root_budget(self):
        self.revise([node('A'),node('B',write=('b.txt',)),node('I',['A','B'],integration=True,write=())])
        barrier=threading.Barrier(2);started=[];lock=threading.Lock()
        def together(ledger,control,task,item,attempt):
            control.launched(attempt['id'],attempt['generation'],{'fixture':True})
            with lock: started.append(item['id'])
            barrier.wait(5)
            result={'artifact':self.store.blob(('isolated-'+item['id']).encode()),'receipt':self.store.blob(b'fixture isolated result')}
            control.finish(attempt['id'],attempt['generation'],result)
            return result
        with self.ledger.transaction() as conn: before=group(conn,self.root_view['anchor_task'])
        with patch.object(dependency_core,'ready_batch',wraps=dependency_core.ready_batch) as reused:
            results=engine.run_batch(self.ledger,'P1',self.isolated(together),slots=2)
            self.assertGreaterEqual(reused.call_count,3)
        self.assertEqual(set(started),{'A','B'})
        self.assertEqual({result['node'] for result in results['results']},{'A','B'})
        self.assertTrue(all(result['state']=='produced' for result in results['results']))
        with self.ledger.transaction() as conn: after=group(conn,self.root_view['anchor_task'])
        self.assertEqual((after['used_calls'],after['reserved_calls']),(2,0))
        self.assertEqual(after['deadline'],before['deadline'])
        reopened=Ledger(self.root,self.ledger.state_root)
        with reopened.transaction() as conn:self.assertEqual(group(conn,self.root_view['anchor_task'])['used_calls'],2)

    def test_overlapping_ownership_never_occupies_two_slots_and_one_slot_order_is_preserved(self):
        self.revise([node('A'),node('Overlap'),node('B',write=('b.txt',)),node('I',['A','Overlap','B'],integration=True,write=())])
        self.assertEqual([item['id'] for item in engine.ready(self.ledger,'P1',slots=1)],['A'])
        first=engine.run_batch(self.ledger,'P1',self.isolated(),slots=2)
        self.assertEqual({result['node'] for result in first['results']},{'A','B'})
        remaining=engine.run_batch(self.ledger,'P1',self.isolated(),slots=1)
        self.assertEqual([result['node'] for result in remaining['results']],['Overlap'])

    def test_active_write_scope_stays_excluded_even_after_other_slot_finishes(self):
        self.revise([node('A'),node('Overlap'),node('B',write=('b.txt',)),node('I',['A','Overlap','B'],integration=True,write=())])
        started,release=threading.Event(),threading.Event(); result={}
        def wait_first(ledger,control,task,item,attempt):
            if item['id']!='A':return self.execute(ledger,control,task,item,attempt)
            control.launched(attempt['id'],attempt['generation'],{'fixture':True});started.set()
            if not release.wait(10):raise AssertionError('fixture release missing')
            control.finish(attempt['id'],attempt['generation'],{'fixture':True})
            return {'artifact':self.store.blob(b'isolated A'),'receipt':self.store.blob(b'isolated A receipt')}
        executor=self.isolated(wait_first)
        thread=threading.Thread(target=lambda:result.update(engine.step(self.ledger,'P1',executor,slots=2,_target='A')))
        thread.start()
        try:
            self.assertTrue(started.wait(5))
            self.assertEqual(engine.step(self.ledger,'P1',executor,slots=2)['node'],'B')
            self.assertEqual(engine.step(self.ledger,'P1',executor,slots=2)['state'],'waiting')
        finally:release.set();thread.join(5)
        self.assertEqual(result['state'],'produced')

    def test_parallel_refuses_undeclared_isolation_and_unsupported_slot_counts(self):
        self.revise([node('A'),node('B',write=('b.txt',)),node('I',['A','B'],integration=True,write=())])
        with self.assertRaisesRegex(LedgerError,'isolate'):
            engine.run_batch(self.ledger,'P1',self.execute,slots=2)
        with self.assertRaisesRegex(LedgerError,'1 or 2'):
            engine.run_batch(self.ledger,'P1',self.isolated(),slots=3)
        self.assertNotIn('node.started',self.kinds())

    def test_failed_branch_can_repair_while_independent_worker_finishes_original_generation(self):
        from onecrew.v2 import repair_tasks
        independent=node('B',write=('b.txt',));independent['read']=['b.txt']
        integration=node('I',['A','B'],integration=True,write=());integration['read']=[]
        self.revise([node('A'),independent,integration]);self.step()
        def failed(item,artifact):
            result=self.checker(item,artifact)
            for row in result['checks']:row['result']='fail'
            return result
        self.verify('A',failed)
        started,release=threading.Event(),threading.Event();result={}
        def finish_later(ledger,control,task,item,attempt):
            control.launched(attempt['id'],attempt['generation'],{'fixture':True});started.set()
            if not release.wait(10):raise AssertionError('fixture release missing')
            candidate={'artifact':self.store.blob(b'independent B'),'receipt':self.store.blob(b'independent B receipt')}
            control.finish(attempt['id'],attempt['generation'],candidate);return candidate
        thread=threading.Thread(target=lambda:result.update(engine.step(self.ledger,'P1',self.isolated(finish_later),slots=2,_target='B')))
        thread.start()
        try:
            self.assertTrue(started.wait(5))
            repair_tasks.prepare(self.ledger,'P1','A','A',reason='Repair only the failed independent branch',evidence=['a.txt:1'])
        finally:release.set();thread.join(5)
        self.assertEqual(result['state'],'produced')
        view=engine.state(self.ledger,'P1')
        self.assertEqual(view['nodes']['A']['generation'],1)
        self.assertEqual(view['nodes']['B']['generation'],0)
        self.assertEqual(view['nodes']['B']['artifact'],result['artifact'])
        self.verify('B')
        with self.ledger.transaction() as conn:self.assertEqual(group(conn,self.root_view['anchor_task'])['used_calls'],2)


class CaseFoldedOwnershipTests(ParallelFixture):
    """W14b (audit, T49d): write scopes are compared with authority.owned_match's rule (case-folded, '\\' as '/'), so 'a.txt' and 'A.txt' are
    one file on Windows: never two writers at once, and a plan that splits them across nodes is refused."""

    def test_ready_batch_treats_case_colliding_owned_paths_as_one(self):
        tasks=[{'id':'A','owned':['a.txt'],'depends_on':[]},{'id':'B','owned':['A.txt'],'depends_on':[]},{'id':'C','owned':['sub\\C.txt'],'depends_on':[]},
               {'id':'D','owned':['SUB/c.txt'],'depends_on':[]}]
        self.assertEqual([t['id'] for t in dependency_core.ready_batch({'plan':{'tasks':tasks[:2]},'done':[]})],['A'])
        self.assertEqual([t['id'] for t in dependency_core.ready_batch({'plan':{'tasks':tasks[2:]},'done':[]})],['C'])
        self.assertEqual([t['id'] for t in dependency_core.ready_batch({'plan':{'tasks':[tasks[0],tasks[2]]},'done':[]})],['A','C'])

    def test_internal_plan_refuses_case_colliding_writes_across_nodes(self):
        with self.assertRaisesRegex(LedgerError,'case'):
            self.revise([node('A'),node('B',write=('A.txt',)),node('I',['A','B'],integration=True,write=())])
        self.assertIsNone(internal_plan.current(self.ledger,'P1')['definition'])

    def test_engine_ready_folds_case_against_ready_and_active_writers(self):
        self.revise([node('A'),node('B',write=('b.txt',)),node('I',['A','B'],integration=True,write=())])
        view=engine.state(self.ledger,'P1')
        self.assertEqual([t['id'] for t in engine._ready(view,2)],['A','B'])
        view['definition']['nodes'][1]['write']=['A.txt']          # a definition admitted before the cross-node check
        self.assertEqual([t['id'] for t in engine._ready(view,2)],['A'])
        view=engine.state(self.ledger,'P1')
        view['active_nodes']=[{'node':'X','attempt':'x','write':['A.TXT']}]
        self.assertEqual([t['id'] for t in engine._ready(view,2)],['B'])
