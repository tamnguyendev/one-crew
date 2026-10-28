"""build_milestone.py <out dir> --milestone A1|A2|B|FINAL --previous-wheel <2.2 wheel> --previous-sha <sha256> - assemble a OneCrew 2.3
milestone package from a CLEAN checkout (onecrew/, tests/, pyproject.toml committed): the wheel built by the project's own builder
(tests/wf_wheel.build_wheel, i.e. the same bytes a test would install), the previous wheel byte-identical for rollback, the verifier
(docs/v23/tools/verify_milestone.py + scenario + the fake claude test double), the 2.3 documents and evidence, examples, README,
manifest.json and SHA256SUMS. Refuses an existing <out> and a dirty code tree. Nothing outside <out> is written."""
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

MILESTONES = {'A1': '2.3-A1 — đọc wiki và giao context cho worker',
              'A2': '2.3-A2 — cập nhật có bằng chứng và dùng lại qua root mới',
              'B': '2.3-B — cleanup và tiếp quản an toàn',
              'FINAL': 'OneCrew 2.3 — A1 + A2 + B'}


def git(*args):
    return subprocess.run(['git', '-C', str(ROOT), *args], check=True, capture_output=True, text=True).stdout.strip()


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


README = '''# OneCrew {version} — gói thử {label}

**Đây là gói thử để chạy trên project copy và sổ riêng, chưa phải bản phát hành.** Chưa được Codex review, chưa nghiệm thu. Gói không tự nhận đã giao (`manifest.json` → `claims`).

| Mục | Giá trị |
|---|---|
| Code | `{commit}` (nhánh `claude/onecrew-2.3`, local) |
| Wheel | `wheel/{wheel}` · SHA256 `{wheel_sha}` |
| Wheel để quay về | `wheel/previous/{previous}` · SHA256 `{previous_sha}` (beta 2.2, giống từng byte gói beta) |
| Dựng lúc | {built} |

## 1. Kiểm hash và kiểm gói

PowerShell, trong cùng một cửa sổ:

```powershell
$py = "C:\\Users\\NUC\\AppData\\Local\\Programs\\Python\\Python313\\python.exe"; $pkg = "{out}"; Get-FileHash -Algorithm SHA256 "$pkg\\wheel\\{wheel}"
```

```powershell
& $py -I "$pkg\\verify\\verify_milestone.py" $pkg "D:\\OneCrewRuns\\v23 thu {milestone_lower}\\verify"
```

Bộ kiểm chạy 7 bước từ chính gói (danh tính, cài vào venv mới, nguồn module, task đầu tiên, phản chứng, console cp1252, quay về 2.2 rồi lên lại); kết quả ở `verify-report.json` trong thư mục làm việc. Bước task đầu tiên dùng `claude` giả (test double, không gọi model).

## 2. Cài và dùng thử

```powershell
$venv = "D:\\OneCrewRuns\\v23 thu {milestone_lower}\\venv"; & $py -m venv $venv; & "$venv\\Scripts\\python.exe" -I -m pip install --no-index --no-build-isolation "$pkg\\wheel\\{wheel}"; & "$venv\\Scripts\\onecrew.exe" --help
```

Dùng trên một **bản sao** project (không dùng sổ đang chạy việc thật). Với project đã `onecrew init` bằng bản 2.2, chỉ cần cài wheel này vào venv thử; `init` mới ghi `%LOCALAPPDATA%\\OneCrew\\hook-projects.json` của người chạy.

- Task đầu tiên chạy được: `examples/first-task/` (trang wiki mẫu, hợp đồng và định nghĩa node mẫu) và `verify/scenario_a1.py` (đúng luồng bộ kiểm chạy).
- Cách viết wiki, lệnh `onecrew wiki pages|show|read`, cách đọc receipt: `docs/HUONG-DAN-WIKI.vi.md`.
- Hợp đồng triển khai, truy vết requirement → test → bằng chứng: `docs/HOP-DONG-2.3.vi.md`. Báo cáo mốc: `docs/` (file BAO-CAO).

## 3. Quay về 2.2 và lên lại

```powershell
& "$venv\\Scripts\\python.exe" -I -m pip install --no-index --no-build-isolation --force-reinstall "$pkg\\wheel\\previous\\{previous}"; $env:PYTHONUTF8 = "1"; & "$venv\\Scripts\\onecrew.exe" --help
```

```powershell
& "$venv\\Scripts\\python.exe" -I -m pip install --no-index --no-build-isolation --force-reinstall "$pkg\\wheel\\{wheel}"; Remove-Item Env:PYTHONUTF8 -ErrorAction SilentlyContinue; & "$venv\\Scripts\\onecrew.exe" --help
```

Bộ kiểm (bước V7) đã diễn tập: sổ do bản này ghi được 2.2 đọc (`compat scan` blocking 0, `plan show` chạy), rồi lên lại bản này dùng tiếp. Không mặc định mọi sổ 2.3 đọc được bởi 2.2 ngoài phạm vi đã diễn tập; với sổ thật hãy chạy `compat scan` trên bản sao trước.

## 4. Giới hạn

{limits}
'''


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('out'); parser.add_argument('--milestone', required=True, choices=sorted(MILESTONES))
    parser.add_argument('--previous-wheel', required=True); parser.add_argument('--previous-sha', required=True)
    parser.add_argument('--limits', required=True, help='a Markdown file with the limits section')
    args = parser.parse_args()
    out = Path(args.out)
    if out.exists(): raise SystemExit(f'{out} exists; a package folder is never reused.')
    dirty = git('status', '--porcelain', '--', 'onecrew', 'tests', 'pyproject.toml', 'docs/v23/tools')
    if dirty: raise SystemExit('code tree is dirty; commit first:\n' + dirty)
    previous = Path(args.previous_wheel)
    if sha(previous) != args.previous_sha: raise SystemExit('previous wheel sha256 differs from --previous-sha')
    commit = git('rev-parse', 'HEAD')
    temp = Path(wh._runs())
    try:
        wheel, _, _ = wh.build_wheel(temp)
        (out / 'wheel' / 'previous').mkdir(parents=True)
        shutil.copy2(wheel, out / 'wheel' / Path(wheel).name)
        shutil.copy2(previous, out / 'wheel' / 'previous' / previous.name)
    finally:
        shutil.rmtree(temp, ignore_errors=True)
    wheel_path = out / 'wheel' / Path(wheel).name
    version = Path(wheel).name.split('-')[1]
    verify = out / 'verify'; verify.mkdir()
    shutil.copy2(ROOT / 'docs/v23/tools/verify_milestone.py', verify / 'verify_milestone.py')
    shutil.copy2(ROOT / 'docs/v23/tools/scenario_a1.py', verify / 'scenario_a1.py')
    if args.milestone in ('A2', 'FINAL'): shutil.copy2(ROOT / 'docs/v23/tools/scenario_a2.py', verify / 'scenario_a2.py')
    shutil.copy2(ROOT / 'tests/v23_fake_claude.py', verify / 'onecrew_fake_claude.py')
    docs = out / 'docs'; docs.mkdir()
    for path in sorted((ROOT / 'docs/v23').glob('*.md')): shutil.copy2(path, docs / path.name)
    if (ROOT / 'docs/v23/evidence').is_dir(): shutil.copytree(ROOT / 'docs/v23/evidence', docs / 'evidence')
    if (ROOT / 'docs/v23/examples').is_dir(): shutil.copytree(ROOT / 'docs/v23/examples', out / 'examples')
    built = time.strftime('%Y-%m-%d %H:%M:%S')
    previous_version = previous.name.split('-')[1]
    readme = README.format(version=version, label=MILESTONES[args.milestone], commit=commit, wheel=wheel_path.name, wheel_sha=sha(wheel_path),
                           previous=previous.name, previous_sha=args.previous_sha, built=built, out=str(out.resolve()),
                           milestone_lower=args.milestone.lower(), limits=Path(args.limits).read_text(encoding='utf-8').strip())
    (out / 'README.md').write_text(readme, encoding='utf-8')
    manifest = {'kind': 'v23-milestone-package', 'milestone': args.milestone, 'label': MILESTONES[args.milestone], 'version': version,
                'code_commit': commit, 'built_at': built, 'ships_paging': False,
                'wheel': {'name': wheel_path.name, 'sha256': sha(wheel_path)},
                'previous_wheel': {'name': previous.name, 'sha256': args.previous_sha, 'version': previous_version},
                'claims': {'delivered': False, 'reviewed_by_codex': False, 'accepted_by_owner': False, 'released': False}}
    (out / 'manifest.json').write_text(json.dumps(manifest, indent=1, ensure_ascii=False), encoding='utf-8')
    lines = [f'{sha(p)}  {p.relative_to(out).as_posix()}' for p in sorted(out.rglob('*')) if p.is_file()]
    (out / 'SHA256SUMS').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(json.dumps({'out': str(out), 'version': version, 'commit': commit, 'wheel_sha256': manifest['wheel']['sha256'], 'files': len(lines) + 1}))


if __name__ == '__main__':
    main()
