# OneCrew

OneCrew hướng tới một core local để nhận công việc đã làm rõ từ **Codex / Claude / Kiro**, điều phối **Codex / Claude Code / Kiro CLI**, lưu tiến độ và kiểm chứng kết quả. CLI trước; công cụ chat và worker có thể thay độc lập.

**Hiện đã chạy được profile CV/local/Codex; orchestration tổng quát vẫn đang thiết kế.** Baseline kiến trúc cập nhật 09/10/2026 (Asia/Saigon).

## Tài liệu hiện hành

| Tài liệu | Nội dung |
|---|---|
| [SPEC-006 — duyệt nhanh](specs/SPEC-006-portable-orchestration.md) | Bản ngắn cho người dùng và 12 yêu cầu chi tiết |
| [Kiến trúc](docs/architecture.vi.md) | Một core, hai nhóm kết nối; inbox, memory, recovery, DAG và quota |
| [Kế hoạch triển khai](docs/mvp-backlog.vi.md) | Bốn mốc có nghiệm thu; bắt đầu core bền vững và một worker tuần tự |
| [Coverage](docs/proposal-coverage.md) | Phân biệt code đã có với phần còn thiếu |
| [CLI spec](docs/spec-review-cli.vi.md) | Review/approve theo revision, diff/history |
| [Runtime và bằng chứng SPEC-005](docs/incremental-autonomy.vi.md) | Chạy CV từ thư mục trống, test/review/repair và preview |
| [JEV connection](docs/jev-connection.vi.md) | Kết nối đã kiểm chứng; chưa semantic routing |

Kiến trúc mới thay hướng Kiro Crew làm host bắt buộc bằng core OneCrew độc lập. Conductor chỉ lập plan/triage khi cần; code giữ queue, quyền, scope và budget. JEV tùy chọn sau benchmark. [Kiến trúc cũ](docs/architecture-2026-10-08.vi.md) và [backlog cũ](docs/mvp-backlog-2026-10-08.vi.md) được giữ làm lịch sử.

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

Có task run/list/status/cancel/outputs/preview cho profile hiện tại; hướng dẫn chạy thật nằm trong tài liệu SPEC-005. **Submit/connect, request inbox/reply, pause/resume, reorder và output acceptance trong kiến trúc là tính năng dự kiến**, chưa là lệnh có thể sử dụng.

## Đã chứng minh và chưa chứng minh

Run RUN-20261008-232057-1d06d8 tự tạo app CV từ thư mục trống trong 585,21 giây, 14 model calls, một repair thật; 19 gate checks đạt và independent review không có findings. Product commit ad3c748, runtime commit bf2e673. Lượt đó ghi nhận 69 tests đạt; xem evidence và giới hạn trong tài liệu SPEC-005.

Chưa có general spec-to-plan, đa repo, worker Claude/Kiro, cross-entry inbox, crash resume, parallel scheduler hoặc run 8 giờ. JEV kết nối được không đồng nghĩa routing đã hoạt động. Kết quả CV đang chờ khách hàng review; dịch vụ chống bot bên ngoài và hiệu quả thực tế chưa được chứng minh.

Mục tiêu tiếp theo: một task tổng quát lưu bền, có câu hỏi chờ trả lời, restart rồi tiếp tục mà không lặp việc/reset budget. Sau đó mới mở rộng entry/worker, song song và quota. Kế hoạch này không tự cấp quyền chạy trả phí hoặc deploy.

Kiểm thử code khi có thay đổi runtime: python -m unittest discover -s tests -v.
