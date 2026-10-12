"""Automatic entry-intervention evidence and runtime identity. Records never grant authority."""
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess

from .ledger import LedgerError, canonical, content_hash, key_field

ACTORS = ('claude', 'codex', 'user', 'keeper', 'onecrew', 'other-entry')
OTHER_ENTRIES = ('kiro', 'cursor', 'copilot', 'gemini', 'windsurf')
SUFFIXES = ('.py', '.md', '.cjs', '.json')
PACKAGE = Path(__file__).resolve().parent
_REVISION = None


def _exact(value):
    value = value.strip().lower() if isinstance(value, str) else ''
    return value if value in ACTORS else None


def _mapped(source):
    tokens = set(re.split(r'[^a-z0-9]+', source.lower())) if isinstance(source, str) else set()
    for known in ('claude', 'codex'):
        if known in tokens: return known
    if tokens & {'human', 'user'}: return 'user'
    return 'other-entry' if tokens & set(OTHER_ENTRIES) else None


def _resolve(source=None):
    return (source and (_exact(source) or _mapped(source))) or _exact(os.environ.get('ONECREW_ACTOR')) or 'unknown'


def actor(source=None):
    """MCP source name first, then ONECREW_ACTOR. Unattributed stays 'unknown', never a guess."""
    return _resolve(source)


def initiator():
    value = os.environ.get('ONECREW_RUNNER_INITIATOR', '')
    return value if re.fullmatch(r'[a-z][a-z0-9-]{0,39}', value) else 'unknown'


def tree(package=PACKAGE):
    package = Path(package)
    files = sorted((p.relative_to(package).as_posix(), p) for p in package.rglob('*')
                   if p.is_file() and p.suffix.lower() in SUFFIXES and '__pycache__' not in p.relative_to(package).parts)
    digest = hashlib.sha256()
    for name, path in files:
        data, encoded = path.read_bytes(), name.encode('utf-8')
        digest.update(len(encoded).to_bytes(4, 'big') + encoded + len(data).to_bytes(8, 'big') + data)
    return digest.hexdigest()


def _git(package, *args):
    try:
        # No console window: callers include detached runners/keepers.
        done = subprocess.run(['git', *args], cwd=package, stdin=subprocess.DEVNULL, capture_output=True, timeout=5,
                              creationflags=0x08000000 if os.name == 'nt' else 0)
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout.decode('utf-8', 'replace').strip() if done.returncode == 0 else None


def _tree(package):
    for _ in range(2):  # a file replaced mid-hash (editor save, checkout) usually settles at once
        try: return tree(package)
        except OSError: pass
    return None  # unknown runtime: evidence collection never turns a runner start into a failure


def revision(package=PACKAGE):
    head = _git(package, 'rev-parse', 'HEAD')
    head = head if head and re.fullmatch('[0-9a-f]{40,64}', head) else None
    changes = _git(package, 'status', '--porcelain', '--', '.') if head else None
    return {'tree': _tree(package), 'git': head, 'dirty': None if changes is None else bool(changes)}


def runtime_revision():
    """Loaded runtime identity, computed once per process (a later edit is a new runtime)."""
    global _REVISION
    if _REVISION is None:
        _REVISION = revision()
    return dict(_REVISION)


def record(ledger, task_id, command, *, actor=None, channel='cli', reason=None, details=None, key=None):
    """Append one attributed control.intervention; the task state itself is never touched."""
    command = key_field('.'.join(command.split()) if isinstance(command, str) else command)  # 'delivery start' -> 'delivery.start'
    key_field(channel)
    who = (_exact(actor) or _mapped(actor) or 'unknown') if actor else _resolve()
    if details is not None:
        if not isinstance(details, dict): raise LedgerError('Intervention details must be an object.')
        if len(canonical(details)) > 4000: details = {'truncated': True, 'sha256': content_hash(details)}
    runtime = runtime_revision()['tree']
    with ledger.transaction(write=True) as conn:
        ledger._task(conn, task_id)
        if key is not None:
            key_field(key)
            old = conn.execute("SELECT payload FROM events WHERE task_id=? AND kind='control.intervention' AND json_extract(payload,'$.key')=?",
                               (task_id, key)).fetchone()
            if old: return json.loads(old['payload'])
        row = conn.execute("SELECT seq FROM events WHERE task_id=? AND kind='workflow.checkpoint' ORDER BY seq DESC LIMIT 1", (task_id,)).fetchone()
        payload = {'actor': who, 'channel': channel, 'command': command, 'reason': None if reason is None else str(reason)[:500],
                   'details': details, 'runtime': runtime, 'checkpoint_seq': row['seq'] if row else None}
        if key is not None: payload['key'] = key
        ledger._event(conn, task_id, 'control.intervention', payload)
        return payload


def note(ledger, task_id, command, **kwargs):
    """Best-effort record after a command already succeeded; never turns success into failure."""
    try:
        return record(ledger, task_id, command, **kwargs)
    except (ValueError, OSError, sqlite3.Error) as error:
        return {'recorded': False, 'error': str(error)[:300]}


TASK = re.compile(r'TASK-[0-9a-f]{32}\Z')
SCOPES = ('project', 'conversation', 'solution', 'consultation', 'delegation', 'trial', 'desktop')
PROJECT_DDL = '''CREATE TABLE IF NOT EXISTS project_interventions(seq INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL, scope TEXT NOT NULL, scope_id TEXT, key TEXT, payload TEXT NOT NULL, created_at TEXT NOT NULL,
    UNIQUE(project_id, key))'''


def record_project(ledger, command, scope='project', scope_id=None, *, actor=None, channel='cli', reason=None, details=None, key=None):
    """A mutating command with no task (conversation, solution, delegation, trial): the same attributed record, project-scoped."""
    command = key_field('.'.join(command.split()) if isinstance(command, str) else command)
    key_field(channel)
    if scope not in SCOPES: raise LedgerError('Unknown intervention scope.')
    if scope_id is not None: key_field(scope_id)
    if key is not None: key_field(key)
    who = (_exact(actor) or _mapped(actor) or 'unknown') if actor else _resolve()
    if details is not None:
        if not isinstance(details, dict): raise LedgerError('Intervention details must be an object.')
        if len(canonical(details)) > 4000: details = {'truncated': True, 'sha256': content_hash(details)}
    payload = {'actor': who, 'channel': channel, 'command': command, 'scope': scope, 'scope_id': scope_id,
               'reason': None if reason is None else str(reason)[:500], 'details': details, 'runtime': runtime_revision()['tree']}
    if key is not None: payload['key'] = key
    from .ledger import utcnow
    with ledger.transaction(write=True) as conn:
        conn.execute(PROJECT_DDL)
        if key is not None:
            old = conn.execute('SELECT payload FROM project_interventions WHERE project_id=? AND key=?', (ledger.project_id, key)).fetchone()
            if old: return json.loads(old['payload'])
        conn.execute('INSERT INTO project_interventions(project_id,scope,scope_id,key,payload,created_at) VALUES(?,?,?,?,?,?)',
                     (ledger.project_id, scope, scope_id, key, canonical(payload), utcnow()))
        return payload


def project_records(ledger, scope=None, scope_id=None):
    with ledger.transaction() as conn:
        if conn is None or not conn.execute("SELECT 1 FROM sqlite_master WHERE name='project_interventions'").fetchone(): return []
        query, params = 'SELECT * FROM project_interventions WHERE project_id=?', [ledger.project_id]
        if scope: query += ' AND scope=?'; params.append(scope)
        if scope_id: query += ' AND scope_id=?'; params.append(scope_id)
        return [dict(json.loads(r['payload']), seq=r['seq'], at=r['created_at']) for r in conn.execute(query + ' ORDER BY seq', params)]


def keyed(command, identity):
    """Replay key for one command identity (a build key, a note request id), within the 128-character key limit."""
    key = f'{command}:{identity}'
    return key if len(key) <= 128 else f'{command}:sha256:{hashlib.sha256(str(identity).encode()).hexdigest()}'


def cli_note(ledger, command, tasks=(), *, scope=('project', None), **kwargs):
    """Record one successful mutating CLI command on each affected task, else once at its project scope.
    Attribution is ONECREW_ACTOR ('unknown' when unset). Never turns the command's success into a failure."""
    tasks = [t for t in dict.fromkeys(tasks) if isinstance(t, str) and TASK.fullmatch(t)]
    try:
        if tasks: return [record(ledger, task, command, **kwargs) for task in tasks]
        return [record_project(ledger, command, scope[0], scope[1], **kwargs)]
    except (ValueError, OSError, sqlite3.Error) as error:
        import sys
        print('Intervention not recorded: ' + str(error)[:300], file=sys.stderr)
        return [{'recorded': False, 'error': str(error)[:300]}]


def summary(ledger, task_ids):
    """Interventions in ledger order, including runtime changes between runner starts."""
    tasks = list(dict.fromkeys(task_ids))
    if not tasks: return []
    with ledger.transaction() as conn:
        if conn is None: return []
        for task in tasks: ledger._task(conn, task)
        marks = ','.join('?' for _ in tasks)
        rows = conn.execute(f"SELECT * FROM events WHERE task_id IN ({marks}) AND kind IN "
                            "('control.intervention','eval.assistance','runner.started') ORDER BY seq", tasks).fetchall()
    result, trees = [], {}
    for row in rows:
        value = json.loads(row['payload'])
        item = {'task': row['task_id'], 'seq': row['seq'], 'at': row['created_at']}
        if row['kind'] == 'runner.started':
            runtime = value.get('runtime')
            current = runtime.get('tree') if isinstance(runtime, dict) else None
            if not current: continue  # Legacy start: change cannot be proven either way.
            previous, trees[row['task_id']] = trees.get(row['task_id']), current
            if previous and previous != current:
                result.append(item | {'actor': 'unknown', 'channel': 'runtime', 'command': 'runtime.changed',
                                      'reason': f'runtime {previous[:12]} -> {current[:12]}'})
        elif row['kind'] == 'eval.assistance':
            result.append(item | {'actor': value.get('actor') or 'unknown', 'channel': 'eval', 'command': 'eval.assistance',
                                  'reason': value.get('reason'), 'category': value.get('category')})
        else:
            result.append(item | {k: value.get(k) for k in ('actor', 'channel', 'command', 'reason')})
    return result
