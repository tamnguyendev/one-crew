"""build_obs1.py <out dir> - assemble the OBS-1 trial package from a CLEAN checkout: the wheel built by the project's own builder
(tests/wf_wheel.build_wheel: the same bytes a test installs), the verifier (verify_obs1.py + scenario_obs1.py + the v24 fake claude + the owner's
one-command wrapper thu-goi-obs1.ps1), the OBS-1 documents, manifest.json and SHA256SUMS. Refuses an existing <out> and a dirty tree of
onecrew/, tests/, pyproject.toml, docs/obs1. Writes nothing outside <out>. The package claims nothing: `claims` says what was and was not checked."""
import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from tests import wf_wheel as wh      # noqa: E402

CODE_PATHS = ('onecrew', 'tests', 'pyproject.toml', 'docs/obs1')
VERIFY = (('docs/obs1/tools/verify_obs1.py', 'verify/verify_obs1.py'), ('docs/obs1/tools/scenario_obs1.py', 'verify/scenario_obs1.py'),
          ('tests/v24_fake_claude.py', 'verify/onecrew_fake_claude_v24.py'), ('docs/obs1/tools/thu-goi-obs1.ps1', 'verify/thu-goi-obs1.ps1'),
          ('tests/obs1_ux_harness.py', 'verify/obs1_ux_harness.py'), ('docs/obs1/tools/mo-trang-obs1.ps1', 'verify/mo-trang-obs1.ps1'), ('docs/obs1/tools/dung-trang-obs1.ps1', 'verify/dung-trang-obs1.ps1'))
DOCS = ('GIAI-PHAP-OBS-1.vi.md', 'BAO-CAO-OBS-1.vi.md', 'limits-obs1.md', 'RELEASE-NOTES-OBS-1.vi.md', 'UX-OBS-1.vi.md')


def git(*args):
    return subprocess.run(['git', '-C', str(ROOT), *args], check=True, capture_output=True, text=True).stdout.strip()


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('out', type=Path); parser.add_argument('--allow-missing-docs', action='store_true')
    args = parser.parse_args()
    out = args.out.resolve()
    if out.exists(): raise SystemExit(f'{out} exists; a package folder is never reused.')
    dirty = git('status', '--porcelain', '--', *CODE_PATHS)
    if dirty: raise SystemExit('the tree is not clean:\n' + dirty)
    commit, branch = git('rev-parse', 'HEAD'), git('rev-parse', '--abbrev-ref', 'HEAD')
    out.mkdir(parents=True); (out / 'wheel').mkdir(); (out / 'verify').mkdir(); (out / 'docs').mkdir()
    wheel, version, _ = wh.build_wheel(out / 'wheel')
    for src, dst in VERIFY: shutil.copyfile(ROOT / src, out / dst)
    for name in DOCS:
        path = ROOT / 'docs' / 'obs1' / name
        if path.is_file(): shutil.copyfile(path, out / 'docs' / name)
        elif not args.allow_missing_docs: raise SystemExit('missing document ' + name)
    built = time.strftime('%Y-%m-%dT%H:%M:%S')
    manifest = {'kind': 'obs1-trial-package', 'label': 'OBS-1 beta', 'version': version, 'code_commit': commit, 'branch': branch, 'built': built,
                'wheel': {'name': wheel.name, 'sha256': sha(wheel)}, 'base': '2.4.0.dev8 (e9c02de, tag v2.4.0.dev8, released) < dev9 (b070559, local) on 2.4.0.dev6 (01b6f62): the 2.4 release line is NOT changed by this package',
                'claims': {'delivered': False, 'accepted': False, 'reviewed_by_codex': False, 'real_provider_tested': False,
                           'note': 'OBS-1 beta package: the tracking view/CLI/page, the four Codex P2 fixes, the UX round (UX-01..08) and the track open identity checked from this package with the fake claude; see docs/limits-obs1.md and docs/RELEASE-NOTES-OBS-1.vi.md'}}
    guide = (ROOT / 'docs' / 'obs1' / 'BAT-DAU-THU-OBS1.vi.md').read_text(encoding='utf-8')
    for key, value in (('@@PACKAGE@@', str(out)), ('@@VERSION@@', version), ('@@COMMIT@@', commit[:7]), ('@@WHEEL@@', wheel.name), ('@@WHEEL_SHA@@', manifest['wheel']['sha256']), ('@@BRANCH@@', branch)):
        guide = guide.replace(key, value)
    (out / 'BAT-DAU-THU.vi.md').write_text(guide, encoding='utf-8', newline='\n')
    (out / 'manifest.json').write_text(json.dumps(manifest, indent=1, ensure_ascii=False), encoding='utf-8', newline='\n')
    files = sorted(p for p in out.rglob('*') if p.is_file())
    (out / 'SHA256SUMS').write_text(''.join(f'{sha(p)}  {p.relative_to(out).as_posix()}\n' for p in files), encoding='utf-8', newline='\n')
    print(json.dumps({'package': str(out), 'version': version, 'commit': commit, 'wheel': manifest['wheel'], 'files': len(files) + 1}, ensure_ascii=False, indent=1))
    return 0


if __name__ == '__main__':
    sys.exit(main())
