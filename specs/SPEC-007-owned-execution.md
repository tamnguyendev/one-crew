# SPEC-007 — OneCrew tự sở hữu công việc

## Duyệt nhanh

### Kết quả
Giao mục tiêu và thư mục cho OneCrew. Codex/Claude/Kiro trong chat chỉ giao việc, xem kết quả và chuyển câu hỏi; OneCrew tự khảo sát, thực hiện và kiểm chứng.

### Phạm vi
Một vòng thực thi tổng quát có tools đọc/tìm repo, sửa candidate, kiểm thử trong sandbox, báo cáo và bàn giao Git khi được cấp quyền. Giữ ledger, budget, supervisor và adapters hiện có. Luồng mới chạy độc lập với chat.

### Không làm
Không tự mở quyền, mua API, merge main hoặc deploy. Chưa thêm routing/JEV, vector DB hay điều phối phân tán. Không viết adapter riêng cho từng task.

### Nghiệm thu
Ba task khác loại trên repo thử nghiệm: review, sửa bug có test, tạo commit/push. Entry chỉ gửi mục tiêu/quyền/ngân sách; không chọn file, gom evidence hoặc cấp plan. Khôi phục không chạy lại side effect chưa rõ; thiếu quyết định thì hỏi qua inbox.

### Lưu ý
Hoàn thành pipeline không đồng nghĩa hoàn thành yêu cầu. Native tools chỉ bật khi có bằng chứng isolation; tools do core cung cấp là một execution mode hợp lệ. Capability thiếu phải hiện rõ. Test live và fixture báo riêng.

### Ngân sách
Triển khai từng chu kỳ có commit. Live nghiệm thu tối đa 60 managed calls tổng, mỗi task tối đa 20 calls/20 phút; chỉ dùng repo thử nghiệm và subscription đã đăng nhập. Dừng sớm khi đạt hoặc phát hiện blocker.

### Cần quyết định
Không có.

## Chi tiết cho AI

Proposal này ưu tiên lấp khoảng trống thực thi trong OC01–OC06/OC09/OC11/OC12 của SPEC-006. Các yêu cầu learning/routing/đa repo song song cũ vẫn được theo dõi riêng, không là điều kiện của lần nâng cấp này.

| ID | Contract | Bằng chứng nghiệm thu |
|---|---|---|
| OE01 | Submit mục tiêu trực tiếp, project root, quyền, budgets, provider; idempotent; không bắt spec/profile/file list | CLI và duplicate/conflict/restart tests |
| OE02 | Tools tự phát hiện repo con, list/search/read theo root và policy; loại control/credentials/links; bounded output/cursors | Discovery trên nhiều cấu trúc repo; escape/link/secret tests |
| OE03 | Vòng observe→act→observe dùng adapter hiện có; plan/checkpoint/receipt lưu bền; context theo ngân sách và refs | Fake worker và live worker tự chọn tools; không host-prepared evidence |
| OE04 | Candidate edits cách ly; kiểm thử chính candidate trong runtime được cấp; kết quả có hash/exit/limits | Bug fixture fail→repair→pass, original source preserved; test tự báo thành công không đủ |
| OE05 | Git adapter chính thức tạo branch/commit/push chỉ với quyền explicit, bind exact file bytes/ref/remote, receipt/reconcile | Real local bare remote, stale source and lost-ack tests; completed chờ delivery |
| OE06 | Core runner độc lập chat; query/cancel/inbox/reply/resume không model; quyền không tăng theo câu trả lời | Native background/restart/cancel; waiting survives restart; duplicate effects do not replay |
| OE07 | Ba bài khác loại dùng cùng runtime, không script task-specific; report sự can thiệp và usage | Review, bugfix with test, Git delivery; live proof separately from deterministic fixtures |

Execution design: OneCrew service giữ outer lifecycle, model thực hiện discovery/planning/actions bên trong vòng có giới hạn. Không cần role/process riêng cho mỗi bước. Adapter native CLI hiện dùng artifact protocol; mở rộng protocol thành tools tổng quát do core thực thi. Native workspace mode là capability nâng cao, không tự mở full access để đạt demo. Agent-influenced commands chỉ chạy trong container không mạng, không credential/ledger/socket; source mounted read-only, outputs collected through core. Image/runtime do operator cấp một lần, không phải script riêng cho từng task.

State: submitted→running→waiting/recovering→verifying/delivering→completed; blocked/cancelled riêng. Persist model intent trước launch; persisted response được replay mà không gọi model mới. Tool intents/receipts có ID; effects chưa rõ chỉ reconcile. Plan là hướng làm việc có thể chỉnh trong scope; model không sửa grants hoặc loại nghĩa vụ nghiệm thu user đã giao.

Read scope theo root/policy, write set thu hẹp theo task; source bytes được chụp khi đọc/sửa. Mọi file publish phải được core đọc/scan/bind và không thay đổi sau seal. Task audit có thể kết luận unknown với bằng chứng, nhưng task implementation không được coi test unknown là pass. Push không rõ trạng thái không được completed. Acceptance của khách hàng vẫn riêng.

Handoff contract và thiết kế chi tiết: [owned-execution.vi.md](../docs/owned-execution.vi.md). Trạng thái thực tế trong [coverage](../docs/proposal-coverage.md). Không thay evidence/ID của workflow cũ.
