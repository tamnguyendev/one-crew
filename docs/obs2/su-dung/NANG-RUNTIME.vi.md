# Nâng runtime OneCrew của một repo lên 2.5.0.dev10 (hướng dẫn riêng)

**Không cần đọc trang này để dùng UI mới.** Chỉ xem UI thì làm mục A của [Repo đang dùng OneCrew](REPO-DANG-DUNG-ONECREW.vi.md), không đổi gì của repo.

Trang này dành cho trường hợp bạn muốn hook và worker của repo chạy bản 2.5.0.dev10. Bản này là **prerelease beta**, nên việc nâng là quyết định của chủ repo.

Trong lượt phát hành:
- quy trình dưới đây **không** được thực hiện trên repo thật nào;
- các lệnh đã được diễn tập trên một repo thử trong phòng lab (mục cuối trang);
- đường nâng từ một version cụ thể của bạn chưa được chứng minh cho đến khi bạn tự thử trên bản sao (mục C2).

## C0. Khi nào chưa nên nâng

- Đang có việc chạy: plan đã duyệt hay đã enforce mà chưa nghiệm thu, hoặc có lượt chạy đang mở. Hãy hoàn tất hoặc tạm dừng trước; chưa ai kiểm việc nâng giữa chừng một mốc.
- Venv hay sổ của repo dùng chung với repo khác mà bạn chưa kiểm hết các repo đó (mục C1).
- Chỉ muốn xem UI: dùng mục A, không nâng.

**Bằng chứng cũ của plan còn mở phải kiểm lại** (từ 2.5.0.dev22, chủ duyệt 10/11):
- **Mốc chính sách.** Lần đầu runtime mới **ghi** vào một plan (chạy verdict, engine step/verify/accept/handoff, hay nghiệm thu), nó ghi một mốc `checkout.policy_epoch` cho cách chép artifact hiện hành. Lệnh chỉ đọc (`plan show`, `plan digest`, trang theo dõi) không ghi gì.
- **Bằng chứng có trước mốc không còn tính**, với mọi plan **chưa nghiệm thu**: verdict của mốc kiểm, kết quả kiểm của từng phần việc (node), và handoff.
  - `plan show` và trang theo dõi ghi **"cần kiểm lại"** thay cho "đạt".
  - `plan accept` từ chối, kèm lý do.
  - Phần việc phụ thuộc không được bắt đầu; node không được nghiệm thu; không handoff.
  - Một node đã **nghiệm thu nội bộ** trước mốc cũng phải kiểm lại (`engine verify`), rồi nghiệm thu lại (từ 2.5.0.dev23).
  - Một **handoff** đã làm trước mốc không còn tính: sau khi kiểm lại các node, chạy handoff lại (từ 2.5.0.dev23).
- **Plan đã nghiệm thu giữ nguyên lịch sử.**
- **Vì vậy:** tốt nhất chỉ nâng khi repo không còn plan mở. Nếu còn, sau khi nâng phải **chạy lại verdict** cho từng mốc (và `engine verify` cho từng phần việc đã kiểm), rồi mới nghiệm thu.
- Mỗi lần cách chép đổi (giá trị `checkout_policy` mới), một mốc mới được ghi, và quy tắc trên áp lại.
- **Plan workflow đang dở (lỗi đã biết, có từ 2.5.0.dev22):** sau khi nâng, một bước đã đạt bị đánh dấu "cần kiểm lại" nhưng chế độ tự chạy không kiểm lại nó, và màn hướng dẫn nói sai "bằng chứng đầu vào không khớp"; root đứng yên. **Cách làm:** chạy `engine verify` cho từng bước đó (xem `LOI-DA-BIET.vi.md`).
- **Từ 2.5.0.dev25:**
  - không có kết quả kiểm nào phải chạy lại: dấu `ONECREW_VERIFIER` không tính vào dấu vân tay; định dạng sổ và tệp canh không đổi; quay về dev24 được (mất hai lớp chặn);
  - một bộ kiểm, reviewer hay lệnh tiền điều kiện gọi lệnh của chủ (`plan approve|accept|enforce`, `hook mode`, `support ...`) trên một sổ ngoài thư mục tạm nay bị từ chối. **Trước khi nâng**, đọc argv của mọi mốc kiểm và mọi lệnh `command_ok` bước 0 của repo xem có gọi `onecrew` như vậy không;
  - khi hai plan cùng hiệu lực trong một dự án, lượt kiểm hay sửa do phiên AI chạy không còn đổi plan mà hook canh; hook theo plan chủ chọn sau cùng. Sau khi nâng, chạy `scripts/owner/enforce.ps1 -Plan <plan đang làm>` để chắc;
  - worker OneCrew (`ONECREW_ACTOR=onecrew`), cùng lệnh mà worker v1 chạy qua OneCrew (mang `ONECREW_VERIFIER`), không còn tắt được enforce hay chạy `support` của chủ;
  - **đây vẫn là lớp mềm:** mã do AI viết mà cố ý né (tự xóa dấu, đổi `TEMP`, hardlink, sửa thẳng sqlite) vẫn qua. "Chỉ chủ duyệt" **chưa** được ép bằng mật mã. Xem `LOI-DA-BIET.vi.md`.
- **Từ 2.5.0.dev24 cách chép là `exact-blob-bytes/3`:** mọi receipt của bộ kiểm lệnh ghi thêm chương trình đã chạy và gói Python của nó. Hệ quả khi nâng từ bản trước: **mọi pass của bộ kiểm lệnh trên plan chưa nghiệm thu phải chạy lại một lần**, có hay không có `inputs`. Plan đã nghiệm thu giữ nguyên.

## C1. Kiểm trước (chỉ đọc)

Đặt các biến của mục A0 trong [Repo đang dùng OneCrew](REPO-DANG-DUNG-ONECREW.vi.md). Sau đó làm A1, A2 và A3: venv 2.5.0.dev10 riêng, hiện trạng `$Truoc`, bản sao sổ `$BanSao`.

1. **Việc đang chạy và hợp đồng đang mở.** Xem trên bản sao:

   ```powershell
   & "$Venv\Scripts\onecrew.exe" --project $DuAn --state-root $BanSao track list --all-projects
   ```

   Mỗi plan là một dòng có trạng thái. Plan nào đang thực hiện, đang chờ bạn, hoặc đã kiểm mà chưa nghiệm thu thì xử lý xong trước.
2. **Ai dùng chung venv và sổ.** Sổ đăng ký của máy liệt kê các repo và sổ của chúng:

   ```powershell
   Get-Content -Raw -Encoding UTF8 -LiteralPath "$env:LOCALAPPDATA\OneCrew\hook-projects.json"
   ```

   Repo nào trỏ cùng sổ `$So`, hoặc có hook gọi cùng `onecrew.exe` (chạy `hien-trang.ps1` cho từng repo), đều bị ảnh hưởng khi nâng. Kiểm thêm các script hay lịch chạy gọi venv đó.
3. **Tương thích dữ liệu.** `sao-chep-so.ps1` in version schema của sổ. Bước A4 cho biết UI mới có đọc được sổ đó không.

## C2. Thử nâng trên bản sao

Mở **một cửa sổ PowerShell mới, chỉ dùng để thử**. Đặt lại biến A0, rồi đổi thư mục dữ liệu máy của **riêng cửa sổ này**, để `init` thử không ghi vào sổ đăng ký thật:

```powershell
$Lab = "$Goc\thu nang"
$env:LOCALAPPDATA = "$Lab\local"
$env:APPDATA = "$Lab\roaming"
```

Sao repo: chỉ phần đã commit, vào thư mục khác. Repo thật không đổi:

```powershell
git clone $DuAn "$Lab\repo"
```

Sao sổ. Đọc `$So` từ file hiện trạng, vì `$env:LOCALAPPDATA` của cửa sổ này đã đổi:

```powershell
$So = (Get-Content -Raw -Encoding UTF8 -LiteralPath $Truoc | ConvertFrom-Json).state_root
```

```powershell
powershell -ExecutionPolicy Bypass -File "$SuDung\sao-chep-so.ps1" -Venv $Venv -Nguon $So -Dich "$Lab\so"
```

Kiểm runtime mới đọc được việc cũ trên sổ sao. Đây là lệnh chỉ đọc; `<plan>` là tên một plan có trong sổ:

```powershell
& "$Venv\Scripts\onecrew.exe" --project $DuAn --state-root "$Lab\so" continue <plan>
```

Gắn runtime mới vào repo sao, rồi kiểm:

```powershell
& "$Venv\Scripts\onecrew.exe" --project "$Lab\repo" --state-root "$Lab\so" init --yes
```

```powershell
& "$Venv\Scripts\onecrew.exe" --project "$Lab\repo" --state-root "$Lab\so" doctor
```

Mong đợi: `doctor` có dòng hook PASS. Có thể chạy thêm một việc nhỏ trên repo sao, theo mục 6 của [Bắt đầu sử dụng](BAT-DAU-SU-DUNG.vi.md), để xem đầu-cuối.

Sổ ghi project theo đường dẫn. Vì vậy repo sao (`$Lab\repo`) là một project mới trong sổ sao; các plan cũ vẫn thuộc đường dẫn của repo thật. Lệnh `continue` ở trên đọc chúng theo đúng đường dẫn đó, chỉ đọc.

## C3. Nâng thật (khi đã quyết, lúc không có việc chạy)

1. Sao lưu, mỗi thứ vào một thư mục mới có ngày giờ:
   - sổ: dùng `sao-chep-so.ps1` với `-Dich` mới;
   - các file `$DuAn\.claude\settings.local.json`, `$DuAn\.claude\settings.json` (nếu có) và `$DuAn\.onecrew\config.json`;
   - ghi lại đường dẫn venv cũ và `onecrew --version` cũ. File `$Truoc` đã có những thông tin này.
2. **Giữ nguyên venv cũ.** Cài 2.5.0.dev10 vào một venv **mới** (`$Venv`); không cài đè.
3. Trỏ hook sang runtime mới:

   ```powershell
   & "$Venv\Scripts\onecrew.exe" --project $DuAn --state-root $So init
   ```

   `init` liệt kê việc sẽ làm và hỏi y/N. Sổ, quy tắc và config đã có thì để nguyên; hook trong `settings.local.json` được trỏ sang `onecrew.exe` mới.
4. Kiểm:

   ```powershell
   & "$Venv\Scripts\onecrew.exe" --project $DuAn --state-root $So doctor
   ```

   Mong đợi: hook PASS. Sau đó mở một phiên Claude Code **mới** trong repo.

## C4. Quay về

- **Hook:** chép lại các file settings và config đã sao lưu ở C3, hoặc chạy `init` của runtime cũ. Sau đó chạy `hien-trang.ps1 … -SoSanh $Truoc` để xác nhận hook đã gọi lại runtime cũ.
- **Dữ liệu: không có cam kết quay về bằng cách cài lại wheel cũ.** Nếu runtime mới đã ghi vào sổ những gì runtime cũ không đọc được, cài lại wheel không xóa chúng đi. Quay về bản sao lưu sổ ở C3 thì mất những gì ghi sau lúc đó. Đó là quyết định của chủ repo; sau khi quay về, kiểm bằng `doctor` của runtime cũ trước khi làm tiếp.
- Chỉ xóa venv cũ khi runtime mới đã chạy việc thật và bạn đã nghiệm thu.

## Không làm

- Không dùng terminal của chủ để né hợp đồng hay chốt quyền. Ví dụ: không duyệt chỉ để AI qua được bước bị chặn; không dùng `owner record` hay `owner enforce --mode log` để vượt kiểm.
- Không sửa hook bằng tay để mở khóa lệnh trên UI.
- Không nâng repo hay runtime của dự án khác "tiện thể" khi thử bản beta này.
- Runtime từ 2.4 có đường `support target | artifact | install | rollback` cho bản vá gắn với một báo lỗi. Bản beta này không phát hành theo đường đó, và đường đó chưa được diễn tập cho bước nâng lên 2.5.0.dev10.

## Đã diễn tập khi phát hành

Diễn tập ngày 05/11/2026 trên một **repo lab**, không phải repo thật, chạy runtime 2.3.0.dev11. Đây là cùng lượt 42/42 ghi trong [Repo đang dùng OneCrew](REPO-DANG-DUNG-ONECREW.vi.md). Đường dẫn có khoảng trắng, sổ đăng ký thật không đổi.

- **C1:** `track list --all-projects` trên bản sao thấy plan; đọc được sổ đăng ký của lab.
- **C2:** chạy trong cửa sổ riêng, có `LOCALAPPDATA` và `APPDATA` trỏ vào lab.
  - `git clone`, rồi sao sổ;
  - `continue <plan>` đọc được việc cũ trên sổ sao;
  - `init --yes` trên repo sao, `doctor` cho hook PASS;
  - repo gốc và sổ đăng ký của cửa sổ chính không đổi.
- **C3:** sao lưu sổ và các file settings, config. `init` của runtime mới gộp hook (có giữ `.bak`). `doctor` cho hook PASS. `hien-trang.ps1` thấy hook đã chuyển sang 2.5.0.dev10.
- **C4:** chép lại settings và config đã sao lưu. `hien-trang.ps1 -SoSanh` in DAT, tức hook đã về 2.3.0.dev11. `doctor` của runtime cũ cho hook PASS.

**Chưa diễn tập:**
- quay về dữ liệu (khôi phục bản sao lưu sổ) sau khi runtime mới đã ghi việc;
- nâng runtime trên repo đang có việc chạy;
- đường `support install | rollback`;
- nâng từ version khác 2.3.0.dev11.
