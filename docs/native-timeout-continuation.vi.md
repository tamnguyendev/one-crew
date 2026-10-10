# Tiếp tục phiên Claude sau timeout — 10/10/2026

Yêu cầu: phiên native 600 giây phải có thể tiếp tục công việc đang làm trong ngân sách task đã cấp, giữ test/review/bàn giao và thông báo. Áp dụng cho recipe `native_change.execution=workspace`; không tự mở rộng sang audit, reviewer hoặc provider khác.

600 giây là lát thời gian của một lần gọi. Root budget, deadline, quyền ghi, solution revision, câu hỏi và cancel vẫn có hiệu lực. Hết deadline hoặc quota không được coi là timeout có thể tự vượt qua.

Runtime xử lý receipt timeout ngay trong vòng chạy, hoặc khi người dùng resume một task cũ đã blocked:

1. Xác nhận attempt đã settled và toàn bộ cây tiến trình đã dừng; không còn attempt đang chạy.
2. Kiểm tra session trong stream, quyền thao tác, file ngoài scope, compiler inputs, approval và ngân sách. Terminal result cần reconciliation; không tự trả tiền cho lần chạy khác khi đã có kết quả cuối chưa xử lý.
3. So sánh hash file thuộc scope và kết quả test với baseline/các checkpoint timeout trước. Không có thay đổi hoặc quay lại checkpoint đã gặp thì blocked và giữ bằng chứng.
4. Lưu checkpoint, receipt và session; kết thúc pending attempt đúng một lần. Lượt đã dùng vẫn tính, usage chưa quan sát được giữ unknown.
5. Lượt tiếp theo dùng `--resume` cùng session/workspace với prompt tiếp tục và test command mới. Kiểm tra file chưa bị ai đổi sau checkpoint. Test cap tám lần cho mỗi invocation; lịch sử ba test cuối tiếp tục ngăn lặp cùng lỗi qua các invocation.
6. Worker tự hoàn tất patch và chạy recipe. Runtime vẫn chạy verification độc lập, review và apply; timeout checkpoint không phải kết quả nghiệm thu. Reviewer phải từ chối test bắt buộc bị skip/làm rỗng.

Đây là checkpoint của file/session/receipt, không phục hồi con trỏ thực thi của một shell command đang bị kill. Chỉ recipe test đã cấp quyền được chạy lại; không mở rộng sang lệnh có tác dụng ngoài workspace. CLI permission không thay thế OS sandbox.

Kiểm thử: `tests/test_workspace_timeout.py` có 14 trường hợp về nối tiếp/idempotency, resume session, ngân sách, process chưa dừng, session sai, terminal result, câu hỏi, deadline guard, file ngoài scope, drift và no-progress/test repetition; mô phỏng chuỗi timeout → worker result → verification → review → apply. `tests/test_owned_handoff.py` kiểm tra outputs và receipt/ACK sau apply. Fixture model/gate/host receipt chỉ là bằng chứng regression; không phải test thiết bị hay thông báo thật.

Thử thực tế: tiếp tục `TASK-b9a0c151d7274e97b5515f8318ad44e2` trong `ca-e2e-1010`, giữ giới hạn 100 calls/7200 giây và deadline 16:36:32 ngày 10/10 (Asia/Saigon). Đã dùng một invocation bị timeout. Có sửa runtime sau dispatch nên phải ghi nhận assisted; entry không sửa source sản phẩm hay chạy hộ test. Kết quả thật và delivery receipt phải được xác minh sau khi runner hoàn tất; không coi restart thành công là task đã xong.
