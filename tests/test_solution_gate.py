import unittest
from tests.test_conversations import ConversationTests,solution
from onecrew import conversations as c
from onecrew import solution_gate as gate
from onecrew.owned_intake import submit
from onecrew.ledger import LedgerError


def approve_fixture(ledger,key='fixture-solution'):
    cid=c.create(ledger,'Fixture contract',key,'fixture')['id']
    sol=c.propose(ledger,cid,'solution',solution(),'fixture')
    c.decide(ledger,sol['id'],sol['revision'],'approve','fixture','Test operator approval')
    return dict(solution_id=sol['id'],solution_revision=sol['revision'])


class SolutionGateTests(ConversationTests):
    def submit_change(self,key='job',binding=None):
        return submit(self.ledger,'Fix arithmetic',key,mode='change',provider='claude',model='sonnet',image='sha256:'+'a'*64,**(binding or approve_fixture(self.ledger)))

    def test_no_approval_no_write_job_and_audit_still_works(self):
        with self.assertRaises(LedgerError):submit(self.ledger,'Fix','bad',mode='change',image='sha256:'+'a'*64)
        first=submit(self.ledger,'Inspect','audit');second=submit(self.ledger,'Inspect','audit')
        self.assertEqual(first['id'],second['id'])

    def test_submission_replay_and_draft_does_not_revoke_running_contract(self):
        binding=approve_fixture(self.ledger);task=self.submit_change(binding=binding)
        cid=c.show_solution(self.ledger,binding['solution_id'])['conversation']
        c.propose(self.ledger,cid,'new',dict(solution(),detail='Changed behavior'),'kiro',binding['solution_id'])
        self.assertEqual(gate.check(self.ledger,task['id'])['revision'],binding['solution_revision'])
        self.assertEqual(self.submit_change(binding=binding)['id'],task['id'])
        with self.assertRaises(LedgerError):self.submit_change('other',binding)

    def test_hold_persists_across_entries_and_stale_reply_cannot_release(self):
        task=self.submit_change();b=gate.context(self.ledger,task['id'])
        req=gate.question(self.ledger,b['conversation'],'q','Change API?','Contract infeasible',[task['id']],'claude')
        with self.assertRaises(LedgerError):gate.check(self.ledger,task['id'])
        with self.assertRaises(LedgerError):gate.reply(self.ledger,req['id'],'old','continue_unchanged','kiro','user')
        self.assertEqual(len(c.read(self.ledger,b['conversation'])['pending_questions']),1)
        gate.reply(self.ledger,req['id'],req['revision'],'continue_unchanged','codex','actual user answer')
        self.assertIsNotNone(gate.check(self.ledger,task['id']))
        self.assertEqual(gate.context(self.ledger,task['id'])['recent_user_answers'][0]['answer']['reference'],'actual user answer')
        with self.assertRaises(LedgerError):gate.reply(self.ledger,req['id'],req['revision'],'stop','kiro','conflicting answer')

    def test_revise_binds_approved_replacement_preserving_task_budget(self):
        task=self.submit_change();b=gate.context(self.ledger,task['id'])
        req=gate.question(self.ledger,b['conversation'],'q','Change contract?','Evidence',[task['id']],'claude')
        sol=c.propose(self.ledger,b['conversation'],'new',dict(solution(),detail='Alternative'),'kiro',b['solution'])
        c.decide(self.ledger,sol['id'],sol['revision'],'approve','codex','user approved replacement')
        gate.reply(self.ledger,req['id'],req['revision'],'revise_solution','codex','user requested amendment',sol['id'],sol['revision'])
        self.assertEqual(gate.check(self.ledger,task['id'])['solution'],sol['id'])
        self.assertEqual(self.ledger.task(task['id'])['deadline'],task['deadline'])

    def test_one_contract_has_one_live_writer(self):
        binding=approve_fixture(self.ledger);self.submit_change(binding=binding)
        with self.assertRaisesRegex(LedgerError,'live task'):self.submit_change('duplicate-writer',binding)

    def test_stop_before_enable_never_releases_authority(self):
        task=self.submit_change();b=gate.context(self.ledger,task['id'])
        request=gate.question(self.ledger,b['conversation'],'stop','Stop?','Scope changed',[task['id']],'claude')
        gate.reply(self.ledger,request['id'],request['revision'],'stop','codex','actual operator stop')
        with self.assertRaisesRegex(LedgerError,'stopped'):gate.check(self.ledger,task['id'])

    def test_reaffirmation_keeps_binding_and_active_stop_is_persisted(self):
        from onecrew.control import Control,migrate
        task=self.submit_change();b=gate.context(self.ledger,task['id'])
        c.decide(self.ledger,b['solution'],b['revision'],'approve','kiro','User reaffirms the same solution')
        self.assertIsNotNone(gate.check(self.ledger,task['id']))
        migrate(self.ledger);control=Control(self.ledger)
        execution=control.configure(task['id'],task['revision'],{'mode':'fixture'})
        attempt=control.reserve(task['id'],execution['revision'],'active',{'stage':'fixture'})
        req=gate.question(self.ledger,b['conversation'],'active-stop','Stop?','Changed intent',[task['id']],'codex')
        answer=gate.reply(self.ledger,req['id'],req['revision'],'stop','operator','Stop now')
        self.assertEqual(answer['state'],'answered')
        self.assertEqual(control.status(task['id'])['status'],'cancelling')
        self.assertTrue(control.status(task['id'])['cancel_requested'])
        control.finish(attempt['id'],attempt['generation'],{'fixture':'stopped'},not_started=True)


if __name__=='__main__':unittest.main()
