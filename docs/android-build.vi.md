# Build APK debug từ nhánh lịch sử

Yêu cầu ngày 09/10/2026: người dùng muốn bản Android APK với UI trước hai thay đổi tháng 8, thử trước khi quyết định tích hợp chức năng mới. Dùng thư viện nội bộ ở commit gần nhất trước mốc UI cũ khi không có phiên bản khóa.

## Phạm vi chu kỳ AB01–AB03

- AB01: lệnh chính thức `android build` lấy commit từ biên nhận nhánh đã hoàn tất và kiểm tra ref còn đúng. Không nhận SHA do entry chọn. Xuất Git tree sang thư mục ngắn `~/OneCrewBuilds/<id>/source`; checkout/index gốc không đổi.
- AB02: lệnh cố định `flutter build apk --debug`, giới hạn 10–1800 giây, Windows Job quản lý cây tiến trình, log/exit code/biên nhận; APK phải tồn tại, ZIP hợp lệ, có manifest/classes và SHA-256. Exit 0 hoặc lời báo thành công chưa đủ. Cùng request key không tự chạy lại; APK thay đổi sau biên nhận bị từ chối.
- AB03: build thật flutter_vimes từ kết quả task lịch sử, bàn giao APK khi có artifact đã xác minh; nếu lỗi, giữ log và ghi Blocked. Không coi unit test của adapter là build ứng dụng thành công.

Đây là **operator adapter cho native build của project tin cậy**, không mở shell cho model và không phải filesystem sandbox. Gradle/pub có thể dùng mạng, cache và cấu hình người dùng. Source copy không phải hàng rào bảo mật đối với build scripts. Agent-influenced container tools của SPEC-007 vẫn giữ giới hạn cũ; lệnh mới không được tự gọi từ protocol của worker. Entry cần quyền build từ người dùng, sau đó OneCrew thực thi recipe cố định.

## CLI

```powershell
.\onecrew.ps1 --project <repo> android build --from-task <TASK-id> --key <build-id> --flutter-root D:\flutter --android-sdk <sdk-path> --max-seconds 1200 --dependency-policy as-of --dependency-root <authorized-parent> --allow-trusted-native-build
.\onecrew.ps1 --project <repo> android status --from-task <TASK-id> --key <build-id>
```

`as-of` chọn commit theo first-parent lịch sử HEAD của từng repo dependency, với committer date không sau commit app. Đây là heuristic có biên nhận, không khẳng định bộ thư viện được dùng trong build gốc. `head` là lựa chọn explicit khác. Chỉ hỗ trợ block YAML path dependencies nằm trong thư mục cha source, mỗi dependency là một repo riêng. Với `as-of` và `--dependency-root`, dependencies Git dùng nhánh di động được chọn lại theo repo local cùng thời điểm app; SHA explicit trong pubspec được giữ. Lockfile là fallback nếu dependency không có repo local trong phạm vi. OneCrew tìm repo trong phạm vi đó theo remote identity (HTTPS/SSH tương đương), chọn first-parent as-of, kiểm tra phiên bản khai báo khớp rồi tạo `pubspec_overrides.yaml` chỉ trong bản sao build. Giữ các dependency overrides gốc. Không tìm được revision phù hợp thì dừng rõ tên package. Dependencies pub còn lại do Flutter giải quyết từ pubspec và lockfile export. Không tự nâng version hoặc thay source để giải quyết lỗi.

Lệnh hiện chạy foreground trong tiến trình CLI; giới hạn thời gian và cây tiến trình do OneCrew quản lý. Dùng `job cancel` trên task nguồn sẽ được guard của build kiểm tra. Nếu CLI bị dừng bất ngờ, trạng thái đang chạy không được coi là hoàn tất và cùng key không chạy lại. Muốn chạy lại sau khi xử lý nguyên nhân, dùng key mới. Chưa có build runner độc lập hoặc khôi phục giữa các bước Gradle.

Biên nhận được ghi vào ledger events (`android.build`) và `android-builds/<id>/receipt.json`. Log đầy đủ trong `stdout.log`/`stderr.log`; khi timeout, log tiến trình `.out`/`.err` còn trong build directory. Không cài SDK, không đồng ý license, không ký release, không push, không sửa source sản phẩm.

Kiểm chứng: fixture kiểm tra exact commit export, checkout/index preservation, idempotency, artifact tamper, missing artifact/nonzero exit, moved branch, missing native authority, dependency pin/boundary, archive traversal/symlink. Live build và các can thiệp sửa adapter phải ghi riêng trong proposal coverage.
