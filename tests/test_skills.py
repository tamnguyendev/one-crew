import json
import unittest
from tests import test_owned as fixtures
from onecrew.owned import Owned
from onecrew.owned_intake import submit
from onecrew.ledger import Ledger, LedgerError
from onecrew import skills
from onecrew.learning import outcomes


class SkillTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.OwnedTests(); self.f.setUp(); self.addCleanup(self.f.doCleanups)
        self.goal='Inspect calculation implementation and report subtraction evidence'
        self.counter=0

    def run_task(self, goal=None, fail=False):
        self.counter+=1
        task=submit(self.f.ledger,goal or self.goal,'history-'+str(self.counter))['id']
        worker=fixtures.FixtureWorker(self.f.ledger,[fixtures.action('read',path='calc.py'),
            fixtures.action('finish',report='calc.py subtracts numbers; runtime not tested.'),
            {'accepted':True,'feedback':'Source evidence sufficient for audit.'}])
        runtime=Owned(self.f.ledger,worker); runtime.enable(task)
        if fail:
            runtime.run(task,steps=1); seq,state=runtime.state(task)
            state['phase']='failed';runtime.persist(task,seq,state)
        else: self.assertEqual(runtime.run(task)['phase'],'completed')
        return runtime,task,worker

    def candidate(self):
        for _ in range(3): self.run_task()
        values=skills.review(self.f.ledger);self.assertEqual(len(values),1)
        return skills.review(self.f.ledger,values[0]['id'])

    def test_retries_and_checkpoint_duplicates_are_not_three_tasks(self):
        runtime,task,_=self.run_task()
        for _ in range(4):
            seq,state=runtime.state(task);state['message']='changed';runtime.persist(task,seq,state)
        self.assertEqual(skills.review(self.f.ledger),[])
        self.run_task();self.assertEqual(skills.review(self.f.ledger),[])
        self.run_task();self.assertEqual(len(skills.review(self.f.ledger)),1)
        self.assertEqual(skills.refresh(self.f.ledger),[])

    def test_failure_is_counted_but_two_successes_required(self):
        self.run_task(fail=True);self.run_task(fail=True);self.run_task()
        self.assertEqual(skills.review(self.f.ledger),[])
        self.run_task();value=skills.review(self.f.ledger)[0]
        self.assertEqual(value['successes'],2);self.assertEqual(value['failures'],2)

    def test_unrelated_goals_technology_and_project_do_not_match(self):
        self.run_task();self.run_task();self.run_task('Review database migration rollback safety permissions')
        self.assertEqual(skills.review(self.f.ledger),[])
        a=skills.signature(self.goal,'audit',{'a.py':1})
        self.assertFalse(skills.similar(a,skills.signature(self.goal,'audit',{'a.dart':1})))
        self.assertFalse(skills.similar(a,skills.signature(self.goal,'change',{'a.py':1})))
        other=self.f.root.parent/'other';other.mkdir()
        self.assertEqual(skills.review(Ledger(other,self.f.ledger.state_root)),[])

    def test_candidate_not_loaded_then_reviewed_revision_used_by_runtime(self):
        value=self.candidate()
        runtime,task,_=self.run_task();self.assertEqual(runtime.state(task)[1]['skills'],[])
        with self.assertRaises(LedgerError): skills.decide(self.f.ledger,value['id'],'old','approved','actual review')
        skills.decide(self.f.ledger,value['id'],value['revision'],'approved','actual review')
        runtime,task,worker=self.run_task()
        selected=runtime.state(task)[1]['skills'];self.assertEqual(selected[0]['revision'],value['revision'])
        self.assertLess(len(selected[0]['body']),8000)
        self.assertEqual(outcomes(self.f.ledger)[0]['skills'][0]['id'],value['id'])
        self.assertEqual(len(worker.calls),3)
        restored=Ledger(self.f.root,self.f.ledger.state_root)
        self.assertEqual(skills.review(restored,value['id'])['status'],'approved')

    def test_tampering_and_stale_success_block_approval(self):
        value=self.candidate();path=skills.skill_path(self.f.ledger,value)
        path.write_text('Changed instructions',encoding='utf-8')
        with self.assertRaises(LedgerError): skills.decide(self.f.ledger,value['id'],value['revision'],'approved','review')
        path.write_text(value['body'],encoding='utf-8')
        task=value['evidence'][0]['task'];runtime=Owned(self.f.ledger)
        seq,state=runtime.state(task);state['phase']='failed';runtime.persist(task,seq,state)
        with self.assertRaises(LedgerError): skills.decide(self.f.ledger,value['id'],value['revision'],'approved','review')
        self.assertFalse(skills.review(self.f.ledger,value['id'])['usable_evidence'])

    def test_permissions_checked_and_rejection_never_loaded(self):
        value=self.candidate()
        # Exercise the capability gate on an otherwise valid approved record.
        with self.f.ledger.transaction(write=True) as conn:
            value.pop('usable_evidence');value.pop('path')
            value.update(status='approved',required_permissions=['git.push'])
            self.f.ledger._event(conn,value['tasks'][0],'skill.state',value)
        selected=skills.select(self.f.ledger,self.goal,{'mode':'audit'},{'files':{'calc.py':'hash'}},['discover','report'])
        self.assertEqual(selected,[])

if __name__=='__main__': unittest.main()
