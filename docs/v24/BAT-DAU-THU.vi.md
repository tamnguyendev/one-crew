# Bắt đầu thử OneCrew @@VERSION@@ (beta, thử cách ly)

Điểm vào duy nhất để thử bản beta 2.4. Đọc trang này là đủ để bắt đầu; hợp đồng và báo cáo kỹ thuật chỉ cần khi muốn đào sâu. Mọi thứ cần dùng nằm trong chính gói này (`verify\`, `verify\thu-tay\`, `docs\`).

| Mục | Giá trị |
|---|---|
| Gói | `@@PACKAGE@@` (đóng băng; `manifest.json`, `SHA256SUMS`) |
| Script thử (trong gói) | `@@PACKAGE@@\verify\thu-tay\` — `chuan-bi.ps1`, `vao-moi-truong.ps1`, `roi-lab.ps1`, `don-dep.ps1` |
| Version · code | `@@VERSION@@` · snapshot `@@COMMIT@@` (nhánh `claude/onecrew-2.4`) |
| Wheel · SHA256 | `wheel\@@WHEEL@@` · `@@WHEEL_SHA@@` |
| Wheel quay về | `wheel\previous\@@PREVIOUS@@` · `@@PREVIOUS_SHA@@` |
| Python | `C:\Users\NUC\AppData\Local\Programs\Python\Python313\python.exe` (không dùng `python` trần) |
| Trạng thái | beta (prerelease), **chưa nghiệm thu production**; `manifest.json` → `claims` ghi đúng trạng thái. Giới hạn: README của gói §4, `docs\limits-final.md`. |

## 1. Bản này có gì mới và bạn kiểm được gì

Năm mốc của 2.4 và xác thực API, chạy trên một bản sao project và sổ riêng:

| Mốc | Người dùng thấy gì | Thử ở bài |
|---|---|---|
| S1 báo lỗi một lần | `support report` cho một mã `FB-…`, gửi lại cùng khóa không tạo mã mới; `support bundle` ghi hồ sơ chẩn đoán ra máy bạn (lọc bí mật theo mẫu), không tải đi đâu | 3 |
| S2 bản vá OneCrew | báo cáo → bản vá → cài vào venv mới tại đích → kiểm lại lỗi gốc → chuyển hook ở điểm an toàn; quay lui có điều kiện; bytecode `.pyc` chưa kiểm không bao giờ chạy | 1 (tự động), 6 |
| A worker tự đọc nguồn | root khai `authority.read`, node khai `sources`; receipt ghi cây, kết quả, số lượt | 1 (tự động) |
| B working context | `knowledge.delivered` cho mỗi attempt; tri thức bị thu hồi khi node đang chạy thì candidate không công bố; `wiki consumers` cho biết node bị ảnh hưởng | 5 |
| C bước 0 và cách chạy node | `plan step0 show` nói đủ để làm chưa và vì sao; `engine measure` đo thời gian tới hành động có ích đầu tiên | 5 |
| Xác thực API cho advisor/reviewer | `plan advise <plan> --auth api` hoặc `"auth": "api"` trong hợp đồng: key `ANTHROPIC_API_KEY` của terminal chỉ vào tiến trình Claude CLI; thiếu key → `credential_missing`; key bị provider phản chiếu lại bị che `[withheld]` | 1 (tự động, CLI giả), 8 (model thật, bạn chạy) |

## 2. Chuẩn bị môi trường cách ly (một lệnh, dot-source)

`onecrew init` ghi registry hook vào `%LOCALAPPDATA%\OneCrew\hook-projects.json` của **tài khoản đang chạy**. Để bài thử không chạm registry thật, `chuan-bi.ps1` đổi `LOCALAPPDATA`, `APPDATA`, `TEMP`, `TMP` **chỉ trong cửa sổ PowerShell sẽ gõ lệnh thử** sang `<lab>\env\…` (không đổi biến cấp User/Machine; không đụng `CLAUDECODE`/`CLAUDE_CODE_CHILD_SESSION`, nên guard owner của OneCrew vẫn hoạt động), ghi dấu sở hữu lab (`<lab>\.lab-thu-dev5.json` + mục trong `%USERPROFILE%\.onecrew-thu-tay\labs.json`), tạo venv thử, bản sao project độc lập, `init`, `doctor`, rồi kiểm: registry thử trong `<lab>\env`, registry thật không đổi hash, hook bản sao trỏ exe thử; cuối cùng để cửa sổ ở trong môi trường thử. Script tìm gói ở hai mức trên nó (`verify\thu-tay` → gói) và đọc version/wheel từ `manifest.json`.

Vì môi trường chỉ sống trong **tiến trình PowerShell** đã nạp script, phải **dot-source** (dấu chấm và khoảng trắng đầu dòng), không chạy `powershell -File`. Dán vào cửa sổ PowerShell bạn sẽ dùng cho mọi bài thử:

```powershell
. "@@PACKAGE@@\verify\thu-tay\chuan-bi.ps1"
```

(Cách khác, một lệnh bấm chạy: `powershell -NoExit -ExecutionPolicy Bypass -Command ". '@@PACKAGE@@\verify\thu-tay\chuan-bi.ps1'"` mở một PowerShell lồng trong cùng terminal, đã ở trong môi trường thử; gõ các bài thử trong đó, `exit` để rời.)

- Mặc định lab = `D:\OneCrewRuns\v24 thu tay dev5` (phải chưa tồn tại; tên khác: `-Lab "<thư mục mới>"`; ít nhất ba mức `D:\<thư mục>\<lab>`), project mẫu Git một file do script tạo. Thử trên bản sao project của bạn: `-Source "<repo Git>"` — `git clone --no-hardlinks`, bỏ remote, xóa `.onecrew` và `.claude\settings.local.json` nếu chúng được commit.
- **ĐẠT** = hai dòng cuối `DAT: dang o moi truong thu (cua so nay): lab=…, onecrew @@VERSION@@` và `DAT: moi truong thu san sang tai <lab>…`; `$labOk` là `True`; `$exe $proj $state $lab $venv` đã đặt. **KHÔNG ĐẠT** = `KHONG DAT: …` và "Dung tai day": dừng tại bước hỏng, `$labOk` là `False`, biến bị xóa — không gõ lệnh thử trong cửa sổ đó.
- `init` hỏi `claude auth status` của CLI thật (chỉ đọc, không đăng nhập); không gọi model.
- **Mở cửa sổ mới hoặc tiếp tục phiên thử:** dot-source `vao-moi-truong.ps1`; nó chỉ nhận lab do `chuan-bi.ps1` tạo (có dấu sở hữu), kiểm `onecrew.exe`, config, sổ, registry thử rồi đặt lại biến; thư mục khác bị từ chối và không bao giờ bị biến thành lab:

```powershell
. "@@PACKAGE@@\verify\thu-tay\vao-moi-truong.ps1" -Lab "D:\OneCrewRuns\v24 thu tay dev5"
```

Dấu hiệu đúng: `DAT: dang o moi truong thu (cua so nay)` và `LOCALAPPDATA=<lab>\env\LocalAppData`. Thấy `KHONG DAT` là cửa sổ vẫn ở registry thật — đừng gõ `init` hay lệnh thử.

## 3. Kiểm gói (tự động, CLI giả, không gọi model)

Lệnh duy nhất, chạy từ terminal của bạn (không chạy trong phiên AI):

```powershell
powershell -ExecutionPolicy Bypass -File "@@PACKAGE@@\verify\thu-goi.ps1"
```

- Kết quả ghi vào một thư mục mới `D:\OneCrewRuns\v24 thu cua anh @@VERSION@@ <yyyyMMdd-HHmmss>`; đường dẫn chính xác in ở dòng `thu muc ket qua:` đầu và cuối. Muốn đặt tên: `-Work "<thư mục trống>"`.
- **ĐẠT** = dòng cuối bắt đầu bằng `DAT: goi @@VERSION@@ ... @@STEPS@@/@@STEPS@@ buoc ...` và mã thoát 0. **KHÔNG ĐẠT** = `KHONG DAT:` và mã khác 0; lý do ở các dòng `- ` ngay trên; mã 2 là từ chối chạy (thư mục kết quả đã có file, thiếu file).
- Bằng chứng: `<kết quả>\verify\verify-report.json` (@@STEPS@@ bước, `result: pass`), `<kết quả>\task dau tien\first-task-drill-log.json`, `<kết quả>\alpha\alpha-flow-log.json` và `feedback-alpha.zip`.
- Mất khoảng 25 phút. Chạy **một lần** cho bản này; không chạy lại sau mỗi bài thử.

## 4. Các bài thử

Ký hiệu: **[TĐ]** tự động, CLI/model giả · **[TT]** bạn thao tác, không cần model · **[MT]** cần provider thật. Mọi lệnh [TT] gõ trong cửa sổ đã vào môi trường thử (mục 2); `$exe`, `$proj`, `$state`, `$lab` đã đặt sẵn.

| # | Bài | Loại | Thao tác | Kết quả mong đợi | Bằng chứng cần xem |
|---|---|---|---|---|---|
| 1 | Kiểm gói | TĐ | mục 3 | `DAT … @@STEPS@@/@@STEPS@@` | `verify-report.json` |
| 2 | Môi trường thử + `init` bản sao | TT (script, dot-source) | mục 2 | `DAT: dang o moi truong thu` + `DAT: moi truong thu san sang`; `$labOk` True; `doctor` 0 FAIL; registry thật không đổi | `<lab>\env\LocalAppData\OneCrew\hook-projects.json` có mục của bản sao; `<lab>\project\.onecrew\config.json`; `<lab>\.lab-thu-dev5.json` |
| 3 | S1 báo lỗi một lần | TT | `& $exe --project $proj --state-root $state support report --text "Buoc kiem M1 bao sai du file dung" --key k1 --json` (hai lần); `$fb = (& $exe --project $proj --state-root $state support list --json \| ConvertFrom-Json)[0].id`; `$out = (& $exe --project $proj --state-root $state support bundle $fb --out "$lab\bundle" \| ConvertFrom-Json).export` | cùng một mã `FB-…` (lần hai `duplicate: true`); `support show $fb --json` → `status: reported`, tái hiện `unknown`; `$out` = `<lab>\bundle\<FB-…>-<12 ký tự>`, `manifest.json` trong đó có `uploaded: false`; `support confirm` bị từ chối trong phiên AI | thư mục `$out`: `manifest.json`, `files\feedback.json`, `files\doctor.txt` (đã lọc bí mật) |
| 4 | Task đầu tiên | TĐ phần A · MT phần B | `examples\first-task\README.vi.md` (A đã chạy tự động trong bài 1; B: model thật) | A: node C chạy, receipt, check đạt; B: README §6B | `first-task-drill-log.json` (A) |
| 5 | Xem bước 0, đo, consumer trên sổ diễn tập | TT | trên `<kết quả bài 1>\task dau tien\task dau tien thu`: `onecrew.exe` trong `venv\Scripts`, `--project "project mau" --state-root "so thu"`: `plan show P1`, `plan step0 show P1`, `engine measure P1`, `wiki consumers --plan P1 --json`, `support list --json` | thẻ bước 0 "đủ để làm: chưa" kèm lý do `no_proposal_check` (plan mẫu không khai bước 0, đúng thiết kế); `measure` có `time_to_first_useful_action_seconds`; `consumers: []`; `support list` `[]` | đầu ra JSON; không lệnh nào ghi gì ngoài sổ thử |
| 6 | S2 chuỗi vá | TĐ (V20–V22, V27–V31) · TT **chưa sẵn sàng** | tự động đã chạy trong bài 1; bài thủ công cần `support target add` (lệnh của chủ), plan sửa đã duyệt có `support_install:<đích>`, wheel vá: chưa có kịch bản thủ công đã kiểm | V21 `blocked_by_authority` khi thiếu quyền; V22 `rollback` → `rolled_back`; V29/V31 quay lui từ chối khi `.pyc` runtime cũ bị thay | `verify-report.json` |
| 7 | A nguồn, B thu hồi, C chế độ chạy | TĐ (V23–V26) | đã chạy trong bài 1 | V23 ngoài phạm vi bị từ chối; V24/V26 node bị giữ `input_changed`, không gọi model; V25 trần điều tra | `verify-report.json` |
| 8 | Xác thực API cho advisor | TĐ (V32, CLI giả) · **MT** bạn chạy | TĐ: V32 từ wheel đã cài (subscription không thấy key; api thấy key, không vào sổ/argv; thiếu key `credential_missing`; key sai 401 một lời gọi; `--auth api` ở CLI). MT: trên sổ thử sau bài 2, với `ANTHROPIC_API_KEY` trong terminal (biến User của bạn là đủ): tạo plan (bài 4A hoặc `examples\first-task`), rồi `& $exe --project $proj --state-root $state plan advise P1 --auth api` | TĐ: V32 pass. MT: `plan.advised` có `auth: api`, `usable: true` (hoặc lỗi thật của provider, không có key trong lỗi) | TĐ: `verify-report.json`; MT: `plan show P1` → `advice`; receipt không chứa key |

Khi một bài sai: ghi lệnh đã gõ, đầu ra, và kèm file bằng chứng ở cột cuối (mục 6). Không cần chạy lại bài 1.

## 5. Kết thúc, tiếp tục, quay về (chỉ trong môi trường cách ly)

- **Tiếp tục phiên thử:** cửa sổ mới → dot-source `vao-moi-truong.ps1 -Lab "<lab>"` (mục 2); sổ thử ở `<lab>\so` giữ nguyên.
- **Kết thúc:** từ một cửa sổ PowerShell **chưa ở trong lab** (cửa sổ đang ở trong lab bị từ chối, vì nó sẽ xóa dưới chân mình). Không có cửa sổ nào khác? Rời lab ngay trong cửa sổ đang dùng bằng `. "@@PACKAGE@@\verify\thu-tay\roi-lab.ps1"` (trả `LOCALAPPDATA/APPDATA/TEMP/TMP` về giá trị thật đã nhớ, xóa `$exe…`, in `DAT: da roi moi truong thu`), rồi chạy:

  ```powershell
  powershell -ExecutionPolicy Bypass -File "@@PACKAGE@@\verify\thu-tay\don-dep.ps1" -Lab "<lab>"
  ```

  `don-dep.ps1` chỉ xóa đúng lab mà `chuan-bi.ps1` đã tạo: đường dẫn tuyệt đối sau khi chuẩn hóa, không nằm trong/chứa gói, sâu ít nhất ba mức, không đi qua link/junction ở lab hay thư mục cha, có `.lab-thu-dev5.json` ghi đúng đường dẫn này với nonce trùng mục trong `labs.json` (script này không bao giờ tạo hai thứ đó), đúng cấu trúc lab. Không qua kiểm → `KHONG DAT … (khong xoa gi)` mã 2. **ĐẠT** = `DAT: da xoa <lab> (kiem: khong con); registry that … khong doi`, mã 0. Thư mục kết quả bài 1 giữ hay xóa tùy bạn (`don-dep.ps1` từ chối xóa nó).
- **Quay về bản trước — hai trường hợp khác nhau, không dùng chung một lệnh:**
  - **A. Chỉ cài wheel để thử (bài 2–5, 8; chưa chạy `support install`):** hook của bản sao vẫn trỏ vào `$venv`; cài đè bản trước vào chính venv đó là đủ:

    ```powershell
    & "$venv\Scripts\python.exe" -I -m pip install --no-index --no-build-isolation --force-reinstall "$pkg\wheel\previous\@@PREVIOUS@@"; & $exe --version
    ```

    Lên lại: cùng lệnh với `$pkg\wheel\@@WHEEL@@`. Bản trước đọc được sổ do bản này ghi trong phạm vi đã diễn tập (bộ kiểm V7 và V16; plan có `auth` đọc được, bản trước bỏ qua `auth`).
  - **B. Đã chuyển hook bằng S2 (`support install … --target <đích>` ra `switched`):** hook trỏ vào **venv mới** cạnh venv cũ; cài đè `$venv` không chuyển hook về, và nếu `$venv` là runtime cũ S2 đã ghi mốc thì đổi nội dung nó làm quay lui chính thức **bị từ chối**. Đường duy nhất: `support rollback` (lệnh của chủ, terminal riêng, bị từ chối trong phiên AI), giữ nguyên runtime cũ:

    ```powershell
    Get-Content "$proj\.claude\settings.local.json"            # exe nào đang được hook gọi, trước và sau
    & $exe --project $proj --state-root $state support status FB-… --json
    & $exe --project $proj --state-root $state support rollback FB-…
    & $exe --project $proj --state-root $state support status FB-… --json
    ```

    Mong đợi: hook trỏ lại runtime cũ, `installed: false`, `rolled_back: true`. **Bị từ chối** (`refused`: runtime cũ đổi so với mốc, `.pyc` không phải bản biên dịch của nguồn, dữ liệu đổi sau diễn tập, không ở điểm an toàn) là kết quả đúng: giữ nguyên, gửi lý do làm feedback; **không** cài đè venv để vượt qua. Bộ kiểm diễn tập từ gói: V22 quay lui thành công, V31 quay lui bị từ chối. Bài thủ công đầy đủ của B chưa sẵn sàng (bài 6).

## 6. Gửi feedback

- Gửi: lệnh đã gõ, đầu ra đầy đủ, file bằng chứng của bài (mục 4), `feedback-alpha.zip` của bài 1 nếu liên quan, thư mục `export` của bài 3 (`manifest.json`, `files\…`) **sau khi bạn đọc**.
- Không gửi: `ANTHROPIC_API_KEY` hay token nào, `~/.claude`, `hook-projects.json` thật, sổ thật. Hồ sơ `support bundle` lọc bí mật theo mẫu, không phải bảo đảm — đọc trước khi gửi.
- Ghi kèm: version (`onecrew --version`), đường dẫn thư mục kết quả, giờ.

## 7. Bằng chứng của bản này

Bằng chứng dựng/kiểm của chính gói này: README của gói (hash, bước kiểm), `docs\BAO-CAO-2.4-2026-11-01.vi.md` (mục của bản `@@VERSION@@`), `docs\CHANGELOG.md`. Kết quả bài 1 trên máy bạn là bằng chứng thử của bạn (thư mục `thu muc ket qua`).

## 8. Giới hạn cần biết trước khi thử

- Những gì bộ kiểm chứng minh là đường đi, nhãn, receipt với CLI/model giả; không chứng minh model thật hiểu wiki hay thao tác người dùng đã đạt. Bài 4B và 8 (MT) cần provider thật và tài khoản của bạn; bài S2 thủ công (6, 5B) chưa có kịch bản đã kiểm.
- Xác thực API: chỉ advisor/reviewer provider `claude`; worker native (`engine step`), quota feed và luồng v1 vẫn chỉ subscription; `~/.claude/settings.json` của máy (`--setting-sources user`) có thể đổi cách CLI xác thực.
- Không dùng gói này để nâng runtime/sổ/project thật; nâng cấp thật là quyết định riêng sau nghiệm thu.
- Gói đã đóng băng: lỗi thật phát hiện khi thử sẽ được sửa ở bản sau, không sửa đè gói này.
