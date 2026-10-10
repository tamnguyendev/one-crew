# Thông báo OneCrew theo vòng đời task

**Kênh thay thế đã chọn và triển khai 10/10/2026:** [cửa sổ kết quả Windows](desktop-notifications.vi.md) do workflow phát theo sự kiện, chống gửi trùng và lưu report/receipt trên D:. Scheduler vẫn PAUSED. Không áp dụng các bước bật lại heartbeat trong tài liệu lịch sử bên dưới; đóng cửa sổ không trả lời hay resume task.

**Thay đổi theo yêu cầu người dùng, 10/10/2026 15:52:** tắt lịch kiểm tra lặp `onecrew-k-t-qu-v-c-u-h-i`; không tự bật lại khi resume theo quy trình cũ bên dưới. Người dùng chỉ muốn một bản kết quả khi hoàn tất, hoặc một lỗi/câu hỏi có thể xử lý khi bị chặn. Cơ chế callback trực tiếp từ runner tới chat chưa có; không tuyên bố đã thay scheduler bằng callback. Final heartbeat 15:51 về task b9a0c151d7274e97b5515f8318ad44e2 đã quan sát được qua host history (marker 563ca3556686184c), nhưng người dùng báo không thấy thông báo hữu ích. Receipt này chỉ chứng minh nội dung trong lịch sử; không chứng minh khả năng thu hút chú ý hay OS toast. Batch đã confirm/ACK; task và CREQ vẫn blocked/pending, không bị trả lời hay resume bởi việc tắt lịch.

Ngày 09/10/2026. Thay thế lịch kiểm tra toàn bộ lịch sử liên tục. Phần đọc trạng thái/batch là code, không gọi worker; host Codex chỉ chạy lượt theo dõi khi entry đã bật lịch cho task được gắn.

## Lỗi đã sửa

Task đọc handover hoàn thành lúc 22:55 nhưng batch nằm pending. Đường dẫn file kết quả dài 238 ký tự, còn file tạm cũ lặp cả tên hash nên dài 272 ký tự. Python Windows trên máy không tạo được file tạm. `durable_write` dùng tên sibling ngắn, vẫn ghi/fsync/replace nguyên tử và giữ nguyên batch ID. Batch chỉ được ACK sau khi ghi thành công. `notifications feed` trả thêm pending_batch và last_error; lỗi sink không được biến task thành failed hoặc coi như đã gửi chat.

CREQ dùng bảng conversation_questions để kiểm tra revision/pending trước khi giao; không bị bỏ nhầm vì tìm trong bảng requests của task.

## Quy trình entry khi giao hoặc tiếp tục task

1. Khởi động runner và nhận Task ID. Giữ nguyên terminal/background flow.
2. Tìm heartbeat của chat bằng automation_update và cấu hình trong CODEX_HOME/automations; cập nhật automation đã có, không tạo bản trùng. Một chat dùng một consumer riêng. Chỉ dùng công cụ host để thay đổi lịch, không tự ghi automation.toml.
3. Thêm Task ID mới vào danh sách `--task` trong prompt; giữ những task khác còn hoạt động. Nếu consumer đang giữ batch chưa ACK, xử lý batch đó trước khi đổi danh sách. Không khởi tạo lại consumer để bỏ thông báo.
4. Bật heartbeat nếu có task vừa dispatch hoặc thông báo chưa giao. Mỗi lượt chạy đúng một `notifications watch`. Batch rỗng được ACK ngay. Batch có thông báo: lượt scheduler gọi `begin-delivery` với nội dung, thread và automation; đăng nguyên văn `message` trả về ở final rồi kết thúc lượt, **không ACK hoặc pause trước khi đăng**. Không chạy worker, sửa source, tự trả lời/duyệt/resume từ lượt theo dõi.
5. Lượt scheduler kế tiếp đọc lịch sử chat bằng `read_thread`. Chỉ final của một lượt heartbeat đã completed, đúng automation/thread, đúng toàn bộ nội dung và marker mới được `confirm-delivery` nhận. Tin status thủ công, commentary, tool output, nội dung cắt ngắn và ACK tự khai không đủ. Sau đó ACK kèm cùng danh sách task trả `should_pause`. Khi true, host cập nhật chính heartbeat thành PAUSED. Nếu unread hoặc còn runner sống, giữ lịch tới lượt sau. Khi cần người dùng và không còn việc độc lập đang chạy, báo câu hỏi rồi PAUSE; câu hỏi vẫn pending. Entry bật lại sau khi có câu trả lời thật và thực sự resume.
6. CLI/bridge lỗi: không ACK, báo một lần và PAUSE để tránh vòng lặp lỗi. Nếu đã bắt đầu gửi nhưng chưa tìm được tin trong lịch sử, gọi `delivery-missing`; tối đa ba lần kiểm tra rồi pause với lỗi, giữ batch chưa giao. Không tự đăng lặp khi chưa biết lần trước có gửi không.
7. Khi người dùng yêu cầu gửi lại tin bị bỏ sót, dùng `redeliver --task ... --reason ...` để tạo lại thông báo trạng thái hiện tại, giữ nguyên cursor và lịch sử. Không tạo consumer mới hoặc lùi cursor để phát lại cả lịch sử.

Ví dụ các lệnh dữ liệu (tham số project/state-root đặt trước notifications):

```text
notifications watch --consumer <chat-consumer> --all-projects --task TASK-A --task TASK-B
notifications begin-delivery --consumer <chat-consumer> --all-projects --batch <batch-id> --thread <thread-id> --automation <automation-id> --file <body.txt>
notifications confirm-delivery --consumer <chat-consumer> --all-projects --batch <batch-id> --evidence-file <read-thread-response.json>
notifications ack --consumer <chat-consumer> --all-projects --task TASK-A --task TASK-B --batch <batch-id>
```

`watch` chỉ gửi sự kiện của các task đã chỉ định (và câu hỏi conversation có affected_tasks tương ứng), loại checkpoint lỗi cũ đã bị trạng thái mới thay thế. Nếu runner không còn sống mà không có kết quả cuối, báo cần kiểm tra một lần; không tự chạy lại. ACK ghi nhận cảnh báo đã giao, không đổi grant, deadline hay quyết định. Kiểm tra unread sau ACK tránh tắt lịch nếu task vừa hoàn thành giữa lúc đọc và xác nhận.

## Cấu hình chat hiện tại và giới hạn

Heartbeat `onecrew-k-t-qu-v-c-u-h-i`, consumer `codex-onecrew-active-20261009`, dùng nhịp một phút khi có việc/thông báo. Trạng thái bật/tắt do tool host quản lý. Những lần chạy trống lúc task còn hoạt động vẫn là lượt host, dù không gửi tin; khi PAUSED thì không có lượt kiểm tra idle. Độ trễ phụ thuộc scheduler/app/máy thức; không phải callback tức thì.

Plain CLI, Claude/Kiro ngoài chat này không tự bật lịch Codex: entry cần gắn task và gọi adapter lịch của host. Chưa có một API callback trực tiếp từ runner tới Desktop. Consultation độc lập chưa thuộc `--task` watch này; dùng conversation/inbox hoặc adapter riêng, không nhập CONSULT-ID như TASK-ID.

Thiết lập thông báo hệ điều hành/app còn do người dùng quản lý: [OpenAI Docs — Notifications](https://learn.chatgpt.com/docs/notifications). Bản tin chat không chứng minh OS đã hiện toast.

## Kiểm chứng

Tests: đường dẫn dài tương đương Python Store; sink lỗi giữ batch; ghi lại cùng batch rồi ACK; lỗi được nhìn thấy; CREQ được giao; running → completed → chỉ báo một lần → pause; hoàn thành giữa pull/ACK; câu hỏi chưa trả lời; task khác vẫn chạy; runner chết/unknown; lọc task không liên quan và checkpoint lỗi cũ. Live: batch handover `723eb2c54b878119d1054d9635620367eef1dd82c56c3b16e987d916bc75f2b3` đã ghi và ACK thành công sau sửa; tool host chấp nhận cấu hình heartbeat mới. Scheduled delivery thực tế và tự pause cần đối chiếu lần tick tiếp theo, không suy ra từ unit tests.

Live host lifecycle: automation_update đã xác nhận ACTIVE rồi PAUSED. Trong lượt sửa, entry đọc và giao event 814 của Cloud Auth, ACK batch b4012a435d254472ceac62d5f8977bc944a977041bb53337c1fa1c866a14de05 trả active=false/unread=false/should_pause=true; host tool xác nhận PAUSED. Đây là kiểm chứng thao tác host trong lượt hiện tại, chưa phải quan sát một lượt scheduler tự thức dậy. 82 test hồi quy đạt, sau bổ sung xử lý pause/build/race conversation thì 23 test tập trung đạt. Không có task model được chạy để test thông báo.

## Sửa nhận định sai về giao thông báo

ACK event 814 trong lượt sửa trước là xác nhận xử lý nội bộ, **không chứng minh có thông báo tự động**. Trạng thái host ACTIVE → PAUSED trước đây chỉ chứng minh đổi cấu hình. Chốt mới ND05–ND07 cấm dùng cách đó để tiêu thụ batch watch có nội dung. Local file feed vẫn dùng ACK cũ vì xác nhận ghi file không có nghĩa là gửi chat.

Receipt có host thread/turn/message ID, hash bằng chứng và thời điểm xác nhận, lưu thành last_delivery sau ACK. Source là phản hồi thật của read_thread do adapter đáng tin cung cấp; CLI không có quyền tự truy vấn host và không chứng thực bằng mật mã dữ liệu do cùng OS user đưa vào. Không coi receipt là chứng minh OS đã hiện toast hoặc người dùng đã đọc.

Kiểm chứng hiện tại: 50 test notification/watch/delivery/discussion đạt, gồm đọc/chuẩn bị không được ACK, final thủ công/commentary/sai thread/sai automation/thiếu nội dung đều bị từ chối, phục hồi giữa gửi và ACK, giới hạn khi không thấy receipt, và redelivery không lùi cursor. Một lượt scheduler thực tế vẫn cần xảy ra sau khi kết thúc lượt sửa; giữ lịch ACTIVE và batch chưa ACK cho đến khi có bằng chứng đó.
