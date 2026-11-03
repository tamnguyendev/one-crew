# OBS-1 — báo cáo bàn giao: màn hình theo dõi chỉ đọc, beta `2.4.0.dev7`

Người lập: Claude (Fable 5.1), 03/11/2026 (lượt 1 ~00:00 trên `bf6994f`; lượt 2 ~09:00 sau review Codex). Nhiệm vụ: OBS-1 (roadmap §0.9, thiết kế §2.10,
bàn giao Claude mục OBS-1) cách ly với bản phát hành 2.4; lượt 2: khép bốn P2 của Codex, kiểm từ wheel, gói cuối, tag + push lên origin private
(chủ ủy quyền một lần 03/11). Bản sửa **chưa được Codex review lại, chưa nghiệm thu**.

## 1. Kết quả ngắn

- **Phát hành:** nhánh `claude/onecrew-obs1` (worktree `D:\TamNT\Workspace\11.OneCrew\wf-obs1`, tách từ `01b6f62` = `v2.4.0.dev6`). Snapshot **`@@SNAP@@`** = `2.4.0.dev7`
  (prerelease kế tiếp còn trống của dòng 2.4; dev6 đã chiếm). Tag `v2.4.0.dev7` + nhánh: @@PUSH@@. Nhánh `claude/onecrew-2.4`, tag `v2.4.0.dev6`, gói dev6 không đổi.
- **Gói cuối:** `D:\OneCrewRuns\obs1\pkg\onecrew-2.4.0.dev7-obs1-beta` — wheel `onecrew-2.4.0.dev7-py3-none-any.whl`, SHA256 `@@WHEEL_SHA@@`; `manifest.json`, `SHA256SUMS`,
  `BAT-DAU-THU.vi.md` (cài → mở UI → chọn project/sổ → xem task; §4 đọc sổ của project đang có OneCrew ≠ nâng runtime; §5 dừng UI, quay về có điều kiện), `docs\RELEASE-NOTES-OBS-1.vi.md`,
  `docs\limits-obs1.md`, bộ kiểm `verify\` (V1–V13) và script chủ `verify\thu-goi-obs1.ps1`.
- **Kiểm từ gói (wheel cài vào venv sạch ngoài checkout, `claude` giả):** `thu-goi-obs1.ps1` → `@@VERIFY@@` (`D:\OneCrewRuns\obs1\thu-goi-dev7-@@SNAP@@\verify-report.json`, ảnh `evidence\obs1-list.png`,
  `obs1-detail-P1.png`, `obs1-disconnected.png`). Số đo: độ trễ ghi sổ → trang `@@LAT@@` s (trần 5 s), đọc overview `@@READMS@@` ms/poll, engine step `@@STEP@@` s, bước dài `@@LONG@@` s.
- **Test:** `tests/test_obs1_p2.py` (10; **9/10 đỏ trên `bf6994f`** — ca thứ 10 là đối chứng `plan.accepted` vẫn "đã nghiệm thu" — → 10/10 xanh), `test_obs1_tracking` (18),
  `test_obs1_web` (7, Chrome headless), `test_obs1_installed` (1, wheel ngoài checkout), `test_g1_core`, `test_wf_r10_console_utf8`, `test_wf_r14_console_entry`,
  `test_v24_docs_sync`: **82/82** trên code của snapshot (log `D:\OneCrewRuns\obs1\logs\test-obs1-all-083740.txt`; các commit sau chỉ sửa scenario kiểm gói và tài liệu).
- **Một lệnh mở UI đã chạy thật** (sổ thử của lượt kiểm, 5 plan + project B): `D:\OneCrewRuns\obs1\mo-trang-obs1.ps1` → `onecrew --project … --state-root … track open`.
- **Không đổi:** runtime/sổ/hook/registry thật (hash `aacad058f478898d…` trước/sau mọi lượt); project SignSDK vẫn 2.3 `venv-23`; `wf-v24`, `wf-v24-pkg`, `wf-v23-hf` không đụng; không model trả phí.

## 2. Bốn finding P2 của Codex (probe `D:\OneCrewRuns\codex-obs1-review-20261103\probe.py` trên wheel `bf6994f`)

| # | Lỗi (phản chứng) | Nguyên nhân | Sửa | Khép bằng |
|---|---|---|---|---|
| P2-01 | `plan.closed` với node chưa chạy hiện "đã nghiệm thu" | `_level` gộp `closed` với `accepted` | chỉ `plan.accepted` là nghiệm thu; `closed` lấy mức từ node (none/produced/verified); trạng thái `hoàn tất` với lý do "đã đóng (đóng không phải nghiệm thu; đầu ra: …)" | `ClosedIsNotAccepted` (3 ca: chưa chạy → `none`; một node produced → `produced`; accepted vẫn accepted); V13 `P3` qua `track show --json` |
| P2-02 | quan sát blocked của attempt cũ đến muộn làm attempt mới (thế hệ mới) hiện "bị chặn" | progress lấy "mới nhất theo node", không ràng attempt | `_progress_rows` giữ mới nhất theo (node, attempt); `_current_progress` chỉ lấy dòng của attempt mà `engine.state` ràng vào node; timeline đánh dấu `stale_attempt` ("attempt cũ"); quan sát của attempt hiện hành vẫn chặn | `OldAttemptObservation` (2 ca: running giữ nguyên, lịch sử có dấu, rồi quan sát attempt hiện hành → blocked; lý do "chưa có quan sát" chỉ của attempt hiện hành); V13 `P4` qua HTTP trong hai cửa sổ (running → blocked) |
| P2-03 | ghi bắt đầu chờ rồi ghi kết thúc cùng khoảng, mọi node verified, UI vẫn "đang chờ external_service" | mỗi sự kiện wait xét riêng | `_waits`: một dòng mỗi (attempt, basis ref) như `executors.summary`; bản ghi có `until` đóng nó dù thứ tự nào; trùng/đến muộn không mở lại; attempt đã kết thúc → `until = unknown`, không hiện hành; mỗi dòng có `open`; `measure.executor_waits`; attempt đang chạy có wait mở → "đang chờ" với lý do executor | `EndedWaits` (3 ca: đã đóng → `done` chờ nghiệm thu; hai khoảng độc lập + trùng + đến muộn; attempt đã kết thúc); V13 `P5` qua CLI JSON + text |
| P2-04 | server `--project-only` A: `?project_id=B` trả 200 kèm bằng chứng của B | `scope = query hoặc server` | `project_id` của query ≠ project của server → 403 trên mọi `/api/*`; = server → 200; chế độ mọi project vẫn thu hẹp được | `ProjectScope` (2 ca HTTP); V13 qua `track serve --project-only` thật rồi server mọi project |

Hồ sơ gốc lượt 1 (snapshot `bf6994f`, gói thử `onecrew-obs1-trial-bf6994f` 12/12) giữ nguyên trong lịch sử nhánh; các dòng "đạt" của lượt 1 ở mục 3 nay đọc là "đạt sau khi sửa P2" ở những hàng có ghi.

## 3. Yêu cầu OBS-1 → code / test / bằng chứng → trạng thái (trên `@@SNAP@@`)

| Yêu cầu | Code | Test / bằng chứng | Trạng thái |
|---|---|---|---|
| A. Danh sách: project, mục tiêu, định danh task/root | `tracking._item` (`project`, `goal`, `id`, `selector`) | `test_obs1_tracking` (mọi ca), ảnh `obs1-list.png` | đạt |
| A. Trạng thái có nguồn: đang thực hiện / đang chờ / bị chặn / hoàn tất / chưa xác định | `tracking._status` → `{kind,label,reason,source[]}` | `EngineTests`, `test_obs1_p2` (đóng ≠ nghiệm thu, attempt cũ không chặn, chờ đã kết thúc) | đạt sau sửa P2-01/02/03 |
| A. Thời gian đã chạy, cập nhật/bằng chứng gần nhất | `_elapsed`, `last_update`, `_last_evidence` | `test_duplicate_observation…`, `test_verified…` | đạt |
| A. Việc thực sự cần người dùng | `_needs_user` (request + lệnh trả lời, duyệt, báo cáo dừng, nghiệm thu) | `test_pending_request…`, V6 | đạt |
| B. Node/attempt, root/child | `detail.nodes`, `detail.attempts`, timeline gộp theo `seq` | `test_running_attempt…`, V4 | đạt |
| B. Phát sinh, retry/generation mới, lý do có bằng chứng | timeline `node.resumed`/`node.held`…, `measure.rework`, `eta.last_change`, `notices`, dấu `stale_generation`/`stale_attempt` | `test_old_generation_event…`, `OldAttemptObservation` | đạt |
| B. Phân biệt hoạt động / đã tạo / đã kiểm / đã nghiệm thu | `status.kind` tách khỏi `level.kind` (`none/produced/verified/accepted`); `closed` không nâng mức | `test_running_attempt…`, `test_verified…`, `ClosedIsNotAccepted` | đạt sau sửa P2-01 |
| B. Mở/xem bằng chứng trong phạm vi | `evidence()` chỉ blob mà sự kiện của root nêu (403), lọc từng dòng, 64 KiB; server không nới project | `test_evidence_only_for_keys…`, `test_get_only…`, `ProjectScope` | đạt sau sửa P2-04 |
| B. Thời gian chờ, ETA có căn cứ hoặc "chưa xác định" | `waits` (`open`/lịch sử, `until`), `measure.wait_seconds` + `executor_waits`, `_eta` | `test_eta_comes_from…`, `EndedWaits` | đạt sau sửa P2-03 |
| C. Cập nhật trong trần độ trễ | poll 2 s, mỗi request đọc sổ mới | `test_a_new_ledger_event…` (≤ 5 s), V6 đo `@@LAT@@` s | đạt (sổ nhỏ) |
| C. Mở lại/reconnect từ nguồn bền | không trạng thái phía server; timeline định danh `seq` | `test_restart_shows_the_same_timeline…`, V7 | đạt |
| C. Không nhân đôi sự kiện/attempt, không cộng đôi overlap | định danh `seq`; `observe` cùng key không ghi; union | `test_duplicate_observation…`, `test_overlapping_attempts…`, `EndedWaits` (wait trùng = một dòng) | đạt |
| C. Đóng UI không dừng worker | server tiến trình riêng, chỉ đọc, không giữ khóa | `test_closing_the_server…`, V8 (tắt server giữa bước `@@LONG@@` s của worker thật) | đạt |
| C. Nguồn thiếu/lỗi/mất kết nối hiển thị đúng | `source.status`; nhãn "MẤT KẾT NỐI … dữ liệu cũ" | `SourceTests`, `SourceProblemTests`, `test_the_page_says_disconnected…`, V11 proxy, ảnh | đạt |
| C. Phiên chưa được theo dõi | `untracked` + `statement` cố định | `test_tasks_outside_a_plan…`, V10, ảnh | đạt |
| UI và CLI cùng mô hình | `track list --json` = `overview()`; trang đọc `/api/overview` cùng hàm | `test_cli_json_is_the_same_model…`, V5, V13 (CLI và HTTP cùng kết luận) | đạt |
| Kiểm UI trực tiếp từ artifact ngoài checkout | Chrome headless `--dump-dom`/`--screenshot` qua gói | `BrowserTests`, `test_obs1_installed`, V11 | đạt trên Chrome (Edge headless không dump; limits) |
| Lọc dữ liệu nhạy cảm | `tracking.clean` (redact_line S1); evidence `redact` | `test_secret_in_the_goal…`, V9 | đạt (theo mẫu) |
| Không điều khiển task từ UI | không endpoint ghi; POST/PUT/DELETE → 405 | `test_get_only…`, V6 | đạt |

## 4. Cách dùng

- **Thử trọn gói:** `powershell -ExecutionPolicy Bypass -File "D:\OneCrewRuns\obs1\pkg\onecrew-2.4.0.dev7-obs1-beta\verify\thu-goi-obs1.ps1"` → `DAT … 13/13`.
- **Mở UI trên sổ thử của lượt kiểm:** `powershell -ExecutionPolicy Bypass -File "D:\OneCrewRuns\obs1\mo-trang-obs1.ps1"` (trình duyệt mặc định; P1 đã kiểm, P2 đã tạo, P3 đóng, P4 bị chặn, P5 chờ kiểm; project B chỉ khi `--all-projects`).
- **Project đang có OneCrew:** `BAT-DAU-THU.vi.md` §3–§5 trong gói: venv thử + `track open --project <p> --state-root <bản sao sổ>`; không nâng runtime thật (quyết định riêng sau Codex review).

## 5. Giới hạn (không biến thành tuyên bố hoàn tất)

`docs/obs1/limits-obs1.md` và `RELEASE-NOTES-OBS-1.vi.md`: worker giả; chỉ root/node/attempt trong sổ; liveness là quan sát; ETA chỉ khi có ước lượng; độ trễ đo trên sổ nhỏ; Chrome headless;
lọc theo mẫu; không xác thực (127.0.0.1); OBS-1 không phải toàn bộ roadmap (MR-R, OBS-2 chưa); bản sửa P2 chưa Codex review lại; gate 2.2 đầy đủ không chạy lại cho lát này;
wheel kiểm = wheel giao theo hash SHA256 (một lần dựng, không cần tái lập byte).

## 6. Việc thật sự cần chủ quyết

1. Codex review lại nhánh (diff `bf6994f..@@SNAP@@`, trọng tâm `tracking.py` `_waits`/`_current_progress`/`_level`, `tracking_web.py` 403) và nghiệm thu OBS-1 beta.
2. Có gộp `claude/onecrew-obs1` vào dòng 2.4 (sau dev6) hay giữ nhánh riêng; số prerelease kế tiếp của 2.4 là dev8.
3. Có cho project thật (SignSDK) *đọc* sổ bằng venv OBS-1 hay chờ nâng runtime chung; nâng runtime không nằm trong lượt này.
