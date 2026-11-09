"""Cross-feature execution from an offline temporary wheel installation only."""
import json
import shutil
import unittest
from tests import wf_wheel as wh
from tests.test_v2_l1 import plan_json
from onecrew.v2 import boundary


class InstalledFeaturesTests(unittest.TestCase):
    def setUp(self):
        from tests.wf_env import owner_terminal
        owner_terminal(self)        # installed scenarios include owner verbs: the owner's own terminal, not an AI session

    @classmethod
    def setUpClass(cls):
        cls.runs = wh._runs()
        cls.wheel, _, (modules, packages) = wh.build_wheel(cls.runs)
        cls.python = wh.make_venv(cls.runs)
        wh.install(cls.python, cls.wheel)
        cls.ctx = wh.build_ctx(cls.python, modules, packages)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.runs, ignore_errors=True)

    def check_body(self, body):
        dump, tail = wh.run_case(self.python, body, cwd=self.runs)
        self.assertIsNotNone(dump, tail)
        self.assertEqual(boundary.violations(dump['end'], self.ctx), [], tail)

    def test_workflow_approval_evidence_report_outcome_context_and_metrics(self):
        contract = json.dumps(plan_json())
        self.check_body('''
import json, os, sys, subprocess, tempfile
from pathlib import Path
from onecrew.ledger import Ledger
from onecrew.v2 import plan, verdict, retention, estimates, report, outcome, context, resume_pack, metrics
with tempfile.TemporaryDirectory() as temp:
    root = Path(temp)/'project'; root.mkdir()
    def git(*args):
        subprocess.run(['git','-C',str(root),*args], check=True, capture_output=True)
    git('init','-q'); git('config','user.name','Fixture'); git('config','user.email','fixture@localhost')
    (root/'a.txt').write_text('base\\n'); git('add','.'); git('commit','-qm','base')
    ledger = Ledger(root, Path(temp)/'state')
    contract = json.loads(''' + repr(contract) + ''')
    contract['milestones'][0]['verifier']['config']['argv'] = [sys.executable,'-c','print("ok")']
    plan.propose(ledger, 'P1', contract, 'codex', workflow=True)
    plan.approve(ledger, 'P1', 'owner', 'authorized temporary fixture', estimate={'execution_seconds':[60,120], 'evidence':['fixture decomposition']})
    verified = verdict.run(ledger, 'P1', 'M1')
    assert verified['milestones'][0]['state'] == 'passed'
    assert retention.list_refs(ledger, 'P1')
    with ledger.transaction() as conn:
        task = plan.derive(ledger, conn, 'P1')['task_id']
        event = conn.execute("SELECT seq FROM events WHERE task_id=? AND kind='milestone.passed'", (task,)).fetchone()[0]
    context.add(ledger, 'P1', kind='task_done', label='verified', text='Fixture verified', source={'type':'event','id':event})
    artifact = verdict.artifact(ledger, 'P1')['artifact_sha']
    plan.accept(ledger, 'P1', 'owner', 'temporary fixture acceptance', artifact)
    assert len(outcome.outcomes(ledger, 'P1')) == 1
    assert outcome.missing(ledger) == []
    assert metrics.measure(ledger, 'P1')['status'] == 'accepted'
    assert estimates.read(ledger, 'P1')['baseline']['execution_seconds'] == [60,120]
    assert 'P1' in report.render_present(ledger.state_root, 'P1')
    assert resume_pack.build(ledger, 'P1')['status'] == 'accepted'
''')

    def test_non_git_data_artifact_uses_same_lifecycle_and_present(self):
        contract = plan_json()
        contract['understanding']['target']['paths'] = ['output.csv']
        contract['understanding']['target']['ref'] = 'snapshot'
        contract['preconditions'][0]['args']['path'] = 'output.csv'
        contract['scope']['owned'] = ['output.csv']
        contract['milestones'][0]['verifier'] = {'type':'data','config':{'path':'output.csv','columns':{'id':'integer'},'key':['id'],'row_count':1}}
        self.check_body('''
import json, tempfile
from pathlib import Path
from onecrew.ledger import Ledger
from onecrew.v2 import plan, verdict, report, outcome
with tempfile.TemporaryDirectory() as temp:
    root=Path(temp)/'project'; root.mkdir(); (root/'output.csv').write_text('id\\n1\\n')
    ledger=Ledger(root,Path(temp)/'state')
    contract=json.loads(''' + repr(json.dumps(contract)) + ''')
    plan.propose(ledger,'Data',contract,'codex')
    plan.approve(ledger,'Data','owner','temporary fixture')
    verified=verdict.run(ledger,'Data','M1')
    assert verified['milestones'][0]['state']=='passed'
    assert 'bộ kiểm data' in report.render_present(ledger.state_root,'Data')
    sha=verdict.artifact(ledger,'Data')['artifact_sha']
    plan.accept(ledger,'Data','owner','temporary fixture acceptance',sha)
    assert len(outcome.outcomes(ledger,'Data'))==1
''')

    def test_installed_progress_and_owner_stop_keep_evidence_and_end_the_root(self):
        contract = plan_json()
        contract['milestones'][0]['max_repairs'] = 0
        self.check_body('''
import json, sys, subprocess, tempfile
from pathlib import Path
from onecrew.ledger import Ledger
from onecrew.snapshots import Snapshots
from onecrew.v2 import plan, verdict, namespaces, questions, progress_track, executors, outcome, resume_pack, report
with tempfile.TemporaryDirectory() as temp:
    root=Path(temp)/'project'; root.mkdir(); (root/'a.txt').write_text('base\\n')
    def git(*args): subprocess.run(['git','-C',str(root),*args],check=True,capture_output=True)
    git('init','-q'); git('add','.'); git('-c','user.name=fixture','-c','user.email=fixture@localhost','commit','-qm','base')
    ledger=Ledger(root,Path(temp)/'state')
    contract=json.loads(''' + repr(json.dumps(contract)) + ''')
    contract['milestones'][0]['verifier']['config']['argv']=[sys.executable,'-c','raise SystemExit(1)']
    plan.propose(ledger,'P1',contract,'codex',workflow=True,capabilities=list(namespaces.CAPABILITIES))
    plan.approve(ledger,'P1','owner','temporary fixture')
    receipt=Snapshots(ledger.state_root).blob(b'actual local observation')
    result=progress_track.observe(ledger,'P1','M1',executors.HookAdapter(),'A1','K1',{'kind':'unknown'},source='receipt',ref=receipt)
    assert result['checkpoint']['status']=='unknown' and result['grants_execution'] is False
    stopped=verdict.run(ledger,'P1','M1')
    assert stopped['status']=='stopped_with_report'
    req=questions.list_for_plan(ledger,'P1',pending=True)[0]
    questions.answer(ledger,req['id'],req['revision'],'stop','Stop after checked failure.')
    assert plan.show(ledger,'P1')['status']=='closed'
    assert outcome.ending(ledger,'P1')['phase']=='cancelled'
    assert resume_pack.build(ledger,'P1')['remaining']['who'] is None
    assert 'ĐÃ ĐÓNG' in report.render_present(ledger.state_root,'P1')
''')

    def test_installed_verified_repair_creates_project_lesson_before_root_completion(self):
        contract = plan_json()
        contract['scope']['owned'] = ['a.txt']
        contract['milestones'][0]['verifier'] = {'type':'reviewer','config':{
            'provider':'claude','model':'fixture-model','max_minutes':1,
            'criteria':[{'id':'R1','question':'Does a.txt preserve both rows? fail if a row is lost.'}]}}
        self.check_body('''
import json, tempfile, subprocess, io, contextlib
from pathlib import Path
from onecrew.ledger import Ledger
from onecrew.v2 import plan, verdict, incidents, lessons, findings, context
from onecrew.v2.cli import main
with tempfile.TemporaryDirectory() as temp:
    root=Path(temp)/'project'; root.mkdir(); (root/'a.txt').write_text('2\\n')
    (root/'.gitignore').write_text('.onecrew/\\n')
    def git(*args): return subprocess.run(['git','-C',str(root),*args],check=True,capture_output=True,text=True).stdout.strip()
    git('init','-q'); git('config','user.name','fixture'); git('config','user.email','fixture@localhost')
    git('add','.'); git('commit','-qm','bug')
    ledger=Ledger(root,Path(temp)/'state')
    contract=json.loads(''' + repr(json.dumps(contract)) + ''')
    plan.propose(ledger,'P1',contract,'codex',workflow=True)
    plan.approve(ledger,'P1','owner','temporary fixture only')
    (root/'a.txt').write_text('2\\n# changed broken output\\n'); git('add','.'); git('commit','-qm','failing candidate')
    def fake_provider(prompt,config,env,scratch,limit):
        result='pass' if (root/'a.txt').read_text()=='1\\n2\\n' else 'fail'
        return json.dumps({'criteria':[{'id':'R1','verdict':result,'evidence':[{'file':'a.txt','line':1,'note':'Fixture compares all rows'}]}],'outside_criteria':[]}),{},None,False,b''
    from onecrew.v2.verifiers import reviewer
    original_call=reviewer.call
    reviewer.call=fake_provider
    try:
        failed=verdict.run(ledger,'P1','M1')
        assert failed['milestones'][0]['state']=='failed', failed['milestones'][0]
        assert not incidents.list_incidents(ledger,'P1')
        (root/'a.txt').write_text('1\\n2\\n'); git('add','.'); git('commit','-qm','repair')
        passed=verdict.run(ledger,'P1','M1')
        assert passed['milestones'][0]['state']=='passed', passed['milestones'][0]
    finally:
        reviewer.call=original_call
    assert len(incidents.list_incidents(ledger,'P1'))==1, incidents.observations(ledger,'P1')
    entries=lessons.retrieve(ledger,name='P1')['entries']
    assert entries and entries[0]['scope']=='project'
    assert plan.show(ledger,'P1')['status']=='approved'
    assert findings.list_findings(ledger,'P1')[0]['status']=='open'
    task=plan.show(ledger,'P1')['anchor_task']
    before=ledger.events(task)
    out=io.StringIO()
    with contextlib.redirect_stdout(out):
        code=main(['--project',str(root),'--state-root',str(ledger.state_root),'lesson','list','--name','P1'])
    assert code==0 and json.loads(out.getvalue())['entries']
    assert ledger.events(task)==before
''')
