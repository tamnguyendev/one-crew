# Hai nhánh DAG dùng chung ngân sách

Profile có thể đặt `"parallel": true`. Core chỉ chọn tối đa hai task ready có ownership không giao nhau; dependency chưa xong thì không chạy, file trùng thì tuần tự. Giới hạn hai workers áp dụng toàn ledger, gồm nhiều root/project. Root grant, deadline và counters vẫn dùng chung cho planner, hai nhánh, repair và review do core gọi.

Schema v3 thay unique active-owner theo root bằng active-owner theo work unit; root operations vẫn khóa độc quyền toàn root. `core migrate` backup v1/v2 trước khi nâng cấp, giữ nguyên task/request/counters/unknown attempts. Unknown root owner vẫn chặn các unit mới. Admission và checkpoint intent của parallel unit được commit trong cùng transaction; lỗi checkpoint rollback reservation.

Một coordinator giữ quyền ghi state. Workers chỉ ghi IO riêng và trả artifacts; coordinator kiểm scope, snapshot gốc của file được giao, rồi ghép lần lượt vào snapshot mới. Output B có thể được xem/comment trong khi C đang chạy; D chỉ chạy sau cả B/C. Gate cuối kiểm snapshot đã ghép. Nếu một response sai, kết quả hợp lệ của sibling vẫn được lưu; root dừng ở blocker, chưa có triage/resume tự động riêng cho từng nhánh lỗi.

Khi đã có plan rõ ràng, tránh tốn thêm một planner call:

```powershell
.\onecrew.ps1 --project D:\MyProject work status TASK-...
.\onecrew.ps1 --project D:\MyProject work plan TASK-... --revision <workflow_revision> --file approved-plan.json
.\onecrew.ps1 --project D:\MyProject work start TASK-...
```

Plan cung cấp bởi local operator chỉ được nhận ở checkpoint planning chưa có attempt active, vẫn kiểm AC/path/dependency/cycle. Ghi rõ `plan_source=local_operator`; không gọi đó là plan do AI sinh. Mặc định không cung cấp plan thì OneCrew vẫn gọi planner theo spec/profile.

Evidence PD01–PD03: fixture A→(B,C)→D đạt, peak hai worker, feedback B khi C chưa xong, overlap tuần tự, cancel chỉ confirmed khi cả hai unit settled, migration giữ unknown reservation, lỗi admission-checkpoint rollback, sibling hợp lệ sống qua lỗi scope. Live Kiro/Haiku chạy hai locale JSON đồng thời và pass gate trong hai calls; xem [parallel-evidence.json](parallel-evidence.json).

Lần live đầu trả sai scope (mỗi worker trả cả hai file), core từ chối, source nguyên vẹn và task dừng ở cap hai calls. Sau khi thu hẹp prompt và enum path theo từng unit, một regression run riêng dùng hai calls đạt. Không reset task thất bại để làm giả budget. Cả hai trial được ghi evidence. Chưa phải bằng chứng eight-hour soak, kill/restart ở mọi parallel transition, multi-repo contract invalidation hoặc merge vào target.
