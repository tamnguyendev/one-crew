# Bắt đầu sử dụng OneCrew 2.5.0.dev10+sol6.4 (beta thử có giám sát)

Trang này là điểm vào duy nhất: tải, kiểm, cài, thử, nâng cấp, quay về, gửi góp ý.

Đây là **prerelease, chưa phải stable**. Giới hạn và bằng chứng: [Ghi chú phát hành](RELEASE-NOTES-sol6.4.vi.md). Hãy thử trên **bản sao** trước; đừng nâng repo thật chỉ để xem thử.

| Bạn có | Làm theo |
|---|---|
| Repo chưa dùng OneCrew | Mục 1 → 5 |
| Repo đang dùng OneCrew | Mục 1 → 4, rồi mục 6. Chỉ làm mục 7 khi đã quyết định nâng |

## 0. Cần có

- Windows 10/11, PowerShell 5.1 trở lên.
- Python 3.10 trở lên, bản cài từ python.org. `py -0p` cho biết đường dẫn. Không dùng alias `python` của Microsoft Store.
- Git trên PATH. Repo phải là một repo Git có ít nhất một commit.
- Claude Code CLI đã đăng nhập: chỉ cần khi cho AI làm việc thật.

## 1. Đặt biến

Dán vào một cửa sổ PowerShell **mới**, sửa giá trị cho máy của bạn. Đường dẫn có khoảng trắng vẫn chạy được.

```powershell
$env:ONECREW_LANG = 'vi'
$Python  = "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe"
$Goc     = "D:\OneCrew thu"
$TaiVe   = "$Goc\tai ve"
$Goi     = "$Goc\onecrew-2.5.0.dev10-sol6.4-beta"
$Venv    = "$Goc\venv sol6.4"
$OneCrew = "$Venv\Scripts\onecrew.exe"
$DuAn    = "D:\du an\repo cua toi"
$BanSao  = "$Goc\ban sao\repo"
$So      = "$Goc\ban sao\so"
$env:LOCALAPPDATA = "$Goc\ban sao\may\local"
$env:APPDATA      = "$Goc\ban sao\may\roaming"
```

Hai dòng cuối chỉ có hiệu lực trong cửa sổ này. Nhờ đó `init` khi thử không ghi vào sổ đăng ký thật của máy. Dòng `$Python` phải đứng trước chúng. Mở cửa sổ mới thì dán lại cả khối.

## 2. Tải và kiểm

```powershell
New-Item -ItemType Directory -Force $TaiVe | Out-Null; foreach ($f in 'onecrew-2.5.0.dev10-sol6.4-beta.zip', 'SHA256SUMS-release.txt') { Invoke-WebRequest -UseBasicParsing -Uri "https://github.com/tamnguyendev/one-crew/releases/download/v2.5.0.dev10-sol6.4-beta/$f" -OutFile "$TaiVe\$f" }
```

Không cần đăng nhập, vì repo công khai. Cũng có thể tải 2 file đó ở [trang phát hành](https://github.com/tamnguyendev/one-crew/releases/tag/v2.5.0.dev10-sol6.4-beta) vào `$TaiVe`.

Kiểm file tải về với `SHA256SUMS-release.txt`:

```powershell
Get-Content -LiteralPath "$TaiVe\SHA256SUMS-release.txt" | ForEach-Object { $h, $n = $_ -split '\s+\*?', 2; $ok = (Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $TaiVe $n)).Hash -eq $h; '{0}  {1}' -f $(if ($ok) { 'DAT' } else { 'SAI' }), $n }
```

Đạt khi có 1 dòng và dòng đó là `DAT`. Có `SAI` thì dừng lại và tải lại.

Giải nén, rồi kiểm từng file bên trong gói:

```powershell
Expand-Archive -LiteralPath "$TaiVe\onecrew-2.5.0.dev10-sol6.4-beta.zip" -DestinationPath $Goc
```

```powershell
powershell -ExecutionPolicy Bypass -File "$Goi\tools\kiem-goi.ps1" -Goi $Goi
```

Đạt khi in `DAT: goi … | onecrew 2.5.0.dev10+sol6.4 | commit 16b47d7… | … sha256 4f25c399…`. Script kiểm mọi file theo `SHA256SUMS` của gói, kể cả hướng dẫn và script, và báo nếu có file lạ.

## 3. Cài vào venv riêng

Không cài vào venv mà hook của repo nào đang gọi.

```powershell
& $Python -m venv $Venv
```

```powershell
& "$Venv\Scripts\python.exe" -m pip install --no-index "$Goi\wheel\onecrew-2.5.0.dev10+sol6.4-py3-none-any.whl"
```

```powershell
& $OneCrew --version
```

Đạt khi in `onecrew 2.5.0.dev10+sol6.4`. Wheel không có thư viện phụ thuộc nên cài offline được. Hook sẽ gọi đúng `$OneCrew`, nên giữ venv này ở nguyên chỗ.

## 4. Chạy smoke

```powershell
powershell -ExecutionPolicy Bypass -File "$Goi\tools\thu-goi.ps1" -Goi $Goi -Python $Python -Thu "$Goc\thu smoke"
```

Đạt khi dòng cuối bắt đầu bằng `DAT:` và có `38 dieu kien smoke`, sau khoảng 2–3 phút. Script tự tạo venv và thư mục riêng. Đây là fixture cục bộ, không gọi model và không phải nghiệm thu.

## 5. Thử trên bản sao project, sổ riêng

Sao repo, chỉ phần đã commit, sang thư mục khác. Repo thật không đổi:

```powershell
git clone $DuAn $BanSao
```

Gắn OneCrew vào bản sao, với sổ riêng. Lệnh liệt kê những gì sẽ ghi rồi hỏi `y/N`, gõ `y`:

```powershell
& $OneCrew --project $BanSao --state-root $So init
```

Lệnh ghi các file sau, không có gì ngoài chúng:

- `$So\ledger.sqlite3` và `$So\plans\owner-rules.md`.
- Trong bản sao: `.onecrew\config.json`, `.claude\settings.local.json` (hook gọi `$OneCrew`; file cũ được sao ra `.bak`), khung `docs\wiki\`.
- Một dòng `hook-projects.json` trong `LOCALAPPDATA` của cửa sổ này.

Mã thoát: 0 xong; 1 đã ghi nhưng Claude CLI chưa có hoặc chưa đăng nhập; 2 không ghi gì; 3 xong trừ khung wiki.

```powershell
& $OneCrew --project $BanSao --state-root $So doctor
```

Đạt khi không có `FAIL`. Trên máy đủ điều kiện: `0 FAIL, 0 WARN, 9 PASS`. Hai dòng `WARN` về Claude CLI nghĩa là AI chưa chạy được.

Thử hợp đồng mẫu. Lệnh không gọi model; `--author` là mã model sẽ làm việc, dùng để người review biết ai viết hợp đồng:

```powershell
& $OneCrew --project $BanSao --state-root $So plan lint --file "$Goi\tools\mau-hop-dong.json" --author claude-sonnet-5-5
```

```powershell
& $OneCrew --project $BanSao --state-root $So plan propose xin-chao --file "$Goi\tools\mau-hop-dong.json" --author claude-sonnet-5-5
```

```powershell
& $OneCrew --project $BanSao --state-root $So plan report xin-chao
```

Đạt khi lint in `lint: clean`, propose có `"status": "proposed"`, và report in được trang.

**Cho AI làm việc thật:** Claude Code chỉ nạp hook lúc bắt đầu phiên. Mở một phiên **mới** trong `$BanSao`, từ chính cửa sổ này để giữ biến môi trường:

```powershell
Set-Location -LiteralPath $BanSao; claude
```

Duyệt, enforce và nghiệm thu là việc của bạn, chạy trong terminal của bạn, không trong phiên AI (trong phiên AI các lệnh này bị từ chối):

```powershell
& $OneCrew --project $BanSao --state-root $So owner approve xin-chao --reference "<lý do của bạn>" --human
```

```powershell
& $OneCrew --project $BanSao --state-root $So owner enforce xin-chao --human
```

Sau khi đã thử kết quả, thay `<sha>` bằng mã cây mà report nêu:

```powershell
& $OneCrew --project $BanSao --state-root $So owner accept xin-chao --artifact-sha <sha> --reference "<đã thử gì>"
```

## 6. Repo đang dùng OneCrew: kiểm trên bản sao

Mục này không đổi runtime, hook hay sổ thật của repo. Đặt thêm biến, trong cùng cửa sổ của mục 1:

```powershell
$Truoc = "$Goc\hien trang truoc.json"
$Sau   = "$Goc\hien trang sau.json"
```

**Bước 1. Ghi phiên bản, runtime và sổ hiện hành (chỉ đọc):**

```powershell
powershell -ExecutionPolicy Bypass -File "$Goi\tools\hien-trang.ps1" -DuAn $DuAn -Ra $Truoc
```

Script in `hook goi: <onecrew.exe> | onecrew <version đang chạy> | sha256 …` và `so (state root): …`. Thoát 2 nghĩa là repo chưa dùng OneCrew: dùng mục 5.

```powershell
$SoThat = (Get-Content -Raw -Encoding UTF8 -LiteralPath $Truoc | ConvertFrom-Json).state_root
```

`$SoThat` rỗng nghĩa là hook dùng sổ mặc định, thường là `%LOCALAPPDATA%\OneCrew` của máy. Khi đó đặt `$SoThat` bằng đường dẫn đầy đủ của thư mục đó, vì `LOCALAPPDATA` của cửa sổ này đã đổi.

**Bước 2. Sao sổ an toàn.** Script mở sổ nguồn ở chế độ chỉ đọc, dùng SQLite backup API, nên bản sao nhất quán kể cả khi sổ đang được ghi. Không chép tay `ledger.sqlite3`.

```powershell
powershell -ExecutionPolicy Bypass -File "$Goi\tools\sao-chep-so.ps1" -Venv $Venv -Nguon $SoThat -Dich $So
```

Đạt khi in `DAT: ban sao o … schema …; N task; M su kien`. `-Dich` phải là thư mục chưa có.

**Bước 3. Xem runtime mới có đọc được việc cũ trên sổ sao không.** Đây là lệnh chỉ đọc:

```powershell
& $OneCrew --project $DuAn --state-root $So track list --all-projects
```

`<plan>` là tên một plan vừa thấy:

```powershell
& $OneCrew --project $DuAn --state-root $So continue <plan>
```

Có lỗi nguồn như `Unsupported ledger schema` nghĩa là chưa tương thích: dừng lại và gửi góp ý, đừng nâng để "sửa".

**Bước 4. Thử gắn runtime mới vào bản sao repo và sổ sao:**

```powershell
git clone $DuAn $BanSao
```

```powershell
& $OneCrew --project $BanSao --state-root $So init --yes
```

```powershell
& $OneCrew --project $BanSao --state-root $So doctor
```

Đạt khi có dòng `PASS hook`. Sổ ghi project theo đường dẫn, nên bản sao repo là một project mới trong sổ sao; các plan cũ vẫn thuộc đường dẫn repo thật.

**Bước 5. Xác nhận repo thật không đổi:**

```powershell
powershell -ExecutionPolicy Bypass -File "$Goi\tools\hien-trang.ps1" -DuAn $DuAn -Ra $Sau -SoSanh $Truoc
```

Đạt khi in `DAT: runtime, hook va config khong doi so voi lan truoc.`

## 7. Nâng runtime của repo thật (quyết định riêng của chủ repo)

Không cần làm mục này để thử. Đừng nâng khi:

- Mục 6 chưa đạt.
- Đang có plan đã duyệt mà chưa nghiệm thu, hoặc có lượt chạy đang mở. Việc nâng giữa chừng một plan chưa được kiểm.
- Venv hoặc sổ dùng chung với repo khác mà bạn chưa kiểm hết: xem `hook-projects.json` trong `%LOCALAPPDATA%\OneCrew` thật.

**Những gì sẽ thay đổi khi nâng:**

- Hook trong `.claude\settings.local.json` được trỏ sang `onecrew.exe` mới. Sổ, quy tắc và config đã có giữ nguyên; `init` hỏi `y/N` trước.
- Phiên Claude Code đang mở vẫn dùng hook cũ cho tới khi mở phiên mới.
- Runtime mới ghi vào sổ cả những sự kiện mới. **Không có cam kết wheel cũ đọc được dữ liệu mới**, và điều này chưa được kiểm.
- Hành vi mới ở mục "Thay đổi hành vi" của ghi chú phát hành có hiệu lực.

**Các bước,** trong một cửa sổ PowerShell **mới**, không đổi `LOCALAPPDATA`, lúc không có việc chạy:

1. Sao lưu vào thư mục mới có ngày giờ: sổ bằng `sao-chep-so.ps1`; các file `.claude\settings.local.json`, `.claude\settings.json` (nếu có), `.onecrew\config.json` của repo. Giữ nguyên venv cũ; `$Truoc` đã ghi đường dẫn và version cũ.
2. Cài wheel vào một venv mới như mục 3. Không cài đè venv cũ.
3. Trỏ hook sang runtime mới:

   ```powershell
   & $OneCrew --project $DuAn --state-root $SoThat init
   ```

4. Kiểm, rồi mở phiên Claude Code mới trong repo:

   ```powershell
   & $OneCrew --project $DuAn --state-root $SoThat doctor
   ```

**Quay về bản trước:**

- **Hook:** chép lại các file settings và config đã sao lưu. Chạy `hien-trang.ps1 -DuAn $DuAn -Ra <file mới> -SoSanh $Truoc`: `DAT` nghĩa là hook đã gọi lại runtime cũ.
- **Dữ liệu:** cài lại wheel cũ không xóa những gì runtime mới đã ghi. Nếu runtime cũ không đọc được sổ, quay về bằng bản sao lưu sổ từ bước 1; các việc ghi sau đó phải làm lại. Đường này chưa được diễn tập.
- Chỉ xóa venv cũ khi runtime mới đã chạy việc thật và bạn đã nghiệm thu.

## 8. Gửi góp ý

Repo công khai, nên **không dán** sổ, key, token, `.env`, cấu hình tài khoản hay mã nguồn riêng vào issue. Tạo issue tại <https://github.com/tamnguyendev/one-crew/issues/new>, tiêu đề bắt đầu bằng `[sol6.4]`, kèm:

- `& $OneCrew --version` và các bước đã làm.
- Kết quả `doctor`, và dòng `DAT` hoặc `KHONG DAT` của script đã chạy.
- Có thể kèm `$Truoc` và `$Sau` sau khi đọc lại: chúng có đường dẫn repo và SHA256 file, không có nội dung sổ.

Có thể tạo gói chẩn đoán đã lọc bí mật, chỉ lưu trên máy bạn: `& $OneCrew --project $BanSao --state-root $So support report --text "<mô tả>"`, rồi `support bundle <mã báo lỗi> --out <thư mục ngoài sổ>`. Đọc lại gói trước khi gửi.

## 9. Gỡ bản thử

Trong cửa sổ đã thử, repo thật không bị đổi. Đóng cửa sổ, rồi xóa thư mục `$Goc`. Nếu đã nâng repo thật (mục 7) thì làm phần quay về trước.

## Đã diễn tập khi phát hành

Diễn tập ngày 06/11/2026 trong phòng lab trên máy dựng gói, bằng đúng các lệnh ở trên, chỉ thay giá trị biến. Mọi đường dẫn có khoảng trắng; `LOCALAPPDATA`, `APPDATA`, `TEMP` trỏ vào lab; sổ đăng ký thật không đổi (đã kiểm). Kết quả: **57/57 kiểm đạt** trên gói dựng thử; lần lặp trên file tải từ trang phát hành ghi ở hồ sơ phát hành.

| Phần | Đã kiểm |
|---|---|
| Mục 2–4 | File tải khớp checksum; `kiem-goi.ps1` đạt, và từ chối khi hướng dẫn bị sửa; wheel đúng byte đã review; cài offline; smoke 38 điều kiện |
| Mục 5 | `git clone`, `init`, `doctor`, `plan lint`, `plan propose`, `plan report`; repo gốc không đổi |
| Mục 6, trên repo lab chạy 2.3.0.dev11 và 2.5.0.dev10 | `hien-trang.ps1`, `sao-chep-so.ps1`; runtime mới đọc được plan cũ trên sổ sao; `init` và `doctor` trên bản sao; runtime, hook, config, sổ nguồn và sổ đăng ký không đổi |
| Mục 7, cùng hai repo lab | Sao lưu, `init` trỏ hook sang runtime mới, `doctor`; quay về hook bằng bản sao lưu; runtime cũ qua `doctor` và đọc được plan của nó |

**Chưa diễn tập:**

- `owner approve`, `enforce`, `accept`: trong phiên AI các lệnh này bị từ chối, và lượt diễn tập đã kiểm đúng việc từ chối đó.
- AI làm việc thật, `verdict run` với model thật, Claude Code nạp hook trong phiên mới.
- Runtime cũ đọc sổ sau khi runtime mới đã **chạy việc**; quay về dữ liệu từ bản sao lưu; nâng từ version khác hai version trên; nâng trên repo thật hoặc repo lớn.
