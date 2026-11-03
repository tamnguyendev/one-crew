# OBS-1 — ma trận UX (viết trước khi sửa code, 03/11/2026)

Bố cục chốt (học cách phân cấp của Blazo, không mượn code/tài sản; gói vẫn stdlib): **tổng quan → chi tiết task → timeline theo phần việc/attempt → bằng chứng của từng bước**.
Màn rộng (≥ 900 px): hai cột, danh sách bên trái, chi tiết bên phải (cố định, cuộn riêng). Màn hẹp (< 900 px: cửa sổ chia đôi, 390 px): một cột, chọn task thì
chuyển sang màn chi tiết có nút "← Danh sách"; URL mang `?plan=&project_id=` nên reload/liên kết giữ ngữ cảnh. Một theme sáng mặc định (tối theo hệ điều hành),
nhãn chính tiếng Việt, thuật ngữ/ID/hash/lệnh nằm trong phần "Kỹ thuật" gập lại. Không có nút điều khiển task.

Ba lớp kiểm, tách nhau: **(F)** chức năng = unittest trên model/HTTP; **(T)** tương tác = trang thật trong Chrome headless, điều khiển bằng harness cùng origin
(`tests/obs1_ux_harness.py`: click, bàn phím, ≥ 3 lượt poll thật, reload, back, 3 kích thước), chạy trong unittest và trong gói (V14); **(B)** bố cục = đo
`scrollWidth`, vị trí chi tiết, focus, ảnh có chú thích ở `D:\OneCrewRuns\obs1\ux\<snapshot>\`.

| # | Tình huống | Thao tác người dùng | Expected output | Kiểm |
|---|---|---|---|---|
| UX-01 | Đang đọc bằng chứng/attempt, dữ liệu poll về | mở "Bằng chứng", mở "Attempt", cuộn timeline, đợi ≥ 3 lượt poll (có và không có sự kiện mới) | phần đã mở vẫn mở, phần tử focus vẫn focus, vị trí cuộn giữ; chỉ số liệu đổi | T: harness đếm poll qua badge `seq`/`đọc`, so `open`, `activeElement`, `scrollTop` trước/sau |
| UX-02 | Đang xem P1 của project A, đổi lọc sang B | chọn project B ở bộ lọc | danh sách chỉ B; chi tiết đóng, ghi "chọn một task của project B"; URL bỏ `plan` | T: harness; F: không có API (chỉ client) |
| UX-03 | Câu hỏi có nhiều lựa chọn | mở chi tiết P1 (request keep/drop) | thấy câu hỏi, từng lựa chọn (id + nhãn, khuyến nghị), mỗi lựa chọn một dòng lệnh đã điền `--choice <id>`, nút "Sao chép"; không nút trả lời | F: `needs_user[].options[].reply_command`; T: harness bấm Sao chép → clipboard/fallback trả đúng lệnh |
| UX-04 | Chọn task ở 1280×720 | click dòng; Tab tới dòng, Enter/Space; ↑/↓ đổi dòng; Esc hoặc "← Danh sách"; reload; Back | chi tiết hiện ngay trong tầm nhìn (cột phải / màn chi tiết), focus vào tiêu đề chi tiết khi chọn bằng bàn phím, Esc trả focus về dòng; reload giữ task; Back về danh sách | T: harness đo `getBoundingClientRect` của chi tiết, `activeElement`, `location.search`, `history.back()` |
| UX-05 | Plan đóng chưa có đầu ra; plan đã kiểm chưa nghiệm thu; đã nghiệm thu | nhìn danh sách | nhãn/màu khác nhau: "đã đóng" (xám), "đã kiểm, chờ nghiệm thu" (xanh ngọc), "đã nghiệm thu" (xanh lá); thời gian ghi đúng đại lượng: "từ khi duyệt (lịch)" ≠ "thực hiện (attempt)" ≠ "chờ" | F: `status.label/outcome`, `elapsed.label`; T: DOM có đúng chữ/lớp |
| UX-06 | Timeline có thế hệ/attempt cũ | mở chi tiết P4 | sự kiện nhóm theo phần việc → attempt, trong nhóm cũ → mới (seq tăng), nhóm attempt cũ gập "lịch sử (n)" và đánh dấu; sự kiện kỹ thuật (attempt.*, executor.managed…) gập "chi tiết kỹ thuật"; bấm một bước → bằng chứng của bước đó | F: `timeline[].stale_attempt`, `evidence_index`; T: harness kiểm thứ tự seq trong DOM, nhóm, click bước |
| UX-07 | Danh sách dày thông tin kỹ thuật | nhìn dòng task | mỗi dòng: trạng thái, tên/mục tiêu ngắn, bước hiện tại, cập nhật gần nhất (tương đối + tuyệt đối), "cần bạn"; ID/đường dẫn/adapter mờ, hash không hiện ở danh sách; bằng chứng có tên/loại/thời điểm ở chi tiết | F: `evidence_index[]` có `kind/at/node/label`; B: ảnh |
| UX-08 | Màn 390×844 và cửa sổ 640 px | mở trang, chọn task, mở bằng chứng | `scrollWidth` ≤ viewport (không cuộn ngang trang); bảng kỹ thuật cuộn trong vùng riêng; điều hướng dùng được | T: harness đo `document.documentElement.scrollWidth` ở 390/640/1280; B: ảnh |
| P2-srv | `track open` gặp marker cũ / cổng bị tiến trình khác dùng / server của wheel khác / hai lần mở cùng lúc | chạy `track open` (script hằng ngày, script SignSDK) | chỉ dùng lại server khi `/api/health` trả đúng `instance` (nonce marker) + version wheel + state-root + phạm vi project; sai → không coi là thành công, không kill tiến trình lạ, mở server mới; hai lần mở cùng lúc → một server, marker không mất; `track stop` chỉ dừng server đã khớp định danh | F: `tests/test_obs1_ux.py` (marker giả, server khác trên cùng cổng, wheel cũ không có `instance`, 2 thread); gói: V15 |
| Mất kết nối / sự kiện muộn / trả ngược thứ tự | server tắt rồi bật; hai request chi tiết về ngược thứ tự | badge "MẤT KẾT NỐI" rồi tự nối lại, dữ liệu cũ giữ nguyên; phản hồi của task đã bỏ chọn không ghi đè task đang chọn | T: harness (proxy chặn `/api/*`, token theo lựa chọn) |
| Đóng UI không dừng worker | tắt server giữa attempt | worker tiếp tục, node vẫn produced | F có sẵn (V8, test web) — giữ |
