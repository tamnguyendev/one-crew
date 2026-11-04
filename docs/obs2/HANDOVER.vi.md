# Bàn giao timeline OBS-2 dev5 — 04/11/2026

**Bản thử hiện hành 2.5.0.dev5**, code `d2e592a4e99c3a79e69d7f627105200a92268803`. Đã khép 5 finding trong phạm vi local và kiểm wheel cuối; chưa phát hành/nghiệm thu/provider thật. Các phần dev4/dev3 bên dưới là lịch sử.

## Mở bản thử

http://127.0.0.1:55268/ — health đã xác nhận pid 27604, instance 9648ed48bb2ea612, read_only, đúng dev5. Nếu viewer tự thoát sau 30 phút không request:

```powershell
powershell -ExecutionPolicy Bypass -File "D:/OneCrewRuns/obs2/mo-obs2-dev5.ps1"
```

Dừng đúng viewer thử này:

```powershell
powershell -ExecutionPolicy Bypass -File "D:/OneCrewRuns/obs2/dung-obs2-dev5.ps1"
```

Chọn **DOC hoặc CODE → Tiến độ**. Sổ/project là dữ liệu mẫu, không cần duyệt để xem UI; các nút sao chép không ghi quyết định.

| Thử | Kết quả mong đợi |
|---|---|
| Mở Tiến độ | Thấy Gantt trước; bảng từng lượt và nhật ký kỹ thuật thu gọn phía dưới |
| Dóng thanh theo nhãn | Đường lưới thẳng hàng với chính mốc0/50ms/…; không chia 25% cố định |
| Bấm tên hoặc thanh | Tên bước, trạng thái/thời lượng chính xác và đầu ra lên trước ID/thế hệ |
| Mở Chi tiết lượt → Thời điểm chính xác | Có timestamp ISO gốc; mở/đóng được giữ khi poll |
| Xem đầu ra DOC | Cùng artifact hiện 1 lần; mở Nguồn vẫn thấy 2 lần ghi nhận với nguồn riêng |
| Chọn Toàn bộ lịch sử | Các lượt cũ mở ngay; khung lịch sử đứng yên |
| Bấm Về hiện hành | Thu gọn lịch sử, trở về lượt hiện hành và tiếp tục theo dữ liệu mới |

## Snapshot và bằng chứng

- Gói `D:/OneCrewRuns/obs2/pkg/onecrew-2.5.0.dev5-obs2-d2e592a`.
- Wheel SHA256 `6122d0a5ec3c1b979e11a95ea73ef82f4ce0e25f6a873993055cdccbed7bc20f`.
- Receipt root `D:/OneCrewRuns/obs2/trial-d2e592a-1`.
- `verify-report.json`: **9/9**, wheel/import đúng 8 module, CLI/API/evidence, project/sổ và registry không đổi.
- `browser/browser-report.json`: **140/140 assertion**,70 desktop1280×720 và70 mobile390×844. Bao gồm disclosure qua poll, vị trí Gantt ngay sau click, grid/tick, lịch sử, nguồn đầu ra và cửa evidence. Đã xem `browser/timeline.png` và `timeline-mobile.png`; harness không tự cuộn đến Gantt để chụp.
- `lifecycle-report.json`: **4/4**, mở/dùng lại/dừng/dừng lần nữa; đúng mã thoát, cùng instance khi reuse; state/project/package/registry không đổi.
- Source: **49/49 unit**;4 phản chứng mới đỏ trên dev4 trước khi sửa, xanh sau sửa. Source browser 140/140 đạt.
- Phản chứng browser cùng harness trên wheel dev4: `D:/OneCrewRuns/obs2/dev5-counterexample-dev4/report-complete.json`, **14/70 assertion đỏ**, không exception, bao phủ cả5finding. `report.json` trước đó giữ nguyên, có exception vì harness giả định disclosure mới tồn tại; bản hoàn chỉnh ghi fail thay vì dừng ở phần tử thiếu.
- OBS-1 hồi quy source tập trung: Gantt 22 desktop + 20 mobile (`dev5-gantt-final`), clock 10, evidence 8, slow25s 5, switch 6 (`dev5-obs1-regression`): **71 assertion đạt**. Lượt Gantt trước đỏ 2 assertion/cỡ vì kỳ vọng lịch sử vẫn gập khi chọn all; đã đổi đúng hành vi được giao, giữ oracle vị trí thanh/thời gian/nguồn và chạy lại riêng Gantt. Không cộng số assertion thành số testcase độc lập.

Không chạy toàn gate; không thay schema, quyền, engine hoặc cửa evidence. Tái sử dụng snapshot/restore, dữ liệu tracking, renderer và bộ dựng/kiểm gói. Gói/bản thử cũ giữ nguyên. SignSDK vẫn 2.3.0.dev11, registry thật giữ SHA256 `AACAD058F478898D41EB0294B619BE21191B83B488544961C080F4BFA0AEE01C`.

Giới hạn: fixture tổng hợp, chưa pilot/sổ lớn/provider hoặc clipboard thật của người dùng; mobile cuộn ngang trong biểu đồ, không tràn cả trang. Phản chứng poll inject cờ live-axis trong phản hồi thử, không ghi sổ. Source/time/duration là khoảng quan sát có nguồn, không suy checker-CPU hoặc ETA chắc chắn. Chưa push/tag/nghiệm thu; không chờ MR-R.

---

# Bàn giao timeline OBS-2 dev4 — 04/11/2026

Bản thử hiện hành: **2.5.0.dev4**, product `525c36138eaf77d5d4ef482e193322ce4be7bf3d`. Đã kiểm trên wheel cuối, chưa phát hành/nghiệm thu. Nội dung dev3 bên dưới là lịch sử, không phải lệnh mở bản mới.

## Mở và thử timeline mới

Trang: http://127.0.0.1:51281/ (pid30604, instance `7a758b5c5d6572ce`, đã kiểm health đúng dev4). Nếu server đã tự thoát sau 30 phút không request:

```powershell
powershell -ExecutionPolicy Bypass -File "D:/OneCrewRuns/obs2/mo-obs2-dev4.ps1"
```

Dừng riêng viewer này:

```powershell
powershell -ExecutionPolicy Bypass -File "D:/OneCrewRuns/obs2/dung-obs2-dev4.ps1"
```

Chọn **DOC hoặc CODE → Tiến độ**. Đây là dữ liệu mẫu, không phải công việc/provider thật; không cần duyệt để xem.

| Thao tác | Mong đợi |
|---|---|
| Mở Tiến độ | Mỗi phần việc có tên, trạng thái và thời lượng; các ID lượt không chiếm hàng chính |
| Bấm tên phần việc hoặc thanh | Xem chi tiết, người thực hiện nếu có nguồn, bằng chứng đúng lượt/thế hệ và timestamp gốc |
| Mở mũi tên | Xem các lượt; lịch sử cũ mở riêng, có nguồn, không chứng nhận đầu ra mới |
| Chọn toàn bộ lịch sử | Cửa sổ thời gian đứng yên khi poll; chọn Vừa khung để trở lại phần hiện hành |
| Xem lượt dưới một giây | Trục tương đối có mili giây, không lặp nhãn giây; độ rộng cửa sổ không phải thời lượng thực thi |
| Xem trên màn hẹp | Cuộn ngang bên trong biểu đồ; chi tiết nằm dưới, trang không tràn ngang |

Nhãn **Từ đầu ra đến kết quả kiểm** diễn tả khoảng quan sát, có thể gồm thời gian chờ; không gọi đó là thời gian checker thực sự chạy. Thiếu dữ liệu vẫn ghi chưa xác định. Ngăn chi tiết chỉ xuất hiện sau khi chọn; chú giải chỉ hiện loại đang có.

## Snapshot và kiểm chứng dev4

- Gói: `D:/OneCrewRuns/obs2/pkg/onecrew-2.5.0.dev4-obs2-525c361`.
- Wheel SHA256: `e19b6639af8a266d68d1d0b57ff3f587a38c9b0c203e5b7bab50c7d2a52382d8`.
- Receipt: `D:/OneCrewRuns/obs2/trial-525c361-1`.
- `verify-report.json`: **9/9**, nhập tám module đúng hash từ venv, CLI/API/evidence và cách ly.
- `browser/browser-report.json`: **108/108 assertion** trên wheel cuối, 54 ở desktop1280×720 và 54 ở mobile390×844. Đã xem ảnh `browser/timeline.png` và `browser/timeline-mobile.png`.
- `lifecycle-report.json`: **4/4**, mở/dùng lại/dừng/dừng lần nữa; exit0/0/0/2 đúng dự kiến, state/project/gói/registry không đổi trong kiểm.
- Source cuối: **45/45 test** timeline/cards/web/clock. OBS-1 hồi quy có phạm vi: Gantt desktop22, mobile20, phản hồi chậm25s5, chuyển task6 và đồng hồ/mất-kết-nối10 assertion đạt. Hai assertion lượt clock đầu dùng setup lịch sử đóng/nhãn cũ; đã sửa setup phù hợp UI mới, giữ kiểm hình học và chạy lại10/10 tại `dev4-live-clock`.
- Không chạy toàn gate. Không nhận bằng chứng provider thật, clipboard người dùng, sổ lớn hay nghiệm thu từ dữ liệu mẫu. Không kiểm lại owner-success ở lượt này; quyền/backend không đổi.

Gói trung gian `...dev4-obs2-1dcb7c7` giữ nguyên, không phải bản giao cuối. Bổ sung cuối ở525c361 giữ timestamp ISO gốc có offset/mili giây trong chi tiết. Gói dev3 và viewer cũ không bị thay. Báo cáo sau build nằm ngoài gói đóng băng.

Runtime SignSDK vẫn `2.3.0.dev11`. Registry thật giữ SHA256 `AACAD058F478898D41EB0294B619BE21191B83B488544961C080F4BFA0AEE01C` trong lượt dev4; không nâng runtime/hook/sổ thật. Không push/tag, không chờ MR-R, không mở rộng OBS-2C/CP-1. Lịch sử sự cố registry dev3 và khôi phục vẫn giữ bên dưới.

---

# Lịch sử: Bàn giao UI/UX OBS-2 dev3 — 04/11/2026

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
