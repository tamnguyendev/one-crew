# OneCrew v2 và v1 — cái gì thêm, cái gì còn nguyên

Quyết định của chủ sở hữu, 19/10/2026: bắt đầu v2 nhưng **giữ toàn bộ mã v1**; v2 là một option tách riêng. Lát L1 của v2 nằm trong gói con `onecrew/v2/`.

## v2 thêm gì (L1)
- Một chức năng: **hợp đồng công việc cho AI** — kế hoạch có mốc, chủ sở hữu duyệt, mỗi mốc có verdict kèm biên nhận, chủ sở hữu nghiệm thu.
- Verb mới `onecrew plan propose|show|approve|accept|amend|enforce` và `onecrew verdict record|run`. Hợp đồng lưu bất biến ở `<state-root>/plans/<tên>/v<N>.json` (băm nội dung); trạng thái chỉ là sự kiện sổ cái trên task neo `plan:<tên>`.
- Tên plan = request key của job sẽ thực hiện (`job submit --key <tên>`); cổng tra theo khóa đó.
- Sáu bất biến đã khóa trong mã ở mức L1: không plan được duyệt thì không dispatch; mốc không verdict thì không qua; hết `max_repairs` thì dừng và hỏi chủ sở hữu một câu; duyệt và nghiệm thu chỉ do `--by owner` (shell khai `ONECREW_ACTOR` là AI bị từ chối). Phạm vi (hook), reviewer độc lập: chưa có (L2, L4).
- Cổng dispatch **mặc định TẮT**. Bật: `plan enforce on --by owner --reference ...` (hoặc `ONECREW_V2_REQUIRE_PLAN=1`). Khi bật, mọi đường dispatch đã đi qua `solution_gate.check` đều đòi plan đã duyệt, kể cả `--mode work` (trước đây lách được SOL).

## v1 còn nguyên ở đâu
- Mã v1 là phần còn lại của `onecrew/` (≈120 module), không đổi hành vi. Chỉ sửa hai chỗ nhỏ: `solution_gate.check` (một lời gọi `require_plan`, vô hiệu khi cổng tắt) và router `cli.py` (verb `plan`, `verdict`).
- Nhánh: `feat/qc-intake-mvp1` (@6aac8ea, v1 + QC MVP-1, điểm xuất phát của v2), `claude/delivery-runtime-recovery`.

## Chạy chỉ v1
Không dùng verb `plan`/`verdict` và không bật `plan enforce`; mọi lệnh cũ (`job`, `delivery`, `qc`, `work`, ...) chạy như trước. Một state-root chưa bao giờ chạy `plan enforce on` không có cổng v2 (`plans/policy.json` không tồn tại).

## Quay lại v1
- Tắt cổng: `plan enforce off --by owner --reference ...` (các plan, sự kiện còn trong sổ cái, không ảnh hưởng v1).
- Bỏ hẳn v2: checkout `feat/qc-intake-mvp1` (hoặc revert hai chỗ sửa trên và xóa `onecrew/v2/`, `tests/test_v2_l1.py`). Task neo `plan:*` là job audit chưa bao giờ chạy; chúng chỉ hiện trong danh sách task.

## Chưa kiểm soát (nói thẳng)
Cưỡng bức chỉ trong tiến trình OneCrew. AI có shell vẫn có thể gõ `--by owner` hoặc sửa file trong state-root; hook và permission deny rules là việc của L2. Xem `docs/v2-parking-lot.vi.md`.
