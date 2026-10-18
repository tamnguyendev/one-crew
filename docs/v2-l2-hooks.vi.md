# v2 L2 — hook cho Claude Code (cưỡng bức khi làm)

Mục tiêu: AI làm trong Claude Code bị chặn ngay tại chỗ khi ra ngoài phạm vi của hợp đồng đã duyệt, và không tự nhận "xong" khi mốc chưa có verdict. Chỉ áp cho phiên có cài hook; phiên khác vẫn là "chưa kiểm soát".

## Chủ sở hữu bật (một lần cho mỗi project)

1. `onecrew --project P --state-root S plan enforce on --by owner --reference "..."` (cổng dispatch, đã có từ L1).
2. `onecrew ... hook install --print > hook-settings.json`, đọc rồi dán `hooks` và `permissions.deny` vào `.claude/settings.json` (OneCrew không tự sửa file settings nào).
3. Sau `plan approve`, file `<project>/.onecrew/active-plan.json` (và bản trong `<state-root>/plans/<tên>/`) được xuất. Mặc định `mode: log` (chỉ ghi, không chặn). Chuyển sang chặn: `onecrew ... hook mode enforce --by owner --reference "..." --plan <tên>`.

## Hook làm gì

| Lệnh | Sự kiện | Hành vi |
|---|---|---|
| `hook check` | PreToolUse (`Edit\|Write\|MultiEdit\|NotebookEdit\|Bash\|PowerShell`) | sửa file ngoài `owned` hoặc khớp `non_goals` (dạng đường dẫn), file của hook/sổ cái/`plans/`/sqlite, lệnh khớp `bash_deny` (push, tag, `rm -rf`, `pip install`, `plan approve/accept/enforce`, `verdict record --by owner`, `ONECREW_ACTOR`, `hook mode`), ghi file qua shell (`>`, `tee`, `Set-Content`, `Out-File`, `cp/mv`, `sed -i`) ra ngoài `owned` → exit 2 kèm luật và cách xin đổi (`plan amend`). Lỗi nội bộ: chặn ở `enforce`, cho qua ở `log`. File kế hoạch hỏng hoặc hết hạn: coi như `enforce`. |
| `hook prompt` | UserPromptSubmit | thấy từ khóa ("giờ", "skip", "bỏ test", ...) thì nhắc một dòng; không bao giờ chặn |
| `hook stop` | Stop | mốc hiện tại chưa có verdict pass → `decision: block`; tối đa 2 lần mỗi phiên rồi cho qua và ghi `stop_cap` |
| `hook session` | SessionStart | tóm tắt hợp đồng ≤ 25 dòng làm `additionalContext` |
| `hook sync` | (tay) | nhập `violations.jsonl` vào sổ cái: `hook.blocked|logged|reminded|stop_blocked` |
| `hook export P` / `hook mode` | (tay, owner) | xuất lại file / đổi `log`↔`enforce` |

Giới hạn thật: Bash không phải ranh giới bảo mật (hook đọc chữ của lệnh, không thấy script ghi gì); lớp cứng là `permissions.deny`. Xem `docs/v2-parking-lot.vi.md` (nhãn L2) cho phần chưa làm.

## Ngân sách theo mục và CREQ có hạn (cổng v2 bật)

- `Control.reserve` nhận `operation.item`: mục `wont` và `should` không được tick lúc duyệt không chạy; `should` không tiêu phần `repair_reserve` (20%); mỗi mục tối đa phần chia đều; mục `must` chạm trần → dừng mục, hỏi chủ sở hữu **một** câu (`v2.item_budget`, tính chung vào `attention.questions`); mục `should` chạm trần → dừng, chuyển mục kế.
- `solution_gate.question` loại `solution_change` cần `delta` (`add|drop|budget_delta`), `reason` ≤ 200 ký tự; yêu cầu thứ 3 bị từ chối và đặt plan vào `stopped_with_report`.

## Sau review Opus lần 1 (r2)

- Hook tìm kế hoạch ở hai nơi: `<project>/.onecrew/active-plan.json` và bản sao trong `<state-root>/plans/<tên>/` (cấu hình in ra có `--state-root`). Xóa `.onecrew/` không tắt cưỡng bức: hook khôi phục bản trong project từ state-root; bản trong project lệch bản state-root thì bị coi là bị sửa và chặn.
- `plan approve|accept|enforce`, `verdict record --by owner`, `hook mode` bị từ chối khi tiến trình có `CLAUDE_CODE_CHILD_SESSION` (Claude Code đặt cho shell của công cụ và hook; terminal IDE của chủ sở hữu chỉ có `CLAUDECODE`). Chủ sở hữu chạy các lệnh này ở terminal riêng.
- Verifier `command` chạy trên checkout bằng `git read-tree` + `checkout-index` (không `git archive`), với môi trường là danh sách cho phép (bỏ `PYTHON*`, `GIT_*` và mọi biến lạ).
- Trần Stop: 2 lần chặn mỗi lượt dừng; sau lần cho qua bộ đếm về 0.
- Giới hạn yêu cầu gửi chủ sở hữu (CREQ): mọi loại câu hỏi đều đếm vào trần 2 và đều cần `reason` ≤ 200 ký tự khi cổng bật.
