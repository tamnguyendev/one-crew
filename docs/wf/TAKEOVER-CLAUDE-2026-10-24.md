# Tiếp quản development từ Codex — Claude, 24/10/2026

Nhánh `codex/wf-development`, worktree `D:\TamNT\Workspace\11.OneCrew\wf-codex`. Điểm tiếp quản: `f2cc7f44` cộng phần chưa commit của Codex,
được chốt nguyên trạng thành `2bfc223` (sao lưu: `D:\OneCrewRuns\wf-codex-handoff-backup-20261024`). Không reset, không ghi đè; sổ thật,
worktree khác và job đang chạy không bị đụng. Không push, tag, publish; không approve/accept trên sổ thật; không gọi provider trả phí.

Trạng thái: **DEVELOPMENT trong phạm vi tự làm được đã đối chiếu và kiểm xong; các phần cần provider thật, pilot thật và nghiệm thu
của chủ sở hữu vẫn CHƯA KIỂM CHỨNG/BLOCKED.** Chưa có nghiệm thu sản phẩm. Đây là gói để Codex review tổng thể một lượt.

## 1. Những gì làm trong lượt này (commit trên `codex/wf-development`)

| Commit | Nội dung | Kiểm |
|---|---|---|
| `2bfc223` | Chốt nguyên trạng phần Codex chưa commit | — |
| `f5d22bd` | Reviewer trên candidate + luật tái dùng bằng chứng khép kín: `proof_mismatch` (họ proof, mốc, cây, plan_sha, revision, argv/config, trần thời gian chỉ được giảm), binding của wrapper phải bằng binding quan sát; typed support `candidate-reviewer-check` trong native learning; sửa lỗi thật: file alternates ghi text mode làm git đọc `objects\r` → mọi review candidate đều inconclusive trên Windows | `test_wf_candidate_reuse_counter` 9 (9 lỗi trước, 9/9 sau), `test_wf_candidate_reviewer` 4 (3 fail trước, 4/4 sau), họ candidate 32 OK |
| `ac9fd5c` | W15 review trên snapshot cố định (T04b/T01); W36 tự yêu cầu pause worker được quản lý khi finding giữ node đang chạy (T07b E16, T15c E7/E9); W37b dựng lại candidate sau crash giữa process đã settled và checkpoint từ bằng chứng bền (intent `dispatching` + base + `worker.result` của output bền), kết quả `failed` tách khỏi `unknown`; hook chặn an toàn khi cache holds cũ hơn sổ (`workflow-holds.json`); sửa `engine._input_blocks` (node tự chặn chính nó sau khi fail, lỗi có sẵn làm 3 test repair_tasks đỏ) | `test_wf_review_snapshot` 2, `test_wf_managed_hold` 2, `test_wf_managed_executor` +2, `test_wf_hook_holds_generation` 2; nhóm managed 20 OK, repair/failed_dependency/engine 18 OK, hook holds + finding_scope 17 OK |
| `a0d378e` | Giữ nguyên pin lịch sử R00 (hoàn `tests/wf_wheel.py`), helper `tests/wf_env.owner_terminal`; đăng ký 17 check vào registry development | `development_gate list`, `test_wf_development_kit` 8 OK |
| `d43bde1` | Ma trận bằng chứng theo từng [E] cho T40a, T04b, T15c, T15a → `complete`; FEATURE-SCOPE sinh từ registry; bỏ status.json cũ | — |
| `2e5a8e6` | T39 (chương trình chạy qua mốc với đúng 2 quyết định thường lệ): `wfkit/program_contract.py` (hợp đồng chương trình 03 §2.3, argv kit-guard ghim sha256, M5 owner-manual, decisions A8/A10), `wfkit/owner_actions.py` (đếm thao tác chủ sở hữu từ sổ + nhật ký chat, 03 §2.4), `tests/test_wf_program_transition.py` 3 ca; sửa lỗi có sẵn: boundary `typing.io`/`typing.re`, owner-manual không có Git, test bản cài chạy như terminal chủ sở hữu; test tree-id của trust fixes theo W09 | 7 OK; retention + packaging OK; 5 bộ bản cài 13 OK |
| `b5c6922`…`5e1309f` | T39 vào registry (R01, complete); manifest development đóng băng ở registry cuối (`eac1f3f` đóng băng sớm bị thu hồi ở `c16079e`, chưa lần chạy nào dựa vào nó) | freeze: 13 release, 269 pin |

Lỗi có sẵn trong bản Codex (`2bfc223`) đã phân loại bằng cách chạy lại trên worktree gốc trước khi sửa: 3 × `test_wf_repair_tasks` (code),
`test_wf_retention_integration` owner-manual không Git (code), `test_v2_trust_fixes` tree-id (test cũ hơn W09), `test_wf_installed_native` ×2
(boundary `typing.io` + marker phiên AI), `test_wf_installed_node_learning` (marker phiên AI). Không lỗi nào do lượt này gây ra.

## 2. Đối chiếu các mục dang dở trong handoff của Codex

| Mục | Kết quả |
|---|---|
| A. Candidate reviewer + reuse | Xong: reviewer chạy trên candidate với độc lập theo tác giả đề xuất và model của child thật, qua `ProviderCall` có ngân sách; `_reuse` kiểm đủ wrapper binding, họ proof, mốc, config, plan_sha, revision, artifact, trần thời gian; receipt của lệnh khác/noop không thay được; typed `candidate-reviewer-check`; docstring/diagnostic sửa |
| B. Review song song, finding | Xong: W15 bind artifact/generation (T04b, T01 complete); tự dispatch managed pause khi có finding, ACK chỉ từ safe point thật; hot hook từ chối khi generation cache cũ |
| C. Recovery | Xong phần có bằng chứng: process settled + intent `dispatching` → dựng lại không gọi lại, không tính phí lần hai; thiếu intent → vẫn `unknown`; exit khác 0 → `failed` (biết), supervisor bị ngắt → `unknown`. Không tuyên bố mọi trường hợp tự phục hồi |
| D. Song song, invalidation | Chạy lại combined: engine/finding/review 121 ca, gate tích hợp một wheel (mục 3). Sửa `_input_blocks` để lỗi của chính node không chặn kiểm lại/repair của nó |
| E. Estimates, learning, report | Chạy lại 73 ca (exceptions, estimates, kn_estimates, r06_learning, findings_report, progress, r03a_metrics, questions, answer_effects): OK |
| F. Bộ kiểm, gói cài | Mọi module test ngoài cổng R00 đã vào registry; manifest development đóng băng; gate tích hợp một wheel chạy (mục 3). Pin lịch sử R00 giữ nguyên (chỉ còn lineage W12b của `test_wf_plan_names.py`, do `wfkit/namespace_lineage` xử lý) |

## 3. Gate tích hợp trên một wheel

Lệnh: `python -m wfkit.development_gate run R01,R02,R03,R04,R05,R06,R07,R08,RP,RX1,RX2,KN,PL --out <thư mục mới trong OS temp> --doc-dir <workflow-chung>`
trên commit `5e1309f`, manifest `wfkit/development-manifest.json`.

Kết quả trên commit `b2cc754` (biên nhận: `C:\Users\NUC\AppData\Local\Temp\wf-dev-gate-20261024-b2cc754\`, log `D:\OneCrewRuns\wf-dev-logs\dev-gate-b2cc754.txt`):

- Wheel một lần: `onecrew-2.2.0.dev3`, sha256 `b7be2e1e557e6e1dc7a2323c49619cad3a1f10eef16a50b18bac9681020c01b4`, cây sạch; bản cài trong venv offline đạt, `control` từ checkout bị từ chối; các check bản cài ghi đúng hash wheel đã dùng.
- 146 check chạy (71 module test, 10 check bản cài, phần còn lại là registry/lineage/finalgate), **1 074 test, 1 073 đạt, 1 fail, 0 skip**. Kit-guard development: OK (269 pin). Kit-guard lịch sử R00: lineage W12b hợp lệ (`namespace_lineage` validate OK), raw vẫn báo `test_wf_plan_names.py` drift như thiết kế. Bộ tự kiểm tài liệu 06 §7: khối mã `a2ef6c0a…`, không file nào trong thư mục tài liệu bị đổi.
- **Quyết định gate: `refused`, không giao release.** Ba nhóm lý do:
  1. Acceptance: 82 testcase `partial`, 10 `blocked` — theo chính sách registry, chưa chứng nhận ma trận acceptance đầy đủ thì không giao. Đây là trạng thái thật, không phải lỗi mới.
  2. `R03/check.r03a_run_started`: 17/18, ca `test_e8_no_progress_events_or_notices` đỏ vì sổ có `estimate.baseline`. Lỗi **có sẵn trên `2bfc223`**: W32a ghi baseline ngay sau `plan.approved` (04 W32a, T36b), test R03a của Codex viết trước W32a và so toàn bộ loại sự kiện trong sổ thay vì các sự kiện do lần chạy ghi. Sửa đúng là một dòng ở test (cho phép `estimate.baseline` trong tập đã khai, hoặc so cửa sổ trước/sau lần chạy); file test đã ghim trong manifest development nên kit-guard từ chối sửa mà không có U1. Không sửa lén; để chủ sở hữu quyết (mục 5).
  3. `R08/check.parallel_native`: 1/1 đạt nhưng registry (do Claude thêm ở `a0d378e`) ghi `installed: true` sai — test này chạy CLI công khai trên checkout với hai process cục bộ, không qua wheel. Sửa đúng là đổi cờ thành `false`; mục case đã ghim nên cũng cần U1 (mục 5).
- Không có lỗi nào khác trong 71 module; không lệch wheel giữa các check bản cài.

Cổng R00 lịch sử (`python wfkit/gate.py R00`, commit `b2cc754`, wheel `0c798e2b…94bbe`, biên nhận `D:\OneCrewRuns\wf-dev-logs\cg-r00-b2cc754\`):
10/10 testcase đạt (T20 8/8, T13a 10/10, T49a 9/9, T48a 5/5, T09a 7/7, T33a 10/10, T13b 8/8, T49b 8/8, T45a 46/46, T38a PROBLEMS 0);
bản cài đạt, chạy từ checkout bị từ chối. Quyết định cổng: **REFUSED** chỉ vì kit-guard lịch sử thấy `tests/test_wf_plan_names.py` khác
pin R00 (lineage W12b/T48b của Codex, ghi ở `wfkit/namespace-lineage.json`; cổng lịch sử không đọc lineage, chỉ U1 của chủ sở hữu mở được).
Trước sửa `plan.closed` (commit `5e1309f`) T13a còn 9/10: lỗi có sẵn từ `d473cd2`. Hai gate đều chạy từ shell không mang marker phiên AI
(test có động từ owner trên sổ tạm; marker làm chúng bị từ chối đúng thiết kế W03/C11).

## 4. Giới hạn, blocker thật, không tuyên bố

- W45 (ma trận provider × vai trò bằng CLI thật), vision thật, PL-A/PL-B (việc thật), nghiệm thu chủ sở hữu: **CHƯA KIỂM CHỨNG / BLOCKED**. Mọi test provider dùng CLI giả; tên model trong fixture không phải chứng nhận provider thật.
- Registry: 82 testcase `partial` (có hồi quy, ma trận acceptance đầy đủ chưa chứng nhận riêng), 10 `blocked`, 6 `complete` (T36c, T40a, T04b, T15c, T15a, T39). Gate từ chối giao release khi còn partial/blocked: đúng thiết kế, không phải lỗi.
- RD/RR/RL/Digital Twin: ngoài phạm vi, không mở.
- Hoàn tác tác động ngoài đã xảy ra: không hứa (HD-26). Exactly-once: không hứa.
- Manifest development `eac1f3f` đóng băng sớm rồi thu hồi ở `c16079e` (ghi rõ, không che).

## 5. Quyết định cần chủ sở hữu (chỉ các quyết định thật)

1. Cho phép chạy W45 (sáu ô provider × vai trò bằng CLI thật, có phí) hay chưa.
2. Chọn việc thật cho PL-A/PL-B và nghiệm thu từng việc (ngoài development).
3. Hai U1 nhỏ để gate development hết hai lý do từ chối kỹ thuật (mục 3): (a) `tests/test_wf_r03a_run_started.py` thêm `estimate.baseline` vào tập sự kiện cho phép của E8 (baseline ghi lúc duyệt theo W32a, không phải lúc chạy); (b) `wfkit/development-testcases.json` R08 `check.parallel_native` → `installed: false`. Hoặc chủ sở hữu cho phép đóng băng lại manifest development (các pin đều lập trong ngày 24/10, chưa có lần giao nào dựa vào). Lý do từ chối còn lại (acceptance partial/blocked) không sửa được bằng U1: cần chứng nhận ma trận từng testcase hoặc giữ nguyên là chưa giao.
4. Pin lịch sử R00 cho `test_wf_plan_names.py` (lineage W12b) nếu muốn cổng R00 lịch sử tự PASS; hiện gate development đã đọc lineage.

## 6. Hướng dẫn cho Codex review tổng thể một lượt

- Baseline `2bfc223`, cuối `5e1309f`: `git diff 2bfc223..5e1309f --stat`.
- Đọc theo thứ tự: mục 1 của file này → `docs/wf/FEATURE-SCOPE.md` (task → testcase → trạng thái → check) → `wfkit/development-testcases.json`
  (ma trận bằng chứng) → biên nhận gate ở mục 3 → mã: `onecrew/common_verification.py`, `onecrew/v2/{engine,managed_executor,findings,hook_cli,active_plan,boundary,plan}.py`, `onecrew/common_executor.py`, `wfkit/{program_contract,owner_actions}.py`.
- Tái lập: `PYTHONPATH=.;tests` với python 3.12 của runtime Codex; từng module test nêu ở mục 1; gate như mục 3.
- Câu hỏi review: (1) luật `proof_mismatch` còn kẽ hở nào để receipt khác đứng thay check đã duyệt; (2) `hold_for_findings`/`_rebuild` có đường nào gọi lại worker hay tính phí hai lần; (3) `holds_current` có fail-open nào; (4) `_input_blocks` thay đổi có nới cổng cho dependent không (test_wf_failed_dependency); (5) T39 đếm thao tác có bỏ sót động từ owner nào theo 03 §2.4.
