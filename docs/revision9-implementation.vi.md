# OneCrew revision 9 — triển khai và chạy thử

Ngày 09/10/2026. Phạm vi: conversation chung, solution trước implementation, consultation xuyên provider và chốt thay đổi. Giữ nguyên runner Windows, ledger, recipe, grants và lịch sử task cũ.

## Luồng đã có

1. Entry tạo/chọn `CONV-`, đọc solution/quyết định/câu hỏi và delta trước khi trao đổi. Append nhận `MSG-`/seq/ACK; không sinh task hoặc model call.
2. `solution propose` lưu bản nhanh tối đa 350 từ và bản chi tiết cùng hash. Đề xuất đồng thời được giữ riêng; chọn bản hiện hành bằng compare-and-swap.
3. Không chỉ định provider: entry đang trả lời tiếp tục. “Hỏi Claude review” là một yêu cầu consultation riêng, pin solution và provider; không đổi worker preference hay trợ lý ở lượt tiếp theo.
4. Consultation dùng phiên CLI riêng, tools bị tắt, chỉ thấy solution và câu hỏi được cung cấp. Runner trả ID ngay, tối đa một invocation/10–600 giây, không fan-out hoặc tự fallback. Kết quả có provenance, usage và stale flag; không approve hoặc implement.
5. Người dùng chốt `SOL-`/hash; `job submit` chế độ change/delivery/branch phải có binding được duyệt. Audit thuần đọc không bị buộc duyệt solution triển khai. Spec workflow mới cũng cần quyết định đúng hash; task trước nâng cấp giữ authority cũ.
6. Worker gọi `solution_change` khi cần đổi hành vi/API/scope/acceptance. Native change đưa câu hỏi bắt buộc vào gate này. `CREQ-` giữ task liên quan; entry chỉ đề xuất, không tự trả lời. Apply/publish/admission kiểm lại gate. Process đang chạy có thể cần settle trước khi ghi quyết định.
7. Reply `continue_unchanged`, `stop` hoặc `revise_solution` cần hash request và reference câu trả lời thật. Không tự tăng budget, reset calls hoặc launch. Stop vẫn có hiệu lực trước khi task được enable. Sau đổi solution, candidate/session cũ bị loại khỏi đường thực thi; evidence vẫn giữ.
8. Output/task question/consultation trả về CONV và notification batch hiện có. ACK chỉ đánh dấu đã nhận. Không có heartbeat AI lúc idle.

## CLI

Các lệnh dùng chung `--project <repo> --state-root <state>` trước nhóm lệnh. Ví dụ PowerShell:

```powershell
$oc = 'D:\TamNT\Workspace\9.VMAgent\onecrew\onecrew.ps1'
& $oc --project 'D:\your\repo' conversation create --title 'Chức năng A' --key 'feature-a' --source codex
& $oc --project 'D:\your\repo' conversation read CONV-ID --after 0
& $oc --project 'D:\your\repo' solution propose CONV-ID --file solution.json --key solution-v1 --source codex
& $oc --project 'D:\your\repo' solution review SOL-ID
& $oc --project 'D:\your\repo' solution approve SOL-ID --revision HASH --source operator --reference 'Câu trả lời duyệt thực tế'
& $oc --project 'D:\your\repo' consultation submit --file review.json --start
& $oc --project 'D:\your\repo' consultation show CONSULT-ID
```

`solution.json`:

```json
{"brief":"Hành vi sẽ thay đổi và ví dụ chính.","detail":"Thiết kế, repo/contract, test và ràng buộc chi tiết.","acceptance":["Ví dụ kiểm chứng được"],"non_goals":["Phần không làm"],"assumptions":[],"questions":[]}
```

`review.json`:

```json
{"conversation":"CONV-ID","key":"review-1","solution":"SOL-ID","revision":"HASH","question":"Phản biện solution, chỉ ra rủi ro có căn cứ; không implement.","entry":"codex","reference":"Người dùng yêu cầu hỏi Claude review","provider":"claude","model":"sonnet","max_seconds":180}
```

`job submit` thêm `--solution-id SOL-ID --solution-revision HASH` cùng grant/recipe đã cấp. Duyệt solution không tự cấp shell, Git push, native test hoặc thêm file vào scope. `conversation question/reply --file ...` nhận các tham số của API typed; MCP expose các thao tác tương đương. `consultation route --file ...` chỉ đọc quy tắc; `jev=true` là ngoại lệ opt-in gọi evaluator bên ngoài, không dispatch worker.

## Review từng phần và công việc liên quan

Owned/native mặc định một writer đang sống trên một SOL; không tạo nhiều job cùng contract để chạy nhanh hơn. Task độc lập dùng solution riêng. Dùng workflow DAG hiện có khi cần parallel với ownership, dependencies và integration checks được seal.

`solution bind --file binding.json` gắn legacy DAG trước model call đầu tiên. JSON gồm `task`, `task_revision`, `solution`, `revision`; bản detail phải nhúng hash spec đã submit. Khi muốn mở rộng song song, runtime kiểm test của lát đầu và tạo REQ review snapshot; chưa trả lời thì không gọi thêm model. Approval chỉ áp pattern/contract hiện hành; amendment làm mất hiệu lực mốc review cũ. `tests/test_solution_slices.py` kiểm A → chờ duyệt thật → B/C song song → D.

Với DAG đổi solution: duyệt spec mới, `work amend` để invalidate đúng dependency/ownership closure, rồi reply `revise_solution` với SOL mới có pin hash spec đó. Code/grants/budget gốc giữ nguyên. Candidate đã publish/apply cần reconciliation riêng; không tự rollback source người dùng. Chưa có scheduler tự tạo graph nhiều repo từ ngôn ngữ tự nhiên hoặc native parallel writers không cần sealed plan.

## MCP và khả năng host

Chạy `onecrew.mcp_entry --allow-discussion --source <host>`. Thêm `--allow-control` cho entry được tin để ghi quyết định thật hoặc submit/resume; không đưa operator server cho worker. Read/append không tự dispatch; `consultation_submit` là thao tác dispatch riêng.

Đã kiểm chứng hai CLI thật (Claude Code 2.1.286, Codex CLI 0.160.0) cùng read/append CONV, ACK lưu dưới source riêng. Script: `scripts/verify_mcp_hosts.py`; evidence: `revision9-live-evidence.json`. Đây là phiên CLI có cấu hình riêng; không có nghĩa mọi cửa sổ Desktop đã tự connect, hoặc mọi tin nhắn riêng được tự đồng bộ. Các host phải thực sự gọi tool và nhận ACK.

Trên máy này, MCP child dùng Python native `C:/Users/NUC/AppData/Local/Programs/Python/Python313/python.exe`. Python Store chạy được smoke test từ terminal nhưng host child trả Access denied. Launcher cần import được package OneCrew (cài package hoặc đặt PYTHONPATH). Claude `--safe-mode` tắt MCP nên không dùng cho entry có MCP; worker consultation vẫn giữ safe mode và không được operator tools.

Codex cho cấu hình approval theo từng MCP tool. Chỉ hai thao tác đọc/append của fixture được cấp trong live test; không đổi global approval hoặc quyền solution/submit. [Tài liệu MCP chính thức](https://learn.chatgpt.com/docs/extend/mcp?surface=cli). `scripts/verify_mcp_hosts.py` chứa cấu hình đã chạy; `docs/entry-mcp.vi.md` có hướng dẫn entry chung.

## Routing, JEV và học từ kết quả

Discussion không đọc preference Claude-first của implementation. Explicit provider/model thắng auto; alias mặc định consultation là Claude `sonnet`/Codex `gpt-6-luna`, Kiro phải nêu model. Host chỉ gửi intent `consult` cho yêu cầu thật; quotes/mentions lưu như data. Không có classifier keyword tự gọi model chỉ vì thấy chữ Claude.

Auto cần policy/workload/candidates rõ. Rule lọc auth/capability/tier/quota fresh trước dispatch; quota unknown giữ unknown. JEV tùy chọn **shadow**, không ghi đè pin/rule hoặc cấp quyền. Ý định evaluator được persist trước API call; mất kết quả giữ unknown và không tự retry charge. Không gửi source/toàn transcript/credentials. Phí JEV riêng; usage/cost không có thì null. Giá quy đổi CLI báo không được coi là hóa đơn subscription.

`consultation feedback --file ...`: `cid`, `reference`, `accepted` (boolean), `missed`/`rework` (số không âm), `evidence`. Feedback có nguồn gắn consultation/route/usage/latency để đánh giá first-review acceptance và rework; không tự biến thành instruction/skill hoặc promote policy. Benchmark thực tế giữa model và quyền bật JEV auto-apply là bước sau; phiên bản này không bật auto-apply.

## Giới hạn nghiệm thu

- Live Claude review solution tổng hợp đã hoàn tất; không phải test ứng dụng khách hàng hay chứng minh mọi review đúng.
- Recovery, stale revision, giữ required question, gate task, notification ACK, DAG slice gate được kiểm bằng fixture; xem coverage để biết bộ test cuối.
- Kiro dùng adapter CLI đã có, nhưng live MCP conversation trên Kiro chưa được xác nhận trong lượt này.
- Callback tự chèn tin vào Desktop chưa có; dùng conversation/inbox/feed khi attach hoặc hỏi status. Không bật lại lịch heartbeat.
- Attribution local không phải xác thực nhiều người dùng. Không đọc private chat history/hidden reasoning.
- Chưa có soak tám giờ, benchmark tối ưu model hoặc đảm bảo phát hiện mọi lệch nghĩa. Task thử tiếp theo phải có scope và ví dụ nghiệm thu rõ.

## Bài học từ nâng cấp

Kiểm bằng ACK trong ledger, không tin câu trả lời model rằng đã sync. Tách capability MCP startup khỏi inference capability. Receipt thành công của provider chỉ chứng minh đã sinh output, không chứng minh tool/AC đã đạt. Giữ các lần smoke thất bại và lý do; không che chúng bằng retry cùng ID hay đặt lại ngân sách. Windows receipt đọc/atomic replace có retry ngắn, hữu hạn cho sharing violation; không retry model chỉ vì file đang bận.
