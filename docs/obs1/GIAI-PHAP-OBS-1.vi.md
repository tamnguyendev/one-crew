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

## 6. Review Codex UX trên `2.4.0.dev7` (03/11): UX-01…UX-08 + P2 định danh server và cách khép

Bằng chứng review: `D:\OneCrewRuns\codex-obs1-ux-review-20261103\observations.json` (+ 3 ảnh), `D:\OneCrewRuns\codex-obs1-dev7-review\reuse-result.json`, `wrong-state-result.json`. Ma trận tình huống → thao tác → expected → cách kiểm viết trước khi sửa: `UX-OBS-1.vi.md`. Bố cục chốt: tổng quan → chi tiết task → timeline theo phần việc/attempt → bằng chứng của từng bước (học cách phân cấp của Blazo, MIT, không mượn code/tài sản; gói vẫn stdlib).

| ID | Vấn đề (trên dev7) | Cách khép (dev8) | Kiểm |
|---|---|---|---|
| UX-01 | poll dựng lại chi tiết → đóng phần đang đọc | chi tiết chỉ dựng lại khi `seq` đổi; khi dựng lại: chụp/khôi phục mục đang mở (`data-k`), focus, cuộn, bước đang chọn, nội dung bằng chứng đã mở | harness `ux01` (≥ 3 poll yên + một lần ghi sổ) ở 1280 và 390 |
| UX-02 | đổi project vẫn hiện chi tiết project cũ | đổi lọc project → nếu task đang chọn không thuộc project đó: bỏ chọn, placeholder nêu project, URL bỏ `plan` | harness `ux02` |
| UX-03 | câu hỏi chỉ hiện lệnh `<option-id>` | thẻ câu hỏi: câu hỏi, vì sao, ảnh hưởng, từng lựa chọn (nhãn, id, khuyến nghị) + lệnh đã điền `--choice <id>` + nút "Sao chép lệnh" (clipboard/fallback, hiện "đã sao chép: …"); không nút trả lời | `test_obs1_ux.QuestionCommands`, harness `ux03` (sao chép đúng lệnh, sổ không đổi) |
| UX-04 | chi tiết ở cuối trang, dòng không có điều khiển bàn phím, URL không đổi | hai cột (chi tiết cố định) / màn hẹp chuyển view; dòng `role=option tabindex=0`, ↑↓/Home/End/Enter/Esc, Enter focus tiêu đề chi tiết, Esc trả focus về dòng; `pushState`/`popstate`, reload giữ task, Back về task trước/danh sách | harness `ux04` ở 1280 và 390 |
| UX-05 | "hoàn tất" xanh cho plan đóng; "đã chạy" gồm cả chờ | `status.outcome` + `OUTCOME_WORDS` (đã nghiệm thu xanh lá / đã kiểm, chờ nghiệm thu xanh ngọc / đã đóng xám); thẻ "Từ khi duyệt (lịch)" / "Thực hiện (attempt)" / "Chờ"; CLI "từ khi duyệt" | `test_obs1_ux.OutcomeWords`, harness `ux05` |
| UX-06 | timeline seq giảm, không nhóm, `stale_attempt` không hiện | nhóm theo plan và từng phần việc, cũ → mới, "lịch sử cũ (n)" gập (đánh dấu stale), "chi tiết kỹ thuật (n)" gập, bấm bước → bằng chứng của bước | harness `ux06` |
| UX-07 | danh sách dày kỹ thuật, bằng chứng chỉ hash | dòng: trạng thái · tên · mục tiêu · bước hiện tại (`current_step`) · cập nhật tương đối · "cần bạn"; ID/đường dẫn/adapter mờ; `evidence_index` (tên/loại/thời điểm/phần việc) | `test_obs1_ux.EvidenceIndex`, harness `ux07` |
| UX-08 | 390 px: trang rộng 1103 px | một cột < 900 px, danh sách ↔ chi tiết, bảng kỹ thuật `overflow:auto` riêng, không cuộn ngang trang | harness `ux08` ở 1280/640/390 (đo `scrollWidth`) |
| P2 server | `track open` dùng lại server wheel cũ / sai sổ khi cổng bị dùng lại | `instance` + `version` + `state_root` + `project_id` + `pid` trong marker và `/api/health`; `reusable()`; khóa mở đồng thời; `track status|stop`; script mở/dừng đi qua `track open|stop` | `test_obs1_ux.ServerIdentity/DetachedOpen`, V15 |

## 7. Review Codex UX trên `2.4.0.dev8` (03/11 ~11:15): hai P2 + UX A–D và cách khép (dev9, local)

| ID | Vấn đề | Nguyên nhân | Khép | Kiểm |
|---|---|---|---|---|
| P2-A | "Từ khi duyệt" 16m44s không đổi qua các poll, reload mới nhảy | đồng hồ cộng `(now − poll cuối)` vào giá trị đã dựng; poll không đổi seq không dựng lại nhưng dời mốc | mốc dựng `data-live-at` gắn với giá trị; tiến theo đồng hồ máy từ mốc; dựng lại/đổi task/reload = giá trị có nguồn mới + mốc mới; kết thúc/chưa duyệt không chạy | harness `clock` (đỏ trên dev8, xanh dev9: ±2 s qua 3 poll, reload, đổi task, P3 đứng, PB chưa xác định); `ElapsedClock` giờ giả |
| P2-B | lệnh trả lời thiếu `--reference` (bắt buộc), thiếu project/sổ | model sinh lệnh tối thiểu | mẫu lệnh đầy đủ với placeholder đánh dấu; `reply_note`; nút "Sao chép mẫu lệnh"; copy hỏng báo hỏng | unit `QuestionCommands` (parser thật từ cwd có khoảng trắng: thiếu → 2, điền → ghi sổ thử); V16 từ wheel; harness `ux03` (clipboard thật) |
| 402 px | `scrollWidth` 402 ở 390 px khi đường dẫn project dài | `label` flex `min-width:auto` + select rộng theo option | `label{min-width:0;max-width:100%}`, `select{min-width:0}` | `ux08` liệt kê phần tử tràn; fixture tên thư mục dài; `ux08` cả khi mở mẫu lệnh |
| A | danh sách dày, không nhận nhóm | — | chip "cần bạn / bị chặn / đang thực hiện (n)"; cột danh sách thu gọn khi đọc chi tiết (ẩn ID/đường dẫn) | `ux07`, `ux03b` |
| B | nhiều câu hỏi đẩy tóm tắt xuống | câu hỏi trước thẻ số liệu, luôn mở | vùng đầu: bước hiện tại + "n câu hỏi chờ bạn"; thẻ số liệu trước; mục "Cần bạn (n)" gập từng câu, không gộp, giữ mở qua poll | `ux03b` (1280 và 390) |
| C | timeline/bằng chứng thiếu trực quan | — | thanh thời lượng attempt khi có mốc kết thúc + số đo; đang chạy "chưa xác định"; không ETA/phần trăm | `ux06` |
| D | held/pending/none là lời giải thích duy nhất | nhãn thô | pha/đầu ra tiếng Việt, mã gốc ở `title`; "lý do (engine)"; badge có ký hiệu | `ux05` |

## 8. Hướng thiết kế chủ chốt 03/11 ~13:30 (dev10): timeline Gantt/waterfall + hai P2 của dev9

| Mục | Cách làm | Nguồn dữ liệu / kiểm |
|---|---|---|
| Cây phần việc → lượt | `detail.gantt.rows` (một hàng mỗi attempt dưới node của nó, `current`/`active`, thế hệ), hàng Plan cho dấu mốc plan; gập từng phần việc, lượt cũ gập "lịch sử (n)" mờ | `attempts` + `node.started` (attempt→node); harness `gantt` (P4 lịch sử) |
| Cùng trục thời gian | `axis.start/end` = min/max mốc có nguồn; `end` = hiện tại khi còn lượt active (`extends_to_now`); vạch 5 mốc; đường "hiện tại" | T: left/width mỗi đoạn so với mốc JSON ≤ 0,6 % |
| Đại lượng | `reserved` (created_at→launched), `execution` (launched→updated_at khi settled), `wait` (executor wait có until), `verification` (produced→verification), `to_now` (mốc mới nhất→now, chưa xác nhận) | `_timeline_spans`; unit `GanttSpans`; T P5 chờ, P4 `to_now` |
| Chồng lấp | P8 hai lượt chạy đồng thời (run_batch slots=2, executor isolate) | T rect giao nhau; model không cộng (union đã có ở measure) |
| Ngăn chi tiết | lượt: đặt chỗ/bắt đầu/kết thúc/thực thi/chờ/kiểm/lý do giữ/quan sát/bằng chứng (evidence_index theo attempt hoặc node); dấu mốc: sự kiện + bằng chứng của seq | T chọn + 3 poll + resize |
| P2-A | `data-k = need:<id>:<revision>`; `knownNeeds` + ghi chú `stale-need` khi request mở biến mất/đổi bản; bỏ `copied` | T `p2a` (trả lời qua CLI thật trong lúc đọc), đỏ dev9 |
| P2-B | `_quote` nháy đơn PowerShell, `_runtime()` = `& '<venv>\Scripts\onecrew.exe'`, `reply_shell` | unit qua `powershell.exe` thật (`$SDK = "CHANGED"`), V16 đường dẫn `demo$SDK 'q' (a)&b``t`, đỏ dev9 |

## 9. Review Codex trên `2.4.0.dev10` (`5e66903`, 03/11 ~16:00): ba P2 + một P3 và cách khép (dev11, local)

| # | Finding (Codex) | Nguyên nhân | Cách khép | Kiểm / phản chứng |
|---|---|---|---|---|
| P2-A | đoạn "tới hiện tại" đứng khi seq không đổi (`tracking_web.py` `loadDetail` bỏ qua dựng lại) | phần đồng hồ của timeline phụ thuộc `axis.now` của reply, nhưng reply không đổi seq bị bỏ | poll không đổi seq: nhận `detailData` mới + `repaintGantt()` (giữ chọn/gập/focus/cuộn); mất kết nối → đóng băng + nhãn; nối lại → theo reply; không dùng đồng hồ máy | harness `gantt_now` (đo `data-to`/pixel qua 3 mẫu, chặn/mở `/api/*`); đỏ dev10 `red-on-dev10` |
| P2-B | lượt hiện hành thế hệ mới hiện "thế hệ 0 đã tạo đầu ra" (`gside` lọc theo node khi `current`) | `evidence_index` không có thế hệ, một mục mỗi khóa (khóa nội dung chung giữa thế hệ), lọc theo node | mục theo (khóa, phần việc, thế hệ, lượt) + `generation` ở mọi mục; lọc theo lượt / (phần việc, thế hệ); tách đầu ra ↔ bằng chứng khác; "chưa có đầu ra"; `rows[].inherits` từ `resume_artifact`/`retained_candidate`/`continues` của view với nguồn | fixture P9; harness `evid`; unit `EvidenceByGeneration`; đỏ dev10 |
| P2-C | so chuỗi ISO khác offset (`tracking.py` `_timeline_spans`) | `max()`/`>` trên chuỗi | mọi so sánh/min/max/sắp xếp trên `_at()` (UTC); phát ra `_iso`; mốc hỏng bỏ | unit `TimelineClock` (trộn `+07:00`/UTC/âm/qua ngày/cùng thời điểm/observed≠received); đỏ dev10 (cuối trục = chuỗi +07:00) |
| P3-D | 1280×720 chật/cắt, P8 cần cuộn ngang | danh sách 1fr/2.4fr + cây 210 + `min-width` 640 + ngăn phải 280 ở ≥ 1100 | 1fr/3.4fr; cây 170; bỏ min-width ≥ 900; ngăn dưới tới 1400; nhãn vạch đầu/cuối trong biểu đồ | harness `gantt` desktop (`scrollWidth ≤ clientWidth`); ảnh 1280/640/390; đỏ dev10 (667 > 540) |

## 11. Review Codex trên `2.4.0.dev12` (`4cdb384`, 04/11 sáng): một P2 và cách khép (dev13, local)

| # | Finding (Codex) | Nguyên nhân | Cách khép | Kiểm / phản chứng |
|---|---|---|---|---|
| P2 | chi tiết task "đang tải" mãi khi `/api/task` trả lời chậm hơn 20 s (25 s: sau 82 s, 4 request, 3 trả lời xong, UI vẫn tải) | `loadDetail` của trang thay lượt đọc chi tiết đang chờ quá 20 s bằng lượt mới ở mỗi poll; trả lời của lượt cũ bị bỏ. Trả lời ~25 s → lặp mãi, "đang tải chi tiết…" không bao giờ kết thúc | mỗi task đang chọn chỉ có một lượt đọc; poll (hay bấm lại đúng task đó) chờ lượt đang chạy, không thay nó; chờ tối đa 45 s (dòng "đang tải" đếm số giây đã chờ); quá 45 s → trang hủy lượt đó và báo "quá 45 s không có trả lời"; sau 3 lần quá hạn mà chưa có trả lời nào được hiện → ngừng tự thử, hiện nút "Thử lại"; lỗi trả về ngay (mạng, HTTP) không đếm và không xóa chuỗi đó, vẫn thử lại sau mỗi lần làm mới danh sách như R4; chỉ một trả lời được hiện mới kết thúc chuỗi; bấm vào một task (kể cả task đang xem), bấm nút, hoặc nối lại kết nối mở chuỗi mới; trong lúc thử lại, dòng trạng thái và đầu trang ghi "đang thử lại" kèm số giây; sau "Thử lại" bằng bàn phím, focus ở lại dòng trạng thái rồi về tiêu đề task; đổi task hay đóng task hủy lượt đọc đang chạy (mở lại là lượt mới, trả lời muộn của lượt cũ không bao giờ chạm trang). Tìm thêm khi sửa, cùng loại lỗi: overview treo thì trang đứng yên dưới huy hiệu "kết nối OK" → đọc overview nay chờ tối đa 5 phút (overview chỉ chậm vẫn chạy như dev12; không bao giờ trả lời thì huy hiệu báo MẤT KẾT NỐI). | fk_slow25, fk_cycles, fk_switch, fk_timeout (1280, 390), fk_timeout1, fk_disc, fk_ovhang, fk_ovslow, fk_mixed, fk_reselect, fk_reconnect (đồng hồ giả) và rt_slow (thời gian thực): đỏ trên trang dev12 (hoặc trên bản sửa trước review cho bốn kịch bản của review), xanh trên bản sửa; V14 của gói |

## 10. Review phát hành độc lập của Codex trên `2.4.0.dev11` (`7c8bfca`, 03/11 ~20:57): bốn P2 + một P3 và cách khép (dev12)

Bằng chứng của Codex: `D:\OneCrewRuns\codex-obs1-release-review\review.json` (+ `audit.py`, `api-audit.json`, `stale-detail.json`). Không dùng số PASS cũ để khép finding: mỗi finding có test đỏ trên code dev11 trước khi sửa, xanh sau khi sửa, và được kiểm lại từ wheel cuối.

| # | Finding (Codex) | Nguyên nhân | Cách khép | Kiểm / phản chứng |
|---|---|---|---|---|
| R1 | bằng chứng lẫn nguồn gốc: hai thế hệ cùng bytes → nhãn của thế hệ 1 hiện ở thế hệ 0; cùng khóa vừa kế thừa vừa tạo mới bị lọc mất; 340 sự kiện với cửa sổ 300 → "lượt này không có đầu ra" | trang gán nhãn bằng bảng khóa → một mục (mục sau thắng); `evidence_index` dựng từ cửa sổ timeline (300) và giữ một mục cho mỗi (khóa, phần việc, thế hệ, lượt); ngăn bước bỏ khóa đã có ở "Kế thừa"; sự kiện `attempt.*` mang thế hệ điều khiển của lượt (luôn 1), không phải thế hệ của phần việc | `evidence_index` = một mục cho mỗi lần dùng (seq sự kiện, khóa): loại, thời điểm, phần việc, thế hệ, lượt (+ căn cứ: của sự kiện / `node.started` / trạng thái engine), vai trò trong payload, là đầu ra hay không; dựng từ TOÀN BỘ lịch sử root + task con (nguồn Gantt đã đọc, không truy vấn thêm), không từ cửa sổ hiển thị; lượt của `attempt.*` lấy (phần việc, thế hệ) từ `node.started` của lượt đó; cửa bằng chứng kiểm thành viên trên toàn lịch sử (lọc `instr` trong SQL rồi đọc payload); trang: nhật ký liệt kê lần dùng của đúng sự kiện, ngăn bước liệt kê đầu ra của lượt và riêng phần kế thừa kèm lần dùng nguồn, dấu mốc hiện đúng lần dùng của sự kiện, mục "Bằng chứng" gom lần dùng theo blob (tối đa 8 dòng/blob: 4 đầu + 4 cuối), nhật ký ghi "đang hiện X/Y sự kiện mới nhất; N sự kiện cũ hơn chưa tải…". Review vòng 2 của nhóm: phần kế thừa của MỌI dòng (cũ hay hiện hành) suy từ `node.resumed` đã mở thế hệ của dòng (`resumed_seq`, nguồn), không còn chỉ dòng hiện hành theo bản ghi engine (`retained_candidate` không còn ở "Kế thừa", vẫn là bằng chứng `node.held` của lượt); chỉ khóa có trong kho là bằng chứng; review vòng 3 (sổ thật: mọi đầu ra của engine là ảnh chụp manifest, vòng 2 gọi tất cả là "không có trong kho") → người điều phối sửa: khóa phân loại theo toàn bộ kho — blob, ảnh chụp (`snapshots/manifests`) hay không có (`evidence_index[].stored`), ảnh chụp mở ra JSON danh sách tệp; `project_id`, revision, sha của plan không bị liệt kê; `estimate.*` không phải lần dùng bằng chứng (1.197 mục nền ước lượng trên một root thật, gấp 2,5 lần dữ liệu); dòng timeline liệt kê đúng lần dùng của chính sự kiện; cửa bằng chứng trả 404 thay vì 503 cho khóa không có trong kho | U `test_obs1_r1_provenance` (đỏ 6/6 trên dev11); T `prov` (đỏ 6/9 kiểm trên dev11); review khép finding phát hiện lỗi thế hệ của `attempt.*` → sửa vòng 1 + ca đỏ riêng; gói V17; probe Codex chạy lại trên wheel dev12 |
| R2 | server chỉ project A trả đường dẫn và sổ của project khác trong `untracked.registry_projects_without_plan` | `_untracked` liệt kê mọi project của registry hook, không biết phạm vi; so chuỗi đường dẫn | phạm vi áp cho TOÀN mô hình trả ra; mục registry so theo định danh của sổ (`project_identity` = digest đường dẫn đã resolve + normcase, như `Ledger.project_id`), không theo chuỗi/tiền tố; dưới phạm vi chỉ còn mục của chính project (khi chưa có plan); chế độ mọi project giữ nguyên; `?project_id=A` trên server mọi project = phạm vi A | U `test_obs1_r23_scope_secrets` R2 (đỏ 6/6 trên dev11); probe Codex trên dev12: không còn OTHER-PRIVATE, B tường minh 403; gói V17 |
| R3 | `password=…` đi nguyên ra ở `waits[].ref` và `measure.executor_waits[].ref` | vài trường thô đi thẳng ra, không qua `clean` | các trường thô qua `clean` (không cắt id/ref); thêm MỘT chốt đầu ra `outward`: mọi chuỗi (khóa và giá trị) của overview/detail/evidence, hai bản chữ, mọi thân JSON của HTTP (cả health và lỗi) và JSON lỗi của CLI đi qua `diagnostics.redact_line` từng dòng, không cắt độ dài; chuỗi không khớp mẫu giữ nguyên từng byte (id, đường dẫn, khóa 64-hex, mẫu lệnh trả lời); sổ không đổi | U R3 (đỏ 2/4 trên dev11; hai ca dương tính xanh từ đầu), tăng cường lúc gộp; probe Codex: ref thành `password=[withheld]`, sổ vẫn giữ bản gốc; gói V17. JSON định danh của `track status/open/stop/serve` giữ nguyên có chủ đích (script ghim dùng đúng giá trị đó); định danh sổ so bằng `state_root_id` để chốt lọc không làm hỏng dùng lại/dừng |
| R4 | mất `/api/task` thì URL và dòng chọn là P8 nhưng nội dung, mẫu lệnh trả lời vẫn của P1 | trang coi `detailData` là "dữ liệu đang hiện" mà không biết của task nào; lỗi mạng bị nuốt; nhánh lỗi HTTP giữ dữ liệu cũ; chọn task khác giữ ngăn cũ tới khi có trả lời | dữ liệu chi tiết gắn với lựa chọn đã tải nó (`detailFor`, `mine()`): mọi chỗ dùng (vẽ, sao chép, bằng chứng, liên kết) chỉ dùng dữ liệu của lựa chọn hiện hành; chọn task khác → tiêu đề của task đó + "đang tải chi tiết…" ngay; lỗi (mạng, HTTP, trả lời không đọc/vẽ được) với task chưa tải → tiêu đề + lỗi, không câu hỏi/mẫu lệnh; với task đang hiện → giữ dữ liệu + cảnh báo độ mới cạnh tiêu đề + đánh dấu mẫu lệnh là của lúc đó (chỉ thẻ có mẫu lệnh nhắc `--revision`); `#conn` chỉ nói tổng quan, `#dconn` nói độ mới chi tiết; khôi phục vẽ lại một lần giữ phần đang mở/focus/cuộn. Gộp: yêu cầu chi tiết đang chạy được chờ thay vì bị thay ở mỗi poll (trước đây chi tiết chậm hơn chu kỳ poll không bao giờ hiện); lỗi khi áp dụng trả lời vào đường lỗi; bản sao chép xong muộn không ghi vào trạng thái đã đổi; ô "Từ khi duyệt" neo vào lúc nhận dữ liệu (không nhảy lùi) | T `stale_detail` desktop + mobile (đỏ 35/59 kiểm mỗi cỡ trên dev11); T `slow_detail` (đỏ trên nhánh gộp trước bản sửa); gói V14 |
| R5 | `mo-/dung-trang-obs1-dev11.ps1` mỗi script tự chọn thư mục `thu-goi-dev11-*` mới nhất: mở A, có B mới hơn, dừng B; có thể chọn lần chạy hỏng | script của người điều phối quét thư mục theo LastWriteTime, không ghim phiên, không kiểm biên nhận | cặp script ghim cứng cho bản phát hành, sinh bởi `tao-loi-vao-obs1.py` từ gói + lần chạy có biên nhận pass của đúng gói (từ chối lần chạy hỏng, gói/commit/version khác, wheel đã cài khác wheel của gói); không quét thư mục; script chung trong gói có `-PinFile` (ghim url, pid, instance, version, sổ, phạm vi); dừng theo định danh (`track stop` với url + instance + pid: chỉ dừng đúng server đó, kể cả khi marker đã thuộc server khác); mở từ chối trước khi khởi động gì nếu phiên ghim cùng sổ còn sống mà lần mở này không dùng lại được; `track open` chờ server tới 30 s và khi hết giờ dừng chính server con nó vừa tạo; hướng dẫn/báo cáo chỉ trỏ tới cặp ghim cứng; script quét thư mục cũ đánh dấu lỗi thời (giữ làm bằng chứng) | PS `test_loi_vao_obs1.ps1` (dev tool, đỏ trên script cũ); U `test_obs1_ux` (dừng theo định danh, mở hết giờ; vòng 5: không qua proxy, đường dẫn tương đối, đọc lại marker dưới khóa); PS T16–T21 (proxy, đường dẫn tương đối, sổ dưới thư mục có tên giống bí mật, ghim bị lần chạy khác ghi giữa chừng, ghim không ghi được, `--replace`); gói V15 + V17 |
