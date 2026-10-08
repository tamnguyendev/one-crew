# MVP và tiêu chí nghiệm thu

Trạng thái: kế hoạch đề xuất, chưa triển khai runtime. Review tổng thể ngày 08/10/2026 đã thay thứ tự ưu tiên dưới đây; các ước lượng thời gian cũ được rút lại cho tới khi spike xác nhận khả năng tích hợp host.

Lát đã có: [CLI duyệt spec local](spec-review-cli.vi.md), có list/review/diff/approve/request-changes/history; kiểm chứng theo [coverage của lát này](proposal-coverage.md). Chưa coi các yêu cầu host, budget hoặc quyền worker dưới đây là đã hoàn thành.

## Thứ tự triển khai sau review tổng thể

1. **Hoàn thiện CLI:** cô lập spec lỗi để vẫn list/review được spec khác; đọc history từ sổ quyết định khi file hiện tại sai định dạng. Hai tình huống đã tái hiện; chưa sửa code. Xem SR02/SR03/SR06 trong coverage.
2. **Một task kiểm soát được:** ghim một host/backend, một repo mẫu; kiểm chứng status/cancel khi model bận, tổng budget không reset, gate đỏ không được accepted, dừng giữ artifact và khôi phục không chạy trùng. Chốt một chủ sở hữu phân rã/retry giữa Conductor và TaskRunner, cùng ranh giới approval ngoài quyền worker.
3. **Conductor tới bàn giao:** trao đổi → brief/spec → duyệt và quyền chạy → task đã kiểm soát → từng checkpoint có artifact/cách thử → khách hàng review từng phần → nghiệm thu bản ghép. Cho xem bản nháp theo yêu cầu; không đợi toàn task xong mới review. Kế hoạch triển khai và tiến độ lưu riêng, không sửa spec liên tục để buộc duyệt lại.
4. **Mở rộng tuần tự:** nhiều repo và Claude/Kiro/Codex vẫn là yêu cầu sản phẩm; chứng minh từng backend qua cùng contract sau luồng đầu. DeepSeek, registry đa máy và dashboard để giai đoạn sau.

Các bảng S/R/C/CN dưới đây là danh mục yêu cầu và ca kiểm chứng, không phải toàn bộ việc phải chạy song song trong lát đầu. Chưa chốt lịch hoặc phần trăm tiết kiệm token trước kết quả spike/benchmark. Mỗi lát kết thúc bằng evidence và phần còn thiếu, không tự mở lát kế tiếp khi vượt quyền/ngân sách đã giao.

## 0. Spike quyết định nền tảng

Baseline Kiro Crew phiên bản ghim với một backend đầu tiên; Claude là lựa chọn thử hiện có. Kiro/Codex được kiểm chứng lần lượt sau luồng đầu. DeepSeek là thử nghiệm giai đoạn sau, không âm thầm nâng main cho mọi việc.

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

## 1. CLI và visibility

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
| R29 — Đổi thứ tự công việc | Xếp lại việc chờ qua Conductor/CLI và cùng queue host; phân biệt ưu tiên với dependency/review gate; không tự ngắt việc đang chạy; chuyển ngay phải checkpoint và xác nhận dừng trước khi nhường ownership; giữ budget, artifact và approval còn hợp lệ, kiểm plan revision và ghi lịch sử thay đổi |

Không import tất cả worktree hiện có thành task đang chạy. Import ban đầu chỉ lập inventory để người dùng gắn task và quyết định giữ/dọn; không tự xóa hoặc di chuyển repo.

R29 chưa triển khai, nối vào luồng Conductor/host đã qua spike. Ca kiểm chứng: A/B đang chờ và độc lập thì chuyển B trước A; X đang chạy vẫn giữ nguyên khi chỉ đổi việc chờ. Yêu cầu dừng X để chuyển việc phải giữ checkpoint và chờ host xác nhận. B phụ thuộc A hoặc đang chờ review không được chạy sớm do ưu tiên mới. Plan revision cũ bị từ chối khi trạng thái thay đổi; lặp request không tạo task/vòng retry mới. Việc đã hoàn tất không chạy lại; chỉ đổi thứ tự không làm mất approval hay cấp thêm ngân sách.

## 2. Workflow và nghiệm thu

| Yêu cầu | Hoàn thành khi |
|---|---|
| R06 — Hai workflow | Quick-fix và feature có đường chạy ngắn/dài rõ ràng |
| R07 — Spec → evidence | Mỗi acceptance criterion gắn với kiểm tra hoặc review có nguồn |
| R08 — Gate bắt buộc | Output không hợp lệ, test fail hoặc timeout đều không thể thành accepted |
| R09 — Freshness | Đổi code/test/spec/gate sau verify làm kết quả thành stale |
| R10 — Triage | Phân biệt lỗi code, test, spec, môi trường, quota; retry có giới hạn |
| R11 — Integration | Sau khi ghép nhánh vẫn chạy gate trên kết quả ghép |
| R27 — Review output từng phần | Có checkpoint ở mốc đã chốt và theo yêu cầu xem sớm; thẻ ngắn kèm artifact/cách thử/evidence/điều chưa đạt; xem lại và diff đúng snapshot/revision, không bị worker ghi đè; bản nháp không được báo là đã nghiệm thu |
| R28 — Phản hồi theo phần và dependency | Accept/yêu cầu sửa gắn đúng output revision và AC; giữ lịch sử, bản mới không kế thừa approval vô điều kiện; chặn phần phụ thuộc cần quyết định nhưng tiếp tục phần độc lập được phép; sửa dùng chung budget và hoàn tất toàn task vẫn cần gate bản ghép |

Lấy OneTechAI làm mẫu cấu trúc, nhập chọn lọc theo manifest và hash. Không chạy `sync.py` global. Jev/Obsidian/AWS/construction không là dependency bắt buộc.

R27/R28 là yêu cầu mới, chưa triển khai, thuộc bước Conductor tới bàn giao. Ca kiểm chứng: công việc có phần A, phần B phụ thuộc A và phần C độc lập. Đưa A ra review khi task chưa xong; yêu cầu sửa A giữ B ở chờ nhưng không chặn C đang được phép chạy. Bản A2 có diff với A1; quyết định cho A1 không tự áp dụng A2. Review bản nháp gate đỏ không làm task accepted; sau chấp nhận A2 vẫn cần kiểm tra tích hợp. Nếu B đã chạy, phải giữ/đánh giá lại đầu ra ảnh hưởng trước khi cho tiếp tục. Không coi chưa trả lời là đã duyệt.

## 3. Đánh giá backend và giao diện

| Yêu cầu | Hoàn thành khi |
|---|---|
| R12 — Backend contract | Kiro, Claude và Codex qua được cùng suite; backend thiếu capability hiển thị rõ |
| R13 — DeepSeek thử nghiệm (giai đoạn sau) | Phiên bản hỗ trợ, gate/resume/cancel được kiểm chứng trên repo mẫu |
| R14 — Model routing | Ghi requested/observed model; chọn model có lý do, không im lặng fallback |
| R15 — Báo cáo | Accepted throughput, thời gian chờ, số lần người can thiệp và usage có thể so sánh |

Dashboard/App UI chỉ xét sau khi CLI, gate và luồng bàn giao đã chứng minh hữu ích. Ước lượng tổng 2–4 tuần trước review không còn là baseline kế hoạch; chỉ lập lại lịch sau khi spike xác nhận các seam tích hợp và phạm vi từng lát.

## Bộ đánh giá ban đầu

Bắt đầu bằng một task mẫu có đầu ra thử được và các biến thể gate fail/cancel/budget/recovery. Sau khi luồng này đạt mới mở bộ so sánh 8–12 việc: sửa lỗi nhỏ, đổi interface, migration có test, cập nhật tài liệu, review diff, tác vụ dài cần resume, xung đột file và lỗi môi trường. Không dùng dữ liệu vận hành nhạy cảm.

So sánh: quy trình Claude/OneTechAI hiện tại, Codex độc lập, Kiro Crew nguyên bản, OneCrew trên Crew; DeepSeek là nhánh thử bổ sung. Giữ cùng task, commit đầu vào và tiêu chí nghiệm thu. Chạy lặp khi ngân sách cho phép, ghi version/model/effort và độ biến thiên.

Các chỉ số đề xuất:

- Tỷ lệ task được accepted với evidence hợp lệ.
- Thời gian đến kết quả được chấp nhận, gồm thời gian chờ người.
- Số lần người phải nhắc, sửa kế hoạch hoặc cứu task.
- Số lần báo xong sai, xung đột worktree, task mất sau restart.
- Usage và chi phí ước tính trên mỗi task accepted, kèm cờ unknown.

Ngưỡng quyết định thử nghiệm: không có false-accepted trong suite; không mất task sau crash; mọi gate có hash và log; giảm ít nhất 30% số lần can thiệp so với baseline trên mẫu đã chọn. Mốc 30% là mục tiêu sản phẩm ban đầu, cần hiệu chỉnh sau dữ liệu thật.

## Bổ sung sau audit lịch sử 25/09–06/10

[Audit toàn bộ lịch sử local](claude-history-audit.vi.md) cho thấy cần đo giá trị bàn giao, ngoài việc quản lý process. Các mục này đi trước dashboard, ngoại trừ R24 đa máy được đưa sang giai đoạn sau; bản local vẫn phải giữ task/repo/owner không trùng:

| ID | Yêu cầu | Hoàn thành khi |
|---|---|---|
| R20 | Lát chức năng thử được | Task có luồng người dùng, SHA/package/cách thử và evidence; code/test xong không tự đồng nghĩa user acceptance |
| R21 | Giới hạn việc đang làm | Giới hạn theo chức năng sản phẩm, không chỉ số process; task con không mở scope mới ngoài plan |
| R22 | Ngân sách hợp nhất | Usage/budget cộng agent con và các workflow mới của cùng task; cache/thinking không đếm trùng; remote thiếu log hiện unknown |
| R23 | Tích hợp sớm | Môi trường mock, integration, UAT được ghi riêng; không dùng kết quả khảo sát thay nghiệm thu luồng sản phẩm |
| R24 | Registry đa máy (giai đoạn sau) | Task ID/owner/branch duy nhất; backend và extension demo cùng bản đã kiểm chứng; không có hai writer được claim cùng phạm vi |
| R25 | Kiểm soát scope | Worker không sửa scope/AC/budget; proposal ngoài phạm vi không tự được dispatch; cải tiến được đưa backlog |
| R26 | Reviewer có căn cứ | Lỗi chặn gắn AC/bất biến hoặc rủi ro nghiêm trọng với evidence; không tự thêm điều kiện phát hành |

Triển khai R25/R26 cùng R17/R20/R22 trước phần giao diện, theo [lát kiểm chứng phạm vi](scope-control.vi.md). Mở rộng workflow hoặc chuyển phiên không được tạo budget mới. Các ngưỡng review/checkpoint là cấu hình thử nghiệm, không làm mất yêu cầu chất lượng hoặc tự cho phép phát hành khi gate đỏ.

Baseline ban đầu nằm trong `claude-history-metrics.json`. Không so 70,46 triệu output token của bốn ngày với một task nhỏ mới để tuyên bố phần trăm tiết kiệm; benchmark phải giữ cùng phạm vi và tiêu chí nghiệm thu.

## Điều còn mở sau audit

Người dùng đã chốt lập trình trên nhiều repo với Claude/Kiro/Codex. Số máy/người dùng, cách trả tiền model và yêu cầu remote access chưa được xác nhận. MVP mặc định local, một người, nhiều repo. Những lựa chọn này không ngăn review, nhưng phải chốt trước khi mở rộng kiến trúc.

## Bổ sung: Conductor trao đổi và điều phối

Theo phản hồi ngày 08/10/2026, [Conductor trong kiến trúc](architecture.vi.md) là đầu mối để khách hàng trao đổi, truy vấn và chốt việc; các vai thực thi phía dưới tiếp nhận gói công việc đã duyệt. Các yêu cầu dưới đây chưa triển khai, tách khỏi coverage của CLI duyệt spec local; không lấy kết quả 16 test CLI để xác nhận Conductor.

| ID | Yêu cầu | Hoàn thành khi |
|---|---|---|
| CN01 | Trao đổi trước khi có task | Tiếp tục được hội thoại và brief có nguồn; giữ riêng quyết định khách hàng, giả định và gợi ý AI; hỏi thông tin không tự tạo task thực thi |
| CN02 | Truy vấn có căn cứ | Trả lời tình trạng/repo/blocker bằng nguồn và độ mới; thiếu dữ liệu báo chưa biết; query trực tiếp vẫn hoạt động khi model bận |
| CN03 | Chốt đề xuất dễ duyệt | Từ hội thoại tạo spec nháp hai phần, liên kết quyết định nguồn; khách hàng review/approve đúng revision qua cơ chế hiện có |
| CN04 | Bàn giao có giới hạn | Host chỉ nhận việc với spec revision và quyền chạy hợp lệ; task con giữ AC/non-goals/repo/budget của cùng mục tiêu; Conductor không tự duyệt hoặc tăng quyền |
| CN05 | Theo dõi tới bàn giao | Worker hoàn tất chưa tự thành user acceptance; Conductor đưa artifact/cách thử/evidence và phần chưa đạt; phản hồi ngoài scope không tự dispatch |
| CN06 | Ngân sách cho cả điều phối | Tính cả trao đổi/khảo sát và worker khi quan sát được; đổi phiên không reset; không gọi model lặp lại khi nhàn rỗi hoặc chỉ đọc trạng thái trực tiếp |

CN01/CN03 tạo lớp trao đổi và spec; luồng Conductor hoàn chỉnh chỉ nối dispatch sau khi spike host/control đạt. Ưu tiên hiện hành là các bước ở đầu tài liệu, thay đề xuất trước đó làm hội thoại trước kiểm chứng host. Việc ghi kế hoạch không tự cấp ngân sách hoặc khởi chạy các lát này.
