# RP — release notes (development, chưa giao)

Commit: `6366137`. Bản giao trước gần nhất theo chương trình: R00 (song song M1) — **chưa có bản giao thật nào được ghi nhận** (release_check không suy ra từ d3120c6).

## Usable outcomes

Những gì bản dựng này làm được, theo task của release (rút gọn từ 04; trạng thái lấy từ registry):

- **W43** — Reviewer và cố vấn theo nhà cung cấp (P1.0): hợp đồng khai provider (claude, codex, kiro) kèm model; mỗi provider là một lệnh CLI chỉ đọc; … _(testcase: T40a complete, T40b blocked)_
- **W45** — Kiểm thật ma trận provider (R3): chạy mỗi ô của ma trận provider × vai trò (claude, codex, kiro × reviewer, cố vấn) một lần bằng CLI thật … _(testcase: T40b blocked)_

## Limits

- Trạng thái `partial` = có kiểm hồi quy nhưng ma trận acceptance đầy đủ của testcase chưa được chứng nhận riêng; `blocked` = cần provider thật, pilot hay chủ sở hữu.
- Mọi test provider dùng CLI giả; không lời gọi provider trả phí nào được thực hiện trong development. Dạng lệnh thật của codex/kiro CHƯA KIỂM CHỨNG (W45/T40b).
- Không hứa exactly-once cho tác động ngoài; không hoàn tác tác động ngoài đã xảy ra (HD-26).
- Chưa có nghiệm thu của chủ sở hữu; không có pilot thật (PL-A/PL-B).
- Sáu ô provider × vai trò chỉ có bằng CLI giả; bundle RP cần provider_bundle thật (PV1/PV2).

## Install

- Wheel một lần từ commit sạch: `python -m build` (gate development dựng và ghi sha256 trong `build.json`); cài vào venv offline; `onecrew --version`/`control` từ checkout bị từ chối (kiểm bản cài của gate).
- Kiểm bản cài: các check `installed: true` của registry tiêu thụ đúng wheel đó (`wheel_used`).
- Hook OneCrew cho Claude Code: `onecrew hook install` theo docs; không bật heartbeat chat.

## Rollback

- Trước khi rollback về R00 (song song M1): chạy `onecrew compat scan` (W46) trên bản sao sổ; chỉ rollback khi 0 điều kiện chặn (B1–B4); sự kiện lớp A của release này bị bản cũ bỏ qua im lặng, sự kiện lớp B chỉ nằm trên root `plan-ns:` mà bản cũ không thấy.
- Diễn tập: `python -m wfkit.upgrade_drill` (sinh fixture bản cài, không dùng sổ thật). Rollback không tua lùi sổ (không xoá/sửa sự kiện).
- Roll-forward: reconcile intent chưa rõ (`verdict status` → `held`, `verdict release-run` là quyết định ghi lại) trước khi root tiếp tục.

## Evidence status

- Registry RP: complete 1, partial 2, blocked 1 (`python -m wfkit.development_gate list`).
- Gate development trên một wheel: gate 6366137: 213/213 check implementation đạt, 0 skip (1 716 lượt test cộng dồn, 1 351 test id); refused chỉ vì acceptance-partial 49 + acceptance-blocked 10.
- Bundle T54 thật (`wfkit.release_bundle`, kết quả `release_check`: **refused**; bundle `C:\Users\NUC\AppData\Local\Temp\wf-bundles-6366137-rp\RP\bundle.json`):
  - INPUTS — lịch sử cổng giao của bản trước: không đạt — previous delivered gate history missing
  - T54.1 — kịch bản chạy từ bản cài: đạt (biên nhận thật)
  - T54.2 — nâng cấp giữ ID/ngân sách/evidence/attempt: đạt (biên nhận thật)
  - T54.3 — lớp sự kiện, S/G/C bản cũ: đạt (biên nhận thật)
  - T54.4 — rollback từ chối/cho phép, roll-forward: đạt (biên nhận thật)
  - T54.5 — ghi chú bốn trạng thái: đạt (biên nhận thật)
  - Bản trước trong bundle là d3120c6 (baseline mà `compat scan` mô hình), KHÔNG phải bản đã giao: chưa có release nào của chương trình được giao, nên điều kiện INPUTS chỉ có thể đạt sau khi chủ sở hữu giao một release (điều kiện ngoài).
- Không ghi "đã giao", "Codex đã review" hay "chủ sở hữu đã nghiệm thu".

Bốn trạng thái bằng chứng (định dạng của `release_check` T54.5, mỗi dòng một trạng thái):

Code: present
Fixture checks: passed
Real checks: not-run
Acceptance: not-requested
