# CHANGELOG

## v2.2.0.dev0 (G1: lõi v2 cài được bằng pip)

- Wheel chỉ gồm lõi + `onecrew.v2` + `onecrew.v2.verifiers` (danh sách `py-modules` trong `pyproject.toml`); lệnh `onecrew` của wheel là router v2 (`plan`, `verdict`, `hook`), `onecrew_cli.py` ở checkout vẫn là router đầy đủ v1 + v2. Chi tiết: `docs/v2-core.vi.md`.
- Tách lõi khỏi v1 bằng cách dời phần dùng chung (một nguồn; v1 import lại): `budget_core` (đọc ngân sách), `independence`, `task_intake` (`submit` của task neo, `outcomes`, `recommend`), `onecrew/v2/changes.py` → `onecrew/solution_changes.py`. Sổ cái, loại và payload sự kiện không đổi; sổ cũ đọc y nguyên.
- Tìm Claude CLI theo hệ điều hành (PATH, rồi `~/.local/bin`, npm global...), lỗi nêu mọi nơi đã tìm; model mặc định (Opus 5.5) ở một module (`onecrew/v2/claude_cli.py`), ghi đè bằng `ONECREW_DEFAULT_MODEL`.
- `tests/test_g1_core.py`: closure import, tìm CLI (posix/nt giả lập), metadata đóng gói, model mặc định.
- Không còn trong wheel: `onecrew-entry-mcp` (chạy từ checkout).

## v2.1.0 (20/10/2026) có gì

v2 = **hợp đồng công việc cho AI**: AI chỉ chạy trong một hợp đồng đã được chủ sở hữu duyệt. Sáu bất biến cứng: không có hợp đồng đã duyệt thì không chạy; ngoài phạm vi thì bị chặn; hết ngân sách thì dừng; mốc chưa có verdict thì không qua; tác giả không tự duyệt việc của mình; chỉ con người mới nghiệm thu.

Phần lõi v2 (lát L1–L2, item 3, item 4):
- Sổ cái (ledger) ghi biên lai và verdict cho từng mốc (L1).
- Hook cho Claude Code: PreToolUse, UserPromptSubmit, Stop; `hook install --print` in cấu hình (L2).
- Verifier `command`: chạy lệnh kiểm trên checkout sạch (L1).
- Verifier `reviewer`: model độc lập duyệt diff theo 3 tiêu chí (item 3).
- Mốc `owner-manual`: chủ sở hữu tự đọc và nghiệm thu (L1).
- `plan report` (kết luận tiếng Việt 4 dòng + 7 mục) và `plan digest` (item 4).

v2.1 bổ sung:
- Job 9: trường `origin`, `decisions`, `items[].source`, trường trình bày; cổng `approve` chặt khi có `<state-root>/plans/owner-rules.md`; `plan advise` (cố vấn Opus, 3 câu hỏi cố định so với file quy tắc; bắt buộc khi `decisions` không rỗng hoặc cỡ M/L); `plan rules init|show`.
- Job 11a: `plan lint`; verifier `command` fail-closed (đầu ra rỗng, chạy nhanh mà im lặng, ký tự điều khiển, thiếu file thực thi → `inconclusive`); hook Stop nhả khi có biên lai chưa verdict hoặc câu hỏi chủ sở hữu đang mở; `amend` sau khi duyệt chỉ đóng băng lại các mốc bị đổi.

Bằng chứng: 14 job thật trong `state-v2-real` (11 đã nghiệm thu), khoảng 290 test.

## Giới hạn đã biết

- Hook Stop chỉ thấy biên lai sau khi lệnh chạy xong; cần sự kiện "bắt đầu chạy" — **dự kiến 11b**.
- `contract.validate` vẫn nhận ký tự điều khiển trong `argv`; chỉ `plan lint` và verifier bắt được.
- Mốc `command` im lặng luôn `inconclusive` dù đạt: lệnh kiểm phải in kết quả.
- Verifier `command` của Flutter không giải được path dependency anh em trên checkout sạch; chạy kiểm trong worktree (như `run_flutter_checks.py`).
- Tỉ lệ bắt lỗi của cố vấn chưa được đo.
- Quy tắc R1 trong `examples/owner-rules.vi.md` ghi sai ("debug cho chạy thử"); đúng: build debug khi đang phát triển, chỉ release khi đã xong, test đạt và chủ sở hữu đã thử trên thiết bị — **dự kiến sửa ở 11b**.
- Hook chỉ đọc chữ của lệnh; script Python dựng lệnh bằng ghép chuỗi vẫn qua lớp hook (xem `docs/v2-parking-lot.vi.md`).
- Reviewer: mỗi lần gọi tốn khoảng 9k token cache; diff quá 120 KB không được review (`inconclusive`); chưa kiểm `evidence.file` có nằm trong diff.
- `plan report` chưa đếm số lệnh/token, chưa có HTML.
- Một số test v1 đỏ sẵn có (ví dụ `test_sandbox_gate` khi đường dẫn worktree dài); không do v2.

## Cách chạy

CLI (từ thư mục repo):

```
<python> -X utf8 onecrew_cli.py --project <repo> --state-root <state-root> plan|verdict|hook ...
```

- Hook: `hook install --print` in cấu hình, dán vào `.claude/settings.json` của project.
- Chạy verifier: `verdict run --plan <tên> --milestone <Mx>`.
- Báo cáo: `plan report`, `plan digest`.
- Các động từ của chủ sở hữu (`approve`, `accept`, `enforce`, `verdict record --by owner`) chỉ gõ từ terminal của chính chủ sở hữu, không từ phiên AI.
- Sổ cái và hợp đồng nằm trong `<state-root>` (`ledger.sqlite3`, `plans/`, `policy.json`); `.onecrew/active-plan.json` trong project là bản xuất để hook đọc.
