"""scenario_a2.py A|B <work dir> <project dir> <state dir> - the A2 mandatory case, run by verify_milestone.py (V8) with the INSTALLED
onecrew (python -I): process A and process B are two separate interpreters; only the project and state paths are shared.

A: root P1 (fixture owner approval in this temporary ledger) runs node C through NativeExecutor -> ClaudeArtifact -> Supervisor -> the
   `claude` on PATH (the fake test double); the worker claims "the required word is VALUE: right" citing spec.txt with check M1; the
   real check passes, so the engine publishes it for the project while P1 is open; integration, handoff, verdict, owner acceptance end P1.
B: a NEW root P2 runs node D (writes b.txt, reads spec.txt) whose fake worker's own default is wrong; root P3's node cannot read
   spec.txt. Then a write on the ended root P1 is attempted. Writes <work>/result.json."""
import contextlib
import io
import json
import os
import subprocess
import sys
from pathlib import Path

from onecrew.budget_core import group as budget_group
from onecrew.common_executor import NativeExecutor
from onecrew.common_verification import CandidateChecker
from onecrew.ledger import Ledger, LedgerError
from onecrew.snapshots import Snapshots
from onecrew.v2 import engine, internal_plan, knowledge, plan
from onecrew.v2.cli import main as cli_main

side, work, root, state = sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3]), Path(sys.argv[4])
caps = ['namespaced-storage', 'root-budget', 'internal-plan', 'sequential-engine']


def git(*args):
    return subprocess.run(['git', '-C', str(root), *args], check=True, capture_output=True, text=True).stdout.strip()


def cli(*args):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = cli_main(['--project', str(root), '--state-root', str(state), *args])
    assert code == 0, out.getvalue()
    return json.loads(out.getvalue())


def policy(**value):
    path = work / ('policy-%d.json' % len(list(work.glob('policy-*.json'))))
    path.write_text(json.dumps(value)); os.environ['ONECREW_FAKE_POLICY'] = str(path)


def contract(target, word):
    check = [sys.executable, '-c', f'from pathlib import Path; v = Path("{target}").read_text().strip(); assert v == "{word}", v; print("ok")']
    return {'schema_version': 2, 'title': 'Required word', 'size': 'S',
            'understanding': {'restated_goal': 'The file holds the word the project requires.', 'target': {'repo': '.', 'ref': 'HEAD', 'paths': [target]},
                              'assumptions': [], 'confidence': 'high', 'unknowns': []},
            'preconditions': [{'id': 'P1', 'check': 'path_exists', 'args': {'path': 'spec.txt'}, 'why': 'the spec is there'}],
            'output': ['The file holds the required word'], 'scope': {'owned': [target]}, 'non_goals': ['Nothing else'],
            'items': [{'id': 'I1', 'title': 'Write the file', 'tier': 'must', 'milestone': 'M1'}],
            'milestones': [{'id': 'M1', 'title': 'Word check', 'verifier': {'type': 'command', 'config': {'argv': check}}, 'covers': ['O1']}],
            'budget': {'max_calls': 100, 'time': 120}, 'attention': {'questions': 1}, 'profile_version': None,
            'authority': {'edit': True, 'commands': True, 'unconfined_commands': True, 'apply_to_project': True,
                          'self_decide': ['Q1', 'Q2', 'Q3', 'Q4', 'Q5', 'Q9', 'Q12']}}


def nodes(nid, target, read):
    pin = {'role': 'worker', 'provider': 'claude', 'model': 'claude-haiku-5-5'}
    base = {'goal': 'Write the file with the word the project requires.', 'input': [], 'output': ['The file holds the required word'],
            'acceptance': ['O1'], 'resources': [], 'estimate_seconds': [1, 60], 'execution_cap_seconds': 60, 'budget_calls': 1}
    item = dict(base, id=nid, depends=[], read=read, write=[target], checks=[{'id': 'M1', 'spec': 'The file holds the required word of the project.'}],
                integration=False, executor=dict(pin))
    integ = dict(base, id='I', depends=[{'node': nid, 'requires': 'verified'}], read=[target], write=[],
                 checks=[{'id': 'M1', 'spec': 'Integration keeps the file.'}], integration=True, executor=dict(pin))
    return [item, integ]


def group(task):
    with ledger.transaction() as conn:
        value = budget_group(conn, task)
    return {k: value.get(k) for k in ('used_calls', 'reserved_calls', 'remaining_calls', 'deadline')} if value else None


os.environ['ONECREW_FAKE_LOG'] = str(work / 'fake.jsonl')
if side == 'A':
    root.mkdir()
    git('init', '-q'); git('config', 'user.name', 'fixture'); git('config', 'user.email', 'fixture@localhost')
    (root / 'a.txt').write_text('base\n'); (root / 'b.txt').write_text('base\n'); (root / 'spec.txt').write_text('The project uses one required word.\n')
    (root / '.gitignore').write_text('.onecrew/\n'); git('add', '.'); git('commit', '-qm', 'base')
    ledger = Ledger(root, state)
    plan.propose(ledger, 'P1', contract('a.txt', 'right'), 'codex', workflow=True, capabilities=caps)
    plan.approve(ledger, 'P1', 'owner', 'fixture owner approves root A in a temporary verification ledger')
    os.environ['ONECREW_ACTOR'] = 'codex'
    internal_plan.revise(ledger, 'P1', nodes('C', 'a.txt', ['a.txt', 'spec.txt']), reason='Root A', evidence=['a.txt:1'])
    policy(target='a.txt', default='right', careful=True,
           claims=[{'kind': 'finding', 'text': 'Files of this project hold the required word VALUE: right (spec.txt).', 'applies_to': ['a.txt'],
                    'sources': ['spec.txt'], 'check': 'M1'}])
    executor, checker = NativeExecutor(ledger), CandidateChecker(ledger, 'P1')
    steps = [engine.step(ledger, 'P1', executor)['state'], engine.verify(ledger, 'P1', 'C', checker)['result']]
    published = [{k: r[k] for k in ('id', 'label', 'visibility', 'evidence')} for r in knowledge.records(ledger) if r['visibility'] == 'project' and 'VALUE: right' in r['text']]
    while_open = plan.show(ledger, 'P1')['status']
    policy(target='a.txt', default='right', careful=True)
    steps += [engine.step(ledger, 'P1', executor)['state'], engine.verify(ledger, 'P1', 'I', checker)['result']]
    delivered = cli('engine', 'handoff', 'P1')
    cli('verdict', 'run', '--plan', 'P1', '--milestone', 'M1')
    os.environ.pop('ONECREW_ACTOR', None)
    status = plan.accept(ledger, 'P1', 'owner', 'fixture owner accepts root A in a temporary verification ledger', delivered['artifact'])['status']
    out = {'pid': os.getpid(), 'steps': steps, 'published': published, 'status_while_published': while_open, 'final_status': status,
           'budget': group(plan.show(ledger, 'P1')['anchor_task'])}
else:
    ledger = Ledger(root, state)
    plan.propose(ledger, 'P2', contract('b.txt', 'right'), 'codex', workflow=True, capabilities=caps)
    plan.approve(ledger, 'P2', 'owner', 'fixture owner approves root B, a new root')
    plan.propose(ledger, 'P3', contract('b.txt', 'right'), 'codex', workflow=True, capabilities=caps)
    plan.approve(ledger, 'P3', 'owner', 'fixture owner approves root P3 (cannot read spec.txt)')
    os.environ['ONECREW_ACTOR'] = 'codex'
    internal_plan.revise(ledger, 'P2', nodes('D', 'b.txt', ['a.txt', 'b.txt', 'spec.txt']), reason='Root B', evidence=['b.txt:1'])
    internal_plan.revise(ledger, 'P3', nodes('E', 'b.txt', ['b.txt']), reason='Root P3', evidence=['b.txt:1'])
    policy(target='b.txt', default='naive', careful=True)
    executor, store = NativeExecutor(ledger), Snapshots(ledger.state_root)

    def run(name, nid):
        produced = engine.step(ledger, name, executor)
        receipt = json.loads(store.read_blob(produced['receipt']))
        view = json.loads(store.read_blob(receipt['knowledge']['package'])) if receipt['knowledge'].get('package') else {'entries': []}
        return {'verdict': engine.verify(ledger, name, nid, CandidateChecker(ledger, name))['result'],
                'delivered': [[e['id'], e['use'], e['label']] for e in view['entries']], 'used': receipt['knowledge_use']['used'],
                'omitted': receipt['knowledge'].get('omitted_by_reason') or {}}
    b, narrow = run('P2', 'D'), run('P3', 'E')
    try:
        anchor = plan.show(ledger, 'P1')['anchor_task']
        with ledger.transaction() as conn: first = conn.execute('SELECT MIN(seq) FROM events WHERE task_id=?', (anchor,)).fetchone()[0]
        knowledge.record(ledger, 'P1', kind='note', text='late write on the ended root', evidence={'status': 'observed', 'sources': [{'type': 'event', 'id': first}]})
        late = 'written'
    except LedgerError as error:
        late = 'refused: ' + str(error)[:120]
    out = {'pid': os.getpid(), 'b': b, 'narrow': narrow, 'late_write_on_a': late, 'a_status': plan.show(ledger, 'P1')['status'],
           'a_budget': group(plan.show(ledger, 'P1')['anchor_task'])}
(work / 'result.json').write_text(json.dumps(out, ensure_ascii=False), encoding='utf-8')
print(json.dumps(out, ensure_ascii=False)[:800])
