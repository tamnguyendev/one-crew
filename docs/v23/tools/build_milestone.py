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

{steps_text} Kết quả ở `verify-report.json` trong thư mục làm việc. Các bước có worker dùng `claude` giả (test double, không gọi model): chứng minh đường đi, không chứng minh model dùng đúng tri thức.

## 2. Cài và dùng thử

```powershell
$venv = "D:\\OneCrewRuns\\v23 thu {milestone_lower}\\venv"; & $py -m venv $venv; & "$venv\\Scripts\\python.exe" -I -m pip install --no-index --no-build-isolation "$pkg\\wheel\\{wheel}"; & "$venv\\Scripts\\onecrew.exe" --help
```

Dùng trên một **bản sao** project (không dùng sổ đang chạy việc thật). Với project đã `onecrew init` bằng bản 2.2, chỉ cần cài wheel này vào venv thử; `init` mới ghi `%LOCALAPPDATA%\\OneCrew\\hook-projects.json` của người chạy.

{try_text}
- Hợp đồng triển khai, truy vết requirement → test → bằng chứng: `docs/HOP-DONG-2.3.vi.md`. Báo cáo mốc: `docs/` (file BAO-CAO).

## 3. Quay về 2.2 và lên lại

```powershell
& "$venv\\Scripts\\python.exe" -I -m pip install --no-index --no-build-isolation --force-reinstall "$pkg\\wheel\\previous\\{previous}"; $env:PYTHONUTF8 = "1"; & "$venv\\Scripts\\onecrew.exe" --help
```

```powershell
& "$venv\\Scripts\\python.exe" -I -m pip install --no-index --no-build-isolation --force-reinstall "$pkg\\wheel\\{wheel}"; Remove-Item Env:PYTHONUTF8 -ErrorAction SilentlyContinue; & "$venv\\Scripts\\onecrew.exe" --help
```

Bộ kiểm (bước V7) đã diễn tập: 2.2 đọc sổ do bản này ghi (`plan show`, `engine state`, `compat scan` không có khối read; khối continue giống sổ do 2.2 tự ghi), rồi lên lại bản này dùng tiếp. 2.2 không biết vòng đời tri thức: mục đã thu hồi hiện như ghi chú bình thường, và 2.2 không khôi phục được attempt đang dở mà worker đã trả khóa `knowledge`. Trước khi quay về, để mọi attempt kết thúc; với sổ thật hãy chạy `compat scan` trên bản sao trước. Không mặc định mọi sổ 2.3 đọc được bởi 2.2 ngoài phạm vi đã diễn tập.

## 4. Giới hạn

{limits}
'''


STEPS = {'A1': 'Bộ kiểm chạy 7 bước từ chính gói: V1 danh tính, V2 cài vào venv mới, V3 nguồn module, V4 task đầu tiên, V5 phản chứng, V6 console cp1252, V7 quay về 2.2 rồi lên lại.',
         'A2': 'Bộ kiểm chạy 8 bước từ chính gói: V1–V7 như A1 và V8 hai root ở hai process (root A công bố điều check đã chứng minh rồi kết thúc; root B mới dùng lại).',
         'B': 'Bộ kiểm chạy 8 bước từ chính gói: V1–V7 như A1 và V9 tiếp quản (controller `engine step` chết thật; `onecrew executor recover` xác nhận dọn; bước sau giữ node, chạy lại đúng 1 lần, không reset ngân sách).',
         'FINAL': 'Bộ kiểm chạy 9 bước từ chính gói: V1 danh tính, V2 cài vào venv mới, V3 nguồn module, V4 task đầu tiên (A1), V5 phản chứng, V6 console cp1252, V7 quay về 2.2 rồi lên lại, V8 hai root ở hai process (A2), V9 tiếp quản sau khi controller chết (B).'}
TRY_A1 = ('- Task đầu tiên chạy được: `examples/first-task/` (trang wiki mẫu, hợp đồng và định nghĩa node mẫu) và `verify/scenario_a1.py` (đúng luồng bộ kiểm chạy).\n'
          '- Cách viết wiki, lệnh `onecrew wiki pages|show|read`, cách đọc receipt: `docs/HUONG-DAN-WIKI.vi.md` §1–5.')
TRY_A2 = ('- Ghi và quản lý tri thức (A2): worker khai `knowledge.new`; điều check của node chứng minh được công bố cho project. Lệnh `onecrew wiki record|withdraw|archive|summarize|export|history`: '
          '`docs/HUONG-DAN-WIKI.vi.md` §6. Ca hai root chạy được: `verify/scenario_a2.py` (đúng luồng bước V8).')
TRY_B = ('- Dọn và tiếp quản (B): khi controller `engine step` chết hoặc treo, chạy `onecrew executor recover <attempt>` (hoặc `engine step` lần sau tự quét); '
         'node bị giữ với `cleanup: confirmed` rồi chạy lại một lần trong ngân sách cũ. Ca chạy được: `verify/scenario_b.py` (bước V9). Ghi chú và giới hạn: `docs/B-NOTES.vi.md`.')
TRY = {'A1': TRY_A1, 'A2': TRY_A1 + '\n' + TRY_A2, 'B': TRY_A1 + '\n' + TRY_B, 'FINAL': TRY_A1 + '\n' + TRY_A2 + '\n' + TRY_B}


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
    if args.milestone in ('B', 'FINAL'): shutil.copy2(ROOT / 'docs/v23/tools/scenario_b.py', verify / 'scenario_b.py')
    shutil.copy2(ROOT / 'tests/v23_fake_claude.py', verify / 'onecrew_fake_claude.py')
    docs = out / 'docs'; docs.mkdir()
    for path in sorted((ROOT / 'docs/v23').glob('*.md')): shutil.copy2(path, docs / path.name)
    if (ROOT / 'docs/v23/evidence').is_dir(): shutil.copytree(ROOT / 'docs/v23/evidence', docs / 'evidence')
    if (ROOT / 'docs/v23/examples').is_dir(): shutil.copytree(ROOT / 'docs/v23/examples', out / 'examples')
    built = time.strftime('%Y-%m-%d %H:%M:%S')
    previous_version = previous.name.split('-')[1]
    readme = README.format(version=version, label=MILESTONES[args.milestone], commit=commit, wheel=wheel_path.name, wheel_sha=sha(wheel_path),
                           previous=previous.name, previous_sha=args.previous_sha, built=built, out=str(out.resolve()),
                           milestone_lower=args.milestone.lower(), steps_text=STEPS[args.milestone], try_text=TRY[args.milestone], limits=Path(args.limits).read_text(encoding='utf-8').strip())
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
