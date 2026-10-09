# OneCrew sở hữu vòng thực thi — kế hoạch 09/10/2026

Baseline `ab25eeb`; proposal [SPEC-007](../specs/SPEC-007-owned-execution.md). Kiến trúc này sửa khoảng trống đã thấy ở task CTS: entry đã phải chọn file, gom evidence và viết adapter thay OneCrew. Các trial đó là evidence assisted, không phải autonomous.

## Ranh giới trách nhiệm

- Entry (Codex/Claude/Kiro chat): clarify, submit goal/root/constraints/permissions/budget, query, reply, review. Không làm discovery hay tạo executor thay runtime.
- OneCrew: admission, task lifecycle, conductor/worker calls, tools, workspace, tests, Git effects, inbox, completion và recovery.
- Worker: đọc/đề xuất/sửa theo tools và quyền core cấp. OneCrew vẫn có thể dùng model Codex; không phụ thuộc phiên Codex đang chat.
- Người dùng: mục tiêu, quyền và quyết định nghiệp vụ; không phải tên file/lệnh thực thi.

## Các chu kỳ triển khai

1. OE01–OE02: intake tự nhiên và discovery/read tools có giới hạn; cùng ledger Control, không scheduler khác. Commit sau tests isolation/idempotency.
2. OE03–OE04: action protocol + generic loop, candidate edits, test runtime và evidence. Không yêu cầu profile/test script do entry viết riêng. Retry chỉ trong root cap; no-progress dừng.
3. OE05–OE06: adapter Git reusable, background runner, inbox/restart và completion đúng requested outcomes. Unknown effect không tự replay.
4. OE07: ba loại task qua CLI chung; ít nhất Codex live trên repo sandbox; tự phát hiện source/tests và giữ nguyên source gốc. Báo model calls, intervention, limitations và không claim eight-hour soak.

Mỗi chu kỳ cập nhật coverage và commit. Không thêm JEV/KB/dashboard trên đường găng. Native tools của provider là tùy chọn sau capability verification; core tools cho phép có vòng tự thực hiện trước mà không bỏ isolation đã có.

## Contract tối thiểu

Input: goal text, project root, client request key, mode (audit/change/delivery), permissions, max calls, absolute deadline, provider/model, optional preinstalled container image. OneCrew tự lưu brief nội bộ; không ghi spec vào repo khách hàng chỉ để submit được.

Tools: metadata/discover/list/read/search, plan, write candidate, sandbox command, diff/Git inspect, Git delivery và ask/finish. Root/path allowlist, sensitive-path exclusions, content cap, read revisions, optimistic edit checks, budget và action policy nằm trong code. Metadata không tự cấp quyền đọc secret. Tool result là dữ liệu có nguồn và cursor; worker không sửa authority.

Context: mục tiêu/quyền, plan hiện tại, task notes, summaries và bounded recent tool results; full receipts đọc theo ID. Không gửi cả source ở mỗi vòng, không bỏ bằng chứng cũ chỉ vì hết cửa sổ gần nhất. State và authority ở ngoài source/candidate.

Tests: worker chọn test entry; core chọn argv của test adapter được hỗ trợ trong sandbox runtime đã cấp; immutable image, không mạng, read-only candidate, tài nguyên/deadline hữu hạn. Không chạy shell model cung cấp trên host. Snapshot/result gắn hash, exit code và command. Test entry ban đầu giữ readonly khi có thể; thay test phải được trình bày riêng, không dùng test mới tự viết như bằng chứng duy nhất đã đạt yêu cầu.

Git: worker đề xuất repo/files/branch/message. Core kiểm quyền, loại dữ liệu nhạy cảm, hash/source freshness, remote allowlist và branch mới; tạo tree bằng index tạm. Mỗi remote có action riêng, partial delivery hiện rõ; verify remote SHA trước completed. Không merge main hoặc force push tự động. Checkout/index người dùng giữ nguyên.

Background: native controller process do OneCrew quản lý, task lock và existing Control admission. Chat đóng không kết thúc task; machine sleep/reboot không được hứa tự chạy. Dừng đợi native worker settlement; resume dùng durable intent/receipt, model report không chứng minh side effect đã xảy ra.

Completion: audit cần report/evidence, implementation cần artifact và checks thật trên candidate, delivery cần receipts của requested effects. User acceptance độc lập. Lỗi infra hoặc thiếu tools là blocker có lý do, không tạo pass giả hay gọi model lặp.

## Điều kiện báo người dùng giao task thật

OE01–OE07 phải có evidence phù hợp; chưa đạt thì báo phần chưa đạt, không gọi nâng cấp đã hoàn tất. Không dùng CTS/SRM làm sandbox. Bài nghiệm thu chỉ seed source/tests và giao mục tiêu, không seed evidence/file list/plan. Giới hạn live: tối đa 60 calls tổng, 20 mỗi task, 20 phút/task; không gọi API trả phí ngoài subscription.

## Cách dùng luồng đã triển khai

Tại thư mục OneCrew, giao việc bằng mục tiêu và project root; không cần tạo spec/profile JSON. `--key` là mã gửi việc: gửi lại cùng nội dung trả cùng task, đổi nội dung với cùng key bị từ chối.

```powershell
.\onecrew.ps1 --project D:\Project job submit --key review-001 --goal "Review kiến trúc và các lỗi chức năng còn tồn tại" --mode audit --max-calls 20 --max-seconds 1200 --start
.\onecrew.ps1 --project D:\Project job status TASK-...
.\onecrew.ps1 --project D:\Project job outputs TASK-...
.\onecrew.ps1 --project D:\Project job cancel TASK-...
```

`job outputs` hiển thị plan, báo cáo, diff candidate, bằng chứng test/Git, câu hỏi và usage. Có thể xem từng phần khi còn chạy. `--details` trả checkpoint đầy đủ và blob references. `entry connect TASK-... --json` chuyển ngữ cảnh sang chat khác; `entry note` lưu trao đổi, không tăng quyền. Các entry cùng dùng project và state root sẽ thấy cùng task.

Sửa code dùng `--mode change --image sha256:<image-id-có-sẵn>`. Kết quả nằm trong candidate riêng, source gốc giữ nguyên. Muốn OneCrew sửa rồi xuất nhánh/push trong cùng task, cấp thêm `--branch onecrew/<nhánh-mới> --remote origin`. Với thay đổi đã có trong source, dùng `--mode delivery` cùng branch/remote. Remote URL của từng repo được chốt khi enable; core không cho model tự chọn đích mới. Push chỉ tạo ref chưa tồn tại, có kiểm tra cạnh tranh bằng expected-empty lease; không ghi đè ref.

Khi cần quyết định, OneCrew tạo inbox request có các lựa chọn. Dùng `request list --task TASK-... --pending --json`, `request show REQ-... --json`, rồi `request reply REQ-... --revision <revision> --choice <option>`. Runner còn sống sẽ tiếp tục sau câu trả lời. Sau khi runner dừng hoặc máy khởi động lại, dùng `job resume TASK-...`; deadline/calls đã dùng không được reset. Lỗi Git chưa rõ kết quả giữ nguyên intent; resume chỉ đối chiếu action cũ, không push lại. Nếu chưa xác minh được thì vẫn blocked.

## Phạm vi đã kiểm chứng và giới hạn

- Chạy nền native Windows; provider adapter vẫn dùng subscription CLI và tắt native tools. Core thực hiện discovery, candidate, sandbox và Git. Đây là luồng tổng quát theo protocol, không phải script dành riêng cho task CTS.
- Discovery hỗ trợ root và repo con, list/read/search theo trang; tối đa 200 file candidate, 200 KB/file đọc, snapshot tổng theo giới hạn hiện có. Search là literal trong từng directory, worker tự đi xuống cây. Các đường dẫn control, credentials và links bị chặn; secret scan là heuristic, không phải bảo đảm phát hiện mọi dữ liệu nhạy cảm.
- Sandbox test của luồng `job` hiện hỗ trợ **Python unittest có sẵn**, chạy trong image Linux đã cài, không mạng, candidate read-only. Native Flutter/Node/browser/MCP test chưa được mở trong luồng này. Thiếu capability phải báo blocked; không coi test chưa chạy là pass. Test mới hoặc framework khác cần adapter chung tiếp theo, không thêm script riêng cho từng task.
- Hoàn tất phải qua kiểm tra deterministic của core và một lượt review báo cáo bằng model có tính vào ngân sách. Reviewer giúp phát hiện mâu thuẫn với evidence, không thay thế nghiệm thu người dùng hay chứng minh đầy đủ tính đúng đắn.
- Receipt, inventory đã khám phá, original/candidate hashes và plan được lưu riêng. Prompt của lượt đang chạy được chốt để thay đổi notes không làm mất khả năng khôi phục; notes mới vào lượt kế tiếp. Ba lần kết quả tool giống nhau trong sáu bước gần nhất dừng vòng không tiến triển. Provider failure đã settled được retry tối đa một lần trong cùng budget.
- Git dùng index tạm, chốt đúng bytes/HEAD/index/remote/ref, giữ checkout/index gốc. Bằng chứng live dùng local bare remote; chưa phải kiểm chứng GitHub network/auth trên một repo thực của người dùng.
- Chưa nghiệm thu soak tám giờ, tất cả loại task/ngôn ngữ, auto-routing/JEV/learning hoặc authenticated native entry integration. Đây là milestone OE01–OE07; backlog OC/LR cũ vẫn giữ trạng thái riêng.

Evidence live được ghi tại [owned-execution-evidence.json](owned-execution-evidence.json); lịch sử triển khai và tests tại [proposal coverage](proposal-coverage.md).
