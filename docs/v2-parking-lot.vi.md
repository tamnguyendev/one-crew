# Bãi đỗ v2 — phát hiện ngoài phạm vi L1 (không tự làm)

Một dòng mỗi mục; `L#` là lát dự kiến.

- L2: AI có shell gõ được `--by owner` (chỉ bị chặn khi `ONECREW_ACTOR` khai là AI); cần hook PreToolUse + permission deny cho `plans/`, `ledger.sqlite3`, `policy.json`.
- L2: AI sửa trực tiếp file trong `<state-root>/plans/` hoặc sqlite: file bị phát hiện qua hash khi đọc, sqlite thì không; cần quyền ghi.
- L2: `policy.json` do shell bất kỳ ghi được (tắt cổng); `plan enforce off` chỉ là lệnh owner, không phải khóa cứng.
- L2: ngân sách theo mục và `attention` theo loại ở lớp ledger; L1 chỉ đếm câu hỏi `v2.plan_stopped` của chính plan.
- L2: `budget.max_calls/time` trong hợp đồng mới chỉ được lưu; chưa nối với `control.reserve`.
- L2: `should` đã tick/chưa tick chỉ ghi và hiển thị (`runs`); chưa có gì chặn việc ngoài `must` + `should` đã tick.
- L2: `scope.owned`, `non_goals` chưa được cưỡng bức (cửa nhận `qc_intake.scope_check` chưa nối).
- L1.1: `plan_cli` chưa có lệnh `plan list`; xem danh sách bằng `task list` (task neo `plan:*` lẫn với job thường).
- L1.1: tên plan trùng giữa hai project dùng chung state-root: thư mục `plans/<tên>` không có project id; cổng kiểm `project_id` qua task neo nhưng file thì dùng chung tên.
- L1.1: ghi verdict rồi mới tạo câu hỏi là hai giao dịch (create_request mở giao dịch riêng); sập giữa chừng thì plan đã `stopped_with_report` nhưng chưa có câu hỏi (khóa idempotent `v2q-…`, chạy lại verdict bị từ chối); cần lệnh `plan ask` hoặc gộp giao dịch.
- L1.1: `until_pass` và `once` hiện cùng trần `max_repairs`; khác biệt chỉ xuất hiện khi có ngân sách theo mục.
- L1.1: `inconclusive` tính là một lần chạy hỏng (tránh vòng lặp không trần); có thể cần trần riêng cho lỗi môi trường.
- L1.1: amend làm mất hiệu lực mọi verdict cũ (verdict gắn revision); amend nhỏ buộc chạy lại mọi mốc.
- L1.1: sha artifact = cây Git của working tree (đã trừ .gitignore); chỉ hợp cho dự án Git; artifact không phải mã (APK, PR) chờ verifier L4+.
- L1.1: `accept` chỉ buộc mốc cuối vào đúng artifact được nghiệm thu; các mốc trước có thể đã kiểm trên artifact khác.
- L1.1: cổng dispatch ghi từ chối vào `plans/refusals.jsonl` (không thể ghi sqlite trong giao dịch sắp rollback); sự kiện `dispatch.refused_no_plan` xuất hiện sau lần chạy lệnh `plan`/`verdict` kế tiếp.
- L3: `understanding` mới là văn bản tự do; chưa có echo cơ học, tiền kiểm, PoC, brainstorm.
- L4: tác giả/reviewer: `--author` ở propose chỉ ghi, chưa có kiểm "reviewer khác tác giả"; verdict từ reviewer LLM chưa có.
