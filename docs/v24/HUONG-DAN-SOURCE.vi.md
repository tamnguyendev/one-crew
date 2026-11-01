# Worker tự đọc nguồn theo quyền (2.4-A)

Bản 2.4.0.dev1, mốc 2.4-A. Code: `onecrew/v2/source_tools.py`. Test: `tests/test_v24_a_sources.py` (sa01–sa11), `tests/test_v24_a_installed.py` (sa12).

## 1. Dùng khi nào

Node cần đọc nhiều file hơn số file liệt kê trong `read` (thư viện phụ thuộc, tài liệu, dữ liệu), nhưng không muốn nhét cả repo vào prompt hay chia task theo 50 KB. Node bật tính năng này thì worker xin đọc từng phần; OneCrew kiểm quyền rồi đưa trang kết quả có nguồn ở lượt sau. Node không khai `sources` chạy y như 2.3 (prompt, schema, receipt, `node.started` giống từng byte).

## 2. Khai báo

**Root (hợp đồng, chủ dự án duyệt):** thêm `read` vào khối `authority` — danh sách thư mục, file hoặc glob mà worker của root được đọc:

```json
"authority": {"edit": true, "commands": true, "self_decide": ["Q1", "Q2", "Q3"],
              "read": ["src/**", "docs/", "data/"]}
```

Không có `authority.read` thì quyền đọc là `scope.owned` + `understanding.target.paths`, không bao giờ "cả project"; mục nào của `target.paths` không phải đường dẫn (chữ mô tả) bị từ chối và nêu trong `scope.refused_grant`, không âm thầm khớp với không gì. Khi root khai `authority.read`, cả danh sách `read` của node (file đưa nguyên vào prompt) cũng phải nằm trong `authority.read` ∪ `scope.owned`, nếu không revise từ chối; root không khai `authority.read` giữ cách của 2.3 cho `read`. Không cấp được đường dẫn điều khiển hay bí mật (`.git`, `.onecrew`, `.ssh`, `.aws`, `.env*`). Hợp đồng không có `read` giữ nguyên sha.

**Node (plan nội bộ):** thêm `sources`:

```json
{"id": "C", "goal": "...", "read": ["src/main.py"], "write": ["out.txt"],
 "sources": {"read": ["src/"], "max_rounds": 4, "max_chars_per_round": 40000}, "...": "..."}
```

- `read`: 1–40 thư mục/file/glob; phải nằm trong quyền đọc của root, nếu không `internal_plan.revise` từ chối (mở rộng quyền là quyết định của chủ dự án).
- `max_rounds`: 1–20 (mặc định 4) — số lượt đọc (attempt kết thúc bằng `continuation`) của node, đếm trên mọi receipt đã giữ của node trong root (mọi chuỗi, sau giữ/chạy lại). Đây là trần cứng: sau `max_rounds` lượt, câu trả lời kế phải là kết quả cuối; trả `continuation` nữa thì node bị giữ (`node.held`, `rounds_exhausted`, bằng chứng là các receipt của các lượt).
- `max_chars_per_round`: 2 000–200 000 (mặc định 40 000) — ký tự kết quả tối đa mỗi lượt.
- Node vẫn cần ít nhất một file trong `read` ∪ `write` như trước.

Được đọc = thuộc `sources.read` **và** quyền root **và** chính sách đọc (không thư mục điều khiển, công cụ, `node_modules`, `build`…) **và** nội dung là văn bản không chứa thông tin đăng nhập.

## 3. Worker xin gì

Lượt đầu worker nhận `source_tools` trong prompt: chỉ dẫn ngắn, cây đã ghim (`tree`, `head`), phạm vi, số lượt còn, và danh mục (list của toàn phạm vi). Muốn đọc thêm, worker trả `continuation` kèm `source.requests` (tối đa 8):

| op | tham số | trả về |
|---|---|---|
| `list` | `path?` (thư mục, `""` = cả phạm vi) | file, kích thước, blob id; tối đa 200/lần |
| `search` | `query`, `path?` | dòng khớp (chữ, không phân biệt hoa thường), coverage; 500 file / 4 MB / 100 dòng mỗi lần |
| `read` | `path` | văn bản, dòng và ký tự bắt đầu/kết thúc, blob id; 12 000 ký tự/lần, cắt ở cuối dòng |
| `page` | `index`, `field`, `offset` | phần tiếp của một kết quả bị cắt trong prompt (chép `page.next`) |
| (mọi op) | `cursor` | tiếp tục đúng chỗ (chép `next_cursor`) |

Yêu cầu chạy ở lượt sau, trên **cùng cây đã ghim** ở lần chạy đầu của chuỗi (file sửa dở và file chưa commit cũng có, hard link và junction bị từ chối). Kết quả đầy đủ lưu trong blob `source-results`; prompt chỉ mang trang vừa ngân sách (Claude/Codex 80 000 ký tự cả prompt, Kiro 15 000 tính cả schema; tri thức giữ phần của nó). Node báo cáo có thể dẫn blob kết quả (`results_blob`) làm `evidence`.

## 4. Bị từ chối hoặc giữ lại

- Ngoài phạm vi, `..`, đường dẫn tuyệt đối/ổ đĩa/UNC (`/etc/x`, `C:/x`, `//host/x`), dấu `\`, tên điều khiển/bí mật: kết quả `refused`, không có byte nào. Ký tự glob trong đường dẫn yêu cầu là chữ thường (không mở rộng). Tên trong cây phân biệt hoa thường; sai hoa thường thì có gợi ý `case_sensitive_tree`.
- Mọi tên Git hợp lệ (`[`, `*`, `?`, `~`, đường dẫn dài, sâu) được khớp đúng như tên; file trong phạm vi mà không phục vụ được có dòng `withheld` với lý do: tên dạng 8.3 (`control_name_alias`, như `backup~1.txt`, cùng một câu trả lời ở list/search/read), dài quá 1 000 ký tự (`too_long`).
- File nhị phân, chứa thông tin đăng nhập, link, quá 2 MB, thư mục bị loại: dòng `withheld` có lý do (`binary`, `secret`, `link`, `too_large`, `excluded`); tên file có dạng bí mật chỉ hiện thư mục. Search rỗng mà còn file bị giữ hoặc chưa quét hết thì kết luận là "không thấy trong phần đã quét", không phải "không tồn tại".
- Cursor của cây khác: "source changed; list again". Cursor của phạm vi khác: "read scope changed; list again".
- Yêu cầu lặp lại đúng yêu cầu đã chạy cho node trên cùng cây (so theo yêu cầu thực: op, đường dẫn, query không phân biệt hoa thường, vị trí; cursor tự dựng ở vị trí 0 cũng là lặp), yêu cầu không kèm `continuation`, quá 8 yêu cầu (quá 16 mục thì phần còn lại bị từ chối trong một dòng có số đếm), quá `max_rounds`, hay sau khi bộ đếm lặp/khám phá của v1 (progress_core) dừng: ghi vào `source.refused` của receipt. Trang tiếp và `next_cursor` là phủ mới, không bị coi là lặp.
- Nội dung nguồn là dữ liệu, không phải quyền: không đổi hợp đồng, phạm vi hay yêu cầu; chỉ code quyết định yêu cầu nào chạy.
- Project không phải cây Git (hoặc không ghim được): `source_tools: {capability: "unavailable", reason}`; node chạy như 2.3, không có phần xin đọc.

## 5. Đếm và khôi phục

- Mỗi lượt đọc là một attempt mới của chuỗi continuation (task con mới, một lần gọi model), tính trong ngân sách chung của root như mọi attempt.
- `max_rounds` và bộ nhớ lặp lấy từ mọi receipt đã giữ của node trong sổ: đổi controller, chạy lại process, task con mới, giữ rồi chạy tiếp hay chuỗi mới đều không reset. Chuỗi mới được ghim lại cây (ghi `previous_tree` khi cây khác); đọc lại cùng file trên cây khác không phải lặp. Receipt hay blob kết quả của node không đọc được: lượt bị từ chối (`chain_problem`), không chạy yêu cầu nào, node bị giữ nếu xin thêm lượt; bộ đếm không bao giờ bị đặt lại.
- Chết giữa lúc xin và lúc có kết quả: lần chạy lại thực thi đúng các yêu cầu đã niêm phong (cùng blob kết quả), không gọi model thêm, không cần dòng intent.
- Receipt `native-node-receipt` có thêm `source` {tree, head, scope, results, count, delivered_chars, pages, not_delivered (kết quả không vào prompt), execution_refused (yêu cầu bị từ chối lúc chạy), withheld_total, requests, refused, rounds_used, max_rounds, progress, previous_tree?, rounds_exhausted?} và `source_requests` (các yêu cầu cho lượt sau).
- Node ghi file: lượt đọc giữa chừng được phép không có file; câu trả lời cuối vẫn phải có ít nhất một file như 2.3 (đã đọc rồi không ghi gì thì bị từ chối).
- Search: dòng bị cắt có `text_truncated` {delivered, total}; file có hơn 20 dòng khớp được đọc tiếp bằng `next_cursor` trong cùng file.

## 6. Giới hạn đã biết

- Một lượt đọc = một lần chạy CLI của worker (không có vòng tool trong một attempt); nên gom yêu cầu.
- Cây ghim một lần cho cả chuỗi; muốn thấy nguồn mới thì node cần thế hệ mới (revise plan) — cursor cũ khi đó bị từ chối.
- Chuỗi là chuỗi continuation (`continues`). Node bị giữ rồi được chủ dự án cho chạy tiếp, hay được thay sau khi controller chết (`executor recover`), bắt đầu chuỗi mới như 2.3 (bản dở cũng bị bỏ): cây được ghim lại, nhưng bộ đếm lượt và bộ nhớ lặp vẫn theo node (xem §5).
- Quay về bản 2.3 trên sổ có root khai `authority.read`: wheel 2.3 từ chối hợp đồng đó (`authority: unknown fields read`); quay về cần root không có khóa này.
- Khôi phục "chết giữa yêu cầu và kết quả" là chạy lại đúng attempt đã đặt chỗ (như T08b điểm a); engine chưa tự chạy lại một attempt native còn ở trạng thái `reserved` (giới hạn có từ 2.3).
- Bộ theo dõi tiến độ của node thấy các lượt đọc không đổi file như "không có thay đổi"; engine chỉ xét nó ở kết quả cuối.
- Adapter nguồn hiện chỉ có cây Git; log/dữ liệu ngoài repo (manifest blob) để sau.
- Mọi kiểm ở mốc này dùng worker giả; chưa chứng minh model thật dùng tốt giao thức.
