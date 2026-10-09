# Worker Codex, Kiro và Claude

`onecrew provider doctor --json` kiểm CLI/version và tình trạng auth có thể đọc được, không gọi model và không in danh tính/token. Native Windows được pin: Codex 0.160.0, Kiro 2.28.0, Claude Code 2.1.286. Thay CLI/OS cần kiểm chứng lại; không tự bật full-access.

Profile workflow có trường tùy chọn `provider`: `codex` (mặc định), `kiro`, `claude`; `model` phải thuộc provider. Codex/Kiro đã chạy artifact workflow thật. Claude đã có command/strict result parser và contract tests, nhưng **Blocked cho live verification** vì `auth status` trả `loggedIn=false` trên máy hiện tại. Cần đăng nhập subscription bằng Claude Code, không gửi key vào chat. Adapter Claude không tự chuyển sang paid API.

Kiro sử dụng agent riêng trong worker IO, `tools: []`, `allowedTools: []`, `resources: []`, `mcpServers: {}`, `includeMcpJson: false`, hooks rỗng; CLI validate config trước launch. Theo [configuration reference của Kiro](https://kiro.dev/docs/custom-agents/configuration-reference/), tools và MCP là các phần cấu hình riêng. Model được đối chiếu danh sách CLI để chặn fallback ngầm sang model mặc định. V2 stream được kiểm terminal success, truncation và tool calls, sau đó parse JSON. Quota được ghi theo metering credit nếu CLI trả; không suy context usage thành số credit còn lại.

Claude dùng `--restricted --tools "" --permission-mode dontAsk`, strict MCP rỗng, tắt hooks/skills và không lưu session. [Thứ tự ưu tiên settings của Claude](https://code.claude.com/docs/en/settings) vẫn có managed settings; vì vậy chưa xem parser tests là bằng chứng authority/cancel live. Header version và trạng thái auth không chứng minh mọi năng lực runtime.

## Đổi worker tại checkpoint

```powershell
.\onecrew.ps1 --project D:\MyProject work status TASK-...
.\onecrew.ps1 --project D:\MyProject work switch TASK-... --revision <workflow_revision> --provider kiro --model claude-haiku-4.5
.\onecrew.ps1 --project D:\MyProject work run TASK-...
```

Lệnh switch là quyết định explicit của local operator, gắn hash workflow hiện tại. Chỉ đổi sau khi tất cả attempts đã settled và không còn output chờ xử lý. Nếu worker đang chạy, pause/cancel phù hợp rồi reconcile; không tự cấp hai writer. Scope/checks/spec/counters/deadline giữ nguyên; không chuyển native session provider. Handoff dùng snapshot + plan + tiến độ đã công bố.

Sau lỗi parser đã sửa, `work resume TASK-... --reuse-output` xử lý lại receipt đã settled, không gọi lại worker cho receipt đó. `resume` mặc định bỏ output thất bại để retry trong trần đã cấp. Không cho resume/switch khi process cũ chưa được reconcile.

Evidence: [provider-evidence.json](provider-evidence.json). Kiro/Haiku hoàn tất routing JSON với 2 calls, khoảng 0,0214884 credit; parser envelope ban đầu sai được sửa và đọc lại receipt. Run Codex planner → Kiro implementation dùng tổng 2 calls, giữ deadline và dirty source bytes, verification pass nhưng acceptance vẫn pending. Các bài này chưa kiểm chứng mid-write handoff, Claude thật, nhiều entry được xác thực hoặc soak dài.

Codex/Claude/Kiro làm **entry** có thể dùng cùng local CLI `task connect`, `request list`, `work status/outputs`; chỉ cần project và task ID. Đổi chat không tạo lại task. Không coi nhãn `--source` là xác thực, và không cấp CLI này cho artifact workers không có tools. Cài skill/agent riêng cho từng host và kiểm chứng interactive entry vẫn thuộc P2 chưa hoàn tất.
