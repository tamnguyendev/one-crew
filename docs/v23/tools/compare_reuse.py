"""compare_reuse.py <out.json> [--repeat N] [--real-model MODEL --real-repeat N] - 2.3-A2 KE-02 (MEM-05 extended): knowledge that an
earlier root wrote itself, used again by a NEW root of the same project in a NEW process, from the INSTALLED wheel of this checkout.

Root A (process 1, fake claude, always the same): node C writes a.txt; its worker claims "the required word is VALUE: right" citing
spec.txt with check M1; the real check passes, so the engine publishes the claim for the project; A ends (fixture owner acceptance).
Root B (process 2, fresh interpreter): node D writes b.txt; its check wants the word the project requires NOW. Conditions for B:
  fresh     no root A at all (a new project)                     B's check wants "right"
  reused    A's knowledge live, spec.txt unchanged               B's check wants "right"
  changed   spec.txt changed after A ("the required word is now bright"): A's entry is delivered as a lead (recheck); B wants "bright"
  withdrawn A's entry withdrawn by a third root before B         B's check wants "right"; the entry must not reach B
Per B run: verdict of B's real check, seconds of B's step, prompt/knowledge characters, delivered uses, declared use, misled (failed while
relying on a delivered entry), rework needed (first candidate failed). The fake claude rows prove the plumbing; `--real-model` runs
the real Claude Code CLI already logged in on this machine for B only (subscription auth; bounded by --real-repeat)."""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
for name in ('CLAUDECODE', 'CLAUDE_CODE_CHILD_SESSION', 'ONECREW_ACTOR'):
    os.environ.pop(name, None)

from tests import v23_harness as hx      # noqa: E402
from tests import wf_wheel as wh         # noqa: E402
from tests.test_v2_l1 import plan_json   # noqa: E402
from tests.test_wf_engine import node    # noqa: E402

COMMON = r'''
import contextlib, io, json, os, subprocess, sys, time
from pathlib import Path
from onecrew.ledger import Ledger, LedgerError
from onecrew.snapshots import Snapshots
from onecrew.common_executor import NativeExecutor
from onecrew.common_verification import CandidateChecker
from onecrew.v2 import plan, engine, internal_plan, knowledge
from onecrew.v2.cli import main as cli_main
work = Path(WORK); root = Path(PROJECT); state = Path(STATE); condition = CONDITION
def git(*args): return subprocess.run(['git','-C',str(root),*args],check=True,capture_output=True,text=True).stdout.strip()
def cli(*args):
    out = io.StringIO()
    with contextlib.redirect_stdout(out): code = cli_main(['--project', str(root), '--state-root', str(state), *args])
    assert code == 0, out.getvalue(); return json.loads(out.getvalue())
def policy(**value):
    path = work / ('policy-%d.json' % len(list(work.glob('policy-*.json')))); path.write_text(json.dumps(value)); os.environ['ONECREW_FAKE_POLICY'] = str(path)
def contract(target, word):
    value = json.loads(CONTRACT)
    value['milestones'][0]['verifier']['config']['argv'] = [sys.executable, '-c', f'from pathlib import Path; v = Path("{target}").read_text().strip().lower(); assert v == "{word}", v; print("ok")']
    value['understanding']['target']['paths'] = [target]; value['scope']['owned'] = [target]; value['preconditions'][0]['args']['path'] = 'spec.txt'
    return value
def nodes(nid, target, read, model):
    item = json.loads(NODE); item.update(id=nid, write=[target], read=read); item['executor']['model'] = model
    integ = json.loads(INTEG); integ['depends'] = [{'node': nid, 'requires': 'verified'}]; integ['read'] = [target]; integ['executor']['model'] = model
    return [item, integ]
caps = ['namespaced-storage','root-budget','internal-plan','sequential-engine']
def init_project():
    root.mkdir()
    git('init','-q'); git('config','user.name','fixture'); git('config','user.email','fixture@localhost')
    (root/'a.txt').write_text('base\n'); (root/'b.txt').write_text('base\n'); (root/'spec.txt').write_text('The project uses one required word.\n')
    (root/'.gitignore').write_text('.onecrew/\n'); git('add','.'); git('commit','-qm','base')
'''

PROCESS_A = COMMON + r'''
init_project()
ledger = Ledger(root, state)
if condition != 'fresh':
    plan.propose(ledger, 'P1', contract('a.txt', 'right'), 'codex', workflow=True, capabilities=caps)
    plan.approve(ledger, 'P1', 'owner', 'fixture owner approves root A in a temporary ledger')
    os.environ['ONECREW_ACTOR'] = 'codex'
    internal_plan.revise(ledger, 'P1', nodes('C', 'a.txt', ['a.txt', 'spec.txt'], 'claude-haiku-5-5'), reason='Root A', evidence=['a.txt:1'])
    policy(target='a.txt', default='right', careful=True,
           claims=[{'kind': 'finding', 'text': 'Files of this project hold the required word VALUE: right (spec.txt).', 'applies_to': ['a.txt', 'b.txt'],
                    'sources': ['spec.txt'], 'check': 'M1'}])
    executor = NativeExecutor(ledger); checker = CandidateChecker(ledger, 'P1')
    assert engine.step(ledger, 'P1', executor)['state'] == 'produced'
    assert engine.verify(ledger, 'P1', 'C', checker)['result'] == 'pass'
    policy(target='a.txt', default='right', careful=True)
    assert engine.step(ledger, 'P1', executor)['state'] == 'produced'
    assert engine.verify(ledger, 'P1', 'I', checker)['result'] == 'pass'
    delivered = cli('engine', 'handoff', 'P1')
    cli('verdict', 'run', '--plan', 'P1', '--milestone', 'M1')
    os.environ.pop('ONECREW_ACTOR', None)
    plan.accept(ledger, 'P1', 'owner', 'fixture owner accepts root A', delivered['artifact'])
    published = [r['id'] for r in knowledge.records(ledger) if r['visibility'] == 'project' and 'VALUE: right' in r['text']]
    if condition == 'changed':
        (root/'spec.txt').write_text('The required word is now bright.\n'); git('commit','-qam','requirement changed')
    if condition == 'withdrawn':
        plan.propose(ledger, 'P9', contract('a.txt', 'right'), 'codex', workflow=True, capabilities=caps)
        plan.approve(ledger, 'P9', 'owner', 'fixture owner approves a reviewing root')
        anchor = plan.show(ledger, 'P9')['anchor_task']
        with ledger.transaction() as conn: first = conn.execute('SELECT MIN(seq) FROM events WHERE task_id=?', (anchor,)).fetchone()[0]
        knowledge.withdraw(ledger, 'P9', published[0], reason='the word was a guess; withdrawn for the comparison', evidence={'sources': [{'type': 'event', 'id': first}]})
else:
    published = []
Path(OUT).write_text(json.dumps({'published': published}), encoding='utf-8')
'''

PROCESS_B = COMMON + r'''
ledger = Ledger(root, state)
os.environ.pop('ONECREW_ACTOR', None)
word = 'bright' if condition == 'changed' else 'right'
plan.propose(ledger, 'P2', contract('b.txt', word), 'codex', workflow=True, capabilities=caps)
plan.approve(ledger, 'P2', 'owner', 'fixture owner approves root B, a new root')
os.environ['ONECREW_ACTOR'] = 'codex'
internal_plan.revise(ledger, 'P2', nodes('D', 'b.txt', ['b.txt', 'spec.txt'], MODEL), reason='Root B', evidence=['b.txt:1'])
policy(target='b.txt', default='naive', careful=True)
store = Snapshots(ledger.state_root)
started = time.perf_counter()
produced = engine.step(ledger, 'P2', NativeExecutor(ledger))
seconds = time.perf_counter() - started
out = {'condition': condition, 'state': produced['state'], 'seconds': round(seconds, 3), 'reason': str(produced.get('reason') or '')[:300]}
if produced['state'] == 'produced':
    receipt = json.loads(store.read_blob(produced['receipt']))
    view = json.loads(store.read_blob(receipt['knowledge']['package'])) if receipt['knowledge'].get('package') else {'entries': []}
    verdict = engine.verify(ledger, 'P2', 'D', CandidateChecker(ledger, 'P2'))['result']
    out.update(verdict=verdict, written=(store.context(produced['artifact']).get('b.txt') or '').strip()[:80], prompt_chars=receipt.get('prompt_chars'),
               knowledge_chars=receipt['knowledge'].get('chars', 0), delivered=[[e['id'], e['use'], e['applicability']['state']] for e in view['entries']],
               declared_used=receipt['knowledge_use']['used'], omitted=receipt['knowledge'].get('omitted_by_reason'))
    out['misled'] = verdict != 'pass' and bool(set(out['declared_used']) & {d[0] for d in out['delivered']})
    out['rework_needed'] = verdict != 'pass'
Path(OUT).write_text(json.dumps(out, ensure_ascii=False), encoding='utf-8')
'''


def bodies(template, work, project, state, out, condition, model):
    item = node('C', write=('a.txt',))
    item['checks'] = [{'id': 'M1', 'spec': 'The file holds the word the project requires now.'}]
    item['goal'] = 'Write the file with the word the project requires.'
    item['executor'] = {'role': 'worker', 'provider': 'claude', 'model': 'claude-haiku-5-5'}
    item['execution_cap_seconds'] = 300; item['estimate_seconds'] = [1, 300]
    integration = node('I', ['C'], integration=True, write=())
    integration['checks'] = [{'id': 'M1', 'spec': 'Integration keeps the file.'}]; integration['executor'] = dict(item['executor'])
    contract = plan_json(authority={'edit': True, 'commands': True, 'unconfined_commands': True, 'apply_to_project': True,
                                    'self_decide': ['Q1', 'Q2', 'Q3', 'Q4', 'Q5', 'Q9', 'Q12']})
    return (template.replace('WORK', repr(str(work))).replace('PROJECT', repr(str(project))).replace('STATE', repr(str(state)))
            .replace('OUT', repr(str(out))).replace('CONDITION', repr(condition)).replace('MODEL', repr(model))
            .replace('CONTRACT', repr(json.dumps(contract))).replace('NODE', repr(json.dumps(item))).replace('INTEG', repr(json.dumps(integration))))


def run(python, base, condition, model, fake_b):
    base.mkdir(parents=True)
    project, state = base / 'project', base / 'state'
    work_a, work_b = base / 'A', base / 'B'; work_a.mkdir(); work_b.mkdir()
    out_a, out_b = work_a / 'out.json', work_b / 'out.json'
    dump, tail = wh.run_case(python, bodies(PROCESS_A, work_a, project, state, out_a, condition, 'claude-haiku-5-5'),
                             env_extra=hx.scenario_env(python, work_a, log=work_a / 'fake.jsonl'), cwd=work_a)
    if not out_a.exists(): return {'condition': condition, 'error': 'root A: ' + tail[-400:]}
    env = hx.scenario_env(python, work_b, log=work_b / 'fake.jsonl') if fake_b else {'PATH': os.environ.get('PATH', '')}
    dump, tail = wh.run_case(python, bodies(PROCESS_B, work_b, project, state, out_b, condition, model), env_extra=env, cwd=work_b)
    if not out_b.exists(): return {'condition': condition, 'error': 'root B: ' + tail[-400:]}
    return dict(json.loads(out_b.read_text(encoding='utf-8')), published_by_a=json.loads(out_a.read_text(encoding='utf-8'))['published'])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('out'); parser.add_argument('--repeat', type=int, default=1)
    parser.add_argument('--real-model'); parser.add_argument('--real-repeat', type=int, default=1)
    args = parser.parse_args()
    runs, python, wheel, ctx = hx.runtime('ke02')
    wheel_sha = __import__('hashlib').sha256(Path(wheel).read_bytes()).hexdigest()
    rows = []
    try:
        for condition in ('fresh', 'reused', 'changed', 'withdrawn'):
            for i in range(args.repeat):
                rows.append(dict(run(python, runs / f'fake-{condition}-{i}', condition, 'claude-haiku-5-5', True), provider='fake', repeat=i))
                print(json.dumps(rows[-1], ensure_ascii=False)[:300], flush=True)
        if args.real_model:
            for condition in ('fresh', 'reused', 'changed', 'withdrawn'):
                for i in range(args.real_repeat):
                    rows.append(dict(run(python, runs / f'real-{condition}-{i}', condition, args.real_model, False), provider='claude-cli', repeat=i))
                    print(json.dumps(rows[-1], ensure_ascii=False)[:300], flush=True)
    finally:
        hx.cleanup(runs)
    result = {'kind': 'v23-ke02-reuse-comparison', 'checkout': subprocess.run(['git', '-C', str(ROOT), 'rev-parse', 'HEAD'], capture_output=True, text=True).stdout.strip(),
              'dirty': bool(subprocess.run(['git', '-C', str(ROOT), 'status', '--porcelain', '--', 'onecrew', 'pyproject.toml'], capture_output=True, text=True).stdout.strip()),
              'wheel_sha256_built_for_run': wheel_sha, 'rows': rows,
              'limits': 'root A always runs the fake claude (the knowledge is written by the real engine path); real rows run B only; one task, few repeats'}
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(result, indent=1, ensure_ascii=False), encoding='utf-8')


if __name__ == '__main__':
    main()
