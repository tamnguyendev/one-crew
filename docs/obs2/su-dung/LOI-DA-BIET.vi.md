# Lỗi đã biết của OneCrew 2.5

Danh sách các lỗi đã biết mà chủ dự án quyết định **chưa sửa** trong 2.5. Theo quy tắc dừng chủ duyệt ngày 10/11, P2 còn lại được ghi vào đây; P1 thì luôn phải sửa trước khi phát hành.

| Từ review | Mức | Lỗi | Khi nào gặp | Cách tránh |
|---|---|---|---|---|
| Kiro dev22 | P2 | Một receipt không có sự kiện `verdict.receipt_issued` (receipt legacy) được tính tuổi theo seq lúc ghi nhận verdict, không theo lúc cấp | Chỉ khi một runtime cũ và runtime 2.5 cùng ghi một sổ sau khi nâng cấp | Sau khi nâng cấp, chỉ dùng runtime 2.5 cho sổ đó (xem `NANG-RUNTIME.vi.md`, mục C0) |
| Kiro dev20–dev22 | P3 | Observation của investigation (review tùy chọn) không khóa chính sách chép, nên có thể dùng lại câu trả lời đọc theo cách chép cũ | Sau khi nâng cấp, với một investigation đã chạy trước đó | Không cần làm gì: observation không cấp quyền (`grants_authority: false`) và không đổi trạng thái node. Muốn chắc thì chạy lại investigation |
