# Nhãn vai cho việc con của plan nội bộ

Mỗi việc con (task) của plan nội bộ có thể mang một **nhãn vai** ngắn như `backend`, `frontend` hay `lead`. Trang theo dõi hiện nhãn này dưới tên việc con, kèm chữ trạng thái ở góc phải. Nhãn chỉ để hiện: nó không đổi cách giao, chạy hay kiểm việc con.

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

1. **Lúc lập plan**: kết quả của lần sửa plan nội bộ (`internal_plan.revise`) có `role_area_report`.
2. **Trong `engine state`**: trường `role_area_report` ở cấp plan.
3. **Trên trang theo dõi**: dòng chữ đỏ dưới việc con bị báo, ví dụ "ghi ngoài vùng của @frontend: api/server.py".

Mỗi mục báo có dạng: `{"node": "FE", "role": "frontend", "kind": "outside_area", "paths": ["api/server.py"]}`. Trường `kind` là `outside_area` hoặc `role_not_in_table`.

Cách khai bảng: tham số `roles` của `internal_plan.revise(..., roles={...})`.

- Không truyền `roles`: plan giữ bảng của bản trước. Vì thế các lần sửa plan tự động (sửa lỗi, khôi phục), vốn chỉ truyền danh sách việc con, không làm mất bảng.
- `roles={}`: bỏ bảng.
- Lệnh `onecrew engine revise --file` chưa nhận khóa `roles` (tệp lệnh đó nằm ngoài hợp đồng NHANVAI). Hiện chỉ khai bảng được qua API Python.

## Chữ trạng thái trên trang theo dõi

Khối **Danh sách task** nằm trong chi tiết việc, ở mục "Agent và việc nền", ngay trên bảng Phần việc (bảng này giữ nguyên). Mỗi việc con một dòng, theo thứ tự khai trong plan:

- Bên trái: số thứ tự và tên việc con chữ đậm, dưới là `@vai` chữ đơn cách.
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
