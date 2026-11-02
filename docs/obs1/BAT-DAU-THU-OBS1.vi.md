# Bắt đầu thử OBS-1 — màn hình theo dõi chỉ đọc (gói thử @@VERSION@@)

Điểm vào duy nhất để thử lát OBS-1. Gói này **không** thuộc bản phát hành 2.4 (nhánh `claude/onecrew-2.4`, gói `2.4.0.dev6`): nó là wheel dựng
từ nhánh `@@BRANCH@@` (snapshot `@@COMMIT@@`, version `@@VERSION@@` = 2.4.0.dev6 + lát OBS-1). Chỉ cài vào venv thử, chỉ đọc sổ thử.

| Mục | Giá trị |
|---|---|
| Gói | `@@PACKAGE@@` (đóng băng; `manifest.json`, `SHA256SUMS`) |
| Wheel · SHA256 | `wheel\@@WHEEL@@` · `@@WHEEL_SHA@@` |
| Python | `C:\Users\NUC\AppData\Local\Programs\Python\Python313\python.exe` (không dùng `python` trần) |
| Trạng thái | bản thử OBS-1, **chưa Codex review, chưa nghiệm thu**; `manifest.json` → `claims`; giới hạn: `docs\limits-obs1.md` |

## 1. Có gì để xem

`onecrew track` — bốn lệnh chỉ đọc trên cùng một mô hình trạng thái (`onecrew/v2/tracking.py`):

| Lệnh | Thấy gì |
|---|---|
| `track list [--json] [--all-projects]` | một dòng mỗi plan: trạng thái có nguồn (đang thực hiện / đang chờ / bị chặn / hoàn tất / chưa xác định), mức đầu ra (chưa có / đã tạo / đã kiểm / đã nghiệm thu), đã chạy, cập nhật và bằng chứng cuối, việc cần bạn; cuối cùng là phần "chưa được theo dõi" |
| `track show <plan> [--json]` | node / thế hệ / attempt, root–child, chờ, giữ, ETA (khoảng có căn cứ hoặc "chưa xác định"), thời gian attempt và chờ (union, không cộng đôi), timeline (sự kiện thế hệ cũ được đánh dấu), các blob bằng chứng mở được |
| `track evidence <plan> <key>` | một blob bằng chứng mà sự kiện của plan nêu, đã lọc bí mật, tối đa 64 KiB |
| `track serve` / `track open` | trang web local `http://127.0.0.1:<cổng>/` (chỉ GET; poll 2 s): danh sách, chi tiết + timeline khi bấm một dòng (hoặc `?plan=P1`), nhãn kết nối ("kết nối OK · dữ liệu lúc … · seq N" hay "MẤT KẾT NỐI … đang hiện dữ liệu cũ"), phần chưa được theo dõi. `serve` chạy trong cửa sổ hiện tại (Ctrl+C chỉ đóng trang); `open` chạy server tách rời (tự thoát sau 30 phút không ai mở) và mở trình duyệt mặc định |

Trang web và CLI **không có nút điều khiển**: đọc, bấm, mở bằng chứng không duyệt, không trả lời, không dừng/tiếp tục task. Đóng trang hay tắt server không dừng worker.

## 2. Kiểm gói (tự động, `claude` giả, không gọi model)

Một lệnh: kiểm hash, cài wheel vào venv mới (ngoài checkout), chạy một task thật trên sổ tạm (root → node → attempt qua NativeExecutor + `claude` giả), rồi kiểm CLI, server, độ trễ ghi→trang (trần 5 s), mở lại server, tắt server giữa lúc worker chạy, lọc bí mật, phần chưa theo dõi, và trang web trong trình duyệt headless (Chrome/Edge, chụp ảnh vào `<kết quả>\evidence`):

```powershell
powershell -ExecutionPolicy Bypass -File "@@PACKAGE@@\verify\thu-goi-obs1.ps1"
```

Đạt khi in `DAT: …` và thoát 0; báo cáo `verify-report.json` trong thư mục kết quả (mặc định `D:\OneCrewRuns\obs1 thu @@VERSION@@ <giờ>`), ảnh ở `evidence\obs1-list.png`, `obs1-detail-P1.png`, `obs1-disconnected.png`. Không có trình duyệt headless chạy được script thì bước V11 là `skipped` và kết quả là `partial` (trang chưa được thấy render trên máy đó).

## 3. Tự xem bằng tay (sổ thử của bạn)

Cài vào venv thử rồi mở trang trên một sổ **bản sao** hoặc sổ thử (không trỏ vào sổ thật đang chạy việc):

```powershell
$py = "C:\Users\NUC\AppData\Local\Programs\Python\Python313\python.exe"; $pkg = "@@PACKAGE@@"; $venv = "D:\OneCrewRuns\obs1 thu tay\venv"; & $py -m venv $venv; & "$venv\Scripts\python.exe" -I -m pip install --no-index --no-build-isolation "$pkg\wheel\@@WHEEL@@"; & "$venv\Scripts\onecrew.exe" --version
```

```powershell
& "D:\OneCrewRuns\obs1 thu tay\venv\Scripts\onecrew.exe" --project <project> --state-root <sổ thử> track open
```

Rồi tạo một task thử trên sổ đó (ví dụ bài `task đầu tiên` của gói 2.4 với `claude` giả, hoặc một plan thật của bạn) và xem dòng của nó đổi: *đang chờ (chờ duyệt)* → *đang chờ (chưa có worker)* → *đang thực hiện (attempt …)* → *đang chờ: đầu ra đã tạo, chờ kiểm* → *hoàn tất: đã kiểm, chờ nghiệm thu* → *đã nghiệm thu*. Bấm một dòng để xem node/attempt/timeline; tắt trang rồi mở lại: dữ liệu dựng lại từ sổ, không mất, không trùng.

Sổ thật của 2.4 (ví dụ `D:\OneCrewRuns\v24\state`) chỉ nên xem bằng `track list` / `track serve` sau khi **sao chép** thư mục sổ: lệnh chỉ đọc, nhưng venv thử là bản OBS-1, không phải bản đang vận hành.

## 4. Giới hạn cần biết

Đọc `docs\limits-obs1.md` trước khi kết luận. Tóm tắt: `claude` giả (không model thật); theo dõi chỉ những root/node/attempt có trong sổ; phiên Claude/Codex ngoài OneCrew ghi "chưa được theo dõi"; ETA chỉ khi sổ có ước lượng; server chỉ lắng nghe 127.0.0.1, không xác thực (máy cá nhân); chưa Codex review, chưa nghiệm thu; không thay đổi nhánh/gói 2.4.
