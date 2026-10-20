# v2: kiểm rẻ hơn, giữ nguyên sáu bất biến (2.2.0.dev2)

Bốn thay đổi, không thêm loại sự kiện, bảng hay migration. Sổ cũ đọc y nguyên.

## 1. Verdict đi theo mốc, không chỉ theo revision
Một mốc **được kế thừa** (`plan show`: `state: passed`, `carried_from: <revision gốc>`) khi revision đang xét **đã được chủ sở hữu duyệt** và:
- verdict gần nhất của mốc đó (ở revision cũ hơn) là `pass`, và tiêu đề + verifier của mốc **byte-giống** (so JSON chuẩn hóa) với revision giữ verdict;
- artifact của verdict đó **bằng artifact hiện tại**, hoặc (mốc `command`) **chỉ khác ở đường dẫn trung lập** (`neutral_diff: true`).

Hệ quả: sửa chữ của mốc khác, đổi tiêu đề kế hoạch, đóng một unknown… không làm mất verdict của mốc không đổi, và `verdict run` mốc sau không bị chặn "mốc trước chưa đạt".
Ngược lại, một verdict `pass` mà **artifact đã đi khỏi** (commit đổi file thật) thì mốc về `pending` (`stale: true`): muốn nghiệm thu, chạy lại — như trước, nhưng giờ `plan show` nói thẳng. `accept` ghi `carried` (mốc → revision gốc) vào sự kiện khi có kế thừa.

Không kế thừa khi: mốc đổi (tiêu đề, argv, cấu hình reviewer, tiêu chí); verdict gần nhất là fail/inconclusive; revision chưa duyệt; mốc `reviewer` hoặc `owner-manual` qua khác biệt trung lập (chúng nhìn chính các file đó). `plan report` và `plan digest` chưa tính kế thừa (đọc sổ thuần, không mở git).

## 2. `scope.neutral`
Danh sách glob (tối đa 20, mỗi cái ≤ 300 ký tự; so bằng `fnmatch` trên đường dẫn có `/`) trong `scope`. Vắng thì **đọc** là `docs/**`, `*.md`, `CHANGELOG*` — không ghi vào hợp đồng, nên hợp đồng cũ không đổi byte. `"neutral": []` tắt hẳn.
Một commit chỉ chạm đường dẫn trung lập: mốc `command` vẫn `passed`, mốc `reviewer` về `pending`. `owner accept --artifact-sha <sha>` nhận verdict kế thừa khi artifact của verdict và artifact nghiệm thu chỉ khác trung lập; mọi mốc vẫn phải `passed`; mốc reviewer phải đạt đúng trên artifact nghiệm thu. Lấy artifact hiện tại: `onecrew verdict artifact --plan P` (JSON `{"artifact_sha": ...}`).

## 3. Reviewer chỉ đọc file có theo dõi
Diff gửi model = `git diff <cơ sở> <HEAD + sửa đổi file đã theo dõi>`. File chưa theo dõi hoặc bị ignore **không bao giờ** vào diff (không còn `build/` làm vỡ trần 120 KB); file mới chưa commit cũng chưa vào — commit trước khi chạy verdict. Cơ sở = artifact của lần `pass` gần nhất của **chính mốc reviewer đó** (mọi revision), chưa có thì cây lúc duyệt đầu như cũ. File chỉ nằm chơi (chưa theo dõi) lúc tạo cơ sở được bỏ khỏi cơ sở, nên không hiện thành "bị xóa"; file đã theo dõi mà bị xóa thật vẫn hiện. Trần 120 KB giữ. Biên nhận vẫn ghi `artifact_sha` kiểu cũ (gồm file chưa theo dõi) và `base_source: previous_pass` khi cơ sở là lần pass trước.
`onecrew verdict diff --plan P --milestone M` in đúng diff đó ra stdout: 0 lượt gọi model, không ghi sổ, không cần mốc trước đạt.
`verdict run` giờ từ chối **trước khi chạy** khi mốc trước chưa đạt hoặc mốc đã đạt trên đúng artifact này (trước đây chạy xong mới từ chối — reviewer tốn tiền).

## 4. `plan lint` kiểm tiêu chí và bước 0
Lint vẫn chỉ đọc, không gọi model.
| Mã | Khi nào | Hậu quả |
|---|---|---|
| `criterion_literal_present` | một chuỗi trong nháy đơn/kép/backtick dài ≥ 4 trong câu hỏi mà `git grep -F` thấy ở HEAD | cảnh báo, exit 0 |
| `criterion_no_fail_clause` | câu hỏi không có "fail if" (không phân biệt hoa thường) | từ chối, exit 1 |
| `criterion_vs_non_goal` | câu hỏi và một non_goal có từ chung ≥ 6 chữ cái (khớp 6 chữ đầu: message/messages) | cảnh báo, exit 0 |
| `unknowns_missing` | cỡ M/L, `unknowns` rỗng, không có `understanding.no_unknowns_because` (≤ 300 ký tự) | từ chối ở lint và ở `approve` |
`--ack-criteria` tắt hai cảnh báo (không tắt `criterion_no_fail_clause`). `unknowns_missing` áp cho mọi hợp đồng cỡ M/L ở lint và ở `approve` (hợp đồng cũ không có trường vẫn đọc được và hiển thị, nhưng muốn duyệt thì phải thêm). Mẫu có chỗ trống: `examples/contract-template.json`.

## 5. Report
`plan report` thêm, sau bảy mục, mục **"Reviewer ghi chú ngoài tiêu chí"** (không đánh số): mỗi mốc reviewer đã đạt và có `outside_criteria` một dòng tiêu đề, mỗi ghi chú một dòng gạch đầu dòng, cắt 300 ký tự. Không có ghi chú thì mục không xuất hiện; mọi mục khác và `plan digest` không đổi byte.
