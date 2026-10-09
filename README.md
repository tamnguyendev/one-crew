# OneCrew

OneCrew hướng tới một core local để nhận công việc đã làm rõ từ **Codex / Claude / Kiro**, điều phối **Codex / Claude Code / Kiro CLI**, lưu tiến độ và kiểm chứng kết quả. CLI trước; công cụ chat và worker có thể thay độc lập.

**Đã có CV runtime và workflow Codex artifact tổng quát:** ledger/inbox, budget/supervisor, snapshot dirty bytes, spec-to-plan, output từng phần, pause/resume/reorder/review. Workflow mới đã chạy hai bài JSON thật; gate ứng dụng, đa provider, integration và chạy dài vẫn cần hoàn thiện. Baseline kiến trúc 09/10/2026, revision 2.

## Tài liệu hiện hành

| Tài liệu | Nội dung |
|---|---|
| [SPEC-006 — duyệt nhanh](specs/SPEC-006-portable-orchestration.md) | Bản ngắn cho người dùng và 12 yêu cầu chi tiết |
| [Kiến trúc](docs/architecture.vi.md) | Core/adapter/inbox; mục 12 ghi nguồn và quyết định áp dụng, mục 13 chốt contract thực thi |
| [Kế hoạch triển khai](docs/mvp-backlog.vi.md) | Bốn mốc, P1 chia bốn lát nhỏ; 30 ca nghiệm thu dự kiến |
| [Coverage](docs/proposal-coverage.md) | Phân biệt code đã có với phần còn thiếu |
| [P1a — task và inbox lưu bền](docs/durable-ledger.vi.md) | Submit/queue/connect, câu hỏi/revision/reply qua CLI; chưa dispatch worker |
| [P1b — admission và supervisor](docs/control-runtime.vi.md) | Schema migration, reservation/counters, action receipts, native Windows process containment |
| [Workflow tổng quát](docs/general-workflow.vi.md) | CLI chạy Codex từ spec/profile, review từng phần, resume, reorder và bằng chứng live |
| [Gate container](docs/container-gates.vi.md) | Contract test chức năng theo snapshot; live đang chờ Docker Linux Engine |
| [Workers và handoff](docs/providers.vi.md) | Codex/Kiro live, Claude chờ login; doctor và switch tại checkpoint |
| [Controller chạy nền](docs/background-runner.vi.md) | Start/reconnect, chờ reply không gọi model, giữ deadline qua pause |
| [Gia hạn có giới hạn](docs/budget-extension.vi.md) | Tăng trần tổng bằng revision riêng, giữ chi phí đã dùng và deadline tối đa tám giờ |
| [Xử lý vấn đề qua inbox](docs/inbox-triage.vi.md) | Tự tạo câu hỏi ngắn, chờ reply và resume trong grant cũ |
| [Routing policy](docs/routing-policy.vi.md) | Đề xuất model theo tier/risk/quota, chưa tự dispatch |
| [Nhánh Git để review](docs/review-branch.vi.md) | Kiểm candidate tree rồi tạo local branch, giữ nguyên source/index |
| [DAG song song](docs/parallel-dag.vi.md) | Hai nhánh độc lập cùng root, output từng phần và budget chung; live Kiro đã đạt |
| [Snapshot](docs/snapshots.vi.md) | Bảo toàn working/index bytes trong scope và output bất biến |
| [CLI spec](docs/spec-review-cli.vi.md) | Review/approve theo revision, diff/history |
| [Runtime và bằng chứng SPEC-005](docs/incremental-autonomy.vi.md) | Chạy CV từ thư mục trống, test/review/repair và preview |
| [JEV connection](docs/jev-connection.vi.md) | Kết nối đã kiểm chứng; chưa semantic routing |

Kiến trúc mới thay hướng Kiro Crew làm host bắt buộc bằng core OneCrew độc lập. Conductor chỉ lập plan/triage khi cần; code giữ queue, quyền, scope và budget. JEV tùy chọn sau benchmark. [Kiến trúc cũ](docs/architecture-2026-10-08.vi.md) và [backlog cũ](docs/mvp-backlog-2026-10-08.vi.md) được giữ làm lịch sử.

Revision 2 học handoff của Agent Orchestrator, action/budget broker của Agent Loop System, adapter của CAO, task claim của Beads, pause/replay của LangGraph, integration của Stoneforge, policy của Omnigent, checkpoint của Gas Town và loop của Athena. Giữ một core Python/SQLite; không thêm chín framework. Những giới hạn thấy trong source được chuyển thành điều kiện nghiệm thu: approval theo nội dung, stop trước đổi writer, reservation mỗi invocation, snapshot đủ dữ liệu, lỗi checkpoint không báo xong và test đúng candidate tích hợp. Đây là cập nhật thiết kế, chưa triển khai các năng lực đó.

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

Workflow mới đã chạy hai cấu trúc JSON ngoài CV, dùng 4 và 3 calls gồm planner retry, giữ source gốc và acceptance pending. Có fault tests crash/receipt/snapshot; đã có Codex→Kiro checkpoint handoff, còn thiếu Git integration đa repo, DAG song song đầy đủ và soak 8 giờ. JEV kết nối được không đồng nghĩa routing đã hoạt động. Kết quả CV vẫn chờ khách hàng review; hiệu quả chống bot thực tế chưa được chứng minh.

Đã bắt đầu nền lưu bền task/inbox bằng P1a. Mục tiêu tiếp theo là admission/budget/supervisor, rồi nối worker vào ledger để tiếp tục thực thi sau crash. Sau đó mới mở rộng entry/worker, song song và quota. Kế hoạch này không tự cấp quyền chạy trả phí hoặc deploy.

Kiểm thử code khi có thay đổi runtime: python -m unittest discover -s tests -v.
