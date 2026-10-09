# Entry MCP local — revision 5

Revision 6: `submit` có thể bỏ provider/model để dùng preference của OneCrew trong state-root chung. Explicit provider/model vẫn ưu tiên; replay giữ lựa chọn gốc. Skill approval qua operator CLI, không cấp cho worker MCP. Xem [contract skill/routing](skills-routing.vi.md).

OneCrew có stdio MCP độc lập với worker. Chạy từ thư mục OneCrew:

```text
.venv/Scripts/python.exe -X utf8 -m onecrew.mcp_entry --project <absolute-repo> --state-root <shared-state-root>
```

Mặc định chỉ có `status`, `outputs`, `inbox`. Entry do người vận hành tin cậy có thể thêm `--allow-control --source <entry-name>` để dùng `submit`, `reply`, `resume`, `cancel`. Không mở HTTP port; project/state-root cố định lúc start, tool call không đổi được root. Submit trả Task ID và bounded runner state, không chờ kết quả. Các task được giao đều là `job`; output cho legacy `work` vẫn dùng CLI tương ứng.

Cấu hình mẫu cho host hỗ trợ MCP stdio (thay project/state-root theo nơi giao việc):

```json
{
  "mcpServers": {
    "onecrew-entry": {
      "command": "D:/TamNT/Workspace/9.VMAgent/onecrew/.venv/Scripts/python.exe",
      "args": ["-X", "utf8", "-m", "onecrew.mcp_entry", "--project", "D:/your/project", "--state-root", "C:/your/OneCrewState", "--allow-control", "--source", "operator-chat"],
      "env": {"PYTHONPATH": "D:/TamNT/Workspace/9.VMAgent/onecrew"}
    }
  }
}
```

Mẫu chưa được tự cài vào Codex/Claude/Kiro. Từng host có cấu hình riêng; stdio smoke test không chứng minh cả ba ứng dụng đã connect. Không cung cấp server operator này cho worker. `source` là attribution local, không là chữ ký xác thực người dùng; same-OS-user/full-shell không phải boundary bảo mật. `--allow-control` tin host giữ đúng ý định người dùng và quyền local; không tuyên bố multi-tenant authentication.

`reply` yêu cầu request ID, revision, option và reference tới câu trả lời thật; không tự resume hoặc gia hạn. Runner đang sống nhận câu trả lời qua ledger, không cần recreating task. Runner dừng cần explicit resume trong quyền/deadline hiện có. Im lặng/dismiss không tạo tool reply. Chuyển chat giữ cùng repo/state-root/Task ID; các host cùng dùng CLI/API này.

Giao thức baseline [MCP 2024-11-05 stdio](https://modelcontextprotocol.io/specification/2024-11-05/basic/transports): newline JSON-RPC, initialize/tools/list/tools/call, stdout chỉ chứa protocol. EOF kết thúc server; không dừng worker đã launch. Mọi status/outputs/inbox không gọi model. Direct push vào chat không thuộc server này; local feed dùng notifications CLI.

Kiểm chứng: `tests/test_mcp_entry.py` chạy handshake qua subprocess, query không worker call, read-only controls, validation và reply revision qua entry khác. CAO/tmux chưa có trên host native, WSL chỉ thấy docker-desktop; chưa có môi trường CAO CLI đã đăng nhập để chứng minh launch/cancel/reconcile. Giữ native adapters, không cài WSL distro hoặc migrate job ngầm.
