# Worker Codex, Kiro và Claude

`onecrew provider doctor --json` kiểm CLI/version và tình trạng auth có thể đọc được, không gọi model và không in danh tính/token. Native Windows được pin: Codex 0.160.0, Kiro 2.28.0/2.29.0/2.30.0, Claude Code 2.1.286. Thay CLI/OS cần kiểm chứng lại; không tự bật full-access. Kiro tự cập nhật (13/10/2026: 2.29.0 → 2.30.0 trong vài phút); bản chưa kiểm chứng bị chặn cho tới khi `scripts/verify_kiro_cli.py` ghi bằng chứng (cờ CLI, agent không-tool, model, một lần gọi tối thiểu qua đúng argv/parser của adapter) vào `docs/kiro-cli-<version>-evidence.json`. Task đang chạy mà CLI đổi bản sẽ dừng ở `Provider capability changed`.

Profile workflow có trường tùy chọn `provider`: `codex` (mặc định), `kiro`, `claude`; `model` phải thuộc provider. Cả ba adapter đã chạy artifact workflow thật. Claude Code 2.1.286 dùng subscription đã hoàn tất code, chuyển checkpoint sang Codex để hoàn tất task và vượt qua gate Docker; phép hủy riêng xác nhận tiến trình đã dừng. [Evidence Claude](claude-live-evidence.json) ghi đúng 3 managed calls cho cả hai trial, không retry. Đăng nhập subscription bằng Claude Code, không gửi key vào chat. Adapter Claude không tự chuyển sang paid API.

Đăng nhập Claude Desktop/trình duyệt chưa xác thực worker Claude Code CLI. `provider doctor claude --json` hiện đường dẫn `executable` và `login_argv` để tránh đăng nhập nhầm bản cài. Với bản native hiện tại, chạy PowerShell:

```powershell
& "$env:USERPROFILE\.local\bin\claude.exe" auth login --claudeai
.\onecrew.ps1 provider doctor claude --json
```

Hoàn tất bước xác thực trên trình duyệt rồi đợi terminal báo thành công. Doctor phải có `authenticated=true`, `subscription_auth=true`, `available=true` trước khi chạy worker. Đó là bằng chứng đăng nhập, chưa phải bằng chứng thực thi/cancel live. Không sao chép credential Desktop vào ledger hoặc gửi token vào chat.

Kiro sử dụng agent riêng trong worker IO, `tools: []`, `allowedTools: []`, `resources: []`, `mcpServers: {}`, `includeMcpJson: false`, hooks rỗng; CLI validate config trước launch. Theo [configuration reference của Kiro](https://kiro.dev/docs/custom-agents/configuration-reference/), tools và MCP là các phần cấu hình riêng. Model được đối chiếu danh sách CLI để chặn fallback ngầm sang model mặc định. V2 stream được kiểm terminal success, truncation và tool calls, sau đó parse JSON. Quota được ghi theo metering credit nếu CLI trả; không suy context usage thành số credit còn lại.

Claude dùng `--restricted --tools "" --permission-mode dontAsk`, strict MCP rỗng, tắt hooks/skills và không lưu session. [Thứ tự ưu tiên settings của Claude](https://code.claude.com/docs/en/settings) vẫn có managed settings; live trial dùng thêm safe mode, strict settings và môi trường đã lọc API credentials. Header version và trạng thái auth không chứng minh mọi năng lực runtime; evidence chỉ áp dụng các ca đã chạy.

## Đổi worker tại checkpoint

```powershell
.\onecrew.ps1 --project D:\MyProject work status TASK-...
.\onecrew.ps1 --project D:\MyProject work switch TASK-... --revision <workflow_revision> --provider kiro --model claude-haiku-4.5
.\onecrew.ps1 --project D:\MyProject work run TASK-...
```

Lệnh switch là quyết định explicit của local operator, gắn hash workflow hiện tại. Chỉ đổi sau khi tất cả attempts đã settled và không còn output chờ xử lý. Nếu worker đang chạy, pause/cancel phù hợp rồi reconcile; không tự cấp hai writer. Scope/checks/spec/counters/deadline giữ nguyên; không chuyển native session provider. Handoff dùng snapshot + plan + tiến độ đã công bố.

Sau lỗi parser đã sửa, `work resume TASK-... --reuse-output` xử lý lại receipt đã settled, không gọi lại worker cho receipt đó. `resume` mặc định bỏ output thất bại để retry trong trần đã cấp. Không cho resume/switch khi process cũ chưa được reconcile.

Evidence: [provider-evidence.json](provider-evidence.json). Kiro/Haiku hoàn tất routing JSON với 2 calls, khoảng 0,0214884 credit; parser envelope ban đầu sai được sửa và đọc lại receipt. Run Codex planner → Kiro implementation dùng tổng 2 calls, giữ deadline và dirty source bytes, verification pass nhưng acceptance vẫn pending. Các bài này chưa kiểm chứng mid-write handoff, nhiều entry được xác thực hoặc soak dài. Trial Claude mới dùng kế hoạch đã cung cấp, kiểm bốn nhóm hành vi của hàm tổng hợp timesheet và kiểm nội dung tài liệu sau handoff. Lượt Claude báo `num_turns=3` trong một managed call; token report được giữ nguyên, chưa suy ra tiền subscription hoặc quota còn lại. Cancellation chỉ xác nhận cây tiến trình local dừng, không hoàn tiền hoặc cam kết request trên server đã được thu hồi.

Codex/Claude/Kiro làm **entry** có thể dùng cùng local CLI `task connect`, `request list`, `work status/outputs`; chỉ cần project và task ID. Đổi chat không tạo lại task. Không coi nhãn `--source` là xác thực, và không cấp CLI này cho artifact workers không có tools. Cài skill/agent riêng cho từng host và kiểm chứng interactive entry vẫn thuộc P2 chưa hoàn tất.

Worker có thể dùng [tools qua core](worker-tools.vi.md) khi profile/grant cấp rõ. Native tools của CLI vẫn bị tắt; schema chuyển yêu cầu read/search/check tới core, không cấp shell/MCP host. Broker có fixture và Docker evidence; live model-tool flow chưa được coi là verified chỉ vì adapter artifact từng chạy được.
