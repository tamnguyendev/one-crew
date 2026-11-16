# OneCrew

OneCrew là **hợp đồng làm việc cho AI** trong Claude Code:

- AI chỉ sửa những gì nằm trong hợp đồng bạn đã duyệt. Hook của Claude Code chặn mọi thay đổi ra ngoài.
- Mỗi mốc của việc được kiểm độc lập (lệnh kiểm hoặc người review riêng), có biên nhận ghi vào sổ.
- Chỉ bạn duyệt và nghiệm thu, trong terminal của bạn. Các lệnh đó bị từ chối nếu chạy trong phiên AI.

**Bản hiện tại: `2.5.0.dev28`, bản beta (prerelease)**, đã thử trên Windows 10/11. Chưa phải bản ổn định. Ghi chú phát hành và các bản khác: trang [Releases](https://github.com/tamnguyendev/one-crew/releases).

> **Luôn cài theo tag phát hành** (ví dụ `v2.5.0.dev28`), như các lệnh bên dưới, để có đúng bản đã được kiểm. Nhánh `main` có thể có thay đổi chưa phát hành.

## Cần có

- Windows 10/11 với PowerShell 5.1 trở lên. Linux và macOS chưa được thử.
- Python 3.10 trở lên, bản cài từ python.org. Gõ `py -0p` để xem các bản đã cài. Đừng dùng alias `python` của Microsoft Store.
- Git 2.40 trở lên, có trong PATH.
- Claude Code CLI, đã đăng nhập.
- Repo bạn muốn đặt dưới hợp đồng phải là một repo Git có ít nhất một commit.

## 1. Cài OneCrew (một lần cho mỗi máy)

Dán vào PowerShell. Sửa hai đường dẫn đầu cho máy của bạn:

```powershell
$Python  = "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe"
$Venv    = "D:\OneCrew\venv"
& $Python -m venv $Venv
& "$Venv\Scripts\python.exe" -m pip install "git+https://github.com/tamnguyendev/one-crew.git@v2.5.0.dev28"
$OneCrew = "$Venv\Scripts\onecrew.exe"
& $OneCrew --version
```

Bạn thấy `onecrew 2.5.0.dev28` là đạt.

**Giữ venv ở nguyên chỗ.** Hook trong repo gọi thẳng `$Venv\Scripts\onecrew.exe`; xóa hay chuyển venv thì hook hỏng.

Hai cách cài khác, kết quả như nhau:
- **Tải wheel:** tải file `.whl` và `SHA256SUMS` ở trang Releases. So SHA256 bằng `Get-FileHash`, rồi chạy `pip install <file .whl>`. GitHub có thể đổi dấu `+` trong tên file, nên hãy so mã băm, đừng so tên.
- **Clone mã nguồn:** `git clone --branch v2.5.0.dev28 https://github.com/tamnguyendev/one-crew.git`, rồi chạy `pip install .` trong thư mục vừa clone.

## 2. Gắn OneCrew vào một repo

```powershell
$env:ONECREW_LANG = 'vi'
$DuAn = "D:\du an\repo cua toi"
$So   = "D:\OneCrew\so"
& $OneCrew --project $DuAn --state-root $So init
```

`$So` là **sổ** (state root), nơi OneCrew lưu hợp đồng, kết quả kiểm và lần duyệt. Đặt sổ ngoài repo. Nhiều repo có thể dùng chung một sổ.

`init` liệt kê những gì sẽ ghi rồi hỏi `Tiếp tục? [y/N]`. Bạn gõ `y`. Lệnh ghi các file sau:

| File | Là gì |
|---|---|
| `$So\ledger.sqlite3`, `$So\plans\owner-rules.md` | Sổ và quy tắc của bạn. Nếu đã có thì giữ nguyên. |
| `$DuAn\.onecrew\config.json` | Đường dẫn sổ trên máy này. **Đừng commit**: thêm `.onecrew/` vào `.gitignore`. |
| `$DuAn\.claude\settings.local.json` | Hook của Claude Code. Hook và quyền đang có được giữ, bản cũ được sao ra `.bak`. Thêm `--shared` nếu muốn ghi vào `settings.json` dùng chung với nhóm. |
| `$DuAn\docs\wiki\` | Khung wiki của project, 3 file. |

Chạy lại `init` không đổi thêm gì.

## 3. Kiểm

```powershell
& $OneCrew --project $DuAn --state-root $So doctor
```

Bạn thấy `0 FAIL` là đạt. Có FAIL thì đọc đúng dòng đó; bảng ở mục 6 có cách xử lý.

Sau đó **mở một phiên Claude Code MỚI trong repo.** Claude Code chỉ nạp hook lúc bắt đầu phiên, nên phiên đang mở từ trước sẽ không thấy hook.

## 4. Việc đầu tiên, từ đầu đến cuối

1. **Giao việc.** Trong phiên Claude Code mới, nói việc bạn muốn bằng lời. Ví dụ: "tạo file docs/xin-chao.md với đúng một dòng: Xin chao OneCrew".
2. **AI viết hợp đồng, kiểm rồi đề xuất.** Hợp đồng ghi mục tiêu, file được sửa, đầu ra và cách kiểm từng mốc. Hợp đồng mẫu cho đúng việc trên: [docs/obs2/su-dung/mau-hop-dong.json](docs/obs2/su-dung/mau-hop-dong.json).
   ```powershell
   & $OneCrew --project $DuAn --state-root $So plan lint --file hop-dong.json --author <model id>
   & $OneCrew --project $DuAn --state-root $So plan propose xin-chao --file hop-dong.json --author <model id>
   ```
   Đạt khi `lint: clean` và `"status": "proposed"`. Dòng `[note …]` chỉ là ghi chú.
3. **Bạn duyệt**, trong terminal của bạn:
   ```powershell
   & $OneCrew --project $DuAn --state-root $So owner approve xin-chao --reference "<vì sao bạn duyệt>" --human
   & $OneCrew --project $DuAn --state-root $So owner enforce xin-chao --human
   ```
   `--human` chỉ để kết quả in ra dễ đọc, thay vì JSON. Từ lúc `enforce`, hook chặn mọi thay đổi ra ngoài hợp đồng. Trong phạm vi đã duyệt, AI làm hết việc mà không cần bạn duyệt lại từng bước.
4. **AI làm việc, rồi kiểm từng mốc.**
   ```powershell
   & $OneCrew --project $DuAn --state-root $So verdict run --plan xin-chao --milestone M1
   & $OneCrew --project $DuAn --state-root $So plan report xin-chao
   ```
5. **Bạn thử kết quả, rồi nghiệm thu**, trong terminal của bạn. Mã artifact lấy từ `verdict artifact`; mã này phải trùng với mã của mốc đã đạt trong `plan report`.
   ```powershell
   & $OneCrew --project $DuAn --state-root $So verdict artifact --plan xin-chao
   & $OneCrew --project $DuAn --state-root $So owner accept xin-chao --artifact-sha <mã> --reference "<đã thử gì>" --human
   ```

Sau `owner accept`, có lúc màn hình báo "Chưa xác nhận được kết quả" dù sổ đã ghi xong. Hãy chạy `plan show xin-chao` để xem lại trước khi chạy lệnh lần nữa.

## 5. Xem tiến độ trên trình duyệt

```powershell
& $OneCrew --project $DuAn --state-root $So track open
```

Lệnh mở một trang web chỉ đọc trên máy bạn, ở `127.0.0.1`. Trang có danh sách mọi việc trong sổ, việc chờ bạn duyệt, kết quả kiểm từng mốc và lịch sử. Trang không chạy lệnh nào, và đóng trang không dừng việc AI đang làm. Hướng dẫn: [DANH-SACH-CONG-VIEC.vi.md](docs/obs2/su-dung/DANH-SACH-CONG-VIEC.vi.md).

## 6. Lỗi thường gặp

| Gặp | Làm gì |
|---|---|
| `requires a different Python` khi chạy `pip install` | Python cũ hơn 3.10. Chọn bản khác trong `py -0p`, rồi tạo lại venv. |
| `init` thoát với mã 2: "No git repository found" | `$DuAn` chưa phải repo Git hoặc chưa có commit. Chạy `git init` **trong chính repo đó** rồi commit một lần. Đừng `git init` thư mục cha chứa nhiều repo. |
| `init` thoát với mã 1 | Đã ghi xong, nhưng Claude CLI chưa có hoặc chưa đăng nhập. |
| `doctor` báo hook FAIL "stale" | Venv đã bị xóa hay chuyển chỗ. Tạo lại venv ở đúng `$Venv`, hoặc chạy lại `init`. |
| `plan lint` báo `[target_path] … does not exist` | `target.paths` trong hợp đồng phải là file hoặc thư mục đang có. |
| `owner … refused: … AI tool session` | Lệnh của chủ đã bị chạy trong phiên AI. Mở terminal riêng của bạn và chạy lại ở đó. |
| Hook không chặn gì | Phiên Claude Code được mở trước `init`/`enforce`, hoặc chưa có hợp đồng nào được `enforce`. Mở phiên mới. |

Các lỗi đã biết khác: [LOI-DA-BIET.vi.md](docs/obs2/su-dung/LOI-DA-BIET.vi.md).

## 7. Nâng bản, gỡ

- **Nâng bản:** cài bản mới vào một venv mới, rồi chạy lại `init` để hook trỏ sang venv đó. Venv cũ cứ giữ, phòng khi cần quay lại. Repo đã dùng OneCrew từ trước thì đọc [REPO-DANG-DUNG-ONECREW.vi.md](docs/obs2/su-dung/REPO-DANG-DUNG-ONECREW.vi.md).
- **Gỡ:**
  - xóa các mục OneCrew khỏi `.claude\settings.local.json`, hoặc khôi phục file `.bak`;
  - xóa thư mục `.onecrew` trong repo;
  - xóa venv.

  Sổ là của bạn: giữ hay xóa tùy bạn.

## Giới hạn của bản beta

- Mới thử trên Windows. Linux và macOS chưa chạy thật.
- `budget.max_calls` trong hợp đồng **không** được đếm cho phiên Claude Code làm việc dưới hook. Con số này chỉ được tính cho các lượt OneCrew tự chạy.
- Mọi test tự động dùng Claude giả. Lời khuyên và review bằng model thật mới chạy thử ở phạm vi nhỏ.
- Khi gửi góp ý, **đừng gửi** `ledger.sqlite3`, thư mục sổ, key, token hay file `.env`. Lệnh `onecrew support report` tạo gói chẩn đoán đã lọc bí mật.

## Tài liệu thêm

- [docs/README.en.md](docs/README.en.md): bản tiếng Anh một trang.
- [docs/CHANGELOG.md](docs/CHANGELOG.md): thay đổi qua từng bản.
- [docs/v2-core.vi.md](docs/v2-core.vi.md): những gì có trong gói cài và cách hợp đồng v2 hoạt động.
- [examples/owner-rules.vi.md](examples/owner-rules.vi.md): mẫu quy tắc của chủ.
- [docs/LICH-SU.vi.md](docs/LICH-SU.vi.md): README cũ, gồm kiến trúc revision 2–9 và luồng `job`/`work` của bản v1. Luồng v1 chỉ chạy từ checkout qua `onecrew_cli.py`, không có trong gói cài.
