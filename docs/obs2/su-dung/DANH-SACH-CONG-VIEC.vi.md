# Danh sách và lịch sử công việc (bản thử 2.5.0.dev28, OBS-2C)

Trang theo dõi giờ cho xem **mọi** công việc của dự án, kể cả việc đã xong, từng trang một. Trang vẫn chỉ đọc: không duyệt, không sửa, không tách hay gộp việc.

## Đọc danh sách

- Mỗi lần trang tải 50 việc, việc mới tạo ở trên. Dòng cuối danh sách ghi: bao nhiêu việc đã tải, tổng bao nhiêu việc trong sổ, còn bao nhiêu chưa tải.
- Bấm **Xem thêm** để tải 50 việc tiếp theo. Trong lúc bạn đọc, việc mới tạo hiện ở đầu; các dòng đã tải không bị mất, không bị lặp.
- Nếu ngoài phần đã tải còn việc đang chờ bạn (chờ duyệt, câu hỏi chưa trả lời, dừng có báo cáo), dòng cuối nói rõ tên các việc đó.

## Tìm và lọc

- Ô **Tìm** tìm trong mọi việc của sổ, không chỉ phần đã tải (tên việc, mục tiêu, lời giao việc).
- **Bộ lọc**:
  - *Trạng thái*: như trước, thêm **Đã kết thúc** (nghiệm thu hoặc đóng). Nút nhanh "Đã kết thúc" ở cạnh ô tìm.
  - *Nguồn*: **Chủ giao**, **AI giao**, **Chưa rõ nguồn**, hoặc **Có việc AI phát sinh** (việc có việc sửa hay việc con).
  - *Thời gian*: theo ngày tạo, ngày cập nhật cuối hoặc ngày kết thúc, từ ngày… đến hết ngày….
- Số trên nút nhanh như "Cần sửa (3, phần đã tải)" chỉ đếm phần đã tải; chọn nút đó để trang tìm trong cả sổ.

## Nguồn của việc: lấy từ sổ, không đoán

- **Chủ giao**: hợp đồng ghi lời giao việc của bạn, hoặc chính bạn là người viết hợp đồng.
- **AI giao**: hợp đồng ghi người giao việc là một AI hay một bên điều phối, không phải bạn.
- **Chưa rõ nguồn**: hợp đồng không ghi ai giao việc. AI viết hợp đồng hay bạn đã duyệt cũng không có nghĩa là bạn giao việc đó.
- Phiên duyệt không khai báo là của ai thì ghi "chưa rõ phiên", không bao giờ ghi là phiên AI.

## Mở một việc: phần "Nguồn và quan hệ"

Ở thẻ **Tổng quan** của việc:
- Ai giao việc, yêu cầu ban đầu (lời của bạn nếu hợp đồng có ghi), lần duyệt, kết thúc.
- **Việc phát sinh**: mỗi việc sửa ghi lý do, lần kiểm không đạt sinh ra nó, phần bị ảnh hưởng, kết quả kiểm lại, và dòng "Nối với việc gốc". Mỗi việc con ghi phần việc và các lượt chạy. Một việc được nhiều sự kiện nhắc tới vẫn chỉ đếm một lần.
- Các bản hợp đồng: ai viết, lý do sửa, ảnh hưởng.
- Tách, gộp, đổi tên việc hay việc bạn nhờ trong chat: sổ chưa ghi, trang ghi **chưa theo dõi**.

## Những điều trang không suy ra

- "Đã đóng" là việc dừng lại, **không** phải thành công; chỉ "Đã nghiệm thu" là bạn đã nhận.
- Một lần kiểm đạt mà receipt không còn trong kho thì không tính là đã kiểm: mốc hiện "Cần kiểm lại".
- Đã kiểm chưa phải đã nghiệm thu; được giao chưa phải đã làm.
