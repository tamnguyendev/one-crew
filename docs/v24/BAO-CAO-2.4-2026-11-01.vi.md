# OneCrew 2.4 — báo cáo bàn giao 01/11/2026

Người viết: Claude (đầu mối 2.4), 01/11/2026, theo chỉ thị người dùng ngày 01/11 ~02:10 ("Tiếp quản và hoàn thành toàn bộ feature đã chốt của OneCrew 2.4 theo roadmap chung: 2.4-S1, S2, A, B, C"). Phạm vi, thiết kế và truy vết đầy đủ: [hợp đồng 2.4](HOP-DONG-2.4.vi.md) §3–§8. Đây là **tự kiểm của tác giả và review của agent độc lập**: chưa có Codex review, chưa có nghiệm thu của chủ sở hữu, chưa phát hành. Mọi kiểm dùng `claude` giả và sổ tạm, không có lượt model thật.

**Tóm tắt (quyết định trước):**
- Cả năm mốc đã có code và test trên một cây (gộp `bde505b`; snapshot cuối `61862e6`, version `2.4.0.dev2`); mỗi mốc có review độc lập, ca review được viết thành test đỏ trước khi sửa.
- Gói cuối gồm cả năm mốc: `D:\OneCrewRuns\v24\pkg\onecrew-2.4.0.dev2-beta` (wheel SHA256 `383df81d…`); kiểm từ gói 25/25 bước; script thử `DAT`/0 (bộ kiểm 25/25, task đầu tiên 25/25, luồng alpha 5/5). Gate 2.2 trên `61862e6`: 286/286 check thực thi đạt; `refused` chỉ vì 23 khoảng trống nghiệm thu, trùng danh sách beta 2.3 (§4).
- Hồi quy tích hợp trên `bde505b`: 170/170 test 2.4; 448 test của module 2.2/2.3 bị ảnh hưởng đạt, 1 skip.
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

**Gate snapshot 2.2** (bắt đầu 13:46:05 trên `61862e6`, log `gate-snapshot-61862e6`): 286/286 check thực thi đạt, `failed []` (2.097 test unittest trong 217 lượt module, 0 fail; gate đếm exit code nên không tách skip/expected failure); quyết định `refused` chỉ vì 23 khoảng trống nghiệm thu/phát hành (13 `acceptance-partial`, 10 `acceptance-blocked`; loại `release-evidence`/`acceptance-audit`/`external-pilot`), danh sách trùng hẳn với gate beta 2.3 dev10 `fb3333b` run 2 (so bằng release/testcase/kind): đòi chủ sở hữu chạy verb nghiệm thu, biên nhận phát hành thật và pilot ngoài; kit-guard `ok` với hai U1 2.4; chạy 13:46:05–16:39:35 (2 h 53, một mình); wheel dựng lại trong gate `304615a7…` khác wheel gói `383df81d…` vì builder không tái lập byte (đã biết từ 2.2), cùng code `61862e6`; hồ sơ `D:\OneCrewRuns\v24\gates-tmp\wf-snapshot-gate-20261101-61862e6\gate\decision.json`, log `gate-snapshot-61862e6`. Trong lúc gate chạy, sổ hook thật đổi lần hai lúc 14:08:57 (SHA256 `23ec9033…` → `8ecf0fda…`, thêm một dòng bản sao `d:\onecrewruns\copies\signsdk-dev10-thu-20261101` → `D:\OneCrewRuns\states\signsdk-dev10-thu-20261101`): là phiên khác thử dev10 trên bản sao, không phải lượt 2.4 (log gate không chạm registry, đường dẫn là bản sao dev10); không khôi phục.

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
