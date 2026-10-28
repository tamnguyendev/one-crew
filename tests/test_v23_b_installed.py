"""2.3-B M4 on the INSTALLED wheel: an `engine step` controller (NativeExecutor, no managed journal) really dies while its contained
worker runs; the installed `onecrew executor recover` reconciles the contained process tree (never a candidate, never a replay), and the
next installed `engine step` holds the node with cleanup confirmed, replays it once inside the same root budget, and produces.

Everything runs from a fresh venv with the wheel built from this tree (`python -I`, cwd outside the checkout); module origins are
checked with onecrew.v2.boundary like tests/test_wf_installed_node_learning.py. The worker is a local process; no provider is called."""
import json
import shutil
import unittest

from onecrew.v2 import boundary
from tests import wf_wheel as wh
from tests.test_v2_l1 import plan_json
from tests.test_wf_engine import node
from tests.wf_env import owner_terminal

WORKER = r'''
import json, os, pathlib, subprocess, sys, time
ops, started, seconds, answer = sys.argv[1:5]
grandchild = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(300)'])
with open(ops, 'a', encoding='utf-8') as out: out.write('launched\n')
pathlib.Path(started).write_text(json.dumps({'worker': os.getpid(), 'grandchild': grandchild.pid}))
time.sleep(float(seconds))
pathlib.Path('answer.json').write_text(answer)
'''

COMMON = r'''
import json, os, sys, threading, time
from pathlib import Path
from onecrew.ledger import Ledger
from onecrew.process_core import Supervisor, native_python
from onecrew.subscription import environment
from onecrew.common_executor import NativeExecutor
def factory_for(ledger, ops, started, seconds):
    def factory(control, provider):
        class Worker:
            def capability(self): return {'provider': provider, 'mode': 'installed-v23b-local-fixture'}
            def run(self, attempt, prompt, schema, profile):
                directory = ledger.state_root / 'worker-io' / attempt['id']; directory.mkdir(parents=True)
                value = {'summary': 'fixture', 'files': [{'path': 'a.txt', 'content': 'candidate ' + attempt['id'] + '\n'}], 'backlog': []}
                return Supervisor(control).run(attempt, [native_python(), '-c', WORKER, ops, str(Path(started) / (attempt['id'] + '.json')),
                                                         str(seconds), json.dumps(value)], cwd=directory, timeout=60, env=environment())
            def result(self, attempt):
                return json.loads((ledger.state_root / 'worker-io' / attempt['id'] / 'answer.json').read_text()), []
        return Worker()
    return factory
'''

CHILD = COMMON + r'''
from onecrew.v2 import engine_cli
root, state, ops, started = sys.argv[1:5]
ledger = Ledger(Path(root), Path(state))
before = set(os.listdir(started))
def watch():
    while True:
        if set(os.listdir(started)) - before: os._exit(41)       # the installed engine-step controller dies while its worker runs
        time.sleep(.02)
threading.Thread(target=watch, daemon=True).start()
engine_cli.main(['--project', root, '--state-root', state, 'engine', 'step', 'P1'],
                native_executor=lambda ledger: NativeExecutor(ledger, worker_factory=factory_for(ledger, ops, started, 30)))
'''

BODY = COMMON + r'''
import subprocess, tempfile
from onecrew.v2 import plan, engine, internal_plan
from onecrew.control_core import Control
from onecrew.budget_core import group
with tempfile.TemporaryDirectory() as temp:
    root = Path(temp) / 'project with space'; root.mkdir()
    def git(*args): return subprocess.run(['git', '-C', str(root), *args], check=True, capture_output=True, text=True).stdout.strip()
    git('init', '-q'); git('config', 'user.name', 'fixture'); git('config', 'user.email', 'fixture@localhost')
    (root / 'a.txt').write_text('base\n'); (root / '.gitignore').write_text('.onecrew/\n')
    git('add', '.'); git('commit', '-qm', 'base')
    state = Path(temp) / 'state'
    ledger = Ledger(root, state)
    caps = ['namespaced-storage', 'root-budget', 'internal-plan', 'sequential-engine']
    plan.propose(ledger, 'P1', json.loads(CONTRACT), 'codex', workflow=True, capabilities=caps)
    plan.approve(ledger, 'P1', 'owner', 'temporary fixture only')
    internal_plan.revise(ledger, 'P1', json.loads(DEFINITION), reason='Scoped installed crash fixture', evidence=['a.txt:1'])
    ops = Path(temp) / 'operations.txt'; started = Path(temp) / 'started'; started.mkdir()
    child = subprocess.run([sys.executable, '-I', '-c', 'WORKER=' + repr(WORKER) + chr(10) + CHILDSRC, str(root), str(state), str(ops), str(started)],
                           capture_output=True, text=True, timeout=180)
    assert child.returncode == 41, (child.returncode, child.stderr[-1500:])
    view = engine.state(ledger, 'P1'); a1 = view['nodes']['C']['attempt']
    assert view['nodes']['C']['phase'] == 'running' and Control(ledger).attempt(a1)['status'] == 'running', view['nodes']['C']
    exe = Path(sys.executable).with_name('onecrew.exe')
    env = {k: v for k, v in os.environ.items() if k not in ('PYTHONPATH', 'PYTHONHOME')}
    done = subprocess.run([str(exe), '--project', str(root), '--state-root', str(state), 'executor', 'recover', a1],
                          capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=120, env=env)
    assert done.returncode == 0, ('installed executor recover', done.returncode, done.stdout[-1500:], done.stderr[-800:])
    recovered = json.loads(done.stdout)
    assert recovered['cleanup'] == 'confirmed' and recovered['candidate'] is None and recovered['state'] == 'unknown', recovered
    settled = Control(ledger).attempt(a1)
    assert settled['status'] == 'settled' and json.loads(settled['result'])['reason'] == 'supervisor_interrupted', settled
    assert len(ops.read_text().splitlines()) == 1
    executor = NativeExecutor(ledger, worker_factory=factory_for(ledger, str(ops), str(started), 0.2))
    taken = engine.step(ledger, 'P1', executor)
    assert taken['state'] == 'produced', taken
    view = engine.state(ledger, 'P1')
    assert view['nodes']['C']['generation'] == 1 and view['nodes']['C']['state'] == 'produced', view['nodes']['C']
    assert len(ops.read_text().splitlines()) == 2
    with ledger.transaction() as conn:
        held = [json.loads(r['payload']) for r in conn.execute("SELECT payload FROM events WHERE kind='node.held'")]
        resumed = [json.loads(r['payload']) for r in conn.execute("SELECT payload FROM events WHERE kind='node.resumed'")]
        used = group(conn, view['root'])['used_calls']
    assert [(h['attempt'], h['cleanup'], h['classification']) for h in held] == [(a1, 'confirmed', 'executor_interrupted')], held
    assert [(r['continues_attempt'], r['budget_reset']) for r in resumed] == [(a1, False)], resumed
    assert used == 2, used
    print('INSTALLED-V23B-OK')
'''


class InstalledEngineStepCrashRecovery(unittest.TestCase):
    def setUp(self):
        owner_terminal(self)        # the scenario approves the plan as the owner, in the owner's own terminal

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

    def test_installed_engine_step_crash_is_reconciled_by_executor_recover_then_replayed_once(self):
        definition = [node('C'), node('I', ['C'], integration=True, write=())]
        for item in definition: item['executor'] = {'role': 'worker', 'provider': 'codex', 'model': 'fixture-model'}
        contract = plan_json(authority={'edit': True, 'commands': True, 'self_decide': ['Q1', 'Q2', 'Q3', 'Q4', 'Q5', 'Q9', 'Q12']})
        body = ('WORKER = ' + repr(WORKER) + '\nCHILDSRC = ' + repr(CHILD) + '\nCONTRACT = ' + repr(json.dumps(contract))
                + '\nDEFINITION = ' + repr(json.dumps(definition)) + '\n' + BODY)
        dump, tail = wh.run_case(self.python, body, cwd=self.runs)
        self.assertIsNotNone(dump, tail)                 # the body raises (no dump) on any failed assertion of the installed scenario
        self.assertEqual(boundary.violations(dump['end'], self.ctx), [], tail)
