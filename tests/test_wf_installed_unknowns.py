"""Installed unknown CLI uses only the common wheel; no managed-worker claim."""
import json
from tests.test_wf_engine import node
from tests.test_v2_l1 import plan_json
from tests.test_wf_installed_features import InstalledFeaturesTests


class InstalledUnknownTests(InstalledFeaturesTests):
    # Parent fixture lifecycle only; avoid inheriting and rerunning unrelated cases.
    test_workflow_approval_evidence_report_outcome_context_and_metrics = None
    test_non_git_data_artifact_uses_same_lifecycle_and_present = None
    test_installed_progress_and_owner_stop_keep_evidence_and_end_the_root = None
    test_installed_verified_repair_creates_project_lesson_before_root_completion = None

    def test_unknown_cli_and_root_delivery_guard_from_wheel(self):
        contract=plan_json(authority={'edit':True,'commands':True,'self_decide':['Q1','Q2','Q9','Q12']})
        nodes=[node('A'),node('I',['A'],integration=True,write=())]
        self.check_body('''
import json, tempfile, subprocess, io, contextlib, sys
from pathlib import Path
from onecrew.ledger import Ledger, LedgerError
from onecrew.v2 import plan, internal_plan, namespaces, engine, verdict, report
from onecrew.v2.cli import main
with tempfile.TemporaryDirectory() as temp:
    root=Path(temp)/'project'; root.mkdir(); (root/'a.txt').write_text('base\\n')
    def git(*args): subprocess.run(['git','-C',str(root),*args],check=True,capture_output=True)
    git('init','-q'); git('add','.'); git('-c','user.name=fixture','-c','user.email=fixture@localhost','commit','-qm','base')
    ledger=Ledger(root,Path(temp)/'state')
    raw=json.loads('''+repr(json.dumps(contract))+''')
    raw['milestones'][0]['verifier']['config']['argv']=[sys.executable,'-c','print("ok")']
    plan.propose(ledger,'P1',raw,'codex',workflow=True,capabilities=list(namespaces.CAPABILITIES))
    plan.approve(ledger,'P1','owner','temporary fixture')
    internal_plan.revise(ledger,'P1',json.loads('''+repr(json.dumps(nodes))+'''),reason='bounded fixture nodes',evidence=['a.txt:1'])
    def cli(*args):
        output=io.StringIO()
        with contextlib.redirect_stdout(output):
            code=main(['--project',str(root),'--state-root',str(ledger.state_root),*args])
        assert code==0,output.getvalue()
        return json.loads(output.getvalue())
    declaration=Path(temp)/'unknown.json'
    declaration.write_text(json.dumps({'question':'Which format is supported?','affected':['A'],'required_by':['A'],'resolver':'doc','evidence':['a.txt:1']}))
    cli('unknown','open','U1','--plan','P1','--file',str(declaration))
    assert engine.ready(ledger,'P1')==[]
    task=plan.show(ledger,'P1')['anchor_task']; before=ledger.events(task)
    assert cli('unknown','list','--plan','P1')['blocked_nodes']=={'A':['U1']}
    assert 'U1' in report.render_present(ledger.state_root,'P1')
    assert ledger.events(task)==before
    cli('unknown','resolve','U1','--plan','P1','--by','doc','--answer','plain text confirmed','--evidence','a.txt:1')
    assert engine.ready(ledger,'P1')[0]['id']=='A'
    verdict.run(ledger,'P1','M1')
    try:
        plan.accept(ledger,'P1','owner','cannot bypass delivery',verdict.artifact(ledger,'P1')['artifact_sha'])
    except LedgerError as error: assert 'handoff' in str(error)
    else: raise AssertionError('Acceptance bypassed internal delivery')
''')
