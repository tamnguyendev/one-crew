# Wiki của project trong OneCrew 2.3 — cách dùng và cách kiểm

Áp dụng cho bản `2.3.0.dev1` trở lên (mốc 2.3-A1). Phần ghi tri thức tự động (A2) và cleanup (B) có ở các bản sau; mục "Giới hạn" ghi rõ bản này làm gì và không làm gì.

## 1. Wiki là gì ở đây

- Thư mục trang Markdown của project, mặc định `docs/wiki/` trong repo. Muốn dùng thư mục khác, thêm vào `.onecrew/config.json` (file của máy này, không commit):
  `"wiki": {"paths": ["docs/wiki", "D:/kho-chung/wiki"]}` — đường dẫn tương đối là trong repo; đường dẫn tuyệt đối là thư mục ngoài repo.
- Wiki là **dữ liệu có nguồn**, không phải lệnh hay quyền. Sổ (ledger) vẫn giữ trạng thái và quyền; wiki không duyệt, không nghiệm thu.
- OneCrew đọc thêm `context.entry` và lesson trong sổ của chính project; cả hai được chọn bằng cùng một bộ đọc.

## 2. Viết một mục

Mỗi heading `##` hoặc `###` là một mục. Mục có kiểu khi có khối ```` ```onecrew ```` chứa một JSON:

````markdown
## Giá trị của a.txt
```onecrew
{"id": "a-value", "kind": "constraint", "label": "verified", "must": true, "applies_to": ["a.txt"],
 "sources": [{"type": "file", "path": "a.txt", "revision": "<commit lúc kết luận được kiểm>"}],
 "conditions": [{"type": "file_contains", "path": "requirements.txt", "text": "lib==1.0"}]}
```
a.txt phải chứa đúng một dòng.
````

| Trường | Ý nghĩa |
|---|---|
| `id` | duy nhất trong project; không có thì sinh từ tên trang + heading (bỏ dấu) |
| `kind` | `decision`, `constraint`, `finding`, `lesson`, `rejected`, `note`, `summary` |
| `label` | `observed`, `hypothesis`, `verified`, `refuted`, `unverified`. `verified`/`refuted` phải có nguồn kiểm được, nếu không bị đọc là `unverified` và trang bị báo lỗi |
| `must` | ràng buộc bắt buộc: luôn được giao khi liên quan tới file của node, không bao giờ bị cắt; không vừa trần thì node dừng trước khi gọi model |
| `applies_to` | file/thư mục (kết thúc `/`)/glob mà mục áp dụng; dùng để chọn và để xét bắt buộc |
| `sources` | `file` (path + `revision` hoặc `blob`), `file_line`, `symbol`, `receipt`, `event`, `url` (url không kiểm được) |
| `conditions` | `file_contains`, `file_unchanged` (sha256), `env` (`platform`, `python`, `provider`, `model`), hoặc chữ (không kiểm được) |
| `status`, `supersedes`, `derived_from`, `ledger_id` | vòng đời và nguồn dẫn xuất (dùng nhiều ở A2) |

Heading không có khối `onecrew` là ghi chú `unverified`: chỉ được giao như **đầu mối**, không bao giờ như sự thật.

## 3. OneCrew chọn gì cho một node

1. **Quyền:** chỉ project này; mọi file mà nguồn của mục trích phải nằm trong `read` ∪ `write` của node, nếu không mục không được giao và không bị nêu tên. Ghi chú làm việc của một root chỉ thuộc root đó.
2. **Trạng thái:** `withdrawn`/`superseded`/`archived` là lịch sử, không giao.
3. **Còn áp dụng không:** file nguồn khác với revision lúc ghi (kể cả thay đổi chưa commit) → `recheck`; điều kiện kiểm được mà sai → `not_applicable` (không giao); điều kiện không kiểm được → `unknown`. Không có hạn dùng theo thời gian.
4. **Cách dùng:** `fact` (verified, còn áp dụng), `rejected` (hướng đã loại, còn áp dụng), `lead` (còn lại: phải kiểm nguồn trước khi dựa vào). Kết luận `refuted` có nguồn đã đổi được mở lại thành `lead`.
5. **Liên quan + trần:** mục bắt buộc trước, rồi theo file và từ khóa của node/plan, tới trần 12 000 ký tự. Phần chưa giao có tổng theo lý do, danh sách id/tiêu đề và con trỏ đọc tiếp.

## 4. Lệnh

```text
onecrew --project <repo> [--state-root <sổ>] wiki pages
onecrew --project <repo> wiki show --plan <plan> [--node <node>] [--cap 12000] [--text]
onecrew --project <repo> wiki read --plan <plan> [--node <node>] --cursor <con trỏ từ wiki show>
```

`pages` liệt kê trang, mục và lỗi (bộ kiểm trang). `show`/`read` cho thấy đúng gói mà node sẽ nhận. Cả ba chỉ đọc. Con trỏ chỉ dùng được khi wiki/sổ chưa đổi; đổi rồi thì chạy lại `show`.

## 5. Giao cho worker và cách kiểm kết quả

- Adapter được hỗ trợ: worker native của engine (`NativeExecutor`, gồm khi chạy qua `ManagedExecutor`). Gói nằm trong prompt dưới khóa `knowledge`.
- Receipt `native-node-receipt` của attempt có:
  - `knowledge.package`: khóa blob của đúng gói đã giao (đọc bằng snapshot store của sổ), `knowledge.delivered`: các id, `knowledge.chars`, `knowledge.omitted_total`, `knowledge.problems` (lỗi trang).
  - `knowledge_use`: worker khai `used`/`rejected`/`requests`; `violations` (id không được giao), `leads_used` (dựa vào đầu mối), `must_unacknowledged`, `proves_semantics: false`.
- Kết quả đúng hay sai do **check của node** quyết định. Khai báo sử dụng chỉ là kiểm cấu trúc.
- Worker cần mục chưa được giao: trả `continuation` kèm `knowledge.requests: [id…]`; lần tiếp tục nhận đúng các mục đó trong `requested` (nếu vẫn được phép).
- Không có wiki và không có mục liên quan: prompt giữ nguyên như 2.2; receipt ghi `knowledge.package: null`.
- Trang wiki hỏng chỉ làm mục của trang đó không được dùng; node độc lập vẫn chạy và receipt ghi lỗi.

## 6. Giới hạn của bản A1 (2.3.0.dev1)

- A1 **không ghi** tri thức mới: không tạo/sửa trang wiki hay mục trong sổ. Ghi tri thức có bằng chứng, dùng lại qua root mới, thu hồi qua tóm tắt: mốc A2.
- Mục của root khác cùng project chỉ được dùng khi đã công bố cho project (lesson, hoặc mục `visibility: project` của A2). Mục `context.entry` cũ của 2.2 coi là ghi chú làm việc của root đó.
- Chỉ một adapter có bằng chứng giao: worker native. Phiên Claude Code tương tác (hook) đọc được bằng `wiki show`, nhưng không có receipt giao.
- Kiểm áp dụng là so blob file và điều kiện kiểu; không phải phân tích ngữ nghĩa. File không đổi không chứng minh kết luận còn đúng về hành vi ngoài file đó.
- Chi phí chọn gói tăng theo số mục: đo trên máy dùng chung khoảng 0,05 s (100 mục), 0,25 s (~1 200), 0,5 s (~6 000), 1,8 s (~22 000) mỗi lần giao (`docs/v23/evidence/ks01-scale.json`). Chưa có chỉ mục riêng; không tuyên bố giảm token/latency.
- Đối chứng wiki: xem `docs/v23/evidence/` — hàng provider giả chỉ chứng minh đường đi và nhãn; hàng Claude thật là một task nhỏ, vài lượt, không có ý nghĩa thống kê.
