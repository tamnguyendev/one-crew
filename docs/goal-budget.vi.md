# Một ngân sách cho nhiều task/repo

`work group` nối một tập task **đã enable và được duyệt riêng** vào cùng trần managed calls/deadline. Dùng khi các task phục vụ một mục tiêu, để không nhân ngân sách bằng cách chia task. Các repo phải dùng cùng `state-root`; group không cấp thêm quyền đọc/sửa file.

```powershell
.\onecrew.ps1 --project D:\RepoA work status TASK-A --json
.\onecrew.ps1 --project D:\RepoB work status TASK-B --json
.\onecrew.ps1 --project D:\RepoA work group TASK-A --revision <workflow-A> --file goal-budget.json
```

File gồm `members`, `max_calls`, `deadline`, `reason`. Mỗi member gồm `task_id`, `project` (đường dẫn repo), `workflow_revision` vừa xem. Owner TASK-A phải nằm trong danh sách. Từ 2 tới 20 tasks, không trùng, không thuộc group khác; tất cả ở checkpoint đã dừng/reconcile, không còn pending result/question.

Trần group không vượt grant của owner và không thấp hơn calls đã dùng/đang giữ của toàn nhóm. Deadline nằm trong grant owner và tối đa tám giờ từ thời điểm submit sớm nhất trong nhóm. Mỗi task vẫn chịu grant/scope/cap riêng; deadline hiệu lực là mốc sớm hơn giữa task và group. Chia task, restart, retry, handoff hoặc gia hạn riêng một task không reset trần group.

Admission tính tổng used/reserved của mọi member trong cùng transaction tạo attempt. Cùng budget/unknown của từng attempt chỉ được đếm một lần; không tạo counter sao chép dễ lệch. `work status` và `task connect` hiện group/owner cùng tổng đã tiêu. Inbox dùng phần còn lại của cả nhóm khi đưa lựa chọn retry.

Hủy owner (`work cancel TASK-A`) đặt cờ hủy cho tất cả thành viên trong một transaction. Supervisor từng repo dừng worker của mình; owner chỉ hiện `cancelled` khi toàn nhóm không còn attempt reserved/running/unknown. Nếu mất xác nhận dừng, owner vẫn hiện `cancelling`; lượt đang giữ không được hoàn tiền tự động. Hủy task con chỉ hủy task con; pause vẫn tác động riêng task được chỉ định.

Group này chưa là scheduler đa repo. Các worker chạy theo lệnh start/run của từng task. Nó không tự tạo cross-repo DAG hoặc transaction Git đa repo; kiểm tra tương thích dùng lệnh `work vector` riêng với hợp đồng đã duyệt. Chưa có thêm member hoặc gia hạn group sau khi tạo; group bất biến, không thể bỏ rồi gắn lại để né cap. Thao tác lặp đúng payload trả cùng group; payload khác bị từ chối.

Kiểm thử dùng hai project cùng ledger: concurrent reserve, restart/counter retention, prior usage/unknown, group reset/stale/project/authority rejection, deadline ở reserve/launch, rollback, local extension không vượt group và inbox không đề nghị retry sai. Kiểm thử hủy bao gồm unknown qua restart, rollback, hủy riêng task con và dừng tiến trình Windows thật ở repo thành viên. Không có model calls trong cycle này; không suy các tests thành soak tám giờ hoặc đa repo tự vận hành hoàn chỉnh.
