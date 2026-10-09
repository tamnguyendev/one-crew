# Thử nghiệm agent native cho audit — NA01–NA04

Nguồn: người dùng đồng ý thử giao trọn công việc cho agent native sau phân tích thất bại Cloud Auth. Baseline `e0285c3`. Đây là lát audit Claude, chưa thay mọi mode/provider của OneCrew.

- NA01: Claude dùng Read/Grep/Glob trong một phiên xuyên suốt một công việc; feedback quay về cùng session. Core giữ quyền và budget.
- NA02: snapshot text có phạm vi dưới project, không symlink/junction hoặc cấu hình nhạy cảm; restricted/safe-mode, không shell/write/network/MCP. Kiểm chứng native tools thật trong fixture trước task thật. Không gọi đây là OS sandbox.
- NA03: reviewer độc lập được đọc cùng snapshot. Citation phải trỏ vào nội dung snapshot; kết luận phân biệt source và APK/runtime. Tối đa hai vòng sửa, không reset lịch sử cũ. Usage/tổng native turns quan sát được ghi riêng khỏi managed CLI calls. Mất session/quota chưa có fallback native đã kiểm chứng: dừng giữ checkpoint.
- NA04: tiếp tục cùng TASK Cloud Auth, giữ budget/deadline và trả lời đúng REQ từ “ok, làm thử đi”. Chỉ kết luận thành công từ kết quả thật. Lesson vẫn proposed, không tự tạo skill.

Kiểm thử: snapshot/path/credential exclusion, citation invalid, review repair session reuse, failure/restart và pending-input; live fixture native Read và từ chối path ngoài workspace. Sau đó commit và dispatch nền task thật, xem kết quả theo yêu cầu kiểm chứng đang có; không bật heartbeat.

Giới hạn: native CLI có vòng model nội bộ; hard cap của OneCrew hiện đếm invocation, không đếm mọi lượt nội bộ. Giữ deadline và timeout mỗi invocation, hiển thị native turns nếu provider báo, không suy quota/cost từ token. Không dùng profile này cho sửa app/build/push.

## Evidence avant task thật

- 41 tests targeted native/owned/effort/review passed; 8 final native tests passed, including crash before and after consumed-result checkpoint (no duplicate model invocation).
- Live fixture `TASK-98bf043828aa4b3f80f5fee46bf8d4fb` completed: worker session `779318e2-f6fc-4eb1-827a-aa7b832fcf18` used Read/Glob, 5 reported turns; reviewer `85b3c56e-2490-419c-8d87-a88cc6106f7c` used Grep, 3 reported turns. Two managed invocations.
- Actual tool_result reported an outside-workspace read denied by restricted mode. Random fixture canary did not appear in stdout. Original calc source unchanged. This verifies one path-boundary case, not an OS sandbox or all path attacks.
- Each invocation now has max 30 native agentic turns and 600 seconds, additionally bounded by root deadline. Reaching a cap/failure preserves the attempt and blocks; no automatic replay/provider migration. Session continuity on repair is covered by fixture; live repair evidence is pending.
- Native snapshot intentionally retains existing secret-path exclusion. It can limit credential analysis; the report must disclose that rather than claim a verified APK diagnosis.

References: [Claude CLI flags](https://code.claude.com/docs/en/cli-reference), locally verified Claude Code 2.1.286 help. Source paths are data, not instructions.

Live dispatch preparation hit Windows WinError 206 under the long Store-Python state root before any inference. Snapshots now use a short managed ~/.onecrew/workspaces path when needed; ledger still binds exact workspace/manifest. Nine native tests passed including this path selection. The failed partial copy was not reused.

Some vendored iOS header paths still exceeded Windows limits after shortening. Snapshot root now uses one short unique directory; unsupported paths over 245 characters are counted explicitly in metadata, alongside existing binary/secret/size omissions. No silent claim of complete repository coverage.

Whole-root capture reached the text bound before inference. Migration now derives source roots from successful git_status receipts of the same task, removes overlapping roots, and discloses source_roots in metadata. No chat-prepared source/file selection. A task without prior repository discovery still uses its project root and may require narrower intake. Ten native tests passed, including excluding an unrelated sibling repo from capture.
