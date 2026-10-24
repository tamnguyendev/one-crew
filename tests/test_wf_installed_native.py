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
