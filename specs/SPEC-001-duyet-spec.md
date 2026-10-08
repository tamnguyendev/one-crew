# SPEC-001 — Duyệt spec nhanh bằng CLI

## Duyệt nhanh

### Kết quả
Anh xem đề xuất ngắn rồi duyệt hoặc yêu cầu sửa ngay trong terminal.

### Phạm vi
- Liệt kê spec đang chờ duyệt.
- Đọc bản ngắn; mở chi tiết khi cần.
- Duyệt đúng phiên bản đã xem, xem thay đổi và lịch sử quyết định.

### Không làm
- Chưa tự chạy Claude/Kiro/Codex sau khi duyệt.
- Chưa có dashboard hoặc duyệt nhiều người qua mạng.

### Nghiệm thu
- Liệt kê và đọc được spec mẫu này.
- Sửa nội dung sau khi xem thì không duyệt được bằng mã cũ.
- Duyệt xong thấy đúng trạng thái; yêu cầu sửa vẫn giữ lịch sử.

### Lưu ý
Duyệt spec là đồng ý phạm vi, chưa phải nghiệm thu phần mềm. Sổ local chưa xác thực danh tính người duyệt.

### Ngân sách
Lát CLI local, dùng thư viện Python chuẩn. Đọc và duyệt không gọi model, không tiêu token AI.

### Cần quyết định
Không có.

## Chi tiết cho AI

### Dữ liệu và hiển thị
- Một Markdown chứa bản nhanh và chi tiết. Phần nhanh là hợp đồng; phần này không thêm hành vi sản phẩm ngoài hợp đồng đó.
- Header mang ID và tên. Bản nhanh có bảy mục bắt buộc, giới hạn 350 từ tách bằng khoảng trắng.
- CLI không sinh lại bản tóm tắt bằng LLM; hiển thị đúng nội dung tác giả đã ghi.

### Quyết định và phiên bản
- Chuẩn hóa CRLF/LF, hash SHA-256 toàn bộ spec rồi hiện 12 ký tự đầu.
- Approve/request-changes yêu cầu mã revision khớp. Câu hỏi chưa chốt chặn approve.
- Lưu loại quyết định, hash đầy đủ, thời điểm UTC, nhãn người ghi nhận, comment và snapshot vào SQLite local.
- Các trạng thái: draft, approved, changes_requested, needs_review. Nội dung khác quyết định gần nhất là needs_review.
- Approve không dispatch worker hoặc deploy. Chưa có xác thực và cách ly kho quyết định với worker cùng tài khoản.

### Kiểm thử
- Luồng list → review → approve → sửa → diff → request-changes → history.
- Kiểm tra hash cũ, câu hỏi mở, ID trùng, định dạng lỗi và kho state lỗi.
- Lệnh đọc không tạo database hay gọi dịch vụ ngoài.
