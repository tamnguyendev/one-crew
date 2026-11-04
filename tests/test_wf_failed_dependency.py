"""A known failed prerequisite cannot authorize bounded produced-edge advance."""
import threading

from onecrew.v2 import repair_tasks
from tests.test_wf_engine import EngineFixture, node


class FailedDependencyTests(EngineFixture):
    def setUp(self):
        super().setUp()
        consumer=node('D',['C'],requires='produced',write=())
        consumer['depends'][0]['advance']={'limit':1,'discard_on_failure':True}
        independent=node('X',write=('b.txt',));independent['read']=['b.txt']
        self.revise([node('C'),consumer,independent,node('I',['C','D','X'],integration=True,write=())])

    def failed(self,item,artifact):
        result=self.checker(item,artifact)
        for row in result['checks']:row['result']='fail'
        return result

    def test_known_failure_blocks_advance_then_real_repair_generation_restores_dependencies(self):
        self.step();self.verify('C',self.failed)
        view=self.engine.state(self.ledger,'P1')
        self.assertEqual(set(view['failed_blockers']),{'C','D','I'})
        self.assertFalse(self.engine.eligible(view,'D')['ready'])
        self.assertEqual(self.step()['node'],'X')
        repair_tasks.prepare(self.ledger,'P1','C','C',reason='Repair the observed failed prerequisite',evidence=['a.txt:1'])
        changed=self.engine.state(self.ledger,'P1')
        self.assertEqual(changed['failed_blockers'],{})
        self.assertEqual(changed['nodes']['C']['generation'],view['nodes']['C']['generation']+1)
        self.assertEqual(self.step()['node'],'C');self.verify('C')
        self.assertEqual(self.step()['node'],'D')

    def test_failure_while_advanced_consumer_is_running_retains_late_result_without_publishing(self):
        self.step()
        started,release=threading.Event(),threading.Event();result={}
        def early(ledger,control,task,item,attempt):
            control.launched(attempt['id'],attempt['generation'],{'fixture':True});started.set()
            if not release.wait(10):raise AssertionError('fixture release missing')
            candidate={'artifact':self.store.blob(b'early consumer'),'receipt':self.store.blob(b'early consumer receipt')}
            control.finish(attempt['id'],attempt['generation'],candidate);return candidate
        thread=threading.Thread(target=lambda:result.update(self.step(early)));thread.start()
        try:
            self.assertTrue(started.wait(5));self.verify('C',self.failed)
        finally:release.set();thread.join(5)
        self.assertEqual(result['state'],'retained')
        self.assertFalse(any(kind=='node.produced' and body['node']=='D' for kind,body in self.events()))
        self.assertEqual(self.step()['node'],'X')
