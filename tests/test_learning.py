import unittest
from tests import test_owned as fixtures
from onecrew.learning import outcomes,propose,lessons
from onecrew.ledger import Ledger,LedgerError


class LearningTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.OwnedTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.run,self.task,self.worker=self.f.runtime([])

    def finish(self,phase='blocked'):
        seq,state=self.run.state(self.task);state['phase']=phase;self.run.persist(self.task,seq,state)
        return outcomes(self.f.ledger)[0]

    def test_outcomes_include_failures_dedup_unknowns_and_no_false_scores(self):
        row=self.finish();self.finish()
        self.assertEqual(len(outcomes(self.f.ledger)),1)
        self.assertEqual(row['phase'],'blocked');self.assertIsNone(row['quality_score'])
        self.assertEqual(row['assistance'],'unknown')
        self.assertEqual(self.worker.calls,[])

    def test_lesson_requires_own_evidence_and_never_promotes_itself(self):
        row=self.finish()
        with self.assertRaises(LedgerError): propose(self.f.ledger,self.task,999999,'Test evidence first')
        result=propose(self.f.ledger,self.task,row['event'],'Test evidence first')
        self.assertEqual(result['status'],'proposed');self.assertFalse(result['automatic_injection'])
        propose(self.f.ledger,self.task,row['event'],'Test evidence first')
        self.assertEqual(len([r for r in lessons(self.f.ledger) if r['id']==result['id']]),1)
        seq,state=self.run.state(self.task);self.run._read(state,{'path':'calc.py'});self.run.persist(self.task,seq,state)
        self.assertEqual(next(r for r in lessons(self.f.ledger) if r['id']==result['id'])['status'],'stale')

    def test_project_isolation(self):
        self.finish()
        other=self.f.root.parent/'other';other.mkdir()
        self.assertEqual(outcomes(Ledger(other,self.f.ledger.state_root)),[])

if __name__=='__main__': unittest.main()
