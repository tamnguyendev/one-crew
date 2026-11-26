# Mẫu prompt có phiên bản

OneCrew có tám mẫu prompt: mẫu giao việc (`mau-giao-viec`), mẫu nhắc khi chủ sở hữu gõ thẳng (`mau-loi-chu`) và sáu mẫu vai `onecrew/templates/role-*.md` (điều phối, kiểm, trao đổi; tiếng Việt và tiếng Anh). Skill đã duyệt của dự án **không** nằm trong danh sách này (xem `skills list`).

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

## Mẫu vai nằm ở đâu

Sáu mẫu vai đi cùng gói cài, là sáu tệp nằm thẳng trong `onecrew/templates/`, nên máy chỉ có bản cài vẫn thấy đủ tám mẫu:

| Vai | Tệp trong gói | Tên mẫu | Bản chép trong mã nguồn |
|---|---|---|---|
| Điều phối | `role-coordinator.vi.md`, `role-coordinator.en.md` | `vai-dieu-phoi-vi`, `vai-dieu-phoi-en` | `docs/vai3/dieu-phoi.*.md` |
| Kiểm | `role-checker.vi.md`, `role-checker.en.md` | `vai-kiem-vi`, `vai-kiem-en` | `docs/vai3/kiem.*.md` |
| Trao đổi | `role-liaison.vi.md`, `role-liaison.en.md` | `vai-trao-doi-vi`, `vai-trao-doi-en` | `docs/vai3/trao-doi.*.md` |

Lệnh đọc các tệp `role-*.md` của gói, rồi đọc `<dự án>/docs/vai3/*.md` (dự án là thư mục của `--project`, mặc định là thư mục hiện tại) và đối chiếu theo **tên mẫu** ở dòng đầu:

- mẫu của dự án thắng mẫu trong gói cùng tên mẫu, dù tên tệp khác nhau; các mẫu khác vẫn lấy từ gói;
- tệp của dự án không có dòng đầu hợp lệ lấy tên theo tên tệp (`kiem.vi.md` thành `vai-kiem-vi`), nên vẫn thắng mẫu cùng tên; `onecrew mau lint` báo thiếu dòng đầu;
- mẫu chỉ có ở dự án được thêm vào danh sách;
- cột đường dẫn của `onecrew mau list` cho biết mỗi mẫu đọc từ đâu.

Chỉ khi cả gói lẫn dự án đều không có mẫu vai thì lệnh mới in một dòng ghi chú.

### Tự sửa một mẫu vai

1. Chạy `onecrew mau list` để lấy đường dẫn của mẫu trong gói.
2. Chép tệp đó sang `<dự án>/docs/vai3/` (tên tệp tùy bạn, ví dụ `kiem.vi.md`).
3. Sửa bản chép: giữ `ten=` ở dòng đầu để nó thay đúng mẫu, và tự tăng số `phien-ban`.
4. Chạy `onecrew mau lint` ở dự án.

Không sửa tệp ngay trong gói đã cài: lần nâng cấp sau sẽ ghi đè. Ngược lại, bản chép trong dự án vẫn thắng sau khi nâng cấp gói và không có cảnh báo lệch phiên bản; muốn dùng mẫu mới của gói thì xóa bản chép hoặc cập nhật nó.

Trong mã nguồn OneCrew, `docs/vai3/` là bản chép giữ khớp từng byte với sáu tệp `onecrew/templates/role-*.md` (bảng trên): sửa một mẫu thì sửa cả hai chỗ, test sẽ báo khi lệch.

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
