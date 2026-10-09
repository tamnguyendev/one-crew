# Controller chạy nền trên Windows

Nhiều TASK- ở các project dùng chung state-root có thể chạy đồng thời, tối đa hai managed workers toàn ledger. Task thứ ba chờ capacity, không báo thất bại hoặc gọi model để hỏi lại. Khi slot được giải phóng, controller tiếp tục. Unknown attempt giữ slot cho tới reconcile. Giới hạn này thuộc workflow mới; runtime CV RUN- cũ chưa chung admission ledger. Mỗi root hiện chạy plan tuần tự; DAG song song trong cùng root vẫn chưa hoàn tất.

Sau `work enable`, dùng:

```powershell
.\onecrew.ps1 --project D:\MyProject work start TASK-...
.\onecrew.ps1 --project D:\MyProject work runner TASK-...
.\onecrew.ps1 --project D:\MyProject work status TASK-...
.\onecrew.ps1 --project D:\MyProject work outputs TASK-...
```

`start` tạo process Python native độc lập với Job của launcher, không mở cửa sổ console. Nếu OS không cho breakaway thì lệnh báo lỗi; không nói đã chạy nền khi chưa tách được. Process giữ lock riêng cho task, ghi PID/creation time, tiến từng checkpoint bằng cùng workflow và ledger. Gọi start lặp trả controller đang sống; không tạo worker thứ hai. stdout/stderr nằm trong state/runners, đường dẫn được trả trong receipt.

Khi task pause hoặc có request pending, controller chỉ đọc SQLite và chờ; không gọi model để poll. Sau khi reply pending request được lưu, controller tiếp tục phần đã được grant cho phép. Câu trả lời không tự mở scope, tăng budget hoặc đổi provider. Task đã blocked do lỗi cần `work resume` theo policy rồi `work start` lại; chưa có triage tự sinh câu hỏi từ mọi lỗi.

`core cancel TASK-...` yêu cầu dừng; status chỉ settle attempt sau khi supervisor xác nhận process tree dừng. `work pause` giữ checkpoint và ngân sách. Với pause không làm mất worker output, `work resume` cho controller đang chờ tiếp tục. Nếu pause đã ngắt worker, cần xử lý receipt theo hướng dẫn workflow; không dùng JSON dở làm kết quả hợp lệ.

Deadline gốc tính cả thời gian chờ người dùng/queue/pause. Chạm deadline thì dừng và ghi lý do; không tự cấp thêm 8 giờ sau resume. `work runner` xem identity đã lưu, không suy PID trùng là process cũ. Đây là controller local theo task, **chưa phải Windows service tự khởi động lại sau reboot**, và không chạy khi máy sleep.

Evidence BG01–BG02: launcher process thật thoát, controller vẫn alive; start lặp cùng identity; cancel kết thúc controller, zero model calls khi paused. Test clock đi qua deadline thêm 8 giờ chứng minh không kéo dài grant và không gọi model. Đây là fault/time simulation, chưa là soak live 8 giờ.
