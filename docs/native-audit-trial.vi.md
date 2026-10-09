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

## Kết quả task thật — outcome 739

`TASK-0236a265d0ef4dd19d5cd14f8e600e95` completed; reviewer accepted lần đầu, 0 repair. Giữ nguyên task, 52 calls cũ → 54 tổng. Native worker session aa5aff35-4d55-4858-a434-331503789254: 13 reported turns, 12 tool calls (gồm StructuredOutput), 76.656s. Reviewer session 7f828f91-6c2a-49eb-b156-ca87ef18bd0d: 7 turns, 6 tool calls, 16.299s. Tổng process 92.955s, không gồm phát triển runtime, capture hoặc các capture thất bại. Runner bắt đầu 21:03:53 ngày 09/10/2026 giờ Việt Nam, dừng sau hoàn tất.

Snapshot 2.417 file, hai roots từ lịch sử task. Core kiểm citation quote/range khớp snapshot; đối chiếu hash các source đã trích vẫn khớp workspace gốc sau run. Task không sửa app, build hay gọi API. Lượt native tự khảo sát và review, nhưng cả trial có hỗ trợ sửa runtime trước đó.

Usage native: 140.095 total tokens = 32.265 uncached input + 99.398 cached input + 8.432 output. Trước native: 673.037 tokens, 0 cached input quan sát, 52 managed calls và chưa có báo cáo accepted. Đây không phải A/B benchmark độc lập; native hưởng phạm vi repo đã tìm trước đó. Không suy số tiền hoặc quota còn lại. Giữ phân biệt managed calls và native turns.

Báo cáo xác nhận snackbar do token null/rỗng trước bước lookup bệnh viện; đề xuất thống nhất credential và phân loại lỗi. APK/runtime/server chưa được kiểm chứng. Entry đã ghi chú nghiệm thu: AUTH_TOKEN có thể được truyền qua nhiều cơ chế dart-define, không chỉ file; guard AppSecrets chưa đọc được; trường hợp “4” trong report thực tế liệt kê 5. AI reviewer accepted không đồng nghĩa mọi câu tuyệt đối đều đúng. Báo cáo gốc trong ledger không bị sửa; bản xuất kèm chú thích ở `.onecrew/reports/TASK-0236a265d0ef4dd19d5cd14f8e600e95-native-audit.md`.

Trial còn phát hiện scanner bỏ sót JSON credential keys viết hoa như AUTH_SERVICE_PASSWORD/AUTH_TOKEN. Đã bổ sung regex và regression: JSON có giá trị credential bị withheld, Dart String.fromEnvironment vẫn đọc được. Probe đọc file cấu hình thật chỉ trả boolean xác nhận withheld, không in giá trị. Snapshot/transcript trước bản sửa được giữ làm lịch sử; không tuyên bố dữ liệu đó chưa từng vào context hoặc đã bị xóa. Scanner là heuristic, không bảo đảm phát hiện mọi secret.

Bốn lesson mới được lưu proposed trong shared ledger gắn outcome 739: whole-task native loop; capture theo repo đã khám phá; đo turns/cache/time riêng; kiểm chứng report và credential filters. Không tự inject, không tạo skill. Live repair session continuity chưa được thử do báo cáo đạt ở vòng đầu; regression kiểm cùng session và crash/restart đã qua.

Final credential-filter/native/owned/search regression: 35 tests passed in 23.842s; existing native fixture ResourceWarning remains with cleanup assertions passing. No application/device tests or source edits.
