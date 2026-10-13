"""Generic execution tools for work contracts: an isolated Git workspace, bounded host commands and processes, Git
effects through the core with receipts, independent verification and a handover. The worker chooses; the core enforces.

Containment, stated plainly: commands run on the Windows host in a Job object (whole tree killed on timeout, cancel or
runner exit), in a cloned workspace whose remote is removed, with arguments pointing into the user's project or the
OneCrew state refused and secrets stripped from the environment. This is not an OS sandbox: a program can still write
elsewhere or use the network. The user's repository is checked against its pins at the end."""
import ctypes
from ctypes import wintypes as w
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time
import uuid

from .discovery import Discovery, scan_text
from .ledger import LedgerError, canonical, content_hash
from .snapshots import durable_write, safe_file, scoped_path
from .work_contract import argv_value, branch_name, git, relative_dir, SHA

OUTPUT_CAP = 2_000_000
RUN_SECONDS = 600
BACKGROUND_LIMIT = 3
SECRET_ENV = re.compile(r'(TOKEN|SECRET|PASSW|CREDENTIAL|API_?KEY|PRIVATE|SESSION)', re.I)
DROP_ENV = ('GIT_', 'ONECREW_', 'ANTHROPIC', 'OPENAI', 'CLAUDE', 'CODEX', 'KIRO', 'AWS_')
ABSOLUTE = re.compile(r'(?<![A-Za-z0-9])([A-Za-z]:[\\/][^\s"\'<>|;,]*|\\\\[^\s"\'<>|;,]+)')
GIT_REFUSED = {'push', 'remote', 'credential', 'send-email', 'daemon', 'filter-branch', 'gc', 'prune', 'update-server-info'}
TEST_FILE = re.compile(r'(^|/)(tests?|__tests__|spec|specs|test_driver|integration_test)/|(^|/)test_[^/]*\.py$|_test\.(py|dart|go)$|'
                       r'\.(test|spec)\.[cm]?[jt]sx?$|Tests?\.(java|kt|cs)$|_spec\.rb$', re.I)
SKIP_MARK = re.compile(r'@(unittest\.)?skip|pytest\.mark\.(skip|xfail)|\b(xit|xdescribe|xtest)\s*\(|\b(it|test|describe)\.(skip|only|todo)\s*\(|'
                       r'\bskip\s*:\s*(true|[\'"])|\bmarkTestSkipped\b|t\.Skip\(|@Disabled|@Ignore', re.I)
ASSERTION = re.compile(r'\bassert\w*\b|\bexpect\s*\(|\bshould\b|\bverify\s*\(', re.I)
_RUNNING = {}  # task -> {id: (Popen, Job, record)}; Job handles die with the runner process, so do their trees


def home(runtime, task_id):
    configured = os.environ.get('ONECREW_WORK_ROOT')
    base = Path(configured) if configured else (Path(Path(__file__).resolve().anchor) / 'ocw' if os.name == 'nt'
                                                else Path(runtime.ledger.state_root) / 'work')
    root = base / content_hash({'state': str(Path(runtime.ledger.state_root).resolve()), 'task': task_id})[:16]
    root.mkdir(parents=True, exist_ok=True)
    return root


def project_repo(runtime, contract):
    repo = Path(runtime.ledger.project).resolve()
    return repo / contract['scope']['repository'] if contract['scope']['repository'] else repo


# --- workspace ---------------------------------------------------------------------------------------------------

def create_workspace(runtime, task_id, contract, base):
    """Idempotent isolated clone at the pinned commit; the user's repository is only read (objects shared read-only)."""
    root = home(runtime, task_id); target = root / 'r'
    if (target / '.git').exists():
        if git(target, 'rev-parse', 'HEAD^{commit}', allow_failure=True) is None: raise LedgerError('Workspace exists but is unreadable.')
        return {'path': str(target), 'base': base, 'repository': contract['scope']['repository']}
    if target.exists(): shutil.rmtree(target)
    source = project_repo(runtime, contract)
    git(root, 'clone', '--shared', '--no-checkout', '--quiet', str(source), 'r', timeout=600)
    hooks = runtime.ledger.state_root / 'empty-hooks'; hooks.mkdir(parents=True, exist_ok=True)
    for key, value in (('core.longpaths', 'true'), ('core.hooksPath', str(hooks)), ('user.name', 'OneCrew'),
                       ('user.email', 'onecrew@localhost'), ('commit.gpgSign', 'false')):
        git(target, 'config', key, value)
    for key in ('core.autocrlf', 'core.eol', 'core.safecrlf'):  # the same line-ending rules as the user's checkout
        value = git(source, 'config', '--get', key, allow_failure=True)
        if value: git(target, 'config', key, value.decode().strip())
    git(target, 'checkout', '--quiet', '--detach', base, timeout=600)
    git(target, 'remote', 'remove', 'origin', allow_failure=True)
    if git(target, 'remote') not in (b'', None): raise LedgerError('Workspace still has a remote; refusing to continue.')
    (root / 'tmp').mkdir(exist_ok=True); (root / 'logs').mkdir(exist_ok=True)
    return {'path': str(target), 'base': base, 'repository': contract['scope']['repository']}


def ws_root(state):
    value = (state.get('work') or {}).get('workspace')
    if not value: raise LedgerError('No workspace: the contract grants neither edit nor commands; use the read-only project tools.')
    return Path(value['path'])


def view(runtime, state):
    """Discovery root for list/search/read: the workspace when one exists, otherwise the project read-only."""
    work = state.get('work') or {}
    if work.get('workspace'): return Discovery(work['workspace']['path']), 'workspace'
    return Discovery(runtime.ledger.project), 'project'


def file_path(state, contract, name, for_write=False):
    scoped_path(name)
    root = ws_root(state)
    target = safe_file(root, name)
    if for_write and contract['scope']['paths'] and not any(name == p or name.startswith(p.rstrip('/') + '/') for p in contract['scope']['paths']):
        raise LedgerError('Path outside the contract scope.paths; not authorized to edit.')
    return target


def is_test(name):
    return bool(TEST_FILE.search(name))


def write(state, contract, args, *, edit=False):
    if not contract['authority']['edit']: raise LedgerError('Edits are not authorized by the work contract.')
    name = args['path']; target = file_path(state, contract, name, for_write=True)
    exists = target.is_file()
    if target.exists() and not exists: raise LedgerError('Not a regular file.')
    base_has = git(ws_root(state), 'cat-file', '-e', state['work']['pins']['head'] + ':' + name, allow_failure=True) is not None
    if is_test(name) and base_has and not contract['authority']['edit_tests']:
        raise LedgerError('Existing test files are immutable under this contract; add a new test file or fix production code.')
    current = target.read_bytes() if exists else None
    expected = args.get('expected_sha256')
    if (hashlib.sha256(current).hexdigest() if current is not None else None) != expected:
        raise LedgerError('Stale or missing expected_sha256: read the file first (null only for a new file).')
    if edit:
        old, new = args.get('old'), args.get('new')
        if not isinstance(old, str) or not old or not isinstance(new, str): raise LedgerError('edit needs non-empty old and a new string.')
        text = current.decode('utf-8')
        if text.count(old) != 1: raise LedgerError(f'old string must occur exactly once (found {text.count(old)}).')
        data = text.replace(old, new).encode('utf-8')
    else:
        text = args.get('text')
        if not isinstance(text, str): raise LedgerError('write needs text.')
        data = text.encode('utf-8')
    if len(data) > 1_000_000: raise LedgerError('File edit exceeds 1 MB.')
    scan_text(data)
    target.parent.mkdir(parents=True, exist_ok=True)
    before = target.stat().st_mtime if exists else None
    durable_write(target, data)
    if before is not None and int(target.stat().st_mtime) <= int(before):
        # Eval gx (13/10/2026): a same-size edit within the same second left Python's bytecode cache "valid", so the old
        # code ran (a stale pass is possible too). Move mtime past the old second so every mtime-based cache sees the edit.
        os.utime(target, (int(before) + 1, int(before) + 1))
    state['work'].setdefault('edits', 0); state['work']['edits'] += 1
    return {'path': name, 'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data), 'created': current is None,
            'where': 'isolated workspace; the user project is unchanged'}


# --- commands and processes ---------------------------------------------------------------------------------------

def _allowed_executable(path):
    lower = str(path).replace('/', '\\').lower()
    if '\\appdata\\local\\microsoft\\windowsapps\\' in lower: return False
    if Path(path).name.lower().startswith('python') and (Path(path).parent.parent / 'pyvenv.cfg').is_file(): return False
    return True


def which(name, path_env):
    """Resolve a command name to a real executable, skipping Store aliases and venv redirectors."""
    if '/' in name or '\\' in name or re.match(r'[A-Za-z]:', name):
        candidate = Path(name)
        if candidate.is_absolute() and candidate.is_file() and _allowed_executable(candidate): return candidate
        raise LedgerError('Executable path not found or not allowed: ' + name[:120])
    extensions = [''] if Path(name).suffix.lower() in ('.exe', '.cmd', '.bat') else ['.exe', '.cmd', '.bat']
    for directory in path_env.split(os.pathsep):
        if not directory: continue
        for extension in extensions:
            candidate = Path(directory) / (name + extension)
            if candidate.is_file() and _allowed_executable(candidate): return candidate
    raise LedgerError('Command not found on PATH (Store aliases and venv redirectors are skipped): ' + name[:80])


def environment(runtime, task_id):
    env = {k: v for k, v in os.environ.items() if not SECRET_ENV.search(k) and not k.upper().startswith(DROP_ENV)}
    tmp = home(runtime, task_id) / 'tmp'; tmp.mkdir(exist_ok=True)
    env['TEMP'] = env['TMP'] = str(tmp)
    env.setdefault('CI', 'true')
    env['PYTHONDONTWRITEBYTECODE'] = '1'  # no stale bytecode, no __pycache__ in the workspace diff
    return env


def refuse_arguments(runtime, state, argv):
    """Arguments may not point into the user's project or the OneCrew state (the workspace itself is allowed)."""
    project = Path(runtime.ledger.project).resolve(); state_root = Path(runtime.ledger.state_root).resolve()
    workspace = ws_root(state).resolve()
    protected = [project, state_root]
    for argument in argv:
        for match in ABSOLUTE.findall(argument):
            try: target = Path(match.rstrip('.:')).resolve()
            except (OSError, ValueError): raise LedgerError('Unresolvable absolute path argument refused.')
            if target.is_relative_to(workspace): continue
            if any(target == p or target.is_relative_to(p) for p in protected):
                raise LedgerError('Argument points into the user project or OneCrew state; use workspace-relative paths.')
    name = Path(argv[0]).name.lower()
    if name in ('git', 'git.exe', 'git.cmd'):
        words = [a for a in argv[1:] if not a.startswith('-')]
        if words and words[0].lower() in GIT_REFUSED: raise LedgerError('git ' + words[0] + ' is not available in the workspace.')
        if any(a in ('--global', '--system') for a in argv): raise LedgerError('Global/system Git configuration is refused.')


def command_line(executable, argv):
    if executable.suffix.lower() in ('.cmd', '.bat'):
        if any(re.search(r'[&|<>^%!"\r\n]', a) for a in argv[1:]):
            raise LedgerError('Script arguments with shell metacharacters are refused.')
        inner = subprocess.list2cmdline([str(executable), *argv[1:]])
        comspec = os.environ.get('COMSPEC', r'C:\Windows\System32\cmd.exe')
        return f'"{comspec}" /d /s /c "{inner}"'
    return [str(executable), *argv[1:]]


def _spawn(line, cwd, env, out, err):
    from .supervisor import Job
    job = Job()
    child = subprocess.Popen(line, cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=out, stderr=err,
                             creationflags=0x4 | 0x08000000)
    try:
        job.assign(child)
        nt = ctypes.WinDLL('ntdll'); nt.NtResumeProcess.argtypes = [w.HANDLE]
        if nt.NtResumeProcess(w.HANDLE(int(child._handle))) != 0: raise LedgerError('Cannot resume contained command.')
    except Exception:
        child.kill(); job.close(); raise
    return child, job


def _tail(path, head=1500, tail=6000):
    data = path.read_bytes() if path.exists() else b''
    text = data.decode('utf-8', errors='replace')
    if len(text) <= head + tail: return text, len(data)
    return text[:head] + f'\n[... {len(text) - head - tail} characters omitted; full log retained ...]\n' + text[-tail:], len(data)


def run(runtime, task_id, state, contract, args, guard):
    if not contract['authority']['commands']: raise LedgerError('Commands are not authorized by the work contract.')
    argv = argv_value(args.get('argv'))
    cwd = safe_file(ws_root(state), relative_dir(args.get('cwd'))) if args.get('cwd') not in (None, '', '.') else ws_root(state)
    if not cwd.is_dir(): raise LedgerError('cwd is not a workspace directory.')
    timeout = args.get('timeout_seconds', 300)
    if type(timeout) is not int or not 1 <= timeout <= RUN_SECONDS: raise LedgerError(f'timeout_seconds: 1-{RUN_SECONDS}.')
    env = environment(runtime, task_id)
    executable = which(argv[0], env.get('PATH', ''))
    refuse_arguments(runtime, state, [str(executable), *argv[1:]])
    line = command_line(executable, argv)
    logs = home(runtime, task_id) / 'logs'; logs.mkdir(exist_ok=True)
    token = f"{state['step']:04d}-{uuid.uuid4().hex[:8]}"
    outpath, errpath = logs / (token + '.out'), logs / (token + '.err')
    if args.get('background'):
        return start_background(runtime, task_id, state, line, cwd, env, outpath, errpath, argv, executable)
    started = time.monotonic(); reason = None
    with outpath.open('wb') as out, errpath.open('wb') as err:
        child, job = _spawn(line, cwd, env, out, err)
        try:
            deadline = started + timeout
            while child.poll() is None:
                guard()
                if time.monotonic() >= deadline: reason = 'timeout'; break
                if max(outpath.stat().st_size, errpath.stat().st_size) > OUTPUT_CAP: reason = 'output_limit'; break
                time.sleep(.05)
        finally:
            try: job.stop()
            finally:
                if child.poll() is None: child.kill()
                child.wait(timeout=10); job.close()
    stdout, out_bytes = _tail(outpath); stderr, err_bytes = _tail(errpath)
    result = {'argv': argv, 'cwd': str(cwd.relative_to(ws_root(state))).replace('\\', '/') if cwd != ws_root(state) else '',
              'executable': str(executable), 'exit_code': None if reason else child.returncode, 'stopped': reason,
              'seconds': round(time.monotonic() - started, 2), 'stdout': stdout, 'stderr': stderr,
              'stdout_bytes': out_bytes, 'stderr_bytes': err_bytes, 'log': token,
              'tests': test_counts(stdout + '\n' + stderr)}
    result['hint'] = diagnose(result)
    state['work'].setdefault('commands', []).append({k: result[k] for k in ('argv', 'cwd', 'exit_code', 'stopped', 'tests', 'log')})
    return result


def start_background(runtime, task_id, state, line, cwd, env, outpath, errpath, argv, executable):
    running = _RUNNING.setdefault(task_id, {})
    alive = {k: v for k, v in running.items() if v[0].poll() is None}
    if len(alive) >= BACKGROUND_LIMIT: raise LedgerError(f'At most {BACKGROUND_LIMIT} background processes; stop one first.')
    out, err = outpath.open('wb'), errpath.open('wb')
    child, job = _spawn(line, cwd, env, out, err)
    identifier = 'P' + uuid.uuid4().hex[:8]
    record = {'id': identifier, 'argv': argv, 'executable': str(executable), 'pid': child.pid, 'log': outpath.stem,
              'started_step': state['step'], 'runner_pid': os.getpid()}
    running[identifier] = (child, job, record, out, err)
    state['work'].setdefault('processes', {})[identifier] = dict(record, status='running')
    return dict(record, status='running', note='Contained in a Job object owned by this runner; it stops with the task or the runner.')


def process(runtime, task_id, state, args):
    identifier = args.get('id'); record = state['work'].get('processes', {}).get(identifier)
    if not record: raise LedgerError('Unknown background process id.')
    entry = _RUNNING.get(task_id, {}).get(identifier)
    if entry is None and record['status'] == 'running':
        record['status'] = 'lost_with_previous_runner'  # its Job was killed when that runner exited
    op = args.get('op', 'status')
    if op not in ('status', 'output', 'stop'): raise LedgerError('op: status, output or stop.')
    if entry:
        child, job, _, out, err = entry
        if op == 'stop' or child.poll() is not None:
            if op == 'stop' and child.poll() is None:
                try: job.stop()
                except LedgerError: child.kill()
            child.wait(timeout=10); out.close(); err.close(); job.close()
            _RUNNING[task_id].pop(identifier, None)
            record['status'] = 'stopped' if op == 'stop' else 'exited'; record['exit_code'] = child.returncode
    logs = home(runtime, task_id) / 'logs'
    result = dict(record)
    if op == 'output' or record['status'] != 'running':
        result['stdout'], _ = _tail(logs / (record['log'] + '.out'), 1000, 4000)
        result['stderr'], _ = _tail(logs / (record['log'] + '.err'), 500, 3000)
    return result


def stop_all(task_id, state):
    for identifier in list(_RUNNING.get(task_id, {})):
        child, job, _, out, err = _RUNNING[task_id].pop(identifier)
        try:
            if child.poll() is None: job.stop()
        except LedgerError: child.kill()
        finally:
            child.wait(timeout=10); out.close(); err.close(); job.close()
        state['work'].get('processes', {}).get(identifier, {})['status'] = 'stopped_by_core'
    for record in state.get('work', {}).get('processes', {}).values():
        if record['status'] == 'running': record['status'] = 'lost_with_previous_runner'


def test_counts(text):
    found = {}
    for name, pattern in (('unittest', r'Ran (\d+) tests? in'), ('pytest', r'=+ .*?(\d+) passed'),
                          ('dart', r'\+(\d+)(?: ~\d+)?(?: -\d+)?: (?:All tests passed|Some tests failed)'),
                          # node --test: TAP (`# pass N`) or the spec reporter Node 24 prints by default (`ℹ pass N`).
                          ('jest', r'Tests:\s+(?:\d+ \w+, )*(\d+) passed'), ('node', r'^(?:# |ℹ )pass (\d+)'),
                          ('mocha', r'(\d+) passing'), ('go', r'^ok\s+\S+')):
        matches = re.findall(pattern, text, re.M)
        if matches:
            found[name] = sum(int(m) for m in matches) if name != 'go' else len(matches)
    skipped = re.findall(r'skipped=(\d+)|(\d+) skipped|~(\d+):|^(?:# skip|ℹ skipped) (\d+)', text, re.M)
    result = {'frameworks': sorted(found), 'passed_or_run': sum(found.values()) if found else None,
              'skipped': sum(int(next(x for x in t if x)) for t in skipped) if skipped else 0}
    if re.search(r'FAILED \(|(\d+) failed|Some tests failed|^(?:# |ℹ )fail [1-9]', text, re.M): result['failures_reported'] = True
    return result


def diagnose(result):
    text = (result['stderr'] + '\n' + result['stdout'])[-8000:].lower()
    if result['stopped'] == 'timeout': return 'environment: command timed out (raise timeout_seconds within the budget, or run it in the background)'
    if re.search(r'is not recognized as an internal|command not found|no such file or directory.*\b(dart|flutter|node|npm|python)\b', text):
        return 'environment: a tool is missing from PATH'
    if re.search(r'modulenotfounderror|cannot find module|could not resolve|package .* not found|pub get|npm (ci|install)', text):
        return 'environment: dependencies/cache missing (restore them inside the workspace)'
    if re.search(r'lock(ed)? (file|by another)|\.lock\b|resource busy|access is denied|being used by another process', text):
        return 'environment: a lock or file in use (inspect stale locks inside the workspace)'
    if re.search(r'getaddrinfo|econnrefused|network is unreachable|could not resolve host|timed out connecting', text):
        return 'environment: network unavailable'
    if result['exit_code'] not in (0, None) and (result['tests'].get('failures_reported') or result['tests'].get('passed_or_run') is not None):
        return 'product: tests ran and reported failures'
    return None


# --- Git through the core -------------------------------------------------------------------------------------------

def _branch_action(runtime, task_id, repo, ref, commit, key, kind, observe_extra=None, fetch_from=None, advance_from=None):
    """advance_from: only for a ref THIS job created with a verified receipt; compare-and-swap from exactly that commit."""
    control = runtime.control
    payload = {'kind': kind, 'repository': str(repo), 'ref': ref, 'commit': commit, 'executor': 'onecrew-core'}
    if advance_from: payload['advance_from'] = advance_from
    with runtime.ledger.transaction() as conn:
        old = conn.execute('SELECT * FROM actions WHERE task_id=? AND request_key=?', (task_id, key)).fetchone()

    def observe(value):
        found = git(repo, 'show-ref', '--verify', '--hash', value['ref'], allow_failure=True)
        return dict(value, verified=found is not None and found.decode().strip() == value['commit'],
                    observed=found.decode().strip() if found else None, checkout_modified=False, index_modified=False, pushed=False)
    if old:
        action = dict(old)
        if json.loads(action['payload']) != payload: raise LedgerError('Branch intent differs from its existing action.')
    else:
        existing = git(repo, 'show-ref', '--verify', '--hash', ref, allow_failure=True)
        if existing and not (advance_from and existing.decode().strip() == advance_from):
            return {'status': 'exists', 'ref': ref, 'commit': existing.decode().strip(), 'requested_commit': commit,
                    'effect': 'none: an existing ref is never overwritten'}
        action = control.propose_action(task_id, key, payload)
    if action['status'] == 'proposed':
        control.authorize_action(action['id'], action['revision']); action['status'] = 'authorized'
    if action['status'] in ('unknown', 'executing'):
        return control.reconcile_action(action['id'], action['revision'], observe)
    if action['status'] == 'verified':
        return json.loads(action['receipt'])

    def effect(value):
        from .sandbox_gate import task_guard
        task_guard(control, task_id)()
        if fetch_from:
            # Objects only: a workspace-local ref names the commit; the user's refs/checkout are untouched until update-ref.
            git(fetch_from, 'update-ref', 'refs/onecrew/export', value['commit'])
            git(repo, 'fetch', '--no-tags', '--no-write-fetch-head', '--quiet', str(fetch_from), 'refs/onecrew/export', timeout=600)
        git(repo, 'update-ref', '-m', 'onecrew ' + task_id, value['ref'], value['commit'],
            value.get('advance_from') or '0' * len(value['commit']))
        return observe(value)
    return control.execute_action(action['id'], effect)


def create_branch(runtime, task_id, state, contract, args):
    name = branch_name(args.get('name'))
    allowed = contract['authority']['local_branches']
    if name not in allowed:
        raise LedgerError('Branch name not authorized by the work contract (authorized: ' + (', '.join(allowed) or 'none') + ').')
    pinned = state['work']['pins']['head']
    target = pinned if contract['authority']['branch_at'] == 'pinned_head' else contract['authority']['branch_at']
    commit = args.get('commit') or target
    if commit != target: raise LedgerError('Commit not authorized: the contract allows ' + target[:12] + ' only.')
    repo = project_repo(runtime, contract)
    if git(repo, 'cat-file', '-e', commit + '^{commit}', allow_failure=True) is None: raise LedgerError('Commit not found in the repository.')
    receipt = _branch_action(runtime, task_id, repo, 'refs/heads/' + name, commit, 'work:branch:' + content_hash(name)[:24], 'local_branch')
    record = {'name': name, 'ref': 'refs/heads/' + name, 'receipt': receipt}
    state['work'].setdefault('branches', []).append(record)
    if receipt.get('status') not in ('verified', 'exists'):
        from .owned_git import EffectUnknown
        raise EffectUnknown('Branch effect unconfirmed; resume reconciles the existing action without creating it again.')
    return receipt


def workspace_commit(state, contract, args):
    if not contract['authority']['edit']: raise LedgerError('Edits are not authorized by the work contract.')
    message = args.get('message')
    if not isinstance(message, str) or not 3 <= len(message) <= 500: raise LedgerError('message: 3-500 characters.')
    root = ws_root(state)
    git(root, 'add', '-A')
    if git(root, 'diff', '--cached', '--quiet', allow_failure=True) is not None: raise LedgerError('Nothing to commit in the workspace.')
    git(root, 'commit', '--quiet', '--no-verify', '-m', message)
    sha = git(root, 'rev-parse', 'HEAD').decode().strip()
    state['work']['workspace_commit'] = sha
    return {'commit': sha, 'where': 'isolated workspace only'}


def export_branch(runtime, task_id, state, contract, args):
    name = branch_name(args.get('name'))
    if name not in contract['authority']['local_branches']: raise LedgerError('Branch name not authorized by the work contract.')
    sha = state['work'].get('workspace_commit')
    root = ws_root(state)
    if not sha or git(root, 'rev-parse', 'HEAD').decode().strip() != sha: raise LedgerError('Commit the workspace first (workspace_commit).')
    if git(root, 'status', '--porcelain'): raise LedgerError('Workspace has uncommitted changes after its commit.')
    repo = project_repo(runtime, contract)
    # A branch this job itself created (verified create_branch receipt, still at that commit) may be advanced to the work;
    # held-out run H1-r1 (13/10/2026) created its delivery branch first and could not land the work on it.
    own = [b['receipt']['result']['commit'] for b in state['work'].get('branches', []) if b['name'] == name
           and b['receipt'].get('status') == 'verified' and b['receipt'].get('result', {}).get('kind') == 'local_branch']
    current = git(repo, 'show-ref', '--verify', '--hash', 'refs/heads/' + name, allow_failure=True)
    advance = own[-1] if own and current and current.decode().strip() == own[-1] else None
    receipt = _branch_action(runtime, task_id, repo, 'refs/heads/' + name, sha, 'work:export:' + content_hash([name, advance])[:24],
                             'exported_branch', fetch_from=root, advance_from=advance)
    state['work'].setdefault('branches', []).append({'name': name, 'ref': 'refs/heads/' + name, 'receipt': receipt})
    if receipt.get('status') not in ('verified', 'exists'):
        from .owned_git import EffectUnknown
        raise EffectUnknown('Exported branch unconfirmed; resume reconciles it.')
    return receipt


def changed_files(state):
    root = ws_root(state); base = state['work']['pins']['head']
    git(root, 'add', '-A')
    raw = git(root, 'diff', '--cached', '--name-status', '-z', '--no-renames', base) or b''
    parts = [p.decode('utf-8', errors='replace') for p in raw.split(b'\0') if p]
    return [{'status': parts[i], 'path': parts[i + 1]} for i in range(0, len(parts) - 1, 2)]


def _clean_blob(repo, path, name):
    """The blob Git would store for a working file under the repository's own line-ending/filter configuration."""
    return git(repo, 'hash-object', '--path=' + name, str(path)).decode().strip()


def apply(runtime, task_id, state, contract, args):
    """Copy the workspace changes into the user's checkout: only granted, only onto files untouched since the pin
    (compared as Git blobs, so CRLF checkouts are not mistaken for edits), with a rollback copy."""
    if not contract['authority']['apply_to_project']: raise LedgerError('Applying to the project is not authorized by the work contract.')
    repo = project_repo(runtime, contract); root = ws_root(state); base = state['work']['pins']['head']
    changes = changed_files(state)
    if not changes: raise LedgerError('No workspace changes to apply.')
    payload = {'kind': 'apply', 'repository': str(repo), 'base': base,
               'files': [{'path': c['path'], 'status': c['status'],
                          'blob': None if c['status'] == 'D' else _clean_blob(root, root / c['path'], c['path'])} for c in changes]}
    control = runtime.control
    backup = home(runtime, task_id) / 'rollback'

    def observe(value):
        ok = all(((repo / f['path']).is_file() and _clean_blob(repo, repo / f['path'], f['path']) == f['blob'])
                 if f['blob'] else not (repo / f['path']).exists() for f in value['files'])
        return dict(value, verified=ok, rollback=str(backup))
    def untouched(value):
        for f in value['files']:
            target = safe_file(repo, f['path'])
            original = git(repo, 'rev-parse', '--verify', '--quiet', base + ':' + f['path'], allow_failure=True)
            current = _clean_blob(repo, target, f['path']) if target.is_file() else None
            if current != (original.decode().strip() if original else None):
                raise LedgerError('Project file changed since the pin; refusing to overwrite: ' + f['path'])
    key = 'work:apply:' + content_hash(payload)[:16]
    with runtime.ledger.transaction() as conn:
        prior = conn.execute('SELECT 1 FROM actions WHERE task_id=? AND request_key=?', (task_id, key)).fetchone()
    if not prior: untouched(payload)  # refuse before any effect exists
    action = control.propose_action(task_id, key, payload)
    if action['status'] == 'proposed':
        control.authorize_action(action['id'], action['revision']); action['status'] = 'authorized'
    if action['status'] in ('unknown', 'executing'):
        receipt = control.reconcile_action(action['id'], action['revision'], observe)
    elif action['status'] == 'verified': receipt = json.loads(action['receipt'])
    else: receipt = None
    if receipt is not None:
        state['work']['applied'] = receipt.get('status') == 'verified'
        if receipt.get('status') != 'verified':
            from .owned_git import EffectUnknown
            raise EffectUnknown('Apply effect unconfirmed; resume reconciles it without writing again.')
        return receipt

    def effect(value):
        untouched(value)  # again under the action, in case the user edited in between
        backup.mkdir(parents=True, exist_ok=True)
        for f in value['files']:
            target = safe_file(repo, f['path'])
            if target.is_file(): durable_write(backup / (content_hash(f['path'])[:16] + '.orig'), target.read_bytes())
            if f['blob'] is None: target.unlink(missing_ok=True)
            else:
                # The workspace checks out with the user's own line-ending rules, so its bytes are what the user would have.
                target.parent.mkdir(parents=True, exist_ok=True); durable_write(target, (root / f['path']).read_bytes())
        durable_write(backup / 'manifest.json', canonical({'files': value['files'], 'base': base}).encode())
        return observe(value)
    receipt = control.execute_action(action['id'], effect)
    state['work']['applied'] = receipt.get('status') == 'verified'
    if receipt.get('status') != 'verified':
        from .owned_git import EffectUnknown
        raise EffectUnknown('Apply effect unconfirmed; resume reconciles it without writing again.')
    return receipt


# --- independent verification and handover --------------------------------------------------------------------------

def _rerun(runtime, task_id, state, contract, item, guard):
    copy = {'argv': item['argv'], 'cwd': item.get('cwd', ''), 'timeout_seconds': min(int(item.get('timeout_seconds', 300)), RUN_SECONDS)}
    result = run(runtime, task_id, state, dict(contract, authority=dict(contract['authority'], commands=True)), copy, guard)
    testlike = bool(re.search(r'test|pytest|unittest|jest|mocha|vitest|spec', ' '.join(item['argv']), re.I))
    ok = result['exit_code'] == 0 and not result['stopped']
    reason = None
    if not ok: reason = 'exit code ' + str(result['exit_code']) + (' (' + result['stopped'] + ')' if result['stopped'] else '')
    elif testlike and result['tests']['passed_or_run'] == 0: reason = 'zero tests ran'; ok = False
    elif testlike and result['tests']['passed_or_run'] and result['tests']['skipped'] >= result['tests']['passed_or_run']:
        reason = 'all tests skipped'; ok = False
    return {'argv': item['argv'], 'cwd': copy['cwd'], 'passed': ok, 'reason': reason, 'exit_code': result['exit_code'],
            'tests': result['tests'], 'testlike': testlike, 'log': result['log'], 'stdout_tail': result['stdout'][-1500:]}


def test_integrity(state, contract):
    findings = []
    if not state.get('work', {}).get('workspace'): return findings
    root = ws_root(state); base = state['work']['pins']['head']
    for change in changed_files(state):
        name, status = change['path'], change['status']
        if not is_test(name): continue
        if status == 'D': findings.append('existing test file deleted: ' + name); continue
        diff = (git(root, 'diff', '--cached', '-U0', base, '--', name) or b'').decode('utf-8', errors='replace')
        added = [l[1:] for l in diff.splitlines() if l.startswith('+') and not l.startswith('+++')]
        removed = [l[1:] for l in diff.splitlines() if l.startswith('-') and not l.startswith('---')]
        if any(SKIP_MARK.search(l) for l in added): findings.append('skip/only marker added in test file: ' + name)
        if status == 'M':
            if not contract['authority']['edit_tests']: findings.append('existing test file modified without edit_tests: ' + name)
            elif sum(len(ASSERTION.findall(l)) for l in removed) > sum(len(ASSERTION.findall(l)) for l in added):
                findings.append('assertions removed from existing test file: ' + name)
    return findings


def verify(runtime, task_id, state, contract, args, guard):
    """Core-run evidence at finish; the worker's word or a single exit code is not proof."""
    from .owned_git import EffectUnknown  # noqa: F401  (actions are checked by the caller as well)
    stop_all(task_id, state)
    work = state['work']; result = {'commands': [], 'checks': [], 'integrity': [], 'preserve': [], 'findings': []}
    declared = args.get('verification') or []
    if not isinstance(declared, list) or len(declared) > 6: raise LedgerError('verification: a list of at most 6 commands.')
    if declared and not contract['authority']['commands']:
        raise LedgerError('Verification commands need the commands authority; this contract is checked by its own checks only.')
    changes = changed_files(state) if work.get('workspace') else []
    result['changed_files'] = changes
    if changes and not declared and not any(c['kind'] == 'command' for c in contract['checks']):
        result['findings'].append('files changed but no verification command was declared for the core to re-run')
    for item in declared:
        if not isinstance(item, dict): raise LedgerError('verification items: {argv, cwd}.')
        item = {'argv': argv_value(item.get('argv')), 'cwd': relative_dir(item.get('cwd')), 'timeout_seconds': item.get('timeout_seconds', 300)}
        value = _rerun(runtime, task_id, state, contract, item, guard)
        result['commands'].append(value)
        if not value['passed']: result['findings'].append('core re-run failed: ' + ' '.join(item['argv'])[:120] + ': ' + value['reason'])
    repo = project_repo(runtime, contract)
    for check in contract['checks']:
        if check['kind'] == 'ref':
            expected = work['pins']['head'] if check['equals'] == 'pinned_head' else check['equals']
            found = git(repo, 'show-ref', '--verify', '--hash', 'refs/heads/' + check['name'], allow_failure=True)
            ok = found is not None and found.decode().strip() == expected
            result['checks'].append({'kind': 'ref', 'name': check['name'], 'expected': expected, 'found': found.decode().strip() if found else None, 'passed': ok})
            if not ok: result['findings'].append(f"contract check failed: refs/heads/{check['name']} != {expected[:12]}")
        else:
            value = _rerun(runtime, task_id, state, contract, check, guard)
            result['checks'].append(dict(value, kind='command'))
            if not value['passed']: result['findings'].append('contract command check failed: ' + ' '.join(check['argv'])[:120])
    result['integrity'] = test_integrity(state, contract)
    result['findings'] += result['integrity']
    created = [b['ref'] for b in work.get('branches', []) if b['receipt'].get('status') == 'verified']
    from .work_contract import preserved
    findings, after = preserved(repo, work['pins'], created, applied=work.get('applied', False))
    result['preserve'] = findings; result['project_after'] = after
    result['findings'] += ['project not preserved: ' + f for f in findings]
    return result


def handover(runtime, task_id, state, contract, verification, report):
    """Deterministic handover written by the core: diff, files, re-run results, receipts and how to roll back."""
    root = home(runtime, task_id) / 'handover'; root.mkdir(exist_ok=True)
    work = state['work']; files = {}
    if work.get('workspace'):
        patch = git(ws_root(state), 'diff', '--cached', '--binary', work['pins']['head']) or b''
        durable_write(root / 'changes.patch', patch); files['patch'] = str(root / 'changes.patch')
    rollback = []
    for branch in work.get('branches', []):
        receipt = branch['receipt']
        if receipt.get('status') == 'verified':
            sha = receipt['result']['commit']
            rollback.append(f"git -C \"{project_repo(runtime, contract)}\" branch -D {branch['name']}   # only while it still points to {sha}")
    if work.get('applied'): rollback.append('restore the files listed in ' + str(home(runtime, task_id) / 'rollback' / 'manifest.json') + ' from the *.orig copies, or git apply -R changes.patch')
    summary = {'task': task_id, 'contract': contract, 'pins': {k: v for k, v in work['pins'].items() if k != 'refs'},
               'workspace': work.get('workspace'), 'changed_files': verification.get('changed_files', []),
               'verification': {k: v for k, v in verification.items() if k != 'changed_files'},
               'branches': work.get('branches', []), 'applied': work.get('applied', False), 'rollback': rollback,
               'executor': 'onecrew-core (Git/commands), worker ' + state['worker']['provider'] + '/' + state['worker']['model'] + ' (decisions)'}
    durable_write(root / 'handover.json', canonical(summary).encode()); files['summary'] = str(root / 'handover.json')
    durable_write(root / 'report.md', report.encode('utf-8')); files['report'] = str(root / 'report.md')
    return files


def inventory(runtime, task_id):
    """Toolchains visible to commands (core-observed facts, not instructions)."""
    path = environment(runtime, task_id).get('PATH', '')
    found = {}
    for name in ('git', 'py', 'python', 'node', 'npm', 'npx', 'dart', 'flutter', 'java', 'gradle', 'dotnet', 'go', 'cargo', 'mvn', 'make', 'pwsh', 'powershell'):
        try: found[name] = str(which(name, path))
        except LedgerError: pass
    return {'os': 'windows' if os.name == 'nt' else os.name, 'tools': found,
            'note': 'Store python aliases and venv redirectors are not runnable; use py or an absolute interpreter path.'}


def facts(runtime):
    """Commands the core itself re-ran successfully in completed work jobs of this project (hints, never authority)."""
    rows = []
    with runtime.ledger.transaction() as conn:
        if conn is None: return rows
        for row in conn.execute("SELECT e.payload FROM events e JOIN tasks t ON t.id=e.task_id WHERE t.project_id=? AND "
                                "e.kind='project.fact' ORDER BY e.seq DESC LIMIT 40", (runtime.ledger.project_id,)):
            value = json.loads(row['payload'])
            key = canonical([value.get('argv'), value.get('cwd')])
            if key not in {canonical([r.get('argv'), r.get('cwd')]) for r in rows}: rows.append(value)
    return rows[:8]
