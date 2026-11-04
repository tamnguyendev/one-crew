# Thử OBS-2 — bảng công việc và timeline dev10

Bản dev7 kế thừa bảng thẻ theo giai đoạn, lọc/sắp xếp chỉ để xem; trạng thái và quyết định cần bạn tách riêng. Mở thẻ để xem phương án, thay đổi, đầu ra hiện hành và vòng kiểm/sửa. Thông tin kỹ thuật thu gọn; thiếu dữ liệu vẫn ghi chưa xác định.

Timeline dev7: mỗi phần việc là một dòng có tên/trạng thái/thời lượng; bấm tên hoặc thanh để mở chi tiết, mũi tên mở từng lượt. Mặc định chỉ khung hiện hành; mở lịch sử sẽ chọn toàn bộ lịch sử và giữ khung qua poll. **Toàn bộ lịch sử** mở ngay các lượt cũ; **Về hiện hành** thu gọn lại và theo dữ liệu mới. Đơn vị trục tương đối tự đổi theo khoảng, không coi cửa sổ vẽ là thời gian thực thi. Khoảng **Từ đầu ra đến kết quả kiểm** có thể gồm chờ, chưa phải thời gian chạy verifier. Số liệu thiếu giữ chưa đủ mốc đo; không cộng đôi song song. Gantt nằm đầu tab Tiến độ, bảng số đo chi tiết thu gọn phía dưới. Gantt cuộn bên trong trên màn nhỏ, ngăn chi tiết nằm bên dưới. Mục nguồn/timestamp đang mở được giữ qua poll. Đầu ra trùng chỉ hiện một lần, các lần ghi nhận vẫn xem được trong phần Nguồn.

Trong thẻ quyết định, đọc thay đổi trước, sao chép khối PowerShell, điền lý do/lựa chọn được đánh dấu rồi chạy trong terminal của bạn. Các lệnh dùng `owner ... --human` để trả kết quả ngắn. Sao chép không ghi quyết định; không chạy thay chủ trong phiên AI. JSON mặc định giữ nguyên cho công cụ. Nghiệm thu chỉ được nhắc khi các mốc và bằng chứng bàn giao trong sổ đủ điều kiện; node pass riêng chưa đủ. Đây là trạng thái theo bằng chứng đã ghi, không phải kiểm lại project hiện tại; lệnh nghiệm thu vẫn kiểm hiện trạng trước khi ghi. Lệnh có tác dụng ghi chỉ xuất hiện khi hook project khớp chính runtime viewer và sổ này. Chưa có hook, khác runtime/sổ hoặc cấu hình hỏng: trang nêu lý do, không cung cấp mẫu ghi kể cả cho từng lựa chọn câu hỏi. Không tự đổi hook hay nâng runtime để mở khóa nút sao chép.

Chưa cần duyệt dữ liệu mẫu để xem UI. Bản đã tạo dùng để thử cách ly; hướng dẫn bàn giao ngoài gói cung cấp lệnh mở/dừng cụ thể.

Đây là gói thử UI OBS-2A/2B, dùng dữ liệu tổng hợp trong thư mục riêng. Không thay runtime, hook, registry hay sổ đang dùng; không gọi provider, không push/tag, không chứng nhận nghiệm thu. MRR không là điều kiện để thử OBS-2A.

Script dựng lấy **commit đầy đủ được chỉ định** qua `git archive`, rồi tái dùng `tests/wf_wheel.py` trên bản xuất đó. Thay đổi chưa commit của checkout không đi vào wheel. Chỉ dựng sau khi đã chốt commit chứa giao diện, dữ liệu, khai báo module trong `pyproject.toml` và các script này. Mỗi lần dùng thư mục gói và thư mục thử mới, nằm ngoài checkout.

```powershell
$Python = 'C:\Users\NUC\AppData\Local\Programs\Python\Python313\python.exe'
& $Python docs/obs2/tools/build_obs2.py --commit <SHA-40-ký-tự> --out D:\OneCrewRuns\obs2\pkg\<tên-gói-mới>
& $Python -I -X utf8 -B D:\OneCrewRuns\obs2\pkg\<tên-gói-mới>\verify\verify_obs2.py D:\OneCrewRuns\obs2\pkg\<tên-gói-mới> D:\OneCrewRuns\obs2\trial-<tên-mới>
```

Chọn đường dẫn Python thường có thật trên máy, tránh alias Microsoft Store khi cần đối chiếu registry với PowerShell: alias đó có thể chuyển `%LOCALAPPDATA%` sang `Packages/.../LocalCache` dù chuỗi đường dẫn nhìn giống nhau. Báo cáo ghi cả đường dẫn yêu cầu, đường dẫn đã resolve và interpreter; hash chỉ chứng minh khoảng quan sát của đúng tệp đó.

Verifier kiểm hash gói/wheel/module, cài offline vào venv mới, đối chiếu nguồn import đã cài và hash `direct_url.json`; tạo hai root CODE và DOC bằng workflow/Control/receipt hiện có. CODE có assertion không đạt trên ứng viên thiếu nội dung, finding, repair, ứng viên mới kiểm đạt, kiểm tích hợp và revision 2 còn chờ duyệt. DOC tạo văn bản, giữ lần kiểm cũ và tạo lượt thử lại kỹ thuật với đầu ra mới chưa kiểm. Đây là assertion và actor của fixture, không là provider hay dự án khách hàng thật.

Sau đó verifier mở server của wheel đã cài, đọc `/api/task`, so `detail.work` với CLI, mở đúng evidence được phép, kiểm ledger/project không đổi byte và registry thật không đổi hash; lần mở lại phải dùng cùng instance. Đo 10 lượt đọc chi tiết CODE/DOC, ghi từng lượt, p50 và max; mỗi lượt phải ≤ 2 giây trên fixture nhỏ này, không suy hiệu năng sổ lớn. Dừng bằng URL + instance + PID + thời điểm khởi động. Marker nằm ngoài sổ thử, trong `trial-...\markers`. Kết quả nằm ở `verify-report.json`, `code-detail.json`, `doc-detail.json`; `manifest.json` và `SHA256SUMS` ở gói. Kết quả `pass` của verifier này chỉ bao phủ các bước trên.

Mở lại để xem giao diện bằng trình duyệt mặc định:

```powershell
powershell -ExecutionPolicy Bypass -File D:\OneCrewRuns\obs2\pkg\<tên-gói-mới>\verify\mo-trang-obs2.ps1 -Package D:\OneCrewRuns\obs2\pkg\<tên-gói-mới> -Work D:\OneCrewRuns\obs2\trial-<tên-mới>
powershell -ExecutionPolicy Bypass -File D:\OneCrewRuns\obs2\pkg\<tên-gói-mới>\verify\dung-trang-obs2.ps1 -Package D:\OneCrewRuns\obs2\pkg\<tên-gói-mới> -Work D:\OneCrewRuns\obs2\trial-<tên-mới>
```

Cặp script chỉ nhận sổ tổng hợp do verifier tạo, kiểm version/hash/commit rồi tái dùng nguyên cặp OBS-1 đã có cơ chế ghim `viewer-pin.json`. Không quét thư mục, không dừng theo tên tiến trình, không trỏ sang sổ thật. Đóng trình duyệt không trả lời, duyệt hay dừng task; script dừng chỉ dừng viewer đã ghim.

Trong trang, chọn CODE/DOC rồi xem năm tab Tổng quan, Solution, Thay đổi, Kết quả & kiểm chứng, Tiến độ. Chuỗi kiểm/sửa nằm trong Kết quả & kiểm chứng. Kiểm mục tiêu và tên phần việc tiếng Việt, bản đang áp dụng so với đề xuất mới, nguồn kết quả/receipt, finding được khép bằng kiểm sau sửa và đầu ra tài liệu mới còn chưa kiểm. Secret/project boundary tiếp tục đi qua cửa chỉ đọc hiện có. Thiếu testcase/actor/link thì hiển thị chưa xác định; check/finding không tự là bug độc lập, attempt không tự là vòng sửa.

Verifier nhỏ không tự mở Chrome/Edge hoặc chụp ảnh desktop/mobile. Gói kèm `verify/tests/obs1_ux_harness.py`, `obs2_ux_harness.py` và namespace riêng để lượt kiểm browser bên ngoài dùng đúng harness của snapshot. Sau khi verifier đã đạt, có thể chạy lượt browser riêng trên wheel đã cài:

```powershell
& $Python -I -X utf8 -B D:\OneCrewRuns\obs2\pkg\<tên-gói-mới>\verify\obs2_artifact_browser.py D:\OneCrewRuns\obs2\pkg\<tên-gói-mới> D:\OneCrewRuns\obs2\trial-<tên-mới>
```

Runner cần Chrome hoặc Edge có sẵn, kiểm tương tác ở 1280×720 và 390×844, ghi `trial-...\browser\browser-report.json` cùng ảnh Solution/Kết quả; không có browser thì không tính là đạt. Bằng chứng browser được ghi riêng trên đúng wheel/package ở bàn giao; chưa có bằng chứng đó thì không gọi OBS2-T8 hoàn tất. Không chạy lại full gate 2.2 chỉ để thử UI này.

Kiểm entrypoint owner trên wheel (chỉ thử từ chối, giữ dấu phiên AI, không ghi duyệt): `verify/check_owner_human.py <trial> <thư-mục-kết-quả-mới>`. Thành công thực hiện owner được kiểm qua fixture có nhãn ở source; thao tác thật của chủ chưa được coi là đã kiểm.

Dev6 sửa phân cột chờ kiểm, điều kiện trình nghiệm thu, binding runtime, mô tả finding, bằng chứng văn bản, nhãn kế hoạch ban đầu và trục nhiều ngày. Kiểm phản chứng từ wheel: dùng Python trong venv thử với `-I -X utf8 -B <gói>/verify/check_review_fixes.py <thư-mục-thử-mới>`. Script chỉ tạo dữ liệu tổng hợp; hook fixture chỉ ở project mới, không đăng ký vào registry thật.

Dev7 khép phản hồi review dev6: không có khung copy rỗng khi hook thiếu/lệch; plan dạng mốc đã có verdict không gọi chưa khởi chạy; finding JSON bị cắt vẫn có mô tả; kế hoạch ban đầu có nội dung riêng. Kiểm DOM từ wheel bằng Python venv thử: `-I -B -X utf8 <gói>/verify/check_unbound_browser.py <thư-mục-mới>`. Bộ kiểm dùng project/sổ mới chỉ propose, không duyệt; kiểm missing/other-runtime/other-state/bound trên desktop và mobile.

Dev8 khép review dev7. (1) Binding hook đổi trong lúc trang đang mở mà sổ không có sự kiện mới: ở lần đọc kế tiếp thẻ "Việc cần bạn" tự cập nhật (mất binding thì không còn lệnh ghi, nút sao chép hay thông báo sao chép cũ; gắn lại thì chỉ hiện lệnh hiện hành), giữ task, tab và vị trí đọc; bấm sao chép trên thẻ vẽ trước khi dữ liệu đổi không chép lệnh đã hết hiệu lực. (2) Plan dạng mốc đã có verdict, lượt kiểm hoặc lượt chạy, kể cả verdict thất bại, không còn hiện "Chưa khởi chạy"; trạng thái nói rõ mốc kiểm chưa đạt và mốc còn chờ verdict; điều kiện nghiệm thu không đổi. Kiểm DOM đổi binding giữa phiên từ wheel bằng Python venv thử: `-I -B -X utf8 <gói>/verify/check_binding_live.py <thư-mục-mới>` (mỗi ca tự xác nhận tiền điều kiện: ban đầu đã gắn hook, có lệnh và có thông báo sao chép; thiếu hook / khác runtime / khác sổ trên desktop và mobile; thêm hai ca thời gian thực đọc chậm khi đổi task).

Dev9 khép P3 focus của review dev8: sau khi sao chép (thành công hoặc thất bại) focus ở lại đúng nút của đúng lựa chọn trong đúng thẻ; nút không còn (mất binding, đổi bản) thì về tiêu đề của thẻ, thẻ không còn thì về tiêu đề task; kết quả sao chép về muộn không kéo focus hay vị trí đọc về chỗ cũ. Ca `focus-desktop`/`focus-mobile` trong `verify/check_binding_live.py` dùng clipboard giả có kiểm soát (headless không cho clipboard thật).

Dev10 khép P2 của review dev9: một lần sao chép không còn là lần hiện hành (đã có lần sao chép mới hơn, đã đổi task kể cả khi quay lại, mất binding, hoặc dữ liệu hiện tại đã đổi bản/lệnh/thẻ) thì khi trình duyệt trả kết quả muộn, trang không thử sao chép dự phòng, không đổi thông báo của lần mới, không kéo focus hay vị trí đọc. Lần sao chép hiện hành vẫn như cũ: thành công; bị từ chối thì sao chép dự phòng; dự phòng cũng hỏng thì báo rõ để sao chép tay. Thao tác clipboard đã gửi tới trình duyệt thì không hủy được. Ca `late-desktop`/`late-mobile` trong `verify/check_binding_live.py` dùng clipboard giả và ghi lại mọi lần sao chép dự phòng; mỗi ca tạo một bản sửa mới của P3 (tác giả fixture, không phải lệnh của chủ) để kiểm trường hợp đổi bản; sổ chỉ đổi trong các lần sửa đó.
