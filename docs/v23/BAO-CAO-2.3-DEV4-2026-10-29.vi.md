# OneCrew 2.3 — bàn giao 2.3.0.dev4 sau review Codex dev3

Người viết: Claude (Opus 5.5), đầu mối triển khai 2.3, 29/10/2026, theo chỉ thị người dùng 29/10 ("Tiếp tục hoàn thiện OneCrew 2.3 từ kết quả Codex review dev3…"). Đây là **tự kiểm của tác giả**, chưa phải Codex review lại, chưa nghiệm thu. Roadmap chung và 92 task beta không bị sửa; không push/tag/publish; không gọi provider thật trong lượt này. Báo cáo trước: [BAO-CAO-2.3-DEV3-2026-10-29](BAO-CAO-2.3-DEV3-2026-10-29.vi.md) (đã thêm đính chính ở đầu).

**Không bàn giao (29/10 ~11:00):** gói `2.3.0.dev4` đã dựng (`84940f7`, wheel `b3a63d1f…`) và qua kiểm từ gói 12/12, diễn tập README 9/9 và task đầu tiên 23/23. Sau đó review độc lập bản sửa tìm thêm lỗi: bản ghi general bị thay thế lại hiện khi không có `--plan`, và kết quả xét bị "cho mượn" giữa hai bản ghi trùng id. Tôi dừng gate trên `84940f7` (không tính là đạt). Bản sửa và gói thay thế: [BAO-CAO-2.3-DEV5-2026-10-29](BAO-CAO-2.3-DEV5-2026-10-29.vi.md). Phần dưới là bản nháp lúc dựng gói dev4, giữ nguyên.

**Bản nào:** bản trong `docs/` của gói là bản lúc dựng gói: §1, §5 và §7 (phần "sau") chỉ có ở bản trong checkout `D:\TamNT\Workspace\11.OneCrew\wf-v23\docs\v23\BAO-CAO-2.3-DEV4-2026-10-29.vi.md`, ghi sau khi kiểm. Gói không tự chứng nhận chính nó.

| | |
|---|---|
| Code | sửa P2 ở `6a8e400`, U1 ở `26a51c5`, công cụ gói (V12) ở `a276462`, nhánh local `claude/onecrew-2.3` (worktree `D:\TamNT\Workspace\11.OneCrew\wf-v23`); mốc Codex review `0594a43` (gói `2.3.0.dev3`, giữ nguyên) |
| Version | `2.3.0.dev4` (gói dev2/dev3 giữ nguyên, không ghi đè) |
| Gói thử | `D:\OneCrewRuns\v23\pkg\onecrew-2.3.0.dev4-final` (commit, wheel và hash: `README.md`, `manifest.json` của gói) |

## 1. Đã sẵn sàng test chưa, trong phạm vi nào

<!-- dev4:verdict -->
_Ghi sau khi kiểm gói (bản trong checkout)._

Phạm vi test như dev3: A1, A2, B trên **bản sao project và state root riêng**, Windows, worker native của engine (Claude Code CLI 2.1.286, subscription); diễn tập dùng `claude` giả. Không dùng với sổ thật hay sổ của task đang chạy.

## 2. P2 của review Codex dev3: tri thức general và khả năng áp dụng

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
- `onecrew/v2/context.py:358` `judged(…, plan=)` dùng kết quả đó cho mục general (`:374–377`, `:396–397`). Một bản ghi 2.3 dùng chung mà bước xét không phủ (lỗi, hoặc không có trong kết quả) không bao giờ hiện như hiện hành (`:405`).
- `onecrew/v2/evidence_cli.py:109` truyền `--plan` vào `judged`.

**Hành vi sau sửa**, trong mọi dạng `context retrieve` trả scope general (không có/có `--plan`, scope `general`/`both`, có `--revision`):

| Bản ghi general | `wiki show --plan` | `context retrieve` |
|---|---|---|
| điều kiện sai ở đây | không giao (`not_applicable`) | `stale`, "not applicable now: platform is win32, the entry holds for linux" |
| điều kiện không kiểm được (`model` khi không có node, điều kiện chữ) | `lead` | `stale`, "cannot be checked now: …" |
| điều kiện đúng | `fact` | `verified` (không đổi) |
| đã thu hồi / bị thay thế | không giao | không hiện; `wiki history` giữ `withdrawn`/`superseded` với nhãn gốc |
| ghi bằng 2.2 (điều kiện chữ, 2.2 không kiểm) | `lead` | giữ nhãn 2.2 (quy tắc tương thích R2-09, không đổi) |

Nhãn gốc giữ ở `stored_label`; nguồn và điều kiện giữ nguyên. Mục project, quyền đọc, cách ly project/root, vòng đời và `onecrew continue` (chỉ scope project) không đổi.

**Phản chứng đỏ → xanh (cùng dữ liệu, cùng kỳ vọng):**

| Lượt | Đỏ trên dev3 | Xanh sau sửa |
|---|---|---|
| `tests/test_v23_codex_review_dev3.py` (8 test qua `onecrew.v2.cli.main`, sổ tạm) | code dev3 (= `0594a43`): 4 phản chứng fail, 12 subtest, tất cả `'verified' != 'stale'`; 4 đối chứng đạt (`D:\OneCrewRuns\v23\dev4\logs\red-0594a43.txt`) | `6a8e400`: 8/8 (`D:\OneCrewRuns\v23\dev4\logs\green-dev3tests.txt`) |
| CLI của wheel **đã cài** trong venv sạch ngoài checkout (đường dẫn có dấu cách), `scenario_codex.py general`, oracle `verify_milestone.general_problems` | wheel gói dev3 `30e6b7e6…ac0ec43`: 8 lỗi, đúng hai bản ghi đó trong 4 dạng; mọi đối chứng đạt (`D:\OneCrewRuns\v23\dev4\cli red dev3\general-cli.json`) | wheel phát triển `dfcc9c62…` (không phải artifact giao): đạt (`D:\OneCrewRuns\v23\dev4\cli green dev\general-cli.json`); trên wheel của gói: bước V12 (§5) |

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
- **Giới hạn ghi rõ:** mục general ghi bằng 2.2 giữ nhãn 2.2 trong `context retrieve` (điều kiện chữ tự do không kiểm được; gói tri thức coi là đầu mối). Chi phí của lần xét thêm cho bản ghi general khi không có `--plan` chưa đo riêng.

## 5. Gói, kiểm từ artifact, gate

<!-- dev4:section5 -->
_Ghi sau khi kiểm gói (bản trong checkout)._

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
- **Sau khi làm:**

<!-- dev4:beta-after -->
_Ghi sau khi kiểm gói (bản trong checkout)._

- **Cách ly:**
  - worktree riêng `wf-v23`, `wf-v23-dev4` (hồi quy trên commit cố định);
  - venv mới ngoài checkout;
  - `TEMP`/`LOCALAPPDATA`/`APPDATA` riêng cho process thử;
  - sổ tạm;
  - không gọi provider thật;
  - không đổi PATH, registry, provider config, hooks, cấu hình Claude dùng chung.

## 8. Còn Blocked và quyết định

<!-- dev4:blocked -->
_Ghi sau khi kiểm gói (bản trong checkout)._
