# OBS-1 — báo cáo bàn giao: màn hình theo dõi chỉ đọc, beta `2.4.0.dev8` (vòng UI/UX theo hướng Blazo + định danh server)

Người lập: Claude (Fable 5.1), 03/11/2026. Lượt 1 (~00:00, `bf6994f`): lát OBS-1; lượt 2 (~09:00, `c3c8361` = `2.4.0.dev7`): bốn P2 của Codex; **lượt 3 (này, `@@SNAP@@` = `2.4.0.dev8`)**: review UX của Codex trên dev7 (UX-01…UX-08) + P2 định danh server của `track open`, kiểm thao tác thật trên gói cài ngoài checkout, bàn giao script mở UI cho SignSDK (đọc sổ thật, runtime 2.3 giữ nguyên), phát hành prerelease kế tiếp lên origin private (chủ ủy quyền một lần 03/11). Các bản sửa **chưa được Codex review lại, chưa nghiệm thu**.

## 1. Kết quả ngắn

- **Phát hành:** nhánh `claude/onecrew-obs1` (worktree `D:\TamNT\Workspace\11.OneCrew\wf-obs1`, tách từ `01b6f62` = `v2.4.0.dev6`). Snapshot **`@@SNAP@@`** = `2.4.0.dev8` (prerelease kế tiếp còn trống của dòng 2.4; dev6, dev7 đã chiếm — kiểm `git ls-remote --tags origin`). @@PUSH@@ Nhánh `claude/onecrew-2.4`, tag/gói `v2.4.0.dev6` và `v2.4.0.dev7` không đổi (script kiểm cả hai tag cũ không dịch).
- **Gói cuối:** `D:\OneCrewRuns\obs1\pkg\onecrew-2.4.0.dev8-obs1-beta` — wheel `onecrew-2.4.0.dev8-py3-none-any.whl`, SHA256 `@@WHEEL_SHA@@`; `manifest.json`, `SHA256SUMS`, `BAT-DAU-THU.vi.md` (cài → mở UI → chọn project/sổ → xem; §4 đọc sổ ≠ nâng runtime; §5 dừng bằng `track stop`), `docs\RELEASE-NOTES-OBS-1.vi.md`, `docs\limits-obs1.md`, `docs\UX-OBS-1.vi.md` (ma trận), bộ kiểm `verify\` (V1–V15, harness `obs1_ux_harness.py`), script chủ `verify\thu-goi-obs1.ps1`, script mở/dừng UI `verify\mo-trang-obs1.ps1` / `dung-trang-obs1.ps1`.
- **Kiểm từ gói (wheel cài vào venv sạch ngoài checkout, `claude` giả):** `thu-goi-obs1.ps1` → @@VERIFY@@ (`@@WORK@@\verify-report.json`, `ux-results.json`, ảnh `evidence\ux-*.png`). Số đo: độ trễ ghi sổ → trang `@@LAT@@` s (trần 5 s), đọc overview `@@READMS@@` ms/poll, engine step `@@STEP@@` s, bước dài `@@LONG@@` s. V14 = @@V14@@ lượt kịch bản UX trong Chrome headless (thao tác thật do harness phát: click, bàn phím, ≥ 3 poll, ghi sổ trong lúc đọc, reload, Back; 1280×720 / 640×720 / 390×844); V15 = `track open` thật từ wheel (dùng lại đúng server, marker sai không dùng lại và không dừng tiến trình khác, hai lần mở đồng thời = một server, `track stop`).
- **Test trên checkout (code = snapshot):** `tests/test_obs1_ux.py` 14/14 (mới), `tests/test_obs1_browser.py` 2/2 (mới, Chrome headless, @@BROWSER_SCEN@@ lượt kịch bản; ảnh `D:\OneCrewRuns\obs1\ux\@@SNAP@@\`), `test_obs1_p2` 10/10 (bốn P2 cũ giữ xanh), `test_obs1_tracking` 18/18, `test_obs1_web` 7/7, `test_obs1_installed` 1/1, `test_g1_core`, `test_wf_r10_console_utf8` + `test_wf_r14_console_entry` + `test_v24_docs_sync` 22/22: @@REG@@ (log `D:\OneCrewRuns\obs1\logs\`).
- **SignSDK:** venv riêng `D:\OneCrewRuns\projects\signsdk-9SignSDK\ui-obs1\venv` (wheel dev8), script `ui-obs1\mo-ui-signsdk.ps1` (= `track open` trên sổ thật `state-23`, chỉ đọc) và `dung-ui-signsdk.ps1` (= `track stop`); diễn tập trên BẢN SAO `ui-obs1\rehearsal-state` trước (hash bản sao trước/sau bằng nhau: `@@REH_HASH@@`), rồi sổ thật: hash toàn bộ file `state-23` trước `@@S23_BEFORE@@` / sau `@@S23_AFTER@@`; registry thật `aacad058f478898d…` trước/sau không đổi; runtime `venv-23` = `2.3.0.dev11` trước/sau. Không init repo thật, không chuyển hook, không ghi vào `state-23`.
- **Không đổi:** `wf-v24`, `wf-v24-pkg`, `wf-v23-hf`, gói/tag dev6 và dev7, sổ/hook/registry thật; không model trả phí (chỉ `claude` giả).

## 2. Bốn finding P2 của Codex trên `bf6994f` (khép ở dev7, giữ xanh ở dev8)

| # | Lỗi | Sửa (dev7) | Khép bằng |
|---|---|---|---|
| P2-01 | `plan.closed` hiện "đã nghiệm thu" | mức từ node; `closed` ≠ `accepted` (dev8: nhãn riêng "đã đóng") | `ClosedIsNotAccepted` (3); V13 P3 |
| P2-02 | quan sát attempt cũ làm attempt mới "bị chặn" | progress ràng theo attempt của `engine.state`; timeline `stale_attempt` | `OldAttemptObservation` (2); V13 P4 |
| P2-03 | khoảng chờ đã `until` vẫn "đang chờ" | `_waits` theo (attempt, ref), `open`/`until`; `measure.executor_waits` | `EndedWaits` (3); V13 P5 |
| P2-04 | `--project-only` bị nới bởi `?project_id=` | query ≠ server → 403 mọi `/api/*` | `ProjectScope` (2); V13 HTTP |

## 3. Review UX của Codex trên dev7 (`D:\OneCrewRuns\codex-obs1-ux-review-20261103\`, `codex-obs1-dev7-review\`) → cách khép → kiểm bằng gì

Bố cục chốt (ma trận viết trước khi sửa: `docs/obs1/UX-OBS-1.vi.md`): **tổng quan → chi tiết task → timeline theo phần việc/attempt → bằng chứng của từng bước**; hai cột ≥ 900 px (chi tiết cố định, cuộn riêng), một cột < 900 px (danh sách ↔ chi tiết, "← Danh sách"); theme sáng mặc định, tối theo hệ điều hành; nhãn tiếng Việt; kỹ thuật gập trong "Kỹ thuật"/"chi tiết kỹ thuật". Học cách phân cấp của Blazo (MIT, `D:\OneCrewRuns\blazo-review-20261102\LICENSE`), không mượn code/tài sản, gói vẫn stdlib.

| ID | Vấn đề reviewer nêu | Nguyên nhân | Khép (dev8) | Kiểm (F = unittest, T = harness Chrome, B = bố cục/ảnh) |
|---|---|---|---|---|
| UX-01 | poll dựng lại chi tiết → đóng Bằng chứng/Attempt đang đọc | `renderDetail` mỗi poll | chi tiết chỉ dựng lại khi `source.last_seq` đổi; khi dựng lại: chụp/khôi phục mục đang mở (`data-k`), phần tử focus (kể cả `summary`/nút trong mục), cuộn của khung chi tiết và cửa sổ, bước đang chọn, nội dung bằng chứng đã mở; thời gian tương đối cập nhật tại chỗ | T `ux01` ở 1280 và 390: ≥ 3 poll yên rồi một lần ghi sổ từ tiến trình khác (`/__signal` → `create_request`): trước/sau giống nhau (@@UX01@@) |
| UX-02 | lọc project B, chi tiết vẫn P1 của A | chi tiết không theo bộ lọc | đổi lọc → task đang chọn không thuộc project đó: bỏ chọn, placeholder nêu project, URL bỏ `plan` | T `ux02` |
| UX-03 | "Cần bạn" chỉ hiện lệnh `<option-id>` | model chỉ cho một lệnh chung | `needs_user[].options[].reply_command` (mỗi lựa chọn một lệnh `--choice <id>`), `reason`/`impact`/`recommendation`; thẻ câu hỏi: câu hỏi, vì sao, ảnh hưởng, từng lựa chọn + lệnh + nút "Sao chép lệnh" (clipboard, fallback, hiện "đã sao chép: …"); không nút trả lời | F `QuestionCommands`; T `ux03` (sao chép đúng lệnh lựa chọn 2, focus giữ trên nút, seq sổ không đổi) |
| UX-04 | chi tiết ở y≈1416 ngoài tầm nhìn; Tab bỏ qua dòng; URL không đổi | chi tiết dưới danh sách; `<tr>` không focus được | hai cột/một cột; dòng `role=option tabindex=0`, ↑↓/Home/End, Enter/Space chọn và focus tiêu đề chi tiết, Esc đóng và trả focus về dòng; `pushState` theo lựa chọn, `popstate`; reload giữ task, Back về task trước rồi về danh sách; dòng vừa xem được đánh dấu | T `ux04` ở 1280 (chi tiết trong tầm nhìn ngay sau click) và 390 |
| UX-05 | plan đóng chưa có đầu ra vẫn "hoàn tất" xanh; "đã chạy" gồm cả chờ | một nhãn `done`; nhãn thời gian mơ hồ | `status.outcome` + `OUTCOME_WORDS`: "đã nghiệm thu" (xanh lá) / "đã kiểm, chờ nghiệm thu" (xanh ngọc) / "đã đóng" (xám); `elapsed.label` = "từ khi duyệt (thời gian lịch, gồm cả chờ)"; thẻ "Từ khi duyệt (lịch)" / "Thực hiện (attempt)" / "Chờ"; CLI "từ khi duyệt" | F `OutcomeWords` (3); T `ux05` (ba màu khác nhau, không còn "đã chạy") |
| UX-06 | "cũ → mới" nhưng seq giảm; `stale_attempt` không hiện | render đảo mảng | nhóm theo Plan và từng phần việc (sự kiện chỉ có attempt gán về phần việc đã khởi động attempt đó: `node_of_attempt`), cũ → mới theo seq, "lịch sử cũ (n)" gập (stale), "chi tiết kỹ thuật (n)" gập; bấm bước → bằng chứng của bước, xem nội dung ngay | T `ux06` (seq tăng, lịch sử gập và đánh dấu, attempt.* gập dưới phần việc, bằng chứng của bước mở/đóng) |
| UX-07 | danh sách dày kỹ thuật; bằng chứng chỉ hash | mọi thứ trên một bảng | dòng: trạng thái · tên · mục tiêu · bước hiện tại (`current_step`, có nguồn) · cập nhật tương đối · "cần bạn"; ID/đường dẫn/adapter mờ; `evidence_index` (tên/loại/thời điểm/phần việc, `stale`); lọc trạng thái + "cần bạn", tìm | F `EvidenceIndex`, `OutcomeWords` (`current_step`); T `ux07` |
| UX-08 | 390 px: trang 1103 px, bảng 1074 px | bảng cố định | một cột < 900 px; danh sách dạng dòng; bảng kỹ thuật `overflow:auto` riêng; header gọn trên màn hẹp | T `ux08` ở 1280/640/390: `scrollWidth ≤ innerWidth` (@@UX08@@) |
| P2 server | `track open` dùng lại server wheel cũ (reuse.py) và server sổ khác khi cổng bị dùng lại (wrong-state.py) | chỉ kiểm `health.ok` | `instance` nonce + `version` + `state_root` + `project_id` + `pid` trong marker và `/api/health`; `reusable()` khớp tất cả mới dùng lại; marker không có instance (wheel cũ) / server không trả lời / định danh khác / version, sổ, phạm vi, PID khác → không dùng lại, mở server mới, `refused.reason`, không kill gì; khóa `tracking/open.lock` (O_EXCL, > 60 s = bỏ sót) cho mở đồng thời; marker atomic, chỉ xóa khi còn là của mình; `track status`, `track stop` (chỉ dừng khi health khớp PID + sổ + instance; marker cũ/sai chỉ bị xóa), `track open --no-browser`; script mở/dừng (gói và SignSDK) đi qua `track open|stop` | F `ServerIdentity` (7, server thật trên cổng thật: wheel cũ, cổng bị chiếm, version/sổ/phạm vi/PID, server chết, stop từ chối server lạ, chờ khóa), `DetachedOpen` (2 tiến trình `track open` đồng thời → một server, `status`, `stop` qua CLI); V15 từ wheel |
| race | hai request chi tiết về ngược thứ tự | không | token theo lựa chọn: trả lời của task đã bỏ chọn bị bỏ | T `race` (P1 bị làm chậm 1,5 s, chọn P2 ngay sau: chi tiết vẫn P2) |
| mất kết nối | — | — | badge "MẤT KẾT NỐI … worker không bị ảnh hưởng; trang tự thử lại", dữ liệu cũ và lựa chọn giữ, tự nối lại | T `disc` (proxy chặn `/api/*` rồi mở lại) |

## 4. Yêu cầu OBS-1 → code / test / bằng chứng (trên `@@SNAP@@`)

Bảng của dev7 (hồ sơ `a17743b`) vẫn đúng; thay đổi ở dev8: hàng "A. Trạng thái có nguồn" nay có `outcome`/nhãn riêng (UX-05); "A. Thời gian đã chạy" → "từ khi duyệt (lịch)" tách khỏi "thực hiện (attempt)" và "chờ"; "A. Việc cần người dùng" có lệnh theo từng lựa chọn (UX-03); "B. Mở/xem bằng chứng" có `evidence_index` và xem ngay trong trang (UX-06/07); "Kiểm UI trực tiếp từ artifact" nay là thao tác thật qua harness (V14) chứ không chỉ `--dump-dom`; thêm "định danh server `track open`" (V15). Mỗi hàng: đạt trên dữ liệu thử với `claude` giả.

## 5. Cách dùng

- **Thử trọn gói:** `powershell -ExecutionPolicy Bypass -File "D:\OneCrewRuns\obs1\pkg\onecrew-2.4.0.dev8-obs1-beta\verify\thu-goi-obs1.ps1"` → `DAT … 15/15` (≈ 4–6 phút).
- **Mở UI trên sổ thử của lượt kiểm (P1 câu hỏi, P2 đã tạo, P3 đóng, P4 đã chạy lại, P5 chờ đã kết thúc, P6 đã kiểm, P7 đã nghiệm thu, PB project B):** `powershell -ExecutionPolicy Bypass -File "D:\OneCrewRuns\obs1\mo-trang-obs1.ps1"`; dừng: `D:\OneCrewRuns\obs1\dung-trang-obs1.ps1`.
- **SignSDK (sổ thật, chỉ đọc, runtime 2.3 giữ nguyên):** `powershell -ExecutionPolicy Bypass -File "D:/OneCrewRuns/projects/signsdk-9SignSDK/ui-obs1/mo-ui-signsdk.ps1"`; dừng: `dung-ui-signsdk.ps1`; cài lại venv UI: `cai-ui-signsdk.ps1`.

## 6. Giới hạn

`docs/obs1/limits-obs1.md`: `claude` giả; thao tác do harness phát trong trang thật (không phải tay người, không screen-reader, không đo thời gian người dùng); Chrome headless (Edge headless không dump khi Edge mở); độ trễ trên sổ nhỏ; thời gian tương đối theo đồng hồ máy mở trang; không xác thực (127.0.0.1); bộ tự động mở `--no-browser` (trình duyệt mặc định mở trang do chủ xác nhận bằng mắt); các bản sửa dev7/dev8 chưa Codex review lại; gate 2.2 đầy đủ không chạy lại.

## 7. Việc thật sự cần chủ quyết

1. Codex review lại diff `c3c8361..@@SNAP@@` (trọng tâm `tracking_web.py`: `reusable`/`open_page`/`stop_page` và script trang; `tracking.py`: `_outcome`, `_current_step`, `evidence_index`, `node_of_attempt`) rồi nghiệm thu beta OBS-1.
2. Có gộp `claude/onecrew-obs1` vào dòng 2.4 hay giữ nhánh; prerelease kế tiếp của 2.4 là dev9.
3. SignSDK: dùng `mo-ui-signsdk.ps1` hằng ngày (đọc sổ thật bằng venv riêng) hay chờ nâng runtime chung; nâng runtime không nằm trong lượt này.
