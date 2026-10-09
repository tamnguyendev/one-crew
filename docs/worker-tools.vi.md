# Worker dùng tools qua core

Worker Codex/Claude/Kiro có thể trả yêu cầu tool theo schema để OneCrew thực thi. Native shell, browser, MCP và hooks của CLI vẫn tắt. Đây là artifact workflow có tools do core quản lý, chưa phải workspace agent với quyền tự chạy lệnh host.

| Tool | Quyền và phạm vi |
|---|---|
| `read_file` | `tool.read`; đọc đúng file trong immutable snapshot đã cấp, tối đa 6000 ký tự, báo truncated nếu dài |
| `search` | `tool.read`; tìm literal trong text snapshot, tối đa 20 kết quả với đường dẫn/số dòng; không đọc file ngoài context |
| `run_check` | `tool.check`; chạy một check ID trong profile đã niêm phong trên candidate chỉ sửa file đang được giao; code runtime chỉ chạy qua container_test đã cấu hình |

Profile thêm trường tùy chọn:

```json
"tools": {"allowed": ["read_file", "search", "run_check"], "max_requests": 6}
```

Grant khi submit cần `artifact.generate` cùng `tool.read`/`tool.check` tương ứng. Profile phải tuần tự (`parallel` bỏ trống hoặc false); workflow hai worker artifact cũ vẫn giữ nguyên. Có thể nhiều task cùng core nhưng mỗi conversation có tools chạy tuần tự. Hiện chưa hỗ trợ browser, MCP ngoài, cài dependency hay shell tùy ý.

Core cung cấp tên/độ dài file; worker yêu cầu đọc phần source cần dùng, tìm nội dung hoặc gửi candidate để thử check. Response gồm `action`, `argument`, `artifact` (summary/files/backlog). `submit` kết thúc phần việc và phải trả toàn bộ thay đổi cuối cùng; candidate của `run_check` không tự nhập vào output. Read/search không được kèm edit. Worker không sửa grant, gate hay ledger. Test pass qua tool chưa hoàn tất task: core vẫn chạy các gate cuối và giữ acceptance riêng.

Mỗi lần hỏi model tính vào managed-call budget cũ; số tool requests có thêm trần 1–20 cho cả task, không reset qua sửa lỗi/handoff. Lặp yêu cầu giống hệt bị chặn. Tool intent được checkpoint trước thực thi, receipt lưu sau kết quả. Nếu mất receipt, chỉ tool đọc/check trên snapshot được chạy lại; không gọi lại model và không tăng trần. Đây không phải bảo đảm exactly-once cho tác dụng bên ngoài: các tool hiện không được phép có tác dụng đó. Container không có mạng, mount source chỉ đọc, không chứa ledger/credentials/Docker socket.

Cancel/pause/deadline được kiểm trước/sau tool và trong container client. Pending tool chặn đổi worker, amendment, request-changes và grouping; resume xử lý cùng intent. Status/outputs hiện tool count, pending và receipts mà không gọi AI.

Kiểm chứng: 8 tests về quyền/scope, read/search/check/submit, cap/no-progress, crash ở receipt, cancel và truncation. [Native Docker evidence](worker-tools-evidence.json) dùng fixture worker để gọi broker rồi chạy Docker thật, zero live model calls; không được suy thành bằng chứng cả ba model tự chọn tool. Task thực tế tiếp theo sẽ kiểm chứng luồng model→tool này sau khi người dùng mô tả phạm vi.
