"""Read-only subscription quota observations. Never start a model turn or consume resets."""
import ctypes
from ctypes import wintypes as w
import datetime as dt
import json
import math
import os
import queue
import subprocess
import tempfile
import threading
import time

from .ledger import LedgerError
from .providers import doctor, executable
from .supervisor import Job, validate_executable


class ReadOnlyRPC:
    ALLOWED = {'initialize', 'account/read', 'account/rateLimits/read'}

    def __init__(self, argv, timeout=20):
        validate_executable(argv)
        self.deadline = time.monotonic()+timeout
        self.messages = queue.Queue(maxsize=100)
        self.sequence = 0
        self.job, self.child, self.reader = Job(), None, None
        self.errors = tempfile.TemporaryFile()
        try:
            self.child = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.errors,
                                          creationflags=0x4 | 0x08000000)
            self.job.assign(self.child)
            nt = ctypes.WinDLL('ntdll')
            nt.NtResumeProcess.argtypes = [w.HANDLE]
            if nt.NtResumeProcess(w.HANDLE(int(self.child._handle))) != 0:
                raise LedgerError('Cannot resume contained quota client.')
            self.reader = threading.Thread(target=self._read, daemon=True)
            self.reader.start()
        except BaseException:
            self.close()
            raise

    def _read(self):
        try:
            total = 0
            for _ in range(100):
                line = self.child.stdout.readline(256_001)
                total += len(line)
                if not line or len(line) > 256_000 or total > 2_000_000:
                    break
                self.messages.put_nowait(json.loads(line))
        except (OSError, ValueError, queue.Full):
            pass
        finally:
            try:
                self.messages.put_nowait(None)
            except queue.Full:
                pass

    def _send(self, value):
        self.child.stdin.write((json.dumps(value)+'\n').encode())
        self.child.stdin.flush()

    def request(self, method, params):
        if method not in self.ALLOWED:
            raise LedgerError('Quota client accepts only initialization and read-only account methods.')
        self.sequence += 1
        self._send({'id': self.sequence, 'method': method, 'params': params})
        while True:
            remaining = self.deadline-time.monotonic()
            if remaining <= 0:
                raise LedgerError('Quota read timed out; limits remain unknown.')
            if os.fstat(self.errors.fileno()).st_size > 2_000_000:
                raise LedgerError('Quota client diagnostic output exceeded the limit.')
            try:
                value = self.messages.get(timeout=min(.2, remaining))
            except queue.Empty:
                continue
            if not isinstance(value, dict):
                raise LedgerError('Quota client disconnected or returned invalid framing.')
            if value.get('id') == self.sequence:
                if 'error' in value or not isinstance(value.get('result'), dict):
                    raise LedgerError('Codex account read was rejected; limits remain unknown.')
                return value['result']
            if 'id' in value and 'method' in value:
                raise LedgerError('Quota client received an unexpected interactive request; no action applied.')

    def initialized(self):
        self._send({'method': 'initialized', 'params': {}})

    def close(self):
        try:
            self.job.stop()
            if self.child:
                if self.child.poll() is None:
                    self.child.kill()
                self.child.wait(timeout=5)
                self.child.stdin.close()
                if self.reader:
                    self.reader.join(timeout=5)
                self.child.stdout.close()
        finally:
            self.job.close()
            self.errors.close()


def normalize(payload, now=None):
    now = now or dt.datetime.now(dt.timezone.utc)
    if not isinstance(payload, dict):
        raise LedgerError('Quota payload must be an object.')
    source = payload.get('rateLimitsByLimitId')
    if source is None:
        legacy = payload.get('rateLimits')
        source = {legacy.get('limitId') or 'legacy': legacy} if isinstance(legacy, dict) else {}
    if not isinstance(source, dict) or len(source) > 50:
        raise LedgerError('Invalid quota bucket map.')
    buckets = {}
    for key, row in source.items():
        if not isinstance(key, str) or not isinstance(row, dict):
            raise LedgerError('Invalid quota bucket.')
        windows, missing = [], []
        for name in ('primary', 'secondary'):
            window = row.get(name)
            if window is None:
                missing.append(name)
                continue
            if not isinstance(window, dict):
                raise LedgerError('Invalid quota window.')
            used, duration, reset = (window.get(k) for k in ('usedPercent', 'windowDurationMins', 'resetsAt'))
            if type(used) not in (int, float) or not math.isfinite(used) or used < 0:
                raise LedgerError('Quota usage must be a non-negative numeric percentage.')
            if type(reset) is not int or type(duration) is not int or duration <= 0:
                missing.append(name)
                continue
            try:
                resets_at = dt.datetime.fromtimestamp(reset, dt.timezone.utc).isoformat()
            except (OverflowError, OSError, ValueError):
                raise LedgerError('Invalid quota reset timestamp.') from None
            windows.append({'name': name, 'used_percent': used, 'remaining': max(0, 100-used),
                            'duration_minutes': duration, 'resets_at': resets_at})
        individual = row.get('individualLimit')
        if individual is not None:
            if not isinstance(individual, dict) or type(individual.get('remainingPercent')) is not int or type(individual.get('resetsAt')) is not int:
                raise LedgerError('Invalid individual spend limit.')
            try:
                resets_at = dt.datetime.fromtimestamp(individual['resetsAt'], dt.timezone.utc).isoformat()
            except (OverflowError, OSError, ValueError):
                raise LedgerError('Invalid individual reset timestamp.') from None
            windows.append({'name': 'individual', 'remaining': max(0, min(100, individual['remainingPercent'])),
                            'resets_at': resets_at, 'duration_minutes': None})
        if row.get('spendControlReached') is not None and type(row['spendControlReached']) is not bool:
            raise LedgerError('Spend-control observation must be a JSON boolean or unavailable.')
        blocked = bool(row.get('rateLimitReachedType')) or row.get('spendControlReached') is True
        buckets[key] = {'windows': windows, 'unavailable_windows': missing, 'server_blocked': blocked,
                        'spend_control_observed': type(row.get('spendControlReached')) is bool,
                        'status': 'blocked' if blocked else 'observed' if windows else 'unknown'}
    return {'provider': 'codex', 'source': 'codex-app-server/account/rateLimits/read',
            'observed_at': now.isoformat(), 'expires_at': (now+dt.timedelta(minutes=2)).isoformat(),
            'status': 'observed' if buckets else 'unknown', 'buckets': buckets, 'model_calls': 0,
            'authority': 'read_only', 'routing_mapping': 'Caller must select the applicable bucket and required windows.'}


def codex(rpc_factory=ReadOnlyRPC, capability=None):
    capability = capability or doctor('codex')
    if not capability.get('available'):
        raise LedgerError('Verified Codex CLI unavailable for quota read.')
    argv = [executable('codex'), '--no-daemon', 'app-server', '--stdio', '--disable', 'hooks',
            '--disable', 'apps', '--disable', 'plugins', '--disable', 'shell_tool']
    rpc = rpc_factory(argv)
    try:
        rpc.request('initialize', {'clientInfo': {'name': 'onecrew_quota', 'version': '0.1.0'},
                                  'capabilities': {'explicitGatewayOauth': True}})
        rpc.initialized()
        account = rpc.request('account/read', {'refreshToken': False})
        if not isinstance(account.get('account'), dict) or account['account'].get('type') != 'chatgpt':
            raise LedgerError('Quota feed requires existing ChatGPT subscription login; no API-key fallback.')
        payload = rpc.request('account/rateLimits/read', {'excludeResetCreditDetails': True, 'supportsLunaReserve': False})
        return normalize(payload)
    finally:
        rpc.close()


def routing_quota(observation, bucket, required_windows, estimate, keep_for_chat):
    """Convert explicit bucket mapping and cost estimate into the existing routing contract."""
    from .routing import number
    number(estimate, 'estimated_call')
    number(keep_for_chat, 'keep_for_chat')
    if estimate <= 0:
        raise LedgerError('A positive estimated call cost is required; unknown is not free.')
    row = observation.get('buckets', {}).get(bucket)
    if (not row or row['server_blocked'] or not row['spend_control_observed']
            or not isinstance(required_windows, list) or not required_windows
            or not all(isinstance(x, str) for x in required_windows)):
        raise LedgerError('Quota bucket unavailable/blocked or required windows unspecified.')
    observed = {w['name'] for w in row['windows']}
    if not set(required_windows) <= observed:
        raise LedgerError('Required quota window unavailable; no unlimited assumption.')
    return {'source': observation['source']+':'+bucket, 'observed_at': observation['observed_at'],
            'expires_at': observation['expires_at'],
            'windows': [{'name': w['name'], 'remaining': w['remaining'], 'reserved': 0,
                         'keep_for_chat': keep_for_chat, 'estimated_call': estimate, 'resets_at': w['resets_at']}
                        for w in row['windows']]}
