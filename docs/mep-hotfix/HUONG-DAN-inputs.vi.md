# Verifier khai `inputs`: hotfix cho repo lớn

Bản `2.5.0.dev10+sol6.4.mep1`, bản thử cách ly. Chưa phát hành, chưa nghiệm thu.

## Vấn đề

Với verifier lệnh, `verdict run` băm toàn bộ cây làm việc, ghi object vào `.git` của project, chép toàn cây ra thư mục tạm, rồi băm lại. Repo nhiều dữ liệu chưa commit tốn thời gian và đĩa, dù lệnh chỉ đọc vài file.

## Cách dùng

Trong hợp đồng, khai đúng những gì lệnh đọc:

```json
{"type": "command", "config": {"argv": ["python", "tool/check.py"], "max_minutes": 15, "inputs": ["tool", "spec/a.txt"]}}
```

- `inputs`: file hoặc thư mục, đường dẫn tương đối từ gốc repo, không wildcard, tối đa 200.
- **Không khai `inputs` thì giữ nguyên đường cũ:** toàn cây, hợp đồng và receipt như trước.
- Thêm `inputs` vào plan đang có là sửa hợp đồng: `plan amend`, rồi chủ duyệt lại.
- `owned` là phạm vi được sửa, không phải input. Lệnh đọc gì thì phải khai cái đó, kể cả cấu hình và dữ liệu.

## Thay đổi khi có `inputs`

| | Đường cũ | Có `inputs` |
|---|---|---|
| Chụp trước và sau | Toàn cây | Chỉ input và các `.gitattributes` phía trên chúng |
| Object ghi vào `.git` | Toàn bộ dữ liệu chưa commit | Chỉ input |
| Checkout | Toàn cây | Chỉ input |
| Bằng chứng còn hiệu lực | Khi cả cây không đổi | Khi input, `.gitattributes` phía trên và file chương trình không đổi |
| Duyệt (khi mọi mốc đều khai) | Duyệt toàn cây, ghi object | Không duyệt toàn cây (vẫn băm file đang theo dõi) |

Receipt có thêm `input_scope`: đường dẫn, số file, số byte, HEAD, và hash chương trình mà lệnh khởi động. Chỉ runtime bản này đọc được plan có `inputs`.

## Khi nào bị từ chối, verifier chưa chạy, chạy lại được ngay

- Input không có, hoặc toàn bộ bị Git ignore.
- Lệnh nêu một đường dẫn có thật trong repo mà không thuộc `inputs`, kể cả `.`.
- Lệnh nêu đường dẫn tuyệt đối vào cây thật.
- Hard link hoặc junction trong input.
- Thư mục làm việc không nằm trong input.
- Root workflow (engine): chưa hỗ trợ `inputs`, vì handoff và test integrity xét toàn artifact.
- Không đủ đĩa cho checkout. Kiểm này áp dụng cho cả đường cũ.

## Giới hạn phải biết

- **Khai thiếu là trách nhiệm của người viết hợp đồng.** Lệnh đọc file không khai qua đường tương đối sẽ không thấy file, nên thường báo lỗi. Script tự ghép đường dẫn tuyệt đối vào cây thật thì OneCrew không chặn được, vì verifier không chạy trong sandbox hệ điều hành; đường cũ cũng vậy. Kiểm dòng lệnh chỉ thấy những gì dòng lệnh nêu.
- **Lệnh ghi ra ngoài input trên cây thật:** đường cũ phát hiện qua chụp sau, đường `inputs` thì không. Chỉ dùng `inputs` cho lệnh chỉ đọc hoặc chỉ ghi trong thư mục làm việc của nó.
- **Chương trình:** chỉ băm đúng file được khởi động, không băm thư viện nó nạp. Thứ gì trong repo thì khai vào `inputs`.
- **Dữ liệu ngoài input đổi không làm bằng chứng cũ hết hiệu lực,** đó chính là mục đích. Chỉ dùng khi chắc lệnh không phụ thuộc phần đó.
- **Nghiệm thu:** `--artifact-sha` nhận một cây hoặc commit chứa đúng các input đã kiểm, không cần chụp toàn cây. `verdict artifact` vẫn chụp toàn cây và ghi object; trên repo lớn hãy truyền commit thay vì gọi lệnh này.
- **Plan trộn** mốc có và không có `inputs`: mốc không khai vẫn chụp toàn cây, và lúc xem trạng thái vẫn phải đi cả cây.
- **Tiến trình bị giết cứng:** thư mục tạm có dấu chủ được dọn ở lần `verdict run` sau; tiến trình con của verifier có thể còn chạy nếu tiến trình cha chết đột ngột. Thư mục tạm của bản cũ không có dấu, không được dọn tự động.

## Thử cách ly

1. Cài wheel vào venv riêng. Không đổi hook hay runtime của repo thật.
2. Tạo bản sao nhỏ chứa đúng các input, hoặc repo tổng hợp; không chạy trên repo thật ở lượt đầu.
3. Theo dõi `.git`, thư mục tạm, và `snapshot` trong receipt.
