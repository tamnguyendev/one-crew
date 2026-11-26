# Nhãn vai cho việc con của plan nội bộ

Mỗi việc con (task) của plan nội bộ có thể mang một **nhãn vai** ngắn như `backend`, `frontend` hay `lead`. Trang theo dõi hiện nhãn này dưới tên việc con, kèm chữ trạng thái ở góc phải. Nhãn chỉ để hiện: nó không đổi cách giao, chạy hay kiểm việc con.

Việc con cũng có thể mang một **tên ngắn** cho người (trường `"title"`), và khối Danh sách task có một **dòng tóm tắt** ở đầu. Xem các mục dưới.

## Khai nhãn vai cho một việc con

Thêm trường `"role"` vào việc con trong tệp plan nội bộ:

```json
{"id": "BE1", "goal": "BE viết hợp đồng API", "role": "backend", "...": "các trường khác giữ như cũ"}
```

- `"role"` không bắt buộc. Việc con không khai thì trang hiện như cũ: không có dòng @vai.
- Dạng hợp lệ: chữ thường a-z, số 0-9 và dấu `-`. Dài 1 đến 24 ký tự, không bắt đầu bằng `-`.
  - Ví dụ đúng: `backend`, `frontend`, `lead`, `qa-2`.
  - Ví dụ sai: `Backend`, `back end`, `bé`, `a_b`, `-x`. Nhãn sai thì plan bị từ chối và lỗi nói rõ nhãn nào sai.
- `"role"` ở việc con khác hẳn `executor.role`. `executor.role` vẫn chỉ nhận `worker` như trước.
- Đổi, thêm hay bỏ nhãn giữa hai bản plan không tính là đổi việc con. Thế hệ giữ nguyên, kết quả đã kiểm giữ nguyên, việc con không chạy lại.
  - Đổi mục tiêu, phạm vi tệp hay phụ thuộc thì vẫn tính là đổi, như trước.

## Tên ngắn cho người: trường "title"

`"goal"` của việc con là câu giao việc cho AI, thường dài vài trăm ký tự. Trang theo dõi cần một tên đọc được ngay. Vì thế việc con có thể khai thêm `"title"`: tên ngắn cho người.

```json
{"id": "K02", "goal": "Cụm 2 review vn-sign-sdk @bef6476 (node độc lập): đọc các tệp ...", "title": "Rà Signature.Domain (26 tệp)", "role": "review", "...": "các trường khác"}
```

- `"title"` không bắt buộc. Đó là một dòng, dài 1 đến 80 ký tự, không để trống hay chỉ có dấu cách.
- Có xuống dòng, dài hơn 80 ký tự hay để trống thì plan bị từ chối, và lỗi nêu `title` của việc con nào.
- Giống nhãn vai, `"title"` chỉ để hiện:
  - nó không đổi cách giao, chạy hay kiểm việc con;
  - `"goal"` vẫn là câu giao việc cho AI;
  - đổi, thêm hay bỏ `"title"` giữa hai bản plan không tính là đổi việc con: thế hệ giữ nguyên, kết quả đã kiểm giữ nguyên, việc con không chạy lại.
- Plan cũ không có `"title"` vẫn chạy y như trước.

### Tên ngắn khi không có "title" (việc cũ)

Việc cũ trong sổ không có `"title"`. Trang đặt tên ngắn cho chúng theo thứ tự sau:

1. **Phần đầu câu giao việc**: câu giao việc đến dấu `": "` hay `". "` đầu tiên. Một dấu `:` hay `.` không có dấu cách sau, như "3.5:1", không cắt câu. Phần đầu được dùng làm tên nếu nó ngắn và không phải chữ máy.
2. **Tên lấy từ phần việc**, khi phần đầu là chữ máy. Chữ máy là phần đầu:
   - có mã commit (7 đến 40 ký tự hex, có ít nhất một chữ số), hoặc
   - có dấu `@`, hoặc
   - dài hơn 40 ký tự.

   Tên có dạng **`<thư mục> — <N> tệp → <tệp ghi>`**:
   - **thư mục**: thư mục chung của các tệp riêng việc con đó đọc, lấy tên cuối. Không có thư mục chung thì là "gốc repo".
   - **tệp riêng**: tệp mà dưới nửa số việc con của cùng plan đọc. Tệp mà nhiều việc con cùng đọc (như tài liệu chung) không được đếm, nên không kéo thư mục chung về gốc.
   - **N**: số tệp riêng.
   - **tệp ghi**: tên tệp đầu tiên việc con ghi.
   - Phần nào không có thì bỏ. Không có tệp riêng thì thư mục lấy theo tệp ghi.
3. Việc con không đọc tệp riêng nào và không ghi gì thì trang dùng lại phần đầu câu giao việc.

Mọi tên dài hơn 70 ký tự đều bị cắt và thêm `…`.

Ví dụ: việc con K02 có câu giao việc "Cụm 2 review vn-sign-sdk @bef6476 (node độc lập): đọc 26 tệp …". Nó đọc 26 tệp chỉ mình nó đọc trong `src/Signature.Domain/`, cùng một tài liệu cả 35 việc con đều đọc, và ghi `reviews/K02.md`. Phần đầu câu có `@` nên là chữ máy. Tên ngắn là "Signature.Domain — 26 tệp → K02.md".

Tên lấy từ phần việc chỉ nói việc con đụng tới đâu, không nói nó làm gì. Vì thế tốt nhất vẫn là khai `"title"`.

### Đặt tên nói nội dung

Dặn người và AI lập plan: mỗi việc con nên có `"title"` viết cho người đọc, nói nội dung việc đó làm, không chỉ số thứ tự hay mã, và không chép lại câu giao việc. Ví dụ:

- "Rà Signature.Domain (26 tệp)"
- "Tổng hợp 34 phần → mục lục báo cáo"
- "BE viết hợp đồng API"
- "Kiểm tích hợp, ghi quyết định"

Tránh:

- tên chỉ có số thứ tự hay mã, như "K02", "Phần 2/34" hay "Cụm 2 @bef6476";
- câu dài hơn một dòng.

## Bảng vai và vùng tệp (tùy chọn)

Plan nội bộ có thể khai một bảng vai: mỗi vai ứng với vùng tệp của nó. Bảng là danh sách mẫu đường dẫn, so theo luật của hook ghi: đúng tệp, thư mục cha, hoặc glob, không phân biệt hoa thường.

```json
{"backend": ["api/"], "frontend": ["ui/**"], "lead": ["docs/integration.md"]}
```

Bảng chỉ để báo, không chặn. Plan vẫn được ghi và chạy y như không có bảng. Có hai trường hợp bị báo:

- **ghi ngoài vùng**: việc con có `write` nằm ngoài vùng của vai mình.
- **vai không có trong bảng**: việc con khai một nhãn mà bảng không có.

Việc con không khai nhãn thì không bị so với bảng.

Báo ở ba chỗ, cùng một nội dung (`role_area_report`):

1. **Lúc lập plan**: kết quả của lần sửa plan nội bộ (lệnh `engine revise` hay `internal_plan.revise`) có `role_area_report`.
2. **Trong `engine state`**: trường `role_area_report` ở cấp plan.
3. **Trên trang theo dõi**: dòng chữ đỏ dưới việc con bị báo, ví dụ "ghi ngoài vùng của @frontend: api/server.py".

Mỗi mục báo có dạng: `{"node": "FE", "role": "frontend", "kind": "outside_area", "paths": ["api/server.py"]}`. Trường `kind` là `outside_area` hoặc `role_not_in_table`.

Có hai cách khai bảng:

- Bằng lệnh: thêm khóa `"roles"` vào tệp của `onecrew engine revise <plan> --file <tệp>`, cạnh `nodes`, `reason`, `evidence`:

  ```json
  {"nodes": [...], "reason": "...", "evidence": ["..."], "roles": {"backend": ["api/"], "frontend": ["ui/**"]}}
  ```

- Bằng API Python: tham số `roles` của `internal_plan.revise(..., roles={...})`.

Quy tắc giữ hay bỏ bảng:

- Không có `roles`: plan giữ bảng của bản trước. Vì thế các lần sửa plan tự động (sửa lỗi, khôi phục), vốn chỉ đưa danh sách việc con, không làm mất bảng.
- `"roles": {}`: bỏ bảng.

## Chữ trạng thái trên trang theo dõi

Khối **Danh sách task** nằm trong chi tiết việc, ở mục "Agent và việc nền", ngay trên bảng Phần việc (bảng này giữ nguyên).

Đầu khối là **dòng tóm tắt**. Dòng này chỉ lấy từ số liệu của sổ, không do AI viết, nên không thể nói khác sổ. Nó gồm, theo thứ tự:

1. tên ngắn của việc;
2. số việc con đã xong và đạt cổng trên tổng số, ví dụ "2/4 phần xong, cổng đạt";
3. số việc con đang làm;
4. số việc con bị giữ;
5. số việc con của mỗi vai, vai nhiều nhất trước, ví dụ "34 @review, 1 @lead". Phần này không có khi không việc con nào khai nhãn.

Ví dụ: "**Rà mã vn-sign-sdk** · 12/35 phần xong, cổng đạt · 3 đang làm · 0 bị giữ · 34 @review, 1 @lead".

Dưới dòng tóm tắt, mỗi việc con một dòng, theo thứ tự khai trong plan:

- Bên trái: số thứ tự và tên ngắn của việc con, chữ đậm, dưới là `@vai` chữ đơn cách.
  - Tên ngắn là `"title"` nếu có, không thì rút từ câu giao việc (xem mục trên).
  - Bấm vào dòng thì mở ra cả câu giao việc (`"goal"`). Bấm lần nữa thì gập lại. Trang tự làm mới vẫn giữ dòng đang mở.
- Góc phải: chữ trạng thái, lấy từ chính sổ:

| Chữ | Màu | Khi nào |
|---|---|---|
| xong · cổng đạt | xanh | việc con đã kiểm đạt hoặc đã nghiệm thu |
| đang làm | cam | việc con đang chạy |
| chờ task 2, 3 | xám | việc con chưa chạy và còn chờ các việc con số 2 và 3 (theo `depends` chưa đạt, đúng thứ tự khai) |
| chưa bắt đầu | xám | việc con chưa chạy và không còn chờ ai |
| chờ kiểm cổng | xám | việc con đã có đầu ra, chưa kiểm |
| kiểm chưa đạt | đỏ | lần kiểm gần nhất không đạt |
| bị giữ | đỏ | engine đang giữ việc con |

"Chờ task" tính theo mức mà `depends` đòi hỏi. Ví dụ việc con 4 cần việc con 2 **đã nghiệm thu** (`"requires": "accepted"`). Khi việc con 2 mới kiểm đạt, nó đã hiện "xong · cổng đạt", nhưng việc con 4 vẫn hiện "chờ task 2".

Dữ liệu tương ứng: `engine state` và chi tiết việc của trang theo dõi có thêm, ở mỗi việc con:

- `role`: nhãn vai, hoặc null.
- `waits_for`: mã các việc con còn phải chờ, đúng thứ tự khai.

Chi tiết việc của trang theo dõi có thêm `role_area`: mục báo vùng tệp của việc con đó, hoặc null.

Chi tiết việc cũng có, ở cấp việc:

- `node_titles`: tên ngắn của mỗi việc con: `"title"`, hoặc tên trang đặt cho việc cũ theo luật ở mục trên. Bảng Phần việc cũng gọi việc con bằng đúng tên này.
  - Tên dài xuống dòng, không tràn trang.
  - Bấm vào tên trong bảng (hay rê chuột lên tên) thì thấy cả câu giao việc, kèm mã việc con.
  - Các chỗ khác của chi tiết việc nêu tên việc con (chờ, dòng thời gian) cũng dùng tên ngắn này, kèm mã.
- `node_goals`: cả câu giao việc của mỗi việc con.

## Ví dụ: bốn việc con như ảnh của chủ (25/11)

```json
[
  {"id": "BE1", "goal": "BE viết hợp đồng API", "role": "backend", "write": ["api/contract.md"], "depends": []},
  {"id": "BE2", "goal": "BE làm API", "role": "backend", "write": ["api/server.py"],
   "depends": [{"node": "BE1", "requires": "verified"}]},
  {"id": "FE", "goal": "FE làm giao diện", "role": "frontend", "write": ["ui/app.js"],
   "depends": [{"node": "BE1", "requires": "verified"}]},
  {"id": "LEAD", "goal": "Lead kiểm tích hợp, ghi quyết định", "role": "lead", "write": ["docs/integration.md"], "integration": true,
   "depends": [{"node": "BE1", "requires": "verified"}, {"node": "BE2", "requires": "accepted"}, {"node": "FE", "requires": "verified"}]}
]
```

Ví dụ chỉ ghi các trường liên quan. Plan thật cần đủ các trường bắt buộc của việc con: input, output, acceptance, read, resources, estimate_seconds, execution_cap_seconds, budget_calls, checks, integration.

Giả sử BE1 và BE2 đã kiểm đạt, FE đang chạy, LEAD chưa chạy. Trang hiện:

```
DANH SÁCH TASK
NHANVAI thử · 2/4 phần xong, cổng đạt · 1 đang làm · 0 bị giữ · 2 @backend, 1 @frontend, 1 @lead
1. BE viết hợp đồng API                 xong · cổng đạt
   @backend
2. BE làm API                           xong · cổng đạt
   @backend
3. FE làm giao diện                            đang làm
   @frontend
4. Lead kiểm tích hợp, ghi quyết định     chờ task 2, 3
   @lead
```

LEAD chờ task 2 vì nó đòi BE2 đã nghiệm thu, không chỉ đã kiểm. Nó chờ task 3 vì FE chưa kiểm đạt.

Script thử của chủ, `scripts/owner/thu-nhanvai.ps1`, dựng đúng sổ thử này rồi mở trang theo dõi.

## Giới hạn

- **Vai chỉ là nhãn.** Vai không đổi quyền, không đổi mô hình hay cách giao, chạy, kiểm việc con. Việc con được ghi tệp nào vẫn do trường `write` của nó quyết định. `executor.role` vẫn chỉ là `worker`.
- **Bảng vai chỉ báo, không chặn.** Việc con ghi ra ngoài vùng của vai mình vẫn được ghi vào plan và vẫn chạy. Người đọc phải tự xem báo cáo `role_area_report` hay dòng chữ đỏ trên trang.
- **Việc con không khai nhãn không bị so với bảng.** Bảng vai không bắt mọi việc con phải có nhãn.
- **Vùng tệp so theo tên đường dẫn**, cùng luật với hook ghi: đúng tệp, thư mục cha, hoặc glob, không phân biệt hoa thường. Nó không theo liên kết hay tên ngắn trên đĩa.
- **Khối Danh sách task nằm trong chi tiết việc**, ở mục "Agent và việc nền", không nằm ở màn hình đầu. Khối chỉ có khi trang đã đọc đủ chi tiết của việc.
- **Plan digest và trang Phiên Claude không hiện nhãn vai hay tên ngắn.** Chỉ engine state và trang theo dõi có nhãn; tên ngắn chỉ có trên trang theo dõi.
- **Tên trang tự đặt cho việc cũ chỉ là phần đầu câu giao việc hay chỗ việc con đụng tới** (thư mục, số tệp, tệp ghi). Nó không nói việc con làm gì.
  - Plan đã có trong sổ không được ghi thêm `"title"`. Muốn tên nói nội dung thì khai `"title"` ở lần sửa plan kế tiếp.
- **Dòng tóm tắt chỉ đếm.** Nó không nói việc con nào chậm hay vì sao; xem từng dòng và các mục chờ của trang.
- **"Chờ task" chỉ tính theo `depends` trong plan.** Việc con chờ người hay chờ tài nguyên dùng chung không hiện ở đây; những thứ đó nằm ở mục chờ và tài nguyên của trang theo dõi.
- **Chữ trạng thái lấy từ sổ lúc trang đọc**, không phải dự đoán: "đang làm" nghĩa là sổ ghi việc con đã bắt đầu và chưa có đầu ra.
