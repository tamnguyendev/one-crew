# Giao việc nền và chờ quyết định — 09/10/2026

**Cập nhật 09/10, sau revision 9:** [vòng đời thông báo hiện tại](notification-watch.vi.md). Đã sửa lỗi file tạm Windows làm batch không được giao. Host watch chỉ theo các Task ID gắn với chat, ACK trả điều kiện tự pause khi hết việc/chờ người dùng. Entry bật lại khi dispatch/resume. Đây là scheduled checking có giới hạn, chưa phải callback trực tiếp; cần phân biệt test lifecycle với một lần host thực sự gửi và pause. Pull/ack/inbox giữ nguyên.

Phạm vi: các comment về trả lại chat sau dispatch, build dài, terminal verbose nhóm agent, thông báo và skip câu hỏi. Không mở rộng model routing hay sửa sản phẩm SRM.

| ID | Yêu cầu nghiệm thu |
|---|---|
| BG01 | Android build mặc định dispatch sang tiến trình nền Windows; CLI trả task/key/PID và lệnh status sau handshake giới hạn, không chờ build. Foreground chỉ khi yêu cầu rõ. |
| BG02 | Tối đa một build native đồng thời trên cùng state-root, gồm nhiều project và đường foreground; queue không gọi model. |
| BG03 | Cùng key/config không chạy trùng; khác config bị từ chối; cancel riêng build; chết runner được báo interrupted, không tự replay; deadline queue và build riêng, đều hữu hạn. |
| IN01 | Câu hỏi bắt buộc lưu trước khi hiển thị chat; defer/skip giữ pending và revision, không tự chọn recommendation; trả lời từ entry khác vẫn dùng đúng revision. |
| IN02 | Feed thông báo bền vững cho kết quả, blocked và câu hỏi; đọc không mất thông báo, ack không trả lời câu hỏi; restart/retry không mất dữ liệu. |
| IN03 | Cầu nối thông báo về chat hiện tại bằng khả năng host hỗ trợ; không hứa callback tức thì khi chỉ có polling. |
| UX01 | Terminal theo dõi build nền, agent nhóm project/task/unit, câu hỏi và lệnh trả lời; đóng viewer không dừng runner. |

Entry phải kết thúc lượt trả lời sau khi xác nhận dispatch, không giữ vòng poll build trong chat. Khi hỏi trạng thái, đọc một lần. Câu hỏi tùy chọn chỉ tiếp tục theo giả định đã nói rõ, trong quyền hiện hữu; approval bắt buộc không được thay bằng giả định. Câu hỏi bắt buộc dùng `request create` trước thẻ chat; khi thẻ bị dismiss dùng `request defer`. Câu hỏi trong UI không phải receipt approve.

Deadline workflow hiện có vẫn tính cả chờ người dùng. Không tự gia hạn budget: hết hạn → blocked, câu hỏi còn pending. Trả lời muộn cần kiểm tra deadline và resume/extension được cấp quyền. Build có thời gian chờ queue riêng để không tiêu hết thời gian thực thi chỉ vì chờ slot.

Trạng thái thực thi và bằng chứng kiểm thử xem `proposal-coverage.md`; tài liệu này là contract, không phải tuyên bố đã hoàn thành.
