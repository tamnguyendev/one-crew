# OBS-1 — báo cáo bàn giao: màn hình theo dõi chỉ đọc

Người lập: Claude (Fable 5.1), 03/11/2026. Nhiệm vụ: triển khai OBS-1 (roadmap §0.9, thiết kế §2.10, bàn giao Claude mục OBS-1) song song và cách ly với
phiên phát hành 2.4. Chưa Codex review, chưa nghiệm thu, không push/tag.

## 1. Kết quả ngắn

- **Nhánh** `claude/onecrew-obs1` (worktree `D:\TamNT\Workspace\11.OneCrew\wf-obs1`) tách từ `01b6f62` (2.4.0.dev6, đã xác minh là HEAD của `claude/onecrew-2.4`).
  Snapshot bàn giao: `@@COMMIT@@`, version `2.4.0.dev6+obs1` (nhãn local của lát; nhánh/gói 2.4 không đổi).
- **Điểm vào**: `onecrew track list|show|evidence|serve|open` (nhóm `track` của CLI cài). Một lệnh mở màn hình: `onecrew --project <p> --state-root <sổ> track open`.
- **Gói thử độc lập**: `@@PACKAGE@@` (wheel `@@WHEEL@@`, SHA256 `@@WHEEL_SHA@@`), kiểm từ gói `@@VERIFY@@`, báo cáo `@@REPORT@@`.
- **Test**: `tests/test_obs1_tracking.py` (18), `tests/test_obs1_web.py` (7, có trình duyệt headless), `tests/test_obs1_installed.py` (1, wheel ngoài checkout): đạt. Module liên quan sẵn có: `@@REGRESS@@`.
- **Số đo** (sổ thử, máy đang chạy gate 2.4 song song): độ trễ ghi sổ → trang `@@LATENCY@@` s (trần 5 s); đọc overview `@@READ_MS@@` ms/lần poll (poll 2 s mặc định).
- **Không đổi**: `claude/onecrew-2.4` vẫn ở `01b6f62`; gói `D:\OneCrewRuns\v24\pkg\onecrew-2.4.0.dev6-beta` không đụng; registry hook thật giữ hash `@@REGISTRY@@` trước/sau mọi lượt; `wf-v23-hf`, SDK, sổ thật không đụng.

## 2. Giải pháp (tóm tắt; chi tiết ở GIAI-PHAP-OBS-1.vi.md)

Một mô hình trạng thái đọc chung `onecrew/v2/tracking.py` (`overview`, `detail`, `evidence`) dựng từ sổ qua `report._Reader` (sqlite `mode=ro`,
`query_only`): plan.* (trạng thái root), `engine.state` (node/thế hệ/attempt, generation cũ bị bỏ), bảng `attempts` (root + task con), `executor.observed`
(liveness/chờ), `requests` (cần người dùng), `notice.exception`, `estimates.read` (ETA), `execution_mode.measure` (union thời gian attempt/chờ),
`managed_executor.hold_views`. CLI (`tracking_cli.py`) và trang web (`tracking_web.py`, `http.server` stdlib trên 127.0.0.1, chỉ GET, HTML một file, poll 2 s)
đọc đúng dict đó. Không sổ tiến độ riêng, không ghi, không model, không nút điều khiển.

## 3. Yêu cầu OBS-1 → code / test / bằng chứng → trạng thái

| Yêu cầu | Code | Test / bằng chứng | Trạng thái |
|---|---|---|---|
| A. Danh sách: project, mục tiêu, định danh task/root | `tracking._item` (`project`, `goal` = `understanding.restated_goal`, `id`, `selector`) | `test_obs1_tracking` (mọi ca), ảnh `obs1-list.png` | đạt |
| A. Trạng thái có nguồn: đang thực hiện / đang chờ / bị chặn / hoàn tất / chưa xác định | `tracking._status` → `{kind,label,reason,source[]}` | proposed→chờ duyệt; approved chưa step→chờ; attempt running→đang thực hiện; unknown→chưa xác định; held→bị chặn; verified→hoàn tất; accepted→đã nghiệm thu (`EngineTests`) | đạt |
| A. Thời gian đã chạy, cập nhật/bằng chứng gần nhất | `_elapsed` (approved→nay/accepted), `last_update`, `_last_evidence` (theo `observed_at`, kèm provenance) | `test_duplicate_observation…`, `test_verified…` | đạt |
| A. Việc thực sự cần người dùng | `_needs_user`: request pending (+ lệnh trả lời), duyệt, báo cáo dừng, nghiệm thu | `test_pending_request…` (đọc không trả lời), V6 | đạt |
| B. Node/attempt, root/child | `detail.nodes` (child task), `detail.attempts` (root + con), timeline gộp root + con theo `seq` | `test_running_attempt…`, V4 | đạt |
| B. Phát sinh, retry/generation mới, lý do có bằng chứng | `node.resumed`/`node.result_retained`/`node.held` trong timeline; `measure.rework`; `eta.last_change`; `notices` | `test_old_generation_event…` (thế hệ cũ không đổi trạng thái, timeline đánh dấu) | đạt |
| B. Phân biệt hoạt động / đã tạo / đã kiểm / đã nghiệm thu | `status.kind` (hoạt động) tách khỏi `level.kind` (`none/produced/verified/accepted`) | `test_running_attempt…` (child checkpoint completed không đánh xong), `test_verified…` | đạt |
| B. Mở/xem bằng chứng trong phạm vi | `evidence()` chỉ blob mà sự kiện của root nêu (403 nếu khác), lọc từng dòng, 64 KiB; `/api/evidence`, `track evidence` | `test_evidence_only_for_keys…`, `test_get_only_and_the_evidence_door` | đạt |
| B. Thời gian chờ, ETA có căn cứ hoặc "chưa xác định" | `waits` (mode wait + executor wait mở), `measure.wait_seconds` (union), `_eta` (khoảng, lý do, không %) | `test_eta_comes_from…`, root không engine → "chưa xác định" | đạt |
| C. Cập nhật trong trần độ trễ | poll 2 s (cấu hình 0.5–60), mỗi request đọc sổ mới | `test_a_new_ledger_event_shows_within_the_latency_ceiling` (≤ 5 s), V6 đo `@@LATENCY@@` s | đạt (sổ nhỏ) |
| C. Mở lại/reconnect từ nguồn bền | không trạng thái phía server/trang; timeline định danh `seq` | `test_restart_shows_the_same_timeline_without_duplicates`, V7 | đạt |
| C. Không nhân đôi sự kiện/attempt, không cộng đôi overlap | định danh `seq`; `observe` cùng key không ghi; union (`execution_mode.measure`) | `test_duplicate_observation…`, `test_overlapping_attempts…` | đạt |
| C. Đóng UI không dừng worker | server tiến trình riêng, chỉ đọc, không giữ khóa | `test_closing_the_server_leaves_a_running_worker_alone`, V8 (tắt server giữa bước 6 s của worker thật) | đạt |
| C. Nguồn thiếu/lỗi/mất kết nối hiển thị đúng | `source.status` missing/unreadable; nhãn "MẤT KẾT NỐI … dữ liệu cũ" | `SourceTests`, `SourceProblemTests`, `test_the_page_says_disconnected…`, V11 proxy, ảnh `obs1-disconnected.png` | đạt |
| C. Phiên chưa được theo dõi | `untracked`: task ngoài plan, project registry không plan, phiên hook; `statement` cố định | `test_tasks_outside_a_plan…`, V10, ảnh | đạt |
| UI và CLI cùng mô hình | `track list --json` = `overview()`; trang đọc `/api/overview` cùng hàm | `test_cli_json_is_the_same_model…`, V5 | đạt |
| Kiểm UI trực tiếp từ artifact ngoài checkout | Chrome headless `--dump-dom`/`--screenshot` qua gói | `BrowserTests`, `test_obs1_installed`, V11 | đạt trên Chrome; Edge headless không dump (ghi ở limits) |
| Lọc dữ liệu nhạy cảm | `tracking.clean` (redact_line S1) mọi chuỗi; evidence `redact` | `test_secret_in_the_goal…`, `test_unknown_attempt…`, V9 | đạt (theo mẫu) |
| Không điều khiển task từ UI | không endpoint ghi; POST/PUT/DELETE → 405 | `test_get_only…`, V6 | đạt |

## 4. Cách tạo một task thử và xem trạng thái đổi

Trong gói: `verify\thu-goi-obs1.ps1` làm trọn (task thật với `claude` giả trên sổ tạm, mở trang, chụp ảnh). Bằng tay: `BAT-DAU-THU.vi.md` §3 (cài venv thử,
`track open` trên sổ thử, chạy bài task đầu tiên của 2.4 hoặc một plan thật; dòng của plan đổi theo thứ tự chờ duyệt → chờ worker → đang thực hiện →
đã tạo, chờ kiểm → đã kiểm, chờ nghiệm thu → đã nghiệm thu).

## 5. Giới hạn (không biến thành tuyên bố hoàn tất)

Xem `limits-obs1.md`: worker giả; chỉ root/node/attempt trong sổ; liveness là quan sát; ETA chỉ khi có ước lượng; độ trễ đo trên sổ nhỏ; Chrome headless;
lọc theo mẫu; `track open` với trình duyệt thật chưa trong bộ tự động; version nhãn local; chưa Codex review; gate 2.2 đầy đủ không chạy lại.

## 6. Việc của chủ / Codex

Codex review nhánh `claude/onecrew-obs1` (diff từ `01b6f62`); chốt số version/tên gói OBS-1; nghiệm thu bằng `thu-goi-obs1.ps1` và `track open` trên
một sổ thử; quyết định gộp sau khi 2.4 phát hành (không gộp vào `claude/onecrew-2.4`).
