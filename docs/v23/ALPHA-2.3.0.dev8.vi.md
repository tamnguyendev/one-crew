# OneCrew 2.3.0.dev8 — bản alpha

Người viết: Claude (Opus 5.5), đầu mối 2.3, 30/10/2026. Làm theo chỉ thị của người dùng 30/10 ~11:30: giao alpha dùng được sớm, rồi hoàn thiện beta.

**Đây là hồ sơ bàn giao alpha, viết riêng.** Hồ sơ này:
- không sửa roadmap chung (do Codex quản lý);
- không đổi điều kiện phát hành beta/stable của hợp đồng 2.3 (`HOP-DONG-2.3.vi.md` §10.5);
- không phải nghiệm thu, và không ghi thay nghiệm thu của chủ sở hữu.

Alpha chứng minh luồng wiki chạy từ gói, trên project mẫu và sổ riêng. Alpha **không** chứng minh:
- toàn bộ 2.3;
- việc dùng với mọi provider;
- việc dùng với sổ thật.

Bản trong `docs/` của gói là bản lúc dựng gói. Các mục §1 và §6 chỉ có trong bản ở checkout (`D:\TamNT\Workspace\11.OneCrew\wf-v23\docs\v23\ALPHA-2.3.0.dev8.vi.md`), vì chúng được ghi sau khi kiểm.

## 1. Bản nào, tải và cài ở đâu

**Bản alpha `2.3.0.dev8` (prerelease), không phải bản ổn định `2.3.0`.** Phát hành 13:54 30/10, theo cách đã làm với `v2.1.0`:
- **Tag** `v2.3.0.dev8` (annotated) trên snapshot `fab7389187cd909c768fb65239b098d0571f7722`, đã push lên `origin` `git@github.com:tamnguyendev/one-crew.git` (repo private, đã kiểm `isPrivate: true`). Đọc lại từ `origin`: tag trỏ tới `fab7389187cd`.
- **Nhánh** `claude/onecrew-2.3` đã push lên `origin` (nhánh mới, không force). Lần đầu đưa lên `origin` 257 commit. Trước khi push đã quét các dòng thêm vào: không dòng nào giống khóa bí mật.
- **Gói cài:** `D:\OneCrewRuns\v23\pkg\onecrew-2.3.0.dev8-alpha`. Lệnh thử một lệnh: `powershell -ExecutionPolicy Bypass -File "D:\OneCrewRuns\v23\pkg\onecrew-2.3.0.dev8-alpha\verify\thu-goi.ps1"`. Cài tay: `pip install --no-index "D:\OneCrewRuns\v23\pkg\onecrew-2.3.0.dev8-alpha\wheel\onecrew-2.3.0.dev8-py3-none-any.whl"` vào một venv mới (README của gói §2). Wheel SHA256 `878e87442f246246c7f315bb4d4c1fac175041eff18f15b4bfe38e4c93d1bf57`.
- **Không làm:** không cấu hình registry, PyPI hay GitHub Release nào, nên không tạo; không đổi quyền repo; không ghi đè tag hay artifact nào.

## 2. Bạn thử gì (5 bước)

1. Mở **PowerShell của chính bạn**, không mở trong phiên AI. Chạy một lệnh:
   `powershell -ExecutionPolicy Bypass -File "<gói>\verify\thu-goi.ps1"`
   Lệnh tự tạo thư mục kết quả mới, venv riêng, project mẫu và sổ tạm. Nó không đụng sổ thật, hook đang dùng, PATH hay cấu hình provider.
2. Đọc dòng cuối. Đạt khi lệnh in `DAT: goi 2.3.0.dev8 qua bo kiem 16/16 buoc, task dau tien tu goi …, luong alpha 5/5 chang …` và thoát mã 0.
3. Mở `<thư mục kết quả>\alpha\logs\` để xem lệnh thật của từng chặng, đầu ra nằm ngay trong từng file. Ba file đáng xem nhất:
   - `wiki-show-P1-C-text`: node C nhận quy tắc wiki là sự thật bắt buộc.
   - `wiki-history-1`: kết quả đã kiểm của C thành ghi nhận `verified`.
   - `wiki-show-P2-D-text`: root mới P2 nhận lại đúng ghi nhận đó.
4. Nếu muốn làm tay: theo `examples/first-task/README.vi.md` trong gói, trên một **bản sao** project và một state root mới.
5. Gửi feedback: file `<thư mục kết quả>\alpha\feedback-alpha.zip` kèm vài dòng bạn thấy gì. File zip gồm log từng lệnh, các trang wiki và kết quả từng chặng; không có biến môi trường, không có file của bạn.

## 3. Kết quả mong đợi

| Chặng | Bạn sẽ thấy |
|---|---|
| S1 init và wiki | `init` tạo `docs/wiki` (`README.md`, `project.md`, `lessons.md`). Wiki mới: 3 trang, 0 mục, 0 vấn đề. `init` lần hai không đổi byte nào. Sau khi thêm `rules.md`, wiki có các mục `a-value` và `no-two-lines`, 0 vấn đề |
| S2 task nhận tri thức trong quyền | Plan P1 được duyệt. Node C (đọc `a.txt`, `b.txt`, `spec.txt`; ghi `a.txt`) nhận `a-value` là **sự thật bắt buộc** |
| S3 kết quả đã kiểm thành tri thức | Worker của C khai một phát hiện có nguồn `spec.txt`, gắn với check M1. Check M1 chạy thật trên ứng viên của C và đạt. `wiki history` có ghi nhận `verified`, thấy được ở cấp project, kèm bằng chứng (receipt của lượt chạy và của check). Lời khai lúc đầu là quan sát riêng của root, đã bị ghi nhận này thay thế. Kết quả của P1 được giao vào project mẫu |
| S4 root mới dùng lại | Node D của plan mới P2 nhận ghi nhận đó là **sự thật áp dụng được**. Quy tắc wiki cũ (kiểm trên `a.txt` trước khi đổi) chỉ còn là đầu mối cần kiểm lại. Worker của D (mặc định của nó sai) dùng ghi nhận, và check của D đạt. Node E của P3 chỉ đọc `c.txt`, nên không nhận ghi nhận lẫn quy tắc |
| S5 guard hard link | Trang wiki là hard link tới file ngoài project: không được đọc, được nêu tên kèm lý do. File trong phạm vi node thành hard link sau khi duyệt: node không chạy, lệnh nêu lý do "hard link", và không có gì của file đó vào sổ |

`hook-projects.json` thật và `.claude\settings.json` thật chỉ được đọc để đối chiếu SHA256 trước và sau; dòng kết quả ghi "khong doi".

## 4. Giới hạn và cách gửi feedback

- **Worker là `claude` giả** (test double, không có model, không gọi provider). Nó chứng minh đường đi, nhãn, quyền và guard. Nó **không** chứng minh model thật hiểu hay dùng đúng tri thức. Model thật của task đầu tiên (phần B trong `examples/first-task/README.vi.md` §6B) chưa chạy ở bản này; đó là bước của bạn, qua subscription.
- **Bước duyệt plan:** chạy trong terminal của bạn thì là lệnh thật `onecrew owner approve` (`owner_step=real`). Chạy trong phiên AI thì bước này được thay bằng fixture có nhãn `fixture` trên sổ tạm.
- **Chưa kiểm ở bản này:**
  - gate 2.2 đầy đủ (286 check) trên snapshot alpha;
  - Codex review lại;
  - dùng với sổ thật hoặc project thật;
  - provider khác Claude Code CLI 2.1.286;
  - pilot.
- Các giới hạn đã ghi của 2.3 vẫn giữ nguyên, trừ các mục alpha đã khép (§5): `README.md` của gói §4, `docs/v23/tools/limits-final.md`.
- **Feedback:** gửi `feedback-alpha.zip` cùng câu bạn mong và câu bạn thấy. Gặp `KHONG DAT` thì gửi luôn cả dòng `- …` in ngay trên nó.

## 5. Danh sách blocker duy nhất

Phân loại theo tác động và bằng chứng, không theo nhãn P1/P2/P3:
- **A:** chặn alpha.
- **B:** không chặn alpha nhưng phải xử lý trước beta theo hợp đồng.
- **C:** cải tiến làm sau.

Mỗi finding được đối chiếu với code và test hiện tại, không mặc định là còn mở hay đã khép.

| # | Vấn đề | Tác động, bằng chứng | Loại | Trạng thái |
|---|---|---|---|---|
| A1 | **AL-01:** ảnh chụp phạm vi node (`Snapshots.capture`, nguồn của engine, file của worker) đọc cả file có hard link | Giao dữ liệu ngoài quyền cho provider: file ngoài project, hay `.env` mà quy tắc snapshot giữ khỏi worker, đi vào snapshot dưới tên thường. Trên gói `2.3.0.dev7`, nội dung file bí mật nằm trong `snapshots/blobs` và trong `attempts/…/stdin.txt` (prompt gửi worker); log `D:\OneCrewRuns\v23\alpha\try10 dev7\alpha-flow-log.json` | A | **khép:** `6d504c0`. Ca `tests/test_v23_alpha_links.py` (5 ca a01–a05) đỏ trên `01c5831`, xanh sau sửa. Chặng S5 trên gói alpha (§6) |
| A2 | **AL-02:** trình đọc wiki theo symlink, đi qua junction và đọc trang có hard link | Giao dữ liệu ngoài quyền: nội dung của file nơi khác thành tri thức giao cho node | A | **khép:** `6d504c0`. Các ca w01–w05 đỏ trên `01c5831`, xanh sau sửa. Chặng S5 trên gói alpha |
| A3 | **FX-R06:** định danh thư mục không Git chép file có hard link (tới `.env` ở nơi khác) vào sổ | Dữ liệu ngoài quyền vào sổ | A | **khép bởi AL-01:** test `x04` từ expected failure thành test hồi quy |
| A4 | Số "đạt" trong báo cáo gộp cả test bỏ qua và expected failure | Làm sai kết quả kiểm được báo, ví dụ "504 test đạt" trong khi chỉ 492 đạt | A | **khép:** hợp đồng §6 sửa hai dòng; từ bản này luôn ghi chạy / đạt / bỏ qua / lỗi đã biết riêng (§6). Bộ kiểm của gói đếm bước, không có bỏ qua |
| A5 | Test hay probe ghi vào sổ đăng ký hook thật (hai lần 29/10, đã khôi phục từng byte) | Làm đổi môi trường thật | A | **khép cho luồng alpha bằng cô lập đã kiểm:** `alpha_flow.py` và `thu-goi.ps1` chạy mọi lệnh với `LOCALAPPDATA`/`APPDATA`/`TEMP` riêng và đối chiếu SHA256 hai file thật trước và sau; bộ kiểm của gói cũng cô lập như vậy. Phần test repo: B4 |
| A7 | Gate cũ hỏng và race Git | Race `.onecrew` của index tạm làm `R03/check.t41_gaps` hỏng trên `c6d8477` | A | **khép:** `01c5831`, test race đỏ rồi xanh, `t41_gaps` 6/6. Gate trên `6cbcaa9` dừng có chủ đích ở 141/286 (không check nào hỏng), ghi là đã hủy (`CANCELLED.json`); không dùng làm chứng nhận cho snapshot alpha |
| B1 | Gate 2.2 đầy đủ trên snapshot cuối (286 check, kit-guard) | Điều kiện §10.5 | B | làm cho beta |
| B2 | Các lệnh chỉ xem trạng thái (`plan show`, báo cáo) vẫn băm cây làm việc. Git có thể ghi blob của file sau hard link vào object store của repo | Nội dung đó không đi ra ngoài repo, không adapter nào đọc. Vẫn lệch với quy tắc "file có hard link không bao giờ được đọc" | B | sửa trước beta |
| B3 | Gate đếm expected failure là đạt (`wfkit/gate.parse_unittest`) | Hiện không module nào của gate có expected failure. `wfkit` thuộc kit đã khóa | B | xét trước beta (kit-guard, cơ chế ngoại lệ) |
| B4 | Test 2.2 đã khóa (`test_g2_install`, `test_v2_trust_fixes`) ghi vào sổ đăng ký hook thật khi chạy trần | Chỉ hại khi chạy tay không cô lập. Runner của lượt này luôn cô lập | B | cần ngoại lệ U1 hoặc guard phía 2.3, chọn trước beta |
| B5 | `tests.test_v2_reviewer.RealCliTests` tự gọi Claude thật khi có `claude.exe` (một lần ~0,07 USD qua subscription, 29/10) | Không nằm trên luồng alpha: gate không chạy module này (receipt gate `b3ecc57`, `6cbcaa9` không có), gói không chứa nó, hồi quy lượt này bỏ nó | B | test đã khóa: cần ngoại lệ U1 của chủ sở hữu hoặc cờ bật rõ ràng |
| B6 | Model thật cho task đầu tiên và luồng alpha; Codex review lại | Chưa có bằng chứng model thật | B | bước của chủ sở hữu |
| B7 | 23 khoảng trống nghiệm thu, pilot, provider của 2.2 | Điều kiện stable | B | giữ nguyên |
| C1 | Verifier: FX-R03, FX-R08, FX-R07 (junction đã ghim); tên 8.3; quy tắc nguồn viết trần; kiểm `ids` khi chưa có id; clean filter trong `.git/config` | Báo sai ồn hoặc từ chối an toàn, không bao giờ đạt sai | C | giới hạn đã ghi |
| C2 | Init và wiki: khoảng rất ngắn giữa lần xét đường dẫn cuối và lúc tạo file vẫn mở với một junction đổi vào đúng lúc đó | Cần một tiến trình chạy đua đúng lúc | C | giới hạn đã ghi |
| C3 | Import công cụ của gói làm Python ghi `__pycache__` vào gói (công cụ kiểm của tôi, `pair_v15`) | Gói thêm một file ngoài `SHA256SUMS` | C | công cụ chạy với `-B`; `alpha_flow` đối chiếu gói trước và sau |

## 6. Điều kiện giao alpha, kiểm trên artifact cuối

Kiểm trên gói `D:\OneCrewRuns\v23\pkg\onecrew-2.3.0.dev8-alpha` (dựng 2026-10-30 13:32:17 từ snapshot `fab7389`), từng bước một, không chạy chồng. Đếm test: chạy, đạt, bỏ qua, lỗi đã biết, hỏng ghi riêng.

| Điều kiện alpha | Kết quả | Bằng chứng |
|---|---|---|
| Danh tính version, commit, wheel, manifest khớp | đạt: `2.3.0.dev8`, commit `fab7389187cd`, `stage: alpha`, wheel `onecrew-2.3.0.dev8-py3-none-any.whl` SHA256 `878e87442f246246c7f315bb4d4c1fac175041eff18f15b4bfe38e4c93d1bf57` khớp file; `claims` đều `false`; `SHA256SUMS` khớp, không có `__pycache__` sau mọi bước | `manifest.json`; `D:\OneCrewRuns\v23\alpha\logs\package-intact-dev8.txt` |
| Cài sạch, entrypoint chạy | đạt: bộ kiểm 16/16 (V2 venv mới, V3 nguồn module từ `site-packages`); README 9/9 (venv có dấu cách, `--help`, quay về 2.2, lên lại) | `D:\OneCrewRuns\v23\alpha\logs\verify-dev8-fab7389.txt`, `D:\OneCrewRuns\v23\alpha\logs\readme-drill-dev8.txt` |
| Luồng wiki đã công bố chạy từ wheel, ngoài checkout | đạt: script thử một lệnh `DAT`, thoát 0 (13:39–13:43); trong đó luồng alpha 5/5 chặng, bước duyệt `fixture`; task đầu tiên 25/25; chạy lại vào cùng thư mục bị từ chối, thoát 2 | `D:\OneCrewRuns\v23\alpha\logs\wrapper-dev8.txt`; `D:\OneCrewRuns\v23 thu script dev8 claude\alpha` |
| Phản chứng của các blocker | đạt: cùng `alpha_flow.py` của gói alpha trên gói `2.3.0.dev7`: S5 hỏng (5 điều kiện; file bí mật vào `snapshots/…`, `attempts/…`); trên gói alpha: 5/5. V15 qua CLI cài: dev6 11 lỗi → dev8 0; ca Codex dev5 qua CLI cài 0 lỗi | `D:\OneCrewRuns\v23\alpha\pair alpha dev7`, `D:\OneCrewRuns\v23\alpha\pair alpha dev8`, `D:\OneCrewRuns\v23\alpha\pair v15 dev6`, `D:\OneCrewRuns\v23\alpha\pair v15 dev8` |
| Cách ly project, sổ, config, provider | đạt: mọi lệnh với `TEMP`/`LOCALAPPDATA`/`APPDATA` riêng, project mẫu và sổ tạm; `claude` trên PATH là bản giả của venv (kiểm trước khi chạy node); `hook-projects.json` thật và `.claude\settings.json` thật không đổi (SHA256 trước và sau); sổ dev5 → dev8 → 2.2 dùng được | `alpha-flow-log.json` (`real_files`); `D:\OneCrewRuns\v23\alpha\logs\compat-dev5-ledger-dev8-package.txt` |
| Hồi quy trên snapshot `fab7389` | 2.3: 522 chạy, 511 đạt, 9 bỏ qua, 2 lỗi đã biết (expected failure). 2.2 (11 module ngoài gate và 13 module dùng kho snapshot nhiều nhất): 417 chạy, 414 đạt, 3 hỏng, gồm: 1 test ghim version `2.2.0.dev3` có từ trước; 1 lỗi môi trường, `test_owned…survives_launcher_and_cancel` không tạo được process tách khỏi Job object trong phiên này (`Access is denied`, hỏng y hệt trên `6cbcaa9`), không tính là đạt; 1 lỗi tên module do file danh sách của tôi ghép hai tên, hai module đó chạy riêng: 51 chạy, 51 đạt | `D:\OneCrewRuns\v23\dev7\logs\int-v23-fab7389.txt`, `D:\OneCrewRuns\v23\dev7\logs\int-22-fab7389.txt`, `D:\OneCrewRuns\v23\dev7\logs\int-22b-fab7389.txt`, `D:\OneCrewRuns\v23\alpha\logs\owned-6cbcaa9.txt` |
| Giới hạn và phần chưa kiểm được ghi rõ | đạt: §4, §5 (B, C), `README.md` của gói §4 | — |
| Beta 2.2 và việc đang chạy | không đổi: gói `wf-handover-34eb7c4-hs2` 687/687 dòng `SHA256SUMS` khớp, 0 file sửa sau 28/10 13:30; `hook-projects.json` thật SHA256 `884335df…` như 29/10 17:05. Không dừng tiến trình của phiên khác (chỉ dừng cây process gate của chính lượt này) | `D:\OneCrewRuns\v23\dev4\beta-check\after-alpha.json` |

**Không phải:** gate 2.2 đầy đủ trên snapshot này (B1), model thật (B6), nghiệm thu.

**Ghi thêm sau beta (30/10 19:50):** có 4 module 2.2 chạm vùng sửa mà gate không chạy, là `test_v2_report`, `test_wf_compat_scan`, `test_wf_packaging` và `test_wf_plan_names`. Hồi quy của alpha không chạy 4 module này. Chúng đã chạy riêng trên snapshot beta `d35b810` (có toàn bộ code alpha): 49 chạy, 49 đạt (`D:\OneCrewRuns\v23\dev7\logs\int-22c-d35b810.txt`). Không cần thu hồi alpha.

## 7. Phần còn lại để lên beta

B1–B7 ở trên, theo thứ tự. Phạm vi A1/A2/B của 2.3 giữ nguyên. Bản beta sẽ:
- dựng từ một snapshot mới có các sửa của B2–B4 (cần quyết định của chủ sở hữu cho các test đã khóa B4, B5);
- chạy gate 2.2 đầy đủ trên đúng snapshot đó;
- kiểm lại từ gói, gồm luồng alpha.
