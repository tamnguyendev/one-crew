# v2: kiểm rẻ hơn, giữ nguyên sáu bất biến (2.2.0.dev2)

Năm thay đổi, không thêm loại sự kiện, bảng hay migration. Sổ cũ đọc y nguyên.

## 1. Verdict đi theo mốc, không chỉ theo revision
Một mốc **được kế thừa** (`plan show`: `state: passed`, `carried_from: <revision gốc>`) khi revision đang xét **đã được chủ sở hữu duyệt**, mốc chưa có verdict nào ở revision này, và:
- verdict gần nhất của mốc đó (ở revision cũ hơn) là `pass`, và tiêu đề + verifier của mốc **byte-giống** (so JSON chuẩn hóa) với revision giữ verdict;
- artifact của verdict đó **bằng artifact hiện tại**, hoặc (mốc `command`) **chỉ khác ở đường dẫn trung lập** (`neutral_diff: true`).

Hệ quả: sửa chữ của mốc khác, đổi tiêu đề kế hoạch, đóng một unknown… không làm mất verdict của mốc không đổi, và `verdict run` mốc sau không bị chặn "mốc trước chưa đạt".

Hai trường hợp artifact đã đi khỏi verdict:
- Verdict `pass` nằm **ngay ở revision này** mà artifact hiện tại không còn được phủ (commit đổi file thật): mốc kèm `stale: true` và về `pending` (hoặc `failed` nếu mốc đó từng có verdict fail ở revision này). Nó vẫn tính cho **thứ tự** (`verdict run` mốc sau không bị chặn, như 2.1) nhưng `accept` từ chối ("every milestone must have passed on exactly that artifact"); muốn nghiệm thu phải chạy lại mốc đó.
- Verdict **kế thừa** từ revision cũ mà không còn phủ artifact hiện tại: không có `stale`, mốc chỉ là `pending` như chưa từng có verdict, nên **chặn thứ tự** cho tới khi chạy lại.

`accept` ghi `carried` (mốc → revision gốc) vào sự kiện `plan.accepted` khi có kế thừa (một trường mới trong payload cũ, không phải loại sự kiện mới).

Không kế thừa khi: mốc đổi (tiêu đề, argv, cấu hình reviewer, tiêu chí); verdict gần nhất là fail/inconclusive; revision chưa duyệt; mốc `reviewer` hoặc `owner-manual` qua khác biệt trung lập (chúng nhìn chính các file đó). `plan report` và `plan digest` chưa tính kế thừa (đọc sổ thuần, không mở git).

## 2. `scope.neutral`
Danh sách glob (tối đa 20, mỗi cái ≤ 300 ký tự) trong `scope`. Cách khớp (`contract.neutral_match`, trên đường dẫn posix tính từ gốc repo): `*` và `?` **không** vượt qua `/`; `**` vượt qua (`docs/**` là mọi thứ dưới `docs/`; `**/*.md` là mọi `.md` ở mọi độ sâu; `*.md` chỉ là `.md` ở thư mục gốc, nên `onecrew/templates/x.md` không khớp). Không có `[lớp ký tự]`. Vắng thì **đọc** là `docs/**`, `*.md`, `CHANGELOG*` — không ghi vào hợp đồng, nên hợp đồng cũ không đổi byte. `"neutral": []` tắt hẳn.
Một commit chỉ chạm đường dẫn trung lập: mốc `command` vẫn `passed`, mốc `reviewer` về `pending`. `owner accept --artifact-sha <sha>` (chỉ nhận mã hex 40 hoặc 64 ký tự; mọi giá trị khác — rỗng, tên ref, `--relative=docs` — bị từ chối bằng lỗi rõ **trước khi gọi git**, nên không có gì ngoài mã hex đến được `git`, và các lệnh git nhận mã sau `--end-of-options`; một mã commit được đọc thành cây của nó, một mã hex git không giải được giữ nguyên và không khớp verdict nào) nhận verdict kế thừa khi artifact của verdict và artifact nghiệm thu chỉ khác trung lập; mọi mốc vẫn phải `passed`; mốc reviewer phải đạt đúng trên artifact nghiệm thu. Lấy artifact hiện tại: `onecrew verdict artifact --plan P` (JSON `{"artifact_sha": ...}`).

## 3. Reviewer chỉ đọc file có theo dõi
Diff gửi model = `git diff <cây trước> <cây sau>`, và **cả hai là cây chỉ gồm file có theo dõi**, ghi sẵn trong sổ. File chưa theo dõi hoặc bị ignore không bao giờ vào diff (không còn `build/` làm vỡ trần 120 KB); file mới chưa commit cũng chưa vào — commit trước khi chạy verdict.
- **Cây sau** = `command.tracked_tree` lúc chạy: `read-tree HEAD` + `add -u` (không `add -A`).
- **Cây trước**, theo thứ tự: (1) `tracked_tree` mà biên nhận của lần `pass` gần nhất của **chính mốc reviewer đó** (mọi revision) đã ghi — chỉ tính lần pass do reviewer ghi, có đúng cấu hình reviewer (model, tiêu chí…) đang chạy và có `tracked_tree` (biên nhận cũ không có thì bị bỏ qua); (2) chưa có thì `base_tracked` mà sự kiện `plan.approved` đầu tiên ghi lúc duyệt (khóa mới trong payload cũ, không phải loại sự kiện mới).
- **Không có đường dự phòng.** Thiếu cả hai (duyệt từ trước 2.2.0.dev2, hoặc `git` không đọc được lúc duyệt) thì không có cây trước, và cũng không có cách nào dựng nó từ thứ khác (không từ artifact `add -A`, không từ commit đoán): `verdict run` ghi biên nhận `inconclusive` với lỗi "no tracked-only base tree ...", không gọi model, `base_source: none`; `verdict diff` in đúng lỗi đó (exit 2). Cơ sở chỉ đọc từ lần duyệt **đầu** của plan, nên muốn tiếp tục phải lập lại plan (propose và duyệt) để lần duyệt đầu của nó ghi `base_tracked`.
Hệ quả: một file chưa theo dõi lúc duyệt rồi commit sau hiện ra là file mới (dòng `+`), không bao giờ có nội dung cũ của nó ở dòng `-`; file đã theo dõi mà bị xóa thật vẫn hiện.
Trần 120 KB giữ. **Artifact sha của verdict giữ nghĩa cũ**: cây `add -A` (có cả file chưa theo dõi) — đó là thứ `accept` gắn vào — còn model chỉ thấy hai cây tracked-only. Biên nhận ghi cả `artifact_sha` (add -A) lẫn `tracked_tree`, và `base_artifact`/`base_source` (`first_approval`, `previous_pass`, hoặc `none`) chỉ để quyết định ghi chú "no change since approval" (cây `add -A` giống hệt cây lúc duyệt thì pass không cần gọi model); chúng không bao giờ là một phía của diff.
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
`plan report` thêm, sau bảy mục, mục **"Reviewer ghi chú ngoài tiêu chí"** (không đánh số): mỗi mốc reviewer đã đạt và có `outside_criteria` một dòng tiêu đề, mỗi ghi chú một dòng gạch đầu dòng, cắt 300 ký tự. Không có ghi chú thì mục không xuất hiện; mọi mục khác và `plan digest` không đổi byte.
