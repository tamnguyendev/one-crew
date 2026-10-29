"""scenario_codex.py <case> <work dir> - the counterexamples of the Codex review of 2.3.0.dev2 (P2-01, P2-02), run by verify_milestone.py
with the INSTALLED onecrew (python -I, cwd = work; the `onecrew` executable and the fake `claude` test double of the verify venv first on
PATH). Temporary project and ledger only (fixture owner approval, never a real ledger). Writes <work>/result.json.

Cases (P2-02, through the real dispatch path engine.step -> NativeExecutor -> ClaudeArtifact -> Supervisor -> fake claude process):
  beyond_pages     2 000 other pages sort before the page holding the mandatory rule -> the rule is delivered, the node runs
  undeliverable    the page holding the mandatory rule is not UTF-8 -> the step stops before any provider process
  optional_broken  control: pages that cannot be read but declare nothing mandatory -> the node runs, the problems are recorded
Case (P2-01, through the installed CLI):
  continue         `onecrew wiki record` (verified, applies to a.txt; a root note superseded by a newer one; a note of another root),
                   `onecrew continue P1 --json` and `onecrew context retrieve --plan P1` before and after a.txt changes.
Case (Codex review of 2.3.0.dev3, P2, through the installed CLI):
  general          shared (general) records whose condition is false here, holds, cannot be checked, or was withdrawn; a project
                   record whose condition is false; a 2.2 shared note: `onecrew context retrieve` in every form that returns the
                   general scope (with/without --plan, scope general/both), `wiki show --plan P1` and `wiki history`."""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from onecrew.common_executor import NativeExecutor
from onecrew.ledger import Ledger
from onecrew.snapshots import Snapshots
from onecrew.v2 import engine, internal_plan, plan

case, work = sys.argv[1], Path(sys.argv[2])
root = work / 'project with space'; root.mkdir()


def git(*args):
    return subprocess.run(['git', '-C', str(root), *args], check=True, capture_output=True, text=True).stdout.strip()


git('init', '-q'); git('config', 'user.name', 'fixture'); git('config', 'user.email', 'fixture@localhost')
(root / 'a.txt').write_text('base\n'); (root / '.gitignore').write_text('.onecrew/\n')
git('add', '.'); git('commit', '-qm', 'base'); recorded = git('rev-parse', 'HEAD')
wiki = root / 'docs' / 'wiki'; wiki.mkdir(parents=True)
meta = {'id': 'a-value', 'kind': 'constraint', 'label': 'verified', 'must': True, 'applies_to': ['a.txt'],
        'sources': [{'type': 'file', 'path': 'a.txt', 'revision': recorded}]}
page = ('# Quy ước\n\n## Giá trị của a.txt\n```onecrew\n' + json.dumps(meta) + '\n```\na.txt phải chứa đúng VALUE: right — không phải giá trị mặc định.\n')
data = page.encode('utf-8')
if case == 'undeliverable': data += b'\n## Ghi ch\xfa\nB\xe1n c\xfa ph\xe1p latin-1.\n'      # not UTF-8: the page cannot be read whole
(wiki / 'zzz-rules.md').write_bytes(data)
if case == 'beyond_pages':
    for i in range(2000):
        (wiki / f'a{i:05d}.md').write_text(f'## Ghi chú {i}\nPhòng họp {i} ở tầng hai.\n', encoding='utf-8')
if case == 'optional_broken':
    (wiki / 'broken.md').write_bytes(b'## Notes\nnot utf-8 \xff\xfe here\n')
    (wiki / 'bad-meta.md').write_text('## Note\n```onecrew\n{"id": "n1", "colour": "red"}\n```\nFree text.\n', encoding='utf-8')
git('add', '.'); git('commit', '-qm', 'wiki')

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
CAPS = ['namespaced-storage', 'root-budget', 'internal-plan', 'sequential-engine']


def node(nid, depends=(), integration=False, write=('a.txt',)):
    return {'id': nid, 'goal': 'Write a.txt with the value the project requires.', 'input': [], 'output': ['a.txt holds the required value'],
            'acceptance': ['O1'], 'depends': [{'node': d, 'requires': 'verified'} for d in depends], 'read': ['a.txt'], 'write': list(write),
            'resources': [], 'estimate_seconds': [1, 60], 'execution_cap_seconds': 60, 'budget_calls': 1,
            'checks': [{'id': 'M1', 'spec': 'a.txt holds the value the project wiki requires.'}], 'integration': integration,
            'executor': {'role': 'worker', 'provider': 'claude', 'model': 'claude-haiku-5-5'}}


def root_plan(name):
    plan.propose(ledger, name, contract, 'codex', workflow=True, capabilities=CAPS)
    plan.approve(ledger, name, 'owner', 'temporary verification fixture (not a real ledger)')


root_plan('P1')
out = {'case': case, 'project': str(root), 'state': str(ledger.state_root)}
if case == 'continue':
    exe = shutil.which('onecrew')
    def cli(*args):
        done = subprocess.run([exe, '--project', str(root), '--state-root', str(ledger.state_root), *args], capture_output=True,
                              text=True, encoding='utf-8', errors='replace', cwd=work)
        return done.returncode, done.stdout, done.stderr
    with ledger.transaction() as conn:
        event = conn.execute('SELECT MAX(seq) FROM events').fetchone()[0]
    def record(*args):
        code, stdout, stderr = cli('wiki', 'record', '--source', f'event:{event}', *args)
        return json.loads(stdout) if code == 0 else {'error': (stdout + stderr)[-300:]}
    decision = record('--plan', 'P1', '--kind', 'decision', '--text', 'Use the old a.txt convention', '--status', 'verified',
                      '--property', 'check M1 passed', '--applies-to', 'a.txt')
    old = record('--plan', 'P1', '--kind', 'note', '--text', 'Old private rule', '--status', 'verified', '--property', 'agreed', '--visibility', 'root')
    new = record('--plan', 'P1', '--kind', 'note', '--text', 'New private rule', '--status', 'verified', '--property', 'agreed', '--visibility', 'root',
                 '--supersedes', old.get('id', '?'))
    root_plan('P2')
    other = record('--plan', 'P2', '--kind', 'note', '--text', 'P2 private working note', '--status', 'observed', '--visibility', 'root')

    def pack():
        code, stdout, stderr = cli('continue', 'P1', '--json')
        return code, ({e['text']: [e['label'], e.get('stale_reason')] for e in json.loads(stdout)['context']} if code == 0 else {'error': (stdout + stderr)[-300:]})
    def retrieved():
        code, stdout, stderr = cli('context', 'retrieve', '--plan', 'P1', '--scope', 'project')
        return {e['text']: e['label'] for e in json.loads(stdout)['entries']} if code == 0 else {'error': (stdout + stderr)[-300:]}
    out['recorded'] = {k: bool(v.get('id')) for k, v in (('decision', decision), ('old', old), ('new', new), ('other', other))}
    out['before_exit'], out['before'] = pack()
    out['retrieve_before'] = retrieved()
    (root / 'a.txt').write_text('a different content\n')
    out['after_exit'], out['after'] = pack()
    out['retrieve_after'] = retrieved()
    code, stdout, _ = cli('wiki', 'history')
    out['history'] = {r['text']: r['status'] for r in json.loads(stdout)['records']} if code == 0 else None
elif case == 'general':
    exe = shutil.which('onecrew')
    elsewhere = 'linux' if sys.platform != 'linux' else 'win32'
    def cli(*args):
        done = subprocess.run([exe, '--project', str(root), '--state-root', str(ledger.state_root), *args], capture_output=True,
                              text=True, encoding='utf-8', errors='replace', cwd=work)
        return done.returncode, done.stdout, done.stderr
    def last_event():
        with ledger.transaction() as conn:
            return conn.execute('SELECT MAX(seq) FROM events').fetchone()[0]
    def general(text, condition):
        code, stdout, stderr = cli('wiki', 'record', '--plan', 'P1', '--kind', 'decision', '--text', text, '--status', 'verified', '--scope', 'general',
                                   '--property', 'the retry check passed', '--source', f'event:{last_event()}', '--condition', json.dumps(condition))
        return json.loads(stdout) if code == 0 else {'error': (stdout + stderr)[-300:]}
    ids = {'false': general('Retry rule for elsewhere', {'type': 'env', 'key': 'platform', 'value': elsewhere}),
           'true': general('Retry rule here', {'type': 'env', 'key': 'platform', 'value': sys.platform}),
           'unknown': general('Retry rule for a model', {'type': 'env', 'key': 'model', 'value': 'some-model'}),
           'withdrawn': general('Withdrawn retry rule', {'type': 'env', 'key': 'platform', 'value': sys.platform})}
    out['recorded'] = {name: bool(value.get('id')) for name, value in ids.items()}
    out['withdraw_exit'] = cli('wiki', 'withdraw', ids['withdrawn'].get('id', '?'), '--plan', 'P1', '--reason', 'shown wrong',
                               '--source', f'event:{last_event()}')[0]
    out['project_exit'] = cli('wiki', 'record', '--plan', 'P1', '--kind', 'decision', '--text', 'Project rule for elsewhere', '--status', 'verified',
                              '--property', 'check M1 passed', '--source', f'event:{last_event()}', '--applies-to', 'a.txt',
                              '--condition', json.dumps({'type': 'env', 'key': 'platform', 'value': elsewhere}))[0]
    out['legacy_exit'] = cli('context', 'add', 'P1', '--kind', 'note', '--label', 'observed', '--text', '2.2 shared note',
                             '--source', f'event:{last_event()}', '--scope', 'general', '--condition', 'Python')[0]
    forms = {'general': ['--scope', 'general'], 'both': ['--scope', 'both'], 'plan general': ['--plan', 'P1', '--scope', 'general'],
             'plan both': ['--plan', 'P1', '--scope', 'both'], 'plan project': ['--plan', 'P1', '--scope', 'project']}
    out['retrieve'] = {}
    for name, form in forms.items():
        code, stdout, stderr = cli('context', 'retrieve', *form)
        out['retrieve'][name] = ({e['text']: [e['label'], e.get('stale_reason'), e.get('stored_label')] for e in json.loads(stdout)['entries']}
                                 if code == 0 else {'error': (stdout + stderr)[-300:]})
    code, stdout, stderr = cli('wiki', 'show', '--plan', 'P1')
    if code == 0:
        package = json.loads(stdout)
        seen = {e['id']: e['use'] for e in package['entries']}
        seen.update({row['id']: row['use'] for row in package['omitted']['index']})
        out['wiki'] = {name: seen.get(value.get('id'), 'not delivered') for name, value in ids.items()}
        out['wiki_left_out'] = package['omitted']['by_reason']
    else:
        out['wiki'] = {'error': (stdout + stderr)[-300:]}
    code, stdout, _ = cli('wiki', 'history')
    out['history'] = {r['text']: [r['status'], r['label']] for r in json.loads(stdout)['records']} if code == 0 else None
else:
    internal_plan.revise(ledger, 'P1', [node('C'), node('I', ['C'], integration=True, write=())], reason='Codex P2-02 case', evidence=['a.txt:1'])
    fake_log = Path(os.environ.get('ONECREW_FAKE_LOG') or (work / 'fake.jsonl'))
    os.environ['ONECREW_FAKE_LOG'] = str(fake_log)
    policy = work / 'policy.json'; policy.write_text(json.dumps({'target': 'a.txt', 'default': 'naive', 'careful': True}))
    os.environ['ONECREW_FAKE_POLICY'] = str(policy)
    store = Snapshots(ledger.state_root)
    produced = engine.step(ledger, 'P1', NativeExecutor(ledger))
    out['fake_runs'] = len(fake_log.read_text(encoding='utf-8').splitlines()) if fake_log.exists() else 0
    out['state'] = produced['state']
    out['reason'] = str(produced.get('reason') or '')[:400]
    if produced['state'] == 'produced':
        receipt = json.loads(store.read_blob(produced['receipt']))
        record = receipt['knowledge']
        view = json.loads(store.read_blob(record['package'])) if record.get('package') else {'entries': []}
        out.update(delivered=record['delivered'], mandatory=[e['id'] for e in view['entries'] if e['must']], wiki=record.get('wiki'),
                   problems=len(record.get('problems') or []), seconds=(record.get('cost') or {}).get('seconds'))
    else:
        with ledger.transaction() as conn:
            rows = conn.execute("SELECT result FROM attempts ORDER BY rowid").fetchall() if conn else []
        out['attempts'] = [r['result'] for r in rows][-1:]
(work / 'result.json').write_text(json.dumps(out, ensure_ascii=False), encoding='utf-8')
print(json.dumps(out, ensure_ascii=False)[:1200])
