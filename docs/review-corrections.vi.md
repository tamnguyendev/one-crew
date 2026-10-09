# Review từng phần và yêu cầu sửa

`work review --decision feedback` lưu ý kiến ngay cả khi nhánh khác đang chạy. Để giao sửa cụ thể, xem output và trạng thái hiện tại rồi dùng `request-changes` tại checkpoint đã dừng/reconcile các worker:

```powershell
.\onecrew.ps1 --project D:\MyProject work outputs TASK-... --full
.\onecrew.ps1 --project D:\MyProject work status TASK-... --json
.\onecrew.ps1 --project D:\MyProject work request-changes TASK-... --revision <workflow-revision> --output <output-revision> --affected config --request-id review-config-1 --comment "Sửa phần config theo tiêu chí đã chốt"
.\onecrew.ps1 --project D:\MyProject work start TASK-...
```

`--revision` là hash toàn checkpoint; `--output` là bản đã xem; `--affected` là ID công việc đã hoàn thành trong plan. Hai hash khác nhau. Cùng request ID và payload trả receipt cũ; dùng ID đó với nội dung khác bị từ chối.

Core kiểm bytes của phần được review còn khớp, tính các dependency/ownership liên quan đã làm, rồi cấp **một lượt repair trong trần cũ** chỉ được sửa các file đó. Nhánh độc lập giữ nguyên. Công việc chưa làm tiếp tục theo DAG sau correction. Không cần đợi cả chức năng xong mới giao sửa; nhưng mutation phải ở checkpoint an toàn, không sửa giữa lúc một worker đang ghi. Có thể lưu feedback trong lúc chờ.

Comment là hướng dẫn sửa trong requirements đã chốt. Nó không thay profile, gate, scope, model, calls, deadline hoặc repair cap. Nếu đổi hành vi/tiêu chí, dùng [work amend](requirement-amendment.vi.md); nếu cần thêm ngân sách, dùng [work extend](budget-extension.vi.md). Không tự chuyển một comment thành quyền thêm feature.

Output liên quan cũ chuyển stale; bản mới vẫn phải qua gate chung trước nghiệm thu. Receipt `candidate_produced` nghĩa đã tạo candidate, không nghĩa khách hàng chấp nhận hay source gốc đã bị sửa. Lỗi schema/vượt scope/no-progress dừng theo cơ chế hiện có; pending correction không thể bị bỏ qua bằng recheck hoặc amend. Hết repair cap thì không tự cấp thêm lượt.

Bảy tests kiểm sửa phần đầu rồi tiếp tục, giữ sibling, crash sau receipt không gọi lại model, dedup/conflict/stale feedback, scope escape, gate failure, budget/deadline/active-writer/cancel, rollback và dependency closure. Chưa có live model trial riêng cho review correction; bằng chứng này là fixture controller.
