# Cho Claude: giao việc bằng task tổng OneCrew

Đã bổ sung `delivery` trong runtime OneCrew. Đọc
[hướng dẫn và giới hạn](solution-delivery.vi.md), dùng
[JSON mẫu](../examples/solution-delivery.json). Không tự dùng nguyên placeholder.

**Việc tiếp theo:** thống nhất công việc cụ thể với người dùng, SOL/revision và quyền
thực thi; chuẩn bị một baseline riêng và dispatch một TASK tổng. Không tiếp tục chuỗi
“OneCrew sửa Dart, Claude tự test/build/ADB” rồi báo đó là OneCrew tự hoàn thành.

```powershell
& 'D:\TamNT\Workspace\9.VMAgent\onecrew\onecrew.ps1' --project 'D:\REPLACE_baseline' --state-root 'C:\REPLACE_state_root' delivery submit --file 'D:\private\REPLACE_delivery.json' --start
```

Giữ TASK tổng trả về. `delivery status TASK-...` và MCP `status/outputs/inbox` đọc
trạng thái bền vững từ entry khác, không cần lịch sử session. Sau câu trả lời thật hoặc
khắc phục blocker đã được phép, dùng `delivery resume TASK-...`; đừng submit task mới
để né trần calls/deadline. Worker/reviewer/repair cùng một ngân sách gốc.

Runtime tự nối các node đã khai báo: child change → regression → structured review →
debug/release → APK audit → install/E2E theo scenario → handover. Lỗi đã biết trong
scope được sửa lại có giới hạn; thiếu quyền/SDK/private config/device, source drift
hoặc side effect chưa rõ sẽ block. Không có quyền sửa runtime đang chạy hoặc tùy ý
thay dependencies, mật khẩu, signer, backend để vượt gate.

Windows: giữ heartbeat chat PAUSED; dùng `desktop enable/status` với đúng state-root.
Task con không mở cửa sổ riêng. Root báo một lần cho blocker episode hoặc kết quả;
report vẫn tồn tại nếu cửa sổ chưa được xác nhận. `shown` không chứng minh người dùng đọc.

Chưa chạy lại Cloud Auth, chưa cài A54, chưa gọi server trong lần nâng runtime này.
Live known-case pilot là bước nghiệm thu tiếp theo, cần chốt baseline/serial/scenario/
private config/signing và thiết bị rảnh tại dispatch. Không suy quyền hay credential
từ đoạn hội thoại cũ. SD05/SD06/SD10 trong coverage còn Blocked trên bằng chứng thực.

Kiểm chứng đã thực hiện: 40 test mới cho delivery, gồm một pipeline tích hợp dùng
provider/Flutter/ADB fixture, concurrency ngân sách, checkpoint, invalidation, review
có điều kiện, private logs, APK identity và foreground guard. Đây **không phải** số
test của ứng dụng Cloud Auth và **không phải** E2E trên điện thoại thật.

Bản gốc có một test monitor gọi capability Codex CLI thật và lỗi khi CLI không sẵn;
đã tái hiện trên `3c3de4a`, rồi cô lập provider trong test đó (giữ nguyên assert về
background runner và monitor failure). Các test containment cũ phát ResourceWarning;
phải đọc kết quả suite cuối, không suy từ warning ra pass/fail.

Commit nền: `54c6653` trên nhánh `codex/solution-delivery-v1`. Bản tích hợp cùng kết quả
suite cuối được ghi bổ sung dưới đây. Không push, không đổi task/build hiện có, không
ghi hoặc gửi tin cho Claude tự động; người dùng chuyển file này cho entry tiếp theo.

Suite toàn repo đã chạy **649 test: 648 đạt, 1 skip** (môi trường không có Python venv
redirector), 352,609 giây. Sau đó 40 test delivery được chạy lại cho các chốt cuối:
manifest lưu riêng, không ghi checkpoint idle, foreground/viewport, grant theo stage,
và receipt Windows đúng episode. Không tính fixture Android là test thiết bị thật.

Đã tích hợp vào repo chính từ `54c6653` + `3f5b162`; kiểm tra lại ngay trong repo chính:
**119 test đạt, 0 skip**, gồm delivery và các đường chạy cũ liên quan. Launcher
`onecrew.ps1 delivery submit --help` hoạt động. Các sửa chưa commit có sẵn trong
`docs/proposal-coverage.md` và các file ngoài phạm vi được giữ nguyên.
