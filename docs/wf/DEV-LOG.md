# DEV-LOG — development chương trình workflow chung

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

## Hàng đợi tích hợp

(trống)

## Checkpoint

- 24/10 ~09:40: `wf/dev@c3ad00a` = R00. FEATURE-SCOPE sinh từ 04 (hash 04 c1d8f8ae40cd).
