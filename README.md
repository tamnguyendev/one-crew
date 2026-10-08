# OneCrew

Project đề xuất để quản lý công việc AI trên nhiều repo, ưu tiên CLI và tận dụng Kiro Crew.

**Trạng thái: đã có CLI duyệt spec local; runtime điều phối agent vẫn ở mức thiết kế.** Ngày cập nhật: 08/10/2026, Asia/Saigon.
Tên OneCrew là tên làm việc. Phạm vi người dùng đã xác nhận: **lập trình trên nhiều repo, dùng Claude/Kiro/Codex**.

## Thử CLI duyệt spec

Từ thư mục project trên Windows:

```powershell
.\onecrew.ps1 spec list --pending
.\onecrew.ps1 spec review SPEC-001
.\onecrew.ps1 spec review SPEC-001 --full
```

Lấy mã phiên bản vừa hiện để dùng `spec approve SPEC-001 --revision <mã>`. Có thêm `diff`, `request-changes` và `history`. Python 3.10+; dùng `.venv` local hoặc đặt `ONECREW_PYTHON`. Cách chạy trực tiếp: `python -m onecrew spec list`.

Một file spec có bản nhanh tối đa 350 từ và chi tiết cho AI. Đọc/duyệt không gọi model. Approval lưu theo nội dung; sửa spec làm bản hiện tại cần duyệt lại. Đây là sổ quyết định local, chưa có xác thực/cách ly với worker và chưa tự chạy AI. Xem [hướng dẫn CLI](docs/spec-review-cli.vi.md) và [spec mẫu đang chờ duyệt](specs/SPEC-001-duyet-spec.md).

Lượt sửa 2 đã xử lý hai lỗi phát hiện trong review: spec đang soạn dở không chặn review/approve spec hợp lệ; history vẫn đọc được khi file hiện tại lỗi hoặc bị xóa. Danh sách hiện lỗi riêng từng file và trả mã thoát 2 nếu kết quả chưa đầy đủ. [Coverage hiện hành](docs/proposal-coverage.md) ghi 8/8 yêu cầu CLI Complete với 24 test đạt; Conductor và runtime chưa triển khai.

Kiểm thử: `python -m unittest discover -s tests -v`.

## Quyết định đề xuất

Xây một project riêng chứa workflow, gate, bằng chứng nghiệm thu và CLI của mình; ưu tiên kiểm chứng Kiro Crew làm nền thực thi. Chỉ chốt nền sau spike; chưa mặc định fork hoặc xây runtime riêng.

- Học OneTechAI cách chuyển yêu cầu thành spec, test, code và bằng chứng.
- Tái sử dụng Kiro Crew cho session, hàng đợi, lịch, worktree và khôi phục.
- Dùng Claude Code làm executor đầu tiên để phù hợp tài sản hiện có; đưa Kiro CLI và Codex vào bộ kiểm chứng bắt buộc của MVP.
- Thử DeepSeek Harness ở giai đoạn sau, với phiên bản Kiro Crew đã hỗ trợ và gate đã được kiểm chứng.
- Trạng thái của task do runtime sở hữu; kết luận đạt yêu cầu cần thêm bằng chứng gate. Không tạo hai scheduler cùng chạy một task.

Các lỗi CLI đã được sửa. Bước kế tiếp là một task có status/cancel/budget/gate trên một repo/backend → nối Conductor từ trao đổi tới bàn giao → mở rộng nhiều repo và cả ba backend. DeepSeek, registry đa máy và dashboard để sau. Chưa dùng lại ước lượng tổng 2–4 tuần trước khi spike có bằng chứng.

## Tài liệu khởi động

| Tài liệu | Nội dung |
|---|---|
| [Review](docs/solution-review.vi.md) | OneTechAI, Claude đang dùng, DeepSeek Harness, Kiro và lựa chọn xây mới |
| [Kiến trúc](docs/architecture.vi.md) | Ranh giới tích hợp, nguồn trạng thái, gate, dữ liệu, CLI dự kiến |
| [CLI duyệt spec](docs/spec-review-cli.vi.md) | Bản ngắn cho người, chi tiết cho AI, approve theo phiên bản, diff và lịch sử |
| [MVP và nghiệm thu](docs/mvp-backlog.vi.md) | Spike, yêu cầu, thứ tự triển khai, kiểm chứng, tiêu chí dừng |
| [Kiểm soát task dài](docs/control-and-latency.vi.md) | Giới hạn task, tiến độ, pause/cancel, chống vòng lặp và giảm thời gian quy trình |
| [Kiểm soát phạm vi](docs/scope-control.vi.md) | Khóa hợp đồng task, phân loại phát hiện, backlog, budget chung và quyền mở rộng scope |
| [Lịch sử Claude thực tế](docs/history-findings.vi.md) | Timeline phiên chậm ngày 01/10, model của 11 agent, kiểm chứng lặp và giới hạn kết luận |
| [Audit toàn bộ lịch sử local](docs/claude-history-audit.vi.md) | Usage đã loại trùng, diễn biến 25/09–06/10, đối chiếu bản thử, nguyên nhân chậm và yêu cầu OneCrew |
| [Phiên bản và nguồn](docs/evidence.json) | Snapshot review; phân biệt release với nhánh phát triển |

## Kết quả cần đạt

Mở một màn hình hoặc chạy một lệnh là biết: AI đang làm gì, trên repo/nhánh nào, đang chờ ai, đã tạo kết quả gì, kiểm chứng ra sao và bước tiếp theo là gì.

Vấn đề ưu tiên người dùng đã xác nhận: chạy Claude Desktop với OneTechAI làm task rất lâu và khó kiểm soát. MVP phải chứng minh điều khiển được task ngay cả khi model chậm, không chỉ bổ sung bảng trạng thái.

Luồng mục tiêu: khách hàng trao đổi với Conductor → đề xuất/spec → duyệt và cấp quyền chạy → thực thi có giới hạn → kiểm chứng → bản thử và nghiệm thu. Việc nhỏ có luồng ngắn; thay đổi hành vi lớn dùng luồng spec đầy đủ. Conductor đề xuất và theo dõi kết quả; host là đường thực thi duy nhất giữ queue, retry và budget.

Các lệnh điều phối task/agent trong tài liệu kiến trúc vẫn là thiết kế; nhóm lệnh `spec` ở trên đã chạy được. Chưa cài hoặc thay cấu hình Claude/Kiro; chưa chạy tác vụ LLM trả phí trong các lượt review/triển khai CLI này.
