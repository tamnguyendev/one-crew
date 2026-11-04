"""T36c E19/E20: real plan/engine/ledger flow, declared fixture estimates only.

Proves preserved baseline, split conservation, sourced mandatory additions and
remaining unfinished work. No calibrated ETA, real provider or pilot claim.
"""
import copy
import os
from unittest.mock import patch

from onecrew.ledger import Ledger, LedgerError
from onecrew.v2 import estimates, internal_plan, plan, report, runtime_unknowns
from tests.test_v2_l1 import plan_json
from tests.test_wf_engine import EngineFixture, node


class InternalEstimateTests(EngineFixture):
    def setUp(self):
        super().setUp()
        value=plan_json(budget={'max_calls':100,'time':600},scope={'owned':['a.txt','b.txt']},authority={
            'edit':True,'commands':True,'edit_tests':True,'self_decide':['Q1','Q2','Q3','Q4','Q9','Q12']})
        plan.propose(self.ledger,'ETA',value,'codex',workflow=True,capabilities=self.engine_caps)
        with patch.dict(os.environ,{'ONECREW_ACTOR':''}):
            plan.approve(self.ledger,'ETA','owner','temporary estimate fixture',estimate={
                'execution_seconds':[21600,28800],'evidence':['initial declared estimate']})
        self.baseline=estimates.read(self.ledger,'ETA')['baseline']

    def definition(self):
        nodes=[node('A'),node('B',write=('b.txt',)),node('I',['A','B'],integration=True,write=())]
        nodes[1]['read']=['b.txt']
        for item,span in zip(nodes,([10,20],[20,30],[2,3])): item['estimate_seconds']=span
        return nodes

    def revise(self,nodes,reason='Split within approved acceptance',refs=None):
        return internal_plan.revise(self.ledger,'ETA',nodes,reason=reason,evidence=refs or ['a.txt:1'])

    def forecast(self): return estimates.read(self.ledger,'ETA')

    def test_split_and_mandatory_task_preserve_baseline_and_do_not_double_count(self):
        nodes=self.definition(); self.revise(nodes)
        self.assertEqual(self.forecast()['remaining_seconds'],[32,53])
        split=copy.deepcopy(nodes)
        split[0]['estimate_seconds']=[4,8]
        second=node('A2'); second['estimate_seconds']=[6,12]
        split.insert(1,second); split[-1]['depends'].append({'node':'A2','requires':'verified'})
        self.revise(split,'Split A without changing its total work')
        self.assertEqual(self.forecast()['remaining_seconds'],[32,53])
        estimates.additional(self.ledger,'ETA','migration','mandatory','Required migration for O1',['O1'],[5,7],['a.txt:1'])
        self.assertEqual(self.forecast()['remaining_seconds'],[37,60])
        estimates.additional(self.ledger,'ETA','cleanup','optional','Unnecessary cleanup',['O1'],[100,200],['a.txt:1'])
        self.assertEqual(self.forecast()['remaining_seconds'],[37,60])
        added=copy.deepcopy(split); migration=node('M'); migration['estimate_seconds']=[5,7]
        added.insert(-1,migration); added[-1]['depends'].append({'node':'M','requires':'verified'})
        self.revise(added,'Represent mandatory migration as its own bounded task',['work.additional:migration','a.txt:1'])
        current=self.forecast()
        self.assertEqual(current['remaining_seconds'],[37,60])
        self.assertEqual(current['history'][-1]['incorporated_additions'],['migration'])
        self.assertEqual(current['baseline'],self.baseline)
        self.assertTrue(all(row['reason'] and row['evidence'] for row in current['history']))
        restarted=Ledger(self.ledger.project,self.ledger.state_root)
        self.assertEqual(estimates.read(restarted,'ETA')['history'],current['history'])
        self.assertEqual(estimates.read(restarted,'ETA')['baseline'],self.baseline)

    def test_verified_node_is_not_added_back_by_unrelated_replan(self):
        nodes=self.definition(); self.revise(nodes)
        self.engine.step(self.ledger,'ETA',self.execute,control=self.control)
        self.engine.verify(self.ledger,'ETA','A',self.checker)
        self.assertEqual(self.forecast()['remaining_seconds'],[22,33])
        changed=copy.deepcopy(nodes); changed[1]['goal']+=' clarified'
        self.revise(changed,'Clarify B, retain verified A')
        self.assertEqual(self.engine.state(self.ledger,'ETA')['nodes']['A']['state'],'verified')
        self.assertEqual(self.forecast()['remaining_seconds'],[22,33])
        self.assertEqual(self.forecast()['baseline'],self.baseline)

    def test_unknown_estimate_is_not_zero_and_observation_reuses_same_basis(self):
        nodes=[node('S',write=()),node('A',['S']),node('I',['S','A'],integration=True,write=())]
        self.revise(nodes)
        runtime_unknowns.open_unknown(self.ledger,'ETA','schema',question='Which schema applies?',affected=['A'],
            required_by=['A'],resolver='poc',evidence=['a.txt:1'],blocks_estimate=True,survey_node='S')
        self.assertIsNone(self.forecast()['remaining_seconds'])
        first=estimates.observe_internal(self.ledger,'ETA',reason='Schema estimate needs bounded survey',evidence=['a.txt:1'])
        self.assertIsNone(first['remaining_seconds'])
        count=len(self.forecast()['history'])
        second=estimates.observe_internal(self.ledger,'ETA',reason='Same unresolved source observed again',evidence=['a.txt:1'])
        self.assertEqual(first['key'],second['key']); self.assertEqual(len(self.forecast()['history']),count)
        self.assertEqual(self.forecast()['execution_seconds'],'unknown')

    def test_work_sum_never_claims_wall_clock_parallel_eta_or_measured_zero(self):
        self.revise(self.definition())
        result=self.forecast()
        self.assertEqual(result['remaining_kind'],'execution_work')
        self.assertEqual(result['remaining_seconds'],[32,53])
        self.assertIsNone(result['wall_clock_remaining_seconds'])
        self.assertEqual(result['execution_seconds'],'unknown')
        self.assertEqual(result['waiting_seconds'],'unknown')
        self.assertFalse(result['calibrated'])

    def test_late_forecast_callback_cannot_overwrite_newer_internal_revision(self):
        nodes=self.definition(); self.revise(nodes)
        stale=self.engine.state(self.ledger,'ETA')
        newer=copy.deepcopy(nodes); newer[1]['estimate_seconds']=[30,40]
        self.revise(newer,'New sourced estimate for B')
        before=self.forecast()['history']
        self.engine._forecast(self.ledger,stale,'obsolete-callback','Late callback must reread current state')
        self.assertEqual(self.forecast()['remaining_seconds'],[42,63])
        self.assertEqual(self.forecast()['history'],before)

    def test_read_does_not_record_or_accept_an_unsourced_manual_override(self):
        self.revise(self.definition())
        estimates.reforecast(self.ledger,'ETA','manual-zero',[0,0],'Unsourced task completion claim',['a.txt:1'])
        with self.ledger.transaction() as conn: before=conn.execute('SELECT MAX(seq) FROM events').fetchone()[0]
        result=self.forecast()
        self.assertIsNone(result['remaining_seconds']); self.assertFalse(result['internal_basis_current'])
        with self.ledger.transaction() as conn: self.assertEqual(before,conn.execute('SELECT MAX(seq) FROM events').fetchone()[0])
        restored=estimates.observe_internal(self.ledger,'ETA',reason='Restore forecast from actual task evidence',evidence=['a.txt:1'])
        self.assertEqual(restored['remaining_seconds'],[32,53])
        with self.assertRaises(LedgerError):
            estimates.observe_internal(self.ledger,'ETA',reason='',evidence=['a.txt:1'])
