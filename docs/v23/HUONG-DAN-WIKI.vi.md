# Wiki của project trong OneCrew 2.3 — cách dùng và cách kiểm

Áp dụng cho bản `2.3.0.dev1` trở lên: đọc/giao (A1) từ dev1, ghi có bằng chứng và dùng lại qua root mới (A2) từ dev2. Mục "Giới hạn" ghi rõ phần không làm.

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

## 6. Ghi tri thức có bằng chứng và dùng lại qua root mới (A2, từ 2.3.0.dev2)

### 6.1 OneCrew tự ghi khi có bằng chứng

- Worker native có thể trả `knowledge.new`: `[{kind, text, applies_to, sources: [file đã đọc], check: <id check của node>}]`. Ngay khi attempt có receipt, mỗi claim được ghi là **quan sát của root đó** (`observed`, `visibility: root`, nguồn = receipt). Claim không bao giờ tự thành sự thật vì đã được nói ra.
- Khi check của node đạt trong lần verify được công bố, claim nêu đúng check đó được **công bố cho project** (`verified`, `visibility: project`): thuộc tính đã chứng minh = "check X (spec) đạt trên artifact Y", nguồn = receipt verify + receipt attempt + file đã trích (ghim blob), `cause: not_established`. Check đỏ thì không công bố gì.
- Worker từ chối một mục đã được giao (`knowledge.rejected`) và node đạt: ghi một phát hiện `contradicts` cho project; mục bị phản bác được giao lại dưới dạng `lead` có lý do.
- Lesson sau sửa đã kiểm (cơ chế 2.2) là tri thức project, dùng được ở root mới.
- Mọi bản ghi chỉ ghi được khi root còn mở; root đã kết thúc thì bị từ chối (guard của 2.2).

### 6.2 Ghi bằng lệnh

```text
onecrew wiki record --plan <root đang mở> --kind finding --text "…" --status verified --property "điều đã chứng minh" \
        --source event:<id> --source path:<file>@<commit> [--applies-to <path>] [--condition '{"type":"file_contains",…}'] \
        [--visibility project|root] [--scope general --condition "…"] [--key <chủ đề> --base <version đã đọc>]
onecrew wiki summarize --plan <root> --text "…" <id> [<id> …]
onecrew wiki withdraw <id> --plan <root đang mở> --reason "…" --source event:<id>
onecrew wiki archive <id> --plan <root đang mở> --reason "…"
onecrew wiki export --out docs/wiki/onecrew-export
onecrew wiki history
```

- Nhãn là mức bằng chứng: `verified` bắt buộc `--property` và ít nhất một nguồn event/receipt/file:line/symbol; `cause` chỉ "established" khi có nguồn nguyên nhân riêng.
- **Tóm tắt** (`summarize`) mang `derived_from`, nhãn bằng nguồn yếu nhất, `semantic_verification: unverified`. Bản sao cùng nội dung, cùng nguồn chỉ là một mục (`copies: n`), không tăng độ tin cậy.
- **Cập nhật đồng thời:** ghi lại một chủ đề (`--key`) kèm `--base` là version đã đọc (`wiki history` → `version`). Nếu chủ đề đã đổi, bản mới được giữ riêng là `contested`; cả hai được giao như `lead` có lý do, không bản nào mất.
- **Thu hồi / thay thế / lưu trữ** là bản ghi mới trên một root đang mở; không xóa sổ, receipt hay trang. Ở lần truy xuất tiếp: mục bị thu hồi, tóm tắt dẫn từ nó và bản sao wiki mang `ledger_id` của nó đều không được giao; `wiki history` vẫn hiện với trạng thái.
- **Xuất wiki** là bản dẫn xuất: mỗi mục giữ `ledger_id`; commit bản xuất vào `docs/wiki/` không tạo nguồn thứ hai (mục còn sống được giao một lần từ sổ; mục đã thu hồi không sống lại từ bản sao).

### 6.3 Root mới dùng lại

Root B mới của cùng project (phiên/process mới) tự nhận các mục `visibility: project` và lesson của root khác, qua cùng bộ chọn A1: quyền đọc nguồn của node B, khả năng áp dụng hiện tại, mức liên quan, trần. Không cần chép tay context của root A, không mở lại A, không đụng ngân sách của A. Mục `visibility: root` (bộ nhớ làm việc) của A không sang B. Project khác không thấy.

## 7. Giới hạn

- Bản A1 (2.3.0.dev1) chỉ đọc/giao; phần ghi và dùng lại qua root mới có từ 2.3.0.dev2 (A2).
- Mục `context.entry` cũ của 2.2 (không có `visibility`) coi là ghi chú làm việc của root đó, không sang root khác.
- Root đang chạy không nhận cập nhật giữa chừng: thu hồi/sửa có hiệu lực ở lần truy xuất tiếp theo (cập nhật consumer đang chạy là 2.4-B).
- Chỉ một adapter có bằng chứng giao: worker native. Phiên Claude Code tương tác (hook) đọc được bằng `wiki show`, nhưng không có receipt giao.
- Kiểm áp dụng là so blob file và điều kiện kiểu; không phải phân tích ngữ nghĩa. File không đổi không chứng minh kết luận còn đúng về hành vi ngoài file đó.
- Chi phí chọn gói tăng gần tuyến tính theo số mục: trên máy dùng chung, min 0,11 s (100 mục), 0,46 s (~1 200), 0,98 s (~6 000), 2,8 s (~22 000) mỗi lần giao, tối đa tới 12 s khi máy tải nặng (`docs/v23/evidence/ks01-scale-41ad32e.json`). Chưa có chỉ mục riêng; không tuyên bố giảm token/latency.
- Đối chứng wiki: xem `docs/v23/evidence/` — hàng provider giả chỉ chứng minh đường đi và nhãn; hàng Claude thật là một task nhỏ, vài lượt, không có ý nghĩa thống kê.
