"""Installed preparation/recovery CLI, with explicit fixture executor and check receipts."""
import json

from tests.test_v2_l1 import plan_json
from tests.test_wf_engine import node
from tests import test_wf_installed_features as installed_fixture


class InstalledNodeActionsTests(installed_fixture.InstalledFeaturesTests):
    test_workflow_approval_evidence_report_outcome_context_and_metrics = None
    test_non_git_data_artifact_uses_same_lifecycle_and_present = None
    test_installed_progress_and_owner_stop_keep_evidence_and_end_the_root = None
    test_installed_verified_repair_creates_project_lesson_before_root_completion = None

    def test_installed_preparation_then_failed_first_bounded_repair(self):
        value = plan_json(scope={'owned': ['a.txt', 'b.txt']}, authority={
            'edit': True, 'commands': True, 'edit_tests': True,
            'self_decide': ['Q1', 'Q2', 'Q3', 'Q4', 'Q5', 'Q9', 'Q12']})
        definition = [node('A'), node('I', ['A'], integration=True, write=())]
        self.check_body('''
import contextlib, io, json, os, subprocess, tempfile
from pathlib import Path
from onecrew.ledger import Ledger
from onecrew.control_core import Control, migrate
from onecrew.snapshots import Snapshots
from onecrew.v2 import engine, plan, repair_tasks
from onecrew.v2.cli import main
with tempfile.TemporaryDirectory() as temp:
    root=Path(temp)/'project'; root.mkdir(); (root/'a.txt').write_text('base\\n')
    def git(*args): return subprocess.check_output(['git','-C',str(root),*args],stderr=subprocess.PIPE).decode().strip()
    git('init','-q'); git('add','.'); git('-c','user.name=fixture','-c','user.email=fixture@localhost','commit','-qm','base')
    ledger=Ledger(root,Path(temp)/'state'); store=Snapshots(ledger.state_root)
    plan.propose(ledger,'P1',json.loads('''+repr(json.dumps(value))+'''),'codex',workflow=True,
                 capabilities=['namespaced-storage','root-budget','internal-plan','sequential-engine'])
    plan.approve(ledger,'P1','owner','temporary fixture only'); os.environ['ONECREW_ACTOR']='codex'
    migrate(ledger); control=Control(ledger)
    def cli(command,body=None,extra=()):
        args=['--project',str(root),'--state-root',str(ledger.state_root),'engine',command,'P1',*extra]
        if body is not None:
            file=Path(temp)/'action.json'; file.write_text(json.dumps(body)); args+=['--file',str(file)]
        output=io.StringIO()
        with contextlib.redirect_stdout(output): code=main(args)
        assert code==0,output.getvalue()
        return json.loads(output.getvalue())
    cli('revise',{'nodes':json.loads('''+repr(json.dumps(definition))+'''),'reason':'Fixture split','evidence':['a.txt:1']})
    cli('prepare-tests',{'implementation':'A','node_id':'Tests','write':['b.txt'],
        'checks':[{'id':'prep','spec':'Acceptance cases prepared'}], 'estimate_seconds':[1,2],
        'execution_cap_seconds':60,'budget_calls':1,'reason':'Acceptance tests before code','evidence':['a.txt:1']})
    assert [n['id'] for n in cli('ready')]==['Tests']
    def execute(ledger,control,task,item,attempt):
        control.launched(attempt['id'],attempt['generation'],{'fixture':True})
        control.finish(attempt['id'],attempt['generation'],{'fixture':True})
        return {'artifact':store.blob(('fixture artifact '+item['id']).encode()),'receipt':store.blob(b'fixture executor receipt')}
    def checker(result):
        return lambda item,artifact: {'artifact':artifact,'checks':[{'id':c['id'],'result':result,'evidence':store.blob(b'fixture check observation')} for c in item['checks']]}
    engine.step(ledger,'P1',execute,control=control); assert cli('ready')==[]
    engine.verify(ledger,'P1','Tests',checker('pass'))
    engine.step(ledger,'P1',execute,control=control); engine.verify(ledger,'P1','A',checker('fail'))
    first=cli('diagnose',extra=['A']); assert first['disposition']=='repair'
    cli('repair',{'target':'A','failed_node':'A','reason':'Repair genuine failed fixture check','evidence':[first['source_receipt']]})
    order=repair_tasks.verification_order(ledger,'P1','A',[{'id':'check-A'}])
    assert order['failed_first']==['check-A'] and order['stop_on_failed_prerequisite']
    engine.step(ledger,'P1',execute,control=control); engine.verify(ledger,'P1','A',checker('fail'))
    second=cli('diagnose',extra=['A']); assert second['disposition']=='diagnose'
    assert second['record']['count']==2 and not second['creates_owner_request']
    assert plan.show(ledger,'P1')['status']=='approved'
''')
