"""Actual verifier finding/register → read/write closure → common engine."""
import os
import sys
import contextlib
import io
import json
from types import SimpleNamespace
from unittest.mock import patch

from onecrew import dependency_core
from onecrew.control_core import Control, migrate
from onecrew.snapshots import Snapshots
from onecrew.v2 import active_plan, engine, finding_scope, findings, hook_cli, internal_plan, plan, verdict
from tests.test_v2_l1 import Fixture, milestone, plan_json
from tests.test_wf_engine import EngineFixture, node


class FindingScopeTests(EngineFixture):
    def setUp(self):
        Fixture.setUp(self)
        self.engine, self.ip = engine, internal_plan
        check=milestone(); check['verifier']={'type':'data','config':{'path':'a.txt','columns':{'one':'string'},'key':['one'],'row_count':2}}
        raw = plan_json(milestones=[check], scope={'owned':['a.txt','b.txt','x.txt']},
            review_policy={'depth':'light','optional_reviews':['OptionalReview']},
            authority={'edit':True,'commands':True,'self_decide':['Q1','Q2','Q3','Q4','Q8','Q9','Q12']})
        caps = ['namespaced-storage','finding-register','root-budget','internal-plan','sequential-engine']
        self.root_view = plan.propose(self.ledger,'P1',raw,'codex',workflow=True,capabilities=caps)
        plan.approve(self.ledger,'P1','owner','temporary fixture grant')
        self.store = Snapshots(self.ledger.state_root); migrate(self.ledger); self.control=Control(self.ledger)
        os.environ['ONECREW_ACTOR']='codex'
        definition=[node('Nw'),node('Nr',write=()),node('Nd',['Nw'],write=('b.txt',)),
                    node('Nx',write=('x.txt',)),node('I',['Nw','Nr','Nd','Nx'],integration=True,write=())]
        definition[2]['read']=[]; definition[3]['read']=['x.txt']; definition[4]['read']=[]
        self.revise(definition)

    def open_finding(self):
        verdict.run(self.ledger,'P1','M1')
        rows=findings.list_findings(self.ledger,'P1',open_only=True)
        self.assertEqual(len(rows),1)
        findings.update(self.ledger,'P1',rows[0]['id'],reason='The failing assertion reads only a.txt',read=['a.txt'],write=[])
        return rows[0]['id']

    def resolve_finding(self, ident):
        (self.root/'a.txt').write_text('one\nrow1\nrow2\n')
        shown=verdict.run(self.ledger,'P1','M1')
        receipt=shown['milestones'][0]['last_verdict']['receipt']
        findings.resolve(self.ledger,'P1',ident,receipt,reason='Original failing assertion now passes',artifact_sha=self.tree())

    def hook(self, tool, data):
        event={'cwd':str(self.root),'session_id':'fixture-external','tool_name':tool,'tool_input':data}
        error=io.StringIO()
        with patch.object(hook_cli,'read_stdin',return_value=(event,None)), contextlib.redirect_stderr(error):
            result=hook_cli.check(SimpleNamespace(project=self.root,state_root=self.ledger.state_root))
        return result,error.getvalue()

    def test_exported_external_hook_withdraws_only_affected_writes_without_opening_ledger(self):
        active_plan.set_mode(self.ledger,'enforce')
        ident=self.open_finding()
        snapshot=json.loads(active_plan.project_file(self.root).read_text(encoding='utf-8'))
        self.assertEqual(snapshot['workflow_holds']['paths'],['a.txt','b.txt'])
        with patch.object(type(self.ledger),'transaction',side_effect=AssertionError('hot hook must not read ledger')):
            for name in ('a.txt','b.txt'):
                code,reason=self.hook('Edit',{'file_path':str(self.root/name)})
                self.assertEqual(code,2); self.assertIn('write permission is withdrawn',reason)
                self.assertIn('session is not stopped',reason)
            self.assertEqual(self.hook('Edit',{'file_path':str(self.root/'x.txt')})[0],0)
            self.assertEqual(self.hook('PowerShell',{'command':"Set-Content b.txt 'changed'"})[0],2)
            self.assertEqual(self.hook('Read',{'file_path':str(self.root/'a.txt')})[0],0)
        self.resolve_finding(ident)
        self.assertEqual(self.hook('Edit',{'file_path':str(self.root/'a.txt')})[0],0)

    def test_late_finding_retains_settled_candidate_then_resolution_releases_without_retry(self):
        calls=[]; opened=[]
        def late(ledger,control,task,item,attempt):
            calls.append(item['id']); result=self.execute(ledger,control,task,item,attempt)
            opened.append(self.open_finding()); return result
        result=self.step(late)
        self.assertEqual(result['state'],'retained')
        self.assertNotIn('node.produced',self.kinds())
        self.assertEqual(self.step()['node'],'Nx')
        self.resolve_finding(opened[0])
        released=self.step(late)
        self.assertTrue(released['released_retained'])
        self.assertEqual(released['artifact'],result['artifact'])
        self.assertEqual(calls,['Nw'])

    def test_finding_changes_optional_and_required_rule_cache_to_hold_without_calling_checker(self):
        from onecrew.v2 import review_dispatch
        produced=self.step()
        def forbidden(*args):raise AssertionError('held/skipped review must not call a checker')
        skipped=self.engine.review_optional(self.ledger,'P1','Nw','OptionalReview',forbidden,produced['artifact'])
        self.assertEqual(skipped['decision']['action'],'SKIP')
        ident=self.open_finding()
        held=self.engine.review_optional(self.ledger,'P1','Nw','OptionalReview',forbidden,produced['artifact'])
        self.assertEqual(held['decision']['action'],'HOLD')
        self.assertIn('Unresolved findings: '+ident,held['decision']['reason'])
        self.assertNotEqual(held['decision']['validity']['input_sha'],skipped['decision']['validity']['input_sha'])
        required=review_dispatch.required(self.ledger,'P1','Nw',['check-Nw'])
        self.assertEqual(required['action'],'HOLD')
        self.resolve_finding(ident)
        self.assertEqual(self.engine.review_optional(self.ledger,'P1','Nw','OptionalReview',forbidden,produced['artifact'])['decision']['action'],'SKIP')

    def test_real_register_holds_writers_readers_and_dependents_but_independent_node_runs(self):
        ident=self.open_finding()
        before=self.ledger.events(self.root_view['anchor_task'])
        with patch.object(dependency_core,'affected_tasks',wraps=dependency_core.affected_tasks) as reused:
            held=finding_scope.blockers(self.ledger,'P1',self.ip.current(self.ledger,'P1')['definition']['nodes'])
            self.assertEqual(held,{nid:[ident] for nid in ('Nw','Nr','Nd','I')})
            self.assertGreaterEqual(reused.call_count,1)
        view=self.engine.state(self.ledger,'P1')
        self.assertEqual(view['finding_blockers'],held)
        self.assertEqual(self.ledger.events(self.root_view['anchor_task']),before)
        self.assertEqual([item['id'] for item in self.engine.ready(self.ledger,'P1')],['Nx'])
        self.assertEqual(self.step()['node'],'Nx')
        self.assertFalse(self.engine.root_ready(self.ledger,'P1'))

    def test_actual_repair_receipt_resolves_only_finding_overlay_and_restores_ready_node(self):
        ident=self.open_finding()
        self.resolve_finding(ident)
        self.assertEqual(finding_scope.blockers(self.ledger,'P1',self.ip.current(self.ledger,'P1')['definition']['nodes']),{})
        self.assertEqual(self.engine.state(self.ledger,'P1')['finding_blockers'],{})
        self.assertEqual([item['id'] for item in self.engine.ready(self.ledger,'P1')],['Nw'])
