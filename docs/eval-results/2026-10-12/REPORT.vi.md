# Kết quả eval OneCrew — 12/10/2026

Đã có lớp eval dùng lại được, corpus 10 case đã gặp và phép đo trước–sau có bằng
chứng. Runtime hiện tại đạt cả 10 case, mỗi case chạy hai lần. Đây là kết quả
**contract/workflow fixture**, chưa phải tỷ lệ tự hoàn thành sản phẩm thật.

## Đo trước–sau trên cùng harness

Harness cố định `d24cc52`; 20 probe test trong 10 case, 2 lượt mỗi case,
cùng Python 3.13/Windows và timeout 120 giây mỗi probe. Không gọi model, Flutter,
ADB hoặc server thật. Các lệnh native cần thiết của fixture được mock trong oracle.

| Phép đo | Trước | Sau | Kết luận được phép |
|---|---:|---:|---|
| Hai revision runtime: `3c3de4a` → `4e8253f` | 6/10 case, 12/20 case-trials | 10/10 case, 20/20 case-trials | Thêm 4 nhóm contract của workflow tổng; 6 nhóm cũ giữ đạt |
| Baseline riêng ngay trước từng fix | 0/10 case | 10/10 case | Hai lỗi tái hiện được; tám baseline thiếu API. Không phải một tỷ lệ tăng trưởng release |
| Task sản phẩm thật không cần entry | Chưa có mẫu chuẩn tương đương | Chưa có mẫu chuẩn tương đương | Không có tỷ lệ tự chủ hoặc kết luận nhân quả |

Không có khác biệt giữa hai lượt lặp của cùng case trong lần đo cuối. Hai lượt
fixture chỉ kiểm độ lặp của harness; không đo độ biến động model. Thời gian probe
không đại diện cho thời gian làm task, chi phí model hoặc tốc độ E2E.

[So release](release-comparison.md), [so từng baseline lịch sử](historical-comparison.md).
JSON đầy đủ: [release-before](release-before.json), [historical-before](historical-before.json),
[after](after.json). Các file giữ nguyên digest, từng probe, commit và diagnostic.

## Case nào đã chứng minh điều gì?

| Case | Bằng chứng ở baseline lịch sử | Hiện tại / giới hạn |
|---|---|---|
| Bàn giao backlog | Tái hiện chính xác `KeyError: 'backlog'` trong `Workflow.outputs` | Outputs đọc được state owned |
| Cache thiếu | `GateUnavailable` không được ném khi thiếu `test_api` | Chặn trước compiler, giữ candidate; **không** tự phục hồi cache |
| Timeout checkpoint | API checkpoint chưa có ở baseline | Resume, giữ session/budget và từ chối không tiến triển; provider/compiler fixture |
| Metadata >2 MB | API evidence/chunk chưa có | Roundtrip, hash và source cap được kiểm |
| Review >80k | Module paging chưa có | Giữ đủ diff/tests, từ chối evidence bị sửa; chưa đo chất lượng suy luận reviewer |
| Windows một lần | Module desktop chưa có | Dedup theo outcome, launcher mock; không mở cửa sổ thật trong replay |
| Parent checkpoint | Module parent chưa có | Giữ node đã xác minh, invalidation và side effect chưa rõ |
| Parent handover | Module parent chưa có | Parent chạy lifecycle child→gates→report với model/Flutter/ADB fixture |
| Review gate | Module parent chưa có | Chặn conditional review và thiếu evidence bắt buộc |
| APK/device gate | Module device chưa có | Kiểm APK identity/signer/ZIP và foreground với fixture |

Tám `capability_unavailable → passed` là bằng chứng capability mới chạy được oracle
hiện tại, **không** phải tám lần đã tái hiện đúng lỗi sản phẩm cũ. Oracle chứa các
test từng dùng khi phát triển; toàn bộ corpus là `known_case`, không phải held-out.
Không hạ tiêu chí hoặc loại case khỏi mẫu số sau khi thấy kết quả.

## Đối chiếu bốn task thật

Đọc ledger ở chế độ read-only, không resume/ACK/chạy lại test. Mẫu được chọn từ task
đã nhắc trong cuộc trao đổi này, không đại diện cho toàn bộ công việc OneCrew.
Event seq/hash và chi tiết từng gate nằm trong [observed.json](observed.json),
bản ngắn [observed.md](observed.md).

| Task | Calls ghi nhận | Timeout checkpoint | Hỗ trợ ghi nhận | Những gì ledger chứng minh |
|---|---:|---:|---|---|
| `TASK-8c1aa253…` | 2 | 0 | Unknown | Code/test/review/apply/report; chưa có build/device/Windows receipt tương ứng |
| `TASK-b9a0c151…` | 5 | 2 | Sửa runtime bởi entry, 1 repair record | Code/test/review/apply/report, Windows receipt; chưa có build/device trong task |
| `TASK-726bd48f…` | 3 | 1 | Sửa runtime bởi entry, 3 repair records; entry kiểm device/server | Có debug APK receipt và Windows receipt; device evidence thuộc entry |
| `TASK-1e6d37de…` | 3 | 1 | Unknown | Code/test/review/apply/report và Windows receipt; chưa có build/device trong task |

Tất cả có `phase=completed`, nhưng không task nào trong mẫu này đủ dữ liệu để
chứng nhận **OneCrew tự hoàn thành toàn bộ sản phẩm mà không cần entry**. Đây là
thiếu bằng chứng theo rubric, không phải kết luận mọi task đều thất bại.

`entry-runtime-repair` chưa xác định đầy đủ actor là Codex hay Claude; không gán
nhầm cho một host. Không có note cũng không nghĩa là không được giúp. Các test
receipt cũ không có tổng số test/skip có cấu trúc, nên không suy từ chữ “passed”
trong report thành mọi tiêu chí đều đạt. Artifact/thiết bị chưa được kiểm lại ở
lượt observe này. `closed/shown` của Windows không chứng minh người dùng đã đọc.

## Còn cần hỗ trợ và cải thiện ở đâu?

1. **Môi trường:** cache/SDK/config đúng phiên bản còn cần chuẩn bị hoặc recovery
   được duyệt. Oracle hiện chỉ chứng minh OneCrew giữ dữ liệu và block đúng khi thiếu.
2. **Lỗi runtime ngoài recipe:** lịch sử timeout/review/snapshot có can thiệp entry.
   Runtime mới vượt các contract liên quan, nhưng chưa có lần live hoàn chỉnh chứng
   minh từ đây các can thiệp đó không còn cần thiết.
3. **Bài test sản phẩm độc lập:** lỗi geometry/keyboard và đăng nhập thật cần oracle
   vượt khỏi báo cáo worker; không được dùng “review accepted” làm tiêu chí duy nhất.
4. **Môi trường E2E được pin:** workflow có build/device nodes, nhưng cần baseline,
   signer, serial, scenario, config và thiết bị rảnh. Chưa chạy paired live pilot này.
5. **Nhật ký hỗ trợ:** đã thêm `eval assistance` để ghi actor/category/checkpoint
   ngay khi entry phải can thiệp; parent tổng hợp cả task con/calls. Điều này tránh
   việc tới cuối lượt mới nhớ lại ai đã làm hộ bước nào.

Hướng nghiệm thu tiếp theo và lệnh dành cho Claude ở [hướng dẫn eval](../../evals.vi.md).
Đo live/held-out (EV07) còn Blocked vì chưa có bộ task chưa thấy và dispatch thiết bị
được pin cho phép chạy cặp tương đương. Không tự khởi chạy lại task Cloud Auth đang
do entry khác quản. Không tự approve lesson/skill/routing từ kết quả này.

## Chất lượng của chính harness

Hai lỗi harness đã được phát hiện và sửa trước lần đo cuối: đọc Python Store alias
như file PE; và profile/temp isolation dẫn đến fallback home trên đường dẫn dài.
Kết quả thử ban đầu giữ tại `D:\OneCrewEvals\2026-10-12`, **không** trộn vào bảng
trước–sau trên. Lần cuối nằm tại `D:\OneCrewEvals\2026-10-12-final`.

Test grader kiểm mismatch corpus/harness/environment, thiếu/trùng case, skip,
expected failure, false pass, runtime import nhầm từ harness, timeout, read-only
ledger, stale receipt, privacy projection và assistance idempotency. Suite cuối: **120 test đạt, 0 skip, 39.662 giây**. Cả 6 JSON evidence qua kiểm digest; hai comparison được tính lại từ raw results và khớp hoàn toàn. Commit evidence được ghi trong phần EV của `docs/proposal-coverage.md`.

Các commit triển khai: `fb14591` (EV01–EV05), `18888ab` (Python Store fingerprint),
`d24cc52` (cách ly/probe grading và assistance). Không push hoặc thay đổi task sản phẩm.
