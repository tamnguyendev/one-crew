"""Installed survey and registered-verifier consumers; explicit fake model only."""
import json

from tests.test_v2_l1 import plan_json
from tests.test_wf_engine import node
from tests.test_wf_r01_step0_survey import scoped_plan
from tests import test_wf_installed_features as installed_fixture


class InstalledCommonConsumersTests(installed_fixture.InstalledFeaturesTests):
    test_workflow_approval_evidence_report_outcome_context_and_metrics = None
    test_non_git_data_artifact_uses_same_lifecycle_and_present = None
    test_installed_progress_and_owner_stop_keep_evidence_and_end_the_root = None
    test_installed_verified_repair_creates_project_lesson_before_root_completion = None

    def test_installed_survey_then_doc_data_candidate_and_handoff(self):
        value = plan_json(scope={'owned': ['guide.md', 'data.csv']}, authority={
            'edit': True, 'apply_to_project': True, 'self_decide': ['Q1','Q2','Q3','Q4','Q9','Q12']})
        value['milestones'] = [
            {'id': 'M1', 'title': 'Document', 'covers': ['O1'], 'verifier': {'type': 'doc',
                'config': {'docs': [{'path': 'guide.md', 'headings': ['Summary']}]}}},
            {'id': 'M2', 'title': 'Data', 'covers': ['O1'], 'verifier': {'type': 'data',
                'config': {'path': 'data.csv', 'columns': {'id':'integer'}, 'key':['id'], 'row_count':1}}}]
        nodes = [node('C', write=['guide.md', 'data.csv']), node('I', ['C'], integration=True, write=())]
        for row in nodes:
            row['read'] = ['guide.md', 'data.csv']
            row['checks'] = [{'id': 'M1', 'spec': 'Approved document checks'}, {'id': 'M2', 'spec': 'Approved data checks'}]
        self.check_body('''
import contextlib, io, json, os, subprocess, tempfile
from pathlib import Path
from onecrew.ledger import Ledger
from onecrew.control_core import Control, migrate
from onecrew.snapshots import Snapshots
from onecrew.common_handoff import handoff
from onecrew.common_verification import CandidateChecker
from onecrew.v2 import engine, internal_plan, plan, survey
from onecrew.v2.verifiers import reviewer
from onecrew.v2.cli import main
with tempfile.TemporaryDirectory() as temp:
    root=Path(temp)/'project'; root.mkdir(); (root/'a.txt').write_text('Source fact.\\n')
    (root/'guide.md').write_text('# Before\\n'); (root/'data.csv').write_bytes(b'id\\r\\n1\\r\\n')
    def git(*args): return subprocess.check_output(['git','-C',str(root),*args],stderr=subprocess.PIPE).decode().strip()
    git('init','-q'); git('config','core.autocrlf','true'); git('add','.')
    git('-c','user.name=fixture','-c','user.email=fixture@localhost','commit','-qm','base')
    ledger=Ledger(root,Path(temp)/'state'); store=Snapshots(ledger.state_root)
    plan.propose(ledger,'Survey',json.loads('''+repr(json.dumps(scoped_plan()))+'''),'codex')
    opened=survey.open_survey(ledger,'Survey','U1',{'cap':{'minutes':1,'calls':2},
        'end_condition':'Cite source fact','scope':{'mode':'read_only','paths':['a.txt']}})
    config=Path(temp)/'worker.json'; config.write_text(json.dumps({'provider':'codex','model':'fixture','paths':['a.txt']}))
    calls=[]
    def provider(prompt,config,env,scratch,limit):
        calls.append(config['model'])
        return json.dumps({'answer':'Source fact is present.','evidence':'a.txt:1','quote':'Source fact.',
            'hypothesis':'confirmed','resolved':True,'confidence':'high'}),{},None,False,b'fixture'
    original=reviewer.call; reviewer.call=provider
    try:
        output=io.StringIO()
        with contextlib.redirect_stdout(output):
            code=main(['--project',str(root),'--state-root',str(ledger.state_root),'plan','survey','run',
                       'Survey',opened['id'],'--file',str(config)])
        assert code==0,output.getvalue()
        assert json.loads(output.getvalue())['status']=='answered' and calls==['fixture']
    finally: reviewer.call=original
    plan.propose(ledger,'P1',json.loads('''+repr(json.dumps(value))+'''),'codex',workflow=True,
        capabilities=['namespaced-storage','root-budget','internal-plan','sequential-engine'])
    plan.approve(ledger,'P1','owner','temporary fixture only'); os.environ['ONECREW_ACTOR']='codex'
    internal_plan.revise(ledger,'P1',json.loads('''+repr(json.dumps(nodes))+'''),reason='Common adapter nodes',evidence=['a.txt:1'])
    migrate(ledger); control=Control(ledger)
    def execute(ledger,control,task,item,attempt):
        control.launched(attempt['id'],attempt['generation'],{'fixture':True})
        artifact=store.overlay(store.capture(root,['guide.md','data.csv']),{'guide.md':b'# Summary\\nDelivered.\\n'},['guide.md','data.csv'])
        control.finish(attempt['id'],attempt['generation'],{'fixture':True,'artifact':artifact})
        return {'artifact':artifact,'receipt':store.blob(b'fixture execution')}
    checker=CandidateChecker(ledger,'P1')
    engine.step(ledger,'P1',execute,control=control); assert engine.verify(ledger,'P1','C',checker)['result']=='pass'
    engine.step(ledger,'P1',execute,control=control); assert engine.verify(ledger,'P1','I',checker)['result']=='pass'
    result=handoff(ledger,'P1'); assert engine.root_ready(ledger,'P1',result['artifact'])
    assert (root/'guide.md').read_text()=='# Summary\\nDelivered.\\n'
    assert plan.show(ledger,'P1')['status']=='approved'
''')
