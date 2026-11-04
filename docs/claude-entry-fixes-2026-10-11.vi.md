# Bàn giao: các sửa OneCrew do Claude (entry linh-thuoc) làm 10–12/10/2026

Các sửa này làm khi OneCrew chạy thật cho `nursing-assistant-linh-thuoc` (extension Chrome, recipe Node). Mỗi lỗi đều gặp thật, có test và có commit riêng. Chưa push vì repo này chưa có remote. Nhánh hiện tại đã chứa đủ các commit dưới đây.

| Commit | Sửa | Lý do (task gặp lỗi) |
|---|---|---|
| `a21b274` | Trích dẫn native audit lệch dòng giờ được sửa lại trong cùng session (tối đa 2 vòng), không chặn task | TASK-79ddce05 |
| `ad772c1`, `164d128` | Thêm toolchain **node** cho native_change: tsc, Vitest, build cố định | Extension TypeScript |
| `e184895` | Worker thấy được assertion nào fail; bản vá thiếu file thành một vòng sửa, không chặn cứng | TASK-443d7386 |
| `6436aed` | File gốc CRLF giữ nguyên CRLF; diff gửi review chỉ chứa nội dung thật | Diff thô 176 KB |
| `9a55689` | Tài liệu `docs/node-change.vi.md` | — |
| `d68dc83` | Discovery đọc được `.mjs/.cjs/.mts/.cts`; native audit bật được ngay từ đầu | Harness e2e `.mjs` |
| `c8a52f8`, `a0e71ce` | Recipe Node có bước e2e cố định tuỳ chọn ("N/N checks passed" ≥ min_checks); `tests` được để trống khi có e2e | E2E mock panel |
| `f310538`, `22f485e` | Native audit chạy tiếp trong cùng session khi chạm giới hạn lượt của CLI (`error_max_turns`) | TASK-4e44fabe |
| `f8e8c49` | `job outputs` không còn KeyError với bằng chứng test không có `exit_code` | Mọi task Node |
| `900f321` | Snapshot native chụp được file nguồn tới **2 MB** (`CAPTURE_MAX`); API đọc của worker vẫn 200 KB | `controller.ts` 254 KB bị bỏ qua, gây "Writable file not captured" |
| `240472f` | Worker được trả **đoạn sửa có neo** cho file lớn: `{path, edits:[{find, replace}]}`. Các đoạn sửa áp theo thứ tự lên file GỐC, mỗi `find` phải khớp đúng một chỗ, file CRLF vẫn giữ CRLF. Đoạn sửa lỗi thì được yêu cầu sửa lại và không cài gì; file mới vẫn phải gửi cả nội dung | Không trả nổi cả file 4005 dòng (TASK-6609f7ad) |
| `850300d` | Worker change chạy tiếp trong cùng session khi chạm giới hạn lượt (tối đa 4 lần). Attempt sai định dạng không còn bị coi là chạm giới hạn lượt | TASK-1ab57f54; test `test_native_tool_receipts` |
| `3c3de4a` | Câu hỏi giả như "none", "n/a" được coi là không có câu hỏi | TASK-d41d4f28 |

Bộ test đầy đủ (`python -m unittest` trên mọi `tests/test_*.py`) sau `850300d` có cùng 19 lỗi như mốc cũ (1 failure, 18 errors có sẵn), không có lỗi mới.

**Gợi ý cho phiên phát triển OneCrew:**
- Rà lại `240472f` (định dạng `edits`) trước khi coi là hợp đồng ổn định.
- Cân nhắc cho chế độ `execution: workspace` (Edit/Write trực tiếp) hỗ trợ toolchain node.
- Repo cần có remote thì mới push được.
