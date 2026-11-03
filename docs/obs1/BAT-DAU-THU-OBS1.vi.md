# Bắt đầu thử OBS-1 — màn hình theo dõi chỉ đọc (beta @@VERSION@@)

Điểm vào duy nhất để thử lát OBS-1. Gói này là beta `@@VERSION@@` của dòng 2.4 dựng từ nhánh `@@BRANCH@@` (snapshot `@@COMMIT@@`) = `2.4.0.dev6` + lát OBS-1
(màn hình theo dõi chỉ đọc) + bốn bản sửa P2 của Codex 03/11 (dev7) + vòng UI/UX 03/11 theo hướng Blazo (UX-01…UX-08, định danh server của `track open`, `track status|stop`; dev8) + vòng UI/UX thứ hai theo review Codex trên dev8 (đồng hồ, mẫu lệnh trả lời đủ `--reference`, tràn 390 px, câu hỏi gập, chip lọc; dev9). Nhánh `claude/onecrew-2.4`, tag và gói `2.4.0.dev6`/`dev7`/`dev8` không đổi. Chỉ cài vào venv thử, chỉ đọc sổ thử hoặc bản sao.

| Mục | Giá trị |
|---|---|
| Gói | `@@PACKAGE@@` (đóng băng; `manifest.json`, `SHA256SUMS`) |
| Wheel · SHA256 | `wheel\@@WHEEL@@` · `@@WHEEL_SHA@@` |
| Python | `C:\Users\NUC\AppData\Local\Programs\Python\Python313\python.exe` (không dùng `python` trần) |
| Trạng thái | beta OBS-1; bản sửa P2 **chưa Codex review lại, chưa nghiệm thu**; `manifest.json` → `claims`; ghi chú phát hành: `docs\RELEASE-NOTES-OBS-1.vi.md`; giới hạn: `docs\limits-obs1.md` |

## 1. Có gì để xem

`onecrew track` — các lệnh chỉ đọc trên cùng một mô hình trạng thái (`onecrew/v2/tracking.py`):

| Lệnh | Thấy gì |
|---|---|
| `track list [--json] [--all-projects]` | một dòng mỗi plan: trạng thái có nguồn (đang thực hiện / đang chờ / bị chặn / đã kiểm, chờ nghiệm thu / đã nghiệm thu / đã đóng / chưa xác định), mức đầu ra (chưa có / đã tạo / đã kiểm / đã nghiệm thu), bước hiện tại, thời gian từ khi duyệt (lịch), cập nhật và bằng chứng cuối, việc cần bạn; cuối cùng là phần "chưa được theo dõi" |
| `track show <plan> [--json]` | node / thế hệ / attempt, root–child, chờ, giữ, ETA (khoảng có căn cứ hoặc "chưa xác định"), thời gian attempt và chờ (union, không cộng đôi), timeline (sự kiện thế hệ cũ được đánh dấu), các blob bằng chứng mở được |
| `track evidence <plan> <key>` | một blob bằng chứng mà sự kiện của plan nêu, đã lọc bí mật, tối đa 64 KiB |
| `track serve` / `track open [--no-browser]` | trang web local `http://127.0.0.1:<cổng>/` (chỉ GET; poll 2 s): **tổng quan** (lọc project/trạng thái, tìm, "cần bạn") → **chi tiết task** (mục tiêu, câu hỏi với từng lựa chọn + lệnh để sao chép, thẻ trạng thái/đầu ra/từ khi duyệt/thực hiện/chờ/ước lượng, bảng phần việc) → **timeline nhóm theo phần việc/attempt** (lịch sử cũ và chi tiết kỹ thuật gập lại; bấm một bước để xem bằng chứng của bước đó) → **bằng chứng** có tên/loại/thời điểm, xem ngay trong trang. Chọn bằng chuột hoặc bàn phím (Tab/↑↓/Enter/Esc), URL `?plan=…&project_id=…` giữ ngữ cảnh khi reload/Back; màn hình hẹp (cửa sổ chia đôi, điện thoại) chuyển danh sách ↔ chi tiết. `serve` chạy trong cửa sổ hiện tại (Ctrl+C chỉ đóng trang); `open` chạy server tách rời (tự thoát sau 30 phút không ai mở) và mở trình duyệt mặc định — chỉ **dùng lại** server đang chạy khi `/api/health` trả đúng định danh (instance của marker, version wheel, sổ, phạm vi) |
| câu hỏi "Cần bạn" | mỗi câu gập trong chi tiết; mở ra có lý do/ảnh hưởng/lựa chọn và **mẫu lệnh** `onecrew --project … --state-root … question answer … --choice … --reference "<lý do hoặc bằng chứng của bạn>"`: phần `<…>` do bạn điền (chữ của chủ sở hữu, ≤ 500 ký tự) rồi chạy trong terminal của bạn; trang không chạy lệnh, không trả lời thay |
| `track status` / `track stop` | `status`: marker `<sổ>\tracking\server.json` + `/api/health` của nó và kết luận có dùng lại được không (vì sao không); `stop`: dừng **chỉ** server khớp marker (PID, sổ, định danh), marker cũ/sai thì chỉ xóa marker, không dừng tiến trình lạ. Dừng màn hình không dừng task |

Trang web và CLI **không có nút điều khiển**: đọc, bấm, mở bằng chứng không duyệt, không trả lời, không dừng/tiếp tục task. Đóng trang hay tắt server không dừng worker.

## 2. Kiểm gói (tự động, `claude` giả, không gọi model)

Một lệnh: kiểm hash, cài wheel vào venv mới (ngoài checkout), chạy một task thật trên sổ tạm (root → node → attempt qua NativeExecutor + `claude` giả), rồi kiểm CLI, server, độ trễ ghi→trang (trần 5 s), mở lại server, tắt server giữa lúc worker chạy, lọc bí mật, phần chưa theo dõi, bốn phản chứng P2 của Codex (V13), **vòng UX** (V14: trang thật trong Chrome headless, harness cùng origin bấm/gõ/cuộn/reload/Back, ≥ 3 lượt poll và một lần ghi sổ trong lúc đang đọc, ở 1280×720, 640×720, 390×844; ảnh `evidence\ux-*.png`), **định danh `track open`** (V15: dùng lại đúng server, marker sai không dùng lại và không dừng tiến trình khác, hai lần mở cùng lúc = một server, `track stop`) và trang web render (V11):

```powershell
powershell -ExecutionPolicy Bypass -File "@@PACKAGE@@\verify\thu-goi-obs1.ps1"
```

Đạt khi in `DAT: …` và thoát 0 (16 bước; V16 = mẫu lệnh trả lời chạy qua CLI cài từ wheel trên sổ thử); báo cáo `verify-report.json` và `ux-results.json` (từng kịch bản UX: checks/notes/số lượt poll) trong thư mục kết quả (mặc định `D:\OneCrewRuns\obs1 thu @@VERSION@@ <giờ>`), ảnh ở `evidence\ux-overview-desktop.png`, `ux-detail-P4-desktop.png`, `ux-detail-P1-desktop.png`, `ux-detail-P1-split.png`, `ux-overview-mobile.png`, `ux-detail-P4-mobile.png` (+ `obs1-list.png`, `obs1-detail-P1.png`, `obs1-disconnected.png`). Không có trình duyệt headless chạy được script thì V11/V14 là `skipped` và kết quả là `partial` (trang và thao tác chưa được thấy trên máy đó). Mất khoảng 4–6 phút.

## 3. Tự xem bằng tay (sổ thử của bạn)

Cài vào venv thử rồi mở trang trên một sổ **bản sao** hoặc sổ thử (không trỏ vào sổ thật đang chạy việc):

```powershell
$py = "C:\Users\NUC\AppData\Local\Programs\Python\Python313\python.exe"; $pkg = "@@PACKAGE@@"; $venv = "D:\OneCrewRuns\obs1 thu tay\venv"; & $py -m venv $venv; & "$venv\Scripts\python.exe" -I -m pip install --no-index --no-build-isolation "$pkg\wheel\@@WHEEL@@"; & "$venv\Scripts\onecrew.exe" --version
```

```powershell
powershell -ExecutionPolicy Bypass -File "@@PACKAGE@@\verify\mo-trang-obs1.ps1" -Venv "D:\OneCrewRuns\obs1 thu tay\venv" -Project <project> -StateRoot <sổ thử>
```

(= `onecrew --project <project> --state-root <sổ thử> track open`; dừng: `dung-trang-obs1.ps1` cùng tham số = `track stop`.)

Rồi tạo một task thử trên sổ đó (ví dụ bài `task đầu tiên` của gói 2.4 với `claude` giả, hoặc một plan thật của bạn) và xem dòng của nó đổi: *đang chờ (chờ duyệt)* → *đang chờ (chưa có worker)* → *đang thực hiện (attempt …)* → *đang chờ: đầu ra đã tạo, chờ kiểm* → *đã kiểm, chờ nghiệm thu* → *đã nghiệm thu* (plan bị đóng hiện *đã đóng*, xám, không phải nghiệm thu). Bấm một dòng (hay Tab tới dòng rồi Enter) để xem chi tiết/timeline/bằng chứng; tắt trang rồi mở lại: dữ liệu dựng lại từ sổ, không mất, không trùng.

Sổ thật của 2.4 (ví dụ `D:\OneCrewRuns\v24\state`) chỉ nên xem bằng `track list` / `track serve` sau khi **sao chép** thư mục sổ: lệnh chỉ đọc, nhưng venv thử là bản OBS-1, không phải bản đang vận hành.

## 4. Dùng với project đang có OneCrew (đọc sổ ≠ nâng runtime)

Hai việc khác nhau:

- **Chỉ xem sổ** (an toàn, không đổi gì): venv thử OBS-1 (mục 3) + `track list|show|serve|open --project <project> --state-root <sổ>` mở sổ ở chế độ chỉ đọc (`mode=ro`), không ghi, không giữ khóa; riêng `track open|status|stop` ghi marker `tracking\server.json` (+ khóa tạm) — mặc định trong thư mục sổ; với sổ thật đặt `ONECREW_TRACK_MARKER_DIR=<thư mục ngoài sổ>` để thư mục sổ không có thêm file nào (script SignSDK làm vậy); runtime đang vận hành của project đó (ví dụ 2.3 `venv-23` của SignSDK) **không bị thay**, hook/registry không đổi. Nên trỏ vào **bản sao** thư mục sổ khi sổ đang có việc chạy; sổ 2.3/2.4 thật đọc được vì mô hình chỉ đọc bảng `tasks/requests/events/attempts` sẵn có.
- **Nâng runtime** lên `@@VERSION@@` (để worker/hook của project chạy bản này) là quyết định riêng, **không** nằm trong bài thử này và không được tự làm: dùng đường nâng cấp/quay về của 2.4 (`support …`, `BAT-DAU-THU` của gói 2.4) sau khi Codex review và chủ quyết.

## 5. Dừng màn hình và quay về bản trước

- **Dừng**: `track serve` → Ctrl+C hoặc đóng cửa sổ; `track open` → `track stop` (hay `verify\dung-trang-obs1.ps1`): dừng đúng server mà marker `<sổ>\tracking\server.json` trỏ tới sau khi `/api/health` của nó khớp PID/sổ/định danh; marker cũ hay cổng đã bị tiến trình khác dùng thì chỉ xóa marker, không dừng gì. Không dùng nữa cũng tự thoát sau 30 phút không request. Dừng màn hình **không** dừng worker hay task nào.
- **Quay về bản trước** (có điều kiện): nếu chỉ dùng venv thử (mục 3) thì xóa thư mục venv đó là xong, không có gì khác để hoàn; nếu đã cài wheel này đè vào một venv khác thì cài lại wheel cũ bằng `pip install --no-index --force-reinstall <wheel cũ>` rồi chạy `onecrew --version` để xác nhận; sổ không cần quay về vì bản này không ghi vào sổ. Chỉ quay về **sau khi** mọi `track serve/open` của venv đó đã tắt.

## 6. Giới hạn cần biết

Đọc `docs\limits-obs1.md` và `docs\RELEASE-NOTES-OBS-1.vi.md` trước khi kết luận. Tóm tắt: `claude` giả (không model thật); theo dõi chỉ những root/node/attempt có trong sổ; phiên Claude/Codex ngoài OneCrew ghi "chưa được theo dõi"; ETA chỉ khi sổ có ước lượng; server chỉ lắng nghe 127.0.0.1, không xác thực (máy cá nhân); bản sửa P2 (dev7) và vòng UX (dev8) chưa Codex review lại, chưa nghiệm thu; không thay đổi nhánh/tag/gói 2.4.0.dev6 và dev7.
