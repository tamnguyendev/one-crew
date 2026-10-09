# Native Flutter change — NC01–NC04

Yêu cầu: giao OneCrew sửa lỗi Cloud Auth đã audit ở TASK-0236a265d0ef4dd19d5cd14f8e600e95. Codex bổ sung adapter và brief; Claude tạo bản sửa, OneCrew thực thi kiểm tra và bàn giao. Không gọi đây là lần chạy hoàn toàn không có hỗ trợ tích hợp.

- NC01: job change có recipe riêng, source roots và danh sách file Dart được sửa rõ ràng. Claude đọc/search trong một session rồi trả toàn bộ bản sửa có cấu trúc. Core ghi candidate, không gọi model cho từng thao tác file. Không thay luồng audit/container cũ.
- NC02: fixed Flutter test recipe từ SDK/cache hiện có, không pub get. Thực thi code test dự án đáng tin trên máy host, không phải OS sandbox. Receipt gắn snapshot, exit code và log; model không tự xác nhận test. Cần assertions thật và review độc lập; chưa phải kiểm chứng Android/server.
- NC03: reviewer session độc lập đọc candidate, diff so với working bytes ban đầu và receipt. Tối đa hai vòng sửa trong session worker cũ; kiểm tra scope/hash, giữ consumed-result checkpoint, deadline, effort warning, inbox. Native quota failover chưa được triển khai; giữ checkpoint khi lỗi.
- NC04: chỉ apply sau test/review đạt; preflight mọi file, kiểm tra baseline trước từng write, ghi atomic từng file, kiểm tra lại kết quả. Bảo toàn dirty source ban đầu và file ngoài scope. Nếu crash giữa nhiều file, có thể còn một phần đã apply; resume nhận diện bytes candidate và tiếp tục, không tuyên bố transaction đa file hay chống được mọi external editor race. Không commit/push/build APK tự động.

`job submit --mode change --native-change-config <operator JSON> --start --terminal` là đường giao việc. Recipe chứa source_roots, owned, extra_sources (Dart đã xem và pin SHA256), package, flutter_root, tests, reference, trusted_native. Tên file nhạy cảm chỉ được miễn filename filter khi operator đã review và pin hash; content scan vẫn áp dụng. Không copy credential JSON. Original snapshots giữ backup bytes trước sửa.

Validation: 35 test native-change/native-audit/owned passed. Bao gồm phạm vi/duplicate/missing tests, recipe authority, conflict trước apply, idempotent resume, crash sau consumed result, fixed test receipt và giới hạn sửa. ResourceWarning từ fixture native cũ vẫn xuất hiện. Task Flutter thật là kiểm chứng tiếp theo, chưa được ghi là đã sửa xong.
