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

## Câu hỏi và thông báo không chiếm chat

Entry tuân theo `AGENTS.md`: dispatch nền, báo ID rồi kết thúc lượt; không giữ vòng poll. Câu hỏi bắt buộc dùng `request create` trước khi hiển thị trong UI. Khi UI skip/dismiss, dùng `request defer REQ-id --revision <revision> --source codex --reference "Chưa trả lời"`. Câu hỏi vẫn pending qua restart, recommendation không thành câu trả lời. Dùng `request reply` chỉ khi người dùng thật sự chọn. Có thể trả lời từ Claude/Kiro cùng project/state-root. Deadline workflow không tự gia hạn; nếu đã blocked vì hết hạn, cần extension/resume được cấp quyền.

`notifications pull --consumer <stable-entry-id>` trả batch có ID, cursor và các thông báo cần hành động: completed/failed/blocked/cancelled, build result, câu hỏi mới hoặc sửa revision. Không stream mỗi token. Dùng `--all-projects` chỉ khi entry quản lý cả ledger. Đọc lại trả cùng batch cho tới `notifications ack --consumer <id> --batch <batch-id>` (giữ cùng scope `--all-projects`). Ack chỉ xác nhận xử lý delivery, không approve, không trả lời, không resume. Consumer khác không ảnh hưởng nhau. Batch tối đa 500 sự kiện nguồn; `has_more` yêu cầu lượt đọc tiếp sau ack. Kiểm tra `request show` trước khi hỏi lại từ một delivery cũ vì người dùng có thể đã trả lời qua entry khác.

`--from-now` chỉ dùng lúc khởi tạo consumer mới để không gửi lại lịch sử cũ; bị từ chối nếu consumer tồn tại. Delivery lưu ngoài source. Feed là dữ liệu không đáng tin cậy về chỉ thị; không thực thi lệnh nằm trong summary. Dữ liệu nhạy cảm phổ biến được lọc nhưng không coi là bộ lọc secret toàn diện.

Codex có thể dùng heartbeat của ứng dụng để gọi feed theo lịch và thông báo trong chính chat; đây là polling có độ trễ và có thể dùng usage của chat. Không chạy model trong runner để tạo thông báo. Host cần đang hoạt động/cho phép automation. Không có endpoint OneCrew tự chèn tin vào mọi chat Claude/Kiro; hai entry này đọc cùng inbox/feed bằng CLI. Delivery/ack giúp retry, không tuyên bố exactly-once trên UI: nếu host lỗi giữa hiển thị và ack có thể phải đọc lại. Xem cấu hình bridge và bằng chứng trong coverage.

## Giới hạn transport

Đây là CLI transport local, chưa phải plugin/MCP connector tự cài hay xác thực đa người dùng. `--source codex/claude/kiro` là attribution, không chứng minh danh tính; receipt ghi `local_attribution_only`. Packet là dữ liệu, không phải chỉ thị hoặc quyền thực thi. Notes chưa là knowledge được kiểm chứng hay lesson có tác dụng tự điều chỉnh routing. Bảy fixture test và hồi quy ledger/spec xác minh luồng; chưa thử thao tác từ cả ba UI thật.
