# SPEC-004 — OneCrew tự thực hiện task local từ đầu đến bàn giao

## Duyệt nhanh

### Kết quả
Giao một yêu cầu bằng CLI; OneCrew tự lập spec/plan, chọn model, tạo code, test, review, sửa và bàn giao bằng chứng.

### Phạm vi
Một host local, Codex CLI, profile form CV từ thư mục trống. Kiểm thử trong sandbox Windows hoặc Docker. Chế độ autonomous là quyền chạy kỹ thuật trong brief, không giả danh khách hàng approve.

### Không làm
Không tự deploy, lấy secret, tăng budget, thêm nghiệp vụ, dashboard, Claude/Kiro adapter hay khẳng định mọi task luôn thành công.

### Nghiệm thu
Một lệnh chạy qua tất cả bước không cần người sửa code sản phẩm. Gate độc lập kiểm code thật. Fail được sửa có giới hạn hoặc báo chưa đạt; không đổi test để xanh. Có status, cancel và snapshot mỗi phần.

### Lưu ý
100% tự vận hành nghĩa là host tự thực thi các bước trong quyền đã giao, không phải bảo đảm 100% chất lượng/chặn bot. Thiếu dịch vụ thật được giữ là blocker.

### Ngân sách
Tối đa 20 phút/run, 8 lượt model, 2 vòng sửa; từng model mặc định 240 giây, có thể cấu hình trước run tới 600 giây trong trần chung. Không auto reset quota. Usage báo được thì cộng dồn; USD unknown.

### Cần quyết định
Không có.

## Chi tiết cho AI

Nguồn: người dùng yêu cầu “không, tôi muốn OneCrew tự vận hành 100%”, sau khi xác nhận lượt CV trước do assistant triển khai thay runtime. Yêu cầu này cho phép thực hiện quy trình kỹ thuật tự động trên task local đã giao. Không suy ra quyền public website hay customer acceptance.

- AR01: `task run --autonomous` nhận brief và output mới, giữ grant/hash/profile/budget bất biến ngoài worker; planner tạo spec đọc nhanh và task dependency có kiểu; policy từ chối plan sai.
- AR02: Router code dùng kind/risk từ plan, áp mức tối thiểu của profile và policy registry. Ghi requested model/effort/reason; không gọi AI cho status/counter. Chưa benchmark tối ưu chi phí; không gọi Jev khi thiếu credentials.
- AR03: Codex chỉ nhận snapshot và trả JSON artifact; host validate schema/ownership/path/size trước ghi. Worker không được sửa gate/policy/state. Tạo checkpoint có hash từng phần.
- AR04: Một controller giữ deadline/call/repair budget, theo dõi process và usage; cancel/timeout dừng process tree; không ghi success trước khi exit. Lỗi provider không mở retry vô hạn. Trạng thái crash không giả hoàn tất.
- AR05: Gate HTTP host-owned có hash, không do builder sửa. Windows dùng Codex native sandbox chặn ghi ngoài workspace, thêm Node guards giới hạn fs/child-process và preflight kiểm thực quyền. Đây không phải VM cho mã cố ý độc hại; Windows cần baseline đọc root, Node guards không được quảng cáo là ranh giới chống malicious code. Docker Linux là adapter khác với non-root, code mount read-only, data tmpfs và internal network. Adapter không qua preflight thì báo blocked trước model calls.
- AR06: Gate fail → sửa tự động với lỗi cụ thể; review semantic có typed finding gắn AC; ngoài scope thành backlog. Tối đa 2 repair, fingerprint phát hiện không tiến triển. Gate và reviewer cùng đạt mới ready_for_review.
- AR07: Bàn giao manifest/checkpoints/report/cách chạy/commit do host tạo. Execution, verification, acceptance tách riêng; không auto-accept sản phẩm. CLI đọc trạng thái/list/output không gọi model.
- AR08: Test failure modes, CLI regression, một live run từ thư mục trống. Trong live run không có assistant sửa source sản phẩm thủ công; nếu cần sửa runtime ghi minh bạch. Bằng chứng phải phân biệt simulation/live và các dependency thật còn thiếu.

Profile CV dùng Node 24 built-in HTTP + SQLite và HTML/CSS/JS, không cài dependency từ worker. Đây là bản riêng để chứng minh quy trình, không copy source app Next.js đã viết thủ công. API contract chuẩn hóa trước test: session → prepare → verify → commit; PDF 5 MiB, demo local có nhãn, mode locked mặc định, Turnstile thật ràng buộc hostname/action/cdata. Không có AV/domain thật nên không phát hành/nhận CV thật.

Thiết kế rộng hơn (multi-repo, reorder, hội thoại tự do, pause/resume đa backend) vẫn là roadmap; không gộp vào tuyên bố hoàn thành lát này. Một local runner là host duy nhất của run, không chạy queue Kiro song song.

Điều chỉnh môi trường trong lượt xây runtime: Docker Linux Engine không hoạt động. Lượt preflight RUN-20261008-211020-297f61 dừng với 0 model calls. Chuyển adapter kiểm thử sang sandbox Windows có sẵn sau khi kiểm quyền ghi ngoài workspace, quyền đọc sentinel và spawn subprocess. Không thay code sản phẩm, AC hay tăng số lượt model của run đang thực thi; run mới ghi rõ adapter và phiên bản gate riêng.
