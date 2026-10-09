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


class Job:
    def __init__(self):
        self.api = kernel()
        self.handle = self.api.CreateJobObjectW(None, None)
        if not self.handle:
            raise LedgerError('Cannot create process containment job.')
        limits = ExtendedLimit()
        limits.basic.flags = 0x2000 | 0x8  # Kill on last handle close; bound child count.
        limits.basic.active_limit = 64
        if not self.api.SetInformationJobObject(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
            self.close()
            raise LedgerError('Cannot enforce process containment.')

    def assign(self, child):
        if not self.api.AssignProcessToJobObject(self.handle, w.HANDLE(int(child._handle))):
            raise LedgerError('Cannot assign suspended process to job; worker will not start.')

    def stop(self):
        if not self.api.TerminateJobObject(self.handle, 1):
            raise LedgerError('Cannot terminate process job.')
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            counts = Accounting()
            if not self.api.QueryInformationJobObject(self.handle, 1, ctypes.byref(counts), ctypes.sizeof(counts), None):
                raise LedgerError('Cannot confirm process-tree termination.')
            if counts.active == 0:
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

    def run(self, attempt, argv, *, cwd, stdin='', timeout=120):
        if not isinstance(argv, list) or not argv or not all(isinstance(a, str) and a for a in argv):
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
        job = Job()  # Must succeed before creating a process.
        began = time.monotonic()
        reason = None
        try:
            with input_path.open('rb') as input_stream, (root/'stdout.txt').open('wb') as out, (root/'stderr.txt').open('wb') as err:
                child = subprocess.Popen(argv, cwd=cwd, stdin=input_stream, stdout=out, stderr=err,
                                         creationflags=0x4 | 0x08000000)  # suspended + no console window
                job.assign(child)
                token = {'worker': identity(child.pid), 'supervisor': identity(os.getpid()), 'job_contained': True}
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
                    time.sleep(.05)
                job.stop()  # Also kills descendants after a successful parent exit.
                child.wait(timeout=10)
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
            self.control.finish(attempt_id, row['generation'], {'reason': 'supervisor_interrupted', 'tree_stopped': True})
            return {'status': 'settled'}
        return {'status': 'alive' if owner == 'alive' else 'unknown', 'supervisor': owner, 'worker': worker}
