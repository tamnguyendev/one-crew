# Native Flutter change — NC01–NC04

## Bổ sung NW01–NW05 — native workspace, 10/10/2026

Recipe mới có thể đặt `execution: "workspace"`, `restore_cache: true`. Mặc định cũ vẫn là `artifact`; task đã giao không tự đổi quyền. Claude dùng Read/Glob/Grep/Edit/Write trong workspace riêng và gọi recipe test bằng Bash ngay trong phiên làm việc. Danh sách file được ghi đến từng đường dẫn. Kết quả trả về là report/question; core thu diff từ file thật, kiểm tra file ngoài scope, chạy lại test độc lập, reviewer riêng rồi CAS apply. Không yêu cầu Claude trả toàn bộ file dưới dạng JSON nữa.

Lệnh test được cấp đúng argv tới bridge Python/context ngoài workspace. CLI 2.1.286 còn tự cho phép một số lệnh shell chỉ đọc; đây không phải allowlist shell tuyệt đối hay OS sandbox. Kiểm chứng trực tiếp: Edit/Write và bridge Python chạy được; Edit file không được giao và `touch` ngoài quyền bị từ chối. `--restricted`, safe mode và dontAsk được giữ; không dùng bypassPermissions. Code test vẫn là native code đáng tin của dự án.

Mỗi invocation tối đa 60 native turns/600 giây, 8 lần gọi test; 3 checkpoint test có cùng snapshot và nội dung lỗi dừng lặp. Managed calls không tương đương số native turns hoặc token. Root deadline/cancel và solution gate kiểm tra cả trong tool. Context và receipt bền vững cho consumed-result/pending recovery; child test không ghi checkpoint của parent.

Core chuẩn bị graph/compiler inputs như trước. Khi `restore_cache` được cấp, bridge được tải đúng package công khai pub.dev tại version/hash lockfile để phục hồi cache thiếu; không pub get, nâng dependency, lấy private/Git package hoặc cài SDK. Hash sai tiếp tục chặn ở lần sau. Thiếu quyền/môi trường chưa có recipe vẫn phải báo blocker. Test output được scan và giới hạn trước khi đưa lại model. File compiler-only được pin hash xuyên suốt worker test và acceptance gate.

Chế độ này hiện dành cho Claude + Flutter recipe; chưa chứng minh tương đương cho mọi provider/stack. Replay Cloud Auth dùng baseline trước sửa ở project riêng, môi trường/cache đã chuẩn bị. Chỉ ghi đạt autonomous khi không có entry sửa runtime hoặc chạy hộ test trong lượt acceptance đó. Tình trạng live và lesson nằm ở coverage, không suy từ unit test.

## Luồng artifact trước đây

Yêu cầu: giao OneCrew sửa lỗi Cloud Auth đã audit ở TASK-0236a265d0ef4dd19d5cd14f8e600e95. Codex bổ sung adapter và brief; Claude tạo bản sửa, OneCrew thực thi kiểm tra và bàn giao. Không gọi đây là lần chạy hoàn toàn không có hỗ trợ tích hợp.

- NC01: job change có recipe riêng, source roots và danh sách file Dart được sửa rõ ràng. Claude đọc/search trong một session rồi trả toàn bộ bản sửa có cấu trúc. Core ghi candidate, không gọi model cho từng thao tác file. Không thay luồng audit/container cũ.
- NC02: fixed Flutter test recipe từ SDK/cache hiện có, không pub get. Thực thi code test dự án đáng tin trên máy host, không phải OS sandbox. Receipt gắn snapshot, exit code và log; model không tự xác nhận test. Cần assertions thật và review độc lập; chưa phải kiểm chứng Android/server.
- NC03: reviewer session độc lập đọc candidate, diff so với working bytes ban đầu và receipt. Tối đa hai vòng sửa trong session worker cũ; kiểm tra scope/hash, giữ consumed-result checkpoint, deadline, effort warning, inbox. Native quota failover chưa được triển khai; giữ checkpoint khi lỗi.
- NC04: chỉ apply sau test/review đạt; preflight mọi file, kiểm tra baseline trước từng write, ghi atomic từng file, kiểm tra lại kết quả. Bảo toàn dirty source ban đầu và file ngoài scope. Nếu crash giữa nhiều file, có thể còn một phần đã apply; resume nhận diện bytes candidate và tiếp tục, không tuyên bố transaction đa file hay chống được mọi external editor race. Không commit/push/build APK tự động.

`job submit --mode change --native-change-config <operator JSON> --start --terminal` là đường giao việc. Recipe chứa source_roots, owned, extra_sources (Dart đã xem và pin SHA256), package, flutter_root, tests, reference, trusted_native. Tên file nhạy cảm chỉ được miễn filename filter khi operator đã review và pin hash; content scan vẫn áp dụng. Không copy credential JSON. Original snapshots giữ backup bytes trước sửa.

Validation: 35 test native-change/native-audit/owned passed. Bao gồm phạm vi/duplicate/missing tests, recipe authority, conflict trước apply, idempotent resume, crash sau consumed result, fixed test receipt và giới hạn sửa. ResourceWarning từ fixture native cũ vẫn xuất hiện. Task Flutter thật là kiểm chứng tiếp theo, chưa được ghi là đã sửa xong.
