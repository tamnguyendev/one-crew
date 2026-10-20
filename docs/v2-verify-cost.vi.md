# v2: kiểm rẻ hơn, giữ nguyên sáu bất biến (2.2.0.dev2)

Năm thay đổi, không thêm loại sự kiện, bảng hay migration. Sổ cũ đọc y nguyên.

## 1. Verdict đi theo mốc, không chỉ theo revision
Một mốc **được kế thừa** (`plan show`: `state: passed`, `carried_from: <revision gốc>`) khi revision đang xét **đã được chủ sở hữu duyệt**, mốc chưa có verdict nào ở revision này, và:
- verdict gần nhất của mốc đó (ở revision cũ hơn) là `pass`, và tiêu đề + verifier của mốc **byte-giống** (so JSON chuẩn hóa) với revision giữ verdict;
- artifact của verdict đó **bằng artifact hiện tại**, hoặc (mốc `command`) **chỉ khác ở đường dẫn trung lập** (`neutral_diff: true`).

Hệ quả: sửa chữ của mốc khác, đổi tiêu đề kế hoạch, đóng một unknown… không làm mất verdict của mốc không đổi, và `verdict run` mốc sau không bị chặn "mốc trước chưa đạt".

Hai trường hợp artifact đã đi khỏi verdict:
- Verdict `pass` nằm **ngay ở revision này** mà artifact hiện tại không còn được phủ (commit đổi file thật): mốc về `pending` kèm `stale: true`. Nó vẫn tính cho **thứ tự** (`verdict run` mốc sau không bị chặn, như 2.1) nhưng `accept` từ chối ("every milestone must have passed on exactly that artifact"); muốn nghiệm thu phải chạy lại mốc đó.
- Verdict **kế thừa** từ revision cũ mà không còn phủ artifact hiện tại: không có `stale`, mốc chỉ là `pending` như chưa từng có verdict, nên **chặn thứ tự** cho tới khi chạy lại.

`accept` ghi `carried` (mốc → revision gốc) vào sự kiện `plan.accepted` khi có kế thừa (một trường mới trong payload cũ, không phải loại sự kiện mới).

Không kế thừa khi: mốc đổi (tiêu đề, argv, cấu hình reviewer, tiêu chí); verdict gần nhất là fail/inconclusive; revision chưa duyệt; mốc `reviewer` hoặc `owner-manual` qua khác biệt trung lập (chúng nhìn chính các file đó). `plan report` và `plan digest` chưa tính kế thừa (đọc sổ thuần, không mở git).

## 2. `scope.neutral`
Danh sách glob (tối đa 20, mỗi cái ≤ 300 ký tự) trong `scope`. Cách khớp (`contract.neutral_match`, trên đường dẫn posix tính từ gốc repo): `*` và `?` **không** vượt qua `/`; `**` vượt qua (`docs/**` là mọi thứ dưới `docs/`; `**/*.md` là mọi `.md` ở mọi độ sâu; `*.md` chỉ là `.md` ở thư mục gốc, nên `onecrew/templates/x.md` không khớp). Không có `[lớp ký tự]`. Vắng thì **đọc** là `docs/**`, `*.md`, `CHANGELOG*` — không ghi vào hợp đồng, nên hợp đồng cũ không đổi byte. `"neutral": []` tắt hẳn.
Một commit chỉ chạm đường dẫn trung lập: mốc `command` vẫn `passed`, mốc `reviewer` về `pending`. `owner accept --artifact-sha <sha>` nhận verdict kế thừa khi artifact của verdict và artifact nghiệm thu chỉ khác trung lập; mọi mốc vẫn phải `passed`; mốc reviewer phải đạt đúng trên artifact nghiệm thu. Lấy artifact hiện tại: `onecrew verdict artifact --plan P` (JSON `{"artifact_sha": ...}`).

## 3. Reviewer chỉ đọc file có theo dõi
Diff gửi model = `git diff <cơ sở> <HEAD + sửa đổi file đã theo dõi>`. Ở phía hiện tại, file chưa theo dõi hoặc bị ignore **không bao giờ** vào diff (không còn `build/` làm vỡ trần 120 KB); file mới chưa commit cũng chưa vào — commit trước khi chạy verdict. Cơ sở = artifact của lần `pass` gần nhất của **chính mốc reviewer đó** (mọi revision), chưa có thì cây lúc duyệt đầu như cũ.
Cơ sở là artifact kiểu cũ (có cả file chưa theo dõi lúc đó), nên trước khi so, những đường dẫn **chỉ nằm chơi** lúc tạo cơ sở được bỏ khỏi cơ sở để không hiện thành "bị xóa". Một đường dẫn bị bỏ khi nó có trong cơ sở, không còn ở cây hiện tại, **không có trong HEAD hiện tại** và **không có trong cây của commit cuối cùng trước lúc tạo cơ sở** (lúc duyệt, hoặc lúc lần pass trước; vì giờ commit chỉ tính theo giây, cây của commit cuối của giây liền trước cũng được tính; không xác định được commit thì chỉ dùng hai điều kiện đầu). Không quét lịch sử. File đã theo dõi mà bị xóa thật vẫn hiện.
Giới hạn còn lại, nói thẳng: một đường dẫn đã theo dõi ở commit đó nhưng lúc tạo cơ sở là file chưa theo dõi nằm trên đĩa (ví dụ `git rm --cached` mà file còn đó) vẫn có thể hiện ra như file bị xóa phía cơ sở. Và file chưa theo dõi lúc lần pass trước rồi được commit sau nguyên văn thì không vào các diff sau.
Trần 120 KB giữ. Biên nhận vẫn ghi `artifact_sha` kiểu cũ (gồm file chưa theo dõi) và `base_source: previous_pass` khi cơ sở là lần pass trước.
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
