"""Pinned live trials: which runtime ran a task and whether anything outside OneCrew changed during the window.

Records are evidence for the scorecard only; opening a trial never starts, resumes or authorizes work."""
import json
import os
from pathlib import Path
import re
import subprocess
import uuid

from .delegations import instant
from .ledger import LedgerError, canonical, content_hash, key_field, utcnow

TRIAL = re.compile(r'TRIAL-[0-9a-f]{32}\Z')
SHA = re.compile(r'[0-9a-f]{40,64}\Z')
DDL = '''CREATE TABLE IF NOT EXISTS eval_trials(id TEXT PRIMARY KEY, project_id TEXT NOT NULL, root_key TEXT NOT NULL,
    payload TEXT NOT NULL, closed TEXT, created_at TEXT NOT NULL)'''


def installed(conn):
    return bool(conn and conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='eval_trials'").fetchone())


def git(path, *args):
    try:
        done = subprocess.run(['git', '-C', str(path), *args], stdin=subprocess.DEVNULL, capture_output=True, timeout=15,
                              creationflags=0x08000000 if os.name == 'nt' else 0)
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout.decode('utf-8', 'replace').strip() if done.returncode == 0 else None


def target_state(path):
    head = git(path, 'rev-parse', '--verify', 'HEAD')
    return {'path': str(path), 'head': head if head and SHA.fullmatch(head) else None,
            'branch': git(path, 'symbolic-ref', '--short', '-q', 'HEAD') or None}


def window_commits(target, end=None):
    """Commits that reached the target branch after the trial opened; None when Git cannot show it."""
    start, branch = target.get('head'), target.get('branch')
    if not start:
        return None
    end = end or git(target['path'], 'rev-parse', '--verify', ('refs/heads/' + branch) if branch else 'HEAD')
    if not end or not SHA.fullmatch(end):
        return None
    listed = git(target['path'], 'rev-list', '--end-of-options', start + '..' + end)
    return None if listed is None else [line for line in listed.splitlines() if SHA.fullmatch(line)]


def view(row):
    value = json.loads(row['payload'])
    return dict(value, id=row['id'], closed=json.loads(row['closed']) if row['closed'] else None)


def _root(conn, project_id, key):
    columns = {r[1] for r in conn.execute('PRAGMA table_info(tasks)')}
    if 'request_key' not in columns:
        return None
    row = conn.execute('SELECT id FROM tasks WHERE project_id=? AND request_key=?', (project_id, key)).fetchone()
    return row['id'] if row else None


def onecrew_commits(conn, task):
    """Commit IDs the delivery recorded in its own receipts."""
    row = conn.execute("SELECT payload FROM events WHERE task_id=? AND kind='workflow.checkpoint' ORDER BY seq DESC LIMIT 1", (task,)).fetchone() if task else None
    nodes = ((json.loads(row['payload']).get('delivery') or {}).get('nodes') or {}) if row else {}
    found = set()
    for value in nodes.values():
        receipt = value.get('receipt') if isinstance(value, dict) and isinstance(value.get('receipt'), dict) else {}
        for sha in [receipt.get('commit')] + (receipt.get('commits') if isinstance(receipt.get('commits'), list) else []):
            if isinstance(sha, str) and SHA.fullmatch(sha): found.add(sha)
    return found


def open_trial(ledger, root_key, *, target=None, predecessor=None, by=None):
    """Pin the runtime (git, tree, dirty), state root and target head before the root task runs."""
    from .interventions import actor, revision
    key_field(root_key)
    if predecessor is not None and not TRIAL.fullmatch(predecessor):
        raise LedgerError('Predecessor must be a TRIAL- id.')
    target = Path(target or ledger.project).resolve()
    payload = {'root_key': root_key, 'project_id': ledger.project_id, 'runtime': revision(), 'state_root': str(ledger.state_root),
               'target': target_state(target), 'opened_at': utcnow(), 'predecessor': predecessor, 'opened_by': by or actor()}
    with ledger.transaction(write=True) as conn:
        conn.execute(DDL)
        if predecessor:
            old = conn.execute('SELECT * FROM eval_trials WHERE id=? AND project_id=?', (predecessor, ledger.project_id)).fetchone()
            if old is None: raise LedgerError('Unknown predecessor trial.')
            if not old['closed']: raise LedgerError('Close the predecessor trial (its result is kept) before opening its successor.')
        live = conn.execute('SELECT * FROM eval_trials WHERE project_id=? AND root_key=? AND closed IS NULL', (ledger.project_id, root_key)).fetchone()
        if live:
            current = view(live)
            if current['predecessor'] == predecessor and current['runtime'] == payload['runtime'] and current['target']['path'] == payload['target']['path']:
                return current  # a replayed open
            raise LedgerError('A trial for this root key is already open: ' + live['id'])
        if conn.execute('SELECT 1 FROM eval_trials WHERE project_id=? AND root_key=?', (ledger.project_id, root_key)).fetchone():
            raise LedgerError('This root key already had a trial; a new trial needs a new root key.')
        if _root(conn, ledger.project_id, root_key):
            raise LedgerError('The root task already exists; open the trial before submitting it.')
        tid = 'TRIAL-' + uuid.uuid4().hex
        conn.execute('INSERT INTO eval_trials VALUES(?,?,?,?,?,?)', (tid, ledger.project_id, root_key, canonical(payload), None, utcnow()))
        return view(conn.execute('SELECT * FROM eval_trials WHERE id=?', (tid,)).fetchone())


def _get(conn, ledger, trial_id):
    row = conn.execute('SELECT * FROM eval_trials WHERE id=? AND project_id=?', (trial_id, ledger.project_id)).fetchone() if installed(conn) else None
    if row is None:
        raise LedgerError('Unknown trial in this project.')
    return row


def close_trial(ledger, trial_id, *, by=None):
    """Snapshot the window (target commits) and the root's scorecard row; the result is kept even if assisted."""
    from .interventions import actor
    with ledger.transaction() as conn:
        record = view(_get(conn, ledger, trial_id))
        if record['closed']:
            return record
        task = _root(conn, ledger.project_id, record['root_key'])
        ours = onecrew_commits(conn, task)
    end = target_state(Path(record['target']['path']))
    window = window_commits(record['target'])
    card = None
    if task:
        from .eval_scorecard import scorecard
        row = scorecard(ledger.state_root, [task])['axes']['task_completion']['tasks'][0]
        card = {k: row[k] for k in ('outcome', 'completion_level', 'assistance_level', 'assistance_reasons')} | {'sha256': content_hash(row)}
    value = {'closed_at': utcnow(), 'closed_by': by or actor(), 'task': task, 'target_head': end['head'],
             'window_commits': window, 'onecrew_commits': sorted(ours & set(window or ())),
             'external_commits': None if window is None else [c for c in window if c not in ours], 'scorecard': card}
    with ledger.transaction(write=True) as conn:
        row = _get(conn, ledger, trial_id)
        if row['closed']:
            return view(row)
        conn.execute('UPDATE eval_trials SET closed=? WHERE id=?', (canonical(value), trial_id))
        return view(conn.execute('SELECT * FROM eval_trials WHERE id=?', (trial_id,)).fetchone())


def show(ledger, trial_id):
    with ledger.transaction() as conn:
        record = view(_get(conn, ledger, trial_id))
        task = _root(conn, ledger.project_id, record['root_key'])
        members = [task] if task else []
        if task and conn.execute("SELECT 1 FROM sqlite_master WHERE name='delivery_children'").fetchone():
            members += [r[0] for r in conn.execute('SELECT task_id FROM delivery_children WHERE root=? ORDER BY task_id', (task,))]
        record['task'] = task
        record['evidence'] = evidence(conn, task, members) if task else None
        record['successors'] = [r['id'] for r in conn.execute('SELECT id,payload FROM eval_trials WHERE project_id=?', (ledger.project_id,))
                                if json.loads(r['payload']).get('predecessor') == trial_id]
    return record


def evidence(conn, task, members):
    """Trial checks for one root task; None when no trial names its key."""
    if not installed(conn):
        return None
    row = conn.execute('SELECT * FROM tasks WHERE id=?', (task,)).fetchone()
    columns = row.keys() if row else []
    if not row or 'request_key' not in columns:
        return None
    found = conn.execute('SELECT * FROM eval_trials WHERE project_id=? AND root_key=? ORDER BY rowid DESC LIMIT 1',
                         (row['project_id'], row['request_key'])).fetchone()
    if not found:
        return None
    record = view(found)
    runtime, target, closed = record.get('runtime') or {}, record.get('target') or {}, record.get('closed')
    assisted, unknown = set(), set()
    if not (runtime.get('tree') and runtime.get('git') and runtime.get('dirty') is not None and target.get('head')):
        unknown.add('trial_unpinned')
    if runtime.get('dirty') is True:
        assisted.add('runtime_changed_in_trial')
    opened, ended = instant(record.get('opened_at')), instant((closed or {}).get('closed_at'))
    created = instant(row['created_at']) if 'created_at' in columns else None
    if opened is None or created is None or created < opened:
        unknown.add('trial_unpinned')  # the window does not cover the whole run
    marks = ','.join('?' for _ in members)
    for start in conn.execute(f"SELECT payload,created_at FROM events WHERE task_id IN ({marks}) AND kind='runner.started' ORDER BY seq", list(members)):
        at = instant(start['created_at'])
        if at is None or (opened and at < opened) or (ended and at > ended):
            continue
        value = json.loads(start['payload']).get('runtime')
        if not isinstance(value, dict) or not value.get('tree'):
            unknown.add('trial_unpinned')
        elif value['tree'] != runtime.get('tree') or value.get('dirty') is True:
            assisted.add('runtime_changed_in_trial')
    if closed:
        external = closed.get('external_commits')
    else:
        window = window_commits(target)
        external = None if window is None else [c for c in window if c not in onecrew_commits(conn, task)]
    if external is None:
        unknown.add('trial_unpinned')
    elif external:
        assisted.add('external_commit')
    return {'id': record['id'], 'closed': bool(closed), 'pinned': 'trial_unpinned' not in unknown,
            'assisted': sorted(assisted), 'unknown': sorted(unknown)}
