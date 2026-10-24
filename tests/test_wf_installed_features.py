"""Cross-feature execution from an offline temporary wheel installation only."""
import json
import shutil
import unittest
from tests import wf_wheel as wh
from tests.test_v2_l1 import plan_json
from onecrew.v2 import boundary


class InstalledFeaturesTests(unittest.TestCase):
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
