"""Real Supervisor safe point is consumed by the engine without another call."""
import copy

from onecrew.ledger import LedgerError, content_hash
from onecrew.task_intake import submit
from onecrew.v2 import executors
from tests.test_wf_managed_executor import ManagedFixture


class EngineManagedTests(ManagedFixture):
    def test_acknowledged_pause_is_held_then_same_candidate_is_released_without_another_process(self):
        self.delay=.5
        thread,result,attempt=self.run_in_background()
        executors.Dispatcher().send(self.adapter,'pause_at_safe_point',attempt,'Temporary scoped hold')
        thread.join(6);self.assertFalse(thread.is_alive());self.assertNotIn('error',result)
        self.assertEqual(result['value']['executor_state'],'paused')
        view=self.engine.state(self.ledger,'P1')
        self.assertEqual(view['nodes']['C']['phase'],'held')
        self.assertIsNone(view['nodes']['C']['artifact'])
        before=self.adapter.control.status(self.adapter.control.attempt(attempt)['task_id'])
        released=self.engine.release_paused(self.ledger,'P1','C',self.adapter)
        self.assertTrue(released['reused_safe_candidate'])
        self.assertEqual(self.launches,[attempt])
        after=self.adapter.control.status(self.adapter.control.attempt(attempt)['task_id'])
        self.assertEqual(before['used_calls'],after['used_calls']);self.assertEqual(before['budget'],after['budget'])
        self.verify('C')

    def test_settled_but_unknown_managed_result_cannot_be_replayed_by_new_internal_revision(self):
        task=submit(self.ledger,'Unknown managed result fixture','unknown-result',plan_selector='plan-ns:P1',max_calls=2,max_seconds=30,provider='codex',model='fixture-model')
        execution=self.adapter.control.configure(task['id'],task['revision'],{'mode':'managed-fixture'})
        attempt=self.adapter.control.reserve(task['id'],execution['revision'],'once',{'unit':'task:C'})
        item=copy.deepcopy(self.ip.current(self.ledger,'P1')['definition']['nodes'][0]);item['input_artifacts']={}
        self.adapter._write(attempt['id'],'prepared',task_revision=task['revision'],node='C',node_sha=content_hash(item),read=item['read'],write=item['write'],inputs_sha=content_hash({}))
        self.adapter.native.start(self.ledger,self.adapter.control,task,item,attempt)
        changed=self.ip.current(self.ledger,'P1')['definition']['nodes'];changed[0]['goal']+=' altered wording'
        with self.assertRaisesRegex(LedgerError,'unknown managed operation'):
            self.revise(changed)
        self.assertEqual(self.launches,[attempt['id']])
