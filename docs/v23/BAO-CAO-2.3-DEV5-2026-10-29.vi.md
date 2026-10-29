# OneCrew 2.3 — bàn giao 2.3.0.dev5 sau review Codex dev3

Người viết: Claude (Opus 5.5), đầu mối triển khai 2.3, 29/10/2026, theo chỉ thị người dùng 29/10 ("Tiếp tục hoàn thiện OneCrew 2.3 từ kết quả Codex review dev3…"). Đây là **tự kiểm của tác giả**, chưa phải Codex review lại, chưa nghiệm thu. Roadmap chung và 92 task beta không bị sửa; không push/tag/publish; không gọi provider thật trong lượt này. Báo cáo trước: [BAO-CAO-2.3-DEV3-2026-10-29](BAO-CAO-2.3-DEV3-2026-10-29.vi.md) (đã thêm đính chính ở đầu). Gói `2.3.0.dev4` đã dựng và kiểm nhưng **không bàn giao**: review độc lập bản sửa tìm thêm lỗi (§2.2); bản nháp của nó: [BAO-CAO-2.3-DEV4-2026-10-29](BAO-CAO-2.3-DEV4-2026-10-29.vi.md).

**Bản nào:** bản trong `docs/` của gói là bản lúc dựng gói: §1, §5 và §7 (phần "sau") chỉ có ở bản trong checkout `D:\TamNT\Workspace\11.OneCrew\wf-v23\docs\v23\BAO-CAO-2.3-DEV5-2026-10-29.vi.md`, ghi sau khi kiểm. Gói không tự chứng nhận chính nó.

| | |
|---|---|
| Code | sửa P2 ở `6a8e400` + sửa sau review độc lập ở `9a2b453`, U1 ở `26a51c5`, công cụ gói (V12) ở `a276462` + `cecc09b`, nhánh local `claude/onecrew-2.3` (worktree `D:\TamNT\Workspace\11.OneCrew\wf-v23`); mốc Codex review `0594a43` (gói `2.3.0.dev3`, giữ nguyên) |
| Version | `2.3.0.dev5` (gói dev2/dev3/dev4 giữ nguyên, không ghi đè) |
| Gói thử | `D:\OneCrewRuns\v23\pkg\onecrew-2.3.0.dev5-final` (commit, wheel và hash: `README.md`, `manifest.json` của gói) |

## 1. Đã sẵn sàng test chưa, trong phạm vi nào

**Sẵn sàng cho Codex review lại**, trong phạm vi dưới đây: phần local đã khép trên snapshot `b3ecc57`, mọi bằng chứng thuộc gói cuối `2.3.0.dev5` (wheel `da500499…`). Gate 2.2 trên snapshot đó: 286/286 check đạt, quyết định `refused` chỉ vì 23 khoảng trống nghiệm thu như beta (không còn vấn đề kit-guard). Đây là tự kiểm của tác giả, không phải Codex chấp thuận, nghiệm thu hay phát hành. Còn mở: F4 (§4) và các mục ở §8.

Phạm vi test như dev3: A1, A2, B trên **bản sao project và state root riêng**, Windows, worker native của engine (Claude Code CLI 2.1.286, subscription); diễn tập dùng `claude` giả. Không dùng với sổ thật hay sổ của task đang chạy.

## 2. P2 của review Codex dev3: tri thức general và khả năng áp dụng

### 2.1 Lỗi Codex và bản sửa đầu

**Lỗi (Codex, 29/10):** trên Windows, một bản ghi general `verified` có điều kiện `platform: linux`:
- `wiki show --plan P1` loại nó (`not_applicable`);
- `context retrieve --scope general` và `context retrieve --plan P1 --scope general` vẫn trả `label: verified`, `stale_reason: null`.

Codex tái hiện qua CLI của wheel dev3 đã cài (`D:\OneCrewRuns\codex-v23-dev3-review-20261029\installed-general-condition-probe.json`, `-control.json`).

**Nguyên nhân:** `context.judged` (code dev3 `onecrew/v2/context.py:389`) chỉ lấy kết quả xét của `knowledge.for_root` cho mục scope `project`. Mục `general` chỉ được so với `knowledge.status_by_id` (`context.py:376`), tức là vòng đời (thu hồi, lưu trữ, thay thế), không xét điều kiện hay độ chắc chắn. Báo cáo dev3 §2 vì vậy tuyên bố rộng hơn hành vi thật.

**Sửa (giải pháp nhỏ nhất, cùng bộ xét, không thêm bộ chọn hay kho):**
- `onecrew/v2/knowledge.py:1222` `for_root` → `_for_reader` (`:1246`) xét cả bản ghi general (`:1254`), bằng đúng `_collect`/`_decide` của gói tri thức, cho người đọc:
  - root của `--plan`;
  - hoặc, khi không có `--plan` (`:1235`), project không có root: không có file, không có node, môi trường là process đang chạy (`_environment`, `:116`).
- Kết quả xét của mỗi root được nhớ trong memo của lệnh (`:1273`), nên `--plan` không xét lại cùng root hai lần.
- Bản ghi general không đi qua nhánh "root khác ghi bản mới hơn" (`:1259`), nhánh đó chỉ dành cho tri thức của root.
- `onecrew/v2/context.py:358` `judged(…, plan=)` dùng kết quả đó cho mục general (`:374–377`, `:396–397`). Một bản ghi 2.3 mà bước xét không phủ (lỗi, không có trong kết quả, hoặc trùng id với bản ghi khác) không bao giờ hiện như hiện hành (`:413`).
- `onecrew/v2/evidence_cli.py:109` truyền `--plan` vào `judged`.

**Hành vi sau sửa**, trong mọi dạng `context retrieve` trả scope general (không có/có `--plan`, scope `general`/`both`, có `--revision`):

| Bản ghi general | `wiki show --plan` | `context retrieve` |
|---|---|---|
| điều kiện sai ở đây | không giao (`not_applicable`) | `stale`, "not applicable now: platform is win32, the entry holds for linux" |
| điều kiện không kiểm được (`model` khi không có node, điều kiện chữ) | `lead` | `stale`, "cannot be checked now: …" |
| điều kiện đúng | `fact` | `verified` (không đổi) |
| đã thu hồi / bị thay thế (kể cả bởi bản ghi dẫn file mà người đọc không đọc được) | không giao (hoặc `lead` khi người đọc không đọc được bản thay thế, quy tắc R3-2) | không hiện, với mọi người đọc; `wiki history` giữ `withdrawn`/`superseded` với nhãn gốc |
| ghi bằng 2.2 (điều kiện chữ, 2.2 không kiểm) | `lead` | giữ nhãn 2.2 (quy tắc tương thích R2-09, không đổi) |
| trùng id tri thức với bản ghi khác (ví dụ hai project cùng dùng một `--key` cho bản ghi general) | chỉ bản mới nhất là ứng viên | bản không được xét: `stale`, "not judged: another record (event N) has the same knowledge id …" — không bao giờ hiện hành |

Nhãn gốc giữ ở `stored_label`; nguồn và điều kiện giữ nguyên. Mục project, quyền đọc, cách ly project/root, vòng đời và `onecrew continue` (chỉ scope project) không đổi.

**Phản chứng đỏ → xanh (cùng dữ liệu, cùng kỳ vọng):**

| Lượt | Đỏ trên dev3 | Xanh sau sửa |
|---|---|---|
| `tests/test_v23_codex_review_dev3.py` (8 test qua `onecrew.v2.cli.main`, sổ tạm) | code dev3 (= `0594a43`): 4 phản chứng fail, 12 subtest, tất cả `'verified' != 'stale'`; 4 đối chứng đạt (`D:\OneCrewRuns\v23\dev4\logs\red-0594a43.txt`) | `6a8e400`: 8/8 (`D:\OneCrewRuns\v23\dev4\logs\green-dev3tests.txt`) |
| CLI của wheel **đã cài** trong venv sạch ngoài checkout (đường dẫn có dấu cách), `scenario_codex.py general`, oracle `verify_milestone.general_problems` | wheel gói dev3 `30e6b7e6…ac0ec43`: 8 lỗi, đúng hai bản ghi đó trong 4 dạng; mọi đối chứng đạt (`D:\OneCrewRuns\v23\dev4\cli red dev3\general-cli.json`) | wheel phát triển `dfcc9c62…` (không phải artifact giao): đạt (`D:\OneCrewRuns\v23\dev4\cli green dev\general-cli.json`); trên wheel của gói: bước V12 (§5) |

### 2.2 Review độc lập bản sửa đầu và sửa lần hai

Một agent Opus 5.5 review riêng `6a8e400` (chỉ đọc code và chạy probe trên sổ tạm; probe chạy cả trên code trước sửa `1a68ce3` để tách lỗi mới khỏi khoảng trống cũ). Báo cáo: `D:\OneCrewRuns\v23\review-dev4\review-dev4.md`. Probe được giữ thành `tests/test_v23_review_dev4.py` (20 probe của reviewer + `r03b` đối xứng).

| Điểm | Mức | Mới hay cũ | Nội dung | Sửa ở `9a2b453` |
|---|---|---|---|---|
| F1, F1b | P1 (reviewer), P3 | mới, do `6a8e400` | bản ghi general bị một bản ghi project dẫn file thay thế lại hiện (`stale`) khi không có `--plan` (người đọc không root không đọc được file) hoặc với plan không đọc được bản thay thế | `context.judged` xét vòng đời của project trước cho mục dùng chung (`context.py:400`): đã mất là không hiện, với mọi người đọc |
| F2 (r02a), r03, r03b | P1 | cũ (trước sửa cũng sai) | bản ghi khác có cùng id tri thức "cho mượn" kết quả xét: bản ghi chỉ đúng trên linux hiện `verified` trên Windows | kết quả xét mang `version` và `scope` của đúng bản ghi được xét (`knowledge.py:1257`); chỉ áp cho đúng bản ghi đó (`context.py:402–405`) |
| F3 (r02b, phần lý do) | P2 | mới, do `6a8e400` | bản ghi hợp lệ hiện `stale` với lý do của bản ghi khác | như trên: lý do giờ là "not judged: another record … has the same knowledge id" |
| F4 (r02b, r02c, r02d) | P2 | cũ | hai project cùng state root dùng cùng một `--key` cho bản ghi general có chung một id tri thức: một bản che bản kia (gói tri thức cũng chỉ thấy bản mới nhất), thu hồi của project này tác động lên bản của project kia, project thứ hai không thu hồi được bản của mình | **chưa sửa** (đổi hợp đồng id tri thức); giữ là expected failure trong test, ghi ở §4 |

Review lần hai, chỉ phần sửa `9a2b453` (cùng agent): **không có điểm mới**. 5 probe thêm (d01–d05: bản đính chính sau thu hồi/lưu trữ, cập nhật bởi root khác, quay về bản cũ) đều đạt và đã đưa vào cùng file test. Hành vi cần biết, theo quy tắc F1b: nếu bản ghi general bị thay bằng một bản ghi project có điều kiện sai ở đây, bản general không hiện với mọi người đọc còn bản thay thế hiện `stale`, nên `context retrieve` không có mục hiện hành nào cho chủ đề đó (`wiki show` vẫn liệt bản general là đầu mối). Không mục nào bị hiện sai như sự thật hiện hành.

Đỏ → xanh, cùng test và cùng kỳ vọng:
- **Test của reviewer** (`tests/test_v23_review_dev4.py`, 26 test sau khi thêm d01–d05):
  - trên `6a8e400`: 13 subtest fail (r01, r01b, r01c, r02a, r03, r03b), 3 expected failure (`D:\OneCrewRuns\v23\dev5\logs\review-probes-6a8e400.txt`);
  - sau sửa: tất cả đạt, 3 expected failure còn lại là nhóm F4 (`review-probes-fix.txt`).
- **CLI của wheel đã cài**, cùng `scenario_codex.py general` (thêm ca F1) và cùng oracle:
  - wheel gói dev3 `30e6b7e6…`: 8 lỗi (P2 Codex);
  - wheel gói dev4 `b3a63d1f…`: 2 lỗi (F1, không có `--plan`);
  - wheel phát triển từ cây dev5: đạt.

  Kết quả ở `D:\OneCrewRuns\v23\dev5\cli red dev3`, `cli red dev4`, `cli green dev`; trên wheel gói dev5 là bước V12 (§5).
- **Gate trên `84940f7` (gói dev4):** tôi dừng lúc 10:55 khi review tìm ra lỗi; không tính là đạt (`D:\OneCrewRuns\v23\dev4\logs\gate-84940f7-stopped.txt`). Trước khi dừng, `R01/check.release_bundle` có 1 test fail, `test_e10…live_files_are_unchanged`: hash của **sổ thật** `state-v2-real` đổi trong lúc test chạy, vì một việc thật khác ghi vào sổ lúc 10:36:43, trong cửa sổ của test (truy vấn chỉ đọc, chỉ đếm loại sự kiện). Test này canh để gate không bao giờ ghi file thật; nó không phân biệt được người ghi khác. Không phải lỗi của 2.3, nhưng vẫn là một check fail.

## 3. U1

Chỉ thị 29/10 mục 3 cho phép ghi ngoại lệ U1 phạm vi hẹp trên nhánh 2.3 cho đúng ba thay đổi Codex đã xem diff. Cơ chế hiện hành hỗ trợ ủy quyền: U1 là file `wfkit/u1/<id>.json` có `authorized_by`, không phải lệnh của chủ sở hữu trên sổ. Vì vậy tôi đã ghi, không có bước nào của chủ sở hữu bị thay.

| U1 | File | Hash cũ → mới (CRLF đọc như LF) | Commit sửa | Vì sao |
|---|---|---|---|---|
| `U1-20261029-V23-PIN-1` | `tests/test_g1_core.py` | `8e824df8…` → `1d454de4…` | `f045a0b` | dòng version `2.2.0.devN` → `2.3.0.devN` |
| `U1-20261029-V23-PIN-2` | `tests/test_wf_r03a_executors.py` | `c02af0a5…` → `6fc526c5…` | `72b1b22` | danh sách executor thật (thêm 2 executor runtime), vẫn so khớp đúng cả danh sách |
| `U1-20261029-V23-PIN-3` | `tests/test_wf_r7_t51b.py` | `ee3f22ce…` → `10023df8…` | `3d96f5b` | đột biến bỏ cả hai lớp lọc; thêm đối chứng từng lớp tự giữ |

Trước khi ghi đã kiểm:
- hash bản `95bb7a6` và bản hiện hành khớp với kit-guard;
- mỗi file chỉ có đúng một commit sửa từ `95bb7a6`;
- diff không xóa kiểm tra, không nới oracle, không có thay đổi khác.

Mỗi bản ghi nêu `authorized_by` = chỉ thị 29/10 (trích nguyên văn) và ghi rõ không phải chữ ký trực tiếp của chủ sở hữu, không phải nghiệm thu. kit-guard development của gate: trước khi ghi từ chối đúng 3 file đó, sau khi ghi đạt (`D:\OneCrewRuns\v23\dev4\u1\kitguard-before.json`, `kitguard-after.json`). Không U1 nào cho file khác. Không đổi manifest kit, tiêu chí nghiệm thu hay checkout `wf-codex`.

## 4. A1/A2/B còn requirement nào chưa đạt

- **A1-R4, A2-R2** (lịch sử ≠ áp dụng hiện tại; project/general có điều kiện): ở dev3 sai trên đường `context retrieve` cho bản ghi general (§2); nay đạt.
- Còn lại như báo cáo dev3 §3. Các khoảng trống nghiệm thu/pilot/provider của 2.2 (Partial/Blocked) giữ nguyên: lượt này không có bằng chứng mới cho chúng.
- **Khoảng trống cũ còn mở (F4, §2.2):** hai project cùng state root dùng cùng một `--key` cho bản ghi general thì có chung một id tri thức. Hậu quả: một bản che bản kia, thu hồi của project này tác động lên bản kia, project thứ hai không thu hồi được bản của mình. Sau sửa, bản không được xét không bao giờ hiện như hiện hành. Khóa mặc định gồm id project nên chỉ xảy ra khi tự đặt `--key` trùng. Sửa đúng cần id tri thức theo project (đổi hợp đồng id: đích thu hồi/thay thế, lịch sử, receipt), để cho version sau.
- **Giới hạn ghi rõ:** mục general ghi bằng 2.2 giữ nhãn 2.2 trong `context retrieve` (điều kiện chữ tự do không kiểm được; gói tri thức coi là đầu mối). Chi phí của lần xét thêm cho bản ghi general khi không có `--plan` chưa đo riêng.

## 5. Gói, kiểm từ artifact, gate

### 5.1 Gói

`D:\OneCrewRuns\v23\pkg\onecrew-2.3.0.dev5-final`: 40 file (39 dòng `SHA256SUMS` + chính nó); `manifest.json` → version `2.3.0.dev5`, commit `b3ecc57`, wheel SHA256 `da500499a86daea1635b7ea61c9a77f40a203e2df87fd0653c1db707b7fd8b89`, wheel quay về `onecrew-2.2.0.dev18` SHA256 `0346577e…ef9bd2` (giống từng byte gói beta), `claims` đều `false`. Gói dev2, dev3, dev4 giữ nguyên.

### 5.2 Kiểm từ artifact — 12/12 đạt

29/10 11:41–11:44, `python -I` của Python 3.13.15, thư mục làm việc `D:\OneCrewRuns\v23 thu dev5\verify` (ngoài checkout, có dấu cách), `LOCALAPPDATA`/`APPDATA` riêng; báo cáo `D:\OneCrewRuns\v23 thu dev5\verify\verify-report.json`, log `D:\OneCrewRuns\v23\dev5\logs\verify-dev5-b3ecc57.txt`. V1–V11 như dev3 (§5.2 của báo cáo dev3), cùng kết quả; mới:

| Bước | Kết quả |
|---|---|
| **V12 general (P2 Codex dev3)** | CLI của wheel cài: bản ghi general có điều kiện sai, đúng, không kiểm được, đã thu hồi, bị thay thế bằng bản ghi project dẫn file; có và không có `--plan`, scope `general`/`both`, `--revision HEAD`. Điều kiện sai hoặc không kiểm được không hiện là `verified`; bản ghi thu hồi hoặc bị thay không hiện lại (ca F1); bản ghi đúng vẫn `verified`; `wiki show` và `context retrieve` cùng kết luận; lịch sử `superseded`, `verified` |

### 5.3 Diễn tập

- **README của gói — 9/9** (các khối PowerShell của README; log `D:\OneCrewRuns\v23 drill dev5\drill.txt`): hash khớp, bộ kiểm 12/12, venv có dấu cách + cài wheel + `--help` có `wiki`, quay về `2.2.0.dev18`, lên lại `2.3.0.dev5`.
- **Task đầu tiên từ gói — 23/23** (`verify/first_task_drill.py`, phần A với `claude` giả, venv mới, gói không đổi; log `D:\OneCrewRuns\v23 task dau tien dev5 ai\drill\first-task-drill-log.json`). Chạy trong phiên AI: bước duyệt plan `onecrew owner approve` của README bị từ chối đúng thiết kế, nên được thay bằng fixture có nhãn; không phải hành động của chủ sở hữu.
- **Chủ sở hữu tự chạy từ terminal của mình** (29/10 15:58–16:02, `D:\OneCrewRuns\v23\thu-goi-dev5.ps1`, kết quả `D:\OneCrewRuns\v23 thu cua anh dev5 20261029-155825`): bộ kiểm 12/12; task đầu tiên 21/21 bước bắt buộc với `owner_step_mode: real`, `in_ai_session: false`, không bước nào bị thay. Lệnh `onecrew owner approve P1` của README chạy đúng như viết, trên **sổ tạm của diễn tập**; gói không đổi. Lần chạy này khép giới hạn "bước duyệt được thay bằng fixture" của lượt diễn tập trong phiên AI. Đây là chủ sở hữu tự thử trên sổ tạm, không phải nghiệm thu, cũng không phải duyệt plan trên sổ thật.

### 5.4 Phản chứng P2 qua CLI cài, cùng kịch bản

Kịch bản `docs/v23/tools/scenario_codex.py` ca `general` (SHA256 `6ac0c7a1…`, giống bản trong `verify/` của gói), venv sạch có dấu cách ngoài checkout, đếm lỗi bằng oracle `general_problems` của V12:

| Wheel | SHA256 | Lỗi |
|---|---|---|
| gói dev3 `2.3.0.dev3` | `30e6b7e6…` | 8 (đỏ: bản ghi general không áp dụng hiện `verified`) |
| gói dev4 `2.3.0.dev4` | `b3a63d1f…` | 2 (F1: bản ghi bị thay lại hiện khi không `--plan`) |
| gói dev5 `2.3.0.dev5` | `da500499…` | 0 |

Kết quả: `D:\OneCrewRuns\v23\dev5\cli red dev3`, `cli red dev4`, `cli green dev5 package` (`general-cli.json`).

### 5.5 Gate snapshot 2.2

29/10 11:41–15:43 (4 h 02 m). Một phiên khác chạy gate 2.2 của nó trên `e432be2` cùng lúc (09:56–13:39), sau đó là bundle; cùng bộ test trên máy này chậm hơn sáng 28/10 khoảng gấp đôi. Lệnh `wfkit.development_gate snapshot` chạy trên commit `b3ecc57` trong worktree tách riêng.
- Kết quả: `D:\OneCrewRuns\v23\gates-tmp\wf-snapshot-gate-20261029-b3ecc57` (`decision.json`, `gate\kitguard.json`, `gate\receipts\`, `gate-run.log`); log lệnh `D:\OneCrewRuns\v23\dev5\logs\gate-snapshot-b3ecc57.txt`.
- **Snapshot:** `intact: true`; build `dirty: []`; Python 3.13.15.
- **Check:** 286/286 có receipt, `failed: []`; 217 lượt chạy module khác nhau, 2 097 test đạt, 0 skip, 0 lỗi. Mọi receipt mang commit `b3ecc57` và wheel của gate.
- **Wheel của gate khác wheel của gói về byte, giống về nội dung:** wheel của gate `a59728f7d05f2f7d5833226bd6f020e574414670fb57dcabbe37a6a93eb5493e` (gate tự dựng từ snapshot); wheel của gói `da500499…` (`build_milestone.py`). Cùng commit và version `2.3.0.dev5`; 132/132 file bên trong giống nhau từng byte. Gate chạy trên wheel của gate; kiểm từ artifact (§5.2), diễn tập (§5.3) và phản chứng CLI (§5.4) chạy trên wheel của gói. Không gọi chúng là cùng một artifact.
- **Cài và nguồn module:** module nạp từ venv của gate; bản checkout bị từ chối đúng như đối chứng (`gate\install.json`).
- **Tự kiểm tài liệu T38a:** đạt, 155 phản chứng và 18 đối chứng.
- **kit-guard: đạt.** Ba ngoại lệ U1 `U1-20261029-V23-PIN-1..3` (§3) được dùng cho đúng ba file ghim; không file ghim nào khác đổi; namespace lineage đạt. Vấn đề kit-guard của gate dev3 không còn.
- **Quyết định gate: `refused`, 23 vấn đề**, đều là khoảng trống nghiệm thu: 13 `acceptance-partial` và 10 `acceptance-blocked`, giống từng chữ gate beta (`D:\OneCrewRuns\wf-handover-34eb7c4-hs2\gate\gate-decision.json`) và gate dev3. Mỗi khoảng trống cần việc thật ngoài phát triển (lệnh nghiệm thu của chủ sở hữu trên bản giao, pilot thật, provider ngoài). "Check thực thi đạt" ở trên khác quyết định cuối của gate: quyết định vẫn là `refused`.
- **Gate trên `84940f7` (dev4):** dừng ở 16/286 khi review tìm ra F1. Trước lúc dừng có 15 check đạt và 1 check fail thật: `R01/check.release_bundle`, test canh sổ thật, vì việc thật của project khác ghi sổ trong lúc test chạy (§2.2, bài học LL-16). Trên `b3ecc57`, check này đạt. Các receipt `error` ghi sau lúc dừng là hệ quả của việc dừng, không tính là đạt hay hỏng (`D:\OneCrewRuns\v23\dev4\logs\gate-84940f7-stopped.txt`).

## 6. Cách cài và chạy task đầu tiên

Theo `README.md` của gói và `examples/first-task/README.vi.md`:
1. kiểm hash wheel;
2. chạy bộ kiểm 12 bước;
3. tạo venv thử mới (đường dẫn tùy ý) và `pip install --no-index` wheel;
4. làm task đầu tiên phần A với `claude` giả, rồi phần B với Claude Code CLI thật đã đăng nhập subscription (bước duyệt plan `onecrew owner approve` do chủ sở hữu chạy trong terminal của mình).

Quay về 2.2: wheel `wheel/previous/`, giống từng byte gói beta.

## 7. Bảo toàn beta và cách ly

- **Trước khi làm (29/10 09:18):**
  - gói `D:\OneCrewRuns\wf-handover-34eb7c4-hs2`: 687/687 dòng `SHA256SUMS` khớp, 0 file sửa sau 28/10 13:30;
  - `hook-projects.json` thật SHA256 `884335df…`, sửa lần cuối 28/10 16:29;
  - checkout `wf-codex` ở `95bb7a6` **đang có thay đổi chưa commit của một phiên khác** (7 file code + `tests/test_wf_r15_beta_signsdk.py`, sửa 09:03–09:14 hôm nay, không phải của tôi; dấu vân tay `D:\OneCrewRuns\v23\dev4\beta-check\wf-codex-before.txt`). Lượt này không đọc, không sửa, không chạy gì trong checkout đó.
  - 09:46: `wf-codex` đã sang `e432be2` ("Round 15 … 2.2.0.dev19", phiên khác commit lúc 09:44); gói beta vẫn 687/687. 2.3 vẫn dựa trên `95bb7a6` (dev18): sửa của dev19 chưa có trong 2.3, wheel quay về là dev18 của gói beta.
  - Trong lúc làm, một phiên khác chạy gate 2.2 của nó trên `e432be2` (`D:\OneCrewRuns\wf-gates\wf-snapshot-gate-20261029-e432be2`); tôi không đụng vào. Máy chịu tải của cả hai gate.
- **Sau khi làm (15:44 29/10):** gói `D:\OneCrewRuns\wf-handover-34eb7c4-hs2` 687/687 dòng `SHA256SUMS` khớp, 0 file sửa sau 28/10 13:30; `hook-projects.json` thật vẫn SHA256 `884335df…`, sửa lần cuối 28/10 16:29 (như trước); checkout `wf-codex` ở `1753f77` (lúc 09:46 là `e432be2`; phiên khác commit thêm, tôi không đụng vào).

- **Cách ly:**
  - worktree riêng `wf-v23`, `wf-v23-dev4` (hồi quy trên commit cố định);
  - venv mới ngoài checkout;
  - `TEMP`/`LOCALAPPDATA`/`APPDATA` riêng cho process thử;
  - sổ tạm;
  - không gọi provider thật;
  - không đổi PATH, registry, provider config, hooks, cấu hình Claude dùng chung.

## 8. Còn Blocked và quyết định

- **Còn mở, không bàn giao như đã khép:**
  - F4 (§4): id tri thức của bản ghi general khi hai project tự đặt cùng `--key`; sửa đúng cần đổi hợp đồng id, để version sau. 3 probe giữ là expected failure.
  - 23 khoảng trống nghiệm thu, pilot và provider của 2.2 (Partial/Blocked) giữ nguyên.
  - Sửa của `2.2.0.dev19` (`e432be2`, phiên khác) chưa có trong 2.3 (2.3 dựa trên dev18 `95bb7a6`).
  - Chưa đo riêng chi phí của lần xét thêm cho bản ghi general khi không có `--plan`.
- **Cần chủ sở hữu:**
  - Codex review lại gói `2.3.0.dev5`.
  - Có đưa dev19 vào nhánh 2.3 trước lượt sau không (đổi baseline: phải chạy lại gate và kiểm gói).
  - Nghiệm thu, push, tag, phát hành: chưa làm, không thuộc lượt này.
