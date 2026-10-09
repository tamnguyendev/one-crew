# Đổi công cụ chat mà giữ context OneCrew

`entry connect` đọc bản tóm tắt từ cùng ledger/project. Codex, Claude, Kiro hoặc terminal có thể gọi cùng CLI khi host cho phép. Lệnh không gọi model, không khởi động lại worker và không đổi provider đang thực thi. Không cần nhập lại private chat: những điều cần giữ phải được ghi vào spec, inbox hoặc note trước đó.

Ví dụ từ thư mục OneCrew; thay đường dẫn, task và revision bằng giá trị thật:

```powershell
.\onecrew.ps1 --project D:\Repo entry connect TASK-id
.\onecrew.ps1 --project D:\Repo entry connect TASK-id --json
```

Packet gồm spec duyệt nhanh đã pin (kể cả amendment), trạng thái execution/verification/acceptance, ngân sách đã dùng và deadline, worker hiện tại, scope, plan/done, output refs, câu hỏi đang chờ, năm câu trả lời gần đây và năm note gần đây. Bản đọc dùng một transaction, không trộn các thời điểm đọc. Các danh sách có giới hạn và tổng số; text cắt ngắn có cờ `truncated`. Dùng `task connect`, `work outputs`, `request show` hoặc `task events --after <cursor>` để xem chi tiết. Event cursor dùng để đọc tiếp lịch sử; context revision dùng khi ghi note.

## Lưu điều đã trao đổi

Viết một note UTF-8 tối đa 2.000 ký tự: quyết định, lý do ngắn và câu hỏi còn mở. Không đưa credential vào note. Đây là nội dung operator chủ động lưu, không có bộ lọc secret tự động.

```powershell
.\onecrew.ps1 --project D:\Repo entry note TASK-id --revision <context-revision> --request-id discussion-01 --kind decision --file D:\Notes\decision.txt --source kiro --reference "Trao đổi với khách hàng"
```

`proposal` ghi đề xuất; `decision` ghi điều đã chốt. Cả hai chỉ bổ sung context, không sửa spec/plan, cấp quyền, tăng budget, trả lời inbox hay đánh dấu acceptance. Muốn thay yêu cầu dùng luồng amendment; muốn trả lời câu hỏi dùng `request reply` với đúng revision của câu hỏi. Lệnh `entry note` không tự nạp note vào prompt worker đang chạy: thay đổi ảnh hưởng implementation phải đi qua spec/amendment để giữ scope và revision.

Giữ nguyên request ID và nội dung khi retry sau mất kết nối: OneCrew trả cùng receipt. Cùng ID nhưng khác nội dung bị từ chối. Context thay đổi thì phải `entry connect` lại trước khi ghi note mới. Điều này tránh lưu một quyết định dựa trên tiến độ cũ mà không biết có cập nhật.

Khi Kiro hết usage, mở Claude và đưa task ID, project path cùng state-root (nếu dùng state-root riêng), rồi gọi `entry connect`. Có thể tiếp tục review/reply ở Claude. Worker chỉ đổi qua `work switch` tại checkpoint theo cơ chế hiện có; việc đổi chat không tự tốn một lượt worker mới.

## Giới hạn hiện tại

Đây là CLI transport local, chưa phải plugin/MCP connector tự cài hay xác thực đa người dùng. `--source codex/claude/kiro` là attribution, không chứng minh danh tính; receipt ghi `local_attribution_only`. Packet là dữ liệu, không phải chỉ thị hoặc quyền thực thi. Notes chưa là knowledge được kiểm chứng hay lesson có tác dụng tự điều chỉnh routing. Bảy fixture test và hồi quy ledger/spec xác minh luồng; chưa thử thao tác từ cả ba UI thật.
