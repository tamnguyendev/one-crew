"""T18a: repeated real failures produce bounded diagnosis, not endless repair."""
import copy
from onecrew.ledger import LedgerError
from onecrew.v2 import repair_tasks, plan
from tests.test_wf_engine import EngineFixture, node


class RecoveryPolicyTests(EngineFixture):
    def setUp(self):
        super().setUp()
        from onecrew.v2 import recovery_policy
        self.recovery=recovery_policy
        self.revise([node('A'),node('I',['A'],integration=True,write=())])

    def fail(self):
        self.step()
        def checker(item,artifact):
            result=self.checker(item,artifact)
            for row in result['checks']: row['result']='fail'
            return result
        self.verify('A',checker)

    def test_repeat_receipt_idempotent_and_changed_generation_does_not_reset_bounds(self):
        self.fail()
        self.assertEqual(self.kinds().count('workflow.recovery_decided'), 1,
                         'the failed verifier automatically supplies the bounded next action')
        first=self.recovery.assess(self.ledger,'P1','A')
        self.assertEqual(first['disposition'],'repair')
        self.assertEqual(self.recovery.assess(self.ledger,'P1','A')['event'],first['event'])
        repair_tasks.prepare(self.ledger,'P1','A','A',reason='Repair the actual failed criterion.',evidence=[first['source_receipt']])
        self.fail()
        second=self.recovery.assess(self.ledger,'P1','A')
        self.assertEqual(second['disposition'],'diagnose')
        with self.assertRaisesRegex(LedgerError,'diagnose'):
            repair_tasks.prepare(self.ledger,'P1','A','A',reason='Try again without progress.',evidence=[second['source_receipt']])
        self.assertEqual(self.ledger.requests(self.root_view['anchor_task']),[])
        self.assertEqual(plan.show(self.ledger,'P1')['status'],'approved')

    def test_one_bounded_replan_preserves_grant_then_blocks_repeated_failure(self):
        self.fail(); first=self.recovery.assess(self.ledger,'P1','A')
        repair_tasks.prepare(self.ledger,'P1','A','A',reason='First bounded repair.',evidence=[first['source_receipt']])
        self.fail(); second=self.recovery.assess(self.ledger,'P1','A')
        definition=copy.deepcopy(self.ip.current(self.ledger,'P1')['definition']['nodes'])
        definition[0]['goal']='Investigate a different supported cause using the retained failing test.'
        before=plan.show(self.ledger,'P1')['sha']
        result=self.recovery.replan(self.ledger,'P1','A',definition,reason='Use a different diagnosis supported by the actual failed receipt.',evidence=[second['source_receipt']])
        self.assertFalse(result['resets_budget'])
        self.fail()
        third=self.recovery.assess(self.ledger,'P1','A')
        self.assertEqual(third['disposition'],'blocked')
        with self.assertRaises(LedgerError):
            self.recovery.replan(self.ledger,'P1','A',definition,reason='Another attempt without new proof.',evidence=[third['source_receipt']])
        self.assertEqual(plan.show(self.ledger,'P1')['sha'],before)
        self.assertEqual(self.ledger.requests(self.root_view['anchor_task']),[])

    def test_no_failed_receipt_cannot_be_counted_as_product_repair(self):
        self.step(); self.verify('A')
        self.assertNotIn('workflow.recovery_decided', self.kinds())
        with self.assertRaises(LedgerError): self.recovery.assess(self.ledger,'P1','A')

    def test_crash_after_replan_reservation_resumes_same_plan_without_reset(self):
        from unittest.mock import patch
        self.fail(); first=self.recovery.assess(self.ledger,'P1','A')
        repair_tasks.prepare(self.ledger,'P1','A','A',reason='First bounded repair.',evidence=[first['source_receipt']])
        self.fail(); second=self.recovery.assess(self.ledger,'P1','A')
        definition=copy.deepcopy(self.ip.current(self.ledger,'P1')['definition']['nodes'])
        definition[0]['goal']='Different diagnosis supported by the retained failed test.'
        args={'reason':'One retained, bounded diagnostic plan.','evidence':[second['source_receipt']]}
        before=self.ip.current(self.ledger,'P1')['internal_revision']
        with patch.object(self.ip,'revise',side_effect=OSError('fixture crash')):
            with self.assertRaises(OSError): self.recovery.replan(self.ledger,'P1','A',definition,**args)
        result=self.recovery.replan(self.ledger,'P1','A',definition,**args)
        self.assertEqual(result['internal_revision'],before+1)
        self.assertFalse(result['resets_budget'])
