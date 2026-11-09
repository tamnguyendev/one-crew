# Bắt đầu sử dụng OneCrew 2.5.0.dev10 (beta UI OBS-2)

Điểm vào cho **repo chưa dùng OneCrew**. Repo đã dùng OneCrew thì đọc [Repo đang dùng OneCrew](REPO-DANG-DUNG-ONECREW.vi.md): ở đó chọn chỉ mở UI mới, hay nâng runtime.

Bản này là **prerelease beta**, chưa phải bản ổn định 2.5. Ghi chú phát hành: [RELEASE-NOTES-2.5.0.dev10.vi.md](RELEASE-NOTES-2.5.0.dev10.vi.md).

OneCrew là hợp đồng làm việc cho AI:
- AI chỉ làm trong kế hoạch bạn đã duyệt;
- mỗi mốc có bước kiểm độc lập;
- chỉ bạn nghiệm thu.

UI OBS-2 là trang web local **chỉ đọc**, cho xem công việc đang có trong sổ của OneCrew.

## 0. Cần có

- Windows 10/11, PowerShell 5.1 trở lên.
- Python 3.10 trở lên (bản cài từ python.org). Gõ `py -0p` để xem các Python đã cài và đường dẫn. Không dùng alias `python` của Microsoft Store.
- Git trên PATH (`git --version`). Repo phải là **một** repo Git có ít nhất một commit.
- Claude Code CLI, đã đăng nhập: cần khi AI làm việc. Nếu chỉ xem UI thì không cần.
- Quyền đọc repo riêng tư `tamnguyendev/one-crew` để tải bản phát hành `v2.5.0.dev10`.

## 1. Đặt biến (dán một lần vào cửa sổ PowerShell, các bước sau dùng lại)

Sửa giá trị cho máy của bạn. Đường dẫn có khoảng trắng vẫn chạy được.

```powershell
$env:ONECREW_LANG = 'vi'
$Python  = "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe"
$Goc     = "D:\OneCrew thu"
$TaiVe   = "$Goc\tai ve"
$Goi     = "$Goc\goi\onecrew-2.5.0.dev10-obs2-c4951f6"
$SuDung  = "$Goc\onecrew-2.5.0.dev10-su-dung"
$Venv    = "$Goc\venv 2.5.0.dev10"
$OneCrew = "$Venv\Scripts\onecrew.exe"
$DuAn    = "D:\du an\repo cua toi"
$So      = "$Goc\so\repo cua toi"
$Ghim    = "$Goc\ui\ghim.json"
```

Ý nghĩa của các biến:
- `$Goc`: thư mục làm việc của bạn.
- `$DuAn`: đúng repo bạn muốn đặt dưới hợp đồng.
- `$So`: sổ (state root), đặt ngoài repo.
- `$Ghim`: file ghi phiên UI đang mở, đặt ngoài venv, ngoài sổ và ngoài gói.

Mở cửa sổ PowerShell mới thì dán lại khối này.

## 2. Tải và kiểm bản phát hành

Tải 4 file của bản `v2.5.0.dev10` vào `$TaiVe`, bằng trình duyệt (trang Releases của repo) hoặc bằng GitHub CLI:

```powershell
gh release download v2.5.0.dev10 --repo tamnguyendev/one-crew --dir $TaiVe
```

Kiểm từng file với `SHA256SUMS-release.txt`:

```powershell
Get-Content -LiteralPath "$TaiVe\SHA256SUMS-release.txt" | ForEach-Object { $h, $n = $_ -split '\s+\*?', 2; $ok = (Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $TaiVe $n)).Hash -eq $h; '{0}  {1}' -f $(if ($ok) { 'DAT' } else { 'SAI' }), $n }
```

Mong đợi: 3 dòng (gói, wheel, hướng dẫn), dòng nào cũng `DAT`. Wheel phải có SHA256 `57445419e7c616f8e7c9f00039c7ac1b8ccc384c4cf464a27e3bc04b9d6879a1`. Có dòng `SAI` thì dừng lại và tải lại; không cài.

Giải nén gói và hướng dẫn:

```powershell
Expand-Archive -LiteralPath "$TaiVe\onecrew-2.5.0.dev10-obs2-c4951f6.zip" -DestinationPath "$Goc\goi"
```

```powershell
Expand-Archive -Path "$TaiVe\onecrew-2.5.0.dev10-su-dung-*.zip" -DestinationPath $Goc
```

Kiểm bên trong gói (18 file theo `SHA256SUMS` của gói, không có file lạ, đúng version, commit và wheel):

```powershell
powershell -ExecutionPolicy Bypass -File "$SuDung\kiem-goi.ps1" -Goi $Goi
```

Mong đợi: `DAT: goi … | 18 file khop SHA256SUMS | onecrew 2.5.0.dev10 | commit c4951f6ee1bc8ab41d055e0091246d95233fae28 | wheel … sha256 57445419…`.

## 3. Cài vào venv riêng

```powershell
& $Python -m venv $Venv
```

```powershell
& "$Venv\Scripts\python.exe" -m pip install --no-index "$Goi\wheel\onecrew-2.5.0.dev10-py3-none-any.whl"
```

```powershell
& $OneCrew --version
```

Mong đợi: `onecrew 2.5.0.dev10`. Wheel không có thư viện phụ thuộc, nên cài offline được.

Hook của repo sẽ gọi đúng `$Venv\Scripts\onecrew.exe`. Vì vậy **giữ venv này ở nguyên chỗ**: nếu xóa hay chuyển nó, `doctor` sẽ báo hook hỏng.

## 4. Chuẩn bị repo

```powershell
git -C $DuAn log -1 --oneline
```

Mong đợi: hiện một commit. Lệnh báo `not a git repository` hoặc chưa có commit thì xử lý trước:
- Repo của bạn ở thư mục khác: sửa `$DuAn` cho đúng.
- Đây là thư mục dự án mới, chưa có Git: chạy `git init` **trong chính thư mục đó**, rồi commit một lần.
- **Không** `git init` một thư mục cha chứa nhiều repo.

OneCrew 2.5.0.dev10 làm việc với một repo mỗi lần. Đọc nhiều repo cùng lúc (MR-R) không có trong bản này.

## 5. Gắn OneCrew vào repo (`init`)

```powershell
& $OneCrew --project $DuAn --state-root $So init
```

Lệnh liệt kê những gì sẽ ghi, rồi hỏi `Tiếp tục? [y/N]`. Gõ `y`. Những file được ghi:
- `$So\ledger.sqlite3`: sổ, nếu chưa có.
- `$So\plans\owner-rules.md`: quy tắc của chủ sở hữu, từ mẫu.
- `$DuAn\.onecrew\config.json`: ghi state root. File này ghi đường dẫn của máy này, **đừng commit**.
- `$DuAn\.claude\settings.local.json`: hook của Claude Code, gọi `$Venv\Scripts\onecrew.exe`. Hook và quyền khác có sẵn được giữ; bản cũ được sao ra `.bak` trước lần sửa đầu.
- `$DuAn\docs\wiki\README.md`, `project.md`, `lessons.md`: khung wiki của project, nếu chưa có.
- Một dòng trong `%LOCALAPPDATA%\OneCrew\hook-projects.json`: sổ đăng ký repo → sổ, dùng chung trên máy.

Mã thoát của `init`:
- 0: xong.
- 1: đã ghi xong, nhưng Claude CLI chưa có hoặc chưa đăng nhập.
- 2: không ghi gì (không phải repo Git, file settings hỏng, hoặc bạn trả lời N).
- 3: xong, trừ khung wiki.

Chạy lại `init` không đổi thêm gì.

Kiểm máy và repo:

```powershell
& $OneCrew --project $DuAn --state-root $So doctor
```

Mong đợi: mỗi kiểm một dòng PASS/WARN/FAIL. Trên máy đủ điều kiện: `0 FAIL, 0 WARN, 9 PASS`. Hai dòng WARN về Claude CLI chỉ có nghĩa là AI chưa chạy được; UI vẫn xem được. Có FAIL thì `doctor` thoát 1; đọc đúng dòng FAIL đó.

**Mở một phiên Claude Code MỚI trong `$DuAn`.** Claude Code chỉ nạp hook lúc bắt đầu phiên, nên phiên đang mở từ trước sẽ không thấy hook vừa ghi.

## 6. Một việc nhỏ từ đầu đến cuối

1. **Giao việc.** Trong phiên Claude Code mới, nói bằng lời việc bạn muốn. Thử lần đầu: "tạo file docs/xin-chao.md với đúng một dòng: Xin chao OneCrew".
2. **Hợp đồng.** AI viết hợp đồng. Mẫu cho đúng việc này: `$SuDung\mau-hop-dong.json` (điền `origin` bằng lời và giờ bạn giao). Hợp đồng nêu mục tiêu, phạm vi được sửa, đầu ra và cách kiểm từng mốc. AI kiểm và đề xuất:

   ```powershell
   & $OneCrew --project $DuAn --state-root $So plan lint --file "$SuDung\mau-hop-dong.json" --author <model id>
   ```

   ```powershell
   & $OneCrew --project $DuAn --state-root $So plan propose xin-chao --file "$SuDung\mau-hop-dong.json" --author <model id>
   ```

   Mong đợi: `lint: clean` (dòng `[note budget_calls_untracked]` chỉ là ghi chú), rồi JSON có `"status": "proposed"`.
3. **Duyệt.** Đây là bước bắt buộc trong lần đầu, và là việc **của bạn**: chạy trong terminal của bạn, không trong phiên AI (trong phiên AI lệnh này bị từ chối).

   ```powershell
   & $OneCrew --project $DuAn --state-root $So owner approve xin-chao --reference "<lý do của bạn>" --human
   ```

   ```powershell
   & $OneCrew --project $DuAn --state-root $So owner enforce xin-chao --human
   ```

   Sau `enforce`, hook chặn mọi sửa đổi nằm ngoài hợp đồng. Hợp đồng là cho cả việc: trong phạm vi đã duyệt, bạn không phải tạo hợp đồng hay cấu hình lại cho từng thao tác.
4. **Chạy.** AI làm việc trong phiên Claude Code. Mỗi mốc được kiểm độc lập:

   ```powershell
   & $OneCrew --project $DuAn --state-root $So verdict run --plan xin-chao --milestone M1
   ```

5. **Xem kết quả**, bằng lệnh hoặc bằng UI (mục 7):

   ```powershell
   & $OneCrew --project $DuAn --state-root $So plan report xin-chao
   ```

6. **Nghiệm thu.** Việc của bạn, chạy trong terminal của bạn, sau khi đã thử kết quả: `owner accept xin-chao --artifact-sha <sha> --reference "<đã thử gì>"`.

Script tạo dữ liệu mẫu trong gói (`verify\verify_obs2.py`) chỉ tạo **dữ liệu tổng hợp để xem UI**. Kết quả "đạt" của nó không phải bằng chứng model hay provider thật đã chạy.

## 7. Mở và dừng UI

Mở. Server chạy tách rời và tự thoát sau 30 phút không ai mở trang:

```powershell
powershell -ExecutionPolicy Bypass -File "$Goi\verify\mo-trang-obs1.ps1" -Venv $Venv -Project $DuAn -StateRoot $So -PinFile $Ghim
```

Mong đợi: `DAT: trang theo doi (chi doc) o http://127.0.0.1:<cổng>/ …`, và trình duyệt tự mở trang. Thêm `-NoBrowser` nếu chỉ muốn in URL.

Trên trang:
- Plan `xin-chao` nằm ở cột chờ duyệt. Thẻ "Quyết định cần bạn" có mẫu lệnh `owner approve` để sao chép, vì hook của repo gọi đúng runtime của trang.
- Sao chép **không** duyệt: bạn tự chạy lệnh đó trong terminal của mình.

Dừng đúng phiên vừa mở:

```powershell
powershell -ExecutionPolicy Bypass -File "$Goi\verify\dung-trang-obs1.ps1" -Venv $Venv -Project $DuAn -StateRoot $So -PinFile $Ghim
```

Mong đợi: `DAT: da dung dung phien da ghim …; worker/task khong bi anh huong`. Chạy lần nữa thì thoát 2 với `khong co phien nao do script mo nay mo`: đó là bình thường.

**Dừng UI khác dừng worker.** Đóng trang hay dừng UI không dừng việc AI đang làm. Muốn dừng việc thì đóng phiên Claude Code đang làm, hoặc dùng `executor stop <attempt>` cho lượt chạy do OneCrew quản lý (xem `& $OneCrew executor --help`).

## 8. Lỗi thường gặp

| Gặp | Làm gì |
|---|---|
| `requires a different Python` khi `pip install` | `$Python` là bản cũ hơn 3.10: chọn bản khác từ `py -0p`, rồi tạo lại venv |
| `init` thoát 2: "No git repository found" | `$DuAn` chưa phải repo Git: mục 4 |
| `doctor`: hook FAIL "stale" | venv đã bị xóa hay chuyển: tạo lại venv đúng `$Venv`, hoặc chạy lại `init` |
| `plan lint`: `[target_path] … does not exist` | `target.paths` trong hợp đồng phải là file hay thư mục **đang có** |
| Thẻ không có mẫu lệnh, ghi "Chưa xác minh hook" | hook của repo gọi runtime khác venv của trang: đúng thiết kế. Không sửa hook bằng tay để mở khóa |
| `mo-trang-obs1.ps1`: "file ghim … nằm trong …" | đặt `$Ghim` ngoài venv, ngoài sổ, ngoài gói |
| Không mở được trang sau 30 phút bỏ trống | server đã tự thoát: chạy lại lệnh mở |

**Bộ kiểm lệnh chạy trên một bản chép của artifact, không chạy trên thư mục đang làm** (từ 2.5.0.dev14):
- **Byte của bản chép** khớp với nội dung git lưu. Kiểu xuống dòng không theo `core.autocrlf` hay `core.eol` của máy; `.gitattributes` của repo vẫn được áp, vì nó là một phần của artifact.
- **Giờ sửa tệp không được giữ:** mọi tệp trong bản chép mang giờ lúc chép. Bộ kiểm đừng dựa vào giờ sửa tệp, ví dụ so "tệp A mới hơn tệp B". Phép so đó luôn cho cùng một kết quả trên bản chép, nên không chứng minh được gì.

## 9. Gửi góp ý

Gửi kèm:
- `& $OneCrew --version` và `code_commit` trong `$Goi\manifest.json`;
- kết quả `doctor`;
- các bước đã làm và ảnh màn hình trang.

Có thể tạo gói chẩn đoán đã lọc bí mật, chỉ lưu trên máy bạn: `support report --text "<mô tả>"`, rồi `support bundle <mã> --out <thư mục ngoài sổ>`. Đọc lại gói đó trước khi gửi.

**Không gửi:** `ledger.sqlite3` hay thư mục `$So`, key/token, file `.env`, cấu hình tài khoản.

## 10. Gỡ

- Xóa các mục OneCrew khỏi `.claude\settings.local.json`, hoặc khôi phục file `.bak`.
- Xóa `$DuAn\.onecrew`.
- Xóa venv.

Sổ `$So` là của bạn: giữ hay xóa tùy bạn.

## Đã diễn tập khi phát hành

Xem mục cuối của [Repo đang dùng OneCrew](REPO-DANG-DUNG-ONECREW.vi.md#đã-diễn-tập-khi-phát-hành): một bảng chung cho cả hai hướng dẫn.
