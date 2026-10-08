# MVP và tiêu chí nghiệm thu

Trạng thái: kế hoạch đề xuất, chưa triển khai. Những khoảng thời gian dưới đây là ước lượng lập kế hoạch cho một lập trình viên có AI hỗ trợ, không phải cam kết.

Lát đã có: [CLI duyệt spec local](spec-review-cli.vi.md), có list/review/diff/approve/request-changes/history; kiểm chứng theo [coverage của lát này](proposal-coverage.md). Chưa coi các yêu cầu host, budget hoặc quyền worker dưới đây là đã hoàn thành.

## 0. Spike quyết định nền tảng — khoảng 2–3 ngày

Baseline Kiro Crew stable với Kiro CLI hoặc Claude adapter. DeepSeek cần thử riêng với bản đã hỗ trợ, không âm thầm nâng main cho mọi việc.

| ID | Ca phải chứng minh | Bằng chứng đầu ra |
|---|---|---|
| S01 | Một task thật tạo/sửa file và kiểm tra trong repo mẫu | Run ID, diff, kết quả test |
| S02 | Gate do host gọi; agent báo xong nhưng test đỏ | Task không được accepted; không chạy bước phụ thuộc |
| S03 | Tắt tiến trình giữa task rồi khôi phục | Không mất task; không chạy lại side effect chưa rõ |
| S04 | Hai task độc lập chạy có ownership riêng | Không trộn run-state hoặc artifact |
| S05 | Builder thử sửa test hoặc verifier bị bảo vệ | Bị chặn hoặc run bị rejected; evidence chỉ rõ cơ chế |
| S06 | CLI submit/status/cancel/resume qua interface có thể duy trì | Contract test với version host đã ghim |
| S07 | Backend usage thiếu hoặc là tổng session | Unknown đúng; không cộng hai lần |
| S08 | Windows path có khoảng trắng/dấu, hủy task đang chạy tool | Không lỗi quoting; tiến trình con được xử lý |
| S09 | Claude/Kiro/Codex lần lượt qua cùng contract cơ bản | Ba bộ evidence; ghi rõ capability khác nhau |

S02, S03, S05, S06 là điều kiện bắt buộc trước khi triển khai extension cho workflow tự động. Nếu thiếu seam nhỏ, cân nhắc upstream/fork nhỏ. Nếu nhiều ràng buộc đòi sửa sâu, ghi ADR và đánh giá wrapper Claude độc lập bằng cùng ca thử. Không mặc định mở một dự án viết runtime lớn.

Sau phản hồi về Claude Desktop/OneTechAI chạy lâu và khó kiểm soát, thêm **C01–C08** trong [contract điều khiển](control-and-latency.vi.md) vào spike. Ưu tiên chứng minh status/cancel/budget hoạt động khi model chậm hoặc mất kết nối trước khi mở rộng workflow và dashboard.

## 1. CLI và visibility — khoảng 3–5 ngày

| Yêu cầu | Hoàn thành khi |
|---|---|
| R01 — Quản lý project | Đăng ký nhiều repo; phân biệt repo chính, worktree và task |
| R02 — Doctor | Báo binary/adapter/version/auth readiness và capability, không in credential |
| R03 — Trạng thái | Một lệnh hiện ai làm gì, ở đâu, chờ gì, bước tiếp theo; có JSON |
| R04 — Vòng đời | Submit idempotent; pause/cancel/resume phản ánh trạng thái thực của host |
| R05 — Theo dõi kết quả | Liên kết task với diff, report, log và artifact; không cần lục transcript |
| R16 — Điều khiển độc lập với model | Host tiếp nhận status/pause/cancel khi model đang bận; hiển thị yêu cầu và xác nhận thực tế riêng |
| R17 — Ngân sách toàn task | Deadline/retry/concurrency không reset khi đổi vai, retry, replan hoặc resume |
| R18 — Chẩn đoán chậm | Tách queue/model/tool/verify/review/wait; hiển thị hoạt động và bằng chứng tiến triển riêng |
| R19 — Chống lặp và chuyển giao | Dừng khi lỗi/đầu vào không đổi và không tiến triển; chuyển giao không có hai writer, không mất artifact |

Không import tất cả worktree hiện có thành task đang chạy. Import ban đầu chỉ lập inventory để người dùng gắn task và quyết định giữ/dọn; không tự xóa hoặc di chuyển repo.

## 2. Workflow và nghiệm thu — khoảng 4–7 ngày

| Yêu cầu | Hoàn thành khi |
|---|---|
| R06 — Hai workflow | Quick-fix và feature có đường chạy ngắn/dài rõ ràng |
| R07 — Spec → evidence | Mỗi acceptance criterion gắn với kiểm tra hoặc review có nguồn |
| R08 — Gate bắt buộc | Output không hợp lệ, test fail hoặc timeout đều không thể thành accepted |
| R09 — Freshness | Đổi code/test/spec/gate sau verify làm kết quả thành stale |
| R10 — Triage | Phân biệt lỗi code, test, spec, môi trường, quota; retry có giới hạn |
| R11 — Integration | Sau khi ghép nhánh vẫn chạy gate trên kết quả ghép |

Lấy OneTechAI làm mẫu cấu trúc, nhập chọn lọc theo manifest và hash. Không chạy `sync.py` global. Jev/Obsidian/AWS/construction không là dependency bắt buộc.

## 3. Đánh giá backend và giao diện — khoảng 3–5 ngày

| Yêu cầu | Hoàn thành khi |
|---|---|
| R12 — Backend contract | Kiro, Claude và Codex qua được cùng suite; backend thiếu capability hiển thị rõ |
| R13 — DeepSeek thử nghiệm | Phiên bản hỗ trợ, gate/resume/cancel được kiểm chứng trên repo mẫu |
| R14 — Model routing | Ghi requested/observed model; chọn model có lý do, không im lặng fallback |
| R15 — Báo cáo | Accepted throughput, thời gian chờ, số lần người can thiệp và usage có thể so sánh |

Dashboard/App UI là bước tiếp theo nếu CLI và gate đã chứng minh hữu ích. Tổng khoảng 2–4 tuần là phạm vi thử nghiệm hẹp, giả định các seam tích hợp dùng được; viết runtime riêng sẽ làm thay đổi ước lượng.

## Bộ đánh giá ban đầu

Chọn 8–12 việc từ repo mẫu hoặc bản sao cô lập: sửa lỗi nhỏ, đổi interface, migration có test, cập nhật tài liệu, review diff, tác vụ dài cần resume, xung đột file và lỗi môi trường. Không dùng dữ liệu vận hành nhạy cảm.

So sánh: quy trình Claude/OneTechAI hiện tại, Codex độc lập, Kiro Crew nguyên bản, OneCrew trên Crew; DeepSeek là nhánh thử bổ sung. Giữ cùng task, commit đầu vào và tiêu chí nghiệm thu. Chạy lặp khi ngân sách cho phép, ghi version/model/effort và độ biến thiên.

Các chỉ số đề xuất:

- Tỷ lệ task được accepted với evidence hợp lệ.
- Thời gian đến kết quả được chấp nhận, gồm thời gian chờ người.
- Số lần người phải nhắc, sửa kế hoạch hoặc cứu task.
- Số lần báo xong sai, xung đột worktree, task mất sau restart.
- Usage và chi phí ước tính trên mỗi task accepted, kèm cờ unknown.

Ngưỡng quyết định thử nghiệm: không có false-accepted trong suite; không mất task sau crash; mọi gate có hash và log; giảm ít nhất 30% số lần can thiệp so với baseline trên mẫu đã chọn. Mốc 30% là mục tiêu sản phẩm ban đầu, cần hiệu chỉnh sau dữ liệu thật.

## Bổ sung sau audit lịch sử 25/09–06/10

[Audit toàn bộ lịch sử local](claude-history-audit.vi.md) cho thấy cần đo giá trị bàn giao, ngoài việc quản lý process. Các mục này thuộc MVP, không để sau dashboard:

| ID | Yêu cầu | Hoàn thành khi |
|---|---|---|
| R20 | Lát chức năng thử được | Task có luồng người dùng, SHA/package/cách thử và evidence; code/test xong không tự đồng nghĩa user acceptance |
| R21 | Giới hạn việc đang làm | Giới hạn theo chức năng sản phẩm, không chỉ số process; task con không mở scope mới ngoài plan |
| R22 | Ngân sách hợp nhất | Usage/budget cộng agent con và các workflow mới của cùng task; cache/thinking không đếm trùng; remote thiếu log hiện unknown |
| R23 | Tích hợp sớm | Môi trường mock, integration, UAT được ghi riêng; không dùng kết quả khảo sát thay nghiệm thu luồng sản phẩm |
| R24 | Registry đa máy | Task ID/owner/branch duy nhất; backend và extension demo cùng bản đã kiểm chứng; không có hai writer được claim cùng phạm vi |
| R25 | Kiểm soát scope | Worker không sửa scope/AC/budget; proposal ngoài phạm vi không tự được dispatch; cải tiến được đưa backlog |
| R26 | Reviewer có căn cứ | Lỗi chặn gắn AC/bất biến hoặc rủi ro nghiêm trọng với evidence; không tự thêm điều kiện phát hành |

Triển khai R25/R26 cùng R17/R20/R22 trước phần giao diện, theo [lát kiểm chứng phạm vi](scope-control.vi.md). Mở rộng workflow hoặc chuyển phiên không được tạo budget mới. Các ngưỡng review/checkpoint là cấu hình thử nghiệm, không làm mất yêu cầu chất lượng hoặc tự cho phép phát hành khi gate đỏ.

Baseline ban đầu nằm trong `claude-history-metrics.json`. Không so 70,46 triệu output token của bốn ngày với một task nhỏ mới để tuyên bố phần trăm tiết kiệm; benchmark phải giữ cùng phạm vi và tiêu chí nghiệm thu.

## Điều còn mở sau audit

Người dùng đã chốt lập trình trên nhiều repo với Claude/Kiro/Codex. Số máy/người dùng, cách trả tiền model và yêu cầu remote access chưa được xác nhận. MVP mặc định local, một người, nhiều repo. Những lựa chọn này không ngăn review, nhưng phải chốt trước khi mở rộng kiến trúc.
