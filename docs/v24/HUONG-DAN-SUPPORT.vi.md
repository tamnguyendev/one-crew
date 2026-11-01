# Báo lỗi một lần với `onecrew support` (2.4-S1)

Bản `2.4.0.dev1` (alpha, chưa nghiệm thu). Mục tiêu: bạn báo lỗi **một lần**, nhận **một mã phản hồi** `FB-…`, và có một **hồ sơ chẩn đoán nằm trên máy bạn**. Bạn không phải tự đi tìm log, mã task hay phiên bản.

## 1. Báo lỗi

```
onecrew support report --text "Bước kiểm M1 báo sai dù file đúng" --expected "M1 đạt" --plan P1
```

- Lệnh in ra mã `FB-…`. Thêm `--json` để nhận kết quả dạng máy đọc.
- Các tùy chọn khác: `--task TASK-…`, `--attempt ATT-…`, `--image anh.png`, `--key K`.
- Gửi lại cùng `--key` thì không tạo bản ghi mới, mà trả về đúng mã cũ.
- Cùng `--key` nhưng nội dung khác thì lệnh từ chối.
- Không có task, hoặc root đã đóng, vẫn báo được. Báo cáo được ghi trên một task "support" riêng của project. Root đã đóng không bị ghi thêm gì.

**OneCrew tự gắn những gì đã chứng minh được:**
- plan → revision và trạng thái lúc báo;
- attempt → task con, root và node;
- node đang bị giữ hoặc hỏng, khi plan có đúng một node như vậy;
- phiên bản bản cài và sha256 của RECORD (không lấy được thì ghi `unknown`, kèm lý do);
- hash code đang chạy, đường dẫn interpreter, và đang chạy checkout hay bản cài.

`refs_source` ghi rõ từng mục là bạn khai (`user`) hay OneCrew suy ra (`derived:…`). Những gì không gắn được nằm trong `refs_unresolved`, ví dụ attempt của một project khác.

**Một báo cáo không phải là lỗi đã tái hiện.** Báo cáo không ghi kết quả kiểm, finding, receipt hay attempt nào. Trạng thái của nó là `reported`, cột tái hiện là `unknown`.

Các lỗi giống nhau chỉ được *gợi ý* là có thể trùng (`possible_duplicates`), không bao giờ bị gộp. Nếu khác phiên bản hoặc khác plan/node, OneCrew không gợi ý trùng.

## 2. Xem, phân loại, liên kết

- `onecrew support show FB-… [--json]`: báo cáo, phân loại, liên kết, hồ sơ và trạng thái.
- `onecrew support status FB-… [--json]`: các cột tách riêng, mỗi cột kèm bằng chứng: đã nhận, đã tái hiện, đang xử lý, có cách tránh, có bản thử, đã cài, đã kiểm tại đích, còn bị chặn, bạn đã xác nhận. Ở S1, các cột bản thử, đã cài và đã kiểm tại đích luôn là `false`; S2 sẽ ghi các cột này.
- `onecrew support classify FB-… --class task_result|environment|provider|onecrew_runtime|new_requirement|unclear --basis <bằng chứng>…`: lần phân loại sau thay lần trước, lịch sử vẫn được giữ.
- `onecrew support link FB-…` với một trong các dạng sau:
  - `--plan P [--project-id ID]`: nối với một plan.
  - `--finding RF1 [--plan P]`: chỉ nối được khi finding có receipt thật. Khi đó cột "đã tái hiện" thành `yes`.
  - `--request REQ-…`: nối với một câu hỏi.
- Lỗi thuộc runtime OneCrew (`onecrew_runtime`) chỉ được nối với plan của project OneCrew, có duyệt và ngân sách riêng. Nó không bao giờ được nối với plan, finding hay ngân sách của project đang báo lỗi.
- Chữ trong báo cáo hay trong log chỉ là dữ liệu. Không có đường code nào biến chữ đó thành quyền, pin hay câu trả lời.
- `onecrew support confirm FB-… --reference "…"` là tín hiệu riêng của chủ dự án: "với tôi, lỗi đã hết". Lệnh bị từ chối khi chạy trong phiên AI. Xác nhận này không có nghĩa là OneCrew đã kiểm tại đích.

Thông báo (`notifications pull`, cửa sổ desktop) chỉ phát khi trạng thái thật sự đổi: phân loại mới, đang xử lý, đã tái hiện, đã xác nhận. Việc nhận lại thông báo, khởi động lại, ACK hay đóng cửa sổ không trả lời câu hỏi nào, không nghiệm thu gì, và không làm mất thông báo mới hơn.

## 3. Hồ sơ chẩn đoán

```
onecrew support bundle FB-… --out D:\chia-se
```

Hồ sơ chỉ lấy những nguồn suy ra từ refs của báo cáo:
- probe runtime;
- tối đa 200 sự kiện mới nhất của root và các task con, cùng các dòng attempts/requests của chúng;
- phần cuối, tối đa 256 KB, của `attempts/<id>/stdout|stderr.txt`;
- các receipt mà những sự kiện đó nhắc tới;
- 200 dòng cuối của `.onecrew/violations.jsonl` thuộc plan;
- kết quả `doctor`, trừ bước gọi Claude CLI.

`manifest.json` ghi từng nguồn với trạng thái `included`, `missing`, `truncated`, `withheld`, `unreadable`, `not_applicable` hoặc `unknown`, kèm số byte và sha256 của bản gốc. Log của runner/host v1 có trạng thái `not_applicable`, vì thành phần đó không có trong bản cài.

Từng dòng được lọc bằng mẫu (`display_core.safe`): dòng có dạng bí mật bị thay, URL có mật khẩu bị che, các dòng khác giữ nguyên. **Bộ lọc theo mẫu không phải là bảo đảm**, nên hãy đọc file trước khi gửi cho ai.

Ảnh không bao giờ được chép vào hồ sơ; chỉ có sha256 của ảnh. Thư mục `--out` không được nằm trong state root, không được là link, và không được chứa `..`. Hồ sơ lớn hơn 8 MB thì nguồn cũ nhất bị bỏ và được đánh dấu `truncated`.

OneCrew không đọc toàn bộ source, sổ, biến môi trường hay hội thoại. Hồ sơ không chạy chương trình nào, không gọi model và không gửi gì lên mạng.

## 4. Khi runtime hoặc sổ bị hỏng

Nếu sổ `ledger.sqlite3` không đọc được, hoặc `onecrew` không import được module của chính nó, báo cáo được ghi vào spool. Lệnh in `spooled: true` và đường dẫn thật của file. OneCrew thử các chỗ theo thứ tự:
1. `<state-root>\support-spool\`
2. `<project>\.onecrew\support-spool\`
3. `%TEMP%\onecrew-support-spool\`

Nếu không chỗ nào ghi được, lệnh trả mã khác 0, in **NOT recorded** và liệt kê mọi chỗ đã thử cùng lỗi của từng chỗ (ví dụ đĩa đầy).

Khi chính file `onecrew.exe` hỏng, chạy:

```
python -I -m onecrew.v2.support_spool --project <project> report --text "…"
```

Sửa xong sổ thì chạy `onecrew support import-spool`. Mỗi file spool được nhập đúng một lần, với chính mã `FB-…` đã in lúc báo, rồi được chuyển vào `imported\`. Spool chỉ là chỗ ghi dự phòng, không phải nơi giữ trạng thái thứ hai.

## 5. S1 chưa làm

- Không tải hồ sơ lên đâu cả và không tự gửi log ra ngoài.
- Không cài hay đổi bản OneCrew (hotfix), không chuyển venv, không tiếp tục root; phần này thuộc 2.4-S2.
- Không đổi pin, quyền hay ngân sách, và không gia hạn root cũ.
- Không tự mở plan sửa lỗi. Việc sửa vẫn đi qua plan có duyệt của project tương ứng.
