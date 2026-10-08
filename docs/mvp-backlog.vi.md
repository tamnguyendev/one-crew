# Kế hoạch triển khai OneCrew — 09/10/2026

Đích: giao yêu cầu đã làm rõ từ Codex/Claude/Kiro cho một core local; tiếp tục qua đổi entry/worker, review từng phần và chạy công việc liên quan trong scope/budget. [Kiến trúc](architecture.vi.md) và [SPEC-006](../specs/SPEC-006-portable-orchestration.md) là baseline. [Backlog 08/10](mvp-backlog-2026-10-08.vi.md) giữ lịch sử; không triển khai song song hai roadmap.

## 0. Điểm xuất phát và nguyên tắc nghiệm thu

Đã có CLI spec, runtime local/Codex cho profile CV cố định, gate/review/repair/checkpoint và preview. SPEC-005 có live delivery và 69 tests ghi nhận; xem [evidence](incremental-autonomy.vi.md). JEV đã kết nối; chưa làm semantic routing. Chưa có general planner, inbox đa entry, crash resume, worker Claude/Kiro, scheduler song song hoặc job 8 giờ.

Mỗi mốc cần một kết quả người dùng thử được, code/commit/evidence và giới hạn còn lại; không tính tài liệu kiến trúc là feature hoàn tất. Mốc đang chờ approval chỉ giữ nhánh phụ thuộc. Không kéo thêm dashboard/roles/JEV vào đường găng. Gate phù hợp từng thay đổi; không lặp full suite khi không có thay đổi hoặc nghi vấn mới.

## 1. P1 — Một task tổng quát, lưu bền và tiếp tục được

Phạm vi: nền OC02/OC03/OC05/OC06/OC09/OC12 và CLI contract OC01; một Codex worker tuần tự.

- Xây core local một instance, schema SQLite versioned, event/outbox, task/attempt/grant/request/checkpoint và root counters. Mutation có idempotency/revision checks; query không gọi model.
- Nối profile mới từ spec được giao và repo thực tế sang plan có AC coverage/ownership; hai feature khác profile CV để chứng minh không hardcode.
- Thêm inbox CLI; lỗi kỹ thuật trong scope tự sửa có giới hạn; ambiguity/out-of-scope tạo request ngắn. Core giữ thẩm quyền, workers không được sửa ledger/grant/gate.
- Dispatch intent/lease/process identity, stop/reconcile và checkpoint gồm dirty diff. Resume sau crash giữ budget, không lặp side effect chưa rõ. Đóng chat không dừng core.
- Output card đầu tiên có snapshot/diff/checks/cách thử; chưa cần UI dashboard.

Điều kiện qua mốc: một task có thể dừng chờ câu trả lời, core restart, trả lời qua CLI rồi tiếp tục; một task khác cấu trúc cũng sinh plan đúng repo. Fault tests chứng minh một writer, duplicate/stale event bị chặn, cancel có xác nhận. Không tuyên bố hỗ trợ mọi backend hoặc 8 giờ ở P1.

**Lát code đầu tiên:** task ledger + submit/status/request-reply bằng CLI, một task tuần tự, persistence và revision/idempotency. Sau đó nối Codex và crash reconciliation trên cùng contract. Không bắt đầu bằng thêm evaluator hoặc dashboard.

## 2. P2 — Giao và tiếp tục việc từ ba công cụ

Phụ thuộc P1 đạt; hoàn thiện OC01/OC04/OC05/OC06 và ranh giới OC12.

- Thin connector/skill/agent configuration cho entry Codex, Claude, Kiro; CLI chung trước. MCP chỉ thêm nếu host cần. Ghi rõ entry nào/phiên bản nào đã kiểm chứng.
- Worker adapters Codex, Claude Code, Kiro CLI; capability registry có version, account/auth mode, cancel/reconcile và usage source. Không giả native session chuyển qua provider khác.
- Handoff entry Kiro→Claude cùng task/request; không restart worker. Handoff worker qua stop/reconcile/snapshot với budget giữ nguyên.
- Caller provenance/capability, trusted reply path; không chuyển local spec approval thành authenticated grant bằng nhãn actor.

Điều kiện qua mốc: từng entry submit/connect/query/reply thật; từng worker chạy, verify và cancel thật; ít nhất một cross-provider handoff. Thiếu auth/capability ghi Blocked cho adapter liên quan, không gọi fixture là integration live. Chứng minh worker không thể giả reply qua đường điều khiển được cấp.

## 3. P3 — Hai việc song song, review và ghép kết quả

Phụ thuộc core/authority/recovery P1; dùng adapters đã đạt P2. Hoàn thiện OC07/OC08/OC11.

- Hai worker toàn core, DAG/ownership/worktree; contract trước, overlap tuần tự. Capacity và reservation kiểm cả nhiều root.
- Integration owner ghép tuần tự, gate bản ghép và commit vector đa repo; bảo toàn phần sửa của người dùng.
- Snapshot review/feedback/accept riêng theo revision, human gates đã thỏa thuận; việc độc lập tiếp tục.
- Reorder việc chờ không bypass dependency; pause/resume rõ ràng cho việc đang chạy. Contract đổi chỉ invalidate nhánh liên quan.

Điều kiện qua mốc: A→(B,C)→D, xem/review B khi C chạy, reorder queued tasks; duplicate/stale reports và conflict integration không làm sai trạng thái. Test fail bản ghép phải dừng delivery dù nhánh riêng pass.

## 4. P4 — Tối ưu quota và kiểm chứng công việc dài

Phụ thuộc P1–P3; hoàn thiện OC09/OC10.

- Policy theo task/risk/capability rồi quota, nhiều windows, freshness, reserve cho chat/review, đồng bộ usage có dedup.
- Chuyển provider ở checkpoint khi được phép; fallback/escalation có trần root, không ping-pong hoặc tự chuyển paid API.
- Trần tùy chọn tới 8 giờ, deadline tuyệt đối gồm waits; hiển thị active/queue/user/quota time. Extension rõ ràng giữ used counters.
- Fault injection dùng clock giả trước; soak run live có mục tiêu/giới hạn được cấp riêng, báo thời gian thật và usage, không gọi model 8 giờ chỉ để tiêu thời gian.
- Đo tổng usage đến kết quả đạt, tỷ lệ AC đạt, latency và can thiệp theo loại việc. JEV chỉ vào shadow benchmark nếu rule baseline cho thấy cần semantic classifier.

Điều kiện qua mốc: các tình huống deadline/restart/quota trong ma trận đạt; soak live có evidence riêng. Chưa có soak thì ghi chưa kiểm chứng vận hành dài, dù virtual-clock tests đạt. Không cam kết mọi feature xong trong 8 giờ hoặc chạy khi máy sleep.

## 5. Ma trận nghiệm thu

Các ca dưới đây là kế hoạch test, chưa phải kết quả đã pass. Dùng fixture cho lỗi khó tái hiện; ghi riêng live capability/authority evidence.

| Ca | Tình huống và kết quả bắt buộc | Yêu cầu | Mốc |
|---|---|---|---|
| T01 | Submit lặp cùng request/spec tạo đúng một root; spec đổi không dùng approval cũ | OC01, OC02, OC12 | P1/P2 |
| T02 | Hai feature khác CV đọc source và tạo plan phù hợp, AC đầy đủ, non-goals giữ nguyên | OC02 | P1 |
| T03 | Crash trước/sau launch, sau write trước ack: reconcile, không hai writer/side effect lặp | OC03, OC06 | P1 |
| T04 | Worker treo; status/cancel không gọi LLM, cancel chỉ confirmed khi đã dừng | OC03, OC04 | P1/P2 |
| T05 | Pending request sống qua restart; duplicate/stale/conflicting reply xử lý đúng; silence không approve | OC05, OC12 | P1/P2 |
| T06 | Kiro entry hết usage, Claude connect cùng ID, trả lời request; worker không bị restart | OC01, OC05, OC06 | P2 |
| T07 | Worker hết usage: old writer dừng, dirty diff giữ, adapter mới tiếp tục cùng budget | OC03, OC04, OC06, OC09 | P2 |
| T08 | Worker giả actor/approval hoặc sửa grant/gate bị boundary thực chặn | OC05, OC12 | P1/P2 |
| T09 | A→(B,C)→D; nhiều root không vượt 2 workers; overlap/cycle không dispatch sai | OC07, OC09 | P3 |
| T10 | Contract đổi chỉ stale descendants; report cũ không hoàn thành task mới/reopen canceled | OC03, OC07, OC11 | P3 |
| T11 | Nhánh riêng pass, bản ghép fail/conflict: không delivery; bảo toàn dirty user work | OC08, OC12 | P3 |
| T12 | Review B khi C chạy; feedback có revision; stale accept/move bị từ chối | OC05, OC11 | P3 |
| T13 | Reorder không bypass dependencies/interrupt/reset; pause/resume giữ checkpoint | OC07, OC09, OC11 | P3 |
| T14 | Restart/handoff/subtask giữ counters/deadline; grant extension giữ đã tiêu | OC03, OC09 | P1/P4 |
| T15 | Quota unknown/stale, ngắn còn nhưng tuần hết; reserve khi parallel; usage cumulative dedup | OC09, OC10 | P4 |
| T16 | Model ít rủi ro tiết kiệm, risk floor giữ; fallback bounded, không tự dùng paid API | OC10, OC12 | P4 |
| T17 | Fault clock + soak thật riêng: deadline chặn call mới, waits không tự kéo dài | OC09 | P4 |
| T18 | Read-only query không model call; đổi project không lẫn memory; stale facts hiện rõ | OC01, OC06, OC10 | P1/P2 |
| T19 | Sửa trong scope tự làm; phát sinh ngoài scope tạo request/backlog; pass khác acceptance | OC02, OC05, OC12 | P1/P3 |

## 6. Migration và giao hàng

Giữ nhóm lệnh spec và task hiện có. Profile CV giữ làm regression, không đổi hash/evidence run cũ. General profile có version riêng. Migration DB có backup/schema version, không tự coi attempt đang chạy là đã dừng hoặc tạo writer mới. Local approval cũ giữ provenance/giới hạn; chỉ cấp quyền mới khi đủ nguồn và authority, không tự nâng cấp bằng cách copy record.

Mỗi mốc cập nhật coverage bằng code + test/evidence, rồi commit phạm vi đó. Không approve SPEC-006 hay chạy workers trong lượt chỉ cập nhật kiến trúc. Run live cần giới hạn rõ, dùng lại quyền đã cấp nếu còn phù hợp; không hỏi lại từng lựa chọn kỹ thuật. Không ghi API keys vào spec, logs hoặc Git.

Chưa nằm trong P1–P4: dashboard/chat app, distributed/multi-user, vector DB, marketplace, Kiro Crew host bắt buộc, Antigravity/DeepSeek adapter chưa kiểm chứng, JEV trên mọi bước, production deploy. Các tài liệu review lịch sử vẫn dùng làm dữ liệu tham khảo, không tự sinh thêm scope.
