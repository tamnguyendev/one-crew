import json
import unittest
from unittest.mock import patch
from tests import test_owned as fixtures
from onecrew.delivery import deliver, feed
from onecrew.notifications import pull


class DeliveryTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.OwnedTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.run,self.task,self.worker=self.f.runtime([])

    def complete(self):
        seq,state=self.run.state(self.task);state.update(phase='completed',message='Done with evidence')
        self.run.persist(self.task,seq,state)

    def test_runner_checkpoint_delivers_once_without_model(self):
        self.complete()
        self.assertEqual(len(feed(self.f.ledger)['batches']),1)
        for _ in range(3): self.assertEqual(deliver(self.f.ledger)['delivered'],0)
        self.assertEqual(self.worker.calls,[])
        self.assertEqual(len(feed(self.f.ledger)['batches']),1)
        self.assertFalse(feed(self.f.ledger)['chat_callback'])

    def test_sink_failure_keeps_batch_unacked_then_replays_same_file(self):
        self.complete()
        with patch('onecrew.delivery.durable_write',side_effect=OSError('disk full')):
            with self.assertRaises(OSError): deliver(self.f.ledger,'retry')
        batch=pull(self.f.ledger,'retry')
        first=deliver(self.f.ledger,'retry')
        self.assertEqual(first['acked'],batch['id'])
        self.assertEqual(deliver(self.f.ledger,'retry')['delivered'],0)

    def test_question_sent_once_and_ack_does_not_answer(self):
        state=self.run.state(self.task)[1]
        profile=self.run.control.status(self.task)['configuration']['profile']
        result=self.run._tool(self.task,state,'ask',dict(question='Which version?',reason='Required',
            options=[{'id':'old','label':'Old'},{'id':'new','label':'New'}],recommendation='old'),profile)
        self.assertEqual(deliver(self.f.ledger)['delivered'],1)
        self.assertEqual(deliver(self.f.ledger)['delivered'],0)
        self.assertEqual(len(self.f.ledger.requests(self.task,pending=True)),1)

    def test_empty_project_does_not_create_delivery_files(self):
        self.assertEqual(deliver(self.f.ledger)['delivered'],0)
        self.assertEqual(feed(self.f.ledger)['batches'],[])

    def test_windows_store_length_state_root_replays_real_pending_batch(self):
        from pathlib import Path
        from onecrew.ledger import Ledger
        from onecrew.owned import Owned
        from onecrew.owned_intake import submit
        from onecrew.notifications import location
        base=Path(self.f.temp.name)
        root=base/('s'*(111-len(str(base))-1))
        ledger=Ledger(self.f.root,root);task=submit(ledger,'Read fixture','long-state')
        # This is a file-path regression, not a live subscription probe.
        from tests.test_workflow import FixtureWorker
        runtime=Owned(ledger,FixtureWorker(ledger,[]));runtime.enable(task['id'])
        seq,state=runtime.state(task['id']);state.update(phase='completed',message='fixture')
        with patch('onecrew.delivery.durable_write',side_effect=OSError('old long-path failure')):
            runtime.persist(task['id'],seq,state)
        pending=pull(ledger,'local-feed');path=location(ledger,'local-feed',False)
        target=path.parent/'delivered'/path.stem/(pending['id']+'.json')
        self.assertGreater(len(str(target))+34,259)
        receipt=deliver(ledger)
        self.assertEqual(receipt['acked'],pending['id']);self.assertEqual(receipt['delivered'],1)
        self.assertTrue(target.exists());self.assertEqual(len(feed(ledger)['batches']),1)
        self.assertIsNone(feed(ledger)['pending_batch'])

    def test_failure_is_visible_without_changing_execution_status(self):
        from onecrew.delivery import best_effort
        self.complete()
        with patch('onecrew.delivery.deliver',side_effect=OSError('sink unavailable')):
            result=best_effort(self.f.ledger)
        self.assertEqual(result['status'],'delivery_pending')
        self.assertIn('sink unavailable',feed(self.f.ledger)['last_error']['error'])
        self.assertEqual(self.run.state(self.task)[1]['phase'],'completed')
        deliver(self.f.ledger);self.assertIsNone(feed(self.f.ledger)['last_error'])

    def test_shared_conversation_question_is_not_discarded_as_missing_task_request(self):
        from onecrew.conversations import create
        from onecrew.solution_gate import question
        cid=create(self.f.ledger,'Shared discussion','delivery-conv','codex')['id']
        req=question(self.f.ledger,cid,'clarify','Which behavior?','Open requirement',[],'codex')
        result=deliver(self.f.ledger)
        self.assertEqual(result['delivered'],1)
        self.assertEqual(feed(self.f.ledger)['batches'][0]['notifications'][0]['request'],req['id'])

if __name__=='__main__': unittest.main()
