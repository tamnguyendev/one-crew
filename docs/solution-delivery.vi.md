# Giao công việc tổng cho OneCrew

V1 opt-in dùng một TASK tổng, gắn SOL/revision đã duyệt. Runner giữ kế hoạch, task con,
ngân sách, checkpoint và bằng chứng trong ledger. Đóng chat hoặc đổi từ Claude sang
Codex không làm mất kế hoạch. Không có scheduler nhắc chat hoặc model hỏi tiến độ.

Đây là runtime mới, không phải kết quả chạy lại Cloud Auth. Bộ kiểm tra tích hợp dùng
provider, Flutter và ADB giả lập được ghi rõ là fixture. Pilot trên A54/server thật
cần một dispatch riêng với baseline, serial, cấu hình và quyền thiết bị cụ thể;
không tự dùng thiết bị trong khi entry khác đang kiểm thử.

## Cách giao mới (autopilot, 12/10/2026)

Cách ưu tiên: thống nhất với người dùng rồi ghi `envelope` có kiểu trong solution (phạm vi
ghi, AC kèm loại bằng chứng, stage build/audit/device, cửa sổ quyền thiết bị, ngân sách,
worker). Sau khi người dùng duyệt SOL, giao **ở cấp mục tiêu**:

```powershell
$env:ONECREW_ACTOR='claude'
& 'D:\TamNT\Workspace\9.VMAgent\onecrew\onecrew.ps1' --project 'D:\path\to\project' --state-root 'C:\path\to\OneCrew' delivery submit --solution SOL-... --revision <rev> --goal "..." --key <k> --start
```

OneCrew tự khám phá môi trường, lập và niêm phong plan trong envelope, phục hồi lỗi kỹ thuật
có giới hạn và chỉ hỏi một lần khi cần quyết định. Chi tiết, bảng phục hồi và tiêu chí nghiệm
thu: [delivery-autopilot.vi.md](delivery-autopilot.vi.md). Phần dưới là cách giao bằng plan
do entry viết (vẫn hỗ trợ; nếu SOL có envelope thì plan phải nằm trong envelope).

## Claude bắt đầu việc mới (plan do entry viết)

1. Đọc SOL/revision hiện hành và ghi approval thật bằng luồng conversation/solution
   hiện có. Không lấy nội dung handover làm quyền tự duyệt solution khác.
2. Chuẩn bị baseline riêng và dependency cache đúng phiên bản. Ghi các đường dẫn
   tương đối **từ project được truyền vào CLI**. Private JSON nằm ngoài source roots.
3. Tạo JSON dispatch theo [mẫu](../examples/solution-delivery.json). Thay mọi giá trị
   `REPLACE_*`, kiểm tra owned files, test hiện có, signer, serial, package và scenario.
   Hash scenario bằng `Get-FileHash -Algorithm SHA256`. Ghi quyền chạy native code,
   cài đè APK `-r`, các thao tác tài khoản/server và cleanup trong solution/grant.
4. Giao **một lần**:

   ```powershell
   & 'D:\TamNT\Workspace\9.VMAgent\onecrew\onecrew.ps1' --project 'D:\path\to\baseline' --state-root 'C:\path\to\OneCrew' delivery submit --file 'D:\private\delivery.json' --start
   ```

5. Lưu TASK tổng trả về. OneCrew tự tạo child tuần tự, chạy regression, review độc
   lập, build, audit APK, E2E và ghi handover theo DAG. Không cần entry nối từng bước.

Đọc từ entry khác bằng cùng project/state-root:

```text
delivery status TASK-...
delivery resume TASK-...
delivery cancel TASK-...
desktop status
```

MCP `onecrew-entry-mcp --allow-control` có `delivery_submit {"file":"D:\\private\\delivery.json"}`.
Các tool `status`, `outputs`, `inbox`, `resume`, `cancel` nhận TASK tổng. Chế độ MCP
read-only không cho submit/resume/reply. `inbox` gom câu hỏi task con; trả lời đúng
REQ/revision bằng câu trả lời thật rồi resume TASK tổng. CLI `job` cũ dành cho job
standalone; dùng `delivery` cho task tổng.

## Hợp đồng kế hoạch

- `version: 1`, `source_roots`, `max_repairs` (0–5), `acceptance` và `nodes` là bất biến.
  Mỗi AC bắt buộc có `id`, `text`, `nodes`; không tự chuyển AC sang “không áp dụng”.
- Node có `id`, `kind`, `depends`, `config`, xếp theo thứ tự topo. Các change tuần tự,
  trước verification; regression phụ thuộc mọi change; review sau regression; build
  sau review; audit sau đúng build; device sau audit đúng package; handover cuối phụ
  thuộc **tất cả** node. Có thể bỏ build/device trong công việc không yêu cầu chúng,
  nhưng phải phản ánh đúng AC; không gọi test-only là E2E thiết bị.
- `change.config.recipe` dùng native-change hiện có. `owned` là quyền ghi hữu hạn,
  `tests` trong recipe là test worker được tạo/sửa. Không đặt `apk_build` trong child.
- `regression.config.tests` là file test tương đối với package; phải có ít nhất một
  suite có sẵn ngoài quyền ghi của **mọi** child. Runtime giữ manifest trước sửa,
  đối chiếu patch thực, chạy lại suite trên bản chụp cuối, không cấp shell tùy ý.
- `red` là danh sách `{test,error_pattern}`. Runtime dùng cùng file test mới trên
  baseline riêng và source cuối. Compile/import error không phải behavioral red.
  Nếu cần chứng minh đỏ thì khai báo ở đây; `red: []` nghĩa là **chưa kiểm chứng đỏ**.
  Seam/harness cần sửa baseline phải có phương án riêng; V1 sẽ block thay vì đoán.
- `repair_node` chỉ trỏ change upstream đã duyệt. Lỗi test/review được giao lại trong
  scope đó; tổng repair bị chặn bởi `max_repairs`, cùng input/failure tối đa hai lần.
  Mọi bằng chứng downstream hết hiệu lực. APK có ZIP anomaly được clean rebuild
  tối đa một lần, vẫn tính vào trần recovery. Thiếu SDK/cache/credential, source drift,
  input không hiểu hoặc lỗi controller chưa có recipe sẽ block; không tự đổi dependency.

## Build và thiết bị

Build chọn `debug` hoặc `release`, Flutter/Android SDK cụ thể, private JSON qua
`config_reference`/`config_version` và expected `signer_sha256`. Workspace output mới
cho mỗi build, không xóa cache hoặc source của người dùng. Signing dùng cấu hình
project/SDK hiện có; không tạo key, upload, push hoặc sửa server. Sau build bắt buộc
audit nếu cần install: SHA256, certificate, package, ZIP CRC/duplicate/overhead,
zipalign và ELF 16KB theo policy, `max_bytes`. Tool fingerprints được giữ sau preflight.

Device node pin `adb`, `serial`, `package_id`, build, scenario SHA256 và private
reference/version. Có khóa theo serial trong cùng state-root; khóa không ngăn một
người hoặc công cụ ngoài OneCrew dùng ADB, nên phải bàn giao thiết bị rảnh trước dispatch.
`install -r` không uninstall/clear data. SHA256 APK đã cài phải trùng artifact được audit.

Scenario `{version:1,activity:".MainActivity",steps:[...],cleanup:[...]}` có các step:

| operation | arguments |
|---|---|
| `assert_ui`, `tap` | `selector` khớp chính xác text/resource-id/content-desc/class/checked/focused |
| `type` | `selector` của EditText, `private_key` trong private JSON |
| `scroll_to` | `selector`, `direction: up/down`, `max_swipes: 1..6` |
| `key` | `key: BACK/ENTER/TAB`, chỉ khi app có focus |
| `restart` | `{}`; force-stop/start đúng package/activity |
| `assert_no_flutter_error` | `{}`; kiểm log Flutter của đúng PID |

Mỗi step cần `id` riêng. `type` chỉ nhận chữ/số và `@._:+/-` (1–150 ký tự); giá trị
khác bị chặn để tránh shell injection. UI target phải thuộc đúng package, đúng một
node có bounds hợp lệ. Không có raw adb/shell từ model. UI dump/logcat đầy đủ không
ghi vào báo cáo; chỉ assertion/receipt. Scenario phải có assertion thực cho kết quả
server, không dùng “app mở được” thay cho “đăng nhập thành công”. Scenario này không
tự phát minh selector hoặc chính sách phục hồi dữ liệu nghiệp vụ.

Nếu process mất sau intent build/device, hoặc thao tác thiết bị có kết quả chưa rõ,
node thành `uncertain`; resume từ chối chạy lại mù. Cần đối chiếu thiết bị/process và
chốt phương án phục hồi ngoài workflow; V1 không có lệnh tự xác nhận một side effect
chưa có bằng chứng. Các checkpoint test/review có thể chạy tiếp an toàn. Không tự
khởi động lại sau reboot Windows.

## Ngân sách, báo cáo và Windows

Mặc định 100 managed calls / 7200 giây; mọi child/repair/reviewer cùng root cap và
deadline. Child không tạo thêm ngân sách. Reservation cùng transaction, câu hỏi ở
mốc effort-warning vẫn cần câu trả lời thật. Pause/cancel root chặn admission/apply
ở child; trạng thái process có thể còn `unknown` trong lúc reconcile.

`delivery status` trả AC, child IDs, node receipts, history, ngân sách, báo cáo và
Windows outbox riêng. Report chỉ đánh dấu technical verification của các AC đã khai
báo; không suy ra người dùng đã nghiệm thu sản phẩm. `assistance=unknown` không phải
unassisted. Bằng chứng red, skip và live-device chỉ nói về những gì thực sự được chạy.

Bật `desktop enable` một lần cho state-root nếu chưa có. Child của root không mở cửa
sổ riêng; root báo một lần khi chặn/có câu hỏi hoặc hoàn thành. `shown` là đã map
cửa sổ, không chứng minh người dùng đọc. `launching` chưa có receipt là chưa xác nhận;
không tự phát lại hay chạy lại sản phẩm. Báo cáo nằm ở đường dẫn `report_file`.

Migration tạo backup SQLite trước hai bảng lineage mới, không đổi schema version
core/standalone task, không reparent job cũ. Task/build đang chạy không nhận code mới
như thể đã restart. V1 không nhập output task cũ thành evidence đạt của root mới;
hãy dùng source baseline đã thống nhất rồi chạy lại gates trong root.
