# Cửa sổ kết quả OneCrew trên Windows

Yêu cầu người dùng 10/10/2026: báo một lần khi hoàn tất hoặc cần xử lý; bỏ lịch nhắc chat liên tục. Người dùng chọn **cửa sổ OneCrew trên Windows**. Đây là kênh cục bộ theo sự kiện, không phải callback vào Codex chat và không gọi model.

## Hành vi

- Owned và legacy workflow gọi delivery sau khi commit checkpoint. `completed`, `failed`, `cancelled`, `blocked`, `waiting`, `paused` hoặc câu hỏi pending tạo báo cáo và một cửa sổ. Checkpoint đang chạy bình thường không mở cửa sổ.
- Cùng task/cùng đợt trạng thái chỉ mở một lần dù checkpoint, runner-finally hoặc entry gọi lại. Câu hỏi có ID/revision được gộp với trạng thái chờ/bị chặn. Sau resume, kết quả mới được thông báo riêng. Chỉ dùng checkpoint mới nhất, không phát lại lỗi đã phục hồi.
- Cửa sổ có Task ID, trạng thái, lỗi/câu hỏi/options/revision, báo cáo worker nếu có, bằng chứng test/verification/review/apply/bàn giao, assistance và số timeout checkpoints. Nội dung là plain text đã lọc secret; không có nút approve/resume hay thực thi lệnh từ báo cáo.
- Tiêu đề theo mức hoàn thành (12/10/2026): `Hoàn thành trọn luồng` chỉ khi root delivery `completed`, verification `passed`, không AC/node nào `not_run`/skipped và plan có cả build lẫn E2E; `Hoàn thành một phần (not_run: …)` khi còn mục chưa chạy hoặc chưa kiểm chứng; `Hoàn thành theo kế hoạch (không có: build, E2E)` khi plan thiếu các bước đó; `Hoàn thành job đơn lẻ (không phải trọn luồng)` cho job độc lập; `Bị chặn` khi blocked; `Cần anh trả lời` khi có câu hỏi pending. Kết quả một phần không bao giờ mang tiêu đề hoàn thành trọn luồng.
- Báo cáo của root delivery liệt kê bằng chứng chung theo node có receipt: `Artifact (...)`, `E2E (...)`, `Git (...)` và `Git baseline` khi có (chỉ các trường thật sự có; nhãn APK chỉ xuất hiện khi có bằng chứng APK). Với câu hỏi pending `REQ-…`, báo cáo in sẵn lệnh trả lời PowerShell cho từng lựa chọn, ghi nhận người dùng tự quyết: `$env:ONECREW_ACTOR='user'; & '<launcher>' --project '…' --state-root '…' request reply REQ-… --revision … --choice <id> --decided-by user`. Trả lời xong runtime tự chạy tiếp (`keeper.after_reply`), không cần `resume`.
- Đóng cửa sổ chỉ ghi `closed`, không trả lời câu hỏi. `shown` cần sự kiện Tk Map thực tế. Receipt không chứng minh người dùng đã đọc. Cửa sổ nổi trên cùng trong 2 giây đầu, sau đó hoạt động như cửa sổ bình thường, không tự nhắc lại.

## Cấu hình và sử dụng

Dùng cùng launcher và `--state-root` của task, đặt global options trước group:

```powershell
& .\onecrew.ps1 --project '<project>' --state-root '<state-root>' desktop enable
& .\onecrew.ps1 --project '<project>' --state-root '<state-root>' desktop status
& .\onecrew.ps1 --project '<project>' --state-root '<state-root>' desktop show --task TASK-ID
& .\onecrew.ps1 --project '<project>' --state-root '<state-root>' desktop retry --id <notification-id>
& .\onecrew.ps1 --project '<project>' --state-root '<state-root>' desktop disable
```

Enable một lần cho state-root; tự áp dụng cho các project/runner dùng cùng cài đặt. Lần enable đầu ghi mốc hiện tại để tránh bật hàng loạt kết quả cũ. `show --task` đưa kết quả hiện hành vào cùng cơ chế chống trùng. Enable lại giữ nguyên mốc và receipt; disable không xóa kết quả hoặc hủy task.

Từ 12/10/2026 hộp thư (config, cờ enable, tập chống trùng, báo cáo) nằm ở `<state-root>/desktop/`, nên runner do keeper khởi động, runner do lệnh reply khởi động hay runtime ở worktree khác đều dùng chung một cờ và một tập chống trùng. Vị trí cũ `<thư mục cài OneCrew>/.onecrew/desktop/<state-root-hash>/` (hoặc `ONECREW_DESKTOP_HOME/<state-root-hash>/`) chỉ còn được đọc một lần để di chuyển: lần đầu dùng mà `<state-root>/desktop/config.json` chưa có, OneCrew chép config và các receipt/báo cáo cũ sang (config ghi sau cùng, kèm `migrated_from`), không sửa file cũ; kết quả đã hiện trước đó không bật lại. `ONECREW_DESKTOP_HOME` không còn đổi vị trí hộp thư. Đánh đổi: hộp thư nay cùng ổ với ledger; nếu ổ đầy thì checkpoint cũng không ghi được. Mỗi kết quả gồm `.txt` và `.json`; `desktop status` cho đường dẫn và trạng thái. Không cần ghi vào ledger để hiện thông báo.

Cửa sổ được mở như `runner.start` (DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | CREATE_BREAKAWAY_FROM_JOB) để sống sót khi lệnh hay shell khởi động nó kết thúc; nếu Job cấm breakaway thì mở detached không breakaway thay vì không mở.

Entry giữ heartbeat `onecrew-k-t-qu-v-c-u-h-i` PAUSED, không bật lại khi dispatch/resume. Runner cũ đã nạp code trước thay đổi không tự nhận module mới; runner mới dùng kênh đã bật. Task hiện đang blocked không được tự resume bởi cấu hình này.

## Giao tin và lỗi

`launching → claimed → shown → closed`. Ghi outbox/report trước spawn; khóa liên tiến trình bảo vệ claim. Trước khi hiện, UI đọc lại checkpoint và câu hỏi từ ledger; kết quả lỗi thời thành `superseded`. Các trạng thái không ghi vào execution.

- Lỗi biết chắc trước khi mở cửa sổ giữ `pending`, thử lại tại sự kiện tiếp theo hoặc `desktop retry`. Không có timer nền để nhắc lặp. Nếu task đã dừng và không có sự kiện mới, cần retry tường minh; báo cáo vẫn có thể đọc trên D:.
- Nếu tiến trình bị kill giữa claim/mapping/receipt, trạng thái có thể còn `launching`/`claimed`/`uncertain`. Không tự phát lại vì không biết lần trước đã hiện chưa. `retry` là lựa chọn có chủ đích; từ chối khi cửa sổ còn mở hoặc receipt đã `shown`/`closed`. Không hứa exactly-once qua mọi thời điểm crash giữa UI và filesystem.
- Lỗi outbox không đổi thành công của task thành thất bại, không ACK host chat và không tiêu thụ model call. Nếu cả ổ outbox cũng không ghi được, không thể đảm bảo lưu receipt; cần khôi phục ổ đĩa rồi gọi lại.
- Cần Windows desktop tương tác và Tkinter trong Python đang chạy OneCrew. Service/session không tương tác không được xem là thông báo người dùng đã nhìn thấy. Kênh này dành cho workflow checkpoints; không hứa thông báo các chương trình độc lập không phát checkpoint.

## Kiểm chứng 10/10/2026

- 17 regression tests mới: mặc định tắt, im lặng khi running, dedup/restart/concurrency, blocked→resume→completed, trạng thái blocked ở đợt mới, sink C lỗi, lỗi ghi outbox, lỗi launch/UI, retry chưa rõ kết quả, câu hỏi REQ/CREQ, lọc secret, receipt sau Map và close không approve.
- 58 tests desktop/delivery/owned/workflow pass, gồm 17 tests desktop. Các kiểm thử là fixture, không chạy hộ test Cloud Auth. Suite có ResourceWarning từ một subprocess fixture cũ; không có test failure.
- Live: state-root thật enable từ sequence 970; `desktop show` cho TASK-b9a0c151d7274e97b5515f8318ad44e2 tạo notice `84c92ce5ec4abfc5238bf3da5e08ef20`. Receipt `shown` lúc 2026-10-10T09:05:22Z, PID 42052, Windows MainWindowHandle 34873020, tiêu đề đúng Task ID. Gọi show lần hai: `launched: []`.
- Báo cáo thật đọc checkpoint 967, phase blocked, CREQ-517c64d4eadc4ecd8a04261ff975b590 pending, verification pending, checks/applied/deliveries rỗng, 2 timeout checkpoints, assistance entry-runtime-repair. Không coi trial đã hoàn tất hoặc unassisted.
