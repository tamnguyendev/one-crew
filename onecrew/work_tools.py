"""Generic execution tools for work contracts: an isolated Git workspace, bounded host commands and processes, Git
effects through the core with receipts, independent verification and a handover. The worker chooses; the core enforces.

Containment, stated plainly (GX-P1-01, 13/10/2026):
- Commands are *contained* unless the user granted authority.unconfined_commands: a restricted Low-integrity token
  (onecrew.contain) lets Windows refuse every write outside the task's workspace, temp and cache directories, so the
  user's project, the OneCrew state/ledger and the user profile cannot be written by any program a command runs. The
  workspace's Git directory lives outside that region, so commands cannot rewrite the configuration the core relies on.
  Contained commands can still READ what the user can read and use the network; this is a write boundary, not a
  read/network sandbox. Every command tree runs in a Job object (killed on timeout, cancel or runner exit).
- What a command, a write or a background process changed is judged by its effect, not by the tool: the core computes
  the workspace delta against the pinned commit with its own index, and only changes within edit authority and
  scope.paths can be committed, exported, applied or handed over.
- Verification is bound to the exact candidate tree and re-checked against the real refs and project files at
  verification and again at completion (GX-P1-03). Side-effecting actions leave a durable intent; a restart reconciles
  it and never re-runs a command whose outcome is unknown (GX-P1-02)."""
import ctypes
from ctypes import wintypes as w
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
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
TEST_FILE = re.compile(r'(^|/)(tests?|__tests__|__snapshots__|spec|specs|test_driver|integration_test|cypress)/|'
                       r'(^|/)(test_[^/]*\.(py|rb)|tests\.py|conftest\.py|setupTests\.[cm]?[jt]sx?)$|_test\.(py|dart|go|rb)$|'
                       r'\.(test|spec|cy)\.[cm]?[jt]sx?$|Tests?\.(java|kt|cs|swift)$|_spec\.rb$', re.I)
SKIP_MARK = re.compile(r'@(unittest\.)?skip|pytest\.mark\.(skip|xfail)|\b(xit|xdescribe|xtest)\s*\(|\b(it|test|describe)\.(skip|only|todo)\s*\(|'
                       r'\bskip\s*:\s*(true|[\'"])|\bmarkTestSkipped\b|t\.Skip\(|@Disabled|@Ignore', re.I)
ASSERTION = re.compile(r'\bassert\w*\b|\bexpect\s*\(|\bshould\b|\bverify\s*\(', re.I)
EFFECTS = ('write', 'edit', 'run', 'process', 'restore', 'workspace_commit', 'create_branch', 'export_branch', 'apply')
CACHES = {'npm_config_cache': 'npm', 'PIP_CACHE_DIR': 'pip', 'YARN_CACHE_FOLDER': 'yarn', 'GOCACHE': 'go-build', 'XDG_CACHE_HOME': 'xdg'}
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


def boundary(contract):
    return 'unconfined' if contract['authority'].get('unconfined_commands') else 'contained'


# --- workspace ---------------------------------------------------------------------------------------------------

def create_workspace(runtime, task_id, contract, base):
    """Idempotent isolated clone at the pinned commit; the user's repository is only read (objects shared read-only).
    Layout: home/r is the work tree (Low label when contained), home/git its Git directory (never Low), home/meta the
    core's copy of that directory's configuration, home/logs, handover and rollback are core-only."""
    root = home(runtime, task_id); target = root / 'r'; gitdir = root / 'git'
    record = {'path': str(target), 'base': base, 'repository': contract['scope']['repository']}
    if gitdir.is_dir() or (target / '.git').exists():
        layout = 'separate' if gitdir.is_dir() else 'legacy'
        if git(target, 'rev-parse', 'HEAD^{commit}', allow_failure=True, git_dir=gitdir if layout == 'separate' else None) is None:
            raise LedgerError('Workspace exists but is unreadable.')
        return dict(record, layout=layout)
    if target.exists(): shutil.rmtree(target)
    source = project_repo(runtime, contract)
    contained = boundary(contract) == 'contained'
    target.mkdir()
    if contained:
        from .contain import private
        private(root)  # owner-independent: readable by the task's contained commands, writable by the core only
        _protect_task(root, target)
    # A shared clone reads the user's object store through alternates; when this task's contained commands cannot read it
    # (an owner-only ACL), Git in the workspace would fail with "bad object HEAD", so the objects are copied instead.
    shared = not contained or _contained_reads(runtime, task_id, source, base)
    git(root, 'clone', '--shared' if shared else '--no-hardlinks', '--no-checkout', '--quiet', '--separate-git-dir=' + str(gitdir),
        str(source), 'r', timeout=600)
    hooks = runtime.ledger.state_root / 'empty-hooks'; hooks.mkdir(parents=True, exist_ok=True)
    for key, value in (('core.longpaths', 'true'), ('core.hooksPath', str(hooks)), ('user.name', 'OneCrew'),
                       ('user.email', 'onecrew@localhost'), ('commit.gpgSign', 'false')):
        git(target, 'config', key, value, git_dir=gitdir)
    for key in ('core.autocrlf', 'core.eol', 'core.safecrlf'):  # the same line-ending rules as the user's checkout
        value = git(source, 'config', '--get', key, allow_failure=True)
        if value: git(target, 'config', key, value.decode().strip(), git_dir=gitdir)
    git(target, 'checkout', '--quiet', '--detach', base, timeout=600, git_dir=gitdir, work_tree=target)
    git(target, 'remote', 'remove', 'origin', allow_failure=True, git_dir=gitdir)
    if git(target, 'remote', git_dir=gitdir) not in (b'', None): raise LedgerError('Workspace still has a remote; refusing to continue.')
    if contained:
        from .contain import own
        for path in (gitdir, target / '.git'): own(path)  # Git's ownership check reads these (safe.directory)
    (root / 'tmp').mkdir(exist_ok=True); (root / 'logs').mkdir(exist_ok=True); (root / 'cache').mkdir(exist_ok=True)
    meta = root / 'meta'; meta.mkdir(exist_ok=True); durable_write(meta / 'empty-exclude', b'')
    for name in ('config', 'info/exclude', 'info/attributes'):
        if (gitdir / name).is_file(): durable_write(meta / name.replace('/', '-'), (gitdir / name).read_bytes())
    return dict(record, layout='separate', boundary=boundary(contract), labelled=contained,
                protected=BOUNDARY_RULES if contained else False, home_private=BOUNDARY_RULES if contained else False,
                task_key=root.name, objects='shared' if shared else 'copied')


def _contained_reads(runtime, task_id, source, revision):
    """Can a contained command of this task read `revision` from the user's repository (as Git in a shared clone would)?"""
    root = home(runtime, task_id); logs = root / 'logs'; logs.mkdir(exist_ok=True)
    env = environment(runtime, task_id)
    safe = 'safe.directory=' + str(Path(source).resolve()).replace('\\', '/')  # readability is asked, not Git's ownership rule
    try: line = command_line(which('git', env.get('PATH', '')), ['git', '-c', safe, '-C', str(source), 'cat-file', '-e', revision + '^{commit}'])
    except LedgerError: return False
    with open(logs / 'objects-probe.out', 'wb') as out, open(logs / 'objects-probe.err', 'wb') as err:
        child, job = _spawn(line, str(root / 'tmp'), env, out, err, contained=True, task=root.name)
        try: return child.wait(60) == 0
        except subprocess.TimeoutExpired: child.kill(); return False
        finally: job.close()


def ws_root(state):
    value = (state.get('work') or {}).get('workspace')
    if not value: raise LedgerError('No workspace: the contract grants neither edit nor commands; use the read-only project tools.')
    return Path(value['path'])


def _home(state):
    return ws_root(state).parent


def gitdir(state):
    separate = _home(state) / 'git'
    return separate if (state['work']['workspace'].get('layout') == 'separate' or separate.is_dir()) else ws_root(state) / '.git'


def wgit(state, *args, **kw):
    """Core Git on the workspace, always naming its own Git directory and work tree explicitly."""
    root = ws_root(state); directory = gitdir(state)
    if (not directory.is_dir() or directory.is_symlink() or getattr(directory, 'is_junction', lambda: False)()
            or (directory / 'commondir').exists()):
        raise LedgerError('The workspace Git directory is not the one the core created; refusing to use it.')
    return git(root, *args, git_dir=directory, work_tree=root, **kw)


def _guard_metadata(state):
    """The workspace Git configuration belongs to the core (filters, excludes and attributes would change what the core
    sees or runs). Contained commands cannot reach it; an unconfined command that changed it is undone and recorded."""
    meta = _home(state) / 'meta'; directory = gitdir(state)
    if not meta.is_dir(): return []
    restored = []
    for name in ('config', 'info/exclude', 'info/attributes'):
        saved = meta / name.replace('/', '-'); live = directory / name
        want = saved.read_bytes() if saved.is_file() else None
        have = live.read_bytes() if live.is_file() else None
        if have != want:
            if want is None: live.unlink()
            else: durable_write(live, want)
            restored.append(name)
    if restored: state['work'].setdefault('metadata_restored', []).append({'step': state.get('step'), 'paths': restored})
    return restored


def snapshot(state, changes=True):
    """The workspace as the core sees it: every non-ignored file (whoever wrote it), as a Git tree, and (changes=True) its
    changes against the pinned commit. Uses the core's own index; the repository's committed .gitignore decides what is
    generated output."""
    base = state['work']['pins']['head']; root = _home(state)
    _guard_metadata(state)
    environment = {'GIT_INDEX_FILE': str(root / 'core.index')}
    if not (root / 'core.index').is_file(): wgit(state, 'read-tree', base, env=environment)
    exclude = root / 'meta' / 'empty-exclude'
    if not exclude.is_file(): durable_write(exclude, b'')
    wgit(state, '-c', 'core.excludesFile=' + str(exclude), 'add', '-A', '--', '.', env=environment, timeout=600)
    tree = wgit(state, 'write-tree', env=environment).decode().strip()
    return {'tree': tree, 'changes': tree_changes(state, base, tree) if changes else None}


MUTATING = ('write', 'edit', 'run', 'process', 'restore', 'workspace_commit', 'apply')
INPUT_RERUNS = 2  # re-runs of one failed command on the same candidate tree after only Git-ignored inputs changed (P4-C)


# What tools rewrite on every run and no command reads as an input: logs, caches, bytecode. Their content never counts as a
# change of the workspace (a timestamped log or a refreshed cache must not turn a real loop into progress).
VOLATILE_DIRS = frozenset(('.cache', '__pycache__', '.pytest_cache', '.mypy_cache', '.ruff_cache', '.hypothesis', '.nyc_output',
                           'htmlcov', 'logs', 'log', 'tmp', 'temp'))
VOLATILE_SUFFIXES = ('.log', '.pyc', '.pyo', '.tmp', '.temp', '.swp', '.pid')
ENTRY_FILES = 2000            # files described per top-level ignored entry (each entry has its own budget)
ENTRY_HASH_BYTES = 8_000_000  # content hashed per top-level ignored entry; beyond it, path and size only
IGNORED_FILE_HASH = 2_000_000  # a single ignored file larger than this is described by its size only
SUMMARY_FILES = 20000         # a dependency tree is summarised (file count, total size) up to this many files
DEPENDENCY_DIRS = frozenset(('node_modules', '.venv', 'venv', 'env', 'site-packages', '.tox', '.nox', 'vendor', '.gradle', 'pods'))


def _volatile(name):
    parts = name.replace('\\', '/').strip('/').split('/')
    return any(p.lower() in VOLATILE_DIRS for p in parts[:-1]) or parts[-1].lower() in VOLATILE_DIRS \
        or parts[-1].lower().endswith(VOLATILE_SUFFIXES)


def ignored_inputs(state):
    """The files Git ignores in the workspace that a command can read as input (generated sources and data, fetched or installed
    files): path, size and content hash, without logs, caches and bytecode. Bounded in files and hashed bytes; deterministic.
    P4-C (Codex deep review P3): a test that failed for a missing generated file was refused after the build created it,
    because only the Git tree (which never contains ignored files) was compared."""
    environment = {'GIT_INDEX_FILE': str(_home(state) / 'core.index')}
    raw = wgit(state, 'ls-files', '--others', '--ignored', '--exclude-standard', '--directory', '-z', env=environment,
               timeout=600) or b''
    root = ws_root(state); entries = []; truncated = False
    def walk(top, limit):
        for directory, subdirs, names in os.walk(top, followlinks=False):
            subdirs[:] = sorted(d for d in subdirs if d.lower() not in VOLATILE_DIRS and not os.path.islink(os.path.join(directory, d)))
            for n in sorted(names):
                if not n.lower().endswith(VOLATILE_SUFFIXES):
                    yield Path(directory) / n; limit -= 1
                    if limit <= 0: return
    for name in sorted(p.decode('utf-8', 'replace') for p in raw.split(bytes(1)) if p):
        if _volatile(name): continue
        top = root / name.rstrip('/')
        if top.is_symlink() or not top.exists(): continue
        relative = top.relative_to(root).as_posix()
        if top.is_dir() and top.name.lower() in DEPENDENCY_DIRS:
            # Installed dependencies: their file count and total size, not their content (hashing them on every action would cost
            # seconds). P4b-R4 (Codex review of P4): the key then cannot see a change of content, so it is marked incomplete
            # (`truncated`) and is never trusted alone; the size was also computed but left out of the key.
            count = size = 0
            for path in walk(top, SUMMARY_FILES + 1):
                try: size += path.lstat().st_size; count += 1
                except OSError: pass
            entries.append([relative + '/', count, size, 'summary' if count <= SUMMARY_FILES else 'summary-truncated'])
            truncated = True
            continue
        # Each top-level entry has its own budget, so one large ignored tree never hides another (a generated file).
        hashed = 0; described = 0
        for path in ([top] if top.is_file() else walk(top, ENTRY_FILES + 1)):
            if described >= ENTRY_FILES: truncated = True; entries.append([relative + '/', described, 'truncated']); break
            try: size = path.lstat().st_size
            except OSError: continue  # removed while listing
            digest = None
            if size <= IGNORED_FILE_HASH and hashed + size <= ENTRY_HASH_BYTES:
                try: digest = hashlib.sha256(path.read_bytes()).hexdigest(); hashed += size
                except OSError: digest = 'unreadable'
            if digest is None or digest == 'unreadable':
                truncated = True  # P4b-R4: a file described by its size only (or unread) hides a same-size change
            entries.append([path.relative_to(root).as_posix(), size, digest]); described += 1
    return entries, truncated


def progress_state(state, tree=None):
    """The workspace as the worker's reads and commands can observe it, as one durable key shared by the progress guard, the
    failed-command check and the failed-read replay (P4-C): the candidate tree (every non-ignored file) plus the ignored
    input files with their content (ignored_inputs). Logs, caches and timings are left out, so they never count as a change;
    a no-op write or a command that changed nothing leaves the key unchanged. Codex review 07d7ad6 (R1) introduced the key."""
    tree = tree or snapshot(state, changes=False)['tree']
    entries, truncated = ignored_inputs(state)
    # truncated: the key does not describe every input by content (summarised dependencies, unhashed or unread files, entries
    # over budget). An unchanged incomplete key is never proof that nothing changed: the failed-command check and the failed-read
    # replay then allow a bounded retry instead of refusing (P4b-R4).
    return {'tree': tree, 'ignored': len(entries), 'truncated': truncated,
            'key': content_hash({'tree': tree, 'ignored': entries})}


def changed_since(state, index):
    """Whether an action that can change the workspace ran after receipt `index` (None: not known, so it may have): a successful
    write, edit or command (MUTATING), or a background process, which may change files at any time — one started after that
    receipt, or one started before it that is not known to have ended (running, or lost with a previous runner)."""
    if index is None: return True
    if any(p.get('status') in ('running', 'lost_with_previous_runner')
           for p in ((state.get('work') or {}).get('processes') or {}).values()): return True
    for ref in (state.get('receipts') or [])[index + 1:]:
        if ref.get('background') or (ref.get('action') in MUTATING and ref.get('successful')): return True
    return False


def key_unproven(state, observed, since, earlier_partial=False):
    """The one trust rule of the workspace key, shared by the failed-command check (run), the failed-read replay (owned._tool)
    and the progress guard (progress.observe). An unchanged key proves that nothing changed when it describes every input by
    content, at both observations compared, or when nothing that can change files ran since receipt `since`. Otherwise it proves
    nothing (True here) and none of them concludes 'unchanged': the failed-command check allows INPUT_RERUNS re-runs per command
    and candidate tree, the failed-read replay runs the read again, the progress guard allows INPUT_RERUNS repeats of a result.
    P4b-R4 (Codex review of P4b): the progress guard alone used to trust an incomplete key."""
    return (bool((observed or {}).get('truncated')) or bool(earlier_partial)) and changed_since(state, since)


def tree_changes(state, old, new):
    raw = wgit(state, 'diff-tree', '-r', '--name-status', '-z', '--no-renames', old, new) or b''
    parts = [p.decode('utf-8', errors='replace') for p in raw.split(b'\0') if p]
    return [{'status': parts[i], 'path': parts[i + 1]} for i in range(0, len(parts) - 1, 2)]


def in_scope(contract, name):
    paths = contract['scope']['paths']
    return not paths or any(name == p or name.startswith(p.rstrip('/') + '/') for p in paths)


def classify(contract, changes):
    """Changes that cannot be delivered under this contract, whichever tool or command made them."""
    a = contract['authority']; bad = []
    for change in changes:
        name = change['path']
        if not a['edit']: reason = 'the contract grants commands but no edit authority, so file changes cannot be delivered'
        elif not in_scope(contract, name): reason = 'outside scope.paths'
        elif is_test(name) and change['status'] in ('M', 'D', 'T') and not a['edit_tests']: reason = 'existing test file changed without edit_tests'
        else: continue
        bad.append({'path': name, 'status': change['status'], 'reason': reason})
    return bad


def _undeliverable(bad, what):
    listed = '; '.join(f"{b['path']} ({b['reason']})" for b in bad[:12]) + (f' and {len(bad) - 12} more' if len(bad) > 12 else '')
    return LedgerError(f'{what}: the workspace holds changes this contract cannot deliver: {listed}. '
                       'Undo them with restore {paths:[...]} (the pinned version comes back), then try again.')


def view(runtime, state):
    """Discovery root for list/search/read: the workspace when one exists, otherwise the project read-only."""
    work = state.get('work') or {}
    if work.get('workspace'): return Discovery(work['workspace']['path']), 'workspace'
    return Discovery(runtime.ledger.project), 'project'


def file_path(state, contract, name, for_write=False):
    scoped_path(name)
    root = ws_root(state)
    target = safe_file(root, name)
    if for_write and not in_scope(contract, name):
        raise LedgerError('Path outside the contract scope.paths; not authorized to edit.')
    return target


def is_test(name):
    return bool(TEST_FILE.search(name))


def write(state, contract, args, *, edit=False):
    if not contract['authority']['edit']: raise LedgerError('Edits are not authorized by the work contract.')
    name = args['path']; target = file_path(state, contract, name, for_write=True)
    exists = target.is_file()
    if target.exists() and not exists: raise LedgerError('Not a regular file.')
    base_has = wgit(state, 'cat-file', '-e', state['work']['pins']['head'] + ':' + name, allow_failure=True) is not None
    if is_test(name) and base_has and not contract['authority']['edit_tests']:
        raise LedgerError('Existing test files are immutable under this contract; add a new test file or fix production code.')
    current = target.read_bytes() if exists else None
    expected = args.get('expected_sha256')
    if (hashlib.sha256(current).hexdigest() if current is not None else None) != expected:
        raise LedgerError('Stale or missing expected_sha256: read the file first (null only for a new file).')
    data = _new_content(current, args, edit)
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


def _new_content(current, args, edit):
    if edit:
        old, new = args.get('old'), args.get('new')
        if not isinstance(old, str) or not old or not isinstance(new, str): raise LedgerError('edit needs non-empty old and a new string.')
        if current is None: raise LedgerError('edit needs an existing file.')
        text = current.decode('utf-8')
        if text.count(old) != 1: raise LedgerError(f'old string must occur exactly once (found {text.count(old)}).')
        data = text.replace(old, new).encode('utf-8')
    else:
        text = args.get('text')
        if not isinstance(text, str): raise LedgerError('write needs text.')
        data = text.encode('utf-8')
    if len(data) > 1_000_000: raise LedgerError('File edit exceeds 1 MB.')
    scan_text(data)
    return data


def restore(runtime, task_id, state, contract, args):
    """Put workspace paths back to the pinned commit: tracked files come back, files absent there are removed. Allowed
    with edit or commands authority, because it only undoes changes; the way to clear what cannot be delivered."""
    if not (contract['authority']['edit'] or contract['authority']['commands']):
        raise LedgerError('restore needs a workspace (edit or commands authority).')
    paths = args.get('paths')
    if not isinstance(paths, list) or not 1 <= len(paths) <= 200: raise LedgerError('restore: paths, a list of 1-200 workspace paths.')
    base = state['work']['pins']['head']; root = ws_root(state); done = []
    for name in paths:
        safe_file(root, scoped_path(name))
        if wgit(state, 'cat-file', '-e', base + ':' + name, allow_failure=True) is not None:
            wgit(state, 'checkout', base, '--', name)
        wgit(state, 'clean', '-f', '-d', '-q', '--', name)  # untracked, not ignored: what the delta shows
        done.append(name)
    left = snapshot(state)
    # Files absent at the pin that a workspace commit made tracked survive `clean`; they go as well.
    added = [c['path'] for c in left['changes'] if c['status'] == 'A'
             and any(c['path'] == n or c['path'].startswith(n.rstrip('/') + '/') for n in paths)]
    for name in added: safe_file(root, name).unlink(missing_ok=True)
    if added: left = snapshot(state)
    return {'restored': done, 'remaining_changes': len(left['changes']),
            'remaining_undeliverable': classify(contract, left['changes'])[:50]}


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


def environment(runtime, task_id, contract=None, verification=False):
    """verification: the environment of core-run verification commands - their own temp and package caches, which the
    worker's commands cannot write, so what verification uses comes from the candidate or from its recorded setup."""
    env = {k: v for k, v in os.environ.items() if not SECRET_ENV.search(k) and not k.upper().startswith(DROP_ENV)}
    root = home(runtime, task_id); tmp = root / ('vtmp' if verification else 'tmp'); tmp.mkdir(exist_ok=True)
    env['TEMP'] = env['TMP'] = str(tmp)
    env.setdefault('CI', 'true')
    env['PYTHONDONTWRITEBYTECODE'] = '1'  # no stale bytecode, no __pycache__ in the workspace diff
    if contract is not None and boundary(contract) == 'contained':
        cache = root / ('vcache' if verification else 'cache')
        for key, name in CACHES.items(): env[key] = str(cache / name)  # package caches the boundary lets them write
    return env


BOUNDARY_RULES = 5  # task ACL version (2: OWNER RIGHTS, 5: full control for the owning task, no verification identity); re-applied on use
VERIFY_RULES = 3  # version of a stored verification record; a record of another version is not reused for review
HOME_NAME = re.compile(r'[0-9a-f]{16}')
ROOT_RELATIVE = re.compile(r'(?:^|[=,;:\s])([\\/](?![\\/])[^\s"\'<>|;,=]+)')
DRIVE_RELATIVE = re.compile(r'(?:^|[=,;\s])[A-Za-z]:(?![\\/])[^\s"\'<>|;,=:]')
_LEGACY_SCANNED = set()


def _protect_task(root, workspace):
    """A task's own regions (workspace, temp, package cache): full control for the task, refused to every other task."""
    from .contain import protect
    for directory in (workspace, root / 'tmp', root / 'cache'): protect(directory, root.name)
    durable_write(root / 'boundary.json', json.dumps({'rules': BOUNDARY_RULES, 'task_key': root.name}).encode())


def _protect_legacy_homes(base):
    """Workspaces of OTHER tasks made before the per-task boundary (6028118: Low label, inherited DACL) stay writable by any
    contained command until their own task runs again. The first contained run in a process gives each of them its own
    task's rules (the task SID derives from the home name). Review of 4a6bdb9, 13/10/2026."""
    if str(base) in _LEGACY_SCANNED: return
    from .contain import own, private
    def link(path):
        return path.is_symlink() or (hasattr(os.path, 'isjunction') and os.path.isjunction(path))
    for root in sorted(Path(base).iterdir()):
        if not HOME_NAME.fullmatch(root.name) or link(root) or not root.is_dir() or link(root / 'r') or not (root / 'r').is_dir():
            continue  # only OneCrew task homes, and never through a link out of the work root
        try: marker = json.loads((root / 'boundary.json').read_text(encoding='utf-8'))
        except (OSError, ValueError): marker = {}
        if isinstance(marker, dict) and isinstance(marker.get('rules'), int) and marker['rules'] >= BOUNDARY_RULES: continue
        try:
            private(root)
            for path in (root / 'git', root / 'r' / '.git'):
                if path.exists(): own(path)
            _protect_task(root, root / 'r')
        except (OSError, LedgerError):
            continue  # its own task re-protects it on first use; a home that cannot be changed is not this task's to fail on
    _LEGACY_SCANNED.add(str(base))


def ensure_boundary(runtime, task_id, state, contract):
    """Contained commands need their task region protected (per-task ACL + Low label); workspaces made before the per-task
    boundary (Codex review 2, 13/10/2026) get it on first use."""
    if boundary(contract) != 'contained': return 'unconfined'
    from .contain import available, private
    root = home(runtime, task_id)
    ok, reason = available(root.name)
    if not ok:
        raise LedgerError('environment: the command write boundary is unavailable here (' + str(reason) + '); commands cannot run '
                          'contained. Running them with the user\'s full rights needs authority.unconfined_commands from the user.')
    workspace = state['work']['workspace']
    if workspace.get('home_private') != BOUNDARY_RULES:
        from .contain import own
        private(root); workspace['home_private'] = BOUNDARY_RULES
        for path in (root / 'git', ws_root(state) / '.git'):
            if path.exists(): own(path)
    if workspace.get('protected') != BOUNDARY_RULES:
        _protect_task(root, ws_root(state))
        workspace.update(labelled=True, protected=BOUNDARY_RULES, task_key=root.name)
    _protect_legacy_homes(root.parent)
    return 'contained'


def refuse_arguments(runtime, state, argv, base=None):
    """Arguments may not point into the user's project or the OneCrew state (the workspace itself is allowed). Defence in
    depth: the contained boundary refuses such writes anyway; unconfined commands rely on this and on the delivery gate.
    base (verification): only the clean checkout is allowed - never the workspace, its temp or anything else of the task."""
    project = Path(runtime.ledger.project).resolve(); state_root = Path(runtime.ledger.state_root).resolve()
    allowed = Path(base).resolve() if base is not None else ws_root(state).resolve()
    protected = [project, state_root] + ([_home(state).resolve()] if base is not None else
                                         [_home(state).resolve() / 'git', _home(state).resolve() / 'meta'])
    for argument in argv:
        for match in ABSOLUTE.findall(argument):
            try: target = Path(match.rstrip('.:')).resolve()
            except (OSError, ValueError): raise LedgerError('Unresolvable absolute path argument refused.')
            if target.is_relative_to(allowed): continue
            if any(target == p or target.is_relative_to(p) for p in protected):
                if base is not None:
                    raise LedgerError('In verification, path arguments may point only into the clean checkout of the candidate '
                                      '(not the workspace, its temp or the OneCrew state); use checkout-relative paths.')
                raise LedgerError('Argument points into the user project or OneCrew state; use workspace-relative paths.')
        if base is not None:
            # Root-relative (\\ocw\\key\\r, /ocw/key/r) and drive-relative (D:git) spellings name places outside the
            # checkout without a drive letter the absolute-path filter would see (third review, 13/10/2026).
            for match in ROOT_RELATIVE.findall(argument):
                target = Path(Path(base).resolve().anchor + match.lstrip('\\/')).resolve()
                if not target.is_relative_to(allowed) and any(target == p or target.is_relative_to(p) for p in protected):
                    raise LedgerError('In verification, path arguments may point only into the clean checkout (' + argument[:80] + ').')
            if DRIVE_RELATIVE.search(argument):
                raise LedgerError('In verification, drive-relative paths are refused (' + argument[:80] + '); use checkout paths.')
        if base is not None and re.search(r'(^|[^.])\.\.([\\/]|$)', argument):
            # Any '..' path segment, wherever it sits in the argument (--opt=a=../x, file:../x, D:..\x): verification
            # commands work inside the checkout and never need to go above it.
            raise LedgerError('In verification, arguments may not contain a ".." path segment (' + argument[:80] + '); '
                              'use paths inside the clean checkout.')
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


def _spawn(line, cwd, env, out, err, contained=False, task=None):
    from .supervisor import Job
    job = Job()
    if contained:
        from .contain import spawn
        if not task: job.close(); raise LedgerError('A contained command needs its task identity.')
        try: child = spawn(line, cwd, env, out, err, task)
        except BaseException: job.close(); raise
        try: job.assign(child); child.resume()
        except BaseException: child.kill(); job.close(); raise
        return child, job
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


def _record_process(logs, token, child):
    """Who ran this command, on disk outside the writable region, so a later runner can prove its tree is gone."""
    from .supervisor import identity
    try: durable_write(logs / (token + '.pid'), canonical(identity(child.pid)).encode())
    except (OSError, LedgerError): pass


def effects(contract, before, after, state):
    """What one command changed in the workspace, and which of those changes this contract cannot deliver."""
    if before['tree'] == after['tree']: return {'changed_paths': []}
    changed = [c['path'] for c in tree_changes(state, before['tree'], after['tree'])]
    names = set(changed)
    current = after['changes'] if after.get('changes') is not None else tree_changes(state, state['work']['pins']['head'], after['tree'])
    bad = [b for b in classify(contract, current) if b['path'] in names]
    result = {'changed_paths': changed[:200]}
    if bad:
        result['undeliverable_changes'] = bad[:50]
        result['remedy'] = ('These changes cannot be committed, exported, applied or handed over under this contract. Undo them '
                            'with restore {paths:[...]} or a command that does not modify them.')
    return result


def run(runtime, task_id, state, contract, args, guard, repeat_guard=True, base=None):
    """base: run in this directory instead of the workspace (the clean verification checkout); the workspace is then not
    observed, because the command does not run there."""
    if not contract['authority']['commands']: raise LedgerError('Commands are not authorized by the work contract.')
    argv = argv_value(args.get('argv'))
    origin = Path(base) if base is not None else ws_root(state)
    cwd = safe_file(origin, relative_dir(args.get('cwd'))) if args.get('cwd') not in (None, '', '.') else origin
    if not cwd.is_dir(): raise LedgerError('cwd is not a directory of the ' + ('verification checkout.' if base is not None else 'workspace.'))
    timeout = args.get('timeout_seconds', 300)
    if type(timeout) is not int or not 1 <= timeout <= RUN_SECONDS: raise LedgerError(f'timeout_seconds: 1-{RUN_SECONDS}.')
    env = environment(runtime, task_id, contract, verification=base is not None)
    executable = which(argv[0], env.get('PATH', ''))
    refuse_arguments(runtime, state, [str(executable), *argv[1:]], base=base)
    mode = ensure_boundary(runtime, task_id, state, contract)
    identity = home(runtime, task_id).name  # verification commands run as the task too, in the clean checkout (decision 13/10/2026)
    line = command_line(executable, argv)
    logs = home(runtime, task_id) / 'logs'; logs.mkdir(exist_ok=True)
    pending = state['work'].get('intent') or {}
    token = (pending.get('log') if pending.get('action') == 'run' and pending.get('step') == state['step'] else None) \
        or f"{state['step']:04d}-{uuid.uuid4().hex[:8]}"
    outpath, errpath = logs / (token + '.out'), logs / (token + '.err')
    # The intent already holds the tree right before this command (written by the coordinator); otherwise take it now.
    observe = base is None
    before = ({'tree': pending['tree']} if pending.get('log') == token and pending.get('tree') else snapshot(state, changes=False)) if observe else None
    where = str(cwd.relative_to(origin)).replace('\\', '/') if cwd != origin else ''
    inputs_rerun = False
    if repeat_guard and observe and not args.get('background'):
        # Acceptance run N2-r2 (13/10/2026) ran the same failing test command five times with no change in between; its
        # timings differed, so no repeat was noticed. A failed command is not run again until the command or the
        # workspace changed. The core's own verification re-runs are exempt.
        # P4-C: "the workspace" is the shared workspace key (candidate tree + ignored inputs by content, without logs and
        # caches). A change of ignored inputs only (a build that generated the missing file) allows a bounded number of
        # re-runs of that command on the same candidate tree.
        commands = state['work'].get('commands', [])
        for earlier in reversed(commands):
            if earlier.get('argv') != argv or earlier.get('cwd', '') != where: continue
            if earlier.get('tree_after') != before['tree'] or not (earlier.get('exit_code') != 0 or earlier.get('stopped')): break
            ended = f"exit {earlier.get('exit_code')}{' (' + earlier['stopped'] + ')' if earlier.get('stopped') else ''}"
            if 'key_after' not in earlier:  # recorded by an earlier runtime: its rule (the candidate tree alone) still applies
                raise LedgerError(f"Nothing changed since log {earlier.get('log')}: the same command in the same workspace ended with "
                                  f"{ended}. Change the command or the files first; re-read that receipt for its output.")
            observed = progress_state(state, tree=before['tree']); current = observed['key']
            # P4b-R4: the shared trust rule; an incomplete key with nothing run since that command proves "unchanged" too.
            if earlier.get('key_after') == current and not key_unproven(state, observed, earlier.get('receipt'),
                                                                         earlier.get('key_truncated')):
                raise LedgerError(f"Nothing changed since log {earlier.get('log')}: the same command in the same workspace (files and "
                                  f"Git-ignored inputs) ended with {ended}. Change the command or the files first; re-read that "
                                  'receipt for its output.')
            reruns = sum(1 for c in commands if c.get('argv') == argv and c.get('cwd', '') == where
                         and c.get('tree_after') == before['tree'] and c.get('inputs_rerun'))
            if reruns >= INPUT_RERUNS:
                raise LedgerError(f"This command already ran {reruns} more times on these files after only Git-ignored inputs "
                                  f"changed, and still ended with {ended} (log {earlier.get('log')}). Change the files or the "
                                  'command, or diagnose from the receipts instead of running it again.')
            inputs_rerun = True
            break
    if args.get('background'):
        if not observe: raise LedgerError('Background processes are not available in the verification checkout.')
        return start_background(runtime, task_id, state, line, cwd, env, outpath, errpath, argv, executable, mode, token)
    started = time.monotonic(); reason = None
    with outpath.open('wb') as out, errpath.open('wb') as err:
        child, job = _spawn(line, cwd, env, out, err, contained=mode == 'contained', task=identity)
        _record_process(logs, token, child)
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
    result = {'argv': argv, 'cwd': where, 'where': 'workspace' if observe else 'verification checkout',
              'executable': str(executable), 'boundary': mode, 'exit_code': None if reason else child.returncode, 'stopped': reason,
              'seconds': round(time.monotonic() - started, 2), 'stdout': stdout, 'stderr': stderr,
              'stdout_bytes': out_bytes, 'stderr_bytes': err_bytes, 'log': token,
              'tests': test_counts(stdout + '\n' + stderr)}
    after = snapshot(state, changes=False) if observe else None
    if observe: result.update(effects(contract, before, after, state))
    result['hint'] = diagnose(result, state, cwd)
    observed = None
    if observe:
        # The shared workspace key after this command; the progress guard reuses it for this step instead of computing it again.
        observed = progress_state(state, tree=after['tree'])
        state['work']['progress_state'] = dict(observed, fresh=True)
    state['work'].setdefault('commands', []).append(dict({k: result[k] for k in ('argv', 'cwd', 'exit_code', 'stopped', 'tests', 'log')},
                                                         tree_after=after['tree'] if after else None, where=result['where'],
                                                         key_after=observed['key'] if observed else None,
                                                         **({'key_truncated': True} if observed and observed.get('truncated') else {}),
                                                         # the receipt this command is stored as (the shared rule's "since")
                                                         **({'receipt': len(state.get('receipts') or [])} if observe else {}),
                                                         **({'inputs_rerun': True} if inputs_rerun else {})))
    return result


def start_background(runtime, task_id, state, line, cwd, env, outpath, errpath, argv, executable, mode='unconfined', token=None):
    running = _RUNNING.setdefault(task_id, {})
    alive = {k: v for k, v in running.items() if v[0].poll() is None}
    if len(alive) >= BACKGROUND_LIMIT: raise LedgerError(f'At most {BACKGROUND_LIMIT} background processes; stop one first.')
    out, err = outpath.open('wb'), errpath.open('wb')
    child, job = _spawn(line, cwd, env, out, err, contained=mode == 'contained', task=home(runtime, task_id).name)
    if token: _record_process(outpath.parent, token, child)
    identifier = 'P' + uuid.uuid4().hex[:8]
    record = {'id': identifier, 'argv': argv, 'executable': str(executable), 'pid': child.pid, 'log': outpath.stem,
              'started_step': state['step'], 'runner_pid': os.getpid(), 'boundary': mode}
    running[identifier] = (child, job, record, out, err)
    state['work'].setdefault('processes', {})[identifier] = dict(record, status='running')
    return dict(record, status='running', note='Contained in a Job object owned by this runner; it stops with the task or the runner.')


def process(runtime, task_id, state, args, contract=None):
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
    if contract is not None and record['status'] != 'running':
        bad = classify(contract, snapshot(state)['changes'])
        if bad: result['workspace_undeliverable_changes'] = bad[:50]
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


def diagnose(result, state=None, cwd=None):
    """cwd: the directory the command ran in; relative paths in its output are resolved against it."""
    text = (result['stderr'] + '\n' + result['stdout'])[-8000:].lower()
    contained = result.get('boundary') == 'contained'
    boundary_note = (' Contained commands can write only inside the workspace: a toolchain that writes into its own '
                     'installation or the user profile (for example the Flutter SDK cache) is refused or waits on a lock. '
                     'That needs authority.unconfined_commands from the user; ask instead of working around it.')
    if result['stopped'] == 'timeout':
        return ('environment: command timed out (raise timeout_seconds within the budget, or run it in the background)'
                + (boundary_note if contained else ''))
    code = result.get('exit_code')
    if isinstance(code, int) and code >= 0xC0000000 and not (result['stdout'] or result['stderr']).strip():
        # N1-r2/N2-r1 (13/10/2026): workers read 3221225794 as an access violation; it was 0xC0000142 (the process never
        # started). Name the Windows status instead of leaving a decimal to guess from.
        known = {0xC0000142: 'STATUS_DLL_INIT_FAILED: the process could not start', 0xC0000005: 'STATUS_ACCESS_VIOLATION',
                 0xC0000409: 'STATUS_STACK_BUFFER_OVERRUN (fast fail)', 0xC0000135: 'STATUS_DLL_NOT_FOUND: a DLL is missing',
                 0xC000013A: 'STATUS_CONTROL_C_EXIT'}
        return (f'environment: the process ended with Windows status {code:#010x} ({known.get(code, "abnormal termination")}) '
                'before printing anything; this is the host or toolchain, not the code under test. Do not repeat it unchanged.')
    if re.search(r'is not recognized as an internal|command not found|no such file or directory.*\b(dart|flutter|node|npm|python)\b', text):
        return 'environment: a tool is missing from PATH'
    if contained and re.search(r'access is denied|permission denied|eacces|eperm|operation not permitted|errno 13|'
                               r'unauthorizedaccess|access to the path .* is denied', text):
        return 'environment: the write boundary refused a write outside the workspace.' + boundary_note
    missing = re.search(r"cannot find module '([^']+)'|can't open file '([^']+)'|no such file or directory: '([^']+)'|"
                        r"enoent: no such file or directory, \w+ '([^']+)'", text)
    named = next((g for g in missing.groups() if g), '') if missing else ''
    if missing and re.search(r'[\\/]|^\.', named) and (Path(cwd) / named if cwd and not Path(named).is_absolute() else Path(named)).is_dir():
        # N2-r3 (13/10/2026): `node --test test/` makes Node load the directory itself as a module. Generic rule: the path exists
        # but is a directory; the project's own manifest says how it runs this tool.
        return ('command: a directory was given where the tool expected a file or module (' + next(g for g in missing.groups() if g)[-120:] +
                '); check how the project runs this tool (project_manifests: its declared test/build scripts) instead of repeating it')
    if missing and result.get('where') == 'verification checkout' and state is not None:
        # Live M1 (14/10/2026): the clean checkout lacked a generated, Git-ignored file the workspace had; the worker only saw
        # "exit code 1" and re-checked the export instead of declaring the project's build as setup.
        ignored = _workspace_ignored(state)
        if ignored:
            return ('verification runs in a clean checkout of the candidate: what Git ignores in your workspace (' +
                    ', '.join(ignored[:6]) + ') does not exist there. If the tests need such a file (' + named[-120:] + '), declare '
                    'setup commands that recreate it in the checkout (project_manifests lists the project\'s build scripts); '
                    'otherwise correct the path.')
    if missing and re.search(r'[\\/]|^\.', next(g for g in missing.groups() if g)):
        # N2-r2: a test runner given a path it could not open was reported as a missing dependency, and the worker kept
        # repeating the command. A missing PATH argument is the command's own mistake.
        return ('command: a path given to the command does not exist (' + next(g for g in missing.groups() if g)[-120:] + '); '
                'compare the arguments with what the workspace contains instead of repeating the command')
    if re.search(r'modulenotfounderror|cannot find module|could not resolve|package .* not found|pub get|npm (ci|install)', text):
        return 'environment: dependencies/cache missing (restore them inside the workspace)'
    if re.search(r'lock(ed)? (file|by another)|\.lock\b|resource busy|access is denied|being used by another process', text):
        return 'environment: a lock or file in use (inspect stale locks inside the workspace)'
    if re.search(r'getaddrinfo|econnrefused|network is unreachable|could not resolve host|timed out connecting', text):
        return 'environment: network unavailable'
    if result['exit_code'] not in (0, None) and (result['tests'].get('failures_reported') or result['tests'].get('passed_or_run') is not None):
        return 'product: tests ran and reported failures'
    return None


# --- durable intent and reconciliation (GX-P1-02) ---------------------------------------------------------------------

def intent(runtime, task_id, state, action, args):
    """Written to the checkpoint BEFORE a side-effecting action runs; cleared with its receipt."""
    from .supervisor import identity
    record = {'step': state['step'], 'action': action, 'arguments': content_hash(args),
              'at': dt.datetime.now(dt.timezone.utc).isoformat(), 'runner': identity(os.getpid())}
    if action == 'run': record['log'] = f"{state['step']:04d}-{uuid.uuid4().hex[:8]}"
    if (state.get('work') or {}).get('workspace') and action in ('run', 'write', 'edit', 'restore', 'workspace_commit', 'verify'):
        record['tree'] = snapshot(state, changes=False)['tree']
        if action == 'workspace_commit': record['head'] = wgit(state, 'rev-parse', 'HEAD').decode().strip()
    return record


def _terminate(record):
    """Stop a process left by a dead runner, only when its identity (pid + creation time) still matches."""
    from .supervisor import kernel, probe
    if probe(record) != 'alive': return False
    api = kernel(); handle = api.OpenProcess(0x0001 | 0x1000, False, record['pid'])
    if not handle: return False
    try:
        api.TerminateProcess.argtypes = [w.HANDLE, w.UINT]
        return bool(api.TerminateProcess(handle, 1))
    finally:
        api.CloseHandle(handle)


def reconcile(runtime, task_id, state, contract, pending, args):
    """A previous runner stopped after recording `pending` but before its receipt. Returns a receipt, or None when the
    action is provably not applied yet or is idempotent by its own action record (then it is executed normally).
    A command whose outcome is unknown is never re-run here."""
    from .supervisor import identity, probe
    # The caller holds the task lock, so no other coordinator is executing this task. A different process that is still
    # alive may still own a command tree of this action, though: then nothing is decided here.
    if pending.get('runner') != identity(os.getpid()) and probe(pending.get('runner')) == 'alive':
        raise LedgerError('The runner that started this action is still alive; it owns the action, so nothing is reconciled.')
    action = pending['action']
    if pending.get('arguments') != content_hash(args): raise LedgerError('Pending intent does not match the response; refusing to guess.')
    if action in ('create_branch', 'export_branch', 'apply', 'process', 'restore'):
        return None  # Git/apply reconcile through their action records; process ops and restore are idempotent.
    if action in ('write', 'edit'):
        target = file_path(state, contract, args['path'], for_write=True)
        current = target.read_bytes() if target.is_file() else None
        digest = hashlib.sha256(current).hexdigest() if current is not None else None
        if digest == args.get('expected_sha256'): return None  # CAS proves the write did not happen: safe to run it
        old = wgit(state, 'cat-file', 'blob', pending['tree'] + ':' + args['path'], allow_failure=True) if pending.get('tree') else None
        try: intended = _new_content(old, args, action == 'edit') if (old is not None or action == 'write') else None
        except LedgerError: intended = None
        if intended is not None and current == intended:
            return {'path': args['path'], 'sha256': digest, 'reconciled': True,
                    'outcome': 'applied before the previous runner stopped; not written again'}
        raise LedgerError('The file changed in a way this write did not produce; read it again before writing.')
    if action == 'workspace_commit':
        head = wgit(state, 'rev-parse', 'HEAD').decode().strip()
        if head == pending.get('head'): return None
        message = (wgit(state, 'log', '-1', '--format=%B', head) or b'').decode().strip()
        if message == str(args.get('message', '')).strip():
            state['work']['workspace_commit'] = head
            return {'commit': head, 'reconciled': True, 'where': 'isolated workspace only'}
        raise LedgerError('Workspace HEAD moved to an unexpected commit while the runner was down; inspect it before committing.')
    if action == 'run':
        logs = home(runtime, task_id) / 'logs'; token = pending.get('log', '')
        stopped = False
        try: stopped = _terminate(json.loads((logs / (token + '.pid')).read_text()))
        except (OSError, ValueError, LedgerError): pass
        stdout, _ = _tail(logs / (token + '.out')); stderr, _ = _tail(logs / (token + '.err'))
        result = {'argv': args.get('argv'), 'exit_code': None, 'outcome': 'unknown', 'reconciled': True, 'log': token,
                  'stdout': stdout, 'stderr': stderr, 'tests': test_counts(stdout + '\n' + stderr),
                  'left_running_and_stopped': stopped, 'background': bool(args.get('background')),
                  'note': ('The runner stopped while this command ran or before its receipt was saved. OneCrew does not run it '
                           'again automatically: read the output and the changed paths, then decide whether running it again '
                           'is safe.')}
        if pending.get('tree') and state['work'].get('workspace'):
            result.update(effects(contract, {'tree': pending['tree']}, snapshot(state, changes=False), state))
        state['work'].setdefault('commands', []).append({'argv': args.get('argv'), 'cwd': args.get('cwd', ''), 'exit_code': None,
                                                         'stopped': 'runner_lost', 'tests': result['tests'], 'log': token})
        return result
    return None


def return_to(state, tree):
    """Bring the workspace back to `tree`: files a verification command created are removed, files it changed come back.
    Returns (removed, restored)."""
    after = snapshot(state, changes=False)
    if after['tree'] == tree: return [], []
    removed, restored = [], []
    for change in tree_changes(state, tree, after['tree']):
        name = change['path']
        if change['status'] == 'A':
            target = safe_file(ws_root(state), name)
            if target.is_file(): target.unlink()
            removed.append(name)
        else:
            wgit(state, 'checkout', tree, '--', name); restored.append(name)
    return removed, restored


# --- Git through the core -------------------------------------------------------------------------------------------

def _branch_action(runtime, task_id, repo, ref, commit, key, kind, observe_extra=None, fetch_from=None, advance_from=None):
    """advance_from: only for a ref THIS job created with a verified receipt; compare-and-swap from exactly that commit.
    fetch_from: the workspace Git directory, already holding refs/onecrew/export at `commit`."""
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
            # Objects only, from the workspace Git directory the core owns; the user's refs/checkout are untouched until update-ref.
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
    """Commits exactly the delta the core sees (its own snapshot), only when all of it can be delivered."""
    if not contract['authority']['edit']: raise LedgerError('Edits are not authorized by the work contract.')
    message = args.get('message')
    if not isinstance(message, str) or not 3 <= len(message) <= 500: raise LedgerError('message: 3-500 characters.')
    snap = snapshot(state)
    head = wgit(state, 'rev-parse', 'HEAD').decode().strip()
    if snap['tree'] == wgit(state, 'rev-parse', head + '^{tree}').decode().strip(): raise LedgerError('Nothing to commit in the workspace.')
    bad = classify(contract, snap['changes'])
    if bad: raise _undeliverable(bad, 'Not committed')
    sha = wgit(state, 'commit-tree', snap['tree'], '-p', head, '-m', message).decode().strip()
    wgit(state, 'update-ref', 'HEAD', sha, head)
    wgit(state, 'reset', '-q', sha)  # the workspace index follows; files are untouched
    state['work']['workspace_commit'] = sha
    return {'commit': sha, 'tree': snap['tree'], 'where': 'isolated workspace only'}


def export_branch(runtime, task_id, state, contract, args):
    name = branch_name(args.get('name'))
    if name not in contract['authority']['local_branches']: raise LedgerError('Branch name not authorized by the work contract.')
    sha = state['work'].get('workspace_commit')
    if not sha or wgit(state, 'rev-parse', 'HEAD').decode().strip() != sha: raise LedgerError('Commit the workspace first (workspace_commit).')
    if snapshot(state, changes=False)['tree'] != wgit(state, 'rev-parse', sha + '^{tree}').decode().strip():
        raise LedgerError('Workspace has uncommitted changes after its commit.')
    bad = classify(contract, tree_changes(state, state['work']['pins']['head'], sha))
    if bad: raise _undeliverable(bad, 'Not exported')
    repo = project_repo(runtime, contract)
    # A branch this job itself created (verified create_branch receipt, still at that commit) may be advanced to the work;
    # held-out run H1-r1 (13/10/2026) created its delivery branch first and could not land the work on it.
    own = [b['receipt']['result']['commit'] for b in state['work'].get('branches', []) if b['name'] == name
           and b['receipt'].get('status') == 'verified' and b['receipt'].get('result', {}).get('kind') == 'local_branch']
    current = git(repo, 'show-ref', '--verify', '--hash', 'refs/heads/' + name, allow_failure=True)
    advance = own[-1] if own and current and current.decode().strip() == own[-1] else None
    wgit(state, 'update-ref', 'refs/onecrew/export', sha)
    receipt = _branch_action(runtime, task_id, repo, 'refs/heads/' + name, sha, 'work:export:' + content_hash([name, advance])[:24],
                             'exported_branch', fetch_from=gitdir(state), advance_from=advance)
    state['work'].setdefault('branches', []).append({'name': name, 'ref': 'refs/heads/' + name, 'receipt': receipt})
    if receipt.get('status') not in ('verified', 'exists'):
        from .owned_git import EffectUnknown
        raise EffectUnknown('Exported branch unconfirmed; resume reconciles it.')
    return receipt


def changed_files(state):
    return snapshot(state)['changes']


def _clean_blob(repo, path, name):
    """The blob Git would store for a working file under the repository's own line-ending/filter configuration."""
    return git(repo, 'hash-object', '--path=' + name, str(path)).decode().strip()


def _blob(state, tree, name):
    found = wgit(state, 'rev-parse', '--verify', '--quiet', tree + ':' + name, allow_failure=True)
    return found.decode().strip() if found else None


def apply(runtime, task_id, state, contract, args):
    """Copy the verified-to-be candidate into the user's checkout: only granted, only deliverable changes, only onto files
    untouched since the pin or last written by this job's own verified apply (compared as Git blobs, so CRLF checkouts
    are not mistaken for edits), with a rollback copy of the user's original. Files this job applied earlier that are no
    longer changed in the workspace go back to the pinned version, so the project always mirrors one candidate."""
    if not contract['authority']['apply_to_project']: raise LedgerError('Applying to the project is not authorized by the work contract.')
    repo = project_repo(runtime, contract); root = ws_root(state); base = state['work']['pins']['head']
    snap = snapshot(state); changes = snap['changes']
    bad = classify(contract, changes)
    if bad: raise _undeliverable(bad, 'Not applied')
    earlier = dict(state['work'].get('applied_files') or {})
    names = {c['path'] for c in changes} | set(earlier)
    if not changes and not earlier: raise LedgerError('No workspace changes to apply.')
    files = [{'path': name, 'blob': _blob(state, snap['tree'], name)} for name in sorted(names)]
    payload = {'kind': 'apply', 'repository': str(repo), 'base': base, 'candidate': snap['tree'], 'files': files}
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
            allowed = {original.decode().strip() if original else None}
            if f['path'] in earlier: allowed.add(earlier[f['path']])  # this job's own verified apply may be updated
            if current not in allowed:
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
    if receipt is None:
        def effect(value):
            untouched(value)  # again under the action, in case the user edited in between
            backup.mkdir(parents=True, exist_ok=True)
            manifest_path = backup / 'manifest.json'
            manifest = json.loads(manifest_path.read_text()) if manifest_path.is_file() else {'base': base, 'files': {}}
            for f in value['files']:
                target = safe_file(repo, f['path'])
                if f['path'] not in manifest['files']:  # the user's original is kept once; later applies never overwrite it
                    copy = content_hash(f['path'])[:16] + '.orig'
                    if target.is_file(): durable_write(backup / copy, target.read_bytes())
                    manifest['files'][f['path']] = {'original': copy if target.is_file() else None}
                if f['blob'] is None: target.unlink(missing_ok=True)
                else:
                    # The workspace checks out with the user's own line-ending rules, so its bytes are what the user would have.
                    target.parent.mkdir(parents=True, exist_ok=True); durable_write(target, safe_file(root, f['path']).read_bytes())
            durable_write(manifest_path, canonical(manifest).encode())
            return observe(value)
        receipt = control.execute_action(action['id'], effect)
    if receipt.get('status') != 'verified':
        from .owned_git import EffectUnknown
        raise EffectUnknown('Apply effect unconfirmed; resume reconciles it without writing again.')
    state['work']['applied'] = True
    state['work']['applied_files'] = dict(earlier, **{f['path']: f['blob'] for f in receipt['result']['files']})
    return receipt


# --- independent verification and handover --------------------------------------------------------------------------

def _remove_tree(path):
    """Remove a core-made directory tree, read-only files and paths beyond MAX_PATH included; when that is impossible (a
    file still held open), move it aside so a fresh one can be made. Junctions are removed, never followed."""
    path = Path(path)
    if not os.path.lexists(path): return
    def unlock(function, name, info):
        try:
            os.chmod(name, stat.S_IWRITE); function(name)
        except OSError:
            pass
    if path.is_symlink() or (hasattr(os.path, 'isjunction') and os.path.isjunction(path)):
        try: os.unlink(path)
        except OSError: os.rmdir(path)  # a directory junction/link: removed itself, its target untouched
        return
    long = ('\\\\?\\' + os.path.abspath(path)) if os.name == 'nt' else str(path)  # never resolved: no link is followed
    shutil.rmtree(long, onexc=unlock)
    if os.path.lexists(path):
        try: os.replace(path, path.with_name(path.name + '.stale-' + uuid.uuid4().hex[:8]))
        except OSError as error: raise LedgerError('environment: cannot clear ' + str(path) + ': ' + str(error)[:200])


def checkout_candidate(runtime, task_id, state, contract, tree):
    """A fresh directory holding exactly `tree`, nothing copied from the workspace: no ignored dependency, generated file or
    leftover can make a test pass for the delivered candidate (Codex review 2, 13/10/2026: an ignored package shadowed the
    delivered module and the dirty workspace verified green). It is a Git work tree of its own (objects borrowed from the
    workspace store, HEAD at a commit of the candidate tree, its index matching the files), so Git-dependent setup and tests
    behave as in the workspace. Returns (directory, its Git directory, the commit)."""
    root = home(runtime, task_id); target = root / 'v'; vgit = root / 'vgit'
    # Fresh every time, temp and package caches included: nothing an earlier (never reviewed) candidate's verification left
    # can feed this one (second review, 13/10/2026).
    for path in (target, vgit, root / 'vtmp', root / 'vcache'): _remove_tree(path)
    contained = boundary(contract) == 'contained'
    target.mkdir(); (root / 'vtmp').mkdir(); (root / 'vcache').mkdir()
    if contained:
        from .contain import protect
        for directory in (target, root / 'vtmp', root / 'vcache'): protect(directory, root.name)
    git(root, 'init', '-q', '--separate-git-dir=' + str(vgit), str(target))
    (vgit / 'objects' / 'info').mkdir(parents=True, exist_ok=True)
    durable_write(vgit / 'objects' / 'info' / 'alternates', (str(gitdir(state) / 'objects').replace('\\', '/') + '\n').encode())
    for key in ('core.autocrlf', 'core.eol', 'core.safecrlf', 'core.longpaths', 'core.hooksPath', 'user.name', 'user.email'):
        value = wgit(state, 'config', '--get', key, allow_failure=True)
        if value: git(target, 'config', key, value.decode().strip(), git_dir=vgit)
    head = wgit(state, 'rev-parse', 'HEAD').decode().strip()
    same = wgit(state, 'rev-parse', head + '^{tree}').decode().strip() == tree
    commit = head if same else wgit(state, 'commit-tree', tree, '-p', head, '-m', 'OneCrew verification candidate').decode().strip()
    git(target, 'update-ref', '--no-deref', 'HEAD', commit, git_dir=vgit)
    git(target, 'read-tree', commit, git_dir=vgit, work_tree=target)
    # -u records the stat data of the written files, so later diff-files examines only the candidate's own files.
    git(target, 'checkout-index', '-a', '-f', '-u', git_dir=vgit, work_tree=target, timeout=600)
    if contained:
        from .contain import own
        for path in (vgit, target / '.git'): own(path)  # Git's ownership check (safe.directory) reads these
    return target, vgit, commit


def _candidate_changes(target, vgit, commit):
    """Candidate files whose CONTENT differs from the candidate now: the index is rebuilt without stat data first, so a
    same-size change with restored timestamps is hashed and seen too."""
    git(target, 'read-tree', commit, git_dir=vgit, work_tree=target, timeout=600)
    git(target, 'update-index', '-q', '--refresh', git_dir=vgit, work_tree=target, allow_failure=True, timeout=600)
    changed = git(target, 'diff-files', '--name-only', '-z', git_dir=vgit, work_tree=target, timeout=600)
    return [n for n in (changed or b'').decode('utf-8', 'replace').split(chr(0)) if n]


NOT_MODULES = {'.json', '.yaml', '.yml', '.toml', '.cfg', '.ini', '.lock', '.md', '.txt', '.xml', '.gradle', '.kts', '.properties',
               '.csv', '.html', '.htm', '.css', '.svg', '.png', '.jpg', '.gif', '.snap', '.sql', '.env', ''}
BINARY_MODULES = {'.pyd', '.so', '.dylib', '.dll', '.node', '.pyc', '.pyo'}


def _shadows(target, delivered, tree_paths):
    """Non-candidate entries next to a DELIVERED source file that an import or require could take instead of it: a directory
    or link named like the module (calc/ next to calc.py) or a compiled module (calc.cp313-win_amd64.pyd) blocks; other
    same-stem files (calc.js next to calc.ts) are listed. Checked in the delivered files' own directories only, so a large
    node_modules elsewhere cannot hide them."""
    found = []
    for name in delivered:
        path = Path(name)
        if path.suffix.lower() in NOT_MODULES: continue
        stem = path.name.split('.')[0]; directory = target / path.parent
        try: entries = list(os.scandir(directory))
        except OSError: continue
        for entry in entries:
            rel = entry.name if str(path.parent) == '.' else (path.parent / entry.name).as_posix()
            if rel in tree_paths or entry.name == path.name or entry.name.split('.')[0] != stem: continue
            kind = 'link' if entry.is_symlink() or (hasattr(os.path, 'isjunction') and os.path.isjunction(entry.path)) else \
                'directory' if entry.is_dir() else 'file'
            blocking = (kind != 'file' and entry.name == stem) or (kind == 'file' and Path(entry.name).suffix.lower() in BINARY_MODULES)
            found.append({'entry': rel, 'kind': kind, 'shadows': name, 'blocking': blocking})
            if len(found) >= 50: return found
        if path.suffix.lower() == '.py':
            # __pycache__/<stem>.<tag>.pyc: Python loads it instead of the source unless it is a checked-hash pyc (validated
            # against the delivered source); timestamp and unchecked-hash entries can carry other code (third review).
            cache = directory / '__pycache__'
            try: cached = [e for e in os.scandir(cache) if e.name.split('.')[0] == stem and e.name.endswith('.pyc')]
            except OSError: cached = []
            for entry in cached:
                rel = (path.parent / '__pycache__' / entry.name).as_posix() if str(path.parent) != '.' else '__pycache__/' + entry.name
                if rel in tree_paths: continue
                try:
                    with open(entry.path, 'rb') as stream: flags = int.from_bytes(stream.read(8)[4:8], 'little')
                except OSError: flags = 0
                if flags != 0b11: found.append({'entry': rel, 'kind': 'compiled cache', 'shadows': name, 'blocking': True})
    return found


def _ignored_outputs(target, tree_paths, limit=20000):
    """Files present in the verification checkout that the candidate does not contain (made by setup or by the tests),
    summarised by top-level entry: the provenance of every non-candidate input a test could have used."""
    summary = {}; seen = 0
    for directory, names, files in os.walk(target):
        base = Path(directory); here = base.relative_to(target).as_posix(); here = '' if here == '.' else here
        if here == '' and '.git' in files: files.remove('.git')
        links = [n for n in names if (base / n).is_symlink() or (hasattr(os.path, 'isjunction') and os.path.isjunction(base / n))]
        names[:] = sorted(n for n in names if n not in links)  # never walk out of the checkout through a link
        for file in sorted(files) + links:
            path = base / file
            name = path.relative_to(target).as_posix()
            if name in tree_paths: continue
            seen += 1
            if seen > limit:
                summary['...'] = {'files': 'more than %d files not from the candidate; the rest is not listed' % limit}
                return summary
            top = name.split('/', 1)[0]
            entry = summary.setdefault(top, {'files': 0, 'bytes': 0}); entry['files'] += 1
            try: entry['bytes'] += path.lstat().st_size
            except OSError: pass
    return summary


def _rerun(runtime, task_id, state, contract, item, guard, base=None):
    copy = {'argv': item['argv'], 'cwd': item.get('cwd', ''), 'timeout_seconds': min(int(item.get('timeout_seconds', 300)), RUN_SECONDS)}
    result = run(runtime, task_id, state, dict(contract, authority=dict(contract['authority'], commands=True)), copy, guard,
                 repeat_guard=False, base=base)
    testlike = bool(re.search(r'test|pytest|unittest|jest|mocha|vitest|spec', ' '.join(item['argv']), re.I))
    ok = result['exit_code'] == 0 and not result['stopped']
    reason = None
    if not ok: reason = 'exit code ' + str(result['exit_code']) + (' (' + result['stopped'] + ')' if result['stopped'] else '')
    elif testlike and result['tests']['passed_or_run'] == 0: reason = 'zero tests ran'; ok = False
    elif testlike and result['tests']['passed_or_run'] and result['tests']['skipped'] >= result['tests']['passed_or_run']:
        reason = 'all tests skipped'; ok = False
    return {'argv': item['argv'], 'cwd': copy['cwd'], 'passed': ok, 'reason': reason, 'exit_code': result['exit_code'],
            'tests': result['tests'], 'testlike': testlike, 'log': result['log'], 'stdout_tail': result['stdout'][-1500:],
            'stderr_tail': result['stderr'][-1500:],
            'boundary': result.get('boundary'), 'where': result.get('where'), 'hint': result.get('hint')}


def test_integrity(state, contract, changes=None, tree=None):
    findings = []
    if not state.get('work', {}).get('workspace'): return findings
    base = state['work']['pins']['head']
    if changes is None or tree is None:
        snap = snapshot(state); changes, tree = snap['changes'], snap['tree']
    for change in changes:
        name, status = change['path'], change['status']
        if not is_test(name): continue
        if status == 'D': findings.append('existing test file deleted: ' + name); continue
        if status == 'T': findings.append('existing test file replaced by another kind of entry (symlink or submodule): ' + name); continue
        diff = (wgit(state, 'diff', '-U0', base, tree, '--', name) or b'').decode('utf-8', errors='replace')
        added = [l[1:] for l in diff.splitlines() if l.startswith('+') and not l.startswith('+++')]
        removed = [l[1:] for l in diff.splitlines() if l.startswith('-') and not l.startswith('---')]
        if any(SKIP_MARK.search(l) for l in added): findings.append('skip/only marker added in test file: ' + name)
        if status == 'M':
            if not contract['authority']['edit_tests']: findings.append('existing test file modified without edit_tests: ' + name)
            elif sum(len(ASSERTION.findall(l)) for l in removed) > sum(len(ASSERTION.findall(l)) for l in added):
                findings.append('assertions removed from existing test file: ' + name)
    return findings


def deliveries(runtime, state, contract, candidate):
    """Observed values of everything this job delivered, read from the user's repository now (not from receipts), and
    the findings when they are not the verified candidate. Returns (fingerprint, findings)."""
    work = state['work']; repo = project_repo(runtime, contract)
    fingerprint = {'branches': {}, 'applied': {}}; findings = []
    latest = {}
    for branch in work.get('branches', []):
        if branch['receipt'].get('status') == 'verified': latest[branch['name']] = branch['receipt']
    for name, receipt in sorted(latest.items()):
        found = git(repo, 'show-ref', '--verify', '--hash', 'refs/heads/' + name, allow_failure=True)
        actual = found.decode().strip() if found else None
        fingerprint['branches'][name] = actual
        expected = receipt['result']['commit']
        if actual != expected:
            findings.append(f"branch {name} is at {actual[:12] if actual else 'nothing (deleted)'}, not {expected[:12]} from its "
                            'receipt: it changed outside this job')
        elif receipt['result'].get('kind') == 'exported_branch' and candidate:
            tree = git(repo, 'rev-parse', actual + '^{tree}').decode().strip()
            if tree != candidate:
                findings.append(f"branch {name} carries {actual[:12]}, not the verified workspace candidate (changed after export): "
                                'commit and export again')
    if work.get('applied') and work.get('workspace'):
        names = {c['path'] for c in tree_changes(state, work['pins']['head'], candidate)} | set(work.get('applied_files') or {})
        for name in sorted(names):
            want = _blob(state, candidate, name)
            target = repo / name
            have = _clean_blob(repo, target, name) if target.is_file() else None
            fingerprint['applied'][name] = have
            if have != want:
                findings.append(f'project file {name} differs from the verified candidate (it was applied from another state or '
                                'changed afterwards): apply again')
    return fingerprint, findings


def _failed(prefix, item, value):
    """A failed core re-run as the worker sees it: why (the diagnosis) and the end of its output, not only an exit code."""
    text = prefix + ' '.join(item['argv'])[:120] + ': ' + str(value.get('reason'))
    if value.get('hint'): text += ' | hint: ' + str(value['hint'])[:500]
    tail = ((value.get('stdout_tail') or '').strip() + '\n' + (value.get('stderr_tail') or '').strip()).strip()[-400:]
    if tail: text += ' | output tail: ' + tail
    return text


def _workspace_ignored(state, limit=40):
    """Top-most Git-ignored entries of the workspace (generated files, dependencies), as names."""
    try:
        raw = wgit(state, 'ls-files', '--others', '--ignored', '--exclude-standard', '--directory', '-z',
                   env={'GIT_INDEX_FILE': str(_home(state) / 'core.index')}, timeout=120) or b''
    except (LedgerError, OSError):
        return []
    return sorted(p.decode('utf-8', 'replace') for p in raw.split(bytes(1)) if p)[:limit]


def _commands(value, name):
    if not isinstance(value, list) or len(value) > 6: raise LedgerError(name + ': a list of at most 6 commands.')
    items = []
    for item in value:
        if not isinstance(item, dict): raise LedgerError(name + ' items: {argv, cwd}.')
        items.append({'argv': argv_value(item.get('argv')), 'cwd': relative_dir(item.get('cwd')), 'timeout_seconds': item.get('timeout_seconds', 300)})
    return items


def verify(runtime, task_id, state, contract, args, guard):
    """Core-run evidence at finish, bound to one candidate tree and to the real delivered outputs. Commands run in a clean
    checkout of the candidate: declared setup commands recreate what tests need (dependencies, generated files) and are
    recorded with what they produced; nothing comes from the workspace."""
    stop_all(task_id, state)
    work = state['work']
    result = {'commands': [], 'setup': [], 'checks': [], 'integrity': [], 'preserve': [], 'findings': [], 'undeliverable': []}
    declared = _commands(args.get('verification') or [], 'verification')
    setup = _commands(args.get('setup') or [], 'setup')
    if (declared or setup) and not contract['authority']['commands']:
        raise LedgerError('Verification commands need the commands authority; this contract is checked by its own checks only.')
    candidate = None; changes = []
    if work.get('workspace'):
        snap = snapshot(state); candidate, changes = snap['tree'], snap['changes']
        result['undeliverable'] = classify(contract, changes)
        result['findings'] += [f"not deliverable under this contract: {b['path']} ({b['reason']})" for b in result['undeliverable'][:20]]
    result['candidate'] = candidate; result['changed_files'] = changes
    if changes and not declared and not any(c['kind'] == 'command' for c in contract['checks']):
        result['findings'].append('files changed but no verification command was declared for the core to re-run')
    checkout = vgit = commit = None; flagged = set()
    result['rules'] = VERIFY_RULES
    if candidate and (declared or setup or any(c['kind'] == 'command' for c in contract['checks'])):
        contained = boundary(contract) == 'contained'
        checkout, vgit, commit = checkout_candidate(runtime, task_id, state, contract, candidate)
        result['verified_in'] = {'kind': 'clean checkout of the candidate tree', 'tree': candidate, 'commit': commit, 'path': str(checkout),
                                 'copied_from_workspace': [], 'git': 'own repository at the candidate commit',
                                 'identity': ('the task\'s own contained identity, in this checkout; path arguments that leave the '
                                              'checkout are refused; reads elsewhere are not contained (decision 13/10/2026)'
                                              if contained else 'unconfined: path arguments that leave the checkout are refused, '
                                              'reads are not contained')}

    def rerun(item, label):
        try: value = _rerun(runtime, task_id, state, contract, dict(item), guard, base=checkout)
        except LedgerError as error:  # refused before it ran (an argument into the workspace, a missing tool): a failed check
            value = {'argv': item['argv'], 'cwd': item.get('cwd', ''), 'passed': False, 'reason': 'refused: ' + str(error)[:300],
                     'exit_code': None, 'tests': {}, 'testlike': False, 'log': None, 'stdout_tail': '', 'boundary': None,
                     'where': 'verification checkout', 'hint': None}
        if checkout is not None:
            # After EVERY command: a candidate file changed by one command and restored by a later one is still caught.
            for name in _candidate_changes(checkout, vgit, commit):
                if name not in flagged and len(flagged) < 20:
                    flagged.add(name)
                    result['findings'].append(f"{label} changed the candidate file {name} in the checkout: " + ' '.join(item['argv'])[:100])
        return value

    for item in setup:
        value = rerun(item, 'a setup command')
        value = dict(value, testlike=False, passed=value['exit_code'] == 0, reason=None if value['exit_code'] == 0 else value['reason'])
        result['setup'].append(value)
        if value['exit_code'] != 0: result['findings'].append('setup command failed in the clean checkout: ' + ' '.join(item['argv'])[:120])
    for item in declared:
        value = rerun(item, 'a verification command')
        result['commands'].append(value)
        if not value['passed']: result['findings'].append(_failed('core re-run failed: ', item, value))
    repo = project_repo(runtime, contract)
    for check in contract['checks']:
        if check['kind'] == 'ref':
            expected = work['pins']['head'] if check['equals'] == 'pinned_head' else check['equals']
            found = git(repo, 'show-ref', '--verify', '--hash', 'refs/heads/' + check['name'], allow_failure=True)
            ok = found is not None and found.decode().strip() == expected
            result['checks'].append({'kind': 'ref', 'name': check['name'], 'expected': expected, 'found': found.decode().strip() if found else None, 'passed': ok})
            if not ok: result['findings'].append(f"contract check failed: refs/heads/{check['name']} != {expected[:12]}")
        else:
            value = rerun(check, 'a contract command check')
            result['checks'].append(dict(value, kind='command'))
            if not value['passed']: result['findings'].append(_failed('contract command check failed: ', check, value))
    if checkout is not None:
        # Whatever exists in the checkout besides the candidate (dependencies, generated files, reports) is provenance, never
        # delivered. A non-candidate DIRECTORY next to a delivered file with the same stem (a package shadowing a module) can
        # stand in for it, so it is a finding; other same-stem entries are listed for the reviewer.
        paths = set((wgit(state, 'ls-tree', '-r', '--name-only', '-z', candidate) or b'').decode('utf-8', 'replace').split('\0'))
        result['verified_in']['not_from_candidate'] = _ignored_outputs(checkout, paths)
        shadows = _shadows(checkout, [c['path'] for c in changes if c['status'] in ('A', 'M', 'T')], paths)
        result['verified_in']['shadowing_candidate_files'] = shadows
        for item in shadows:
            if item['blocking']:
                result['findings'].append(f"{item['entry']} ({item['kind']}, not from the candidate) shadows the delivered file "
                                          f"{item['shadows']} in the verification checkout; the tests may have used it instead")
        # Commands of this task may write the workspace as well; finish compares it with the candidate again.
        if snapshot(state, changes=False)['tree'] != candidate: result['findings'].append('the workspace changed during verification')
    result['integrity'] = test_integrity(state, contract, changes, candidate) if candidate else []
    result['findings'] += result['integrity']
    fingerprint, delivered = deliveries(runtime, state, contract, candidate)
    result['deliveries'] = fingerprint; result['findings'] += delivered
    created = [b['ref'] for b in work.get('branches', []) if b['receipt'].get('status') == 'verified']
    from .work_contract import preserved
    findings, after = preserved(repo, work['pins'], created, applied=sorted(work.get('applied_files') or {}) if work.get('applied') else ())
    result['preserve'] = findings; result['project_after'] = after
    result['findings'] += ['project not preserved: ' + f for f in findings]
    return result


def recheck(runtime, task_id, state, contract):
    """At completion, after a review that may have taken long: the candidate, every delivered output and the preserved
    repository must still be exactly what was verified. Returns findings (empty = still valid)."""
    verification = state['work'].get('verification') or {}; findings = []
    candidate = verification.get('candidate')
    if state['work'].get('workspace'):
        stop_all(task_id, state)
        if snapshot(state, changes=False)['tree'] != candidate: findings.append('the workspace changed after verification')
    fingerprint, delivered = deliveries(runtime, state, contract, candidate)
    findings += delivered
    if fingerprint != verification.get('deliveries'): findings.append('a delivered branch or applied file changed after verification')
    created = [b['ref'] for b in state['work'].get('branches', []) if b['receipt'].get('status') == 'verified']
    from .work_contract import preserved
    work = state['work']
    lost, _ = preserved(project_repo(runtime, contract), work['pins'], created,
                        applied=sorted(work.get('applied_files') or {}) if work.get('applied') else ())
    findings += ['project not preserved: ' + f for f in lost]
    return findings


def handover(runtime, task_id, state, contract, verification, report):
    """Deterministic handover written by the core: diff, files, re-run results, receipts and how to roll back."""
    root = home(runtime, task_id) / 'handover'; root.mkdir(exist_ok=True)
    work = state['work']; files = {}
    if work.get('workspace') and verification.get('candidate'):
        patch = wgit(state, 'diff', '--binary', work['pins']['head'], verification['candidate']) or b''  # the verified tree
        durable_write(root / 'changes.patch', patch); files['patch'] = str(root / 'changes.patch')
    rollback = []
    for branch in work.get('branches', []):
        receipt = branch['receipt']
        if receipt.get('status') == 'verified':
            sha = receipt['result']['commit']
            rollback.append(f"git -C \"{project_repo(runtime, contract)}\" branch -D {branch['name']}   # only while it still points to {sha}")
    if work.get('applied'): rollback.append('restore the files listed in ' + str(home(runtime, task_id) / 'rollback' / 'manifest.json') + ' from the *.orig copies (original null: delete the file), or git apply -R changes.patch')
    summary = {'task': task_id, 'contract': contract, 'pins': {k: v for k, v in work['pins'].items() if k not in ('refs', 'dirty_paths')},
               'workspace': work.get('workspace'), 'changed_files': verification.get('changed_files', []),
               'candidate': verification.get('candidate'), 'delivered': verification.get('deliveries'),
               'verification': {k: v for k, v in verification.items() if k != 'changed_files'},
               'branches': work.get('branches', []), 'applied': work.get('applied', False), 'rollback': rollback,
               'executor': 'onecrew-core (Git/commands), worker ' + state['worker']['provider'] + '/' + state['worker']['model'] + ' (decisions)'}
    durable_write(root / 'handover.json', canonical(summary).encode()); files['summary'] = str(root / 'handover.json')
    durable_write(root / 'report.md', report.encode('utf-8')); files['report'] = str(root / 'report.md')
    return files


CONTINUE = {
    'no_progress': 'The same result repeated with nothing changed. Resume (job resume) only when there is a reason to expect a '
                   'different approach; the guard counters are kept, so the repeated result stops the task again at once.',
    'permission': 'The worker kept asking for actions outside the contract. Widening authority is a user decision (a new '
                  'contract); otherwise resume so the worker reports what it cannot do.',
    'review': 'The reviewer rejected the evidence repeatedly; read the review feedback before deciding to resume.',
    'environment': 'The machine or sandbox failed (see the reason); fix it, then resume.',
    'auth': 'The provider account needs a login; fix it, then resume.', 'quota': 'The provider quota is exhausted; resume later.',
    'effect_unknown': 'An external effect may or may not have happened; reconcile it (the reason names it) before resuming.',
}


def blocker_handover(runtime, task_id, state, control=None):
    """Deterministic blocker handover, written by the core when a work job is blocked (P4-D; no model involved): why it
    stopped, the evidence (last actions and their errors, the repeated result), what exists (changed files and their patch
    against the pin, core verification, branches), budget and deadline, the contract terms and how to continue. The
    checkpoint names its report, so the existing Windows result window of a blocked job shows it once."""
    root = home(runtime, task_id) / 'handover'; root.mkdir(exist_ok=True)
    work = state['work']; step = state['step']; files = {}; changes = []
    stem = f"blocker-{step:04d}-{len(work.get('blocks') or []) + 1}"  # one per block, even two at the same step
    tree = (work.get('progress_state') or {}).get('tree')
    if work.get('workspace') and tree:
        try:
            durable_write(root / (stem + '.patch'), wgit(state, 'diff', '--binary', work['pins']['head'], tree) or b'')
            files['patch'] = str(root / (stem + '.patch'))
            changes = [c['status'] + ' ' + c['path'] for c in tree_changes(state, work['pins']['head'], tree)][:200]
        except (OSError, LedgerError) as error:
            files['patch_error'] = str(error)[:300]
    last = []
    for ref in state['receipts'][-10:]:
        try: result = json.loads(runtime.store.read_blob(ref['blob'])).get('result')
        except (OSError, ValueError): result = None
        last.append({'receipt': ref['index'], 'action': ref['action'], 'ok': ref.get('successful'),
                     'error': str(result.get('error'))[:300] if isinstance(result, dict) and 'error' in result else None})
    progress = state.get('progress') or {}; stopped = progress.get('stopped_by')
    kind = (state.get('recovery') or {}).get('kind')
    verified = work.get('verification') or {}
    budget = terms = None
    if control is not None:
        try:
            status = control.status(task_id)
            budget = {'used_calls': status['used_calls'], 'max_calls': status['budget']['limits']['max_calls'],
                      'deadline': status['budget']['deadline']}
            contract = status['configuration']['profile']['contract']
            terms = {'goal': contract['goal'], 'acceptance': contract['acceptance']}
        except (LedgerError, KeyError, TypeError, OSError): pass
    summary = {'task': task_id, 'phase': 'blocked', 'reason': state.get('message'), 'kind': kind, 'step': step, 'contract': terms,
               'plan': state.get('plan'),
               'repeated': ({k: stopped.get(k) for k in ('action', 'arguments', 'count', 'step')}
                            if stopped and stopped.get('step') is not None and stopped['step'] >= step - 1 else None),
               'last_actions': last, 'workspace_changes': changes, 'patch': files.get('patch'),
               'core_verification': ({k: verified.get(k) for k in ('step', 'candidate', 'findings', 'interrupted')} if verified else None),
               'branches': [{'name': b['name'], 'status': b['receipt'].get('status')} for b in work.get('branches', [])],
               'budget': budget, 'pins': {k: work['pins'].get(k) for k in ('head', 'branch')},
               'earlier_blocks': (work.get('blocks') or [])[-5:],
               'to_continue': CONTINUE.get(kind, 'Read the reason and the last actions; fix what they name, then resume (job resume). '
                                                 'Budget, deadline and authority change only by a user decision.'),
               'executor': 'onecrew-core, written when the job was blocked (no model call)'}
    durable_write(root / (stem + '.json'), canonical(summary).encode()); files['summary'] = str(root / (stem + '.json'))
    lines = [f'# OneCrew: task {task_id} blocked at step {step}', '', 'Reason: ' + str(summary['reason']), '',
             'To continue: ' + summary['to_continue'], '']
    if summary['repeated']: lines += ['Repeated result: ' + canonical(summary['repeated']), '']
    lines += ['Files changed against the pin (' + str(work['pins'].get('head'))[:12] + '): ' + (', '.join(changes) or 'none'),
              'Patch: ' + str(files.get('patch')), '', 'Last actions:']
    lines += [f"- receipt {a['receipt']}: {a['action']} {'ok' if a['ok'] else 'FAILED'}" + (f" - {a['error']}" if a['error'] else '')
              for a in last]
    lines += ['', 'Core verification: ' + canonical(summary['core_verification']), 'Budget: ' + canonical(budget),
              'Plan at the block: ' + str(summary['plan'])[:2000], '',
              'Written by the OneCrew core when the job was blocked; no model was involved. Full data: ' + files['summary']]
    durable_write(root / (stem + '.md'), '\n'.join(lines).encode('utf-8')); files['report'] = str(root / (stem + '.md'))
    return files


MANIFEST_NAMES = ('package.json', 'pyproject.toml', 'setup.cfg', 'tox.ini', 'pytest.ini', 'Makefile', 'pubspec.yaml', 'go.mod',
                  'Cargo.toml', 'pom.xml', 'build.gradle', 'build.gradle.kts', 'composer.json', 'Gemfile', 'deno.json', 'justfile')
TEST_RUNNERS = ('jest', 'mocha', 'vitest', 'ava', 'tap', 'jasmine', 'karma', 'pytest', 'nose2', 'tox')


def project_manifests(root, limit=12):
    """What the project itself declares about building and testing (manifests, task files, CI steps), read by the core.
    Data for the worker, never instructions or authority. N2 (13/10/2026): Kiro never looked at package.json's test script."""
    root = Path(root); found = []
    candidates = [root / n for n in MANIFEST_NAMES]
    for child in sorted(p for p in root.iterdir() if p.is_dir() and p.name not in ('.git', 'node_modules', 'build', 'dist', '.venv', 'venv')) \
            if root.is_dir() else []:
        candidates += [child / n for n in MANIFEST_NAMES]
    workflows = root / '.github' / 'workflows'
    if workflows.is_dir(): candidates += sorted(workflows.glob('*.y*ml'))[:8]
    for path in candidates:
        if len(found) >= limit: break
        if not path.is_file() or path.stat().st_size > 400_000: continue
        name = path.relative_to(root).as_posix()
        try: text = path.read_text(encoding='utf-8-sig', errors='replace')
        except OSError: continue
        entry = {'file': name}
        if path.name == 'package.json':
            try: data = json.loads(text)
            except ValueError: data = {}
            if not isinstance(data, dict): data = {}
            scripts = data.get('scripts') if isinstance(data.get('scripts'), dict) else {}
            entry['scripts'] = dict(list({str(k)[:60]: str(v)[:200] for k, v in scripts.items()
                                          if re.search(r'test|build|lint|check|spec', str(k), re.I)}.items())[:15])
            deps = {}
            for key in ('devDependencies', 'dependencies'):
                if isinstance(data.get(key), dict): deps.update(data[key])
            entry['test_runners'] = sorted(d for d in deps if d in TEST_RUNNERS)
            entry['module_type'] = data.get('type') if isinstance(data.get('type'), str) else None
            entry['how_to_run'] = 'npm test' if 'test' in scripts else None
        elif path.name in ('pyproject.toml', 'setup.cfg', 'tox.ini', 'pytest.ini'):
            entry['sections'] = sorted(set(re.findall(r'^\[([^\]\n]*(?:pytest|tox|testenv|tool\.\w+|scripts)[^\]\n]*)\]', text, re.M)))[:10]
        elif path.name in ('Makefile', 'justfile'):
            entry['targets'] = sorted(set(re.findall(r'^([A-Za-z][\w.-]*)\s*:', text, re.M)) & {'test', 'tests', 'check', 'build', 'lint', 'ci', 'all'})
        elif path.suffix in ('.yml', '.yaml') and '.github' in name:
            entry['run_steps'] = [step[:160] for step in _run_steps(text) if re.search(r'test|build|check|lint', step, re.I)][:6]
        else:
            entry['kind'] = path.name
        found.append(entry)
    while len(canonical(found)) > MANIFEST_BUDGET and len(found) > 1:
        found.pop()  # bounded: the worker prompt is not shrunk by the provider fit, so this survey must stay small
        found[-1]['more_manifests_not_listed'] = True
    if found and len(canonical(found)) > MANIFEST_BUDGET:
        found = [{'file': found[0]['file'], 'note': 'too large to list; read the file itself'}]
    return found


MANIFEST_BUDGET = 6000


def _run_steps(text):
    """`run:` steps of a CI workflow, including block scalars (`run: |` followed by indented lines)."""
    steps = []; lines = text.splitlines()
    for index, line in enumerate(lines):
        match = re.match(r'^(\s*-?\s*)run:\s*(.*)$', line)
        if not match: continue
        value = match.group(2).strip()
        if value[:1] in ('|', '>'):
            indent = len(match.group(1)); block = []  # the column of the run key: the block is indented deeper
            for following in lines[index + 1:]:
                if following.strip() and len(following) - len(following.lstrip()) <= indent: break
                if following.strip(): block.append(following.strip())
            steps += block
        elif value:
            steps.append(value)
    return steps


def _bounded(items, chars):
    """As many items as fit in `chars` characters (as JSON), then a count of the rest: facts stay bounded for any change size."""
    kept, used = [], 0
    for item in items:
        used += len(canonical(item)) + 1
        if used > chars: return kept + [f'... and {len(items) - len(kept)} more (not listed)']
        kept.append(item)
    return kept


def review_facts(runtime, state, contract, verification):
    """Facts the core established for the delivered candidate, for the completion review, computed once per review prompt
    and bounded in size; the per-file diffs are returned separately (they are the worker's content, so untrusted) at full
    length and shrunk to the prompt budget by fit_diffs. N4 (13/10/2026): a reviewer under Kiro's prompt cap lost the
    receipts that showed the existing tests were untouched and rejected a correct, core-verified result."""
    work = state['work']; candidate = verification.get('candidate'); base = work['pins']['head']
    changes = verification.get('changed_files') or []
    verified_in = dict(verification.get('verified_in') or {}) or (
        {'kind': 'no verification command ran in a checkout (the contract is checked by its own checks only)'}
        if verification.get('rules') == VERIFY_RULES else
        {'kind': 'verified by an earlier runtime: NOT a clean checkout of the candidate'})
    if isinstance(verified_in.get('not_from_candidate'), dict):
        verified_in['not_from_candidate'] = _bounded(sorted([k, v] for k, v in verified_in['not_from_candidate'].items()), 1500)
    if isinstance(verified_in.get('shadowing_candidate_files'), list):
        verified_in['shadowing_candidate_files'] = _bounded(verified_in['shadowing_candidate_files'], 1500)
    delivered = verification.get('deliveries') or {}
    delivered = {'branches': delivered.get('branches'),
                 'applied': _bounded(sorted([path, blob] for path, blob in (delivered.get('applied') or {}).items()), 1500)}
    facts = {'base_commit': base, 'candidate_tree': candidate, 'files_changed_count': len(changes),
             'files_changed_vs_pin': _bounded(changes, 2500),
             'test_file_rule': 'a path is a test file when it is under tests/, test/, __tests__/, __snapshots__/, spec(s)/, '
                               'test_driver/, integration_test/ or cypress/, or is named test_*.py|rb, tests.py, conftest.py, '
                               'setupTests.*, *_test.py|dart|go|rb, *.test.*|*.spec.*|*.cy.* (js/ts), *Test(s).java|kt|cs|swift '
                               'or *_spec.rb',
             'existing_test_files_modified_or_deleted': _bounded([c['path'] for c in changes if is_test(c['path']) and c['status'] != 'A'], 1500),
             'new_test_files': _bounded([c['path'] for c in changes if is_test(c['path']) and c['status'] == 'A'], 1000),
             'test_integrity_findings': _bounded(verification.get('integrity', []), 1500),
             'undeliverable_changes': _bounded(verification.get('undeliverable', []), 1500),
             'verified_in': verified_in,
             'setup': [{'argv': c.get('argv'), 'exit_code': c.get('exit_code')} for c in verification.get('setup', [])][:6],
             'verification_commands': [{k: c.get(k) for k in ('argv', 'cwd', 'passed', 'exit_code', 'tests', 'where')} for c in verification.get('commands', [])][:6],
             'contract_checks': [{k: c.get(k) for k in ('kind', 'name', 'argv', 'passed', 'expected', 'found')} for c in verification.get('checks', [])][:12],
             'delivered': delivered, 'preserve_findings': _bounded(verification.get('preserve', []), 1500),
             'core_findings': _bounded(verification.get('findings', []), 2000)}
    diffs = []
    if candidate and work.get('workspace') and changes:
        ordered = sorted(changes, key=lambda c: (is_test(c['path']), c['path']))
        for change in ordered[:40]:
            text = (wgit(state, 'diff', '--no-color', '-U2', base, candidate, '--', change['path']) or b'').decode('utf-8', 'replace')
            lines = text.splitlines()
            diffs.append({'path': change['path'], 'status': change['status'], 'blob': _blob(state, candidate, change['path']),
                          'added': sum(1 for l in lines if l.startswith('+') and not l.startswith('+++')),
                          'removed': sum(1 for l in lines if l.startswith('-') and not l.startswith('---')), 'text': text[:20000]})
        if len(ordered) > 40: facts['diffs_omitted'] = len(ordered) - 40
    return facts, diffs


def fit_diffs(diffs, budget):
    """Per-file diffs within `budget` characters IN TOTAL (entries included): excerpts first shrink, then entries are left
    out and counted; files_changed_vs_pin in core_facts still names every file."""
    share = budget // max(1, len(diffs)); fitted = []; used = 0
    for index, item in enumerate(diffs):
        text = item['text']; value = {k: v for k, v in item.items() if k != 'text'}
        if share < 120: value['diff'] = None  # too tight for an excerpt
        else: value['diff'] = text if len(text) <= share else text[:share] + '\n[... diff truncated by the prompt budget; the blob id names the full file ...]'
        value['truncated'] = len(text) > share
        size = len(canonical(value)) + 1
        if used + size > budget:
            fitted.append({'omitted_diffs': len(diffs) - index, 'note': 'beyond the prompt budget; files_changed_vs_pin names them'})
            break
        fitted.append(value); used += size
    return fitted


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
