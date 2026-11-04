"""The actual installed engine consumer, fake CLI provider only; real Git/checks/CAS."""
import json

from tests.test_v2_l1 import plan_json
from tests.test_wf_engine import node
from tests import test_wf_installed_features as installed_fixture


class InstalledNativeTests(installed_fixture.InstalledFeaturesTests):
    test_workflow_approval_evidence_report_outcome_context_and_metrics = None
    test_non_git_data_artifact_uses_same_lifecycle_and_present = None
    test_installed_progress_and_owner_stop_keep_evidence_and_end_the_root = None
    test_installed_verified_repair_creates_project_lesson_before_root_completion = None

    def test_installed_parallel_managed_processes_then_actual_integration_and_handoff(self):
        raw=plan_json(scope={'owned':['a.txt','b.txt']},authority={'edit':True,'commands':True,'unconfined_commands':True,
            'apply_to_project':True,'self_decide':['Q1','Q2','Q3','Q4','Q9','Q12']})
        second=json.loads(json.dumps(raw['milestones'][0]));second['id']='M2';second['title']='Check second producer';raw['milestones'].append(second)
        raw['understanding']['target']['paths']=['a.txt','b.txt']
        nodes=[node('A'),node('B',write=('b.txt',)),node('I',['A','B'],integration=True,write=())]
        nodes[1]['read']=['b.txt'];nodes[2]['read']=['a.txt','b.txt']
        for item,ids in zip(nodes,[['M1'],['M2'],['M1','M2']]):
            item['executor']={'role':'worker','provider':'codex','model':'fixture-model'}
            item['checks']=[{'id':mid,'spec':'Run approved '+mid} for mid in ids]
        self.check_body('''
import contextlib,io,json,os,subprocess,sys,tempfile
from pathlib import Path
from onecrew import artifact_provider_core
from onecrew.budget_core import group
from onecrew.ledger import Ledger
from onecrew.process_core import Supervisor,native_python
from onecrew.subscription import environment
from onecrew.v2 import plan,engine
from onecrew.v2.cli import main
with tempfile.TemporaryDirectory() as temp:
    root=Path(temp)/'project';root.mkdir();(root/'a.txt').write_text('base\\n');(root/'b.txt').write_text('base-b\\n')
    def git(*args):return subprocess.check_output(['git','-C',str(root),*args],stderr=subprocess.PIPE).decode().strip()
    git('init','-q');git('add','.');git('-c','user.name=fixture','-c','user.email=fixture@localhost','commit','-qm','base')
    initial_index=git('write-tree');ledger=Ledger(root,Path(temp)/'state')
    raw=json.loads('''+repr(json.dumps(raw))+''')
    for milestone,path in zip(raw['milestones'],['a.txt','b.txt']):
        milestone['verifier']['config']['argv']=[sys.executable,'-c','from pathlib import Path; assert Path('+repr(path)+').read_text()=='+repr('candidate-'+path+'\\n')+'; print("actual candidate check passed")']
    caps=['namespaced-storage','root-budget','internal-plan','sequential-engine','parallel-engine']
    plan.propose(ledger,'P1',raw,'codex',workflow=True,capabilities=caps);plan.approve(ledger,'P1','owner','temporary bounded two-slot fixture')
    os.environ['ONECREW_ACTOR']='codex'
    ready=Path(temp)/'ready';ready.mkdir();calls=[]
    def factory(control,provider):
        class Worker:
            def capability(self):return {'provider':provider,'mode':'local-process-no-provider'}
            def run(self,attempt,prompt,schema,profile):
                calls.append(attempt['id']);directory=ledger.state_root/'worker-io'/attempt['id'];directory.mkdir(parents=True)
                paths=schema['properties'].get('files',{}).get('items',{}).get('properties',{}).get('path',{}).get('enum',[])
                value=({'summary':'isolated producer','files':[{'path':path,'content':'candidate-'+path+'\\n'} for path in paths],'backlog':[]} if paths else {'summary':'integration report','evidence':[]})
                script='import pathlib,sys,time\\nready=pathlib.Path(sys.argv[1]);(ready/sys.argv[2]).write_text("ready")\\nend=time.monotonic()+5\\nwhile sys.argv[4]=="pair" and len(list(ready.iterdir()))<2 and time.monotonic()<end:time.sleep(.02)\\nassert sys.argv[4]!="pair" or len(list(ready.iterdir()))>=2,"second slot missing"\\npathlib.Path("answer.json").write_text(sys.argv[3])\\n'
                return Supervisor(control).run(attempt,[native_python(),'-c',script,str(ready),attempt['id'],json.dumps(value),'pair' if paths else 'single'],cwd=directory,timeout=8,env=environment())
            def result(self,attempt):return json.loads((ledger.state_root/'worker-io'/attempt['id']/'answer.json').read_text()),[]
        return Worker()
    def cli(*args):
        out=io.StringIO()
        with contextlib.redirect_stdout(out):code=main(['--project',str(root),'--state-root',str(ledger.state_root),*args])
        assert code==0,out.getvalue();return json.loads(out.getvalue())
    definition=Path(temp)/'nodes.json';definition.write_text(json.dumps({'nodes':json.loads('''+repr(json.dumps(nodes))+'''),'reason':'Explicit disjoint producers and mandatory integration','evidence':['a.txt:1']}))
    cli('engine','revise','P1','--file',str(definition))
    with ledger.transaction() as conn:before=group(conn,plan.show(ledger,'P1')['anchor_task'])
    original=artifact_provider_core.make_worker;artifact_provider_core.make_worker=factory
    try:
        batch=cli('engine','batch','plan-ns:P1','--slots','2');assert all(item['state']=='produced' for item in batch['results']),batch
        cli('engine','verify','P1','A');cli('engine','verify','P1','B')
        cli('engine','step','P1');cli('engine','verify','P1','I')
        delivered=cli('engine','handoff','P1')
    finally:artifact_provider_core.make_worker=original
    assert len(calls)==3
    assert git('write-tree')==initial_index
    assert (root/'a.txt').read_text()=='candidate-a.txt\\n' and (root/'b.txt').read_text()=='candidate-b.txt\\n'
    assert engine.root_ready(ledger,'P1',delivered['artifact'])
    cli('verdict','run','--plan','P1','--milestone','M1');cli('verdict','run','--plan','P1','--milestone','M2')
    os.environ.pop('ONECREW_ACTOR',None);assert plan.accept(ledger,'P1','owner','actual two-slot delivered fixture accepted',delivered['artifact'])['status']=='accepted'
    with ledger.transaction() as conn:after=group(conn,plan.show(ledger,'P1')['anchor_task'])
    assert after['used_calls']==3 and after['reserved_calls']==0 and after['deadline']==before['deadline']
    assert not any(name in sys.modules for name in ('onecrew.workflow','onecrew.control','onecrew.supervisor','onecrew.solution_gate'))
''')

    def test_installed_cli_producer_integration_commands_cas_and_owner_accept(self):
        contract = plan_json(authority={'edit': True, 'commands': True, 'unconfined_commands': True,
            'apply_to_project': True, 'self_decide': ['Q1','Q2','Q3','Q4','Q9','Q12']})
        nodes = [node('C'), node('I',['C'],integration=True,write=())]
        for item in nodes:
            item['executor'] = {'role':'worker','provider':'codex','model':'gpt-6.1-sol'}
            item['checks'] = [{'id':'M1','spec':'Run the approved immutable root command'}]
        self.check_body('''
import contextlib, importlib.util, io, json, os, subprocess, sys, tempfile
from pathlib import Path
from unittest.mock import patch
from onecrew.ledger import Ledger, LedgerError
from onecrew.v2 import engine, plan, verdict
from onecrew.v2.cli import main
assert importlib.util.find_spec('onecrew.workflow') is None
assert importlib.util.find_spec('onecrew.control') is None
with tempfile.TemporaryDirectory() as temp:
    root=Path(temp)/'project'; root.mkdir(); (root/'a.txt').write_text('base\\n')
    def git(*args): return subprocess.check_output(['git','-C',str(root),*args],stderr=subprocess.PIPE).decode().strip()
    git('init','-q'); git('add','.'); git('-c','user.name=fixture','-c','user.email=fixture@localhost','commit','-qm','base')
    original_index=git('write-tree')
    ledger=Ledger(root,Path(temp)/'state')
    raw=json.loads('''+repr(json.dumps(contract))+''')
    raw['milestones'][0]['verifier']['config']['argv']=[sys.executable,'-c','from pathlib import Path; assert Path("a.txt").read_text()=="candidate\\\\n"; print("actual installed candidate checked")']
    plan.propose(ledger,'P1',raw,'codex',workflow=True,capabilities=['namespaced-storage','root-budget','internal-plan','sequential-engine'])
    plan.approve(ledger,'P1','owner','temporary authorized fixture')
    os.environ['ONECREW_ACTOR']='codex'
    calls=[]
    def factory(control,provider):
        class Worker:
            def capability(self): return {'provider':provider,'mode':'fixture-no-tools'}
            def run(self,attempt,prompt,schema,profile):
                calls.append({'provider':provider,'model':profile['model']})
                control.launched(attempt['id'],attempt['generation'],{'fixture':True})
                control.finish(attempt['id'],attempt['generation'],{'exit_code':0})
            def result(self,attempt):
                return ({'summary':'producer','files':[{'path':'a.txt','content':'candidate\\n'}],'backlog':[]}
                        if len(calls)==1 else {'summary':'readonly integration','evidence':[]}),[]
        return Worker()
    def cli(*args):
        output=io.StringIO()
        with contextlib.redirect_stdout(output): code=main(['--project',str(root),'--state-root',str(ledger.state_root),*args])
        assert code==0,output.getvalue()
        return json.loads(output.getvalue())
    definition=Path(temp)/'internal.json'
    definition.write_text(json.dumps({'nodes':json.loads('''+repr(json.dumps(nodes))+'''),'reason':'Bounded explicit nodes','evidence':['a.txt:1']}))
    cli('engine','revise','plan-ns:P1','--file',str(definition))
    with patch('onecrew.artifact_provider_core.make_worker',side_effect=factory):
        cli('engine','step','plan-ns:P1'); cli('engine','verify','plan-ns:P1','C')
        cli('engine','step','plan-ns:P1'); cli('engine','verify','plan-ns:P1','I')
        assert (root/'a.txt').read_text()=='base\\n'
        assert not engine.root_ready(ledger,'P1')
        result=cli('engine','handoff','plan-ns:P1')
    assert calls==[{'provider':'codex','model':'gpt-6.1-sol'}]*2
    assert (root/'a.txt').read_text()=='candidate\\n'
    assert git('write-tree')==original_index
    assert engine.root_ready(ledger,'P1',result['artifact'])
    assert plan.show(ledger,'P1')['status']=='approved'
    cli('verdict','run','--plan','plan-ns:P1','--milestone','M1')
    os.environ.pop('ONECREW_ACTOR',None)
    accepted=plan.accept(ledger,'P1','owner','actual installed delivered tree accepted',result['artifact'])
    assert accepted['status']=='accepted'
    assert not any(name in sys.modules for name in ('onecrew.workflow','onecrew.supervisor','onecrew.control','onecrew.owned','onecrew.solution_gate'))
''')
