# Wiki của project trong OneCrew 2.3 — cách dùng và cách kiểm

Áp dụng cho bản `2.3.0.dev1` trở lên: đọc/giao (A1) từ dev1, ghi có bằng chứng và dùng lại qua root mới (A2) từ dev2, `onecrew init` tạo hoặc dùng lại wiki (§0) từ dev7. Mục "Giới hạn" ghi rõ phần không làm.

## 0. Khởi tạo: `onecrew init` tạo hoặc dùng lại wiki (từ 2.3.0.dev7)

`onecrew init` (chạy lại được) ngoài sổ, hook và `.onecrew/config.json` còn lo wiki của project. Nó quyết định trước khi ghi bất cứ gì:
- `.onecrew/config.json` có `"wiki": {"paths": [...]}`:
  - đúng một thư mục trong repo: chưa có thì tạo khung ở đó, có rồi thì dùng;
  - nhiều thư mục, hoặc một thư mục tuyệt đối ngoài repo: chỉ dùng lại, init không chọn chỗ ghi; thiếu thư mục nào thì init dừng (mã 2) và không ghi gì.
- Không cấu hình: `docs/wiki/`.
- Thư mục đã có một trang của bạn: dùng nguyên, không thêm file. Trang khung bạn đã sửa cũng là trang của bạn: init chỉ coi một trang là của nó khi trang còn đúng từng byte như lúc init viết. Thư mục chưa có, rỗng, hoặc chỉ có trang khung init viết mà chưa ai sửa (init trước bị ngắt): tạo các trang khung còn thiếu.
- `docs/wiki` (hoặc thư mục cha) là link/junction tới một wiki đã có trang: dùng nguyên, init không ghi gì vào đó. Link tới thư mục rỗng hay chưa có: init dừng (mã 2). Wiki dùng chung nên khai bằng đường dẫn tuyệt đối trong `wiki.paths`.

Khung gồm `README.md` (cách viết một mục, có ví dụ), `project.md` (ngữ cảnh project) và `lessons.md` (bài học nhóm tự viết; điều OneCrew ghi kèm bằng chứng nằm trong sổ: `onecrew wiki history`, `onecrew lesson list`). Dòng đầu mỗi trang là `<!-- onecrew:wiki-skeleton 1 -->`. Khung không có heading `##`/`###` nào và không khai báo mục bắt buộc (ví dụ trong `README.md` không có `must`), nên chưa có mục nào được giao cho worker: `onecrew wiki pages` cho 3 trang, 0 mục. Bắt đầu bằng cách thêm mục vào `project.md` (§2).

Init không bao giờ ghi đè file, ghi ngoài repo hay qua link/junction, ghi vào `.git`, `.onecrew`, `.claude`, commit, gọi model hay quét repo. Init dừng với mã 2 và không ghi gì khi `config.json` không đọc được hoặc `wiki` sai dạng (trước dev7, một `config.json` không đọc được bị ghi đè), khi đường dẫn ra ngoài repo (kể cả `/docs/wiki`: thư mục gốc của ổ đĩa, như bộ đọc hiểu nó), khi một thành phần được viết theo cách khác của Windows (dấu chấm hoặc khoảng trắng ở cuối, stream `:`, tên ngắn 8.3), khi thư mục wiki là file, hoặc là hay đi qua link/junction mà không có trang nào. Init xét lại đường dẫn ngay trước khi ghi, nên một junction tạo ra trong lúc init chờ trả lời cũng không bị ghi xuyên qua. Ghi khung lỗi giữa chừng (thư mục chỉ đọc chẳng hạn): các bước khác của init vẫn xong, init in file đã ghi và lỗi, thoát mã 3; sửa rồi chạy lại để hoàn tất.

Project đã `init` bằng bản 2.2: chạy `onecrew init` của bản này một lần. Sổ, `config.json` (các khóa khác giữ nguyên), plan và ngân sách giữ nguyên; hook được gộp sang lệnh mới; khung wiki được thêm nếu project chưa có wiki. Cài hay nâng wheel không tự init project nào. Bằng chứng: `tests/test_v23_wiki_init.py`, bước V15 của bộ kiểm gói (CLI của wheel đã cài, có ca project do wheel 2.2 cài).

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
| `sources` | `file` (path + `revision` là **commit đầy đủ** hoặc `blob`), `file_line`, `symbol`, `receipt`, `event`, `url` (url không kiểm được). Revision dạng tên (`HEAD`, nhánh) luôn chỉ "bây giờ" nên không kiểm lại được: trang bị báo lỗi và mục chỉ là đầu mối. Event/receipt phải có thật trong sổ này |
| `conditions` | `file_contains`, `file_unchanged` (sha256 của nội dung, CRLF đọc như LF), `env` (`platform`, `python` = Python đang chạy OneCrew, `provider`, `model` = pin của node), hoặc chữ (không kiểm được) |
| `status`, `supersedes`, `derived_from`, `ledger_id` | vòng đời và nguồn dẫn xuất (dùng nhiều ở A2) |

Heading không có khối `onecrew` là ghi chú `unverified`: chỉ được giao như **đầu mối**, không bao giờ như sự thật.

## 3. OneCrew chọn gì cho một node

1. **Quyền:** chỉ project này; mọi file mà nguồn của mục trích, mọi file cụ thể trong `applies_to` đã được ghim, và toàn bộ phạm vi node đã sinh ra tri thức đó (`read` ∪ `write` của node, với tri thức A2) phải nằm trong `read` ∪ `write` của node đọc — nếu không, mục không được giao và không bị nêu tên. Ghi chú làm việc của một root chỉ thuộc root đó; ghi chú đó cũng không thay thế/thu hồi gì cho root khác.
2. **Trạng thái:** `withdrawn`/`superseded`/`archived` là lịch sử, không giao.
3. **Còn áp dụng không** — xét trên đúng nội dung file worker sẽ thấy (nguồn của prompt, gồm output của node trước), file khác thì trên working tree: blob khác với lúc ghi → `recheck`; điều kiện kiểm được mà sai → `not_applicable` (không giao); điều kiện, revision dạng tên, event/receipt không có, hay file trong `applies_to` chưa được ghim nội dung → `unknown`. Không có hạn dùng theo thời gian.
4. **Cách dùng:** `fact` (verified, còn áp dụng — kèm `evidence.property` là điều đã chứng minh và `evidence.cause`), `rejected` (hướng đã loại, còn áp dụng), `lead` (còn lại: phải kiểm nguồn trước khi dựa vào). Kết luận `refuted` có nguồn đã đổi được mở lại thành `lead`; mục bị tranh chấp hay bị phản bác là `lead`; tóm tắt không bao giờ mạnh hơn nguồn yếu nhất còn được giao.
5. **Liên quan + trần:** trần tính trên **cả gói** (khung, danh sách mục chưa giao, lỗi trang), tối đa 16 000 ký tự và không quá chỗ prompt 80 000 ký tự còn lại — tri thức tùy chọn không bao giờ làm node bị giữ. Mục bắt buộc trước (không bị cắt; không vừa thì node bị giữ trước khi gọi model), rồi các mục yêu cầu đọc tiếp, rồi theo file và từ khóa của node/plan. Phần chưa giao có tổng theo lý do, danh sách id/tiêu đề và con trỏ đọc tiếp; con trỏ gắn với đúng task và trạng thái tri thức.

## 4. Lệnh

```text
onecrew --project <repo> [--state-root <sổ>] wiki pages
onecrew --project <repo> wiki show --plan <plan> [--node <node>] [--cap 12000] [--text]
onecrew --project <repo> wiki read --plan <plan> [--node <node>] --cursor <con trỏ từ wiki show>
```

`pages` liệt kê trang, mục và lỗi (bộ kiểm trang). `show`/`read` cho thấy gói node sẽ nhận, xét trên working tree (lúc chạy thật, engine xét trên đúng file trong prompt, nên mục về file mà node trước vừa sửa có thể khác). Cả ba chỉ đọc. Con trỏ chỉ dùng được khi wiki/sổ và task chưa đổi; đổi rồi thì chạy lại `show`.

## 5. Giao cho worker và cách kiểm kết quả

- Adapter được hỗ trợ: worker native của engine (`NativeExecutor`, gồm khi chạy qua `ManagedExecutor`). Gói nằm trong prompt dưới khóa `knowledge`.
- Receipt `native-node-receipt` của attempt có:
  - `knowledge.package`: khóa blob của đúng gói đã giao (đọc bằng snapshot store của sổ), `knowledge.delivered`: các id, `knowledge.chars`, `knowledge.omitted_total`, `knowledge.problems` (lỗi trang), và `knowledge.wiki` khi wiki không được đọc hết (`complete: false`, số trang không đọc, trang không đọc được, mục bắt buộc không giao được); gói trong prompt mang cùng khóa `wiki`.
  - `knowledge_use`: worker khai `used`/`rejected`/`requests`; `violations` (id không được giao), `leads_used` (dựa vào đầu mối), `must_unacknowledged`, `proves_semantics: false`.
- Kết quả đúng hay sai do **check của node** quyết định. Khai báo sử dụng chỉ là kiểm cấu trúc.
- Worker cần mục chưa được giao: trả `continuation` kèm `knowledge.requests: [id…]`; lần tiếp tục nhận đúng các mục đó trong `requested` (nếu vẫn được phép).
- Không có wiki và không có mục liên quan: prompt giữ nguyên như 2.2; receipt ghi `knowledge.package: null`.
- Trang wiki hỏng chỉ làm mục hỏng không được dùng (mục khác của trang và trang khác vẫn được giao); node vẫn chạy và receipt ghi lỗi — **trừ khi phần hỏng là một mục bắt buộc** (xem dưới).
- **Ràng buộc bắt buộc không mất vì giới hạn đọc** (sửa sau review Codex P2-02): 2 000 trang đầu (theo tên) được đọc trọn; mọi trang sau đó vẫn được dò tìm khối `onecrew` có `"must": true` hoặc `"supersedes"`, và mục bắt buộc, mục thay thế cùng mục mà mục bắt buộc dẫn xuất từ đó (cùng trang, ở mọi tầng) được dùng như thường; phần còn lại của các trang đó không đọc, gói ghi rõ số trang (`wiki.not_read`, `wiki.partly_read`). Trang UTF-8 có BOM được đọc bình thường; trang có byte NUL (UTF-16 không BOM) được coi là không phải UTF-8.
- **Khi một mục bắt buộc không giao được thì node bị giữ trước khi gọi model** (lý do `Mandatory knowledge cannot be established: …` nêu trang/dòng; sửa trang rồi chạy lại), với node mà mục đó có thể áp dụng (`applies_to` khớp file của node, hoặc không có `applies_to`). Các trường hợp: trang lớn hơn 2 MB, không phải UTF-8 (kể cả UTF-16 do PowerShell 5.1 ghi), metadata sai (kể cả đường dẫn nguồn tuyệt đối), hai mục khác nhau cùng một id, khối nằm ngoài mục `##`/`###`, mục bắt buộc dẫn xuất (ở bất kỳ tầng nào) từ một mục không đọc được, hai mục bắt buộc khác nhau cùng id mà id đó là bản sao của một chủ đề sổ này không có; wiki lớn hơn 256 MB không dò hết; sổ không đọc được phần context mà sổ có bản ghi bắt buộc; lớp chọn tri thức lỗi bất ngờ (git treo, sổ bị khóa…) trong khi project có khai báo tri thức bắt buộc. Bản sao giống hệt của một mục (trang chép hai nơi, hai bản `wiki export`) không giữ node.
- **Lỗi làm không biết nội dung thì được báo, không chặn task độc lập:** `config.json` không đọc được hoặc khóa `"wiki"` sai, thư mục wiki đã cấu hình mà không có, trang không đọc được mà không thấy dấu hiệu bắt buộc → dòng lỗi trong `problems` và `wiki.complete: false` (thêm `missing_folders`, `config_problem`), node vẫn chạy. Lớp chọn lỗi bất ngờ mà project không có tri thức bắt buộc nào → node chạy trên input của nó, receipt ghi `knowledge.error`. Dòng lỗi trang không bao giờ chiếm chỗ của mục bắt buộc: khi thiếu chỗ, chúng chỉ ở receipt. Trên trang không đọc được, dấu hiệu bắt buộc là chuỗi `"must": true`, nên một trang hỏng chỉ nhắc chuỗi đó trong văn bản cũng bị coi là có mục bắt buộc (thà giữ node còn hơn chạy thiếu ràng buộc).
- Khai báo `knowledge` sai giới hạn schema bị bỏ và ghi `knowledge_declaration_problem` vào receipt; artifact vẫn giữ. Claim nêu file ngoài phạm vi node, hoặc file không có trong candidate, bị từ chối và ghi `knowledge_claims_refused`.

## 6. Ghi tri thức có bằng chứng và dùng lại qua root mới (A2, từ 2.3.0.dev2)

### 6.1 OneCrew tự ghi khi có bằng chứng

- Worker native có thể trả `knowledge.new`: `[{kind, text, applies_to, sources: [file đã đọc], check: <id check của node>}]`; `applies_to`/`sources` phải là file của node. Ngay khi attempt có receipt, mỗi claim được ghi là **quan sát của root đó** (`observed`, `visibility: root`, nguồn = receipt, ghim blob trên candidate worker vừa tạo). Claim không bao giờ tự thành sự thật vì đã được nói ra.
- Khi check của node đạt trong lần verify được công bố, claim nêu đúng check đó (kể cả claim của các attempt dở dang trước đó) được **công bố cho project** (`verified`, `visibility: project`): thuộc tính đã chứng minh = "check X (spec) đạt trên artifact Y" — check chứng minh thuộc tính của nó, không chứng minh từng chữ của claim, và điều này đi kèm mục khi giao —, nguồn = receipt verify + receipt attempt + file đã trích (ghim blob trên artifact đã verify), `cause: not_established`, phạm vi đọc = phạm vi node. Nếu candidate chưa được áp vào project, root sau nhận mục này là `lead`/`recheck` cho tới khi file trong project khớp. Check đỏ thì không công bố gì.
- Worker từ chối một mục đã được giao (`knowledge.rejected`) và node đạt: ghi một phát hiện `contradicts` cho project; mục bị phản bác được giao lại dưới dạng `lead` có lý do.
- Lesson sau sửa đã kiểm (cơ chế 2.2) là tri thức project, dùng được ở root mới.
- Mọi bản ghi chỉ ghi được khi root còn mở; root đã kết thúc thì bị từ chối (guard của 2.2).

### 6.2 Ghi bằng lệnh

```text
onecrew wiki record --plan <root đang mở> --kind finding --text "…" --status verified --property "điều đã chứng minh" \
        --source event:<id> --source path:<file>@<commit> [--applies-to <path>] [--condition '{"type":"file_contains",…}'] \
        [--visibility project|root] [--scope general --condition "…"] [--key <chủ đề> --base <state_version đã đọc>]
onecrew wiki summarize --plan <root> --text "…" <id> [<id> …]
onecrew wiki withdraw <id> --plan <root đang mở> --reason "…" --source event:<id>
onecrew wiki archive <id> --plan <root đang mở> --reason "…"
onecrew wiki export --out docs/wiki/onecrew-export
onecrew wiki history
```

- Nhãn là mức bằng chứng: `verified` bắt buộc `--property` và ít nhất một nguồn event/receipt/file:line/symbol; `cause` chỉ "established" khi có nguồn nguyên nhân riêng.
- **Tóm tắt** (`summarize`) mang `derived_from`, nhãn bằng nguồn yếu nhất, `semantic_verification: unverified`. Bản sao cùng nội dung, cùng nguồn chỉ là một mục (`copies: n`), không tăng độ tin cậy.
- **Cập nhật đồng thời:** ghi lại một chủ đề (`--key`) kèm `--base` là `state_version` đã đọc (`wiki history`; thường bằng `version`, còn khi mục đã bị thu hồi hoặc lưu trữ thì là bản ghi thu hồi/lưu trữ đó — đính chính dựa trên nó thành version kế tiếp, không thành contested). Nếu chủ đề đã đổi, bản mới được giữ riêng là `contested`; cả hai được giao như `lead` có lý do, không bản nào mất.
- **Thu hồi / thay thế / lưu trữ** là bản ghi mới trên một root đang mở; không xóa sổ, receipt hay trang. Ở lần truy xuất tiếp: các phiên bản viết trước bản ghi thu hồi, tóm tắt dẫn từ nó, bản sao wiki mang `ledger_id` của nó và lesson cùng id (cả `lesson list`, `issue localize`) đều không được giao; một bản đính chính viết sau bản ghi thu hồi thì sống lại. `wiki history` vẫn hiện tất cả với trạng thái (ghi chú riêng của một root theo vòng đời của chính root đó). Mục general chỉ project đã viết nó mới thu hồi được, bằng một bản ghi general mọi project đều đọc.
- Bản ghi **general** chỉ mang chữ, điều kiện và nguồn event/receipt — không `applies_to`, `must`, `supersedes`, tiêu đề hay file; phần riêng của project bị từ chối ngay khi ghi.
- **Xuất wiki** là bản dẫn xuất: mỗi mục giữ `ledger_id`; commit bản xuất vào `docs/wiki/` không tạo nguồn thứ hai (mục còn sống được giao một lần từ sổ; mục đã thu hồi không sống lại từ bản sao).

### 6.3 Gói tiếp tục và `context retrieve` đọc cùng một quyết định

`onecrew continue <plan> [--json]` (gói tiếp tục) và `onecrew context retrieve` cho agent tiếp tục một root xem tri thức của chính root đó theo **đúng quyết định của gói tri thức** (sửa sau review Codex P2-01): mục bị thu hồi, lưu trữ, bị thay thế (kể cả ghi chú riêng bị ghi chú mới thay) hay dẫn xuất từ các mục đó không hiện; mục có file ghim hoặc nguồn đã đổi, không còn áp dụng, hay (bản ghi 2.3) không kiểm được, hiện nhãn `stale` kèm lý do — không bao giờ `verified`. Mục mà root khác đã ghi phiên bản mới hơn (cùng chủ đề) hiện `stale` với lý do, không lộ nội dung của root kia. Mục còn đúng giữ nguyên nhãn; ghi chú hợp lệ không mất; project khác không hiện. Mục 2.2 (không có trường tri thức 2.3) giữ quy tắc 2.2 cho nguồn của nó (dòng/ký hiệu được trích có đổi không), chỉ vòng đời, tranh chấp và phản bác tác động lên nó. `context retrieve --plan <plan>` chỉ hiện root đó; không có `--plan` thì như 2.2 là danh sách của cả project (mỗi mục xét theo root của chính nó, gồm ghi chú riêng của các root). `context retrieve --revision <rev>` xét khả năng áp dụng trên file của commit đó (riêng trang wiki vẫn đọc từ working tree). Bản ghi **general** (dùng chung) cũng được xét theo đúng quyết định đó cho người đọc: root của `--plan`, hoặc project khi không có `--plan` (môi trường là process đang chạy: platform, Python; không có node nên điều kiện `provider`/`model` không kiểm được), vòng đời theo project đã viết nó (sửa sau review Codex dev3). Bản ghi general có điều kiện sai ở đây → `stale` "not applicable now…"; bản ghi 2.3 có điều kiện không kiểm được → `stale` "cannot be checked now…"; nhãn gốc giữ ở `stored_label`, điều kiện và nguồn giữ nguyên. Mục general mà vòng đời của project đã thu hồi, lưu trữ hay thay thế không hiện với bất kỳ người đọc nào, kể cả người đọc không đọc được bản thay thế.

**Mỗi chủ đề thuộc project đã ghi nó** (sửa sau review Codex dev5, P2-B):
- Với project của bạn, bản ghi của chính bạn giữ id `ctx-<key>`. Bản ghi general của project khác hiện với id `ctx-<key>@<12 ký tự>`; 12 ký tự đó là dấu của project lấy từ task đầu tiên của nó trong sổ (ngẫu nhiên), không suy ra được đường dẫn hay mã project.
- Vì vậy hai project dùng chung một `--key` vẫn là hai chủ đề:
  - không bản nào che bản nào;
  - thu hồi hay lưu trữ chỉ tác động lên bản của project đã ghi lệnh đó;
  - mỗi project tự thu hồi được bản của mình, còn bản của project khác thì bị từ chối.
- Muốn thay thế (`--supersedes`) bản general của project khác cho riêng project mình, dùng đúng id hiện ở `wiki history` hoặc `wiki show`. Thu hồi hay lưu trữ một id không phải bản ghi, lesson hay mục wiki nào của project thì bị từ chối (không ghi lệnh vô hiệu); id `…@<dấu của chính project>` được hiểu là bản của mình.
- Tham chiếu ghi trước 2.3.0.dev6 (id trơn, trong `supersedes`, `derived_from`, `contradicts` của sổ) giữ nghĩa lúc ghi: chủ đề mới nhất mang key đó mà project nhìn thấy khi ghi. Trang wiki không có thời điểm, nên id trơn trong trang được đọc theo project: trỏ bản của project nếu có; nếu không có và đúng một bản general của project khác mang key đó thì trỏ bản đó; nhiều bản thì không trỏ bản nào. Mọi id trơn mà bản general của project khác cũng khớp đều được báo (`wiki pages` và gói) kèm nghĩa hiện tại và id cần viết; một lần ghi sau làm đổi nghĩa thì cũng được báo, không bao giờ âm thầm. Muốn chỉ rõ bản của chính project (không bị báo), viết `ctx-<key>@<dấu của project mình>` (dấu hiện trong `wiki history` của project khác); trong sổ cũng vậy.
- Bản tóm tắt không trích được bản ghi của project khác khi bản đó dẫn sự kiện (bằng chứng phải là sự kiện của chính project); bản dẫn receipt của state root chung thì tóm tắt được và theo vòng đời của bản gốc. Tranh chấp (hai phiên bản ghi đồng thời) của bản general có hiệu lực với mọi project. Khóa bắt đầu bằng `lesson-` dành cho lesson: `wiki record`, `context add` từ chối.
- Trong cùng một project, một `--key` là một chủ đề: ghi bản general với key đã có bản project (hoặc ngược lại) bị từ chối; ghi chú làm việc của root (`ctx-<key>.r<root>`) và mục `context add` kiểu 2.2 là chủ đề khác, không chặn. Dữ liệu cũ đã có cả hai scope là các phiên bản của một chủ đề: project khác vẫn nhận bản general đã công bố như trước (không thấy gì về bản không chia sẻ của bạn), và `wiki history` của bạn hiện bản đó ở trường `published`; thu hồi chủ đề ghi một bản ghi của project (nguồn và lý do của bạn) và một bản ghi chung trung tính ("withdrawn by its project"), nên có hiệu lực với mọi project. Phiên bản nào không phải bản được xét thì hiện `stale` "not judged: another record … has the same knowledge id …", không bao giờ hiện hành.

Mục general ghi bằng 2.2 (`context add --scope general --condition "<chữ>"`) có điều kiện chữ tự do mà 2.2 không kiểm: giữ nhãn 2.2, gói tri thức coi nó là đầu mối. Nếu bước xét lỗi, mục đã thu hồi/thay thế vẫn không hiện và mọi mục còn lại là `stale` có lý do. Lịch sử đầy đủ vẫn ở `wiki history`.

### 6.4 Root mới dùng lại

Root B mới của cùng project (phiên/process mới) tự nhận các mục `visibility: project` và lesson của root khác, qua cùng bộ chọn A1: quyền đọc nguồn của node B, khả năng áp dụng hiện tại, mức liên quan, trần. Không cần chép tay context của root A, không mở lại A, không đụng ngân sách của A. Mục `visibility: root` (bộ nhớ làm việc) của A không sang B. Project khác không thấy.

## 7. Giới hạn

- Khung wiki viết bằng ngôn ngữ của `ONECREW_LANG` lúc init (vi, mặc định en); init không dịch hay sửa trang đã có.
- Trên Python 3.10/3.11 (chưa có `Path.is_junction`), init nhận ra junction qua đường dẫn sau khi phân giải: junction trỏ ra ngoài repo vẫn bị từ chối; junction trỏ tới chỗ khác trong repo thì không bị coi là junction.

- **Quay về 2.2:** 2.2 đọc được sổ 2.3 (plan show, engine state, compat scan không có khối read — diễn tập ở bộ kiểm gói), nhưng 2.2 không biết vòng đời tri thức: mục đã thu hồi/lưu trữ/thay thế hiện như ghi chú bình thường trong `context retrieve`/gói tiếp tục của 2.2, và 2.2 không khôi phục được một attempt đang dở mà worker đã trả khóa `knowledge` (attempt đó giữ trạng thái unknown). Trước khi quay về, để mọi attempt kết thúc; sau khi quay về, coi tri thức 2.3 trong sổ là dữ liệu thô.
- Bản A1 (2.3.0.dev1) chỉ đọc/giao; phần ghi và dùng lại qua root mới có từ 2.3.0.dev2 (A2).
- Mục `context.entry` cũ của 2.2 (không có `visibility`) coi là ghi chú làm việc của root đó, không sang root khác.
- Root đang chạy không nhận cập nhật giữa chừng: thu hồi/sửa có hiệu lực ở lần truy xuất tiếp theo (cập nhật consumer đang chạy là 2.4-B).
- Chỉ một adapter có bằng chứng giao: worker native. Phiên Claude Code tương tác (hook) đọc được bằng `wiki show`, nhưng không có receipt giao.
- Kiểm áp dụng là so blob file và điều kiện kiểu; không phải phân tích ngữ nghĩa. File không đổi không chứng minh kết luận còn đúng về hành vi ngoài file đó.
- Chi phí chọn gói tăng gần tuyến tính theo số mục và số trang: số đo trên bản cuối ở BAO-CAO-2.3 §4 (`docs/v23/evidence/ks01-scale-*.json`). Mỗi lần giao đọc lại toàn bộ wiki (dò mục bắt buộc trên mọi trang); chưa có chỉ mục riêng; không tuyên bố giảm token/latency.
- Gói tiếp tục bây giờ chạy cùng bộ chọn với gói tri thức (đọc wiki và toàn bộ tri thức của sổ một lần mỗi lệnh `continue` hay `context retrieve`, dù có bao nhiêu root); các reader nội bộ khác (`issue localize`, bản đồ issue, incident) giữ cách đọc của 2.2.
- Đối chứng wiki: xem `docs/v23/evidence/` — hàng provider giả chỉ chứng minh đường đi và nhãn; hàng Claude thật là một task nhỏ, vài lượt, không có ý nghĩa thống kê.
