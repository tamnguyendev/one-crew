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


def _read(path, default=None):
    try: return json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError): return default


def _write(path, value):
    durable_write(Path(path), canonical(value).encode('utf-8'))


def _when(text):
    value = dt.datetime.fromisoformat(text)
    return value if value.tzinfo else value.replace(tzinfo=dt.timezone.utc)


# --- lease -----------------------------------------------------------------------------------------------------------

def lease(base=None):
    """The live host's lease, or None (missing, stale heartbeat or dead process)."""
    from .supervisor import probe
    record = _read((base or home()) / 'lease.json')
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
    roots = _read(path, {'roots': []})
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
                                   creationflags=0x200 | 0x08000000)  # new process group, no console window
    return {'identity': identity(process.pid), 'logs': str(directory), 'runtime': str(runtime)}


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


def _admit(request, launch):
    from . import runner
    ledger = Ledger(request['project'], request['state_root'])
    view = _task_view(ledger, request['task'])
    if view['phase'] is None or view['phase'] in TERMINAL or view['cancel']:
        payload = {'request': request['id'], 'reason': 'task is terminal, cancelled or not enabled', 'phase': view['phase']}
        _event(ledger, request['task'], 'host.refused', payload); return dict(payload, action='refused')
    current = runner.status(ledger, request['task'])
    if current['status'] in ('alive', 'unknown'):
        payload = {'request': request['id'], 'runner': current.get('identity'), 'note': 'a runner already owns this task'}
    else:
        payload = dict({'request': request['id']}, **launch(request))
    _event(ledger, request['task'], 'host.admitted', payload)
    return dict(payload, action='admitted')


def _supervise(entry, now, launch, boot):
    """One supervised task: returns (keep, action or None)."""
    from . import runner
    from .supervisor import probe
    ledger = Ledger(entry['project'], entry['state_root']); task = entry['task']
    view = _task_view(ledger, task)
    current = runner.status(ledger, task)
    if view['phase'] in TERMINAL or view['phase'] is None:
        return False, {'task': task, 'action': 'released', 'phase': view['phase']}
    if view['cancel']:
        if current['status'] == 'alive':
            since = entry.setdefault('cancel_seen', now.isoformat())
            if (now - _when(since)).total_seconds() >= CANCEL_GRACE:
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
        _event(ledger, task, 'host.restart_exhausted', {'restarts': restarts, 'at': now.isoformat()})
        _block(ledger, task, detail + ' Inspect the runner logs, then resume with job resume.', 'coordinator')
        return False, {'task': task, 'action': 'exhausted'}
    since = entry.setdefault('dead_since', now.isoformat())
    if (now - _when(restarts[-1] if restarts else since)).total_seconds() < BACKOFF[len(restarts)]:
        return True, {'task': task, 'action': 'backoff'}
    started = launch(dict(entry, id='restart-' + uuid.uuid4().hex[:8]))
    restarts.append(now.isoformat())
    entry.update(restarts=restarts, runner=started['identity']); entry.pop('dead_since', None)
    _event(ledger, task, 'host.restarted', {'runner': started['identity'], 'logs': started['logs'], 'restart_count': len(restarts),
                                            'at': now.isoformat(), 'cause': 'runner_dead'})
    return True, {'task': task, 'action': 'restarted'}


def scan(state_root, now=None, launch=None, boot=None):
    """Admit queued requests of one state root and supervise the tasks admitted there. Returns actions taken."""
    now = now or dt.datetime.now(dt.timezone.utc); launch = launch or _launch
    root = Path(state_root); actions = []
    supervised_path = root / 'host' / 'supervised.json'
    supervised = _read(supervised_path, {'tasks': {}})
    for path in sorted(queue_dir(root).glob('HD-*.json')):
        request = _read(path)
        try:
            if not request or Path(request['state_root']).resolve() != root.resolve(): raise LedgerError('Malformed or foreign request.')
            result = _admit(request, launch)
            if result['action'] == 'admitted':
                supervised['tasks'][request['task']] = {'task': request['task'], 'project': request['project'],
                    'state_root': request['state_root'], 'runtime': request['runtime'], 'admitted_at': now.isoformat(),
                    'runner': result.get('identity') or result.get('runner'), 'restarts': []}
            actions.append(dict(result, task=request.get('task') if request else None))
        except (ValueError, OSError, KeyError, sqlite3.Error) as error:
            actions.append({'request': path.stem, 'action': 'failed', 'error': str(error)[:300]})
        done = root / 'host' / 'done'; done.mkdir(parents=True, exist_ok=True)
        os.replace(path, done / path.name)
    for task, entry in list(supervised['tasks'].items()):
        try:
            keep, action = _supervise(entry, now, launch, boot if boot is not None else _boot())
        except (ValueError, OSError, sqlite3.Error) as error:
            keep, action = True, {'task': task, 'action': 'error', 'error': str(error)[:300]}
        if not keep: supervised['tasks'].pop(task)
        if action: actions.append(action)
    _write(supervised_path, supervised)
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
        try:
            while True:
                roots = _read(base / 'roots.json', {'roots': []})['roots']
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
