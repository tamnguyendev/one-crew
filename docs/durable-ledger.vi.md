# P1a — task và inbox lưu bền

Đã có CLI ghi nhận task từ spec, xem lại mục tiêu, lưu câu hỏi, sửa revision câu hỏi và trả lời. Đóng terminal rồi mở lại vẫn dùng cùng ID. Lát này chưa chạy worker, chưa tự lập plan hoặc áp dụng hành động từ câu trả lời.

Ledger dùng SQLite schema v1 tại `%LOCALAPPDATA%/OneCrew/ledger.sqlite3` trên Windows, hoặc `~/.onecrew/ledger.sqlite3` khi không có LOCALAPPDATA. Một DB chứa nhiều project, query/mutation lọc theo hash đường dẫn project đã resolve. `--state-root <directory>` trước nhóm lệnh cho môi trường thử riêng; bắt buộc ngoài project. Các entry dùng cùng project path và state root để thấy cùng công việc. Đổi vị trí source chưa có migration identity tự động.

## Dùng thử từ thư mục OneCrew

Ví dụ tạo một bản ghi thử theo SPEC-006; câu hỏi retention là dữ liệu demo để thử inbox, không là scope bổ sung của SPEC-006. Grant ví dụ không có quyền thực thi. Các lệnh sau không gọi model hoặc sửa spec approval.

```powershell
$review = .\onecrew.ps1 spec review SPEC-006 --json | ConvertFrom-Json
$task = .\onecrew.ps1 task submit --spec SPEC-006 --revision $review.revision --request-id ledger-demo-01 --grant examples/ledger-grant.json --json | ConvertFrom-Json
.\onecrew.ps1 task queue
.\onecrew.ps1 task status $task.id
.\onecrew.ps1 task connect $task.id

$request = .\onecrew.ps1 request create --task $task.id --request-id retention-demo-01 --file examples/ledger-question.json --json | ConvertFrom-Json
.\onecrew.ps1 request list --task $task.id --pending
.\onecrew.ps1 request show $request.id
.\onecrew.ps1 request reply $request.id --revision $request.revision --choice seven --source terminal --reference "Tôi chọn 7 ngày trong bản demo"
.\onecrew.ps1 task events $task.id --after 0 --json
```

Mọi command mới có `--json` và `--help`. Để đọc từ thư mục/công cụ khác, thêm `--project <đường-dẫn-source>` trước `task` hoặc `request`. `task connect` là đọc snapshot và inbox, không mở session hoặc khởi động worker. Không có model call cho submit/queue/status/connect/inbox/events.

`task queue` liệt kê task ledger với ID `TASK-...`; `task list` giữ nguyên lịch sử runtime CV với ID `RUN-...`. `task status` chọn đúng kho theo loại ID. `run/cancel/outputs/preview` hiện chỉ phục vụ runtime CV, không chạy hay hủy task ledger.

## Chống trùng và revision

- Giữ `--request-id` khi retry submit/create sau mất kết nối. Cùng key và nội dung trả record cũ; cùng key nhưng nội dung khác bị từ chối. Deadline không được cấp lại khi retry.
- Submit dùng full revision 64 ký tự của spec đã xem. Spec thay trước submit mới thì revision cũ bị từ chối. Task đã ack giữ snapshot riêng; retry đúng submission cũ vẫn trả task đó kể cả file spec bị đổi/xóa. Không cập nhật task ngầm theo file ngoài.
- Cần thay câu hỏi đang pending: sửa JSON, dùng `request revise <id> --revision <revision-vừa-xem> --file <file>`. Toàn bộ nội dung/action và task revision được bind vào revision mới; reply revision cũ bị từ chối. Lịch sử phiên bản nằm trong `task events`.
- Câu hỏi đã answered không sửa tại chỗ; tạo request mới với key mới. Reply trùng cùng choice/revision trả receipt ban đầu; reply khác bị conflict. Hai process trả lời trái nhau chỉ một bên commit.
- Có nhiều câu hỏi thì task vẫn waiting tới khi hết pending. Trả lời không đổi verification/acceptance, không áp dụng action và không cấp execution grant. Hết pending chỉ đưa trạng thái quan sát về queued.

## Format dữ liệu và ranh giới của P1a

Grant intent gồm đúng `schema_version: 1`, `permissions` (list tên action, có thể rỗng), `limits` (`max_calls` 1–10000, `max_seconds` 1–28800) và `source` (nguồn yêu cầu). Các số là đề nghị lưu trong task, không nâng giới hạn runtime CV hiện tại. Deadline tuyệt đối tính từ submit, bao gồm thời gian chờ. Hiển thị expired nhưng P1a không dispatch nên chưa có bộ cưỡng chế deadline/budget cho worker.

Question gồm đúng các field trong [ví dụ](../examples/ledger-question.json), 2–8 lựa chọn ID duy nhất và recommendation phải thuộc các ID đó. JSON input tối đa 64 KiB, không nhận key lặp hoặc NaN/Infinity; số nguyên không nhận boolean/chuỗi. API request/action ở đây chỉ ghi dữ liệu, không thực thi `action.type`.

Reply ghi login local cùng source/reference khai báo; `trust=local_attribution_only`, `action_applied=false`, task luôn `dispatch_enabled=false`, `grant_status=unverified_local`. Đây chưa là xác thực người dùng xuyên Claude/Kiro/Codex hoặc isolation với process cùng OS user. Worker adapters tương lai không được dùng những record này như execution grant đã được duyệt.

Đặt state ngoài source giảm nguy cơ sửa nhầm/commit nhầm, không tự tạo security boundary. Không đưa secrets, dữ liệu CV thật hoặc toàn bộ private chat vào spec/grant/question. Spec snapshot và thông tin đã giao nằm trong DB. Người có quyền đọc state có thể đọc dữ liệu đó.

## Persistence và lỗi

Mutation dùng transaction SQLite `BEGIN IMMEDIATE`, synchronous FULL; task/request/reply và event commit cùng nhau. Đọc dùng `mode=ro`, không khởi tạo DB hoặc gọi model. Trạng thái chưa có trả list rỗng; task/request không thuộc project hiện tại bị từ chối. Schema/app ID lạ không tự migrate hoặc ghi đè. Đây là phiên bản schema đầu tiên; upgrade/backup orchestration ở lát sau.

Event có sequence và `--after`, tối đa 200 records/lần; dùng `next_cursor` đọc tiếp. Poll có thể đọc lặp, consumer tự giữ cursor. Chưa có push notification/outbox delivery service. DB là nguồn record, không dựng lại task từ event log.

CLI trả exit 0 sau thành công, exit 2 khi input/revision/conflict/storage lỗi; `--json` trả object `error` cho lỗi nghiệp vụ/storage. Lỗi cú pháp CLI do argparse trả usage và exit 2. Không tự retry câu trả lời khác hoặc ghi nhận thành công khi transaction thất bại. Khi process chết trước commit, transaction bị rollback; sau commit nhưng mất stdout, retry nhận record/receipt cũ.

## Bằng chứng và bước tiếp theo

`tests/test_ledger.py` kiểm restart bằng process CLI riêng, submit/reply đồng thời, rollback khi ghi event lỗi, process chết trước commit, lịch sử revision, spec snapshot sau file bị xóa, project isolation và schema mới hơn bị từ chối. Đây là kiểm chứng ledger local; chưa có worker để chứng minh kill cả supervisor/worker hoặc handoff đa provider.

P1b tiếp theo: admission/reservation/action receipts và supervisor qua adapter giả lập lỗi. P1c mới nối worker Codex và boundary/process recovery; P1d nối general planner. Xem [backlog](mvp-backlog.vi.md) và [coverage](proposal-coverage.md).
