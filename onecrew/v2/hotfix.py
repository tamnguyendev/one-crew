"""2.4-S2: feedback -> fix plan -> artifact -> install at a declared target -> recheck of the original error -> resume, with evidence.

Records (class A, on the support anchor of the reporting project; nothing is written on the customer root except what the engine itself
writes when the recheck re-runs the original check):

  support.target            {id, venv, exe, python, consumers, replaces}   OWNER verb `support target add` (refused in an AI session)
  support.artifact          {feedback, wheel_sha256, record_sha256, version, code_commit, tree, files_checked, bound_to, wheel_blob, ...}
  support.install_prepared  {key, venv, trial, identity, consumers, drill, authority, blocked_by}
  support.install           phase claim | release | intent | switched_one, or a final {key, action: install|rollback, result, ...}
  support.recheck           {feedback, refs, environment: target|copy, at_runtime, receipt, result} (an intent first)
  support.resumed           {feedback, root, node, mode, request, budget_reset: False, grants_authority: False}

Authority (install AND rollback): the approved contract of the linked FIX plan (another project: the OneCrew repo) must name
`support_install:<target id>` in authority.granted_actions, checked through authority.enforce on that root with its remaining budget. A
report, a log line, a hash in a text, a manifest or a project edit grant never grants it. Without the grant the dependent effect is blocked
(blocked_by_authority) while the preparation still completes in a trial venv under the state root. `support rollback` and `support target
add` are owner verbs (refused when CLAUDE_CODE_CHILD_SESSION or CLAUDECODE is set).

Artifact identity (S2-R01): the manifest is evidence, never authority. The wheel CONTENT is bound to the commit: every file the wheel ships
under onecrew/ must be byte-equal to that file at `code_commit` in the fix project (the raw blob, or the same text with CRLF line ends as a
Windows checkout writes it), the set of shipped files must be exactly what that commit's pyproject declares (py-modules, the __init__ of
their packages, onecrew/templates/*.md), RECORD must list exactly those files plus the dist-info files with their right hashes, METADATA
must name onecrew at the pyproject version of that commit; and the commit's tree must be the tree OneCrew verified for the fix plan
(`plan.accepted.artifact_sha`, else a `milestone.passed.artifact_sha` of every milestone of the approved revision). Limit: the build itself
is not repeated; what is proven is "this wheel holds exactly the files of the verified commit".

Install: always a NEW venv beside the declared one, `<venv>-<version>-<wheel sha8>`, never a change to the old venv; a folder that already
exists is reused only when it IS the bound wheel (verify_installed: the content of every file against the verified wheel rows, never the
venv's own RECORD; the files its `onecrew` executable loads; Codex r1 F1), else refused, never deleted. Drill on a copy of every consuming
state root (ledger, plans/ and the blobs those roots reference), fenced BEFORE the copy, the copy holding exactly the fenced data. Switch
only at a safe point (the fence compared again), inside an exclusive claim, with an intent recorded before each repoint; the window, the
fence and the processes of the runtime being left are re-checked after it (Codex r1 F2).

Round 2 (review-s2-r2): a venv OneCrew makes gets a creation baseline (every file the wheel does not give: pyvenv.cfg, Scripts/, the rest of
site-packages) recorded right after its first passing check; every later judgement matches it, and no program of a venv runs before its
static checks pass. The fence, the new venv and the claim are checked again right before the first hook file is written; the claim is a
lease renewed before each phase and taken over only from an expired lease or a holder process that is gone on this host. An install that
ends in switch_window_violation can be rolled back; the rollback checks the old venv is the one recorded at the install.

Round 3 (review-s2-r3): no final record is a dead end: after a violation on either side, install and rollback both run again (each drills the
current data); status says what the hooks run now and why. The switch window is from the snapshot right before the first hook write to the
one right after the last. A venv folder without a baseline in this ledger is never reused or run (the owner removes an interrupted one of
this ledger with `support cleanup --venv`); each ledger has its own venv (`-<state root8>`); the target's base python is resolved without
fallback and its `home` is re-checked at every judgement. Rollback only when the OLD runtime reads the current data (see rollback). `installed` and `verified_at_target` are projected against
what the consumers' hook handlers run NOW.
"""
import ast
import base64
import csv
import hashlib
import io
import json
import os
import re
import shutil
import socket
import sqlite3
import subprocess
import sys
import tomllib
import uuid
import zipfile
from pathlib import Path

from ..ledger import Ledger, LedgerError, canonical, content_hash, utcnow
from ..snapshots import Snapshots, is_link
from . import authority, hook_cli, install as installer, internal_plan, namespaces, ownership, plan as plans, support, where

TARGET_ID = re.compile(r'[a-z0-9_.-]{1,40}\Z')
COMMIT = re.compile(r'[0-9a-f]{40}([0-9a-f]{24})?\Z')
HEX64 = re.compile(r'[0-9a-f]{64}')
WORK = 'support-work'
INSTALL_SECONDS = 600
CLAIM_SECONDS = 900
FENCE_SKIP = (WORK, 'support-spool', 'snapshots/blobs', 'notifications', 'hook-projects.json', 'backups')
CRASH_ENV = 'ONECREW_SUPPORT_CRASH'
DIST_FILES = ('METADATA', 'WHEEL', 'RECORD', 'entry_points.txt')
PROVEN = 'readable and state-derivable with the old runtime; end-to-end continuation not proven'
NOT_ENUMERATED = ['the OneCrew host service, MCP or Codex configurations and scripts that run the old executable are not enumerated '
                  '(only Claude Code hook handlers and the target\'s declared consumers are)']
FINALS = ('switched', 'rolled_back', 'refused', 'refused_by_drill', 'refused_unsafe', 'blocked_by_authority', 'switch_window_violation')
_ACTIVE = set()                                     # claim tokens held by this process (a crashed holder's token is not here)
_TAKEN = {}                                         # token -> the claim it took over (claim_taken_over_from of the final record)


class Crash(RuntimeError):
    """A fixture crash point (ONECREW_SUPPORT_CRASH=<point>): the process stops as if killed there."""


def _crash(point):
    if os.environ.get(CRASH_ENV) == point: raise Crash(f'fixture crash at {point}')


def _ai_session():
    return any(name in os.environ for name in ('CLAUDE_CODE_CHILD_SESSION', 'CLAUDECODE'))


def _refuse_ai(what):
    if _ai_session():
        raise LedgerError(f'{what} refused: this process runs inside an AI tool session (CLAUDE_CODE_CHILD_SESSION or CLAUDECODE is set). '
                          'The owner runs it in a terminal of their own.')


# ---- the venv side (replaceable in tests) -------------------------------------------------------------------------------------

def run(argv, cwd=None, env=None, timeout=900, data=None):
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


INTERPRETER = ('import importlib.util, json, marshal, sys\n'
               'out = {"base_prefix": sys.base_prefix, "base_exec_prefix": sys.base_exec_prefix, "tag": sys.implementation.cache_tag, "pyc": {}}\n'
               'for path in json.loads(sys.argv[1]):\n'
               '    try:\n'
               '        source = importlib.util.source_from_cache(path)\n'
               '        data = open(path, "rb").read()\n'
               '        if data[:4] != importlib.util.MAGIC_NUMBER:\n'
               '            out["pyc"][path] = "other interpreter"; continue\n'
               '        level = 2 if ".opt-2." in path else 1 if ".opt-1." in path else 0\n'
               '        code = compile(open(source, "rb").read(), source, "exec", dont_inherit=True, optimize=level)\n'
               '        out["pyc"][path] = "same" if marshal.loads(data[16:]) == code else "differs"\n'
               '    except ValueError:\n'
               '        out["pyc"][path] = "other interpreter"\n'
               '    except Exception as error:\n'
               '        out["pyc"][path] = "unreadable: " + type(error).__name__\n'
               'print(json.dumps(out))')


def interpreter(venv, caches):
    """What the venv's own interpreter says when started with -I -S (no site, no .pth: no code of the venv runs): its base prefix and cache
    tag, and for each bytecode cache whether its code is the compile of its source (Python loads a cache instead of the source)."""
    code, out, err = run([venv_python(venv), '-I', '-S', '-c', INTERPRETER, json.dumps([str(c) for c in caches])], timeout=300)
    try:
        return json.loads(out) if code == 0 else {'error': (err or out or f'exit {code}')[-300:]}
    except ValueError:
        return {'error': (out or err or 'no answer')[-300:]}


def entry_run(venv):
    """(exit, stdout, stderr) of the venv's `onecrew --version` under PYTHONVERBOSE=1: the interpreter itself writes where every module the
    executable loads comes from. No bytecode is written into the venv."""
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith('PYTHON')}
    env.update(PYTHONVERBOSE='1', PYTHONDONTWRITEBYTECODE='1')
    return run([venv_exe(venv), '--version'], cwd=venv, env=env, timeout=300)


LOADED = re.compile(r"^# (?:code object from|extension module '[^']*' loaded from) (.+?)\s*$")


def site_packages(venv):
    """The site-packages folder of a venv, from its layout (no code of the venv runs to find it); None when it is not one folder."""
    venv = Path(venv)
    if os.name == 'nt': return venv / 'Lib' / 'site-packages'
    found = sorted((venv / 'lib').glob('python3*/site-packages'))
    return found[0] if len(found) == 1 else None


def _linked(site, relative):
    """True when the file, or a folder between site-packages and it, is a link or junction (its content is then somewhere else)."""
    path = Path(site)
    for part in relative.split('/'):
        path = path / part
        if is_link(path): return True
    return False


def _loaded(text):
    """The files the interpreter reports loading (PYTHONVERBOSE lines); None for a line whose path cannot be read."""
    found = []
    for line in (text or '').splitlines():
        match = LOADED.match(line)
        if not match: continue
        text = match.group(1)
        if text[:1] not in ('"', "'"):                # R2-04: a module loaded from source is written without quotes
            found.append(text); continue
        try:
            found.append(str(ast.literal_eval(text)))
        except (ValueError, SyntaxError):
            found.append(None)
    return found


def _source_of(relative):
    """The source a bytecode cache path stands for (pkg/__pycache__/m.cpython-313.pyc -> pkg/m.py); other paths unchanged."""
    if '/__pycache__/' not in relative or not relative.endswith('.pyc'): return relative
    folder, name = relative.rsplit('/__pycache__/', 1)
    return f'{folder}/{name.split(".")[0]}.py'


def _console_modules(site, rows):
    """The modules the console scripts of the bound wheel run (its entry_points.txt, whose bytes are compared with the rows first)."""
    entry = next((p for p, _ in rows if p.endswith('.dist-info/entry_points.txt')), None)
    if entry is None or not (Path(site) / entry).is_file(): return []
    section, modules = None, []
    for line in (Path(site) / entry).read_text(encoding='utf-8', errors='replace').splitlines():
        line = line.strip()
        if line.startswith('['): section = line; continue
        if section == '[console_scripts]' and '=' in line: modules.append(line.split('=', 1)[1].split(':')[0].strip())
    return modules


DATA_DIR = '.onecrew'                                 # site-packages/.onecrew: the runtime's own data (desktop outbox), not code
PYC_LEFTOVER = re.compile(r'\.pyc\.\d+\Z')            # R2-11: an importlib temporary file left by an interrupted compile


def _walk(root):
    """(path, is_link) of every file under `root`, never entering a link or junction."""
    stack = [Path(root)]
    while stack:
        folder = stack.pop()
        try:
            items = sorted(folder.iterdir())
        except OSError:
            continue
        for item in items:
            if is_link(item): yield item, True
            elif item.is_dir(): stack.append(item)
            else: yield item, False


def venv_tree(venv, art=None):
    """R2-01/R2-08: {relative path: sha256 | 'link'} of the files of a venv the bound wheel does not give: pyvenv.cfg, Scripts/ (python.exe,
    pythonw.exe, onecrew.exe, the pip launchers), pip and every other entry of site-packages. With `art`, the wheel's row files and the
    files under its package folders (judged one by one by identity) are left out; without it (the old runtime), bytecode caches are. The
    runtime's own data folder site-packages/.onecrew is left out in both."""
    venv, site = Path(venv), site_packages(venv)
    rows = {p for p, _ in art['rows']} if art else set()
    tops = {p.split('/')[0] for p in rows if '/' in p and '.dist-info/' not in p}
    out = {}
    for item, link in _walk(venv):
        relative = item.relative_to(venv).as_posix()
        if site is not None and item.is_relative_to(site):
            inner = item.relative_to(site).as_posix()
            if inner == DATA_DIR or inner.startswith(DATA_DIR + '/') or inner in rows or inner.split('/')[0] in tops: continue
        if not art and '__pycache__' in relative.split('/'): continue
        out[relative] = 'link' if link else hashlib.sha256(item.read_bytes()).hexdigest()
    return out


def _pyvenv(venv):
    """{home, system_site} of a venv's pyvenv.cfg, None when it cannot be read."""
    try:
        text = (Path(venv) / 'pyvenv.cfg').read_text(encoding='utf-8-sig')
    except (OSError, UnicodeDecodeError):
        return None
    values = {}
    for line in text.splitlines():
        if '=' in line:
            name, value = line.split('=', 1)
            values[name.strip().casefold()] = value.strip()
    return {'home': values.get('home'), 'system_site': values.get('include-system-site-packages', '').casefold()}


def venv_baseline(venv, art):
    """R2-01: what the product records right after it made a venv, installed the wheel and the venv passed the creation check: every file
    the wheel does not give, with its sha256, and the pyvenv.cfg values. Every later judgement of that venv must match it exactly."""
    tree = venv_tree(venv, art)
    return {'digest': content_hash(tree), 'tree': tree, 'pyvenv': _pyvenv(venv), 'files': len(tree)}


def _static(venv, art, baseline=None, home=None):
    """The checks that run NO program of the venv (R2-03): (facts, problems)."""
    venv = Path(venv)
    site = site_packages(venv)
    wanted = {p: h for p, h in art['rows'] if not p.endswith('.dist-info/RECORD')}
    out = {'site': str(site) if site else None, 'location': str(site / 'onecrew') if site else None, 'files': {}, 'linked': [], 'extras': [],
           'caches': {}, 'cache_files': [], 'pth': [], 'loaded': [], 'outside': [], 'entry_modules': [], 'exit': None, 'version_line': '',
           'version': 'unknown', 'present': False, 'error': None, 'ran': False, 'pyvenv': _pyvenv(venv)}
    if site is None or not site.is_dir():
        out['error'] = f'no site-packages folder in {venv}'
        return out, [out['error']]
    for path in sorted(wanted):
        if _linked(site, path):
            out['linked'].append(path); continue
        out['files'][path] = _hash((site / path).read_bytes()) if (site / path).is_file() else None
    out['present'] = any(v is not None for v in out['files'].values())
    sources = {p for p in wanted if p.endswith('.py')}
    for top in sorted({p.split('/')[0] for p in wanted if '/' in p and '.dist-info/' not in p}):
        folder = site / top
        if is_link(folder) or not folder.is_dir(): continue                       # already a linked or missing file of the wheel
        for item, link in _walk(folder):
            relative = item.relative_to(site).as_posix()
            if relative in wanted: continue
            if link: out['linked'].append(relative); continue
            if item.parent.name == '__pycache__' and (item.suffix == '.pyc' or PYC_LEFTOVER.search(item.name)):
                if item.suffix == '.pyc' and _source_of(relative) in sources: out['cache_files'].append(str(item))
                continue                                  # never loaded: a leftover, or a cache of no wheel source
            out['extras'].append(relative)
    for pth in sorted(site.glob('*.pth')):
        try:
            lines = pth.read_bytes().decode('utf-8-sig').splitlines()           # R2-01: as site.py reads it
        except (OSError, UnicodeDecodeError):
            out['pth'].append(f'{pth.name} (cannot be decoded as UTF-8)'); continue
        if any(line.startswith(('import ', 'import\t')) for line in lines): out['pth'].append(pth.name)
    meta = next((p for p in wanted if p.endswith('.dist-info/METADATA')), None)
    if meta and out['files'].get(meta):
        found = re.search(r'(?m)^Version: *(\S+)\s*$', (site / meta).read_text(encoding='utf-8', errors='replace'))
        out['version'] = found.group(1) if found else 'unknown'
    if not any(p.endswith('.dist-info/entry_points.txt') and out['files'].get(p) not in (None, h) for p, h in wanted.items()):
        out['entry_modules'] = _console_modules(site, art['rows'])
    problems = []
    files, linked = out['files'], sorted(out['linked'])
    missing = sorted(p for p in wanted if p not in linked and files.get(p) is None)
    differ = sorted(p for p, h in wanted.items() if files.get(p) is not None and files[p] != h)
    if differ: problems.append(f'its installed files are not the bound wheel (the content differs): {", ".join(differ[:5])}')
    if missing: problems.append(f'files of the bound wheel are missing: {", ".join(missing[:5])}')
    if linked: problems.append(f'links or junctions stand in the installed tree: {", ".join(linked[:5])}')
    if out['extras']: problems.append(f'files the bound wheel does not hold, in its package folders: {", ".join(out["extras"][:5])}')
    if out['pth']: problems.append(f'.pth files run code at every start of this venv: {", ".join(out["pth"][:5])}')
    if out['version'] != art['version']: problems.append(f'it holds onecrew {out["version"]}, not {art["version"]}')
    cfg = out['pyvenv']
    if cfg is None: problems.append('pyvenv.cfg cannot be read')
    elif cfg['system_site'] != 'false': problems.append(f'pyvenv.cfg: include-system-site-packages is {cfg["system_site"] or "unset"}, not false')
    elif home is not None and (not cfg['home'] or not _same(cfg['home'], home)):
        problems.append(f'pyvenv.cfg: home is {cfg["home"]}, not {home} (the base python the venv was made with)')
    if baseline is not None:
        now = venv_tree(venv, art)
        then = baseline.get('tree') or {}
        changed = sorted(p for p in set(now) | set(then) if now.get(p) != then.get(p))
        if changed: problems.append(f'the venv differs from the baseline recorded when OneCrew made it: {", ".join(changed[:5])}')
    return out, problems


def identity(venv, art, baseline=None, home=None, run_programs=True):
    """Codex r1 F1 + round 2: what the files of `venv` and its running executable show, against the VERIFIED wheel rows of `art` (never the
    venv's own RECORD or metadata) and against the creation baseline (`baseline`, or `home` when the venv is being made). Static checks
    first (R2-03): wheel file content, links, extra files, .pth start-up code (read as UTF-8 with BOM, like site.py), pyvenv.cfg, every
    other file of the venv. Only when all pass, programs of the venv run: its interpreter (-I -S) compares bytecode caches with their
    source, and its `onecrew --version` shows what it loads. `static` holds the static problems."""
    out, static = _static(venv, art, baseline, home)
    out['static'] = static
    if static or not run_programs: return out
    venv, site = Path(venv), Path(out['site'])
    out['ran'] = True
    facts = interpreter(venv, out['cache_files'])
    if facts.get('error'): out['error'] = 'the venv interpreter did not answer: ' + facts['error']
    for path, verdict in (facts.get('pyc') or {}).items():
        out['caches'][Path(path).relative_to(site).as_posix()] = verdict
    code, stdout, stderr = entry_run(venv)
    out.update(exit=code, version_line=(stdout or '').strip()[:300])
    bases = [Path(p).resolve() for p in (facts.get('base_prefix'), facts.get('base_exec_prefix')) if p]
    here, launcher = site.resolve(), venv_exe(venv).resolve()
    for path in _loaded(stderr):
        if path is None:
            out['outside'].append('(a path the interpreter wrote that cannot be read)'); continue
        file = Path(path).resolve()
        if file.is_relative_to(here): out['loaded'].append(file.relative_to(here).as_posix())
        elif file == launcher or file.is_relative_to(launcher): continue                     # the launcher's own __main__
        elif any(file.is_relative_to(b) for b in bases) and 'site-packages' not in {p.casefold() for p in file.parts}: continue   # stdlib
        else: out['outside'].append(str(file))
    return out


def run_onecrew(exe, args, cwd=None, env=None):
    return run([exe, *args], cwd=cwd, env=env)


def _onecrew(exe, args):
    return run_onecrew(exe, [str(a) for a in args])


CLASSES = ('import json, sys\nfrom onecrew.v2 import compat\n'
           'print(json.dumps({k: compat.event_class(k) for k in json.loads(sys.argv[1])}))')


def event_classes(venv, kinds):
    """{kind: '0' | 'A' | 'B' | None} as the runtime of `venv` itself classifies them (None: a kind that runtime does not know)."""
    code, out, err = run([venv_python(venv), '-I', '-c', CLASSES, json.dumps(sorted(kinds))])
    try:
        return json.loads(out) if code == 0 else None
    except ValueError:
        return None


def platform():
    return os.name


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
    cannot be known (a process with the name of a program of the venv whose image cannot be read, or no way to list processes: any
    platform but Windows here). An empty list means none seen through the venv's own launchers (a base interpreter running the venv's code
    is not seen)."""
    venv = Path(venv).resolve()
    if platform() != 'nt': return None
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


def _emit(ledger, kind, payload, conn=None):
    if conn is not None:
        plans.emit(ledger, conn, support._anchor(conn, ledger.project_id), kind, payload)
        return payload
    with ledger.transaction(write=True) as connection:
        plans.emit(ledger, connection, support._anchor(connection, ledger.project_id), kind, payload)
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

def target_add(ledger, ident, venv, python=None, consumers=(), replace=False):
    """Declare an install target: the venv OneCrew runs from for the projects that use it. The owner's verb. A target id is immutable:
    declaring it again is refused unless the owner passes replace, which records the previous declaration (S2-R10)."""
    _refuse_ai('support target add')
    ownership.refuse_in_ai_session('support target add')
    if not isinstance(ident, str) or not TARGET_ID.match(ident):
        raise LedgerError('--id: 1-40 lowercase letters, digits, _ . - (it becomes support_install:<id> in a fix plan grant).')
    venv = Path(venv).resolve()
    if not venv.is_dir() or not venv_exe(venv).is_file(): raise LedgerError(f'--venv {venv}: no {venv_exe(venv).name} in this venv.')
    if python is not None and not Path(python).is_file(): raise LedgerError(f'--python {python}: not a file.')
    hints = []
    for item in consumers or ():
        project = Path(item).resolve()
        if not project.is_dir(): raise LedgerError(f'--consumers {item}: not a folder.')
        hints.append(os.path.normcase(str(project)))
    previous = targets(ledger).get(ident)
    if previous and not replace:
        raise LedgerError(f'Target {ident} is already declared ({previous["venv"]}); a target id is immutable: --replace (owner) records the change.')
    _anchor(ledger)
    return _emit(ledger, 'support.target', {'id': ident, 'venv': str(venv), 'exe': str(venv_exe(venv)), 'python': str(python) if python else None,
                                            'consumers': hints, 'replaces': previous and {k: previous.get(k) for k in ('venv', 'exe', 'python', 'seq')},
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


def _git(project, *args, data=None):
    done = subprocess.run(['git', '-C', str(project), *args], input=data, capture_output=True, timeout=300)
    if done.returncode != 0: raise LedgerError(f'git {" ".join(args[:2])} failed: {done.stderr.decode("utf-8", "replace")[-300:]}')
    return done.stdout


def _blobs(project, commit, paths):
    """{path: bytes or None} of `paths` at `commit` (the raw blobs), through one `git cat-file --batch`."""
    specs = [f'{commit}:{p}' for p in paths]
    out = _git(project, 'cat-file', '--batch', data=('\n'.join(specs) + '\n').encode('utf-8'))
    result, pos = {}, 0
    for path in paths:
        end = out.index(b'\n', pos)
        header = out[pos:end].decode('utf-8', 'replace').split()
        pos = end + 1
        if len(header) < 3 or header[-1] == 'missing':
            result[path] = None
            continue
        size = int(header[2])
        result[path] = out[pos:pos + size]
        pos += size + 1
    return result


def _hash(data):
    return 'sha256=' + base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b'=').decode()


def record_digest(rows):
    """The digest of a wheel's file list: sha256 of the sorted [path, hash] rows, RECORD itself left out. The installed RECORD of the same
    wheel gives the same digest over those paths (pip adds INSTALLER, REQUESTED, caches: other paths)."""
    return hashlib.sha256(canonical(sorted([p, h] for p, h in rows if not p.endswith('.dist-info/RECORD'))).encode('utf-8')).hexdigest()


def check_wheel(project, commit, data):
    """S2-R01: what the wheel bytes prove against `commit` of the fix project (see the module docstring), or LedgerError naming the files."""
    try:
        listing = set(_git(project, 'ls-tree', '-r', '--name-only', commit).decode('utf-8').splitlines())
        meta = tomllib.loads(_git(project, 'show', f'{commit}:pyproject.toml').decode('utf-8'))
    except (LedgerError, ValueError, UnicodeDecodeError) as error:
        raise LedgerError(f'code_commit {commit}: no readable pyproject.toml in the fix project ({error})') from error
    version = (meta.get('project') or {}).get('version')
    tool = (meta.get('tool') or {}).get('setuptools') or {}
    modules, packages = tool.get('py-modules') or [], tool.get('packages') or []
    if not version or not modules: raise LedgerError(f'code_commit {commit}: the pyproject declares no version or no py-modules.')
    expected = {m.replace('.', '/') + '.py' for m in modules}
    parents = {'/'.join(m.split('.')[:i]) for m in modules for i in range(1, len(m.split('.')))} | {p.replace('.', '/') for p in packages}
    expected |= {p + '/__init__.py' for p in parents if p + '/__init__.py' in listing}
    expected |= {n for n in listing if n.startswith('onecrew/templates/') and n.count('/') == 2 and n.endswith('.md')}
    absent = sorted(expected - listing)
    if absent: raise LedgerError(f'code_commit {commit} does not hold what its pyproject declares: {", ".join(absent[:5])}')
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as error:
        raise LedgerError('Not a wheel.') from error
    dist = f'onecrew-{version}.dist-info/'
    names = [n for n in archive.namelist() if not n.endswith('/')]
    shipped = {n for n in names if not n.startswith(dist)}
    extra, missing = sorted(shipped - expected), sorted(expected - shipped)
    if extra: raise LedgerError(f'The wheel ships files that {commit[:12]} does not declare: {", ".join(extra[:5])}')
    if missing: raise LedgerError(f'The wheel lacks files that {commit[:12]} declares: {", ".join(missing[:5])}')
    others = sorted(n for n in names if n.startswith(dist) and n[len(dist):] not in DIST_FILES)
    if others or dist + 'METADATA' not in names or dist + 'RECORD' not in names:
        raise LedgerError(f'The wheel dist-info is not {", ".join(DIST_FILES)}: {", ".join(others[:5]) or "METADATA or RECORD missing"}')
    metadata = archive.read(dist + 'METADATA').decode('utf-8', 'replace')
    if not re.search(r'(?m)^Name: *onecrew\s*$', metadata) or not re.search(rf'(?m)^Version: *{re.escape(version)}\s*$', metadata):
        raise LedgerError(f'The wheel METADATA does not name onecrew {version} (the pyproject version at {commit[:12]}).')
    raw = _blobs(project, commit, sorted(shipped))
    same = lambda data, blob: blob is not None and (data == blob or (b'\r' not in blob and data.replace(b'\r\n', b'\n') == blob))
    differ = [n for n in sorted(shipped) if not same(archive.read(n), raw[n])]
    if differ: raise LedgerError(f'The wheel files differ from {commit[:12]}: {", ".join(differ[:5])}')
    rows = list(csv.reader(io.StringIO(archive.read(dist + 'RECORD').decode('utf-8'))))
    listed = {r[0]: r[1] if len(r) > 1 else '' for r in rows if r}
    if set(listed) != set(names): raise LedgerError('The wheel RECORD does not list exactly the files of the wheel.')
    wrong = [n for n in names if n != dist + 'RECORD' and listed[n] != _hash(archive.read(n))]
    if wrong: raise LedgerError(f'The wheel RECORD hashes do not match: {", ".join(wrong[:5])}')
    return {'version': version, 'files_checked': len(shipped), 'rows': [[p, h] for p, h in sorted(listed.items())],
            'record_sha256': record_digest(listed.items()), 'line_endings': 'raw' if all(archive.read(n) == raw[n] for n in shipped) else 'crlf checkout'}


def bind(fix, state, commit):
    """bound_to: the fix plan record whose verified tree is the tree of `commit` (see the module docstring), or LedgerError."""
    try:
        tree = _git(fix.project, 'rev-parse', '--verify', commit + '^{tree}').decode().strip()
    except LedgerError as error:
        raise LedgerError(f'code_commit {commit} is not a commit of the fix project.') from error
    accepted = state.get('accepted') or {}
    if accepted.get('artifact_sha') == tree:
        return {'record': 'plan.accepted', 'selector': state['selector'], 'revision': accepted.get('revision'), 'tree': tree,
                'note': 'an accepted plan is ended: an install needs an approved, open fix plan (S2-R13)'}
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


def artifact(ledger, ident, wheel, manifest):
    """Bind a wheel to the feedback after checking its CONTENT against the verified commit (S2-R01). The manifest only says which commit to
    check; its claims must agree with what the bytes prove. The wheel bytes are stored and are what the install later uses."""
    shown, feedback = _feedback(ledger, ident)
    wheel, manifest = Path(wheel), Path(manifest)
    for path in (wheel, manifest):
        if is_link(path) or not path.is_file(): raise LedgerError(f'{path}: not a regular file.')
    data, manifest_bytes = wheel.read_bytes(), manifest.read_bytes()          # each read once (S2-R18)
    sha = hashlib.sha256(data).hexdigest()
    try:
        document = json.loads(manifest_bytes.decode('utf-8-sig'))
    except ValueError as error:
        raise LedgerError('The manifest is not JSON.') from error
    if not isinstance(document, dict) or not isinstance(document.get('wheel'), dict): raise LedgerError('The manifest names no wheel.')
    if document['wheel'].get('sha256') != sha:
        raise LedgerError(f'The wheel bytes (sha256 {sha}) are not the wheel the manifest names (sha256 {document["wheel"].get("sha256")}).')
    if document['wheel'].get('name') != wheel.name: raise LedgerError(f'The manifest names {document["wheel"].get("name")}, not {wheel.name}.')
    commit = document.get('code_commit')
    if not isinstance(commit, str) or not COMMIT.match(commit): raise LedgerError('The manifest has no code_commit.')
    fix, state, target = fix_plan(ledger, shown)
    bound = bind(fix, state, commit)
    checked = check_wheel(fix.project, commit, data)
    if checked['version'] != document.get('version') or f'-{checked["version"]}-' not in wheel.name:
        raise LedgerError(f'The wheel is onecrew {checked["version"]} (pyproject at {commit[:12]}); the manifest or file name says otherwise.')
    store = Snapshots(ledger.state_root)
    payload = {'feedback': ident, 'wheel_name': wheel.name, 'wheel_sha256': sha, 'record_sha256': checked['record_sha256'],
               'version': checked['version'], 'code_commit': commit, 'tree': bound['tree'], 'files_checked': checked['files_checked'],
               'line_endings': checked['line_endings'], 'manifest_sha': hashlib.sha256(manifest_bytes).hexdigest(),
               'manifest_blob': store.evidence(manifest_bytes), 'wheel_blob': store.evidence(data), 'bound_to': bound,
               'fix': {'project_id': target['project_id'], 'selector': target['selector']}, 'rows': checked['rows'],
               'trust': 'every shipped file equals the verified commit; RECORD and METADATA checked; the manifest is evidence only'}
    return _emit(ledger, 'support.artifact', payload)


# ---- state roots: fence, copy, readers ------------------------------------------------------------------------------------------

def _skip(relative):
    return relative.name.startswith('ledger.sqlite3') or any(relative.as_posix() == s or relative.as_posix().startswith(s + '/') for s in FENCE_SKIP)


def fence(state_root):
    """A hash of the data of a state root (every SQL row, every file) that must not change between the drill and the switch. The support
    anchor's own rows and the content-addressed blobs (which only ever grow) are left out: S2 writes those itself in between."""
    return _fenced(state_root)[0]


def _fenced(state_root):
    """(fence, data) from ONE read of the state root: data is the digest of what a drill copy holds (every SQL row but the support
    anchor's, the files under plans/), so the copy can be compared with the fenced state (Codex r1 F2)."""
    rows, files = _fence_parts(state_root)
    return content_hash({'rows': rows, 'files': files}), content_hash({'rows': rows, 'plans': {k: v for k, v in files.items() if k.startswith('plans/')}})


def _fence_parts(state_root):
    state_root = Path(state_root)
    rows = {}
    path = state_root / 'ledger.sqlite3'
    if path.is_file():
        conn = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)
        try:
            conn.execute('PRAGMA query_only=ON')
            conn.execute('BEGIN')                     # every table from one read snapshot
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
    return rows, files


def _drill_copy(state, target, project, fences, datas):
    """Codex r1 F2: fence a consuming state root BEFORE its first copy (once per state root, so the drill of a second consumer of the
    same root never moves it), then copy it; (copy, bytes, problems), a problem when the copy does not hold exactly the fenced data."""
    if state not in fences: fences[state], datas[state] = _fenced(state)
    copy, size = copy_state(state, target, project=project)
    moved = [] if _fenced(copy)[1] == datas[state] else [f'fence: the data of {state} changed between its fence and its copy; nothing was '
                                                          'switched, run it again']
    return copy, size, moved


def _referenced_blobs(source, project):
    """The blob keys the roots of `project` (and their child tasks) reference, transitively through JSON blobs (S2-R12)."""
    store, seen, todo = Snapshots(source), set(), []
    conn = sqlite3.connect((Path(source) / 'ledger.sqlite3').as_uri() + '?mode=ro', uri=True)
    try:
        key = os.path.normcase(str(Path(project).resolve())) if project else None
        rows = conn.execute("SELECT e.payload FROM events e JOIN tasks t ON t.id=e.task_id WHERE (? IS NULL OR t.project_path=?) AND "
                            "(t.request_key LIKE 'plan:%' OR t.request_key LIKE 'plan-ns:%' OR t.request_key LIKE 'wf:%')", (key, key)).fetchall()
    finally:
        conn.close()
    for (payload,) in rows: todo += HEX64.findall(payload)
    while todo:
        blob = todo.pop()
        if blob in seen: continue
        path = Path(source) / 'snapshots' / 'blobs' / blob
        if not path.is_file(): continue
        seen.add(blob)
        if path.stat().st_size <= 2_000_000:
            text = path.read_bytes()
            if text[:1] in (b'{', b'['): todo += HEX64.findall(text.decode('utf-8', 'replace'))
    return seen


def copy_state(source, target, project=None, full=False):
    """A consistent copy of a state root: the ledger through sqlite's backup API, plans/, and (unless full) only the blobs the roots of
    `project` reference. Returns (copy, bytes copied)."""
    source, target = Path(source), Path(target)
    if target.exists(): shutil.rmtree(target)
    target.mkdir(parents=True)
    if full:
        shutil.rmtree(target)
        shutil.copytree(source, target, ignore=lambda folder, names: [n for n in names if Path(folder) == source and n in (WORK, 'support-spool')
                                                                        or n.startswith('ledger.sqlite3')])
    else:
        if (source / 'plans').is_dir(): shutil.copytree(source / 'plans', target / 'plans')
        blobs = target / 'snapshots' / 'blobs'
        blobs.mkdir(parents=True)
        for key in _referenced_blobs(source, project) if (source / 'ledger.sqlite3').is_file() else ():
            shutil.copy2(source / 'snapshots' / 'blobs' / key, blobs / key)
    if (source / 'ledger.sqlite3').is_file():
        src = sqlite3.connect((source / 'ledger.sqlite3').as_uri() + '?mode=ro', uri=True)
        dst = sqlite3.connect(target / 'ledger.sqlite3')
        try:
            src.backup(dst)
        finally:
            src.close(); dst.close()
    size = sum(p.stat().st_size for p in target.rglob('*') if p.is_file())
    return target, size


def _roots(state_root, project):
    """[(request_key, open engine root?)] of the plan roots of `project` in a state root, read by this runtime."""
    path = Path(state_root) / 'ledger.sqlite3'
    if not path.is_file(): return []
    from .report import _Reader
    key = os.path.normcase(str(Path(project).resolve()))
    reader = _Reader(state_root)
    found = []
    with reader.transaction() as conn:
        rows = conn.execute("SELECT project_id, project_path, request_key FROM tasks WHERE project_path=? AND (request_key LIKE 'plan:%' OR "
                            "request_key LIKE 'plan-ns:%') ORDER BY created_at", (key,)).fetchall() if conn else []
        for row in rows:
            reader.project_id, reader.project_path = row['project_id'], row['project_path']
            try:
                state = plans.derive(reader, conn, row['request_key'])
            except LedgerError:
                state = None
            engine_root = bool(state) and state['status'] == 'approved' and namespaces.has_capability(state, 'sequential-engine')
            found.append((row['request_key'], engine_root))
    return found


def _read_check(exe, project, copy, engine=False):
    """What a runtime proves about a copy of the data: its compat scan (of THIS copy), `plan show` of every root of the project, and with
    engine=True `engine state` + `engine ready` of every open engine root."""
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
    for root, engine_root in _roots(copy, project):
        verbs = [['plan', 'show', root]] + ([['engine', 'state', root], ['engine', 'ready', root]] if engine and engine_root else [])
        for verb in verbs:
            code, out, err = _onecrew(exe, ['--project', project, '--state-root', copy, *verb])
            reads.append({'root': root, 'command': ' '.join(verb[:2]), 'exit': code})
            if code != 0: problems.append(f'{" ".join(verb[:2])} {root} failed (exit {code}): {(err or out)[-200:]}')
    return {'scan': scan, 'reads': reads, 'problems': problems}


# ---- consumers and the safe point -------------------------------------------------------------------------------------------------

def _same(a, b):
    try:
        return os.path.normcase(str(Path(a).resolve())) == os.path.normcase(str(Path(b).resolve()))
    except OSError:
        return False


def _registry():
    """(projects, problem): the hook registry, strictly. An unreadable or malformed registry is a problem (S2-R07), never an empty set."""
    path = where.registry_file()
    if not path.exists(): return {}, None
    try:
        value = json.loads(path.read_text(encoding='utf-8-sig'))
        projects = value['projects']
        if not isinstance(projects, dict) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in projects.items()): raise ValueError
        return projects, None
    except (OSError, ValueError, KeyError, TypeError) as error:
        return {}, f'the hook registry {path} cannot be read ({type(error).__name__}): its projects are unknown'


def _programs(path, unknown):
    """The programs (resolved) OneCrew hook handlers of a settings file run; an unreadable file or an unresolvable handler goes to unknown."""
    if not path.exists(): return set()
    data, bad = installer.read_settings(path)
    if bad:
        unknown.append({'file': str(path), 'why': bad}); return set()
    found = set()
    for entries in installer.our_entries(data or {}).values():
        for entry in entries:
            for handler in entry.get('hooks', []):
                if not installer.is_ours(handler): continue
                program = installer.handler_words(handler)[0][0]
                resolved = program if Path(program).is_absolute() else shutil.which(program)
                if not resolved or not Path(resolved).exists():
                    unknown.append({'file': str(path), 'why': f'the handler program {program} cannot be resolved'}); continue
                found.add(str(resolved))
    return found


def consumers(ledger, exe, also=None, hints=()):
    """(found, unknown): every project whose OneCrew hook handlers run `exe` (the hook registry, the reporting project and the target's
    declared consumers), with its state root and the settings files that name it; and what could not be judged (an unreadable registry or
    settings file, a handler that cannot be resolved). `also` (the new runtime) keeps a project already switched in the set."""
    registry, problem = _registry()
    unknown = [{'file': str(where.registry_file()), 'why': problem}] if problem else []
    candidates = dict(registry)
    candidates.setdefault(os.path.normcase(str(ledger.project)), str(ledger.state_root))
    for hint in hints or ():
        candidates.setdefault(hint, str(where.configured_state_root(hint) or where.default_state_root()))
    found = []
    for key, state in sorted(candidates.items()):
        project = Path(key)
        if not project.is_dir(): continue
        files = []
        for name in ('settings.local.json', 'settings.json'):
            path = project / '.claude' / name
            if any(_same(p, exe) or (also is not None and _same(p, also)) for p in _programs(path, unknown)): files.append(str(path))
        if files: found.append({'project': os.path.normcase(str(project.resolve())), 'state_root': str(Path(state).resolve()), 'files': files})
    return found, unknown


def _activity(state_root):
    """Active attempts and executing/unknown actions of a state root, and a snapshot of attempts/actions to compare after a switch."""
    path = Path(state_root) / 'ledger.sqlite3'
    active, rows = [], {'attempts': [], 'actions': [], 'max_seq': 0}
    if not path.is_file(): return active, rows
    conn = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)
    conn.row_factory = sqlite3.Row
    try:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        rows['max_seq'] = conn.execute('SELECT COALESCE(MAX(seq),0) FROM events').fetchone()[0]
        if 'attempts' in tables:
            for row in conn.execute('SELECT id, status, identity, created_at FROM attempts'):
                rows['attempts'].append([row['id'], row['status'], row['created_at']])
                if row['status'] in ('reserved', 'running', 'unknown'):
                    try:
                        from ..process_core import probe
                        ident = json.loads(row['identity'] or '{}')
                        alive = probe(ident.get('supervisor') or ident.get('worker')) if isinstance(ident, dict) else 'unknown'
                    except Exception:
                        alive = 'unknown'
                    active.append(f'attempt {row["id"]} is {row["status"]} (process {alive}) in {state_root}: reconcile it first')
        if 'actions' in tables:
            for row in conn.execute('SELECT id, status FROM actions'):
                rows['actions'].append([row['id'], row['status']])
                if row['status'] in ('executing', 'unknown'): active.append(f'action {row["id"]} is {row["status"]} in {state_root}: reconcile it first')
    finally:
        conn.close()
    return active, rows


def safe_point(entries, fences, venv):
    """[] when the switch may happen now, else the problems: an attempt reserved|running|unknown or an action executing|unknown in any
    consuming state root, a process running from the venv being left (or processes that cannot be listed), data changed since the drill."""
    problems = []
    for state in sorted({c['state_root'] for c in entries}):
        problems += _activity(state)[0]
        if fences.get(state) != fence(state): problems.append(f'fence: the data of {state} changed since the drill; drill again')
    running = processes_under(venv)
    if running is None: problems.append('processes: unknown (they cannot be listed here); the switch is refused and nothing is stopped')
    else: problems += [f'process {p["pid"]} runs {p["image"]}' for p in running]
    return problems, ('unknown' if running is None else running)


def _events_after(state_root, seq):
    """The events of a state root after `seq`, the support anchor's own records left out."""
    path = Path(state_root) / 'ledger.sqlite3'
    if not path.is_file(): return 0
    conn = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)
    try:
        return conn.execute('SELECT COUNT(*) FROM events e JOIN tasks t ON t.id=e.task_id WHERE e.seq>? AND t.request_key!=?',
                            (seq, support.ANCHOR_KEY)).fetchone()[0]
    finally:
        conn.close()


def _post(states):
    """R3-03: {state root: (attempt/action rows, fence)} read right after the last hook write."""
    return {s: (_activity(s)[1], fence(s)) for s in states}


def _window(states, pre, post, fences, left, strict, ledger=None, token=None, venv=None):
    """S2-R09, Codex r1 F2, round 2 (R2-02) and round 3 (R3-03): (problems, fences right after the last write, counts). The window is
    from the snapshot right before the first hook write (`pre`) to the one right after the last (`post`): attempts or actions that appear
    or change between them started while hooks of both runtimes were live (a violation); rows before `pre` were judged by the safe
    point; rows after `post` belong to the runtime the hooks now run (counted: `events_after_repoint`, `attempts_after_repoint`). Also
    a violation: a process of the runtime being left still running, a claim no longer ours, and with `strict` (rollback) data changed
    between the drilled fence and `post` (the old runtime must run on the data it was drilled on)."""
    changed, now_fences, counts = [], {}, {'events_in_window': 0, 'events_after_repoint': 0, 'attempts_after_repoint': 0}
    for state in states:
        rows, now_fences[state] = post[state]
        old = pre.get(state) or {'attempts': [], 'actions': [], 'max_seq': 0}
        for table in ('attempts', 'actions'):
            fresh = [r for r in rows[table] if r not in old[table]]
            changed += [f'{table[:-1]} {r[0]} ({r[1]}) appeared or changed in {state} between the first and the last hook write' for r in fresh]
        counts['events_in_window'] += _events_after(state, old.get('max_seq', 0)) - _events_after(state, rows['max_seq'])
        counts['events_after_repoint'] += _events_after(state, rows['max_seq'])
        later = _activity(state)[1]
        counts['attempts_after_repoint'] += len([r for t in ('attempts', 'actions') for r in later[t] if r not in rows[t]])
        if strict and now_fences[state] != fences.get(state):
            changed.append(f'fence: the data of {state} changed between the drill and the last hook write; the old runtime did not drill it')
    running = processes_under(left)
    if running is None: changed.append('processes: unknown after the switch (they cannot be listed here)')
    else: changed += [f'process {p["pid"]} of the runtime being left ({p["image"]}) was running during the switch' for p in running]
    if ledger is not None and not still_ours(ledger, token, venv): changed.append('the claim of the target was lost during the switch')
    return changed, now_fences, counts


# ---- the exclusive claim (S2-R09) ---------------------------------------------------------------------------------------------------

def _claim_rows(conn):
    return [dict(json.loads(r['payload']), seq=r['seq']) for r in conn.execute(
        "SELECT e.seq, e.payload FROM events e JOIN tasks t ON t.id=e.task_id WHERE t.request_key=? AND e.kind='support.install' "
        "AND json_extract(e.payload,'$.phase') IN ('claim','renew','release') ORDER BY e.seq", (support.ANCHOR_KEY,)).fetchall()]


def _claims(conn):
    """The open claims (no release of the same token) of every support anchor of this ledger, with their latest lease (R2-06)."""
    open_ = {}
    for payload in _claim_rows(conn):
        if payload['phase'] == 'claim': open_[payload['token']] = payload
        elif payload['phase'] == 'renew' and payload.get('token') in open_: open_[payload['token']]['expires_at'] = payload['expires_at']
        else: open_.pop(payload.get('token'), None)
    return list(open_.values())


def _holder():
    """{pid, created, host} of this process (process_core.identity), None where it cannot be known."""
    try:
        from ..process_core import identity as process_identity
        return process_identity(os.getpid())
    except Exception:
        return None


def _holder_dead(claim):
    """True only when the claim names a holder process on THIS host and that exact process (pid and creation time) is not running."""
    holder = claim.get('holder')
    if not isinstance(holder, dict) or holder.get('host') != socket.gethostname() or not holder.get('pid') or holder.get('created') is None:
        return False
    try:
        from ..process_core import probe
        return probe(holder) == 'dead'
    except Exception:
        return False


def _expired(claim):
    import datetime as dt
    return dt.datetime.fromisoformat(claim['expires_at']) <= dt.datetime.now(dt.timezone.utc)


def _live(claim):
    if _expired(claim): return False
    if claim.get('pid') == os.getpid(): return claim['token'] in _ACTIVE
    return not _holder_dead(claim)                    # another process: held until it releases, it is gone, or the lease expires


def _lease():
    import datetime as dt
    return (dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=CLAIM_SECONDS)).isoformat()


def claim(ledger, venv, key, what, target):
    """Take the exclusive claim of target venv `venv` (one install, rollback or switch at a time, across the support anchors of this
    ledger). A live claim of another run refuses. A claim is taken over (and the takeover recorded in the new claim, `taken_over_from`)
    when its lease expired, when it is this process's own interrupted claim, or when its holder process, recorded with its host and
    creation time, is not running on this host; a claim of another host or without a holder is honoured until its lease expires."""
    token, taken = uuid.uuid4().hex, []
    with ledger.transaction(write=True) as conn:
        for held in _claims(conn):
            if not _same(held['venv'], venv): continue
            if _live(held):
                raise LedgerError(f'another {held["what"]} of target {held["target"]} is in progress (claim {held["token"][:8]}, until '
                                  f'{held["expires_at"]}); nothing was done')
            why = ('its lease expired' if _expired(held) else 'an interrupted claim of this process' if held.get('pid') == os.getpid() else 'its holder process is not running')
            taken.append({'token': held['token'], 'key': held.get('key'), 'what': held.get('what'), 'pid': held.get('pid'),
                          'holder': held.get('holder'), 'expires_at': held['expires_at'], 'why': why})
            _emit(ledger, 'support.install', {'phase': 'release', 'token': held['token'], 'taken_over_by': token}, conn=conn)
        _emit(ledger, 'support.install', {'phase': 'claim', 'token': token, 'key': key, 'venv': str(venv), 'target': target, 'what': what,
                                          'pid': os.getpid(), 'holder': _holder(), 'expires_at': _lease(),
                                          'taken_over_from': taken or None}, conn=conn)
    _ACTIVE.add(token)
    _TAKEN[token] = taken[-1] if taken else None
    return token


def renew(ledger, token, venv, before):
    """R2-06: renew the lease of this run's claim before the next phase, after checking it is still ours: not released or taken over, and no
    claim of the same venv taken after it. A lost claim refuses the run before anything else is switched."""
    with ledger.transaction(write=True) as conn:
        if not _ours(conn, token, venv):
            raise LedgerError(f'the claim of {venv} held by this run was lost before {before} (its lease ran out and another run claimed '
                              'the target): refused, nothing more is switched')
        _emit(ledger, 'support.install', {'phase': 'renew', 'token': token, 'before': before, 'expires_at': _lease()}, conn=conn)


def _ours(conn, token, venv):
    rows = _claim_rows(conn)
    mine = next((r for r in rows if r['phase'] == 'claim' and r['token'] == token), None)
    if mine is None or token not in _ACTIVE or any(r['phase'] == 'release' and r.get('token') == token for r in rows): return False
    return not any(r['phase'] == 'claim' and r['seq'] > mine['seq'] and _same(r['venv'], venv) for r in rows)


def still_ours(ledger, token, venv):
    with ledger.transaction() as conn:
        return _ours(conn, token, venv)


def release(ledger, token):
    _ACTIVE.discard(token)
    _TAKEN.pop(token, None)
    _emit(ledger, 'support.install', {'phase': 'release', 'token': token})


def _claimed(ledger, venv, key, what, target, work):
    """Run work(token) inside the claim; a fixture Crash leaves the claim as a killed process would (its holder is then dead)."""
    token = claim(ledger, venv, key, what, target)
    try:
        result = work(token)
    except Crash:
        _ACTIVE.discard(token)
        raise
    except BaseException:
        release(ledger, token)
        raise
    release(ledger, token)
    return result


class Refused(LedgerError):
    """A pre-switch check failed right before the first hook file is rewritten: nothing was switched."""

    def __init__(self, problems):
        super().__init__('; '.join(problems))
        self.problems = problems


def repoint(ledger, ident, key, entries, new_exe, old_exe, action, check=None):
    """Rewrite the OneCrew hook handlers of every consuming settings file from old_exe to new_exe (as `onecrew init` writes them): an intent
    record before each write, a switched_one record after it (S2-R08). `check()` runs right before the FIRST write and returns problems
    (the fence, the content, the claim): any problem raises Refused with nothing written. A file that now runs a THIRD program (neither
    old_exe nor new_exe) is never overwritten (R2-12)."""
    done, first = [], True
    for entry in entries:
        for name in entry['files']:
            path = Path(name)
            unknown = []
            programs = _programs(path, unknown)
            if unknown: raise LedgerError(f'{name} became unreadable during the switch: {unknown[0]["why"]}')
            third = sorted(p for p in programs if not _same(p, old_exe) and not _same(p, new_exe))
            if third: raise LedgerError(f'{name} now runs {third[0]}, neither {old_exe} nor {new_exe}: it is not overwritten; nothing more '
                                        'is switched (the files already switched are in the record)')
            if not any(_same(p, old_exe) for p in programs) and any(_same(p, new_exe) for p in programs):
                done.append({'file': name, 'changed': False}); continue
            if first and check is not None:
                problems = check()
                if problems: raise Refused(problems)
            first = False
            data, bad = installer.read_settings(path)
            merged = installer.merge_settings(data, hook_cli.portable_settings(Path(new_exe).resolve(), entry['state_root']))
            before = path.read_bytes()
            _emit(ledger, 'support.install', {'phase': 'intent', 'feedback': ident, 'key': key, 'action': action, 'file': name,
                                              'from': str(old_exe), 'to': str(new_exe), 'before_sha256': hashlib.sha256(before).hexdigest()})
            installer.write_text(path, installer.dump(merged))
            item = {'file': name, 'changed': True, 'before_sha256': hashlib.sha256(before).hexdigest(),
                    'after_sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'to': str(new_exe)}
            _emit(ledger, 'support.install', dict(item, phase='switched_one', feedback=ident, key=key, action=action))
            done.append(item)
            _crash('mid_switch')
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
    """The base python new venvs of `target` are made with and judged against: the target's declared --python, else the `home` of the
    target venv's pyvenv.cfg (read as site.py reads it). R3-06: no silent fallback to the python running OneCrew; a pyvenv.cfg that cannot
    be read, has no home, or names a folder without a python refuses (declare the target again with --python)."""
    if target.get('python'): return target['python']
    cfg = _pyvenv(target['venv'])
    if not cfg or not cfg.get('home'):
        raise LedgerError(f'The target venv {target["venv"]} has no readable pyvenv.cfg home: its base python is unknown. The owner declares '
                          'the target again with support target add --python <base python> --replace.')
    candidate = Path(cfg['home']) / ('python.exe' if os.name == 'nt' else 'python3')
    if not candidate.is_file():
        raise LedgerError(f'The pyvenv.cfg home of {target["venv"]} ({cfg["home"]}) holds no python: declare the target with --python.')
    return str(candidate)


def _home(target):
    return Path(_base_python(target)).parent


def new_venv_path(target, art, state_root):
    """R3-04: the venv one ledger makes for one wheel at one target, `<venv>-<version>-<wheel sha8>-<state root8>`: two ledgers (two
    projects) installing the same wheel to the same target get two venvs and two baselines, each in its own ledger."""
    root = hashlib.sha256(os.path.normcase(str(Path(state_root).resolve())).encode('utf-8')).hexdigest()[:8]
    return Path(f'{target["venv"]}-{art["version"]}-{art["wheel_sha256"][:8]}-{root}')


def _authority(ledger, shown, target_id, what='install'):
    """(result, fix, state) of authority.enforce on the fix plan's root for support_install:<target> (install and rollback alike)."""
    fix, state, link = fix_plan(ledger, shown)
    approved = state.get('approved') or {}
    if state['status'] != 'approved' or not approved:
        return {'in_authority': False, 'class': 'U2', 'reason': f'the fix plan {state["selector"]} is {state["status"]}, not approved and open'}, fix, state
    contract, sha = plans.load(fix, state, approved['revision'])
    with fix.transaction() as conn:
        try:
            ctx = internal_plan.ceilings(fix, conn, state)
        except LedgerError as error:
            return {'in_authority': False, 'class': 'U2', 'reason': f'the fix plan has no usable root budget: {error}'}, fix, state
    action = {'kind': 'support_install', 'target': target_id, 'cost': {'seconds': INSTALL_SECONDS}, 'operation': what}
    result, _ = authority.enforce(fix, state['task_id'], contract, action, name=state['selector'], revision_sha=sha, ctx=ctx,
                                  component='onecrew.support')
    return result, fix, state


def verify_installed(venv, art, found=None, baseline=None, home=None, run_programs=True):
    """(problems, identity): `venv` is the bound wheel only when (S2-R02, Codex r1 F1, round 2) every static check of identity passes (the
    CONTENT of every wheel file against the verified wheel rows, never the venv's own RECORD; links; extra files; .pth start-up code;
    pyvenv.cfg; every other file of the venv against the creation `baseline`, or pyvenv.cfg `home` when OneCrew is making it) and then,
    only then, its interpreter finds every bytecode cache equal to the compile of its source and its `onecrew --version` runs, names the
    version and loads onecrew (and its console-script module) from these files, nothing from outside the venv but the standard library."""
    found = found or identity(venv, art, baseline, home, run_programs)
    problems = list(found.get('static') or [])
    if problems or not found.get('ran'): return problems, dict(found, record_sha256=None)
    if found.get('error'): problems.append(found['error'])
    wanted = {p: h for p, h in art['rows'] if not p.endswith('.dist-info/RECORD')}
    caches = sorted(p for p, v in (found.get('caches') or {}).items() if v not in ('same', 'other interpreter'))
    if caches: problems.append(f'bytecode caches that are not the compile of their source (Python loads them instead): {", ".join(caches[:5])}')
    if found.get('exit') != 0: problems.append(f'its onecrew executable did not run (exit {found.get("exit")})')
    if art['version'] not in (found.get('version_line') or ''): problems.append(f'onecrew --version says {found.get("version_line")!r}')
    loaded = {_source_of(p) for p in found.get('loaded') or []}
    foreign = sorted(p for p in loaded if p not in wanted)
    if foreign: problems.append(f'its onecrew executable loaded files the bound wheel does not hold: {", ".join(foreign[:5])}')
    if found.get('outside'):
        problems.append(f'its onecrew executable loaded code from outside the venv and the standard library: {", ".join(found["outside"][:3])}')
    required = {'onecrew/__init__.py'} | {m.replace('.', '/') + '.py' for m in found.get('entry_modules') or []}
    absent = sorted(required - loaded)
    if absent: problems.append(f'its onecrew executable did not load {", ".join(absent)} from this venv')
    return problems, dict(found, record_sha256=None if problems else record_digest((found.get('files') or {}).items()))


def _finals(ledger, ident=None, key=None):
    return [r for r in _records(ledger, 'support.install', ident) if r.get('result') in FINALS and (key is None or r.get('key') == key)]


def _intents(ledger, key):
    """The intents of `key` not followed by a final record of that key: a switch (or a rollback) that was interrupted."""
    rows = [r for r in _records(ledger, 'support.install') if r.get('key') == key]
    last_final = max((r['seq'] for r in rows if r.get('result') in FINALS), default=0)
    return [r for r in rows if r.get('phase') in ('intent', 'switched_one') and r['seq'] > last_final]


def _baseline_of(ledger, venv, art):
    """The creation baseline (R2-01) OneCrew recorded for `venv` holding `art`'s wheel, its tree read back from the evidence store and
    checked against the recorded digest; None when there is none (a venv OneCrew did not make, or did not finish checking)."""
    rows = [r for r in _records(ledger, 'support.install') if r.get('phase') == 'baseline' and r.get('wheel_sha256') == art['wheel_sha256']
            and _same(r.get('venv'), venv)]
    if not rows: return None
    try:
        tree = json.loads(Snapshots(ledger.state_root).read_evidence(rows[-1]['tree_blob']))
    except (LedgerError, OSError, ValueError, KeyError):
        return None
    return dict(rows[-1], tree=tree) if content_hash(tree) == rows[-1]['digest'] else None


def _record_baseline(ledger, key, venv, art, base):
    made = venv_baseline(venv, art)
    record = {'phase': 'baseline', 'key': key, 'venv': str(venv), 'wheel_sha256': art['wheel_sha256'], 'digest': made['digest'],
              'files': made['files'], 'pyvenv': made['pyvenv'], 'base_python': str(base),
              'tree_blob': Snapshots(ledger.state_root).evidence(canonical(made['tree']).encode('utf-8'))}
    _emit(ledger, 'support.install', record)
    return dict(record, tree=made['tree'])


def _judge(ledger, venv, art, target):
    """The problems of a venv this ledger made, against its creation baseline and the target's base python (R3-06); none recorded: not
    judged the bound wheel, and nothing of it runs."""
    known = _baseline_of(ledger, venv, art)
    if known is None: return [f'OneCrew has no creation baseline for {venv} in this ledger'], {}
    return verify_installed(venv, art, baseline=known, home=_home(target))


def _judge_switched(ledger, final, art):
    return _judge(ledger, final['new_venv'], art, targets(ledger)[final['target']])[0]


def install(ledger, ident, target_id, keep=False):
    """See the module docstring. Returns the install record (result switched | blocked_by_authority | refused_by_drill | refused_unsafe |
    switch_window_violation)."""
    shown, feedback = _feedback(ledger, ident)
    arts = _records(ledger, 'support.artifact', ident)
    if not arts: raise LedgerError('No verified artifact for this feedback: run support artifact FB --wheel W --manifest M first.')
    art = arts[-1]
    target = targets(ledger).get(target_id)
    if target is None: raise LedgerError(f'No install target {target_id}: the owner declares it with support target add.')
    key = _key(ident, art, target_id)
    finals = _finals(ledger, ident, key)
    if finals and finals[-1]['result'] == 'switched' and finals[-1].get('action') == 'install' and runtime_now(finals[-1])['current']:
        problems = _judge_switched(ledger, finals[-1], art)
        if problems: raise LedgerError(f'The switched venv {finals[-1]["new_venv"]} is no longer the bound wheel ({"; ".join(problems)}): '
                                       'nothing was changed; the owner rolls back (support rollback).')
        return dict(finals[-1], already=True)
    # R3-01: a violation (install or rollback side) is never a dead end: installing again drills the CURRENT data with the new runtime
    # and binds the switch to it (files that already run the new exe are left as they are)
    return _claimed(ledger, target['venv'], key, 'install', target_id,
                    lambda token: _install(ledger, ident, target, target_id, art, key, keep, token))


def _install(ledger, ident, target, target_id, art, key, keep, token):
    shown, feedback = _feedback(ledger, ident)
    old_venv, old_exe = Path(target['venv']), Path(target['exe'])
    interrupted = _intents(ledger, key)
    result, fix, state = _authority(ledger, shown, target_id)
    allowed = bool(result.get('in_authority'))
    if not allowed and interrupted:                   # S2-R08: complete the switch an earlier decision allowed; the record says so
        earlier = [r for r in _records(ledger, 'support.install_prepared', ident) if r.get('key') == key and (r.get('authority') or {}).get('in_authority')]
        if earlier:
            allowed, result = True, dict(earlier[-1]['authority'], reason='completing an interrupted switch under the decision of '
                                                                           f'event {earlier[-1]["seq"]}; now: {result.get("reason")}')
    work = ledger.state_root / WORK / key
    venv = new_venv_path(target, art, ledger.state_root) if allowed else work / 'trial-venv'
    marker = work / ('venv-' + content_hash(str(venv))[:12] + '.json')
    wheel = work / 'wheel' / art['wheel_name']
    base = _base_python(target)
    if venv.exists():                                 # R2-01, R3-02: only a venv this ledger made AND recorded is ever reused
        known = _baseline_of(ledger, venv, art)
        if known is None:
            static, _ = verify_installed(venv, art, run_programs=False)
            raise LedgerError(f'{venv} exists and OneCrew has no creation baseline for it in this ledger (another ledger or someone else made '
                              f'it, or an install stopped before checking it){": " + "; ".join(static) if static else ""}. Refused; nothing '
                              'was deleted, switched or run from it. If this ledger began it (support-work marker), the owner removes it with '
                              f'support cleanup --venv "{venv}" and installs again.')
        problems, found = verify_installed(venv, art, baseline=known, home=Path(base).parent)
        if problems: raise LedgerError(f'{venv} exists and is not the bound wheel ({"; ".join(problems)}): refused, nothing deleted or switched.')
    else:
        work.mkdir(parents=True, exist_ok=True)
        marker.write_text(json.dumps({'venv': str(venv), 'key': key, 'at': utcnow()}), encoding='utf-8')
        make_venv(base, venv)
        _crash('after_venv')
        pip_install(venv_python(venv), _wheel_file(ledger, art, wheel))
        problems, found = verify_installed(venv, art, home=Path(base).parent)
        if problems: raise LedgerError(f'The new venv {venv} is not the bound wheel ({"; ".join(problems)}): refused, nothing switched.')
        known = _record_baseline(ledger, key, venv, art, base)
    renew(ledger, token, target['venv'], 'the drill')
    entries, unknown = consumers(ledger, old_exe, venv_exe(venv), target.get('consumers'))
    fences, datas, drill, moved = {}, {}, [], []
    for index, entry in enumerate(entries):
        copy, size, shifted = _drill_copy(entry['state_root'], work / 'drill' / str(index) / 'state', entry['project'], fences, datas)
        moved += shifted
        checked = _read_check(venv_exe(venv), entry['project'], copy, engine=True)
        drill.append(dict(checked, state_root=entry['state_root'], project=entry['project'], copy=str(copy), copy_bytes=size,
                          copy_kept=bool(keep or checked['problems'])))
        if not keep and not checked['problems']: shutil.rmtree(copy.parent, ignore_errors=True)
    renew(ledger, token, target['venv'], 'the safe point')
    problems = [p for d in drill for p in d['problems']]
    blocked = ('authority' if not allowed else 'drill' if problems else 'consumers' if unknown or not entries else None)
    old_tree = venv_tree(old_venv)
    prepared = {'key': key, 'feedback': ident, 'target': target_id, 'wheel_sha256': art['wheel_sha256'], 'version': art['version'],
                'venv': str(venv), 'trial': not allowed, 'identity': {k: found.get(k) for k in ('version', 'location', 'version_line', 'record_sha256')},
                'baseline': {'digest': known['digest'], 'files': known['files'], 'event': known.get('seq')},
                'old_runtime': {'venv': str(old_venv), 'digest': content_hash(old_tree), 'files': len(old_tree),
                                'note': 'every file of the old venv but bytecode caches and site-packages/.onecrew (R2-08)'},
                'consumers': entries, 'consumers_unknown': unknown, 'not_enumerated': NOT_ENUMERATED, 'fences': fences, 'drill': drill,
                'authority': {k: result.get(k) for k in ('in_authority', 'class', 'reason')}, 'blocked_by': blocked,
                'desktop_outbox': {'old': str(old_venv / 'Lib' / 'site-packages' / '.onecrew' / 'desktop'), 'carried': False,
                                   'note': 'set ONECREW_DESKTOP_HOME to keep one outbox across runtimes; pending windows of the old outbox stay there'}}
    _emit(ledger, 'support.install_prepared', prepared)
    _crash('after_prepared')
    outcome = {'key': key, 'feedback': ident, 'action': 'install', 'target': target_id, 'version': art['version'], 'old_venv': str(old_venv),
               'new_venv': str(venv), 'identity': prepared['identity'], 'consumers': entries, 'not_enumerated': NOT_ENUMERATED,
               **({'claim_taken_over_from': _TAKEN[token]} if _TAKEN.get(token) else {})}
    if blocked == 'authority':
        return dict(outcome, result='blocked_by_authority', reason=result.get('reason'), authority=prepared['authority'],
                    note='Prepared in a trial venv (not the target); nothing switched. This is not a PASS.')
    if blocked == 'drill':
        return _emit(ledger, 'support.install', dict(outcome, result='refused_by_drill', problems=problems, drill=drill))
    if blocked == 'consumers':
        why = [f'consumer unknown: {u["file"]}: {u["why"]}' for u in unknown] or ['no project uses this target: nothing to switch']
        return _emit(ledger, 'support.install', dict(outcome, result='refused_unsafe', problems=why))
    unsafe, running = safe_point(entries, fences, old_venv)
    unsafe = moved + unsafe
    if unsafe:
        return _emit(ledger, 'support.install', dict(outcome, result='refused_unsafe', problems=unsafe, processes=running))
    states = sorted({e['state_root'] for e in entries})

    before = {s: _activity(s)[1] for s in states}
    pre = {'rows': before}

    def check():                                      # right before the first hook file is rewritten (R2-02, R2-06, R2-13)
        found = [f'fence: the data of {s} changed since the drill; drill again' for s in states if fences.get(s) != fence(s)]
        found += [f'the new runtime: {p}' for p in verify_installed(venv, art, baseline=known, home=Path(base).parent)[0]]
        try:
            renew(ledger, token, target['venv'], 'the repoint')
        except LedgerError as error:
            found.append(str(error))
        if not found: pre['rows'] = {s: _activity(s)[1] for s in states}       # R3-03: the snapshot right before the first write
        return found
    try:
        files = repoint(ledger, ident, key, entries, venv_exe(venv), old_exe, 'install', check=check)
    except Refused as refused:
        return _emit(ledger, 'support.install', dict(outcome, result='refused_unsafe', problems=refused.problems, processes=running))
    post = _post(states)                              # R3-03: the snapshot right after the last write
    changed, after, counts = _window(states, pre['rows'], post, fences, old_venv, False, ledger, token, target['venv'])
    bound = {'drilled': fences, 'at_switch': after}
    max_seq = {s: r['max_seq'] for s, r in pre['rows'].items()}
    if changed:
        return _emit(ledger, 'support.install', dict(outcome, result='switch_window_violation', problems=changed, files=files, fences=bound,
                     max_seq=max_seq, **counts,
                     note='work started, or a process of the old runtime ran, between the first and the last hook write: nothing is '
                          'stopped; support install (it drills the current data again) or support rollback'))
    return _emit(ledger, 'support.install', dict(outcome, result='switched', files=files, processes=running, at=utcnow(), fences=bound,
                                                 max_seq=max_seq, **counts))


def runtime_now(final):
    """S2-R04: does every settings file the switch wrote still run the switched runtime (`new_venv` for an install)? Read now."""
    exe = venv_exe(final['new_venv'] if final.get('action') == 'install' else final['old_venv'])
    files, current = [], True
    for item in final.get('files') or []:
        unknown = []
        programs = _programs(Path(item['file']), unknown)
        here = bool(programs) and all(_same(p, exe) for p in programs) and not unknown
        files.append({'file': item['file'], 'runs': sorted(programs), 'current': here})
        current = current and here
    return {'current': current and bool(files), 'runtime': str(exe), 'files': files}


def _switched(ledger, ident):
    """The latest final install/rollback of this feedback when it is a switched install, else None."""
    rows = [r for r in _finals(ledger, ident) if r.get('result') in ('switched', 'rolled_back')]
    return rows[-1] if rows and rows[-1]['result'] == 'switched' and rows[-1].get('action') == 'install' else None


def rollback(ledger, ident, keep=False):
    """Repoint the hooks back to the old venv. The owner's verb, under the same support_install:<target> grant. Only when the old venv is
    still the runtime recorded at the install (R2-08) and the OLD runtime, on a copy of the current data, reads every root (compat scan
    without read blocks, plan show), derives the state of every open engine root (engine state + engine ready), and knows every event kind
    written since the switch. A switched install, a partially switched one and an install that ended in switch_window_violation (R2-02:
    the hooks may run the new runtime on data written in the window) are rolled back alike. What is proven is recorded; continuation of the
    old work by the old runtime is not proven (S2-R03, S2-R06)."""
    _refuse_ai('support rollback')
    ownership.refuse_in_ai_session('support rollback')
    # R3-01: what is current comes from the last final record AND the install it belongs to: after an install violation, or a rollback
    # that itself ended in a violation, the rollback runs again (it drills the current data); only a completed rollback ends it
    ends = [r for r in _finals(ledger, ident) if r.get('result') in ('switched', 'rolled_back', 'switch_window_violation')]
    current = None
    if ends and ends[-1]['result'] != 'rolled_back':
        installs = [r for r in ends if r.get('action') == 'install' and r.get('key') == ends[-1].get('key')]
        if installs: current = dict(installs[-1], from_violation=ends[-1]['result'] == 'switch_window_violation',
                                    rerun_of=ends[-1]['seq'] if ends[-1].get('action') == 'rollback' else None)
    if current is None:
        intents = [r for r in _records(ledger, 'support.install', ident) if r.get('phase') == 'switched_one' and r.get('action') == 'install']
        partial = intents and _intents(ledger, intents[-1]['key']) and intents[-1]
        if not partial: raise LedgerError('Nothing to roll back: no switched (or partially switched) install for this feedback.')
        prepared = [r for r in _records(ledger, 'support.install_prepared', ident) if r.get('key') == partial['key']][-1]
        current = {'key': partial['key'], 'target': prepared['target'], 'old_venv': str(Path(targets(ledger)[prepared['target']]['venv'])),
                   'new_venv': prepared['venv'], 'consumers': prepared['consumers'], 'max_seq': {}, 'partial': True}
    target = targets(ledger).get(current['target'])
    return _claimed(ledger, target['venv'], current['key'], 'rollback', current['target'],
                    lambda token: _rollback(ledger, ident, current, keep, token, target['venv']))


def _old_runtime(ledger, ident, current):
    """R2-08: [] when the old venv is still the runtime recorded at the install (every file but caches and its data folder), else why not."""
    prepared = [r for r in _records(ledger, 'support.install_prepared', ident) if r.get('key') == current['key'] and r.get('old_runtime')]
    if not prepared: return ['the old runtime was not recorded at the install: rollback refused']
    recorded = prepared[-1]['old_runtime']
    if content_hash(venv_tree(current['old_venv'])) != recorded['digest']:
        return [f'the old runtime {current["old_venv"]} changed since the install (its files differ from the record of event '
                f'{prepared[-1]["seq"]}): rollback refused, nothing switched']
    return []


def _rollback(ledger, ident, current, keep, token, claimed):
    shown, feedback = _feedback(ledger, ident)
    base = {'key': current['key'], 'feedback': ident, 'action': 'rollback', 'target': current['target'], 'old_venv': current['old_venv'],
            'new_venv': current['new_venv'], 'consumers': current['consumers'], 'partial': bool(current.get('partial')),
            'from_violation': bool(current.get('from_violation')), **({'claim_taken_over_from': _TAKEN[token]} if _TAKEN.get(token) else {})}
    result, fix, state = _authority(ledger, shown, current['target'], 'rollback')
    if not result.get('in_authority'):
        return _emit(ledger, 'support.install', dict(base, result='blocked_by_authority', reason=result.get('reason')))
    changed_old = _old_runtime(ledger, ident, current)
    if changed_old:                                   # checked before any program of the old venv runs
        return _emit(ledger, 'support.install', dict(base, result='refused', problems=changed_old, reason=changed_old[0]))
    work = ledger.state_root / WORK / current['key']
    old_venv = Path(current['old_venv'])
    old_exe = venv_exe(old_venv)
    checks, problems, fences, datas, moved = [], [], {}, {}, []
    for index, entry in enumerate(current['consumers']):
        # Codex r1 F2: the fence is taken BEFORE the copy and the copy must hold exactly the fenced data; the kinds written since the switch
        # are read from that copy, so the old runtime judges the very data the switch decision is bound to
        copy, size, shifted = _drill_copy(entry['state_root'], work / 'rollback' / str(index) / 'state', entry['project'], fences, datas)
        moved += shifted
        checked = _read_check(old_exe, entry['project'], copy, engine=True)
        since = (current.get('max_seq') or {}).get(entry['state_root'], 0)
        conn = sqlite3.connect((Path(copy) / 'ledger.sqlite3').as_uri() + '?mode=ro', uri=True)
        try:
            kinds = sorted({r[0] for r in conn.execute("SELECT DISTINCT e.kind FROM events e JOIN tasks t ON t.id=e.task_id WHERE e.seq>? AND "
                                                       "t.request_key!=?", (since, support.ANCHOR_KEY))})
        finally:
            conn.close()
        classes = event_classes(old_venv, kinds) if kinds else {}
        if classes is None: checked['problems'].append('the old runtime cannot classify the event kinds written since the switch')
        else: checked['problems'] += [f'the old runtime does not know the event kind {k} written since the switch' for k, c in classes.items() if c is None]
        checked.update(state_root=entry['state_root'], copy_bytes=size, kinds_since_switch=kinds)
        checks.append(checked)
        problems += checked['problems']
        if not keep and not checked['problems']: shutil.rmtree(copy.parent, ignore_errors=True)
    base['reader_pair'] = checks
    _crash('rollback_after_drill')
    renew(ledger, token, claimed, 'the safe point')
    if problems:
        return _emit(ledger, 'support.install', dict(base, result='refused', problems=problems,
                     reason='the old reader cannot read or derive the current data: rollback refused, the new runtime and the ledger stay as they are'))
    unsafe, running = safe_point(current['consumers'], fences, current['new_venv'])
    unsafe = moved + unsafe
    if unsafe:
        return _emit(ledger, 'support.install', dict(base, result='refused', problems=unsafe, processes=running,
                     reason='not a safe point, or the data changed since the drill: rollback refused, the new runtime and the ledger stay as they are'))
    states = sorted({e['state_root'] for e in current['consumers']})

    pre = {'rows': {s: _activity(s)[1] for s in states}}

    def check():                                      # right before the first hook file is rewritten
        found = [f'fence: the data of {s} changed since the drill; drill again' for s in states if fences.get(s) != fence(s)]
        found += _old_runtime(ledger, ident, current)
        try:
            renew(ledger, token, claimed, 'the repoint')
        except LedgerError as error:
            found.append(str(error))
        if not found: pre['rows'] = {s: _activity(s)[1] for s in states}
        return found
    try:
        files = repoint(ledger, ident, current['key'], current['consumers'], old_exe, venv_exe(current['new_venv']), 'rollback', check=check)
    except Refused as refused:
        return _emit(ledger, 'support.install', dict(base, result='refused', problems=refused.problems, processes=running,
                     reason='the data, the old runtime or the claim changed right before the repoint: rollback refused, nothing switched'))
    post = _post(states)
    _crash('rollback_after_repoint')
    changed, after, counts = _window(states, pre['rows'], post, fences, current['new_venv'], True, ledger, token, claimed)
    bound = {'drilled': fences, 'at_switch': after}
    if changed:
        return _emit(ledger, 'support.install', dict(base, result='switch_window_violation', problems=changed, files=files, fences=bound, **counts,
                     note='the data changed between the drill and the last hook write, or work started in between: the hooks run the old '
                          'runtime on data it did not drill. Nothing is stopped; support rollback again drills the current data and binds to '
                          'it, or support install again switches to the new runtime.'))
    return _emit(ledger, 'support.install', dict(base, result='rolled_back', files=files, processes=running, proven=PROVEN, fences=bound, **counts))


# ---- the status projection (support._status reads it) ------------------------------------------------------------------------------

def projection(ledger, ident):
    """{installed, rolled_back, partially_switched, verified, still_blocked_reason}: projected from the records AND the hook handlers now."""
    finals = [r for r in _finals(ledger, ident) if r.get('result') in ('switched', 'rolled_back', 'switch_window_violation')]
    last = finals[-1] if finals else None
    out = {'installed': False, 'installed_evidence': [], 'rolled_back': False, 'violation': None, 'partially_switched': [], 'current_runtime': None,
           'restart_sessions': None}
    if last and last['result'] == 'switched':
        now = runtime_now(last)
        out.update(installed=now['current'], current_runtime=now, installed_evidence=[f'event:{last["seq"]} switched to {last["new_venv"]}'])
    elif last and last['result'] == 'rolled_back':
        out.update(rolled_back=True, installed_evidence=[f'event:{last["seq"]} rolled back to {last["old_venv"]}'])
    elif last:                                        # R2-02, R3-01: the violation with its real reason, and what the hooks run NOW
        new_now, old_now = runtime_now(dict(last, action='install')), runtime_now(dict(last, action='rollback'))
        runs = 'the new runtime' if new_now['current'] else 'the old runtime' if old_now['current'] else 'a mix of runtimes'
        out['violation'] = (f'event:{last["seq"]} switch_window_violation of the {last.get("action")}: '
                            f'{"; ".join((last.get("problems") or ["unknown"])[:2])}; the hooks run {runs} now; '
                            'support install or support rollback drills the current data again')
        out.update(installed=new_now['current'], current_runtime=new_now if new_now['current'] else old_now,
                   installed_evidence=[f'event:{last["seq"]} switch_window_violation; the hooks run {last["new_venv"]}'] if new_now['current'] else [])
    if last:
        out['restart_sessions'] = ('Claude Code sessions opened before this switch may still run the previous onecrew.exe: restart them '
                                   f'(events after the repoint: {last.get("events_after_repoint", "unknown")})')
    keys = {r.get('key') for r in _records(ledger, 'support.install', ident) if r.get('phase') == 'switched_one'}
    for key in keys:
        if _intents(ledger, key): out['partially_switched'] += [r['file'] for r in _intents(ledger, key) if r.get('phase') == 'switched_one']
    rechecks = _records(ledger, 'support.recheck', ident)
    done = [r for r in rechecks if r.get('result')]
    passed = done[-1] if done and done[-1]['environment'] == 'target' and done[-1]['result'] == 'pass' and done[-1].get('receipt') else None
    current = (bool(passed) and out['installed'] and not out['violation'] and passed['seq'] > (last or {}).get('seq', 0)
               and (passed.get('at_runtime') or {}).get('venv') == (last or {}).get('new_venv'))     # a pass after the switch it judges
    out['verified'] = {'value': current, 'recheck': passed, 'current': current,
                       'at_runtime': (passed or {}).get('at_runtime'), 'last': done[-1] if done else None}
    return out


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


def recheck(ledger, ident, keep=False):
    """Re-run the ORIGINAL node's checks through the engine with the new runtime: at the target when the switch is CURRENT (the hooks run
    it now), else on a named copy of the target's state root. A real node.verification; its receipt is the evidence. An intent is recorded
    first, so a crash after the engine ran is recovered by adopting that verification, never by running it twice."""
    shown, feedback = _feedback(ledger, ident)
    refs = feedback.get('refs') or {}
    if not (refs.get('plan') and refs.get('node') and refs.get('root_task')):
        raise LedgerError('Nothing to recheck: the report names no node of a root.')
    prepared = [r for r in _records(ledger, 'support.install_prepared', ident) if (r.get('identity') or {}).get('version') == r.get('version')]
    if not prepared: raise LedgerError('No runtime is prepared for this feedback: run support install first.')
    view = projection(ledger, ident)
    if view['violation']: raise LedgerError('A switch window violation is recorded: the recheck is refused until support install or '
                                            'support rollback has drilled the current data and bound the switch to it.')
    switched = _switched(ledger, ident) if view['installed'] else None
    rows = _records(ledger, 'support.recheck', ident)
    pending = rows[-1] if rows and not rows[-1].get('result') else None
    chosen = ([r for r in prepared if r.get('key') == switched['key']] or prepared)[-1] if switched else prepared[-1]
    arts = [a for a in _records(ledger, 'support.artifact', ident) if a['wheel_sha256'] == chosen['wheel_sha256']]
    if not arts: raise LedgerError('No verified artifact for the prepared runtime of this feedback.')
    judged = Path(switched['new_venv']) if switched else Path(chosen['venv'])
    checked, found = _judge(ledger, judged, arts[-1], targets(ledger)[chosen['target']])
    if checked:                                      # Codex r1 F1: the recheck runs only the bound wheel, judged on its content now
        raise LedgerError(f'The runtime {chosen["venv"]} is not the bound wheel now ({"; ".join(checked)}): the recheck is refused.')
    if switched:
        environment, state, venv = 'target', ledger.state_root, Path(switched['new_venv'])
        size = 0
    else:
        latest = prepared[-1]
        environment, venv = 'copy', Path(latest['venv'])
        state = Path(pending['state_root']) if pending and pending['environment'] == 'copy' and Path(pending['state_root']).exists() else None
        if state is None:
            state, size = copy_state(ledger.state_root, ledger.state_root / WORK / latest['key'] / f'recheck-{len(rows) + 1}' / 'state', full=True)
        else:
            size = 0
    if pending and pending['environment'] == environment:
        before = pending['before_seq']
    else:
        before, _ = _latest_verification(state, refs['root_task'], refs['node'])
        _emit(ledger, 'support.recheck', {'feedback': ident, 'phase': 'intent', 'environment': environment, 'state_root': str(state),
                                          'venv': str(venv), 'before_seq': before})
    seq, verification = _latest_verification(state, refs['root_task'], refs['node'])
    code, out, err = (None, '', 'adopted the verification of the interrupted recheck') if seq > before else \
        _onecrew(venv_exe(venv), ['--project', str(ledger.project), '--state-root', str(state), 'engine', 'verify', refs['plan'], refs['node']])
    _crash('recheck_after_verify')
    seq, verification = _latest_verification(state, refs['root_task'], refs['node'])
    if verification is None or seq <= before:
        result, receipt = 'inconclusive', None
    else:
        result, receipt = verification['result'], verification['receipt']
        if environment == 'copy':
            Snapshots(ledger.state_root).blob(Snapshots(state).read_blob(receipt))      # the receipt is kept in the target's store too
    at_runtime = {'venv': str(venv), 'version': found.get('version'), 'record_sha256': found.get('record_sha256'),
                  'content_checked': 'every file of the bound wheel hashed, executable origins checked, before the run'}
    payload = {'feedback': ident, 'phase': 'result', 'refs': refs, 'environment': environment, 'state_root': str(state), 'venv': str(venv),
               'version': at_runtime['version'], 'at_runtime': at_runtime, 'exit': code, 'receipt': receipt, 'result': result,
               'copy_bytes': size, 'output_tail': (err or out)[-600:] if result == 'inconclusive' else None,
               'recurrence_of': feedback.get('recurrence_of', [])}
    _emit(ledger, 'support.recheck', payload)
    if environment == 'copy' and not keep and result != 'inconclusive': shutil.rmtree(Path(state).parent, ignore_errors=True)
    return payload


def _passed_current(ledger, ident):
    view = projection(ledger, ident)
    return view['verified']['recheck'] if view['verified']['value'] else None


def resume(ledger, ident):
    """Continue the old work only through the engine's own guards, and only while the runtime the recheck passed on is the one the hooks run
    now (S2-R04); never extend or reopen the customer root, never reset its budget."""
    shown, feedback = _feedback(ledger, ident)
    passed = _passed_current(ledger, ident)
    if passed is None: raise LedgerError('Resume needs a passing recheck at the target with the runtime the hooks run now (support recheck).')
    refs = feedback['refs']
    with ledger.transaction() as conn:
        state = plans.derive(ledger, conn, refs['plan'])
    if state is None or state['status'] != 'approved':
        raise LedgerError(f'The root {refs.get("plan")} is {state and state["status"]}: an ended or stopped root is never extended or reopened.')
    from . import engine
    view = engine.state(ledger, refs['plan'])
    record = view['nodes'].get(refs['node']) or {}
    base = {'feedback': ident, 'root': refs['root_task'], 'plan': refs['plan'], 'node': refs['node'], 'recheck_receipt': passed['receipt'],
            'at_runtime': passed.get('at_runtime'), 'budget_reset': False, 'grants_authority': False}
    if record.get('phase') != 'held':
        _crash('resume_before_record')
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
    _crash('resume_before_record')
    return _emit(ledger, 'support.resumed', dict(base, mode='resume_held', request=request['id'], generations_after=done['generations_after']))


def learn(ledger, ident, text):
    """A lesson on the FIX plan's root, only after a passing recheck at the target with the runtime the hooks run now, citing that receipt;
    cause not established; one lesson per feedback."""
    shown, feedback = _feedback(ledger, ident)
    passed = _passed_current(ledger, ident)
    if passed is None: raise LedgerError('A lesson needs a passing recheck at the target with the runtime the hooks run now (support recheck).')
    fix, state, target = fix_plan(ledger, shown)
    from . import knowledge
    title, mark = f'Support {ident}', f'(support {ident})'
    existing = [r for r in knowledge.records(fix) if mark in r.get('text', '')]
    if existing: return dict(existing[-1], recorded=False, root=state['selector'], feedback=ident)
    recorded = knowledge.record(fix, state['selector'], kind='lesson', text=f'{text} {mark}', title=title,
                                evidence={'status': 'verified', 'sources': [{'type': 'receipt', 'key': passed['receipt']}],
                                          'property': f'the original check of node {passed["refs"]["node"]} passed at the target with OneCrew '
                                                      f'{passed.get("version")} (support recheck)'})
    return dict(recorded, root=state['selector'], feedback=ident, certainty='verified at the target; cause not established')


def _hook_users(ledger, venv):
    """(files, unknown): the settings files of the projects OneCrew knows (hook registry, this project, the targets' declared consumers)
    whose OneCrew hook handlers run a program inside `venv`, and what could not be read."""
    registry, problem = _registry()
    unknown = [problem] if problem else []
    candidates = set(registry) | {os.path.normcase(str(ledger.project))}
    for target in targets(ledger).values(): candidates |= set(target.get('consumers') or [])
    files, inside = [], Path(venv).resolve()
    for key in sorted(candidates):
        for name in ('settings.local.json', 'settings.json'):
            path = Path(key) / '.claude' / name
            found = []
            programs = _programs(path, found)
            unknown += [f'{u["file"]}: {u["why"]}' for u in found]
            if any(Path(p).resolve().is_relative_to(inside) for p in programs): files.append(str(path))
    return files, unknown


def cleanup_venv(ledger, venv):
    """R3-02: the owner's way out of a venv folder this ledger began but never recorded a creation baseline for (an install stopped
    between python -m venv and the first passing check). Removed only when a marker in this ledger's support-work names it, no baseline
    of it exists in this ledger, no process runs from it and no OneCrew hook file points into it; the removal is recorded first."""
    _refuse_ai('support cleanup --venv')
    ownership.refuse_in_ai_session('support cleanup --venv')
    venv = Path(venv).resolve()
    markers = []
    for marker in sorted((ledger.state_root / WORK).glob('*/venv-*.json')) if (ledger.state_root / WORK).is_dir() else []:
        try:
            if _same(json.loads(marker.read_text(encoding='utf-8')).get('venv') or '', venv): markers.append(marker)
        except (OSError, ValueError):
            continue
    problems = []
    if not markers: problems.append('no marker of this ledger names it: OneCrew of this ledger did not begin it')
    if is_link(venv) or not venv.is_dir(): problems.append('it is not a folder (or it is a link)')
    if any(r.get('phase') == 'baseline' and _same(r.get('venv') or '', venv) for r in _records(ledger, 'support.install')):
        problems.append('a creation baseline of it exists in this ledger: it is a checked runtime, not an interrupted one')
    running = processes_under(venv) if venv.is_dir() else []
    if running is None: problems.append('processes: unknown (they cannot be listed here)')
    elif running: problems += [f'process {p["pid"]} runs {p["image"]}' for p in running]
    files, unknown = _hook_users(ledger, venv)
    problems += [f'the hook file {f} runs a program of it' for f in files] + [f'hook file unknown: {u}' for u in unknown]
    with ledger.transaction() as conn:
        if any(_live(c) for c in _claims(conn)): problems.append('an install, rollback or switch is in progress (a live claim)')
    if problems: raise LedgerError(f'support cleanup --venv {venv} refused, nothing removed: {"; ".join(problems)}')
    _anchor(ledger)
    _emit(ledger, 'support.install', {'phase': 'cleanup', 'venv': str(venv), 'markers': [str(m) for m in markers], 'by': 'owner',
                                      'session': ownership.session_info(), 'at': utcnow()})
    shutil.rmtree(venv)
    for marker in markers: marker.unlink(missing_ok=True)
    return {'removed': str(venv), 'markers': [str(m) for m in markers], 'note': 'support install creates the venv again'}


def cleanup(ledger):
    """Remove the finished drill, rollback and recheck copies under <state-root>/support-work (venvs and wheels are kept). The only
    retention S2 has (S1-R21/S2-R12). Refused while an install, rollback or switch holds a claim."""
    with ledger.transaction() as conn:
        live = [c for c in _claims(conn) if _live(c)] if conn else []
    if live: raise LedgerError('An install, rollback or switch is in progress: cleanup refused.')
    removed, size = [], 0
    root = ledger.state_root / WORK
    for key in sorted(root.iterdir()) if root.is_dir() else []:
        for item in sorted(key.iterdir()):
            if item.name in ('drill', 'rollback') or item.name.startswith('recheck-'):
                size += sum(p.stat().st_size for p in item.rglob('*') if p.is_file())
                shutil.rmtree(item, ignore_errors=True)
                removed.append(str(item))
    return {'removed': removed, 'bytes': size, 'kept': 'venvs, wheels and records'}
