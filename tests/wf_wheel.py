"""Kit harness for W40/T33a: build the wheel (pure-python, by hand — no setuptools needed), install it offline into a fresh venv, and run
the install-boundary check of onecrew.v2.boundary against that INSTALLED distribution. The wheel is built from the same pyproject py-modules
test_g1_core checks, so the shipped set and the RECORD agree by construction."""
import base64
import csv
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import uuid
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _runs():
    base = Path(os.environ.get('TEMP') or '/tmp') / 'wf40' / uuid.uuid4().hex[:6]
    base.mkdir(parents=True)
    return base


def _b64(data):
    return base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b'=').decode()


def _log_used(whl):
    """WF_WHEEL_USED_LOG (set by wfkit/gate.py): append the sha256 of the wheel this run actually used, so the receipt can prove it."""
    log = os.environ.get('WF_WHEEL_USED_LOG')
    if log:
        with open(log, 'a', encoding='utf-8') as f:
            f.write(hashlib.sha256(Path(whl).read_bytes()).hexdigest() + chr(10))


def _reuse_wheel(src, into):
    """WF_WHEEL: use the wheel the release gate already built (same bytes, same hash) instead of building another one."""
    src = Path(src)
    if not src.is_file():
        raise RuntimeError(f'WF_WHEEL {src} is not a file')
    digest = hashlib.sha256(src.read_bytes()).hexdigest()
    expected = os.environ.get('WF_WHEEL_SHA256')
    if expected and expected != digest:
        raise RuntimeError(f'WF_WHEEL {src} has sha256 {digest}, the gate said {expected}')
    m = re.match(r'onecrew-(.+)-py3-none-any\.whl$', src.name)
    if not m:
        raise RuntimeError(f'WF_WHEEL {src.name} is not onecrew-<version>-py3-none-any.whl')
    pj = (REPO / 'pyproject.toml').read_text(encoding='utf-8')
    modules = re.findall(r'"([\w.]+)"', re.search(r'py-modules\s*=\s*\[(.*?)\]', pj, re.S).group(1))
    packages = re.findall(r'"([\w.]+)"', re.search(r'^\s*packages\s*=\s*\[(.*?)\]', pj, re.M | re.S).group(1))
    dst = Path(into) / src.name
    if dst.resolve() != src.resolve():
        dst.write_bytes(src.read_bytes())
    _log_used(dst)
    return dst, m.group(1), (set(modules), set(packages))


def build_wheel(into):
    """Build onecrew-<version>-py3-none-any.whl from REPO's pyproject into `into`. Returns (wheel_path, version, (modules, packages)).
    When WF_WHEEL names a prebuilt wheel (the release gate sets it) that exact file is reused; otherwise the behaviour is unchanged."""
    if os.environ.get('WF_WHEEL'):
        return _reuse_wheel(os.environ['WF_WHEEL'], into)
    pj = (REPO / 'pyproject.toml').read_text(encoding='utf-8')
    version = re.search(r'version = "([^"]+)"', pj).group(1)
    modules = re.findall(r'"([\w.]+)"', re.search(r'py-modules\s*=\s*\[(.*?)\]', pj, re.S).group(1))
    packages = re.findall(r'"([\w.]+)"', re.search(r'^\s*packages\s*=\s*\[(.*?)\]', pj, re.M | re.S).group(1))
    whl = Path(into) / f'onecrew-{version}-py3-none-any.whl'
    records = []
    with zipfile.ZipFile(whl, 'w', zipfile.ZIP_DEFLATED) as z:
        def add(arc, data):
            z.writestr(arc, data); records.append((arc, 'sha256=' + _b64(data), str(len(data))))
        for m in modules:
            add(m.replace('.', '/') + '.py', (REPO / (m.replace('.', '/') + '.py')).read_bytes())
        parents = {'/'.join(m.split('.')[:i]) for m in modules for i in range(1, len(m.split('.')))}
        parents |= {p.replace('.', '/') for p in packages}
        for pkg in sorted(parents):
            init = REPO / pkg / '__init__.py'
            if init.is_file():
                add(pkg + '/__init__.py', init.read_bytes())
        tpl = REPO / 'onecrew' / 'templates'
        if tpl.is_dir():
            for md in tpl.glob('*.md'):
                add(f'onecrew/templates/{md.name}', md.read_bytes())
        di = f'onecrew-{version}.dist-info'
        add(f'{di}/METADATA', f'Metadata-Version: 2.1\nName: onecrew\nVersion: {version}\nRequires-Python: >=3.10\n'.encode())
        add(f'{di}/WHEEL', b'Wheel-Version: 1.0\nGenerator: wf-handbuild\nRoot-Is-Purelib: true\nTag: py3-none-any\n')
        add(f'{di}/entry_points.txt', b'[console_scripts]\nonecrew = onecrew.v2.cli:main\n')
        rec = io.StringIO(); w = csv.writer(rec)
        for arc, h, sz in records:
            w.writerow([arc, h, sz])
        w.writerow([f'{di}/RECORD', '', ''])
        z.writestr(f'{di}/RECORD', rec.getvalue())
    _log_used(whl)
    return whl, version, (set(modules), set(packages))


def make_venv(into):
    venv = Path(into) / 'venv'
    subprocess.run([sys.executable, '-m', 'venv', str(venv)], check=True, capture_output=True)
    return venv / ('Scripts' if os.name == 'nt' else 'bin') / ('python.exe' if os.name == 'nt' else 'python')


def install(python, wheel):
    r = subprocess.run([str(python), '-m', 'pip', 'install', '--no-index', '--no-build-isolation', str(wheel)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError('offline wheel install failed: ' + (r.stdout + r.stderr)[-400:])


# ---- building the boundary ctx from the INSTALLED distribution + the interpreter -----------------------------------------

def installed_record(python):
    """The RECORD of the installed onecrew dist, as absolute normalised file paths, read from the venv."""
    code = ('import json, sys\n'
            'from importlib.metadata import distribution\n'
            'from pathlib import Path\n'
            'd = distribution("onecrew")\n'
            'base = Path(d.locate_file(""))\n'
            'files = [str((base / f.as_posix()).resolve()) for f in d.files]\n'
            'req = list(d.requires or [])\n'
            'print(json.dumps({"files": files, "requires": req}))')
    r = subprocess.run([str(python), '-c', code], capture_output=True, text=True)
    return json.loads(r.stdout)


def markers(python):
    """The stdlib marker origins and directories, from `python -I -S` + find_spec over stdlib_module_names (never hard-coded)."""
    code = ('import sys, json, importlib.util\n'
            'out = {}\n'
            'for n in sorted(sys.stdlib_module_names):\n'
            '    try: s = importlib.util.find_spec(n)\n'
            '    except Exception: s = None\n'
            '    out[n] = None if s is None else s.origin\n'
            'print(json.dumps({"origins": out, "builtin": sorted(sys.builtin_module_names)}))')
    r = subprocess.run([str(python), '-I', '-S', '-c', code], capture_output=True, text=True)
    data = json.loads(r.stdout)
    from onecrew.v2.boundary import norm
    dirs = sorted({norm(os.path.dirname(o)) for o in data['origins'].values() if o and o not in ('built-in', 'frozen')})
    dirs = sorted({d if not os.path.exists(os.path.join(d, '__init__.py')) else os.path.dirname(d) for d in dirs})
    return data['origins'], set(data['builtin']), dirs


def build_ctx(python, modules, packages, base_exempt=()):
    from onecrew.v2.boundary import norm, shipped_names
    pj = (REPO / 'pyproject.toml').read_text(encoding='utf-8')
    m, pk, parents = shipped_names(pj)
    rec = installed_record(python)
    origins, builtin, marker_dirs = markers(python)
    return {'modules': m, 'packages': pk, 'parents': parents,
            'record_files': {norm(f) for f in rec['files']},
            'stdlib_names': set(origins), 'ref': origins, 'builtin': builtin, 'marker_dirs': marker_dirs,
            'dep_tops': set(), 'dep_files': set(), 'base_exempt': set(base_exempt), 'driver': None}


_DUMP = ('import sys, _imp, json\n'
         'def _dump():\n'
         '    out = {}\n'
         '    for n, mod in list(sys.modules.items()):\n'
         '        spec = getattr(mod, "__spec__", None)\n'
         '        out[n] = {"file": getattr(mod, "__file__", None),\n'
         '                  "origin": getattr(spec, "origin", None) if spec else None,\n'
         '                  "frozen": bool(_imp.is_frozen(n)), "builtin": n in sys.builtin_module_names}\n'
         '    return out\n')


def run_case(python, body, *, env_extra=None, flags=('-I',), cwd=None):
    """Run a subprocess interpreter that executes `body` then dumps sys.modules (start + end). Returns {'start':[...], 'end':{...}} or None."""
    code = _DUMP + '_start = sorted(sys.modules)\n' + body + '\nprint("@@" + json.dumps({"start": _start, "end": _dump()}))\n'
    # An installed scenario is the owner's own terminal: the AI-session markers of the test runner must not leak into it
    # (owner verbs such as plan approve are refused inside an AI session, W03/C11). A case that wants the marker sets it in env_extra.
    env = {k: v for k, v in os.environ.items() if k not in ('PYTHONPATH', 'PYTHONSTARTUP', 'PYTHONHOME', 'CLAUDE_CODE_CHILD_SESSION', 'CLAUDECODE')}
    env.update(env_extra or {})
    r = subprocess.run([str(python), *flags, '-c', code], capture_output=True, text=True, encoding='utf-8', errors='replace',
                       env=env, cwd=str(cwd) if cwd else None)
    line = next((l for l in r.stdout.splitlines() if l.startswith('@@')), None)
    return (json.loads(line[2:]) if line else None, (r.stdout + r.stderr)[-500:])
