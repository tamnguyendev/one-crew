# Bàn giao UI/UX OBS-2 dev3 — 04/11/2026

Bản thử local đã kiểm từ wheel cuối. Có OBS-2A/2B trên nền OBS-1; không chờ MR-R. Chưa nâng SignSDK, chưa push/tag hoặc nghiệm thu.

## Mở bản thử

Trang hiện hành: http://127.0.0.1:64836/ . Khi trang tự thoát sau 30 phút không có request, chạy:

```powershell
powershell -ExecutionPolicy Bypass -File "D:/OneCrewRuns/obs2/mo-obs2-dev3.ps1"
```

Dừng đúng viewer này, không dừng worker:

```powershell
powershell -ExecutionPolicy Bypass -File "D:/OneCrewRuns/obs2/dung-obs2-dev3.ps1"
```

CODE và DOC là dữ liệu thử; không cần duyệt để xem UI. Giữ nguyên các bản dev1/dev2 và OBS-1 dev13 đã giao.

## Những gì đã đổi

- Bảng thẻ theo giai đoạn: Chưa bắt đầu → Đang xử lý → Chờ kiểm → Chờ nghiệm thu → Hoàn tất; Đã đóng/Chưa xác định tách riêng. Chỉ đọc, không kéo thả để đổi sổ. Cột **Đang xử lý** là giai đoạn; bộ đếm **Đang chạy** chỉ tính thực thi đang hoạt động.
- Trạng thái nói chờ ai: chờ bạn duyệt kế hoạch, chờ bạn trả lời, đã có đầu ra chờ kiểm, đã kiểm đạt chờ nghiệm thu. Nhãn **quyết định cần bạn** độc lập với giai đoạn. Phương án mới chưa duyệt không được xếp chờ nghiệm thu chỉ vì bản cũ đã pass.
- Sắp xếp được ghi rõ: cần xử lý trước, cập nhật, ngày tạo, hạn. Thiếu hạn xếp sau, không biến ngân sách giờ thành ngày hẹn.
- Thẻ quyết định thu gọn; mở ra thấy nội dung, vì sao, ảnh hưởng, nút xem thay đổi và khối PowerShell có **Sao chép lệnh**. Đường runtime/project/sổ/revision được ghim. Phần lý do/lựa chọn cần điền được đánh dấu; sao chép không duyệt.
- Lệnh `owner ... --human` có kết quả ngắn và mã thoát đúng; mặc định JSON cũ giữ nguyên. Không tự duyệt trong phiên AI. Chỉ đưa lệnh nghiệm thu khi đủ artifact/revision có nguồn; thiếu thì giải thích và đưa lệnh xem báo cáo.
- Tổng quan, Solution, Thay đổi, Kết quả & kiểm chứng, Tiến độ/Gantt dùng lại dữ liệu sẵn có. Đầu ra hiện hành đứng trước lịch sử; chuỗi kiểm → giao sửa → kiểm lại có liên kết. Pass cũ không chứng nhận đầu ra mới.

## Thử nhanh

| Thao tác | Mong đợi |
|---|---|
| Bảng → CODE | Đang xử lý, nhãn chờ duyệt kế hoạch; 1 quyết định cần bạn |
| Bảng → DOC | Chờ kiểm, không có quyết định dành cho bạn |
| CODE → thẻ Duyệt kế hoạch | Thấy bản 2, nội dung/lý do/ảnh hưởng; mở Thay đổi trước khi quyết định |
| Sao chép lệnh | Có phản hồi sao chép; sổ vẫn chờ duyệt. Điền phần đánh dấu rồi tự chạy trong PowerShell khi muốn thử quyết định trên sổ mẫu |
| CODE → Solution/Thay đổi | Bản đề xuất 2 khác bản đã duyệt/có thể thực hiện 1; lịch sử nội bộ có số riêng |
| CODE → Kết quả & kiểm chứng | Mở đầu ra; cuộn xem fail/finding/giao sửa/kiểm lại; không coi số lượt kiểm là số bug |
| DOC → Kết quả & kiểm chứng | Đầu ra mới chưa kiểm, pass cũ nằm trong lịch sử |

## Snapshot và bằng chứng

- Product commit: `ff81554de7f3a99ae0bdc9d0fc9ef1cfc0f791c9`; version `2.5.0.dev3`.
- Gói: `D:/OneCrewRuns/obs2/pkg/onecrew-2.5.0.dev3-obs2-ff81554`.
- Wheel SHA256: `a3ef09d2c5ac16da2631dfafe0a078b084a0a89a83e0debc61adf95002fc3869`.
- Trial: `D:/OneCrewRuns/obs2/trial-ff81554-1`.
- `verify-report.json`: **9/9**; tám module nhập từ venv đúng hash, CLI/API/evidence, read-only, mở/dùng lại/dừng; mười lượt đọc fixture nhỏ p50 0,053s, max 0,073s. Không suy hiệu năng sổ lớn.
- `browser/browser-report.json`: **90/90**, 45 mỗi cỡ 1280×720 và 390×844. Ảnh board/overview/solution/results/decision đã xem trực tiếp. Browser stop đúng instance.
- `lifecycle-report.json`: **4/4**, mở/dùng lại/dừng/dừng lần nữa với mã thoát mong đợi; state/project/gói/registry không đổi trong khoảng kiểm.
- `D:/OneCrewRuns/obs2/owner-human-wheel-ff81554-1/owner-human-report.json`: hai entrypoint JSON/human từ chối đúng trong phiên AI, exit2, không ghi approval hoặc đổi sổ. Thao tác chủ thành công được kiểm qua fixture ở source, chưa có thao tác người thật trên wheel này.
- Source cuối: renderer/cards **25/25**, cộng ca G2 được sửa cách ly **1/1**. Các suite owner13/13, dữ liệu/acceptance/replay/phản chứng A-pass/B-fail đã đạt qua các lượt tập trung; không cộng các lượt trùng thành số test duy nhất.
- Hồi quy OBS-1 Source/Engine **18/18** và sáu lượt Gantt/slow25/switch/timeout đạt trước các chỉnh cuối về nhóm thẻ, nhãn và thu gọn. Đường timeout/poll không đổi sau đó; final browser ở trên kiểm trên wheel cuối. Không chạy full gate 2.2.

Manifest giữ nguyên trạng thái lúc build; receipt sau build nằm ngoài gói. Hai gói dev3 trước `025c8ca` và `47fc8f3` giữ làm bằng chứng trung gian, không phải bản giao này. Review ảnh phát hiện trường hợp pending amendment bị xếp theo pass cũ và khối quyết định chiếm màn hình; đã thêm phản chứng và kiểm bản cuối.

## Cách ly và sự cố test đã khôi phục

Runtime SignSDK vẫn `2.3.0.dev11`; không nâng hook/venv/sổ công việc. Một test G2 lịch sử đã đăng ký project tạm vào registry host vì không cô lập LOCALAPPDATA. Đã xác định đường gọi, chỉ loại đúng mục fixture và khôi phục byte-for-byte hash ban đầu `AACAD058F478898D41EB0294B619BE21191B83B488544961C080F4BFA0AEE01C`. Fixture G2 nay cô lập LOCALAPPDATA/APPDATA; chạy lại ca gây rò đạt, hash host không đổi. Báo cáo: `D:/OneCrewRuns/obs2/isolation-recovery/recovery-report.json`. Không tuyên bố registry chưa từng bị chạm; kiểm gói/lifecycle cuối xác nhận hash ban đầu ổn định.

Giới hạn: dữ liệu mẫu, chưa provider/pilot/sổ lớn, chưa chứng minh clipboard của trình duyệt thật của người dùng (harness kiểm nội dung đúng hoặc thông báo thất bại rõ), chưa thao tác duyệt thật trên wheel. UI chỉ theo dõi nguồn có trong sổ; không tự theo dõi mọi phiên chat. Cột/thẻ không là cơ chế đổi quyền. MR-R giữ checkpoint riêng; CP-1 chưa triển khai trong lượt này.
