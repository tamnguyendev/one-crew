# Working context theo consumer (2.4-B)

Bản 2.4.0.dev1, mốc 2.4-B. Code: `onecrew/v2/working_context.py` (gọi từ `knowledge.for_native`, `common_executor`, `engine`). Test: `tests/test_v24_b_context.py` (sb01–sb10), `tests/test_v24_b_installed.py`.

## 1. OneCrew ghi gì

Mỗi attempt native được giao tri thức (gói `knowledge-package` của 2.3) hay đã đọc file qua 2.4-A thì có **một** sự kiện `knowledge.delivered` (lớp A, trên root `plan-ns:`), ghi ngay sau khi chọn tri thức và chạy yêu cầu đọc, **trước khi** khởi chạy worker:

```json
{"plan": "P1", "node": "C", "generation": 0, "attempt": "ATT-…", "task": "TASK-…", "base": "<snapshot worker đã thấy>",
 "package": "<blob của gói>", "revision": "<revision của gói>", "delivered": ["ctx-…"],
 "entries": [{"id": "ctx-…", "use": "fact", "must": true, "event": 41, "sources": [{"path": "a.txt", "blob": "<git blob>"}]}],
 "consumer_paths": ["a.txt"], "sources_read": {"tree": "<cây đã ghim>", "blobs": {"src/lib/x.py": "<git blob>"}},
 "delta": {"…": "khi có"}, "grants_authority": false}
```

- Một bản cho mỗi attempt (ghi lại khi khởi động lại không tạo bản thứ hai). Dựng lại candidate sau khi controller chết không ghi lại: bản đã ghi là sự thật về những gì đã giao.
- Node không được giao gì (không tri thức, không đọc file) thì không có sự kiện; prompt, schema, receipt của node đó giữ như 2.3.
- Intent `dispatching` của executor có quản lý trỏ tới sự kiện này (`knowledge_delivered`), không chép lại.
- Không có kho mới: chỉ sổ và blob gói.

## 2. Delta là gì

Delta = so bản đã giao với cách chọn **bây giờ** (cùng code chọn gói, cùng consumer), **trên đúng những file worker đã thấy** (snapshot `base` của attempt: ảnh chụp lúc bắt đầu + artifact đầu vào + candidate dở được mang theo), không phải cây làm việc trơn: mục đã bị thu hồi/lưu trữ/thay thế (`withdrawn` + lý do), mục đổi cách dùng hay có bản mới (`changed`: fact → lead, không còn áp dụng, phiên bản mới), mục bắt buộc mới liên quan (`added_mandatory`). Chỉ id và lý do, không kèm lịch sử hay văn bản cũ.

- **Ở điểm an toàn** (lượt continuation, hay thế hệ mới sau khi giữ/chạy lại): gói của attempt mới có `delta` so với attempt trước của node; mục đã thu hồi chỉ xuất hiện trong `delta.withdrawn`, không bao giờ trong `entries`/`requested`. Nếu attempt đang tiếp tục từ một candidate dở dựng khi mục đó còn được giao: `delta.recheck_partial: true`. Receipt ghi `knowledge.delta`.
- Không có kênh gửi giữa lúc worker đang chạy (adapter chạy một lần, không giữ phiên): delta chỉ đến ở điểm an toàn.

## 3. Consumer đang chạy hay đã xong nhưng chưa kiểm

Trước khi một candidate được công bố là kết quả của node (`engine.step`, nhận candidate sau crash, thả candidate giữ lại hay đã tạm dừng), trước khi kiểm (`engine.verify`) **và lần nữa ngay trong giao dịch ghi kết quả kiểm**, OneCrew chạy **một** hàm quyết định (`working_context.decide`) — cũng là hàm các lệnh xem dùng:

| Thay đổi | Quyết định |
|---|---|
| mục `must` hay `fact` đã giao bị thu hồi/thay thế/lưu trữ | kiểm lại |
| mục đã giao là `fact` nay không còn là fact, hay có bản mới | kiểm lại |
| mục `must` có bản mới | kiểm lại |
| có mục bắt buộc mới liên quan tới node (node không được giao gì: mục bắt buộc trong sổ ghi sau khi attempt bắt đầu) | kiểm lại |
| file có nội dung đã vào prompt qua 2.4-A (đọc, dòng search, danh sách) đổi trong project | kiểm lại: ghim lại cây, mang theo candidate, có lượt đọc mới |
| chỉ artifact đầu vào được dựng trên thay đổi như trên, trực tiếp hay qua bất kỳ chuỗi đầu vào nào; hay chuỗi đầu vào không kiểm hết được (biên nhận thiếu hoặc không đọc được, attempt sinh hay bản ghi bắt đầu không có trong sổ, vòng lặp, quá `MAX_WALK`) | **giữ ngay** (`input_changed`, nêu node sinh và id, hay điều không kiểm được), không gọi model |
| mục `lead` đổi hay bị thu hồi; lead thành fact | chỉ ghi chú |
| không có gì đổi | công bố như cũ (thế giới không đổi luôn cho `publish`) |

"Kiểm lại" = candidate không được công bố là hiện hành: được giữ (`node.result_retained`) và node chạy tiếp ở thế hệ mới nhận delta (`node.resumed`, `budget_reset: false`, `knowledge_changed`, mang theo candidate), trong ngân sách còn lại của root và tối đa 2 lần cho một node; quá giới hạn hay hết ngân sách thì giữ node (`node.held`, `knowledge_changed`) chờ quyết định. Đổi trong lúc checker chạy: biên nhận kiểm được giữ ("changed while the checker ran"), không ghi `node.verification`, node kiểm lại.

"Giữ ngay" (`input_changed`): chạy lại node phụ thuộc trên cùng đầu vào không giúp gì; cũng kiểm trước khi giao node đi (node chưa chạy cũng bị giữ, không gọi model). Sửa là mở lại node sinh (đường sửa có sẵn: quyết định của chủ dự án / engine cho node sinh), rồi node phụ thuộc chạy trên artifact mới.

## 4. Ai bị ảnh hưởng

`knowledge.affected_consumers(ledger, plan | None, ids)` trả các node chưa kiểm xong mà quyết định (cùng hàm với cổng) nêu id đổi: của chính nó, hay `via` node sinh artifact nó đã dùng hoặc sẽ dùng — kể cả khi node sinh đã được kiểm. Chỉ root đang mở; theo attempt hiện tại của node. Nhánh độc lập không bị đụng. Lệnh chỉ đọc:

```
onecrew wiki consumers --plan P1
```

liệt kê mỗi node mở: thế hệ, attempt, gói, revision, id đã giao, trạng thái (`none`, `withdrawn`, `changed`, `added_mandatory`, `source_changed`, `input_changed`) và delta. Lệnh không cấp hay từ chối gì.

## 5. Không tuyên bố

- Bản ghi giao, delta và ACK chỉ chứng minh **đã giao gì**, không chứng minh worker đã hiểu hay đã dùng đúng; `check_use` vẫn là kiểm cấu trúc, checks của node mới phán kết quả.
- Không có phiên model giữ lâu; không tuyên bố xóa được thứ model đã "nhớ" trong lượt chạy cũ — chỉ bảo đảm lượt sau không nhận lại mục đã thu hồi và kết quả cũ không được công bố như hiện hành.
- Tri thức được xét trên snapshot worker đã thấy; file đã đọc qua 2.4-A được so với cây làm việc hiện tại (thứ lần ghim sau sẽ thấy), thay đổi chưa commit cũng tính. Cổng chạy trong giao dịch ghi sự kiện công bố, nên một thu hồi đồng thời trong sổ phải chờ; sửa trang wiki hay file nguồn không bị khóa chung (khoảng dưới một giây).
- Giới hạn đã biết (review B-R08): `MAX_RECHECKS` đếm mọi lần kiểm lại của node trong đời root (kể cả trước một lần revise hay chủ dự án cho chạy tiếp); ghi bản giao lỗi thì attempt dừng trước khi chạy (đóng an toàn); mục chỉ xuất hiện trong `omitted.index` (tiêu đề) không được ghi nên thu hồi chúng không gây kiểm lại; commit trang wiki thêm mục `must` có thể làm mọi node đang chạy liên quan kiểm lại tới 2 lần rồi giữ (trong quyền của người commit wiki); mẫu quyền đọc có `[` chữ vẫn được đọc như glob; `affected_consumers` là hàm thư viện và lệnh xem, không phải kênh báo tự động.
- Mọi kiểm ở mốc này dùng worker giả; chưa có bằng chứng với model thật.
