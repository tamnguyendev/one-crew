# Quy tắc của chủ sản phẩm (OneCrew đọc file này)

Cố vấn chỉ phán xét theo các dòng dưới đây. Mỗi quy tắc một dòng, có mã R1..R6.

R1. Đang phát triển một tính năng thì chỉ build DEBUG; chỉ build RELEASE khi phát triển đã kết thúc, test đạt và chủ sản phẩm đã thử trên thiết bị thật, như một bước giao bản riêng.
R2. Mỗi job chỉ có đúng hai tin nhắn gửi chủ sản phẩm: "Xin duyệt" và "Xin nghiệm thu", mỗi tin theo mẫu 5 mục bên dưới, cộng mục "Quyết định của tôi mà bạn chưa yêu cầu".
R3. Mọi sản phẩm bàn giao (code, mockup, tài liệu, bản build) đều đi qua một hợp đồng v2.
R4. Chẩn đoán chỉ đọc dưới khoảng 5 lệnh và các động từ của chủ sản phẩm nằm ngoài v2 nhưng phải được ghi log.
R5. Mọi việc khác nằm ngoài v2 phải được chủ sản phẩm đồng ý trước.
R6. Không báo "Xin nghiệm thu" cho tính năng giao diện khi chưa chạy thử trên thiết bị thật.

## Mẫu tin nhắn (tối đa 6 dòng)

1. Yêu cầu: việc được yêu cầu, bằng lời của chủ sản phẩm.
2. Người dùng sẽ thấy: kết quả nhìn thấy được.
3. Cách bạn nghiệm thu: các bước chủ sản phẩm tự làm để kiểm tra.
4. Không làm: những gì cố ý để ngoài.
5. Rủi ro: điều có thể sai và cách chặn.

Cuối tin: "Quyết định của tôi mà bạn chưa yêu cầu" (mỗi quyết định kèm lựa chọn thay thế và chi phí; ghi "không có" nếu không có).
