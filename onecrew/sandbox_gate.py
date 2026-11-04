"""Trusted container test contract; no generated code executes on the host."""
import ctypes
from ctypes import wintypes as w
import datetime as dt
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time
import uuid

from .ledger import LedgerError, canonical, content_hash, exact_fields, text_field
from .snapshots import durable_write
from .supervisor import Job, validate_executable


class GateUnavailable(LedgerError):
    """Infrastructure/cancellation is not a product failure to send to an AI repairer."""


def validate(check, profile):
    value = check['expected']
    exact_fields(value, ('image', 'argv', 'timeout_seconds'), 'Container gate')
    if not isinstance(value['image'], str) or not re.fullmatch(r'sha256:[0-9a-f]{64}', value['image']):
        raise LedgerError('Container gate needs a locally installed immutable image ID; no tag/pull.')
    argv = value['argv']
    if not isinstance(argv, list) or not 2 <= len(argv) <= 30:
        raise LedgerError('Container gate requires a bounded executable/argument list.')
    for arg in argv:
        text_field(arg, 'Container argument', 1000)
    if not argv[0].startswith('/') or '/work/' + check['path'] not in argv[1:]:
        raise LedgerError('Use an absolute container executable and the trusted /work/<check path> argument.')
    if check['path'] in profile['owned']:
        raise LedgerError('Container test entry must be read-only context, never worker-owned.')
    if type(value['timeout_seconds']) is not int or not 1 <= value['timeout_seconds'] <= 300:
        raise LedgerError('Container test timeout must be 1-300 seconds.')


def command(argv, directory, timeout, guard=None, environment_extra=None):
    """Bound an operator-selected native client and its child tree, not a filesystem sandbox."""
    validate_executable(argv)
    directory.mkdir(parents=True, exist_ok=True)
    token = uuid.uuid4().hex
    outpath, errpath = directory/(token+'.out'), directory/(token+'.err')
    child, job = None, Job()
    try:
        environment = {k: v for k, v in os.environ.items() if k.upper() in
                       ('SYSTEMROOT', 'WINDIR', 'PATH', 'PATHEXT', 'COMSPEC', 'TEMP', 'TMP',
                        'USERPROFILE', 'LOCALAPPDATA', 'APPDATA', 'PROGRAMFILES', 'PROGRAMFILES(X86)', 'PROGRAMDATA')}
        if environment_extra:
            if set(environment_extra) - {'JAVA_HOME', 'ANDROID_HOME', 'ANDROID_SDK_ROOT', 'FLUTTER_ROOT',
                                         'GRADLE_USER_HOME', 'CI', 'FLUTTER_SUPPRESS_ANALYTICS', 'DART_SUPPRESS_ANALYTICS',
                                         'PUB_CACHE','PUB_HOSTED_URL','PYTHONUTF8','PYTHONIOENCODING',
                                         # Node recipe mock e2e step (node_change.E2E_ENV), operator-pinned values only.
                                         'CHROME_PATH','CHROME_ARGS','NA_PYTHON','NA_BACKEND_DIR','NA_E2E_BACKEND_PORT',
                                         'NA_MOCK_PORT','NA_PROXY_PORT'}:
                raise GateUnavailable('Unsupported native client environment override.')
            environment.update(environment_extra)
        with outpath.open('wb') as out, errpath.open('wb') as err:
            child = subprocess.Popen(argv, cwd=directory, env=environment, stdin=subprocess.DEVNULL,
                                     stdout=out, stderr=err, creationflags=0x4 | 0x08000000)
            job.assign(child)
            nt = ctypes.WinDLL('ntdll')
            nt.NtResumeProcess.argtypes = [w.HANDLE]
            if nt.NtResumeProcess(w.HANDLE(int(child._handle))) != 0:
                raise GateUnavailable('Cannot resume contained native client.')
            deadline = time.monotonic() + timeout
            while child.poll() is None:
                if guard:
                    guard()
                if time.monotonic() >= deadline:
                    raise GateUnavailable('Native command deadline exceeded.')
                if max(outpath.stat().st_size, errpath.stat().st_size) > 2_000_000:
                    raise GateUnavailable('Native command exceeded output limit.')
                time.sleep(.05)
            job.stop()
            child.wait(timeout=5)
        if max(outpath.stat().st_size, errpath.stat().st_size) > 2_000_000:
            raise GateUnavailable('Native command exceeded output limit.')
        return child.returncode, outpath.read_text(encoding='utf-8', errors='replace'), errpath.read_text(encoding='utf-8', errors='replace')
    finally:
        try:
            job.stop()
            if child:
                if child.poll() is None:
                    child.kill()  # Handles assignment failure while still suspended.
                child.wait(timeout=5)
        finally:
            job.close()


class ContainerGate:
    def __init__(self, store, run_command=None):
        self.store = store
        self.root = store.root.parent/'gates'
        self.run_command = run_command or command
        self.docker = shutil.which('docker')
        self.guard = None

    def call(self, *args, timeout=15, cleanup=False):
        if not self.docker:
            raise GateUnavailable('Docker CLI unavailable; container gate was not executed.')
        if self.guard and not cleanup:
            self.guard()
        config = self.root/'empty-config'
        config.mkdir(parents=True, exist_ok=True)
        # Pin the local Desktop Linux pipe; never inherit a remote Docker context or credentials.
        return self.run_command([self.docker, '--config', str(config), '--host',
                                 'npipe:////./pipe/dockerDesktopLinuxEngine', *args],
                                self.root/'client-logs', timeout, None if cleanup else self.guard)

    def preflight(self, checks):
        code, out, _ = self.call('info', '--format', '{{json .}}')
        try:
            info = json.loads(out)
            if code or not isinstance(info, dict) or info.get('OSType') != 'linux':
                raise ValueError()
        except ValueError:
            raise GateUnavailable('Local Docker Linux Engine unavailable; no container tests executed.') from None
        for check in checks:
            expected = check['expected']['image']
            code, out, _ = self.call('image', 'inspect', expected, '--format', '{{json .}}')
            try:
                image = json.loads(out)
            except ValueError:
                image = {}
            if code or not isinstance(image, dict) or image.get('Id') != expected or not isinstance(image.get('Config'), dict):
                raise GateUnavailable('Pinned gate image unavailable locally; install it explicitly before enable.')
            if image.get('Config', {}).get('Volumes'):
                raise GateUnavailable('Gate image must not declare persistent volumes.')
        return {'engine': info.get('ServerVersion'), 'os': info['OSType'], 'transport': 'local_desktop_pipe'}

    def cleanup(self, name):
        code, _, err = self.call('rm', '--force', '--volumes', name, cleanup=True)
        if code:
            # Absence is a structured engine observation, not a guess from an error string.
            code, out, _ = self.call('container', 'ls', '--all', '--filter', 'name=^/'+name+'$', '--format', '{{.Names}}', cleanup=True)
            if code or out.strip():
                raise GateUnavailable('Container cleanup unconfirmed; no test result may pass: '+err[:200])

    def evaluate(self, snapshot, check, guard=None):
        key = content_hash({'snapshot': snapshot, 'check': check, 'gate_version': 1})
        from .workflow import task_lock
        from types import SimpleNamespace
        with task_lock(SimpleNamespace(state_root=self.root.parent), 'gate.'+key):
            return self._evaluate(snapshot, check, key, guard)

    def _evaluate(self, snapshot, check, key, guard):
        self.guard = guard
        root = self.root/key
        root.mkdir(parents=True, exist_ok=True)
        marker = root/'resource.json'
        name = 'onecrew-gate-'+key[:40]
        # The snapshot/check key is deterministic. Crash recovery removes the old container
        # before any new execution; the container has only disposable, networkless state.
        if marker.exists():
            self.cleanup(name)
        environment = self.preflight([check])
        workspace = root/('candidate-'+uuid.uuid4().hex)
        self.store.materialize(snapshot, workspace)
        if ',' in str(workspace):
            raise GateUnavailable('Container mount path contains a comma.')
        script = workspace/check['path']
        if not script.is_file():
            raise GateUnavailable('Trusted test entry is missing from the candidate snapshot.')
        durable_write(marker, canonical({'name': name, 'snapshot': snapshot, 'check': content_hash(check)}).encode())
        value = check['expected']
        argv = ['create', '--pull', 'never', '--name', name, '--label', 'onecrew.gate='+key,
                '--network', 'none', '--read-only', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges',
                '--user', '65534:65534', '--pids-limit', '64', '--memory', '256m', '--memory-swap', '256m', '--cpus', '1', '--no-healthcheck',
                '--log-driver', 'local', '--log-opt', 'max-size=2m', '--log-opt', 'max-file=1', '--log-opt', 'compress=false',
                '--tmpfs', '/tmp:rw,noexec,nosuid,nodev,size=64m,mode=1777',
                '--mount', f'type=bind,source={workspace},target=/work,readonly', '--workdir', '/work',
                '--env', 'HOME=/tmp', '--env', 'PYTHONDONTWRITEBYTECODE=1',
                '--entrypoint', value['argv'][0], value['image'], *value['argv'][1:]]
        result = None
        try:
            code, _, err = self.call(*argv)
            if code:
                raise GateUnavailable('Cannot create isolated test container: '+err[:300])
            code, out, err = self.call('start', '--attach', name, timeout=value['timeout_seconds'])
            inspect_code, raw, _ = self.call('inspect', '--format', '{{json .State}}', name)
            try:
                state = json.loads(raw)
            except ValueError:
                raise GateUnavailable('Container exit state unavailable.') from None
            if inspect_code or not isinstance(state, dict) or state.get('Running') is not False or type(state.get('ExitCode')) is not int:
                raise GateUnavailable('Container exit was not confirmed.')
            if state.get('Error') or str(state.get('StartedAt', '')).startswith('0001-'):
                raise GateUnavailable('Container failed before tests ran: '+str(state.get('Error') or err)[:500])
            passed = code == 0 and state['ExitCode'] == 0 and state.get('OOMKilled') is False and not state.get('Error')
            result = {'passed': passed, 'detail': 'Container tests passed.' if passed else (out+err)[-2000:] or 'Container test failed.',
                      'evidence': {'snapshot': snapshot, 'check_revision': content_hash(check), 'image': value['image'],
                                   'environment': environment, 'exit_code': state['ExitCode'], 'oom_killed': state.get('OOMKilled'),
                                   'stdout': out[-4000:], 'stderr': err[-2000:], 'network': 'none', 'source_mount': 'read-only'}}
        finally:
            self.cleanup(name)
        durable_write(root/'receipt.json', canonical(result).encode())
        return result


def task_guard(control, task_id):
    def check():
        from .solution_gate import check as check_solution
        check_solution(control.ledger,task_id)
        state = control.status(task_id)
        if (state['cancel_requested'] or state['status'] == 'paused'
                or control.clock() >= dt.datetime.fromisoformat(state['deadline'])):
            raise GateUnavailable('Container gate stopped by root cancel/pause/deadline.')
    return check
