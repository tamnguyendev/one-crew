# SPEC-003 — Form upload CV có kiểm soát bot

## Duyệt nhanh

### Kết quả
Trang tiếng Việt cho ứng viên gửi CV PDF, xem lại thông tin và nhận biên nhận.

### Phạm vi
Bản local Next.js SSR, PDF tối đa 5 MiB, phiên form, Turnstile phía server, hạn mức gửi và chống gửi trùng. OneCrew lưu spec, giao một lượt review Codex có giới hạn và lưu bằng chứng.

### Không làm
Không hứa chặn mọi AI agent. Không encrypt DOM, huấn luyện AI từ dữ liệu giả, dashboard HR, gửi email hay public website trong lượt này.

### Nghiệm thu
Gửi thành công hồ sơ hợp lệ. Từ chối thiếu xác minh, sai phiên, sai payload, quá hạn, file không đúng và quá hạn mức. Gửi lại không tạo hồ sơ trùng. Dễ review riêng giao diện, bảo vệ API và triển khai.

### Lưu ý
Demo local dùng xác minh mô phỏng có nhãn rõ ràng; không chứng minh khả năng chống bot thật. CV được cách ly, chưa quét malware và không có đường dẫn tải công khai.

### Ngân sách
Một app, một lượt Codex review tối đa 180 giây, không tự retry. Không gọi dịch vụ AI khi ứng viên gửi form. Chi phí USD không được CLI đo chính xác.

### Cần quyết định
Không có.

## Chi tiết cho AI

Nguồn yêu cầu: https://chatgpt.com/share/6ac79282-b250-83ec-8d71-a1e9c0d1054d và yêu cầu tạo trang bằng OneCrew. Chat đã cho phép triển khai; không tạo bản ghi giả rằng khách hàng đã chạy CLI approve.

Giới hạn lát cắt: app riêng tại ../cv-guard, chạy một Node server và SQLite trên đĩa riêng. Không thay đổi runtime OneCrew. Chỉ dùng cầu nối Codex thử nghiệm có hồ sơ run; model chọn thủ công theo công việc review bảo mật, không tuyên bố Decision AI đã chạy.

- CV-001: Form SSR tiếng Việt, responsive, nhãn truy cập được; tên, email, vị trí, PDF, đồng ý lưu hồ sơ; xem lại và biên nhận. Không chặn paste/autofill/IME hoặc ép chờ 30 giây.
- CV-002: POST cấp phiên và nonce; cookie HttpOnly/SameSite; kiểm tra Origin, phiên và thời hạn trên API; private/no-store và CSP cho HTML/API.
- CV-003: Prepare đóng băng thông tin và SHA-256 file. Verify kiểm tra Turnstile success, hostname, action và cdata; lỗi nhà cung cấp từ chối gửi. Mặc định khóa nếu thiếu cấu hình; demo chỉ khi bật rõ ràng ở loopback.
- CV-004: Commit ràng buộc permit với phiên/pending/file; TTL, giao dịch SQLite, biên nhận idempotent và chống replay song song. Chỉ chấp nhận một hồ sơ trên một phiên form.
- CV-005: Giới hạn dung lượng ở stream, allowlist PDF, tên file an toàn, kiểm tra chữ ký; dữ liệu ngoài public, cách ly unscanned, không download. Quy trình xóa dữ liệu cũ và giới hạn lưu trữ.
- CV-006: Hạn mức server toàn cục/phiên/email; telemetry tổng hợp tùy chọn và honeypot chỉ là tín hiệu shadow. Không tin timing/client bot score để cho qua hoặc kết tội bot. Không thu nội dung phím/clipboard.
- CV-007: Test tích cực/tiêu cực, build, kiểm tra browser local; docs kiến trúc, checklist review từng phần, coverage và hồ sơ OneCrew/Codex.
- CV-008: Turnstile thật/domain, WAF/rate IP tại edge và chặn truy cập origin trực tiếp. Blocked khi thiếu khóa/hạ tầng. Không tự deploy.
- CV-009: Quét malware trước khi HR đọc, vận hành lưu trữ/retention, benchmark người thật và browser agent. Blocked khi thiếu pipeline/hạ tầng/dataset và quyết định vận hành.

Luồng: tạo phiên → nhập thông tin → prepare → xem lại → challenge → verify → upload/commit → biên nhận. Chưa gửi bytes CV trước khi permit được xác minh. Sửa thông tin quay lại prepare sẽ vô hiệu pending cũ. Đầu vào ngoài scope chuyển sang đề xuất, không tự triển khai.
