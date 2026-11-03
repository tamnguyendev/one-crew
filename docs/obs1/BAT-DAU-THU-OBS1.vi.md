# Bắt đầu thử OBS-1 — màn hình theo dõi chỉ đọc (beta @@VERSION@@)

Điểm vào duy nhất để thử lát OBS-1. Gói này là beta `@@VERSION@@` của dòng 2.4 dựng từ nhánh `@@BRANCH@@` (snapshot `@@COMMIT@@`) = `2.4.0.dev6` + lát OBS-1
(màn hình theo dõi chỉ đọc) + bốn bản sửa P2 của Codex 03/11. Nhánh `claude/onecrew-2.4`, tag và gói `2.4.0.dev6` không đổi. Chỉ cài vào venv thử, chỉ đọc sổ thử hoặc bản sao.

| Mục | Giá trị |
|---|---|
| Gói | `@@PACKAGE@@` (đóng băng; `manifest.json`, `SHA256SUMS`) |
| Wheel · SHA256 | `wheel\@@WHEEL@@` · `@@WHEEL_SHA@@` |
| Python | `C:\Users\NUC\AppData\Local\Programs\Python\Python313\python.exe` (không dùng `python` trần) |
| Trạng thái | beta OBS-1; bản sửa P2 **chưa Codex review lại, chưa nghiệm thu**; `manifest.json` → `claims`; ghi chú phát hành: `docs\RELEASE-NOTES-OBS-1.vi.md`; giới hạn: `docs\limits-obs1.md` |

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

Một lệnh: kiểm hash, cài wheel vào venv mới (ngoài checkout), chạy một task thật trên sổ tạm (root → node → attempt qua NativeExecutor + `claude` giả), rồi kiểm CLI, server, độ trễ ghi→trang (trần 5 s), mở lại server, tắt server giữa lúc worker chạy, lọc bí mật, phần chưa theo dõi, bốn phản chứng P2 của Codex (V13: plan đóng ≠ nghiệm thu, quan sát attempt cũ, khoảng chờ đã kết thúc, giới hạn project qua HTTP) và trang web trong trình duyệt headless (Chrome/Edge, chụp ảnh vào `<kết quả>\evidence`):

```powershell
powershell -ExecutionPolicy Bypass -File "@@PACKAGE@@\verify\thu-goi-obs1.ps1"
```

Đạt khi in `DAT: …` và thoát 0 (13 bước); báo cáo `verify-report.json` trong thư mục kết quả (mặc định `D:\OneCrewRuns\obs1 thu @@VERSION@@ <giờ>`), ảnh ở `evidence\obs1-list.png`, `obs1-detail-P1.png`, `obs1-disconnected.png`. Không có trình duyệt headless chạy được script thì bước V11 là `skipped` và kết quả là `partial` (trang chưa được thấy render trên máy đó). Mất khoảng 2–3 phút.

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

## 4. Dùng với project đang có OneCrew (đọc sổ ≠ nâng runtime)

Hai việc khác nhau:

- **Chỉ xem sổ** (an toàn, không đổi gì): venv thử OBS-1 (mục 3) + `track list|show|serve|open --project <project> --state-root <sổ>` mở sổ ở chế độ chỉ đọc (`mode=ro`), không ghi, không giữ khóa; runtime đang vận hành của project đó (ví dụ 2.3 `venv-23` của SignSDK) **không bị thay**, hook/registry không đổi. Nên trỏ vào **bản sao** thư mục sổ khi sổ đang có việc chạy; sổ 2.3/2.4 thật đọc được vì mô hình chỉ đọc bảng `tasks/requests/events/attempts` sẵn có.
- **Nâng runtime** lên `@@VERSION@@` (để worker/hook của project chạy bản này) là quyết định riêng, **không** nằm trong bài thử này và không được tự làm: dùng đường nâng cấp/quay về của 2.4 (`support …`, `BAT-DAU-THU` của gói 2.4) sau khi Codex review và chủ quyết.

## 5. Dừng màn hình và quay về bản trước

- **Dừng**: `track serve` → Ctrl+C hoặc đóng cửa sổ; `track open` → server tách rời tự thoát sau 30 phút không request, hoặc tắt ngay bằng `Stop-Process -Id <pid>` với `pid` in trong dòng JSON lúc mở (cũng ghi ở `<sổ>\tracking\server.json`). Dừng màn hình **không** dừng worker hay task nào.
- **Quay về bản trước** (có điều kiện): nếu chỉ dùng venv thử (mục 3) thì xóa thư mục venv đó là xong, không có gì khác để hoàn; nếu đã cài wheel này đè vào một venv khác thì cài lại wheel cũ bằng `pip install --no-index --force-reinstall <wheel cũ>` rồi chạy `onecrew --version` để xác nhận; sổ không cần quay về vì bản này không ghi vào sổ. Chỉ quay về **sau khi** mọi `track serve/open` của venv đó đã tắt.

## 6. Giới hạn cần biết

Đọc `docs\limits-obs1.md` và `docs\RELEASE-NOTES-OBS-1.vi.md` trước khi kết luận. Tóm tắt: `claude` giả (không model thật); theo dõi chỉ những root/node/attempt có trong sổ; phiên Claude/Codex ngoài OneCrew ghi "chưa được theo dõi"; ETA chỉ khi sổ có ước lượng; server chỉ lắng nghe 127.0.0.1, không xác thực (máy cá nhân); bản sửa P2 chưa Codex review lại, chưa nghiệm thu; không thay đổi nhánh/tag/gói 2.4.0.dev6.
