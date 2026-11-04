# Bàn giao thử OBS-1 / OBS-2A / OBS-2B — 04/11/2026

Đã có bản thử local cho cả ba lát, không chờ MR-R. Bản OBS-2 mới chứa cả A và B; bản A đã giao vẫn giữ nguyên. Đây là bản development cách ly, chưa phát hành, chưa nghiệm thu và chưa nâng runtime SignSDK.

## Mở ngay

Trang đã mở: http://127.0.0.1:61334/ . Nếu trang tự thoát sau 30 phút không có request, chạy lại:

```powershell
powershell -ExecutionPolicy Bypass -File "D:/OneCrewRuns/obs2/mo-obs2-dev2.ps1"
```

Lệnh in URL hiện hành và dùng đúng gói, venv, project mẫu, sổ thử đã ghim. Không cần cài lại hay chạy lại gate. Dừng đúng trang này:

```powershell
powershell -ExecutionPolicy Bypass -File "D:/OneCrewRuns/obs2/dung-obs2-dev2.ps1"
```

## Anh thử gì

| Chọn | Xem | Kết quả mong đợi |
|---|---|---|
| CODE → Tổng quan | Mục tiêu, đầu ra, phần đang chờ | Nêu đang chờ duyệt bản 2; không coi toàn task đã nghiệm thu |
| CODE → Solution | Bản đề xuất và bản đã duyệt | Phân biệt revision 2 mới đề xuất với revision 1 đã duyệt; quyền chạy có trạng thái riêng |
| CODE → Thay đổi | Trước/sau, lý do, nguồn và phạm vi ảnh hưởng | Thấy sửa hợp đồng và thay đổi kế hoạch nội bộ; không gộp mọi retry thành đổi solution |
| CODE → Kết quả & kiểm chứng | Đầu ra, lượt kiểm, finding và sửa lại | Theo được fail → finding → giao sửa → kiểm lại pass; xem bằng chứng và nguồn đóng finding |
| DOC → Kết quả & kiểm chứng | Đầu ra mới sau một lượt cũ đã pass | Đầu ra mới chưa kiểm vẫn là chưa kiểm; pass cũ không chứng nhận đầu ra mới |
| CODE → Tiến độ | Gantt, từng lượt và số đo | Phân biệt tiếp nhận/chuẩn bị/thực thi; chỗ thiếu mốc ghi chưa xác định |

CODE và DOC là dữ liệu thử tổng hợp qua engine và sổ thật của môi trường thử; không phải công việc SignSDK hoặc kết quả provider thật. Các lượt mẫu rất nhanh nên số giây làm tròn trên màn hình có thể là 0s. Các thao tác duyệt tạo fixture chỉ trên sổ thử, không phải nghiệm thu sản phẩm. UI chỉ đọc; không duyệt/trả lời/dừng task từ trang.

## Định danh cố định

| Lát | Snapshot / gói |
|---|---|
| OBS-1 | dev13, product `79ba44b`; đính chính tài liệu `ec7c279`. Gói `D:/OneCrewRuns/obs1/pkg/onecrew-2.4.0.dev13-obs1-beta` giữ nguyên |
| OBS-2A đã giao | `20cabd5adf954dd741f22150eeaecb2884b37bef`, `2.5.0.dev1`, gói `D:/OneCrewRuns/obs2/pkg/onecrew-2.5.0.dev1-obs2-20cabd5` |
| OBS-2A/B mới | `026fbda7f5da3e4c300d2ffc41b324067089ca74`, `2.5.0.dev2`, gói `D:/OneCrewRuns/obs2/pkg/onecrew-2.5.0.dev2-obs2-026fbda` |
| Wheel mới | SHA256 `30e222686228005044d6becabd27843fa1d63c3681375dac2259fb92b9aeac49` |
| Sổ/venv/project thử mới | `D:/OneCrewRuns/obs2/trial-026fbda-1` |

Mở OBS-1 độc lập bằng `D:/OneCrewRuns/obs1/mo-trang-obs1-dev13.ps1`; đóng bằng `dung-trang-obs1-dev13.ps1` cùng thư mục. Không thay bản A đang mở ở cổng 52193.

## Kiểm chứng

Trên wheel cuối dev2, dùng chính script trong gói, cài offline vào venv sạch ngoài checkout:

- `trial-026fbda-1/verify-report.json`: 9/9 bước đạt, định danh/module/CLI/API, phạm vi bằng chứng và đọc không đổi sổ/project/gói/registry.
- `trial-026fbda-1/browser/browser-report.json`: 56/56 kiểm, 28 mỗi kích thước 1280×720 và 390×844; CODE/DOC, năm tab, lịch sử và bằng chứng. Ảnh `browser/solution.png`, `browser/results.png`.
- `trial-026fbda-1/lifecycle-report.json`: 4/4 mở/dùng lại/dừng/dừng lại đúng điều kiện. Phản chứng hash wheel sai bị từ chối, exit 1, không mở server hay tạo pin.
- `trial-026fbda-1/timing-fields-report.json`: năm lượt có số đo tiếp nhận/chuẩn bị/thực thi từ nguồn hiện hữu. Mười lần đọc detail: p50 0,049s, max 0,074s trên fixture nhỏ này; không suy ra tải production.
- Source: renderer 15/15; data 18 ca ban đầu + ca reviewer zero-call + ca timing được kiểm qua các lượt tập trung (không phải một lượt 20/20 duy nhất). Hồi quy Source/Engine OBS-1 18/18; trình duyệt OBS-1 Gantt/slow25/switch/timeout 75 assertion trong 6 lượt. Đây là phạm vi hồi quy đã chạy, không phải toàn gate 2.2.

Manifest trong gói ghi `browser_verified: false` tại lúc dựng. Bằng chứng browser sau dựng nằm trong trial và ghim đúng commit/hash ở trên; không sửa manifest/gói để cập nhật trạng thái.

## Tái sử dụng và giới hạn

Đọc lại plan/SOL v1, step0/card, contract_diff/internal_plan, finding_core, repair_tasks và receipt/engine/tracking hiện hữu. Không thêm sổ riêng hoặc workflow nghiệp vụ. Các projection/UI mới ở `onecrew/v2/tracking_work.py` và `tracking_work_web.py`; thời gian bổ sung lấy từ measure hiện hữu.

Phân công không chứng minh đã thực hiện; reviewer zero-call không được ghi là đã review. Số lượt test không phải số bug duy nhất. Một attempt không mặc nhiên là một vòng sửa. Kết quả cũ và bằng chứng kế thừa có nguồn/phạm vi; thiếu dữ liệu giữ chưa xác định. Khoảng từ đầu ra đến kết quả kiểm có thể bao gồm chờ, chưa có thời gian bộ kiểm hoạt động riêng. Chưa đo hàng đợi scheduler riêng; thời gian chồng nhau dùng hợp khoảng.

Chưa thử provider thật, clipboard thật, tải sổ lớn hoặc nâng UI trên sổ SignSDK. Không push/tag, không chạy full gate, không ghi nghiệm thu. Registry thật giữ SHA256 `AACAD058F478898D41EB0294B619BE21191B83B488544961C080F4BFA0AEE01C`; venv SignSDK vẫn `2.3.0.dev11`. Các kiểm thử dùng môi trường cách ly; không thay hook/runtime/sổ thật.

MR-R dừng tại checkpoint riêng `D:/OneCrewRuns/codex-mrr-implementation/CHECKPOINT.md`, không chặn bản này. CP-1 chưa bắt đầu. Khi phản hồi UI, chỉ cần nêu task, tab và điều anh mong nhìn thấy; không cần tự chạy lại toàn bộ kiểm.
