# P1b — admission, ngân sách và supervisor

Core đã có các primitive lưu bền: reserve trước invocation, charge khi launch, giữ reservation khi chưa rõ kết quả, chặn worker mới khi attempt cũ chưa reconcile, counters không reset qua configure/restart, deadline tuyệt đối và tối đa hai active attempts toàn DB. Mỗi root hiện chỉ một attempt active. Inbox pending chặn cả reserve lẫn launch; cancel requested khác cancelled đã xác nhận.

Đây là API controller và hạ tầng kiểm chứng bằng subprocess thật/fake workload. Chưa tự lập plan hoặc gọi model từ task ledger. Quyền local của P1a vẫn chưa tự nâng thành execution grant. Core không gọi lại external action chỉ vì handler timeout: ghi unknown, đối chiếu bằng observer trước khi xác nhận.

## CLI

```powershell
.\onecrew.ps1 core migrate --json
.\onecrew.ps1 core status TASK-<id> --json
.\onecrew.ps1 core cancel TASK-<id> --json
.\onecrew.ps1 core reconcile ATT-<id> --json
```

Thêm `--project <path>` và `--state-root <path>` trước nhóm `core` nếu cần. `migrate` backup SQLite v1 trong `state-root/backups`, giữ writer lock trong lúc chụp backup và đổi schema v2; lặp migration không thay dữ liệu. Không enable task hoặc cấp lại budget. `status/cancel` cần execution đã được controller cấu hình; task P1a chỉ được submit chưa có execution sẽ báo rõ chưa cấu hình.

Migration chỉ v1→v2; ứng dụng không tự downgrade database. Muốn thử restore, dùng bản sao backup ở state root riêng và cùng project path, không ghi đè state đang chạy. Future schema bị từ chối. Dữ liệu cũ vẫn có thể đọc qua task queue/connect sau migration.

## Bảo đảm và giới hạn

- Reservation, attempt/generation, counters và event commit cùng transaction. Cùng key/operation trả cùng attempt; khác operation báo conflict. Một CLI invocation có thể chứa nhiều model calls bên trong; bộ đếm này không phải hard token cap.
- Unknown giữ capacity/budget. Không dùng timeout lease như bằng chứng process chết; PID được bind với creation time và host để tránh PID reuse.
- Windows supervisor tạo process suspended, gắn Job Object trước resume, ghi launch trước chạy. Job kill-on-close dừng process khi supervisor chết; stop kiểm process accounting và test kiểm descendant PID. Parent exit thành công vẫn dừng descendants còn lại.
- Windows Store execution aliases và venv redirectors bị từ chối. Helpers stdlib dùng native Python tại `sys.base_prefix/python.exe`; không đổi interpreter âm thầm cho project cần venv dependencies. Adapter/gate có venv phải chứng minh cách chạy phù hợp riêng.
- Crash trong khoảng process create → identity commit có thể để launch chưa rõ. Giữ reservation và yêu cầu reconcile, không tự dispatch lại. Chưa tuyên bố recovery tự động được mọi crash window.
- Job Object không thay sandbox chống truy cập file/network hoặc broker bên ngoài. Các executable phải thuộc adapter được kiểm chứng; worker artifact/read-only sẽ có giới hạn tool riêng ở P1c.
- Authorize/finish/action observer là API trusted controller, chưa là endpoint cho worker. Reply inbox không tự authorize action. Action verifier phải trả boolean thật, chuỗi false không được pass.

Tests trong `tests/test_control.py` gồm subprocess thật, kill supervisor, timeout có descendant, PID reuse, transaction failure, budget restart/concurrency và action unknown. Đây chưa phải test live Codex/Claude/Kiro hoặc soak tám giờ. Xem [coverage](proposal-coverage.md) cho kết quả cuối chu kỳ.
