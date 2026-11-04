"""Build a LOCAL OBS-2 trial from an explicit committed snapshot, never the dirty checkout.

python docs/obs2/tools/build_obs2.py --commit <full SHA> --out <new directory>
Uses tests/wf_wheel.py unchanged, offline; writes only the new output directory.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[3]
MODULES = ('onecrew/v2/tracking.py', 'onecrew/v2/tracking_web.py',
           'onecrew/v2/tracking_work.py', 'onecrew/v2/tracking_work_web.py')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def build(commit, out):
    if not re.fullmatch(r'[0-9a-f]{40}', commit): raise ValueError('--commit requires an exact full 40-hex commit.')
    out = Path(out).resolve()
    if out.exists(): raise ValueError('Output exists; use a new package directory.')
    if out == ROOT or ROOT in out.parents: raise ValueError('Package must be outside the checkout.')
    actual = subprocess.check_output(['git', '-C', str(ROOT), 'rev-parse', '--verify', commit + '^{commit}'], text=True).strip()
    if actual != commit: raise ValueError('Commit did not resolve exactly.')
    out.mkdir(parents=True)
    with tempfile.TemporaryDirectory(prefix='snapshot-', dir=out) as tmp:
        snapshot = Path(tmp)
        archive = snapshot / 'source.zip'
        subprocess.run(['git', '-C', str(ROOT), 'archive', '--format=zip', '--output=' + str(archive), commit,
                        'onecrew', 'tests/wf_wheel.py', 'pyproject.toml', 'docs/obs2',
                        'tests/obs1_ux_harness.py', 'tests/obs2_ux_harness.py', 'tests/obs2_artifact_browser.py',
                        'docs/obs1/tools/mo-trang-obs1.ps1', 'docs/obs1/tools/dung-trang-obs1.ps1'], check=True)
        with zipfile.ZipFile(archive) as zipped:
            for name in zipped.namelist():
                if not (snapshot / name).resolve().is_relative_to(snapshot): raise ValueError('Unsafe archive path.')
            zipped.extractall(snapshot)
        for name in MODULES:
            if not (snapshot / name).is_file(): raise ValueError('Snapshot lacks required module: ' + name)
        spec = importlib.util.spec_from_file_location('obs2_snapshot_wheel', snapshot / 'tests/wf_wheel.py')
        builder = importlib.util.module_from_spec(spec); spec.loader.exec_module(builder)
        saved = {k: os.environ.pop(k, None) for k in ('WF_WHEEL', 'WF_WHEEL_SHA256', 'WF_WHEEL_USED_LOG')}
        try:
            (out / 'wheel').mkdir(); wheel, version, _ = builder.build_wheel(out / 'wheel')
        finally:
            for key, value in saved.items():
                if value is not None: os.environ[key] = value
        with zipfile.ZipFile(wheel) as zipped:
            for name in MODULES:
                if zipped.read(name) != (snapshot / name).read_bytes(): raise ValueError('Wheel/source mismatch: ' + name)
        (out / 'verify').mkdir()
        for name in ('verify_obs2.py', 'scenario_obs2.py', 'viewer_obs2.ps1', 'mo-trang-obs2.ps1', 'dung-trang-obs2.ps1'):
            shutil.copyfile(snapshot / 'docs/obs2/tools' / name, out / 'verify' / name)
        for name in ('mo-trang-obs1.ps1', 'dung-trang-obs1.ps1'):
            shutil.copyfile(snapshot / 'docs/obs1/tools' / name, out / 'verify' / name)
        (out / 'verify/tests').mkdir()
        (out / 'verify/tests/__init__.py').write_text('# Packaged browser harness only, not installed runtime.\n', encoding='utf-8')
        for name in ('obs1_ux_harness.py', 'obs2_ux_harness.py'):
            shutil.copyfile(snapshot / 'tests' / name, out / 'verify/tests' / name)
        shutil.copyfile(snapshot / 'tests/obs2_artifact_browser.py', out / 'verify/obs2_artifact_browser.py')
        shutil.copyfile(snapshot / 'docs/obs2/README.vi.md', out / 'README.vi.md')
        manifest = {'kind': 'obs2-local-trial', 'label': 'OBS-2A/2B synthetic fixture; local, not accepted',
                    'code_commit': commit, 'version': version, 'wheel': {'name': wheel.name, 'sha256': sha(wheel)},
                    'module_sha256': {name: sha(snapshot / name) for name in MODULES},
                    'claims': {'real_provider_tested': False, 'real_state_used': False, 'accepted': False,
                               'browser_verified': False, 'note': 'Run verify_obs2.py; build alone proves no runtime result.'}}
        (out / 'manifest.json').write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding='utf-8')
    (out / 'SHA256SUMS').write_text(''.join(f'{sha(p)}  {p.relative_to(out).as_posix()}\n'
        for p in sorted(out.rglob('*')) if p.is_file()), encoding='utf-8')
    return {'package': str(out), **manifest}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--commit', required=True); parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.commit, args.out), ensure_ascii=False, indent=2))
