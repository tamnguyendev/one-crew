"""Installed W26 API/closure; produced node is explicitly synthetic, no provider."""
import json
import shutil
import unittest

from tests import wf_wheel as wh
from tests.test_v2_l1 import plan_json
from tests.test_wf_engine import node
from onecrew.v2 import boundary


class InstalledReviewDispatchTests(unittest.TestCase):
    def test_installed_optional_skip_and_required_checker_keep_authority_separate(self):
        runs = wh._runs()
        self.addCleanup(shutil.rmtree, runs, ignore_errors=True)
        wheel, _, (modules, packages) = wh.build_wheel(runs)
        python = wh.make_venv(runs)
        wh.install(python, wheel)
        ctx = wh.build_ctx(python, modules, packages)
        contract = plan_json(review_policy={'depth': 'light', 'optional_reviews': ['extra']},
            authority={'edit': True, 'commands': True, 'edit_tests': True,
                       'self_decide': ['Q1', 'Q2', 'Q3', 'Q4', 'Q9', 'Q12']})
        body = '''
import json, os, subprocess, tempfile
from pathlib import Path
from onecrew.ledger import Ledger
from onecrew.snapshots import Snapshots
from onecrew.v2 import plan, engine, internal_plan, review_dispatch
for name in ('ONECREW_ACTOR','CLAUDECODE','CLAUDE_CODE_CHILD_SESSION'): os.environ.pop(name,None)
with tempfile.TemporaryDirectory() as temp:
    root=Path(temp)/'project'; root.mkdir(); (root/'a.txt').write_text('fixture\\n')
    def git(*args): subprocess.run(['git','-C',str(root),*args],check=True,capture_output=True)
    git('init','-q'); git('config','user.name','Fixture'); git('config','user.email','fixture@localhost')
    git('add','.'); git('commit','-qm','base')
    ledger=Ledger(root,Path(temp)/'state'); store=Snapshots(ledger.state_root)
    plan.propose(ledger,'P1',CONTRACT,'codex',workflow=True,
        capabilities=['namespaced-storage','root-budget','internal-plan','sequential-engine'])
    plan.approve(ledger,'P1','owner','authorized temporary fixture')
    os.environ['ONECREW_ACTOR']='codex'
    internal_plan.revise(ledger,'P1',NODES,reason='Fixture decomposition',evidence=['a.txt'])
    assert review_dispatch.required(ledger,'P1','C',['check-C'])['action']=='DEFER'
    assert engine.review_optional(ledger,'P1','C','extra',None,None)['status']=='deferred'
    # A test-only produced event isolates installed review from checkout-only Control.
    artifact=store.blob(b'explicit synthetic candidate')
    with ledger.transaction(write=True) as conn:
        current=engine.state(ledger,'P1',conn)
        engine._event(ledger,conn,current,'C','node.produced',artifact=artifact,
                      receipt=store.blob(b'explicit synthetic executor receipt'),inputs={})
    def forbidden(*args): raise AssertionError('optional checker must not execute')
    assert engine.review_optional(ledger,'P1','C','extra',forbidden,artifact)['status']=='skipped'
    assert engine.state(ledger,'P1')['nodes']['C']['state']=='produced'
    calls=[]
    def checker(item,artifact):
        calls.append(item['id'])
        return {'artifact':artifact,'checks':[{'id':'check-C','result':'pass','evidence':store.blob(b'fixture checked')}],
                'action':'SKIP'}
    result=engine.verify(ledger,'P1','C',checker)
    assert result['result']=='pass' and calls==['C'],result
    assert engine.state(ledger,'P1')['nodes']['C']['state']=='verified'
    assert ledger.requests()==[]
    with ledger.transaction() as conn:
        root=plan.anchor_events(ledger,conn,'P1')
    decisions=[e['payload'] for e in ledger.events(root['task_id']) if e['kind']=='decision.recorded'
               and e['payload']['subject']['component']=='review_policy']
    assert {p['validity']['action'] for p in decisions}=={'DEFER','SKIP','REVIEW'}
    assert all(p['subject']['model']=='rules' for p in decisions)
'''.replace('CONTRACT', repr(contract)).replace('NODES', repr([node('C'), node('I', ['C'], integration=True, write=())]))
        dump, tail = wh.run_case(python, body, cwd=runs)
        self.assertIsNotNone(dump, tail)
        self.assertEqual(boundary.violations(dump['end'], ctx), [], tail)
