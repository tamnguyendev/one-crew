# Repo đang dùng OneCrew: chỉ mở UI mới, hay nâng runtime?

| Bạn muốn | Làm theo |
|---|---|
| Xem công việc của repo bằng UI OBS-2 mới, **giữ nguyên** runtime, hook và sổ đang chạy | **A** ngay dưới đây (khuyên dùng) |
| Cho hook và worker của repo chạy bản 2.5.0.dev10 | [Nâng runtime](NANG-RUNTIME.vi.md): quyết định riêng, thử trên bản sao trước |

Muốn xem UI thì **không cần** nâng runtime. Bản 2.5.0.dev10 là prerelease beta ([ghi chú phát hành](RELEASE-NOTES-2.5.0.dev10.vi.md)). Repo chưa dùng OneCrew thì đọc [Bắt đầu sử dụng](BAT-DAU-SU-DUNG.vi.md).

## A. Chỉ mở UI mới

Ba nguyên tắc:
- UI chạy từ một venv **riêng** có 2.5.0.dev10. Không `pip install` vào venv mà hook của repo đang gọi.
- Thử trên **bản sao** sổ trước. Bản sao làm bằng script dùng cơ chế sao chép của chính OneCrew (SQLite backup API), không chép tay file `ledger.sqlite3` đang được ghi.
- Không đổi hook, runtime, sổ hay sổ đăng ký (registry) của repo. Bước A6 kiểm lại điều này.

### A0. Đặt biến

```powershell
$env:ONECREW_LANG = 'vi'
$Python = "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe"
$Goc    = "D:\OneCrew thu"
$TaiVe  = "$Goc\tai ve"
$Goi    = "$Goc\goi\onecrew-2.5.0.dev10-obs2-c4951f6"
$SuDung = "$Goc\onecrew-2.5.0.dev10-su-dung"
$Venv   = "$Goc\venv ui 2.5.0.dev10"
$DuAn   = "D:\du an\repo dang dung"
$BanSao = "$Goc\ban sao so\lan 1"
$Ghim   = "$Goc\ui\ghim repo dang dung.json"
$Truoc  = "$Goc\hien trang truoc.json"
$Sau    = "$Goc\hien trang sau.json"
```

- `$DuAn`: repo đang dùng OneCrew.
- `$BanSao`: thư mục **chưa có**; mỗi lần sao chép dùng một tên mới.
- `$Truoc` và `$Sau`: hai file ghi hiện trạng trước và sau khi thử.

### A1. Tải, kiểm, cài vào venv riêng

Làm mục 2 và mục 3 của [Bắt đầu sử dụng](BAT-DAU-SU-DUNG.vi.md), với `$Venv` ở trên. Mong đợi: `kiem-goi.ps1` in `DAT`, và `& "$Venv\Scripts\onecrew.exe" --version` in `onecrew 2.5.0.dev10`.

### A2. Ghi hiện trạng của repo (chỉ đọc)

```powershell
powershell -ExecutionPolicy Bypass -File "$SuDung\hien-trang.ps1" -DuAn $DuAn -Ra $Truoc
```

Mong đợi:
- một dòng `hook goi: <đường dẫn onecrew.exe> | onecrew <version đang chạy> | sha256 …`;
- dòng `so (state root): …`;
- `DAT: da ghi hien trang.`

Nếu thoát 2 và báo `khong co hook OneCrew`, repo này chưa dùng OneCrew: đọc [Bắt đầu sử dụng](BAT-DAU-SU-DUNG.vi.md).

Lấy đường dẫn sổ từ file vừa ghi:

```powershell
$So = (Get-Content -Raw -Encoding UTF8 -LiteralPath $Truoc | ConvertFrom-Json).state_root
```

Nếu `$So` rỗng (repo không có `.onecrew\config.json`), hook đang dùng sổ mặc định: đặt `$So = "$env:LOCALAPPDATA\OneCrew"`.

### A3. Sao chép sổ an toàn

```powershell
powershell -ExecutionPolicy Bypass -File "$SuDung\sao-chep-so.ps1" -Venv $Venv -Nguon $So -Dich $BanSao
```

Mong đợi: `DAT: ban sao o … (… byte; schema …; N task; M su kien). So nguon khong bi ghi.`

Script này:
- mở sổ nguồn ở chế độ chỉ đọc, sao bằng SQLite backup API, nên bản sao nhất quán kể cả khi sổ đang được ghi;
- chép nguyên các thư mục khác của sổ;
- bỏ qua `support-work`, `support-spool` và marker của trang theo dõi;
- từ chối nếu `$BanSao` đã có.

### A4. Mở UI trên bản sao

```powershell
powershell -ExecutionPolicy Bypass -File "$Goi\verify\mo-trang-obs1.ps1" -Venv $Venv -Project $DuAn -StateRoot $BanSao -PinFile $Ghim
```

Mong đợi: `DAT: trang theo doi (chi doc) o http://127.0.0.1:<cổng>/ …`, và trang hiện các plan của repo.

Thẻ "Quyết định cần bạn" vẫn hiện câu hỏi và việc cần duyệt, nhưng **không có mẫu lệnh sao chép**; trang nêu lý do ("Chưa xác minh hook…"). Đó là đúng thiết kế: hook của repo gọi runtime đang chạy và sổ thật, không phải venv này và bản sao. **Không sửa hook để mở khóa.** Muốn chạy lệnh của chủ thì dùng runtime đang chạy của repo, như trước nay.

Kết luận tương thích:
- Trang mở được, thấy đúng các plan và mở được chi tiết: UI mới đọc được sổ này.
- Trang báo lỗi nguồn (ví dụ "Unsupported ledger schema"): chưa tương thích. Dừng ở đây và gửi góp ý (mục A8). Không nâng runtime để "sửa".

Đã diễn tập với sổ do runtime 2.3.0.dev11 ghi. Sổ của version khác chưa diễn tập, nên với chúng bước A4 trên bản sao là phép thử quyết định.

### A5. Dừng UI

```powershell
powershell -ExecutionPolicy Bypass -File "$Goi\verify\dung-trang-obs1.ps1" -Venv $Venv -Project $DuAn -StateRoot $BanSao -PinFile $Ghim
```

Mong đợi: `DAT: da dung dung phien da ghim …; worker/task khong bi anh huong`. Chạy lần nữa thì thoát 2, đó là bình thường. Dừng UI không dừng worker hay task nào của repo.

### A6. Xác nhận runtime, hook, config không đổi

```powershell
powershell -ExecutionPolicy Bypass -File "$SuDung\hien-trang.ps1" -DuAn $DuAn -Ra $Sau -SoSanh $Truoc
```

Mong đợi: `DAT: runtime, hook va config khong doi so voi lan truoc.`

Sổ không được so sánh, vì worker thật của repo có thể vẫn đang ghi; trang chỉ đọc nên không ghi vào sổ.

### A7. Tùy chọn: xem sổ thật, chỉ đọc

Chỉ làm sau khi A4 đã đạt trên bản sao. Nên làm lúc repo không có việc đang chạy. Trang đọc sổ ở chế độ chỉ đọc nhưng mỗi lượt poll vẫn giữ khóa đọc trong chốc lát, nên khi sổ đang ghi nhiều thì dùng bản sao mới (A3).

Đặt marker của server UI ra ngoài thư mục sổ, để thư mục sổ không có thêm file nào:

```powershell
$env:ONECREW_TRACK_MARKER_DIR = "$Goc\ui\marker"
```

```powershell
powershell -ExecutionPolicy Bypass -File "$Goi\verify\mo-trang-obs1.ps1" -Venv $Venv -Project $DuAn -StateRoot $So -PinFile $Ghim
```

Dừng, trong **cùng cửa sổ** (để còn biến marker):

```powershell
powershell -ExecutionPolicy Bypass -File "$Goi\verify\dung-trang-obs1.ps1" -Venv $Venv -Project $DuAn -StateRoot $So -PinFile $Ghim
```

Sau đó chạy lại A6.

### A8. Gửi góp ý

Gửi kèm:
- hai file `$Truoc` và `$Sau`: chúng có đường dẫn repo và SHA256 của file, không có nội dung sổ hay key;
- `& "$Venv\Scripts\onecrew.exe" --version`;
- `code_commit` trong `$Goi\manifest.json`;
- ảnh màn hình trang và các bước đã làm.

**Không gửi** sổ, bản sao sổ, key/token hay file `.env`.

### A9. Gỡ

- Dừng UI (A5).
- Xóa `$Venv`, `$BanSao` và các file ghim, marker.

Repo, hook và runtime đang chạy không cần hoàn lại gì, vì chúng chưa bị đổi.

## Đã diễn tập khi phát hành

Bảng này dùng chung cho [Bắt đầu sử dụng](BAT-DAU-SU-DUNG.vi.md), trang này và [Nâng runtime](NANG-RUNTIME.vi.md).

Diễn tập ngày 05/11/2026 trong một phòng lab trên máy dựng gói:
- mọi đường dẫn đều có khoảng trắng;
- lab đóng vai "máy khác": `LOCALAPPDATA`, `APPDATA`, `TEMP` trỏ vào lab, nên sổ đăng ký thật của máy không đổi (đã kiểm);
- dùng đúng các lệnh trong hướng dẫn, chỉ thay giá trị biến.

Kết quả: **42/42 kiểm đạt.**

| Phần | Đã kiểm |
|---|---|
| Bắt đầu sử dụng (repo mới) | Ba file tải về khớp `SHA256SUMS-release.txt`. `kiem-goi.ps1` in DAT (18 file, 2.5.0.dev10, `c4951f6`). Cài offline, `onecrew 2.5.0.dev10`. `init` hỏi y/N và ghi đúng các file đã liệt kê. `doctor`: 0 FAIL, 0 WARN, 9 PASS. `plan lint` clean, `plan propose` cho trạng thái proposed. Trang hiện thẻ duyệt có mẫu lệnh `owner approve`. Mở và dừng đúng phiên đã ghim; dừng lần hai thoát 2 |
| Repo đang dùng OneCrew (A) | Repo lab chạy runtime 2.3.0.dev11, cùng wheel với một repo thật đang dùng. `hien-trang.ps1` thấy hook gọi 2.3.0.dev11. `sao-chep-so.ps1` in DAT, và từ chối thư mục đích đã có. Trang đọc được bản sao (tổng quan và chi tiết plan); thẻ duyệt không có lệnh sao chép và nêu lý do. Dừng DAT; hiện trạng không đổi. Xem sổ của repo lab ở chế độ chỉ đọc, marker đặt ngoài sổ: thư mục sổ giống hệt từng byte trước và sau |
| Nâng runtime (C), trên repo lab | Xem mục cuối của [Nâng runtime](NANG-RUNTIME.vi.md) |
| Tải lại từ trang phát hành | Kiểm sau khi phát hành; kết quả ở ghi chú của bản `v2.5.0.dev10` trên trang Releases và trong hồ sơ bàn giao |

**Chưa diễn tập**, vì cần chủ hoặc model thật:
- `owner approve`, `enforce`, `accept`: trong phiên AI các lệnh này bị từ chối, và lượt diễn tập đã kiểm đúng việc từ chối đó;
- AI làm việc và `verdict run`;
- Claude Code nạp hook trong phiên mới;
- trình duyệt tự mở trang (diễn tập dùng `-NoBrowser`);
- sổ do một runtime khác 2.3.0.dev11 ghi.
