# Round 11 — khép phần local theo review Codex 26/10 (lượt 11), đêm 26→27/10/2026

Ủy quyền: chủ sở hữu, chat Claude Code 26/10/2026 ~19:40, dán nguyên văn chỉ thị lượt 11 ("Tôi ủy quyền tự chia task, chọn cách sửa, chạy agent phù hợp, bổ sung test, xử lý lỗi, commit local và dựng/kiểm gói trong phạm vi dưới đây. Không hỏi tôi duyệt từng file, task, test hoặc commit."). Ngoại lệ một lần: sửa tối thiểu tài liệu Codex quản lý + bộ kiểm tài liệu cho ba cảnh báo K-OWNER và link hỏng. Mọi quyết định kỹ thuật theo ủy quyền, không phải chữ ký trực tiếp.
Đầu vào: snapshot dev11 `73d6c77`, báo cáo `b0c1fe0`, gói `D:\OneCrewRuns\wf-handover-73d6c77`. Phạm vi 2.2; không kéo feature 2.3–2.7.

## Tách việc
| Agent | Model | Finding | File |
|---|---|---|---|
| V | Opus | A (guard output chặn xoá/file rỗng) + B (tham chiếu không extension lọt M1) | onecrew/common_verification.py, onecrew/v2/verifiers/output_refs.py, docs/wf/audit/tools/reverify_nodes.py, tests/test_wf_r11_output_guard.py, tests/test_wf_r11_output_refs.py, tests/test_wf_r10_output_refs.py |
| C | Opus | C (D8 kiểm deadline theo node đã xong) | onecrew/v2/internal_plan.py, tests/test_wf_r11_d8_deadline.py |
| D | Sonnet | D (gói lệch snapshot, provenance wheel trước, bundle refused thiếu, trộn định danh, 60fdf15) | docs/wf/audit/tools/{build_package,run_bundles}.py, wfkit/package_check.py, tests/test_wf_package_check.py, tests/test_wf_package_verifier_shipped.py, tests/test_wf_r11_build_package.py |
| E | Sonnet | E (anchor hỏng 00:469; K-OWNER báo nhầm ROADMAP:46/:345, HANDOFF:46) | ngoài checkout: workflow-chung/00-THIET-KE…:469, 06-TRUY-VET… §7 (khối tự kiểm); trong checkout: wfkit/u1/U1-20261027-DOCCHECK-OWNERNEG.json |
| Đầu mối | Fable | tích hợp, registry (R05 check.r11_output_guard_refs, R04 check.r11_d8_deadline, PL check.r11_build_package), U1 R11-1..3, dev12, snapshot, gate, kiểm lại 55 artifact, bundles, audit, gói, verify/legacy, báo cáo | — |

## Bảng lỗi → tái hiện → đỏ trước → sửa → xanh sau
| # | Tái hiện | Test đỏ trước sửa | Sửa | Xanh sau |
|---|---|---|---|---|
| A | Worker xoá `a.txt` trong quyền → "declared output missing or empty"; file rỗng cố ý cũng fail; manifest xoá file ngoài quyền (né API) lại PASS | `tests.test_wf_r11_output_guard` 11 test: 9 fail + 1 error (test_a, b, c, d KeyError, e–i, k) | `common_verification.required_outputs/output_expectations/output_check`: `write` = quyền; đầu ra BẮT BUỘC = đường dẫn ghi được nêu nguyên văn trong `output` của node/hợp đồng; nội dung khai (kể cả "") phải khớp (git hash-object), `null` = phải vắng; ngoài quyền so với snapshot cha → fail | 11/11 qua engine.step + artifact API + engine.verify thật |
| B | Báo cáo chứa `Dockerfile:999999`, cây không có → 0 tham chiếu, PASS | `tests.test_wf_r11_output_refs`: 11 fail + 1 error; `test_h_report_citing_a_missing_dockerfile_fails_m1` 'pass' != 'fail' | `output_refs._CANDIDATE` (extension tùy chọn), `_one` phân họ, `check.promoted()`: token không chấm là tham chiếu khi là file trong cây / tên generic (Dockerfile, Makefile, LICENSE…) / có `/` neo vào thư mục đỉnh / trùng basename file trong cây (offender); còn lại → `ignored` (đếm riêng, không offender); đối chứng URL, host:port, 12:30, 16:9, image tag, C:\, văn xuôi | xanh; smoke sample 15/21 không đổi, đếm tham chiếu từng node bằng baseline cũ |
| C | A/B verified cap 600 s, I cap 30 s, root còn 100 s → revise I bị từ chối | `tests.test_wf_r11_d8_deadline` 7 chạy, 1 fail + 2 error (repro, b2, d) | `internal_plan._beyond_deadline(nodes, counted, remaining)` dùng tập `_to_come`, kiểm cả lúc quyết định và trong giao dịch publish (đếm lại phải trùng, lệch → từ chối); không nới deadline/hoàn chi phí/reset | 8/8; hồi quy d8/d6/d7/engine/root_budget/w20/parallel/kn + 6 module khác xanh |
| D1 | Gói 73d6c77: audit-92 ghim abb570a | `test_audit_of_another_commit_is_refused_before_anything_is_written` | `build_package.check_one_build` + `--audit`; từ chối trước khi ghi | gói thử refused đúng; gói nhất quán có tasks_92_commit=73d6c77 |
| D2 | hardcode `d3120c6` cho wheel trước | `PreviousWheelProvenanceTests` | `previous_provenance`: `--previous-evidence` → sidecar → manifest gói trước → METADATA; sha/version lệch → từ chối | previous_wheel = dev8, commit 4b1b7b1…, nguồn "previous package manifest.json" |
| D3 | RP refused không có trong gói | `RunBundlesKeepsRefusalTests`, `BundlesKeepEveryResultTests` | `run_bundles.keep_result` ghi `bundle-result.json`; manifest 11 entry có decision/produced/reason | 11 bundle trong manifest |
| D4 | bundle/receipt/snapshot commit hoặc wheel khác | `ConsistencyTests`, `PackageIdentityStepTests` (8) | builder từ chối; `package_check.identity_problems` trong `package_scope` → judge từ chối gói trộn | gói cũ 73d6c77 bị từ chối (3 lý do), gói thử r11check pass |
| D5 | 60fdf15 hai nhánh | `PreviousWheelIsWhatItClaimsTests` (wheel dev3 thật, dev8 thật, dev3 đổi tên dev8, version khai lệch) | nhánh chọn theo METADATA của wheel ghim + version khai; lệch → từ chối | xanh |
| E | anchor `#2-hiện-trạng…` không còn; K-OWNER báo 3 câu phủ định | tự kiểm: PROBLEMS 4; CX-OWNER9 (gần-miss) LỌT ở lần chạy đầu | 00:469 → `#2-baseline-lịch-sử-2210-và-giới-hạn-xác-minh`; `k_owner` bỏ mệnh đề phủ định hẹp `không (hỏi|thêm|cần) … (duyệt|nghiệm thu)`; thêm `commit`; thu hẹp whitelist `duyệt một lần(?! … | mà)`; 3 đối chứng + 5 phản chứng mới | PROBLEMS 0; 155/155 phản chứng, 18/18 đối chứng; pin `doc:wf-doc-check` a2ef6c0a… → 482bf8a3… qua U1 |

## Ghi chú trung thực
- legacy_continuation dev11 có **15** bước (báo cáo R10 trước ghi 16 — đã sửa).
- W45: quyền trong phiên ("cho chạy W45", "Cho chạy lại W45 trên wheel 6366137") gắn với wheel 6366137; không chạy ma trận trả phí trên wheel mới → RP giữ Partial/Blocked, ghi quyết định cho chủ sở hữu.
- Gói `wf-handover-73d6c77` và các gói cũ hơn KHÔNG qua được bước identity mới (audit lệch commit) — đúng thiết kế; gói bàn giao là gói mới từ snapshot dev12.
- Rủi ro còn lại (từ agent): đầu ra bắt buộc chỉ nhận ra khi đường dẫn xuất hiện nguyên văn trong output node/hợp đồng; tham chiếu không extension không neo được vào cây → `ignored` chứ không fail; whitelist K-OWNER cũ `không (…|cần|phải) … duyệt` vẫn lỏng (không nới thêm); U1 R10-2/R10-8 bị kitguard báo thiếu `old_sha256` khi verify ở cây bẩn (gate 73d6c77 vẫn đạt kitguard — kiểm lại ở gate dev12).
