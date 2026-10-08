# SPEC-005 — Chạy task theo từng phần và tự phục hồi

## Duyệt nhanh

### Kết quả
OneCrew tạo lại form CV từ thư mục trống; tự xây từng phần, test, review, sửa và commit bàn giao.

### Phạm vi
Sửa controller local/Codex của SPEC-004. Mỗi task sở hữu một file nhỏ, có contract giao tiếp rõ; lưu checkpoint sau từng file. Giữ API/nghiệm thu CV hiện có.

### Không làm
Không copy app cũ, tự deploy, dùng CV thật, thay test để xanh hoặc gọi JEV để thay worker viết code.

### Nghiệm thu
Một live run tự đi từ plan tới delivery, không assistant sửa source sản phẩm. Có bằng chứng chạy HTTP và review; lỗi được đưa lại cho worker trong ngân sách. Test cả timeout và sửa lỗi thật.

### Lưu ý
Tự vận hành không bảo đảm mọi task đều thành công; gặp hết budget hoặc lỗi không thể phục hồi phải báo rõ. Bot protection live, AV và hiệu quả chặn agent vẫn cần dịch vụ/kiểm chứng ngoài.

### Ngân sách
Lượt kiểm chứng đầu tối đa 30 phút, 24 calls, 3 vòng sửa; mỗi call 120 giây. Lượt đó đã dừng sau review với lỗi bắt buộc còn lại. Sau khi sửa contract/gate, lượt mới từ thư mục trống cấp trước tối đa 30 phút, 32 calls, 4 vòng sửa; không thay quota trong run cũ. Retry dùng chung counters, không tự tạo run mới. Các lượt và tổng usage được báo riêng.

### Cần quyết định
Không có; người dùng đã yêu cầu sửa và chạy lại từ đầu.

## Chi tiết cho AI

- IA01: Planner tạo DAG trên các file/module cho phép, ownership đúng một file/task; dependency và coverage được kiểm bằng code. Host contract định nghĩa giao tiếp, không chứa code implementation sản phẩm.
- IA02: Worker trả một file raw text thay vì JSON chứa toàn backend. Host validate path/size, syntax, lưu snapshot có manifest trước khi chuyển task. Context có giới hạn; không chạy source ngoài sandbox hiện có.
- IA03: Provider timeout/output lỗi được ghi ngay với usage unknown; tối đa một retry mỗi task trong ngân sách chung, giữ các task đã xong. Cancel/budget/tamper không retry. Không quảng cáo auto-resume sau controller crash.
- IA04: Test/review chỉ kích hoạt sửa file liên quan với nguyên lỗi, giữ test/AC; reverify toàn bộ sau sửa. Không mark delivery khi review/gate chưa đạt. Phát hiện không tiến triển vẫn dừng.
- IA05: Chạy mới, không sửa code sản phẩm bằng tay; controller lưu model/usage/calls, checkpoints, HTTP/browser evidence, review và commit. Phân biệt fixture/live. Mở bản local để khách hàng review khi có bản bàn giao đạt.

Model policy v4 dùng worker nhỏ cho plan/HTML/CSS/tài liệu, model mạnh hơn cho bảo mật/tích hợp/client flow, mọi repair và retry; reviewer độc lập kiểm toàn hệ thống. Repair không thay đổi source bị từ chối trước checkpoint. Đây là policy thử nghiệm có giới hạn và gate bắt buộc, chưa là benchmark tối ưu. Profile cũ vẫn tồn tại để đọc/test tương thích; CLI mặc định dùng profile incremental mới. JEV connection giữ nguyên, chưa cấp quyền dispatch tự động.
