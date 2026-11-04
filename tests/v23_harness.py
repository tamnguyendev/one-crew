"""2.3 test harness: the installed wheel in a fresh venv (path with spaces), the FAKE claude command (tests/v23_fake_claude.py) installed as
the `claude` console script of that venv, and the environment a scenario process runs in (venv Scripts first on PATH, isolated
LOCALAPPDATA/APPDATA, no checkout on sys.path). Fixture helpers only; the product code runs from the installed wheel."""
import base64
import hashlib
import io
import os
import shutil
import sys
import zipfile
from pathlib import Path

from tests import wf_wheel as wh

HERE = Path(__file__).resolve().parent
FAKE = 'onecrew_fake_claude'


def _record_line(name, data):
    digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).decode().rstrip('=')
    return f'{name},sha256={digest},{len(data)}'


def build_fake_wheel(into):
    """A wheel holding tests/v23_fake_claude.py as module onecrew_fake_claude with console script `claude`."""
    source = (HERE / 'v23_fake_claude.py').read_bytes()
    info = f'{FAKE}-0.1.dist-info'
    files = {f'{FAKE}.py': source,
             f'{info}/METADATA': b'Metadata-Version: 2.1\nName: onecrew-fake-claude\nVersion: 0.1\nSummary: test double of the claude CLI\n',
             f'{info}/WHEEL': b'Wheel-Version: 1.0\nGenerator: v23_harness\nRoot-Is-Purelib: true\nTag: py3-none-any\n',
             f'{info}/entry_points.txt': f'[console_scripts]\nclaude = {FAKE}:main\n'.encode()}
    record = [_record_line(name, data) for name, data in files.items()] + [f'{info}/RECORD,,']
    files[f'{info}/RECORD'] = ('\n'.join(record) + '\n').encode()
    path = Path(into) / 'onecrew_fake_claude-0.1-py3-none-any.whl'
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return path


def runtime(label='v23'):
    """(runs, python, wheel, ctx): a fresh temp folder, the product wheel built from this checkout, a venv under a folder with a space,
    the product + fake claude installed, and the boundary ctx of the installed distribution."""
    runs = Path(wh._runs())
    wheel, _, (modules, packages) = wh.build_wheel(runs)
    spaced = runs / f'{label} run with space'
    spaced.mkdir()
    python = wh.make_venv(spaced)
    wh.install(python, wheel)
    wh.install(python, build_fake_wheel(runs))
    ctx = wh.build_ctx(python, modules, packages)
    return runs, python, wheel, ctx


def scenario_env(python, work, policy=None, log=None):
    """Environment of a scenario process: the venv Scripts (fake claude) first on PATH, own LOCALAPPDATA/APPDATA, no AI-session markers."""
    scripts = Path(python).parent
    local = Path(work) / 'localappdata'; roaming = Path(work) / 'appdata'
    local.mkdir(parents=True, exist_ok=True); roaming.mkdir(parents=True, exist_ok=True)
    env = {'PATH': str(scripts) + os.pathsep + os.environ.get('PATH', ''), 'LOCALAPPDATA': str(local), 'APPDATA': str(roaming)}
    if policy is not None: env['ONECREW_FAKE_POLICY'] = str(policy)
    if log is not None: env['ONECREW_FAKE_LOG'] = str(log)
    return env


def clean_os_env():
    """os.environ without the variables that would leak the checkout or mark an AI session into a scenario process."""
    drop = {'PYTHONPATH', 'PYTHONSTARTUP', 'PYTHONHOME', 'CLAUDECODE', 'CLAUDE_CODE_CHILD_SESSION', 'ONECREW_ACTOR', 'PYTHONUTF8', 'PYTHONIOENCODING'}
    return {k: v for k, v in os.environ.items() if k.upper() not in drop}


def cleanup(runs):
    shutil.rmtree(runs, ignore_errors=True)
