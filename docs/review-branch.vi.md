# Bàn giao bằng nhánh Git để review

Khi output hiện tại đã pass checks được cấu hình:

```powershell
.\onecrew.ps1 --project D:\MyProject work branch TASK-... --revision <output-sha256> --name feature-preview
```

OneCrew tạo `onecrew/feature-preview` trong repo local. Không checkout, merge vào branch hiện tại, push, chạy Git hooks hoặc sửa working tree/index của người dùng. Tên đã tồn tại không bị ghi đè. Project chưa có Git HEAD dùng `work export` thay thế.

Muốn ghép vào một nhánh local có sẵn chưa checkout, dùng [work merge](target-integration.vi.md): expected target commit, conservative three-way ở mức file, gate trên đúng bản ghép và CAS cập nhật ref.

Candidate có hai commit: snapshot bytes người dùng trong scope trên HEAD đã biết (ghi rõ gồm sửa của người dùng), rồi commit artifact do OneCrew tạo. Git index tạm nằm ngoài source. Blob được tạo với no-filters, không chạy clean/smudge hooks; reference hooks, fsmonitor và GPG signing bị tắt cho các lệnh này. Git objects chưa được ref trỏ tới có thể còn nếu crash; không cleanup dữ liệu người dùng.

Trước công bố branch, core kiểm HEAD/index/working bytes trong scope vẫn bằng snapshot đầu, tạo tree, đọc lại **chính tree đó** và chạy các checks của profile trên nội dung đọc lại. Source thay đổi hoặc check fail thì không công bố branch. Đây vẫn là gate được cấu hình: JSON/text/syntax checks không tương đương test chức năng cả app.

Action broker giữ payload gồm ref/commit/tree/snapshot/evidence. Nếu ref đã tạo nhưng mất ack, trạng thái unknown được đối soát với đúng commit thay vì tạo lại mù. Gọi lại cùng task/revision/name trả receipt cũ; ref đã bị người khác di chuyển sẽ báo stale. Không tự coi receipt là user acceptance.

Evidence IB01–IB02: test Git thật xác nhận checkout/index/dirty bytes nguyên vẹn, snapshot baseline giữ user bytes, candidate đúng nội dung, ref-hook không chạy; stale source/existing branch/gate failure bị chặn; fault sau update-ref được reconcile. Chưa có automatic merge/rebase hoặc vector integration đa repo/parallel DAG đầy đủ.
