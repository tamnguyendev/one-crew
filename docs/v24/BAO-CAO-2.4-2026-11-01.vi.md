# OneCrew 2.4 — báo cáo bàn giao 01/11/2026

Người viết: Claude (đầu mối 2.4), 01/11/2026, theo chỉ thị người dùng ngày 01/11 ~02:10 ("Tiếp quản và hoàn thành toàn bộ feature đã chốt của OneCrew 2.4 theo roadmap chung: 2.4-S1, S2, A, B, C"). Phạm vi, thiết kế và truy vết đầy đủ: [hợp đồng 2.4](HOP-DONG-2.4.vi.md) §3–§8. Đây là **tự kiểm của tác giả và review của agent độc lập**: Codex đã review dev2 vòng 1 (bốn finding, đã sửa ở dev3, xem §8); dev3 chưa được Codex review lại, chưa có nghiệm thu của chủ sở hữu, chưa phát hành. Mọi kiểm dùng `claude` giả và sổ tạm, không có lượt model thật.

**Tóm tắt (quyết định trước):**
- **Mới nhất (02/11): dev2 → dev3 sau review Codex vòng 1.** Bốn finding đã sửa trên nhánh, có phản chứng đỏ trước và xanh sau, snapshot `2.4.0.dev3` = `5a7a8ef`: F1 (P1) runtime bị sửa file vẫn được nhận là đúng artifact; F2 (P1) rollback lấy mốc dữ liệu sau khi diễn tập; F3 (P2) chuỗi phụ thuộc dài công bố tri thức đã thu hồi; F4 (P3) báo cáo/giới hạn sai hoặc cũ. Review độc lập: S2 bốn lượt (kết quả cuối P1 0/P2 1/P3 4, P2 đã sửa), B hai lượt (cuối P1 0/P2 0/P3 4). Hồi quy tích hợp 2.4 trên `fe495c1` (trước vòng 4–5 của S2): 238/238, 0 skip. Gói dev3 và gate trên `5a7a8ef`: chưa có, xem §8.5–§8.6. Các gạch đầu dòng dưới đây và §1–§7 mô tả dev2 (`61862e6`).
- Cả năm mốc đã có code và test trên một cây (gộp `bde505b`; snapshot cuối `61862e6`, version `2.4.0.dev2`); mỗi mốc có review độc lập, ca review được viết thành test đỏ trước khi sửa.
- Gói cuối gồm cả năm mốc: `D:\OneCrewRuns\v24\pkg\onecrew-2.4.0.dev2-beta` (wheel SHA256 `383df81d…`); kiểm từ gói 25/25 bước; script thử `DAT`/0 (bộ kiểm 25/25, task đầu tiên 25/25, luồng alpha 5/5). Gate 2.2 trên `61862e6`: 286/286 check thực thi đạt; `refused` chỉ vì 23 khoảng trống nghiệm thu, trùng danh sách beta 2.3 (§4).
- Hồi quy tích hợp trên `bde505b`: 170/170 test 2.4; 448 test của 34 module 2.2/2.3 bị ảnh hưởng: 447 đạt, 1 skip, 0 fail.
- Việc của chủ sở hữu: cho Codex review gói cuối; quyết định phát hành; cho thử với model thật nếu muốn; nghiệm thu. Lượt này không push, không tag, không nâng runtime đang dùng.

Log nằm ở `D:\OneCrewRuns\v24\logs\` (ghi tên ngắn, bỏ `reg-` và `.txt`); review ở `D:\OneCrewRuns\v24\review-*\`.

**Bản nào:** bản báo cáo trong `docs\` của gói là bản lúc dựng gói (còn các chỗ trống). Kết quả gói, tích hợp và gate chỉ có ở bản trong checkout `wf-v24-pkg`, ghi sau khi kiểm. Gói không tự chứng nhận chính nó.

## 1. Kết quả từng mốc

| Mốc | Người dùng được gì (một dòng) | Trạng thái | Bằng chứng (file : test : receipt) |
|---|---|---|---|
| S1 | Báo lỗi một lần, nhận một mã `FB-…`, có hồ sơ chẩn đoán trên máy; sổ hỏng vẫn báo được | đã có code + test + gói | `onecrew/v2/support.py`, `diagnostics.py`, `support_spool.py` : `test_v24_s1_*` (47 test) : gói cuối V17–V19 (`D:\OneCrewRuns\v24 thu 2.4.0.dev2\verify\verify-report.json`) |
| S2 | Bản vá OneCrew được gắn đúng định danh, cài vào venv mới ở điểm an toàn, kiểm lại lỗi gốc, tiếp tục việc cũ; thiếu quyền thì dừng đúng chỗ | đã có code + test + gói | `onecrew/v2/hotfix.py` : `test_v24_s2_apply` (12), `test_v24_s2_installed` (1) : gói cuối V20–V22 |
| A | Worker xin đọc thêm file trong quyền, từng trang, trên nguồn đã ghim; không nhét cả repo vào prompt | đã có code + test + gói (chỉ gói cuối) | `onecrew/v2/source_tools.py`, `authority.py` (`read`) : `test_v24_a_sources` (18), `test_v24_a_review` (17), `test_v24_a_installed` (1) : `aff-test_v24_a_*-br` (`c5b78e9`); gói cuối V23 |
| B | Node nhận phần tri thức đã đổi (delta) ở điểm an toàn; kết quả dựng trên tri thức đã thu hồi không được công bố như hiện hành | đã có code + test + gói (chỉ gói cuối) | `onecrew/v2/working_context.py` : `test_v24_b_context` (21), `test_v24_b_installed` (1) : `aff-test_v24_b_*-br` (`c5b78e9`); gói cuối V24 |
| C | Thẻ bước 0 nói đủ hay chưa đủ để làm; engine ghi vì sao chạy song song, tiếp tục, chạy kiểm không cần model hay chờ | đã có code + test + gói (chỉ gói cuối) | `onecrew/v2/execution_mode.py`, `step0.py`, `proposal.py`, `survey.py` : `test_v24_c_*` (52) : `c-after-review-extra-fix1` (63 OK, `21b6a56`); gói cuối V25 |

Giới hạn chung của cả năm mốc: chưa có model thật; capability mới đều opt-in, root cũ chạy như 2.3; giới hạn từng mốc ở `docs/v24/limits-s1.md`, `limits-s2.md`, `limits-a.md`, `limits-b.md`, `limits-c.md` (gộp trong `limits-final.md`) và hướng dẫn `docs/v24/HUONG-DAN-*.vi.md` §"Giới hạn".

## 2. Mapping tái sử dụng v1/2.3 và phần mới

| Mốc | Dùng lại (không viết lại) | Phần mới |
|---|---|---|
| S1 | sổ (sự kiện, task), `task_intake`, log attempt, blob receipt, `violations.jsonl`, `doctor`, outbox thông báo; ngữ nghĩa idempotent của `feedback.py` v1 (không import) | task neo `support:records`, 5 loại sự kiện `support.*`, hồ sơ có manifest, spool chỉ stdlib |
| S2 | `engine.resume_held`, `reconcile_orphans`, Control, `compat scan`, `authority.enforce` | `hotfix.py` (định danh wheel theo nội dung commit, venv mới, diễn tập trên bản sao, chuyển hook ở điểm an toàn, quay lui có điều kiện), quyền `support_install:<đích>`, 6 loại sự kiện |
| A | `paging.py` v1 (đưa vào wheel, không sửa), luật đọc của `discovery`, `command.artifact_sha`, vòng continuation của engine | `source_tools.py`, khóa tùy chọn `authority.read`, trường node `sources` |
| B | chọn/giao/thu hồi tri thức của 2.3 (`knowledge.py`), `dependency_core`, thế hệ của engine | `working_context.py`, sự kiện `knowledge.delivered`, `delta`, cổng kiểm lại, `wiki consumers` |
| C | `step0.evaluate`, đề xuất W47, `survey`, `engine._ready`, Control, executors | ba trường tùy chọn của đề xuất, `step0.card`, `execution_mode.py`, capability `execution-mode`, sự kiện `workflow.mode`, `engine measure` |

Chi tiết từng năng lực (có file:dòng và phân loại A/B/C/E): hợp đồng §3.

## 3. Gói thử, snapshot/hash, lệnh cài/thử/quay về

| Gói | Code | Wheel SHA256 | Bước kiểm | Ghi chú |
|---|---|---|---|---|
| `D:\OneCrewRuns\v24\pkg-trial\onecrew-2.4.0.dev1-S1-trial` | `1cc0940` (nhánh gói; S1 **trước** bản sửa review `b6b300c`) | `c7fb832c0ffe2dd53e1f19ba0b0cc1c9ac3a6cb28d0b9d2d9600c095fc874ebc` | 19/19 (09:17–09:31); script thử: kiểm 19/19, task đầu tiên 23/23, luồng alpha 5/5, `DAT`/0 (`pkg-trial\logs\thugoi-trial1.txt`); chạy lại vào thư mục cũ → từ chối, mã 2 (`thugoi-reuse.txt`) | chỉ còn giá trị lịch sử: thiếu bản sửa S1-R01…R08 |
| `D:\OneCrewRuns\v24\pkg-trial\onecrew-2.4.0.dev1-S2-trial` | `0c94f9a` (S1 + S2 đã sửa review; code C đã gộp nhưng không có bước kiểm C; chưa có A/B) | `98339b88f972bc9df4ee0f134e3ff4ed0e6309e5d26669804362118846222332` | 22/22 (12:13–12:18, `pkg-trial\verify-s2.log`); script thử chưa chạy trên gói này | |
| `D:\OneCrewRuns\v24\pkg\onecrew-2.4.0.dev2-beta` (**gói bàn giao**, beta, S1/S2/A/B/C) | `61862e6e26d339bf4df03f116428e9f922103e72` | `383df81d49d7d13adcc1d8c5cee11d0e1fc6258246898b94274ee90a510f151a` | 25/25 từ gói (13:34:36–13:39:25, máy rảnh; `pkg-verify-2.4.0.dev2`); script thử `DAT`/0 (13:39:25–13:45:20): bộ kiểm 25/25, task đầu tiên 25/25 bước bắt buộc, luồng alpha 5/5 (bước duyệt plan: fixture); chạy lại vào cùng thư mục → `KHONG DAT`, mã 2 (`pkg-wrapper-2.4.0.dev2`, `-reuse`) | `SHA256SUMS` 62 dòng, khớp 62/62; manifest `ships_paging: true` |

Hai gói trong `pkg-trial` (`2.4.0.dev1`) là bản thử của bộ dựng/kiểm gói, không phải bản bàn giao; gói bàn giao là `2.4.0.dev2`. Mỗi gói có `wheel\previous\onecrew-2.3.0.dev10-py3-none-any.whl` (SHA256 `8ab065c3bc6d2863888314952e3743b031d44ea44c1e92cd740abba385a1b4f7`, giống từng byte gói beta 2.3) và `wheel\regression\onecrew-2.2.0.dev18-py3-none-any.whl` (`0346577e…`).

**Thử cả gói** (kiểm hash, bộ kiểm, task đầu tiên, luồng alpha trên thư mục mới với sổ tạm; đạt khi in `DAT:` và thoát 0):

```bash
powershell -ExecutionPolicy Bypass -File "D:/OneCrewRuns/v24/pkg/onecrew-2.4.0.dev2-beta/verify/thu-goi.ps1"
```

**Cài vào venv thử** (đường dẫn có dấu cách, không mạng), xem version:

```powershell
$py = "C:\Users\NUC\AppData\Local\Programs\Python\Python313\python.exe"; $pkg = "D:\OneCrewRuns\v24\pkg\onecrew-2.4.0.dev2-beta"
$venv = "D:\OneCrewRuns\v24 thu tay 2.4.0.dev2\venv"; & $py -m venv $venv; & "$venv\Scripts\python.exe" -I -m pip install --no-index --no-build-isolation "$pkg\wheel\onecrew-2.4.0.dev2-py3-none-any.whl"
& "$venv\Scripts\onecrew.exe" --version
```

**Quay về 2.3.0.dev10:** `& "$venv\Scripts\python.exe" -I -m pip install --no-index --no-build-isolation --force-reinstall "$pkg\wheel\previous\onecrew-2.3.0.dev10-py3-none-any.whl"`. Đã kiểm: wheel 2.2.0.dev18 và 2.3.0.dev10 thật đọc được sổ có bản ghi S1 (`test_v24_s1_oldreaders`). Chưa kiểm: bản cũ đọc bản ghi S2, `knowledge.delivered`, `workflow.mode`. Root khai `authority.read` bị 2.3 từ chối. Trước khi quay về với sổ thật, chạy `compat scan` của bản cũ trên bản sao sổ.

## 4. Số test đạt/fail/skip/expected failure và giới hạn thực tế

**Test 2.4** (số test đếm bằng `grep "def test_"`; tổng 170):

| File | Số test | Lượt gần nhất có ghi | Kết quả |
|---|---|---|---|
| `test_v24_a_sources` / `_a_review` / `_a_installed` | 18 / 17 / 1 | `aff-test_v24_a_*-br` (`c5b78e9`, cây sạch) | 18/18, 17/17, 1/1; 0 skip |
| `test_v24_b_context` / `_b_installed` | 21 / 1 | `aff-test_v24_b_*-br` (`c5b78e9`) | 21/21, 1/1; 0 skip |
| `test_v24_c_execution_mode` / `_c_review` / `_c_step0_card` | 15 / 24 / 13 | `c-after-review-extra-fix1` (`21b6a56`, cây sạch): 63 test OK | không có số riêng từng file: các log này và `int-v24-bde505b` chỉ in dấu chấm, không in tên test; cả ba file nằm trong 170/170 của `int-v24-bde505b` |
| `test_v24_s1_intake` / `_bundle` / `_spool` / `_status` / `_review` / `_installed` / `_oldreaders` | 8 / 9 / 5 / 7 / 15 / 2 / 1 | `s1all-h6` (68 OK), `s2rest-h6` (58 OK), `s2inst-h6` (1 OK), chạy trên cây đang sửa trước commit `58c740d` | lượt sạch: nằm trong 170/170 của `int-v24-bde505b` (cây sạch, `bde505b`); không có số riêng từng file (log không in tên test) |
| `test_v24_s2_apply` / `_s2_installed` | 12 / 1 | như trên | như trên |
| Tất cả `tests/test_v24_*` trên `bde505b` | 170 | `int-v24-bde505b` (12:41–13:20) | `Ran 170 tests in 2346.975s`, `OK`: 170 đạt, 0 hỏng, 0 skip, 0 expected failure |

**Module 2.3/2.2 bị ảnh hưởng:**

| Lượt | Code | Kết quả |
|---|---|---|
| 11 module A/B (`aff-*-br`: a1/a2 knowledge, review_dev7, candidate_handoff, engine, engine_managed, …) | `c5b78e9` | đạt hết; 1 skip trong `test_v23_review_dev7` (skip có điều kiện môi trường trong test; log không ghi lý do) |
| 22 module ở `aff-*-b1` | `58b863f` | đạt hết (cùng 1 skip) |
| 17 module ở `aff-*-a2` | `26a86e7` | đạt, trừ 1 lỗi có từ trước trong `test_search_recovery` (dưới) |
| hồi quy ảnh hưởng của C (`c-affected-t1`) | `a67bb19` | 315/315 |
| `finalB-8577db4` / `finalA-8577db4` / `g2l2-58c740d` | `8577db4`, `58c740d` | 186/186; 117 với 1 hỏng; 100 với 1 hỏng (cùng một test có từ trước) |
| hồi quy sau gộp C (`merge-c-65ef023`) | `65ef023` | 72/72 |
| 34 module 2.2/2.3 bị ảnh hưởng (`int-aff-bde505b`, 12:41–13:34; số 34 theo người điều phối, log không in tên module) | `bde505b` | `Ran 448 tests in 3151.847s`, `OK (skipped=1)`: 447 đạt, 0 hỏng, 1 skip |

**Hỏng có từ trước, không do 2.4, không sửa:**
- `tests.test_g2_install.PackagingTests.test_the_templates_are_package_data_and_the_examples_keep_a_copy`: ghim `version = "2.2.0.dev3"` trong mẫu; hỏng cả trên `913e798`, trước mọi code S1 (`g2tpl-base`). Không có U1 cho test này.
- `tests.test_search_recovery.CTSCheckpointContinuationTests.test_C_real_build_delivers_a_valid_page_via_minimal_recovery_trim`: `PromptBudgetError` dưới trần Kiro 15 000; hỏng cả trên bản sao `5c34f4a` (`v24a-sr-base`).
- Expected failure: không lượt 2.4 nào báo `expected failures`.

**Từ `bde505b` tới snapshot cuối `61862e6`** chỉ đổi `tests/test_wf_metered_verifier.py` và `wfkit/u1/U1-20261101-V24-DEADLINE-1.json` (`7767982`), dòng version trong `pyproject.toml` (`61862e6`), tài liệu và công cụ gói (`a039d1f`, `d9d3075`) (`git diff --stat bde505b 61862e6`). Kết quả tích hợp trên `bde505b` dùng cho code của `61862e6` theo đúng điều kiện này; gate dưới đây chạy trên chính `61862e6`.

**Gate snapshot 2.2** (bắt đầu 13:46:05 trên `61862e6`, log `gate-snapshot-61862e6`): 286/286 check thực thi đạt, `failed []` (217 lượt module riêng biệt: 2.097 test chạy, 2.097 đạt, 0 fail, 0 skip, 0 expected failure, 0 unexpected success — cộng theo log riêng biệt, vì 99 trong 286 receipt dùng lại 30 log chung; receipt ghi riêng `tests_run/passed/skipped/expected_failures/unexpected_successes/errors`); quyết định `refused` chỉ vì 23 khoảng trống nghiệm thu/phát hành (13 `acceptance-partial`, 10 `acceptance-blocked`; loại `release-evidence`/`acceptance-audit`/`external-pilot`), danh sách trùng hẳn với gate beta 2.3 dev10 `fb3333b` run 2 (so bằng release/testcase/kind): đòi chủ sở hữu chạy verb nghiệm thu, biên nhận phát hành thật và pilot ngoài; kit-guard `ok` với hai U1 2.4; chạy 13:46:05–16:39:35 (2 h 53, một mình); wheel dựng lại trong gate `304615a7…` khác wheel gói `383df81d…` vì builder không tái lập byte (đã biết từ 2.2), cùng code `61862e6`; hồ sơ `D:\OneCrewRuns\v24\gates-tmp\wf-snapshot-gate-20261101-61862e6\gate\decision.json`, log `gate-snapshot-61862e6`. Trong lúc gate chạy, sổ hook thật đổi lần hai lúc 14:08:57 (SHA256 `23ec9033…` → `8ecf0fda…`, thêm một dòng bản sao `d:\onecrewruns\copies\signsdk-dev10-thu-20261101` → `D:\OneCrewRuns\states\signsdk-dev10-thu-20261101`): là phiên khác thử dev10 trên bản sao, không phải lượt 2.4 (log gate không chạm registry, đường dẫn là bản sao dev10); không khôi phục.

**U1 test hạn root:** trên `bde505b` dưới tải, test cũ hỏng 4/4 (`D:\OneCrewRuns\v24\probe-mv\bde505b\probe-mv.json`); sau U1-DEADLINE-1: 2/2 (`deadline-green1-dirty`, `-green2-dirty`) và cả module 4/4 (`deadline-module-dirty`).

## 5. Kết quả đo

Chỉ số quan sát được; không có so sánh trước/sau trên cùng điều kiện, nên không có kết luận nhanh hơn hay chậm hơn.

| Số đo | Giá trị | Nguồn | Ghi chú |
|---|---|---|---|
| Thao tác người dùng để báo một lỗi (S1) | 1 lệnh `onecrew support report` | `docs/v24/HUONG-DAN-SUPPORT.vi.md` §1; gói V17 | đếm theo thiết kế lệnh, không đo trên người dùng thật |
| Thời gian bước báo lỗi + hồ sơ + xem (V17) | 2,0 s ở gói cuối (máy rảnh); 6,8 s / 5,5 s / 2,6 s ở các gói thử | `D:\OneCrewRuns\v24 thu 2.4.0.dev2\verify\verify-report.json`; gói thử S1, script thử S1, gói thử S2 | tải máy khác nhau giữa các lượt |
| Spool khi sổ hỏng (V18) | 1,7 s ở gói cuối; 4,3 s / 2,6 s / 2,3 s ở các gói thử | như trên | |
| Chuỗi bản vá S2: V20 / V21 / V22 | 24,4 s / 21,8 s / 8,4 s ở gói cuối; 33,6 s / 30,5 s / 13,0 s ở gói thử S2 | verify-report gói cuối; `pkg-trial\work-verify-s2\verify-report.json` | gồm dựng repo tạm, build wheel, venv; `claude` giả |
| Bước A / B / C của gói cuối: V23 / V24 / V25 | 27,6 s / 7,7 s / 7,3 s | verify-report gói cuối | worker giả |
| Cả bộ kiểm 25 bước / script thử | 13:34:36–13:39:25 (~4 phút 49 giây) / 13:39:25–13:45:20 (~5 phút 55 giây) | `pkg-verify-2.4.0.dev2`, `pkg-wrapper-2.4.0.dev2` | máy rảnh |
| Định danh trước khi chạy lệnh kiểm (`verified_sha`, checkout, ràng bằng chứng) | 4–9 s dưới tải | lý do ghi trong `wfkit/u1/U1-20261101-V24-DEADLINE-1.json`; probe: cả test 7,5–8,6 s (`probe-mv.json`) | số trong bản ghi U1, chưa có số đo riêng được lưu |
| Ký tự prompt khi có / không có `sources` | unknown | — | chưa đo |
| `engine measure` trên fixture C | tới kết quả hữu ích đầu tiên 2,75 s; tổng attempt (hợp, không cộng) 0,69 s; chờ 1,55 s | `c-samples.txt` | worker giả, 4 node; chỉ chứng minh cách tính, không phải hiệu năng |
| Lần hỏi lại dữ kiện đã có, thông báo trùng, lỗi tái phát, thời gian tới bản thử trên lỗi thật | unknown | — | không có lỗi thật nào đi qua S1/S2 trong lượt này |

## 6. Việc thực sự ngoài quyền và việc local chưa làm

**Ngoài quyền của lượt này (cần chủ sở hữu hoặc Codex):**
- Push nhánh, tag, publish bất kỳ gói 2.4 nào.
- Nâng runtime đang dùng (`%LOCALAPPDATA%\OneCrew`, venv thật, hook thật), đọc/ghi `state-v2-real`.
- Chạy model hay provider thật (có thể tốn phí, cần quyền).
- Codex review; nghiệm thu của chủ sở hữu; xác nhận `support confirm` thật.
- U1 ngoài hai bản đã ghi (`U1-20261101-V24-PIN-1`, `U1-20261101-V24-DEADLINE-1`), ví dụ cho test ghim mẫu `2.2.0.dev3`.
- Quyết định giữ khóa mặc định của báo cáo theo nội dung (reviewer S1-R08 ghi đây là việc của chủ; đã chọn theo quyền tự quyết kỹ thuật).

**Local, trong quyền, chưa làm (nói thật):**
- Phần model thật của A/B/C: worker thật dùng giao thức đọc nguồn, hiểu delta, bước 0 đề xuất đúng — chưa chứng minh.
- Linux/POSIX: liệt kê process của S2 trả `unknown` nên từ chối chuyển; cây phân biệt hoa thường (`src/` và `SRC/`) chưa thử; mọi lượt chạy trên Windows.
- Giữ/xoá dữ liệu: hồ sơ chẩn đoán có thể tới 8 MB blob mỗi lần, chưa có chính sách giữ/xoá chung; `support cleanup` chỉ xoá bản sao diễn tập (HUONG-DAN-SUPPORT §5 mục 10).
- Bản cũ đọc bản ghi S2, `knowledge.delivered`, `workflow.mode`: chưa diễn tập.
- Đã khép trong lượt (`d9d3075`): `limits-s1.md` và `limits-final.md` viết lại theo code hiện hành (diễn tập bản cũ đọc sổ, bộ lọc theo dòng); `ships_paging` đọc từ `py-modules`, manifest gói cuối ghi `true`.
- Số test riêng từng file S1/S2/C trong lượt tích hợp: không có (log không in tên test); chỉ có tổng 170/170.
- Ngân sách plan sửa không bị trừ khi cài; hook chuyển dùng mẫu settings của runtime đang cài; bản vá thứ hai cho cùng đích cần quay lui hoặc `--replace` (`limits-s2.md`).

## 7. Danh sách để Codex review

- **S1 lọc bí mật** — `onecrew/v2/diagnostics.py` (`redact_line`): mẫu, không bảo đảm; xem `test_v24_s1_review` r01, s2_r11.
- **S1 khóa mặc định và spool không xác thực** — `support.py`, `support_spool.py`: tái phát, khác version, file spool cài sẵn; `test_v24_s1_review` r08, s2_r05, r06.
- **S2 định danh wheel** — `hotfix.py` (`artifact`): so nội dung wheel với commit đã kiểm, không build lại; `test_v24_s2_apply` `test_wrong_wheel_hash_source_or_unchecked_pair_refused`, `test_venv_reuse_planted_or_other_wheel_refused`.
- **S2 quyền và điểm an toàn** — `authority.py` `_support_install`, `hotfix.py` (claim 15 phút, liệt kê process, fence dữ liệu): `test_project_edit_grant_does_not_allow_onecrew_fix_or_install`, `test_running_process_unknown_effect_shared_consumer_or_changed_data_blocks_switch`.
- **S2 crash và quay lui** — `hotfix.py` intent/`switched_one`, rollback "đọc được ≠ chạy tiếp được": `test_crash_between_prepare_install_switch_resume_no_double_effect`, `test_unreadable_by_old_refuses_rollback_and_keeps_new_ledger`.
- **Task neo `support:records` với bản cũ** — `support.py:26`, `control_core.py` (configure từ chối): `test_v24_s1_oldreaders`, `test_p3a_the_support_anchor_is_never_executable`.
- **A quyền đọc** — `authority.py` (`read`, mở rộng schema), `source_tools.py` `Scope`: `test_sa01b…`, `test_a_r03_a_declared_read_grant_binds_node_read`, `test_a_r01_…`.
- **A đếm lượt qua restart và đồng thời** — `source_tools.py`, `engine.py` (`rounds_exhausted`): `test_sa07…`, `test_a_r04_…`, `test_a_r13_two_concurrent_continuations_run_one_attempt`.
- **B cổng công bố** — `working_context.decide`, các điểm gọi trong `engine.py` (step, nhận candidate, verify trong giao dịch ghi): `test_b_r01…`, `test_b_r02…`, `test_sb05…`.
- **B consumer bị ảnh hưởng** — `knowledge.affected_consumers`: `test_sb02…`, `test_sb08…`, `test_b_r07…`.
- **C điểm dừng bước 0** — `proposal.py` (luật mới), `survey.open_in`: `test_v24_c_review` r01 ×3, r02.
- **C chế độ `tools` và giữ phiên** — `execution_mode.py`, `engine.py` (claim tools, `resources`): `test_r03_…`, `test_r04_…`, `test_r06_reuse_needs_the_previous_attempt_session_the_same_id_and_the_same_pin`; lưu ý C-R17 (fixture `list(namespaces.CAPABILITIES)`).


**Điểm rủi ro mới sau vòng sửa dev3 (cho Codex xem lại):**

- **S2 mốc tạo venv nằm trong sổ** — `hotfix.py` (mốc `support.install` ghi sau lần kiểm đầu: `pyvenv.cfg`, `Scripts/`, phần còn lại của `site-packages`): người ghi được sổ hoặc thư mục `support-work` giả được cả mốc lẫn marker (đã ghi trong `limits-s2.md`). Mốc không chứng minh `python -m venv` đã tạo đúng. Test: `test_v24_s2_review2` `R2_*`, `R3_02`, `R3_04`.
- **S2 quy kết trong cửa sổ chuyển** — `_window`, `_settled`, `events_in_window`, `attempts_in_window`: cửa sổ từ lần chụp ngay trước lần ghi hook đầu tới lần chụp ngay sau lần ghi cuối; một process hook khởi động trước lần ghi cuối có thể ghi sau lần chụp đó và được đếm như của runtime mới; nhiều file hook thì không phân biệt được ai ghi giữa file đầu và file cuối; project bận có thể làm bước kiểm trước lần ghi đầu từ chối lặp lại. Test: `R3_03`, `R4_02a/b`, `InstallWindow`, `RollbackWindow`.
- **S2 `support cleanup --venv`** — `cleanup_venv`, `_cleanable`, `_reparse`, `ownership.refuse_argv`, `hook_cli.OWNER_DENY`: chỉ hai dạng thư mục của lần cài trong sổ này, không bao giờ xóa venv đích đã khai, không qua link hay junction, luật chặn cho phiên AI kể cả viết tắt (`--v*`). Còn lại: thư mục giữa gốc và đường dẫn được đưa bị thay bằng junction sau các phép kiểm (R5-02, ghi trong `limits-s2.md`); quote động từ lách mọi mẫu deny (giới hạn của mẫu). Test: `R4_01`, `R4_03`, `R4_04`, `R4_06`, `R5_01`.
- **B duyệt đủ chuỗi đầu vào và nghĩa "không kiểm được"** — `working_context._walk`, `_edge`, `_attempt_of`, `decide`: attempt sinh lấy từ sổ theo node + biên nhận + generation, không từ biên nhận; mọi trường hợp không kiểm hết (biên nhận thiếu/không đọc được, attempt không có trong sổ, vòng, `MAX_WALK`) thành `input_changed`. Chi phí duyệt nằm trong khóa ghi (đo trên `8424336`: 0,18 s ở node thứ 2 và 0,50 s ở node thứ 12 của chuỗi 12 node). Test: `test_f3_a` … `test_f3_o`.

**P3 còn lại từ hai review cuối (không chặn; Codex nên biết):**

- Từ `review-s2-r5.md` (S2, 0 P1/1 P2/4 P3; P2 R5-01 đã sửa ở `bb19222`): R5-02 TOCTOU của `cleanup_venv` (đổi thư mục giữa gốc và đường dẫn sau kiểm; không sửa, ghi vào giới hạn); R5-03 `_norm` fail-closed (đường dẫn dạng `\\?\`, tên 8.3, ổ `subst` không khớp thì từ chối; lời từ chối nay nói "đưa đường dẫn đúng như `install` in ra"); R5-04 bước kiểm trước lần ghi đầu từ chối khi có bất kỳ thay đổi nào của project bận (an toàn, chạy lại; đã ghi); R5-05 câu "lần chụp thứ hai" trùng nghĩa với "lần đọc thứ hai" (đã sửa lời).
- Từ `review-f3-r2.md` (B, 0 P1/0 P2/4 P3; đã xử lý ở `5b24fca`, `d2f1c5f`): P3-1 lời khuyên "re-open the producer" của `node.held` vẫn chung cho mọi `input_changed` (lý do đã nêu phần không kiểm được; với biên nhận nêu sai attempt cần sửa executor của node sinh); P3-2 `f3_m` đã chặt hơn, `f3_o` mới; P3-3 ràng buộc không có `generation` lấy kết quả mới nhất của node sinh mang biên nhận đó (ghi `limits-b.md`); P3-4 chi phí duyệt đã đo lại.
- Từ `review-f3.md` (B vòng 1) P3-1, **chưa xử lý và chưa ghi trong `limits-b.md`**: `decide` trả `publish` khi root không resolve được hoặc không mở được sổ; `_own` bỏ mọi kiểm tri thức của node sinh không còn trong định nghĩa hiện tại. Reviewer thấy hai đường này không với tới được từ các điểm gọi hiện tại của engine; tài liệu vẫn viết "luôn đóng khi không kiểm được".
- Sửa S2 mất năm vòng vì mỗi vòng sửa mở thêm một khe vòng đời (xem LL-37 ở `wiki/LESSONS.vi.md`). Còn ngoài phạm vi: Linux/POSIX (liệt kê process `unknown` nên từ chối chuyển), bản cũ đọc bản ghi S2, mọi thứ cần model thật.

## 8. Review Codex vòng 1 trên dev2 → dev3 (02/11)

Chỉ thị chủ 01/11 ~20:55 sau review Codex vòng 1 trên `2.4.0.dev2` (code `61862e6`, tài liệu `953096a`): sửa 2 P1 (F1, F2), 1 P2 (F3), 1 P3 (F4). Mỗi finding có phản chứng đỏ trên baseline `953096a` trước khi sửa. Snapshot sau sửa: `2.4.0.dev3` = `5a7a8ef`. Bảng finding → ca thử → kỳ vọng: `D:/OneCrewRuns/v24/codex-r1/plan.md`. §1–§7 ở trên vẫn mô tả dev2 (`61862e6`), không viết lại; mọi thay đổi của dev3 nằm ở đây.

**Quyết định trước:** cả bốn finding đã sửa trên nhánh, có test đỏ → xanh và review độc lập (riêng F4 là tài liệu, chưa có review riêng). Chưa có Codex review lại dev3, chưa có kết quả gói dev3 và gate (neo ở cuối mục). Không push, không tag, không phát hành.

### 8.1 Bảng finding

Số dòng là của lượt sửa đầu (vòng 1); các vòng 2–5 đã dời dòng, tên hàm giữ nguyên. Đường dẫn bằng chứng nằm dưới `D:/OneCrewRuns/v24/codex-r1/` (trừ khi ghi `logs/`, là `D:/OneCrewRuns/v24/logs/`).

| Finding | Thay đổi (file:dòng, vòng 1) | Đỏ trước / xanh sau | Test | Review độc lập (vòng, kết quả cuối) |
|---|---|---|---|---|
| **F1 P1, S2:** runtime bị sửa vẫn được nhận là đúng artifact | `onecrew/v2/hotfix.py`: `identity()` :211 băm nội dung từng file theo RECORD của wheel đã kiểm (không đọc RECORD trong venv); `interpreter()` :141, `entry_run()` :151 (`PYTHONVERBOSE`); `verify_installed()` :990 dùng ở `_install` :1073 (venv mới và venv dùng lại), :1050 (đã chuyển), :1280 (recheck). Vòng 2–5: mốc tạo venv ghi vào sổ, kiểm tĩnh trước khi chạy gì của venv, `.pth` đọc utf-8-sig, một venv cho mỗi sổ, `support cleanup --venv` (lệnh của chủ) | Đỏ: probe Codex `runtime_probe` trên `953096a`: sửa `diagnostics.py`, giữ RECORD, `before []`/`after []`; `s2/red-953096a.txt` (20 test, 16 hỏng + 1 lỗi, gồm cả F2). Xanh: `s2/codex-probes/runtime_probe-fixed.txt` (`after_problems` nêu `onecrew/v2/diagnostics.py`); `s2/green-final.txt` (103 OK) … `s2/round5-green.txt` | `tests/test_v24_s2_review2.py`: `RealVenvIdentity` (`test_f1_*`; venv và wheel thật: nguyên vẹn, nối byte, sửa, xóa, file thừa, `.pth`, `.pyc` giả, entrypoint sai), `RealVenvRound2` (`R2_01*`, `R2_03`–`R2_05`, `R2_11`), `Round2`–`Round4` (`R2_*`, `R3_*`, `R4_*`), `R5_01`; thêm vào `test_v24_s2_installed.py`, `test_v24_s2_apply.py`; bước gói V27 | 4 lượt (r2–r5): r2 P1 3/P2 5/P3 5; r3 2/3/4; r4 2/2/4; **r5 (cuối) 0/1/4**; P2 của r5 (viết tắt `--ven` lọt luật chặn) đã sửa ở `bb19222`, chưa review lại riêng |
| **F2 P1, S2:** rollback lấy mốc dữ liệu sau khi diễn tập | `hotfix.py`: `_fenced()` :593 (fence và băm dữ liệu trong một lượt đọc), `_drill_copy()` :624 (fence mỗi state root trước khi chép; bản chép phải đúng dữ liệu đó), `_window()` :841 (kiểm lại sau khi trỏ hook), `_rollback()` :1169, điểm crash mới `rollback_after_drill` :1201. Vòng 2–5: cửa sổ tính từ lần chụp ngay trước lần ghi hook đầu tới lần chụp ngay sau lần ghi cuối; vi phạm không còn là ngõ cụt; claim có thời hạn, gia hạn, tiếp quản khi tiến trình giữ claim đã chết | Đỏ: `baseline/rollback_probe-953096a.json`: `result rolled_back` với `data_changed_since_drill true`; `s2/red-953096a.txt` (7/7 ca `RollbackWindow` và 2 ca `InstallWindow` hỏng). Xanh: `s2/codex-probes/rollback_probe-fixed.txt`: `result refused`; xanh như F1 | `RollbackWindow`, `InstallWindow` (`test_f2_*`; chèn ghi ở từng ranh giới, hai consumer chung một state root, crash sau diễn tập, ca đối chứng không đổi), `rollback_window` trong `test_v24_s2_installed.py` (runtime thật), `R2_02*`, `R3_01`, `R4_02*`; bước gói V28 | như F1 (cùng 4 lượt review, cùng hàm) |
| **F3 P2, B:** chuỗi dài bỏ lọt tri thức đã thu hồi (`INPUT_DEPTH=3`) | `onecrew/v2/working_context.py`: bỏ `INPUT_DEPTH`; `MAX_WALK=10000` :34; `_walk` :316 (ngăn xếp tường minh, mỗi attempt xét một lần), `_facts` :279, `_edge` :260, `_attempt_of` :239, `_upstream` :294, `_decision` :228, `decide` :342. Không kiểm hết được thì `input_changed`, không bao giờ `publish`. Sau review: attempt sinh luôn lấy từ sổ (`8424336`), lý do hold nêu phần không kiểm được (`5b24fca`) | Đỏ: `b/probe-before-953096a.txt` (probe Codex `chain_integration`: A recheck, D `input_changed`, E `publish`, `verify E` được nhận); `b/red-test_v24_b_review2-12-953096a.txt` (12 test: 10 hỏng, 2 lỗi); `b/red-p1-misattributed-155ed60.txt`; `b/red-r2-hold-text-31baabf.txt`. Xanh: `b/probe-after-fix.txt` (E `input_changed`, `verify E` bị từ chối), `b/depth_probe-after-fix.json`, `b/green-test_v24_b_review2-12.txt`, `logs/reg-r2-review2-r2.txt` | `tests/test_v24_b_review2.py`: `test_f3_a` … `test_f3_o` (15 test): chuỗi 7 node, thứ tự/memo, restart, bản mới của mục bắt buộc, fan-in, fan-out, biên nhận không đọc được, biên nhận của executor khác, chuỗi 40, vòng, thiếu bản ghi start, trần `MAX_WALK`, biên nhận nêu sai attempt (`f3_m`, `f3_n`, `f3_o`); bước gói V26 | 2 lượt: `review-b/review-f3.md` P1 1/P2 0/P3 4 (P1-1: biên nhận nêu attempt của node khác thì chuỗi bị bỏ lọt; đã sửa); **`review-b-r2/review-f3-r2.md` (cuối) 0/0/4 P3**, đã xử lý ở `5b24fca`, `d2f1c5f` |
| **F4 P3:** báo cáo/giới hạn sai hoặc cũ | Phần 1 `9e9de4d`: số gate `61862e6` đúng (217 lượt, 2.097/2.097, 0 skip/xfail), 447 đạt + 1 skip của 448, `limits-s2` không còn ghi "chỉ alpha S1/S2". Phần 2 (lượt này): mục 8 này, hợp đồng §6–§8, `limits-final.md` đồng bộ với `limits-s2.md`, `limits-b.md`, wiki; `docs/CHANGELOG.md` mục dev3 (`5a7a8ef`) | Đỏ: đọc tài liệu `953096a` (`plan.md` hàng F4). Xanh: tài liệu ở `5a7a8ef` và commit này | Không có (tài liệu) | Chưa có review độc lập riêng; Codex xem ở lượt sau |

### 8.2 Chủ dự án thấy gì sau khi sửa

- **F1:** `support install` và `support recheck` không còn nhận một venv đã bị sửa file, dù RECORD trong venv vẫn nguyên. Kiểm nội dung từng file với wheel đã kiểm, kiểm file lạ, `.pth`, `.pyc`, link và junction trước khi chạy bất cứ thứ gì của venv. Venv mà sổ này không ghi mốc lúc tạo thì không dùng lại; chủ dọn venv dở dang bằng `support cleanup --venv` (lệnh của chủ, bị từ chối trong phiên AI). Hook không đổi khi bị từ chối.
- **F2:** nếu dữ liệu đổi giữa lúc diễn tập và lúc chuyển hook hay quay lui, lệnh từ chối (`refused`/`refused_unsafe`) và không ghi hook; kết quả `rolled_back` hay `switched` chỉ có khi dữ liệu đúng bản đã diễn tập. Nếu dữ liệu đổi sau lần ghi hook đầu thì lệnh ghi vi phạm cửa sổ chuyển, nhưng không còn ngõ cụt: chủ chạy lại `rollback` hay `install` thì diễn tập lại trên dữ liệu hiện tại. Trạng thái nói theo hook đang chạy thật và nhắc khởi động lại phiên Claude Code đang mở.
- **F3:** nếu tri thức bắt buộc hoặc nguồn bị thu hồi ở đầu một chuỗi node dài, mọi node phía sau dựa trên nó bị giữ (`input_changed`), không công bố và không verify, dù chuỗi dài bao nhiêu. Node độc lập vẫn chạy. Khi không kiểm hết được (biên nhận thiếu hay nêu sai attempt, vòng, vượt `MAX_WALK`), kết quả là giữ, không bao giờ là công bố; lý do hold nêu phần không kiểm được.
- **F4:** báo cáo, hợp đồng và giới hạn nói đúng những gì đã có và chưa có ở dev3; số liệu tách đạt/hỏng/skip. Không có thay đổi hành vi.

### 8.3 Số test

Đọc từ đuôi log (`Ran N tests`, `OK`, `OK (skipped=…)` hay `FAILED`). Không log nào dưới đây có dòng `skipped`: 0 skip.

| Lượt | Code | Kết quả |
|---|---|---|
| Hồi quy tích hợp 2.4 (`logs/reg-int-v24-830af1a.txt`, 22:56:30–23:22:36) | `830af1a` (sau vòng 2 của S2, F3 đã sửa P1-1) | `Ran 228 tests in 1565.184s`, `OK`: 228 đạt, 0 hỏng, 0 skip |
| Hồi quy tích hợp 2.4 (`logs/reg-int-v24-fe495c1.txt`, 23:54:15–00:29:50) | `fe495c1` (sau vòng 3 của S2 và vòng P3 của B) | `Ran 238 tests in 2133.359s`, `OK`: 238 đạt, 0 hỏng, 0 skip |
| S2, đỏ trên baseline (`s2/red-953096a.txt`) | `953096a` | 20 test: 16 hỏng, 1 lỗi, 3 đạt |
| S2, xanh vòng 1 (`s2/green-final.txt`) | `0af3482` | 103 test (ba module S2, các `test_v24_s1_*`, `test_g1_core`): OK, 0 skip |
| S2, vòng 2: đỏ `round2/red-da9c913.txt`, xanh `round2/green-r2final.txt` (dưới `s2/`) | `da9c913` → `a7964a3` | đỏ 43 test (16 hỏng, 2 lỗi); xanh 142 test OK |
| S2, vòng 3: `round3/red-830af1a.txt`, `round3/green-r3final.txt` | `830af1a` → `550f40a` | đỏ 10 test (6 hỏng, 4 lỗi); xanh 151 test OK |
| S2, vòng 4: `round4/red-fe495c1.txt`, `round4/green-r4final.txt`, `round4/green-r4fix.txt` | `fe495c1` → `daa3caa` | đỏ 9 test (7 hỏng); xanh 340 test, 2 hỏng: 1 là assertion của `R3_02` (sửa trong lượt, chạy lại ở `green-r4fix.txt`), 1 là `test_g2_install` (dưới) |
| S2, vòng 5: `s2/round5-green.txt` | `34709d5` + sửa `bb19222` | 183 test, 1 hỏng (chỉ `test_g2_install`); 182 đạt, 0 skip. Danh sách module không in trong log |
| B, đỏ trên baseline (`b/red-test_v24_b_review2-12-953096a.txt`) | `953096a` | 12 test: 10 hỏng, 2 lỗi |
| B, xanh vòng 1 (`b/green-test_v24_b_review2-12.txt`) | `3cf5b30` | 12 test OK |
| B, P1-1: đỏ `b/red-p1-misattributed-155ed60.txt`; xanh `logs/reg-p1-green2-p1fix.txt` | `155ed60` → `8424336` | đỏ 2 test (1 hỏng); xanh 2 test OK |
| B, vòng P3: đỏ `b/red-r2-hold-text-31baabf.txt`; xanh `logs/reg-r2-review2-r2.txt` (module `test_v24_b_review2`) | `31baabf` → `5b24fca` | đỏ 4 test (3 hỏng); xanh 15 test OK, 0 skip |
| B, hồi quy module liên quan (`logs/`) | `3cf5b30`, `8424336`, `5b24fca` | `reg-f3-b1-fix1` 125 OK; `reg-f3-b2-fix1` 146 OK; `reg-p1-b1-p1fix` 41 OK; `reg-p1-b2-p1fix` 146 OK; `reg-r2-b1-r2` 42 OK |
| Bước gói V26–V28 trên gói dev2 (`pkg/v26-on-dev2-r2.txt`, `v27-on-dev2-r2.txt`, `v28-on-dev2-r2.txt`) | gói dev2 | cả ba FAIL (V26 93,2 s, V27 58,4 s, V28 67,5 s) |
| V26–V28 trên wheel dựng từ `fe495c1` (`D:/OneCrewRuns/v24 thu v2x fe495c1`) | `fe495c1` | đạt (lượt của agent công cụ) |

**Hỏng có từ trước, không sửa (bộ 2.2 bị khóa):** `tests.test_g2_install.PackagingTests.test_the_templates_are_package_data_and_the_examples_keep_a_copy` ghim version `2.2.0.dev3`; hỏng y hệt trên `61862e6` và `fe495c1` (`s2/round4/g2-packaging-on-fe495c1.txt`: `Ran 1 test`, `FAILED (failures=1)`). Không có U1 cho test này.

### 8.4 Cách ly

Mọi lượt (implementer, reviewer, hồi quy, probe) chạy với `TEMP`, `LOCALAPPDATA`, `APPDATA` dưới `D:/OneCrewRuns/v24/tmp-int` và dùng `claude` giả hay worker giả. SHA256 sổ hook thật `8ecf0fda5097d187…` bằng nhau trước và sau mỗi lượt agent và mỗi hồi quy (báo cáo implementer, reviewer và log hồi quy đều ghi). Không đụng worktree 2.3, sổ thật, runtime đang dùng, `state-v2-real`; không push, không tag.

### 8.5 Gói dev3

Gói `D:/OneCrewRuns/v24/pkg/onecrew-2.4.0.dev3-beta` (snapshot `5a7a8ef`, 28 bước): wheel SHA256, kết quả kiểm từ gói (28 bước, thời gian), script thử, chạy lại vào cùng thư mục: chưa có.

<!-- v24:dev3-pkg -->

### 8.6 Gate và hồi quy trên dev3

Gate 2.2 trên `5a7a8ef` và hồi quy tích hợp 2.4 trên `5a7a8ef`: chưa có. Hai lượt tích hợp ở §8.3 là trên `830af1a` và `fe495c1`, trước vòng 4–5 của S2 (`f171ac9`, `bb19222`); vòng 4–5 mới có lượt module S2 riêng.

<!-- v24:dev3-gate -->

## 9. Review Codex trên dev3 → dev4 (02/11)

Mốc Codex review: code `5a7a8ef`, `2.4.0.dev3`, gói `D:/OneCrewRuns/v24/pkg/onecrew-2.4.0.dev3-beta`, wheel `35c78a4927dabc5a30ea2f6394362537731abac54e7ed240b4f5fc6188f92c29`; tài liệu checkout `c6f83e3`, `7e61b46` sau snapshot gói. Bằng chứng của Codex: `D:/OneCrewRuns/codex-dev3-review-c2a9a088/` (`bytecode_probe.py`, `bytecode-result.json`: `marker_created true`, `entrypoint_exit 0`). Gói dev3 giữ nguyên, không sửa.

### 9.1 Bảng finding

| Finding | Nguyên nhân | Sửa (file:line ở snapshot dev4) | Phản chứng đỏ trước → xanh sau |
|---|---|---|---|
| P1 (S2) bytecode sai chạy trước khi bị từ chối | `identity` ghi verdict `.pyc` của trình thông dịch rồi vẫn gọi `entry_run` (`onecrew --version`); `verify_installed` chỉ thêm lỗi sau khi đã chạy. Cùng lớp: quay lui so runtime cũ theo mốc **bỏ qua cache** rồi chạy runtime cũ (drill, `event_classes`) | `onecrew/v2/hotfix.py`: `unproven_caches` :192, `identity` dừng trước `entry_run` :411–416, `verify_installed` báo `entry_blocked` :1310, `entry_run` với `PYTHONPYCACHEPREFIX` riêng :172–188, quay lui `_old_runtime` + `venv_caches` :205, :1558–1564, danh sách cache qua stdin :165 | `tests/test_v24_s2_bytecode.py` trên venv thật (wheel của checkout, pip): 7/8 đỏ trên `7e61b46` (`reg-p1-bytecode-red-7e61b46.txt`: file đánh dấu được tạo, `onecrew` của venv được chạy), 8/8 xanh sau sửa (`reg-p1-bytecode-green-p1fix3.txt`). Bước gói V29 trên chính gói dev3: FAIL (`pkg-red-dev3-V29-s2-bytecode.txt`) |
| P3 tài liệu trong gói không đồng bộ | Gói dev3 dựng từ `5a7a8ef`; tài liệu tổng hợp sửa sau snapshot (`c6f83e3`) không vào gói. Trong gói: mục S2, B của `limits-final.md` khác `limits-s2.md`, `limits-b.md`; dòng claim cũ; README "chưa được Codex review" khác dòng đầu giới hạn | snapshot dev4 chứa tài liệu đã sửa; câu `.pyc` ở dòng "Ranh giới tin cậy" (`limits-s2.md`, `limits-final.md`), `HUONG-DAN-SUPPORT.vi.md`; README trỏ dòng review của mục Giới hạn (`build_milestone.py`) | `tests/test_v24_docs_sync.py` (mỗi mục giới hạn tổng hợp = file của mốc; claim nêu pid + thời điểm tạo + gia hạn; dòng tin cậy nêu `.pyc`). Bước gói V30 trên gói dev3: FAIL ba lý do (`pkg-red-dev3-V30-s2-docs.txt`) |

### 9.2 Hành vi mới

- `onecrew --version` của phép kiểm danh tính chỉ chạy khi mọi `.pyc` của nguồn trong wheel có câu trả lời `same` (hoặc `other interpreter`: tag/magic khác, Python này không nạp). `.pyc` khác, không đọc được, không có câu trả lời, hay trình thông dịch không trả lời → `entry_blocked`, venv bị từ chối, `exit` để trống (không có chương trình nào chạy để có exit).
- Lần chạy `onecrew --version` đó đọc bytecode từ một thư mục trống riêng (`PYTHONPYCACHEPREFIX`), xóa sau khi chạy: `.pyc` bị thay ngay sau phép so cũng không chạy trong phép kiểm; lần xét kế tiếp (ngay trước khi ghi hook, recheck) thấy nó.
- Quay lui: sau khi mốc runtime cũ khớp, mọi `.pyc` có nguồn bên cạnh trong `site-packages` của runtime cũ được trình thông dịch `-I -S` của nó so với nguồn; không đạt thì từ chối trước khi chạy runtime cũ. Danh sách dài đi qua file tạm thay cho dòng lệnh (giới hạn 32k ký tự của Windows).
- Giới hạn còn lại: phép so cần code `.pyc` giống hệt code biên dịch từ nguồn; nó không bắt mã độc nằm ngay trong nguồn của runtime cũ (nguồn đó chỉ được so với mốc lúc cài). Python gốc và thư viện chuẩn vẫn được tin như trước.

### 9.3 Kiểm

Do Claude chạy trong lượt này (log dưới `D:/OneCrewRuns/v24/logs/`, trừ khi ghi khác):

| Kiểm | Snapshot / artifact | Kết quả |
|---|---|---|
| P1 phản chứng, code chưa sửa | `7e61b46` (code = `5a7a8ef`) | `reg-p1-bytecode-red-7e61b46.txt`: 7 hỏng / 8 (hành vi: file đánh dấu được tạo, `onecrew` của venv được chạy); 1 đối chứng đạt |
| P1 phản chứng, sau sửa | checkout | `reg-p1-bytecode-green-p1fix3.txt` 8/8; cùng tiến trình với S2 cài và tài liệu `reg-s2-installed-fix-stdin.txt` 12/12 |
| V29, V30 trên chính gói dev3 | gói dev3 | `pkg-red-dev3-V29-s2-bytecode.txt`, `pkg-red-dev3-V30-s2-docs.txt`: cả hai FAIL đúng lý do |
| Probe của Codex, chỉ đổi đường dẫn wheel + version | wheel dev4, venv sạch | `D:/OneCrewRuns/v24/codex-probe-dev4b/bytecode-result.json`: `before_problems []`, `cache_verdict differs`, **`marker_created false`, `entrypoint_exit null`** (dev3: `true`, `0`). Thư mục `codex-probe-dev4` là lượt sai đường dẫn wheel (so với RECORD dev3), không tính |
| Hồi quy mọi module `tests/test_v24_*` | `4f03e54`, `wf-v24` sạch | `reg-v24-all-4f03e54.txt`: **259/259 đạt, 0 skip** (02:43:40–03:18:06) |
| Kiểm từ gói | gói dev4 | `pkg-verify-2.4.0.dev4.txt` **30/30** (V1–V16 hồi quy 2.3, V17–V30 năm mốc; V29 19,5 s, V30 đạt); `pkg-wrapper-2.4.0.dev4.txt` `DAT` (task đầu tiên 25/25, alpha 5/5); chạy lại cùng thư mục `KHONG DAT` exit 2 (đúng thiết kế); `SHA256SUMS` 62/62 khớp (`pkg-run-2.4.0.dev4.txt`) |

Lượt hồi quy trên cây đang sửa (`reg-v24-all-p1fix3.txt`, 255/256) không dùng làm bằng chứng: tài liệu, bộ kiểm gói và version đã đổi trong lúc nó chạy. Lỗi duy nhất của lượt đó là `test_v24_s2_installed` (bản fix không được đổi version), có từ khi nâng lên dev3: test chỉ đổi version khi `pyproject.toml` ghi đúng `2.4.0.dev1`; đã sửa ở `0b4f539` (regex thay mọi dòng version).

Không chạy: provider/model thật (không cần cho hai finding); POSIX.

### 9.4 Gói dev4

`D:/OneCrewRuns/v24/pkg/onecrew-2.4.0.dev4-beta` — snapshot `4f03e543118d4795578f5e90d8f4b7b36acbbb54`, version `2.4.0.dev4`, wheel `onecrew-2.4.0.dev4-py3-none-any.whl`
SHA256 `8fa0dfde7698ca135dc591989e2c923b4ce4eb3b0a318c3f62322af90d3c8587`. Dựng bằng `D:/OneCrewRuns/wf-dev-tools/v24/run_final_package.sh 4f03e54 2.4.0.dev4` trong worktree tách `wf-v24-final` (02:43:42). Gói dev3 giữ nguyên để truy vết.

Tài liệu đồng bộ trong chính gói: `docs/limits-final.md` (mỗi mục = `docs/limits-<mốc>.md`, kiểm bằng V30), `docs/limits-s2.md` và `docs/HUONG-DAN-SUPPORT.vi.md` (quy tắc `.pyc`), README (mục Giới hạn = `limits-final.md`, version/commit/wheel đúng manifest, câu review trỏ dòng đầu Giới hạn), `docs/CHANGELOG.md` (dev4), báo cáo và hợp đồng ở bản của snapshot (mục này được thêm sau snapshot; xem bản checkout).

Lệnh thử (PowerShell, terminal của chủ):

```
powershell -ExecutionPolicy Bypass -File "D:\OneCrewRuns\v24\pkg\onecrew-2.4.0.dev4-beta\verify\thu-goi.ps1"
```

Chạy xong thấy dòng `DAT: goi 2.4.0.dev4 ... 30/30 buoc ...` là đạt.

### 9.5 Gate 2.2 trên dev4

Gate snapshot 2.2 trên `4f03e54` (`D:/OneCrewRuns/wf-dev-tools/v24/run_gate.sh`, 02/11 03:18:18–06:02:28, chạy một mình; output `D:/OneCrewRuns/v24/gates-tmp/wf-snapshot-gate-20261102-4f03e54`, log `D:/OneCrewRuns/v24/logs/gate-snapshot-4f03e54.txt`): **286/286 check thực thi đạt, `failed []`**, snapshot nguyên vẹn (`snapshot.intact true`, worktree tách sạch tại commit, fingerprint thư mục tài liệu và python `3.13.15`), kit-guard đạt. 217 lượt module riêng biệt: 2.097 test chạy, 2.097 đạt, 0 hỏng, 0 lỗi, 0 skip, 0 expected failure, 0 unexpected success (cộng theo log riêng biệt). Quyết định `refused`, `release_delivery false`, chỉ vì 23 khoảng trống nghiệm thu (13 partial, 10 blocked: provider thật, pilot, bản giao trước thật), trùng từng mục với gate `61862e6`. Gate là bộ kiểm 2.2; test 2.4 chạy ở hồi quy §9.3 (259/259). Sổ hook thật không đổi trong lượt gate (`8d339faddcf7881…` trước và sau).

### 9.6 Cách ly

Mọi lượt dùng `TEMP`, `LOCALAPPDATA`, `APPDATA` dưới `D:/OneCrewRuns/v24/tmp-int` (hồi quy), thư mục của từng bước kiểm gói, hoặc `D:/OneCrewRuns/v24/gates-tmp` (gate). SHA256 sổ hook thật `8ecf0fda5097d18…` bằng nhau trước và sau mỗi lượt (log ghi). Không đụng `wf-v23`, 2.2, runtime đang dùng, `state-v2-real`; không push, không tag; không gọi provider/model.

## 10. Review Codex trên dev4 → dev5 (02/11)

Mốc Codex review: snapshot `4f03e54`, `2.4.0.dev4`, gói `D:/OneCrewRuns/v24/pkg/onecrew-2.4.0.dev4-beta`, wheel `8fa0dfde7698ca135dc591989e2c923b4ce4eb3b0a318c3f62322af90d3c8587`. Bằng chứng của Codex: `D:/OneCrewRuns/codex-dev4-review-af11587c/` (`rollback_caller_probe.py` → `rollback-caller-result.json`: `all_proven true`, `marker_created true`, `reader_pair[0].problems []`; `rollback_race_probe.py` → `rollback-race-result.json`: `guard_problems []`, `marker_after_classifier true`). Phép thử của Codex dùng wheel/process/SQLite thật, giả feedback/quyền/lease, dừng trước khi ghi hook; không phải rollback trên runtime thật. Gói dev4 giữ nguyên, không sửa.

### 10.1 Việc local còn thiếu (lập đầu lượt, từ hợp đồng §2 và finding)

| Việc local | Tiêu chí hoàn tất | Bằng chứng |
|---|---|---|
| P1: bytecode bị thay sau phép kiểm chạy khi quay lui | Bước đọc sổ và phân loại sự kiện của rollback không thực thi `.pyc` bị thay; runtime cũ nguyên vẹn vẫn đọc/phân loại; thiếu câu trả lời không thành đường chạy; phép kiểm trước khi ghi hook từ chối | `reg-p1rb-red-final-a0ac49d.txt` 4/14 đỏ (marker) → `reg-p1rb-green2-p1rb-fix1.txt` 14/14; V31 FAIL trên gói dev4, đạt trên gói dev5; probe Codex trên wheel dev5: `marker_created false` |
| Cùng lớp lỗi trực tiếp | Cùng cửa chạy chương trình của venv đã kiểm: bước đọc sổ khi diễn tập cài, recheck; `PYTHONPATH` của terminal không thay runtime đã kiểm | `test_drill_reader_never_loads_the_venv_caches`, `test_drill_reader_runs_the_checked_venv_not_a_package_on_pythonpath` (đỏ trên dev4, xanh); install drill và recheck đi qua cùng `_onecrew` |
| Hồi quy S2 và cả 2.4 (S1, A, B, C không đổi code nhưng snapshot đổi) | `tests/test_v24_*` đạt trên snapshot dev5 sạch | `reg-s2-group-p1rb-fix1.txt` 93/93 (checkout); `reg-v24-all-387d3cb.txt` **265/265, 0 skip** trên `387d3cb` sạch |
| Gói beta mới, kiểm từ artifact | Bước kiểm gói (thêm V31) đạt hết; script thử của chủ `DAT`; chạy lại cùng thư mục bị từ chối; `SHA256SUMS` khớp; tài liệu trong gói đồng bộ (V30) | `pkg-verify-2.4.0.dev5.txt` **31/31**; `pkg-wrapper-2.4.0.dev5.txt` `DAT`; chạy lại cùng thư mục `KHONG DAT` exit 2; `SHA256SUMS` 62/62 (`pkg-run-2.4.0.dev5.txt`) |
| Wheel cuối trong venv sạch, đường dẫn có khoảng trắng | Phản chứng và đối chứng từ wheel; module origin, entrypoint, version, hash; không dùng nguồn checkout | `codex-probes-dev5.txt`: SHA256 wheel = manifest; `onecrew` nạp từ `D:/OneCrewRuns/v24/codex probe dev5/venv/Lib/site-packages`; `onecrew --version` = `2.4.0.dev5`; ba probe của Codex (bản sao không đổi) như §10.4 |
| Gate 2.2 trên snapshot cuối | Mọi check thực thi đạt; `refused` chỉ vì các khoảng trống nghiệm thu đã biết, đối chiếu từng mục | §10.6 |
| Hồ sơ | README, giới hạn, hướng dẫn, changelog trong gói; báo cáo/hợp đồng/wiki sau snapshot gắn hash gói | mục này, hợp đồng §7, wiki CURRENT/LESSONS |

### 10.2 Finding

| Finding | Nguyên nhân | Sửa (file:line ở snapshot dev5) | Phản chứng đỏ trước → xanh sau |
|---|---|---|---|
| P1 (S2) bytecode bị thay sau phép kiểm chạy khi quay lui | `_old_runtime` so `.pyc` của runtime cũ, rồi `_read_check` (`onecrew compat scan`, `plan show`, `engine …`) và `event_classes` chạy runtime cũ với `__pycache__` của venv. Chỉ lần chạy `onecrew --version` của identity có thư mục bytecode trống riêng (dev4). Cùng lớp: `_onecrew` kế thừa mọi biến của terminal, nên một `PYTHONPATH` làm bước đọc sổ nạp onecrew khác runtime đã kiểm | `onecrew/v2/hotfix.py`: `checked_run` :174–188, `entry_run` dùng nó :191–196, `_onecrew` (bước đọc sổ khi diễn tập, recheck) :445–448, `event_classes` (`-I -B -X pycache_prefix`) :455–459. Test: `tests/test_v24_s2_bytecode.py` :166–270. Bộ kiểm gói: `V31_PROBE` :1499, `v31_rollback_bytecode` :1564 (`docs/v24/tools/verify_milestone.py`) | Venv thật (wheel của checkout, pip), qua caller `_rollback` thật trên sổ thật có một task ghi sau khi chuyển; giả: feedback, quyền, tra bản ghi, lease, sự kiện cuối; `safe_point` dừng trước khi ghi hook (như Codex). Đỏ trên `hotfix.py` của `a0ac49d` (= dev4) với file test cuối: 4/14 hỏng đúng vì marker (bước đọc sổ, `PYTHONPATH`, bước phân loại, caller); 3 đối chứng và 7 ca dev4 đạt (`reg-p1rb-red-final-a0ac49d.txt`). Xanh 14/14 (`reg-p1rb-green2-p1rb-fix1.txt`). V31 trên chính gói dev4: FAIL `DEFECT (Codex dev4 P1)` (`pkg-red-dev4-V31-s2-rollback-bytecode.txt`) |

### 10.3 Hành vi mới

- Mọi chương trình của venv đã kiểm mà `hotfix` chạy (`onecrew --version` của identity, bước đọc sổ khi diễn tập cài/quay lui và recheck, bước phân loại sự kiện) chạy trong `checked_run`: bytecode chỉ từ một thư mục trống riêng (`PYTHONPYCACHEPREFIX`; lần chạy `-I` của bước phân loại dùng `-X pycache_prefix` và `-B`, vì `-I` bỏ qua biến `PYTHON*`), không ghi bytecode, không nhận biến `PYTHON*` của terminal; đầu ra `utf-8` (đúng cách `run` đọc). Thư mục bị xóa sau khi chạy.
- `.pyc` bị thay ngay sau phép so không chạy; các chương trình đó biên dịch nguồn đã kiểm. Phép kiểm ngay trước khi ghi hook (`_old_runtime` trong `check()`) thấy `.pyc` bị thay và từ chối: "rollback refused, nothing switched".
- Quyền, dữ liệu và trạng thái: không đổi đường nào của quyền hay sổ; runtime nguyên vẹn vẫn đọc và phân loại được (đối chứng); bản ghi quay lui nêu đúng việc đã làm (drill đã đọc nguồn đã kiểm; từ chối trước khi ghi hook nếu cache đổi).
- Giới hạn: nguồn `.py` bị sửa giữa phép so và lúc chạy chỉ bị bắt ở phép kiểm kế tiếp (trước khi ghi hook). Sau khi hook đã chuyển, hook chạy runtime như Python thường chạy (có `__pycache__`), không được canh liên tục. Python gốc và thư viện chuẩn vẫn được tin.
- Đính chính §9.2: dòng "danh sách dài đi qua file tạm" mô tả bản trung gian; snapshot dev4 (và dev5) đưa danh sách cache qua stdin của trình thông dịch, không qua file.

### 10.4 Kiểm

Do Claude chạy trong lượt này (log dưới `D:/OneCrewRuns/v24/logs/`):

| Kiểm | Snapshot / artifact | Kết quả |
|---|---|---|
| Phản chứng P1, code dev4 | `a0ac49d` (code = `4f03e54`) + test mới | `reg-p1rb-red-final-a0ac49d.txt`: 4 hỏng / 14, đều vì file đánh dấu được tạo |
| Phản chứng P1, sau sửa | checkout | `reg-p1rb-green2-p1rb-fix1.txt` 14/14 |
| Nhóm S2 + tài liệu | checkout (code = snapshot) | `reg-s2-group-p1rb-fix1.txt` 93/93 (07:32–07:47) |
| V31 trên chính gói dev4 | gói dev4, bộ kiểm có V31 | `pkg-red-dev4-V31-s2-rollback-bytecode.txt`: FAIL đúng lý do, đối chứng đạt |
| Hồi quy mọi `tests/test_v24_*` | `387d3cb`, `wf-v24` sạch | `reg-v24-all-387d3cb.txt`: **265/265, 0 skip** (07:48–08:22) |
| Kiểm từ gói | gói dev5 | **31/31** (V29 20,7 s, V30, V31 25,0 s đạt); script thử `DAT` (task đầu tiên 25/25, alpha 5/5); chạy lại cùng thư mục `KHONG DAT` exit 2; `SHA256SUMS` 62/62 |
| Probe Codex trên wheel dev5, venv sạch có khoảng trắng | wheel `6ed8ab8a…` | `codex-probes-dev5.txt`, `D:/OneCrewRuns/v24/codex probe dev5/`: rollback caller `all_proven true`, **`marker_created false`**, `reader_pair[0].problems []`, dừng ở điểm an toàn; race `guard_problems []`, **`marker_after_classifier false`**, phép kiểm kế tiếp từ chối `compat.pyc`; probe bytecode dev3 `marker_created false`, `entrypoint_exit null` |

Chuỗi `real_paths` trong `rollback-caller-result.json` ghi "installed dev4 wheel": đó là chữ cố định trong script của Codex (giữ nguyên), wheel thật là dev5 (dòng `origin`/`version` của log). Không chạy: provider/model thật; POSIX; rollback trên runtime/hook thật.

### 10.5 Gói dev5

`D:/OneCrewRuns/v24/pkg/onecrew-2.4.0.dev5-beta` — snapshot `387d3cbff8e74bebc760a2a178d95b58273f1d2e`, version `2.4.0.dev5`, wheel `onecrew-2.4.0.dev5-py3-none-any.whl`
SHA256 `6ed8ab8a8568d271d4fd7d4b89f7bbb5ed98c8b387898f109c2f9b73ae409655`. Dựng bằng `D:/OneCrewRuns/wf-dev-tools/v24/run_final_package.sh 387d3cb 2.4.0.dev5` trong worktree tách `wf-v24-final` (07:48). Gói dev4 giữ nguyên.

Tài liệu đồng bộ trong gói: `docs/limits-s2.md`, `docs/limits-final.md` (dòng "Ranh giới tin cậy": mọi chương trình của venv đã kiểm đọc bytecode từ thư mục trống riêng, giới hạn còn lại; dòng đầu: trạng thái review dev4/dev5; V30 kiểm khớp), `docs/HUONG-DAN-SUPPORT.vi.md`, README (version, commit, wheel theo manifest), `docs/CHANGELOG.md` (dev5). Mục này và nhật ký hợp đồng viết sau snapshot, không có trong gói.

Lệnh thử (PowerShell, terminal của chủ; bản sao và sổ riêng trong thư mục kết quả mới):

```
powershell -ExecutionPolicy Bypass -File "D:/OneCrewRuns/v24/pkg/onecrew-2.4.0.dev5-beta/verify/thu-goi.ps1"
```

Chạy xong thấy dòng `DAT: goi 2.4.0.dev5 ... 31/31 buoc ...` là đạt.

### 10.6 Gate 2.2 trên dev5

Gate snapshot 2.2 trên `387d3cb` (`run_gate.sh`, 02/11 08:22:39–11:27:30; output `D:/OneCrewRuns/v24/gates-tmp/wf-snapshot-gate-20261102-387d3cb`, log `D:/OneCrewRuns/v24/logs/gate-snapshot-387d3cb.txt`): **286/286 check thực thi đạt, `failed 0`, `receipted 286`**, snapshot nguyên vẹn (`intact true`, python `3.13.15`). Đếm cùng một cách trên hai thư mục gate (mọi file có dòng `Ran`): dev5 219 log, 2.107 test, 0 hỏng, 0 lỗi, 0 skip; dev4 (`4f03e54`) cũng 219 log, 2.107 test (báo cáo §9.5 ghi 217/2.097 theo cách gộp log trùng; con số ở đây so cùng cách đếm). Quyết định `refused`, `release_delivery false`, `pilot_passed false`, `owner_acceptance false`: **23 vấn đề trùng từng mục với gate dev4** (so chuỗi `problems` của hai `decision.json`: bằng nhau), tức chỉ các khoảng trống nghiệm thu đã biết (provider thật, pilot, bản giao trước thật), không có vấn đề mới. Lượt này chạy lâu hơn dev4 (3 h 05 so với 2 h 44) vì chủ chọn dựng gói hotfix 2.3 song song (10:17–10:40); không test nào hỏng vì tải. Sổ hook thật không đổi (`8d339faddcf7881…` trước và sau).

### 10.7 Cách ly và điều kiện bên ngoài

Mọi lượt dùng `TEMP`, `LOCALAPPDATA`, `APPDATA` riêng (`D:/OneCrewRuns/v24/tmp-int`, thư mục từng bước kiểm gói, `D:/OneCrewRuns/v24/codex probe dev5`, `D:/OneCrewRuns/v24/gates-tmp`). SHA256 sổ hook thật `8d339faddcf7881…` bằng nhau trước và sau mọi lượt của dev5 (log ghi; lần đổi cuối 02:20:51, của phiên khác, §9). `wf-v23` vẫn ở `fe0a044`; không đụng 2.2, runtime đang dùng, `state-v2-real`; không push, không tag; không gọi provider/model. Một tiến trình python (pid 21388, tạo 03:57:50, chờ file `D:/OneCrewRuns/v24/gate`) có từ trước lượt này; không rõ của lượt nào, không dừng nó.

Điều kiện bên ngoài còn lại (không thuộc quyền lượt này): Codex review dev5; quyết định phát hành; thử với model thật; pilot; nghiệm thu của chủ. Các khoảng trống nghiệm thu của gate đối chiếu ở §10.6.

### 10.8 Ghi nhận review Codex trên dev5 (02/11, do chủ dự án chuyển lại)

Codex đã kiểm: gói dev5 62/62 hash khớp; gate 286/286 check không lỗi, 23 mục `refused` giống dev4; nội dung từng file trong wheel của gate và wheel bàn giao giống nhau; log hồi quy 265 test OK, kiểm gói 31/31; ba phản chứng độc lập trên wheel dev5 chặn lỗi bytecode/rollback cũ; snapshot code không đổi sau lần kiểm, HEAD sau snapshot chỉ cập nhật hồ sơ.

Kết luận của Codex, đúng phạm vi: P1 rollback của dev4 đã khép trong các kịch bản được kiểm; chưa phát hiện blocker mới trong phần thay đổi được review; dev5 có thể bàn giao để thử cách ly. Đây **không** phải nghiệm thu toàn bộ sản phẩm, kiểm provider thật hay chứng nhận an toàn tuyệt đối. Gói dev5 (`docs/limits-final.md` trong gói ghi "dev5 chưa được Codex review lại" lúc dựng) giữ nguyên, không sửa đè; điểm vào thử `docs/v24/BAT-DAU-THU-2.4.0.dev5.vi.md` (ngoài gói) ghi kết luận này và các giới hạn: dev5 chưa có xác thực API của hotfix 2.3 (`plan advise --auth api` chưa hỗ trợ), không dùng dev5 nâng runtime SDK, hotfix 2.3 tích hợp bằng task riêng, không cherry-pick `a3d6a15` trong lượt này.

### 10.9 Review Codex trên hướng dẫn thử (02/11): 2 P2 + 1 P3, đã sửa

| Finding | Sửa | Bằng chứng |
|---|---|---|
| P2 bài thủ công chưa cách ly registry (`init` ghi `%LOCALAPPDATA%\OneCrew\hook-projects.json` thật; `where.py` chọn theo `LOCALAPPDATA`) | script ngoài gói `thu-tay-dev5/chuan-bi.ps1` (đổi `LOCALAPPDATA/APPDATA/TEMP/TMP` của cửa sổ sang `<lab>/env`, venv thử, bản sao project độc lập, `init`, `doctor`, kiểm registry thử/thật), `vao-moi-truong.ps1` (cửa sổ mới), `don-dep.ps1`; nguồn `docs/v24/tools/thu-tay-dev5/`; hướng dẫn §2, §5 | `logs/guide-drill-chuan-bi.txt` 14:06: `DAT`, registry thử trong lab, registry thật giữ hash `aacad058…`, cửa sổ mới `doctor` 0 FAIL, dọn dẹp `DAT` |
| P2 lệnh quay về không phân biệt cài lại venv với quay lui sau S2 (`hotfix.py` so runtime cũ với mốc trước khi quay lui) | hướng dẫn §5 tách A (chỉ cài wheel: pip đè dev10) và B (đã `switched`: chỉ `support rollback`, đọc hook/`support status`; từ chối là kết quả đúng, không cài đè); bài 6 ghi "thủ công chưa sẵn sàng" | thành công: V22 của bài 1 chủ (kế thừa; `--only V22` không chạy được vì cần V21); từ chối: V31 chạy riêng `logs/pkg-only-V31-s2-rollback-bytecode-dev5-guide.txt` `partial-pass 4/4` |
| P3 tên thư mục kết quả | §3: `D:\OneCrewRuns\v24 thu cua anh 2.4.0.dev5 <yyyyMMdd-HHmmss>` như `thu-goi.ps1` in ở dòng `thu muc ket qua:` | đối chiếu `thu_goi.ps1` và lượt chạy của chủ 13:20 |

Không chạy lại gate, hồi quy hay bài 1; gói dev5 và kết quả bài 1 của chủ giữ nguyên (`SHA256SUMS` 62/62 sau lượt).

### 10.10 Review Codex bộ script thử (02/11): 1 P1 + 2 P2, đã sửa

| Finding | Trước (`c17e465`) | Sửa | Bằng chứng |
|---|---|---|---|
| P1 `don-dep.ps1` xóa thư mục không phải lab (chỉ kiểm có `env\LocalAppData`, rồi `Remove-Item -Recurse` cả `-Lab`; Codex: thư mục có `keep.txt` bị xóa, `DAT`) | `don-dep.ps1:8,12` | Dấu sở hữu do `chuan-bi.ps1` ghi: `<lab>\.lab-thu-dev5.json` (đường dẫn tuyệt đối + nonce) **và** mục cùng nonce trong `thu-tay-dev5\labs.json`; `don-dep.ps1` chuẩn hóa đường dẫn, từ chối: trong/chứa gói, nông hơn 3 mức, link/junction ở lab hay cha, thiếu/khác dấu sở hữu, không có mục `labs.json`, sai cấu trúc, cửa sổ đang ở trong lab; sau xóa kiểm đã mất và registry thật giữ hash; không bao giờ tự tạo dấu sở hữu; `vao-moi-truong.ps1` cũng chỉ nhận lab có dấu sở hữu | `thu-tay-tests.ps1`: cũ **2/11**, mới **11/11** (`logs/thu-tay-tests-old.txt`, `-new.txt`; `D:/OneCrewRuns/v24/thu-tay-tests new/results.json`): ca giống lab/dấu giả/nông/trong gói/junction/cửa sổ trong lab đều `KHONG DAT (khong xoa gi)` mã 2, `keep.txt` còn; lab thật dọn `DAT`, lần hai từ chối |
| P2 hướng dẫn chạy `powershell -File chuan-bi.ps1` (tiến trình con) rồi bảo "cùng cửa sổ" (Codex: `PARENT_EXE_DEFINED=False`) | hướng dẫn §2; `chuan-bi.ps1` dùng `exit` nên không dot-source được | `chuan-bi.ps1` và `vao-moi-truong.ps1` viết để **dot-source**, không `exit` (try/catch, `return`), đặt `$labOk` và các biến trong cửa sổ gọi; thất bại → `KHONG DAT`, biến bị xóa, cửa sổ không đóng; `chuan-bi` kết thúc bằng dot-source `vao-moi-truong` (kiểm lại lab) ; hướng dẫn §2 dán `. "…\chuan-bi.ps1"`, hoặc một lệnh `powershell -NoExit … -Command ". '…'"` mở shell lồng đã ở trong lab | test `p2_dot_source_chuan_bi_leaves_the_window_in_the_lab`, `p2_new_window_dot_source_vao_then_harmless_report`, `p2_vao_refuses_a_folder_that_is_not_a_lab`; diễn tập shell lồng `-NoExit` (`logs/guide-drill-nested-noexit.txt`): `NESTED_LABOK=True`, `NESTED_EXE=True`, `NESTED_ENV=True` |
| P2 `vao-moi-truong.ps1:18` xóa `CLAUDECODE`, `CLAUDE_CODE_CHILD_SESSION` (dấu hiệu phiên AI của `ownership.py`) | marker bị xóa (Codex: `AI_MARKER_AFTER=False`) | Bỏ dòng đó; script chỉ đổi 4 biến thư mục (và nhớ `ONECREW_LAB_REAL_LOCALAPPDATA` để đối chiếu) | test `p2_ai_markers_kept_and_owner_verb_refused` (marker giả `fixture-marker` giữ nguyên; `support confirm` trên sổ thử bị từ chối "runs inside an AI tool session", mã 2, trước khi ghi); diễn tập shell lồng: `MARKER=fixture-marker` |

Phần giả trong test: giá trị marker AI và các thư mục "giống lab"; phần thật: tiến trình PowerShell con, filesystem, `onecrew init/doctor/support report/support confirm` của wheel dev5 trên sổ thử. Không chạy lại gate/hồi quy/bài 1; gói dev5 `SHA256SUMS` 62/62 và kết quả bài 1 của chủ (`…20261102-132042`) không đổi; registry thật `aacad058…` giữ hash trước–sau mỗi lượt (quan sát hiện tại, không suy ra "không đổi suốt lịch sử"). Nguồn script: `docs/v24/tools/thu-tay-dev5/` (kèm `thu-tay-tests.ps1`), bản ngoài gói `D:/OneCrewRuns/v24/pkg/thu-tay-dev5/`.
