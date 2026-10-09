# Revision 5 — triển khai và giới hạn kiểm chứng

Phần tiếp nối [revision 6](skills-routing.vi.md) đã bổ sung skill candidate từ lịch sử lặp, preference Claude và JEV shadow. Các giới hạn/evidence revision 5 bên dưới giữ phạm vi lịch sử; JEV hiện có proposal opt-in nhưng chưa tự dispatch.

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

## Entry và learning

[Stdio MCP entry](entry-mcp.vi.md) dùng cùng task/inbox/runner, mặc định read-only. Điều khiển cần operator cấu hình `--allow-control`. Chưa tự sửa cấu hình host hoặc mở network endpoint.

Owned checkpoints terminal (`completed`, `failed`, `blocked`, `cancelled`) ghi outcome cùng transaction với checkpoint. Idempotency theo dữ liệu kết quả; lưu provider/model, số managed calls, usage known/unknown, snapshot, progress/recovery và trạng thái verification/acceptance. Assistance và quality chưa có evidence thì là unknown/null, không tự đánh giá model tốt từ một test xanh.

```text
onecrew --project <repo> learning outcomes
onecrew --project <repo> learning propose <TASK-ID> --evidence <outcome-event-id> --text "Bài học có phạm vi"
onecrew --project <repo> learning lessons
```

Lesson phải trỏ đúng outcome của task/project, chỉ `proposed`, không tự nạp vào worker hay đổi routing. Snapshot thay đổi làm lesson stale. Đây là nền outcome/lesson, chưa hoàn tất calibration/benchmark model hoặc promotion tự động. JEV vẫn giữ kết nối hiện có, chưa đưa lên đường quyết định.

## Trial thật và phạm vi bàn giao

Harness chạy thủ công: `.venv/Scripts/python.exe -X utf8 -m tests.live_revision5` (gọi subscription thật, không nằm trong unittest discovery). Hai trial đều giới hạn 12 managed calls/600 giây, Codex `gpt-6-luna`, Docker image khóa SHA; source trong thư mục thử riêng.

- [Trial đầu](revision5-live-evidence.json): sửa đúng và test đạt nhưng thử Git ngoài scope, review không thống nhất delivery rồi hết 12 calls. Giữ trạng thái blocked; không gia hạn hoặc xóa chi phí. Đây là baseline trước khi sửa contract.
- [Trial sau](revision5-live-evidence-d2151ab1.json): completed với 8 calls, tự list/read, tái hiện 2 tests fail, sửa một hàm, 3 tests pass, review accepted; source gốc nguyên vẹn. Không can thiệp trong lượt chạy. Sau trial đầu, runtime được sửa và task mới được tạo; không gọi cả quá trình phát triển là unassisted.

Worker chỉ được nhìn action phù hợp grant; reviewer nhận cùng delivery contract. Candidate không cấp Git sẽ không bị yêu cầu publish để completed. Live evidence dùng HEAD `2117dce` cộng thay đổi cycle 2 chưa commit; trial sau có SHA256 từng source module, không suy toàn bộ code đã nằm trong HEAD đó. Bản MCP xử lý lỗi launch được bổ sung sau trial và kiểm chứng riêng, không ảnh hưởng vòng runtime đã chạy.

Trial nhỏ chứng minh vòng discovery → sửa → test → review, không chứng minh chất lượng trên repo lớn, APK thật hay tám giờ. 70.113 tokens quan sát/8 calls vẫn có overhead lớn cho việc rất nhỏ; chưa tuyên bố tối ưu token. Cần task thực tế tiếp theo để đo thời gian, chi phí, độ đúng và mức can thiệp. Entry sẽ giao nền, báo Task ID rồi trả chat; thông báo chủ động vào chat vẫn chưa có.
