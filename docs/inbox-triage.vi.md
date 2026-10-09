# Khi OneCrew gặp vấn đề

Controller `work start` tự tạo câu hỏi ngắn khi workflow dừng vì lỗi. Câu hỏi có lý do, ảnh hưởng, số lượt gọi còn lại và lựa chọn. Chờ câu trả lời chỉ đọc ledger, không gọi model; thời gian chờ vẫn tính trong deadline root. Đóng chat rồi mở công cụ khác vẫn đọc cùng request ID.

```powershell
.\onecrew.ps1 --project D:\MyProject request list --pending
.\onecrew.ps1 --project D:\MyProject request show REQ-...
.\onecrew.ps1 --project D:\MyProject request reply REQ-... --revision <question-revision> --choice retry
```

`retry` chỉ tiếp tục phạm vi đã được local operator cấp, giữ model, counters và deadline. Core kiểm lại trạng thái lỗi, attempt cũ đã dừng, retry cap và ngân sách; trả lời muộn không vượt các giới hạn đó. `stop` yêu cầu hủy task nhưng giữ output. Khi không thể retry an toàn, câu hỏi dùng `inspect` để yêu cầu kiểm tra nguyên nhân, không tự gọi worker.

Nếu chạy `work run` ở foreground, dùng `work triage TASK-...` để tạo/đọc/xử lý câu hỏi, hoặc `work start TASK-...` để controller chờ và tiếp tục tự động. Các lệnh đọc status/outputs và request không cần LLM. `request show` có `controller_effect` sau khi controller đã áp dụng câu trả lời; receipt ban đầu vẫn chỉ xác nhận câu trả lời được lưu. Effect và checkpoint resume được commit cùng transaction.

Đây là luồng local operator, chưa xác thực danh tính người dùng từ từng ứng dụng chat. Không tự nâng câu trả lời thành quyền mở scope, mua API, đổi provider hoặc tăng budget. Sửa ngoài scope cần task/grant mới. Triage hiện dừng root; xử lý riêng từng nhánh và để mọi nhánh độc lập tiếp tục vẫn là phần cần xây dựng. Deadline hết thì controller dừng và ghi lý do, không đợi vô hạn.

Kiểm chứng: tests/test_triage.py kiểm restart, chờ không gọi model, receipt rollback, trả lời xung đột, trạng thái thay đổi giữa đọc và khóa, deadline hết, stop idempotent và controller tiếp tục sau reply. Đây là kiểm thử core với fixture worker; không giả là live entry Claude/Kiro.
