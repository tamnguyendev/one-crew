# Delivery autopilot — bằng chứng 12/10/2026 (cập nhật sau review Codex P1)

Thiết kế và tiêu chí: [delivery-autopilot.vi.md](../../delivery-autopilot.vi.md). Ba trục chấm riêng;
số test xanh không dùng thay cho bằng chứng tự hoàn thành. Chưa lượt thật nào hoàn thành tự chủ trọn luồng.

Runtime cuối: `153c553` (delivery). `923ceb0` chỉ thêm cột báo cáo người gửi trả lời trong scorecard.
Harness/corpus cuối: `803aa2f` (35 case, 112 probe).

## Trục 1 — Test runtime

- Suite đầy đủ trên `803aa2f` (runtime `153c553`): **821 test, 820 đạt**; 1 lỗi có sẵn
  (`test_incremental` cần Codex CLI; tái hiện từ trước đợt). `923ceb0`: 19 test liên quan đạt.
- Regression test P1 (`tests/test_codex_review_p1.py`, 14 test) chạy trên `d7410c1` (cha bản sửa, worktree
  tạm): 6 fail hành vi (deadline stop/retry, scorecard partial, thiết bị hết hạn khi install/sau bước,
  reconcile), 4 error (trường/hàm mới chưa có: scorecard levels ×2, preflight `permission_left`, actor
  của `923ceb0`), 4 đạt (guard: gia hạn rồi tiếp tục; ba nhánh Delivery). Trên `153c553`/`923ceb0`: 14/14.
- **Eval kết luận (một harness, một corpus):** `--harness-ref 803aa2f --repeat 2`
  - Release: trước `356fb82` **32/70** (12 `assertion_failed` = đỏ bằng hành vi, 26
    `capability_unavailable` = module mới chưa có) → sau `153c553` **70/70**, 0 regressed.
    `D:\OneCrewEvals\autopilot-20261012-v3\compare.md`
  - Historical 3 case P1 (trước = `d7410c1`, cha của bản sửa): **0/6 → 6/6**.
    `D:\OneCrewEvals\autopilot-20261012-v3\compare-p1-historical.md`. Theo từng probe trên `d7410c1`:
    đỏ hành vi `RED-DEADLINE-STOP`, `RED-DEADLINE-RETRY`, `RED-SCORECARD-PARTIAL`, `RED-DEVICE-WINDOW`
    (×2) và reconcile sau hết hạn; 3 probe lỗi vì đọc trường mới (KeyError/ValueError); 4 probe là guard
    đạt cả trước và sau (gia hạn rồi tiếp tục; ba nhánh Delivery với receipt giả) — không phân biệt.
- Đỏ bằng hành vi trên `356fb82` (release): P1 IME, P2 pubspec, transient-retry, ask-once,
  crash-replay-once (kill coordinator thật), flutter-reporter-red. Các case còn lại ở `356fb82` là
  `capability_unavailable`, tức năng lực mới, không phải tái hiện lỗi.
- Các lần chạy trước **đã bị thay thế, không cộng gộp**: harness `6982749` (sau `8207d61`, 50/62, lỗi
  môi trường probe thiếu `USERNAME`); harness `b39c502` (sau `2d46da3`, 62/64, một probe phụ thuộc
  Claude CLI). Không dùng các số đó cho bản runtime cuối.

## Trục 2 — Task thực tế (sandbox `settings_trial`, emulator, không dùng A54)

Cùng một mục tiêu cấp công việc, cùng envelope (AC1 code+red+review, AC2 APK debug+audit, AC3 E2E thiết
bị tùy chọn, 40 calls/2 giờ/2 repairs). Entry chỉ tạo conversation/SOL, ghi duyệt theo ủy quyền,
`delivery submit --solution --goal`; không viết plan/recipe/test/scenario. Scorecard chấm lại bằng
`923ceb0` (mức hoàn thành và mức hỗ trợ tách riêng; Calls lấy từ ledger ngân sách của task):

| Lượt | Runtime | Dừng ở | AC1 | AC2 | AC3 | Calls | Mức hoàn thành | Mức hỗ trợ |
|---|---|---|---|---|---|---|---|---|
| 1 `TASK-fd13e281` | trước 8207d61; 3 bản runtime trong lượt | câu hỏi `product` → entry stop | chưa | chưa | chưa | 13 | incomplete | assisted |
| 2 `TASK-03a6a3a9` | 8207d61; 3 bản (commit phiên khác) | câu hỏi `product` → entry stop | chưa (review lỗi giao thức) | chưa | chưa | 13 | incomplete | assisted |
| 3 `TASK-e991ebeb` | 2d46da3; 2 bản (commit phiên khác) | câu hỏi `device_assertion` → entry stop | đạt kỹ thuật | đạt kỹ thuật | không kiểm chứng | 6 | incomplete | assisted |

Không lượt nào `autonomous_complete` hay `partial_complete`; cả ba kết thúc `cancelled` do entry trả
lời stop. Các lượt chạy trên runtime trước `153c553`; chưa có lượt thật trên runtime cuối.

Lượt 3 (diễn biến): planner 2 vòng → sửa code đạt lần đầu → regression có đỏ hành vi trên baseline →
review đạt → build; entry giết coordinator giữa build → keeper khởi động lại sau ~3 s → build phát lại
một lần → audit đạt → E2E hỏng (emulator System UI ANR; selector kịch bản không khớp nhãn Flutter
`content-desc`, ô cổng không có `resource-id`) → 4 lần tự thử → **một** câu hỏi, **một** cửa sổ Windows.

Lỗi runtime do lượt thật phát hiện (đã sửa, có test và case eval): `parse_tests` bỏ `print`;
generation child cũ không đóng; regression `--no-test-assets`; review đúng nhưng trích sai ref bị coi
là lỗi code; ANR/khóa stream/nhãn Flutter. Ba lỗi P1 do Codex review: câu trả lời sau deadline không
được áp dụng; scorecard gọi task partial là autonomous_complete; `valid_until` chỉ kiểm lúc bắt đầu.

## Trục 3 — Entry còn phải làm

| Việc | Lượt | Loại |
|---|---|---|
| Thống nhất envelope, ghi duyệt SOL | 1-3 | quyết định (ủy quyền) |
| Chuẩn bị sandbox, làm ấm Gradle, khởi động emulator | trước dispatch | môi trường |
| Chẩn đoán từ log và sửa runtime | 1-3 | runtime |
| Trả lời retry/stop (scorecard: 4/4 trả lời do `claude` gửi, 0 do người dùng) | 1-3 | quyết định thay người dùng |
| Đóng hộp thoại ANR trên emulator; UI dump chỉ đọc để chẩn đoán | 3 | môi trường / chẩn đoán |
| Giết coordinator (fault injection) | 1, 3 | thử nghiệm |

Không còn: viết plan/recipe/owned/test/red/SDK/signer/scenario, gọi `delivery resume`, khởi động lại
coordinator, tự chạy test/build/E2E, tự viết báo cáo handover. Còn thiếu: hiệu chỉnh selector kịch bản
từ UI thật trước khi niêm phong; chẩn đoán/sửa runtime vẫn do entry; nhiều phiên cùng commit runtime lên
một nhánh làm runtime đổi giữa lượt (scorecard ghi `runtime_changed`).

Scorecard: `D:\OneCrewEvals\autopilot-20261012-v3\scorecard-trial*`.
