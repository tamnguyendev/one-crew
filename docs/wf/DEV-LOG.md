# DEV-LOG — development chương trình workflow chung

## Claude tiếp quản từ Codex — 24/10 chiều, cùng nhánh `codex/wf-development`

- Điểm tiếp quản `f2cc7f4` + phần chưa commit của Codex, chốt nguyên trạng ở `2bfc223` (sao lưu `D:\OneCrewRuns\wf-codex-handoff-backup-20261024`). Codex đã dừng; agent Sonnet của lượt sáng (nhánh `wf/*`) bị cắt vì hạn mức chi tiêu, kết quả của chúng không ghép vào nhánh này.
- Ownership: một người làm (Claude) trên worktree `wf-codex`; không agent phụ sau khi hạn mức reset vì hàng đợi tích hợp là nút cổ chai, không phải thông lượng code.
- Đường găng đã đi: candidate reviewer/reuse (A) → W15/W36/W37b/hook holds (B, C) → sửa lỗi có sẵn của bản Codex → registry + T39 → đóng băng manifest → gate tích hợp một wheel.
- Báo cáo tiếp quản, bảng đối chiếu handoff, giới hạn và gói cho Codex review: [TAKEOVER-CLAUDE-2026-10-24.md](TAKEOVER-CLAUDE-2026-10-24.md). Phạm vi → testcase → trạng thái: [FEATURE-SCOPE.md](FEATURE-SCOPE.md) (sinh từ registry).
- Log test: `D:\OneCrewRuns\wf-dev-logs\*.txt` (takeover-*, fixA-*, fixB-*, fixC-*, fixE-*, regress-*, groupE-*, t39-*, dev-gate-*, cg-r00-*).
- Blocker thật còn lại: W45 provider thật (cần cho phép chi phí), PL-A/PL-B việc thật, nghiệm thu chủ sở hữu. Không gọi là hoàn tất toàn bộ chương trình.

## Codex tiếp quản development — 24/10, nhánh riêng

- Nhánh `codex/wf-development`, worktree `D:\TamNT\Workspace\11.OneCrew\wf-codex`, nền `d3120c6`; các worktree Claude và sổ thật giữ nguyên.
- Sol: implementation/test theo module (retention/namespace/binding; findings/discovery). Astra: bằng chứng bàn giao, quyền hạn, review các chỗ nối và rollback. Parent: tích hợp, report/policy, kiểm bản cài. Tối đa ba agent phụ trong phiên này.
- Dùng lại W30a/W47 đã commit; W23a và W31a dùng snapshot có hash từ nhánh Claude rồi kiểm độc lập. Không coi thay đổi đang làm ở nhánh nguồn là hoàn thành.
- Commit đã kiểm: `230089a` (danh tính CLI), `53e07f1` (CG-KET từ dữ liệu thật của bundle; fixture không phải pilot thật), `038a0b3` (quyền root, sửa các đường cho qua sai).
- Namespace/retention/findings và policy đang ghép; review đã tái hiện và sửa trường hợp dùng pass cũ để đóng finding sau fail mới. Việc nối job với root tường minh và scan rollback đang được kiểm.
- Checkpoint tích hợp: R01 40 ca; R02 57 ca (các lỗi fixture/helper được sửa và chỉ chạy lại ca hỏng); R03 quan sát 34 ca +7 ca sửa hẹp; metrics 20 ca; root budget 9+2 ca và goal v1 10 ca; RX1 79 ca được đối chiếu, generic finding 4 ca. Số đếm theo suite, có thể chồng nhau, không cộng thành một tỷ lệ hoàn thành.
- Bản cài tạm offline: luồng Git đã đi qua approval→verdict→retention→context→accept→outcome→metrics→resume. Ca dữ liệu ngoài Git phát hiện lỗi step0 đòi Git; đã sửa target `ref=snapshot`, chạy lại ca từ wheel đạt. Không dùng emit duyệt giả để che lỗi này.
- Một ca P6 prompt-cap của bộ v1 dài hỏng ngay ở baseline trước extraction; giữ log, không đổi test để cho qua. Các ca register 26 trước/26 sau và learning 3 trước/3 sau đạt.
- Tiếp tục development: engine/internal revision/điều phối; thông báo dùng outbox v1; incident/lesson/localization. Chưa coi checkpoint này là hoàn thành WF.
- Bằng chứng chi tiết và phần chưa xong: `docs/proposal-coverage.md`. Log tại `D:\OneCrewRuns\wf-dev-logs\codex-*.txt`. Chưa phát hành hay nghiệm thu toàn bộ WF.
- Checkpoint tiếp: engine tuần tự dùng Control/ready_batch v1, worker pin riêng provider/model; core tiến triển/recovery và outbox được tách một nguồn để v1/v2 cùng dùng. Trả lời dừng đóng root, tiếp tục giữ nguyên quyền/budget và kiểm generation. Receipt hết hiệu lực khi input/config/môi trường đổi. Lỗi sửa xong có incident và lesson project trước khi root xong.
- Kiểm tích hợp 55 ca đạt; hàng rào kết quả về muộn sau đóng root được kiểm thêm trong nhóm 19 ca đạt. Bản cài notification và stale evidence đã chạy offline; provider/window dùng fixture, không phải chứng nhận dùng thật. Tiếp tục candidate checker/handoff, unknown, repair và DAG song song; không dừng ở checkpoint này.

Ngắn, cập nhật theo checkpoint. Phạm vi và trạng thái từng task: [FEATURE-SCOPE.md](FEATURE-SCOPE.md).

## Quyết định ảnh hưởng implementation

| Ngày | Quyết định | Lý do / nguồn |
|---|---|---|
| 24/10 | Development làm trực tiếp trên nhánh `wf/dev` (worktree `D:\TamNT\Workspace\11.OneCrew\wf-dev`), agent phụ làm trên nhánh `wf/<task>` riêng, ghép vào `wf/dev`. Không đi qua hợp đồng v2 trên sổ thật, không ghi approve/accept. | Chỉ đạo chủ sở hữu 24/10 (quyền development một lần; không tự ghi approve/accept; sổ thật giữ nguyên) |
| 24/10 | Dùng lại R00 do KiroCrew làm (`wf/r00@c3ad00a`, 7 task); không làm lại. Worktree `wf-r00`, `wf-integration` của KiroCrew giữ nguyên, không ghi vào. | Kiểm lại trên `wf/dev@c3ad00a`: 57/57 test WF R00 đạt (36 s), log `D:\OneCrewRuns\wf-dev-logs\r00-wf.txt` |
| 24/10 | Bộ kiểm từng release (WK*) đặt trong repo (`tests/test_wf_*.py` + lệnh cổng trong repo), không ở `verify-kit\wf\` (thư mục không có Git). Kit-guard dùng manifest sha256 của file test. | Để test có version cùng code và review được |
| 24/10 | Vòng sửa tài liệu L (CG-KET) dừng; phần còn thiếu (bộ đánh giá tính KQ1–KQ7 từ dữ liệu biên nhận/artifact/đối chiếu/lịch sử) thành yêu cầu code của W38d/T45d ở KET. | Chỉ đạo 24/10 §6 |

## Tài nguyên (đo 24/10 09:3x)

i5-1340P 12 nhân / 16 luồng, tải ~2%; RAM 31,6 GB, trống 16,6 GB; C: trống 21,8 GB, D: trống 43,9 GB. Đang chạy của người khác: Codex app, các tiến trình Claude Code; không dừng. Agent phụ: tối đa 6–7 đồng thời (bộ nhớ, tích hợp theo kịp).

## Đường găng

R00 (xong) → R04 (16 task) → R05 (17) → R08 (7) → KET. R03 cần R01. Đợt 1 chạy song song: R01, R02, R04 phần 1, RP (W43), RX1.

## Agent / task / ownership

| Agent | Nhánh / worktree | Task | File chính (owner) | Trạng thái |
|---|---|---|---|---|
| r01-step0 (Sonnet) | `wf/r01-step0`, `D:\OneCrewRuns\wf\r01-step0` | W30a, W47, W31a | `v2/step0.py`, module thẻ/đề xuất mới | đang làm từ 09:5x |
| r01-report (Sonnet) | `wf/r01-report`, `D:\OneCrewRuns\wf\r01-report` | W23a | `v2/report.py`, lệnh `plan present` | đang làm |
| r02 (Sonnet) | `wf/r02`, `D:\OneCrewRuns\wf\r02` | W23b, W48a, W48b | module outcome/gói tiếp tục/ngữ cảnh mới | đang làm |
| r04a (Sonnet) | `wf/r04a`, `D:\OneCrewRuns\wf\r04a` | W01, W02, W06, W04, W05, W10 | `v2/contract.py`, `plan.py`, `gate.py`, `lint.py`, `budget_core.py`, `task_intake.py` | đang làm (đường găng) |
| rp-w43 (Sonnet) | `wf/rp-w43`, `D:\OneCrewRuns\wf\rp-w43` | W43 | `v2/verifiers/reviewer.py`, `advisor.py`, `claude_cli.py`, adapter provider | đang làm |
| rx1 (Sonnet) | `wf/rx1`, `D:\OneCrewRuns\wf\rx1` | W22 | `v2/verifiers/doc.py` (mới) | đang làm |
| kit (Sonnet) | `wf/kit`, `D:\OneCrewRuns\wf\kit` | WK0, WK00 (T45a, T38a) | `wfkit/` (mới), `tests/test_wf_kit.py` | đang làm |
| r03a (Sonnet) | `wf/r03a`, `D:\OneCrewRuns\wf\r03a` | W44, W33a, W23c | `v2/verdict.py`, `hook_cli.py` (Stop), module quan sát/số đo mới | đang làm |
| chính (Opus) | `wf/dev`, `wf-dev` | tích hợp, kiểm lại, W40-Rnn | — | — |

File dùng chung giữa nhánh (sửa nhỏ, cộng thêm, agent chính gộp): `v2/contract.py`, `step0.py`, `plan.py`, `cli.py`, `compat.py`, `pyproject.toml`.

## Hàng đợi tích hợp

(trống)

## Checkpoint

- 24/10 ~09:40: `wf/dev@c3ad00a` = R00. FEATURE-SCOPE sinh từ 04 (hash 04 c1d8f8ae40cd).
- 24/10 tối (Claude, tiếp quản và hoàn thành): 20 task feature Partial → Done với code nối đường dùng + 36 test mới (W48a, W50b, W33a, W37a, W21, W26, W20, W05, W14b, W15, W23d, W49b, W32a, W30b, W24, W24b, W06, W03, W17, W44); registry +19 check, 9 case complete; manifest development đóng băng lại ở `0d296fe` (307 pin); bảng 92 task: Done 57 · Partial 31 · Blocked 4 (`docs/wf/audit/AUDIT-92.md`); release notes 11 release (`docs/wf/release-notes/`); gate development trên `0d296fe` đang chạy. Chi tiết và quyết định cần chủ sở hữu: `docs/wf/TAKEOVER-CLAUDE-2026-10-24.md` §5.
- 24/10 ~22:45 (Claude, hoàn thiện lượt 2): 13 feature Partial cuối → Done (W12a/W18/W36 theo quyết định B1–B3 của chủ sở hữu, W51 liveness, W23a ba trạng thái task, W39, W11a, W46a/b, W40, W41 finding trong drill, W37b host guard + phản chứng E6, W01); registry: T07a/T18b/T07b/T30/T38b/T14b + 9 testcase R03/R04 complete theo ma trận audit; khung phát hành chung `wfkit.release_bundle` (5 điều T54 trên quan sát thật, INPUTS = điều kiện ngoài), drill adapter bản cài (RX1/RX2), ma trận provider x1–x7, ca T55, checker báo cáo pilot; manifest đóng băng lại 361 pin tại `ceb46c6`; gate snapshot cuối chạy trên `ceb46c6` (`%TEMP%\wf-snapshot-gate-20261024-ceb46c6`). Bảng 92: Done 72 · Partial 5 · Blocked 15.
- 25/10 ~00:10 (Claude): gate snapshot `ceb46c6` 195/195 đạt (1 541 test, 0 skip); 11 bundle T54 đạt T54.1–T54.5 (INPUTS ngoài); W45 chạy thật 4/6; gói bàn giao `D:\OneCrewRuns\wf-handover-ceb46c6` kiểm từ artifact pass. Bảng 92: Done 73 · Partial 5 · Blocked 14.
- 25/10 (Claude, lượt 3+4 sau review Codex `a2476ab`): 4 P1 + 2 P2 sửa (TAKEOVER §9.1); bundle `c95f603` lộ R05–R08 fail T54.1 vì token task "W17:" → sửa 25 chuỗi kịch bản, luật khung, gate test áp cùng cách đọc validator (U1-20261025-SCN-TASKS theo ủy quyền), công cụ kiểm tiếp tục root cũ TỪ GÓI (`legacy_continuation.py` + test judge trong gate + test thật với WF_PACKAGE); manifest 395 pin, re-freeze `6366137`. Gate snapshot `6366137` **213/213 đạt** (1 716 lượt test, 1 351 test id, 0 skip; refused chỉ vì acceptance 49 partial + 10 blocked); 11 bundle T54.1–T54.4 đạt, T54.5 10/11 (RP "comparison missing" = W45 cần kiểm lại cho artifact mới, không chạy provider trả phí), INPUTS ngoài; gói `D:\OneCrewRuns\wf-handover-6366137` kiểm từ artifact: verify 26/26 pass, legacy continuation 14/14 pass (lần đầu refused do needle judge sai → sửa), test thật OK. Bảng 92: Done 73 · Partial 5 · Blocked 14 (không đổi). Chưa: Codex review lượt 4, nghiệm thu, giao.
- 25/10 (Claude, W45 lại theo cho phép của chủ sở hữu): ma trận W45 trên wheel `6366137` (`D:\OneCrewRuns\wf-w45-matrix-6366137`) 4/6 usable (codex thiếu CLI); bundle RP T54.1–T54.5 đạt; gói `wf-handover-6366137` dựng lại với ma trận mới và kiểm lại từ artifact.
- 25/10 (Claude, lượt 5 sau Codex xác nhận 3 P1 + 2 P2): P1-1 oracle package_check/legacy judge; P1-2 reply+hiệu lực một transaction mọi entry; P2-1 ngữ nghĩa thời gian + time-to-deadline + cảnh báo 70% trong quyền; P2-2 gói giao thư mục verify/ ghim hash; P1-3 đối chiếu lại đủ 92 task: 21 lỗi hành vi (20 sửa có phản chứng fail-trước, W11b chờ chủ sở hữu), 11 task bổ sung bằng chứng [E], công cụ pilot local (W38b/d), bootstrap bản giao đầu tiên INPUTS(bootstrap) + baseline d3120c6 ghim + cổng CG-Rnn (refused khi acceptance partial). Registry +26 check, 14 testcase partial→complete (54/34/10), manifest 447 pin, U1-20261025-R5-* theo ủy quyền. Bảng 92 (một nguồn, năm mức riêng): Done 60 · Partial 29 · Blocked 3 — bảng cũ 73/5/14 là khai quá; đối chiếu lại trước sửa 30/61/1. Commit snapshot `c18c46e` (2.2.0.dev4); gate đang chạy `%TEMP%\wf-snapshot-gate-20261025-c18c46e`. Chưa: Codex review lượt 5, nghiệm thu, giao.
