# Round 10 — khép 2.2 theo review Codex 26/10 (lượt 10)

Ủy quyền: chủ sở hữu, chat Claude Code 26/10/2026 ~13:30, dán nguyên văn chỉ thị lượt 10 của Codex ("Tôi ủy quyền một lần cho công việc này. Tự chia task, sửa code/test/cấu hình, chạy kiểm chứng và xử lý lỗi trong phạm vi đã giao; không hỏi tôi duyệt từng việc"). Quyết định kỹ thuật theo ủy quyền; không phải chữ ký trực tiếp cho từng dòng.
Tài liệu đã đọc: ROADMAP-CLAUDE-HANDOFF.vi.md (26/10 09:53), ROADMAP-DESIGN-20261026.vi.md (26/10 09:54) §2.6/§4/§5/§7, ROADMAP.vi.md §0. Việc này = 2.2 / L0; không kéo core-tools 2.4.
Mốc đầu vào: hotfix R9 aa466ce, snapshot dev9 da96db8 (gate đang chạy), docs 71c5b1f.

## Tách việc (ownership file)
| Agent | Model | Phạm vi | File |
|---|---|---|---|
| A | Opus | D6 finding/repair qua revise; D7 context tích hợp chỉ output producer + đo prompt cuối; D8 trần revise theo phần còn phải chạy; D9 giữ guard, tìm cơ chế gia hạn hợp lệ | onecrew/v2/{repair_tasks,findings,finding_scope,internal_plan,engine,recovery_policy}.py, common_executor.prepare, tests/test_wf_r10_d6/d7/d8 |
| B | Sonnet | Kiểm output khai báo + tham chiếu file:dòng trong output văn bản của node (grammar chặt, unresolvable/unverifiable = fail), phản chứng qua CandidateChecker thật, file thừa ngoài cây niêm phong, tool kiểm lại 55 cụm trên bản sao sổ | common_verification.py, v2/verifiers/output_refs.py, tests/test_wf_r10_output_refs, tests/test_wf_r10_tree_extra_file, docs/wf/audit/tools/reverify_nodes.py |
| C | Sonnet | cp1252 console, lệnh PowerShell chạy thật, README/provider matrix khớp wheel, AUDIT-92 nhất quán | entry console, README, BAO-CAO-SANG, docs/wf/audit/* |
| Đầu mối | Fable | Sổ thử riêng (bản sao nhất quán), slice 7 file lớn, tích hợp + U1, snapshot dev10, gate, bundles, gói, legacy/rollback, kiểm lại 55 cụm + KZ + M2 trên wheel cuối, bảng 92, bàn giao | — |

## Sổ thử riêng
`D:\OneCrewRuns\sdk-trial\state-sdk-trial` = bản sao của state-v2-real lúc 13:35 (sqlite backup API + copytree plans/snapshots/attempts/worker-io; ORIGIN.txt). Sổ thật không ghi thêm từ 12:05. Project thử: các clone sẵn có `D:\OneCrewRuns\sdk-trial\vn-sign-{sdk,sample}` (cùng project_path trong receipt, không tráo path). Venv: `venv dev9` (sẽ thay bằng venv dev10 từ gói cuối).

## Coverage 7 file lớn
Worker không có công cụ đọc theo phần (2.4). Trong 2.2: đầu mối tạo slice đúng dòng của nguồn (không sửa) tại `docs/onecrew-review/slices/<file>.L<a>-L<b><ext>` + INDEX.md; node mới đọc slice, tham chiếu phải ghi ĐƯỜNG DẪN GỐC + số dòng gốc (đã nêu offset trong goal) để máy kiểm tham chiếu giải được trên cây ứng viên.

## Kết quả
(điền theo bằng chứng thật)

## Phát hiện trong lúc chạy
- `tests.test_g1_core.test_the_model_id_is_written_in_one_module_only` (đăng ký, release R0x) đỏ từ commit 3284941 vì TAKEOVER §13.4 ghi literal model id → gate da96db8 sẽ đỏ check này (ghi đúng, không sửa gate đang chạy). Sửa tài liệu cho dev10 (thay literal bằng mô tả). Agent C cũng báo 3 test closure đỏ vì module mới `output_refs.py` của agent B chưa vào `py-modules` → sẽ nối khi tích hợp.

## Gate da96db8 (dev9, 10:16–14:18, song song bài thử + Defender chưa loại trừ)
`%TEMP%\wf-snapshot-gate-20261026-da96db8`, log `D:\OneCrewRuns\wf-dev-logs\snapshot-gate-da96db8.txt`, wheel sha256 `1580e948…18c4e1a`: **refused** — 269 check có biên nhận, 268 đạt, 1 đỏ `PL/check.wheel_closure` ("not a real passing test execution"), 1 document-selfcheck; 2.152 lượt test, 2.151 pass, 0 skip; acceptance partial 14 / blocked 10 như dev8. Bằng chứng của da96db8, không chứng nhận sửa mới (R10). Không có gói dev9 (gate refused).

## Tự kiểm tài liệu T38a (chạy lại 14:25, read-only): PROBLEMS: 4 — toàn bộ trong tài liệu do Codex quản lý (ngoài checkout)
- K-LINK: `00-THIET-KE-WORKFLOW-CHUNG.vi.md:469` anchor không có `../ROADMAP.vi.md#2-hiện-trạng-và-giới-hạn-xác-minh` (ROADMAP 26/10 đổi tiêu đề §2).
- K-OWNER ×3: ROADMAP.vi.md:46, :345 (và 1 dòng nữa) ghi thao tác của chủ sở hữu không gắn U1–U4/duyệt/nghiệm thu.
→ Gate dev10 sẽ vẫn bị refused ở document-selfcheck cho tới khi Codex sửa ROADMAP/00; đầu mối không tự sửa tài liệu Codex quản lý (E ngoài). Log: `D:\OneCrewRuns\wf-dev-logs\doccheck-r10.txt`.
