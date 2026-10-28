# OneCrew 2.3 — báo cáo bàn giao (A1 + A2 + B) để Codex review tổng thể

Người viết: Claude (Opus 5.5), đầu mối triển khai 2.3, 28/10/2026. Đây là **tự kiểm của tác giả cộng review độc lập bằng agent**, chưa phải Codex review, chưa nghiệm thu. Roadmap chung không bị sửa; 2.3 không cộng vào 92 task beta; không push/tag/publish.

**Đã có bản sau:** gói `2.3.0.dev2` này là mốc Codex review ngày 28/10 (3 finding P2); bản sửa và gói `2.3.0.dev3`: [BAO-CAO-2.3-DEV3-2026-10-29](BAO-CAO-2.3-DEV3-2026-10-29.vi.md). Nội dung dưới đây giữ nguyên như lúc giao dev2.

**Bản nào:** bản trong `docs/` của gói là bản lúc dựng gói. Kết quả kiểm gói từ artifact và gate (§4.4, §4.5) chỉ có ở bản trong checkout, commit sau khi kiểm: gói không tự chứng nhận chính nó.

| | |
|---|---|
| Code | `bba3da6` (nhánh local `claude/onecrew-2.3`, worktree `D:\TamNT\Workspace\11.OneCrew\wf-v23`); gốc `95bb7a6` (= code beta `34eb7c4`) |
| Version | `2.3.0.dev2` |
| Gói thử | `D:\OneCrewRuns\v23\pkg\onecrew-2.3.0.dev2-final` (wheel và hash: `README.md`, `manifest.json` của gói) |
| Test 2.3 | 154/154 đạt, 0 skip, trên `bba3da6` (`D:\OneCrewRuns\v23\logs\final-bba3da6-v23.txt`) |
| Số đo | KS-01, KE-01, KE-02 trên `4182ee5` (code giống `bba3da6`): `docs/v23/evidence/*-4182ee5.json` |

## 1. Người dùng làm được gì, thử thế nào

- **A1 — wiki có nguồn tới worker.** Viết trang Markdown trong `docs/wiki/` (mỗi heading một mục; khối `onecrew` cho kiểu, nhãn, nguồn ghim revision, điều kiện, `must`). Khi engine chạy node native, worker nhận gói tri thức theo quyền đọc của node, khả năng áp dụng (so blob trên view của node), mức liên quan và trần ký tự. Ràng buộc bắt buộc không bị cắt âm thầm: vượt trần thì node dừng trước khi gọi model. Receipt niêm phong đúng phần chữ trong prompt và khai báo sử dụng của worker. `onecrew wiki pages|show|read` để xem và đọc tiếp theo con trỏ.
- **A2 — học có bằng chứng, dùng lại qua root mới.** Worker khai `knowledge.new`: claim là quan sát của root, được công bố cho project ngay khi check của node chứng minh đạt (không chờ root kết thúc, không chờ phản hồi). Root mới, process mới của cùng project tự nhận theo quyền. `onecrew wiki record|withdraw|archive|summarize|export|history`: tóm tắt không mạnh hơn nguồn; cập nhật đồng thời không mất bản nào (bản cũ thành `contested`); thu hồi/lưu trữ có hiệu lực ở lần đọc tiếp, kể cả qua tóm tắt, bản sao wiki, gói tiếp tục; ledger và receipt không bị xóa.
- **B — dọn xong mới tiếp quản.** Controller `engine step`/`batch` chết hoặc treo: `onecrew executor recover <attempt>` (hoặc lần `engine step` kế tiếp) dừng đúng cây process của attempt đó, xác nhận đã dừng rồi mới giải phóng. Crash không có lệnh dừng → chạy lại đúng 1 lần trong ngân sách cũ; dừng/quá cap/quá deadline → node bị giữ, tiếp quản bằng revise. Output muộn của chủ cũ không bao giờ được publish; bản sao state root không bao giờ giết việc của root gốc.

**Thử từ gói** (PowerShell, theo `README.md` của gói): §1 kiểm hash và chạy bộ kiểm 9 bước; §2 cài vào venv thử, chạy task đầu tiên `examples/first-task/` hoặc `verify/scenario_a1.py`, `scenario_a2.py`, `scenario_b.py`; §3 quay về 2.2 rồi lên lại. Hướng dẫn: `docs/HUONG-DAN-WIKI.vi.md` (A1 §1–5, A2 §6, giới hạn §7), `docs/B-NOTES.vi.md`.

## 2. Trạng thái từng yêu cầu

Truy vết requirement → tái dùng → task → testcase → bằng chứng: [HOP-DONG-2.3.vi.md](HOP-DONG-2.3.vi.md) §4. Chi tiết: [BAO-CAO-A1](BAO-CAO-A1-2026-10-28.vi.md) §2 (gói A1, lịch sử), [BAO-CAO-A2](BAO-CAO-A2-2026-10-28.vi.md) §2, [B-NOTES](B-NOTES.vi.md) §2.

| Req | Trạng thái | Bằng chứng chính |
|---|---|---|
| A1-R1 nguồn, revision, hash | Đạt | KA-01/02; gói V4 |
| A1-R2 quyền consumer, không lộ root/project | Đạt | KA-03…05, T51b; review r1–r3; gói V5a |
| A1-R3 liên quan + trần, không bỏ ràng buộc âm thầm | Đạt | KA-06…08; gói V5c (dừng trước model) |
| A1-R4 lịch sử ≠ áp dụng hiện tại | Đạt (so blob + điều kiện kiểu, không phân tích ngữ nghĩa) | KA-09…12; gói V5b |
| A1-R5 đọc tiếp | Đạt | KA-13…15 |
| A1-R6 giao qua adapter + bằng chứng giao | Đạt cho worker native của engine (Claude Code CLI) | KA-16/17, `test_v23_a1_installed`; gói V4 |
| A1-R7 đọc ≠ dùng đúng | Đạt (kiểm cấu trúc, `proves_semantics: false`) | KA-18/19; KE-01 |
| A1-R8 đối chứng không wiki / đúng / sai-cũ | Đạt có giới hạn (1 task nhỏ, vài lượt) | KE-01 `evidence/ke01-4182ee5.json` |
| A1-R9 đo chi phí khi kho tăng | Đạt (đã đo; chưa tối ưu, chưa có chỉ mục) | KS-01 `evidence/ks01-scale-4182ee5.json` |
| A1-R10 gói chạy không cần checkout/wiki máy tác giả | Đạt | `test_v23_a1_installed`, `test_g1_core`; gói V2, V3, V6 |
| A1-R11 A1 không ghi wiki | Đạt | KA-20; gói V4 |
| A2-R1 ghi khi có bằng chứng, không đợi root kết thúc | Đạt | KB-01/02/02b; gói V8 |
| A2-R2 project/general, phạm vi, nguồn, trạng thái, điều kiện | Đạt | KB-03 |
| A2-R3 tóm tắt không nâng độ chắc chắn | Đạt | KB-04/05/06 |
| A2-R4 revision/provenance, đồng thời | Đạt | KB-07 (hai process OS), review r3 R3-3, test CLI `state_version` |
| A2-R5 thu hồi qua wiki/tóm tắt, không sống lại | Đạt | KB-08/09/10, NoResurrection |
| A2-R6 vòng đời, không xóa ledger/receipt | Đạt | KB-11 |
| A2-R7 ca bắt buộc: root A kết thúc → root B mới, process mới | Đạt | KB-12 + KB-13 trên wheel cài; gói V8 |
| A2-R8 không lộ ngoài quyền | Đạt | KB-14; review r2 N5/N19, r3 R3-1/R3-2 |
| A2-R9 đối chứng mở rộng | Đạt có giới hạn | KE-02 `evidence/ke02-4182ee5.json` |
| A2-R10 guard root đã kết thúc | Đạt | KB-15 |
| B-R1…R7 dọn/tiếp quản an toàn (thiết kế §7 ca 1–7, 14, 15) | Đạt cho ManagedExecutor và cây process của `engine step`, chỉ Windows | 29 test B (process thật, Job thật), `test_v23_b_installed`; gói V9; review B 4 vòng |
| PK-R1 gói, kiểm từ wheel thật | Đạt | gói 9/9 từ artifact, diễn tập README 9/9 (§4.4) |

## 3. Tái dùng v1/2.2 và code mới

- **Không có kho/ledger/router/engine thứ hai.** Mọi bản ghi tri thức là `context.entry` (lớp A) trong ledger có sẵn; không thêm kind sự kiện, không đổi schema; B dùng `attempt.unknown`, `node.held`, `node.resumed` sẵn có.
- **Dùng trực tiếp:** `context.add/retrieve` (thêm `extra`, `expect_latest`, `lifecycle_target`), `lessons._still_open`/`refine_context`, `Snapshots` (blob gói), `NativeExecutor`/`ClaudeArtifact`/`Supervisor`, giao dịch `BEGIN IMMEDIATE`, engine verify/receipt, `recovery_core.decide('interrupted')`, `Control` (attempt, unknown, fence generation), `budget_core.group`, Job object của `process_core`, `compat scan`, `tests/wf_wheel`.
- **Dùng lại ngữ nghĩa, không đóng gói module v1** (chúng làm việc trên record tool/harness hoặc kéo import ngoài wheel): `paging`, `owned._fit_work`, `entry` (revision/provenance), `evaluation.replay/compare`, `conversations.summarize`, `incidents.finalize`.
- **Code mới** (`git diff 95bb7a6 bba3da6`): 16 file trong `onecrew/` + `pyproject.toml`, +2 538/−68 dòng; phần lớn ở `onecrew/v2/knowledge.py` (mới, 1 233), `onecrew/v2/wiki.py` (mới, 274), `process_core.py` (+373, B), `engine.py` (+232), `context.py` (+141), `managed_executor.py` (+119), `common_executor.py` (+71); nhóm CLI `wiki`. Test: 18 file, +3 127 dòng. Không thêm module ngoài hai module trên vào wheel.

## 4. Kết quả kiểm

### 4.1 Test

| Lượt | Kết quả | Nguồn |
|---|---|---|
| Mọi module `tests/test_v23_*` + `test_g1_core`, `test_wf_r7_t51b`, `test_wf_r03a_executors` trên `bba3da6` | 154/154, 0 skip, 11,5 phút | `D:\OneCrewRuns\v23\logs\final-bba3da6-v23.txt` |
| Danh sách bắt buộc 14 module của khảo sát B (sau vòng sửa cuối) | 118 OK, 1 skip (venv redirector) | `D:\OneCrewRuns\v23\b-evidence\green-round3-mandatory.txt` |
| Các module v1 gọi `Supervisor.reconcile` (parallel, workflow, discussion, solution_delivery, parallel_native, t08b, t18b) | 78/78 | `b-evidence\green-round3-reconcile-callers.txt` |
| Hồi quy rộng 101 module có import code B (trên `72b1b22`) | 890 test; 3 lỗi `test_provider_fallback` đã sửa (54/54 chạy lại), 1 lỗi phụ thuộc môi trường (`test_workspace_worker` giả định TEMP ổ C:, 12/12 khi TEMP ở C:) | `b-evidence\broad-regression-101-modules.txt` |
| Hồi quy rộng 492 test sau A1/A2 review r1 (cây đổi trong lúc chạy) | 2 lỗi T51b → chạy lại trên cây hiện tại 4/4; 1 tên module sai trong danh sách của tôi | `D:\OneCrewRuns\v23\logs\regress-r1.txt` |
| Gate snapshot 2.2 (286 check) trên commit của gói | xem bản trong checkout (§4.5) | — |

### 4.2 Số đo KS-01 — chi phí chọn gói khi kho tăng

`evidence/ks01-scale-4182ee5.json` (commit sạch `4182ee5`; 20% mục trích file; 3 lần đo, min–max; máy dùng chung, có phiên khác chạy song song):

| Mục project | Mục project khác | Mục wiki | Ứng viên | Chọn gói (s) | `context.retrieve` 200 mục mới / bản 2.2 (s) |
|---|---|---|---|---|---|
| 100 | 0 | 0 | 100 | 0,06–0,10 | 0,05 / 0,06 |
| 1 000 | 1 000 | 200 | 1 200 | 0,33–0,38 | 0,08 / 0,09 |
| 5 000 | 5 000 | 1 000 | 6 000 | 0,78–0,90 | 0,15 / 0,22 |
| 20 000 | 20 000 | 2 000 | 22 000 | 2,5–2,7 | 0,54 / 0,67 |

Chi phí tăng gần tuyến tính theo số mục; lượt đo của gói A1 (`41ad32e`, máy tải nặng hơn) cho 22 000 mục 2,8–12,2 s. Bộ lọc SQL mới không chậm hơn 2.2 khi đọc 200 mục. Chưa có chỉ mục riêng; không tuyên bố giảm token hay latency.

### 4.3 Đối chứng KE-01 và KE-02 (claude giả + Claude Code CLI thật, `claude-haiku-5-5`)

**KE-01 — cùng task, bốn điều kiện wiki** (`evidence/ke01-4182ee5.json`):

| Điều kiện | Claude giả ×2 (policy cố định) | Claude thật ×2 |
|---|---|---|
| không wiki | 2 sai (giá trị mặc định), cần làm lại | 1 trả kết quả dở dang, 1 bị giữ (danh sách file không hợp lệ) |
| wiki đúng | 2 đạt ngay | 2 đạt ngay |
| wiki cũ (nguồn đã đổi → giao là `lead`/`recheck`) | 2 không bị dẫn sai, 2 sai | **2 bị dẫn sai** (dùng mục cũ dù nhãn `lead`), check bắt |
| wiki sai (nguồn không đổi) | 2 bị dẫn sai, check bắt | 2 bị dẫn sai, check bắt |

Ký tự prompt: không wiki 715; có wiki 2 863–2 927 (gói tri thức 2 135–2 169).

**KE-02 — tri thức root A tự ghi, root B mới dùng lại** (`evidence/ke02-4182ee5.json`; chi tiết [BAO-CAO-A2](BAO-CAO-A2-2026-10-28.vi.md) §3): Claude thật ×2 — reused 2/2 đạt ngay bằng mục của A; changed (nguồn đổi) 2/2 đạt, tự đọc lại nguồn; withdrawn: mục không tới B; fresh: 0/2 đạt. Claude giả ở ca changed bị test double tự lừa (giới hạn của test double, giải thích ở BAO-CAO-A2 §3).

**Đọc số này thế nào:** wiki đúng giúp ngay; wiki sai luôn dẫn sai và chỉ check của node bắt được; nhãn `lead` không bảo đảm model kiểm lại nguồn (KE-01 wiki cũ: lượt này 2/2 bị dẫn sai, lượt gói A1 0/2, lượt chưa commit 1/2), trong khi ở KE-02 changed model kiểm lại 2/2. Một task nhỏ, vài lượt: không có ý nghĩa thống kê. Lượt gọi provider thật trong toàn bộ 2.3: 40 lượt `claude-haiku-5-5` qua Claude Code CLI 2.1.286 đã đăng nhập subscription của máy (16 cho gói A1, 8 cho KE-02 lần đầu, 16 cho lượt đo cuối); adapter bỏ API key, không bật API trả phí, không đổi pin của việc nào.

### 4.4 Gói thử, kiểm từ artifact

Gói `D:\OneCrewRuns\v23\pkg\onecrew-2.3.0.dev2-final`: dựng từ commit sạch `38981bd` (code giống `bba3da6`) bằng `docs/v23/tools/build_milestone.py --milestone FINAL`; 27 file (26 dòng `SHA256SUMS` + chính nó). Wheel `onecrew-2.3.0.dev2-py3-none-any.whl` SHA256 `68ee776e4262611f2369013b5d1a6ff075503f86ccdb83a41ad5b00f16b846f4`; wheel quay về `wheel/previous/onecrew-2.2.0.dev18-py3-none-any.whl` SHA256 `0346577e…ef9bd2`, giống từng byte gói beta. `manifest.json` → `claims` đều `false` (chưa giao, chưa Codex review, chưa nghiệm thu, chưa phát hành).

**Bộ kiểm từ artifact: 9/9 đạt** (28/10 20:03–20:04; `python -I` của Python 3.13.15, cwd và thư mục làm việc ngoài checkout, đường dẫn có dấu cách, `LOCALAPPDATA` riêng; báo cáo `D:\OneCrewRuns\v23 thu final\verify\verify-report.json`, log `D:\OneCrewRuns\v23\logs\verify-final-38981bd.txt`):

| Bước | Kết quả |
|---|---|
| V1 danh tính | 26 file khớp `SHA256SUMS`, không thiếu/thừa; manifest đúng wheel và hash |
| V2 cài | venv mới (đường dẫn có dấu cách), `pip install --no-index` → `2.3.0.dev2` |
| V3 nguồn module | `onecrew.v2.knowledge`, `wiki`, executor nạp từ venv, không từ checkout; `--help` có `wiki` |
| V4 task đầu tiên | `examples/first-task`: engine thật → ClaudeArtifact → Supervisor → process `claude` giả; ràng buộc `a-value` giao là `fact`/`applies`, check thật đạt, receipt niêm phong gói, trang wiki không đổi |
| V5 phản chứng | nguồn ngoài quyền đọc → không giao, không nêu tên; nguồn đổi → giao `lead`/`recheck`; ràng buộc bắt buộc 22 025 ký tự vượt chỗ trống 14 072 → dừng trước model (`native_preflight`, claude giả 0 lượt) |
| V6 console cp1252 | `--help` exit 0; `wiki pages` in đúng tiêu đề tiếng Việt |
| V7 quay về 2.2 | wheel 2.2.0.dev18 cài đè: `plan show`, `engine state` exit 0 trên sổ của V4; `compat scan` không có khối read, khối continue `B1` giống sổ đối chứng do chính 2.2 ghi; lên lại 2.3: `wiki show` chạy |
| V8 hai root | root A (process 50248) công bố mục `verified`/`project` khi còn `approved`, rồi được nghiệm thu bởi owner fixture; root B mới (process 51740) nhận đúng mục đó là `fact`, khai dùng, check đạt; root hẹp không đọc được nguồn → không nhận (`source_outside_read_scope`), sai; ghi vào root A đã kết thúc bị từ chối; ngân sách A không đổi (2 lượt) |
| V9 tiếp quản | controller `engine step` cài đặt chết thật (exit 41) khi worker + cháu đang chạy; `onecrew executor recover` cài đặt: `cleanup: confirmed`, không candidate, không replay; attempt settle `supervisor_interrupted`; bước sau giữ node rồi chạy lại 1 lần (generation 1), `budget_reset: false`, tổng 2 lần launch, 2 lượt tính phí |

**Diễn tập README** (các khối PowerShell của `README.md` gần nguyên văn, chỉ đổi tên thư mục; cwd `D:\TamNT\Workspace\9.VMAgent\onecrew` — checkout có sẵn thư mục `onecrew/` và `onecrew.egg-info`; `LOCALAPPDATA`/`APPDATA` riêng; log `D:\OneCrewRuns\v23 drill final\drill.txt`): R1 hash khớp manifest; R2 bộ kiểm 9/9; R3 venv đường dẫn có dấu cách, cài wheel, `--help` không cần `PYTHONUTF8` có `wiki`; R4 quay về `2.2.0.dev18`; R5 lên lại `2.3.0.dev2` — 9/9 bước exit 0.

### 4.5 Gate snapshot 2.2

Xem bản trong checkout.

## 5. Cách ly

- **Riêng cho 2.3:** worktree `wf-v23` (nhánh `claude/onecrew-2.3`), `wf-v23-a1`, `wf-v23-b`; mọi thư mục tạm, log, gói, sổ thử ở `D:\OneCrewRuns\v23\` và thư mục thử của gói; venv tạo mới trong thư mục kiểm; test chạy với `TEMP`, `LOCALAPPDATA`, `APPDATA` riêng (`D:\OneCrewRuns\v23\isolated\…`) và bỏ `CLAUDECODE`, `CLAUDE_CODE_CHILD_SESSION`, `ONECREW_ACTOR`, `PYTHONUTF8`, `PYTHONIOENCODING` chỉ cho process thử; không đổi biến môi trường toàn máy, hook, registry, PATH, cấu hình provider.
- **Beta 2.2 giữ nguyên (đã kiểm):** gói `D:\OneCrewRuns\wf-handover-34eb7c4-hs2` 687/687 dòng `SHA256SUMS` khớp, wheel `onecrew-2.2.0.dev18` SHA256 `0346577e…ef9bd2`, không file nào có giờ sửa sau 13:30 ngày 28/10 (trước khi bắt đầu 2.3); checkout `wf-codex` sạch ở `95bb7a6`.
- **Sổ thật:** không công cụ/test nào của 2.3 trỏ tới `state-v2-real` (tìm trong mọi script); `%LOCALAPPDATA%\OneCrew\hook-projects.json` thật chỉ có mục của việc khác (`signsdk`, `signsdk-hayhv` lúc 16:29 của một phiên beta khác, `cts-port`, `vimes.ehr`), không có project thử nào của 2.3.
- **Process:** không dừng/kill process nào ngoài cây do chính test/probe tạo; reviewer xác nhận không để lại process.
- **Giới hạn:** máy dùng chung, phiên khác chạy song song suốt thời gian làm; số đo thời gian có nhiễu. Không hứa "không ảnh hưởng hiệu năng".

## 6. Review độc lập (agent Opus 5.5, chỉ đọc, chạy trên bản `git archive`)

| Vòng | Phạm vi | Kết quả |
|---|---|---|
| A1/A2 r1 | `e7a2aa9` | 33 phát hiện (9 P1, 13 P2, 11 P3), 21/23 probe tái hiện → sửa ở `a9b1d1d` |
| A1/A2 r2 | `a9b1d1d` | 29/33 đóng; 3 P1 + 4 P2 mới → `8709bfa` |
| A1/A2 r3 | `8709bfa` | r2 đóng; 1 P1 + 2 P2 mới → `1db1507` |
| A1/A2 r4 | `1db1507` | **0 P1/P2**; 1 P3 tài liệu → `9307ade` |
| B r1 | `a34eb12` | 1 P1 (bản sao state root giết việc của root gốc), 2 P2, 7 P3 → `d55e4a7` |
| B r2 | `c690f3a` | F1–F6, F10 đóng; 1 P2 mới (phiên Windows đã kết thúc → attempt kẹt) + 3 P3 → `f38d118` |
| B r3 | `ee7d012` | **0 P1/P2**; 3 P3 → `3c393d0` |
| B r4 | `bba3da6` | đóng hết; 2 ghi chú P3 tuỳ chọn (đã là giới hạn ở B-NOTES §5) |

Báo cáo review: `D:\OneCrewRuns\v23\review-a1a2*.md`, `review-b*.md`. Mỗi phát hiện được sửa kèm test tái hiện (đỏ trên commit trước, xanh sau); test từ probe của reviewer nằm trong `tests/test_v23_review_r*.py` và `tests/test_v23_b_*.py`. Gói A1 (`2.3.0.dev1`) được giao trước review r1 và có lỗi review tìm ra: không dùng tiếp (BAO-CAO-A1 §9).

## 7. Blocker thật và quyết định cần chủ sở hữu

- **Không có blocker** trong phạm vi đã ủy quyền: A1, A2, B đều làm xong và tự kiểm.
- **Không thuộc quyền đã cấp, để chủ sở hữu/Codex:** Codex review tổng thể trên gói này; nghiệm thu; push/tag/publish; dùng 2.3 trên sổ thật hay migrate sổ thật.
- **Không có quyết định nào đang chặn.**

## 8. Dùng lần đầu và quay về an toàn

1. Kiểm hash wheel và chạy bộ kiểm của gói (`README.md` §1). Bộ kiểm chỉ ghi vào thư mục làm việc bạn đưa.
2. Tạo venv thử mới, cài wheel bằng `pip install --no-index` (`README.md` §2). Không cài vào venv đang dùng cho beta.
3. Dùng trên **bản sao** project với **state root riêng**; không dùng `state-v2-real` hay sổ của task đang chạy. `onecrew init` ghi `%LOCALAPPDATA%\OneCrew\hook-projects.json` của người chạy, nên với project đã init bằng 2.2 chỉ cần cài wheel vào venv thử.
4. Task đầu tiên: `examples/first-task/` (trang wiki mẫu + hợp đồng + node), xem gói bằng `onecrew wiki show`, chạy `engine step`.
5. **Quay về 2.2:** để mọi attempt kết thúc; `pip install --force-reinstall` wheel 2.2 trong `wheel/previous/` (giống từng byte gói beta) vào cùng venv thử; `compat scan` trên bản sao sổ trước khi dùng sổ đó với 2.2. 2.2 không biết vòng đời tri thức (mục đã thu hồi hiện như ghi chú bình thường), không khôi phục được attempt đang dở có khóa `knowledge`, và vẫn coi attempt mà 2.3-B đã giải phóng là `unresolved`. Bộ kiểm V7 đã diễn tập quay về rồi lên lại; ngoài phạm vi đó, không mặc định sổ 2.3 đọc được bởi 2.2.

## 9. Giới hạn

- Adapter có bằng chứng giao tri thức: chỉ worker native của engine (Claude Code CLI đúng bản ghim 2.1.286, subscription, không fallback trả phí). Codex/Kiro giữ giới hạn 2.2; phiên Claude Code tương tác chỉ đọc bằng `onecrew wiki show|read`.
- Áp dụng = so blob trên view của worker + điều kiện kiểu; điều kiện chữ tự do luôn `unknown`; không phân tích ngữ nghĩa. Nhãn `lead` không bảo đảm model kiểm lại nguồn (KE-01). `wiki show` không có node xét trên cây làm việc.
- Công bố claim: OneCrew kiểm id check, quyền nguồn/file và check đạt, không kiểm check có thật sự đo đúng điều claim nói (`cause: not_established`).
- Chi phí chọn gói tăng tuyến tính (§4.2); chưa có chỉ mục.
- Root đang chạy không nhận cập nhật giữa chừng; `context retrieve` (bộ đọc thô 2.2) vẫn trả mọi `context.entry` theo luật cũ.
- B: chỉ Windows; không có watchdog nền; stop/cap/deadline → giữ node (tiếp quản bằng revise); replay tự động chỉ khi crash không trigger và được quét trong cửa sổ cap; độc quyền theo state root (bản sao/root đã di chuyển chỉ quan sát); tên 8.3 bị từ chối theo hình dạng; Job dùng DACL mặc định của user; crash sau khi worker xong có thể chạy lại 1 provider call; token của các bản dựng trung gian (chưa từng giao) kẹt ở pending. Đầy đủ: `B-NOTES.vi.md` §5.
- Bộ kiểm dùng `claude` giả: chứng minh đường đi, nhãn, receipt; không chứng minh model dùng đúng tri thức.
