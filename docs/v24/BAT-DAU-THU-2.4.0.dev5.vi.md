# Bắt đầu thử OneCrew 2.4.0.dev5 (beta, thử cách ly)

Điểm vào duy nhất để thử bản beta 2.4. Đọc trang này là đủ để bắt đầu; hợp đồng và báo cáo kỹ thuật chỉ cần khi muốn đào sâu. Trang này và các script trợ giúp nằm **ngoài** gói đóng băng; gói không đổi.

| Mục | Giá trị |
|---|---|
| Gói | `D:\OneCrewRuns\v24\pkg\onecrew-2.4.0.dev5-beta` (đóng băng; `manifest.json`, `SHA256SUMS`) |
| Script trợ giúp (ngoài gói) | `D:\OneCrewRuns\v24\pkg\thu-tay-dev5\` — `chuan-bi.ps1`, `vao-moi-truong.ps1`, `don-dep.ps1` |
| Version · code | `2.4.0.dev5` · snapshot `387d3cb` (nhánh `claude/onecrew-2.4`; hồ sơ sau snapshot: `1d111e0`, `e8bc1c4` và commit của trang này) |
| Wheel · SHA256 | `wheel\onecrew-2.4.0.dev5-py3-none-any.whl` · `6ed8ab8a8568d271d4fd7d4b89f7bbb5ed98c8b387898f109c2f9b73ae409655` |
| Wheel quay về | `wheel\previous\onecrew-2.3.0.dev10-py3-none-any.whl` · `8ab065c3bc6d2863888314952e3743b031d44ea44c1e92cd740abba385a1b4f7` |
| Python | `C:\Users\NUC\AppData\Local\Programs\Python\Python313\python.exe` (không dùng `python` trần) |
| Trạng thái | beta, **chưa nghiệm thu, chưa phát hành**. Codex đã review phần thay đổi dev4→dev5 (mục 7). |

## 1. Bản này có gì mới và bạn kiểm được gì

Năm mốc của 2.4, chạy trên một bản sao project và sổ riêng:

| Mốc | Người dùng thấy gì | Thử ở bài |
|---|---|---|
| S1 báo lỗi một lần | `support report` cho một mã `FB-…`, gửi lại cùng khóa không tạo mã mới; `support bundle` ghi hồ sơ chẩn đoán ra máy bạn, không tải đi đâu | 3 |
| S2 bản vá OneCrew | báo cáo → bản vá → cài vào venv mới tại đích → kiểm lại lỗi gốc → chuyển hook ở điểm an toàn; quay lui có điều kiện. Sau dev5: bytecode `.pyc` bị thay sau phép kiểm **không** còn chạy ở bước đọc sổ/phân loại (finding Codex dev4) | 1 (tự động), 6 |
| A worker tự đọc nguồn | root khai `authority.read`, node khai `sources`; receipt ghi cây, kết quả, số lượt | 1 (tự động) |
| B working context | `knowledge.delivered` cho mỗi attempt; tri thức bị thu hồi khi node đang chạy thì candidate không công bố; `wiki consumers` cho biết node bị ảnh hưởng | 5 |
| C bước 0 và cách chạy node | `plan step0 show` nói đủ để làm chưa và vì sao; `engine measure` đo thời gian tới hành động có ích đầu tiên | 5 |

Hai thứ **không** có trong dev5 (mục 8): xác thực API cho advisor/reviewer (hotfix 2.3) và nâng runtime SDK.

## 2. Chuẩn bị môi trường cách ly (một lệnh)

`onecrew init` ghi registry hook vào `%LOCALAPPDATA%\OneCrew\hook-projects.json` của **tài khoản đang chạy** (chọn theo `LOCALAPPDATA`, không theo `--state-root`). Để bài thử không chạm registry thật, script dưới đây đổi `LOCALAPPDATA`, `APPDATA`, `TEMP`, `TMP` **chỉ trong cửa sổ PowerShell đang chạy** sang `<lab>\env\…` (không đổi biến cấp User/Machine), tạo venv thử, bản sao project độc lập, `init`, `doctor`, rồi kiểm: registry thử được tạo trong `<lab>\env`, registry thật không đổi hash, hook của bản sao trỏ vào exe thử.

```powershell
powershell -ExecutionPolicy Bypass -File "D:\OneCrewRuns\v24\pkg\thu-tay-dev5\chuan-bi.ps1"
```

- Mặc định lab = `D:\OneCrewRuns\v24 thu tay dev5` (phải chưa tồn tại; muốn tên khác: `-Lab "<thư mục mới>"`), project mẫu Git một file do script tạo. Muốn thử trên bản sao project của bạn: thêm `-Source "<repo Git>"` — script `git clone --no-hardlinks`, bỏ remote, xóa `.onecrew` và `.claude\settings.local.json` nếu chúng được commit (bản sao không dùng lại config/hook/remote của bản gốc).
- **ĐẠT** = dòng `DAT: moi truong thu san sang tai <lab> (onecrew 2.4.0.dev5)`, mã thoát 0. `KHONG DAT:` + mã 1 = một bước hỏng (dừng ngay tại đó, không chạy tiếp); mã 2 = từ chối chạy (lab đã có, `-Source` không phải repo Git).
- `init` hỏi `claude auth status` của CLI thật (chỉ đọc, không đăng nhập) để in dòng "Claude CLI: found … logged in"; không gọi model.
- **Mọi lệnh thử sau đó gõ trong cùng cửa sổ.** Mở cửa sổ mới: dot-source để vào lại đúng môi trường (đặt sẵn `$py $pkg $lab $venv $proj $state $exe`):

```powershell
. "D:\OneCrewRuns\v24\pkg\thu-tay-dev5\vao-moi-truong.ps1" -Lab "D:\OneCrewRuns\v24 thu tay dev5"
```

Dòng in `LOCALAPPDATA=<lab>\env\LocalAppData` xác nhận cửa sổ đang ở môi trường thử; thiếu dòng đó là đang ở registry thật — đừng gõ `init`.

## 3. Kiểm gói (tự động, CLI giả, không gọi model)

Lệnh duy nhất, chạy từ terminal của bạn (không chạy trong phiên AI):

```powershell
powershell -ExecutionPolicy Bypass -File "D:\OneCrewRuns\v24\pkg\onecrew-2.4.0.dev5-beta\verify\thu-goi.ps1"
```

- Kết quả ghi vào một thư mục mới `D:\OneCrewRuns\v24 thu cua anh 2.4.0.dev5 <yyyyMMdd-HHmmss>`; đường dẫn chính xác in ở dòng `thu muc ket qua:` ngay đầu và lặp lại ở dòng cuối. Muốn đặt tên: `-Work "<thư mục trống>"`.
- **ĐẠT** = dòng cuối bắt đầu bằng `DAT: goi 2.4.0.dev5 ... 31/31 buoc ...` và mã thoát 0. **KHÔNG ĐẠT** = dòng `KHONG DAT:` và mã khác 0; lý do ở các dòng `- ` ngay trên; mã 2 là từ chối chạy (thư mục kết quả đã có file, thiếu file) — chưa chạy gì.
- Bằng chứng: `<kết quả>\verify\verify-report.json` (31 bước, `result: pass`), `<kết quả>\task dau tien\first-task-drill-log.json`, `<kết quả>\alpha\alpha-flow-log.json` và `feedback-alpha.zip`.
- Mất khoảng 25 phút. Chỉ cần chạy **một lần** cho bản này; **bạn đã chạy đạt** (mục 7); không chạy lại sau mỗi bài thử.

## 4. Các bài thử

Ký hiệu: **[TĐ]** tự động, CLI/model giả · **[TT]** bạn thao tác, không cần model · **[MT]** cần provider thật, **chưa thực hiện** trong lượt bàn giao. Mọi lệnh [TT] gõ trong cửa sổ đã vào môi trường thử (mục 2); `$exe`, `$proj`, `$state` đã đặt sẵn.

| # | Bài | Loại | Thao tác | Kết quả mong đợi | Bằng chứng cần xem |
|---|---|---|---|---|---|
| 1 | Kiểm gói | TĐ | mục 3 | `DAT … 31/31` | `verify-report.json` |
| 2 | Môi trường thử + `init` bản sao | TT (script) | mục 2 | `DAT: moi truong thu san sang`; `doctor` 0 FAIL; registry thật không đổi | `<lab>\env\LocalAppData\OneCrew\hook-projects.json` có mục của bản sao; `<lab>\project\.onecrew\config.json` |
| 3 | S1 báo lỗi một lần | TT | `& $exe --project $proj --state-root $state support report --text "Bước kiểm M1 báo sai dù file đúng" --key k1 --json` (hai lần); `support show FB-… --json`; `support bundle FB-… --out "$lab\bundle"` | cùng một mã `FB-…` cả hai lần; `status: reported`, tái hiện `unknown`; `bundle\manifest.json` có `uploaded: false`; `support confirm` bị từ chối trong phiên AI | mã `FB-…`, `bundle\manifest.json`, `feedback.json` đã lọc bí mật |
| 4 | Task đầu tiên | TĐ phần A · MT phần B | `examples\first-task\README.vi.md` (A: `claude` giả trên đầu PATH của **một** cửa sổ; đã chạy tự động trong bài 1) · B: model thật, chưa thực hiện | A: node C chạy, receipt, check đạt; B: xem README §6B | `first-task-drill-log.json` (A) |
| 5 | Xem bước 0, đo, consumer trên sổ diễn tập | TT | trên `<kết quả bài 1>\task dau tien\task dau tien thu`: `onecrew.exe` trong `venv\Scripts`, `--project "project mau" --state-root "so thu"`: `plan show P1`, `plan step0 show P1`, `engine measure P1`, `wiki consumers --plan P1 --json`, `support list --json` | thẻ bước 0 in "đủ để làm: chưa" kèm lý do (plan mẫu không khai bước 0); `measure` in `time_to_first_useful_action_seconds`; `consumers: []`; `support list` `[]` | đầu ra JSON; không lệnh nào ghi gì ngoài sổ thử |
| 6 | S2 chuỗi vá | TĐ (V20–V22, V27–V31) · TT **chưa sẵn sàng** | tự động đã chạy trong bài 1; bài thủ công cần `support target add` (lệnh của chủ), plan sửa đã duyệt có `support_install:<đích>`, wheel vá: chưa có kịch bản thủ công đã kiểm cho người dùng | V21 `blocked_by_authority` khi thiếu quyền, `installed`/`verified_at_target` theo hook đang chạy; V22 `rollback` → `rolled_back`; V29/V31 quay lui từ chối khi `.pyc` runtime cũ bị thay, không chạy chương trình nào của nó | `verify-report.json` các bước đó |
| 7 | A nguồn, B thu hồi, C chế độ chạy | TĐ (V23–V26) | đã chạy trong bài 1 | V23 ngoài phạm vi bị từ chối; V24/V26 node bị giữ `input_changed`, không gọi model; V25 trần điều tra | `verify-report.json` các bước đó |

Khi một bài sai: ghi lệnh đã gõ, đầu ra, và kèm file bằng chứng ở cột cuối (mục 6). Không cần chạy lại bài 1.

## 5. Kết thúc, tiếp tục, quay về (chỉ trong môi trường cách ly)

- **Tiếp tục phiên thử:** cửa sổ mới → dot-source `vao-moi-truong.ps1 -Lab "<lab>"` (mục 2); sổ thử ở `<lab>\so` giữ nguyên.
- **Kết thúc:** `powershell -ExecutionPolicy Bypass -File "D:\OneCrewRuns\v24\pkg\thu-tay-dev5\don-dep.ps1" -Lab "<lab>"` xóa cả lab (venv, bản sao, sổ thử, registry thử) và in registry thật không đổi. Không sửa tay registry thật. Thư mục kết quả bài 1 giữ hay xóa tùy bạn.
- **Quay về 2.3.0.dev10 — hai trường hợp khác nhau, không dùng chung một lệnh:**
  - **A. Chỉ cài wheel để thử (bài 2–5, chưa chạy `support install`):** hook của bản sao vẫn trỏ vào `$venv`; cài đè dev10 vào chính venv đó là đủ. Đã kiểm: dev10 đọc được sổ có bản ghi S1 (`test_v24_s1_oldreaders`); **chưa** diễn tập dev10 đọc sổ có bản ghi S2.

    ```powershell
    & "$venv\Scripts\python.exe" -I -m pip install --no-index --no-build-isolation --force-reinstall "$pkg\wheel\previous\onecrew-2.3.0.dev10-py3-none-any.whl"; & $exe --version
    ```

    Lên lại dev5: cùng lệnh với `$pkg\wheel\onecrew-2.4.0.dev5-py3-none-any.whl`.
  - **B. Đã chuyển hook bằng S2 (`support install … --target <đích>` ra `switched`):** hook của bản sao giờ trỏ vào **venv mới** cạnh venv cũ, không còn là `$venv`; cài đè `$venv` không chuyển hook về, và nếu `$venv` là runtime cũ S2 đã ghi mốc thì đổi nội dung nó làm quay lui chính thức **bị từ chối** (OneCrew so runtime cũ với mốc lúc cài trước khi quay lui). Đường duy nhất: `support rollback` (lệnh của chủ, terminal riêng, bị từ chối trong phiên AI), giữ nguyên runtime cũ:

    ```powershell
    Get-Content "$proj\.claude\settings.local.json"            # exe nào đang được hook gọi, trước và sau
    & $exe --project $proj --state-root $state support status FB-… --json
    & $exe --project $proj --state-root $state support rollback FB-…
    & $exe --project $proj --state-root $state support status FB-… --json
    ```

    Mong đợi: sau rollback hook trỏ lại runtime cũ, `installed: false`, `rolled_back: true`. **Bị từ chối** (`refused`, lý do: runtime cũ đổi so với mốc, `.pyc` không phải bản biên dịch của nguồn, dữ liệu đổi sau diễn tập, không ở điểm an toàn) là kết quả đúng của bảo vệ: giữ nguyên, gửi lý do làm feedback; **không** cài đè venv để vượt qua. Đã diễn tập từ gói (không phải thao tác tay): V22 quay lui thành công (`rolled_back`), V31 quay lui bị từ chối khi `.pyc` runtime cũ bị thay (mục 7). Bài thủ công đầy đủ của trường hợp B chưa sẵn sàng (bài 6).

## 6. Gửi feedback

- Gửi: lệnh đã gõ, đầu ra đầy đủ, file bằng chứng của bài (mục 4), `feedback-alpha.zip` của bài 1 nếu liên quan, và `bundle\manifest.json` + `feedback.json` của bài 3 **sau khi bạn đọc**.
- Không gửi: `ANTHROPIC_API_KEY` hay token nào, `~/.claude`, `hook-projects.json` thật, sổ thật. Hồ sơ `support bundle` lọc bí mật theo mẫu, không phải bảo đảm — đọc trước khi gửi.
- Ghi kèm: version (`onecrew --version`), đường dẫn thư mục kết quả, giờ.

## 7. Bằng chứng đã có cho bản này (không cần chạy lại)

| Nguồn | Kết quả |
|---|---|
| **Bài 1 do bạn chạy** 02/11 13:20 (`D:\OneCrewRuns\v24 thu cua anh 2.4.0.dev5 20261102-132042`) | `DAT`: kiểm gói 31/31; task đầu tiên 23/23 bước bắt buộc (+2 bước thông tin), `owner_step_mode: real`, `in_ai_session: false`, trên sổ thử; alpha 5/5 với worker giả; `package_unchanged: true`. "Owner step real" nghĩa là bước duyệt plan do terminal thật của bạn làm trên sổ thử — không phải bằng chứng provider thật hay nghiệm thu |
| Kiểm gói lúc dựng, 02/11 07:48–08:11 (`D:\OneCrewRuns\v24\logs\pkg-verify-2.4.0.dev5.txt`, `pkg-wrapper-2.4.0.dev5.txt`) | 31/31; `DAT`; chạy lại cùng thư mục bị từ chối; `SHA256SUMS` 62/62 |
| Hồi quy `tests/test_v24_*` trên `387d3cb` (`reg-v24-all-387d3cb.txt`) | 265/265, 0 skip |
| Gate 2.2 trên `387d3cb` (`gate-snapshot-387d3cb.txt`) | 286/286 check, 2.107/2.107 test; `refused` chỉ vì 23 khoảng trống nghiệm thu đã biết, trùng dev4 |
| Probe của Codex trên wheel dev5 (`D:\OneCrewRuns\v24\codex probe dev5`) | bytecode bị thay không chạy ở identity, bước đọc sổ, bước phân loại |
| Diễn tập mục 2 và 5 của trang này, 02/11 14:06 (`guide-drill-chuan-bi.txt`) | `chuan-bi.ps1` → `DAT` trên lab mới: registry thử tạo trong `<lab>\env`, registry thật giữ hash, hook bản sao trỏ exe thử; cửa sổ mới dot-source `vao-moi-truong.ps1` → `doctor` 0 FAIL, `support list` `[]`; `don-dep.ps1` → `DAT`, registry thật giữ hash |
| Quay lui từ gói | Thành công: bước V22 trong **bài 1 của bạn** (kế thừa; `support rollback` → `rolled_back`, `installed: false`). V22 chỉ chạy được sau V21 trong cùng lượt, nên không chạy riêng được (lượt `--only V22` 02/11 14:05 bị từ chối đúng lý do, không tính). Từ chối: bước V31 chạy riêng 02/11 14:06 (`pkg-only-V31-s2-rollback-bytecode-dev5-guide.txt`, `partial-pass 4/4`): `.pyc` runtime cũ bị thay sau phép kiểm → quay lui từ chối trước khi chạy chương trình nào của nó |
| **Review Codex trên dev5** (02/11) | Codex đã kiểm: gói 62/62 hash; gate 286/286, 23 mục `refused` giống dev4; nội dung từng file trong wheel gate và wheel bàn giao giống nhau; log hồi quy 265 OK, kiểm gói 31/31; ba phản chứng độc lập trên wheel dev5 chặn lỗi bytecode/rollback cũ; snapshot code không đổi sau kiểm, HEAD sau snapshot chỉ cập nhật hồ sơ. Kết luận của Codex: P1 rollback dev4 đã khép trong các kịch bản được kiểm; chưa phát hiện blocker mới trong phần thay đổi được review; dev5 có thể bàn giao để thử cách ly. **Không phải** nghiệm thu toàn bộ sản phẩm, kiểm provider thật hay chứng nhận an toàn tuyệt đối. Review hướng dẫn thử (02/11): 2 P2 (bài thủ công chưa cách ly registry; lệnh quay về không phân biệt cài lại venv với quay lui sau S2) và 1 P3 (tên thư mục kết quả) — đã sửa ở bản này |

Chi tiết kỹ thuật: `docs\BAO-CAO-2.4-2026-11-01.vi.md` (§10 cho dev5), giới hạn từng mốc: `docs\limits-final.md` trong gói.

## 8. Giới hạn cần biết trước khi thử

- **Chưa có xác thực API cho advisor/reviewer.** Dev5 gọi Claude CLI của advisor/reviewer bằng đăng nhập subscription của CLI; `plan advise --auth api` **chưa được hỗ trợ** trong dev5 (tùy chọn `--auth` chưa tồn tại). Trên máy mà tổ chức đã tắt subscription, lời gọi advisor/reviewer provider `claude` ra `inconclusive`; các bài trên không cần model nên không bị ảnh hưởng.
- **Không dùng dev5 để nâng runtime SDK** đang dùng 2.3 dev11 và API; runtime đó giữ nguyên.
- **Hotfix 2.3** (xác thực API) được tích hợp bằng task riêng sau khi các finding của hotfix được khép và kiểm chứng; không cherry-pick riêng `a3d6a15` trong lượt này.
- Những gì bộ kiểm chứng minh là đường đi, nhãn, receipt với CLI/model giả; không chứng minh model thật hiểu wiki hay thao tác người dùng đã đạt. Phần cần provider thật (bài 4B) chưa chạy; bài S2 thủ công (6, 5B) chưa có kịch bản đã kiểm.
- Gói đã đóng băng: lỗi thật phát hiện khi thử sẽ được sửa ở bản sau, không sửa đè gói này.
