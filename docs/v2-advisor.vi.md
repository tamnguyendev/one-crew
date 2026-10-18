# v2: nguồn yêu cầu, quyết định và cố vấn (job 9)

Hợp đồng v2 có thêm các trường TÙY CHỌN (hợp đồng cũ vẫn đọc được): `origin` {by, at, quote ≤500}, `decisions` [{id D1.., choice, alternative, cost}] (0–10), `items[].source` (`origin` hoặc id quyết định), `presentation` (lời của hai tin gửi chủ sản phẩm). `plan show` in origin, decisions, nguồn của từng mục và lời cố vấn mới nhất.

## Khi nào approve từ chối (mã lý do có kiểu)
- `origin_missing`: không có `origin`. `item_without_source`: có mục không có `source`. `unknown_decision`: `source` trỏ id không có trong `decisions` (luôn kiểm).
- `advice_missing`: `decisions` khác rỗng, HOẶC size M/L, mà revision đang duyệt chưa có sự kiện `plan.advised` dùng được. Size S không có quyết định thì không cần cố vấn.
- Ba lý do đầu và luật size M/L áp cho hợp đồng dùng bất kỳ trường mới nào, và cho MỌI hợp đồng khi file quy tắc đã có trong state-root. Hợp đồng cũ trong state-root chưa `plan rules init` không bị đòi (giữ test cũ). Phản đối của cố vấn không bao giờ chặn; chỉ việc thiếu lời cố vấn dùng được mới chặn.

## Ba câu hỏi cố định (`plan advise <tên> [--model claude-opus-5-5]`)
Một lần gọi `claude -p` như reviewer (không công cụ, thư mục trống, JSON). Mỗi câu trả `{verdict: ok|objection, note ≤300}`; chỉ xét theo file quy tắc.
- Q1: hợp đồng có làm nhiều hơn `origin.quote` yêu cầu không?
- Q2: có quyết định (hoặc việc thiếu quyết định cho một mặc định hiển nhiên) nào mâu thuẫn một quy tắc trong file không?
- Q3: thứ tự mục/mốc có trái một quy tắc không (vd. release trước khi chạy thử)?

Độc lập: cùng `qc_gate.independence` như reviewer, đối với tác giả của revision; cùng model hoặc tác giả không rõ model → từ chối trước khi gọi (tên tác giả phải là mã model, vd. `claude-fable-5-1`). Kết quả ghi `plan.advised` {revision, sha, model, independence, answers, usable, receipt}; receipt là blob chứa prompt, đầu ra thô và câu trả lời đã phân tích. Trả lời hỏng → `inconclusive`, không dùng được.

## File quy tắc
`examples/owner-rules.vi.md` (R1..R6 và mẫu 5 mục) → `plan rules init` chép sang `<state-root>/plans/owner-rules.md` nếu chưa có (không bao giờ ghi đè); `plan rules show` in ra. Thiếu file: `plan advise` ghi lời khuyên `inconclusive` với ghi chú "no owner-rules file", không gọi model và không tính là đã có lời cố vấn. Hook UserPromptSubmit thêm một dòng nêu đường dẫn file khi nó tồn tại.
