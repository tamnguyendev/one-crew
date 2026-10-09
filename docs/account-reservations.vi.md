# Giữ quota giữa các worker

Lát này thêm admission theo quota cho **worker đã chọn**, chưa tự chọn/đổi model. Các workflow không bind quota giữ hành vi grant cũ; không được quảng cáo là có bảo vệ quota subscription tự động.

```powershell
.\onecrew.ps1 --project D:\MyProject work status TASK-... --json
.\onecrew.ps1 --project D:\MyProject work quota TASK-... --revision <workflow-revision> --file quota-binding.json
.\onecrew.ps1 --project D:\MyProject work run TASK-...
```

File có `account` (alias không chứa email/token), `bucket`, `provider`, `model` và `quota` theo contract [routing](routing-policy.vi.md). `quota` gồm source, observed_at, expires_at, windows; mỗi window gồm name, remaining, reserved, keep_for_chat, estimated_call, resets_at. Các số này dùng cùng đơn vị phần trăm 0–100, dự toán phải dương. `quota.routing_quota` chuyển observation Codex vào contract khi caller đã chọn bucket/windows và mức dự phòng. Không dùng token/credits thay phần trăm.

Operator phải ánh xạ đúng tài khoản/bucket và các cửa sổ áp dụng. Mọi project dùng cùng tài khoản phải dùng **cùng state-root và cùng alias**. Binding không xác minh danh tính tài khoản từ một tên tự khai; không bảo vệ giữa hai ledger độc lập hoặc các ứng dụng ngoài OneCrew. Account/bucket và tập window được ghim cho provider trong task, không thể refresh để né reservation.

Code đọc binding ngay trong transaction admission. Root calls, capacity, attempt/dispatch intent, quota reservation và checkpoint đều commit cùng nhau hoặc rollback. Hai task/nhánh không được giữ cùng phần quota còn lại. Binding phải khớp worker hiện tại; refresh/switch cần checkpoint đã dừng/reconcile. Kiểm freshness lần nữa trước launch; dữ liệu hết hạn không tự gọi model hoặc chuyển API.

Chỉ hoàn reservation khi xác nhận chưa launch. Running/unknown tiếp tục giữ quota qua restart/reset. Lượt đã dùng giữ dự toán tới reset nếu đã kết thúc trước reset; lượt vắt qua reset vẫn giữ vì chưa biết quota thuộc cửa sổ nào. Observation mới có thể đã trừ usage đó: hiện core vẫn giữ thêm dự toán, nên có thể dừng sớm hơn quota thật. Chưa có settlement feed đủ chứng cứ để tự giải phóng phần vắt qua reset. Đây là giới hạn bảo thủ được ghi rõ, không phải hard cap token/credits.

`work status --json` và `work outputs --json` có `usage_summary`. Receipt cùng attempt được dedup; cached input Codex là phần của input, tổng token = input + output. Kiro credits được ghi riêng. Missing, conflicting hoặc nhiều cumulative reports chưa xác định session/event semantics hiện unknown; không suy thành zero. Format Claude chưa có live verification nên chưa chuẩn hóa totals. Legacy record thiếu provider không bị gán provider hiện tại sau handoff.

Hai counter bằng nhau không đủ chứng minh là cùng event. Nếu một receipt có nhiều token/metering records mà không có định danh/semantics đã xác minh, summary ghi unknown; không gom theo giá trị rồi báo chi phí thấp hơn có thể đã tiêu.

Fixture kiểm concurrent roots, rollback admission, launch freshness, known-not-started refund, unknown/cross-reset, pinned mapping và workflow thực qua core. Usage tests kiểm replay, cache, tín hiệu mâu thuẫn và missing receipts. Feed Codex có live evidence riêng; cycle admission này không tiêu model calls. Tự refresh nhiều provider, cumulative settlement và calibrated routing/fallback vẫn là phần còn thiếu của OC10.
