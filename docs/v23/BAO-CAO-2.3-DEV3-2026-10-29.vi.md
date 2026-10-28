# OneCrew 2.3 — bàn giao 2.3.0.dev3 sau review Codex (A1 + A2 + B)

Người viết: Claude (Opus 5.5), đầu mối triển khai 2.3, đêm 28–29/10/2026, theo chỉ thị người dùng đêm 28/10 ("Tiếp tục làm OneCrew 2.3 đến sáng, ưu tiên sửa hết các finding Codex vừa review…"). Đây là **tự kiểm của tác giả cộng review độc lập bằng agent**, chưa phải Codex review lại, chưa nghiệm thu. Roadmap chung không bị sửa; 2.3 không cộng vào 92 task beta; không push/tag/publish. Báo cáo trước (gói `2.3.0.dev2`, mốc Codex review): [BAO-CAO-2.3-2026-10-28](BAO-CAO-2.3-2026-10-28.vi.md).

**Bản nào:** bản trong `docs/` của gói là bản lúc dựng gói. Kết quả kiểm gói từ artifact, diễn tập và gate (§5) chỉ có ở bản trong checkout, commit sau khi kiểm: gói không tự chứng nhận chính nó.

| | |
|---|---|
| Code | `6a8421d` (nhánh local `claude/onecrew-2.3`, worktree `D:\TamNT\Workspace\11.OneCrew\wf-v23`); mốc Codex review `38981bd` |
| Version | `2.3.0.dev3` (gói `2.3.0.dev2` giữ nguyên, không ghi đè) |
| Gói thử | xem §5 (đường dẫn, wheel SHA256, kết quả) |

## 1. Đã sẵn sàng test chưa, trong phạm vi nào

Xem §5 (điền sau khi kiểm gói). Phạm vi test: A1 (đọc wiki, chọn/giao context có quyền, khả năng áp dụng, trần, đọc tiếp), A2 (ghi có bằng chứng, vòng đời, dùng lại qua root mới/process mới), B (dọn, sở hữu, tiếp quản an toàn) trên project bản sao và state root riêng; provider giả cho diễn tập, Claude Code CLI thật (subscription) cho phần B của task đầu tiên.

## 2. Ba finding Codex đã khép thế nào

Truy vết đầy đủ: [HOP-DONG-2.3](HOP-DONG-2.3.vi.md) §7.

| Finding | Đã sửa thế nào | Đỏ trước | Xanh sau |
|---|---|---|---|
| **P2-01** gói tiếp tục (`onecrew continue`) đưa tri thức cũ ra như đã xác minh | Gói tiếp tục, `context retrieve` và `wiki history` dùng **cùng một quyết định** với gói tri thức (`knowledge.for_root` trên cùng `_collect`/`_decide`): mục bị thu hồi/lưu trữ/thay thế (kể cả ghi chú riêng bị ghi chú mới thay) không hiện; mục có file ghim hoặc nguồn đã đổi, không còn áp dụng, root khác đã ghi bản mới hơn, hay (bản ghi 2.3) không kiểm được → `stale` có lý do; `wiki history` ghi `superseded`. Mục 2.2 giữ quy tắc 2.2. Lịch sử giữ nguyên. | `tests/test_v23_codex_review` trên `38981bd`: 3/4 ca P2-01 fail (log `D:\OneCrewRuns\v23\logs\codex-red-38981bd.txt`) | 4/4; V11 từ gói (§5) |
| **P2-02** giới hạn 2 000 trang làm mất ràng buộc `must` | Mọi trang được dò tìm mục bắt buộc/thay thế; mục bắt buộc sau giới hạn vẫn được giao. Mục bắt buộc không giao được (trang > 2 MB, không phải UTF-8/UTF-16, metadata sai, id trùng khác nội dung, ngoài mục, dẫn xuất từ mục không đọc được), wiki > 256 MB, sổ không đọc được khi có bản ghi bắt buộc, hay lớp chọn lỗi bất ngờ khi project có tri thức bắt buộc → node **bị giữ trước khi gọi model** với lý do nêu trang/dòng. Lỗi làm không biết nội dung (thư mục cấu hình mất, config hỏng, trang không đọc được) → báo `wiki.complete: false` + dòng lỗi, không chặn task độc lập. Ràng buộc đọc được nhưng vượt trần → giữ node như trước. | 6/8 ca P2-02 fail trên `38981bd` (2 đối chứng đạt) | 8/8; V10 từ gói (§5) |
| **P2-03** task đầu tiên chưa tự chạy được từ gói | `examples/first-task/`: `contract.json`, `nodes.json`, `fake-policy.json`, README với khối lệnh PowerShell cụ thể, đường dẫn nằm trong gói; phần A diễn tập với `claude` giả, phần B dùng Claude Code CLI thật; `verify/first_task_drill.py` chạy đúng các khối lệnh của README từ gói. | README cũ từ gói dev2: đường dẫn `../../tools/scenario_a1.py`, `../../HUONG-DAN-WIKI.vi.md` không tồn tại, 0 file JSON mẫu, 0 khối lệnh (`D:\OneCrewRuns\v23\p2-03\red\`) | diễn tập 23/23 trên gói thử của agent (`D:\OneCrewRuns\v23\p2-03\drill run 2`); trên gói cuối: §5 |

**Review độc lập bản sửa** (agent Opus 5.5, probe ghi thành test, chạy đối chứng trên bản trước): r1 trên `581fbca` 18 điểm (11 P2, 7 P3; 6 do bản sửa gây ra) → `989eb9c`; r2 10 điểm (3 P2, 7 P3; 4 do r1 gây ra) → `522a6c9`; r3 3 P3 (do r2 gây ra), 0 P1/P2 → `6a8421d`. Không vòng nào có P1. Probe: `tests/test_v23_review_codex_r1.py` (25), `_r2.py` (14), `_r3.py` (4), tất cả đạt trên `6a8421d`. Báo cáo: `D:\OneCrewRuns\v23\review-codex-r1.md`, `-r2.md`, `-r3.md`.

## 3. A1/A2/B còn requirement nào chưa đạt

Bảng trạng thái từng requirement của bản dev2 ([BAO-CAO-2.3-2026-10-28](BAO-CAO-2.3-2026-10-28.vi.md) §2) vẫn đúng, với các điểm đổi sau review Codex:

- **A1-R3** (không bỏ ràng buộc âm thầm): trước đây sai ở giới hạn trang (P2-02) — nay đạt, có thêm các ca trang hỏng/mã hóa/dẫn xuất.
- **A1-R4, A2-R5, A2-R6, A2-R8** (áp dụng hiện tại, thu hồi, vòng đời, quyền) trên đường **tiếp tục**: trước đây sai (P2-01) — nay đạt.
- **A1-R9** (đo chi phí khi kho tăng): hợp đồng yêu cầu 1k/10k/50k mục; bản dev2 mới đo tới 22k — nay đo thêm 10k, 50k và chuỗi số trang wiki (§5).
- **A1-R10, PK-R1** (gói tự chạy được, task đầu tiên): trước đây chưa đủ (P2-03) — nay có mẫu và diễn tập từ gói.
- **B-R1…R7**: không đổi so với dev2 (hồi quy lại trên code cuối, §5).
- Requirement chưa đạt: xem §5 sau khi kiểm (điền theo kết quả thật).

## 4. Tái dùng và code mới đợt này

- Không thêm kho/ledger/engine nào: sửa trên `onecrew/v2/wiki.py`, `knowledge.py`, `context.py`, `evidence_cli.py`; gói tiếp tục (`resume_pack`) dùng lại bộ chọn A1/A2. Không đổi schema, không thêm kind sự kiện.
- Test mới: `tests/test_v23_codex_review.py` (12), `_review_codex_r1/r2/r3.py` (43). Công cụ gói: `docs/v23/tools/scenario_codex.py` (V10, V11), `first_task_drill.py`, `make_fake_claude_wheel.py`; `measure_scale.py` thêm 10k/50k và chuỗi số trang.

## 5. Gói, kiểm từ artifact, gate

(điền sau khi dựng và kiểm gói — bản trong checkout)

## 6. Cách cài và chạy task đầu tiên

Theo `README.md` của gói và `examples/first-task/README.vi.md`: kiểm hash wheel, chạy bộ kiểm 11 bước, tạo venv thử mới (đường dẫn tùy ý), `pip install --no-index` wheel, làm task đầu tiên phần A (claude giả) rồi phần B (Claude Code CLI thật đã đăng nhập subscription; bước duyệt plan `onecrew owner approve` do chủ sở hữu chạy trong terminal của mình). Quay về 2.2: wheel `wheel/previous/` (giống từng byte gói beta).

## 7. Bảo toàn beta và cách ly

(điền sau khi kiểm — bản trong checkout)

## 8. Quyết định cần chủ sở hữu

(điền sau khi kiểm — bản trong checkout)
