# Cấm sửa test có sẵn

Test có sẵn là thước đo cho việc mới. Một phiên làm sửa test cũ cho tới khi đạt thì bộ kiểm vẫn báo xanh, nhưng không còn đo gì. Vì thế OneCrew mặc định không cho phiên làm sửa test đã có, trừ khi hợp đồng nói rõ là được.

## Test có sẵn là gì

Một tệp có trong commit HEAD của dự án, và thoả một trong hai điều:

- nằm dưới một thư mục tên `test`, `tests` hay `__tests__`, ở bất kỳ cấp nào;
- có tên dạng `test_*`, `*_test` hay `*_tests`, phần mở rộng thế nào cũng được.

Tệp test chưa có trong HEAD là test mới. Test mới luôn viết và sửa được.

## Cảnh báo của `plan lint`: `owned_covers_existing_tests`

`plan lint` in cảnh báo `owned_covers_existing_tests` khi:

- `scope.owned` của hợp đồng trùm ít nhất một test có sẵn (thư mục như `tests/`, glob như `src/**`, hay chính tên tệp test), và
- hợp đồng chưa cấp quyền sửa test (xem dưới).

Cảnh báo nêu số tệp, tối đa 3 tên tệp, và cách xử lý. Đây chỉ là cảnh báo: `plan lint` vẫn kết thúc với mã 0, hợp đồng vẫn đề xuất và duyệt được.

Cảnh báo không hiện khi:

- `scope.owned` chỉ nêu tệp test chưa có trong HEAD (test mới);
- hợp đồng đã cấp quyền sửa test;
- dự án không có git, hoặc có git nhưng chưa có commit nào. Không có lỗi nào được báo.

Khi thấy cảnh báo, người soạn chọn một trong hai:

- thu hẹp `scope.owned` về đúng các tệp test mới, hoặc
- nếu việc này thật sự phải sửa test cũ, cấp quyền sửa test như mục dưới.

## Cấp quyền sửa test cũ: `edit_tests`

Hợp đồng nào thật sự phải sửa test có sẵn thì khai `authority` với cả `edit` và `edit_tests`:

```json
"authority": {"edit": true, "commands": true, "edit_tests": true, "self_decide": []}
```

- Phải có cả `"edit": true` và `"edit_tests": true`. Chỉ có `edit_tests` thì chưa tính là cấp.
- Đây là công tắc có sẵn của hợp đồng; không có trường mới.
- Khai `authority` cũng làm hợp đồng được xét theo luật "việc con nằm trong quyền" khi OneCrew tự quyết. Chủ duyệt hợp đồng là duyệt luôn quyền này.

## Hook chặn sửa test cũ: luật `existing_test`

Khi kế hoạch được xuất cho hook (lúc chủ duyệt, `owner enforce`, `hook export`), tệp `active-plan.json` ghi thêm `frozen_tests`: danh sách test có sẵn mà `scope.owned` trùm.

- Danh sách chụp từ HEAD lúc bản đã duyệt được xuất lần đầu. Các lần xuất lại cùng bản đó giữ nguyên danh sách, kể cả lần làm mới của hook Stop. Nhờ vậy, một test mới mà phiên viết rồi commit vẫn là test mới, phiên vẫn sửa được.
- Chủ duyệt một bản mới thì danh sách được chụp lại từ HEAD lúc đó.
- Hợp đồng đã cấp `edit_tests` thì danh sách rỗng.

Hook so tên tệp với danh sách, không gọi git ở mỗi lần ghi:

- Ở chế độ `enforce`: sửa một tệp trong danh sách (bằng công cụ sửa tệp, hay lệnh shell có đích ghi hook đọc được) bị từ chối với luật `existing_test`. Lời từ chối nói cách xử lý: viết test mới, hoặc xin chủ bản hợp đồng có `edit_tests`.
- Ở chế độ `log`: hook không chặn, chỉ ghi vi phạm `existing_test` vào `.onecrew/violations.jsonl`, như các luật khác.
- Test mới và các tệp khác trong `scope.owned` vẫn sửa được như cũ.
- Kế hoạch xuất bởi bản OneCrew trước thay đổi này không có `frozen_tests`; hook xét nó như trước, không chặn thêm gì.
- Bản chép trong dự án (`.onecrew/active-plan.json`) mà bỏ hay đổi `frozen_tests` so với bản trong sổ bị coi là bản bị sửa. Ở chế độ `enforce` mọi lệnh ghi bị chặn cho tới khi xuất lại.

## Giới hạn

- Hook chỉ chặn đường ghi nó đọc được: công cụ sửa tệp, và lệnh shell có đích ghi hook đọc được (như chuyển hướng `>` hay `>>` tới một đường dẫn rõ). Ghi bằng một chương trình mà hook không đọc được đích (như `python -c "open(...).write(...)"`, `sed -i`, `cat > ...` qua biến) vẫn lọt. Bộ kiểm M1 của từng hợp đồng vẫn đòi test cũ không đổi; đó là lớp kiểm thứ hai.
- OneCrew không kiểm theo `git diff` lúc báo xong cho các plan không khai `--workflow`. Plan khai `--workflow` đã có kiểm toàn vẹn test riêng.
- Danh sách là ảnh chụp: test có trong HEAD sau lần chụp, do người khác commit, chỉ được đóng băng khi chủ duyệt bản mới.
- `plan lint` chỉ cảnh báo; `plan propose` và `plan approve` không nhắc lại cảnh báo này. Người điều phối đọc cảnh báo trước khi đưa chủ duyệt.
