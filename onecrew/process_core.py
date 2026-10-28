"""Windows process containment. Never release ownership on a lease timeout."""
from __future__ import annotations

import ctypes
from ctypes import wintypes as w
import datetime as dt
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time

from .ledger import LedgerError

# 2.3-B (L1): every Supervisor attempt runs in its OWN named Job, so recovery can terminate exactly that attempt's tree (never a process by
# name, never another attempt of the same controller). The name is recorded in the launch token before the worker is resumed.
JOB_PREFIX = 'Local\\OneCrew-'
# Exit code of a tree that recovery terminated (Supervisor.terminate). A live controller that races the termination reads it back as
# reason 'stopped_by_recovery' instead of an ordinary non-zero exit (a "known failure").
RECOVERY_EXIT_CODE = 0x4F435243
# Bounded escalation for a hung controller (design §2.5, decision Q3): recovery terminates the attempt's own tree only after an explicit
# stop/cancel of its execution or a passed execution cap (Supervisor timeout or execution deadline), PLUS this grace period, which lets a
# healthy controller honour the request itself first. Silence, low CPU or a missing checkpoint are never a trigger. Tests shorten it.
ESCALATION_GRACE_MAX = 60.0
ESCALATION_GRACE_FRACTION = 0.1


def job_name(attempt_id):
    return JOB_PREFIX + attempt_id


def grace_seconds(cap):
    """min(ESCALATION_GRACE_MAX, ESCALATION_GRACE_FRACTION x cap); the maximum when the cap is unknown."""
    if type(cap) not in (int, float) or cap <= 0:
        return float(ESCALATION_GRACE_MAX)
    return float(min(ESCALATION_GRACE_MAX, ESCALATION_GRACE_FRACTION * cap))


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
        job = Job(job_name(attempt['id']))  # Must succeed before creating a process; named per attempt (2.3-B).
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
                         'job_name': job.name, 'timeout': timeout, 'started_at': self.control.clock().isoformat()}
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
        if owner == 'dead' and worker == 'dead':
            result = {'reason': 'supervisor_interrupted', 'tree_stopped': True}
            if token.get('job_name'):
                # 2.3-B (Q7): the Job itself is the proof for the whole tree, not only the two probed roots. A Job that still exists
                # with active members means descendants live on: nothing is settled.
                try:
                    evidence = job_evidence(token['job_name'])
                except (LedgerError, OSError) as error:
                    return {'status': 'unknown', 'supervisor': owner, 'worker': worker,
                            'job': {'name': token['job_name'], 'error': str(error)[:300]}}
                if evidence.get('active'):
                    return {'status': 'unknown', 'supervisor': owner, 'worker': worker, 'job': evidence}
                result['job'] = evidence
            self.control.finish(attempt_id, row['generation'], result)
            return {'status': 'settled'}
        return {'status': 'alive' if owner == 'alive' else 'unknown', 'supervisor': owner, 'worker': worker}

    def escalation(self, attempt_id):
        """When recovery may terminate this attempt's own process tree (read-only). Only after an explicit stop/cancel of its execution
        or a passed execution cap (the recorded Supervisor timeout, or the execution deadline), plus `grace_seconds(cap)`; never on
        silence, CPU, liveness or a missing checkpoint. Values are stable for the same trigger (safe to record repeatedly)."""
        row = self.control.attempt(attempt_id)
        token = json.loads(row['identity']) if row['identity'] else None
        if row['status'] not in ('running', 'unknown') or not isinstance(token, dict) or not token.get('job_contained') or not token.get('job_name'):
            return {'due': False, 'trigger': None, 'reason': 'no live attempt with a named contained process job'}
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
        """Bounded escalation for a hung controller (2.3-B M3). When `escalation` says it is due: record the intent (the attempt
        becomes `unknown`; a ledger that cannot record it - a suspended controller holding the lock - stops here and nothing is
        terminated), open the attempt's named Job, check it holds the recorded worker, terminate the Job and confirm 0 active
        processes, then settle 'stopped_by_recovery' with the member list as evidence. Any failure keeps the attempt `unknown`.
        Only this attempt's Job is touched: other attempts (other Jobs) and processes outside any OneCrew Job never are."""
        due = self.escalation(attempt_id)
        if not due['due']:
            return dict(due, status='not_due')
        row = self.control.attempt(attempt_id)
        token = json.loads(row['identity'])
        self.control.unknown(attempt_id, 'recovery is terminating the contained process tree after ' + due['trigger']
                             + '; the stop is not confirmed yet')
        job, before, counts = None, None, None
        try:
            job = Job.open(token['job_name'])
            if job is None:
                raise LedgerError('the named attempt job no longer exists while its controller is alive')
            if probe(token['worker']) == 'alive' and job.contains(token['worker']) is not True:
                raise LedgerError('the named job does not contain the recorded worker')
            before = job.members()
            job.stop(RECOVERY_EXIT_CODE)
            counts = job.counts()
        except (LedgerError, OSError) as error:
            self.control.unknown(attempt_id, 'process-tree stop unconfirmed: ' + str(error)[:300])
            return {'status': 'unknown', 'trigger': due['trigger'], 'error': str(error)[:300]}
        finally:
            if job is not None:
                job.close()
        result = {'reason': 'stopped_by_recovery', 'tree_stopped': True, 'trigger': due['trigger'], 'trigger_since': due['since'],
                  'grace_seconds': due['grace_seconds'],
                  'job': {'name': token['job_name'], 'members_before': before, 'active_after': counts.active, 'total_processes': counts.total}}
        try:
            self.control.finish(attempt_id, row['generation'], result)
        except LedgerError:
            if self.control.attempt(attempt_id)['status'] != 'settled':
                raise
            return {'status': 'settled', 'by': 'owner', 'trigger': due['trigger']}   # the controller recorded its own settlement first
        return {'status': 'settled', 'trigger': due['trigger'], 'job': result['job']}


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
