"""Installed NativeExecutor and actual command checks produce mid-root learning."""
import json
import shutil
import unittest

from onecrew.v2 import boundary
from tests import wf_wheel as wh
from tests.test_v2_l1 import plan_json, milestone
from tests.test_wf_engine import node
from tests.wf_env import owner_terminal


class InstalledNodeLearning(unittest.TestCase):
    def setUp(self):
        owner_terminal(self)        # the installed scenario approves the plan as the owner, in the owner's own terminal

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

    def test_native_fail_repair_pass_emits_one_episode_and_lesson_on_actual_candidate(self):
        definition = [node('C'), node('I', ['C'], integration=True, write=())]
        for item in definition:
            item['checks'] = [{'id': 'M1', 'spec': 'Preserve both rows under the approved real command.'}]
            item['executor'] = {'role': 'worker', 'provider': 'codex', 'model': 'fixture-model'}
        contract = plan_json(authority={'edit': True, 'commands': True, 'unconfined_commands': True,
                            'self_decide': ['Q1', 'Q2', 'Q3', 'Q4', 'Q5', 'Q9', 'Q12']})
        body = '''
import json, os, subprocess, sys, tempfile
from pathlib import Path
from onecrew.ledger import Ledger
from onecrew.snapshots import Snapshots
from onecrew.common_executor import NativeExecutor
from onecrew.common_verification import CandidateChecker
from onecrew.v2 import plan, engine, internal_plan, incidents, lessons, context, repair_tasks, findings
with tempfile.TemporaryDirectory() as temp:
    root=Path(temp)/'project'; root.mkdir()
    def git(*args): return subprocess.run(['git','-C',str(root),*args],check=True,capture_output=True,text=True).stdout.strip()
    git('init','-q'); git('config','user.name','fixture'); git('config','user.email','fixture@localhost')
    (root/'a.txt').write_text('base\\n'); (root/'.gitignore').write_text('.onecrew/\\n')
    git('add','.'); git('commit','-qm','base')
    ledger=Ledger(root,Path(temp)/'state')
    contract=json.loads(CONTRACT)
    contract['milestones'][0]['verifier']['config']['argv']=[sys.executable,'-c','from pathlib import Path; assert Path("a.txt").read_text().splitlines()==["1","2"]; print("row preservation verified")']
    caps=['namespaced-storage','root-budget','internal-plan','sequential-engine']
    plan.propose(ledger,'P1',contract,'codex',workflow=True,capabilities=caps)
    plan.approve(ledger,'P1','owner','temporary fixture only')
    internal_plan.revise(ledger,'P1',json.loads(DEFINITION),reason='Scoped real-command fixture',evidence=['a.txt:1'])
    output=['2\\n']; calls=[]
    def factory(control,provider):
        class Worker:
            def capability(self): return {'provider':provider,'mode':'explicit-no-provider-call-fixture'}
            def run(self,attempt,prompt,schema,profile):
                calls.append(attempt['id'])
                control.launched(attempt['id'],attempt['generation'],{'fixture':True})
                control.finish(attempt['id'],attempt['generation'],{'exit_code':0})
            def result(self,attempt):
                return {'summary':'fixture','files':[{'path':'a.txt','content':output[0]}],'backlog':[]},[]
        return Worker()
    executor=NativeExecutor(ledger,worker_factory=factory); checker=CandidateChecker(ledger,'P1')
    engine.step(ledger,'P1',executor)
    assert engine.verify(ledger,'P1','C',checker)['result']=='fail'
    receipt=engine.state(ledger,'P1')['nodes']['C']['verification_receipt']
    repair_tasks.prepare(ledger,'P1','C','C',reason='Repair actual row-preservation assertion',evidence=[receipt])
    output[0]='1\\n2\\n'; engine.step(ledger,'P1',executor)
    passed=engine.verify(ledger,'P1','C',checker)
    if passed['result']!='pass':
        wrapper=json.loads(Snapshots(ledger.state_root).read_blob(passed['observed']['checks'][0]['evidence']))
        proof=json.loads(Snapshots(ledger.state_root).read_blob(wrapper['command_receipt']))
        raise AssertionError({k:proof.get(k) for k in ('error','exit_code','timed_out','artifact_sha','artifact_sha_after')})
    saved=incidents.list_incidents(ledger,'P1'); assert len(saved)==1,saved
    assert saved[0]['finding'] is None and saved[0]['episode'].startswith('NEP-')
    assert [o['classification'] for o in saved[0]['attempts']]==['product','verified']
    assert len(calls)==2
    entries=context.retrieve(ledger,plan='P1',revision=passed['observed']['candidate_tree'])['entries']
    entry=next(e for e in entries if e.get('lesson')); assert entry['label']=='verified',entry
    lesson=lessons._latest(ledger,'P1')[entry['lesson']]
    assert lesson['location']['revision']==passed['observed']['candidate_tree']
    assert lesson['location']['path']=='a.txt' and lesson['location']['test']=='check:M1'
    assert not lesson['automatic_promotion'] and not lesson['automatic_injection']
    assert findings.list_findings(ledger,'P1')==[]
    assert plan.show(ledger,'P1')['status']=='approved' and not engine.verification_ready(ledger,'P1')
    assert (root/'a.txt').read_text()=='base\\n'
'''.replace('CONTRACT', repr(json.dumps(contract))).replace('DEFINITION', repr(json.dumps(definition)))
        dump, tail = wh.run_case(self.python, body, cwd=self.runs)
        self.assertIsNotNone(dump, tail)
        self.assertEqual(boundary.violations(dump['end'], self.ctx), [], tail)
