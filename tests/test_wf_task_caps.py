"""T36a: split ordinary work; explicit bounded indivisible exceptions."""
import copy
import os
from unittest.mock import patch
from onecrew.ledger import LedgerError
from onecrew.v2 import plan, internal_plan
from tests.test_v2_l1 import plan_json
from tests.test_wf_engine import EngineFixture, node


class TaskCapTests(EngineFixture):
    def test_ordinary_large_task_requires_real_decomposition(self):
        a=node('A'); a.update(estimate_seconds=[10800,14400],execution_cap_seconds=14400)
        with self.assertRaisesRegex(LedgerError,'Split'):
            internal_plan._validate([a,node('I',['A'],integration=True,write=())],['O1'])
        split=[node('A1'),node('A2',['A1']),node('I',['A1','A2'],integration=True,write=())]
        for row in split[:2]: row.update(estimate_seconds=[3600,7200],execution_cap_seconds=7200)
        accepted=internal_plan._validate(split,['O1'])
        self.assertTrue(all(n['estimate_seconds'][1]<=7200 for n in accepted))

    def test_indivisible_cap_is_sealed_and_does_not_extend_root_deadline(self):
        value=plan_json(budget={'max_calls':100,'time':600},authority={'edit':True,'commands':True,'self_decide':['Q1','Q2','Q9','Q12']})
        plan.propose(self.ledger,'Long',value,'codex',workflow=True,capabilities=self.engine_caps)
        with patch.dict(os.environ,{'ONECREW_ACTOR':''}): plan.approve(self.ledger,'Long','owner','temporary fixture')
        task=node('C'); task.update(estimate_seconds=[3600,5400],execution_cap_seconds=9000,
            indivisible={'reason':'The declared operation produces one atomic result and cannot checkpoint halfway.','cap_seconds':9000})
        definition=[task,node('I',['C'],integration=True,write=())]
        result=internal_plan.revise(self.ledger,'Long',definition,reason='bounded indivisible operation',evidence=['a.txt:1'])
        self.assertEqual(result['definition']['nodes'][0]['indivisible']['cap_seconds'],9000)
        with self.assertRaisesRegex(LedgerError,'deadline'):
            self.revise(definition)
        self.assertEqual(plan.show(self.ledger,'P1')['contract']['budget']['time'],120)

    def test_bad_exception_and_nonfinite_caps_are_rejected(self):
        for cap, exception in [(float('inf'),{'reason':'long enough explicit reason','cap_seconds':float('inf')}),
                (9000,{'reason':'because','cap_seconds':9000}), (9000,{'reason':'An indivisible external operation','cap_seconds':12000})]:
            item=node('C'); item.update(execution_cap_seconds=cap,indivisible=exception)
            with self.subTest(cap=cap),self.assertRaises(LedgerError):
                internal_plan._validate([item,node('I',['C'],integration=True,write=())],['O1'])

    def test_attempt_starting_during_replan_prevents_revision_publication(self):
        definition=[node('A'),node('I',['A'],integration=True,write=())]
        self.revise(definition)
        changed=copy.deepcopy(definition); changed[0]['goal']+=' refined'
        original=internal_plan.decide
        def single_race(*args,**kwargs):
            result=original(*args,**kwargs)
            with patch.object(internal_plan,'decide',original):
                self.step(lambda ledger,control,task,item,attempt:{'artifact':self.store.blob(b'unknown'),'receipt':self.store.blob(b'pending attempt')})
            return result
        with patch.object(internal_plan,'decide',side_effect=single_race):
            with self.assertRaisesRegex(LedgerError,'active workflow attempt'): self.revise(changed)
        self.assertEqual(self.ip.current(self.ledger,'P1')['internal_revision'],1)
