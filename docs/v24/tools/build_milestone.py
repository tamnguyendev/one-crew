"""build_milestone.py <out dir> --milestone S1|S2|A|B|C|FINAL --stage alpha|beta --limits <file> [--previous-wheel W --previous-sha H]
[--regression-wheel W --regression-sha H] - assemble a OneCrew 2.4 milestone package from a CLEAN checkout (onecrew/, tests/, pyproject.toml,
docs/v23, docs/v24 committed): the wheel built by the project's own builder (tests/wf_wheel.build_wheel, the same bytes a test would
install), the previous wheel (the 2.3.0.dev10 beta, to go back to) and the regression wheel (2.2.0.dev18, which the 2.3 regression steps V7/V15/V16
install; byte-identical to the one the 2.3 package shipped), the verifier (docs/v24/tools/verify_milestone.py + the 2.3 scenario files + the fake
claude test double + first_task_drill.py + alpha_flow.py + the owner's one-command wrapper thu_goi.ps1, shipped as verify/thu-goi.ps1), the 2.4
documents, the 2.3 documents as history, the examples (the first task), README, manifest.json and SHA256SUMS.

The manifest says which milestones the package contains (`milestones_included`, cumulative: S1 -> ['S1'], S2 -> ['S1','S2'], ..., FINAL -> all)
and the verifier runs the steps of exactly those milestones (verify_milestone.MILESTONE_STEPS). A milestone that has no verifier step or no
"Thu nhanh" text yet is refused BEFORE anything is written: a package never claims a milestone nobody can check.
Refuses an existing <out> and a dirty code or documents tree. Nothing outside <out> is written."""
import argparse
import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from tests import wf_wheel as wh      # noqa: E402

MILESTONES = {'S1': 'báo lỗi một lần, hồ sơ chẩn đoán',
              'S2': 'nối bản vá với công việc cũ',
              'A': 'worker đọc và tìm source trong quyền',
              'B': 'working context và cập nhật cho consumer',
              'C': 'bước 0 và chọn cách thực hiện',
              'FINAL': 'toàn bộ 2.4'}
ORDER = ['S1', 'S2', 'A', 'B', 'C']          # cumulative: a package of milestone X contains every milestone up to X
DEFAULT_PREVIOUS = ('D:/OneCrewRuns/v23/pkg/onecrew-2.3.0.dev10-beta/wheel/onecrew-2.3.0.dev10-py3-none-any.whl',
                    '8ab065c3bc6d2863888314952e3743b031d44ea44c1e92cd740abba385a1b4f7')
DEFAULT_REGRESSION = ('D:/OneCrewRuns/v23/pkg/onecrew-2.3.0.dev10-beta/wheel/previous/onecrew-2.2.0.dev18-py3-none-any.whl',
                      '0346577e4847a1388e1843765edd48a0fcf1e453ca25fdf13342e07323ef9bd2')
CODE_PATHS = ('onecrew', 'tests', 'pyproject.toml', 'docs/v23', 'docs/v24', 'docs/CHANGELOG.md')      # the tree the package is made of must be committed
REGRESSION_STEPS = 16                                                  # V1-V16 of 2.3, run for every 2.4 package (verify_milestone.REGRESSION_STEPS)
SCENARIOS = ('scenario_a1.py', 'scenario_a2.py', 'scenario_b.py', 'scenario_codex.py')       # V4-V14 need all of them, whatever the 2.4 milestone
SHARED_TOOLS = ('make_fake_claude_wheel.py', 'first_task_drill.py', 'alpha_flow.py')         # what examples/first-task/README.vi.md names under verify/


def git(*args):
    return subprocess.run(['git', '-C', str(ROOT), *args], check=True, capture_output=True, text=True).stdout.strip()


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_verifier():
    """docs/v24/tools/verify_milestone.py as a module (its MILESTONE_STEPS table); importing it runs nothing."""
    sys.dont_write_bytecode = True               # importing the verifier must not leave a __pycache__ in the tree being checked for cleanliness
    spec = importlib.util.spec_from_file_location('v24_verify_milestone', ROOT / 'docs/v24/tools/verify_milestone.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


README = '''# OneCrew {version} — gói thử 2.4 ({label})

**Đây là bản thử {stage}(prerelease) `{version}`, không phải bản ổn định; chạy trên bản sao project và sổ riêng.** Chưa nghiệm thu; trạng thái review của bản này ghi ở dòng đầu mục Giới hạn. Gói không tự nhận đã giao (`manifest.json` → `claims`).

**Gói nằm dưới `D:\\OneCrewRuns\\v24\\pkg-trial` là bản thử của công cụ dựng và kiểm gói, không phải bản giao.** Bản giao là gói được dựng từ snapshot cuối của nhánh 2.4 (người điều phối dựng); chỉ gói đó được báo là bàn giao.

| Mục | Giá trị |
|---|---|
| Code | `{commit}` (nhánh `{branch}`) |
| Mốc 2.4 có trong gói | {included} |
| Wheel | `wheel/{wheel}` · SHA256 `{wheel_sha}` |
| Wheel để quay về | `wheel/previous/{previous}` · SHA256 `{previous_sha}` (beta 2.3, giống từng byte gói beta 2.3.0.dev10) |
| Wheel hồi quy (chỉ bộ kiểm dùng) | `wheel/regression/{regression}` · SHA256 `{regression_sha}` (beta 2.2: bước V7, V15, V16 của 2.3 cần một bản 2.2 để cài trước rồi nâng lên) |
| Dựng lúc | {built} |

## 1. Kiểm hash và kiểm gói

Một lệnh làm cả kiểm hash, bộ kiểm của gói, task đầu tiên từ README và luồng alpha 2.3 (`verify/alpha_flow.py`, 5 chặng), trên thư mục kết quả mới và sổ tạm:

```powershell
powershell -ExecutionPolicy Bypass -File "{out}\\verify\\thu-goi.ps1"
```

Đạt khi in dòng bắt đầu bằng `DAT:` và thoát mã 0. Mọi trường hợp khác (lệnh lỗi, thiếu báo cáo, báo cáo cũ hoặc của gói khác, thư mục kết quả đã có file) in `KHONG DAT:` và thoát mã khác 0. Hoặc làm từng bước:

PowerShell, trong cùng một cửa sổ:

```powershell
$py = "C:\\Users\\NUC\\AppData\\Local\\Programs\\Python\\Python313\\python.exe"; $pkg = "{out}"; Get-FileHash -Algorithm SHA256 "$pkg\\wheel\\{wheel}"
```

```powershell
& $py -I "$pkg\\verify\\verify_milestone.py" $pkg "D:\\OneCrewRuns\\v24 thu {tag}\\verify"
```

{steps_text} Kết quả ở `verify-report.json` trong thư mục làm việc: nó ghi cả các mốc có trong gói và các bước bị bỏ vì mốc đó chưa có trong gói. Các bước có worker dùng `claude` giả (test double, không gọi model): chứng minh đường đi, không chứng minh model dùng đúng tri thức.

## 2. Cài và dùng thử

```powershell
$venv = "D:\\OneCrewRuns\\v24 thu {tag}\\venv"; & $py -m venv $venv; & "$venv\\Scripts\\python.exe" -I -m pip install --no-index --no-build-isolation "$pkg\\wheel\\{wheel}"; & "$venv\\Scripts\\onecrew.exe" --help
```

Dùng trên một **bản sao** project (không dùng sổ đang chạy việc thật). `onecrew --version` in version đã cài. Với project đã `onecrew init` bằng bản trước, chạy lại `onecrew init` của bản này: sổ, config và hook được giữ (hook trỏ sang lệnh mới). `init` ghi `%LOCALAPPDATA%\\OneCrew\\hook-projects.json` của người chạy.

### Thử nhanh

{try_text}

## 3. Quay về 2.3.0.dev10 và lên lại

```powershell
& "$venv\\Scripts\\python.exe" -I -m pip install --no-index --no-build-isolation --force-reinstall "$pkg\\wheel\\previous\\{previous}"; & "$venv\\Scripts\\onecrew.exe" --help
```

```powershell
& "$venv\\Scripts\\python.exe" -I -m pip install --no-index --no-build-isolation --force-reinstall "$pkg\\wheel\\{wheel}"; & "$venv\\Scripts\\onecrew.exe" --help
```

Bộ kiểm của gói **không** diễn tập việc 2.3.0.dev10 đọc sổ do bản này ghi (xem mục 4); test `tests/test_v24_s1_oldreaders.py` của nhánh diễn tập 2.2.0.dev18 và 2.3.0.dev10 đọc sổ có bản ghi support của S1 (chưa có bản ghi S2). Hồi quy bộ kiểm chạy là quay về 2.2 rồi lên lại (bước V7 và V16 của 2.3). Trước khi quay về với sổ thật, chạy `compat scan` trên bản sao sổ.

## 4. Giới hạn

{limits}
'''


MILESTONE_TRY = {
    'S1': ('- **2.4-S1, báo lỗi một lần:** hướng dẫn đầy đủ ở `docs/HUONG-DAN-SUPPORT.vi.md`. Trên bản sao project, sau khi cài ở mục 2:\n'
           '  - `& "$venv\\Scripts\\onecrew.exe" --project <project> --state-root <sổ thử> support report --text "Bước kiểm M1 báo sai dù file đúng" --key k1 --json` in một mã `FB-…`; chạy lại với cùng `--key` trả đúng mã đó.\n'
           '  - `support show FB-… --json` và `support status FB-… --json`: báo cáo chưa phải lỗi đã tái hiện (`reported`, cột tái hiện `unknown`).\n'
           '  - `support bundle FB-… --out <thư mục ngoài sổ>` ghi `manifest.json` và hồ sơ chẩn đoán trên máy bạn; không tải gì lên đâu cả. Đọc file trước khi gửi cho ai.\n'
           '  - Khi sổ hỏng: `& "$venv\\Scripts\\python.exe" -I -m onecrew.v2.support_spool --project <project> --state-root <sổ> report --text "…" --json` ghi vào `support-spool\\`; sửa sổ xong chạy `support import-spool`.\n'
           '  - `support confirm` là lệnh của riêng chủ dự án, bị từ chối trong phiên AI.\n'
           '  - Bộ kiểm chạy đúng các lệnh này từ gói (bước V17–V19), nên có thể làm theo log của nó.'),
    'S2': ('- **2.4-S2, bản vá OneCrew từ báo cáo tới tiếp tục việc cũ:** hướng dẫn ở `docs/HUONG-DAN-SUPPORT.vi.md` mục 5. Chỉ trên bản sao project và sổ thử, sau khi cài ở mục 2:\n'
           '  - Chủ dự án khai báo đích cài, trong terminal riêng (lệnh bị từ chối trong phiên AI): `& "$venv\\Scripts\\onecrew.exe" --project <project> --state-root <sổ thử> support target add --id lab --venv <venv thử>`.\n'
           '  - Báo cáo được phân loại `onecrew_runtime` và nối với plan sửa của project OneCrew (`support classify`, `support link FB-… --plan FIX1 --project-id <id>`); plan sửa đã duyệt phải ghi `authority.granted_actions: ["support_install:lab"]`.\n'
           '  - `support artifact FB-… --wheel <file.whl> --manifest <manifest.json>`: wheel phải chứa đúng các file của commit đã kiểm của plan sửa; một file lạ là bị từ chối.\n'
           '  - `support install FB-… --target lab`: venv mới cạnh venv cũ, diễn tập trên bản sao, chuyển hook chỉ tại điểm an toàn. Không có quyền thì kết quả là `blocked_by_authority`, không phải đạt.\n'
           '  - `support recheck FB-…` chạy lại đúng check gốc bằng runtime mới; `support status FB-… --json` nói `installed` và `verified_at_target` theo hook đang chạy lúc này.\n'
           '  - `support rollback FB-…` là lệnh của chủ (bị từ chối trong phiên AI); sau đó trạng thái là `installed: false`, `rolled_back: true`, còn bị chặn.\n'
           '  - Bộ kiểm chạy chuỗi này từ gói trên một repo OneCrew dựng tạm từ chính wheel của gói (bước V20–V22), nên có thể làm theo log của nó.\n'
           '  - Bước V27: venv của lần cài bị sửa một file (diagnostics.py, RECORD giữ nguyên) thì `support install` và `support recheck` đều bị từ chối, hook và file không đổi; trả file về thì dùng lại được.\n'
           '  - Bước V28: `support rollback` dừng sau diễn tập (`ONECREW_SUPPORT_CRASH=rollback_after_drill`), ghi một sự kiện vào sổ thật, chạy lại: chỉ rolled_back sau khi diễn tập lại dữ liệu có sự kiện đó.'),
    'A': ('- **2.4-A, worker tự đọc nguồn theo quyền:** hướng dẫn ở `docs/HUONG-DAN-SOURCE.vi.md`. Trên bản sao project:\n'
          '  - Root khai `authority.read` (ví dụ `["src/**"]`) trong hợp đồng; node khai `sources` `{"read": ["src/"], "max_rounds": 4}` trong plan nội bộ.\n'
          '  - Worker xin `list`/`search`/`read`/`page` kèm `continuation`; lượt sau nhận trang kết quả trên cùng cây đã ghim. Receipt có `source` (cây, kết quả, số lượt).\n'
          '  - Ngoài phạm vi, `..`, tên bí mật bị từ chối; cursor của cây khác bị từ chối; quá `max_rounds` thì node bị giữ `rounds_exhausted`.\n'
          '  - Node không khai `sources` chạy y như 2.3.\n'
          '  - Bộ kiểm chạy đúng các trường hợp này từ gói (bước V23).'),
    'B': ('- **2.4-B, working context theo consumer:** hướng dẫn ở `docs/HUONG-DAN-CONTEXT.vi.md`.\n'
          '  - Mỗi attempt được giao tri thức có một sự kiện `knowledge.delivered`.\n'
          '  - Tri thức đã giao bị thu hồi lúc node đang chạy thì candidate không được công bố; node chạy tiếp ở thế hệ mới nhận `delta`.\n'
          '  - `& "$venv\\Scripts\\onecrew.exe" --project <project> --state-root <sổ thử> wiki consumers --plan <plan> --json` liệt kê node bị ảnh hưởng (chỉ đọc).\n'
          '  - Bộ kiểm chạy đúng trường hợp này từ gói, cả qua một lần khởi động lại (bước V24).\n'
          '  - Bước V26: chuỗi 6 node A→F chỉ A nhận quy tắc bắt buộc; rút quy tắc thì `wiki consumers` nêu F là `input_changed`, `engine verify <plan> F` bị từ chối (F bị giữ, không gọi model, không đặt lại ngân sách), node X độc lập vẫn được kiểm.'),
    'C': ('- **2.4-C, bước 0 đủ để làm và cách chạy node:** hướng dẫn ở `docs/HUONG-DAN-BUOC-0.vi.md`.\n'
          '  - `plan proposal check <plan> --file <f.json>` với `preserve`, `estimate`, `investigation`; `plan step0 show <plan> [--json]` nói đủ để làm chưa và vì sao.\n'
          '  - Khảo sát vượt trần điều tra bị từ chối; unknown đổi được quyết định chỉ đóng khi có bằng chứng (`plan unknown close`).\n'
          '  - Root khai capability `execution-mode`: `node.started` ghi chế độ chạy và lý do; `engine batch <plan> --slots 2`; `engine measure <plan>` chỉ đọc, thiếu quan sát là `unknown`.\n'
          '  - Bộ kiểm chạy đúng các trường hợp này từ gói (bước V25).'),
}
TRY_REGRESSION = ('- **Hồi quy 2.3, task đầu tiên:** làm theo `examples/first-task/README.vi.md`. Thư mục đó có trang wiki mẫu `docs/wiki/rules.md`, hợp đồng `contract.json`, định nghĩa node `nodes.json`, '
                  '`fake-policy.json`, các lệnh `onecrew` cụ thể và đường dẫn nằm trong gói. Phần A diễn tập với `claude` giả (không gọi model); phần B dùng Claude Code CLI thật '
                  '(điều kiện ở mục 6B của file đó). Bước duyệt plan là việc của chủ sở hữu, trong terminal riêng; AI không duyệt thay.\n'
                  '- Diễn tập tự động phần A từ chính gói, trên một thư mục trống: `& $py -I "$pkg\\verify\\first_task_drill.py" $pkg "D:\\OneCrewRuns\\v24 task dau tien drill"`, '
                  'rồi đọc `first-task-drill-log.json` trong thư mục đó (`result: pass`). Nó chạy các khối PowerShell của README nên chứng minh các lệnh trong đó chạy được; '
                  'không chứng minh phần B (model thật) và không chứng minh model hiểu wiki.\n'
                  '- Cách viết wiki, lệnh `onecrew wiki pages|show|read`, cách đọc receipt: `docs/HUONG-DAN-WIKI.vi.md` §1–5 (bản gốc 2.3 ở `docs/v23/`).')


def included_for(milestone):
    return list(ORDER) if milestone == 'FINAL' else ORDER[:ORDER.index(milestone) + 1]


def steps_text(verifier, included):
    lines = []
    total = REGRESSION_STEPS
    for m in included:
        for sid, title, _ in verifier.MILESTONE_STEPS.get(m, []):
            lines.append(f'{sid} ({m}) {title}')
            total += 1
    text = (f'Bộ kiểm chạy {total} bước từ chính gói: V1–V{REGRESSION_STEPS} là hồi quy 2.3 (danh tính, cài vào venv mới, nguồn module, task đầu tiên, phản chứng, '
            f'console cp1252, quay về 2.2 rồi lên lại, hai root, tiếp quản, ràng buộc bắt buộc, tri thức general, trùng khóa, verifier tài liệu, init wiki, việc cũ chạy tiếp)')
    if lines: text += ', rồi các bước của mốc 2.4 có trong gói: ' + '; '.join(lines)
    return text + '.', total


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('out'); parser.add_argument('--milestone', required=True, choices=sorted(MILESTONES))
    parser.add_argument('--previous-wheel', default=DEFAULT_PREVIOUS[0]); parser.add_argument('--previous-sha', default=DEFAULT_PREVIOUS[1])
    parser.add_argument('--regression-wheel', default=DEFAULT_REGRESSION[0]); parser.add_argument('--regression-sha', default=DEFAULT_REGRESSION[1])
    parser.add_argument('--limits', required=True, help='a Markdown file with the limits section')
    parser.add_argument('--stage', default='', choices=['', 'alpha', 'beta'], help='the prerelease stage named in the README and the manifest')
    args = parser.parse_args()
    out = Path(args.out)
    if out.exists(): raise SystemExit(f'{out} exists; a package folder is never reused.')
    dirty = git('status', '--porcelain', '--', *CODE_PATHS)
    if dirty: raise SystemExit('code or documents tree is dirty; commit first:\n' + dirty)
    previous, regression = Path(args.previous_wheel), Path(args.regression_wheel)
    if sha(previous) != args.previous_sha: raise SystemExit('previous wheel sha256 differs from --previous-sha')
    if sha(regression) != args.regression_sha: raise SystemExit('regression wheel sha256 differs from --regression-sha')
    included = included_for(args.milestone)
    verifier = load_verifier()
    missing = [m for m in included if not verifier.MILESTONE_STEPS.get(m) or m not in MILESTONE_TRY]
    if missing:
        raise SystemExit(f'milestone(s) {", ".join(missing)} have no verifier steps (verify_milestone.MILESTONE_STEPS) or no "Thử nhanh" text '
                         f'(build_milestone.MILESTONE_TRY): add them before a package may claim the milestone.')
    stage_text, expected = steps_text(verifier, included)
    commit = git('rev-parse', 'HEAD')
    branch = git('rev-parse', '--abbrev-ref', 'HEAD')
    import re
    shipped = re.findall(r'"([\w.]+)"', re.search(r'py-modules\s*=\s*\[(.*?)\]', (ROOT / 'pyproject.toml').read_text(encoding='utf-8'), re.S).group(1))
    ships_paging = 'onecrew.paging' in shipped           # what the wheel really ships (the verifier checks it against the wheel)
    temp = Path(wh._runs())
    try:
        wheel, _, _ = wh.build_wheel(temp)
        (out / 'wheel' / 'previous').mkdir(parents=True)
        (out / 'wheel' / 'regression').mkdir()
        shutil.copy2(wheel, out / 'wheel' / Path(wheel).name)
        shutil.copy2(previous, out / 'wheel' / 'previous' / previous.name)
        shutil.copy2(regression, out / 'wheel' / 'regression' / regression.name)
    finally:
        shutil.rmtree(temp, ignore_errors=True)
    wheel_path = out / 'wheel' / Path(wheel).name
    version = Path(wheel).name.split('-')[1]
    verify = out / 'verify'; verify.mkdir()
    shutil.copy2(ROOT / 'docs/v24/tools/verify_milestone.py', verify / 'verify_milestone.py')
    for name in SCENARIOS: shutil.copy2(ROOT / 'docs/v23/tools' / name, verify / name)         # the 2.3 scenarios, unchanged (V4-V14)
    shutil.copy2(ROOT / 'tests/v23_fake_claude.py', verify / 'onecrew_fake_claude.py')
    shutil.copy2(ROOT / 'tests/v24_fake_claude.py', verify / 'onecrew_fake_claude_v24.py')     # 2.4-A V23: the fake that reads by request
    for name in SHARED_TOOLS: shutil.copy2(ROOT / 'docs/v23/tools' / name, verify / name)
    shutil.copy2(ROOT / 'docs/v24/tools/thu_goi.ps1', verify / 'thu-goi.ps1')      # the owner's one-command test: runs the verifier, the drill and the alpha flow and accepts only reports of THIS run
    docs = out / 'docs'; docs.mkdir()
    for path in sorted((ROOT / 'docs/v24').glob('*.md')): shutil.copy2(path, docs / path.name)
    shutil.copy2(ROOT / 'docs/CHANGELOG.md', docs / 'CHANGELOG.md')
    history = docs / 'v23'; history.mkdir()
    for path in sorted((ROOT / 'docs/v23').glob('*.md')): shutil.copy2(path, history / path.name)
    shutil.copy2(ROOT / 'docs/v23/HUONG-DAN-WIKI.vi.md', docs / 'HUONG-DAN-WIKI.vi.md')       # examples/first-task/README.vi.md links ../../docs/HUONG-DAN-WIKI.vi.md (the drill lints it)
    if (ROOT / 'docs/v23/evidence').is_dir(): shutil.copytree(ROOT / 'docs/v23/evidence', history / 'evidence')
    for source in (ROOT / 'docs/v23/examples', ROOT / 'docs/v24/examples'):
        if source.is_dir(): shutil.copytree(source, out / 'examples', dirs_exist_ok=True)
    built = time.strftime('%Y-%m-%d %H:%M:%S')
    tries = [MILESTONE_TRY[m] for m in included] + [TRY_REGRESSION]
    readme = README.format(stage=(args.stage + ' ') if args.stage else '', version=version, label=args.milestone + ': ' + MILESTONES[args.milestone], commit=commit, branch=branch,
                           included=', '.join(f'`{m}`' for m in included), wheel=wheel_path.name, wheel_sha=sha(wheel_path),
                           previous=previous.name, previous_sha=args.previous_sha, regression=regression.name, regression_sha=args.regression_sha,
                           built=built, out=str(out.resolve()), tag=f'{args.milestone.lower()} {version}', steps_text=stage_text,
                           try_text='\n'.join(tries), limits=Path(args.limits).read_text(encoding='utf-8').strip())
    (out / 'README.md').write_text(readme, encoding='utf-8')
    manifest = {'kind': 'v24-milestone-package', 'milestone': args.milestone, 'label': MILESTONES[args.milestone], 'milestones_included': included,
                'version': version, 'code_commit': commit, 'branch': branch, 'built_at': built, 'ships_paging': ships_paging, 'stage': args.stage or None,
                'expected_steps': expected,
                'wheel': {'name': wheel_path.name, 'sha256': sha(wheel_path)},
                'previous_wheel': {'name': previous.name, 'sha256': args.previous_sha, 'version': previous.name.split('-')[1]},
                'regression_wheel': {'name': regression.name, 'sha256': args.regression_sha, 'version': regression.name.split('-')[1]},
                'claims': {'delivered': False, 'reviewed_by_codex': False, 'accepted_by_owner': False, 'released': False}}
    (out / 'manifest.json').write_text(json.dumps(manifest, indent=1, ensure_ascii=False), encoding='utf-8')
    lines = [f'{sha(p)}  {p.relative_to(out).as_posix()}' for p in sorted(out.rglob('*')) if p.is_file()]
    (out / 'SHA256SUMS').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(json.dumps({'out': str(out), 'version': version, 'commit': commit, 'milestones_included': included, 'expected_steps': expected,
                      'wheel_sha256': manifest['wheel']['sha256'], 'files': len(lines) + 1}))


if __name__ == '__main__':
    main()
