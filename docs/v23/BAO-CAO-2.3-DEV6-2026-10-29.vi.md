# OneCrew 2.3 — bàn giao 2.3.0.dev6 sau Codex review gói dev5

Người viết: Claude (Opus 5.5), đầu mối triển khai 2.3, 29/10/2026, theo chỉ thị người dùng 29/10 ("Tiếp tục hoàn thiện OneCrew 2.3 từ kết quả Codex review dev5…"). Đây là **tự kiểm của tác giả**, chưa phải Codex review lại, chưa nghiệm thu, chưa phát hành, không push/tag. Roadmap chung và 92 task beta không bị sửa; không gọi provider thật. Báo cáo trước: [BAO-CAO-2.3-DEV5-2026-10-29](BAO-CAO-2.3-DEV5-2026-10-29.vi.md) (đã thêm đính chính ở đầu: câu "phần local đã khép" ở đó không đúng).

**Bản nào:** bản trong `docs/` của gói là bản lúc dựng gói. Các mục §1, §5 và §7 (phần "sau") chỉ có ở bản trong checkout `D:\TamNT\Workspace\11.OneCrew\wf-v23\docs\v23\BAO-CAO-2.3-DEV6-2026-10-29.vi.md`, ghi sau khi kiểm. Gói không tự chứng nhận chính nó.

| | |
|---|---|
| Mốc Codex review | gói `2.3.0.dev5` (`b3ecc57`, wheel `da500499…`), bằng chứng `D:\OneCrewRuns\codex-dev5-handover-review-20261029` |
| Code | nhánh local `claude/onecrew-2.3`: P2-C/P2-D `b32ae19`, P2-B `ebcfa20`, công cụ gói `844b1e5`, P2-A `fca2813` (gộp `80b9ff9`), sửa sau review độc lập `926bdcf`, `a87389f` (gộp `98eb283`), `4516cc5` |
| Version | `2.3.0.dev6` (gói dev2…dev5 giữ nguyên, không ghi đè) |

## 1. Đã sẵn sàng test chưa, trong phạm vi nào

<!-- dev6:verdict -->
_Ghi sau khi kiểm gói (bản trong checkout)._

Phạm vi test như dev5: A1, A2, B trên **bản sao project và state root riêng**, Windows, worker native của engine; diễn tập dùng `claude` giả. Không dùng với sổ thật hay sổ của task đang chạy.

## 2. Bốn lỗi của Codex review dev5

### 2.1 P2-A — script thử báo đạt bằng log cũ

- **Nguyên nhân:** `D:\OneCrewRuns\v23\thu-goi-dev5.ps1` đọc báo cáo mà không kiểm chúng thuộc lần chạy nào. Codex đặt log đã đạt vào thư mục kết quả rồi chạy lại: diễn tập task đầu tiên từ chối chạy vì thư mục không rỗng (exit 1), nhưng script vẫn đọc log cũ, in 21/21 và "DAT", thoát 0.
- **Sửa:** script mới `docs/v23/tools/thu_goi.ps1`, gói mang nó dưới tên `verify\thu-goi.ps1` (`fca2813`, viết bởi một agent Sonnet, logic chấm đạt được tôi review độc lập).
  - Đọc version, commit, wheel từ `manifest.json` của gói; kiểm hash wheel; kiểm manifest, wheel và hai công cụ khớp `SHA256SUMS`.
  - Thư mục kết quả đã có thứ gì thì từ chối trước khi chạy (mã 2).
  - Chạy cả hai công cụ, kiểm mã thoát từng cái. Báo cáo chỉ được nhận khi: chưa có trước lúc công cụ chạy; giờ bắt đầu và giờ ghi không sớm hơn lúc chạy; ghi đúng gói, version, commit (bộ kiểm: cả tên và hash wheel; diễn tập: thư mục làm việc, version cài, `package_unchanged`); mọi bước bắt buộc đạt, đếm từ chính danh sách bước.
  - Chỉ in `DAT:` và thoát 0 khi không có vấn đề nào; thoát 1 khi đã chạy mà không đạt.
- **Đỏ → xanh:** `tests/test_v23_owner_wrapper.py` (22 test, gói giả). Ca của Codex: bản sao nguyên văn script dev5 in `DAT`, thoát 0; script mới từ chối, thoát 2. Chạy thật trên gói dev5 (chỉ đọc): đạt 12/12 và 23/23 (phiên AI nên bước duyệt là `fixture`); chạy lại cùng thư mục: từ chối, thoát 2.
- **Giữ nguyên:** lần thử hợp lệ của chủ sở hữu (`D:\OneCrewRuns\v23 thu cua anh dev5 20261029-155825`) và script dev5 (bằng chứng của lỗi) không bị sửa.

### 2.2 P2-B — hai project dùng chung một khóa tri thức

- **Nguyên nhân:** `knowledge.ledger_id` đặt id `ctx-<key>` không kèm project. Hai project cùng state root ghi bản general với cùng `--key` thì thành một chủ thể: bản mới che bản cũ, project này thu hồi bản của mình làm bản của project kia biến mất, project kia không thu hồi được bản của chính mình (`installed-collision.json`).
- **Sửa (`ebcfa20`, rồi `926bdcf`, `4516cc5` sau review):**
  - Chủ thể thuộc project đã ghi nó. Bản của chính project giữ nguyên id, nên dữ liệu một project đọc như trước. Bản general của project khác là `ctx-<key>@<12 ký tự>`; 12 ký tự là dấu lấy từ task đầu tiên của project đó trong sổ (ngẫu nhiên), không suy ra được đường dẫn. Khóa không chứa được `@`, nên không giả được id của project khác.
  - Đích thu hồi/lưu trữ và các tham chiếu (`supersedes`, `derived_from`, `conflict_with`, `contradicts`) đọc theo không gian tên của project đã ghi. Chỉ project chủ thu hồi được; id `…@<dấu của mình>` được hiểu là bản của mình; id không trỏ bản ghi, lesson hay mục wiki nào thì bị từ chối.
  - Tham chiếu ghi trước bản sửa (format ≤ 2) giữ nghĩa lúc ghi: chủ thể mới nhất mang khóa đó mà project nhìn thấy khi ghi. Lần từ chối của worker từ gói niêm phong trước khi nâng cấp được ánh xạ qua sự kiện gốc. Trang wiki không có thời điểm: id trơn đọc theo project, và mọi id trơn mà bản general của project khác cũng khớp đều được báo (`wiki pages` và gói) kèm id cần viết.
  - Trong một project, một khóa là một chủ thể: ghi khóa đó ở scope kia bị từ chối. Dữ liệu cũ có cả hai scope: project khác vẫn nhận bản general đã công bố (không thấy gì về bản không chia sẻ), chủ sở hữu thấy bản đó ở `published` trong `wiki history`; thu hồi ghi một bản ghi của project và một bản ghi chung trung tính, có hiệu lực với mọi project. `ctx-<key>@<dấu của chính project>` chỉ rõ bản của mình.
  - Khóa bắt đầu bằng `lesson-` dành cho lesson: bản ghi mới không lấy được; bản ghi 2.3 cũ mang khóa đó theo quy tắc project.
- **Đỏ → xanh:** r02b, r02c, r02d (`tests/test_v23_review_dev4.py`) là expected failure trên dev5, nay là test thường và đạt; `tests/test_v23_codex_review_dev5.py` (10), `tests/test_v23_review_dev6.py` (17), `tests/test_v23_review_dev6_delta.py` (10). Qua CLI của wheel đã cài, cùng kịch bản: wheel dev5 có 14 lỗi, wheel sửa không lỗi (§5).
- **Dữ liệu cũ:** sổ do wheel dev5 ghi (hai project trùng khóa, thu hồi, `--supersedes` kiểu cũ), đọc bằng wheel mới: bản của A hiện lại, bản B đã thu hồi vẫn thu hồi, `--supersedes` cũ giữ nghĩa, A thu hồi được bản của mình (dev5 từ chối); wheel 2.2 vẫn đọc được sổ đó (§5).

### 2.3 P2-C và P2-D — verifier tài liệu

- **Nguyên nhân:** `Port.files()` dừng cả lượt kiểm khi checkout có tên bị cấm đọc (`.env.example`…), báo sai là "ngoài checkout" (P2-C); với mẫu trích dẫn, `[S1][S2]` bị đọc thành reference link `[s2]` chưa định nghĩa (P2-D).
- **Sửa:**
  - Tiếp nhận có chọn lọc bản sửa beta R15 (`e432be2`): đúng ba file `onecrew/snapshots.py`, `onecrew/v2/verifiers/port.py`, `onecrew/v2/verifiers/doc.py` (nhánh 2.3 chưa đổi chúng; sau khi nhận giống từng dòng `e432be2`) và các test B5/B3 đi kèm (`b32ae19`). Các sửa khác của R15 (B1, B2, B4, B6: hook, plan lint) không thuộc lỗi này, không nhận.
  - Review độc lập tìm thêm bốn điểm trong vùng này, sửa ở `a87389f`: mẫu trích dẫn có neo (`^S\d+$`) che `[S1][S9]` chưa định nghĩa; `[S1][ S9 ]` không bị báo; file bị cấm đọc được qua tên ngắn 8.3 (`ENV~1.EXA`, có từ trước); link/junction mang tên bị cấm không còn dừng lượt chạy. Nay một định nghĩa trích dẫn dùng chung cho kiểm nguồn và kiểm link; tên ngắn bị chặn sau khi phân giải; link mang tên bị cấm vẫn là vi phạm phạm vi.
- **Đỏ → xanh:** `tests/test_v23_r15_port.py` (22 test: 9 fail + 7 lỗi trên dev5, đạt), `tests/test_v23_review_dev6_port.py` (20 test: 15 đỏ, đạt). Qua wheel đã cài: wheel dev5 có 4 lỗi, wheel sửa không lỗi (§5).

### 2.4 Review độc lập

Review theo rủi ro (chỉ thị 29/10): phần định danh/quyền/vòng đời tri thức và logic chấm đạt của script thử được review độc lập; phần tiếp nhận nguyên văn từ R15 được kiểm bằng test của R15 và review chung.
- Vòng 1 (agent Opus, trên `ebcfa20` và `b32ae19`): 15 điểm (1 P1, 9 P2, 5 P3), 7 do bản sửa, 8 có từ trước — sửa ở `926bdcf` và `a87389f`.
- Vòng 2 (cùng agent, trên `926bdcf`): 8 điểm mới (2 P2, 6 P3), phần lớn do cách sửa R7 — sửa ở `4516cc5`.
- Vòng 3 (cùng agent, trên `4516cc5` và `a87389f`): không còn điểm P1/P2; 4 điểm P3 (E1–E4). E1–E3 sửa ở commit sau `4516cc5`: dạng id kèm dấu của chính project, D6 theo phương án thứ hai của review (chủ sở hữu thấy bản đã công bố; project khác không thấy gì về bản không chia sẻ, không đọc thêm); E4 (hard link, có từ trước) ghi ở §3. 708 test của reviewer trên `4516cc5` đạt, trừ 2 lỗi môi trường (không có Codex CLI; một test cần TEMP trên C:). Lượt soát ngắn trên `3cfe327`: không có P1/P2; `published` chỉ hiện trong `wiki history` của chủ sở hữu (không vào gói, không sang project khác); một điểm P3 hiển thị (F1: `published` còn hiện bản đã thu hồi) sửa trong snapshot.
- Báo cáo và probe: `D:\OneCrewRuns\v23\review-dev6\review-p2b.md`. Các probe được giữ thành test; probe nào đổi kỳ vọng theo thiết kế đã chọn thì docstring của test nói lý do.

## 3. Còn mở, ngoài bốn lỗi

- Một attempt đã gửi trước khi nâng cấp mà xin thêm (requests) một bản general của project khác bằng id cũ: lần tiếp theo có thể nhận bản cùng khóa của chính project.
- Mục general ghi bằng `context add` kiểu 2.2 với khóa `lesson-…` vẫn được đọc như lesson.
- Kiểm `ids.pattern` của verifier tài liệu có cùng điểm yếu với mẫu neo (ngoài R9–R14, không đổi).
- `validate_config` của adapter data/ops vẫn nhận tên ngắn 8.3 lúc đề xuất (không có checkout để phân giải); lúc chạy bị từ chối khi đọc.
- `wiki history` hiện mã project đầy đủ của bản ghi project khác (có từ trước; không có trong gói giao cho worker).
- File bị cấm đọc đọc được qua hard link trong checkout (E4, có từ trước); checkout Git và snapshot không tạo hard link.
- Các khoảng trống nghiệm thu, pilot và provider của 2.2 (Partial/Blocked) giữ nguyên.

## 4. Lần thử dev5 của chủ sở hữu (giữ nguyên làm bằng chứng)

- 29/10 15:58–16:02, từ terminal của chủ sở hữu: kiểm gói 12/12; task đầu tiên 21 bước bắt buộc đạt, cộng 2 bước chỉ ghi thông tin.
- `owner_step_mode=real` chỉ chứng minh lệnh `onecrew owner approve` chạy thật trên **sổ của bài diễn tập**; worker vẫn là `claude` giả.
- Lượt chạy trong phiên AI có 23 bước bắt buộc vì bước duyệt được thay bằng ba bước kiểm/fixture.
- Không lượt nào là provider thật, nghiệm thu, hay duyệt trên sổ thật.

## 5. Gói, kiểm từ artifact, gate

<!-- dev6:section5 -->
_Ghi sau khi kiểm gói (bản trong checkout)._

## 6. Cách cài, thử và quay về

Theo `README.md` của gói:
1. một lệnh làm cả kiểm hash, bộ kiểm 14 bước và task đầu tiên trên thư mục mới, sổ tạm: `powershell -ExecutionPolicy Bypass -File "<gói>\verify\thu-goi.ps1"` (đạt khi in `DAT:` và thoát 0);
2. hoặc làm từng bước: kiểm hash wheel; chạy `verify\verify_milestone.py`; tạo venv thử mới và `pip install --no-index` wheel;
3. task đầu tiên: phần A với `claude` giả; phần B với Claude Code CLI thật đã đăng nhập subscription (bước duyệt plan do chủ sở hữu chạy trong terminal của mình).

Quay về 2.2: wheel `wheel\previous\`, giống từng byte gói beta.

## 7. Bảo toàn beta và cách ly

- **Trước khi làm (29/10 17:05):** gói `D:\OneCrewRuns\wf-handover-34eb7c4-hs2` 687/687 dòng `SHA256SUMS` khớp, 0 file sửa sau 28/10 13:30; `hook-projects.json` thật SHA256 `884335df…` (sửa lần cuối 28/10 16:29); checkout `wf-codex` ở `1753f77` (phiên khác), không có thay đổi chưa commit.

<!-- dev6:beta-after -->
_Ghi sau khi kiểm gói (bản trong checkout)._

- **Cách ly:** worktree riêng (`wf-v23`, `wf-v23-p2a`, `wf-v23-verifier`, `wf-v23-review6`), venv mới ngoài checkout, `TEMP`/`LOCALAPPDATA`/`APPDATA` riêng cho process thử, sổ tạm, không gọi provider thật, không đổi PATH, registry, provider config, hook, cấu hình Claude dùng chung.

## 8. Còn Blocked và quyết định

<!-- dev6:blocked -->
_Ghi sau khi kiểm gói (bản trong checkout)._
