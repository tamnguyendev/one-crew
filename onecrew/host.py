"""OneCrew host (GX-GAP-04, 13/10/2026): runs dispatched jobs outside any chat or entry process.

An entry only writes a durable dispatch request (a ledger event plus a queue file in the state root). The host - one per
user, started by the Windows Task Scheduler at logon with the user's least privilege, never a child of a chat - admits
the request, launches the coordinator runner as its own child, supervises it and restarts it within a bound when it
dies (the checkpoint, intents and action records make that safe). It honours cancel, pause and pending questions,
never revives a runner that died with a reboot (that needs an explicit resume), and leaves one Windows notice to the
runner's existing checkpoint hook. It never calls a model, answers a question, extends a budget or widens a grant.

Installing the Task Scheduler entry changes the user's machine configuration, so it is an explicit user decision
(`host install`); without a host, `job start` says that the run is bound to the entry instead of pretending."""
import argparse
import contextlib
import datetime as dt
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import time
import uuid

from .ledger import Ledger, LedgerError, canonical, utcnow
from .snapshots import durable_write

TASK_NAME = r'OneCrew\Host'
HEARTBEAT = 30          # seconds after which a host lease without a heartbeat is not trusted
BACKOFF = (10, 60, 300)  # seconds before restart 1, 2, 3 within the rolling hour (same bound as the keeper)
WINDOW = 3600
CANCEL_GRACE = 120      # a cancelled task whose runner does not stop by itself is stopped after this many seconds
ADMIT_BACKOFF = (2, 5, 10, 20, 40)  # seconds between admission attempts after a transient ledger error (R3)
NORMAL_PRIORITY = 0x20  # NORMAL_PRIORITY_CLASS: runners do not inherit the Task Scheduler's below-normal class (R4)
LAUNCH_GRACE = 120      # a launch recorded as in progress (host stopped between record and runner identity) blocks relaunch this long
ACTIVE = ('running', 'waiting_operation')
TERMINAL = ('completed', 'cancelled', 'failed')


def home():
    """Outside AppData on purpose: acceptance run N1-r1 (13/10/2026) found that writes of a packaged (MSIX) entry such as
    Claude Desktop under %LOCALAPPDATA% are redirected into the package's private LocalCache, so the host never saw the
    registry the entry wrote. The user profile root is not virtualized."""
    configured = os.environ.get('ONECREW_HOST_HOME')
    base = Path(configured) if configured else Path.home() / '.onecrew' / 'host'
    base.mkdir(parents=True, exist_ok=True)
    return base


class _Unreadable(OSError):
    """A host file that exists but cannot be read right now (another process holds it open, an I/O error). It is neither
    missing nor malformed, and nothing it describes may be dropped or decided on because of it."""


def _load(path):
    """('ok', value) | ('missing', None) | ('corrupt', error) | ('unreadable', error).
    P4-A (Codex deep review P3, reproduced with a real Windows lock): the former reader turned every OSError into None, and
    the scan then moved a valid dispatch request that was only locked for a moment out of the queue for good."""
    try: data = Path(path).read_bytes()
    except FileNotFoundError: return 'missing', None
    except OSError as error: return 'unreadable', error
    try: return 'ok', json.loads(data.decode('utf-8'))
    except ValueError as error: return 'corrupt', error  # includes UnicodeDecodeError


def _read(path, default=None):
    """Missing or malformed -> default. A file that exists but cannot be read now raises _Unreadable: callers decide later,
    they never treat it as absent."""
    status, value = _load(path)
    if status == 'unreadable': raise _Unreadable(f'{Path(path).name} cannot be read right now: {value}')
    return value if status == 'ok' else default


def _read_patiently(path, default=None, attempts=4, pause=.05):
    """For readers that must answer now (the lease seen by an entry): a few short retries, then _Unreadable."""
    for attempt in range(attempts):
        try: return _read(path, default)
        except _Unreadable:
            if attempt == attempts - 1: raise
            time.sleep(pause * (attempt + 1))


def _write(path, value):
    durable_write(Path(path), canonical(value).encode('utf-8'))


def _when(text):
    value = dt.datetime.fromisoformat(text)
    return value if value.tzinfo else value.replace(tzinfo=dt.timezone.utc)


# --- lease -----------------------------------------------------------------------------------------------------------

def lease(base=None):
    """The live host's lease, or None (missing, stale heartbeat or dead process)."""
    from .supervisor import probe
    try: record = _read_patiently((base or home()) / 'lease.json')
    except _Unreadable: return None  # cannot prove a live host right now; the entry says so instead of queueing blindly
    if not record or record.get('stopped_at'): return None
    try:
        if (dt.datetime.now(dt.timezone.utc) - _when(record['heartbeat'])).total_seconds() > HEARTBEAT: return None
    except (KeyError, ValueError): return None
    return record if probe(record.get('identity')) == 'alive' else None


# --- entry side: dispatch ----------------------------------------------------------------------------------------------

def served(state_root, base=None, record=None):
    """True only when the live host itself reports scanning this state root: the entry's own copy of the registry
    proves nothing if the entry's writes are invisible to the host."""
    record = record or lease(base)
    return bool(record) and str(Path(state_root).resolve()) in (record.get('roots_seen') or {})


def register(state_root, base=None):
    """The user's choice of state roots this host serves (host install/register); a test or scratch root is never served."""
    base = base or home(); path = base / 'roots.json'
    status, roots = _load(path)
    if status == 'unreadable': raise _Unreadable(f'roots.json cannot be read right now ({roots}); nothing was changed, try again')
    if status == 'corrupt' or (status == 'ok' and not isinstance((roots or {}).get('roots'), list)):
        raise LedgerError(f'{path} is malformed; it was left as it is (fix or remove it, then register again)')
    roots = roots if status == 'ok' else {'roots': []}
    resolved = str(Path(state_root).resolve())
    if resolved not in [r['state_root'] for r in roots['roots']]:
        roots['roots'].append({'state_root': resolved, 'added_at': utcnow()}); _write(path, roots)
    return resolved


def queue_dir(state_root):
    path = Path(state_root) / 'host' / 'queue'; path.mkdir(parents=True, exist_ok=True)
    return path


def dispatch(ledger, task_id, initiator=None, wait=15, base=None):
    """Ask the live host to run this task. Returns the admission (or 'queued' if the host has not admitted yet)."""
    from .interventions import actor
    base = base or home()
    record = lease(base)
    if not record: raise LedgerError('No OneCrew host is running.')
    if not served(ledger.state_root, base, record): raise LedgerError('The OneCrew host does not serve this state root (host register).')
    request = {'id': 'HD-' + uuid.uuid4().hex, 'task': task_id, 'project': str(Path(ledger.project).resolve()),
               'state_root': str(Path(ledger.state_root).resolve()), 'runtime': str(Path(__file__).resolve().parents[1]),
               'initiator': initiator or actor(), 'at': utcnow()}
    with ledger.transaction(write=True) as conn:
        ledger._event(conn, task_id, 'host.dispatch', request)
    _write(queue_dir(ledger.state_root) / (request['id'] + '.json'), request)
    queued = queue_dir(ledger.state_root) / (request['id'] + '.json')
    deadline = time.monotonic() + wait
    while True:
        with ledger.transaction() as conn:
            row = conn.execute("SELECT kind,payload FROM events WHERE task_id=? AND kind IN ('host.admitted','host.refused') "
                               "AND json_extract(payload,'$.request')=? ORDER BY seq DESC LIMIT 1", (task_id, request['id'])).fetchone()
        if row: return dict(json.loads(row['payload']), status='admitted' if row['kind'] == 'host.admitted' else 'refused', via='host')
        if time.monotonic() >= deadline: break
        time.sleep(.2)
    scanned = ((lease(base) or {}).get('roots_seen') or {}).get(str(Path(ledger.state_root).resolve()))
    try: retrying = _read(_retry_path(ledger.state_root, request['id']))
    except _Unreadable as error:  # the host is writing its retry record right now: it has seen the request
        retrying = {'count': '?', 'last_error': str(error)[:200]}
    if retrying:  # the host saw the request and is retrying its admission after a transient error (R3)
        return {'status': 'queued', 'request': request['id'], 'via': 'host', 'note': 'The host is retrying the admission '
                f"(attempt {retrying.get('count')}: {retrying.get('last_error')}); the entry may close."}
    if wait and scanned and scanned > request['at'] and queued.exists():
        # The host scanned this root after the request was written and still did not see it: never leave a request that
        # might be admitted much later, unseen by anyone.
        queued.unlink(missing_ok=True)
        with ledger.transaction(write=True) as conn:
            ledger._event(conn, task_id, 'host.unseen', {'request': request['id'], 'host_scan': scanned})
        raise LedgerError('The OneCrew host scans this state root but cannot see the request this entry wrote (the entry\'s '
                          'writes are probably virtualized, e.g. a packaged app writing under AppData). Request withdrawn.')
    return {'status': 'queued', 'request': request['id'], 'via': 'host',
            'note': 'The host has the durable request and will admit it; the entry may close.'}


# --- host side ---------------------------------------------------------------------------------------------------------

def _launch(request, initiator='host'):
    """The runner, as a child of the host (never of an entry). Logs go to the state root like runner.start."""
    from .supervisor import identity, native_python
    runtime = Path(request['runtime'])
    if not (runtime / 'onecrew' / 'runner.py').is_file(): raise LedgerError('Dispatch runtime is not a OneCrew checkout: ' + str(runtime))
    directory = Path(request['state_root']) / 'runners' / uuid.uuid4().hex; directory.mkdir(parents=True)
    argv = [native_python(), '-X', 'utf8', '-m', 'onecrew.runner', '--project', request['project'],
            '--state-root', request['state_root'], request['task']]
    env = dict(os.environ, ONECREW_RUNNER_INITIATOR=initiator, ONECREW_ACTOR='onecrew')
    env.pop('PYTHONPATH', None)  # the runner imports exactly the dispatched runtime
    with (directory / 'stdout.txt').open('wb') as out, (directory / 'stderr.txt').open('wb') as err:
        process = subprocess.Popen(argv, cwd=runtime, stdin=subprocess.DEVNULL, stdout=out, stderr=err, close_fds=True, env=env,
                                   creationflags=0x200 | 0x08000000 | NORMAL_PRIORITY)  # new group, no window, Normal priority
    try: started = identity(process.pid)
    except (OSError, ValueError):  # the process exists: never report this launch as failed
        started = {'pid': process.pid, 'unverified': True}
    return {'identity': started, 'logs': str(directory), 'runtime': str(runtime)}


def _boot():
    from .keeper import _boot as boot
    return boot()


def _task_view(ledger, task_id):
    """Phase, execution status, cancel flag, pending questions and deadline from one read transaction."""
    with ledger.transaction() as conn:
        execution = conn.execute('SELECT status,cancel_requested FROM executions WHERE task_id=?', (task_id,)).fetchone()
        checkpoint = conn.execute("SELECT payload FROM events WHERE task_id=? AND kind='workflow.checkpoint' ORDER BY seq DESC LIMIT 1",
                                  (task_id,)).fetchone()
        pending = conn.execute("SELECT COUNT(*) FROM requests WHERE task_id=? AND state='pending'", (task_id,)).fetchone()[0]
    phase = json.loads(checkpoint['payload']).get('phase') if checkpoint else None
    return {'phase': phase, 'status': execution['status'] if execution else None,
            'cancel': bool(execution and execution['cancel_requested']), 'pending': pending}


def _event(ledger, task_id, kind, payload):
    with ledger.transaction(write=True) as conn:
        ledger._event(conn, task_id, kind, payload)


def _block(ledger, task_id, message, kind):
    """One blocker the user can act on; the runner's checkpoint hook shows it once in the Windows channel."""
    from .runner import workflow_for
    from .workflow import task_lock
    workflow = workflow_for(ledger, task_id)
    with task_lock(ledger, task_id):
        seq, state = workflow.state(task_id)
        if state is None or state['phase'] in TERMINAL or state['phase'] == 'blocked': return False
        state.setdefault('resume_phase', state['phase'])
        state.update(phase='blocked', message=message, recovery={'kind': kind, 'automatic_retry': False})
        workflow.persist(task_id, seq, state)
    return True


def _launch_record(state_root, task):
    return Path(state_root) / 'host' / 'launch' / (task + '.json')


def _launch_state(state_root, task):
    """The durable launch record. Unreadable right now -> _Unreadable (the caller decides again later, never launches on it).
    Malformed -> treated as a launch in progress since the file was last written (LAUNCH_GRACE), never as 'nothing'."""
    path = _launch_record(state_root, task)
    status, record = _load(path)
    if status == 'unreadable': raise _Unreadable(f'launch record of {task} cannot be read right now: {record}')
    if status == 'missing': return {}
    if status == 'corrupt' or not isinstance(record, dict) or not isinstance(record.get('at'), str):
        try: at = dt.datetime.fromtimestamp(path.stat().st_mtime, dt.timezone.utc).isoformat()
        except OSError: at = utcnow()
        return {'task': task, 'state': 'launching', 'at': at, 'malformed': True}
    return record


def _runner_lock_held(ledger, task):
    """The runner holds its task lock for its whole life: a held lock is an owner even if nothing else says so."""
    import msvcrt
    from .ledger import key_field
    path = Path(ledger.state_root) / 'locks' / (key_field(task + '.runner') + '.lock')
    if not path.exists(): return False
    try:
        with path.open('a+b') as stream:
            stream.seek(0)
            try: msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError: return True
            stream.seek(0); msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            return False
    except OSError:
        return False


def _owner(ledger, task, entry, now):
    """Who owns this task's runner right now, or None. Codex review 2 (13/10/2026): two requests and a retry admitted
    before runner.started was written launched three runners. Checked before every launch, admission or restart."""
    from . import runner
    from .supervisor import probe
    current = runner.status(ledger, task)
    if current['status'] in ('alive', 'unknown'): return {'kind': 'registered runner', 'identity': current.get('identity')}
    record = _launch_state(ledger.state_root, task)  # _Unreadable propagates: no launch is decided on an unread record
    for identity in ((entry or {}).get('runner'), record.get('identity')):
        if identity and probe(identity) == 'alive': return {'kind': 'runner launched by the host, not registered yet', 'identity': identity}
    if (record.get('state') == 'launching' or (record.get('identity') or {}).get('unverified')) and \
            (now - _when(record['at'])).total_seconds() < LAUNCH_GRACE:
        return {'kind': 'a launch is in progress (recorded, runner identity not yet known)', 'identity': None}
    if _runner_lock_held(ledger, task): return {'kind': 'the runner task lock is held', 'identity': None}
    return None


def _start(ledger, request, launch, now, cause):
    """Durable launch: recorded BEFORE the process starts, its identity recorded right after. A launch that fails is
    recorded as failed, so it does not hold off the next request for LAUNCH_GRACE as if it were still starting."""
    path = _launch_record(ledger.state_root, request['task']); path.parent.mkdir(parents=True, exist_ok=True)
    base = {'task': request['task'], 'request': request['id'], 'cause': cause, 'at': now.isoformat()}
    try: _write(path, dict(base, state='launching'))
    except OSError as error:  # P4-A: nothing was started; a record that cannot be written now is no launch failure
        raise _Unreadable(f'launch record of {request["task"]} cannot be written right now: {error}') from error
    try:
        started = launch(request)
    except Exception as error:  # a handled failure; a host killed here leaves 'launching', which LAUNCH_GRACE covers
        try: _write(path, dict(base, state='failed', error=str(error)[:300]))
        except OSError: pass  # 'launching' stays; LAUNCH_GRACE then lets the next attempt decide
        raise _LaunchError(str(error)[:300]) from error  # never mistaken for a transient file error, whatever its type
    try:
        _write(path, dict(base, state='launched', identity=started['identity'], logs=started.get('logs')))
    except OSError as error:  # the runner runs; 'launching' stays recorded, so no second launch within LAUNCH_GRACE
        raise _Unrecorded('runner started, launch record not updated: ' + str(error)[:200]) from error
    return started


class _Busy(LedgerError):
    """Another process is deciding admission for this task right now."""


class _LaunchFailed(LedgerError):
    """The runner could not be started (before any process existed); the task is blocked with the reason."""


class _Unrecorded(Exception):
    """A runner was started but its outcome could not be recorded yet: never relaunch, record it on a later attempt."""


class _Malformed(LedgerError):
    """A queue file that is damaged or foreign and has no copy in the ledger: the only request ended without a decision."""


class _LaunchError(Exception):
    """Starting the runner process itself failed (no process exists). A launch failure, never a transient file error."""


def _transient(error):
    """A ledger or file the host could not use for a moment: the request stays queued and is tried again (R3). P4-A: a ledger
    another process holds without sharing reports 'unable to open database file' (SQLITE_CANTOPEN) or an I/O error, and a host
    file held by a reader cannot be replaced (WinError 5 / errno 13): all of them pass, so none may end a request."""
    if isinstance(error, (_Unrecorded, _Unreadable)): return True
    if isinstance(error, sqlite3.OperationalError):
        return any(word in str(error).lower() for word in ('locked', 'busy', 'unable to open', 'disk i/o'))
    return isinstance(error, OSError) and (getattr(error, 'winerror', None) in (5, 32, 33) or error.errno == 13)


@contextlib.contextmanager
def _admission(state_root, task, wait=15.0):
    """One admission decision per task at a time, across processes (two hosts serving one state root, or a host and a
    retry): the owner check and the launch record happen under this lock. LedgerError when it cannot be had in time."""
    import msvcrt
    path = _launch_record(state_root, task).with_suffix('.lock'); path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a+b') as stream:
        stream.seek(0)
        deadline = time.monotonic() + wait
        while True:
            try: msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1); break
            except OSError:
                if time.monotonic() >= deadline: raise _Busy('another admission of this task is in progress')
                time.sleep(0.05)
        try: yield
        finally:
            stream.seek(0); msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)


def _admit(request, launch, now, entry=None):
    ledger = Ledger(request['project'], request['state_root'])
    view = _task_view(ledger, request['task'])
    if view['phase'] is None or view['phase'] in TERMINAL or view['cancel']:
        payload = {'request': request['id'], 'reason': 'task is terminal, cancelled or not enabled', 'phase': view['phase']}
        _event(ledger, request['task'], 'host.refused', payload); return dict(payload, action='refused')
    try:
        with _admission(ledger.state_root, request['task']):
            owner = _owner(ledger, request['task'], entry, now)
            if owner:
                payload = {'request': request['id'], 'runner': owner['identity'], 'note': 'not launched: ' + owner['kind'], 'launched': False}
            else:
                try:
                    started = _start(ledger, request, launch, now, 'dispatch')
                except (_Unrecorded, _Unreadable):
                    raise  # transient: the request stays queued and is decided again (nothing or an already recorded runner)
                except Exception as error:
                    _launch_failed(ledger, request, now, error)
                    raise _LaunchFailed(str(error)[:300]) from error
                payload = dict({'request': request['id'], 'launched': True}, **started)
    except _Busy as error:  # another process is deciding for this task right now; that decision stands (a failed launch is not this)
        payload = {'request': request['id'], 'runner': None, 'note': 'not launched: ' + str(error), 'launched': False}
    # A transient ledger error here (after a launch) keeps the request queued; the next attempt finds the runner as owner.
    _event(ledger, request['task'], 'host.admitted', payload)
    return dict(payload, action='admitted')


def _launch_failed(ledger, request, now, error):
    """The entry was told the host will admit the task and may already be closed: a launch the host cannot make must not
    vanish. The task is blocked with the reason, which reaches the user once. If the ledger is busy right now, that error is
    raised instead, so the request stays queued and the launch is decided again (the record says no process exists)."""
    reason = str(error)[:300]
    _event(ledger, request['task'], 'host.launch_failed', {'request': request['id'], 'error': reason, 'at': now.isoformat()})
    try:
        _block(ledger, request['task'], 'The OneCrew host could not start this task: ' + reason +
               '. Fix the cause, then resume it (job resume).', 'host_launch')
    except LedgerError:
        pass  # the task is busy elsewhere; the event above still records why nothing was launched


def _retry_path(root, request_id):
    return Path(root) / 'host' / 'retry' / (request_id + '.json')


def _defer(root, path, request, error, now):
    """Keep a request whose admission met a transient error; after the last attempt, end it with a reason. Returns
    (keep_in_queue, action)."""
    retry_path = _retry_path(root, path.stem); retry = _read(retry_path) or {}
    count = retry.get('count', 0) + 1; first = retry.get('first_at', now.isoformat())
    reason = type(error).__name__ + ': ' + str(error)[:200]
    task = request.get('task') if request else None
    if count <= len(ADMIT_BACKOFF):
        retry_path.parent.mkdir(parents=True, exist_ok=True)
        _write(retry_path, {'request': path.stem, 'task': task, 'count': count, 'first_at': first, 'last_error': reason,
                            'next_at': (now + dt.timedelta(seconds=ADMIT_BACKOFF[count - 1])).isoformat()})
        return True, {'request': path.stem, 'task': task, 'action': 'retrying', 'attempt': count, 'error': reason}
    if not request:
        # Neither the queue file nor the ledger could be read, so the task is unknown and cannot be blocked: the request is
        # kept and looked at again every few minutes (host.log and the lease carry the reason). Nothing unread is dropped.
        _write(retry_path, dict(retry, count=count, last_error=reason, next_at=(now + dt.timedelta(seconds=300)).isoformat()))
        return True, {'request': path.stem, 'task': None, 'action': 'unreadable', 'attempt': count, 'error': reason}
    try: record = _launch_state(root, request['task'])
    except _Unreadable:  # P4-A: an unread launch record never decides anything; look again in a minute
        _write(retry_path, dict(retry, count=count, last_error=reason, next_at=(now + dt.timedelta(seconds=60)).isoformat()))
        return True, {'request': request['id'], 'task': request['task'], 'action': 'retrying', 'attempt': count, 'error': reason}
    if record.get('state') in ('launching', 'launched') and record.get('at', '') >= first:
        # A runner was started for this request: never end it as failed. Its outcome is recorded once the ledger is free.
        _write(retry_path, dict(retry, count=count, last_error=reason, next_at=(now + dt.timedelta(seconds=60)).isoformat()))
        return True, {'request': request['id'], 'task': request['task'], 'action': 'recording_outcome', 'error': reason}
    message = (f'The OneCrew host could not admit this task: {reason} through {count} attempts since {first}. Nothing was '
               'started. Resume it (job resume) once the cause is gone.')
    try:
        ledger = Ledger(request['project'], request['state_root'])
        _event(ledger, request['task'], 'host.admission_failed', {'request': request['id'], 'attempts': count, 'first_at': first,
                                                                  'error': reason, 'at': now.isoformat()})
        _block(ledger, request['task'], message, 'host_admission')
    except Exception as again:
        if not _transient(again): raise
        _write(retry_path, dict(retry, count=count, last_error=reason, next_at=(now + dt.timedelta(seconds=60)).isoformat()))
        return True, {'request': request['id'], 'task': request['task'], 'action': 'retrying', 'attempt': count, 'error': reason}
    return False, {'request': request['id'], 'task': request['task'], 'action': 'failed', 'blocked': True, 'error': reason}


def _supervise(entry, now, launch, boot):
    """One supervised task: returns (keep, action or None)."""
    from . import runner
    from .supervisor import probe
    ledger = Ledger(entry['project'], entry['state_root']); task = entry['task']
    view = _task_view(ledger, task)
    # Launched by this host and alive but not registered yet (acceptance run N1-r2: 38 s under load), a launch in progress
    # or a held runner lock all count as an owner: a second runner would only lose the task lock; it is not a restart.
    owner = _owner(ledger, task, entry, now)
    current = {'status': 'alive', 'identity': owner['identity'], 'owner': owner['kind']} if owner else {'status': 'stopped'}
    if owner and owner['identity'] and owner['identity'] != entry.get('runner'):
        entry['runner'] = owner['identity']  # the reboot rule below needs the identity of the runner that actually owns the task
    if view['phase'] in TERMINAL or view['phase'] is None:
        return False, {'task': task, 'action': 'released', 'phase': view['phase']}
    if view['cancel']:
        if current['status'] == 'alive':
            since = entry.setdefault('cancel_seen', now.isoformat())
            if (now - _when(since)).total_seconds() >= CANCEL_GRACE and current.get('identity'):
                from .work_tools import _terminate
                stopped = _terminate(current['identity'])
                _event(ledger, task, 'host.cancel_enforced', {'runner': current['identity'], 'stopped': stopped, 'at': now.isoformat()})
                return False, {'task': task, 'action': 'cancel_enforced'}
            return True, None
        return False, {'task': task, 'action': 'released', 'reason': 'cancelled'}
    if current['status'] in ('alive', 'unknown'):
        entry.pop('dead_since', None); return True, None
    # The runner is gone and the task is not finished.
    if view['phase'] == 'blocked' or view['status'] == 'paused' or view['pending'] or view['phase'] == 'waiting':
        return False, {'task': task, 'action': 'released', 'reason': 'waiting for the user (blocked, paused or a question)'}
    created = (entry.get('runner') or {}).get('created')
    if boot and isinstance(created, int) and created < boot:
        _block(ledger, task, 'The coordinator stopped with a Windows restart; continuing needs an explicit resume (job resume).',
               'coordinator_reboot')
        return False, {'task': task, 'action': 'reboot'}
    restarts = [r for r in entry.get('restarts', []) if (now - _when(r)).total_seconds() < WINDOW]
    if len(restarts) >= len(BACKOFF):
        detail = f'Coordinator runner died {len(restarts)} times within {WINDOW // 60} minutes; automatic restarts exhausted.'
        if entry.get('last_launch_error'): detail += ' The last restart could not start the runner: ' + entry['last_launch_error'] + '.'
        _event(ledger, task, 'host.restart_exhausted', {'restarts': restarts, 'at': now.isoformat()})
        _block(ledger, task, detail + ' Inspect the runner logs, then resume with job resume.', 'coordinator')
        return False, {'task': task, 'action': 'exhausted'}
    since = entry.setdefault('dead_since', now.isoformat())
    if (now - _when(restarts[-1] if restarts else since)).total_seconds() < BACKOFF[len(restarts)]:
        return True, {'task': task, 'action': 'backoff'}
    try:
        with _admission(ledger.state_root, task):
            if _owner(ledger, task, entry, now): return True, None  # someone else started it meanwhile
            started = _start(ledger, dict(entry, id='restart-' + uuid.uuid4().hex[:8]), launch, now, 'restart')
    except _Busy:
        return True, None
    except _Unrecorded:
        # The runner started; only its launch record is behind. It registers itself, and the record keeps a second launch out.
        restarts.append(now.isoformat()); entry['restarts'] = restarts; entry.pop('dead_since', None)
        return True, {'task': task, 'action': 'restarted', 'note': 'launch record not updated yet'}
    except Exception as error:
        if _transient(error):  # the ledger was busy while deciding: nothing was launched, decide again on the next scan
            return True, {'task': task, 'action': 'retrying', 'error': str(error)[:300]}
        # A restart that could not launch counts as an attempt: backoff and the exhaustion rule apply to it as well.
        restarts.append(now.isoformat()); entry['restarts'] = restarts; entry['last_launch_error'] = str(error)[:300]
        _event(ledger, task, 'host.restart_failed', {'error': str(error)[:300], 'restart_count': len(restarts), 'at': now.isoformat()})
        return True, {'task': task, 'action': 'restart_failed', 'error': str(error)[:300]}
    restarts.append(now.isoformat())
    entry.update(restarts=restarts, runner=started['identity']); entry.pop('dead_since', None); entry.pop('last_launch_error', None)
    _event(ledger, task, 'host.restarted', {'runner': started['identity'], 'logs': started['logs'], 'restart_count': len(restarts),
                                            'at': now.isoformat(), 'cause': 'runner_dead'})
    return True, {'task': task, 'action': 'restarted'}


DECISIONS = ('host.admitted', 'host.refused', 'host.admission_failed', 'host.launch_failed')


def _valid(request, root, request_id):
    return (isinstance(request, dict) and request.get('id') == request_id
            and all(isinstance(request.get(k), str) and request.get(k) for k in ('task', 'project', 'state_root', 'runtime'))
            and Path(request['state_root']).resolve() == Path(root).resolve())


def _dispatched(root, request_id):
    """The request exactly as the entry recorded it in the ledger (event host.dispatch, written BEFORE the queue file): the
    durable copy the host falls back to when the queue file is unreadable or damaged (P4-A). None when the ledger has none."""
    path = Path(root) / 'ledger.sqlite3'
    if not path.is_file(): return None
    conn = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=10)
    try:
        row = conn.execute("SELECT payload FROM events WHERE kind='host.dispatch' AND json_extract(payload,'$.id')=? "
                           'ORDER BY seq LIMIT 1', (request_id,)).fetchone()
    finally: conn.close()
    return json.loads(row[0]) if row else None


def _decision(ledger, task, request_id):
    """The decision already recorded for this request, if any: a request is decided once, across host restarts and whether
    its queue file could be moved away or not."""
    with ledger.transaction() as conn:
        row = conn.execute(f"SELECT kind FROM events WHERE task_id=? AND kind IN ({','.join('?' * len(DECISIONS))}) "
                           "AND json_extract(payload,'$.request')=? ORDER BY seq DESC LIMIT 1", (task, *DECISIONS, request_id)).fetchone()
    return row['kind'] if row else None


def _set_aside(root, path, now, to='done', reason=None):
    """Move a decided (or rejected) request out of the queue. A file another process still holds stays where it is: the ledger
    has the decision, so the next scans only try to move it (quietly, every 30 s)."""
    target = root / 'host' / to; target.mkdir(parents=True, exist_ok=True)
    try: os.replace(path, target / path.name)
    except FileNotFoundError: pass  # another host serving this root took the request; its decision stands
    except OSError:
        try:
            retry_path = _retry_path(root, path.stem); retry_path.parent.mkdir(parents=True, exist_ok=True)
            _write(retry_path, {'request': path.stem, 'decided': to == 'done', 'next_at': (now + dt.timedelta(seconds=30)).isoformat()})
        except OSError: pass
        return False
    if reason is not None:
        try: _write(target / (path.stem + '.reason.json'), dict(reason, at=now.isoformat()))
        except OSError: pass
    _retry_path(root, path.stem).unlink(missing_ok=True)
    return True


def _ledger_rows(root, sql, args):
    path = Path(root) / 'ledger.sqlite3'
    if not path.is_file(): return []
    conn = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=10)
    try: return conn.execute(sql, args).fetchall()
    finally: conn.close()


def _rebuilt_entry(root, record, now):
    """A supervision entry from a launch record and the ledger: the request it came from (or, for a restart, the task's latest
    dispatch) and the restarts within the window, so the restart bound is not reset."""
    task = record.get('task')
    request = _dispatched(root, record['request']) if str(record.get('request', '')).startswith('HD-') else None
    if request is None:
        rows = _ledger_rows(root, "SELECT payload FROM events WHERE task_id=? AND kind='host.dispatch' ORDER BY seq DESC LIMIT 1", (task,))
        request = json.loads(rows[0][0]) if rows else None
    if not task or not request: return None
    restarts = []
    for (payload,) in _ledger_rows(root, "SELECT payload FROM events WHERE task_id=? AND kind IN ('host.restarted','host.restart_failed')",
                                   (task,)):
        at = json.loads(payload).get('at')
        if at and (now - _when(at)).total_seconds() < WINDOW: restarts.append(at)
    return {'task': task, 'project': request['project'], 'state_root': request['state_root'], 'runtime': request['runtime'],
            'admitted_at': record.get('at'), 'runner': record.get('identity'), 'restarts': restarts, 'rebuilt': True}


def _released_since_launch(root, record):
    """Why the host may have released this launch's runner, from durable evidence only, or None when it cannot have.
    The host releases a task only when its runner is gone and the task is terminal, cancelled, blocked, waiting, paused or has
    a pending question. So: None when a runner of this launch still runs (terminal and cancelled tasks are then released by
    _supervise), or when the ledger records the launch (a host.admitted of its request, or the host.restarted at its time) and,
    from the moment its runner may have been gone (its runner.stopped, else the launch), the task was never in such a state —
    neither the state in force at that moment (latest checkpoint) nor any later one (checkpoint, question created or answered,
    cancel). A pause is never reconstructed from the ledger (an unpause writes no event), so any pause counts.
    P4b-R3 (Codex review of P4b): for launches recorded before the supervision file had a reconciliation map."""
    from .supervisor import probe
    task, request = record['task'], str(record.get('request') or '')
    if request.startswith('HD-'):
        launch = _ledger_rows(root, "SELECT seq, payload FROM events WHERE task_id=? AND kind='host.admitted' "
                                    "AND json_extract(payload,'$.request')=? ORDER BY seq", (task, request))
    else:
        launch = _ledger_rows(root, "SELECT seq, payload FROM events WHERE task_id=? AND kind='host.restarted' "
                                    "AND json_extract(payload,'$.at')=? ORDER BY seq", (task, record.get('at')))
    runners = [record.get('identity')] + [json.loads(p).get(k) for _, p in launch for k in ('identity', 'runner')]
    if any(isinstance(r, dict) and probe(r) == 'alive' for r in runners): return None
    if not launch: return 'the ledger has no admission or restart of this launch'
    since = launch[0][0]
    identity = record.get('identity') or {}
    if isinstance(identity.get('pid'), int) and isinstance(identity.get('created'), int):
        stopped = _ledger_rows(root, "SELECT seq FROM events WHERE task_id=? AND kind='runner.stopped' AND seq>? AND "
                                     "json_extract(payload,'$.identity.pid')=? AND json_extract(payload,'$.identity.created')=? "
                                     'ORDER BY seq LIMIT 1', (task, since, identity['pid'], identity['created']))
        if stopped: since = stopped[0][0]  # it ended by itself here; before this the runner ran and nothing was released
    waits = TERMINAL + ('blocked', 'waiting'); marks = ','.join('?' * len(waits))
    phase = _ledger_rows(root, "SELECT json_extract(payload,'$.phase') FROM events WHERE task_id=? AND kind='workflow.checkpoint' "
                               'AND seq<=? ORDER BY seq DESC LIMIT 1', (task, since))
    if phase and phase[0][0] in waits: return 'checkpoint ' + phase[0][0] + ' when its runner may have been gone'
    paused = _ledger_rows(root, "SELECT 1 FROM events WHERE task_id=? AND kind='execution.pause_requested' LIMIT 1", (task,))
    if paused: return 'execution.pause_requested'
    after = _ledger_rows(root, "SELECT kind, json_extract(payload,'$.phase') FROM events WHERE task_id=? AND seq>? AND (kind IN "
                         "('execution.cancel_requested','request.created','request.answered','host.cancel_enforced',"
                         f"'host.restart_exhausted') OR (kind='workflow.checkpoint' AND json_extract(payload,'$.phase') IN ({marks}))) "
                         'ORDER BY seq LIMIT 1', (task, since, *waits))
    return ' '.join(str(v) for v in after[0] if v) if after else None


def _before(record, moment):
    try: return _when(record['at']) < _when(moment)
    except (KeyError, TypeError, ValueError): return True  # no usable time: treated as launched before


def _supervision(root, now):
    """(supervised, writable). Unreadable right now -> (None, False): admissions and supervision wait for the next scan, the
    file is never overwritten from a guess (P4-A: an unread file used to become an empty list of supervised tasks).
    Malformed -> rebuilt from the launch records and the ledger (the damaged copy is kept).
    Every launch record is reconciled once, durably: `reconciled[task]` holds the identity (request, at) of the last launch record
    that was READ and handled (supervised, or already supervised, or not a running launch). A record that cannot be read now stays
    unreconciled and is looked at again on every scan — P4b-R3 (Codex review of P4): the file time used before let a record that
    was locked during one scan look "older than the supervision file" afterwards, so a launched runner whose supervision write had
    failed was never supervised again.
    A supervision file without this map was written before P4b: the first scan that reads it notes the moment (`upgraded_at`).
    A record launched before that moment and not in the file is supervised again only if the ledger shows that the host cannot
    have released it since its launch (_released_since_launch); otherwise it is never revived and the reason is kept in
    `not_revived` — P4b-R3 (Codex review of P4b): every such record used to count as released, so a runner admitted and launched
    by the old host whose supervision write had failed was left unsupervised after the upgrade."""
    path = root / 'host' / 'supervised.json'
    status, value = _load(path)
    if status == 'unreadable': return None, False
    if status == 'ok' and isinstance(value, dict) and isinstance(value.get('tasks'), dict): supervised = value
    elif status == 'missing': supervised = {'tasks': {}, 'reconciled': {}}
    else: supervised = None
    legacy = supervised is not None and not isinstance(supervised.get('reconciled'), dict)
    rebuilt = supervised if supervised is not None else {'tasks': {}, 'rebuilt_at': now.isoformat(), 'reconciled': {}}
    if legacy: rebuilt['reconciled'] = {}; rebuilt['upgraded_at'] = now.isoformat()
    seen = rebuilt['reconciled']; upgraded = rebuilt.get('upgraded_at')
    try:
        for record_path in sorted((root / 'host' / 'launch').glob('TASK-*.json')):
            try: record = _read(record_path)
            except _Unreadable: continue  # held by another process right now: stays unreconciled, looked at again next scan
            if not isinstance(record, dict) or not isinstance(record.get('task'), str): continue
            task = record['task']; identity = f"{record.get('request')}|{record.get('at')}"
            if seen.get(task) == identity: continue
            if task in rebuilt['tasks'] or record.get('state') not in ('launching', 'launched'):
                seen[task] = identity; continue
            if upgraded and _before(record, upgraded):
                released = _released_since_launch(root, record)
                if released:  # possibly released by the host before the upgrade: never revived (a resume dispatches anew)
                    seen[task] = identity; rebuilt.setdefault('not_revived', {})[task] = released[:200]; continue
            entry = _rebuilt_entry(root, record, now)
            if entry: rebuilt['tasks'][task] = entry; seen[task] = identity
            # no entry yet (the ledger has no dispatch for it): stays unreconciled, looked at again next scan
    except (OSError, ValueError, sqlite3.Error):
        return None, False  # the ledger or a record cannot be read now: decide nothing this scan, overwrite nothing
    if supervised is None:
        try:
            path.with_name(f'supervised.corrupt-{now.strftime("%Y%m%dT%H%M%S")}.json').write_bytes(path.read_bytes())
            _write(path, rebuilt)
        except OSError:
            return None, False
    return rebuilt, True


def scan(state_root, now=None, launch=None, boot=None):
    """Admit queued requests of one state root and supervise the tasks admitted there. Returns actions taken."""
    now = now or dt.datetime.now(dt.timezone.utc); launch = launch or _launch
    root = Path(state_root); actions = []
    supervised_path = root / 'host' / 'supervised.json'
    supervised, writable = _supervision(root, now)
    if not writable:
        return [{'action': 'deferred', 'reason': 'host/supervised.json cannot be read right now; queue and supervision wait for '
                                                 'the next scan (nothing is dropped or overwritten)'}]
    for path in sorted(queue_dir(root).glob('HD-*.json')):
        rid = path.stem; request = None
        try:
            retry = _read(_retry_path(root, rid)) or {}
        except _Unreadable:
            continue  # its backoff record is being written right now; the request stays queued
        if retry.get('next_at') and now < _when(retry['next_at']): continue  # backing off after a transient error
        try:
            status, value = _load(path)
            if status == 'missing': continue  # taken by another host serving this root meanwhile
            if status == 'ok' and _valid(value, root, rid): request = value
            else:
                recorded = _dispatched(root, rid)  # P4-A: the ledger's copy, when the file is unreadable or damaged
                if recorded is not None and _valid(recorded, root, rid): request = recorded
                elif status == 'unreadable':
                    raise _Unreadable(f'queue file {path.name} cannot be read right now ({value}) and the ledger has no dispatch '
                                      'with this id yet')
                else:
                    raise _Malformed('Malformed or foreign request (not in this ledger either): ' + str(value)[:200])
            ledger = Ledger(request['project'], request['state_root'])
            decided = _decision(ledger, request['task'], rid)
            if decided or retry.get('decided'):
                # Decided before (a restart, or a file that could not be moved): only tidy the queue, never decide again.
                if _set_aside(root, path, now): actions.append({'request': rid, 'task': request['task'], 'action': 'reconciled',
                                                                'decision': decided})
                continue
            result = _admit(request, launch, now, supervised['tasks'].get(request['task']))
            if result['action'] == 'admitted':
                entry = supervised['tasks'].get(request['task'])
                if entry is None or result.get('launched'):  # a duplicate keeps the existing supervision and its restart history
                    supervised['tasks'][request['task']] = dict(entry or {'restarts': []}, task=request['task'], project=request['project'],
                        state_root=request['state_root'], runtime=request['runtime'], admitted_at=now.isoformat(),
                        runner=result.get('identity') or result.get('runner') or (entry or {}).get('runner'))
                # Persist after each request, so a crash later in this scan cannot lose who was launched. A file another
                # process holds right now is written at the end of the scan or, failing that, rebuilt from the launch record.
                try: _write(supervised_path, supervised)
                except OSError as error:
                    actions.append({'task': request['task'], 'action': 'supervision_write_deferred', 'error': str(error)[:200]})
            actions.append(dict(result, task=request['task'], source='queue' if status == 'ok' and request is value else 'ledger'))
        except Exception as error:
            if isinstance(error, _Malformed):
                # P4-A: only a request that is damaged AND absent from the ledger is ended without a decision; kept with its reason.
                actions.append({'request': rid, 'action': 'failed', 'rejected': True, 'error': str(error)[:300]})
                _set_aside(root, path, now, to='rejected', reason={'status': status, 'error': str(error)[:500]})
                continue
            if isinstance(error, _LaunchFailed):  # decided: host.launch_failed is in the ledger and the task is blocked
                actions.append({'request': rid, 'task': request['task'], 'action': 'failed', 'error': str(error)[:300]})
            elif isinstance(error, (ValueError, OSError, KeyError, sqlite3.Error, _Unrecorded)):
                # Any other error never ends a request silently: bounded retries, then the task is blocked with the cause.
                try: keep, action = _defer(root, path, request, error, now)
                except Exception as again:  # even its retry record cannot be written now: it simply stays queued
                    keep, action = True, {'request': rid, 'action': 'deferred', 'error': type(again).__name__ + ': ' + str(again)[:200]}
                actions.append(action)
                if keep: continue
            else:
                raise
        _set_aside(root, path, now)
    for task, entry in list(supervised['tasks'].items()):
        try:
            keep, action = _supervise(entry, now, launch, boot if boot is not None else _boot())
        except (ValueError, OSError, sqlite3.Error) as error:
            keep, action = True, {'task': task, 'action': 'error', 'error': str(error)[:300]}
        if not keep: supervised['tasks'].pop(task)
        if action: actions.append(action)
    try: _write(supervised_path, supervised)
    except OSError as error:  # kept in memory only for this scan; the next one rebuilds missing entries from launch records
        actions.append({'action': 'supervision_write_deferred', 'error': str(error)[:200]})
    return actions


def log(base, message, **fields):
    """The host has no console (pythonw under Task Scheduler): its evidence goes to host.log next to the lease."""
    path = Path(base) / 'host.log'
    try:
        if path.is_file() and path.stat().st_size > 2_000_000: os.replace(path, path.with_suffix('.log.1'))
        with path.open('a', encoding='utf-8') as stream: stream.write(canonical(dict(fields, at=utcnow(), message=message)) + '\n')
    except (OSError, TypeError, ValueError):
        pass


def _trace():
    import traceback
    return traceback.format_exc()[-1500:]


def serve(base=None, interval=2.0, once=False):
    """The host loop: single instance per user (lock), heartbeat lease, every registered state root scanned."""
    from types import SimpleNamespace
    from .supervisor import identity
    from .workflow import task_lock
    base = base or home()
    with task_lock(SimpleNamespace(state_root=base), 'host'):
        record = {'identity': identity(os.getpid()), 'host': socket.gethostname(), 'started_at': utcnow(), 'heartbeat': utcnow(),
                  'runtime': str(Path(__file__).resolve().parents[1]), 'python': sys.executable, 'interval': interval,
                  'last_actions': [], 'last_error': None}
        (base / 'stop').unlink(missing_ok=True)
        _write(base / 'lease.json', record)
        log(base, 'host started', pid=os.getpid(), runtime=record['runtime'], python=sys.executable, home=str(base))
        if not (base / 'roots.json').is_file(): log(base, 'no state root registered yet (host register --state-root)')
        roots = []
        try:
            while True:
                status_, value = _load(base / 'roots.json')
                if status_ == 'ok' and isinstance((value or {}).get('roots'), list): roots = value['roots']
                elif status_ == 'missing': roots = []
                else:  # unreadable right now or damaged: keep serving the roots read last time (P4-A)
                    log(base, 'roots.json ' + status_ + '; serving the previous list', error=str(value)[:300])
                errors = {}; seen = {}
                for item in roots:
                    try:
                        started = utcnow()
                        actions = scan(item['state_root'])
                        seen[str(Path(item['state_root']).resolve())] = started
                        if actions:
                            record['last_actions'] = (record['last_actions'] + actions)[-20:]
                            log(base, 'actions', state_root=item['state_root'], actions=actions)
                    except Exception as error:  # one root's defect never stops the host or hides another root's error
                        errors[item['state_root']] = type(error).__name__ + ': ' + str(error)[:400]
                        log(base, 'scan failed', state_root=item['state_root'], error=errors[item['state_root']], trace=_trace())
                record['last_error'] = errors or None; record['roots_seen'] = seen
                record['heartbeat'] = utcnow()
                try: _write(base / 'lease.json', record)
                except OSError: pass
                if once or (base / 'stop').exists(): return 'stopped'
                time.sleep(interval)
        finally:
            record['stopped_at'] = utcnow()
            try: _write(base / 'lease.json', record)
            except OSError: pass


# --- installation (an explicit user decision) ----------------------------------------------------------------------------

def _pythonw():
    from .supervisor import native_python
    candidate = Path(native_python()).with_name('pythonw.exe')
    return candidate if candidate.is_file() else Path(native_python())


def task_xml(runtime, user=None):
    """Per-user logon task, least privilege, no time limit, restarted by Windows if the host process fails."""
    user = user or (os.environ.get('USERDOMAIN', '') + '\\' + os.environ.get('USERNAME', '')).strip('\\')
    from xml.sax.saxutils import escape
    return f'''<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo><Description>OneCrew host: runs dispatched OneCrew jobs outside chat sessions (installed on the user's request).</Description></RegistrationInfo>
  <Triggers><LogonTrigger><Enabled>true</Enabled><UserId>{escape(user)}</UserId></LogonTrigger></Triggers>
  <Principals><Principal id="Author"><UserId>{escape(user)}</UserId><LogonType>InteractiveToken</LogonType><RunLevel>LeastPrivilege</RunLevel></Principal></Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries><StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate><StartWhenAvailable>true</StartWhenAvailable>
    <IdleSettings><StopOnIdleEnd>false</StopOnIdleEnd><RestartOnIdle>false</RestartOnIdle></IdleSettings>
    <AllowStartOnDemand>true</AllowStartOnDemand><Enabled>true</Enabled><Hidden>false</Hidden>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <RestartOnFailure><Interval>PT1M</Interval><Count>3</Count></RestartOnFailure>
    <Priority>5</Priority>
  </Settings>
  <Actions Context="Author"><Exec><Command>{escape(str(_pythonw()))}</Command><Arguments>-X utf8 -m onecrew.host run</Arguments><WorkingDirectory>{escape(str(runtime))}</WorkingDirectory></Exec></Actions>
</Task>
'''


def _schtasks(*args):
    done = subprocess.run(['schtasks', *args], capture_output=True, timeout=60, creationflags=0x08000000)
    return done.returncode, (done.stdout + done.stderr).decode(errors='replace').strip()


def install(runtime):
    runtime = Path(runtime).resolve()
    if not (runtime / 'onecrew' / 'host.py').is_file(): raise LedgerError('Not a OneCrew checkout with the host: ' + str(runtime))
    path = home() / 'task.xml'; path.write_text(task_xml(runtime), encoding='utf-16')
    code, text = _schtasks('/Create', '/TN', TASK_NAME, '/XML', str(path), '/F')
    if code: raise LedgerError('Task Scheduler refused the host task: ' + text[:400])
    return {'status': 'installed', 'task': TASK_NAME, 'runtime': str(runtime), 'python': str(_pythonw()), 'trigger': 'logon (this user)',
            'privilege': 'least', 'remove_with': 'python -m onecrew host uninstall'}


def start():
    code, text = _schtasks('/Run', '/TN', TASK_NAME)
    if code: raise LedgerError('Cannot start the host task: ' + text[:400])
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        current = lease()
        if current: return {'status': 'alive', 'identity': current['identity'], 'via': 'Task Scheduler'}
        time.sleep(.5)
    return {'status': 'starting', 'note': 'Task Scheduler accepted the start; no heartbeat yet.'}


def stop():
    (home() / 'stop').write_text('stop requested ' + utcnow())
    code, text = _schtasks('/End', '/TN', TASK_NAME)
    return {'status': 'stop_requested', 'scheduler': text[:200]}


def uninstall():
    stop()
    code, text = _schtasks('/Delete', '/TN', TASK_NAME, '/F')
    return {'status': 'removed' if code == 0 else 'not_installed', 'scheduler': text[:200]}


def status():
    code, text = _schtasks('/Query', '/TN', TASK_NAME, '/FO', 'LIST')
    record = _read(home() / 'lease.json')
    return {'installed': code == 0, 'scheduler': text[:600] if code == 0 else None, 'alive': lease() is not None,
            'lease': record, 'registered': _read(home() / 'roots.json', {'roots': []})['roots'],
            'served_by_host': sorted((record or {}).get('roots_seen') or {})}


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] == 'host': args = args[1:]
    parser = argparse.ArgumentParser(prog='onecrew host')
    sub = parser.add_subparsers(dest='command', required=True)
    run = sub.add_parser('run'); run.add_argument('--interval', type=float, default=2.0); run.add_argument('--once', action='store_true')
    inst = sub.add_parser('install'); inst.add_argument('--runtime', type=Path, default=Path(__file__).resolve().parents[1])
    inst.add_argument('--state-root', type=Path, action='append', default=[])
    reg = sub.add_parser('register'); reg.add_argument('--state-root', type=Path, required=True)
    for name in ('start', 'stop', 'uninstall', 'status'): sub.add_parser(name)
    parsed = parser.parse_args(args)
    try:
        if parsed.command == 'run': result = serve(interval=parsed.interval, once=parsed.once)
        elif parsed.command == 'install':
            result = install(parsed.runtime); result['state_roots'] = [register(r) for r in parsed.state_root]
        elif parsed.command == 'register': result = {'state_root': register(parsed.state_root), 'served': True}
        else: result = {'start': start, 'stop': stop, 'uninstall': uninstall, 'status': status}[parsed.command]()
        print(json.dumps(result, ensure_ascii=False, indent=2)); return 0
    except (ValueError, OSError) as error:
        print(json.dumps({'error': str(error)}, ensure_ascii=False)); return 2


if __name__ == '__main__':
    raise SystemExit(main())
