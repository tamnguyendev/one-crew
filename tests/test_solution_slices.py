import unittest
from unittest.mock import patch
import test_workflow as fixtures
import test_parallel as parallel
from tests.test_conversations import solution
from onecrew import conversations as c
from onecrew.solution_slices import bind
from onecrew.workflow import Workflow
from onecrew.ledger import content_hash,LedgerError


class SliceTests(unittest.TestCase):
    def test_answer_during_recovery_does_not_change_reserved_prompt_or_reinvoke(self):
        from onecrew import solution_gate as gate
        f=fixtures.WorkflowTests();f.setUp();self.addCleanup(f.tearDown)
        cid=c.create(f.ledger,'Recovery','recovery')['id']
        sol=c.propose(f.ledger,cid,'sol',dict(solution(),detail='Pinned spec '+f.task['spec_revision']),'codex')
        c.decide(f.ledger,sol['id'],sol['revision'],'approve','operator','Fixture approval')
        bind(f.ledger,f.task['id'],f.task['revision'],sol['id'],sol['revision'])
        f.enable()
        with patch.object(f.worker,'result',side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):f.workflow.run(f.task['id'],steps=1)
        req=gate.question(f.ledger,cid,'q','Continue original?','External clarification',[f.task['id']],'claude')
        gate.reply(f.ledger,req['id'],req['revision'],'continue_unchanged','operator','Keep approved behavior')
        state=f.workflow.run(f.task['id'],steps=1)
        self.assertEqual(state['phase'],'working',state.get('message'))
        self.assertEqual(f.worker.calls,['plan'])

    def test_shared_solution_dag_requires_verified_first_slice_and_actual_answer(self):
        f=fixtures.WorkflowTests();f.setUp();self.addCleanup(f.tearDown)
        cid=c.create(f.ledger,'Feature','feature')['id']
        sol=c.propose(f.ledger,cid,'sol',dict(solution(),detail='Implement spec hash '+f.task['spec_revision']),'codex')
        c.decide(f.ledger,sol['id'],sol['revision'],'approve','operator','Actual fixture solution approval')
        bind(f.ledger,f.task['id'],f.task['revision'],sol['id'],sol['revision'])
        worker=parallel.DagWorker(f.ledger);worker.hold_c.set();runtime=Workflow(f.ledger,worker)
        state=runtime.enable(f.task['id'],f.task['revision'],parallel.profile())
        runtime.set_plan(f.task['id'],content_hash(state),parallel.dag())
        state=runtime.run(f.task['id'])
        self.assertEqual(state['done'],['A']);self.assertEqual(worker.calls,['A'])
        request=f.ledger.requests(f.task['id'],pending=True)[0]
        runtime.run(f.task['id']);self.assertEqual(worker.calls,['A'])
        with self.assertRaises(LedgerError):f.ledger.reply(request['id'],'stale','approve','claude','actual approval')
        f.ledger.reply(request['id'],request['revision'],'approve','claude','Reviewed first slice diff and test evidence')
        result=runtime.run(f.task['id'])
        self.assertEqual(result['phase'],'completed',result.get('message'))
        self.assertEqual(worker.peak,2)
        self.assertEqual(len(c.read(f.ledger,cid)['tasks']),1)
