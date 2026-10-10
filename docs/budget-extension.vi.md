# Gia hạn công việc có kiểm soát

Root giữ tổng số managed CLI invocations đã dùng và deadline tuyệt đối qua retry, restart, đổi worker hoặc chia nhánh. `work extend` là lệnh local operator riêng để cấp **trần tổng mới**, không phải xóa bộ đếm hoặc cấp unlimited.

```powershell
.\onecrew.ps1 --project D:\MyProject work status TASK-... --json
# Đọc control.budget.revision và số calls đã dùng trước khi chọn trần mới.
.\onecrew.ps1 --project D:\MyProject work extend TASK-... --revision <budget-revision> --request-id extension-1 --max-calls 12 --deadline "2026-10-09T18:00:00+07:00" --reason "Hoàn thiện AC còn lại trong phạm vi đã giao"
.\onecrew.ps1 --project D:\MyProject work resume TASK-...
.\onecrew.ps1 --project D:\MyProject work start TASK-...
```

Timestamp trên chỉ minh họa, cần chọn deadline tương lai của task thật. Deadline mới không quá **tám giờ kể từ submit gốc**, gồm tất cả thời gian chờ; max_calls tối đa 10.000. Không giảm trần cũ, không đổi scope/provider/repair cap và không tự resume. Task đã cancel/completed/failed không được gia hạn. Attempts phải đã dừng/reconcile; pending question phải được giải quyết trước khi thay revision của budget.

Gia hạn là event có revision và receipt trong SQLite; original task/grant vẫn bất biến. Cùng request-id và proposal trả receipt cũ; khác proposal hoặc revision cũ bị chặn. Số đã dùng, reserved/unknown và lịch sử không mất. Status hiển thị budget hiệu lực; task handoff vẫn chứa grant gốc để audit. Câu trả lời triage cũ không cấp quyền tiếp tục trên revision budget mới.

Đây là thẩm quyền tài khoản OS local, chưa phải xác thực approval đa ứng dụng. Worker artifact không có control tool. Không có tự gia hạn, tự mua token/API hoặc cam kết hoàn thành mọi chức năng trong tám giờ. Trần managed invocation không giới hạn cứng mọi request nội bộ của từng CLI provider.

Tests kiểm exhaustion→extension→restart→dispatch, deadline cũ/mới, giới hạn tuyệt đối, dữ liệu kiểu sai, unknown attempt, rollback, cạnh tranh revision và stale inbox reply. Giả lập thời gian không thay cho soak tám giờ thực.

## Chạy lại sau khi hết hạn qua ngày (CR04, 10/10/2026)

Mặc định vẫn giữ trần tám giờ từ submit. Khi người dùng trực tiếp yêu cầu thử lại task đã hết hạn, entry có thể thêm `--restart-expired` vào `work extend`: deadline mới tối đa tám giờ từ lần cấp lại này, không mặc định cấp đủ tám giờ. Lần Cloud Auth chỉ cấp 30 phút. Worker và heartbeat không được tự gọi tùy chọn này.

Tùy chọn đòi deadline cũ đã hết, không có shared goal budget, không có attempt chưa reconcile hoặc câu hỏi pending; không áp dụng cho terminal/cancelled task. Cumulative used/reserved, trần calls cũ, scope, grant gốc và checkpoint giữ nguyên. Receipt ghi authorized_at, previous_deadline và seconds; request-id/revision vẫn chống lặp và xung đột. Không tự resume. `max_seconds` trong budget hiệu lực vẫn là khoảng lịch từ submit đến deadline mới (có thể vượt tám giờ vì thời gian đã chờ); restart_window.seconds là cửa sổ mới được cấp. Đây là ngoại lệ có thẩm quyền cho retry qua ngày, không phải tự gia hạn khi restart process.
