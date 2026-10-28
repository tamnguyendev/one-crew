"""measure_scale.py <out.json> - 2.3-A1 KS-01: the cost of choosing a knowledge package as the store grows (wall time, candidates,
delivered), on a fresh repository and state root under TEMP. Ledger entries are inserted directly as `context.entry` rows of the shape
context.add writes (generation is not what is measured); a fraction cite a file at a commit (the code-bound path that runs git),
the rest cite a ledger event. Other projects share the state root (their rows must be skipped cheaply). Wiki pages hold sections.
Run from the checkout: python -B docs/v23/tools/measure_scale.py D:/OneCrewRuns/v23/measure/scale.json"""
import json
import os
import random
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
for name in ('CLAUDECODE', 'CLAUDE_CODE_CHILD_SESSION', 'ONECREW_ACTOR'):
    os.environ.pop(name, None)

from onecrew.ledger import Ledger, content_hash, utcnow           # noqa: E402
from onecrew.v2 import knowledge, plan as plans, context          # noqa: E402
from tests.test_v2_l1 import plan_json                            # noqa: E402


def git(root, *args):
    return subprocess.run(['git', '-C', str(root), *args], check=True, capture_output=True, text=True).stdout.strip()


def repo(base, name):
    root = base / name; root.mkdir()
    git(root, 'init', '-q'); git(root, 'config', 'user.name', 'm'); git(root, 'config', 'user.email', 'm@localhost')
    for i in range(20): (root / f'f{i}.txt').write_text(f'line {i}\n')
    (root / 'a.txt').write_text('one\n')
    git(root, 'add', '.'); git(root, 'commit', '-qm', 'base')
    return root, git(root, 'rev-parse', 'HEAD')


def insert(ledger, plan_name, start, count, head, code_fraction, rng, topic):
    with ledger.transaction(write=True) as conn:
        task = conn.execute("SELECT id FROM tasks WHERE project_id=? AND request_key LIKE ?", (ledger.project_id, '%' + plan_name)).fetchone()['id']
        anchor_seq = conn.execute('SELECT MIN(seq) FROM events WHERE task_id=?', (task,)).fetchone()[0]
        for i in range(start, start + count):
            code = rng.random() < code_fraction
            path = f'f{rng.randrange(20)}.txt'
            source = {'type': 'file_line', 'path': path, 'line': 1, 'revision': head} if code else {'type': 'event', 'id': anchor_seq}
            text = f'{topic} note {i} about {path if code else "the process"} and item {rng.randrange(1000)}'
            body = {'version': 1, 'key': content_hash([plan_name, i, topic])[:24], 'scope': 'project', 'project': ledger.project_id,
                    'plan': plan_name, 'plan_anchor': 'plan-ns:' + plan_name, 'kind': 'note', 'label': 'observed', 'text': text,
                    'source': source, 'source_text': 'x', 'symbol': None, 'revision_ref': head if code else None,
                    'line_hash': None, 'conditions': None, 'visibility': 'project'}
            body['id'] = content_hash(body)
            conn.execute('INSERT INTO events(task_id, kind, payload, created_at) VALUES (?,?,?,?)',
                         (task, 'context.entry', json.dumps(dict(body, root=task, plan_revision=1)), utcnow()))


def base_reader():
    """context.py of the 2.2 baseline (95bb7a6), loaded as a sibling module so its relative imports resolve: the reader A1 replaced."""
    import importlib.util
    code = subprocess.run(['git', '-C', str(ROOT), 'show', '95bb7a6:onecrew/v2/context.py'], check=True, capture_output=True).stdout
    path = Path(tempfile.mkdtemp()) / '_context_base.py'; path.write_bytes(code)
    spec = importlib.util.spec_from_file_location('onecrew.v2._context_base', path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


def timed(fn, repeat=3):
    times = []
    for _ in range(repeat):
        started = time.perf_counter(); value = fn(); times.append(time.perf_counter() - started)
    return round(min(times), 4), value


def measure(ledger, cons, repeat=3):
    times, pkg = [], None
    for _ in range(repeat):
        started = time.perf_counter()
        pkg = knowledge.package(ledger, cons, cap_chars=12000)
        times.append(time.perf_counter() - started)
    return {'seconds_min': round(min(times), 4), 'seconds_max': round(max(times), 4), 'candidates': pkg['cost']['candidates'],
            'eligible': pkg['cost']['eligible'], 'delivered': len(pkg['entries']), 'omitted_total': pkg['omitted']['total']}


def main(out):
    global BASE
    BASE = base_reader()
    rng = random.Random(23)
    rows = []
    with tempfile.TemporaryDirectory() as temp:
        base = Path(temp)
        mine, head = repo(base, 'mine')
        other, other_head = repo(base, 'other')
        state = base / 'state'
        ledger, foreign = Ledger(mine, state), Ledger(other, state)
        plans.propose(ledger, 'P1', plan_json(), 'codex')
        plans.propose(foreign, 'Q1', plan_json(), 'codex')
        cons = knowledge.consumer(ledger, 'P1', node={'id': 'C', 'read': ['a.txt', 'f1.txt'], 'write': ['a.txt'], 'goal': 'Fix the a.txt line',
                                                        'output': ['a.txt fixed'], 'checks': [{'id': 'M1', 'spec': 'a.txt has one line'}]})
        total_mine = total_other = 0
        for target_mine, target_other, sections in ((100, 0, 0), (1000, 1000, 200), (5000, 5000, 1000), (10000, 10000, 1000), (20000, 20000, 2000),
                                                    (50000, 50000, 2000)):
            insert(ledger, 'P1', total_mine, target_mine - total_mine, head, 0.2, rng, 'mine'); total_mine = target_mine
            insert(foreign, 'Q1', total_other, target_other - total_other, other_head, 0.2, rng, 'foreign'); total_other = target_other
            wiki_dir = mine / 'docs' / 'wiki'; wiki_dir.mkdir(parents=True, exist_ok=True)
            pages = max(1, sections // 100) if sections else 0
            for f in wiki_dir.glob('*.md'): f.unlink()
            for p in range(pages):
                (wiki_dir / f'page{p}.md').write_text(''.join(f'## Topic {p}-{s}\nWiki text {s} about f{s % 20}.txt and deployment.\n' for s in range(100)), encoding='utf-8')
            row = {'ledger_entries_project': total_mine, 'ledger_entries_other_project': total_other, 'wiki_sections': pages * 100}
            row.update(measure(ledger, cons))
            row['context_retrieve_200_new_s'], _ = timed(lambda: context.retrieve(ledger, plan='P1', scope='both'))
            row['context_retrieve_200_base_s'], _ = timed(lambda: BASE.retrieve(ledger, plan='P1', scope='both'))
            rows.append(row); print(json.dumps(row))
        pages_rows = []                                # Codex P2-02: every page is looked through; past wiki.MAX_PAGES only for mandatory sections
        plans.propose(ledger, 'P2', plan_json(), 'codex')
        quiet = Ledger(mine, base / 'state-pages')
        plans.propose(quiet, 'P1', plan_json(), 'codex')
        cons_pages = knowledge.consumer(quiet, 'P1', node={'id': 'C', 'read': ['a.txt', 'f1.txt'], 'write': ['a.txt'], 'goal': 'Fix the a.txt line',
                                                            'output': ['a.txt fixed'], 'checks': [{'id': 'M1', 'spec': 'a.txt has one line'}]})
        for f in wiki_dir.glob('*.md'): f.unlink()
        made = 0
        for count in (1000, 2000, 2001, 5000, 10000):
            for p in range(made, count):
                (wiki_dir / f'p{p:05d}.md').write_text(f'## Topic {p}\nWiki text about f{p % 20}.txt and deployment.\n', encoding='utf-8')
            made = count
            (wiki_dir / 'zzz-must.md').write_text('## a.txt value\n```onecrew\n{"id": "required-last", "kind": "constraint", "must": true, '
                                                  '"applies_to": ["a.txt"]}\n```\nVALUE: right\n', encoding='utf-8')
            row = {'wiki_pages': count + 1, 'ledger_entries_project': 0}
            row.update(measure(quiet, cons_pages))
            pkg = knowledge.package(quiet, cons_pages, cap_chars=12000)
            row['mandatory_delivered'] = [e['id'] for e in pkg['entries'] if e['must']]
            row['wiki'] = pkg.get('wiki')
            pages_rows.append(row); print(json.dumps(row))
    result = {'kind': 'v23-ks01-scale', 'checkout': subprocess.run(['git', '-C', str(ROOT), 'rev-parse', 'HEAD'], capture_output=True, text=True).stdout.strip(),
              'dirty': bool(subprocess.run(['git', '-C', str(ROOT), 'status', '--porcelain', '--', 'onecrew', 'pyproject.toml'], capture_output=True, text=True).stdout.strip()),
              'python': sys.version.split()[0], 'platform': sys.platform, 'machine_shared': True,
              'note': 'wall time on a shared Windows machine (other sessions running); rows inserted directly; 20% code-bound entries cite 20 files',
              'rows': rows, 'pages_rows': pages_rows}
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text(json.dumps(result, indent=1), encoding='utf-8')


if __name__ == '__main__':
    main(sys.argv[1])
