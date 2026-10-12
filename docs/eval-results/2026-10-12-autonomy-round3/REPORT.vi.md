# Vòng 3 — sửa ba phát hiện Codex review đợt 2 (12/10/2026)

Nguồn: `D:\TamNT\Workspace\9.VMAgent\REVIEW-CODEX-ONECREW-ROUND2-742a139-2026-10-12.txt` (review trên `742a139`).
Nhánh `claude/delivery-runtime-recovery`, commit cục bộ, **chưa push, chưa tag**.

| Commit | Nội dung |
|---|---|
| `742a139` | (đã push trước đó, chưa được Codex duyệt) chế độ thiết bị thật: selector exact, bằng chứng đã che, phục hồi theo quyền |
| `b19b35e` | Sửa P1-1, P1-2, P2 + regression `tests/test_codex_review_round2.py` + đính chính tài liệu |
| `67e2365` | Harness: 4 case eval (`calibration-equivalence`, `emulator-identity`, `emulator-ownership`, `device-exact-mode`), corpus 46/163 |

## Phát hiện → sửa → bằng chứng

**P1-1 Hiệu chỉnh làm yếu assertion.** `delivery_calibrate.equivalence()`: mọi bước bị đổi (bước trượt, bước sau, cleanup)
chỉ được đổi *cách định vị*. Nhãn mong đợi giữ nguyên văn (chuyển giữa text/content-desc/hint hoặc là một phần nguyên vẹn
của nhãn gộp); `class`/`resource-id` được đổi; `checked` giữ mọi bước, `focused` giữ ở bước kiểm tra; `assert_absent` không
bao giờ đổi; selector không có nhãn không được trỏ lại. Probe Codex: trên `742a139` cả hai ví dụ `findings=[]`; sau sửa bị từ chối
(`condition checked='true' must stay exactly`; `an absence check is never recalibrated`).

**P1-2 Không xác minh AVD.** `delivery_android.verify()` đọc `adb emu avd name` + `boot_id` trước mọi thao tác thay đổi emulator
(trong `prepare`, trước khởi động lại, trước khi tắt). Sai AVD / không đọc được → không cài, không nhập, không tắt; lỗi
`permission`. Probe Codex: trên `742a139` `identity_queried=false, kill_sent=true, passed=true`; sau sửa `identity_queried=true,
kill_sent=false, install_sent=false, input_sent=false`, lỗi "is AVD OtherUserAVD, not the approved AVD ApprovedTrial".

**P2 Mất quyền sở hữu qua retry.** Bản ghi bền `emulator-<serial>.json` (AVD + `boot_id`) trong thư mục task khi OneCrew boot;
sống qua lần thử và khởi động lại coordinator. Chỉ instance trùng bản ghi (`owned`) mới được khởi động lại/tắt; instance người dùng
mở (kể cả đúng AVD) hoặc bị thay thế là `borrowed`. Receipt ghi `environment.emulator_cleanup` riêng; dọn thất bại thành gap bàn giao.

## Kiểm thử

- Regression `tests/test_codex_review_round2.py` (10 test) trên `742a139` (worktree tạm): **8 đỏ bằng assertion**
  (P1-1 ×4: bỏ checked, đổi assert_absent, bước sau + cleanup, locator không nhãn; P1-2 ×3; P2 ×1), 1 lỗi (trường
  `emulator_cleanup` chưa có), 1 guard đạt cả hai bên (đổi chỗ nhãn hợp lệ). Sau sửa: 10/10.
- Test cũ chỉnh theo ngữ nghĩa mới (không bỏ assertion): khởi động lại emulator khi crash nay cần instance do OneCrew boot; thêm biến thể
  `borrowed` không bị khởi động lại; ví dụ hiệu chỉnh dùng selector có nhãn (selector chỉ `resource-id` nay bị từ chối).
- Suite đầy đủ trên `b19b35e`: **878 test, 877 đạt**; 1 lỗi có sẵn (`test_incremental`, cần Codex CLI).
- **Eval cùng harness `67e2365`, repeat 2:**
  - Release: trước `742a139` → sau `b19b35e`: **86/92 → 92/92**, 0 regressed. Trước: 86 passed, 4 assertion_failed, 2 runtime_error;
    6 lượt `recovered` = đúng 3 case review (calibration-equivalence, emulator-identity: assertion_failed; emulator-ownership:
    runtime_error vì trường mới). `D:\OneCrewEvals\round3-20261012\compare.md`
  - Historical (case review so `742a139`; `device-exact-mode` so `62925f2`): calibration-equivalence 4 đỏ assertion + 1 guard;
    emulator-identity 3 đỏ assertion; emulator-ownership 1 đỏ assertion + 1 runtime_error; device-exact-mode capability_unavailable
    (năng lực mới của `742a139`). `D:\OneCrewEvals\round3-20261012\historical\`

## Phạm vi chưa kiểm chứng

- Không chạy trial live mới; các trial 4–7 chạy trên runtime trước sửa.
- Kiểm tra live duy nhất (emulator sandbox `OneCrew_CloudAuth_Fresh`, không phải A54): `adb emu avd name` trả
  the AVD name then a line `OK` (with CR characters), `boot_id` trả một UUID; `parse_avd_name`/`parse_boot_id` đọc đúng cả hai. Đây là kiểm định
  dạng lệnh, không phải chạy stage thiết bị qua OneCrew.
- `742a139` (chế độ thiết bị thật) chưa được Codex duyệt; chưa chạy trên A54/HIS. Test/mock xanh không chứng minh live A54/HIS đạt.
- `release/1.0.0` (`5625c41`) **không** chứa `742a139`/`b19b35e`; ghi chú phát hành ở đó còn câu "không làm yếu assertion" chưa đúng.
- Chưa resume `TASK-5f472cdf04e34a6f99cd8ca703f1993b`, chưa dùng A54, không gia hạn/sửa sealed plan.
