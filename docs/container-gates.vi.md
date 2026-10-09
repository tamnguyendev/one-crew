# Kiểm thử chức năng trong container

Profile có thêm `container_test` để chạy test do operator chốt trên đúng snapshot ứng viên. Test entry phải thuộc `context` nhưng không thuộc `owned`. Worker chỉ sửa code sản phẩm; không sửa command, image, expected check hoặc file test entry. Các test/dependency hỗ trợ cũng nên là context chỉ đọc.

Ví dụ một check (thay image bằng ID thực đã cài trên Docker Desktop):

```json
{
  "id": "functional",
  "acceptance": ["AC-01"],
  "kind": "container_test",
  "path": "tests/acceptance.py",
  "expected": {
    "image": "sha256:<64 hex characters of installed image ID>",
    "argv": ["/usr/local/bin/python", "-B", "/work/tests/acceptance.py"],
    "timeout_seconds": 60
  }
}
```

Test tự import/gọi ứng dụng trong `/work` và trả exit code khác 0 khi thất bại. Có thể dùng test HTTP khởi động server và client cùng container. Cài dependency sẵn trong image; OneCrew không pull/build/install hoặc mở mạng tự động. Image được operator tin cậy và không được khai báo persistent volumes. Profile được kiểm preflight trước enable để tránh tốn model khi Docker/image thiếu.

Runtime hiện pin transport Docker Desktop Linux Engine qua named pipe local trên Windows. Container không có mạng, user 65534, rootfs và snapshot mount chỉ đọc, bỏ Linux capabilities, chặn thêm privileges, giới hạn CPU/RAM/PID/logs; `/tmp` là tmpfs tạm. Không mount source gốc, ledger, credentials hoặc Docker socket. Tham chiếu cấu hình: [Docker container runtime](https://docs.docker.com/engine/containers/run/).

Gate kiểm exit state của container và dọn resource trước khi lưu receipt. Receipt gồm snapshot, hash check, image ID, engine version, exit code và log giới hạn. Gate cũng chạy trên Git candidate thực trước tạo review branch. Lỗi engine/timeout/cleanup chưa xác nhận làm workflow blocked, không tự gọi AI repair; resume chỉ chạy lại gate trên candidate đã lưu. Test thất bại mới đi qua repair có giới hạn.

Resource name được lưu trước create. Restart cùng gate dọn container cũ trước khi chạy lại; không replay side effect bên ngoài vì container không có network và chỉ ghi tmpfs. Nếu controller chết hẳn, container có thể còn chạy tới khi controller/gate được khởi động lại; đây chưa phải bảo đảm tự dọn sau reboot/host death. Cần Docker Engine hoạt động để xác nhận cleanup. Không gọi cơ chế này là sandbox chống mọi lỗ hổng kernel/image độc hại.

Ngày 09/10/2026: sau khi người dùng khởi động Docker Desktop, Engine 28.3.2 và image Python chính thức được kiểm chứng. Image ID, logs, snapshots và costs nằm trong [functional-evidence.json](functional-evidence.json). Hai chức năng có test hành vi và Git-candidate gate đạt: tính đơn hàng (5 test methods, Kiro) và nhập CSV (4 test methods, Codex regression). Boundary checks thực kiểm mount/rootfs không ghi được, không có Docker socket/host canary env và không kết nối được mạng ngoài. Đây là kiểm chứng cấu hình hiện tại, không phải chống mọi kiểu kernel escape.

Lần đầu bị lỗi logging driver của Docker; core đã phân loại sai và tốn một repair ở mỗi task. Đã thêm `compress=false` và phân biệt startup error với test failure. Bài đơn hàng recheck đạt mà không gọi model mới. Bài CSV phát hiện lỗi chữ số Unicode thật, original task vẫn blocked ở 3 calls; một regression riêng tham chiếu task cũ, plan do operator cung cấp, dùng 1 Codex call để sửa. Tổng cả ba trial: **7 managed calls**, gồm đầy đủ lượt thất bại; không reset bộ đếm hay giấu chi phí. Hai kết quả đạt vẫn acceptance=pending. Source/index giữ nguyên, tất cả attempts settled, không còn gate containers.

Sau khi sửa hạ tầng, dùng `work recheck TASK-... --revision <snapshot>` để kiểm lại candidate đã hoàn tất implementation. Lệnh chỉ chạy gate, không gọi AI hoặc tự repair, kể cả test fail; giữ budget/deadline, thu hồi acceptance cũ về pending và yêu cầu revision hiện hành. Gate vẫn cần deadline còn hiệu lực. Full suite sau sửa và thêm recheck/card: 173 tests đạt trong 71.702 giây.
