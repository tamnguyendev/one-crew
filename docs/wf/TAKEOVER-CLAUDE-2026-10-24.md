# Tiếp quản development từ Codex — Claude, 24/10/2026

Nhánh `codex/wf-development`, worktree `D:\TamNT\Workspace\11.OneCrew\wf-codex`. Điểm tiếp quản: `f2cc7f44` cộng phần chưa commit của Codex,
được chốt nguyên trạng thành `2bfc223` (sao lưu: `D:\OneCrewRuns\wf-codex-handoff-backup-20261024`). Không reset, không ghi đè; sổ thật,
worktree khác và job đang chạy không bị đụng. Không push, tag, publish; không approve/accept trên sổ thật; không gọi provider trả phí.

Trạng thái (cập nhật lần 4, đêm 24/10 ~22:45, lượt "hoàn thiện toàn bộ development"): **mọi việc local trong phạm vi đã giao đã làm xong hoặc ghi rõ phần còn thiếu**; mã cuối `ceb46c6`; gate snapshot cuối đang chạy trên `ceb46c6` (mục 8 ghi kết quả khi xong). Còn Partial 5 task bộ kiểm (thiếu test/ma trận, không phải điều kiện ngoài — mục 8.4) và Blocked 15 task cần điều kiện ngoài (bản giao trước thật, provider thật, pilot). Chưa có nghiệm thu sản phẩm; review Codex lượt 1 (`9aca8be`) đã xử lý xong, chưa có review lượt 2.

## 0. Kết quả tóm tắt (đọc 5 dòng)

- 92 task: **Done 58 · Partial 30 · Blocked 4** tại `bb177f0` (lượt 1 sáng nay: 37 · 51 · 4; trưa 57 · 31 · 4 trước khi hạ 3 P1 rồi sửa xong). Tách nhóm: feature 47/13/0; bộ kiểm 11/6/0; phát hành 0/11/0; provider thật 0/0/1; pilot/nghiệm thu 0/0/3.
- 20 task feature chuyển Partial → Done trong lượt này, mỗi task có code nối vào đường dùng thật + test mới (36 test mới, 15 file) — chi tiết mục 2.
- Registry development: 19 check mới, 9 testcase lên `complete` (15 complete tổng), manifest đóng băng lại ở `0d296fe` (307 pin; commit message ghi nhầm 310).
- Gate cuối = gate SNAPSHOT trên `bb177f0` (worktree tách rời sạch, mục 3/7): **đang chạy**. Các gate trên cây làm việc (`b2cc754`, `eae44ce`, `0d296fe` bị dừng) chỉ còn là bằng chứng hồi quy có nhãn, không phải chứng nhận commit.
- Còn lại thật sự: 11 task phát hành (cần bản giao trước thật — E), W45/W38b-d (provider/pilot — E), 14 feature Partial (7 là quyết định của chủ sở hữu hoặc mutant/kịch bản ở mức bộ kiểm — mục 5).

## 1. Commit của lượt này (sau `5e1309f`)

| Commit | Nội dung | Kiểm |
|---|---|---|
| `b2cc754`, `eae44ce`, `a84b1fb`, `0bb3c95`, `c148057` | Lượt 1 (sáng): NS_KINDS/`plan.closed`, U1 E8/PN, W05 (acceptance_diff, test_integrity), guard reply W03, W01/W13 khảo sát | gate b2cc754 1 074/1 073; eae44ce xem mục 3 |
| `b225e5c` | W48a (ngữ cảnh thu bằng mã), W50b (`--provider`, `issue evaluate`), W33a (`hold_views` + report), W37a (reconcile run chưa rõ kết quả, `verdict release-run`), W21 (finding từ node engine, phạm vi theo dependency, repair thả node), W26 (`engine review-optional`), W20 (blocker có lần thử + chi phí, hiện trên report); wheel +2 module W05 | 258 + 129 + 107 + 9 (bản cài) test, chỉ còn r01_card E7 (flake giờ, mục 5) |
| `c4cfede` | W14b (T04d), W15 (review lần hai trên A2), W23d (dòng finding có tiêu chí+artifact), W49b (lesson sau khi root kết thúc, tên file trước dấu câu) | 34 test |
| `28f8fb0` | W32a (phát sinh vượt quyền → 1 U2 + giữ phụ thuộc), W30b (present/report nêu lựa chọn của chủ sở hữu), W24 (test kênh T43a) | 50 test |
| `602414f` | Registry: 18 check, 9 case complete với ma trận [E] | `development_gate list` |
| `0d296fe` | T08 E6 grep (W37b) + manifest development thu hồi & đóng băng lại (307 pin) | kitguard.verify qua `layout()`: chỉ 7 pin `registry` lệch trước khi đóng băng lại, không file test nào |
| `635c037` | Test đợt 5 (T37/W06, T43c/W24b, T20 E5/W03 — chưa đăng ký) + bảng 92 task + FEATURE-SCOPE | 3 module |
| `9aca8be` | Release notes 11 release, báo cáo (bản 2), DEV-LOG, coverage, handoff — **mốc Codex review** | — |
| `5f8d7b6` | P1 W05: test_integrity decorator/lớp/discovery/support, unproven → inconclusive | t19_counterexamples 5 + T19/T21 14 |
| `60658ec` | P1 W37a: reconciled(unknown) là hold, nguyên tử; hoàn tất từ receipt đã phát hành; hold theo mốc qua revision | t08a_faults 5 + reconcile 4 + E6 2; hồi quy verdict 11 module OK |
| `50820d6` | P1 W32a: CLI truyền nodes/still_running, kiểm trước ghi, hold lỗi = lỗi | t36b_cli 4 + 29 láng giềng |
| `bcc4d88` | P2: `development_gate snapshot --commit` (worktree sạch, fingerprint nguồn ngoài, intact) | snapshot_gate 3 + kit 8 |
| `9107d61`, `165a190` | Registry +9 check (review + W03/W06/W24b + T08b(a) + T36a); manifest đóng băng lại (lệch trước: chỉ snapshot registry + development_gate.py) | kitguard.verify qua layout() |
| `cafc5f2` | W37b điểm (a) kill thật trước dispatch → chạy đúng 1 lần; W32b kịch bản T36a | 1 + 3 test, managed 15 OK |
| `10976ea`, `bb177f0` | Báo cáo §7 (5 finding), bảng 92 task tại 165a190 | — |

## 2. Chuyển trạng thái có bằng chứng (Partial → Done, theo loại nguyên nhân của bản audit)

| Task | Loại cũ | Đã làm | Test / check |
|---|---|---|---|
| W48a | B | `authority.record` → context.entry `decision` (nguồn = sự kiện quyết định, khử trùng theo chủ đề); `engine.verify` pass → `task_done` (nguồn = biên nhận) | test_wf_context_wiring (3); R02 check.context_wiring; T51a complete |
| W50b | B,C,E | `providers.vision()` khai capability (không provider nào khai vision → ảnh không mở, nêu lý do); `issue localize --provider`; `issue evaluate --cases --oracle` | test_wf_issue_provider (4); R07; T53b complete |
| W33a | B,C | `managed_executor.hold_views` (hook: ngừng cấp quyền ghi; managed: đã yêu cầu dừng, chưa xác nhận) → `plan report`/bàn giao | test_wf_hold_report (2); R03; T15b complete |
| W37a | A,C | marker bền `dispatched`/`receipt` theo run_id; `reconcile` trước mọi run mới; `verdict.run_reconciled/run_held/run_released` (lớp A); `verdict release-run --reason`; có receipt marker → phát hành biên nhận cũ, không chạy lại | test_wf_t08a_reconcile (4, kill tiến trình thật), test_wf_t08b_no_exactly_once (2); R05; T08a complete |
| W21 | A,C | `findings.record_node_verification` (finding nội bộ từ biên nhận node, phạm vi = input mà I tích hợp, pass đóng); `finding_scope._release_repairs`; `engine._input_blocks` cho dependent đã thả; `repair_tasks.rerun_order` | test_wf_t11_integration_finding (3); R05; T11 complete |
| W26 | B,C | `engine review-optional` trên CLI công khai | test_wf_review_optional_cli (2); R05; T29 complete |
| W20 | B,C | `recovery_policy.assess` ghi `attempts` + `spent`; report/bàn giao in Blocker | test_wf_t18a_blocker (2); R05 |
| W05 | A,C | `acceptance_diff` (a–g), `test_integrity` (assert nới/test xoá → mốc đỏ U1) | test_wf_acceptance_change (9), test_wf_test_integrity (5); R04; T21, T19 complete |
| W14b | C | finding ở E1 giữ E1/F/I, E2 xong, không giữ root (2 slot thật) | test_wf_t04d_finding_holds_branch (1); R08; T04d complete |
| W15 | C | reviewer thật trên snapshot A1 khi X và cây dự án đổi; A2 cần review mới, diff là của A2 | test_wf_review_snapshot_integration (1); R08; ma trận T04b |
| W23d | C | dòng finding mở có tiêu chí + artifact; F1 mở/F2 đóng | test_wf_t35d_handover_findings (1); R03 |
| W49b | C | `lessons._still_open` (kể cả `closed`); `_private_reasons` bắt tên file trước dấu câu | test_wf_t52b_lesson_limits (2); R06 |
| W32a | A,C | `estimates.additional(outside_authority, nodes)` → đúng 1 U2 + giữ phụ thuộc qua unknown; bắt buộc vào ETA có lý do; tùy chọn vào backlog | test_wf_t36b_additional_u2 (1); R03 |
| W30b | A,C | present/report: "Chủ sở hữu đã chọn dừng/amend/tiếp tục («tham chiếu»)" | test_wf_t47a_answers (3); R03 |
| W24 | C | grep có tiêu chí (kênh, heartbeat), qua desktop_core v1, mở đúng trang | test_wf_t43a_channels (2); R03 |
| W24b | C | 6 giờ yên lặng = 0 thông báo; trạng thái giao không có "đã đọc" | test_wf_t43c_quiet (2) — chưa đăng ký |
| W06 | C | T37: hai task con accepted nội bộ với HD-05 Q12; root chờ; AI accept bị từ chối (bước 3 không chạy: O4 chưa "có") | test_wf_t37_child_acceptance (1) — chưa đăng ký |
| W03 | A | guard `ledger.reply` (decided_by user / by owner) trong phiên AI, API + CLI | test_wf_t20_reply_guard (2) — chưa đăng ký |
| W17 | C | test register v1 (`test_review_lifecycle`, `test_review_p6`) đăng ký vào R05 cho T28 E1 (chậm, chạy trong gate 0d296fe) | check.register_v1_guard(_p6) |
| W44 | C,D | E8 đã áp U1; chờ biên nhận gate 0d296fe | check.r03a_run_started |

Lượt 1 đã chốt (xem bản báo cáo trước, giữ trong lịch sử Git): candidate reviewer + luật tái dùng, W15 snapshot, W36 pause tự động, W37b dựng lại, hook holds theo generation, T39, boundary, NS_KINDS.

## 3. Gate development một wheel

Lệnh: `python -m wfkit.development_gate run R01,R02,R03,R04,R05,R06,R07,R08,RP,RX1,RX2,KN,PL --out <thư mục mới trong OS temp> --doc-dir <workflow-chung>`,
chạy từ shell không mang marker phiên AI (`env -u CLAUDE_CODE_CHILD_SESSION -u CLAUDECODE`).

- `b2cc754` (sáng): 146 check, 1 074 test / 1 073 đạt / 0 skip; từ chối vì acceptance partial + E8 (đã U1) + cờ installed (đã U1).
- `eae44ce` (trưa): 146/146 biên nhận; 3 check đỏ **vì gate đọc cây làm việc trong lúc Claude đang sửa dở** (`record()` chưa có `integrity`, `reconcile` chưa định nghĩa) — không phải lỗi mã đã commit; `r01_card` E7 đỏ vì flake giờ (mục 5). Biên nhận: `C:\Users\NUC\AppData\Local\Temp\wf-dev-gate-20261024-eae44ce\`.
- `0d296fe` (tối): chạy trên cây làm việc, **bị dừng ở 55/165 biên nhận** sau review Codex P2 (gate cuối phải chạy trên snapshot cố định). Biên nhận giữ nguyên nhãn.
- `9107d61` (đêm, gate snapshot đầu tiên): dừng ở 10/165 vì không còn là commit cuối (W37b(a)/W32b vào sau).
- **`bb177f0` (đêm, gate snapshot cuối)**: `python -m wfkit.development_gate snapshot R01,…,PL --commit bb177f0 --out <mới dưới OS temp> --doc-dir <workflow-chung>`; output `%TEMP%\wf-snapshot-gate-20261024-bb177f0\` (snapshot.json: commit, fingerprint doc-dir + interpreter; gate\decision.json; decision.json tổng có `snapshot.intact`), log `D:\OneCrewRuns\wf-dev-logs\snapshot-gate-bb177f0.txt`. **Đang chạy** (~3 h, 170 check kể cả hai module register v1). Kết quả PASS/FAIL/SKIP từng check được ghi vào mục này khi xong. Kỳ vọng: `refused` vì acceptance partial/blocked (đúng thiết kế), mọi implementation check xanh trừ `r01_card` E7 nếu chạy trong khung 10–19 UTC.

Hồi quy đã chạy trên cây này (log `D:\OneCrewRuns\wf-dev-logs\`): `w48a-w50b-regress.txt` 258 test (5 F: 4 do wheel thiếu 2 module W05 → đã sửa pyproject, chạy lại `installed-regress-2.txt` 9/9; 1 r01_card flake), `w37a-regress.txt` 129 OK, `w21-regress.txt` 107 OK, các module mới chạy riêng (mục 1).
Không chạy: toàn bộ `tests.test_v2_reviewer` (RealCliTests gọi provider thật); không provider trả phí; không sổ thật.

## 4. Dùng lại lõi v1 (không viết lại)

`dependency_core.affected_tasks/ready_batch` (phạm vi finding, repair, slot), `control_core.Control` + Supervisor (attempt, fence, safe point), `budget_core.group` (chi phí trong blocker), `finding_core` (register, close_finding), `recovery_core.decide` (vòng sửa), `progress_core.observe_counters`, `desktop_core/notifications` (kênh), `routing.validate_decision` (lớp quyết định), `admission_core` (đọc, không nối — mục 5 W18), `amendment.affected_tasks` qua `dependency_core`.

## 5. Blocker thật và quyết định cần chủ sở hữu

1. **W45** (sáu ô provider × vai trò bằng CLI thật, có phí) và **W38b/c/d** (pilot PL-A/PL-B, CG-KET): chưa được cấp quyền → không chạy; harness/validator có (`wfkit/provider_evidence.py`, `finalgate.py`, `release_check.py`).
2. **11 task phát hành W40-R01…RX2**: bundle T54 cần bản giao trước thật, kịch bản đầu-cuối theo release, artifact đóng băng và lịch sử biên nhận đã giao; chưa có bản giao nào. Release notes (5 mục T54.5) đã sinh ở `release-notes/` với `Fixture checks: pending` cho tới khi gate xanh.
3. **U1 nhỏ**: `tests/test_wf_r01_card.py` E7 `assertNotIn('T1', json.dumps(shown))` khớp giờ ISO `…T11:…` → đỏ trong khung 10–19 UTC; sửa đúng là so trên thẻ, không trên JSON có timestamp. File pin R01 → cần U1.
4. **W12a**: T48a E10 bị W12b thay (không gian tên theo project); `plan.refuse_duplicate_name` mồ côi; pin R00 `test_wf_plan_names.py` lệch theo lineage W12b. Chọn (a) U1 chấp nhận thay thế hay (b) giữ nghĩa R00.
5. **W36 / T07b E16**: "thả nhánh → attempt mới" so với handoff C "tái dùng candidate đã settle": mã tái dùng khi việc đã xong; đường "còn dở → attempt mới" chưa có. Cần chủ sở hữu chốt nghĩa trước khi thêm (1–2 h).
6. **W18 / T07a E14**: `branch_inbox.blocks` của v1 chặn toàn root theo MỌI request chờ → trái T16 nếu nối thẳng; v2 giữ nhánh bằng register finding + `affected_tasks`. Ghi nhận lệch có lý do hay yêu cầu bộ lọc riêng.
7. Còn Partial loại C (mutant/kịch bản bộ kiểm, không chặn): W11a, W46a, W46b, W40, W41, W23a, W32b, W39, W37b (kill thật ở (a)), W51 (liveness 'command' lúc chạy), WK03/04a/04b/05b/P/PL.

## 6. Hướng dẫn cho Codex review tổng thể một lượt

- Baseline `2bfc223`, cuối `635c037` (+ commit tài liệu): `git diff 2bfc223..HEAD --stat`; phần lượt 2: `git diff 5e1309f..HEAD --stat`.
- Thứ tự đọc: mục 0–2 của file này → `audit/AUDIT-92.md` → `FEATURE-SCOPE.md` → `wfkit/development-testcases.json` (ma trận [E]) → biên nhận gate (mục 3) → mã:
  `onecrew/v2/{verdict,findings,finding_scope,engine,repair_tasks,recovery_policy,estimates,report,authority,managed_executor,providers,learning_cli,engine_cli,lessons,context,compat}.py`, `onecrew/common_verification.py`, `wfkit/{program_contract,owner_actions,development_gate,kitguard}.py`.
- Tái lập: `PYTHONPATH=.;tests` với python 3.12 của runtime Codex, từ shell không mang marker phiên AI; từng module test ở mục 2; gate như mục 3 (thư mục `--out` mới).
- Câu hỏi review: (1) `reconcile` có đường nào chạy lại X khi marker `dispatched` tồn tại mà không có `release-run`; `_complete_from_marker` có phát hành biên nhận sai revision; (2) `record_node_verification`/`_release_repairs`/`_input_blocks` có mở cửa cho dependent chạy trên input đang bị finding giữ ngoài trường hợp repair; (3) `_remember` có làm hỏng giao dịch quyết định; (4) `_outside_authority` có tạo request thứ hai hay giữ sai node; (5) `_still_open`/`_private_reasons` có chặn nhầm; (6) manifest development thu hồi + đóng băng lại ở `0d296fe` có che lệch nào (bằng chứng: chỉ 7 pin `registry` lệch, không file test).
- Không ghi "Codex đã review", "chủ sở hữu đã duyệt/nghiệm thu", "release đã giao": chưa xảy ra.

## 7. Review Codex tại `9aca8be` — 3 P1 + 2 P2 (xử lý đêm 24/10)

| # | Finding | Nguyên nhân | Sửa (commit) | Tái hiện trước / sau |
|---|---|---|---|---|
| P1 | W05: thêm `@unittest.skip` vào test đã duyệt mà mốc vẫn PASS, `test_integrity = None` | `test_integrity` chỉ băm thân hàm; không nhìn decorator, lớp, discovery, helper | `analyse` băm cả định nghĩa (decorator), skip/xfail cấp lớp, discovery theo tên file, support hash → `insufficient`; `verdict.integrity_result`: weakened→fail (U1), insufficient/error→inconclusive (`5f8d7b6`) | `tests/test_wf_t19_counterexamples.py`: trước sửa 4/5 đỏ (skip hàm/lớp, helper yếu → `passed`); sau 5/5 + T19/T21 cũ 14/14. Giới hạn: Python theo tên file; không bắt sinh test động/`load_tests`/pytest.ini/mã dưới kiểm |
| P1 | W32a: CLI `estimate additional --file` bỏ `nodes`/`still_running`; lỗi hold bị nuốt | API nhận tham số nhưng CLI không truyền; `_outside_authority` try/except trả `{'error'}` như thành công | `_node_lists` kiểm trước mọi ghi; mở unknown trước, lỗi lan ra ngoài; CLI truyền và từ chối trường lạ; retry idempotent theo key (`50820d6`) | `tests/test_wf_t36b_cli.py`: trước sửa 4/4 đỏ (U2 không hold, node sai/hold lỗi vẫn exit 0); sau 4/4; resolve unknown không đổi quyền (write ngoài scope vẫn U2, request vẫn pending) |
| P1 | W37a: crash giữa `run_reconciled(unknown)` và `run_held` → run bị bỏ qua, X chạy lại | hai sự kiện ở hai giao dịch; `reconcile` lọc theo revision; marker xoá trước khi ghi verdict | `reconciled(unknown)` LÀ hold (một giao dịch với `run_held`); `_record_issued` hoàn tất verdict từ receipt đã phát hành; marker xoá sau ghi; hold theo mốc qua mọi revision; `_begin_run` từ chối khi còn hold (`60658ec`) | `tests/test_wf_t08a_faults.py` (fault injection thật qua `plans.emit`, X đếm bằng file): trước sửa (i)(ii)(iv) đỏ; sau 5/5 + t08a_reconcile 4 + E6 2 |
| P2 | Gate chạy trên cây làm việc đang đổi, gắn commit đầu vào receipt; `0d296fe` ghi dirty | `development_gate run` kiểm checkout hiện tại | `development_gate snapshot --commit <sha>`: worktree tách rời sạch tại commit, fingerprint doc-dir + interpreter, gate chạy BÊN TRONG snapshot, từ chối nếu snapshot đổi (`bcc4d88`); gate `0d296fe` bị dừng, biên nhận cũ giữ nguyên nhãn "chạy trên cây làm việc" | `tests/test_wf_snapshot_gate.py` 3/3 (sửa ngoài không tới snapshot; sửa trong/HEAD đổi/doc đổi → refused). Gate snapshot thật trên `9107d61`: xem mục 3 |
| P2 | Trạng thái 92 task: W05/W32a/W37a ghi Done khi còn lỗi; câu "đã hoàn thành phần tự làm được" | chấm theo test có, chưa có phản chứng độc lập | Hạ về Partial ngay khi bắt đầu, nâng lại Done chỉ sau sửa + phản chứng; câu tuyên bố sửa ở đầu file; đăng ký W03/W06/W24b + 4 test review vào registry (`9107d61`); bảng 92 sinh lại | `docs/wf/audit/AUDIT-92.md` tại `9107d61`: Done 57 · Partial 31 · Blocked 4 (3 P1 quay lại Done có phản chứng) |

Manifest development thu hồi + đóng băng lại ở `9107d61` (321 pin). Lệch trước khi đóng băng lại (kitguard.verify qua `layout()`): 4 snapshot `registry`
(R01/R03/R04/R05) + `wfkit/development_gate.py` (runner snapshot, `bcc4d88`); không file test pin nào.

## 8. Lượt 2 đêm 24/10 — hoàn thiện development (chỉ thị "Tiếp tục OneCrew đến khi hoàn thiện toàn bộ")

### 8.1 Kết quả 5 dòng

- 92 task tại `ceb46c6`: **Done 72 · Partial 5 · Blocked 15** (feature 60/0/0; bộ kiểm 12/5/0; phát hành 0/0/11; provider thật 0/0/1; pilot/nghiệm thu 0/0/3). Bảng đầy đủ: `docs/wf/audit/AUDIT-92.md` (một nguồn: `overrides.json` + `tools/audit_merge.py`).
- 13 feature Partial cuối → Done: W12a, W18, W36 theo quyết định B1–B3 của chủ sở hữu; W51 liveness lệnh dài (Supervisor → progress_track, một bộ đếm với v1); W23a ba trạng thái task; W39, W11a, W46a/b, W40, W41 (finding mở thật qua rollback), W37b (host guard + phản chứng E6), W01.
- Khung phát hành chung `wfkit/release_bundle.py`: năm điều T54 chạy THẬT trên bản cài/bản sao sổ sinh và ghi thành bundle cho `release_check`; T54.1–T54.4 đạt trên biên nhận thật cho R01/R05/R08/RX1 (chạy thử), INPUTS bị từ chối đúng lý do ngoài (chưa có bản giao trước).
- Registry: T07a, T18b, T07b, T30, T38b, T14b và 9 testcase R03/R04 lên `complete` theo ma trận [E]→test đã audit (đọc test, không suy); 16 check mới; manifest đóng băng lại 361 pin. Testcase nào còn thiếu E thì gap ghi đúng danh sách E.
- Gói bàn giao: `docs/wf/audit/tools/build_package.py` + `verify_package.py` (cài venv sạch ngoài checkout từ wheel của gate, smoke qua `onecrew.exe`, kiểm module nạp từ venv, rollback/roll-forward trên bản sao sổ). Kết quả thật ghi ở 8.5 sau khi gate xong.

### 8.2 Commit lượt 2 (sau `9fc9a00`)

`bb177f0` (W05/W32a/W37a + snapshot gate, đã nêu mục 7) → `3fe7c7a` (W12a, W23a, W39, W01, U1 r01_card) → `e47bd65` (W18) → `0af3fd1` (W36 + W51) → `81f3c1d` (W11a/W46/W40 tests) → `9c49010` (W41 finding) → `07c8137` (registry 6 testcase complete, 11 check, U1 drill, tools) → `a398259` (release_bundle, installed adapters, provider matrix, package tools) → `ceb46c6` (registry R03/R04 audit, T55 cases, pilot_report, manifest 361 pin).

### 8.3 Quyết định đã ghi theo ủy quyền (không phải chữ ký chủ sở hữu)

- `wfkit/u1/U1-20261024-CARD.json` (hash sửa lại theo cách băm của kit-guard), `U1-20261024-DRILL-KIT.json`, `U1-20261024-DRILL-TEST.json` — mỗi bản ghi nêu lý do, bằng chứng, trích dẫn ủy quyền mục A của chỉ thị đêm 24/10.
- Quyết định B1–B3 của chủ sở hữu (W12a/W12b, W18, W36) được áp đúng như đã chốt; không hỏi lại.

### 8.4 Còn lại thật sự (không giấu)

- **Partial 5 (bộ kiểm, loại C — thiếu test, không phải điều kiện ngoài):** WK03 (T12 E1/E3/E4/E6; T36b 9 E: restart, đồng hồ giả, cảnh báo 70%; T43b/T43c/T47a vài E; T41a E2, T35d E3 tái hiện đỏ), WK04a (T03 E1/E7, T19 E1 assert U1 cho ca xoá test, T37 chờ O4), WK04b (T49d N1–N7 trên S2 hai bản cài; ma trận T05/T25/T26/T32/T48b/T49c/T49d/T54d), WK05b (ma trận T04c/T16b/T16c/T17c/T18a/T43d/T47c), WKPL (T14c module, cổng vào T45b/T45c độc lập, phần báo cáo z1–z12).
- **Blocked 15 (điều kiện ngoài, đủ 5 điều kiện mục G):** W40-R01…R08, RX1, RX2, RP — release_check INPUTS cần biên nhận cổng giao CG- của bản trước; chưa release nào được giao; phần cục bộ (bundle, ghi chú, drill) đã xong. W45 (CLI provider thật, có phí). W38b/c/d (pilot).
- **Phát hiện cần quyết định (ghi lại, chưa sửa vì là ngữ nghĩa):** (1) root cũ do bản cũ duyệt không có artifact gốc → kiểm toàn vẹn test (W05) của bản mới không lập được → lệnh pass bị ghi `inconclusive` (mốc failed) sau nâng cấp — giới hạn tương thích, cần chủ sở hữu chọn (giữ như hiện tại hay coi "không có baseline" là pass có ghi chú); (2) T55 CK12/CK21/CK23: `finalgate.decide` từ chối thêm KQ4/KQ7 so với bảng; (3) `tests/test_control.py` có 1 skip theo môi trường (không có redirector) nên để ngoài gate, `tests/test_host.py` đăng ký thay (T30 E1); (4) O4 (T37 E3/E6) vẫn mở.

### 8.5 Gate snapshot cuối, bundle, gói bàn giao

(điền khi gate `ceb46c6` kết thúc)
