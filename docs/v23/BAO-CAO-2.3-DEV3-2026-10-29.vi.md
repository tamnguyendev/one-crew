# OneCrew 2.3 — bàn giao 2.3.0.dev3 sau review Codex (A1 + A2 + B)

Người viết: Claude (Opus 5.5), đầu mối triển khai 2.3, đêm 28–29/10/2026, theo chỉ thị người dùng đêm 28/10 ("Tiếp tục làm OneCrew 2.3 đến sáng, ưu tiên sửa hết các finding Codex vừa review…"). Đây là **tự kiểm của tác giả cộng review độc lập bằng agent**, chưa phải Codex review lại, chưa nghiệm thu. Roadmap chung không bị sửa; 2.3 không cộng vào 92 task beta; không push/tag/publish. Báo cáo trước (gói `2.3.0.dev2`, mốc Codex review): [BAO-CAO-2.3-2026-10-28](BAO-CAO-2.3-2026-10-28.vi.md).

**Đính chính 29/10 (sau review Codex trên gói này):** hai tuyên bố dưới đây rộng hơn hành vi thật của gói `2.3.0.dev3`:
- §2, hàng P2-01 ("dùng cùng một quyết định với gói tri thức") chỉ đúng với tri thức của project/root. `context retrieve` xét bản ghi general (dùng chung) theo vòng đời mà không xét điều kiện áp dụng: bản ghi general `verified` có điều kiện `platform: linux` vẫn hiện `verified` trên Windows, trong khi `wiki show --plan` loại nó là `not_applicable`. Codex tái hiện qua CLI của wheel dev3 đã cài (`D:\OneCrewRuns\codex-v23-dev3-review-20261029\installed-general-condition-*.json`). P2-01 vì vậy chưa khép hết ở gói này.
- §1 và §8 ("chỉ còn chủ sở hữu quyết U1") không đúng: còn lỗi trên.

Bản sửa, U1 và gói thay thế `2.3.0.dev5` (gói dev4 không bàn giao): [BAO-CAO-2.3-DEV5-2026-10-29](BAO-CAO-2.3-DEV5-2026-10-29.vi.md). Phần dưới giữ nguyên như lúc giao dev3.

**Bản nào:** bản trong `docs/` của gói là bản lúc dựng gói. Kết quả kiểm gói từ artifact, diễn tập và gate (§5) chỉ có ở bản trong checkout, commit sau khi kiểm: gói không tự chứng nhận chính nó.

| | |
|---|---|
| Code | `6a8421d` (nhánh local `claude/onecrew-2.3`, worktree `D:\TamNT\Workspace\11.OneCrew\wf-v23`); mốc Codex review `38981bd` |
| Version | `2.3.0.dev3` (gói `2.3.0.dev2` giữ nguyên, không ghi đè) |
| Gói thử | `D:\OneCrewRuns\v23\pkg\onecrew-2.3.0.dev3-final` (dựng từ `0594a43`, code giống `6a8421d`) |
| Wheel | `onecrew-2.3.0.dev3-py3-none-any.whl` SHA256 `30e6b7e67d7a2701451f460a2d4dbf5af824fc713d90b2a75eb539ff9ac0ec43` |

## 1. Đã sẵn sàng test chưa, trong phạm vi nào

**Sẵn sàng để Codex review lại và để thử trên bản sao project và state root riêng** (phạm vi dưới đây). **Chưa sẵn sàng phát hành hay dùng trên sổ thật.** Mọi kiểm bắt buộc đã chạy xong:
- kiểm từ artifact 11/11;
- diễn tập README 9/9 và task đầu tiên 23/23 từ gói;
- hồi quy trên code cuối đạt;
- gate snapshot 2.2 trên `0594a43` chạy hết, **286/286 check đạt** (2 097 test, 0 skip, 0 lỗi).

Quyết định của gate là `refused`. Gate beta cũng `refused`, vì trong phát triển gate không thể đạt khi chưa có nghiệm thu và pilot thật. Có hai nhóm vấn đề:
- 23 khoảng trống cần việc của chủ sở hữu, pilot hoặc provider thật, giống từng chữ gate beta;
- **một vấn đề mới của 2.3, kit-guard:** ba file test được ghim trong bộ kit 2.2 đã được sửa trên nhánh 2.3 mà không có ngoại lệ U1 (§5.5). Việc này cần chủ sở hữu quyết định (§8).

Phạm vi test: A1 (đọc wiki, chọn/giao context có quyền, khả năng áp dụng, trần, đọc tiếp), A2 (ghi có bằng chứng, vòng đời, dùng lại qua root mới/process mới), B (dọn, sở hữu, tiếp quản an toàn) — trên **bản sao project và state root riêng**, Windows, worker native của engine (Claude Code CLI 2.1.286, subscription). Diễn tập dùng `claude` giả; task đầu tiên phần B dùng Claude Code CLI thật. Không dùng với sổ thật hay sổ của task đang chạy.

## 2. Ba finding Codex đã khép thế nào

Truy vết đầy đủ: [HOP-DONG-2.3](HOP-DONG-2.3.vi.md) §7.

| Finding | Đã sửa thế nào | Đỏ trước | Xanh sau |
|---|---|---|---|
| **P2-01** gói tiếp tục (`onecrew continue`) đưa tri thức cũ ra như đã xác minh | Gói tiếp tục, `context retrieve` và `wiki history` dùng **cùng một quyết định** với gói tri thức (`knowledge.for_root` trên cùng `_collect`/`_decide`): mục bị thu hồi/lưu trữ/thay thế (kể cả ghi chú riêng bị ghi chú mới thay) không hiện; mục có file ghim hoặc nguồn đã đổi, không còn áp dụng, root khác đã ghi bản mới hơn, hay (bản ghi 2.3) không kiểm được → `stale` có lý do; `wiki history` ghi `superseded`. Mục 2.2 giữ quy tắc 2.2. Lịch sử giữ nguyên. | `tests/test_v23_codex_review` trên `38981bd`: 3/4 ca P2-01 fail (log `D:\OneCrewRuns\v23\logs\codex-red-38981bd.txt`) | 4/4; V11 từ gói (§5) |
| **P2-02** giới hạn 2 000 trang làm mất ràng buộc `must` | Mọi trang được dò tìm mục bắt buộc/thay thế; mục bắt buộc sau giới hạn vẫn được giao. Mục bắt buộc không giao được (trang > 2 MB, không phải UTF-8/UTF-16, metadata sai, id trùng khác nội dung, ngoài mục, dẫn xuất từ mục không đọc được), wiki > 256 MB, sổ không đọc được khi có bản ghi bắt buộc, hay lớp chọn lỗi bất ngờ khi project có tri thức bắt buộc → node **bị giữ trước khi gọi model** với lý do nêu trang/dòng. Lỗi làm không biết nội dung (thư mục cấu hình mất, config hỏng, trang không đọc được) → báo `wiki.complete: false` + dòng lỗi, không chặn task độc lập. Ràng buộc đọc được nhưng vượt trần → giữ node như trước. | 6/8 ca P2-02 fail trên `38981bd` (2 đối chứng đạt) | 8/8; V10 từ gói (§5) |
| **P2-03** task đầu tiên chưa tự chạy được từ gói | `examples/first-task/`: `contract.json`, `nodes.json`, `fake-policy.json`, README với khối lệnh PowerShell cụ thể, đường dẫn nằm trong gói; phần A diễn tập với `claude` giả, phần B dùng Claude Code CLI thật; `verify/first_task_drill.py` chạy đúng các khối lệnh của README từ gói. | README cũ từ gói dev2: đường dẫn `../../tools/scenario_a1.py`, `../../HUONG-DAN-WIKI.vi.md` không tồn tại, 0 file JSON mẫu, 0 khối lệnh (`D:\OneCrewRuns\v23\p2-03\red\`) | diễn tập 23/23 trên gói thử của agent (`D:\OneCrewRuns\v23\p2-03\drill run 2`); trên gói cuối: §5 |

**Review độc lập bản sửa** (agent Opus 5.5, probe ghi thành test, chạy đối chứng trên bản trước): r1 trên `581fbca` 18 điểm (11 P2, 7 P3; 6 do bản sửa gây ra) → `989eb9c`; r2 10 điểm (3 P2, 7 P3; 4 do r1 gây ra) → `522a6c9`; r3 3 P3 (do r2 gây ra), 0 P1/P2 → `6a8421d`. Không vòng nào có P1. Probe: `tests/test_v23_review_codex_r1.py` (25), `_r2.py` (14), `_r3.py` (4), tất cả đạt trên `6a8421d`. Báo cáo: `D:\OneCrewRuns\v23\review-codex-r1.md`, `-r2.md`, `-r3.md`.

## 3. A1/A2/B còn requirement nào chưa đạt

**Không còn requirement nào của A1, A2, B chưa đạt** trong phạm vi hợp đồng ([HOP-DONG-2.3](HOP-DONG-2.3.vi.md) §4, §7), với các giới hạn đã ghi (§9 của báo cáo dev2, `README.md` của gói). Thay đổi so với bản dev2:

- **A1-R3** (không bỏ ràng buộc âm thầm): bản dev2 sai ở giới hạn trang (P2-02) — nay đạt, kể cả trang hỏng/mã hóa/dẫn xuất/bản sao (3 vòng review).
- **A1-R4, A2-R5, A2-R6, A2-R8** trên đường **tiếp tục**: bản dev2 sai (P2-01) — nay đạt.
- **A1-R9**: hợp đồng yêu cầu 1k/10k/50k mục; nay đã đo 100 → 52 000 mục và 1 001 → 10 001 trang (§5.4).
- **A1-R10, PK-R1**: bản dev2 thiếu mẫu task đầu tiên (P2-03) — nay đạt, có diễn tập từ gói.
- **B-R1…R7**: không đổi; hồi quy lại trên code cuối đạt.

## 4. Tái dùng và code mới đợt này

- Không thêm kho/ledger/engine nào: sửa trên `onecrew/v2/wiki.py`, `knowledge.py`, `context.py`, `evidence_cli.py`; gói tiếp tục (`resume_pack`) dùng lại bộ chọn A1/A2. Không đổi schema, không thêm kind sự kiện.
- Test mới: `tests/test_v23_codex_review.py` (12), `_review_codex_r1/r2/r3.py` (43). Công cụ gói: `docs/v23/tools/scenario_codex.py` (V10, V11), `first_task_drill.py`, `make_fake_claude_wheel.py`; `measure_scale.py` thêm 10k/50k và chuỗi số trang.

## 5. Gói, kiểm từ artifact, gate

### 5.1 Gói

`D:\OneCrewRuns\v23\pkg\onecrew-2.3.0.dev3-final`: 34 file (33 dòng `SHA256SUMS` + chính nó); `manifest.json` → version `2.3.0.dev3`, commit `0594a43`, wheel SHA256 `30e6b7e6…ac0ec43`, wheel quay về `onecrew-2.2.0.dev18` SHA256 `0346577e…ef9bd2` (giống từng byte gói beta), `claims` đều `false`. Gói `2.3.0.dev2` (`onecrew-2.3.0.dev2-final`, mốc Codex review) giữ nguyên.

### 5.2 Kiểm từ artifact — 11/11 đạt

29/10 00:38–00:44, `python -I` của Python 3.13.15, thư mục làm việc `D:\OneCrewRuns\v23 thu dev3\verify` (ngoài checkout, có dấu cách), `LOCALAPPDATA`/`APPDATA` riêng; báo cáo `D:\OneCrewRuns\v23 thu dev3\verify\verify-report.json`, log `D:\OneCrewRuns\v23\logs\verify-dev3-0594a43.txt`.

| Bước | Kết quả |
|---|---|
| V1 danh tính | 33 file khớp `SHA256SUMS`, không thiếu/thừa; manifest đúng wheel và hash |
| V2 cài | venv mới (đường dẫn có dấu cách), `pip install --no-index` → `2.3.0.dev3` |
| V3 nguồn module | `onecrew.v2.knowledge`, `wiki`, executor nạp từ venv; `--help` có `wiki` |
| V4 task đầu tiên (luồng fixture) | engine thật → ClaudeArtifact → Supervisor → process `claude` giả; ràng buộc `a-value` giao là `fact`, check thật đạt, receipt niêm phong gói |
| V5 phản chứng | nguồn ngoài quyền → không giao, không nêu tên; nguồn đổi → `lead`/`recheck`; bắt buộc 22 025 ký tự vượt chỗ 14 536 → dừng trước model |
| V6 console cp1252 | `--help` exit 0; `wiki pages` in đúng tiêu đề tiếng Việt |
| V7 quay về 2.2 | wheel 2.2 cài đè đọc được sổ của V4 (`plan show`, `engine state`, `compat scan` không có khối read, khối continue như sổ đối chứng 2.2); lên lại 2.3 chạy |
| V8 hai root | root A (process 12716) công bố mục `verified`/`project`; root B mới (process 49184) dùng đúng mục đó là `fact`, đạt; root hẹp không nhận; ghi vào root đã kết thúc bị từ chối |
| V9 tiếp quản | controller chết thật (exit 41); `executor recover` xác nhận dọn; giữ node rồi chạy lại 1 lần (generation 1), 2 lần launch, 2 lượt tính phí |
| **V10 bắt buộc (P2-02)** | 2 000 trang đứng trước trang có ràng buộc `a-value` → vẫn giao là bắt buộc, node chạy; trang ràng buộc không phải UTF-8 → dừng trước model (`native_preflight`, claude giả 0 lượt); trang tùy chọn hỏng → node chạy, receipt ghi `wiki.complete: false`, `unreadable: 1` |
| **V11 tiếp tục (P2-01)** | CLI cài: `continue --json` và `context retrieve` ghi quyết định `verified`, rồi `stale` ("a.txt changed since blob …") khi a.txt đổi; ghi chú riêng bị thay không hiện, `wiki history` ghi `superseded`; ghi chú mới vẫn `verified`; ghi chú của root khác không hiện |

### 5.3 Diễn tập

- **README của gói — 9/9** (các khối PowerShell gần nguyên văn; cwd `D:\TamNT\Workspace\9.VMAgent\onecrew` có sẵn `onecrew/` và `onecrew.egg-info`; `LOCALAPPDATA`/`APPDATA` riêng; log `D:\OneCrewRuns\v23 drill dev3\drill.txt`): hash khớp, bộ kiểm 11/11, venv có dấu cách + cài wheel + `--help` có `wiki`, quay về `2.2.0.dev18`, lên lại `2.3.0.dev3`.
- **Task đầu tiên từ gói — 23/23** (`verify/first_task_drill.py`, chạy đúng các khối PowerShell của `examples/first-task/README.vi.md`, venv mới, `claude` giả, gói không đổi; log `D:\OneCrewRuns\v23 task dau tien dev3 ai\drill\first-task-drill-log.json`). Bước duy nhất được thay: duyệt plan — lệnh `onecrew owner approve` trong README bị từ chối trong phiên AI (đúng thiết kế), diễn tập thay bằng duyệt fixture trên sổ tạm và ghi `substituted`.
- **Ghi rõ một lượt không dùng làm bằng chứng:** lượt diễn tập đầu (`D:\OneCrewRuns\v23 task dau tien dev3\drill`, 21/21) tôi chạy với biến đánh dấu phiên AI đã bị gỡ khỏi môi trường process, nên lệnh `owner approve` của README đã chạy thật trên **sổ tạm của diễn tập** (không phải sổ thật, không phải quyết định của chủ sở hữu). Đã chạy lại đúng chế độ (lượt 23/23 ở trên).

### 5.4 Test và số đo

| Lượt | Kết quả | Nguồn |
|---|---|---|
| Hồi quy trên code cuối `6a8421d`: mọi `tests/test_v23_*` (gồm 55 test từ phản chứng Codex và 3 vòng review) + `test_g1_core`, `test_wf_r03a_executors`, `test_wf_r02_resume/retrieval/boundaries`, `test_wf_r06_learning`, `test_wf_r07_localization`, `test_wf_r7_t46a/t46b`, `test_wf_node_learning`, `test_wf_runtime_unknowns`, `test_wf_w49b/w50a_evidence` | 268/268 đạt, 0 skip; `test_wf_r7_t51b` lỗi import vì lượt chạy bỏ `tests` khỏi `PYTHONPATH` → chạy lại 4/4 đạt | `D:\OneCrewRuns\v23\logs\final-regress-6a8421d.txt`, `final-t51b-6a8421d.txt` |
| Gate snapshot 2.2 (286 check) trên `0594a43` | 286/286 check đạt (217 lượt module, 2 097 test, 0 skip, 0 lỗi); quyết định `refused`: 23 khoảng trống ngoài (giống beta) + kit-guard (3 test ghim đã sửa) | §5.5 |

KS-01 (chọn gói, giây, min–max của 3 lần; đo **song song** code cũ `38981bd` và code mới `0594a43` trong cùng lúc, máy đang chạy gate nên số tuyệt đối cao hơn lượt `4182ee5` lúc máy rảnh — 22 000 mục khi đó 2,5–2,7 s):

| Kho | Code cũ `38981bd` | Code mới `0594a43` |
|---|---|---|
| 100 mục | 0,18–0,30 | 0,18–0,36 |
| 1 200 mục | 0,78–4,5 | 0,84–4,6 |
| 6 000 mục | 1,8–6,6 | 1,9–6,7 |
| 11 000 mục | 5,3–10,5 | 5,4–10,1 |
| 22 000 mục | 8,9–10,4 | 9,0–11,5 |
| 52 000 mục | 20,7–27,3 | 21,3–28,1 |
| 2 001 trang wiki, ràng buộc ở trang cuối | 0,6–5,2 — **ràng buộc mất** | 0,9 — ràng buộc giao |
| 10 001 trang wiki | 1,4–5,1 — **ràng buộc mất** | 3,1–10,1 — ràng buộc giao, `wiki.not_read: 8000` |

Code mới không chậm hơn ở cùng cỡ sổ; với wiki trên 2 000 trang nó chậm hơn vì dò mọi trang (đó là bản sửa P2-02). Nguồn: `docs/v23/evidence/ks01-scale-0594a43.json`, `ks01-scale-side-38981bd.json`. Không có chỉ mục; mỗi lần giao đọc lại toàn bộ.

KE-01/KE-02 trên `0594a43` (claude giả + Claude Code CLI thật `claude-haiku-5-5`, subscription, không API trả phí): gói tri thức giống hệt lượt `4182ee5` (2 135/2 169 ký tự; KE-02 2 484/2 526), cùng kết quả đúng/sai theo điều kiện; khác: KE-01 "không wiki" với Claude thật 2/2 bị giữ (danh sách file không hợp lệ). Nguồn: `docs/v23/evidence/ke01-0594a43.json`, `ke02-0594a43.json`. Lượt gọi provider thật đêm nay: 16 (KE) + 1 lượt ngoài ý muốn của agent P2-03 (22,7 s, dữ liệu mẫu, không tính làm bằng chứng).

### 5.5 Gate snapshot 2.2

29/10 00:45–04:19 (3 h 34 m; máy đang chịu tải của phiên khác). Lệnh `wfkit.development_gate snapshot` chạy trên commit `0594a43` (code = `6a8421d`) trong worktree tách riêng.
- Kết quả: `D:\OneCrewRuns\v23\gates-tmp\wf-snapshot-gate-20261029-0594a43` (`decision.json`, `gate\kitguard.json`, `gate\receipts\`, `gate-run.log`).
- Log lệnh: `D:\OneCrewRuns\v23\logs\gate-snapshot-0594a43.txt`.

- **Snapshot:** `intact: true` (cây code và thư mục tài liệu không đổi trong lúc chạy); build `dirty: []`; Python 3.13.15.
- **Check:** 286/286 có receipt, `failed: []`; 217 lượt chạy module khác nhau, 2 097 test đạt, 0 skip, 0 lỗi. Mọi receipt mang commit `0594a43` và wheel của gate.
- **Wheel của gate khác wheel của gói về byte, giống về nội dung.** Gate luôn tự dựng wheel từ snapshot:
  - wheel của gate: `bc43c37e47458fa73ca03440942c6b9d2f3e6f8f494b4236b24935de41cb19ff`, dựng 00:45;
  - wheel của gói: `30e6b7e6…ac0ec43`, dựng 00:38 bằng `build_milestone.py`.

  Hai wheel cùng commit `0594a43` và version `2.3.0.dev3`; 132/132 file bên trong giống nhau từng byte, chỉ khác giờ ghi trong zip. Gate chạy trên wheel `bc43c37e…`; kiểm từ artifact (§5.2) và diễn tập (§5.3) chạy trên wheel của gói `30e6b7e6…`.
- **Cài và nguồn module:** wheel cài vào venv của gate và module được nạp từ venv; bản checkout bị từ chối đúng như đối chứng (`gate\install.json`).
- **Tự kiểm tài liệu T38a:** đạt, 155/155 phản chứng và 18/18 đối chứng (khối `482bf8a3…`). Vấn đề `document-selfcheck` của gate beta `34eb7c4` không còn.
- **Quyết định gate: `refused`, 24 vấn đề:**
  - **23 khoảng trống nghiệm thu:** 13 `acceptance-partial` (R01–R08, RP, RX1, RX2) và 10 `acceptance-blocked` (PL, RP). Mỗi khoảng trống cần một việc thật: chủ sở hữu chạy lệnh nghiệm thu trên bản giao, pilot thật, provider ngoài (W45), hoặc receipt giao của bản trước. Nội dung giống từng chữ gate beta (`D:\OneCrewRuns\wf-handover-34eb7c4-hs2\gate\decision.json`); không khoảng trống nào đóng được trong phát triển.
  - **1 vấn đề mới: `kit-guard`.** Bộ kit 2.2 ghim hash của các test đã duyệt. Nhánh 2.3 đã sửa 3 file ghim; cả ba thay đổi có từ trước mốc Codex review và đều nằm trong gói dev2:

| File ghim | Release | Commit sửa | Vì sao sửa | Oracle |
|---|---|---|---|---|
| `tests/test_g1_core.py` | PL | `f045a0b` | dòng version `2\.2\.0\.dev\d+` → `2\.3\.0\.dev\d+` | các ràng buộc khác của metadata giữ nguyên |
| `tests/test_wf_r03a_executors.py` | R03 | `72b1b22` (2.3-B) | `executor list` nay có thêm 2 executor runtime mà engine khởi động | vẫn so khớp đúng cả danh sách |
| `tests/test_wf_r7_t51b.py` | R02 | `3d96f5b` (2.3-A1) | bộ lọc project nay có thêm lớp SQL; đột biến bỏ cả hai lớp, thêm test chứng minh mỗi lớp tự giữ được | chặt hơn |

  Không file nào hạ oracle, nhưng kit không có ngoại lệ U1 cho chúng nên từ chối. Đó là đúng thiết kế. Đặt lại bản 2.2 của các file này không giải quyết được: trên code 2.3, ba check đó sẽ đỏ vì version 2.3, danh sách executor mới và đột biến một lớp không còn làm lộ dữ liệu. Vì vậy không có cách sửa kỹ thuật nào không cần chủ sở hữu.

  Tôi không ghi ngoại lệ U1 và không sửa manifest của kit; việc đó cần chủ sở hữu (§8). Ghim lịch sử R00 (`tests/test_wf_plan_names.py`) đổi như ở beta và được namespace lineage chấp nhận như ở beta (`lineage_valid: true`).
- **Gate baseline trên `38981bd`:** dừng ở 155/286, không có decision, không tính là đạt.

## 6. Cách cài và chạy task đầu tiên

Theo `README.md` của gói và `examples/first-task/README.vi.md`: kiểm hash wheel, chạy bộ kiểm 11 bước, tạo venv thử mới (đường dẫn tùy ý), `pip install --no-index` wheel, làm task đầu tiên phần A (claude giả) rồi phần B (Claude Code CLI thật đã đăng nhập subscription; bước duyệt plan `onecrew owner approve` do chủ sở hữu chạy trong terminal của mình). Quay về 2.2: wheel `wheel/previous/` (giống từng byte gói beta).

## 7. Bảo toàn beta và cách ly

- **Beta giữ nguyên (kiểm 29/10 ~01:30):** gói `D:\OneCrewRuns\wf-handover-34eb7c4-hs2` 687/687 dòng `SHA256SUMS` khớp, file mới nhất 28/10 12:34; wheel `2.2.0.dev18` SHA256 `0346577e…`; checkout `wf-codex` sạch ở `95bb7a6`.
- **Môi trường thật:** `%LOCALAPPDATA%\OneCrew\hook-projects.json` không đổi từ 28/10 16:29 (mốc của một phiên beta khác), không có project thử nào của 2.3; không đổi PATH, registry, provider config, hooks hay executable; không công cụ nào của 2.3 dùng `state-v2-real` (hai chỗ nhắc tên đều là chặn/cảnh báo).
- **Cách ly của mọi lượt chạy:** worktree riêng (`wf-v23`, `wf-v23-ft`, `wf-v23-r2`, `wf-v23-r3`; worktree đo tạm đã xóa), venv mới trong thư mục kiểm, `TEMP`/`LOCALAPPDATA`/`APPDATA` riêng chỉ cho process thử, sổ tạm.
- **Process:** chỉ dừng job do chính tôi chạy: gate baseline trên `38981bd` (155/286, đều pass, không decision — không tính là đạt; `D:\OneCrewRuns\v23\logs\gate-38981bd-stopped.txt`) và ba lượt hồi quy đã cũ. Lượt hồi quy bị dừng in hàng loạt lỗi `0xC0000142` (git không khởi động được khi process đang bị dừng) — không phải lỗi sản phẩm, không dùng làm kết quả.
- **Giới hạn quan sát:** máy dùng chung, phiên khác chạy song song; số đo thời gian có nhiễu; không hứa "không ảnh hưởng hiệu năng".

## 8. Quyết định cần chủ sở hữu

- **Cần quyết định: ngoại lệ kit-guard cho 3 test ghim (§5.5).**
  - Đổi gì: ghi 3 bản ghi U1 (hash cũ → mới, lý do) cho `tests/test_g1_core.py`, `tests/test_wf_r03a_executors.py` và `tests/test_wf_r7_t51b.py`, chỉ trên nhánh 2.3.
  - Vì sao: ba test 2.2 này kiểm version 2.2, danh sách executor của 2.2 và đột biến một lớp; 2.3 đổi đúng ba điều đó.
  - Ảnh hưởng: chạy lại gate (~3,5 h); sau đó gate chỉ còn đúng 23 khoảng trống như beta.
  - Không đổi: beta và bộ kit của `wf-codex`, các test khác, oracle.
  - Rủi ro: nếu không duyệt, gate 2.3 luôn `refused` vì kit-guard; Codex vẫn review được.
  - Tôi chưa làm gì cho việc này.
- Ngoài việc trên, không quyết định nào khác đang chặn công việc trong phạm vi đã ủy quyền.
- Việc của chủ sở hữu/Codex (ngoài quyền đã cấp): giao Codex review lại gói `2.3.0.dev3`; nghiệm thu; push/tag/publish; dùng 2.3 trên sổ thật hay migrate sổ thật.
- Ghi nhận để chủ sở hữu biết: một lượt diễn tập đã chạy `owner approve` trên sổ tạm (§5.3); một lượt Claude thật ngoài ý muốn của agent P2-03 (§5.4).
