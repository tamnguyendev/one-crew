# Revision 5 — triển khai và giới hạn kiểm chứng

## Runtime và recipe

`job submit --mode branch --branch onecrew/<name> --android-build-config <file.json>` cấp một recipe cố định cho task lịch sử Android. Cấu hình được đóng trong grant, cùng request key khác cấu hình bị từ chối:

```json
{
  "flutter_root": "D:/SDK/flutter",
  "android_sdk": "C:/Users/NUC/AppData/Local/Android/Sdk",
  "dependency_root": "D:/project/dependencies",
  "dependency_policy": "as-of",
  "max_seconds": 1200,
  "queue_seconds": 1800,
  "native_authorized": true
}
```

Đây là quyền chạy build native của source tin cậy, không phải filesystem sandbox. `dependency_root` có thể null. Runtime tự khảo sát, tạo nhánh đã được duyệt, gọi action `android_build {}`, chuyển `waiting_operation` và chờ bằng code. Một operation key cố định giữ qua restart; không build lại ngầm sau thất bại. Deadline/pause/cancel root áp vào cả queue và build của owned task. Build recipe standalone của task lịch sử đã completed giữ tương thích.

Chỉ recipe Android lịch sử hiện có được nối vào `job`; task cần shell tùy ý, framework chưa có gate hoặc native tool workspace chưa kiểm chứng vẫn phải báo giới hạn. Không cấu hình SDK từ lời worker. `job outputs` hiển thị operation, APK/hash, progress counters, recovery; device_tested luôn false cho build-only.

## Giới hạn tiến triển và evidence

Policy v1 lưu trong checkpoint: cùng kết quả 3 lần, tối đa 16 bước khảo sát liên tiếp, 8 writes, 3 failed tests, 3 rejected reviews. Resume/model switch không reset counters. Đây là chốt tiết kiệm cho lát nhỏ, không phải bộ hiểu scope ngữ nghĩa hoàn hảo. Các task lớn cần chia lát qua workflow có DAG, không nâng trần tự động.

Auth/quota/environment/effect_unknown chặn retry model. Lỗi provider đã settled và chưa xác định hoặc tạm thời chỉ được một retry theo đường hiện có. Không đổi provider tự động. Candidate change phải có kết quả đạt của tất cả original Python test files đã capture ở snapshot hiện tại; không suy rằng đã tìm đủ mọi test trong repo. Report vẫn qua review evidence; user acceptance độc lập.

## Thông báo local không gọi AI

Owned checkpoint, runner stop và build finish thử chuyển outbox sang feed local. Sự kiện lưu trong ledger; lỗi sink giữ batch chưa ack để retry. Cùng batch dùng một file; câu hỏi kiểm lại revision/pending trước chuyển. Không ack thành approval.

```text
onecrew --project <repo> notifications feed --consumer local-feed
onecrew --project <repo> notifications deliver --consumer local-feed
```

Feed ở `<state-root>/notifications/delivered/<consumer-scope-hash>/`. `deliver` xử lý tối đa một batch 500 event; `has_more` nghĩa còn dữ liệu. Runner không mở thêm model để drain. Command/monitor/entry đọc theo nhu cầu. Không có heartbeat AI khi idle; không tự gửi ra ứng dụng ngoài. Direct chat callback vẫn chưa có; trường `chat_callback=false` luôn rõ ràng. Automation Codex cũ giữ PAUSED.

## Kiểm chứng

`tests/test_revision5.py`: grants, restart chờ build không model calls, artifact tamper, failed build, exploration/duplicate-result caps, auth no retry, all captured tests/current snapshot, active parent build và root deadline. `tests/test_delivery.py`: checkpoint→local delivery, retry sink failure, idempotency, pending questions và empty feed. Fixture APK chỉ chứng minh protocol/integrity; không phải Android app thực tế hoặc test thiết bị.

Trạng thái tổng thể và các khoảng P1/P2 còn thiếu được giữ trong [coverage](proposal-coverage.md). Không coi các tests này là chứng minh hoàn tất mọi yêu cầu revision 5 hoặc soak tám giờ.
