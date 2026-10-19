# Lõi v2 và gói cài đặt (OneCrew 2.2, bước G1)

**Một câu:** `pip install` một wheel là có lệnh `onecrew plan | verdict | hook` chạy được trên Windows và Linux, không cần checkout; phần v1 (job, work, delivery...) vẫn chạy từ checkout như trước.

## Lõi là gì (có trong wheel)

| Nhóm | Module | Làm gì |
|---|---|---|
| Sổ cái | `ledger`, `snapshots`, `specs` | SQLite, blob, hash; không đổi schema |
| Đọc ngân sách | `budget_core` | `local_current`, `current`, `remaining`, `group`, `shared`, `cancellation_status` (trước nằm trong `budget`, `goal_budget`, `delivery_store`) |
| Nhận việc | `task_intake`, `model_preferences`, `routing` | `submit` ghi dòng `tasks` + sự kiện `task.submitted`; v2 dùng nó tạo task neo của plan (chỉ chế độ `audit`) |
| Độc lập reviewer | `independence` | `NATIVE_REVIEWERS`, `independence()` (trước nằm trong `qc_gate`) |
| Hợp đồng/kiểm | `work_contract`, `qc_intake` | `argv_value`, `git`, `locate`, `_commit` |
| v2 | `onecrew.v2.*` và `onecrew.v2.verifiers.*` | plan, gate, hook, verdict, report, lint, step0, `claude_cli` (tìm Claude CLI + model mặc định), `cli` (router) |

Danh sách đúng nằm ở `[tool.setuptools] py-modules` trong `pyproject.toml`. `tests/test_g1_core.py` kiểm: mọi import (kể cả import lười trong hàm) của module trong danh sách đều trỏ vào danh sách; không module v1-only nào lọt vào; mỗi module import được riêng trong một thư mục chỉ có chúng.

## v1-only là gì (không có trong wheel)

Mọi module còn lại của `onecrew/`: `workflow`, `owned*`, `delivery*`, `solution_*`, `native_*`, `android_*`, `runner`, `supervisor`, `host`, `qc_gate`, `learning`, `budget`, `goal_budget`, `cli` (router đầy đủ)... Chúng import lõi, lõi **không** import chúng. Việc dời từ v1 sang lõi: v1 `import` lại tên từ lõi (một nguồn, không chép): `budget`/`goal_budget`/`delivery_store` ← `budget_core`; `qc_gate` ← `independence`; `learning.outcomes` và `budget_policy.recommend`/hằng mặc định ← `task_intake`; `owned_intake.submit` = `task_intake.submit` kèm phần mở rộng v1 (hợp đồng work, native/QC/Android, delivery con, gắn solution). `onecrew/v2/changes.py` (móc của cổng v2 vào luồng solution của v1) đổi chỗ thành `onecrew/solution_changes.py`.

## Lệnh `onecrew` của wheel

`onecrew = onecrew.v2.cli:main`: chỉ ba nhóm `plan`, `verdict`, `hook`; nhóm khác báo lỗi và chỉ về `onecrew_cli.py`. Checkout giữ router đầy đủ (`onecrew/cli.py`), dùng chung hàm `route` của `onecrew/v2/cli.py` cho ba nhóm v2.

## Tìm Claude CLI và model mặc định

`onecrew/v2/claude_cli.py` là chỗ duy nhất:
- `cli_argv`: `shutil.which('claude')` trên PATH của môi trường lọc; không thấy thì thử theo hệ điều hành — Windows: `~\.local\bin\claude.exe`, `~\.claude\local\claude.exe`, `%APPDATA%\npm\claude.cmd|exe` (và `NPM_CONFIG_PREFIX`); Linux/macOS: `~/.local/bin/claude`, `~/.claude/local/claude`, `$NPM_CONFIG_PREFIX/bin/claude`, `~/.npm-global/bin/claude`, `/usr/local/bin`, `/opt/homebrew/bin`, `/usr/bin`. Lỗi liệt kê mọi nơi đã tìm.
- `DEFAULT_MODEL = 'claude-opus-5-5'`, ghi đè bằng biến môi trường `ONECREW_DEFAULT_MODEL`. `plan advise` (không có `--model`) và `advisor.advise` dùng nó. Model của reviewer mỗi mốc vẫn do hợp đồng ghi rõ.

## Build wheel

Tại thư mục gốc của checkout (cần mạng để pip lấy `setuptools`):

```bash
python -m pip wheel --no-deps -w dist .
python -m venv /tmp/v && /tmp/v/bin/pip install dist/onecrew-2.2.0.dev0-py3-none-any.whl
/tmp/v/bin/onecrew --help
```

Phiên bản hiện là `2.2.0.dev0` (chưa phải số phát hành). Chưa có CI, PyPI, `onecrew init`/`doctor` (các bước G2–G3).

## Chạy v1 từ checkout

```bash
python onecrew_cli.py --project <repo> job submit ...     # hoặc: python -m onecrew ...
```

`onecrew_cli.py` giữ router đầy đủ v1 + v2. Lệnh `onecrew-entry-mcp` không còn trong wheel; chạy `python -m onecrew.mcp_entry` từ checkout.

## Còn lại cho G2

- `plan rules init` đọc `examples/owner-rules.vi.md` cạnh checkout; trong bản cài từ wheel mẫu này không có (đưa vào wheel là việc G2).
- `hook install --print` còn ghi đường dẫn tuyệt đối của checkout.
