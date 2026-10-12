# Autonomy đợt 2 — bằng chứng 12/10/2026

Yêu cầu: sửa lỗi scorecard Codex tìm ra; khắc phục emulator treo và selector không khớp Flutter; regression
test + eval trước–sau cùng harness/corpus; trial trọn luồng với runtime cố định, mục tiêu cấp công việc,
OneCrew sở hữu cả bàn giao và thông báo. Thiết kế: [delivery-autopilot.vi.md](../../delivery-autopilot.vi.md).
Ba trục chấm riêng; số test xanh không thay bằng chứng thực tế.

## Commit (nhánh `claude/delivery-runtime-recovery`, cục bộ, chưa push; cha `277033c`)

| Commit | Nội dung | Nguồn phát hiện |
|---|---|---|
| `9e97460` | Quy nguồn quyết định (user / relayed / entry / unknown); kiểm tra + phục hồi thiết bị trong quyền (Wait, keyguard, emulator trong envelope); selector theo tầng có bằng chứng; `hint`, `assert_absent`; ảnh chụp UI khi trượt; hiệu chỉnh kịch bản có giới hạn | Codex review; trial 3 |
| `218f010` | 4 case eval | |
| `a9a5020` | System UI treo lặp sau boot: chờ ổn định có giới hạn trước khi khởi động lại emulator | smoke thật trên emulator (trước trial) |
| `39cfc47` | case `boot-settle` | |
| `c113c10` | App chết là bằng chứng crash, không phải "cửa sổ khác giữ focus"; crash Java → product; crash native trên emulator đã duyệt → khởi động lại một lần; câu thông báo nêu đúng ai quyết | trial 5 |
| `011ff53` | case `app-crash-evidence` | |
| `fe94a63` | Thiếu red trên code đúng → task con sửa **chỉ test** (production giữ nguyên byte) + phản hồi cụ thể | trial 6 |
| `f01e9ce` | case `red-only-repair` (corpus 42 case / 148 probe) — **runtime cuối** (trial 7) | |
| `87712a1` | Harness cuối: test `boot-settle` tái hiện đúng smoke (đỏ trước `a9a5020`), import `delivery_calibrate` lười; runtime giữ nguyên `f01e9ce` | eval historical |

## Trục 1 — Test runtime

- Suite đầy đủ trên `f01e9ce`: **857 test, 856 đạt**; 1 lỗi có sẵn (`test_incremental` cần Codex CLI).
- 35 test mới trong `tests/test_autonomy_round2.py` (fixture XML là dump thật của app trial; crash buffer là dòng thật của trial 5).
  Fixture thiết bị cũ được bổ sung trả lời `pidof`/focus (runtime giờ kiểm app còn sống); không sửa assertion nào.
  Test cũ đổi kỳ vọng có chủ đích: fixture "autonomous" của scorecard trước đây là câu trả lời của `codex` không rõ ai quyết —
  đúng lỗi Codex chỉ ra; nay dùng câu trả lời của chính người dùng và thêm 3 fixture `entry_decided`/`relayed`/`unattributed`.
- **Eval cùng harness `87712a1`, repeat 2:**
  - Release (trước `277033c` → sau `87712a1`, runtime = `f01e9ce`): **68/84 → 84/84**, 0 regressed.
    Trước: 68 passed, 2 assertion_failed, 2 runtime_error, 12 capability_unavailable.
    Phân loại: 12 `capability_added` (năng lực mới: live-ui-selectors, device-environment-recovery, boot-settle,
    scenario-calibration, app-crash-evidence, red-only-repair); 2 `recovered` decision-provenance; 2 `recovered`
    intervention-recording — **chỉ vì kỳ vọng test đổi có chủ đích** (details reply giờ ghi `decided_by`), không phải sửa hành vi.
    `D:\OneCrewEvals\round2-20261012\compare.md`
  - Historical (mỗi case so commit ngay trước bản sửa của nó), theo từng probe:
    - `decision-provenance` trên `277033c` (lỗi Codex): **4 đỏ bằng assertion** (entry tự quyết, entry chuyển lời, không quy được
      nguồn → bản cũ chấm autonomous_complete; và test scorecard 3 fixture mới), 1 runtime_error (CLI chưa có `--decided-by`),
      1 guard đạt cả trước/sau (câu trả lời của chính người dùng).
    - `boot-settle` trên `218f010`: **đỏ bằng assertion** (bản cũ khởi động lại emulator khi System UI còn đang ổn định).
    - `app-crash-evidence` trên `39cfc47` (trial 5): **4 đỏ bằng assertion**, 1 capability (`crash_summary`), 1 runtime_error.
    - `red-only-repair` trên `011ff53` (trial 6): **probe chính đỏ bằng assertion**, 1 capability (`red_only`), 2 runtime_error.
    - `live-ui-selectors`, `device-environment-recovery`, `scenario-calibration` trên `277033c`: capability_unavailable/runtime_error
      — năng lực mới, không khẳng định tái hiện lỗi hành vi.
    `D:\OneCrewEvals\round2-20261012\historical\`
- Đã thay thế, **không cộng gộp**: harness `218f010` (dừng giữa chừng vì runtime đổi); harness `f01e9ce` (đủ: 68/84 → 84/84,
  nhưng historical cho thấy probe `boot-settle` đạt ngay trên commit trước bản sửa — test yếu, đã sửa ở `87712a1`).
  Thư mục `D:\OneCrewEvals\round2-20261012\superseded-*`.

## Trục 2 — Trial thực tế (sandbox, emulator `OneCrew_CloudAuth_Fresh`/`emulator-5554`, không A54)

Mỗi trial: sandbox mới từ mã gốc (chưa sửa), envelope có `device.required: true` và `device.emulator`, ngân sách 40 calls /
2 giờ / 2 vòng sửa, runtime chạy từ worktree ghim một commit (không đổi giữa lượt; scorecard: 1 bản runtime/trial).

| Trial | Runtime | Mục tiêu | Kết quả | Calls | Thời gian | Scorecard |
|---|---|---|---|---|---|---|
| 4 `TASK-5f843e4047db4d2298a8063c51cc6a28` | `39cfc47` | cổng 1–65535 (mục tiêu đã dùng ở trial 1–3) | **hoàn thành**, 3/3 AC | 5 | 6 phút 32 s | **complete + autonomous = autonomous_complete** |
| 5 `TASK-dc9d90b913cc40e290ccfe800c682362` | `39cfc47` | địa chỉ máy chủ (mục tiêu mới) | dừng ở 1 câu hỏi (environment) | 7 | 13,5 phút tới câu hỏi | incomplete + assisted (entry_decision, assistance_recorded) |
| 6 `TASK-71ae16559f61457591163283bf30b256` | `011ff53` | như trial 5 | dừng ở 1 câu hỏi (product) | 10 | 6 phút tới câu hỏi | incomplete + assisted (entry_decision) |
| 7 `TASK-c37881073b1046cc94a0553ca936bbce` | `f01e9ce` | như trial 5 | **hoàn thành**, 3/3 AC | 5 | 20 phút 44 s | **complete + autonomous = autonomous_complete** |

**Trial 4 (từng bước, đều từ ledger):** planner 1 vòng, kịch bản 11 bước do OneCrew soạn (content-desc/hint, có
`assert_absent`) → change-1 (task con) → regression 10/10, red đúng hành vi trên baseline (6 test đỏ) → review accept →
build APK debug `d11061c6…` → audit (chữ ký debug, package, ZIP) → OneCrew boot emulator, bỏ keyguard, cài APK, hash khớp,
11/11 bước đạt (selector đều tầng `exact`), cleanup, tắt emulator → handover → **một** cửa sổ Windows `shown`.
Lỗ hổng sản phẩm review không bắt: `int.tryParse` nhận `+80` và dạng hex `0x50`.

**Trial 5:** đạt tới thiết bị. Trực tiếp trên UI thật: boot, bỏ keyguard ×5, Wait trên System UI "not responding" ×2; bước
s7 (selector `focused:false`, ô vẫn giữ focus) trượt → ảnh chụp UI (giá trị riêng che `<private>`) → **hiệu chỉnh bằng model**:
bỏ `focused`, validator chấp nhận (chỉ đổi bước trượt, khớp đúng một node) → kịch bản bản 1 → chạy lại: app **crash native**
(SIGSEGV luồng raster Flutter) mỗi lần mở; OneCrew đọc nhầm thành "cửa sổ khác giữ focus" (launcher), thử lại 2 lần rồi hỏi.
→ sửa `c113c10`.

**Trial 6:** production đúng, 6/6 test đạt, nhưng red không đỏ do hành vi (test red gọi hàm `isValidHost` mới → không load trên
mã gốc). Hai thế hệ sửa đều bị cổng native-change từ chối "No production fix in patch" vì cách sửa đúng chỉ chạm test → hỏi.
→ sửa `fe94a63`.

**Trial 7:** planner 1 vòng; red đúng hành vi ngay (13/13 test), review accept, build/audit; thiết bị lần 1: boot, keyguard ×13,
Wait ×32 (System UI treo liên tục khoảng 11 phút), khởi động lại emulator 1 lần, qua s1 rồi `uiautomator` không trả cây → transient,
tự thử lại sau 15 s → 10/10 bước + cleanup đạt → handover → một cửa sổ Windows `shown`.
Lưu ý môi trường: lúc đó entry đang chạy suite đầy đủ song song (17:36–17:50) làm máy quá tải — tác động môi trường do entry gây ra.
Hai bản sửa `c113c10`/`fe94a63` **không** bị kích hoạt trong trial 7 (không crash, không thiếu red) — chúng chỉ được kiểm bằng
test/eval. Hiệu chỉnh selector đã chạy thật trong trial 5.

## Trục 3 — Entry còn làm

| Việc | Trial | Loại |
|---|---|---|
| Soạn SOL + envelope theo ủy quyền, ghi duyệt `claude-entry-delegated` (người dùng chưa tự đọc các revision) | 4–7 | quyết định ủy quyền |
| Tạo sandbox: chép app đã `pub get` từ trial 3, trả `lib/`/`test/` về mã gốc; private inputs; bật desktop | 4–7 | môi trường trước dispatch |
| `delivery submit` cấp mục tiêu | 4–7 | handoff |
| Smoke dev (trước trial 4): boot emulator, cài APK trial 3, chạy `device()` mới — app trial 3 còn cài trên emulator | trước 4 | phát triển |
| Trả lời `stop` (`--decided-by entry`) để giữ kết quả thất bại | 5, 6 | quyết định của entry (chấm assisted) |
| Chẩn đoán chỉ đọc (`dumpsys`, `logcat`) + thử khởi động lại emulator một lần (ghi `eval assistance`) | 5 | chẩn đoán |
| Chạy suite đầy đủ song song với stage thiết bị | 7 | tải môi trường |
| Tắt emulator OneCrew để lại (lần thử đạt không phải lần đã boot) | sau 7 | dọn môi trường |
| Sửa runtime giữa các trial (không trong trial nào) | 5→6→7 | runtime |

Không còn: viết plan/recipe/test/scenario, khởi động emulator, đóng hộp thoại ANR, sửa selector, gọi `resume`, khởi động lại
coordinator, chạy test/build/E2E, viết bàn giao, bật cửa sổ thông báo.

## Kết luận

- OneCrew **tự hoàn thành trọn luồng** (lập kế hoạch → sửa → test có red → review → APK → E2E trên emulator tự boot →
  bàn giao → một thông báo Windows), không câu hỏi, không can thiệp entry trong task, ở **2/4 trial** đợt này
  (trial 4: mục tiêu đã biết; trial 7: mục tiêu mới, sau hai lần sửa runtime). Trial 5 và 6 thất bại, giữ nguyên làm bằng chứng.
- Đây là mẫu nhỏ trên một app thử nghiệm, một emulator; không phải tỷ lệ tổng quát. Phần duyệt envelope và chuẩn bị sandbox
  vẫn do entry làm theo ủy quyền.
- Chưa resume `TASK-5f472cdf04e34a6f99cd8ca703f1993b`, chưa dùng A54: cần quyền thiết bị + deadline còn hiệu lực.

Scorecard: `D:\OneCrewEvals\round2-20261012\scorecard-trial-{4,5,6,7}`. Eval: `D:\OneCrewEvals\round2-20261012\`.
