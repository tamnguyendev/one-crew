# Delivery autopilot — bằng chứng 12/10/2026

Thiết kế và tiêu chí: [delivery-autopilot.vi.md](../../delivery-autopilot.vi.md). Báo cáo chấm
riêng ba trục; số test xanh không dùng thay cho bằng chứng tự hoàn thành.

## Trục 1 — Test runtime

- Suite đầy đủ: 808 test, 807 đạt; 1 lỗi có sẵn (test_incremental cần Codex CLI, tái hiện từ trước đợt), chạy trên ced7163 với môi trường tạm cô lập.
- Eval replay (corpus v3, 32 case, repeat 2, harness `b39c502`, cùng Python/OS):
  trước `356fb82` 32/64 lượt đạt (12 `assertion_failed` = đỏ bằng hành vi, 20
  `capability_unavailable` = thiếu module mới); sau `2d46da3` 62/64 lượt đạt, 0 regressed (12 đỏ hành vi và 20 thiếu năng lực đều đạt; 2 lượt child-question-continuation hỏng chỉ vì probe cần Claude CLI, không có trong môi trường cô lập — đã sửa probe ở a9fe13f và replay lại 2/2 đạt trên 2d46da3).
  So sánh: `D:\OneCrewEvals\autopilot-20261012-v2\compare.md`.
- Lượt eval đầu (harness `6982749`) bị 10 `runtime_error` giả do môi trường probe thiếu
  `USERNAME` (getpass); đã sửa harness `b39c502` và chạy lại cả hai phía, giữ kết quả cũ ở
  `D:\OneCrewEvals\autopilot-20261012\compare-B.md`.
- Đỏ bằng hành vi trên 356fb82: P1 IME, P2 pubspec, transient-retry, ask-once,
  crash-replay-once (kill coordinator thật), flutter-reporter-red. Các case còn lại là năng lực
  mới (`capability_added`), không phải tái hiện lỗi.

## Trục 2 — Task thực tế (sandbox `settings_trial`, emulator, không dùng A54)

Cùng một mục tiêu cấp công việc, cùng envelope (AC1 code+red+review, AC2 APK debug+audit,
AC3 E2E thiết bị tùy chọn, 40 calls/2 giờ/2 repairs). Entry chỉ tạo conversation/SOL, ghi
duyệt theo ủy quyền, `delivery submit --solution --goal`; không viết plan/recipe/test/scenario.

| Lượt | Runtime | Kết quả | AC1 | AC2 | AC3 | Calls |
|---|---|---|---|---|---|---|
| 1 `TASK-fd13e281` | trước 8207d61 + 2 sửa giữa lượt | dừng ở câu hỏi `product` → entry stop | chưa | chưa | chưa | 13 |
| 2 `TASK-03a6a3a9` | 8207d61 (+ commit phiên khác) | dừng ở câu hỏi `product` → entry stop | chưa (review lỗi giao thức) | chưa | chưa | 13 |
| 3 `TASK-e991ebeb` | 2d46da3 (+ commit phiên khác giữa lượt) | dừng ở câu hỏi `device_assertion` → entry stop | **đạt** | **đạt** | không kiểm chứng | 6 |

Không lượt nào `autonomous_complete`. Lượt 3: OneCrew tự lập plan (2 vòng planner), sửa code
lần đầu đạt, regression có đỏ hành vi trên baseline, review độc lập đạt, build APK; entry giết
coordinator giữa build → keeper tự khởi động lại sau ~3 s → build phát lại một lần → audit đạt;
E2E thất bại vì emulator System UI ANR và selector kịch bản (Flutter dùng `content-desc`, ô
cổng không có `resource-id`); OneCrew tự thử lại 4 lần rồi hỏi **một** câu, **một** cửa sổ
Windows (`shown`).

Lỗi runtime do lượt thật phát hiện (đều đã sửa, có test, có case eval):
1. `parse_tests` bỏ `print` của testWidgets → đỏ không khớp, phản hồi sửa mơ hồ.
2. Generation child cũ không đóng → intake từ chối child mới (`live task`).
3. Regression chạy `--no-test-assets` → test có sẵn hỏng (shader ink_sparkle), bị coi là lỗi sản
   phẩm; nay build test assets và đối chiếu baseline.
4. Review chấp nhận nhưng trích hash snapshot → bị đẩy thành vòng sửa code.
5. Thiết bị: chờ UI khi cửa sổ hệ thống chiếm focus, stream bị khóa (WinError 32), nhãn Flutter
   `content-desc`.

## Trục 3 — Entry còn phải làm

| Việc | Lượt | Loại |
|---|---|---|
| Thống nhất envelope, ghi duyệt SOL | 1-3 | quyết định hợp lệ (ủy quyền) |
| Chuẩn bị sandbox, làm ấm Gradle, khởi động emulator | trước dispatch | môi trường |
| Chẩn đoán từ log và sửa runtime (5 nhóm lỗi trên) | 1-3 | runtime |
| Trả lời retry/stop thay người dùng theo ủy quyền | 1-3 | quyết định |
| Đóng hộp thoại ANR trên emulator | 3 | môi trường |
| Giết coordinator (fault injection) | 1, 3 | thử nghiệm |

Không còn: viết plan/recipe/owned/test/red/SDK/signer/scenario, gọi `delivery resume`, khởi động
lại coordinator, tự chạy test/build/E2E, tự viết báo cáo handover. Phiên Claude khác commit
runtime vào cùng nhánh giữa lượt 2 và 3; scorecard ghi `runtime.changed`.

Mọi can thiệp được ghi bằng `control.intervention` (tự động) và `eval assistance`. Scorecard:
`D:\OneCrewEvals\autopilot-20261012\scorecard-trial*`.
