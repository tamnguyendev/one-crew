Tạo một trang form upload CV tiếng Việt có kiểm soát bot ở phía server. Ứng viên nhập tên, email, vị trí, chọn PDF tối đa 5 MiB, đồng ý lưu thông tin, xem lại/chỉnh sửa, xác minh rồi gửi và nhận biên nhận.

Đọc và áp dụng ý chính từ lịch sử đã được khách hàng cung cấp: bảo vệ hành động ghi hồ sơ, không dựa vào encrypt DOM, không kết luận nhập nhanh là bot, không cấm paste/autofill/IME. Phiên, nonce, challenge, permit và file hash phải được kiểm phía server. Thiếu/sai xác minh, replay, khác phiên, tệp thay đổi hoặc vượt hạn mức phải bị xử lý đúng. Turnstile phải được xác minh phía server và ràng buộc ngữ cảnh.

Tạo sản phẩm mới trong thư mục trống theo profile CV của OneCrew. Không copy source cv-guard đã viết thủ công. Giao diện responsive, sạch và dễ đọc; có nhãn demo local, không hứa chặn mọi AI agent hoặc giả vờ có nhà tuyển dụng thật. Mode locked mặc định; demo phải bật rõ ràng, chỉ dùng dữ liệu giả. Thiếu domain/khóa/AV không cản trở tạo bản local, nhưng phải ghi chưa kiểm chứng thật.

OneCrew tự lập kế hoạch, chọn model, thực hiện, kiểm thử, review và sửa trong ngân sách. Tôi đã cấp quyền autonomous cho các bước kỹ thuật này; không cần dừng giữa các bước để xin duyệt lại. Không tự deploy, gửi mail, thêm dashboard HR, lấy secret hay thay scope/budget. Bàn giao source, hướng dẫn, commit và bằng chứng. Acceptance sản phẩm vẫn để khách hàng review.
