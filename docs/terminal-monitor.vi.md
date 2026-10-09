# Terminal theo dõi OneCrew

Yêu cầu 09/10/2026: khi start OneCrew, có thể mở terminal hiển thị công việc và nhóm các agent đang chạy, để chat chính không phải chờ log.

## Phạm vi TM01–TM03

- TM01: `job submit/start/resume --terminal` khởi động runner nền rồi mở console Windows riêng. Trả trạng thái sau handshake có giới hạn; cùng phạm vi dùng lại viewer còn sống. Lỗi mở terminal không khởi động lại hoặc hủy worker.
- TM02: nhóm project → task → worker/unit từ ledger. Hiển thị provider/model, trạng thái, lượt gọi và câu hỏi đang chờ. Nếu operation không ghi model, chỉ rõ model lấy từ cấu hình hiện tại. Không tự tạo nhóm ngân sách hoặc bật agent song song; hiển thị các unit thực sự có. Mỗi unit hiển thị lượt gọi gần nhất, ưu tiên lượt còn chạy.
- TM03: chế độ verbose có plan, thông báo, tool receipt IDs/actions, sự kiện và đuôi log build. Đọc ledger bằng transaction read-only, giới hạn số task/log; lọc chuỗi điều khiển terminal và các dạng secret nhận diện được. Không stream suy luận riêng hoặc toàn bộ prompt/response của provider. Đóng console/Ctrl+C chỉ dừng viewer, không hủy task.

## Sử dụng

```powershell
.\onecrew.ps1 --project <repo> job submit --goal "Kiểm tra chức năng..." --key <unique-key> --terminal
.\onecrew.ps1 --project <repo> job start <TASK-id> --terminal
.\onecrew.ps1 --project <repo> work start <TASK-id> --terminal
.\onecrew.ps1 --project <repo> monitor --all-projects --verbose --terminal
.\onecrew.ps1 --project <repo> monitor --task <TASK-id> --verbose
.\onecrew.ps1 --project <repo> monitor --all-projects --once --json
```

`job ... --terminal` mở một viewer chung cho các project trong cùng ledger, verbose bật sẵn. `monitor --terminal` mở cửa sổ riêng; bỏ flag để xem ngay trong terminal hiện tại. `--limit` 1–100 task (mặc định 12), ưu tiên task chưa kết thúc rồi task mới; header ghi số task hiển thị/tổng. `--interval` 1–60 giây (mặc định 2). Những thay đổi task/workers được đọc từ ledger mà không gọi model. Không phải mỗi dòng là một agent mới.

Chat entry chỉ cần gọi start, xác nhận runner đã khởi động rồi trả lời người dùng. Không gọi vòng `wait` để giữ lượt chat chỉ nhằm theo dõi console. Xem lại bằng `monitor --once` hoặc `job outputs`. Dừng task bằng `job cancel`, trả lời qua `request reply`; terminal không tự approve.

Viewer là tiến trình riêng và không giữ process handle điều khiển worker. Scope/global filter chỉ thay đổi cách xem, không đổi quyền/budget/dependency của task. Console có thể chứa thông tin dự án; bộ lọc secret là bảo vệ bổ sung, không bảo đảm nhận ra mọi dạng dữ liệu nhạy cảm.

Giới hạn: đây là nhóm logic trong một console, chưa phải các tab/pane Windows Terminal cho từng agent. Android build mặc định có runner nền riêng, viewer hiển thị queue/input/running/final và liveness quan sát được, kèm tail log khi verbose. Câu hỏi có options/revision/lệnh reply; viewer không trả lời hộ. Feed `notifications pull/ack` và bridge của chat độc lập với viewer; xem [giao việc nền](background-handoff.vi.md). Đóng terminal không hủy task/build.
