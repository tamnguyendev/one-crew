# Một nhánh chờ, việc độc lập vẫn chạy

Trong profile `parallel: true`, lỗi của một unit được lưu riêng vào `branch_errors`. Core tạo câu hỏi inbox có danh sách tasks bị ảnh hưởng. Ví dụ A→(B,C)→D, E chỉ phụ thuộc C: khi B lỗi, B/D chờ, C/E tiếp tục. Chưa đạt tất cả AC thì root không được completed hay accepted.

```powershell
.\onecrew.ps1 --project D:\MyProject work status TASK-...
.\onecrew.ps1 --project D:\MyProject request list --pending
.\onecrew.ps1 --project D:\MyProject request show REQ-...
.\onecrew.ps1 --project D:\MyProject request reply REQ-... --revision <question-revision> --choice retry
```

Controller đang chạy sẽ áp dụng ở checkpoint tiếp theo; nếu controller đã dừng, dùng `work start TASK-...`. `work triage TASK-...` chỉ tạo/xử lý inbox, không gọi model. Khi hết việc độc lập, trạng thái là `waiting_branches`; chờ không tốn token và deadline vẫn chạy.

Reply gắn failure/attempt, plan revision và budget revision. Retry chỉ sau attempt cũ đã settled, trong root grant/deadline và retry cap còn lại. Writer unknown giữ capacity; nhánh độc lập chỉ dùng slot còn trống. Nếu đã trả lời nhưng chưa reconcile, câu trả lời vẫn được lưu, chưa áp dụng; `request show` phân biệt answer và controller_effect. Reply lặp không làm unit chạy lại lần hai. `stop` trong câu hỏi này dừng **toàn bộ root**, giữ outputs.

No-progress hoặc hết retry cap chỉ có inspect/stop. Retry cap dùng chung root, không cấp một cap mới cho từng nhánh. Câu hỏi global/manual thông thường vẫn chặn mọi nhánh. Root budget và giới hạn hai workers toàn ledger không đổi. Khi amend yêu cầu, lỗi nhánh bị invalidate được bỏ khỏi trạng thái hiện hành sau khi pending questions đã giải quyết; lịch sử lỗi/answer vẫn còn.

Đây là boundary theo graph/ownership đã khai báo, local operator và artifact-only workers. Không suy rằng mọi việc “trông có vẻ độc lập” đều được chạy; thiếu dependency trong plan vẫn cần review. Lỗi disk/checkpoint cấp core không được xem như lỗi sản phẩm để bỏ qua.

Năm tests kiểm B/D chờ trong khi C/E hoàn tất, restart rồi reply, unknown writer chưa được chạy chồng, hai lần lỗi dừng theo cap, global question không bị bỏ qua và background controller tiếp tục đúng một nhánh. Các tests dùng fixture worker; live parallel Kiro evidence ở tài liệu DAG là một phép kiểm chứng riêng.
