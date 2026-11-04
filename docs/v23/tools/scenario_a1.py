"""scenario_a1.py <case> <work dir> - the A1 first task, run by verify_milestone.py with the INSTALLED onecrew (python -I, cwd = work).

A project with one wiki rule ("a.txt must hold VALUE: right"), a plan approved in this temporary ledger (fixture owner, never a real
ledger), an engine root with node C (pin claude / claude-haiku-5-5) whose real command check wants "right". engine.step goes through the
real NativeExecutor -> ClaudeArtifact -> Supervisor -> the `claude` on PATH (the fake test double installed in the verify venv).
Cases: first | outside_scope (the rule cites a file outside C's read scope) | stale_source (a.txt changed after the rule was recorded)
| mandatory_over_cap (a mandatory rule longer than the knowledge cap) | control22 (the same flow, run by a 2.2 install: no knowledge
fields are read, so the ledger it writes is the rollback control). Writes <work>/result.json."""
import json
import os
import subprocess
import sys
from pathlib import Path

from onecrew.common_executor import NativeExecutor
from onecrew.common_verification import CandidateChecker
from onecrew.ledger import Ledger
from onecrew.snapshots import Snapshots
from onecrew.v2 import engine, internal_plan, plan

case, work = sys.argv[1], Path(sys.argv[2])
root = work / 'project with space'; root.mkdir()


def git(*args):
    return subprocess.run(['git', '-C', str(root), *args], check=True, capture_output=True, text=True).stdout.strip()


git('init', '-q'); git('config', 'user.name', 'fixture'); git('config', 'user.email', 'fixture@localhost')
(root / 'a.txt').write_text('base\n'); (root / 'secret.txt').write_text('PRIVATE material\n'); (root / '.gitignore').write_text('.onecrew/\n')
git('add', '.'); git('commit', '-qm', 'base'); recorded = git('rev-parse', 'HEAD')
cited = 'secret.txt' if case == 'outside_scope' else 'a.txt'
meta = {'id': 'a-value', 'kind': 'constraint', 'label': 'verified', 'must': True, 'applies_to': ['a.txt'],
        'sources': [{'type': 'file', 'path': cited, 'revision': recorded}]}
text = 'a.txt phải chứa đúng VALUE: right — không phải giá trị mặc định.'
if case == 'outside_scope': text += ' Nguồn: PRIVATE material.'
if case == 'mandatory_over_cap': text += ' Quy tắc chi tiết.' * 1200
page = ('# Quy ước\n\n## Giá trị của a.txt\n```onecrew\n' + json.dumps(meta) + '\n```\n' + text + '\n\n'
        '## Lịch họp\nHọp nhóm thứ hai hằng tuần ở phòng lớn.\n')
(root / 'docs' / 'wiki').mkdir(parents=True)
(root / 'docs' / 'wiki' / 'rules.md').write_text(page, encoding='utf-8')
git('add', '.'); git('commit', '-qm', 'wiki')
if case == 'stale_source':
    (root / 'a.txt').write_text('changed after the rule was recorded\n'); git('commit', '-qam', 'a.txt changed')

ledger = Ledger(root, work / 'state with space')
check = [sys.executable, '-c', 'from pathlib import Path; v = Path("a.txt").read_text().strip(); assert v == "right", v; print("value verified")']
contract = {'schema_version': 2, 'title': 'Viết a.txt theo wiki', 'size': 'S',
            'understanding': {'restated_goal': 'a.txt chứa giá trị mà wiki của project yêu cầu.', 'target': {'repo': '.', 'ref': 'HEAD', 'paths': ['a.txt']},
                              'assumptions': [], 'confidence': 'high', 'unknowns': []},
            'preconditions': [{'id': 'P1', 'check': 'path_exists', 'args': {'path': 'a.txt'}, 'why': 'the file to work on is there'}],
            'output': ['a.txt holds the required value'], 'scope': {'owned': ['a.txt']}, 'non_goals': ['Nothing else'],
            'items': [{'id': 'I1', 'title': 'Write a.txt', 'tier': 'must', 'milestone': 'M1'}],
            'milestones': [{'id': 'M1', 'title': 'Value check', 'verifier': {'type': 'command', 'config': {'argv': check}}, 'covers': ['O1']}],
            'budget': {'max_calls': 100, 'time': 120}, 'attention': {'questions': 1}, 'profile_version': None,
            'authority': {'edit': True, 'commands': True, 'unconfined_commands': True, 'self_decide': ['Q1', 'Q2', 'Q3', 'Q4', 'Q5', 'Q9', 'Q12']}}


def node(nid, depends=(), integration=False, write=('a.txt',)):
    return {'id': nid, 'goal': 'Write a.txt with the value the project requires.', 'input': [], 'output': ['a.txt holds the required value'],
            'acceptance': ['O1'], 'depends': [{'node': d, 'requires': 'verified'} for d in depends], 'read': ['a.txt'], 'write': list(write),
            'resources': [], 'estimate_seconds': [1, 60], 'execution_cap_seconds': 60, 'budget_calls': 1,
            'checks': [{'id': 'M1', 'spec': 'a.txt holds the value the project wiki requires.'}], 'integration': integration,
            'executor': {'role': 'worker', 'provider': 'claude', 'model': 'claude-haiku-5-5'}}


plan.propose(ledger, 'P1', contract, 'codex', workflow=True, capabilities=['namespaced-storage', 'root-budget', 'internal-plan', 'sequential-engine'])
plan.approve(ledger, 'P1', 'owner', 'temporary verification fixture (not a real ledger)')
internal_plan.revise(ledger, 'P1', [node('C'), node('I', ['C'], integration=True, write=())], reason='A1 first task', evidence=['a.txt:1'])
fake_log = Path(os.environ.get('ONECREW_FAKE_LOG') or (work / 'fake.jsonl'))
os.environ['ONECREW_FAKE_LOG'] = str(fake_log)
policy = work / 'policy.json'; policy.write_text(json.dumps({'target': 'a.txt', 'default': 'naive', 'careful': True}))
os.environ['ONECREW_FAKE_POLICY'] = str(policy)
store = Snapshots(ledger.state_root)
produced = engine.step(ledger, 'P1', NativeExecutor(ledger))
runs = len(fake_log.read_text(encoding='utf-8').splitlines()) if fake_log.exists() else 0
out = {'case': case, 'project': str(root), 'state': str(ledger.state_root), 'fake_runs': runs}
if case == 'control22':
    out.update(step_state=produced['state'], reason=str(produced.get('reason') or '')[:300])
elif produced['state'] == 'produced':
    receipt = json.loads(store.read_blob(produced['receipt']))
    record = receipt['knowledge']
    view = json.loads(store.read_blob(record['package'])) if record.get('package') else {'entries': []}
    out.update(delivered=record['delivered'], uses=[[e['id'], e['use'], e['applicability']['state']] for e in view['entries']],
               use_violations=receipt['knowledge_use']['violations'], package_text=json.dumps(view, ensure_ascii=False)[:4000],
               omitted=view.get('omitted'), page_unchanged=(root / 'docs' / 'wiki' / 'rules.md').read_text(encoding='utf-8') == page)
    if case == 'first':
        out['verdict'] = engine.verify(ledger, 'P1', 'C', CandidateChecker(ledger, 'P1'))['result']
elif produced['state'] == 'held' and str(produced.get('reason', '')).startswith('Mandatory knowledge'):
    with ledger.transaction() as conn:
        rows = conn.execute("SELECT result FROM attempts ORDER BY rowid").fetchall() if conn else []
    out.update(state='refused_before_model', reason=produced['reason'][:300], attempts=[r['result'] for r in rows][-1:])
else:
    out.update(state=produced['state'], reason=str(produced.get('reason'))[:300])
(work / 'result.json').write_text(json.dumps(out, ensure_ascii=False), encoding='utf-8')
print(json.dumps({k: v for k, v in out.items() if k != 'package_text'}, ensure_ascii=False)[:1000])
