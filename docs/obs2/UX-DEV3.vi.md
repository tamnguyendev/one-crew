# UX dev3 — yêu cầu hiện hành 04/11

Nguồn: toàn bộ comment chủ sau bản thử dev2. Thực hiện local trên `codex/obs2`, base `3fbb07b`; không đổi quyền, engine, runtime/sổ/gói thật, không chờ MR-R hoặc CP-1.

| ID | Kết quả phải có | Kiểm |
|---|---|---|
| UX1 | Thẻ công việc nhóm theo giai đoạn; sort rõ; chọn thẻ xem phần việc/lượt bên trong | CODE/DOC, trạng thái không rõ/đóng/chờ nghiệm thu, sort không viết sổ |
| UX2 | Trạng thái nói chờ ai/vì sao; needs độc lập giai đoạn; mẫu thử rõ ràng | không suy chờ kiểm là cần chủ; blocked + nhánh khác chạy không mất dữ liệu |
| UX3 | Thẻ quyết định ngắn có nguồn, link thay đổi; khối PowerShell riêng copy đầy đủ, placeholder rõ | đúng runtime/project/sổ/revision; stale và ký tự đặc biệt; copy không approve |
| UX4 | Lệnh từ UI có output người dùng ngắn, chuẩn exit, không mất chi tiết lỗi; JSON cũ giữ nguyên | approve/answer/accept hoặc giới hạn có lý do; refusal, repeat, AI guard |
| UX5 | Solution/thay đổi có tóm tắt tiếng Việt, bản nội bộ khác revision hợp đồng; kỹ thuật thu gọn | before/after, raw diff vẫn xem được, không dựng lý do/phạm vi |
| UX6 | Kết quả hiện hành trước lịch sử; vòng kiểm/sửa có links và actor có nguồn | old pass không xác nhận new output, không biến check thành bug |
| UX7 | Bố cục dễ đọc desktop/mobile, không tràn trang, header ít nhiễu, poll không mất lựa chọn | 1280/390, slow/switch/stale, wheel browser |
| UX8 | Gói fixed snapshot, lệnh mở/dừng, báo cáo + wiki, giữ runtime thật | installed wheel, human CLI trong môi trường thử, hashes |

Chỉ thêm trình bày trên cơ chế hiện hữu: owner wrapper/guards; quote/runtime và question templates; plan/SOL/contract diff/repair/finding/measure và v1 redaction. Không mở quyền duyệt trong browser, không tự chọn quyết định, không chuyển mọi CLI sang text. Giai đoạn bảng là projection, không kéo thả ghi trạng thái. Thiếu nguồn giữ chưa xác định.

Cycle 3: UX1–UX8, unit tập trung → browser source → commit → wheel + CLI/browser cách ly → docs. Expected commit `feat(obs2): make work tracking actionable with cards and owner commands`.
