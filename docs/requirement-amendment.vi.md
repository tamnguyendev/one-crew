# Thay đổi yêu cầu mà không làm lại mọi việc

Sau khi trao đổi và chốt thay đổi, sửa spec/profile rồi dùng `work amend`. Đây là quyết định **local operator duyệt yêu cầu mới**, không tự phát sinh từ một ý tưởng trong output hay một comment feedback. Chỉ sửa acceptance/checks trong tập file đã được cấp; thêm file, tăng quyền, đổi model hoặc nới repair cap cần luồng riêng.

```powershell
.\onecrew.ps1 --project D:\MyProject spec review SPEC-101 --json
.\onecrew.ps1 --project D:\MyProject work status TASK-... --json
.\onecrew.ps1 --project D:\MyProject work amend TASK-... --revision <workflow-revision> --spec-revision <reviewed-spec-revision> --profile revised-profile.json --affected B --reason "Đã chốt thay đổi hành vi của B"
.\onecrew.ps1 --project D:\MyProject work start TASK-...
```

Trước amend, tất cả workers phải dừng/reconcile, không có câu hỏi pending và source/index của file worker được sửa phải còn khớp baseline đã chụp. Scope context/owned, IDs của AC, provider/model, timeout và repair cap giữ nguyên. Deadline/counters không reset; nếu cần thêm calls/time phải dùng grant extension rõ ràng. Lệnh amend không tự start controller mới.

Core lấy tasks được chọn, thêm tasks có AC/check thay đổi, rồi tính closure theo dependency và ownership giao nhau. Ví dụ A→(B,C)→D: chọn B sẽ làm lại B/D và giữ A/C. Chọn A sẽ làm lại cả graph. Các file bị ảnh hưởng trở về bytes baseline, nhánh độc lập giữ candidate đã làm. Profile/spec mới được lưu bền; workers tiếp theo nhận bản mới. Test/context chỉ đọc do operator sửa được chụp vào baseline mới, còn source gốc không bị OneCrew ghi đè.

Operator phải chỉ rõ tasks bị ảnh hưởng bởi thay đổi ngữ nghĩa trong phần prose/read-only context mà graph chưa biểu diễn. Core suy dependency từ plan/AC/path đã khai báo, không hứa hiểu mọi quan hệ ngầm trong repository. Task IDs và graph giữ nguyên trong thao tác này; thêm một nhánh hoặc chức năng ngoài phạm vi cần plan/grant mới.

Output cũ và quyết định cũ còn trong lịch sử; phần bị ảnh hưởng được đánh dấu stale. Verification/acceptance của candidate mới về pending; old accept/reorder không áp lên revision mới. `task connect --json` hiển thị `accepted_amendment`, ngoài handoff gốc bất biến, để entry mới thấy yêu cầu đang có hiệu lực. Git review branch kiểm profile mới và đúng baseline/candidate mới.

Năm tests kiểm closure/overlap, B/D rerun giữ A/C và budget, tự thêm task có check đổi, old revision rejection, source/running-writer guards, readonly-context refresh và rollback khi lỗi checkpoint. Không thêm model calls cho tính closure hoặc hiển thị review. Tự xử lý blocker riêng từng nhánh còn là phần tiếp theo.
