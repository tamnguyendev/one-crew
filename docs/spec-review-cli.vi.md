# CLI duyệt spec — lát đầu của OneCrew

## Yêu cầu và phạm vi

Nguồn: yêu cầu người dùng ngày 08/10/2026: liệt kê spec, review nhanh bằng lời dễ hiểu, approve qua CLI; file vẫn chứa chi tiết cho AI.

Một file Markdown có hai phần: `Duyệt nhanh` và `Chi tiết cho AI`. Phần nhanh là hợp đồng về kết quả, phạm vi, việc để sau, nghiệm thu, lưu ý, ngân sách và câu hỏi. Chi tiết mô tả cách triển khai, interface và kiểm thử; không tự thêm nghĩa vụ sản phẩm không được nêu ở phần nhanh. CLI không thể tự xác minh hoàn toàn tính nhất quán ngữ nghĩa giữa hai phần.

| ID | Yêu cầu nghiệm thu |
|---|---|
| SR01 | Một file chứa cả bản nhanh và chi tiết; bản nhanh đủ bảy mục, tối đa 350 từ tách bằng khoảng trắng; không cắt bỏ nội dung để vừa màn hình |
| SR02 | `spec list` hiện ID, tên, trạng thái; `--pending` lọc các spec chưa được duyệt đúng nội dung hiện tại |
| SR03 | `spec review ID` hiện phần nhanh và mã phiên bản; `--full` hiện cả file; các lệnh đọc không gọi model hoặc ghi state |
| SR04 | `spec approve ID --revision HASH` ghi quyết định cho đúng SHA-256 nội dung đã xem, thời điểm và người ghi nhận; từ chối hash cũ và câu hỏi chưa chốt |
| SR05 | `spec request-changes ID --revision HASH --comment TEXT` ghi yêu cầu sửa; không xóa spec hoặc mất quyết định trước |
| SR06 | `spec diff ID` so bản nhanh với quyết định gần nhất, báo riêng nếu chi tiết đổi; `--full` cho diff đầy đủ; `spec history ID` xem các quyết định |
| SR07 | File sai định dạng, trùng ID, đường dẫn thoát project và state lỗi không được diễn giải thành approved; sửa file sau duyệt làm trạng thái cần duyệt lại |
| SR08 | Chạy trên Windows bằng Python chuẩn, không cần dịch vụ/model; có launcher, spec mẫu và test luồng sử dụng |

Ngoài lát này: dispatch agent, nhập tự động spec cũ của nursing-assistant, xác thực người dùng, kho approval cách ly worker, dashboard, nhiều máy. Lệnh approve ở đây là sổ quyết định local, chưa phải biên giới phân quyền chống một agent có toàn quyền filesystem. Tên người duyệt là nhãn được khai báo hoặc tên tài khoản hệ điều hành, chưa xác thực danh tính.

Approve ghi nhận đồng ý spec, không chạy AI, không chứng nhận chức năng đã đạt và không cho phép deploy. Các nội dung spec cũ vẫn giữ nguyên.

## Cách chạy

Từ thư mục OneCrew, dùng Python 3.10 trở lên:

```powershell
python -m onecrew spec list
python -m onecrew spec review SPEC-001
python -m onecrew spec review SPEC-001 --full
python -m onecrew spec diff SPEC-001
python -m onecrew spec approve SPEC-001 --revision <mã-vừa-hiện>
python -m onecrew spec request-changes SPEC-001 --revision <mã-vừa-hiện> --comment "Chỉ làm luồng đọc và duyệt trước"
python -m onecrew spec history SPEC-001
```

Launcher Windows: `./onecrew.ps1 spec list`. Nó dùng `.venv/Scripts/python.exe` của OneCrew nếu có, hoặc `python.exe` trên PATH. Có thể đặt `ONECREW_PYTHON` để chọn interpreter; không cần đổi cài đặt global. Launcher giữ nguyên thư mục đang đứng, trừ khi người dùng chỉ rõ project:

```powershell
./onecrew.ps1 --project "D:\duong dan\project" spec list --pending
```

Các lệnh hỗ trợ `--json`. `--by "Tên người duyệt"` là tùy chọn trên hai lệnh ghi quyết định. Mã revision là 12 ký tự đầu SHA-256; sổ lưu hash đầy đủ. Khi nội dung thay đổi dù chỉ ở chi tiết, bản cũ không còn duyệt cho bản mới. `diff` giúp tránh đọc lại toàn bộ. Thay đổi xuống dòng CRLF/LF đơn thuần được chuẩn hóa; các thay đổi nội dung khác không bị bỏ qua.

Spec nằm ở `specs/SPEC-*.md`. Sổ quyết định SQLite ở `.onecrew/spec-reviews.sqlite3`, nằm ngoài Git; mỗi quyết định giữ snapshot nội dung. SQLite là kho quyết định local, không phải scheduler. CLI chỉ hash file spec này, chưa theo dõi nội dung tài liệu được liên kết.

## Quy ước viết

Dùng [spec mẫu](../specs/SPEC-001-duyet-spec.md). Bản nhanh trả lời:

1. Người dùng sẽ làm được gì?
2. Lần này làm những gì?
3. Những gì để sau?
4. Thử thế nào để biết đạt?
5. Có thay đổi/rủi ro gì cần biết?
6. Ngân sách hoặc giới hạn công việc?
7. Còn quyết định nào chưa chốt?

Mục `Cần quyết định` dùng `Không có.` hoặc checklist `- [ ]` / `- [x]`. Còn ô chưa chọn thì chưa approve được. Mọi mục khác phải có nội dung. Nếu bản nhanh vượt 350 từ, CLI báo lỗi để tác giả viết gọn hoặc chia lát; không tự giấu bớt điều kiện.

Tác giả cập nhật cả hai phần trước khi đề nghị duyệt. Không tóm tắt lại bằng một lần gọi LLM mỗi khi mở màn hình: CLI hiển thị nguyên phần nhanh trong đúng file đang duyệt, nên đọc/duyệt không tiêu token model.
