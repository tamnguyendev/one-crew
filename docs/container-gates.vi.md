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

Ngày 09/10/2026: sáu test contract/native client timeout đạt; integration Git bốn test đạt. Probe Docker thật trả Linux Engine unavailable, nên **gate container live và hai chức năng ứng dụng tổng quát vẫn Blocked**, không dùng fixture để tuyên bố chạy thật. Không có model calls/container live mới cho vòng này. Nội dung/syntax gates vẫn dùng được độc lập.
