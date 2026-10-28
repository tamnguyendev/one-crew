# 2.3-B (L1) — cleanup xong rồi mới tiếp quản: ghi chú triển khai

Người làm: Claude (Opus 5.5), worktree `wf-v23-b`, nhánh `claude/onecrew-2.3-b`, từ `95bb7a6` (code = 2.2.0.dev18 `34eb7c4`).
Nguồn: chỉ thị người dùng 28/10 (qua đầu mối), khảo sát `D:\OneCrewRuns\v23\survey-B.md`, hợp đồng `wf-v23\docs\v23\HOP-DONG-2.3.vi.md` dòng B-R1…R7, thiết kế `ROADMAP-DESIGN-20261026.vi.md` §2.5, §7 ca 1–7, 14, 15. Không sửa các tài liệu đó, không sửa `docs/wf/audit/*`; 2.3-B không tính vào 92 task.

## 1. Executor được hỗ trợ

`ManagedExecutor` ('managed-native-artifact') là executor L1 duy nhất: có journal, stop, recover. `NativeExecutor` (đường `onecrew engine step`) không khai stop/recover; từ 2.3-B cây process chứa trong Job của nó được **Supervisor** đối soát (chỉ cây process, không bao giờ dựng candidate hay chạy lại). Hook (`claude-code-hook`) vẫn không khai gì; không lệnh nào được gửi tới nó.

## 2. Yêu cầu → thay đổi → test → đỏ/xanh

Bằng chứng đỏ (trên `95bb7a6`, trước khi sửa) và xanh: `D:\OneCrewRuns\v23\b-evidence\`.

| Yêu cầu | Thay đổi (file:hàm) | Test | Đỏ trên base → xanh |
|---|---|---|---|
| Mỗi attempt một Job riêng, có tên, ghi trong launch token trước khi resume worker (để giết đúng cây của A, không đụng C) | `process_core.py`: `Job(name)`, `Job.open/members/contains/counts/stop(code)`, `Supervisor.run` (token thêm `job_name`, `timeout`, `started_at`) | T3, T3b, T6 | T3/T3b: không có leo thang → đỏ; xanh |
| Controller treo: không chờ vô hạn, không giết vì im lặng; chỉ sau stop/cancel hoặc quá cap + thời gian ân hạn | `process_core.py`: `ESCALATION_GRACE_MAX=60`, `ESCALATION_GRACE_FRACTION=0.1`, `grace_seconds`, `Supervisor.escalation`, `Supervisor.terminate`; gọi từ `managed_executor.ManagedExecutor.recover/stop` | T1 (im lặng > grace → không giết; stop → recover sớm → không giết; sau grace → giết cả cây) | đỏ (base không bao giờ leo thang, probe P2) → xanh |
| Không ghi "đã dọn" khi chưa xác nhận; lỗi dừng cây → unknown, giữ ownership | `Supervisor.terminate`: ghi ý định (`Control.unknown`) trước, mọi lỗi → `unknown('process-tree stop unconfirmed')`; `managed_executor.cleanup_view` (`confirmed` chỉ khi settled + `tree_stopped`) | T5 (tiêm lỗi `Job.stop`), Q4 | T5 đỏ → xanh |
| Bằng chứng cây đã dừng (Q7) | `terminate` lưu `job.members_before`, `active_after=0`; `reconcile` dùng `job_evidence` (Job còn tồn tại và còn process → không settle) | T1 (`members_before` chứa worker + cháu, `active_after==0`), T2 | đỏ → xanh |
| Ledger bị khoá bởi controller treo (Q4) → không ghi gì, không giết gì | ý định ghi trước khi giết; `managed_cli` bắt `sqlite3.OperationalError` → `cleanup: pending` | Q4 | đỏ (thiếu trường `cleanup`) → xanh |
| A lỗi/dừng → cleanup/reconcile xong rồi B mới tiếp quản (M1) | `engine.py`: `reconcile_orphans` (quét đầu `step` và `run_batch`), `_lost`, `_classify` | T1, T2, T3, T3b, T6, cài đặt | đỏ (probe P1: node kẹt `running`) → xanh |
| Tiếp quản: giữ ownership, chính sách có sẵn, không reset budget (M2, Q1, Q2) | `engine.py`: `_takeover` (`node.held` có `cleanup:'confirmed'`, `process_receipt`, `decision`; `node.resumed` có `continues_attempt`, `budget_reset:false`), `_replay_decision` = `recovery_core.decide(...,'interrupted',...)` (replay ×1 rồi giữ), kiểm còn đủ budget gốc | T2 (lần 2 bị giữ `decision:'ask'`, không launch lần 3; used_calls = 2) | đỏ → xanh |
| `unresolved()` không còn chặn revise mãi sau khi cleanup đã xác nhận và engine đã giữ node | `managed_executor.unresolved` + `released()` | T2 (`unresolved == []`), T5 (khi chưa xác nhận vẫn liệt kê) | đỏ → xanh |
| Output muộn của chủ cũ không bao giờ được publish | đã có hàng rào generation/`Control.finish`; thêm: nhánh lỗi của `step` chuyển attempt `stopped_by_recovery` sang `_takeover` (ai thấy trước làm cùng một việc), còn lại `_retain` | T1, T3 (controller cũ chạy tiếp → `node.result_retained` gen 0, `node.produced` chỉ của gen 1) | đỏ → xanh |
| Controller sống tranh với recovery | `RECOVERY_EXIT_CODE`: controller đọc lại thành `reason:'stopped_by_recovery'`, không thành "lỗi đã biết" | (đường đua; đọc code) | — |
| C độc lập vẫn chạy (Q5) | Job theo attempt; sweep chỉ chạm node đã mất chủ | T3 (C ở controller khác chạy xong khi A bị giết), T3b (cùng controller: Job của B không bị đụng; B bị gián đoạn theo, cùng sweep phục hồi cả hai) | đỏ → xanh |
| Không dọn nhầm process dùng chung (Q10) | chỉ `TerminateJobObject` trên Job của attempt; không bao giờ theo tên | T6 (process ngoài cùng `python.exe` sống sót qua stop, leo thang, tiếp quản) | đỏ (thiếu leo thang) → xanh |
| `engine step` cài đặt bị crash phục hồi được (M4) | `managed_executor.recover_contained`, `contained_state`; `managed_cli.main` nhận `state`/`recover` cho attempt không journal nhưng `job_contained`; sweep dùng cùng hàm | `test_v23_b_installed` (wheel, venv sạch, `-I`, đường dẫn có dấu cách, kiểm origin module) | đỏ (`executor recover` exit 2) → xanh |
| `executor list` khai trung thực (ca 14) | `executors.listing()` thêm managed + native với ghi chú `process`; `observe` không mở rộng (REGISTRY giữ nguyên) | `DeclarationTests` + cập nhật kỳ vọng trong `test_wf_r03a_executors` | đỏ (KeyError) → xanh |
| `cleanup: pending|confirmed|not_applicable` trong state (M5) | `ManagedExecutor.state` + `cleanup_evidence` | T1, T5, Q4, T10 | đỏ → xanh |
| Bản sao ledger không đọc thư mục gốc (M6, ca 15) | `process_core.output_file`; dùng ở `provider_limits.check_attempt(..., state_root)`, `ExternalArtifact.stdout`, `CodexArtifact.result` | T10 (copy, đổi tên gốc; ID, used_calls, held/unknown, state giống hệt; stdout đọc từ bản sao) | đỏ → xanh |
| 8.3 short name (Q6) | `internal_plan._validate`: từ chối thành phần dạng `LONGNA~1.TXT` trong read/write của node | `test_q6_…` | đỏ (lỗi khác: U2) → xanh |
| Hai caller cùng task (ca 1) | không đổi (đã đúng) | T8: hai process OS `engine step` cùng lúc → 1 thân executor, 1 lần tính phí | xanh trên base (bằng chứng lớp C) |
| Kill thật trong bước apply (ca 5) | không đổi (CAS + reconcile_action đã đúng) | T7b: process chết sau khi ghi file dự án, trước receipt → action `executing`, writer khác bị chặn; handoff sau quan sát, không ghi lại, `reconciled:true` | xanh trên base (bằng chứng lớp C) |

## 3. Quyết định đã áp dụng

- **Q1** Chỉ "mất chủ" mới là *interrupted*: `supervisor_interrupted` (controller chết, Job đã bị kernel huỷ) hoặc `stopped_by_recovery` (recovery giết cây sau stop/cap + grace). Áp `recovery_core.decide('interrupted')`: replay 1 lần trong budget gốc còn lại, lần sau giữ (`decision:'ask'`), không U-class, không thẻ owner. Stop/timeout/lỗi mà controller *còn sống* tự ghi → controller đó tự giữ node như 2.2 (không tự replay). Lỗi process đã biết (exit ≠ 0) và kết quả không dựng lại được → giữ, không replay. Không bao giờ replay khi cleanup `pending`.
- **Q2** Giữ ngữ nghĩa 2.2: budget gốc dùng chung, không reset; generation mới có child task mới với `budget_calls` của node như mọi generation. T1/T2 kiểm used_calls gốc = số lần launch.
- **Q3** "Treo" không bao giờ suy từ im lặng/CPU. Grace = `min(ESCALATION_GRACE_MAX=60 s, 10% cap)`; cap = timeout Supervisor ghi trong token; trigger = cancel/stop (thời điểm sự kiện `execution.cancel_requested`), quá cap, hoặc quá deadline thực thi. Lần `stop` đầu không bao giờ tới hạn; `recover` (hoặc `stop` lặp lại, hoặc sweep) sau grace mới giết.
- **Q4** Ý định được ghi trước khi giết; ledger khoá → lỗi `database is locked`, không giết, trạng thái giữ nguyên (`running`), `cleanup: pending`.
- **Q5** Job theo attempt. Hai attempt cùng một controller treo: giết A không đụng Job của B, nhưng B cũng không tiến được; khi controller đó kết thúc, Job của B bị kernel đóng, cùng sweep phục hồi B (T3b).
- **Q6** Độc quyền tính **theo state root** (Control/root_writer chỉ thấy một ledger); nhiều state root trên cùng repo, hard link: chưa chặn (giới hạn). Đã chặn tên 8.3 trong scope node (thay đổi nhỏ, cục bộ).
- **Q7** Bằng chứng là danh sách process của Job (`members_before`) + `active_after == 0`; khi controller chết: Job không còn tồn tại (`exists:false`).
- **Q8** Attempt `reserved` không có launch identity: sweep chỉ báo `cleanup: pending`, không ghi gì, không đoán "chưa chạy" (Job có tên chỉ được tạo trong `Supervisor.run`, không chứng minh được gì cho một controller đã chết trước đó).
- **Q9** Worktree riêng này.
- **Q10** v2 không khởi động shared service; registry consumer cho shared service không thuộc v2. T6 chứng minh chỉ Job của attempt bị giết.
- **Q11** Không mở lại W12b, W14a/b, W18, W20, W33a/b, W36, W37a/b, W51; không sửa `docs/wf/audit/*`.

## 4. Tinh chỉnh so với M1–M6 của khảo sát

- **M4**: không chuyển `engine step` sang ManagedExecutor (nhiều test/kịch bản cài đặt dùng worker fixture không mang token Supervisor; đổi sẽ phá chúng) — chọn nhánh "recover xử lý attempt không journal nhưng `job_contained`", dùng chung cho CLI và sweep. Đây là năng lực của Supervisor, không phải của NativeExecutor; `executor list` nói rõ.
- **Ý định trước khi giết** dùng sự kiện có sẵn `attempt.unknown` (qua `Control.unknown`), không thêm kind/phase mới.
- Không thêm kind sự kiện, không đổi schema. Trường mới chỉ là payload: token launch (JSON TEXT), kết quả attempt (`job`, `trigger`), `node.held`/`node.resumed` (lớp B, chỉ root `plan-ns:`), `executor.managed` phase `reconciled` thêm `escalation` (lớp A). Bản 2.2 đọc được ledger 2.3-B (projector chỉ đọc `reason`/`classification`/`resume_artifact`); 2.2 vẫn coi attempt đã giải phóng là `unresolved` (bảo thủ hơn, không sai).
- Không đổi `common_executor.py` (đầu mối đang sửa cho A1). Không thêm module vào wheel; `test_g1_core` xanh.

## 5. Giới hạn trung thực

- Chỉ Windows (Job object); OS khác không được hỗ trợ cho L1.
- Chỉ ManagedExecutor (đầy đủ) và cây process của NativeExecutor (đối soát). Hook-only: chỉ thu quyền ghi; không stop/recover. Phiên native do người dùng mở: ngoài phạm vi.
- Escalation chỉ chạy khi có ai gọi `recover`/`stop`/`engine step|batch` (không có watchdog nền; host v1 không thuộc wheel).
- Attempt `reserved` không identity, controller chết giữa `prepared` và launch: vẫn cần đối soát thủ công (Q8). Điểm (a) của T08b vẫn do `ManagedExecutor.start` tự dispatch lại khi được gọi trực tiếp.
- Đồng hồ: trigger cancel dùng `created_at` (giờ thực) của sự kiện, so với `Control.clock()`; test có đồng hồ giả lệch giờ thực có thể thấy grace khác.
- Kết quả process thành công nhưng không dựng được candidate (`result_unknown`): node bị giữ, vẫn `unresolved` (revise bị chặn như 2.2) — cố ý bảo thủ.
- Remote/API: process chết không chứng minh API không chạy; v2 artifact executor không có tác động ngoài state root; apply dự án dùng CAS + reconcile (T7b).
- Nhiều state root trên một repo, hard link, junction ngoài snapshot: không rào chung (theo state root).
- Shared service có consumer: không có trong v2 (Q10).

## 6. Lệnh chạy và kết quả

Môi trường như gate: cwd = worktree, `PYTHONPATH=.;tests`, `TEMP/TMP=D:\OneCrewRuns\v23\tmp-b`, bỏ `CLAUDECODE`, `CLAUDE_CODE_CHILD_SESSION`, `ONECREW_ACTOR`, `PYTHONUTF8`, `PYTHONIOENCODING`; Python `C:\Users\NUC\AppData\Local\Programs\Python\Python313\python.exe -B -m unittest …`.

| Lần chạy | Kết quả | File bằng chứng (`D:\OneCrewRuns\v23\b-evidence\`) |
|---|---|---|
| Test mới trên base `95bb7a6` (trước khi sửa) | takeover: 8 chạy, 7 đỏ (T8 xanh: hành vi đã đúng); apply/copy/installed: 5 chạy, 4 đỏ + T7b lỗi fixture, sửa fixture → T7b xanh trên base | `red-takeover-base-95bb7a6.txt`, `red-apply-copy-installed-base-95bb7a6.txt`, `base-apply-95bb7a6.txt` |
| Probe khảo sát P1–P3 trên base | P1 node kẹt `running`; P2 không leo thang (`stop_requested`, `reconcile: alive` sau 2 s); P3 `executor recover` exit 2, chiếm 1 slot | `red-probes-base-95bb7a6.txt` |
| 4 module test mới sau khi sửa | 13/13 OK (≈100 s) | `green-v23b-new-tests.txt` |
| Danh sách bắt buộc của khảo sát (14 module) | lần 1: 118 test, 1 fail = kỳ vọng cũ `executor list` ở `test_wf_r03a_executors` (đã cập nhật); lần cuối: 118 test, 116 OK, 1 skip (venv redirector), 1 fail `test_g1_core` vì ghi chú này chứa id model (docs bị cấm) → sửa ghi chú, `test_g1_core` chạy lại 24/24 OK | `mandatory-regression-first-run.txt`, `green-mandatory-regression.txt`, `green-g1-core-after-notes.txt` |
| 101 module còn lại có import code đã đổi (grep, danh sách trong `broad-regression-modules.txt`) | 890 test, 88,8 phút: 3 lỗi `test_provider_fallback` (adapter dựng với `control=None` → M6 đã sửa để rơi về đường dẫn lưu; chạy lại 54/54 OK cùng `test_native_audit`, `test_wf_r03a_executors`, `test_v23_b_copy`), 1 fail `test_workspace_worker` phụ thuộc môi trường (giả định TEMP ổ `C:`; với TEMP ổ C: 12/12 OK, với TEMP ổ D: bắt buộc thì fail cả khi không liên quan thay đổi này) | `broad-regression-101-modules.txt`, `rerun-after-m6-fix.txt` |
| Test quét `docs/` (7 module, có ghi chú này) | 163/163 OK (18,9 phút) | `docs-scanners.txt` |

Lệnh mẫu (bash): `cd D:/TamNT/Workspace/11.OneCrew/wf-v23-b && env -u CLAUDECODE -u CLAUDE_CODE_CHILD_SESSION -u ONECREW_ACTOR -u PYTHONUTF8 -u PYTHONIOENCODING TEMP='D:\OneCrewRuns\v23\tmp-b' TMP='D:\OneCrewRuns\v23\tmp-b' PYTHONPATH='.;tests' C:/Users/NUC/AppData/Local/Programs/Python/Python313/python.exe -B -m unittest tests.test_v23_b_takeover tests.test_v23_b_apply tests.test_v23_b_copy tests.test_v23_b_installed`

Test đã sửa (không làm yếu): `tests/test_wf_r03a_executors.py` — danh sách `executor list` chính xác nay là 4 tên (thêm `common-native-artifact`, `managed-native-artifact`), vẫn so khớp tuyệt đối.
