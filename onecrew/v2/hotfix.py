"""2.4-S2: feedback -> fix plan -> artifact -> install at a declared target -> recheck of the original error -> resume, with evidence.

Records (class A, on the support anchor of the reporting project; nothing is written on the customer root except what the engine itself
writes when the recheck re-runs the original check):

  support.target            {id, venv, exe, python}                 OWNER verb `support target add` (refused inside an AI session)
  support.artifact          {feedback, wheel_sha256, version, code_commit, manifest_sha, wheel_blob, manifest_blob, bound_to, fix}
  support.install_prepared  {key, venv, trial, identity, consumers, drill, authority, blocked_by}
  support.install           {key, action: install|rollback, result, new_venv, old_venv, switched files, processes, problems}
  support.recheck           {feedback, refs, environment: target|copy, state_root, version, receipt, result, recurrence_of}
  support.resumed           {feedback, root, node, mode, request, budget_reset: False, grants_authority: False}

Authority: an install is allowed only when the approved contract of the linked FIX plan (another project: the OneCrew repo) names
`support_install:<target id>` in authority.granted_actions, checked through authority.enforce on that root (with its remaining budget). A
report, a log line, a hash in a text or a project edit grant never grants it. Without the grant (or with its budget spent) the dependent
effect is blocked and recorded as blocked_by_authority while the preparation still completes in a trial venv under the state root.

Artifact identity (support.artifact.bound_to): the wheel bytes' sha256 must equal the manifest's wheel sha256, the wheel's METADATA version the
manifest version, and the manifest's code_commit must be a commit of the fix project whose git tree is the tree OneCrew verified for the fix
plan: its `plan.accepted.artifact_sha` when the plan is accepted, else a `milestone.passed.artifact_sha` for EVERY milestone of the approved
revision. Limit: the wheel is not rebuilt from that commit (no reproducible build); the binding is manifest -> commit -> verified tree.

Install: always a NEW venv beside the declared one (`<venv>-<version>`), never a change to the old venv; `python -m venv` + `pip install
--no-index --no-deps`; then its RECORD sha and `onecrew --version`. Drill on a copy of every consuming state root with the new runtime
(compat scan of that copy, and `plan show` of each root of the consuming project). Switch only at a safe point; rollback only when the old
runtime reads a copy of the current data. Every step records first and is idempotent by key = feedback + wheel sha + target.
"""
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import zipfile
from pathlib import Path

from ..ledger import Ledger, LedgerError, content_hash, read_json, utcnow
from ..snapshots import Snapshots, is_link
from . import authority, hook_cli, install as installer, internal_plan, namespaces, ownership, plan as plans, support, where

TARGET_ID = re.compile(r'[a-z0-9_.-]{1,40}\Z')
COMMIT = re.compile(r'[0-9a-f]{40}([0-9a-f]{24})?\Z')
WORK = 'support-work'
INSTALL_SECONDS = 600
FENCE_SKIP = (WORK, 'support-spool', 'snapshots/blobs', 'notifications', 'hook-projects.json', 'backups')
CRASH_ENV = 'ONECREW_SUPPORT_CRASH'
ACTIVE_ACTIONS = ('executing', 'unknown')


class Crash(RuntimeError):
    """A fixture crash point (ONECREW_SUPPORT_CRASH=<point>): the process stops as if killed there."""


def _crash(point):
    if os.environ.get(CRASH_ENV) == point: raise Crash(f'fixture crash at {point}')


# ---- the venv side (replaceable in tests) -------------------------------------------------------------------------------------

def run(argv, cwd=None, env=None, timeout=900):
    try:
        done = subprocess.run([str(a) for a in argv], cwd=str(cwd) if cwd else None, env=env, capture_output=True, text=True, encoding='utf-8',
                              errors='replace', timeout=timeout, stdin=subprocess.DEVNULL)
        return done.returncode, done.stdout, done.stderr
    except (OSError, subprocess.SubprocessError) as error:
        return None, '', f'{type(error).__name__}: {error}'


def _scripts(venv):
    return Path(venv) / ('Scripts' if os.name == 'nt' else 'bin')


def venv_exe(venv):
    return _scripts(venv) / ('onecrew.exe' if os.name == 'nt' else 'onecrew')


def venv_python(venv):
    return _scripts(venv) / ('python.exe' if os.name == 'nt' else 'python')


def make_venv(base, path):
    code, out, err = run([base, '-m', 'venv', path])
    if code != 0: raise LedgerError(f'python -m venv {path} failed: {(out + err)[-400:]}')


def pip_install(python, wheel):
    code, out, err = run([python, '-m', 'pip', 'install', '--no-index', '--no-deps', '--disable-pip-version-check', wheel])
    if code != 0: raise LedgerError(f'pip install of {Path(wheel).name} failed: {(out + err)[-400:]}')


IDENTITY = ('import hashlib, json\nfrom importlib import metadata\nd = metadata.distribution("onecrew")\nr = d.read_text("RECORD") or ""\n'
            'print(json.dumps({"version": d.version, "record_sha256": hashlib.sha256(r.encode("utf-8")).hexdigest(), '
            '"location": str(d.locate_file("onecrew"))}))')


def identity(venv):
    """{version, record_sha256, location, version_line} of the onecrew installed in `venv`, read by that venv's own interpreter."""
    code, out, err = run([venv_python(venv), '-I', '-c', IDENTITY])
    try:
        value = json.loads(out) if code == 0 else {}
    except ValueError:
        value = {}
    code, line, err2 = run([venv_exe(venv), '--version'])
    return {'version': value.get('version', 'unknown'), 'record_sha256': value.get('record_sha256', 'unknown'), 'location': value.get('location'),
            'version_line': (line or '').strip()[:300], 'error': None if value else (err or err2 or 'no answer')[-300:]}


def run_onecrew(exe, args, cwd=None, env=None):
    return run([exe, *args], cwd=cwd, env=env)


def _onecrew(exe, args):
    return run_onecrew(exe, [str(a) for a in args])


def _windows_processes():
    import ctypes
    from ctypes import wintypes as w

    class Entry(ctypes.Structure):
        _fields_ = [('dwSize', w.DWORD), ('cntUsage', w.DWORD), ('th32ProcessID', w.DWORD), ('th32DefaultHeapID', ctypes.c_void_p),
                    ('th32ModuleID', w.DWORD), ('cntThreads', w.DWORD), ('th32ParentProcessID', w.DWORD), ('pcPriClassBase', ctypes.c_long),
                    ('dwFlags', w.DWORD), ('szExeFile', ctypes.c_wchar * 260)]
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateToolhelp32Snapshot.restype = w.HANDLE
    kernel.OpenProcess.restype = w.HANDLE
    snapshot = kernel.CreateToolhelp32Snapshot(2, 0)
    if not snapshot or snapshot == w.HANDLE(-1).value: return None
    entries, entry = [], Entry()
    entry.dwSize = ctypes.sizeof(Entry)
    try:
        more = kernel.Process32FirstW(snapshot, ctypes.byref(entry))
        while more:
            entries.append((entry.th32ProcessID, entry.th32ParentProcessID, entry.szExeFile))
            more = kernel.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        kernel.CloseHandle(snapshot)

    def image(pid):
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle: return None
        try:
            size = w.DWORD(32768)
            buffer = ctypes.create_unicode_buffer(size.value)
            return buffer.value if kernel.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)) else None
        finally:
            kernel.CloseHandle(handle)
    return entries, image


def processes_under(venv):
    """[{pid, image}] of the running processes whose image is inside `venv` (this process and its ancestors excepted); None when that
    cannot be known (a process with the name of a program of the venv whose image cannot be read, or no way to list processes)."""
    venv = Path(venv).resolve()
    if os.name != 'nt': return None                       # not implemented without psutil on POSIX: unknown, the switch is refused
    try:
        listed = _windows_processes()
    except (OSError, AttributeError, ValueError):
        return None
    if listed is None: return None
    entries, image = listed
    parents = {pid: parent for pid, parent, _ in entries}
    mine, current = set(), os.getpid()
    while current and current not in mine:
        mine.add(current); current = parents.get(current)
    try:
        names = {p.name.casefold() for p in venv.rglob('*.exe')}
    except OSError:
        return None
    found = []
    for pid, _, name in entries:
        if pid in mine or name.casefold() not in names: continue
        path = image(pid)
        if path is None: return None
        if Path(path).resolve().is_relative_to(venv): found.append({'pid': pid, 'image': path})
    return found


# ---- records -------------------------------------------------------------------------------------------------------------------

def _anchor(ledger):
    from ..task_intake import submit
    return submit(ledger, support.GOAL, support.ANCHOR_KEY, mode='audit')['id']


def _emit(ledger, kind, payload):
    with ledger.transaction(write=True) as conn:
        anchor = support._anchor(conn, ledger.project_id)
        plans.emit(ledger, conn, anchor, kind, payload)
    return payload


def _records(ledger, kind, feedback=None):
    with ledger.transaction() as conn:
        anchor = support._anchor(conn, ledger.project_id) if conn else None
        rows = support._rows(conn, anchor, kind) if anchor else []
    return [dict(r['payload'], seq=r['seq']) for r in rows if feedback is None or r['payload'].get('feedback') == feedback]


def _feedback(ledger, ident):
    shown = support.show(ledger, ident)
    return shown, shown['feedback']


# ---- target (owner) --------------------------------------------------------------------------------------------------------------

def target_add(ledger, ident, venv, python=None):
    """Declare an install target: the venv OneCrew runs from for the projects that use it. The owner's verb."""
    ownership.refuse_in_ai_session('support target add')
    if not isinstance(ident, str) or not TARGET_ID.match(ident):
        raise LedgerError('--id: 1-40 lowercase letters, digits, _ . - (it becomes support_install:<id> in a fix plan grant).')
    venv = Path(venv).resolve()
    if not venv.is_dir() or not venv_exe(venv).is_file(): raise LedgerError(f'--venv {venv}: no {venv_exe(venv).name} in this venv.')
    if python is not None and not Path(python).is_file(): raise LedgerError(f'--python {python}: not a file.')
    _anchor(ledger)
    return _emit(ledger, 'support.target', {'id': ident, 'venv': str(venv), 'exe': str(venv_exe(venv)), 'python': str(python) if python else None,
                                            'by': 'owner', 'session': ownership.session_info()})


def targets(ledger):
    found = {}
    for record in _records(ledger, 'support.target'): found[record['id']] = record
    return found


# ---- the fix plan and the artifact ------------------------------------------------------------------------------------------------

def fix_plan(ledger, shown):
    """(fix ledger, state, link target) of the plan the feedback is linked to in ANOTHER project, the class being onecrew_runtime."""
    feedback = shown['feedback']
    if (shown.get('classification') or {}).get('class') != 'onecrew_runtime':
        raise LedgerError('Only a feedback classified onecrew_runtime is fixed by a OneCrew hotfix (support classify ... --class onecrew_runtime).')
    links = [l['target'] for l in shown['links'] if l['target']['kind'] == 'plan' and l['target']['project_id'] != feedback['project_id']]
    if not links: raise LedgerError('Link the fix plan of the OneCrew project first: support link FB --plan NAME --project-id ID.')
    target = links[-1]
    with ledger.transaction() as conn:
        row = conn.execute('SELECT project_path FROM tasks WHERE id=?', (target['root_task'],)).fetchone()
    if row is None or not Path(row['project_path']).is_dir(): raise LedgerError('The fix plan project is not on this machine.')
    fix = Ledger(row['project_path'], ledger.state_root)
    with fix.transaction() as conn:
        state = plans.derive(fix, conn, target['selector'])
    if state is None: raise LedgerError(f'No fix plan {target["selector"]}.')
    return fix, state, target


def _git_tree(project, commit):
    from .verifiers import command
    try:
        return command._git(project, 'rev-parse', '--verify', commit + '^{tree}')
    except Exception as error:                     # an unknown commit, or no git: the manifest names no verified tree
        raise LedgerError(f'code_commit {commit} is not a commit of the fix project ({type(error).__name__}).') from error


def bind(fix, state, commit):
    """bound_to: the fix plan record whose verified tree is the tree of `commit` (see the module docstring), or LedgerError."""
    tree = _git_tree(fix.project, commit)
    accepted = state.get('accepted') or {}
    if accepted.get('artifact_sha') == tree:
        return {'record': 'plan.accepted', 'selector': state['selector'], 'revision': accepted.get('revision'), 'tree': tree}
    approved = state.get('approved') or {}
    if not approved: raise LedgerError(f'The fix plan {state["selector"]} is not approved.')
    revision = approved['revision']
    contract = plans.load(fix, state, revision)[0]
    with fix.transaction() as conn:
        passed = [dict(json.loads(r['payload']), seq=r['seq']) for r in conn.execute(
            "SELECT seq, payload FROM events WHERE task_id=? AND kind='milestone.passed' ORDER BY seq", (state['task_id'],))]
    events = {}
    for row in passed:
        if row.get('revision') == revision and row.get('artifact_sha') == tree: events[row.get('milestone')] = row['seq']
    wanted = [m['id'] for m in contract['milestones']]
    if wanted and all(m in events for m in wanted):
        return {'record': 'milestone.passed', 'selector': state['selector'], 'revision': revision, 'tree': tree, 'events': [events[m] for m in wanted]}
    raise LedgerError(f'code_commit {commit} (tree {tree[:12]}) is not the verified or accepted tree of {state["selector"]}: '
                      'every milestone must have passed on it, or the plan must be accepted with it.')


def _wheel_version(data):
    import io
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            name = next(n for n in archive.namelist() if n.endswith('.dist-info/METADATA'))
            found = re.search(r'(?m)^Version: *(\S+)', archive.read(name).decode('utf-8', 'replace'))
            return found.group(1) if found else None
    except (zipfile.BadZipFile, StopIteration, KeyError) as error:
        raise LedgerError(f'Not a wheel: {type(error).__name__}.') from error


def artifact(ledger, ident, wheel, manifest):
    """Bind a wheel to the feedback after checking its identity (see the module docstring). The wheel bytes are stored as evidence, so the
    install later uses exactly these bytes."""
    shown, feedback = _feedback(ledger, ident)
    wheel, manifest = Path(wheel), Path(manifest)
    for path in (wheel, manifest):
        if is_link(path) or not path.is_file(): raise LedgerError(f'{path}: not a regular file.')
    data = wheel.read_bytes()
    sha = hashlib.sha256(data).hexdigest()
    document = read_json(manifest)
    if not isinstance(document, dict) or not isinstance(document.get('wheel'), dict): raise LedgerError('The manifest names no wheel.')
    if document['wheel'].get('sha256') != sha:
        raise LedgerError(f'The wheel bytes (sha256 {sha}) are not the wheel the manifest names (sha256 {document["wheel"].get("sha256")}).')
    if document['wheel'].get('name') != wheel.name: raise LedgerError(f'The manifest names {document["wheel"].get("name")}, not {wheel.name}.')
    version = _wheel_version(data)
    if not version or version != document.get('version') or f'-{version}-' not in wheel.name:
        raise LedgerError(f'The wheel version {version} is not the manifest version {document.get("version")}.')
    commit = document.get('code_commit')
    if not isinstance(commit, str) or not COMMIT.match(commit): raise LedgerError('The manifest has no code_commit.')
    fix, state, target = fix_plan(ledger, shown)
    bound = bind(fix, state, commit)
    store = Snapshots(ledger.state_root)
    payload = {'feedback': ident, 'wheel_name': wheel.name, 'wheel_sha256': sha, 'version': version, 'code_commit': commit,
               'manifest_sha': hashlib.sha256(manifest.read_bytes()).hexdigest(), 'manifest_blob': store.evidence(manifest.read_bytes()),
               'wheel_blob': store.evidence(data), 'bound_to': bound, 'fix': {'project_id': target['project_id'], 'selector': target['selector']},
               'trust': 'manifest sha == wheel bytes; commit tree == the fix plan record above; the wheel is not rebuilt from the commit'}
    return _emit(ledger, 'support.artifact', payload)


# ---- state roots: fence, copy, readers ------------------------------------------------------------------------------------------

def _skip(relative):
    return relative.name.startswith('ledger.sqlite3') or any(relative.as_posix() == s or relative.as_posix().startswith(s + '/') for s in FENCE_SKIP)


def fence(state_root):
    """A hash of the data of a state root (every SQL row, every file) that must not change between the drill and the switch. The support
    anchor's own rows and the content-addressed blobs (which only ever grow) are left out: S2 writes those itself in between."""
    state_root = Path(state_root)
    rows = {}
    path = state_root / 'ledger.sqlite3'
    if path.is_file():
        conn = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)
        try:
            conn.execute('PRAGMA query_only=ON')
            anchors = {r[0] for r in conn.execute('SELECT id FROM tasks WHERE request_key=?', (support.ANCHOR_KEY,))}
            for (table,) in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name").fetchall():
                found = conn.execute(f'SELECT * FROM "{table}"').fetchall()
                if table == 'events': found = [r for r in found if r[1] not in anchors]
                if table == 'tasks': found = [r for r in found if r[0] not in anchors]
                rows[table] = sorted(json.dumps(list(r), default=str) for r in found)
        finally:
            conn.close()
    files = {}
    for item in sorted(state_root.rglob('*')) if state_root.is_dir() else []:
        relative = item.relative_to(state_root)
        if item.is_file() and not _skip(relative): files[relative.as_posix()] = hashlib.sha256(item.read_bytes()).hexdigest()
    return content_hash({'rows': rows, 'files': files})


def copy_state(source, target):
    """A consistent copy of a state root: the ledger through sqlite's backup API, the other files as they are (support work left out)."""
    source, target = Path(source), Path(target)
    if target.exists(): shutil.rmtree(target)
    shutil.copytree(source, target, ignore=lambda folder, names: [n for n in names if Path(folder) == source and n in (WORK, 'support-spool')
                                                                    or n.startswith('ledger.sqlite3')])
    if (source / 'ledger.sqlite3').is_file():
        src = sqlite3.connect((source / 'ledger.sqlite3').as_uri() + '?mode=ro', uri=True)
        dst = sqlite3.connect(target / 'ledger.sqlite3')
        try:
            src.backup(dst)
        finally:
            src.close(); dst.close()
    return target


def _roots(state_root, project):
    path = Path(state_root) / 'ledger.sqlite3'
    if not path.is_file(): return []
    conn = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)
    try:
        key = os.path.normcase(str(Path(project).resolve()))
        return [r[0] for r in conn.execute("SELECT request_key FROM tasks WHERE project_path=? AND (request_key LIKE 'plan:%' OR request_key LIKE "
                                           "'plan-ns:%') ORDER BY created_at", (key,))]
    finally:
        conn.close()


def _read_check(exe, project, copy):
    """What a runtime proves about a copy of the data: its compat scan (of THIS copy) and `plan show` of every root of the project."""
    sha = hashlib.sha256((Path(copy) / 'ledger.sqlite3').read_bytes()).hexdigest() if (Path(copy) / 'ledger.sqlite3').is_file() else None
    code, out, err = _onecrew(exe, ['--project', project, '--state-root', copy, 'compat', 'scan', '--json'])
    problems, scan = [], {}
    try:
        report = json.loads(out) if code == 0 else None
    except ValueError:
        report = None
    if report is None:
        problems.append(f'compat scan failed (exit {code}): {(err or out)[-300:]}')
    else:
        blocking = report.get('blocking') or {}
        scan = {'ledger_sha': report.get('ledger_sha'), 'read_blocks': blocking.get('read', 0), 'continue_blocks': blocking.get('continue', 0),
                'continue_blocks_baseline': report.get('old_version'), 'grants_switch': False,
                'note': 'continue blocks are judged for the scan baseline reader, not for this pair; they neither grant nor refuse'}
        if report.get('ledger_sha') != sha: problems.append('the compat scan is not of this data (its ledger sha differs from the copy)')
        if blocking.get('read', 0): problems.append(f'compat scan: {blocking["read"]} read block(s) (records a reader cannot read)')
    reads = []
    for root in _roots(copy, project):
        code, out, err = _onecrew(exe, ['--project', project, '--state-root', copy, 'plan', 'show', root])
        reads.append({'root': root, 'exit': code})
        if code != 0: problems.append(f'plan show {root} failed (exit {code}): {(err or out)[-200:]}')
    return {'scan': scan, 'reads': reads, 'problems': problems}


# ---- consumers and the safe point -------------------------------------------------------------------------------------------------

def _same(a, b):
    try:
        return os.path.normcase(str(Path(a).resolve())) == os.path.normcase(str(Path(b).resolve()))
    except OSError:
        return False


def _programs(path):
    data, bad = installer.read_settings(path)
    if bad or not data: return set()
    return {installer.handler_words(h)[0][0] for entries in installer.our_entries(data).values() for e in entries
            for h in e.get('hooks', []) if installer.is_ours(h)}


def consumers(ledger, exe, also=None):
    """Every project whose OneCrew hook handlers run `exe` (from the hook registry, plus the reporting project), with its state root and
    the settings files that name it. A shared install has more than one consumer: all are checked and switched together. `also` (the new
    runtime) keeps a project already switched by an interrupted run in the set, so the record and a rollback still cover it."""
    registry = dict(where._read_registry(where.registry_file()))
    registry.setdefault(os.path.normcase(str(ledger.project)), str(ledger.state_root))
    found = []
    for key, state in sorted(registry.items()):
        project = Path(key)
        if not project.is_dir(): continue
        files = [str(project / '.claude' / n) for n in ('settings.local.json', 'settings.json')
                 if any(_same(p, exe) or (also is not None and _same(p, also)) for p in _programs(project / '.claude' / n))]
        if files: found.append({'project': os.path.normcase(str(project.resolve())), 'state_root': str(Path(state).resolve()), 'files': files})
    return found


def safe_point(entries, fences, venv):
    """[] when the switch may happen now, else the problems: an attempt reserved|running|unknown or an action executing|unknown in any
    consuming state root, a process running from the venv being left (or processes that cannot be listed), data changed since the drill."""
    from ..process_core import probe
    problems = []
    for state in sorted({c['state_root'] for c in entries}):
        path = Path(state) / 'ledger.sqlite3'
        if path.is_file():
            conn = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)
            conn.row_factory = sqlite3.Row
            try:
                tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                if 'attempts' in tables:
                    for row in conn.execute("SELECT id, status, identity FROM attempts WHERE status IN ('reserved','running','unknown')"):
                        try:
                            ident = json.loads(row['identity'] or '{}')
                            alive = probe(ident.get('supervisor') or ident.get('worker')) if isinstance(ident, dict) else 'unknown'
                        except Exception:
                            alive = 'unknown'
                        problems.append(f'attempt {row["id"]} is {row["status"]} (process {alive}) in {state}: reconcile it first')
                if 'actions' in tables:
                    for row in conn.execute("SELECT id, status FROM actions WHERE status IN ('executing','unknown')"):
                        problems.append(f'action {row["id"]} is {row["status"]} in {state}: reconcile it first')
            finally:
                conn.close()
        if fences.get(state) != fence(state): problems.append(f'fence: the data of {state} changed since the drill; drill again')
    running = processes_under(venv)
    if running is None: problems.append('processes: unknown (they cannot be listed here); the switch is refused and nothing is stopped')
    else: problems += [f'process {p["pid"]} runs {p["image"]}' for p in running]
    return problems, ('unknown' if running is None else running)


def repoint(entries, new_exe, old_exe, crash_after_first=False):
    """Rewrite the OneCrew hook handlers of every consuming settings file from old_exe to new_exe (as `onecrew init` writes them)."""
    store, done = None, []
    for entry in entries:
        for name in entry['files']:
            path = Path(name)
            data, bad = installer.read_settings(path)
            if bad: raise LedgerError(bad)
            if not any(_same(p, old_exe) for p in _programs(path)) and any(_same(p, new_exe) for p in _programs(path)):
                done.append({'file': name, 'changed': False}); continue
            merged = installer.merge_settings(data, hook_cli.portable_settings(Path(new_exe).resolve(), entry['state_root']))
            before = path.read_bytes()
            installer.write_text(path, installer.dump(merged))
            store = store or Snapshots(entry['state_root'])
            done.append({'file': name, 'changed': True, 'before_sha256': hashlib.sha256(before).hexdigest(),
                         'after_sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
            if crash_after_first: _crash('mid_switch')
    return done


# ---- install ------------------------------------------------------------------------------------------------------------------------

def _wheel_file(ledger, art, wheel):
    """The exact bytes support.artifact checked, written out for pip (never the path the user gave)."""
    data = Snapshots(ledger.state_root).read_evidence(art['wheel_blob'])
    if hashlib.sha256(data).hexdigest() != art['wheel_sha256']: raise LedgerError('The stored wheel bytes do not match the artifact record.')
    wheel.parent.mkdir(parents=True, exist_ok=True)
    wheel.write_bytes(data)
    return wheel


def _key(ident, art, target):
    return content_hash({'feedback': ident, 'wheel': art['wheel_sha256'], 'target': target})[:32]


def _base_python(target):
    if target.get('python'): return target['python']
    try:
        home = re.search(r'(?m)^home\s*=\s*(.+)$', (Path(target['venv']) / 'pyvenv.cfg').read_text(encoding='utf-8')).group(1).strip()
        candidate = Path(home) / ('python.exe' if os.name == 'nt' else 'python3')
        if candidate.is_file(): return str(candidate)
    except (OSError, AttributeError):
        pass
    from ..process_core import native_python
    return native_python()


def _authority(ledger, shown, target_id):
    """(result, decision context) of authority.enforce on the fix plan's root for support_install:<target>."""
    fix, state, link = fix_plan(ledger, shown)
    approved = state.get('approved') or {}
    if state['status'] not in ('approved',) or not approved:
        return {'in_authority': False, 'class': 'U2', 'reason': f'the fix plan {state["selector"]} is {state["status"]}, not approved and open'}, fix, state
    contract, sha = plans.load(fix, state, approved['revision'])
    with fix.transaction() as conn:
        try:
            ctx = internal_plan.ceilings(fix, conn, state)
        except LedgerError as error:
            return {'in_authority': False, 'class': 'U2', 'reason': f'the fix plan has no usable root budget: {error}'}, fix, state
    action = {'kind': 'support_install', 'target': target_id, 'cost': {'seconds': INSTALL_SECONDS}}
    result, _ = authority.enforce(fix, state['task_id'], contract, action, name=state['selector'], revision_sha=sha, ctx=ctx,
                                  component='onecrew.support')
    return result, fix, state


def install(ledger, ident, target_id):
    """See the module docstring. Returns the install record (result switched | blocked_by_authority | refused_by_drill | refused_unsafe)."""
    shown, feedback = _feedback(ledger, ident)
    arts = _records(ledger, 'support.artifact', ident)
    if not arts: raise LedgerError('No verified artifact for this feedback: run support artifact FB --wheel W --manifest M first.')
    art = arts[-1]
    target = targets(ledger).get(target_id)
    if target is None: raise LedgerError(f'No install target {target_id}: the owner declares it with support target add.')
    key = _key(ident, art, target_id)
    done = [r for r in _records(ledger, 'support.install', ident) if r.get('key') == key]
    if done and done[-1].get('result') == 'switched' and done[-1].get('action') == 'install':
        return dict(done[-1], already=True)
    old_venv, old_exe = Path(target['venv']), Path(target['exe'])
    result, fix, state = _authority(ledger, shown, target_id)
    allowed = bool(result.get('in_authority'))
    work = ledger.state_root / WORK / key
    venv = Path(str(old_venv) + '-' + art['version']) if allowed else work / 'trial-venv'
    wheel, marker = work / 'wheel' / art['wheel_name'], work / ('venv-' + content_hash(str(venv))[:12] + '.json')
    if venv.exists():
        found = identity(venv)
        if found.get('version') != art['version']:
            mine = marker.is_file() and json.loads(marker.read_text(encoding='utf-8')).get('venv') == str(venv)
            if not mine: raise LedgerError(f'{venv} exists and does not hold onecrew {art["version"]}: refused (an existing venv is never overwritten).')
            pip_install(venv_python(venv), _wheel_file(ledger, art, wheel))       # finish this install's own interrupted step
            found = identity(venv)
    else:
        work.mkdir(parents=True, exist_ok=True)
        marker.write_text(json.dumps({'venv': str(venv), 'key': key, 'at': utcnow()}), encoding='utf-8')
        make_venv(_base_python(target), venv)
        _crash('after_venv')
        pip_install(venv_python(venv), _wheel_file(ledger, art, wheel))
        found = identity(venv)
    if found.get('version') != art['version']:
        raise LedgerError(f'The new venv reports onecrew {found.get("version")}, not {art["version"]}: refused.')
    entries = consumers(ledger, old_exe, venv_exe(venv))
    fences, drill = {}, []
    for index, entry in enumerate(entries):
        fences[entry['state_root']] = fence(entry['state_root'])
        copy = copy_state(entry['state_root'], work / 'drill' / str(index) / 'state')
        checked = _read_check(venv_exe(venv), entry['project'], copy)
        drill.append(dict(checked, state_root=entry['state_root'], project=entry['project'], copy=str(copy)))
    problems = [p for d in drill for p in d['problems']]
    blocked = 'authority' if not allowed else ('drill' if problems else (None if entries else 'consumers'))
    prepared = {'key': key, 'feedback': ident, 'target': target_id, 'wheel_sha256': art['wheel_sha256'], 'version': art['version'],
                'venv': str(venv), 'trial': not allowed, 'identity': found, 'consumers': entries, 'fences': fences, 'drill': drill,
                'authority': {k: result.get(k) for k in ('in_authority', 'class', 'reason')}, 'blocked_by': blocked,
                'desktop_outbox': {'old': str(old_venv / 'Lib' / 'site-packages' / '.onecrew' / 'desktop'), 'carried': False,
                                   'note': 'set ONECREW_DESKTOP_HOME to keep one outbox across runtimes; pending windows of the old outbox stay there'}}
    _emit(ledger, 'support.install_prepared', prepared)
    _crash('after_prepared')
    outcome = {'key': key, 'feedback': ident, 'action': 'install', 'target': target_id, 'version': art['version'], 'old_venv': str(old_venv),
               'new_venv': str(venv), 'identity': found, 'consumers': entries}
    if blocked == 'authority':
        return dict(outcome, result='blocked_by_authority', reason=result.get('reason'), authority=prepared['authority'],
                    note='Prepared in a trial venv (not the target); nothing switched. This is not a PASS.')
    if blocked == 'drill':
        return _emit(ledger, 'support.install', dict(outcome, result='refused_by_drill', problems=problems, drill=drill))
    if blocked == 'consumers':
        return _emit(ledger, 'support.install', dict(outcome, result='refused_unsafe', problems=['no project uses this target: nothing to switch']))
    unsafe, running = safe_point(entries, fences, old_venv)
    if unsafe:
        return _emit(ledger, 'support.install', dict(outcome, result='refused_unsafe', problems=unsafe, processes=running))
    files = repoint(entries, venv_exe(venv), old_exe, crash_after_first=True)
    return _emit(ledger, 'support.install', dict(outcome, result='switched', files=files, processes=running, at=utcnow()))


def _switched(ledger, ident):
    rows = [r for r in _records(ledger, 'support.install', ident) if r.get('result') in ('switched', 'rolled_back')]
    return rows[-1] if rows and rows[-1]['result'] == 'switched' else None


def rollback(ledger, ident):
    """Repoint the hooks back to the old venv, only when the OLD runtime reads a copy of the current data; else refuse and keep the state."""
    current = _switched(ledger, ident)
    if current is None: raise LedgerError('Nothing to roll back: no switched install for this feedback.')
    work = ledger.state_root / WORK / current['key']
    old_exe = venv_exe(current['old_venv'])
    checks, problems = [], []
    for index, entry in enumerate(current['consumers']):
        copy = copy_state(entry['state_root'], work / 'rollback' / str(index) / 'state')
        checked = _read_check(old_exe, entry['project'], copy)
        checks.append(dict(checked, state_root=entry['state_root']))
        problems += checked['problems']
    base = {'key': current['key'], 'feedback': ident, 'action': 'rollback', 'target': current['target'], 'old_venv': current['old_venv'],
            'new_venv': current['new_venv'], 'consumers': current['consumers'], 'reader_pair': checks}
    if problems:
        return _emit(ledger, 'support.install', dict(base, result='refused', problems=problems,
                     reason='the old reader cannot read a copy of the current data: rollback refused, the new runtime and the ledger stay as they are'))
    fences = {e['state_root']: fence(e['state_root']) for e in current['consumers']}
    unsafe, running = safe_point(current['consumers'], fences, current['new_venv'])
    if unsafe: return _emit(ledger, 'support.install', dict(base, result='refused', problems=unsafe, reason='not a safe point', processes=running))
    files = repoint(current['consumers'], old_exe, venv_exe(current['new_venv']))
    return _emit(ledger, 'support.install', dict(base, result='rolled_back', files=files, processes=running))


# ---- recheck, resume, lesson --------------------------------------------------------------------------------------------------------

def _latest_verification(state_root, root_task, node):
    path = Path(state_root) / 'ledger.sqlite3'
    conn = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)
    try:
        row = conn.execute("SELECT seq, payload FROM events WHERE task_id=? AND kind='node.verification' AND json_extract(payload,'$.node')=? "
                           "ORDER BY seq DESC LIMIT 1", (root_task, node)).fetchone()
        return (row[0], json.loads(row[1])) if row else (0, None)
    finally:
        conn.close()


def recheck(ledger, ident):
    """Re-run the ORIGINAL node's checks through the engine with the new runtime: at the target when the switch happened, else on a named
    copy of the target's state root. A real node.verification; its receipt is the evidence."""
    shown, feedback = _feedback(ledger, ident)
    refs = feedback.get('refs') or {}
    if not (refs.get('plan') and refs.get('node') and refs.get('root_task')):
        raise LedgerError('Nothing to recheck: the report names no node of a root.')
    prepared = [r for r in _records(ledger, 'support.install_prepared', ident) if (r.get('identity') or {}).get('version') == r.get('version')]
    if not prepared: raise LedgerError('No runtime is prepared for this feedback: run support install first.')
    switched = _switched(ledger, ident)
    if switched:
        environment, state, venv = 'target', ledger.state_root, Path(switched['new_venv'])
    else:
        latest = prepared[-1]
        environment, venv = 'copy', Path(latest['venv'])
        count = len(_records(ledger, 'support.recheck', ident))
        state = copy_state(ledger.state_root, ledger.state_root / WORK / latest['key'] / f'recheck-{count + 1}' / 'state')
    before, _ = _latest_verification(state, refs['root_task'], refs['node'])
    code, out, err = _onecrew(venv_exe(venv), ['--project', str(ledger.project), '--state-root', str(state), 'engine', 'verify', refs['plan'],
                                                  refs['node']])
    seq, verification = _latest_verification(state, refs['root_task'], refs['node'])
    if verification is None or seq <= before:
        result, receipt = 'inconclusive', None
    else:
        result, receipt = verification['result'], verification['receipt']
        if environment == 'copy':
            Snapshots(ledger.state_root).blob(Snapshots(state).read_blob(receipt))      # the receipt is kept in the target's store too
    identity_now = identity(venv) if environment == 'target' else (prepared[-1].get('identity') or {})
    return _emit(ledger, 'support.recheck', {'feedback': ident, 'refs': refs, 'environment': environment, 'state_root': str(state),
                                             'venv': str(venv), 'version': identity_now.get('version'), 'exit': code, 'receipt': receipt,
                                             'result': result, 'output_tail': (err or out)[-600:] if result == 'inconclusive' else None,
                                             'recurrence_of': feedback.get('recurrence_of', [])})


def _passed_at_target(ledger, ident):
    rows = _records(ledger, 'support.recheck', ident)
    return rows[-1] if rows and rows[-1]['environment'] == 'target' and rows[-1]['result'] == 'pass' and rows[-1].get('receipt') else None


def resume(ledger, ident):
    """Continue the old work only through the engine's own guards; never extend or reopen the customer root, never reset its budget."""
    shown, feedback = _feedback(ledger, ident)
    passed = _passed_at_target(ledger, ident)
    if passed is None: raise LedgerError('Resume needs a passing recheck at the target first (support recheck).')
    refs = feedback['refs']
    with ledger.transaction() as conn:
        state = plans.derive(ledger, conn, refs['plan'])
    if state is None or state['status'] != 'approved':
        raise LedgerError(f'The root {refs.get("plan")} is {state and state["status"]}: an ended or stopped root is never extended or reopened.')
    from . import engine
    view = engine.state(ledger, refs['plan'])
    record = view['nodes'].get(refs['node']) or {}
    base = {'feedback': ident, 'root': refs['root_task'], 'plan': refs['plan'], 'node': refs['node'], 'recheck_receipt': passed['receipt'],
            'budget_reset': False, 'grants_authority': False}
    if record.get('phase') != 'held':
        return _emit(ledger, 'support.resumed', dict(base, mode='not_held', node_state=record.get('state'), generation=record.get('generation'),
                                                     note='nothing is held: the root continues by its own engine steps'))
    with ledger.transaction() as conn:
        holds = [dict(r) for r in conn.execute("SELECT * FROM requests WHERE task_id=? ORDER BY created_at", (refs['root_task'],))
                 if json.loads(r['payload'])['action']['type'] == 'v2.workflow_hold'
                 and refs['node'] in json.loads(r['payload'])['action']['parameters'].get('affected', [])]
    if not holds: raise LedgerError('The node is held without a workflow hold question: nothing can resume it here.')
    request = holds[-1]
    if request['state'] != 'answered':
        raise LedgerError(f'Waiting for the owner: onecrew question answer {request["id"]} --revision {request["revision"]} --choice continue.')
    params = json.loads(request['payload'])['action']['parameters']
    done = engine.resume_held(ledger, refs['plan'], request_id=request['id'], request_revision=request['revision'],
                              contract_sha=params['contract_sha'], generations=params['generations'])
    return _emit(ledger, 'support.resumed', dict(base, mode='resume_held', request=request['id'], generations_after=done['generations_after']))


def learn(ledger, ident, text):
    """A lesson on the FIX plan's root, only after a passing recheck at the target, citing that receipt; cause not established."""
    shown, feedback = _feedback(ledger, ident)
    passed = _passed_at_target(ledger, ident)
    if passed is None: raise LedgerError('A lesson needs a passing recheck at the target first (support recheck).')
    fix, state, target = fix_plan(ledger, shown)
    from . import knowledge
    recorded = knowledge.record(fix, state['selector'], kind='lesson', text=text, title=f'Support {ident}',
                                evidence={'status': 'verified', 'sources': [{'type': 'receipt', 'key': passed['receipt']}],
                                          'property': f'the original check of node {passed["refs"]["node"]} passed at the target with OneCrew '
                                                      f'{passed.get("version")} (support recheck)'})
    return dict(recorded, root=state['selector'], feedback=ident, certainty='verified at the target; cause not established')
