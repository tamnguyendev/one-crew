# v2: kiểm rẻ hơn, giữ nguyên sáu bất biến (2.2.0.dev3)

Năm thay đổi của đợt 1 (2.2.0.dev2), nay sửa theo kết quả review độc lập của Codex ở `8383446` (2.2.0.dev3, mục 6): không thêm loại sự kiện, bảng hay migration. Sổ cũ đọc y nguyên.

## 1. Verdict đi theo mốc, không chỉ theo revision
Một mốc **được kế thừa** (`plan show`: `state: passed`, `carried_from: <revision gốc>`) khi revision đang xét **đã được chủ sở hữu duyệt**, mốc chưa có verdict nào ở revision này, và:
- verdict gần nhất của mốc đó (ở revision cũ hơn) là `pass`, và **chữ ký** của mốc **byte-giống** (so JSON chuẩn hóa) với revision giữ verdict. Chữ ký gồm: tiêu đề, verifier (loại + cấu hình), `covers` và **toàn văn từng output mốc phủ** (output được nhận biết bằng mã `O<n>` theo vị trí). Thêm, bớt hay sửa **bất kỳ chữ nào** của một output được phủ, hoặc đổi `covers`, thì mốc chạy lại; sửa chữ một output mốc **không** phủ thì mốc giữ verdict. Chưa phân biệt "đổi chữ" với "đổi nghĩa": mọi đổi chữ của output được phủ đều chạy lại;
- mốc `reviewer`: luật độc lập (reviewer không phải tác giả, kể cả tác giả viết chữ của revision) được kiểm lại **cho revision mới**; revision do chính model reviewer viết thì verdict không được kế thừa, và `accept` từ chối;
- artifact của verdict đó **bằng artifact hiện tại**, hoặc (mốc `command`) **chỉ khác ở đường dẫn hợp đồng tự khai là trung lập** (`neutral_diff: true`, mục 2).

Hệ quả: sửa chữ của mốc khác, đổi tiêu đề kế hoạch, đóng một unknown, sửa chữ một output mốc không phủ… không làm mất verdict của mốc không đổi, và `verdict run` mốc sau không bị chặn "mốc trước chưa đạt".

Hai trường hợp artifact đã đi khỏi verdict:
- Verdict `pass` nằm **ngay ở revision này** mà artifact hiện tại không còn được phủ (commit đổi file thật): mốc kèm `stale: true` và về `pending` (hoặc `failed` nếu mốc đó từng có verdict fail ở revision này). Nó vẫn tính cho **thứ tự** (`verdict run` mốc sau không bị chặn, như 2.1) nhưng `accept` từ chối ("every milestone must have passed on exactly that artifact"); muốn nghiệm thu phải chạy lại mốc đó.
- Verdict **kế thừa** từ revision cũ mà không còn phủ artifact hiện tại: không có `stale`, mốc chỉ là `pending` như chưa từng có verdict, nên **chặn thứ tự** cho tới khi chạy lại.

`accept` ghi `carried` (mốc → revision gốc) vào sự kiện `plan.accepted` khi có kế thừa (một trường mới trong payload cũ, không phải loại sự kiện mới).

Không kế thừa khi: mốc đổi (tiêu đề, argv, cấu hình reviewer, tiêu chí, `covers`, chữ một output được phủ); verdict gần nhất là fail/inconclusive; revision chưa duyệt; reviewer là tác giả của revision mới; mốc `reviewer` hoặc `owner-manual` qua khác biệt trung lập (chúng nhìn chính các file đó).

`plan show`, `plan report` và `accept` dùng **một** cách tính view mốc (`plan.views_for`): kế thừa tính, một pass mà artifact đã rời đi là `stale`. Plan đã nghiệm thu được đọc **tại artifact đã nghiệm thu**, nên view và report của nó không đổi khi project có commit sau đó; plan chưa nghiệm thu được đọc tại artifact của project lúc này. Riêng `plan digest` chỉ đọc những gì mỗi plan ghi trên chính revision của nó (không mở git của từng project) và giữ nguyên từng byte.

## 2. `scope.neutral`
Danh sách glob (tối đa 20, mỗi cái ≤ 300 ký tự) trong `scope`. Cách khớp (`contract.neutral_match`, trên đường dẫn posix tính từ gốc repo): `*` và `?` **không** vượt qua `/`; `**` vượt qua (`docs/**` là mọi thứ dưới `docs/`; `**/*.md` là mọi `.md` ở mọi độ sâu; `*.md` chỉ là `.md` ở thư mục gốc, nên `onecrew/templates/x.md` không khớp). Không có `[lớp ký tự]`.
**Không có danh sách mặc định** (từ 2.2.0.dev3; trước đó `docs/**`, `*.md`, `CHANGELOG*` được đọc khi hợp đồng vắng khai, nên mã dưới `docs/` hay một `.md` mà test đọc lúc chạy vẫn kế thừa pass). Chỉ đường dẫn mà **chính hợp đồng khai** trong `scope.neutral` mới trung lập; hợp đồng không khai (hay `"neutral": []`) thì không có đường dẫn nào trung lập, và một commit chỉ sửa tài liệu cũng làm mốc `command` chạy lại — muốn tránh thì khai `"neutral": ["docs/**"]` trong hợp đồng. Hợp đồng cũ không đổi byte.
Một commit chỉ chạm đường dẫn trung lập: mốc `command` vẫn `passed`, mốc `reviewer` về `pending`. `owner accept --artifact-sha <sha>` (chỉ nhận mã hex 40 hoặc 64 ký tự; mọi giá trị khác — rỗng, tên ref, `--relative=docs` — bị từ chối bằng lỗi rõ **trước khi gọi git**, nên không có gì ngoài mã hex đến được `git`, và các lệnh git nhận mã sau `--end-of-options`; một mã commit được đọc thành cây của nó, một mã hex git không giải được giữ nguyên và không khớp verdict nào) nhận verdict kế thừa khi artifact của verdict và artifact nghiệm thu chỉ khác trung lập; mọi mốc vẫn phải `passed`; mốc reviewer phải đạt đúng trên artifact nghiệm thu. Lấy artifact hiện tại: `onecrew verdict artifact --plan P` (JSON `{"artifact_sha": ...}`).

## 3. Reviewer đọc cây Git đang theo dõi, và không bỏ sót gì mà nghiệm thu sẽ lấy
Diff gửi model = `git diff <cây trước> <cây sau>`, và **cả hai là cây "đang theo dõi"**, ghi sẵn trong sổ. Artifact (cây `add -A`, thứ `accept` gắn vào) vẫn là cây rộng hơn, nên có hai luật để model không bao giờ nhận ít hơn artifact mà không ai biết:
- **Cây sau** = `command.tracked_tree` lúc chạy: bản sao **index thật** của repo (nên file mới đã `git add` có trong đó, dù chưa commit) + `add -u` (sửa/xóa của file đã có trong index; không `add -A`); index thật và ref không bị đụng. File bị ignore không vào (không còn `build/` làm vỡ trần 120 KB).
- **File chưa theo dõi mà không bị ignore** nằm trong artifact (vì `add -A` lấy nó) nhưng không nằm trong cây sau, nên model không thấy: mốc reviewer ra `inconclusive`, **không gọi model**, lý do liệt kê các đường dẫn đó (`git add` chúng, thêm vào `.gitignore`, hoặc xóa, rồi chạy lại); biên nhận ghi `not_shown`. Luật này áp cả cho nhánh "no change since approval". `verdict diff` vẫn in diff (không có các file đó), 0 lượt gọi model, không ghi sổ.
- **Một cây, chụp một lần.** `verdict run` lấy artifact trước, rồi chụp cây "đang theo dõi" **một lần** và cắt diff từ đúng cây đó; biên nhận ghi cả `tracked_tree` (cây sau), `base_tracked` (cây trước) và diff, nên diff trong biên nhận đúng bằng `git diff base_tracked tracked_tree`. Một thay đổi xảy ra sau khi chụp (artifact trước ≠ artifact sau lúc review) hoặc giữa lúc lấy artifact và lúc chụp (cây khác artifact ở đường dẫn đó, được liệt kê) → `inconclusive`. Mọi đường dẫn khác nhau giữa hai cây mà diff không nêu tên cũng → `inconclusive` (git ghi một tiêu đề cho mỗi đường dẫn đổi, kể cả file nhị phân, symlink và submodule: `Binary files differ`, đích của link, `Subproject commit`; nội dung đó model chỉ biết là đã đổi, không đọc được).
- **Cây trước**, theo thứ tự: (1) `tracked_tree` mà biên nhận của lần `pass` gần nhất của **chính mốc reviewer đó** (mọi revision) đã ghi — chỉ tính lần pass do reviewer ghi, có đúng cấu hình reviewer (model, tiêu chí…) đang chạy và có `tracked_tree` hợp lệ (biên nhận cũ không có, hoặc có mà không phải mã cây hex 40/64, thì bị bỏ qua); (2) chưa có thì `base_tracked` mà sự kiện `plan.approved` đầu tiên ghi lúc duyệt (khóa mới trong payload cũ, không phải loại sự kiện mới).
- **Mã cây đọc từ sổ hay biên nhận** chỉ được đưa cho git khi là hex 40 hoặc 64 ký tự thường, và đứng sau `--end-of-options`: một giá trị như `--output=x` không bao giờ được đọc thành tùy chọn.
- **Không có đường dự phòng.** Thiếu cây trước (duyệt từ trước 2.2.0.dev2, `git` không đọc được lúc duyệt, hay `base_tracked` không phải mã cây) thì không có cây trước, và cũng không có cách nào dựng nó từ thứ khác (không từ artifact `add -A`, không từ commit đoán): `verdict run` ghi biên nhận `inconclusive` có lý do ("no tracked-only base tree ..." hoặc "the recorded base tree is not a tree id ..."), không gọi model, `base_source: none`, không bao giờ làm `verdict run` lỗi; `verdict diff` in đúng lý do đó (exit 2). Cơ sở chỉ đọc từ lần duyệt **đầu** của plan, nên muốn tiếp tục phải lập lại plan (propose và duyệt) để lần duyệt đầu của nó ghi `base_tracked`.
Hệ quả: một file chưa theo dõi lúc duyệt rồi commit sau hiện ra là file mới (dòng `+`), không bao giờ có nội dung cũ của nó ở dòng `-`; file đã theo dõi mà bị xóa thật vẫn hiện.
Trần 120 KB giữ. Biên nhận ghi cả `artifact_sha` (add -A) lẫn `tracked_tree`, và `base_artifact`/`base_source` (`first_approval`, `previous_pass`, hoặc `none`) chỉ để quyết định ghi chú "no change since approval" (cây `add -A` giống hệt cây lúc duyệt thì pass không cần gọi model); chúng không bao giờ là một phía của diff.
`onecrew verdict diff --plan P --milestone M` in đúng diff đó ra stdout: 0 lượt gọi model, không ghi sổ (sổ mở chỉ đọc), không cần mốc trước đạt.
`verdict run` giờ từ chối **trước khi chạy** khi mốc trước chưa đạt hoặc mốc đã đạt trên đúng artifact này (trước đây chạy xong mới từ chối — reviewer tốn tiền).

## 4. `plan lint` kiểm tiêu chí và bước 0
Lint vẫn chỉ đọc, không gọi model.
| Mã | Khi nào | Hậu quả |
|---|---|---|
| `criterion_literal_present` | một chuỗi trong nháy đơn/kép/backtick dài ≥ 4 trong câu hỏi mà `git grep -F` thấy ở HEAD | cảnh báo, exit 0 |
| `criterion_no_fail_clause` | câu hỏi không có "fail if" (không phân biệt hoa thường) | từ chối, exit 1 |
| `criterion_vs_non_goal` | câu hỏi và một non_goal có từ chung ≥ 6 chữ cái (khớp 6 chữ đầu: message/messages) | cảnh báo, exit 0 |
| `unknowns_missing` | cỡ M/L, `unknowns` rỗng, và `understanding.no_unknowns_because` vắng hoặc ngắn hơn 20 ký tự (tối đa 300) | từ chối ở lint và ở `approve` |
`--ack-criteria` tắt hai cảnh báo (không tắt `criterion_no_fail_clause`). `unknowns_missing` áp cho mọi hợp đồng cỡ M/L ở lint và ở `approve` (hợp đồng cũ không có trường vẫn đọc được và hiển thị, nhưng muốn duyệt thì phải thêm). Mẫu có chỗ trống: `examples/contract-template.json`.

## 5. Report
`plan report` thêm, sau bảy mục, mục **"Reviewer ghi chú ngoài tiêu chí"** (không đánh số): mỗi mốc reviewer đã đạt và có `outside_criteria` một dòng tiêu đề, mỗi ghi chú một dòng gạch đầu dòng, cắt 300 ký tự (với mốc được kế thừa thì ghi chú của lần pass được kế thừa). Không có ghi chú thì mục không xuất hiện.
Từ 2.2.0.dev3 report đọc **cùng view mốc** với `plan show` và `accept` (mục 1): plan đã nghiệm thu được đọc tại artifact đã nghiệm thu nên report của nó không đổi; plan chưa nghiệm thu có thể nay hiện `stale` hay mốc được kế thừa như `plan show`, và chỉ các dòng tính từ trạng thái mốc đổi theo (dòng kết luận ở đầu, tiến độ và dòng output ở mục 1, dòng mốc ở mục 2, dòng `should` ở mục 7). `plan digest` không đổi byte.

## 6. Hook và `init` (2.2.0.dev3)
- Hook không có `--project` (dạng `onecrew init` cài) lấy project từ `CLAUDE_PROJECT_DIR`, rồi cwd của sự kiện, rồi cwd của tiến trình: **một** thư mục, tìm bản `.onecrew/active-plan.json` từ đó lên tới gốc repo và **không xa hơn** — plan của repo cha hay của project khác không bao giờ chi phối nó. Mất bản trong project thì bản sao ở state-root có `project` là chính thư mục này vẫn tìm thấy (state-root lấy từ `.onecrew/config.json`) và vẫn chặn; bản trong project được dựng lại.
- Mọi lệnh hook (`check`, `prompt`, `stop`, `session`…) ép stdout và stderr sang UTF-8 ngay khi khởi động, dù gọi bằng module hay bằng `onecrew hook <verb>` do `init` cài, nên tiêu đề tiếng Việt không còn làm hook lỗi trên đường ống cp1252 của Windows (lỗi đó làm mất lệnh chặn của hook `check`).
- `onecrew init` chỉ thay các handler do chính OneCrew cài: dạng `onecrew hook <verb>` và dạng checkout (`python -c "… from onecrew.v2.hook_cli import main …" hook <verb>`). Một handler của công cụ khác chỉ nhắc tên module (`echo onecrew.v2.hook_cli is monitored`) được giữ nguyên.
