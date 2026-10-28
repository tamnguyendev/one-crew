"""scenario_b.py <work dir> - the 2.3-B case, run by verify_milestone.py (V9) with the INSTALLED onecrew (python -I, cwd = work).

An `engine step` controller (the installed engine CLI, NativeExecutor, no managed journal) really dies (os._exit) while its contained
worker — a local process with a grandchild — runs; the installed `onecrew executor recover` reconciles the contained process tree
(cleanup confirmed, no candidate, no replay); the next `engine step` holds the node with cleanup confirmed, replays it ONCE inside the
same root budget (no reset) and produces. No provider is called; the plan is approved by the fixture owner in this temporary ledger.
Writes <work>/result.json with every observed fact (the verifier judges them)."""
import json
import os
import subprocess
import sys
from pathlib import Path

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

exec(COMMON)
from onecrew.budget_core import group
from onecrew.control_core import Control
from onecrew.v2 import engine, internal_plan, plan

work = Path(sys.argv[1])
root = work / 'project with space'; root.mkdir()


def git(*args):
    return subprocess.run(['git', '-C', str(root), *args], check=True, capture_output=True, text=True).stdout.strip()


git('init', '-q'); git('config', 'user.name', 'fixture'); git('config', 'user.email', 'fixture@localhost')
(root / 'a.txt').write_text('base\n'); (root / '.gitignore').write_text('.onecrew/\n')
git('add', '.'); git('commit', '-qm', 'base')
state = work / 'state with space'
ledger = Ledger(root, state)
check = [sys.executable, '-c', 'print("ok")']
contract = {'schema_version': 2, 'title': 'Crash and takeover', 'size': 'S',
            'understanding': {'restated_goal': 'Write a.txt; survive a lost controller.', 'target': {'repo': '.', 'ref': 'HEAD', 'paths': ['a.txt']},
                              'assumptions': [], 'confidence': 'high', 'unknowns': []},
            'preconditions': [{'id': 'P1', 'check': 'path_exists', 'args': {'path': 'a.txt'}, 'why': 'the file to work on is there'}],
            'output': ['a.txt written'], 'scope': {'owned': ['a.txt']}, 'non_goals': ['Nothing else'],
            'items': [{'id': 'I1', 'title': 'Write a.txt', 'tier': 'must', 'milestone': 'M1'}],
            'milestones': [{'id': 'M1', 'title': 'Check', 'verifier': {'type': 'command', 'config': {'argv': check}}, 'covers': ['O1']}],
            'budget': {'max_calls': 100, 'time': 120}, 'attention': {'questions': 1}, 'profile_version': None,
            'authority': {'edit': True, 'commands': True, 'self_decide': ['Q1', 'Q2', 'Q3', 'Q4', 'Q5', 'Q9', 'Q12']}}


def node(nid, depends=(), integration=False, write=('a.txt',)):
    return {'id': nid, 'goal': 'Produce evidence for O1', 'input': [], 'output': ['Evidence for O1'], 'acceptance': ['O1'],
            'depends': [{'node': d, 'requires': 'verified'} for d in depends], 'read': ['a.txt'], 'write': list(write), 'resources': [],
            'estimate_seconds': [1, 2], 'execution_cap_seconds': 60, 'budget_calls': 1,
            'checks': [{'id': 'check-' + nid, 'spec': 'Check the declared O1 output of ' + nid}], 'integration': integration,
            'executor': {'role': 'worker', 'provider': 'codex', 'model': 'fixture-model'}}


caps = ['namespaced-storage', 'root-budget', 'internal-plan', 'sequential-engine']
plan.propose(ledger, 'P1', contract, 'codex', workflow=True, capabilities=caps)
plan.approve(ledger, 'P1', 'owner', 'temporary verification fixture (not a real ledger)')
internal_plan.revise(ledger, 'P1', [node('C'), node('I', ['C'], integration=True, write=())], reason='Scoped installed crash fixture', evidence=['a.txt:1'])
ops = work / 'operations.txt'; started = work / 'started'; started.mkdir()
child = subprocess.run([sys.executable, '-I', '-c', 'WORKER=' + repr(WORKER) + chr(10) + CHILD, str(root), str(state), str(ops), str(started)],
                       capture_output=True, text=True, timeout=180)
out = {'child_exit': child.returncode}
view = engine.state(ledger, 'P1'); a1 = view['nodes']['C']['attempt']
out.update(phase_after_crash=view['nodes']['C']['phase'], attempt_after_crash=Control(ledger).attempt(a1)['status'])
exe = Path(sys.executable).with_name('onecrew.exe')
env = {k: v for k, v in os.environ.items() if k not in ('PYTHONPATH', 'PYTHONHOME')}
done = subprocess.run([str(exe), '--project', str(root), '--state-root', str(state), 'executor', 'recover', a1],
                      capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=120, env=env)
out['recover_exit'] = done.returncode
try:
    recovered = json.loads(done.stdout)
    out.update(recover_cleanup=recovered.get('cleanup'), recover_candidate=recovered.get('candidate'), recover_state=recovered.get('state'))
except ValueError:
    out['recover_output'] = (done.stdout + done.stderr)[-600:]
settled = Control(ledger).attempt(a1)
out.update(settled_status=settled['status'], settled_reason=json.loads(settled['result'] or '{}').get('reason'),
           launches_before_takeover=len(ops.read_text().splitlines()))
taken = engine.step(ledger, 'P1', NativeExecutor(ledger, worker_factory=factory_for(ledger, str(ops), str(started), 0.2)))
view = engine.state(ledger, 'P1')
with ledger.transaction() as conn:
    held = [json.loads(r['payload']) for r in conn.execute("SELECT payload FROM events WHERE kind='node.held'")]
    resumed = [json.loads(r['payload']) for r in conn.execute("SELECT payload FROM events WHERE kind='node.resumed'")]
    used = group(conn, view['root'])['used_calls']
out.update(takeover_state=taken['state'], generation=view['nodes']['C']['generation'], node_state=view['nodes']['C']['state'],
           launches_total=len(ops.read_text().splitlines()), first_attempt=a1,
           held=[[h.get('attempt'), h.get('cleanup'), h.get('classification')] for h in held],
           resumed=[[r.get('continues_attempt'), r.get('budget_reset')] for r in resumed], used_calls=used)
(work / 'result.json').write_text(json.dumps(out, ensure_ascii=False), encoding='utf-8')
print(json.dumps(out, ensure_ascii=False)[:800])
