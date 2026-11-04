"""Windows process containment. Never release ownership on a lease timeout."""
from __future__ import annotations

import ctypes
from ctypes import wintypes as w
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import time

from .ledger import LedgerError

# 2.3-B (L1): every Supervisor attempt runs in its OWN named Job, so recovery can terminate exactly that attempt's tree (never a process by
# name, never another attempt of the same controller). The name is recorded in the launch token before the worker is resumed.
# Review F1/F8: the name carries what a copy of the ledger does NOT share (a tag of the resolved state root) and a random nonce, so a copied
# or moved state root can never open-and-terminate the original's Job, and the name cannot be guessed from the attempt id.
JOB_PREFIX = 'Local\\OneCrew-'
# Exit code of a tree that recovery terminated (Supervisor.terminate). A live controller that races the termination reads it back as
# reason 'stopped_by_recovery' instead of an ordinary non-zero exit (a "known failure").
RECOVERY_EXIT_CODE = 0x4F435243
# Bounded escalation for a hung controller (design §2.5, decision Q3): recovery terminates the attempt's own tree only after an explicit
# stop/cancel of its execution or a passed execution cap (Supervisor timeout or execution deadline), PLUS this grace period, which lets a
# healthy controller honour the request itself first. Silence, low CPU or a missing checkpoint are never a trigger. Tests shorten it.
ESCALATION_GRACE_MAX = 60.0
ESCALATION_GRACE_FRACTION = 0.1
# Review F4: never shorter than a healthy controller's own bounded stop: Job.stop waits up to 10 s, child.wait up to 10 s, and its
# settlement may wait 10 s on a busy ledger (sqlite timeout) - 30 s, plus a 5 s margin.
ESCALATION_GRACE_FLOOR = 35.0


def root_tag(state_root):
    """12 hex of sha256(normcase(realpath(state root))): the same state root gives the same tag, a copy or a moved root another."""
    return hashlib.sha256(os.path.normcase(os.path.realpath(str(state_root))).encode('utf-8')).hexdigest()[:12]


def job_name(state_root, attempt_id):
    return f'{JOB_PREFIX}{root_tag(state_root)}-{attempt_id}-{secrets.token_hex(8)}'


def owns_job(state_root, attempt_id, name):
    """Is `name` the Job of `attempt_id` launched from THIS state root? Only such a Job may ever be terminated from here."""
    return isinstance(name, str) and name.startswith(f'{JOB_PREFIX}{root_tag(state_root)}-{attempt_id}-')


def session_id(pid=None):
    """The Windows session of `pid` (default: this process). `Local\\` object names live per session, so a Job name looked up in one
    session says nothing about another (review F3)."""
    sid = w.DWORD()
    if not ctypes.WinDLL('kernel32', use_last_error=True).ProcessIdToSessionId(w.DWORD(pid or os.getpid()), ctypes.byref(sid)):
        return None
    return int(sid.value)


class SessionInfo(ctypes.Structure):
    _fields_ = [('id', w.DWORD), ('name', w.LPWSTR), ('state', ctypes.c_int)]


def live_sessions():
    """The ids of the Windows sessions that exist now (WTSEnumerateSessionsW), or None when they cannot be listed."""
    try:
        wts = ctypes.WinDLL('wtsapi32', use_last_error=True)
    except OSError:
        return None
    wts.WTSEnumerateSessionsW.argtypes = [w.HANDLE, w.DWORD, w.DWORD, ctypes.POINTER(ctypes.POINTER(SessionInfo)), ctypes.POINTER(w.DWORD)]
    pointer, count = ctypes.POINTER(SessionInfo)(), w.DWORD()
    if not wts.WTSEnumerateSessionsW(None, 0, 1, ctypes.byref(pointer), ctypes.byref(count)):
        return None
    try:
        return {int(pointer[i].id) for i in range(count.value)}
    finally:
        wts.WTSFreeMemory(pointer)


def uptime_ms():
    """Milliseconds since this boot (GetTickCount64). Monotonic within a boot and untouched by any change of the system clock."""
    api = ctypes.WinDLL('kernel32', use_last_error=True)
    api.GetTickCount64.restype = ctypes.c_ulonglong
    return int(api.GetTickCount64())


def gone_proof(token):
    """Review N1/N2/R3-1: (proof, None) when "the named Job is not found here" proves the controller's tree is gone, else (None, why).
    `Local\\` names live per Windows session, so "not found" from another session says nothing - unless that session no longer exists
    (its whole namespace and every process of it ended) or the machine has rebooted since the launch (no process survives a reboot).
    The reboot is read from the uptime recorded in the launch token: the uptime now is LOWER only after a new boot, and no clock change
    moves it (a wall-clock estimate of the boot could be moved by a clock step). A token without that uptime has no reboot proof; after
    a Fast Startup shutdown the uptime continues, so the rule stays silent there (a safe miss)."""
    recorded = token.get('session')
    if recorded is not None and recorded == session_id():
        return 'same_session', None
    launched = token.get('uptime_ms')
    if type(launched) is int and uptime_ms() < launched:
        return 'rebooted_since_controller_start', None
    if recorded is None:
        return None, ('no session was recorded and no reboot since the launch can be shown; a Job name not found proves nothing')
    live = live_sessions()
    if live is None:
        return None, ('the end of the controller\'s recorded Windows session cannot be shown (the session list is unavailable); '
                      'a Local\\ Job name not found here proves nothing')
    if recorded not in live:
        return 'session_ended', None
    return None, 'the controller ran in another Windows session that still exists; a Local\\ Job name not found here proves nothing'


def grace_seconds(cap):
    """max(ESCALATION_GRACE_FLOOR, min(ESCALATION_GRACE_MAX, ESCALATION_GRACE_FRACTION x cap)); the maximum when the cap is unknown."""
    if type(cap) not in (int, float) or cap <= 0:
        return float(max(ESCALATION_GRACE_FLOOR, ESCALATION_GRACE_MAX))
    return float(max(ESCALATION_GRACE_FLOOR, min(ESCALATION_GRACE_MAX, ESCALATION_GRACE_FRACTION * cap)))


def output_file(state_root, attempt_id, stored):
    """M6 (2.3-B, design §7 case 15): the Supervisor stdout/stderr of `attempt_id` inside THIS state root. The settled result records
    the absolute path of the state root it ran in; a ledger copied or moved elsewhere must read its own copy, never the original folder.
    A path that is not a Supervisor attempt output (another layout) is returned unchanged."""
    path = Path(stored)
    if path.name in ('stdout.txt', 'stderr.txt') and path.parent.name == attempt_id and path.parent.parent.name == 'attempts':
        return Path(state_root) / 'attempts' / attempt_id / path.name
    return path


def native_python():
    """Bypass Windows Store execution aliases/venv redirectors for stdlib helpers."""
    return str(Path(sys.base_prefix) / 'python.exe') if os.name == 'nt' else sys.executable


def validate_executable(argv):
    executable = Path(argv[0])
    if not executable.is_absolute() or not executable.is_file() or executable.suffix.lower() != '.exe':
        raise LedgerError('Supervisor requires an absolute native .exe path from a verified adapter.')
    name = str(executable).replace('/', '\\').lower()
    configuration = executable.parent.parent / 'pyvenv.cfg'
    redirected = executable.name.lower().startswith('python') and configuration.is_file()
    if '\\appdata\\local\\microsoft\\windowsapps\\' in name or redirected:
        raise LedgerError('Execution aliases/venv redirectors are not contained; use a verified native executable.')


def kernel():
    if os.name != 'nt':
        raise LedgerError('This supervisor requires verified Windows Job Object support.')
    api = ctypes.WinDLL('kernel32', use_last_error=True)
    api.CreateJobObjectW.argtypes = [ctypes.c_void_p, w.LPCWSTR]
    api.CreateJobObjectW.restype = w.HANDLE
    api.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
    api.OpenProcess.restype = w.HANDLE
    api.CloseHandle.argtypes = [w.HANDLE]
    api.GetProcessTimes.argtypes = [w.HANDLE] + [ctypes.POINTER(w.FILETIME)] * 4
    api.WaitForSingleObject.argtypes = [w.HANDLE, w.DWORD]
    api.SetInformationJobObject.argtypes = [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD]
    api.AssignProcessToJobObject.argtypes = [w.HANDLE, w.HANDLE]
    api.TerminateJobObject.argtypes = [w.HANDLE, w.UINT]
    api.QueryInformationJobObject.argtypes = [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD, ctypes.c_void_p]
    api.OpenJobObjectW.argtypes = [w.DWORD, w.BOOL, w.LPCWSTR]
    api.OpenJobObjectW.restype = w.HANDLE
    api.IsProcessInJob.argtypes = [w.HANDLE, w.HANDLE, ctypes.POINTER(w.BOOL)]
    return api


def identity(pid):
    api = kernel()
    handle = api.OpenProcess(0x1000 | 0x100000, False, pid)
    if not handle:
        raise LedgerError('Process identity unavailable.')
    try:
        times = [w.FILETIME() for _ in range(4)]
        if not api.GetProcessTimes(handle, *[ctypes.byref(x) for x in times]):
            raise LedgerError('Process creation time unavailable.')
        return {'pid': pid, 'created': times[0].dwLowDateTime | times[0].dwHighDateTime << 32,
                'host': socket.gethostname()}
    finally:
        api.CloseHandle(handle)


def probe(record):
    if not record or record.get('host') != socket.gethostname():
        return 'unknown'
    api = kernel()
    handle = api.OpenProcess(0x1000 | 0x100000, False, record['pid'])
    if not handle:
        return 'dead' if ctypes.get_last_error() == 87 else 'unknown'
    try:
        times = [w.FILETIME() for _ in range(4)]
        if not api.GetProcessTimes(handle, *[ctypes.byref(x) for x in times]):
            return 'unknown'
        created = times[0].dwLowDateTime | times[0].dwHighDateTime << 32
        if created != record['created']:
            return 'dead'
        state = api.WaitForSingleObject(handle, 0)
        return {0: 'dead', 258: 'alive'}.get(state, 'unknown')
    finally:
        api.CloseHandle(handle)


class BasicLimit(ctypes.Structure):
    _fields_ = [('process_time', ctypes.c_longlong), ('job_time', ctypes.c_longlong),
                ('flags', w.DWORD), ('minimum', ctypes.c_size_t), ('maximum', ctypes.c_size_t),
                ('active_limit', w.DWORD), ('affinity', ctypes.c_size_t),
                ('priority', w.DWORD), ('scheduling', w.DWORD)]


class ExtendedLimit(ctypes.Structure):
    _fields_ = [('basic', BasicLimit), ('io', ctypes.c_ulonglong * 6),
                ('process_memory', ctypes.c_size_t), ('job_memory', ctypes.c_size_t),
                ('peak_process', ctypes.c_size_t), ('peak_job', ctypes.c_size_t)]


class Accounting(ctypes.Structure):
    _fields_ = [('times', ctypes.c_longlong * 4), ('page_faults', w.DWORD),
                ('total', w.DWORD), ('active', w.DWORD), ('terminated', w.DWORD)]


class ProcessIds(ctypes.Structure):
    _fields_ = [('assigned', w.DWORD), ('listed', w.DWORD), ('ids', ctypes.c_size_t * 64)]


class Job:
    def __init__(self, name=None, *, _opened=None):
        """A new containment Job (KILL_ON_JOB_CLOSE, at most 64 processes). `name` (2.3-B) makes it openable by recovery; an existing
        object of that name is refused, so a Job is never shared with something OneCrew did not create for this attempt."""
        self.api = kernel()
        self.name = name
        if _opened is not None:
            self.handle = _opened                  # Job.open: an existing Job, its limits untouched
            return
        ctypes.set_last_error(0)
        self.handle = self.api.CreateJobObjectW(None, name)
        if not self.handle:
            raise LedgerError('Cannot create process containment job.')
        if name and ctypes.get_last_error() == 183:   # ERROR_ALREADY_EXISTS
            self.close()
            raise LedgerError('A containment job with this attempt name already exists; the worker will not start.')
        limits = ExtendedLimit()
        limits.basic.flags = 0x2000 | 0x8  # Kill on last handle close; bound child count.
        limits.basic.active_limit = 64
        if not self.api.SetInformationJobObject(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
            self.close()
            raise LedgerError('Cannot enforce process containment.')

    @classmethod
    def open(cls, name):
        """The live named Job of an attempt (query + terminate rights), or None when no object of that name exists any more."""
        api = kernel()
        handle = api.OpenJobObjectW(0x0004 | 0x0008, False, name)   # JOB_OBJECT_QUERY | JOB_OBJECT_TERMINATE
        if not handle:
            if ctypes.get_last_error() == 2:                       # ERROR_FILE_NOT_FOUND: the kernel destroyed it
                return None
            raise LedgerError('Cannot open the attempt process job (error ' + str(ctypes.get_last_error()) + ').')
        return cls(name, _opened=handle)

    def assign(self, child):
        if not self.api.AssignProcessToJobObject(self.handle, w.HANDLE(int(child._handle))):
            raise LedgerError('Cannot assign suspended process to job; worker will not start.')

    def counts(self):
        counts = Accounting()
        if not self.api.QueryInformationJobObject(self.handle, 1, ctypes.byref(counts), ctypes.sizeof(counts), None):
            raise LedgerError('Cannot confirm process-tree termination.')
        return counts

    def members(self):
        """The process ids currently in the Job (JobObjectBasicProcessIdList; the Job allows at most 64)."""
        ids = ProcessIds()
        if not self.api.QueryInformationJobObject(self.handle, 3, ctypes.byref(ids), ctypes.sizeof(ids), None):
            raise LedgerError('Cannot list the processes of the attempt job.')
        return sorted(int(ids.ids[i]) for i in range(ids.listed))

    def contains(self, record):
        """True/False whether the identified live process is in this Job; None when it cannot be checked."""
        handle = self.api.OpenProcess(0x1000, False, record['pid'])
        if not handle:
            return None
        try:
            inside = w.BOOL()
            if not self.api.IsProcessInJob(handle, self.handle, ctypes.byref(inside)):
                return None
            return bool(inside.value)
        finally:
            self.api.CloseHandle(handle)

    def stop(self, code=1):
        if not self.api.TerminateJobObject(self.handle, code):
            raise LedgerError('Cannot terminate process job.')
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if self.counts().active == 0:
                return
            time.sleep(.02)
        raise LedgerError('Process tree still active; ownership retained.')

    def close(self):
        if self.handle:
            self.api.CloseHandle(self.handle)
            self.handle = None


class Supervisor:
    def __init__(self, control):
        self.control = control

    def run(self, attempt, argv, *, cwd, stdin='', timeout=120, env=None):
        if not isinstance(argv, list) or not argv or not argv[0] or not all(isinstance(a, str) for a in argv):
            raise LedgerError('Command must be a non-empty argv list.')
        if type(timeout) not in (int, float) or not 0 < timeout <= 28800:
            raise LedgerError('Invalid process timeout.')
        if attempt['status'] != 'reserved':
            raise LedgerError('Cannot replay an already dispatched attempt.')
        try:
            validate_executable(argv)
        except LedgerError:
            self.control.finish(attempt['id'], attempt['generation'], {'reason': 'unsupported_launcher'}, not_started=True)
            raise
        root = self.control.ledger.state_root / 'attempts' / attempt['id']
        root.mkdir(parents=True, exist_ok=False)
        input_path = root / 'stdin.txt'
        input_path.write_text(stdin, encoding='utf-8')
        child = None
        resumed = False
        job = Job(job_name(self.control.ledger.state_root, attempt['id']))  # Must succeed before creating a process; named per attempt (2.3-B).
        began = time.monotonic()
        reason = None
        # W51 (T18b): an executor may ask to be told, every `liveness_every` seconds, that the command is still running and how much it
        # has written. The hook is optional and never fails the run; v1 callers set nothing and see no change.
        liveness = getattr(self.control, 'liveness_hook', None)
        every = float(getattr(self.control, 'liveness_every', 30.0) or 30.0)
        last_tick = began
        try:
            with input_path.open('rb') as input_stream, (root/'stdout.txt').open('wb') as out, (root/'stderr.txt').open('wb') as err:
                child = subprocess.Popen(argv, cwd=cwd, stdin=input_stream, stdout=out, stderr=err, env=env,
                                         creationflags=0x4 | 0x08000000)  # suspended + no console window
                job.assign(child)
                # 2.3-B: the Job name and the execution cap are part of the identity committed BEFORE the worker is resumed, so
                # recovery can find exactly this tree and knows when the cap has passed even if this controller hangs.
                token = {'worker': identity(child.pid), 'supervisor': identity(os.getpid()), 'job_contained': True,
                         'job_name': job.name, 'session': session_id(), 'uptime_ms': uptime_ms(), 'timeout': timeout,
                         'started_at': self.control.clock().isoformat()}
                self.control.launched(attempt['id'], attempt['generation'], token)
                nt = ctypes.WinDLL('ntdll')
                nt.NtResumeProcess.argtypes = [w.HANDLE]
                if nt.NtResumeProcess(w.HANDLE(int(child._handle))) != 0:
                    raise LedgerError('Cannot resume contained worker.')
                resumed = True
                while child.poll() is None:
                    state = self.control.status(attempt['task_id'])
                    if state['cancel_requested']:
                        reason = 'cancelled'
                    elif state['status'] == 'paused':
                        reason = 'paused'
                    elif self.control.clock() >= dt.datetime.fromisoformat(state['deadline']):
                        reason = 'deadline'
                    elif time.monotonic()-began >= timeout:
                        reason = 'timeout'
                    elif any((root/name).stat().st_size > 16_000_000 for name in ('stdout.txt', 'stderr.txt')):
                        reason = 'output_limit'
                    if reason:
                        break
                    if liveness is not None and time.monotonic() - last_tick >= every:
                        last_tick = time.monotonic()
                        try:
                            liveness(attempt, {'elapsed_seconds': round(time.monotonic() - began, 3),
                                               'stdout_bytes': (root/'stdout.txt').stat().st_size, 'stderr_bytes': (root/'stderr.txt').stat().st_size})
                        except Exception:                      # noqa: BLE001 — an observation must never stop the supervised command
                            pass
                    time.sleep(.05)
                job.stop()  # Also kills descendants after a successful parent exit.
                child.wait(timeout=10)
            if reason is None and child.returncode == RECOVERY_EXIT_CODE:
                reason = 'stopped_by_recovery'     # recovery terminated this tree while this controller was still able to observe it
            result = {'exit_code': child.returncode, 'reason': reason, 'stdout': str(root/'stdout.txt'),
                      'stderr': str(root/'stderr.txt'), 'seconds': round(time.monotonic()-began, 3),
                      'tree_stopped': True}
            self.control.finish(attempt['id'], attempt['generation'], result)
            return result
        except BaseException:
            stopped = False
            try:
                job.stop()
                if child is not None:
                    if child.poll() is None:
                        child.kill()  # Handles failure before assignment; it is still suspended.
                    child.wait(timeout=10)
                stopped = True
            finally:
                if stopped:
                    record = self.control.attempt(attempt['id'])
                    if record['status'] != 'settled':
                        self.control.finish(attempt['id'], attempt['generation'],
                                            {'reason': 'supervisor_error', 'tree_stopped': True},
                                            not_started=not resumed and record['status'] == 'reserved')
                else:
                    self.control.unknown(attempt['id'], 'process-tree stop unconfirmed')
            raise
        finally:
            job.close()

    def _intent(self, attempt_id, row, reason):
        """Durable intent BEFORE a termination: the attempt becomes `unknown` (an existing attempt.unknown event). An attempt that is
        already unknown gets no second event (review F10), but the ledger must still be writable: a locked ledger (a suspended controller
        holding it, Q4) raises here and nothing is terminated."""
        if row['status'] == 'running':
            self.control.unknown(attempt_id, reason)
            return
        with self.control.ledger.transaction(write=True) as conn:
            conn.execute('UPDATE attempts SET updated_at=updated_at WHERE id=?', (attempt_id,))

    def _unconfirmed(self, attempt_id, reason):
        """Record an unconfirmed stop once: the same reason is not written again on every sweep (review F10)."""
        row = self.control.attempt(attempt_id)
        try:
            current = json.loads(row['result'] or '{}').get('reason')
        except (ValueError, TypeError, AttributeError):
            current = None
        if row['status'] == 'unknown' and current == reason:
            return
        self.control.unknown(attempt_id, reason)

    def _settle(self, attempt_id, generation, result):
        try:
            self.control.finish(attempt_id, generation, result)
        except LedgerError:
            if self.control.attempt(attempt_id)['status'] != 'settled':
                raise
            return {'status': 'settled', 'by': 'owner'}          # the controller recorded its own settlement first
        return {'status': 'settled', 'result': result}

    def reconcile(self, attempt_id):
        row = self.control.attempt(attempt_id)
        if row['status'] == 'settled':
            return {'status': 'settled'}
        token = json.loads(row['identity']) if row['identity'] else None
        if not token or not token.get('job_contained'):
            self.control.unknown(attempt_id, 'Launch identity unavailable; manual reconciliation required.')
            return {'status': 'unknown'}
        owner = probe(token['supervisor'])
        worker = probe(token['worker'])
        if owner != 'dead' or not token.get('job_name'):
            if owner == 'dead' and worker == 'dead':           # a launch token without a named Job (2.2): the original rule
                self.control.finish(attempt_id, row['generation'], {'reason': 'supervisor_interrupted', 'tree_stopped': True})
                return {'status': 'settled'}
            return {'status': 'alive' if owner == 'alive' else 'unknown', 'supervisor': owner, 'worker': worker}
        return self._reconcile_job(attempt_id, row, token, worker)

    def _reconcile_job(self, attempt_id, row, token, worker):
        """The controller is dead and the attempt has a named Job (2.3-B). The Job is the proof for the whole tree (Q7):
        * Job gone - proof only when `gone_proof` holds (the controller's recorded session is this one, has ended, or the uptime shows a
          reboot since the launch: review F3, N1, N2, R3-1) and the recorded worker does not probe alive; then every member ended with
          the last handle (KILL_ON_JOB_CLOSE);
        * Job present with 0 active processes - proof, unless the recorded worker probes alive (it escaped the Job: review N3);
        * Job present with members (a member or another process keeps a handle) - an orphan tree: terminated here (intent first,
          TerminateJobObject, confirm 0 active), but ONLY when the recorded name is this state root's own Job (review F1);
        anything else stays `unknown` with its reason. Never settled without the proof."""
        name = token['job_name']
        dead = {'status': 'unknown', 'supervisor': 'dead', 'worker': worker}
        try:
            job = Job.open(name)
        except (LedgerError, OSError) as error:
            return dict(dead, job={'name': name, 'error': str(error)[:300]})
        if job is None:
            if worker == 'alive':
                return dict(dead, reason='the worker lives although its named Job is gone; manual reconciliation required')
            proof, why = gone_proof(token)
            if proof is None:
                return dict(dead, reason=why)
            self.control.finish(attempt_id, row['generation'], {'reason': 'supervisor_interrupted', 'tree_stopped': True,
                                'job': {'name': name, 'exists': False, 'session': token.get('session'), 'proof': proof}})
            return {'status': 'settled'}
        before, after, failure = None, None, None
        try:
            counts = job.counts()
            if counts.active == 0 and worker == 'alive':
                return dict(dead, reason='the Job has no active member but the recorded worker lives outside it; manual reconciliation required')
            if counts.active == 0:
                after = counts
            elif not owns_job(self.control.ledger.state_root, attempt_id, name):
                return dict(dead, reason='the live Job belongs to another state root (copied or moved ledger); it is never terminated from here')
            else:
                self._intent(attempt_id, row, 'recovery is terminating the process tree of a dead controller; the stop is not confirmed yet')
                before = job.members()
                job.stop(RECOVERY_EXIT_CODE)
                after = job.counts()
        except (LedgerError, OSError) as error:
            failure = str(error)[:300]
        finally:
            job.close()
        if failure is not None:
            self._unconfirmed(attempt_id, 'process-tree stop unconfirmed: ' + failure)
            return dict(dead, error=failure)
        evidence = {'name': name, 'exists': True, 'active_after': after.active, 'total_processes': after.total}
        if before is not None:
            evidence.update(members_before=before, terminated_after_owner_death=True)
        self._settle(attempt_id, row['generation'], {'reason': 'supervisor_interrupted', 'tree_stopped': True, 'job': evidence})
        return {'status': 'settled'}

    def escalation(self, attempt_id):
        """When recovery may terminate this attempt's own process tree (read-only). Only after an explicit stop/cancel of its execution
        or a passed execution cap (the recorded Supervisor timeout, or the execution deadline), plus `grace_seconds(cap)`; never on
        silence, CPU, liveness or a missing checkpoint. Never for a Job of another state root (review F1) or a controller in another
        Windows session. Values are stable for the same trigger (safe to record repeatedly)."""
        row = self.control.attempt(attempt_id)
        token = json.loads(row['identity']) if row['identity'] else None
        if row['status'] not in ('running', 'unknown') or not isinstance(token, dict) or not token.get('job_contained') or not token.get('job_name'):
            return {'due': False, 'trigger': None, 'reason': 'no live attempt with a named contained process job'}
        if not owns_job(self.control.ledger.state_root, attempt_id, token['job_name']):
            return {'due': False, 'trigger': None, 'foreign_job': True,
                    'reason': 'the attempt Job belongs to another state root (copied or moved ledger): it is never terminated from here'}
        if token.get('session') is None or token.get('session') != session_id():
            return {'due': False, 'trigger': None, 'reason': 'the controller runs in another Windows session: its Job cannot be reached from here'}
        status = self.control.status(row['task_id'])
        now = self.control.clock()
        cap = token.get('timeout')
        grace = grace_seconds(cap)
        passed = []
        if status['cancel_requested']:
            with self.control.ledger.transaction() as conn:
                event = conn.execute("SELECT created_at FROM events WHERE task_id=? AND kind='execution.cancel_requested' ORDER BY seq LIMIT 1",
                                     (row['task_id'],)).fetchone()
            if event:
                passed.append(('stop_requested', dt.datetime.fromisoformat(event['created_at'])))
        if token.get('started_at') and type(cap) in (int, float):
            capped = dt.datetime.fromisoformat(token['started_at']) + dt.timedelta(seconds=cap)
            if capped <= now: passed.append(('execution_cap', capped))
        deadline = dt.datetime.fromisoformat(status['deadline'])
        if deadline <= now: passed.append(('deadline', deadline))
        if not passed:
            return {'due': False, 'trigger': None, 'reason': 'no stop request and no passed execution cap: silence is never a reason'}
        trigger, since = min(passed, key=lambda item: item[1])
        due_at = since + dt.timedelta(seconds=grace)
        return {'due': now >= due_at, 'trigger': trigger, 'since': since.isoformat(), 'grace_seconds': grace, 'due_at': due_at.isoformat()}

    def terminate(self, attempt_id):
        """Bounded escalation for a hung controller (2.3-B M3). When `escalation` says it is due (this state root's own Job, same session):
        * the Job is gone while the controller lives (its own unconfirmed-stop path closed it, review F10): KILL_ON_JOB_CLOSE ended every
          member, so the attempt settles `job_closed` with that proof - no intent, no repeated unknown;
        * otherwise record the intent (the attempt becomes `unknown`; a ledger that cannot record it stops here and nothing is
          terminated), check the Job holds the recorded worker, terminate the Job, confirm 0 active processes and settle
          'stopped_by_recovery' with the member list. Any failure keeps the attempt `unknown` (recorded once).
        Only this attempt's Job is touched: other attempts (other Jobs) and processes outside any OneCrew Job never are."""
        due = self.escalation(attempt_id)
        if not due['due']:
            return dict(due, status='not_due')
        row = self.control.attempt(attempt_id)
        token = json.loads(row['identity'])
        trigger = {'trigger': due['trigger'], 'trigger_since': due['since'], 'grace_seconds': due['grace_seconds']}
        try:
            job = Job.open(token['job_name'])
        except (LedgerError, OSError) as error:
            self._unconfirmed(attempt_id, 'process-tree stop unconfirmed: ' + str(error)[:300])
            return {'status': 'unknown', 'trigger': due['trigger'], 'error': str(error)[:300]}
        if job is None:
            if probe(token['worker']) == 'alive':
                self._unconfirmed(attempt_id, 'process-tree stop unconfirmed: the worker lives although its named Job is gone')
                return {'status': 'unknown', 'trigger': due['trigger']}
            result = dict({'reason': 'job_closed', 'tree_stopped': True,              # escalation is due only in the recorded session
                           'job': {'name': token['job_name'], 'exists': False, 'session': token['session'], 'proof': 'same_session'}},
                          **trigger)
            return dict(self._settle(attempt_id, row['generation'], result), trigger=due['trigger'])
        before, counts, failure = None, None, None
        try:
            self._intent(attempt_id, row, 'recovery is terminating the contained process tree after ' + due['trigger']
                         + '; the stop is not confirmed yet')
            if probe(token['worker']) == 'alive' and job.contains(token['worker']) is not True:
                raise LedgerError('the named job does not contain the recorded worker')
            before = job.members()
            job.stop(RECOVERY_EXIT_CODE)
            counts = job.counts()
        except (LedgerError, OSError) as error:
            failure = str(error)[:300]
        finally:
            job.close()
        if failure is not None:
            self._unconfirmed(attempt_id, 'process-tree stop unconfirmed: ' + failure)
            return {'status': 'unknown', 'trigger': due['trigger'], 'error': failure}
        result = dict({'reason': 'stopped_by_recovery', 'tree_stopped': True,
                       'job': {'name': token['job_name'], 'members_before': before, 'active_after': counts.active,
                               'total_processes': counts.total}}, **trigger)
        settled = self._settle(attempt_id, row['generation'], result)
        return dict(settled, trigger=due['trigger'], job=result['job']) if 'by' not in settled else dict(settled, trigger=due['trigger'])


def job_evidence(name):
    """What the named Job shows now: {'name', 'exists': False} once the kernel destroyed it (its last handle closed, KILL_ON_JOB_CLOSE
    ended every member), or the active count and members of a Job that still exists."""
    job = Job.open(name)
    if job is None:
        return {'name': name, 'exists': False, 'active': 0}
    try:
        return {'name': name, 'exists': True, 'active': job.counts().active, 'members': job.members()}
    finally:
        job.close()
