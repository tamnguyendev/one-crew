"""2.3-A2 KB-12 (the mandatory case) on the INSTALLED wheel: root A ends, then a NEW root B of the same project, in a NEW process, finds
and uses what A learned — without anything handed over by hand.

Process 1 (python -I, venv of the wheel): project with spec.txt; root A (plan P1) runs node C through the real NativeExecutor ->
ClaudeArtifact -> Supervisor -> fake claude process; the worker claims "the required word is VALUE: right" citing spec.txt with check M1;
the node's real command check passes, so the engine publishes the claim for the project (verified, citing the verification receipt,
cause not established) while A is open; then integration, handoff, the milestone verdict and the (fixture) owner's acceptance end A.
Process 2 (a new interpreter; only the project and state paths are passed): root B (plan P2, its own approval and budget) runs node D
that writes b.txt; the fake worker's own default is wrong, so it passes only if A's knowledge reached its prompt. Counter-checks in the
same process: root P3 whose node cannot read spec.txt does not receive it (and fails); nothing can be written on the ended root A;
A's budget and status are unchanged; the knowledge B used is A's published entry (same id), not a copy."""
import json
import unittest
from pathlib import Path

from onecrew.v2 import boundary
from tests import v23_harness as hx
from tests import wf_wheel as wh
from tests.test_v2_l1 import plan_json
from tests.test_wf_engine import node
from tests.wf_env import owner_terminal

COMMON = r'''
import contextlib, io, json, os, subprocess, sys
from pathlib import Path
from onecrew.ledger import Ledger, LedgerError
from onecrew.snapshots import Snapshots
from onecrew.common_executor import NativeExecutor
from onecrew.common_verification import CandidateChecker
from onecrew.v2 import plan, engine, internal_plan, knowledge
from onecrew.v2.cli import main as cli_main
work = Path(WORK); root = Path(PROJECT); state = Path(STATE)
def git(*args): return subprocess.run(['git','-C',str(root),*args],check=True,capture_output=True,text=True).stdout.strip()
def cli(*args):
    out = io.StringIO()
    with contextlib.redirect_stdout(out): code = cli_main(['--project', str(root), '--state-root', str(state), *args])
    assert code == 0, out.getvalue(); return json.loads(out.getvalue())
def policy(**value):
    path = work / ('policy-%d.json' % len(list(work.glob('policy-*.json')))); path.write_text(json.dumps(value)); os.environ['ONECREW_FAKE_POLICY'] = str(path)
def contract(target, word):
    value = json.loads(CONTRACT)
    value['milestones'][0]['verifier']['config']['argv'] = [sys.executable, '-c', f'from pathlib import Path; v = Path("{target}").read_text().strip(); assert v == "{word}", v; print("ok")']
    value['understanding']['target']['paths'] = [target]; value['scope']['owned'] = [target]
    value['preconditions'][0]['args']['path'] = 'spec.txt'
    return value
def nodes(nid, target, read):
    item = json.loads(NODE); item.update(id=nid, write=[target], read=read)
    integ = json.loads(INTEG); integ['depends'] = [{'node': nid, 'requires': 'verified'}]; integ['read'] = [target]
    return [item, integ]
def group(task):
    from onecrew.budget_core import group as budget_group
    with ledger.transaction() as conn:
        value = budget_group(conn, task)
    return {k: value.get(k) for k in ('used_calls', 'reserved_calls', 'remaining_calls', 'deadline')} if value else None
caps = ['namespaced-storage','root-budget','internal-plan','sequential-engine']
'''

PROCESS_A = COMMON + r'''
root.mkdir()
git('init','-q'); git('config','user.name','fixture'); git('config','user.email','fixture@localhost')
(root/'a.txt').write_text('base\n'); (root/'b.txt').write_text('base\n'); (root/'spec.txt').write_text('The project uses one required word.\n')
(root/'.gitignore').write_text('.onecrew/\n'); git('add','.'); git('commit','-qm','base')
ledger = Ledger(root, state)
plan.propose(ledger, 'P1', contract('a.txt', 'right'), 'codex', workflow=True, capabilities=caps)
plan.approve(ledger, 'P1', 'owner', 'fixture owner approves root A in a temporary ledger')
os.environ['ONECREW_ACTOR'] = 'codex'
internal_plan.revise(ledger, 'P1', nodes('C', 'a.txt', ['a.txt', 'spec.txt']), reason='Root A', evidence=['a.txt:1'])
policy(target='a.txt', default='right', careful=True,
       claims=[{'kind': 'finding', 'text': 'Files of this project hold the required word VALUE: right (spec.txt).', 'applies_to': ['a.txt'],
                'sources': ['spec.txt'], 'check': 'M1'}])
executor = NativeExecutor(ledger); checker = CandidateChecker(ledger, 'P1')
r = engine.step(ledger, 'P1', executor); assert r['state'] == 'produced', ('step C', r)
v = engine.verify(ledger, 'P1', 'C', checker); assert v['result'] == 'pass', ('verify C', v.get('result'), str(v)[:300])
published = [r for r in knowledge.records(ledger) if r['visibility'] == 'project' and 'VALUE: right' in r['text']]
open_status = plan.show(ledger, 'P1')['status']
policy(target='a.txt', default='right', careful=True)
r = engine.step(ledger, 'P1', executor); assert r['state'] == 'produced', ('step I', r)
v = engine.verify(ledger, 'P1', 'I', checker); assert v['result'] == 'pass', ('verify I', v.get('result'), str(v)[:300])
delivered = cli('engine', 'handoff', 'P1')
cli('verdict', 'run', '--plan', 'P1', '--milestone', 'M1')
os.environ.pop('ONECREW_ACTOR', None)
accepted = plan.accept(ledger, 'P1', 'owner', 'fixture owner accepts root A in a temporary ledger', delivered['artifact'])['status']
task = plan.show(ledger, 'P1')['anchor_task']
out = {'pid': os.getpid(), 'published': [{k: r[k] for k in ('id', 'label', 'visibility', 'evidence', 'root')} for r in published],
       'status_when_published': open_status, 'final_status': accepted, 'budget': group(task), 'task': task}
Path(OUT).write_text(json.dumps(out, ensure_ascii=False), encoding='utf-8')
'''

PROCESS_B = COMMON + r'''
ledger = Ledger(root, state)
os.environ.pop('ONECREW_ACTOR', None)
plan.propose(ledger, 'P2', contract('b.txt', 'right'), 'codex', workflow=True, capabilities=caps)
plan.approve(ledger, 'P2', 'owner', 'fixture owner approves root B, a new root')
plan.propose(ledger, 'P3', contract('b.txt', 'right'), 'codex', workflow=True, capabilities=caps)
plan.approve(ledger, 'P3', 'owner', 'fixture owner approves root P3 (narrow read scope)')
os.environ['ONECREW_ACTOR'] = 'codex'
internal_plan.revise(ledger, 'P2', nodes('D', 'b.txt', ['a.txt', 'b.txt', 'spec.txt']), reason='Root B', evidence=['b.txt:1'])
internal_plan.revise(ledger, 'P3', nodes('E', 'b.txt', ['b.txt']), reason='Root P3, cannot read spec.txt', evidence=['b.txt:1'])
policy(target='b.txt', default='naive', careful=True)
log = Path(os.environ['ONECREW_FAKE_LOG'])
executor = NativeExecutor(ledger)
store = Snapshots(ledger.state_root)
def run(name, nid):
    produced = engine.step(ledger, name, executor)
    receipt = json.loads(store.read_blob(produced['receipt']))
    view = json.loads(store.read_blob(receipt['knowledge']['package'])) if receipt['knowledge'].get('package') else {'entries': [], 'omitted': {}}
    verdict = engine.verify(ledger, name, nid, CandidateChecker(ledger, name))['result']
    return {'verdict': verdict, 'delivered': [[e['id'], e['use'], e['label']] for e in view['entries']], 'used': receipt['knowledge_use']['used'],
            'omitted': receipt['knowledge'].get('omitted_by_reason') or {}, 'written': store.context(produced['artifact'])['b.txt']}
b = run('P2', 'D'); narrow = run('P3', 'E')
try:
    knowledge.record(ledger, 'P1', kind='note', text='late write on the ended root', evidence={'status': 'observed', 'sources': [{'type': 'event', 'id': 1}]})
    late = 'written'
except LedgerError as error:
    late = 'refused: ' + str(error)[:120]
task_a = plan.show(ledger, 'P1')['anchor_task']
out = {'pid': os.getpid(), 'b': b, 'narrow': narrow, 'late_write_on_A': late, 'a_status': plan.show(ledger, 'P1')['status'], 'a_budget': group(task_a),
       'fake_runs': len(log.read_text(encoding='utf-8').splitlines())}
Path(OUT).write_text(json.dumps(out, ensure_ascii=False), encoding='utf-8')
'''


class InstalledA2(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runs, cls.python, cls.wheel, cls.ctx = hx.runtime('a2')

    @classmethod
    def tearDownClass(cls):
        hx.cleanup(cls.runs)

    def setUp(self):
        owner_terminal(self)

    def body(self, template, work, project, state, out):
        item = node('C', write=('a.txt',))
        item['checks'] = [{'id': 'M1', 'spec': 'The file holds the required word of the project.'}]
        item['executor'] = {'role': 'worker', 'provider': 'claude', 'model': 'claude-haiku-5-5'}
        integration = node('I', ['C'], integration=True, write=())
        integration['checks'] = [{'id': 'M1', 'spec': 'Integration keeps the file.'}]
        integration['read'] = []
        integration['executor'] = dict(item['executor'])
        contract = plan_json(authority={'edit': True, 'commands': True, 'unconfined_commands': True, 'apply_to_project': True,
                                        'self_decide': ['Q1', 'Q2', 'Q3', 'Q4', 'Q5', 'Q9', 'Q12']})
        return (template.replace('WORK', repr(str(work))).replace('PROJECT', repr(str(project))).replace('STATE', repr(str(state)))
                .replace('OUT', repr(str(out))).replace('CONTRACT', repr(json.dumps(contract)))
                .replace('NODE', repr(json.dumps(item))).replace('INTEG', repr(json.dumps(integration))))

    def test_kb12_root_a_ends_then_a_new_root_in_a_new_process_uses_what_a_learned(self):
        base = self.runs / 'two roots'; base.mkdir()
        project, state = base / 'project', base / 'state'
        work_a, work_b = base / 'process A', base / 'process B'; work_a.mkdir(); work_b.mkdir()
        out_a, out_b = work_a / 'out.json', work_b / 'out.json'
        dump, tail = wh.run_case(self.python, self.body(PROCESS_A, work_a, project, state, out_a),
                                 env_extra=hx.scenario_env(self.python, work_a, log=work_a / 'fake.jsonl'), cwd=work_a)
        self.assertIsNotNone(dump, tail); self.assertEqual(boundary.violations(dump['end'], self.ctx), [], tail)
        a = json.loads(out_a.read_text(encoding='utf-8'))
        self.assertEqual(len(a['published']), 1, a)
        published = a['published'][0]
        self.assertEqual((published['label'], published['visibility']), ('verified', 'project'))
        self.assertEqual(published['evidence']['cause'], 'not_established')
        self.assertEqual(a['status_when_published'], 'approved')                     # written while A was open
        self.assertEqual(a['final_status'], 'accepted')
        dump, tail = wh.run_case(self.python, self.body(PROCESS_B, work_b, project, state, out_b),
                                 env_extra=hx.scenario_env(self.python, work_b, log=work_b / 'fake.jsonl'), cwd=work_b)
        self.assertIsNotNone(dump, tail); self.assertEqual(boundary.violations(dump['end'], self.ctx), [], tail)
        b = json.loads(out_b.read_text(encoding='utf-8'))
        self.assertNotEqual(a['pid'], b['pid'])                                       # a new process, nothing carried over in memory
        self.assertEqual(b['b']['verdict'], 'pass', b)
        self.assertIn([published['id'], 'fact', 'verified'], b['b']['delivered'])
        self.assertEqual(b['b']['used'], [published['id']])
        self.assertEqual(b['narrow']['verdict'], 'fail')                             # P3 cannot read spec.txt: not delivered, not named
        self.assertNotIn(published['id'], json.dumps(b['narrow']['delivered']))
        self.assertGreaterEqual(b['narrow']['omitted'].get('source_outside_read_scope', 0), 1)
        self.assertTrue(b['late_write_on_A'].startswith('refused'), b['late_write_on_A'])
        self.assertEqual(b['a_status'], 'accepted')
        self.assertEqual(b['a_budget'], a['budget'])                                  # A's budget untouched by B
        self.assertEqual(b['fake_runs'], 2)
