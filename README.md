# OneCrew

OneCrew hướng tới một core local để nhận công việc đã làm rõ từ **Codex / Claude / Kiro**, điều phối **Codex / Claude Code / Kiro CLI**, lưu tiến độ và kiểm chứng kết quả. CLI trước; công cụ chat và worker có thể thay độc lập.

**Luồng mới `job` — runtime tự làm việc:** giao mục tiêu + project root + quyền/ngân sách; OneCrew tự discovery, gọi worker, dùng tools, sửa candidate, kiểm thử và bàn giao Git. Entry không phải chọn file hoặc chuẩn bị evidence/profile. Ba loại task đã có Codex live evidence trong repo thử nghiệm; sandbox test của luồng mới hiện hỗ trợ Python unittest. Xem [hướng dẫn và giới hạn](docs/owned-execution.vi.md). Kiến trúc hiện hành revision 5, [hợp nhất KiroCrew + CAO](docs/architecture-kiro-cao.vi.md), SPEC-007 và [giao việc nền/inbox](docs/background-handoff.vi.md); các luồng `work`/spec cũ vẫn giữ tương thích.

Revision 5 đã có runtime recipe Android, giới hạn lặp/repair, kiểm evidence theo snapshot, local event delivery, stdio MCP entry và outcome/lesson có nguồn. Xem [phạm vi triển khai](docs/revision5-implementation.vi.md) và [coverage](docs/proposal-coverage.md). Giữ một core và runner Windows; CAO tùy chọn chưa đủ điều kiện chạy thử trên máy này. Bridge Codex mỗi 5 phút giữ PAUSED; local feed chạy bằng code, chưa có callback vào chat. Chưa hoàn tất toàn roadmap hoặc nghiệm thu task thực tế tiếp theo.

`job submit --start --terminal` giao việc nền và mở viewer nhóm agent. `android build --terminal` cũng chạy nền mặc định, có `android status/cancel`; một slot build chung trên state-root. Entry trả chat sau dispatch. `request defer` giữ câu hỏi pending; `notifications pull/ack` nhận thông báo bền vững mà không approve. Cầu nối chat là cấu hình host riêng, không phải callback realtime mặc định cho mọi công cụ.

**Đã chạy được workflow tổng quát với Codex, Kiro và Claude:** spec-to-plan, snapshot giữ dirty bytes, tối đa hai worker, inbox theo nhánh, controller nền, review/sửa từng phần, thay đổi yêu cầu và gia hạn hữu hạn. Test chức năng trong Docker, ghép target local và kiểm tương thích bộ commit đa repo đã có evidence thật. Có ngân sách chung và hủy toàn nhóm đã duyệt. Entry connectors có xác thực, điều phối đa repo tự động, routing tự động và soak tám giờ còn chưa hoàn tất. Đây là các năng lực nền của revision 2; trạng thái hiện hành nằm trong coverage revision 3.

## Tài liệu hiện hành

Revision 6 bổ sung [skill từ history và model preference/JEV](docs/skills-routing.vi.md). `skills list/review/approve/reject` quản lý candidate từ quy trình lặp; task đơn lẻ không tự tạo skill dùng chung. Trạng thái từng phần ở coverage.

| Tài liệu | Nội dung |
|---|---|
| [SPEC-007 — tự sở hữu công việc](specs/SPEC-007-owned-execution.md) | Goal intake, tools, candidate/test, Git delivery và runner độc lập chat |
| [Vận hành `job`](docs/owned-execution.vi.md) | CLI mới, ranh giới trách nhiệm, evidence và giới hạn đã kiểm chứng |
| [SPEC-006 — duyệt nhanh](specs/SPEC-006-portable-orchestration.md) | Bản ngắn cho người dùng và 12 yêu cầu chi tiết |
| [Kiến trúc](docs/architecture.vi.md) | Core/adapter/inbox; mục 12 ghi nguồn và quyết định áp dụng, mục 13 chốt contract thực thi |
| [Kiến trúc revision 5 — KiroCrew + CAO](docs/architecture-kiro-cao.vi.md) | Luồng trọn task, ranh giới CAO, event delivery, recovery và gate P0/P1/P2 |
| [Triển khai revision 5](docs/revision5-implementation.vi.md) | Recipe được cấp quyền, chống lặp, evidence, local delivery, outcomes và giới hạn |
| [MCP entry](docs/entry-mcp.vi.md) | Cổng stdio local dùng chung, read-only mặc định; điều khiển do operator bật |
| [Kế hoạch triển khai](docs/mvp-backlog.vi.md) | Ưu tiên revision 5; giữ contract và ca nghiệm thu nền P1–P4 |
| [Coverage](docs/proposal-coverage.md) | Phân biệt code đã có với phần còn thiếu |
| [P1a — task và inbox lưu bền](docs/durable-ledger.vi.md) | Submit/queue/connect, câu hỏi/revision/reply qua CLI; chưa dispatch worker |
| [P1b — admission và supervisor](docs/control-runtime.vi.md) | Schema migration, reservation/counters, action receipts, native Windows process containment |
| [Workflow tổng quát](docs/general-workflow.vi.md) | CLI chạy Codex từ spec/profile, review từng phần, resume, reorder và bằng chứng live |
| [Gate container](docs/container-gates.vi.md) | Test chức năng trên snapshot/Git candidate; hai chức năng live đạt, có cả evidence lỗi và sửa |
| [Đăng nhập subscription](docs/subscription-auth.vi.md) | Kiểm tra auth trước dispatch, lọc API key khỏi môi trường worker; không thay cấu hình người dùng |
| [Tools qua core](docs/worker-tools.vi.md) | Worker yêu cầu đọc/tìm source và chạy check đã cấp; serial, native tools vẫn tắt |
| [Context giữa các công cụ chat](docs/entry-context.vi.md) | entry connect/note: tiến độ, câu hỏi và quyết định qua CLI; không tự dispatch/approve |
| [Workers và handoff](docs/providers.vi.md) | Ba worker live có evidence; doctor và switch tại checkpoint |
| [Controller chạy nền](docs/background-runner.vi.md) | Start/reconnect, chờ reply không gọi model, giữ deadline qua pause |
| [Gia hạn có giới hạn](docs/budget-extension.vi.md) | Tăng trần tổng bằng revision riêng, giữ chi phí đã dùng và deadline tối đa tám giờ |
| [Ngân sách chung nhiều repo](docs/goal-budget.vi.md) | Nhóm task đã duyệt chia sẻ trần tổng; không reset khi chia task hoặc restart |
| [Bộ commit đa repo](docs/commit-vector.vi.md) | Kiểm tương thích đúng bộ commit; ref đổi làm evidence stale |
| [Xử lý vấn đề qua inbox](docs/inbox-triage.vi.md) | Tự tạo câu hỏi ngắn, chờ reply và resume trong grant cũ |
| [Routing policy](docs/routing-policy.vi.md) | Đề xuất model theo tier/risk/quota, chưa tự dispatch |
| [Quota Codex](docs/quota-feed.vi.md) | Đọc quota subscription không gọi model; unknown/stale chặn routing |
| [Giữ quota giữa workers](docs/account-reservations.vi.md) | Admission có reservation trong cùng ledger, usage dedup và phần dữ liệu chưa rõ |
| [Nhánh Git để review](docs/review-branch.vi.md) | Kiểm candidate tree rồi tạo local branch, giữ nguyên source/index |
| [Ghép vào target local](docs/target-integration.vi.md) | Three-way mức file, test đúng bản ghép, CAS ref; conflict giữ evidence |
| [DAG song song](docs/parallel-dag.vi.md) | Hai nhánh độc lập cùng root, output từng phần và budget chung; live Kiro đã đạt |
| [Inbox theo nhánh](docs/branch-inbox.vi.md) | Nhánh lỗi/dependents chờ quyết định, nhánh độc lập vẫn tiến triển |
| [Thay đổi yêu cầu](docs/requirement-amendment.vi.md) | Revision mới chỉ làm lại nhánh bị ảnh hưởng và dependency, giữ kết quả độc lập |
| [Yêu cầu sửa sau review](docs/review-corrections.vi.md) | Sửa phần liên quan trong requirements/caps cũ, giữ nhánh độc lập |
| [Snapshot](docs/snapshots.vi.md) | Bảo toàn working/index bytes trong scope và output bất biến |
| [CLI spec](docs/spec-review-cli.vi.md) | Review/approve theo revision, diff/history |
| [Runtime và bằng chứng SPEC-005](docs/incremental-autonomy.vi.md) | Chạy CV từ thư mục trống, test/review/repair và preview |
| [JEV connection](docs/jev-connection.vi.md) | Kết nối đã kiểm chứng; chưa semantic routing |

Kiến trúc mới thay hướng Kiro Crew làm host bắt buộc bằng core OneCrew độc lập. Conductor chỉ lập plan/triage khi cần; code giữ queue, quyền, scope và budget. JEV tùy chọn sau benchmark. [Kiến trúc cũ](docs/architecture-2026-10-08.vi.md) và [backlog cũ](docs/mvp-backlog-2026-10-08.vi.md) được giữ làm lịch sử.

Revision 2 học handoff của Agent Orchestrator, action/budget broker của Agent Loop System, adapter của CAO, task claim của Beads, pause/replay của LangGraph, integration của Stoneforge, policy của Omnigent, checkpoint của Gas Town và loop của Athena. Giữ một core Python/SQLite; không thêm chín framework. Các contract được triển khai từng lát; coverage ghi bằng chứng code/test/live và phần thiếu, thay vì coi toàn thiết kế đã hoàn thành.

## Dùng CLI hiện có

Từ thư mục project trên Windows, Python 3.10+; launcher dùng .venv local hoặc ONECREW_PYTHON:

```powershell
.\onecrew.ps1 spec list --pending
.\onecrew.ps1 spec review SPEC-006
.\onecrew.ps1 spec review SPEC-006 --full
.\onecrew.ps1 task run --help
.\onecrew.ps1 task list
```

Dùng revision vừa xem cho lệnh spec approve; sửa nội dung cần duyệt revision mới. Có diff, request-changes và history. Bản nhanh tối đa 350 từ, chung file/hash với chi tiết cho AI. Các lệnh đọc/duyệt không gọi model. Approval hiện là sổ local, chưa có xác thực/cách ly worker và không tự cấp quyền runtime tổng quát.

Có task run/list/status/cancel/outputs/preview cho CV; hướng dẫn nằm trong SPEC-005. **task submit/queue/connect/events/status và request create/list/show/revise/reply** lưu task/inbox qua restart. Nhóm **work enable/run/status/outputs/pause/resume/reorder/review/export** nối TASK- với Codex artifact workflow; xem hướng dẫn workflow và JSON/examples. Câu trả lời local chưa là quyền thực thi đã xác thực đa entry.

## Đã chứng minh và chưa chứng minh

Run RUN-20261008-232057-1d06d8 tự tạo app CV từ thư mục trống trong 585,21 giây, 14 model calls, một repair thật; 19 gate checks đạt và independent review không có findings. Product commit ad3c748, runtime commit bf2e673. Lượt đó ghi nhận 69 tests đạt; xem evidence và giới hạn trong tài liệu SPEC-005.

Workflow mới đã chạy hai cấu trúc JSON ngoài CV, dùng 4 và 3 calls gồm planner retry. Có Codex→Kiro checkpoint handoff, hai Kiro workers cùng root và test chức năng đơn hàng/CSV trong Docker. Ba trial chức năng dùng tổng 7 calls, giữ cả trial lỗi và regression riêng trong evidence; không che chi phí repair do lỗi hạ tầng ban đầu. Source/index gốc giữ nguyên, acceptance pending. JEV kết nối được không đồng nghĩa routing đã hoạt động. Kết quả CV vẫn chờ khách hàng review; hiệu quả chống bot thực tế chưa được chứng minh.

Các phần còn thiếu được theo dõi theo OC01–OC12 trong coverage: entry có xác thực, đầy đủ fault/cancel/handoff transitions, điều phối đa repo tự động, routing/fallback, settlement usage đầy đủ và soak dài. CLI hiện dùng local operator; không tự cấp quyền chạy API trả phí hoặc deploy.

Kiểm thử code khi có thay đổi runtime: python -m unittest discover -s tests -v.
