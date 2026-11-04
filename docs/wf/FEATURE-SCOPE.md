# FEATURE-SCOPE — chương trình workflow chung (development)

Sinh từ `docs/wf/sources/04-TASKS.vi.md` (sha256 c1d8f8ae40cd) và `wfkit/development-testcases.json` (trạng thái acceptance theo từng testcase; `python -m wfkit.development_gate list`). Trạng thái: `complete` = có bảng bằng chứng theo từng [E]; `partial` = có kiểm hồi quy, ma trận acceptance và phản chứng đầy đủ của T-case chưa được chứng nhận riêng; `blocked` = cần provider thật, pilot hay chủ sở hữu (ngoài development). R00 được kiểm bằng cổng riêng `wfkit/gate.py R00` (biên nhận PASS 24/10, D:\OneCrewRuns\wf-dev-logs\cg-r00). 

## R00

| Task | Kết quả (rút gọn từ 04) | Testcase | Trạng thái registry | Kiểm hiện có | Khoảng trống |
|---|---|---|---|---|---|
| WK0 | Làm trong bước trình, trước khi duyệt (03 §6). Khung kit của chương trình: kit-guard (manifest sha256, chỉ … | T38a | cổng R00 (wfkit/gate.py R00) |  |  |
| WK0 | Làm trong bước trình, trước khi duyệt (03 §6). Khung kit của chương trình: kit-guard (manifest sha256, chỉ … | T39 | complete | program_transition, snapshot_gate |  |
| WK00 | Bộ kiểm R00: T09a, T13a, T13b, T20, T33a, T45a, T48a, T49a, T49b | — | — | — | bộ kiểm (WK*) / khảo sát: không có T-case riêng |
| W03 | Bản ghi quyết định (chủ thể thật, căn cứ, bằng chứng, phạm vi, hiệu lực); `interventions` vào wheel; từ chối … | T20 | cổng R00 (wfkit/gate.py R00) | test_wf_decisions |  |
| W03 | Bản ghi quyết định (chủ thể thật, căn cứ, bằng chứng, phạm vi, hiệu lực); `interventions` vào wheel; từ chối … | T16a | complete | engine, r04a_authority, t20_reply_guard |  |
| W11a | Sổ loại sự kiện trên anchor bản cũ thấy (00 §6.1): chỉ ghi lớp 0 (giữ mọi trường cũ, cùng kiểu) hay lớp A lên … | T13a | cổng R00 (wfkit/gate.py R00) | test_wf_events |  |
| W12a | Kiểm tên plan trước khi ghi (từ chối `:`, ký tự đường dẫn, dạng ổ đĩa, đường dẫn tuyệt đối) ở mọi đường tạo; … | T48a | cổng R00 (wfkit/gate.py R00) | test_wf_plan_names |  |
| W46a | Lệnh chỉ đọc `compat scan` trong wheel: mỗi root anchor `plan:` có ba tính chất (giữ nguyên, bản cũ đọc được, … | T49a | cổng R00 (wfkit/gate.py R00) | test_wf_compat_scan |  |
| W27a | Lỗi provider của cố vấn có kiểu (không dùng được, quá giờ, sai schema): verdict `inconclusive` kèm lý do, … | T09a | cổng R00 (wfkit/gate.py R00) | test_wf_advisor_errors |  |
| W40 | Khung đóng gói và kiểm bản cài, dùng lại cho mọi release: module cần thiết vào wheel (hoặc tách module mới để … | T33a | cổng R00 (wfkit/gate.py R00) | test_wf_packaging |  |
| W41 | Khung diễn tập nâng cấp, rollback và roll-forward trên bản sao sổ, dùng lại cho mọi release; ở R00 là 2.1 → … | T13b | cổng R00 (wfkit/gate.py R00) | test_wf_rollback |  |
| W41 | Khung diễn tập nâng cấp, rollback và roll-forward trên bản sao sổ, dùng lại cho mọi release; ở R00 là 2.1 → … | T49b | cổng R00 (wfkit/gate.py R00) | test_wf_rollback |  |

## R01

| Task | Kết quả (rút gọn từ 04) | Testcase | Trạng thái registry | Kiểm hiện có | Khoảng trống |
|---|---|---|---|---|---|
| WK01 | Bộ kiểm R01: T24a, T27, T33b, T38b, T42, T50a, T50b, T54a | — | — | — | bộ kiểm (WK*) / khảo sát: không có T-case riêng |
| W47 | Đề xuất vừa đủ ở bước 0: một phương án ưu tiên, kết quả trước–sau, căn cứ chọn phương án ít tác động mà đủ … | T50a | partial | r01_step0_proposal, r01_step0_compat, w47_proposal_binding | acceptance-audit |
| W23a | Báo cáo bàn giao theo acceptance (HD-31) và `plan present` tối giản (P1.2): một trang sinh từ sổ, không gọi … | T42 | partial | r01_report | acceptance-audit |
| W23a | Báo cáo bàn giao theo acceptance (HD-31) và `plan present` tối giản (P1.2): một trang sinh từ sổ, không gọi … | T24a | partial | r01_report | acceptance-audit |
| W23a | Báo cáo bàn giao theo acceptance (HD-31) và `plan present` tối giản (P1.2): một trang sinh từ sổ, không gọi … | T38b | complete | r01_report, t38b_task_states |  |
| W30a | Một schema thẻ quyết định (REQ/CREQ/`decisions`): vấn đề, lựa chọn, đề xuất, bằng chứng, phạm vi, mốc phải … | T50b | partial | r01_card, w30a_card_grant | acceptance-audit |
| W31a | Khảo sát/PoC ở bước 0 có trần, điều kiện kết thúc, phạm vi chỉ đọc; unknown ghi `affected`, `required_by` … | T27 | partial | r01_step0_survey, survey_worker, w31a_unknown_scope | acceptance-audit |
| W40-R01 | Phát hành R01: module mới vào wheel, kịch bản R01 chạy từ bản cài với kiểm ranh giới module của T33a; diễn … | T54a | partial | installed_features, release_bundle, upgrade_drill, w41_guard_swap, release_bootstrap, delivery_gate | release-evidence |
| W40-R01 | Phát hành R01: module mới vào wheel, kịch bản R01 chạy từ bản cài với kiểm ranh giới module của T33a; diễn … | T33b | partial | installed_features, installed_r00_scenarios, release_bundle | release-evidence |

## R02

| Task | Kết quả (rút gọn từ 04) | Testcase | Trạng thái registry | Kiểm hiện có | Khoảng trống |
|---|---|---|---|---|---|
| WK02 | Bộ kiểm R02: T35a, T46a, T51a, T51b, T54b | — | — | — | bộ kiểm (WK*) / khảo sát: không có T-case riêng |
| W23b | Ghi outcome (A1, cùng định dạng `learning.outcome`) cho mọi kết cục, can thiệp (A4, `control.intervention` … | T35a | partial | r02_outcome, w23b_outcome_window | acceptance-audit |
| W23b | Ghi outcome (A1, cùng định dạng `learning.outcome`) cho mọi kết cục, can thiệp (A4, `control.intervention` … | T46a | partial | r02_resume | acceptance-audit |
| W48a | Ngữ cảnh ghi trong lúc làm bằng sự kiện `context.entry` (lớp A) trên anchor, không thêm bảng hay đổi version … | T51a | complete | r02_context, context_wiring |  |
| W48b | Truy xuất ngữ cảnh hai phạm vi bằng một cơ chế: project (dữ kiện riêng) và chung (nội dung đã khái quát, có … | T51b | partial | r02_retrieval, r02_boundaries | acceptance-audit |
| W40-R02 | Phát hành R02: theo quy trình chung của T54 (khung W40, W41 ở R00) cho phần của R02; lớp A mới … | T54b | partial | installed_features, upgrade_drill | release-evidence |

## R03

| Task | Kết quả (rút gọn từ 04) | Testcase | Trạng thái registry | Kiểm hiện có | Khoảng trống |
|---|---|---|---|---|---|
| WK03 | Bộ kiểm R03: T12, T15b, T35d, T36b, T41a, T41b, T43a, T43b, T43c, T47a, T54c | — | — | — | bộ kiểm (WK*) / khảo sát: không có T-case riêng |
| W44 | `verdict.run_started` (P1.1): ghi sự kiện bắt đầu chạy khi `verdict run` bắt đầu; Stop hook coi mốc đang chạy … | T41a | complete | r03a_run_started, t41_gaps |  |
| W44 | `verdict.run_started` (P1.1): ghi sự kiện bắt đầu chạy khi `verdict run` bắt đầu; Stop hook coi mốc đang chạy … | T41b | complete | r03a_run_started |  |
| W33a | Quan sát có nguồn: adapter khai capability (bắt đầu, dừng, pause tại điểm an toàn, cô lập, đo, recovery); ghi … | T15b | complete | hold_report, observation_integration, r03a_executors, shared_worker_ports |  |
| W32a | Baseline ước lượng theo khoảng, ghi một lần ngay sau `plan.approved` bằng sự kiện `estimate.baseline` (lớp A; … | T36b | complete | estimates, r03a_executors, t36b_additional_u2, t36b_cli, t36b_gaps, t36b_time, exceptions, t43c_quiet |  |
| W23c | Số đo hiệu quả lấy từ sổ bằng hàm đánh giá v1 qua adapter (02, TD27): thời gian tới đầu ra, rework, quyết … | T35d | complete | r03a_metrics, t35_gaps, t35d_handover_findings |  |
| W24 | Ba trạng thái riêng `verified` / `accepted` / thông báo đã giao (HD-31); đúng một thông báo cho mỗi sự kiện … | T12 | complete | exceptions, installed_notifications, t12_gaps |  |
| W24 | Ba trạng thái riêng `verified` / `accepted` / thông báo đã giao (HD-31); đúng một thông báo cho mỗi sự kiện … | T43a | complete | exceptions, installed_notifications, t43a_channels |  |
| W24b | Thông báo ngoại lệ (đổi có chủ đích so với W24 cũ), ghi bằng `notice.exception` (lớp A) để outbox v1 đọc từ … | T43c | complete | estimates, exceptions, t43_gaps, t43c_quiet |  |
| W30b | Câu trả lời được ghi đúng (A6, phần không đổi trạng thái): lệnh đọc và lệnh trả lời câu hỏi trong wheel (động … | T47a | complete | questions, t47_gaps, t47a_answers |  |
| W30b | Câu trả lời được ghi đúng (A6, phần không đổi trạng thái): lệnh đọc và lệnh trả lời câu hỏi trong wheel (động … | T43b | complete | exceptions, installed_notifications, questions, t43_gaps |  |
| W40-R03 | Phát hành R03: theo quy trình chung của T54 (khung W40, W41 ở R00) cho phần của R03; `verdict.run_started`, … | T54c | partial | installed_notifications, upgrade_drill | release-evidence |

## R04

| Task | Kết quả (rút gọn từ 04) | Testcase | Trạng thái registry | Kiểm hiện có | Khoảng trống |
|---|---|---|---|---|---|
| WK04a | Bộ kiểm R04, nhóm quyền và kế hoạch: T02, T03, T04a, T16a, T17a, T19, T21, T36a, T37 | — | — | — | bộ kiểm (WK*) / khảo sát: không có T-case riêng |
| WK04b | Bộ kiểm R04, nhóm trạng thái và tương thích: T05, T25, T26, T32, T48b, T49c, T49d, T54d | — | — | — | bộ kiểm (WK*) / khảo sát: không có T-case riêng |
| W01 (S) | Câu trả lời: ánh xạ từng trường `authority` của v1 (`edit`, `commands`, `local_branches`, `branch_at`, … | — | — | — | bộ kiểm (WK*) / khảo sát: không có T-case riêng |
| W02 | Hợp đồng root có quyền cấp (ghi, lệnh, nhánh, sửa test, trần ngân sách/deadline, danh sách tự quyết); lint và … | T17a | complete | r04a_authority, w02_effective_authority |  |
| W02 | Hợp đồng root có quyền cấp (ghi, lệnh, nhánh, sửa test, trần ngân sách/deadline, danh sách tự quyết); lint và … | T16a | complete | engine, r04a_authority, t20_reply_guard |  |
| W02 | Hợp đồng root có quyền cấp (ghi, lệnh, nhánh, sửa test, trần ngân sách/deadline, danh sách tự quyết); lint và … | T37 | partial | engine, r04a_authority, t37_child_acceptance | acceptance-audit |
| W04 | Revision kế hoạch nội bộ (`plan.revised`) tách khỏi revision hợp đồng; trong quyền thì không cần duyệt | T16a | complete | engine, r04a_authority, t20_reply_guard |  |
| W04 | Revision kế hoạch nội bộ (`plan.revised`) tách khỏi revision hợp đồng; trong quyền thì không cần duyệt | T03 | complete | control_core, engine, metered_verifier, root_budget, t03_gaps, w10_allocation |  |
| W05 | Phân loại đổi acceptance (HD-04) và phát hiện làm yếu bộ kiểm qua hash/manifest | T21 | complete | acceptance_change, engine |  |
| W05 | Phân loại đổi acceptance (HD-04) và phát hiện làm yếu bộ kiểm qua hash/manifest | T19 | complete | engine, t19_counterexamples, t19_gaps, test_integrity, w05_acceptance_change |  |
| W06 | Ba trạng thái node; dependency khai `requires`; hàm "đủ điều kiện chạy" theo trạng thái | T05 | complete | engine, failed_dependency, w06_t05_evidence |  |
| W06 | Ba trạng thái node; dependency khai `requires`; hàm "đủ điều kiện chạy" theo trạng thái | T37 | partial | engine, r04a_authority, t37_child_acceptance | acceptance-audit |
| W10 | Ngân sách và deadline không reset qua chia/retry/restart; đóng lỗ "khoá khác thì ngân sách mới" trong cùng … | T03 | complete | control_core, engine, metered_verifier, root_budget, t03_gaps, w10_allocation |  |
| W10 | Ngân sách và deadline không reset qua chia/retry/restart; đóng lỗ "khoá khác thì ngân sách mới" trong cùng … | T32 | complete | control_core, namespace, plan_binding, root_budget, root_writer, w12b_cross_root_writer |  |
| W11b | Version workflow và capability khai trong root; plan schema 2 giữ semantics | T25 | complete | events, namespace, v2_trust_fixes, w05_acceptance_change, w11b_schema2_integrity |  |
| W12b | Một nguồn duyệt (SOL liên kết như solution revision); một writer mỗi root; không gian tên theo project (A8): … | T26 | complete | installed_solution_link, solution_link, t26_e4_one_source, w12b_cross_root_writer |  |
| W12b | Một nguồn duyệt (SOL liên kết như solution revision); một writer mỗi root; không gian tên theo project (A8): … | T32 | complete | control_core, namespace, plan_binding, root_budget, root_writer, w12b_cross_root_writer |  |
| W12b | Một nguồn duyệt (SOL liên kết như solution revision); một writer mỗi root; không gian tên theo project (A8): … | T48b | complete | namespace, plan_binding |  |
| W46b | `compat scan` mở rộng cho anchor `plan-ns:` (đóng băng khi rollback), tên trùng, B1 (active plan trỏ root bản … | T49c | complete | namespace_compat, w46b_t49c_evidence |  |
| W13 (S) | Câu trả lời: engine cho lát tuần tự R04 (mô hình node/cạnh/generation của delivery, `parallel.ready_batch` … | — | — | — | bộ kiểm (WK*) / khảo sát: không có T-case riêng |
| W14a | Root chạy task tuần tự theo engine đã chọn, dependency theo trạng thái (HD-15), một slot. Lớp mỏng nối các … | T04a | complete | engine, engine_cli, installed_native, native_executor |  |
| W14a | Root chạy task tuần tự theo engine đã chọn, dependency theo trạng thái (HD-15), một slot. Lớp mỏng nối các … | T16b | partial | candidate_handoff, candidate_reviewer, native_executor, observed_handoff | acceptance-audit |
| W14a | Root chạy task tuần tự theo engine đã chọn, dependency theo trạng thái (HD-15), một slot. Lớp mỏng nối các … | T17b | partial | findings_integration, retention_integration | acceptance-audit |
| W31b | Unknown trong thực thi có `affected`, `required_by`, chủ thể giải; giữ cục bộ hoặc toàn cục trên engine tuần … | T02 | complete | installed_unknowns, runtime_unknowns |  |
| W32b | Trường ước lượng (khoảng) cho task của kế hoạch nội bộ; trần mỗi task; luật chia (chia khi vượt trần; việc … | T36a | complete | t36a_scenario, task_caps |  |
| W40-R04 | Phát hành R04: theo quy trình chung của T54 (khung W40, W41 ở R00) cho phần của R04; root mới mang anchor … | T54d | partial | installed_native, upgrade_drill | release-evidence |
| W40-R04 | Phát hành R04: theo quy trình chung của T54 (khung W40, W41 ở R00) cho phần của R04; root mới mang anchor … | T49d | partial | namespace_compat, upgrade_drill | acceptance-audit |

## R05

| Task | Kết quả (rút gọn từ 04) | Testcase | Trạng thái registry | Kiểm hiện có | Khoảng trống |
|---|---|---|---|---|---|
| WK05a | Bộ kiểm R05, nhóm evidence và finding: T06, T07a, T11, T15a, T17b, T22, T24b, T28, T31, T38c | — | — | — | bộ kiểm (WK*) / khảo sát: không có T-case riêng |
| WK05b | Bộ kiểm R05, nhóm vòng sửa, quyết định, tích hợp: T04c, T08a, T16b, T16c, T17c, T18a, T18b, T29, T43d, T47c, … | — | — | — | bộ kiểm (WK*) / khảo sát: không có T-case riêng |
| W07 | Biên nhận gắn thêm input, cấu hình, môi trường; stale nêu đúng thứ đổi | T06 | partial | evidence_binding, candidate_adapters, candidate_reuse_counter | acceptance-audit |
| W08 | Căn cứ tái dùng evidence được ghi; căn cứ chỉ là `scope.neutral` đã khai hay căn cứ theo hành vi có bằng … | T22 | partial | evidence_binding, candidate_reuse_counter, handoff_reuse | acceptance-audit |
| W09 | Retention: ref cục bộ giữ cây và blob mà evidence tham chiếu; không push; không tự xoá ref, chỉ chủ sở hữu … | T31 | partial | retention, retention_integration | acceptance-audit |
| W16 | Node chuẩn bị test từ acceptance chạy trước implementation | T04c | complete | test_preparation |  |
| W17 | Finding register cho plan v2 (A3; phần "không thêm cổng" của đề xuất `DE-XUAT-LO3-A3-A5` không theo, vì HD-25 … | T28 | partial | findings, adapter_findings, register_v1_guard, register_v1_guard_p6 | acceptance-audit |
| W17 | Finding register cho plan v2 (A3; phần "không thêm cổng" của đề xuất `DE-XUAT-LO3-A3-A5` không theo, vì HD-25 … | T07a | complete | findings, findings_integration, adapter_findings, finding_scope, repair_tasks, t04d_finding_holds_branch, t11_integration_finding, t07a_e14_request_holds |  |
| W18 | Phạm vi ảnh hưởng theo dependency + phạm vi đọc/ghi; giữ nhánh (tuần tự: không chạy task bị ảnh hưởng; … | T07a | complete | findings, findings_integration, adapter_findings, finding_scope, repair_tasks, t04d_finding_holds_branch, t11_integration_finding, t07a_e14_request_holds |  |
| W18 | Phạm vi ảnh hưởng theo dependency + phạm vi đọc/ghi; giữ nhánh (tuần tự: không chạy task bị ảnh hưởng; … | T15a | complete | finding_scope, hook_holds_generation |  |
| W18 | Phạm vi ảnh hưởng theo dependency + phạm vi đọc/ghi; giữ nhánh (tuần tự: không chạy task bị ảnh hưởng; … | T17b | partial | findings_integration, retention_integration | acceptance-audit |
| W18 | Phạm vi ảnh hưởng theo dependency + phạm vi đọc/ghi; giữ nhánh (tuần tự: không chạy task bị ảnh hưởng; … | T16b | partial | candidate_handoff, candidate_reviewer, native_executor, observed_handoff | acceptance-audit |
| W19 | Repair task; chạy lại ca từng hỏng trước, rồi phần bị ảnh hưởng; vô hiệu hoá theo generation | T38c | complete | repair_tasks |  |
| W19 | Repair task; chạy lại ca từng hỏng trước, rồi phần bị ảnh hưởng; vô hiệu hoá theo generation | T11 | complete | engine, candidate_handoff, candidate_reviewer, t11_integration_finding |  |
| W19 | Repair task; chạy lại ca từng hỏng trước, rồi phần bị ảnh hưởng; vô hiệu hoá theo generation | T18a | complete | recovery_policy, t18a_blocker, w20_ceiling |  |
| W19 | Repair task; chạy lại ca từng hỏng trước, rồi phần bị ảnh hưởng; vô hiệu hoá theo generation | T16b | partial | candidate_handoff, candidate_reviewer, native_executor, observed_handoff | acceptance-audit |
| W51 | Không dừng nhầm việc đang tiến triển. Tách phần dùng chung của `progress.observe` (đếm lặp theo hash kết quả … | T18b | complete | progress, t18b_liveness |  |
| W20 | Vòng sửa không tiến triển → tự chẩn đoán, replan trong quyền, hoặc blocker có bằng chứng | T18a | complete | recovery_policy, t18a_blocker, w20_ceiling |  |
| W21 | Node tích hợp: unit xanh mà tích hợp đỏ thì root chưa `verified` | T11 | complete | engine, candidate_handoff, candidate_reviewer, t11_integration_finding |  |
| W23d | Bàn giao theo finding: báo cáo và `plan present` liệt kê finding còn mở lấy từ register (W17), finding đã … | T24b | partial | findings_report | acceptance-audit |
| W26 | Lớp quyết định theo quy tắc: `SKIP`/`DEFER`/`REVIEW`/`HOLD` có lý do, bằng chứng, phạm vi, hiệu lực; cache … | T29 | complete | review_dispatch, installed_review_dispatch, review_optional_cli |  |
| W26 | Lớp quyết định theo quy tắc: `SKIP`/`DEFER`/`REVIEW`/`HOLD` có lý do, bằng chứng, phạm vi, hiệu lực; cache … | T16c | complete | review_dispatch, review_optional_cli, review_policy, runtime_unknowns, w26_t16c_evidence |  |
| W30c | Áp câu trả lời thành trạng thái trên root `plan-ns:`: trả lời "dừng" đóng root có lý do (`plan.closed`, lớp … | T47c | complete | answer_effects, answer_atomicity |  |
| W30c | Áp câu trả lời thành trạng thái trên root `plan-ns:`: trả lời "dừng" đóng root có lý do (`plan.closed`, lớp … | T43d | complete | answer_effects, answer_atomicity |  |
| W37a | Reconcile tối thiểu trong vòng sửa tuần tự: lệnh có kết quả chưa rõ (crash sau dispatch, trước biên nhận) … | T08a | complete | node_actions_cli, installed_node_actions, metered_verifier, t08a_reconcile, t08a_faults |  |
| W40-R05 | Phát hành R05: theo quy trình chung của T54 (khung W40, W41 ở R00) cho phần của R05; sự kiện lớp B (`HOLD`, … | T54e | partial | installed_native, installed_node_actions, upgrade_drill | release-evidence |

## R06

| Task | Kết quả (rút gọn từ 04) | Testcase | Trạng thái registry | Kiểm hiện có | Khoảng trống |
|---|---|---|---|---|---|
| WK06 | Bộ kiểm R06: T52a, T52b, T54f | — | — | — | bộ kiểm (WK*) / khảo sát: không có T-case riêng |
| W49a | Incident trong root: nối finding, các attempt, giả thuyết bị bác bỏ; phân biệt test đỏ có chủ đích, lỗi môi … | T52a | complete | installed_node_learning, node_learning, r06_learning |  |
| W49b | Lesson sau khi sửa đã kiểm, trước khi root kết thúc: bản project giữ vị trí, revision, test; bản chung là ứng … | T52b | complete | installed_node_learning, r02_boundaries, r06_learning, t52b_lesson_limits, w49b_t52b_evidence |  |
| W40-R06 | Phát hành R06: theo quy trình chung của T54 (khung W40, W41 ở R00) cho phần của R06; `learning.incident`, … | T54f | partial | installed_features, upgrade_drill | release-evidence |

## R07

| Task | Kết quả (rút gọn từ 04) | Testcase | Trạng thái registry | Kiểm hiện có | Khoảng trống |
|---|---|---|---|---|---|
| WK07 | Bộ kiểm R07: T53a, T53b, T54g | — | — | — | bộ kiểm (WK*) / khảo sát: không có T-case riêng |
| W50a | Mô tả issue → nghi phạm: tìm chuỗi, route, symbol, thay đổi gần đây; bản đồ project tăng dần; lesson liên … | T53a | complete | installed_localization, r07_localization, w50a_t53a_evidence |  |
| W50b | Ảnh issue: chỉ đọc ảnh khi provider khai capability vision; không có thì giữ luồng văn bản và không tuyên bố … | T53b | complete | installed_localization, issue_provider, r07_localization |  |
| W40-R07 | Phát hành R07: theo quy trình chung của T54 (khung W40, W41 ở R00) cho phần của R07 | T54g | partial | installed_localization, upgrade_drill | release-evidence |

## R08

| Task | Kết quả (rút gọn từ 04) | Testcase | Trạng thái registry | Kiểm hiện có | Khoảng trống |
|---|---|---|---|---|---|
| WK08 | Bộ kiểm R08: T01, T04b, T04d, T07b, T08b, T15c, T30, T54h | — | — | — | bộ kiểm (WK*) / khảo sát: không có T-case riêng |
| W14b | DAG song song: nhiều slot qua `ready_batch` sau khi một slot đã đúng (W14a); phần độc lập chạy tiếp khi một … | T04d | complete | parallel_engine, parallel_native, t04d_finding_holds_branch |  |
| W15 | Review và test chạy trên snapshot cố định; code tiếp tục trên phiên bản khác | T04b | complete | candidate_adapters, parallel_engine, review_snapshot, review_snapshot_integration, w15_evidence |  |
| W15 | Review và test chạy trên snapshot cố định; code tiếp tục trên phiên bản khác | T01 | complete | parallel_engine, review_snapshot, w15_evidence |  |
| W33b | Interface executor đầy đủ: dừng, pause tại điểm an toàn, cô lập, recovery theo capability đã khai (W33a); … | T15c | complete | managed_executor, managed_hold, w33b_t15c_evidence |  |
| W36 | Generation; kết quả muộn hay trùng được ghi và bỏ qua; pause tại điểm an toàn cho worker được quản lý | T07b | complete | parallel_engine, managed_executor, managed_hold, engine_managed, findings, finding_scope, t04d_finding_holds_branch, t11_integration_finding, hook_holds_generation, t07b_e16_continuation |  |
| W37b | Intent bền, idempotency, reconcile qua bốn điểm crash; khôi phục checkpoint khác tự khởi động sau reboot | T08b | complete | managed_executor, node_actions_cli, t08b_crash_before_dispatch, t08b_no_exactly_once, engine_managed |  |
| W37b | Intent bền, idempotency, reconcile qua bốn điểm crash; khôi phục checkpoint khác tự khởi động sau reboot | T30 | complete | managed_executor, node_actions_cli, engine_managed, host_checkpoint, host_v1_guard, t08b_crash_before_dispatch, t30_counterexamples |  |
| W40-R08 | Phát hành R08: theo quy trình chung của T54 (khung W40, W41 ở R00) cho phần của R08; tạm dừng mới (lớp B) chỉ … | T54h | partial | installed_native, upgrade_drill | release-evidence |

## RP

| Task | Kết quả (rút gọn từ 04) | Testcase | Trạng thái registry | Kiểm hiện có | Khoảng trống |
|---|---|---|---|---|---|
| WKP | Bộ kiểm RP: T40a, T40b, T40c, T54i | — | — | — | bộ kiểm (WK*) / khảo sát: không có T-case riêng |
| W43 | Reviewer và cố vấn theo nhà cung cấp (P1.0): hợp đồng khai `provider` (`claude`, `codex`, `kiro`) kèm … | T40a | complete | rp_providers, metered_verifier, candidate_reviewer |  |
| W43 | Reviewer và cố vấn theo nhà cung cấp (P1.0): hợp đồng khai `provider` (`claude`, `codex`, `kiro`) kèm … | T40b | blocked | finalgate, provider_matrix, rp_providers | acceptance-audit |
| W45 | Kiểm thật ma trận provider (R3): chạy mỗi ô của ma trận provider × vai trò (`claude`, `codex`, `kiro` × … | T40b | blocked | finalgate, provider_matrix, rp_providers | acceptance-audit |
| W40-RP | Phát hành RP: theo quy trình chung của T54 (khung W40, W41 ở R00) cho phần của RP; giao subset đã kiểm thật … | T54i | partial | release_check, upgrade_drill | release-evidence |
| W40-RP | Phát hành RP: theo quy trình chung của T54 (khung W40, W41 ở R00) cho phần của RP; giao subset đã kiểm thật … | T40c | partial | release_check, finalgate | acceptance-audit |

## RX1

| Task | Kết quả (rút gọn từ 04) | Testcase | Trạng thái registry | Kiểm hiện có | Khoảng trống |
|---|---|---|---|---|---|
| WKX1 | Bộ kiểm RX1: T14a, T23, T54j | — | — | — | bộ kiểm (WK*) / khảo sát: không có T-case riêng |
| W22 | Adapter kiểm cho đầu ra tài liệu dạng verifier của v2 (nguồn, cấu trúc, link/ID); lõi chặn adapter vượt … | T14a | complete | candidate_adapters, rx1_core, rx1_doc |  |
| W22 | Adapter kiểm cho đầu ra tài liệu dạng verifier của v2 (nguồn, cấu trúc, link/ID); lõi chặn adapter vượt … | T23 | complete | rx1_core |  |
| W40-RX1 | Phát hành RX1: theo quy trình chung của T54 (khung W40, W41 ở R00) cho adapter tài liệu; diễn tập đầu-cuối … | T54j | partial | installed_adapters, installed_features, upgrade_drill | release-evidence |

## RX2

| Task | Kết quả (rút gọn từ 04) | Testcase | Trạng thái registry | Kiểm hiện có | Khoảng trống |
|---|---|---|---|---|---|
| WKX2 | Bộ kiểm RX2: T14b, T54k | — | — | — | bộ kiểm (WK*) / khảo sát: không có T-case riêng |
| W39 | Adapter kiểm cho đầu ra dữ liệu (schema, đối soát, mẫu) và vận hành (pre/postcondition, receipt, reconcile); … | T14b | complete | rx2_adapters, candidate_adapters, t14b_same_core |  |
| W40-RX2 | Phát hành RX2: theo quy trình chung của T54 (khung W40, W41 ở R00) cho adapter dữ liệu và vận hành; artifact … | T54k | partial | installed_adapters, installed_features, upgrade_drill | release-evidence |

## KN

| Task | Kết quả (rút gọn từ 04) | Testcase | Trạng thái registry | Kiểm hiện có | Khoảng trống |
|---|---|---|---|---|---|
| WKN | Bộ kiểm tích hợp giữa release: T36c, T46b, T47b. Mỗi phần chạy khi bản dựng có đủ hai release của nó | — | — | — | bộ kiểm (WK*) / khảo sát: không có T-case riêng |

## PL

| Task | Kết quả (rút gọn từ 04) | Testcase | Trạng thái registry | Kiểm hiện có | Khoảng trống |
|---|---|---|---|---|---|
| WKPL | Bộ kiểm pilot và cổng cuối: T14c, T35b, T35c, T45b, T45c, T45d, T45e, T40d, T55a | — | — | — | bộ kiểm (WK*) / khảo sát: không có T-case riêng |

## PL-A

| Task | Kết quả (rút gọn từ 04) | Testcase | Trạng thái registry | Kiểm hiện có | Khoảng trống |
|---|---|---|---|---|---|
| W38b | PL-A: 3 việc thật đầu tiên (code, tài liệu) do chủ sở hữu chọn, trên bản cài đặt cô lập (venv + state-root … | T35b | blocked | pilot_report | release-evidence |
| W38b | PL-A: 3 việc thật đầu tiên (code, tài liệu) do chủ sở hữu chọn, trên bản cài đặt cô lập (venv + state-root … | T45b | blocked | finalgate | external-pilot |

## PL-B

| Task | Kết quả (rút gọn từ 04) | Testcase | Trạng thái registry | Kiểm hiện có | Khoảng trống |
|---|---|---|---|---|---|
| W38c | PL-B: đủ ít nhất 10 việc thật tích lũy, có ít nhất một việc dữ liệu và một việc vận hành; reviewer khác hãng … | T35c | blocked | pilot_report | release-evidence |
| W38c | PL-B: đủ ít nhất 10 việc thật tích lũy, có ít nhất một việc dữ liệu và một việc vận hành; reviewer khác hãng … | T14c | blocked |  | external-pilot |
| W38c | PL-B: đủ ít nhất 10 việc thật tích lũy, có ít nhất một việc dữ liệu và một việc vận hành; reviewer khác hãng … | T45c | blocked | finalgate | external-pilot |

## KET

| Task | Kết quả (rút gọn từ 04) | Testcase | Trạng thái registry | Kiểm hiện có | Khoảng trống |
|---|---|---|---|---|---|
| W38d | Đối chiếu bằng chứng pilot với artifact cuối (03 §5.2), rồi cho mọi cổng chạy trên artifact cuối dùng kết quả … | T45e | blocked | finalgate, t55_cases | acceptance-audit; external-pilot |
| W38d | Đối chiếu bằng chứng pilot với artifact cuối (03 §5.2), rồi cho mọi cổng chạy trên artifact cuối dùng kết quả … | T55a | blocked | finalgate | external-pilot |

## Ngoài chương trình (hoãn theo nguồn)

RD, RR, RL (04 mục "Hoãn: nhánh có điều kiện") và Digital Twin không thuộc development này.
