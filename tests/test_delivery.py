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

if __name__=='__main__': unittest.main()
