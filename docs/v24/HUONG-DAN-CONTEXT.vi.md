# Working context theo consumer (2.4-B)

Bản 2.4.0.dev1, mốc 2.4-B. Code: `onecrew/v2/working_context.py` (gọi từ `knowledge.for_native`, `common_executor`, `engine`). Test: `tests/test_v24_b_context.py` (sb01–sb10), `tests/test_v24_b_installed.py`.

## 1. OneCrew ghi gì

Mỗi attempt native được giao tri thức (gói `knowledge-package` của 2.3) hay đã đọc file qua 2.4-A thì có **một** sự kiện `knowledge.delivered` (lớp A, trên root `plan-ns:`), ghi ngay sau khi chọn tri thức và chạy yêu cầu đọc, **trước khi** khởi chạy worker:

```json
{"plan": "P1", "node": "C", "generation": 0, "attempt": "ATT-…", "task": "TASK-…",
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

Delta = so bản đã giao với cách chọn **bây giờ** (cùng code chọn gói, cùng consumer): mục đã bị thu hồi/lưu trữ/thay thế (`withdrawn` + lý do), mục đổi cách dùng hay có bản mới (`changed`: fact → lead, không còn áp dụng, phiên bản mới), mục bắt buộc mới liên quan (`added_mandatory`). Chỉ id và lý do, không kèm lịch sử hay văn bản cũ.

- **Ở điểm an toàn** (lượt continuation, hay thế hệ mới sau khi giữ/chạy lại): gói của attempt mới có `delta` so với attempt trước của node; mục đã thu hồi chỉ xuất hiện trong `delta.withdrawn`, không bao giờ trong `entries`/`requested`. Nếu attempt đang tiếp tục từ một candidate dở dựng khi mục đó còn được giao: `delta.recheck_partial: true`. Receipt ghi `knowledge.delta`.
- Không có kênh gửi giữa lúc worker đang chạy (adapter chạy một lần, không giữ phiên): delta chỉ đến ở điểm an toàn.

## 3. Consumer đang chạy hay đã xong nhưng chưa kiểm

Trước khi một candidate được công bố là kết quả của node (`engine.step`, nhận candidate sau crash, thả candidate giữ lại hay đã tạm dừng) và trước khi kiểm (`engine.verify`), OneCrew kiểm lại bản đã giao của nó và của các node sinh ra artifact mà nó dùng:

| Thay đổi | Quyết định |
|---|---|
| mục `must` hay `fact` đã giao bị thu hồi/thay thế/lưu trữ | kiểm lại |
| mục đã giao là `fact` nay không còn là fact, hay có bản mới | kiểm lại |
| mục `must` có bản mới | kiểm lại |
| có mục bắt buộc mới liên quan tới node | kiểm lại |
| file đã đọc qua 2.4-A đổi trong cây làm việc | kiểm lại (chuỗi mới, ghim lại cây) |
| artifact đầu vào được dựng trên thay đổi như trên | kiểm lại |
| mục `lead` đổi hay bị thu hồi; lead thành fact | chỉ ghi chú |
| không có gì đổi | công bố như cũ |

"Kiểm lại" = candidate không được công bố là hiện hành: được giữ (`node.result_retained`) và node chạy tiếp ở thế hệ mới nhận delta (`node.resumed`, `budget_reset: false`, `knowledge_changed`), trong ngân sách còn lại của root và tối đa 2 lần cho một node; quá giới hạn hay hết ngân sách thì giữ node (`node.held`, `knowledge_changed`) chờ quyết định. `verify` trên candidate như vậy bị từ chối và không ghi kết quả kiểm. Kết quả đến muộn sau khi thế hệ đã chuyển vẫn không được công bố (như trước).

## 4. Ai bị ảnh hưởng

`knowledge.affected_consumers(ledger, plan | None, ids)` trả các node chưa kiểm xong có bản giao chứa id đổi, và các node phụ thuộc **đã dùng artifact** của chúng (`via`). Nhánh độc lập không bị đụng. Lệnh chỉ đọc:

```
onecrew wiki consumers --plan P1
```

liệt kê mỗi node mở: thế hệ, attempt, gói, revision, id đã giao, trạng thái (`none`, `withdrawn`, `changed`, `added_mandatory`, `source_changed`, `input_changed`) và delta. Lệnh không cấp hay từ chối gì.

## 5. Không tuyên bố

- Bản ghi giao, delta và ACK chỉ chứng minh **đã giao gì**, không chứng minh worker đã hiểu hay đã dùng đúng; `check_use` vẫn là kiểm cấu trúc, checks của node mới phán kết quả.
- Không có phiên model giữ lâu; không tuyên bố xóa được thứ model đã "nhớ" trong lượt chạy cũ — chỉ bảo đảm lượt sau không nhận lại mục đã thu hồi và kết quả cũ không được công bố như hiện hành.
- Kiểm áp dụng được tính trên cây làm việc hiện tại (thay đổi chưa commit cũng tính). Một khoảng rất ngắn giữa lúc kiểm và lúc ghi sự kiện công bố không bị khóa chung.
- Mọi kiểm ở mốc này dùng worker giả; chưa có bằng chứng với model thật.
