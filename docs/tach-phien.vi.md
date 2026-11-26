# Nhắc tách phiên

Phiên càng dài thì ngữ cảnh càng lớn. Bộ nhớ đệm của mô hình chỉ giữ được một lúc; quay lại sau khi nghỉ quá hạn thì cả ngữ cảnh phải ghi lại từ đầu, tốn hơn nhiều. `hook prompt` nhắc bạn đúng lúc để mở phiên mới. Nó **chỉ nhắc, không bao giờ chặn**.

## Khi nào có lời nhắc

Đủ cả ba điều:

- bạn gõ thẳng vào phiên (tin của phiên khác và thông báo của app không được nhắc);
- phiên đang theo một plan đã duyệt hoặc đã dừng chờ bạn;
- đọc được nhật ký phiên của Claude Code (`transcript_path` mà Claude Code đưa cho hook).

Hook này do `onecrew init` cài vào dự án (mục `hook prompt`). Hook toàn máy (`hook user install`) chỉ xét lệnh và sửa tệp, không có lời nhắc này.

## Ba loại lời nhắc

| Loại | Khi nào | Nói gì |
|---|---|---|
| `idle` | ngữ cảnh lớn **và** lượt cuối của AI cũ hơn hạn bộ nhớ đệm | lượt kế sẽ ghi lại toàn bộ ngữ cảnh; nên mở phiên mới |
| `big` | ngữ cảnh lớn | nên mở phiên mới |
| `boundary` | plan đã duyệt vừa được duyệt, một mốc vừa đạt, hoặc đủ mốc chờ nghiệm thu, và ngữ cảnh quá sàn | chỗ hợp để mở phiên mới |

Mỗi lượt nhiều nhất một lời nhắc, theo thứ tự `idle`, `big`, `boundary`. Mỗi chỗ chuyển giai đoạn chỉ nhắc một lần. Mỗi phiên nhiều nhất 3 lời nhắc. Mỗi lời nhắc ghi một dòng `reminded` (rule `split_session:<loại>`) trong `.onecrew/violations.jsonl`, không ghi chữ bạn gõ.

Lời nhắc đi vào ngữ cảnh cho AI và nhờ AI báo bạn một dòng ngắn; AI có thể không làm theo.

## Mang việc sang phiên mới

Lời nhắc kèm lệnh có sẵn:

```
onecrew continue <plan>
```

Lệnh chỉ đọc: nó in gói tiếp tục của plan từ sổ. Thêm `--project` và `--state-root` nếu phiên mới không tự tìm ra. Mở phiên mới, dán gói đó (hoặc bảo AI chạy lệnh), rồi làm tiếp. OneCrew không tự mở, đóng hay đổi phiên.

## "Ngữ cảnh lớn" đo thế nào

Lấy lượt cuối của AI trong nhật ký phiên: tổng token đọc vào, ghi bộ nhớ đệm và đọc bộ nhớ đệm. Chỉ đọc 512 KB cuối của tệp. Không đọc được, không thấy lượt nào trong đoạn đó, hoặc phiên vừa nén (compact) sau lượt đó thì im lặng.

## Chỉnh ngưỡng hoặc tắt

Tạo tệp `<sổ>\plans\tach-phien.json`:

```json
{"tokens": 200000, "ttl_seconds": 3600, "boundary_tokens": 60000, "max_reminders": 3, "off": false}
```

| Khóa | Nghĩa | Mặc định |
|---|---|---|
| `tokens` | ngữ cảnh từ mức này là lớn | 200000 |
| `ttl_seconds` | hạn bộ nhớ đệm, tính bằng giây | 3600 |
| `boundary_tokens` | sàn để gợi ý lúc chuyển giai đoạn | 60000 |
| `max_reminders` | số lời nhắc nhiều nhất mỗi phiên | 3 |
| `off` | `true` là tắt hẳn | false |

Khóa nào thiếu hay không phải số nguyên từ 0 trở lên thì dùng mặc định; tệp hỏng thì dùng mặc định cả. Tắt: `{"off": true}`.

## Giới hạn

- Claude Code đổi định dạng nhật ký phiên thì lời nhắc im lặng cho tới khi sửa.
- Hạn 1 giờ là ước từ một ca thực địa; thực tế khác thì đổi `ttl_seconds`.
- Chỉ nhắc khi bạn gõ; phiên chạy nền không có chữ bạn gõ thì không bao giờ được nhắc.
- Bộ đếm lời nhắc nằm trong `.onecrew/hook-state.json`, tệp này giữ 20 phiên gần nhất.
