# Ghi chú — OneCrew `2.4.0.dev10` (OBS-1, timeline Gantt/waterfall; LOCAL, chưa phát hành)

Snapshot, wheel và SHA256 của gói này: `manifest.json` cạnh file này (và dòng đầu `BAT-DAU-THU.vi.md`). Ghi chú này chỉ đúng cho đúng snapshot/wheel đó.

## Có gì

- `2.4.0.dev6` (beta 2.4 đã phát hành 03/11, tag `v2.4.0.dev6`) + lát **OBS-1**: `onecrew track list|show|evidence|serve|open` — màn hình theo dõi chỉ đọc (danh sách task, chi tiết + timeline, bằng chứng, trang web local).
- Bốn bản sửa sau review Codex 03/11 (P2-01 đóng ≠ nghiệm thu; P2-02 quan sát attempt cũ; P2-03 khoảng chờ đã kết thúc; P2-04 giới hạn project của server) — từ `2.4.0.dev7`.
- **Mới ở dev8 — vòng UI/UX theo hướng Blazo** (review Codex UX trên dev7, UX-01…UX-08): tổng quan → chi tiết task → timeline theo phần việc/attempt → bằng chứng của từng bước; hai cột trên màn rộng, danh sách ↔ chi tiết trên màn hẹp; phần đang đọc/focus/cuộn giữ nguyên qua các lượt poll; đổi project đóng chi tiết của project khác; câu hỏi hiện đủ lựa chọn với lệnh trả lời để sao chép (không tự trả lời); chọn bằng bàn phím, chi tiết trong tầm nhìn, URL giữ task khi reload/Back; ba kiểu "xong" ba nhãn/màu (đã nghiệm thu / đã kiểm, chờ nghiệm thu / đã đóng); nhãn thời gian đúng đại lượng (từ khi duyệt – lịch / thực hiện – attempt / chờ); timeline cũ → mới, lịch sử attempt cũ và sự kiện kỹ thuật gập lại; bằng chứng có tên/loại/thời điểm. **P2 định danh server**: `track open` chỉ dùng lại server khớp instance/version/sổ/phạm vi, không dừng tiến trình lạ, khóa khi mở đồng thời; thêm `track status`, `track stop`, `track open --no-browser`; script `verify\mo-trang-obs1.ps1` / `dung-trang-obs1.ps1`. Chi tiết: `docs/CHANGELOG.md`, `BAO-CAO-OBS-1.vi.md`, ma trận `UX-OBS-1.vi.md`.
- Không đổi gì ở runtime 2.4: lát chỉ thêm module `onecrew/v2/tracking*.py`, nhóm lệnh `track` và test; không ghi sổ, không hook, không model.

- **Mới ở dev9 (review Codex trên dev8):** P2-A đồng hồ "Từ khi duyệt" tiến đúng khi sổ không đổi; P2-B lệnh trả lời là mẫu đầy đủ (project, sổ, `--reference` để người dùng điền); tràn 402 px ở 390 px với đường dẫn project dài sửa gốc; chip lọc nhanh có số; danh sách thu gọn khi đọc chi tiết; vùng đầu có bước hiện tại + "n câu hỏi chờ bạn"; câu hỏi gập có đếm; thanh thời lượng attempt khi có số đo; nhãn pha tiếng Việt; badge có ký hiệu. Chi tiết `docs/CHANGELOG.md`.

- **Mới ở dev10 (chủ chốt hướng thiết kế):** màn chi tiết lấy timeline Gantt/waterfall làm trung tâm: cây phần việc → lượt (trái), thanh trên cùng trục thời gian (giữa), ngăn chi tiết bước (phải); đặt chỗ/thực thi/chờ/kiểm/tới-hiện-tại phân biệt; dấu mốc; lịch sử cũ gập; chú giải; chọn khoảng. P2-A: mục câu hỏi bám `REQ id + revision`, request biến mất/đổi bản có ghi chú. P2-B: mẫu lệnh PowerShell nháy đơn với exe venv. Chi tiết `docs/CHANGELOG.md`.

## Không có / chưa chứng minh

- Không phải toàn bộ roadmap: MR-R, OBS-2 và các feature sau chưa có. Không điều khiển task từ màn hình (không duyệt/dừng/sửa).
- Mọi kiểm dùng `claude` giả; chưa provider thật. Độ trễ đo trên sổ nhỏ. Trình duyệt kiểm: Chrome headless (thao tác do harness phát trong trang thật, chưa có người dùng thật/screen-reader).
- Bản sửa P2 (dev7) và vòng UX + định danh server (dev8) chưa được Codex review lại; chưa nghiệm thu. Gate 2.2 đầy đủ không chạy lại cho lát này.

## Bằng chứng gắn snapshot

`verify/thu-goi-obs1.ps1` chạy lại trọn bộ (V1–V15, gồm V14 thao tác UX trong Chrome headless và V15 định danh `track open`) trên máy của bạn và ghi `verify-report.json` + `ux-results.json` + ảnh `evidence\ux-*.png` nêu đúng version/commit của gói; báo cáo bàn giao `docs/BAO-CAO-OBS-1.vi.md` ghi kết quả lượt kiểm của người dựng gói trên cùng snapshot.

## Cài, dừng, quay về

`BAT-DAU-THU.vi.md` §3 (cài venv thử, mở màn hình bằng `mo-trang-obs1.ps1`), §4 (đọc sổ của project đang có OneCrew mà không nâng runtime — ví dụ SignSDK giữ runtime 2.3), §5 (dừng màn hình bằng `track stop`/`dung-trang-obs1.ps1`; quay về bản trước có điều kiện).
