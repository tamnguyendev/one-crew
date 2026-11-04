# Thử OBS-2 từ wheel local

Đây là gói thử UI OBS-2A/2B, dùng dữ liệu tổng hợp trong thư mục riêng. Không thay runtime, hook, registry hay sổ đang dùng; không gọi provider, không push/tag, không chứng nhận nghiệm thu. MRR không là điều kiện để thử OBS-2A.

Script dựng lấy **commit đầy đủ được chỉ định** qua `git archive`, rồi tái dùng `tests/wf_wheel.py` trên bản xuất đó. Thay đổi chưa commit của checkout không đi vào wheel. Chỉ dựng sau khi đã chốt commit chứa giao diện, dữ liệu, khai báo module trong `pyproject.toml` và các script này. Mỗi lần dùng thư mục gói và thư mục thử mới, nằm ngoài checkout.

```powershell
python docs/obs2/tools/build_obs2.py --commit <SHA-40-ký-tự> --out D:\OneCrewRuns\obs2\pkg\<tên-gói-mới>
python -I D:\OneCrewRuns\obs2\pkg\<tên-gói-mới>\verify\verify_obs2.py D:\OneCrewRuns\obs2\pkg\<tên-gói-mới> D:\OneCrewRuns\obs2\trial-<tên-mới>
```

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
python -I -B D:\OneCrewRuns\obs2\pkg\<tên-gói-mới>\verify\obs2_artifact_browser.py D:\OneCrewRuns\obs2\pkg\<tên-gói-mới> D:\OneCrewRuns\obs2\trial-<tên-mới>
```

Runner cần Chrome hoặc Edge có sẵn, kiểm tương tác ở 1280×720 và 390×844, ghi `trial-...\browser\browser-report.json` cùng ảnh Solution/Kết quả; không có browser thì không tính là đạt. Bằng chứng browser được ghi riêng trên đúng wheel/package ở bàn giao; chưa có bằng chứng đó thì không gọi OBS2-T8 hoàn tất. Không chạy lại full gate 2.2 chỉ để thử UI này.
