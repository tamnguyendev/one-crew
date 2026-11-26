# Mẫu prompt có phiên bản

OneCrew có tám mẫu prompt: mẫu giao việc (`mau-giao-viec`), mẫu nhắc khi chủ sở hữu gõ thẳng (`mau-loi-chu`) và sáu mẫu vai trong `docs/vai3/` (điều phối, kiểm, trao đổi; tiếng Việt và tiếng Anh). Skill đã duyệt của dự án **không** nằm trong danh sách này (xem `skills list`).

## Dòng đầu và số phiên bản

Dòng đầu tiên của mỗi mẫu khai tên và số phiên bản:

- tệp mẫu giao việc, mẫu lời chủ: `# onecrew-mau: ten=mau-giao-viec phien-ban=1`
- tệp mẫu vai (markdown): `<!-- onecrew-mau: ten=vai-kiem-vi phien-ban=1 -->`

Tên viết thường, gồm chữ không dấu, số và dấu `-`; `phien-ban` là số nguyên. Trình đọc mẫu giao việc bỏ qua dòng này như dòng chú thích. Dòng đầu của mẫu lời chủ được bỏ đi trước khi lời nhắc gửi vào phiên; tệp chỉ có dòng đầu được coi là rỗng (tắt lời nhắc).

Tệp của bạn trong `<state-root>/plans/` (`mau-giao-viec.md`, `mau-loi-chu.md`) thay cho mẫu có sẵn. Tệp chưa có dòng đầu vẫn chạy như cũ; phiên bản hiện là `chua-ghi`. OneCrew không tự sửa tệp của bạn.

### Khi nào tăng số phiên bản

Người sửa mẫu tự tăng số mỗi khi đổi nội dung làm người nhận phải làm khác đi (thêm, bớt, đổi mục, từ khóa, phần của vai, câu chỉ dẫn). Sửa lỗi chính tả không đổi nghĩa thì không cần. Máy không tự tăng số và chưa cảnh báo khi quên; băm ngắn trong `onecrew mau list` đổi theo nội dung nên so được hai lần xem.

## onecrew mau list

```
onecrew --project <dự án> mau list
```

Mỗi mẫu một dòng: tên, `phien-ban=<số hoặc chua-ghi>`, băm ngắn (12 ký tự đầu SHA-256 của nội dung) và đường dẫn. Mẫu có sẵn trong chương trình ghi `(có sẵn trong chương trình)` hay `(built into the program)` thay cho đường dẫn.

Sáu mẫu vai không nằm trong gói cài: lệnh đọc `<dự án>/docs/vai3`, không có thì đọc `docs/vai3` cạnh mã nguồn đang chạy; không có cả hai thì in một dòng ghi chú. Với bản cài từ gói, trỏ `--project` vào bản mã có thư mục đó.

## onecrew mau lint

```
onecrew --project <dự án> mau lint
```

Kiểm mọi mẫu theo một quy chuẩn chung, in từng lỗi dạng `<tên> <đường dẫn>:<dòng>: <lỗi>`; có lỗi thì thoát mã khác 0.

- **Dòng đầu**: có, đúng cú pháp.
- **Không chồng chéo**: hai mẫu không cùng tên; mẫu giao việc không có mục viết hai lần, hai mục không dùng cùng một từ khóa; mẫu vai không viết một phần hai lần.
- **Không bỏ trống**: mẫu giao việc đủ sáu mục (Mục tiêu, Tệp được sửa, Xong khi, Không làm, Cách kiểm, Skill; mục được tính khi trùng tên hoặc có một từ khóa của mục có sẵn), mục nào cũng có từ khóa, không có dòng lạ; mẫu vai đủ bốn phần (Việc của vai, Không làm, Nhận việc từ, Báo cho; bản tiếng Anh: Role, Not doing, Takes work from, Reports to) và phần nào cũng có chữ.

Tệp mẫu lời chủ rỗng nghĩa là bạn đã tắt lời nhắc: chỉ ghi chú, không tính lỗi. Lint không chấm chất lượng chữ.

Cả hai lệnh chỉ đọc tệp mẫu: không mở sổ, không ghi gì.

## Phiên bản đã dùng được ghi ở đâu

- Dòng `reminded` của lời nhắc giao việc (và lời nhắc gửi vào phiên) ghi `mẫu mau-giao-viec@<số>`. Lời nhắc vẫn không chặn.
- Dòng tóm tắt theo dõi của một lời giao việc (Agent, Task, SendMessage, start_session, send_message) mang `template: mau-giao-viec` và `template_version` (trống khi tệp chưa ghi số). Đó là bản mẫu đang hiệu lực lúc giao.

## Để lát sau

So kết quả có và không có skill, rút lại skill khi kém; đưa skill vào cùng danh sách; hiện phiên bản trên trang theo dõi; ghi phiên bản theo từng lần giao ngoài hai chỗ trên; máy so băm cũ với băm mới để báo "sửa mà quên đổi số".
