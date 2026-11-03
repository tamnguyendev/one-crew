# Ghi chú — OneCrew `2.4.0.dev12` (OBS-1 beta: các bản sửa R1–R5 theo review phát hành độc lập của Codex trên dev11; chưa nghiệm thu)

Snapshot, wheel và SHA256 của gói này: `manifest.json` cạnh file này (và dòng đầu `BAT-DAU-THU.vi.md`). Ghi chú này chỉ đúng cho đúng snapshot/wheel đó.

## Có gì

- `2.4.0.dev6` (beta 2.4 đã phát hành 03/11, tag `v2.4.0.dev6`) + lát **OBS-1**: `onecrew track list|show|evidence|serve|open` — màn hình theo dõi chỉ đọc (danh sách task, chi tiết + timeline, bằng chứng, trang web local).
- Bốn bản sửa sau review Codex 03/11 (P2-01 đóng ≠ nghiệm thu; P2-02 quan sát attempt cũ; P2-03 khoảng chờ đã kết thúc; P2-04 giới hạn project của server) — từ `2.4.0.dev7`.
- **Mới ở dev8 — vòng UI/UX theo hướng Blazo** (review Codex UX trên dev7, UX-01…UX-08): tổng quan → chi tiết task → timeline theo phần việc/attempt → bằng chứng của từng bước; hai cột trên màn rộng, danh sách ↔ chi tiết trên màn hẹp; phần đang đọc/focus/cuộn giữ nguyên qua các lượt poll; đổi project đóng chi tiết của project khác; câu hỏi hiện đủ lựa chọn với lệnh trả lời để sao chép (không tự trả lời); chọn bằng bàn phím, chi tiết trong tầm nhìn, URL giữ task khi reload/Back; ba kiểu "xong" ba nhãn/màu (đã nghiệm thu / đã kiểm, chờ nghiệm thu / đã đóng); nhãn thời gian đúng đại lượng (từ khi duyệt – lịch / thực hiện – attempt / chờ); timeline cũ → mới, lịch sử attempt cũ và sự kiện kỹ thuật gập lại; bằng chứng có tên/loại/thời điểm. **P2 định danh server**: `track open` chỉ dùng lại server khớp instance/version/sổ/phạm vi, không dừng tiến trình lạ, khóa khi mở đồng thời; thêm `track status`, `track stop`, `track open --no-browser`; script `verify\mo-trang-obs1.ps1` / `dung-trang-obs1.ps1`. Chi tiết: `docs/CHANGELOG.md`, `BAO-CAO-OBS-1.vi.md`, ma trận `UX-OBS-1.vi.md`.
- **Mới ở dev11 (review Codex trên dev10 `5e66903`, 3 P2 + 1 P3):** đoạn "tới hiện tại"/đường hiện tại/cuối trục tiến theo đồng hồ server mỗi poll kể cả khi sổ im (mất kết nối → đứng + nhãn); ngăn chi tiết chỉ hiện đầu ra/bằng chứng của đúng lượt hoặc (phần việc, thế hệ) đang chọn, "chưa có đầu ra" nói rõ, kế thừa hợp lệ hiện riêng với nguồn; mọi phép so thời gian của timeline theo giá trị (không so chuỗi khác offset); ở 1280×720 thấy trọn trục không cuộn ngang (cây 170 px, ngăn chi tiết dưới biểu đồ tới 1400 px).
- **Mới ở dev12 (review phát hành độc lập của Codex trên dev11 `7c8bfca`, 4 P2 + 1 P3):** R1 bằng chứng gắn đúng sự kiện/phần việc/thế hệ/lượt của từng lần dùng (hai thế hệ cùng bytes không lẫn nhãn; vừa kế thừa vừa tạo mới cùng hiện; lịch sử dài hơn cửa sổ tải không bao giờ thành "không có đầu ra", nhật ký nói phần chưa tải); R2 server/CLI chỉ một project không lộ đường dẫn hay sổ của project khác ở bất kỳ trường nào; R3 một chốt lọc bí mật cho mọi đầu ra (sổ giữ nguyên); R4 chi tiết luôn là của task đang chọn khi đang tải/lỗi/trả muộn/khôi phục, kết nối tổng quan và độ mới chi tiết hiện riêng, chi tiết chậm hơn chu kỳ poll vẫn hiện; R5 lối mở/dừng ghim cứng vào gói + lần chạy đã nghiệm, dừng đúng viewer đã mở. Chi tiết `docs/CHANGELOG.md`, `GIAI-PHAP-OBS-1.vi.md` §10, bảng `UX-OBS-1.vi.md` §5.
- Không đổi gì ở runtime 2.4: lát chỉ thêm module `onecrew/v2/tracking*.py`, nhóm lệnh `track` và test; không ghi sổ, không hook, không model.

- **Mới ở dev9 (review Codex trên dev8):** P2-A đồng hồ "Từ khi duyệt" tiến đúng khi sổ không đổi; P2-B lệnh trả lời là mẫu đầy đủ (project, sổ, `--reference` để người dùng điền); tràn 402 px ở 390 px với đường dẫn project dài sửa gốc; chip lọc nhanh có số; danh sách thu gọn khi đọc chi tiết; vùng đầu có bước hiện tại + "n câu hỏi chờ bạn"; câu hỏi gập có đếm; thanh thời lượng attempt khi có số đo; nhãn pha tiếng Việt; badge có ký hiệu. Chi tiết `docs/CHANGELOG.md`.

- **Mới ở dev10 (chủ chốt hướng thiết kế):** màn chi tiết lấy timeline Gantt/waterfall làm trung tâm: cây phần việc → lượt (trái), thanh trên cùng trục thời gian (giữa), ngăn chi tiết bước (phải); đặt chỗ/thực thi/chờ/kiểm/tới-hiện-tại phân biệt; dấu mốc; lịch sử cũ gập; chú giải; chọn khoảng. P2-A: mục câu hỏi bám `REQ id + revision`, request biến mất/đổi bản có ghi chú. P2-B: mẫu lệnh PowerShell nháy đơn với exe venv. Chi tiết `docs/CHANGELOG.md`.

## Không có / chưa chứng minh

- Không phải toàn bộ roadmap: MR-R (đọc đa repo) được phát triển trên nhánh riêng và không thuộc gói này; OBS-2, CP-1 và các feature sau chưa có. Không điều khiển task từ màn hình (không duyệt/dừng/sửa).
- Mọi kiểm dùng `claude` giả; chưa provider thật. Độ trễ đo trên sổ nhỏ. Trình duyệt kiểm: Chrome headless (thao tác do harness phát trong trang thật, chưa có người dùng thật/screen-reader).
- Codex đã review độc lập dev11 `7c8bfca` (03/11 ~20:57) và nêu R1–R5; các bản sửa dev12 **chưa được Codex review lại**; chưa nghiệm thu; beta không phải bản stable và không nâng runtime nào. Gate 2.2 đầy đủ không chạy lại cho lát này (chỉ module tracking và cli nhập lát này).

## Bằng chứng gắn snapshot

`verify/thu-goi-obs1.ps1` chạy lại trọn bộ (V1–V17, gồm V14 thao tác UX trong Chrome headless, V15 định danh `track open` và V17 phản chứng R1/R2/R3/R5 của review phát hành) trên máy của bạn và ghi `verify-report.json` + `ux-results.json` + ảnh `evidence\ux-*.png` nêu đúng version/commit của gói; báo cáo bàn giao `docs/BAO-CAO-OBS-1.vi.md` ghi kết quả lượt kiểm của người dựng gói trên cùng snapshot.

## Cài, dừng, quay về

`BAT-DAU-THU.vi.md` §3 (cài venv thử, mở màn hình bằng `mo-trang-obs1.ps1`), §4 (đọc sổ của project đang có OneCrew mà không nâng runtime — ví dụ SignSDK giữ runtime 2.3), §5 (dừng màn hình bằng `track stop`/`dung-trang-obs1.ps1`; quay về bản trước có điều kiện).
