# Snapshot và đầu ra để review

`onecrew.snapshots.Snapshots` lưu blob theo SHA-256 bên ngoài project. Controller chỉ chụp danh sách file cụ thể; không tự quét toàn repo. Không cho đường dẫn control/credential phổ biến, symlink/junction, submodule, Windows device hoặc case collision. Người giao việc vẫn cần chọn context không chứa bí mật trong các file có tên thông thường.

Snapshot giữ working bytes (bao gồm binary, untracked, deleted) và từng Git index stage/mode/blob trong scope, kèm HEAD. Đọc lại working/index/HEAD trước khi công bố để phát hiện sửa đồng thời. Giới hạn 2 MB/file, 16 MB/snapshot, 200 file; vượt giới hạn thì dừng, không cắt nội dung âm thầm.

`overlay(base, changes, owned)` chỉ tạo phiên bản mới của các file được giao. `diff(before, after)` dùng cho output card. `materialize(revision, directory)` khôi phục working bytes vào thư mục **chưa tồn tại**; `staged=True` xuất riêng staged bytes, từ chối conflict chưa giải quyết. API không sửa source hoặc Git index hiện tại, không tự commit/integrate. Manifest vẫn giữ các conflict stages để xử lý sau.

Ghi blob/manifest qua temporary file, flush + fsync + replace; hash được kiểm lại trước khi trả reference. Hỏng blob/manifest hoặc lỗi ghi đĩa không được tính checkpoint thành công. Orphan blob sau crash có thể còn; chưa tự garbage collect. Đây là bảo toàn nội dung trong scope, chưa phải clone toàn bộ repository hoặc khôi phục executable permissions trên mọi OS.

Evidence CP01–CP03: sáu test trong `tests/test_snapshots.py` kiểm dirty/staged/untracked/deleted/binary, source race, corrupt hash, disk failure, ownership/path và không ghi đè destination. Lỗi cleanup readonly Git object trên Windows đã được sửa ở fixture. Snapshot runtime và CLI output card được nối ở vòng tiếp theo.
