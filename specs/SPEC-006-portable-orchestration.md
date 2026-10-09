# SPEC-006 — Điều phối độc lập với công cụ AI

## Duyệt nhanh

### Kết quả
Trao đổi ở Codex, Claude hoặc Kiro rồi giao yêu cầu đã rõ cho OneCrew. Có thể đổi công cụ, trả lời câu hỏi đang chờ và tiếp tục đúng việc mà không kể lại từ đầu.

### Phạm vi
Core local lưu task, quyết định, checkpoint và ngân sách; chia việc theo source/spec; kết nối các worker; review từng phần. Làm tuần tự trước, sau đó tối đa hai worker song song có kiểm soát phụ thuộc.

### Không làm
Chat app riêng, dashboard, vector DB, điều phối đa máy, JEV bắt buộc hoặc tự deploy/mua API credits.

### Nghiệm thu
Khởi động lại không lặp việc; đổi entry vẫn thấy cùng câu hỏi và output; đổi worker không có hai writer hoặc reset budget. Duyệt đúng nội dung, giữ phần code chưa commit; lỗi checkpoint phải hiện rõ. Task liên quan chỉ chạy khi dependency đạt; kiểm thử đúng bản ghép trước bàn giao. Không mở rộng scope ngoài quyền đã cấp.

### Lưu ý
Đã có Codex/Kiro workflow, checkpoint handoff, DAG hai worker và gate container với evidence. Claude live, entry có xác thực, integration đa repo, quota routing tự động và soak tám giờ còn thiếu. History chat chưa lưu vào OneCrew không tự chuyển được. Coverage ghi trạng thái từng phần.

### Ngân sách
Triển khai theo bốn mốc có bằng chứng. Mỗi lượt model/live run cần grant cụ thể, giữ tổng chi phí theo mục tiêu. Tám giờ là trần tùy chọn, gồm thời gian chờ, không phải số giờ phải dùng hết.

### Cần quyết định
Không có.

## Chi tiết cho AI

Baseline: [kiến trúc 09/10/2026 revision 2](../docs/architecture.vi.md). Mục 12 ghi quyết định từ chín repo; mục 13 là contract bắt buộc làm rõ OC01–OC12 dưới đây. Triển khai theo [backlog](../docs/mvp-backlog.vi.md), ghi evidence vào [coverage](../docs/proposal-coverage.md). Đây là proposal mới, không tự approve bằng việc file tồn tại. Các requirement mô tả đích đầy đủ; từng mốc chỉ nhận phạm vi tương ứng.

### OC01 — Entry độc lập với worker
Một contract submit/connect/query cho Codex/Claude/Kiro. Submit idempotent theo client_request_id, gắn spec revision và grant. Đổi entry không tạo task mới hoặc restart worker. Nghiệm thu: submit lặp chỉ một root; reconnect cùng ID thấy output và pending requests; chứng minh trên từng entry thực thay vì chỉ fixture.

### OC02 — Spec thành công việc từ repo thực
Giữ bản nhanh/chi tiết cùng revision; Conductor dùng AC/non-goals và trạng thái source để lập plan tổng quát. Code kiểm AC coverage, DAG và ownership; không dùng graph CV cố định để quảng cáo planner tổng quát. Nghiệm thu: hai chức năng khác cấu trúc CV có plan phù hợp source, đầu ra thử được; spec thay revision làm approval cũ không còn áp dụng phần thay đổi.

### OC03 — Core bền vững và một writer
Core độc lập với chat, chỉ một scheduler; persist dispatch intent/lease/process identity/counters và checkpoint trước khi chuyển bước. Restart phải reconcile rồi mới dispatch. Nghiệm thu: crash trước/sau launch, sau write nhưng trước ack, late event và duplicate event không sinh hai writer hoặc chạy lại side effect chưa rõ; status/cancel không cần LLM.

### OC04 — Worker adapter thay thế được
Codex/Claude Code/Kiro CLI qua interface capability/version, launch/events/cancel/reconcile/artifact/usage. Unknown không giả hỗ trợ; credentials theo account/adapter, không copy vào task memory. Nghiệm thu: từng adapter chạy/verify/cancel thật và handoff khác provider sau xác nhận writer cũ dừng, giữ dirty diff và root counters.

### OC05 — Inbox và approval có revision
Lưu request ngắn có recommendation/options/impact, affected tasks và proposed action revision; reply qua entry có actor/provenance. Không hỏi lại quyền còn hiệu lực. Nghiệm thu: duplicate reply idempotent, reply conflict/stale bị từ chối, im lặng không approve; nhánh độc lập tiếp tục; model/worker không giả reply khách hàng.

### OC06 — Memory và handoff chung
Spec/decision summary Markdown, task/event/requests SQLite, artifact/source Git hoặc snapshot có hash. Phân biệt proposal/fact/decision/verified result; project isolation và stale references. Chỉ core ghi state; entry nhận durable ack khi lưu quyết định. Nghiệm thu: chuyển công cụ không mất quyết định đã ack hoặc diff chưa commit; chưa persist phải báo thiếu, không bịa; không mang secrets/private transcript sang worker.

### OC07 — Song song có phụ thuộc
DAG revision, ownership/worktree và giới hạn hai worker toàn core; kiểm capacity/provider/root budget khi dispatch. Contract trước rồi nhánh độc lập, việc overlap tuần tự. Nghiệm thu: A→(B,C)→D, cycle rejection, hai root không vượt capacity; contract đổi chỉ vô hiệu phần phụ thuộc, report cũ không đổi revision mới.

### OC08 — Kiểm chứng bản ghép
Integration owner ghép tuần tự trên base đã biết, gate theo snapshot; đa repo giữ vector commit/contract. Nghiệm thu: hai nhánh pass riêng nhưng ghép fail không được completed/accepted; conflict giữ evidence và sửa có giới hạn; không ghi đè sửa của người dùng hoặc tự publish.

### OC09 — Budget và công việc dài
Deadline tuyệt đối, counters/reservations root cộng mọi task/attempt/role do OneCrew gọi. Trần tùy chọn tới 8 giờ gồm waits; hoàn thành sớm thì dừng. Nghiệm thu: restart/switch/spawn không reset; deadline chặn dispatch; unknown usage hiển thị; budget extension có grant revision và giữ đã tiêu. Recovery qua fault injection, soak live báo riêng, không suy soak thành bảo đảm mọi feature hoàn thành.

### OC10 — Routing theo task và quota
Rule lọc quyền/capability/risk trước, rồi xét model đủ năng lực/quota/budget; nhiều cửa sổ quota và freshness, reserve cho tương tác. Nghiệm thu: quota stale/unknown không coi unlimited, hết tuần không dispatch vì cửa sổ ngắn còn; reserve khi song song, dedup cumulative usage, cached input không cộng hai lần; fallback không ping-pong, không tự dùng API trả phí. JEV chỉ là thử nghiệm tùy chọn sau benchmark.

### OC11 — Review từng phần và thứ tự
Output card có cách thử/diff/evidence/giới hạn, revision immutable và feedback history. Human gate chỉ khi thỏa thuận. Reorder queued tasks bằng plan revision, không bypass dependency hoặc ngắt running. Nghiệm thu: review phần A trong lúc B độc lập chạy, feedback cũ không approve bản mới; move không reset budget, stale move bị từ chối; pause/resume giữ checkpoint.

### OC12 — Thẩm quyền và scope
Conductor đề xuất; code cưỡng chế grant/scope/budget/gate, worker không sửa authority store. Lựa chọn kỹ thuật trong scope tự xử lý; phát sinh ngoài scope vào backlog/request. Execution/verification/acceptance tách biệt. Nghiệm thu: worker giả approval hoặc sửa gate/grant bị chặn bằng boundary thực; test pass không tự user acceptance; publish cần quyền riêng đã cấp. Cùng OS user full shell chưa đủ isolation, phải chứng minh boundary trước bật tự động.

## Contract bổ sung từ review source — revision 2

Các dòng dưới đây là điều kiện của OC hiện hữu, không tạo thêm sản phẩm hoặc đổi trạng thái implementation thành Complete. T01–T19 giữ nguyên; T20–T30 là ca bổ sung trong backlog.

| Yêu cầu | Điều kiện bắt buộc | Kiến trúc | Nghiệm thu bổ sung |
|---|---|---|---|
| OC01, OC05 | Entry attach/reply không restart worker; pending request dựng lại từ DB cả khi core và worker chết | 13.1, 13.3 | T22 |
| OC02, OC10, OC12 | AI đề xuất theo schema; strict booleans/evidence; code giữ authority, không model call cho query | 13.8, 13.9 | T28, T29 |
| OC03, OC07 | Admission transaction claim + capacity + generation + dispatch intent + reservation; không replay launch chưa rõ | 13.2 | T20, T21, T25 |
| OC04, OC06 | Handoff lưu từng transition; xác nhận old writer dừng trước quyền ghi target; giữ dirty bytes; capability theo OS/version | 13.1, 13.4, 13.6 | T21, T24, T27 |
| OC05, OC12 | Hash bind toàn payload thực thi, caller có quyền, reply CAS; stale/conflicting approval không áp dụng | 13.3 | T22 |
| OC06, OC09 | Checkpoint ghi blob rồi DB reference; lỗi storage không completed; unknown effect cần reconcile; migration không mất tiến độ | 13.5, 13.6 | T23, T24, T25, T30 |
| OC08, OC11 | Test đúng integration candidate, thiếu worktree không fallback; base đổi thì stale; evidence/acceptance theo snapshot | 13.7 | T26 |
| OC09, OC10 | Reserve trước từng managed invocation; internal CLI calls chỉ hard-cap nếu adapter enforce; extension hữu hạn, giữ used/unknown | 13.1, 13.5 | T20, T27 |
| OC09, OC12 | No-progress có ngưỡng policy/root budget; không tự mở scope, reset qua retry hoặc gỡ sandbox | 13.5, 13.8, 13.9 | T27, T29 |

## Ràng buộc migration

Giữ CLI spec và profile CV để hồi quy. Run cũ giữ ID/hash/evidence, không sửa artifact. Approval local cũ không tự chuyển thành authenticated grant. Schema có version/backup; unknown/in-flight attempt cần reconcile. Các lệnh mới trong kiến trúc là đề xuất, không ghi vào hướng dẫn như tính năng đã hoạt động.
