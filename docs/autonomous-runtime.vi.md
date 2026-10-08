# Runtime tự vận hành local — SPEC-004

OneCrew đã có controller chạy một task local qua CLI: Conductor → policy chọn model → worker backend/frontend → gate HTTP độc lập → review → sửa có giới hạn → commit và bàn giao. Đây là lát kiểm chứng profile form CV, chưa phải executor tổng quát mọi repo/backend.

## Giao việc

```powershell
cd D:\TamNT\Workspace\9.VMAgent\onecrew
.\onecrew.ps1 task run --autonomous `
  --brief examples\cv-autonomous-brief.vi.md `
  --output D:\TamNT\Workspace\9.VMAgent\cv-autonomous-new `
  --max-seconds 1200 --max-calls 8 --max-repairs 2
```

Output phải là thư mục chưa tồn tại. `--autonomous` cấp quyền cho toàn bộ vòng kỹ thuật trong brief/profile và budget; không tự tạo approval spec hay nghiệm thu khách hàng. Quyền deploy, thêm nghiệp vụ, lấy secret hoặc tăng ngân sách không được suy từ cờ này. Lượt gọi trên là một execution grant mới; không dùng nó để lách budget của một task đang chạy.

```powershell
.\onecrew.ps1 task list
.\onecrew.ps1 task status RUN-YYYYMMDD-HHMMSS-xxxxxx
.\onecrew.ps1 task outputs RUN-YYYYMMDD-HHMMSS-xxxxxx
.\onecrew.ps1 task cancel RUN-YYYYMMDD-HHMMSS-xxxxxx
```

Các lệnh đọc/cancel không gọi AI. `cancel_requested` chỉ là yêu cầu; đợi `status=cancelled` để xác nhận controller đã dừng subprocess. Không có pause/resume/reorder trong lát này. Khi controller chết, status chiếu `interrupted`, không tự chạy lại hoặc báo đã dừng mọi tài nguyên; xem PID/resource record trước phục hồi.

## Model và giới hạn

| Việc | Policy local-v1 |
|---|---|
| Lập brief/plan có schema | gpt-6-luna, medium |
| Frontend thông thường | gpt-6.1-sol, medium |
| Backend, review, repair hoặc risk cao | gpt-6.1-sol, high |

Conductor đánh giá risk/dependency theo schema; code áp mức tối thiểu theo loại việc. Đây là routing theo công việc, chưa có benchmark chứng minh tối ưu chi phí, chưa gọi Jev. Requested model được ghi; không giả định CLI trả một model-resolved ID mà thực tế không có.

Deadline chung và số calls/repairs do controller giữ; đổi role/model không reset. Context tối đa 80.000 ký tự trước dispatch, artifact tối đa 400 KB. Mỗi model mặc định tối đa 240 giây; `--step-seconds` cho phép đặt trước run từ 1 tới 600 giây và không vượt deadline chung. Không gọi model cho counter/status/test. Usage cộng các sự kiện CLI báo; thiếu usage hoặc in-flight được ghi riêng, không suy từ zero thành miễn phí. USD unknown; timeout không bảo đảm provider ngừng tính phí ngay.

Model chỉ nhận snapshot và trả JSON file; shell/apps/plugins/hooks/multi-agent bị tắt, Codex chạy read-only. Host kiểm schema, ownership, path và kích thước rồi mới ghi file. Worker không được trả package/gate/policy/state; không trực tiếp commit hoặc dispatch.

## Gate, sửa và bàn giao

Host giữ API contract/profile và gate ngoài workspace của sản phẩm, ghim hash từ đầu run. Sau mỗi phần lưu ZIP và manifest bất biến. Gate HTTP chạy server thật, kiểm session/origin/challenge/permit, replay đồng thời, payload, file/rate limit, chế độ locked và source/data không được public.

Gate đỏ được gửi nguyên lỗi tới repair worker. Gate xanh mới gọi semantic reviewer. Chỉ finding blocking gắn AC hợp lệ và evidence mới chặn; yêu cầu ngoài scope được ghi backlog. Cùng lỗi và cùng artifact không tiến triển hoặc hết budget thì dừng, không thay AC/test. Mỗi sửa làm evidence cũ stale; trước/sau review và delivery đều kiểm manifest.

Chỉ khi gate và review cùng đạt, host mới git-init/stage các file sản phẩm đã cho phép/commit, tạo `delivery.json`. Trạng thái `ready_for_review` tách với `verification=passed` và `acceptance=pending_user_review`. Không deploy và không tự mở web server lâu dài sau gate. Cách chạy nằm trong README do worker tạo.

## Sandbox và giới hạn thực

Windows dùng `codex sandbox -P :workspace`: OS chặn ghi ngoài workspace. Node permission flags bổ sung giới hạn đọc/ghi và cấm child process. Preflight dùng sentinel ngoài workspace kiểm quyền và xác minh sentinel không bị thay đổi; không chạy nếu probe không đạt. Env của server bỏ các biến có tên token/secret/password/API-key phổ biến; đây không phải một bộ phát hiện bí mật hoàn chỉnh.

Native adapter không phải môi trường cho mã cố ý độc hại: Node mô tả permission model là lớp chống thao tác ngoài ý muốn, không là ranh giới bảo mật chống malicious code; Windows sandbox cần baseline đọc root. Không đưa dữ liệu/secret vận hành thật vào phép thử này. Tham khảo [Node permissions](https://nodejs.org/api/permissions.html) và [Codex permissions](https://learn.chatgpt.com/docs/permissions).

Docker adapter dùng image Node chính thức, pin image ID, non-root, read-only root/source, tmpfs data, cap-drop, không mount socket hoặc secrets và internal network. Chưa có live Docker verification trên máy này vì Engine không kết nối được; không tự đổi cấu hình/reset Docker.

Các giới hạn chưa giải quyết: recovery tự động sau crash, ngân sách gom nhiều run do người mở riêng, nhiều repo/backends, quyền control đa người dùng, Docker live test, benchmark router, live Turnstile/AV/edge và agent-bot efficacy. Không được gọi toàn bộ roadmap là đã hoạt động 100%.

## Kết quả kiểm chứng hiện tại

Controller đã qua 51 test. Lượt live chưa tạo được sản phẩm: Conductor chạy được, nhưng backend không trả artifact trước timeout 240/600 giây; một lượt khác gặp lỗi khóa file Windows đã được sửa và thêm regression test. Không có app mới được bàn giao, không có live gate/review thành công. Xem [bằng chứng và usage còn thiếu](autonomous-coverage.md). Các checkpoint/delivery mô tả ở trên là hành vi đã kiểm bằng fixture, không phải tuyên bố lượt live đã đạt.
