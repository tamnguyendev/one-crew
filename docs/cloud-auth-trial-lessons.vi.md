# Cloud Auth audit: bằng chứng và bài học đang đề xuất

Ngày 09/10/2026. Task `TASK-0236a265d0ef4dd19d5cd14f8e600e95`, project `D:\TamNT\Workspace\1.Vimes\7.SRM`. Phạm vi là kiểm tra source cho thông báo Cloud Auth trong ảnh, không sửa app, build, commit hay push source ứng dụng.

## Trạng thái kiểm chứng

**Chưa hoàn thành.** Lần tiếp tục sau commit `e3359e1` đi từ 32 đến 52 lượt trong khoảng 5 phút. OneCrew tự lấy Git metadata, đọc luồng thiết lập và route app, rồi hai lần sửa báo cáo theo reviewer. Reviewer vẫn phát hiện báo cáo bỏ sót hoặc phủ nhận dữ liệu đã đọc. Tổng quan sát tại mốc cảnh báo: 673.037 token; đây không phải giá tiền hay quota subscription còn lại.

REQ `REQ-4c43f23b52ce47d59220cff6943f4817`, revision `4041a4b678a5dfebbf128b6bd2451af2642cb5c4e80965acfc3dcac99c84de53`, đang chờ lựa chọn continue/pause/stop. Không tự trả lời từ việc người dùng từng tăng ngân sách. Hard cap vẫn 10.000 lượt, deadline 01:44:25 ngày 10/10/2026 giờ Việt Nam; thời gian chờ không tự gia hạn.

Worker dùng Claude Sonnet; chưa có chuyển provider do quota. Codex đã sửa runtime giữa các lượt. Vì vậy không thể gọi cả trial là tự vận hành không hỗ trợ. Chưa có báo cáo cuối được chấp nhận, chưa tái hiện trên thiết bị, chưa chứng minh APK đang cài tương ứng với working tree đã khảo sát.

## Bài học từ lỗi đã có bằng chứng

| Bài học | Bằng chứng | Thay đổi và giới hạn |
|---|---|---|
| Tăng ngân sách không sửa lỗi phân loại | Outcome 573: dừng ở 32 lượt, nhãn quota từ feedback review có từ 429/OAuth | `ReviewRejected` được phân loại theo kiểu trước keyword; không thay native quota handling |
| Reviewer cần nội dung bằng chứng đủ dùng | Feedback cũ nói receipts bị cắt; code cũ chỉ gửi 1.000 ký tự/receipt | Full receipts trong budget 45.000 ký tự, manifest và tối đa 3 vòng truy hồi; không tự hạ tiêu chí chấp nhận |
| Worker cũng cần giữ bằng chứng qua các bước | Hai review mới yêu cầu lại dirty status và endpoint vốn đã đọc | Context mới giữ full receipts tối đa 36.000 ký tự, loại trùng read/receipt và giữ feedback gần nhất; hiệu quả trên lần chạy thật tiếp theo chưa xác nhận |
| Empty search phải có scope/page | Outcome 414 dừng sau 11 lượt ở các search khác nhau | Giữ query/directory/cursor; phân biệt search rỗng khác phạm vi, vẫn chặn lặp và vượt root budget |
| Không bỏ chính sách bảo vệ file để ép báo xong | Lượt 52: đọc file tên chứa secret bị từ chối | Giữ chính sách; receipt mới ghi path/cursor để mô tả giới hạn chính xác, không lộ nội dung. Không suy đoán điều kiện credential chưa đọc |
| Cảnh báo phải là quyết định thật | 20 lượt mới tạo REQ, tổng calls đứng ở 52 khi chờ | Pending không sinh model calls; tiếp tục chỉ đổi mốc cảnh báo, không reset tổng usage hoặc deadline |

Ba lesson được lưu trong shared ledger ở trạng thái **proposed**, gắn outcome 573/414. Không tự inject thành chỉ dẫn, không tự đổi routing, không tạo skill: nhiều lần thử của cùng một task không phải nhiều công việc lặp độc lập. Lesson về kết quả thành công chỉ có thể bổ sung sau khi có kết quả thật.

## Kiểm thử runtime

- Review/owned/revision5/effort/fallback: 57 test qua trước lần chạy thật.
- Git branch/detached/dirty và index preservation: fixture Git thật.
- Sau lỗi quên context: 31 test owned/search/review qua; 23 test review/effort/history qua; 9 test review cuối qua sau chỉnh dedup.
- Có ResourceWarning của fixture native process ở bộ regression; cleanup assertions qua.
- Chưa chạy full suite hoặc kiểm thử app/thiết bị. Các test này không thay thế nghiệm thu task Cloud Auth.
