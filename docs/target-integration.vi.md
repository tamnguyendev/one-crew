# Ghép kết quả vào nhánh Git đích

```powershell
.\onecrew.ps1 --project D:\MyProject work merge TASK-... --revision <verified-output> --target refs/heads/integration-target --expected <exact-target-commit>
.\onecrew.ps1 --project D:\MyProject work outputs TASK-... --full
```

Đây là lệnh local operator giao cập nhật một **nhánh local chưa được checkout ở bất kỳ worktree nào**. Target phải tồn tại và đi từ Git base đã chụp; expected commit phải khớp. Không checkout, push, chạy Git hooks/custom merge drivers, sửa source hoặc index của người dùng. Nếu cần xem trước mà chưa cập nhật nhánh có sẵn, dùng `work branch` tạo nhánh review mới.

Core ghép ba phía ở mức file: Git base, snapshot đã verify và target hiện tại. Một phía giữ nguyên thì lấy thay đổi phía kia; hai phía có cùng bytes/mode thì lấy bản đó. Nếu cả hai sửa khác nhau, ghi danh sách conflict rồi dừng. Chưa tự line-merge, xử lý rename hay gọi model đoán cách giải quyết conflict; cần candidate mới được chốt và kiểm chứng. File ngoài scope giữ nguyên từ target. Dirty bytes thuộc snapshot được giữ trong lịch sử source commit; source/index thực không bị sửa.

Candidate được dựng bằng index riêng; gate đọc lại đúng tree Git đã ghép. Nếu target đổi entry test container đã được seal, cần revision source/gate mới. Test fail giữ gate snapshot/evidence, không cập nhật ref. Sau pass, core đối chiếu lại source và expected target rồi CAS update-ref; target đổi trong lúc chạy thì không overwrite. Mất acknowledgment sau update chuyển unknown và reconcile bằng exact commit, không merge lại mù.

`work outputs` hiển thị lịch sử integration.conflict/integration.failed và trạng thái delivery. Verification của snapshot gốc, gate của bản ghép và user acceptance là các bằng chứng khác nhau; merge pass không tự nghiệm thu. Đây là một repo/một ref. [Commit vector](commit-vector.vi.md) kiểm compatibility nhiều repo riêng; không có transaction cập nhật refs xuyên repo hoặc tự rebase.

Bảy tests dùng Git thật trong repo tạm: target thay đổi ngoài scope; giữ dirty/index; conflict; gate thật fail do contract target đổi; target race/checked-out rejection; lost acknowledgment không replay; cancel chặn publish; source đổi sau authorize cũng chặn ref update. Không gọi model trong cycle này. Các thao tác Git bên ngoài OneCrew không chịu task lock; cần tránh checkout target đồng thời, CAS bảo vệ commit ref nhưng không thể khóa mọi công cụ Git khác.
