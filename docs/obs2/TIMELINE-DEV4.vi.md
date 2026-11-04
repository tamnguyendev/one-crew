# Timeline dev4 — triển khai review 04/11

Baseline HEAD20b5baa, productff81554. Chủ cho sửa timeline, tái sử dụng hiện hữu, kiểm wheel; không full gate, không hỏi duyệt từng bước, không đổi runtime thật.

| ID | Yêu cầu | Kiểm |
|---|---|---|
| TL1 | Gọi đúng khoảng thực thi/trước khởi chạy/chờ/từ đầu ra đến kết quả kiểm; không suy CPU hoặc thời gian chạy verifier | mốc produced→verification dài nhưng không checker-start; unknown |
| TL2 | Trục tương đối thích ứng ms/giây/phút/giờ, không nhãn lặp; cửa sổ khác thời lượng | <1s, vài giây, nhiều giờ, offset/zero/missing |
| TL3 | Mỗi phần việc một dòng chính rõ tên/trạng thái/thời lượng; lượt và lịch sử mở khi cần | tên dài, pending, produced chưa verified, retry, song song |
| TL4 | Chọn dòng mở chi tiết có actor/bằng chứng theo nguồn; không giữ ngăn trống; desktop/mobile đọc được | keyboard, source boundary, 1280/390, chọn/đổi task |
| TL5 | Vừa khung/Hiện hành/Toàn bộ lịch sử; poll không kéo khung lịch sử; stale/slow giữ guard | poll, switch, frozen history, current live |
| TL6 | Source checks + fixed wheel/browser/lifecycle + bàn giao/wiki | isolated state/project/env, registry stable, no full gate |

Cycle4: TL1–TL5 renderer/source validation, commit; TL6 wheel+docs commit. Expected commit feat(obs2): clarify task timeline with adaptive time scale. Không thêm feature OBS-2C/MR-R/CP-1/RD-A. Default xem lượt hiện hành của mỗi bước; lịch sử vẫn xem được. Hợp khoảng chỉ dùng nơi có mốc, không tô lấp khoảng trống hoặc cộng đôi song song. Dữ liệu thiếu giữ chưa xác định.
