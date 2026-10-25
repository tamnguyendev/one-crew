# Tiếp quản development từ Codex — Claude, 24/10/2026

Nhánh `codex/wf-development`, worktree `D:\TamNT\Workspace\11.OneCrew\wf-codex`. Điểm tiếp quản: `f2cc7f44` cộng phần chưa commit của Codex,
được chốt nguyên trạng thành `2bfc223` (sao lưu: `D:\OneCrewRuns\wf-codex-handoff-backup-20261024`). Không reset, không ghi đè; sổ thật,
worktree khác và job đang chạy không bị đụng. Không push, tag, publish; không approve/accept trên sổ thật; không gọi provider trả phí.

Trạng thái (cập nhật lần 4, đêm 24/10 ~22:45, lượt "hoàn thiện toàn bộ development"): **mọi việc local trong phạm vi đã giao đã làm xong hoặc ghi rõ phần còn thiếu**; mã cuối `ceb46c6`; gate snapshot cuối trên `ceb46c6`: 195/195 kiểm hiện thực đạt (mục 8.5); gói bàn giao đã kiểm từ artifact. Còn Partial 5 task bộ kiểm (thiếu test/ma trận, không phải điều kiện ngoài — mục 8.4) và Blocked 15 task cần điều kiện ngoài (bản giao trước thật, provider thật, pilot). Chưa có nghiệm thu sản phẩm; review Codex lượt 1 (`9aca8be`) đã xử lý xong, chưa có review lượt 2.

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

### 8.5 Gate snapshot cuối, bundle, gói bàn giao (kết quả thật)

- **Gate snapshot `ceb46c6`** (`%TEMP%\wf-snapshot-gate-20261024-ceb46c6`, log `D:\OneCrewRuns\wf-dev-logs\snapshot-gate-ceb46c6.txt`): **195/195 kiểm hiện thực đạt, 1 541 test, 0 skip, 0 hỏng**; kit-guard đạt (pin R00 `test_wf_plan_names.py` lệch được bù bằng lineage W12b, đúng cơ chế); nguồn cài đạt, control checkout bị từ chối; tự kiểm tài liệu đạt; snapshot nguyên vẹn. `decision = refused` CHỈ vì 61 testcase acceptance partial + 10 blocked trong registry (không release nào đủ điều kiện giao) — không phải lỗi mã. Wheel `onecrew-2.2.0.dev3` sha256 `c44704da3585172e373f75f356f0942f3f702a782660a336af427c606294ac44`.
- **11 bundle T54** (`wfkit.release_bundle`, trên đúng wheel/commit của gate, `%TEMP%\wf-bundles-ceb46c6`): R01…R08, RP, RX1, RX2 đều **T54.1–T54.5 đạt trên biên nhận thật**; **INPUTS không đạt** ở cả 11 vì "previous delivered gate history missing" (điều kiện ngoài: chưa release nào được giao; bản trước = d3120c6). RP mang ma trận W45 thật (4/6 dùng được, P1.0 = subset).
- **W45 chạy thật** (ủy quyền chat đêm 24/10): `D:\OneCrewRuns\wf-w45-matrix-ceb46c6\matrix.md` — claude reviewer/cố vấn đạt (claude.exe 2.1.286, $0.18), kiro reviewer/cố vấn đạt (kiro-cli 2.30.0→2.34.0, tự cập nhật giữa hai lần gọi — hai sha ghi riêng), codex 2 ô chưa kiểm chứng (không có CLI codex trên máy). Harness `wfkit/provider_matrix.py` thêm SAU commit gate (kit, không nằm trong wheel).
- **Gói bàn giao** `D:\OneCrewRuns\wf-handover-ceb46c6` (491 file + SHA256SUMS; `README.md` cách cài/smoke/rollback; `manifest.json`): wheel + wheel bản trước, gate (decision, snapshot, kitguard, build, 195 biên nhận, log), 11 bundle, ma trận provider, docs (AUDIT-92, FEATURE-SCOPE, release notes, registry + manifest), `verification/verify-report.json`.
- **Kiểm từ artifact** (`verify_package.py` → `D:\OneCrewRuns\wf-verify-ceb46c6`): **pass**, 19 bước — SHA256SUMS khớp; venv sạch ngoài checkout; cài wheel từ gói; `onecrew --help`; một root code propose→approve→`verdict run` qua `onecrew.exe` của venv đạt M1; `plan report`; mọi module `onecrew.*` nạp từ venv; checkout không trên sys.path; `compat scan` chỉ đọc trên bản sao sổ; cài wheel bản trước (`plan digest` exit 2 — **SUPERSEDED 25/10: đó là UnicodeEncodeError của tiến trình con (cp1252), không phải hành vi namespace; script kiểm cũ còn ghi pass dù có bước ok=false — review a2476ab P1, sửa ở mục 9**); roll-forward đọc lại root, sổ không đổi.
- **Bảng 92 cuối** (`docs/wf/audit/AUDIT-92.md` tại `ceb46c6`): **Done 73 · Partial 5 · Blocked 14** (feature 60/0/0; bộ kiểm 12/5/0; phát hành 0/0/11; provider thật 1/0/0; pilot 0/0/3).
- Không có: nghiệm thu của chủ sở hữu, Codex review lượt 2, release nào đã giao.

## 9. Lượt 3 (25/10) — review Codex tại `a2476ab`: 4 P1 + 2 P2, sửa và kiểm lại

Chỉ thị chủ sở hữu 25/10: sửa hết, hoàn tất phần local, chạy lại gate và kiểm chính gói trên snapshot cố định, không hỏi duyệt từng việc. Mã lượt 3: **`c95f603`**; mã lượt 4 (9.4): **`6366137`**; mã lượt 4 (9.4): **`6366137`** (manifest 393 pin; U1-20261025-RC-VALIDATOR / -RC-TESTS / -RB-TEST ghi theo ủy quyền cho ba file kit bị siết chặt).

### 9.1 Sáu finding — nguyên nhân, sửa, phản chứng

| # | Finding | Nguyên nhân | Sửa | Phản chứng trước → sau |
|---|---|---|---|---|
| P1-A | `verify_package.py` báo PASS dù có bước FAIL; `plan digest` exit 2 là lỗi encoding; nhánh scan chặn vẫn cài bản cũ | result gán vô điều kiện; tiến trình con không có PYTHONUTF8; một nhánh rollback | `wfkit/package_check.py`: `judge()` suy kết quả từ bước bắt buộc, từ chối báo cáo không nhất quán, lỗi encoding, negative sai lý do, pip chạy trong nhánh bị chặn; hai bản sao sổ (có chặn / không chặn); con chạy UTF-8 | `tests/test_wf_package_check.py` 13: báo cáo cũ (ok=false + pass) bị từ chối là "incoherent"; `UnicodeEncodeError` exit 0 bị từ chối; nhánh chặn với pip>0 bị từ chối; gói thật: refused trên bản sao có B1, allowed trên bản sao sạch |
| P1-B | T54.1 cho qua kịch bản import-only (R02/R04/R06/R07/R08/RP) | probe `import onecrew...` được chấm đạt | Khung `tests/wf_scenarios.py` + 38 kịch bản HÀNH VI khai báo theo release (yêu cầu W-task → assertion → sự kiện); `release_check` T54.1 đòi assertion đạt, sự kiện ghi thật, ranh giới module, trình thông dịch venv, mọi task của release được chứng minh | `test_wf_release_check` T54.1: không kịch bản / import-only / feature tắt / im lặng / result giả / checkout che module / sai wheel / sai interpreter / thiếu task → refused; `test_wf_scenarios` phản chứng khung |
| P1-C | T54.3 không kiểm đủ sự kiện của release (R06 thiếu incident/lesson, R08 thiếu pause) | producer tự chọn tập so | `wfkit/release_events.json` = inventory của validator; T54.3 so inventory kỳ vọng với quan sát từ kịch bản bản cài, mẫu sự kiện thật từng kind, so S/G/C bản cũ từng kind lớp A (probe R0+A với payload thật); release không thêm kind phải nêu lý do + kịch bản hồi quy đạt | bỏ kind / feature không phát / sai lớp / sai anchor / thiếu so bản cũ / inventory release khác / inventory bị thu hẹp → refused; phát hiện thêm: `decision.hold/defer` không có writer trong sản phẩm → không đưa vào inventory (ghi chú) |
| P1-D | Root cũ sau nâng cấp kẹt `inconclusive` vì thiếu baseline | duyệt bản cũ không có artifact gốc; fixture không có `at` và dòng sổ trước mọi commit | `plan.derive` mang `recorded_at` (giờ dòng sổ); `reviewer.base_tree`: base_artifact → baseline chủ sở hữu ghi → commit cuối trước lúc duyệt; `verdict baseline` (chỉ chủ sở hữu, có chứng cứ, không ghi đè, phiên AI bị từ chối); báo cáo chỉ đường | `tests/test_wf_t13b_legacy_baseline.py` 3: (a) giờ dòng sổ → pass; (b) không commit trước → inconclusive có lý do, AI không ghi được, chủ sở hữu ghi → pass, không ghi đè, binary cũ vẫn đọc; (c) root mới giữ base_artifact; bundle: route first=inconclusive → baseline → passed |
| P2-A | Partial/Blocked còn việc local | — | 8 module gap test (23) cho R03/R04; kit pilot T14c/T45b/T45c (24); audit [E] R04/R05/R06/R07/R08/RX1/KN áp vào registry (T04b/T15c hạ xuống partial vì E6/E8 chưa phủ) | 9 testcase lên complete có ma trận; E còn thiếu ghi đúng trong gaps (T36b E4/E7/E17 cần đổi sản phẩm) |
| P2-B | Số liệu/báo cáo mâu thuẫn | — | `docs/wf/audit/tools/gate_numbers.py` (check, lượt chạy suite, lượt test cộng dồn, test id duy nhất); mục 9.3; một nguồn trạng thái (`overrides.json` → AUDIT-92) | — |

### 9.2 Những gì KHÔNG đổi, và những gì ghi lại

- Không sửa validator để nhận import-only; không nới acceptance; không đổi receipt cũ; không chạy lại provider trả phí (ma trận W45 là bằng chứng của wheel `ceb46c6`; với artifact mới, luật hiệu lực HL cho `cần kiểm lại`, ghi trong bundle RP).
- Số 72/5/15 (23/10 23:00, ceb46c6 trước W45) và 73/5/14 (25/10 00:10, sau W45) là hai mốc lịch sử; mốc hiện hành ở 9.3.
- Phát hiện giữ cho chủ sở hữu/Codex: T36b E4/E7/E17 (đổi sản phẩm), CK12/CK21/CK23 (bảng vs cổng), O4 (T37), `decision.hold/defer` chỉ là tên dự phòng.

### 9.3 Gate snapshot `c95f603` (lượt 3) — kết quả thật

Gate `%TEMP%\wf-snapshot-gate-20261025-c95f603`: wheel sha256 `39578d4561859dda678c4cac318b9a19d0b83ac6c2bd0dc1f927d19348113b0d`; 212/212 check implementation đạt (212 lượt chạy suite, 1 710 lượt test cộng dồn, 0 skip, 146 module, 1 345 test id duy nhất); từ chối chỉ vì acceptance-partial 49 + acceptance-blocked 10 (đúng kỳ vọng: gate không tự nghiệm thu).

Bundle trên `c95f603` (`%TEMP%\wf-bundles-c95f603`, đã bị thay): R01–R04 đạt T54.1–T54.4; **R05–R08 bị từ chối tại T54.1** "release tasks without a behaviour scenario"; RP/RX1/RX2 lỗi vì file kịch bản bị sửa giữa lúc chạy (lỗi quy trình của tôi, không phải sản phẩm). Nguyên nhân và sửa ở 9.4. Không có gói nào được dựng từ `c95f603`.

### 9.4 Lượt 4 — từ chối bundle R05–R08, công cụ kiểm tiếp tục root cũ từ gói, gate `6366137`

**Vì sao validator từ chối mà gate test lại đạt.** `release_check` T54.1 đọc task của một yêu cầu kịch bản là token đầu tiên (tách theo khoảng trắng). File kịch bản R05–RX2 viết `'W17: text'`, `'W36/W18: text'` nên token đọc được là `W17:` / `W36/W18:` — không trùng task nào trong inventory → "release tasks without a behaviour scenario". Gate test `tests/test_wf_scenarios.py` lúc đó chỉ kiểm thân kịch bản, không áp cùng cách đọc, nên đạt. Sửa (commit `20916f5`, U1-20261025-SCN-TASKS theo ủy quyền, manifest 395 pin, re-freeze `6366137`):
- 25 chuỗi yêu cầu trong `tests/wf_scenarios_r05_rx2.py` viết lại đúng dạng `W17 text`; R05 bổ sung yêu cầu W26 vào kịch bản đã sẵn kiểm W26 (`r05-findings-holds-retained`).
- Khung `tests/wf_scenarios.register` từ chối ngay lúc khai báo token trông như task id mà không phải (`W47:`, `W36/W18`).
- Gate test áp CÙNG cách đọc của validator: mọi task trong inventory của release phải được chứng minh bởi token đầu của một yêu cầu; hai phản chứng (`['W47: proposal check']`, `['W36/W18 holds']` → ValueError). Validator **không đổi**.

**Kiểm tiếp tục root cũ TỪ GÓI (P1-D, mục bắt buộc của chỉ thị).** `docs/wf/audit/tools/legacy_continuation.py` (ngoài kit pin) chạy bản cũ (`previous_wheel` trong manifest gói) trong venv riêng để tạo root `plan:` thật với dòng `plan.approved` trước W05 (không `at`, không `base_artifact`, 2000-01-01), rồi bản mới từ gói: `verdict run` → `inconclusive` + phân loại `insufficient` + lỗi "no approved baseline" + trang bàn giao chỉ đường `verdict baseline`, O1 không "đạt"; `verdict baseline` bị từ chối với `ONECREW_ACTOR=claude` và với commit không có trong repo (exit≠0, 0 sự kiện ghi); chủ sở hữu ghi → một `plan.baseline_recorded` có tree = `HEAD^{tree}`; chạy lại → `passed`; ghi lại không ghi đè; anchor/revision/approved không đổi; module nhập từ venv. `judge()` quyết từ 14 bước bắt buộc (negative phải fail đúng lý do, lỗi encoding bị từ chối, báo cáo tự nhận pass có lý do → incoherent). Kiểm: `tests/test_wf_legacy_continuation_tool.py` 6 (testcase PL `check.legacy_continuation_tool`, trong gate); `tests/test_wf_legacy_continuation_real.py` chạy trên gói đã dựng với `WF_PACKAGE` (không trong registry vì phải skip khi không có gói). Phản chứng trước: chạy trên gói cũ `wf-handover-ceb46c6` → refused tại `legacy_inconclusive_not_passed` (bản `ceb46c6` báo "The plan has no approval time or base artifact…", không chỉ đường).

**Gate snapshot `6366137`** (`%TEMP%\wf-snapshot-gate-20261025-6366137`, log `D:\OneCrewRuns\wf-dev-logs\snapshot-gate-6366137.txt`): wheel sha256 `503f624f8912857f9fff2e51a725bcaa161c7c0c296dfade0ca271b7a4b31237`; **213/213 check implementation đạt**, 213 lượt chạy suite, 1 716 lượt test cộng dồn, 0 skip, 147 module, 1 351 test id duy nhất (`gate_numbers.py`); từ chối chỉ vì acceptance-partial 49 + acceptance-blocked 10 (không có check implementation nào thất bại; exit 1 của gate là "refused" theo thiết kế).

**Bundle trên `6366137`** (`%TEMP%\wf-bundles-6366137`, ma trận W45 của `ceb46c6`): **11/11 bundle đạt T54.1–T54.4 trên biên nhận thật** (R05–R08 nay đạt T54.1 với kịch bản hành vi đúng token; RX1/RX2 đạt); T54.5 đạt 10/11 ở lượt chạy đầu, **RP T54.5 không đạt: "comparison missing"** = luật hiệu lực HL đúng thiết kế: ma trận W45 thuộc wheel `ceb46c6`, artifact mới chưa có so sánh → ghi `cần kiểm lại`, không chạy lại provider trả phí (ngoài quyền áp dụng), không đổi hash receipt cũ. INPUTS không đạt ở cả 11 ("previous delivered gate history missing": chưa release nào được giao; điều kiện ngoài). `simulated_receipts_used = false`. Release notes 12 file sinh lại từ gate + bundle (`docs/wf/release-notes/`).

**W45 chạy lại trên wheel `6366137` (chủ sở hữu cho phép trong chat 25/10: "Cho chạy lại W45 trên wheel 6366137")**: `wfkit.provider_matrix` từ venv sạch cài wheel của gói → `D:\OneCrewRuns\wf-w45-matrix-6366137` (matrix.json commit/wheel = 6366137, receipt từng ô có sha CLI): claude reviewer/advisor usable, kiro reviewer/advisor usable, codex 2 ô unverified (CLI không có) → P1.0 = subset 4/6, như lần `ceb46c6`. Bundle RP chạy lại với ma trận này: **T54.1–T54.5 đạt**, chỉ còn INPUTS (ngoài). Ma trận cũ của `ceb46c6` giữ nguyên, không đổi hash. Gói dựng lại với ma trận mới; bản dựng trước giữ ở `wf-handover-6366137-pre-w45`.

**Gói bàn giao `D:\OneCrewRuns\wf-handover-6366137`** (526 file; wheel `onecrew-2.2.0.dev3-py3-none-any.whl` sha256 `503f624f…b31237`, bản trước `ceb46c6`/d3120c6 trong `wheel/previous/`, `manifest.json`, `SHA256SUMS`, gate + receipts, 11 bundle, ma trận W45 của `ceb46c6`, bảng 92, release notes). Kiểm TỪ ARTIFACT, venv sạch ngoài checkout:
- `verify_package.py` → `D:\OneCrewRuns\wf-verify-6366137`: **pass, 26/26 bước** (SHA256SUMS, hash wheel, venv, pip, smoke, verdict run, plan report, module từ venv, checkout không trên path; bản sao sổ có B1 → scan chặn, pip không chạy, cài đặt/sổ không đổi; bản sao sạch → gỡ bản mới, cài bản cũ, digest cũ đọc được, bản cũ không đọc `plan-ns:` root, sổ không đổi, cài lại bản mới = cùng build, roll-forward đọc lại, sổ không đổi).
- `legacy_continuation.py` → `D:\OneCrewRuns\wf-legacy-6366137`: **pass, 14/14 bước bắt buộc** (root `plan:` thật do bản cũ tạo + duyệt trước W05 → bản mới: inconclusive/insufficient/"no approved baseline", trang bàn giao chỉ `verdict baseline`; AI bị từ chối exit 2, 0 sự kiện; commit lạ bị từ chối exit 2, 0 sự kiện; chủ sở hữu ghi 1 `plan.baseline_recorded` tree = HEAD; chạy lại → passed; ghi lại không thêm; anchor/revision/approved không đổi; module từ venv).
- `WF_PACKAGE=<gói> python -m unittest tests.test_wf_legacy_continuation_real` → **OK (1 test, ~28 s)**.
- Phát hiện khi kiểm thật (sửa trong lượt này, ngoài kit pin): lần chạy đầu `legacy_continuation.py` **refused** vì judge của tôi đoán sai câu từ chối (chờ "owner"/"not in") trong khi sản phẩm nói "an AI cannot approve or accept" và "git rev-parse --verify failed: … Needed a single revision" (đúng hành vi, exit 2, 0 sự kiện). Sửa needle theo đúng câu sản phẩm; bài test thật là cái bắt lỗi này. Ghi chú cho Codex: câu từ chối commit lạ của `verdict baseline` là lỗi git thô, nên nói rõ "commit không có trong repo" (không chặn).
- Báo cáo kiểm được chép vào `<gói>/verification/` (không nằm trong SHA256SUMS, như gói trước).

Không ghi: Codex đã review lượt 4, chủ sở hữu đã nghiệm thu, release đã giao — chưa xảy ra. Gate `decision = refused` vì acceptance partial/blocked là đúng thiết kế.

## 10. Lượt 5 (25/10) — Codex xác nhận 3 P1 + 2 P2; đối chiếu lại 92 task; sửa 21 lỗi hành vi

Chỉ thị chủ sở hữu 25/10 (sau review Codex gói `wf-handover-6366137`): sửa đủ 3 P1 + 2 P2, khép phần local của 92 task, bootstrap bản giao đầu tiên, snapshot mới và kiểm từ artifact; không hỏi duyệt từng việc. Mã lượt 5: **`__COMMIT5__`** (wheel `2.2.0.dev4`, phân biệt với mọi wheel trước). Mọi bản ghi U1 lượt này ghi "theo ủy quyền" (`wfkit/u1/U1-20261025-R5-*.json`).

### 10.1 Năm finding Codex — nguyên nhân, sửa, phản chứng trước → sau

| # | Finding | Nguyên nhân | Sửa | Phản chứng trước → sau |
|---|---|---|---|---|
| P1-1 | `package_check.judge` nhận báo cáo sai thành PASS (hạ `mandatory`, đổi `expect`) | oracle đọc từ báo cáo | Oracle là hằng của module: bước bắt buộc, luật `ok` từng bước TÍNH LẠI từ quan sát đã ghi, kỳ vọng negative cố định; báo cáo chỉ cung cấp quan sát; từ chối hạ bước, trùng id, thiếu fact, `ok` lệch fact, đổi expect, exit 0 ở negative. Cùng luật cho judge của `legacy_continuation.py` | `tests/test_wf_package_oracle.py` 15 + `test_wf_package_check` 12 + `test_wf_legacy_continuation_tool` 12: bypass 1, bypass 2 và 9 biến thể pass trên judge cũ → refused; gói thật 6366137 vẫn pass |
| P1-2 | Trả lời và hiệu lực không nguyên tử | `ledger.reply` commit riêng rồi `answer_effects.apply` | `Ledger.reply(conn=)`/`_reply`; `answer_effects.reply_and_apply` một transaction cho reply + hiệu lực bắt buộc; export/outcome sau commit; MỌI entry (question answer, `request reply`, MCP) đi qua cùng helper; `reconcile` chỉ sửa dữ liệu bản cũ | `tests/test_wf_answer_atomicity.py` 18: crash trong hiệu lực → request vẫn pending, 0 sự kiện; crash sau commit → cả hai đã commit; retry một lần; trùng/cũ/xung đột; provenance; stop + continue; bất biến answered⇒applied trên mọi route (6 ca fail trên code cũ) |
| P1-3 | Bảng 92 khẳng định Done quá bằng chứng (73/5/14; 60/60 feature) | trạng thái cũ, "module xanh" = Done | Đối chiếu lại đủ 92 ID (5 agent Opus + đầu mối), phát hiện **21 lỗi hành vi** (xem 10.2), sửa hết trừ W11b (quyết định chủ sở hữu); bổ sung bằng chứng đúng loại cho 11 task thiếu [E]; `audit_merge.py` in NĂM MỨC riêng (task Done / acceptance complete / gate / gói / owner acceptance) từ một nguồn | Trước đối chiếu 73/5/14 → sau đối chiếu, trước sửa **30/61/1** → sau sửa **__T92__**; bảng đầy đủ `docs/wf/audit/AUDIT-92.md` |
| P2-1 | Thời gian chờ tính vào thực thi; thiếu thời gian tới deadline | `executors.summary` không trừ wait; `wall_clock_remaining_seconds` luôn None | Ngữ nghĩa cố định: thực thi = (end−start) − hợp các wait cắt trong attempt (gộp chồng/lặp, unknown lan truyền, không đoán); chờ = hợp wait; `read(now=)` → time-to-deadline riêng (`wall_clock_kind`, `deadline_passed`, không clamp); cảnh báo 70% ngân sách = một `notice.exception budget_warning` trong quyền, không request, không lặp | `tests/test_wf_t36b_time.py` 10 (ca Codex 08–12/09–11 → 2 h/2 h) + e4_e7 chờ trong attempt; E4/E7/E15/E17(70%) có test; E17 phần "ETA trễ" chưa có test riêng |
| P2-2 | Gói thiếu công cụ kiểm mà README gọi | verify_package ở checkout, wfkit không trong wheel | Thư mục `verify/` giao trong gói (package_check.py, legacy_core.py, hai launcher stdlib), ghim hash trong `manifest.verifier` + SHA256SUMS; launcher TỰ KIỂM hash trước, nạp module chỉ từ `verify/`, ghi `verifier-origin.json`; README chỉ gọi file có trong gói, cwd bất kỳ, có khoảng trắng | `tests/test_wf_package_verifier_shipped.py` 9: sửa 1 byte / xóa file / sai manifest / file lạ → refused, không tạo venv; chạy từ cwd mới có khoảng trắng, env sạch → origin toàn bộ dưới `verify/` |

### 10.2 Đối chiếu 92 task: 21 lỗi hành vi tìm thấy và sửa (mỗi lỗi có phản chứng fail-trước)

W32a, W30c (hai finding Codex); W24b notice lặp theo hash evidence → key theo lần vượt baseline + gộp; W03 phiên AI ghi được quyết định/duyệt dưới danh owner → từ chối ở decisions/conversations/skills/cards; W12a key `plan:` không kiểm tên, `NUL`, `x.` → kiểm trước mọi ghi, anchor + revision một transaction; W41 `guard_swap` không đọc block của scan bản cài → từ chối; W47 requirement không gắn với plan → hash-bound; W30a lựa chọn "technical" với grant bịa → phải resolve grant thật; W31a unknown mở không có affected/required_by → bắt buộc trên plan-ns; W23b 200 outcome v2 đẩy lịch sử v1 → cửa sổ theo phân vùng; W02 root workflow không có `authority` cho job con ghi ngoài scope → chấm theo effective; W05 tách node bỏ check / module helper yếu / đổi cwd-provider = routine → U1/insufficient; W10 3×100 call dưới một duyệt 100 → tổng hạn mức ≤ duyệt; W12b hai root một writer sống trên cùng file → từ chối; W19 marker sửa cũ kẹt node → rebind khi revise; W37a reconcile tin lý do 'error' → marker trước, dispatched không receipt = held; W14b `a.txt`/`A.txt` chạy song song → case-fold; W36+W37b candidate đã lưu trước node.produced bị bỏ, chạy lại tính phí 2 → engine adopt; W20 không có blocker khi chạm trần → blocker spent==ceiling + authority_basis; W46b (từ bằng chứng mới) compat scan dự đoán "refused" cho `plan report` của bản cũ trên tên trùng trong khi bản cũ in report của root project khác → nhãn `reads_other_root`. **W11b** (luật T19 áp cho root schema-2) không sửa: đổi acceptance, cần chủ sở hữu.

Bộ kiểm WK01–WKN: trước ghi Done chỉ vì "module xanh" dù để lọt các lỗi trên → Partial C cho tới khi acceptance của release tương ứng complete; các phản chứng mới đã nằm trong kit.

### 10.3 Bản giao đầu tiên (INPUTS) — kết luận có bằng chứng

Không có lịch sử giao thật: receipt gate R00 duy nhất đạt (`cg-r00`) thuộc build d467546 (wheel `0981dbd0…`), khác bản trước của bundle (d3120c6, scanner chỉ mô hình d3120c6) và không có trường `gate`. Vì vậy: (1) đường bootstrap tường minh trong `release_check` — trường `first_release.baseline` (commit, wheel sha, role compat-baseline, delivered=false, accepted=false), điều kiện riêng **`INPUTS(bootstrap)`**, từ chối khi có bất kỳ `gate_history`, khi baseline khác `artifacts.previous`, khi receipt drill không chứng minh đã chạy đúng baseline, khi baseline ghi delivered/accepted; luật INPUTS thường không đổi; `owner_acceptance` luôn false; (2) baseline d3120c6 ghim một lần tại `D:\OneCrewRuns\wf-baseline-d3120c6\` (wheel + sidecar; kiểm từng file bằng git blob) và producer dùng lại qua `--baseline-wheel`; (3) `gate.decide` ghi `gate: CG-<release>` + provenance để một gate đạt đọc được làm lịch sử; `wfkit/delivery_gate.py` = cổng CG-Rnn cho R01+ theo 03 §4 ("mỗi cổng giao do AI chạy, không cần chủ sở hữu"), **refused** trên snapshot này vì acceptance còn partial và chưa có bản ghi review độc lập; `wfkit/gate_history.py derive` chỉ tạo receipt lịch sử khi chứng minh được identity trên đĩa. 38 + 11 test.

### 10.4 Gate snapshot `__COMMIT5__`, bundle, gói, kiểm từ artifact

__GATE5__

### 10.5 Không ghi

Codex đã review lượt 5, chủ sở hữu đã nghiệm thu, release đã giao, W45 6/6: chưa xảy ra. Gate `refused` vì acceptance partial/blocked là đúng thiết kế.

