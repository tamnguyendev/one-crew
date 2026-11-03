# OBS-1 — UI theo dõi chỉ đọc: giải pháp, nguồn dữ liệu, testcase

Người lập: Claude (Fable 5.1), 03/11/2026, theo nhiệm vụ OBS-1 (roadmap §0.9, thiết kế §2.10, bàn giao Claude mục OBS-1). Baseline `01b6f62`
(2.4.0.dev6), nhánh `claude/onecrew-obs1`, worktree `D:\TamNT\Workspace\11.OneCrew\wf-obs1`. Nhánh release 2.4, gói dev6, sổ/registry thật không đổi.

## 1. Giải pháp (nhỏ nhất đủ đầu ra)

- **Một mô hình trạng thái đọc chung** `onecrew/v2/tracking.py`: `overview(state_root)` (danh sách) và `detail(state_root, plan)` (chi tiết + timeline),
  chỉ đọc sổ qua `report._Reader` (sqlite `mode=ro`, `query_only`). Không ghi sổ, không tạo sổ tiến độ riêng, không gọi model.
- **CLI cùng nguồn** `onecrew track list|show|serve|open` (`onecrew/v2/tracking_cli.py`): `list`/`show --json` in đúng JSON mà UI đọc.
- **UI web nhỏ** `onecrew/v2/tracking_web.py`: `http.server` stdlib trên `127.0.0.1`, chỉ GET (`POST/PUT/DELETE` → 405), trang HTML một file không tài
  nguyên ngoài; JS poll `/api/overview` mỗi 2 s (trần cập nhật đặt ở §4), `/api/task?plan=…` cho chi tiết, `/api/evidence?…&key=…` mở bằng chứng
  (chỉ blob mà sự kiện của root đó nêu, lọc bí mật, giới hạn 64 KiB). Không có nút điều khiển task.
- **Đóng UI không dừng worker:** server là tiến trình riêng, chỉ đọc, không giữ khóa sổ; worker (engine step) không biết đến nó.
- **Mở lại/reconnect:** UI không giữ trạng thái; mỗi lần poll dựng lại từ sổ (nguồn bền). Timeline định danh theo `(task, seq)` của sổ → không nhân đôi;
  sự kiện đến trễ hiển thị cả `observed_at` (nguồn thời gian của adapter) và `received_at`/`created_at` (lúc sổ nhận).
- **Lọc bí mật:** mọi chuỗi đưa lên UI/JSON đi qua `diagnostics.redact_line` (bộ lọc S1) + bỏ ký tự điều khiển; không đưa môi trường, prompt hay transcript.

## 2. Nguồn dữ liệu (giữ/nối, không viết lại)

| Hiển thị | Nguồn (có sẵn) | Ghi chú |
|---|---|---|
| Project, mục tiêu, định danh task/root | `tasks` (`request_key plan:`/`plan-ns:`), `plan.derive`, hợp đồng (`plan.load`) | goal = `contract.goal`/`title`; id = task id + selector |
| Trạng thái root | `plan.derive.status` (proposed/approved/accepted/stopped_with_report/closed) | nguồn = sự kiện plan.* |
| Node/generation/attempt, root/child | `engine.state` (chỉ root `sequential-engine`), bảng `attempts` (root + child task), `node.started.child` | generation cũ bị `engine.state` bỏ qua; timeline đánh dấu "thế hệ cũ" |
| Đang có hoạt động (liveness) | `executor.observed what=progress` (`progress_track`), trạng thái attempt (`reserved/running/unknown/settled`) | im lặng không suy "không tiến triển"; `unknown` = chưa xác định |
| Đã tạo / đã kiểm / đã nghiệm thu | `node.produced` / `node.verification pass` / `node.accepted`; plan: `verdict.recorded`, `milestone.passed`, `plan.accepted` | tách bốn mức, không gộp |
| Bị chặn | `node.held`, `finding_blockers`, `unknown_blockers`, `failed_blockers`, `workflow.recovery_decided` (blocked/diagnose), checkpoint progress `blocked` | lý do kèm nguồn |
| Chờ, phát sinh, retry | `workflow.mode wait`, `executor.observed what=wait`, `node.resumed` (generation mới), `node.result_retained`, `estimates additional` | thời gian chờ = union (`execution_mode.measure`) |
| Cần người dùng | `requests state=pending` (+ `request reply` command), root `proposed` (duyệt), `stopped_with_report`, mọi mốc passed mà chưa accept (nghiệm thu) | đọc/ACK không duyệt |
| Thời gian đã chạy | `plan.approved` → nay/`plan.accepted`; attempt wall = union span (`measure.attempts_wall_seconds`) | không cộng đôi overlap |
| ETA | `estimates.read` (`remaining_seconds` khoảng, `wall_clock_remaining_seconds`, `remaining_reason`) | thiếu → "chưa xác định", không phần trăm |
| Bằng chứng gần nhất | receipt của `node.produced`/`node.verification`/`verdict.recorded`, `executor.observed` (`observed_at`, `time_source`) | mở blob qua `/api/evidence` |
| Chưa được theo dõi | task không phải plan (v1: chỉ `workflow.checkpoint.phase`), project trong registry hook (`where.registry_file`) chưa có plan, phiên hook (`.onecrew/hook-state.json`) | ghi rõ "chưa được theo dõi"; phiên chat ngoài OneCrew không có nguồn |

## 3. Testcase (ca lỗi trước)

1. Không có sổ / sổ hỏng → overview báo `source` lỗi, không raise, UI hiện "nguồn thiếu".
2. Root proposed → chờ duyệt; cần người dùng = duyệt. 3. Approved chưa step → chờ (chưa có attempt), không "đang chạy".
4. Attempt running, child task ghi checkpoint `completed` → node vẫn running (attempt chưa settled). 5. Attempt `unknown` → chưa xác định.
6. `node.resumed` → generation 2; `node.produced` generation 1 đến sau → không đổi trạng thái; timeline ghi "thế hệ cũ".
7. `node.held` / finding / unknown mở → bị chặn kèm lý do. 8. Request pending → cần người dùng; không hoạt động → chờ người dùng.
9. Mọi node verified → hoàn tất mức "đã kiểm" + cần nghiệm thu; `plan.accepted` → "đã nghiệm thu".
10. Cùng key quan sát ghi hai lần → một dòng; `observed_at` sớm hơn dòng trước → vẫn theo seq, bằng chứng mới nhất theo `observed_at`.
11. Hai attempt chồng thời gian → thời gian chạy = union. 12. Bí mật trong goal/câu hỏi/receipt → `[withheld]` trong JSON, HTML, evidence.
13. Không có estimate → ETA "chưa xác định" + lý do; có → khoảng. 14. Task v1 và project registry không plan → "chưa được theo dõi".
15. Web: GET ok, POST 405, evidence key lạ 404, key không thuộc root 403; sự kiện mới hiện trong ≤ trần; server tắt → mở lại cùng dữ liệu, không trùng;
    server tắt giữa lúc worker chạy → worker vẫn `produced`. 16. Từ wheel ngoài checkout: `track list --json`, server, trang HTML render (Edge headless `--dump-dom`).

## 4. Trần độ trễ và chi phí (đặt trước, đo sau)

- Trần cập nhật: sự kiện ghi vào sổ xuất hiện trên UI trong **≤ 5 s** (poll 2 s + đọc sổ). Đo bằng test 15 và từ gói (`verify_obs1.py` V6).
- Chi phí quan sát: thời gian `overview()` trên sổ thử ghi vào báo cáo; server không giữ transaction giữa hai lần poll.

## 5. Review Codex 03/11 (snapshot `bf6994f`): bốn P2 và cách khép

Phản chứng: `D:/OneCrewRuns/codex-obs1-review-20261103/probe.py` (chạy trên wheel đã cài). Test đỏ-trước-xanh-sau đi qua sổ/engine (P2-01..03) và HTTP (P2-04): `tests/test_obs1_p2.py`; từ gói: bước `V13-p2-findings` của `verify_obs1.py` (scenario `p2`).

| # | Lỗi | Nguyên nhân | Sửa |
|---|---|---|---|
| P2-01 | `plan.closed` hiện "đã nghiệm thu" dù node chưa chạy | `_level` gộp `closed` với `accepted` | `_level`: chỉ `plan.accepted` là nghiệm thu; `closed` lấy mức từ node (none/produced/verified). Trạng thái `done` với lý do "đã đóng (đóng không phải nghiệm thu; đầu ra: …)" |
| P2-02 | quan sát blocked của attempt cũ đến muộn làm attempt mới hiện "bị chặn" | progress lấy "mới nhất theo node", không ràng attempt | `_progress_rows` giữ mới nhất theo (node, attempt); `_current_progress` chỉ lấy dòng của attempt mà `engine.state` ràng vào node; timeline đánh dấu `stale_attempt` ("attempt cũ"); quan sát của attempt hiện hành vẫn chặn |
| P2-03 | khoảng chờ đã ghi `until` vẫn là "đang chờ" | mỗi sự kiện wait xét riêng, không đối soát theo (attempt, ref) | `_waits`: một dòng mỗi (attempt, basis ref) như `executors.summary`; bất kỳ bản ghi có `until` đóng nó, trùng/đến muộn không mở lại; attempt đã kết thúc → `until = unknown`, không hiện hành; mỗi dòng có `open`; `measure.executor_waits` giữ số đo; attempt đang chạy có wait mở → "đang chờ" với lý do của executor |
| P2-04 | server `--project-only` A trả 200 cho `project_id=B` | `scope = query hoặc server` | `project_id` của query ≠ project của server → 403 cho mọi đường `/api/*`; bằng project của server → 200; mọi project (không `--project-only`) vẫn thu hẹp được |
