"""Per-state-root coordinator supervisor: restarts dead delivery-root runners within a bound.

Not a reminder scheduler: never calls a model, sends chat, answers a question or extends a budget. It adopts only roots
last started by a keeper-aware runtime (others need an explicit resume) and never revives a runner that died with a
reboot: it raises one typed question for it instead, and the answer continues the root.
"""
import argparse
import datetime as dt
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import time
from types import SimpleNamespace

from .ledger import Ledger, LedgerError, canonical, utcnow
from . import runner
from .snapshots import durable_write
from .supervisor import identity, native_python, probe
from .workflow import task_lock

BACKOFF = (10, 60, 300)  # seconds before restart 1, 2, 3 within the rolling window; also spaces lost-report retries
WINDOW = 3600
LIMIT = len(BACKOFF)
REPORTS = 3  # attempts to raise the coordinator-lost blocker before the episode is closed anyway
ACTIVE = ('running', 'waiting_operation')
TERMINAL = ('completed', 'cancelled', 'failed')
LOCK_WAIT = 3  # a replacement may start while the previous keeper is still releasing


def _when(text):
    value = dt.datetime.fromisoformat(text)
    return value if value.tzinfo else value.replace(tzinfo=dt.timezone.utc)


def _boot():
    """Last boot as a FILETIME (the unit of supervisor identity 'created'); None when unknown."""
    if os.name != 'nt': return None
    import ctypes
    api = ctypes.WinDLL('kernel32'); api.GetTickCount64.restype = ctypes.c_ulonglong
    return int((time.time()+11644473600)*10**7) - api.GetTickCount64()*10**4


def _roots(state_root):
    """Non-terminal delivery roots in one short read transaction; nothing is held while runners start or events are written."""
    path = Path(state_root).resolve()/'ledger.sqlite3'
    if not path.is_file(): return []
    conn = sqlite3.connect(path.as_uri()+'?mode=ro', uri=True, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute('BEGIN')
        names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {'delivery_roots', 'executions'} <= names: return []
        children = 'delivery_children' in names
        result = []
        for row in conn.execute('SELECT r.task_id,t.project_path FROM delivery_roots r JOIN tasks t ON t.id=r.task_id ORDER BY r.task_id').fetchall():
            task = row['task_id']
            execution = conn.execute('SELECT status,cancel_requested FROM executions WHERE task_id=?', (task,)).fetchone()
            checkpoint = conn.execute("SELECT seq,payload FROM events WHERE task_id=? AND kind='workflow.checkpoint' ORDER BY seq DESC LIMIT 1", (task,)).fetchone()
            if not execution or not checkpoint or execution['cancel_requested'] or execution['status'] in TERMINAL: continue
            phase = json.loads(checkpoint['payload']).get('phase')
            if phase in TERMINAL: continue
            members = [task] + ([r[0] for r in conn.execute('SELECT task_id FROM delivery_children WHERE root=?', (task,))] if children else [])
            pending = conn.execute(f"SELECT COUNT(*) FROM requests WHERE state='pending' AND task_id IN ({','.join('?' for _ in members)})", members).fetchone()[0]
            events = conn.execute("SELECT seq,kind,payload,created_at FROM events WHERE task_id=? AND kind IN ('runner.started','runner.stopped',"
                                  "'coordinator.restarted','coordinator.restart_exhausted','coordinator.lost_report') ORDER BY seq", (task,)).fetchall()
            restarts, reports, lifecycle, latest, exhausted, manual, detail, reboots = [], [], None, {}, 0, 0, None, []
            for event in events:
                value, kind = json.loads(event['payload']), event['kind']
                at = _when(value.get('at') or event['created_at']) if kind.startswith('coordinator.') else None
                if kind == 'coordinator.restarted':
                    restarts.append({'seq': event['seq'], 'at': at})
                elif kind == 'coordinator.restart_exhausted':
                    # An exhaustion recorded without an outcome predates report retries and was final.
                    exhausted, detail = event['seq'], value.get('detail')
                    reports = [{'at': at, 'status': (value.get('coordinator_lost') or {'status': 'unavailable'}).get('status')}]
                elif kind == 'coordinator.lost_report' and value.get('cause') == 'reboot':
                    reboots.append({'at': at, 'status': value.get('status')})
                elif kind == 'coordinator.lost_report':
                    reports.append({'at': at, 'status': value.get('status')})
                else:
                    lifecycle = _when(event['created_at'])
                    if kind == 'runner.started':
                        latest, reboots = value, []  # reboot reports belong to the runner that died with the reboot
                        # A person's or entry's start (resume, the answer to a lost-coordinator question) opens a new episode.
                        if value.get('initiator') != 'keeper': manual, restarts = event['seq'], []
            exhausted = exhausted > manual
            result.append({'task': task, 'project': row['project_path'], 'phase': phase, 'checkpoint_seq': checkpoint['seq'],
                           'eligible': execution['status'] != 'paused' and (phase in ACTIVE or phase == 'waiting' and not pending),
                           # Only roots last started by a keeper-aware runtime are adopted; older ones need an explicit resume.
                           'adopted': isinstance(latest.get('runtime'), dict), 'created': (latest.get('identity') or {}).get('created'),
                           'restarts': restarts, 'lifecycle': lifecycle, 'exhausted': exhausted, 'detail': detail,
                           'reports': reports if exhausted else [], 'reboots': reboots,
                           'closed': exhausted and (len(reports) >= REPORTS or any(r['status'] in ('reported', 'unavailable') for r in reports))})
        return result
    finally:
        conn.close()


def _launching(state_root):
    """A runner directory created moments ago (wall clock) may belong to a runner not yet registered."""
    try:
        with os.scandir(Path(state_root)/'runners') as entries:
            newest = max((e.stat().st_mtime for e in entries if e.is_dir()), default=0)
    except OSError:
        return False
    return time.time()-newest < BACKOFF[0]


def _lost(ledger, task, detail, cls=None):
    from .solution_delivery import Delivery
    if not hasattr(Delivery, 'coordinator_lost'): return {'status': 'unavailable'}
    try:
        if cls: Delivery(ledger).coordinator_lost(task, detail, cls=cls)
        else: Delivery(ledger).coordinator_lost(task, detail)
        return {'status': 'reported'}
    except Exception as error:  # another module's code: a defect there must not end supervision of every root
        return {'status': 'failed', 'error': (type(error).__name__+': '+str(error))[:500]}


REBOOT = 'Coordinator runner died with a Windows reboot or shutdown; OneCrew never restarts it silently.'


def _reboot(ledger, task, root, now, act):
    """A runner that died with a reboot is never revived silently: one typed question, hence one notice, per runner.

    Idempotent: a landed report (or the question it raised, which makes the root wait on a person) ends the episode;
    a failed report is retried on later scans, spaced and bounded like a lost-coordinator report."""
    action = {'task': task, 'action': 'reboot', 'reason': 'Runner died with a reboot; the user is asked once instead of a silent restart.'}
    reports = root['reboots']
    if not act or len(reports) >= REPORTS or any(r['status'] in ('reported', 'unavailable') for r in reports): return action
    if reports:
        last, wait = reports[-1]['at'], BACKOFF[min(len(reports), LIMIT)-1]
        if (now-last).total_seconds() < wait: return dict(action, retry_after=(last+dt.timedelta(seconds=wait)).isoformat())
    payload = dict(_lost(ledger, task, REBOOT, 'coordinator_lost'), cause='reboot', runner_created=root['created'],
                   last_checkpoint_seq=root['checkpoint_seq'], attempt=len(reports)+1, at=now.isoformat())
    with ledger.transaction(write=True) as conn:
        ledger._event(conn, task, 'coordinator.lost_report', payload)
    return dict(action, **payload)


def _scan(state_root, now=None, start=None, act=True):
    """(actions, live): live counts roots the keeper must stay up for, i.e. a live runner or a dead root it can restart."""
    now = now or dt.datetime.now(dt.timezone.utc)
    start = start or runner.start
    actions, live, launching, boot = [], 0, None, _boot()
    for root in _roots(state_root):
        task = root['task']
        if not root['adopted'] or root['closed']: continue  # never launched (entry owns that start), legacy start, or episode over
        try:
            ledger = Ledger(root['project'], state_root)
            current = runner.status(ledger, task)['status']
        except (ValueError, OSError, sqlite3.Error) as error:
            actions.append({'task': task, 'action': 'skipped', 'reason': str(error)[:300]}); continue
        if current == 'alive':
            live += 1; continue  # supervised, including a decision wait or a pause: it may still die later
        if current == 'unknown':
            actions.append({'task': task, 'action': 'unknown', 'reason': 'Runner liveness cannot be proven; not restarted.'}); continue
        if not root['eligible']: continue  # waiting on a person, paused or blocked: the answer/resume restarts it
        if boot and isinstance(root['created'], int) and root['created'] < boot:
            actions.append(_reboot(ledger, task, root, now, act)); continue
        live += 1
        if not act: continue
        if root['exhausted']:  # the blocker did not reach the user yet: retry it, spaced and bounded
            last, wait = root['reports'][-1]['at'], BACKOFF[min(len(root['reports']), LIMIT)-1]
            if (now-last).total_seconds() < wait:
                actions.append({'task': task, 'action': 'backoff', 'retry_after': (last+dt.timedelta(seconds=wait)).isoformat()}); continue
            payload = dict(_lost(ledger, task, root['detail']), attempt=len(root['reports'])+1, at=now.isoformat())
            with ledger.transaction(write=True) as conn:
                ledger._event(conn, task, 'coordinator.lost_report', payload)
            actions.append({'task': task, 'action': 'lost_report', **payload}); continue
        recent = [r for r in root['restarts'] if (now-r['at']).total_seconds() < WINDOW]
        if len(recent) >= LIMIT:
            detail = f'Coordinator runner died {len(recent)} times within {WINDOW//60} minutes; automatic restarts exhausted.'
            # Written once per episode; a failed report is retried from this outcome until it lands or REPORTS run out.
            payload = {'cause': 'runner_dead', 'restarts': [r['seq'] for r in recent], 'last_checkpoint_seq': root['checkpoint_seq'],
                       'detail': detail, 'at': now.isoformat(), 'coordinator_lost': _lost(ledger, task, detail)}
            with ledger.transaction(write=True) as conn:
                ledger._event(conn, task, 'coordinator.restart_exhausted', payload)
            actions.append({'task': task, 'action': 'exhausted', **payload})
            continue
        reference = recent[-1]['at'] if recent else root['lifecycle']
        wait = BACKOFF[len(recent)]
        if reference and (now-reference).total_seconds() < wait:
            actions.append({'task': task, 'action': 'backoff', 'retry_after': (reference+dt.timedelta(seconds=wait)).isoformat()}); continue
        if launching is None: launching = _launching(state_root)
        if launching:
            actions.append({'task': task, 'action': 'backoff', 'reason': 'A runner launch is in progress.'}); continue
        try:
            result = start(ledger, task, initiator='keeper')
        except (ValueError, OSError) as error:
            result = {'status': 'failed', 'error': str(error)[:500]}
        payload = {'cause': 'runner_dead', 'last_checkpoint_seq': root['checkpoint_seq'], 'restart_count': len(recent)+1,
                   'runner': {k: result[k] for k in ('status', 'identity', 'logs', 'exit_code', 'error') if k in result},
                   'at': now.isoformat()}
        with ledger.transaction(write=True) as conn:
            ledger._event(conn, task, 'coordinator.restarted', payload)
        actions.append({'task': task, 'action': 'restarted', **payload})
    return actions, live


def scan(state_root, now=None, start=None):
    """Restart eligible dead delivery roots (start defaults to runner.start); returns actions taken."""
    return _scan(state_root, now, start)[0]


def location(state_root):
    return Path(state_root).resolve()/'keeper'/'status.json'


def read_status(state_root):
    try:
        return json.loads(location(state_root).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None


def _write(state_root, record):
    durable_write(location(state_root), canonical(record).encode('utf-8'))


def _supervise(root, interval, idle_exit):
    record = {'pid': os.getpid(), 'identity': identity(os.getpid()) if os.name == 'nt' else None, 'started_at': utcnow(),
              'last_scan': None, 'interval': interval, 'idle_exit': idle_exit, 'live_roots': 0, 'last_actions': [], 'last_error': None}
    _write(root, record)
    idle_since = time.monotonic()
    while True:
        try:
            actions, live = _scan(root)
            record.update(last_scan=utcnow(), live_roots=live, last_error=None,
                          last_actions=(actions or record['last_actions'])[-10:])
        except (ValueError, OSError, sqlite3.Error) as error:
            live = None
            record.update(last_scan=utcnow(), last_error=str(error)[:500])
        if live or _launching(root): idle_since = time.monotonic()  # a runner being launched registers within seconds
        elif time.monotonic()-idle_since >= idle_exit:
            # Publish the exit before a final check: an ensure() that saw us alive ran after its runner was live or launching.
            record['stopped_at'] = utcnow(); _write(root, record)
            try: live = _scan(root, act=False)[1] or _launching(root)
            except (ValueError, OSError, sqlite3.Error): live = 0
            if not live: return 'idle'
            record.pop('stopped_at'); idle_since = time.monotonic()
        try: _write(root, record)
        except OSError: pass  # status is advisory; supervision continues
        time.sleep(interval)


def loop(state_root, interval=5, idle_exit=120):
    """Singleton per state-root; exits after idle_exit seconds without a supervised delivery root."""
    root = Path(state_root).resolve()
    deadline = time.monotonic()+LOCK_WAIT
    while True:
        try:
            with task_lock(SimpleNamespace(state_root=root), 'keeper'):
                return _supervise(root, interval, idle_exit)
        except LedgerError as error:
            if 'already owns' not in str(error): raise
            if time.monotonic() >= deadline: return 'duplicate'
            time.sleep(.2)


def ensure(state_root):
    """Start a detached keeper unless the recorded one is provably alive."""
    if os.environ.get('ONECREW_KEEPER', '').lower() in ('0', 'off', 'disabled'):
        return {'status': 'disabled'}
    if os.name != 'nt':
        raise LedgerError('Keeper is verified only on native Windows.')
    root = Path(state_root).resolve()
    current = read_status(root)
    if current and not current.get('stopped_at') and probe(current.get('identity')) == 'alive':
        return {'status': 'alive', 'identity': current['identity'], 'last_scan': current.get('last_scan')}
    directory = root/'keeper'
    directory.mkdir(parents=True, exist_ok=True)
    argv = [native_python(), '-X', 'utf8', '-m', 'onecrew.keeper', '--state-root', str(root)]
    with (directory/'stdout.txt').open('ab') as out, (directory/'stderr.txt').open('ab') as err:
        # Same breakaway as runner.start: the keeper must outlive the launching command.
        process = subprocess.Popen(argv, cwd=Path(__file__).resolve().parents[1], stdin=subprocess.DEVNULL,
                                   stdout=out, stderr=err, close_fds=True, env=dict(os.environ, ONECREW_ACTOR='keeper'),
                                   creationflags=0x8 | 0x200 | 0x01000000)
    return {'status': 'starting', 'identity': identity(process.pid), 'logs': str(directory)}


def after_reply(ledger, task_id):
    """Answer-driven continuation: a reply to a delivery root/child restarts a stopped root runner."""
    from .delivery_store import root_id
    try:
        with ledger.transaction() as conn:
            root = root_id(conn, task_id)
        if root is None: return None
        current = runner.status(ledger, root)
        if current['status'] == 'stopped':
            return dict(runner.start(ledger, root, initiator='reply'), task=root, started=True)  # start pairs the keeper
        result = {'task': root, 'status': current['status'], 'started': False}
        if current['status'] == 'alive':
            # The live runner applies the answer itself; its keeper may have idle-exited during the wait.
            try: result['keeper'] = ensure(ledger.state_root)
            except (OSError, ValueError) as error: result['keeper'] = {'status': 'unavailable', 'error': str(error)[:300]}
        return result
    except (ValueError, OSError, sqlite3.Error) as error:
        return {'task': task_id, 'status': 'not_started', 'started': False, 'error': str(error)[:500]}


def main(argv=None):
    parser = argparse.ArgumentParser(prog='onecrew.keeper')
    parser.add_argument('--state-root', required=True, type=Path)
    parser.add_argument('--interval', type=float, default=5)
    parser.add_argument('--idle-exit', type=float, default=120)
    args = parser.parse_args(argv)
    try:
        print(loop(args.state_root, args.interval, args.idle_exit), flush=True)
        return 0
    except (ValueError, OSError) as error:
        print(str(error), flush=True)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
