# Ghi chú phát hành — OneCrew `2.4.0.dev7` (beta OBS-1)

Snapshot, wheel và SHA256 của gói này: `manifest.json` cạnh file này (và dòng đầu `BAT-DAU-THU.vi.md`). Ghi chú này chỉ đúng cho đúng snapshot/wheel đó.

## Có gì

- `2.4.0.dev6` (beta 2.4 đã phát hành 03/11, tag `v2.4.0.dev6`) + lát **OBS-1**: `onecrew track list|show|evidence|serve|open` — màn hình theo dõi chỉ đọc (danh sách task, chi tiết + timeline, bằng chứng, trang web local).
- Bốn bản sửa sau review Codex 03/11 (P2-01 đóng ≠ nghiệm thu; P2-02 quan sát attempt cũ; P2-03 khoảng chờ đã kết thúc; P2-04 giới hạn project của server). Chi tiết: `docs/CHANGELOG.md` của repo, báo cáo `BAO-CAO-OBS-1.vi.md` §2.
- Không đổi gì ở runtime 2.4: lát chỉ thêm module `onecrew/v2/tracking*.py`, nhóm lệnh `track` và test; không ghi sổ, không hook, không model.

## Không có / chưa chứng minh

- Không phải toàn bộ roadmap: MR-R, OBS-2 và các feature sau chưa có. Không điều khiển task từ màn hình (không duyệt/dừng/sửa).
- Mọi kiểm dùng `claude` giả; chưa provider thật. Độ trễ đo trên sổ nhỏ. Trình duyệt kiểm: Chrome headless.
- Bản sửa P2 chưa được Codex review lại; chưa nghiệm thu. Gate 2.2 đầy đủ không chạy lại cho lát này.

## Bằng chứng gắn snapshot

`verify/thu-goi-obs1.ps1` chạy lại trọn bộ (V1–V13) trên máy của bạn và ghi `verify-report.json` nêu đúng version/commit của gói; báo cáo bàn giao `docs/BAO-CAO-OBS-1.vi.md` ghi kết quả lượt kiểm của người dựng gói trên cùng snapshot.

## Cài, dừng, quay về

`BAT-DAU-THU.vi.md` §3 (cài venv thử, mở màn hình), §4 (đọc sổ của project đang có OneCrew mà không nâng runtime), §5 (dừng màn hình; quay về bản trước có điều kiện).
