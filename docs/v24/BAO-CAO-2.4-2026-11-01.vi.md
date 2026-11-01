# OneCrew 2.4 — báo cáo bàn giao 01/11/2026

Người viết: Claude (đầu mối 2.4), 01/11/2026, theo chỉ thị người dùng ngày 01/11 ~02:10 ("Tiếp quản và hoàn thành toàn bộ feature đã chốt của OneCrew 2.4 theo roadmap chung: 2.4-S1, S2, A, B, C"). Phạm vi, thiết kế và truy vết đầy đủ: [hợp đồng 2.4](HOP-DONG-2.4.vi.md) §3–§8. Đây là **tự kiểm của tác giả và review của agent độc lập**: chưa có Codex review, chưa có nghiệm thu của chủ sở hữu, chưa phát hành. Mọi kiểm dùng `claude` giả và sổ tạm, không có lượt model thật.

**Tóm tắt (quyết định trước):**
- Cả năm mốc đã có code và test trên một cây (`bde505b`, rồi `7767982`); mỗi mốc có review độc lập, ca review được viết thành test đỏ trước khi sửa.
- Gói thử đã kiểm: S1 (19/19 bước), S2 (22/22 bước). Gói cuối gồm cả năm mốc: <!-- v24:final-package -->. Gate 2.2: <!-- v24:gate -->.
- Hồi quy tích hợp trên `bde505b`: <!-- v24:TODO kết quả reg-int-v24-bde505b, reg-int-aff-bde505b -->.
- Việc của chủ sở hữu: cho Codex review gói cuối; quyết định phát hành; cho thử với model thật nếu muốn; nghiệm thu. Lượt này không push, không tag, không nâng runtime đang dùng.

Log nằm ở `D:\OneCrewRuns\v24\logs\` (ghi tên ngắn, bỏ `reg-` và `.txt`); review ở `D:\OneCrewRuns\v24\review-*\`.

## 1. Kết quả từng mốc

| Mốc | Người dùng được gì (một dòng) | Trạng thái | Bằng chứng (file : test : receipt) |
|---|---|---|---|
| S1 | Báo lỗi một lần, nhận một mã `FB-…`, có hồ sơ chẩn đoán trên máy; sổ hỏng vẫn báo được | đã có code + test + gói thử (gói S1, S2, gói cuối) | `onecrew/v2/support.py`, `diagnostics.py`, `support_spool.py` : `test_v24_s1_*` (47 test) : gói S1 V17–V19 (`D:\OneCrewRuns\v24\pkg-trial\work-verify\verify\verify-report.json`) |
| S2 | Bản vá OneCrew được gắn đúng định danh, cài vào venv mới ở điểm an toàn, kiểm lại lỗi gốc, tiếp tục việc cũ; thiếu quyền thì dừng đúng chỗ | đã có code + test + gói thử (gói S2, gói cuối) | `onecrew/v2/hotfix.py` : `test_v24_s2_apply` (12), `test_v24_s2_installed` (1) : gói S2 V20–V22 (`…\work-verify-s2\verify-report.json`) |
| A | Worker xin đọc thêm file trong quyền, từng trang, trên nguồn đã ghim; không nhét cả repo vào prompt | đã có code + test; gói: chỉ gói cuối | `onecrew/v2/source_tools.py`, `authority.py` (`read`) : `test_v24_a_sources` (18), `test_v24_a_review` (17), `test_v24_a_installed` (1) : `aff-test_v24_a_*-br` (`c5b78e9`); gói cuối <!-- v24:final-package --> |
| B | Node nhận phần tri thức đã đổi (delta) ở điểm an toàn; kết quả dựng trên tri thức đã thu hồi không được công bố như hiện hành | đã có code + test; gói: chỉ gói cuối | `onecrew/v2/working_context.py` : `test_v24_b_context` (21), `test_v24_b_installed` (1) : `aff-test_v24_b_*-br` (`c5b78e9`); gói cuối <!-- v24:final-package --> |
| C | Thẻ bước 0 nói đủ hay chưa đủ để làm; engine ghi vì sao chạy song song, tiếp tục, chạy kiểm không cần model hay chờ | đã có code + test; gói: chỉ gói cuối | `onecrew/v2/execution_mode.py`, `step0.py`, `proposal.py`, `survey.py` : `test_v24_c_*` (52) : `c-after-review-extra-fix1` (63 OK, `21b6a56`); gói cuối <!-- v24:final-package --> |

Giới hạn chung của cả năm mốc: chưa có model thật; capability mới đều opt-in, root cũ chạy như 2.3; giới hạn từng mốc ở `docs/v24/limits-s1.md`, `limits-s2.md` và hướng dẫn `docs/v24/HUONG-DAN-*.vi.md` §"Giới hạn".

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
| Gói cuối | <!-- v24:final-package --> | <!-- v24:final-package --> | <!-- v24:final-package --> | |

Cả ba gói mang version `2.4.0.dev1`; phân biệt bằng commit và sha wheel (hợp đồng §8). Mỗi gói có `wheel\previous\onecrew-2.3.0.dev10-py3-none-any.whl` (SHA256 `8ab065c3bc6d2863888314952e3743b031d44ea44c1e92cd740abba385a1b4f7`, giống từng byte gói beta 2.3) và `wheel\regression\onecrew-2.2.0.dev18-py3-none-any.whl` (`0346577e…`).

**Thử cả gói** (kiểm hash, bộ kiểm, task đầu tiên, luồng alpha trên thư mục mới với sổ tạm; đạt khi in `DAT:` và thoát 0):

```bash
powershell -ExecutionPolicy Bypass -File "<!-- v24:final-package -->/verify/thu-goi.ps1"
```

**Cài vào venv thử** (đường dẫn có dấu cách, không mạng), xem version:

```powershell
$py = "C:\Users\NUC\AppData\Local\Programs\Python\Python313\python.exe"; $pkg = "<!-- v24:final-package -->"
$venv = "D:\OneCrewRuns\v24 thu 2.4\venv"; & $py -m venv $venv; & "$venv\Scripts\python.exe" -I -m pip install --no-index --no-build-isolation "$pkg\wheel\onecrew-2.4.0.dev1-py3-none-any.whl"
& "$venv\Scripts\onecrew.exe" --version
```

**Quay về 2.3.0.dev10:** `& "$venv\Scripts\python.exe" -I -m pip install --no-index --no-build-isolation --force-reinstall "$pkg\wheel\previous\onecrew-2.3.0.dev10-py3-none-any.whl"`. Đã kiểm: wheel 2.2.0.dev18 và 2.3.0.dev10 thật đọc được sổ có bản ghi S1 (`test_v24_s1_oldreaders`). Chưa kiểm: bản cũ đọc bản ghi S2, `knowledge.delivered`, `workflow.mode`. Root khai `authority.read` bị 2.3 từ chối. Trước khi quay về với sổ thật, chạy `compat scan` của bản cũ trên bản sao sổ.

## 4. Số test đạt/fail/skip/expected failure và giới hạn thực tế

**Test 2.4** (số test đếm bằng `grep "def test_"`; tổng 170):

| File | Số test | Lượt gần nhất có ghi | Kết quả |
|---|---|---|---|
| `test_v24_a_sources` / `_a_review` / `_a_installed` | 18 / 17 / 1 | `aff-test_v24_a_*-br` (`c5b78e9`, cây sạch) | 18/18, 17/17, 1/1; 0 skip |
| `test_v24_b_context` / `_b_installed` | 21 / 1 | `aff-test_v24_b_*-br` (`c5b78e9`) | 21/21, 1/1; 0 skip |
| `test_v24_c_execution_mode` / `_c_review` / `_c_step0_card` | 15 / 24 / 13 | `c-after-review-extra-fix1` (`21b6a56`, cây sạch): 63 test OK | log không ghi danh sách module, nên chưa có số riêng từng file: <!-- v24:TODO số riêng từng file C từ reg-int-v24-bde505b --> |
| `test_v24_s1_intake` / `_bundle` / `_spool` / `_status` / `_review` / `_installed` / `_oldreaders` | 8 / 9 / 5 / 7 / 15 / 2 / 1 | `s1all-h6` (68 OK), `s2rest-h6` (58 OK), `s2inst-h6` (1 OK), chạy trên cây đang sửa trước commit `58c740d` | chưa có lượt sạch trên commit đã chốt: <!-- v24:TODO số riêng từng file S từ reg-int-v24-bde505b --> |
| `test_v24_s2_apply` / `_s2_installed` | 12 / 1 | như trên | như trên |
| Tất cả `tests/test_v24_*` trên `bde505b` | 170 | `int-v24-bde505b` | <!-- v24:TODO Ran/OK/FAILED/skip --> |

**Module 2.3/2.2 bị ảnh hưởng:**

| Lượt | Code | Kết quả |
|---|---|---|
| 11 module A/B (`aff-*-br`: a1/a2 knowledge, review_dev7, candidate_handoff, engine, engine_managed, …) | `c5b78e9` | đạt hết; 1 skip trong `test_v23_review_dev7` (skip có điều kiện môi trường trong test; log không ghi lý do) |
| 22 module ở `aff-*-b1` | `58b863f` | đạt hết (cùng 1 skip) |
| 17 module ở `aff-*-a2` | `26a86e7` | đạt, trừ 1 lỗi có từ trước trong `test_search_recovery` (dưới) |
| hồi quy ảnh hưởng của C (`c-affected-t1`) | `a67bb19` | 315/315 |
| `finalB-8577db4` / `finalA-8577db4` / `g2l2-58c740d` | `8577db4`, `58c740d` | 186/186; 117 với 1 hỏng; 100 với 1 hỏng (cùng một test có từ trước) |
| hồi quy sau gộp C (`merge-c-65ef023`) | `65ef023` | 72/72 |
| module ảnh hưởng trên `bde505b` (`int-aff-bde505b`) | `bde505b` | <!-- v24:TODO Ran/OK/FAILED/skip --> |

**Hỏng có từ trước, không do 2.4, không sửa:**
- `tests.test_g2_install.PackagingTests.test_the_templates_are_package_data_and_the_examples_keep_a_copy`: ghim `version = "2.2.0.dev3"` trong mẫu; hỏng cả trên `913e798`, trước mọi code S1 (`g2tpl-base`). Không có U1 cho test này.
- `tests.test_search_recovery.CTSCheckpointContinuationTests.test_C_real_build_delivers_a_valid_page_via_minimal_recovery_trim`: `PromptBudgetError` dưới trần Kiro 15 000; hỏng cả trên bản sao `5c34f4a` (`v24a-sr-base`).
- Expected failure: không lượt 2.4 nào báo `expected failures`.

**Gate snapshot 2.2:** <!-- v24:gate -->

**U1 test hạn root:** trên `bde505b` dưới tải, test cũ hỏng 4/4 (`D:\OneCrewRuns\v24\probe-mv\bde505b\probe-mv.json`); sau U1-DEADLINE-1: 2/2 (`deadline-green1-dirty`, `-green2-dirty`) và cả module 4/4 (`deadline-module-dirty`).

## 5. Kết quả đo

Chỉ số quan sát được; không có so sánh trước/sau trên cùng điều kiện, nên không có kết luận nhanh hơn hay chậm hơn.

| Số đo | Giá trị | Nguồn | Ghi chú |
|---|---|---|---|
| Thao tác người dùng để báo một lỗi (S1) | 1 lệnh `onecrew support report` | `docs/v24/HUONG-DAN-SUPPORT.vi.md` §1; gói V17 | đếm theo thiết kế lệnh, không đo trên người dùng thật |
| Thời gian bước báo lỗi + hồ sơ + xem (V17) | 6,8 s / 5,5 s / 2,6 s | gói S1, script thử S1, gói S2 (verify-report) | máy dùng chung, tải khác nhau giữa các lượt |
| Spool khi sổ hỏng (V18) | 4,3 s / 2,6 s / 2,3 s | như trên | |
| Chuỗi bản vá S2: V20 / V21 / V22 | 33,6 s / 30,5 s / 13,0 s | `pkg-trial\work-verify-s2\verify-report.json` | gồm dựng repo tạm, build wheel, venv; `claude` giả |
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
- `docs/v24/limits-s1.md` (và phần S1 của `limits-final.md` ở `a039d1f`) còn ghi "bản cũ đọc sổ có báo cáo chưa được diễn tập" và lọc bằng `display_core.safe`; cả hai đã cũ sau `b6b300c` (`test_v24_s1_oldreaders`, bộ lọc rộng hơn).
- Manifest gói ghi `ships_paging: false` cố định (`docs/v24/tools/build_milestone.py`), dù wheel từ khi có A mang `onecrew.paging`; bước V3 của gói cuối vẫn kiểm nguồn `onecrew.paging` qua `MILESTONE_MODULES['A']` (đọc ở `a039d1f`).
- Lượt sạch của test S1/S2 trên commit đã chốt: chờ hồi quy tích hợp (§4).
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
