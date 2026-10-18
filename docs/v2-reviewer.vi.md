# v2: mốc do reviewer kiểm (verifier `reviewer`)

Một mốc khai `verifier: {"type": "reviewer", "config": {...}}` (mỗi mốc một verifier; muốn cả lệnh lẫn reviewer thì hai mốc). Ví dụ: `examples/v2-reviewer-milestone.json`.

```json
{"provider": "claude", "model": "claude-haiku-5-5", "max_minutes": 10,
 "criteria": [{"id": "R1", "question": "Trong onecrew/v2/verdict.py, run() có gọi reviewer.check_independence trước reviewer.run không?"}]}
```

## Chạy thế nào
`verdict run --plan P --milestone M` gọi `claude -p` đúng một lần (không công cụ, không phiên lưu, cwd trống). Prompt = diff giữa cây lúc chủ sở hữu duyệt (`plan.approved.base_artifact`; plan cũ: commit cuối trước giờ duyệt) và cây hiện tại, cộng các criterion. Báo cáo của tác giả, thông điệp commit và chữ trong plan không vào prompt.
Trước khi gọi: `qc_gate.independence`. Cùng hãng mà cùng model, hoặc tác giả cùng hãng nhưng không rõ model → từ chối, không tốn call. Tác giả lấy từ `author` và `content_author` của revision; model tác giả là `author_model` của sự kiện hoặc chính tên tác giả nếu là mã model (`--author claude-opus-5-5`).

## Kết luận
- `pass` chỉ khi MỌI criterion trả `pass` kèm bằng chứng `{file, line, note}`; có criterion `fail` → `fail`; còn lại `inconclusive`.
- `inconclusive` (không bao giờ pass): JSON hỏng, thiếu criterion, verdict lạ, pass/fail không có file, hết giờ, CLI lỗi, diff rỗng hoặc quá 120 KB, cây đổi trong lúc review.
- `outside_criteria` được lưu trong receipt, không đổi kết luận; criterion ngoài hợp đồng bị bỏ.

## Viết criterion trả lời được bằng file:dòng
Một câu hỏi có đáp án có/không, chỉ vào file hoặc loại thay đổi. Schema từ chối câu hỏi không có `/`, đuôi file, hay chữ như test, assert, diff, file, line, dòng.

| Tốt | Xấu |
|---|---|
| "Trong tests/test_x.py, mỗi test mới có assert vào kết quả (không chỉ chạy không lỗi) không?" | "Test có tốt không?" |
| "Diff có xóa dòng nào khỏi onecrew/v2/gate.py không?" | "Có vấn đề bảo mật không?" |
| "Hàm parse() trong a.py có nhánh nào trả pass khi JSON hỏng không?" | "Code có sạch không?" |

Mẹo: một criterion một khẳng định; nêu cái gì thì `fail` ("fail nếu thấy..."); đừng hỏi về thứ ngoài diff (reviewer chỉ thấy diff, không thấy repo).

## Giới hạn đã biết
Reviewer chỉ có Claude (hợp đồng từ chối provider khác). Receipt lưu diff, prompt, câu trả lời gốc, token và giá (blob trong state-root). Cây gốc là đối tượng Git chưa được tham chiếu; `git gc` sau vài tuần có thể xóa, diff trong receipt vẫn còn.

## Diff rỗng so với cây đã duyệt (job 4)

Khi cây đang xét **đúng bằng** cây chủ sở hữu duyệt (`base_source == "approval"` và `base_artifact == artifact_sha`, diff rỗng) thì không còn gì để review và cũng không còn gì để sửa: verdict là `pass`, receipt ghi `note: "no change since approval"`, `calls: 0`, mỗi tiêu chí `pass` với `evidence` rỗng. Verdict `pass` không phải lỗi nên không tính vào `repairs_used`/`failures`. Đây là nhánh DUY NHẤT pass mà không gọi model: `expected_result` coi một pass `calls: 0` là `inconclusive` nếu thiếu note đó, nếu base không đến từ approval, hoặc nếu cây khác base. Base lấy từ "commit cuối trước lúc duyệt" (plan cũ) mà diff rỗng vẫn là `inconclusive`, không gọi gì (như trước). Diff không rỗng vẫn gọi reviewer.
