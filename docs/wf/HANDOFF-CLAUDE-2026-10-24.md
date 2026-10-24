# Bàn giao development cho Claude — 24/10/2026

Chủ sở hữu đã yêu cầu Codex **dừng lại và bàn giao cho Claude**. Codex dừng development; file này chỉ ghi trạng thái để tiếp quản. Chưa có nghiệm thu hay chứng nhận hoàn tất toàn bộ chương trình.

## Điểm tiếp quản bắt buộc

- Worktree: `D:\TamNT\Workspace\11.OneCrew\wf-codex`.
- Branch: `codex/wf-development`.
- HEAD: `f2cc7f4486332cf0194a32b31326cc4353d258bb`.
- Nền trước development: `d3120c6`; các checkpoint đã commit: `1b4f4c6`, `d473cd2`, `f2cc7f4`.
- **Có nhiều thay đổi tracked và file untracked chưa commit sau HEAD.** Chúng là phần implementation mới nhất. Không reset/clean, không chỉ lấy HEAD rồi bỏ các file này. Đọc `git status --short` và diff trước khi làm.
- Worktree/sổ thật và các công việc của Claude ở chỗ khác chưa được sửa, duyệt, nghiệm thu hoặc khởi động lại bởi lượt development này.

## Phạm vi đã giao

Tiếp tục development toàn bộ feature WF đã chốt; không dừng ở MVP và không mở lại vòng tranh luận roadmap. Nguồn phạm vi gốc: `D:\TamNT\Workspace\11.OneCrew\outputs\onecrew-as-qc\workflow-chung\00` đến `06`; bản nguyên byte của 04/05 đã nằm trong `docs/wf/sources/`.

Dùng `docs/proposal-coverage.md` để đọc bằng chứng các checkpoint 1–3. `docs/wf/FEATURE-SCOPE.md` và `status.json` còn là snapshot đầu kỳ, không phản ánh đầy đủ implementation mới. **Cycle 4 chưa được cập nhật vào proposal-coverage**; trạng thái dưới đây bổ sung cho nó.

Tái sử dụng v1: Control, budget, dependency/ready_batch, provider/process, snapshot/Git/CAS apply, finding, progress/recovery, context/outcome/learning, notification/outbox. Không tạo workflow riêng cho từng nghiệp vụ hoặc store/scheduler thay thế khi core hiện có đáp ứng được.

Tự quyết chia task, sửa lỗi, replan, viết/chạy test và tích hợp trong phạm vi development đã cấp; không hỏi chủ sở hữu duyệt từng việc. Không tự mở rộng acceptance/quyền/ngân sách. Không push/tag/deploy, đổi provider thật, gọi model trả phí để chứng nhận, ghi approve/accept lên sổ thật hoặc restart job thật. Blocker thật ngoài phạm vi phải giữ bằng chứng, tiếp tục phần độc lập rồi báo cuối.

## Phân workflow/model

Trong lượt Codex: Sol thực hiện module/test; Astra kiểm các bất biến xuyên module, compatibility, bộ kiểm và estimates; parent tích hợp và kiểm bản cài. Không cần dùng model sâu nhất cho mọi thao tác. Claude nên phân tương tự theo khả năng thực tế của môi trường; ghim rõ model/provider cho từng nhiệm vụ và reviewer độc lập với tác giả.

Runtime đã có `executor={role:worker,provider,model}` theo node; reviewer có cấu hình riêng trong milestone, survey có provider/model tường minh. Các test provider là fixture, **không chứng minh provider/model thật chạy được**. Không tự đổi model khi provider lỗi. R08 dùng tối đa hai slot của core v1; đây không phải scheduler tự điều chỉnh CPU/RAM của chương trình RR.

## Phần mới chưa commit

| Nhóm | File chính | Trạng thái / bằng chứng đã có |
|---|---|---|
| Finding và nhánh lỗi | `v2/finding_scope.py`, `engine.py`, `internal_plan.py`, `active_plan.py`, `hook_cli.py`, `findings.py`, `review_dispatch.py` | Finding giữ writer/reader/dependent và integration; hook chặn ghi nhánh liên quan. Known failed verification không cho dependency chỉ cần produced vượt qua. Legacy hook 27 ca đạt; scoped/engine 14 ca đạt; hai phản chứng failed-dependency đạt. |
| Song song / sửa độc lập | `engine.py`, `engine_cli.py`, `internal_plan.py`, `repair_tasks.py` | Batch dùng ready_batch/Control v1, capability riêng. Đã sửa việc replan một nhánh làm mất kết quả nhánh khác; valid_internal_revisions giữ kết quả về muộn của node không đổi. Một lỗi closure đi ngược từ input integration về producer độc lập đã được test KN phát hiện và sửa bằng dependency có hướng. Cần kiểm checkpoint cuối của agent bên dưới. |
| Managed process | `v2/managed_executor.py`, `managed_cli.py`, `host_status_core.py`, `host.py` | Pause chỉ ACK sau safe point có biên nhận Supervisor; stop kiểm tree_stopped; candidate đã lưu được tái dùng không gọi worker lại. 8 managed + 2 host ca đạt (14.746s); v1 host 24 trước/24 sau đạt. Trạng thái read-only không tự tạo sổ. |
| Tự học từ node | `v2/incidents.py`, `lessons.py`, hook trong `engine.py` | Actual command fail→repair→pass tạo episode/incident/lesson project tự động, không cần finding giả hoặc owner feedback. Bản cài 1 ca đạt 26.582s; các ca nguồn và preservation đã đạt. Không tự promote thành rule chung. |
| Candidate adapter | `common_verification.py`, `git_candidate_core.py` | Command/doc/data/ops dùng verifier gốc trên candidate Git thật; sửa CRLF bằng Git filters chỉ ở đường candidate, mặc định v1 không đổi. 13 ca mới + preservation đạt 63.631s; installed survey + doc/data + CAS 1 ca đạt 45.340s. |
| Bàn giao không thay file | `common_handoff.py` | No-change dùng actual Control observation receipt; không giả biên nhận apply. 3 ca đạt 70.871s, gồm forged receipt/user edit. |
| Survey bước 0 | `v2/survey_worker.py`, `plan_cli.py`, `compat.py` | Provider/model ghim rõ; input có scope/cap, bằng chứng path:line và quote được kiểm; intent trước call, mất receipt không blind retry. 5 ca đầu + ca cap bổ sung đạt; installed consumer đạt. Không tuyên bố OS/network isolation. |
| Metered reviewer / deadline | `v2/metered_verifier.py`, `verdict.py`, `verifiers/{reviewer,command,port}.py` | Reviewer dùng Control/root budget; unknown call không được refund hoặc gọi lại mù. Root/node command/adapter dùng deadline tuyệt đối. 14 ca đạt 32.678s; hồi quy command/RX1-core/RX2 54 ca đạt 189.210s. |
| KN estimates | `v2/estimates.py`, `report.py`, `exceptions.py`, hooks engine/revise | Baseline giữ nguyên; progress/replan bỏ phần đã verified, giữ unknown, không đếm việc phát sinh hai lần. Phân biệt execution_work với thời điểm hoàn tất lịch. 20 KN/estimates/registry ca đạt 41.473s; 16 exception ca đạt trước khi thêm nhãn payload cuối. |
| Bộ kiểm / rollback | `wfkit/development_gate.py`, `development-testcases.json`, `release_check.py`, `provider_evidence.py`, `upgrade_drill.py`, `namespace_lineage.py` | Actual install old→current→old→current trên sổ thử nghiệm, scan/refusal/reconcile/preservation: 3 ca đạt 80.629s. Release checker + finalgate 55 ca đạt 19.646s. Registry/lineage selftests 11 ca đạt. **Chưa freeze development manifest, chưa chạy full gate cuối.** |

## Đang dở / ưu tiên tiếp theo

1. **Candidate reviewer + reuse đang sửa dở trong `common_verification.py`.** Có branch gọi reviewer.run, dùng metered ProviderCall, kiểm tác giả proposal và actual producing child model, lấy approval Git objects thật qua alternates ở repo tạm. Chưa được coi là đã kiểm chứng đầy đủ.
2. Handoff đã gọi `CandidateChecker(..., previous_receipt=record['verification_receipt'])`. Hai ca `tests/test_wf_handoff_reuse.py` đã đạt **2 PASS, 32.026s**: exact evidence không chạy command lại; đổi environment phải chạy original check lại. Kết quả này chưa đóng các kiểm tra raw proof còn thiếu bên dưới.
3. Review request còn mở cho `_reuse`: phải so wrapper.evidence_binding với observed binding; proof kind/milestone/config/plan_sha/revision với milestone đã duyệt, chỉ cho giảm max_minutes trong cap đã ghi. Không để receipt pass của một command khác/noop thay thế check thật. Giữ diagnostic substring `approved command milestone` mà test hiện có kiểm. Sửa docstring còn nói reviewer chưa hỗ trợ khi implementation đã xong.
4. Agent retention báo kết quả cuối đã hoàn tất trước khi dừng: **installed managed parallel 1 PASS, 54.243s** — actual CLI → hai local Supervisor process → real per-node checks → integration → CAS hai file → root verdicts → owner accept trên fixture; strict installed boundary sạch. Không cần chạy lại riêng ca này nếu không đổi code liên quan; final combined wheel vẫn chưa kiểm.
5. Thêm đầy đủ test mới vào development registry; kiểm runner sau lineage integration; đối chiếu per-E acceptance còn partial. Không biến một unit test xanh thành pass cho toàn bộ T-case.
6. Khi code/test ổn định mới freeze manifest, cập nhật coverage, commit các path rõ ràng và chạy gate một wheel cuối. Không sửa hash lịch sử để che test bị thay.

Các phần retention bàn giao còn mở, phải đối chiếu requirement trước khi báo hoàn thành:

- W15: review snapshot bất biến trong khi nhánh code liên quan vẫn tiến triển chưa được khép kín.
- Khi finding đến, chưa tự dispatch managed pause; lệnh pause tường minh và việc tiêu thụ candidate sau pause đã chạy được.
- Recovery dựng lại candidate từ snapshot gốc khi process đã settled trước checkpoint candidate chưa làm; hiện giữ unknown.
- Hot hook phụ thuộc active-plan cache export thành công; chưa có cơ chế bổ sung để từ chối an toàn khi generation của cache không hợp lệ.
- Directed-dependency adaptation mới được kiểm tập trung; chưa có combined rerun toàn bộ sau lần sửa cuối.

Các kết quả cuối retention: public CLI supervised parallel **1 PASS, 4.872s**; directed dependency + independent active repair **2 PASS, 3.949s**; parallel/recovery/failed-dependency **11 PASS, 24.580s**. Đây là các phạm vi khác nhau, không cộng thành một chứng nhận full suite.

## Giới hạn phải giữ nguyên khi báo cáo

- Managed process đã settled nhưng chưa có candidate bền vững hiện bị giữ `unknown`; có cả trường hợp provider/schema thất bại. Exact Supervisor result vẫn giữ. Chưa có cơ chế chứng minh mọi trường hợp này đều tự phục hồi được; không tuyên bố retry tự động đầy đủ.
- Native internal engine hỗ trợ candidate file/Git. Root code/doc/data/ops dùng chung verifier lifecycle; không đồng nghĩa engine tự thực thi mọi report/non-Git output. T14/W22 không yêu cầu viết thêm executor riêng cho từng nghiệp vụ.
- W45 provider×role thật, vision thật, PL user pilots và owner acceptance chưa kiểm chứng. Fixture không phải chứng nhận thật.
- RD/RR/RL/Digital Twin là phần deferred theo phạm vi đã chốt. Không cài local model hoặc tự thay Jev trong lượt này.
- Full source acceptance matrices còn partial/blocked; full release gate chưa pass. Không báo 100% feature/release-ready dựa trên tổng số test.

## Lệnh và log để tiếp tục

Python đã dùng: `C:\Users\NUC\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe`; môi trường test `PYTHONPATH=.;tests`, cwd luôn là worktree trên.

Đọc trước: `git status --short`, `git diff --stat`, `python -m wfkit.development_gate list`.

Sau khi hoàn tất phần đang dở và freeze/commit, gate tích hợp dự kiến:

```text
python -m wfkit.development_gate run R01,R02,R03,R04,R05,R06,R07,R08,RP,RX1,RX2,KN --out <THU_MUC_MOI_TRONG_OS_TEMP>
```

Registry tại thời điểm bàn giao có khoảng 70 module chạy duy nhất, 10 installed checks; runner khử trùng lặp và truyền cùng WF_WHEEL cho bản cài. Danh sách sẽ tăng khi bổ sung test reviewer. **Không chạy toàn bộ `tests.test_v2_reviewer`: lớp RealCliTests gọi provider thật.** Chỉ dùng các lớp pure hoặc fixture đã chọn.

Log parent: `D:\OneCrewRuns\wf-dev-logs\codex-*.txt`, nhất là `codex-metered-verifier-final.txt`, `codex-deadline-verifier-preservation.txt`, `codex-observed-handoff.txt`, `codex-installed-common-consumers.txt`. Số đếm giữa suite có thể chồng nhau; không cộng thành tỷ lệ hoàn thành.

Log KN: `C:\Users\NUC\AppData\Local\Temp\codex-kn-final.txt`. Lineage: `C:\Users\NUC\AppData\Local\Temp\wf-dev-registry-smoke-20261024a\namespace-lineage-3\receipt.json`: 5 original frozen tests tại `8e0d52c` + 5 successor tests từ wheel đạt. Runner tổng chưa chạy lại sau khi nối lineage.

Một lỗi prompt-budget CTS/P6 của v1 đã tồn tại ở baseline; giữ log riêng, không ghi thành pass hay lén sửa assertion. Control baseline có một environment skip venv redirector, không tính skip thành pass.

Sau khi hoàn tất development: bàn giao diff/commit, wheel hash, test receipts và phần blocked thật để Codex review tổng thể một lượt. Không gửi việc lại cho Codex sau từng module.

## Xác nhận dừng của agent

- Inventory: không còn test process riêng đang chạy. Sessions `74877`, `92349`, `18384`, `27655`, `98072`, `90823` đã xong; kết quả trong tool transcript, không có log file riêng. Candidate reviewer chưa có test riêng; native learning chưa hỗ trợ typed `candidate-reviewer-check` (giữ unknown, không suy pass).
- Retention: session `44246` đã xong với installed parallel PASS trước lúc poll dừng; không còn session test riêng đang chạy.
- Scope audit: không còn test riêng chạy; handle `35594` thuộc KN 20-test run đã kết thúc OK. Development manifest chưa freeze; runner sau lineage chưa được chạy lại.
- Parent: session `54813` đã xác nhận kết thúc exit 0 (54-test preservation). Chỉ tạo/cập nhật file handoff sau lệnh dừng; không sửa thêm implementation hoặc chạy test mới.
