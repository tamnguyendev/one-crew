# Trang gộp: một trang theo dõi xem mọi sổ trên máy

Trang gộp là trang theo dõi sẵn có, xem thêm các sổ khác của máy. Mọi sổ mở **chỉ đọc**; trang không duyệt, không đóng, không ghi gì vào sổ nào và vào tệp nào.

## Mở trang

```powershell
onecrew --project <repo> --state-root <sổ chính> track open --so <sổ thứ hai> --so <sổ thứ ba>
```

`--so <thư mục sổ>` dùng được cho `track serve` và `track open`, lặp được. Thư mục phải có sổ, không có thì lệnh báo lỗi và không mở trang. `track open` chỉ dùng lại server đang chạy khi server đó có đúng các sổ `--so` này.

Muốn không phải gõ lại, ghi vào `tracking.json` trong thư mục của sổ chính:

```json
{
  "port": 9692,
  "so": ["D:\\thu-muc\\so-phat-trien", {"path": "D:\\thu-muc\\so-dieu-phoi", "ten": "điều phối"}],
  "de_xuat_tu": "D:\\thu-muc\\ROADMAP.vi.md",
  "phien_claude_thu_muc": ["C:\\Users\\ten\\.claude\\projects\\<thư mục dự án>"]
}
```

| Khóa trong tracking.json | Nghĩa |
|---|---|
| `port` | cổng cố định (không bắt buộc) |
| `so` | các sổ xem thêm; mỗi mục là đường dẫn, hoặc `{"path", "ten"}` để đặt nhãn |
| `de_xuat_tu` | tệp markdown của bạn; các gạch đầu dòng hiện ở "Đề xuất chờ bạn" |
| `phien_claude_thu_muc` | các thư mục nhật ký phiên Claude được phép đọc; không liệt kê thì không đọc |

Tệp được đọc lại mỗi lần tải trang. Không có `--so` và không có ba khóa `so`, `de_xuat_tu`, `phien_claude_thu_muc` thì trang giữ nguyên như trước.

## Trang có gì

**Nút lọc sổ** trên cùng: Tất cả, hoặc từng sổ. Nhãn sổ lấy từ tên thư mục (thư mục tên `state` thì lấy tên thư mục cha).

**Công việc** (`#viec`): một danh sách gồm việc của mọi sổ, mỗi dòng ghi sổ của nó. Bấm một việc mở đúng việc ở đúng sổ. Việc dưới khóa `plan:` của bản OneCrew cũ ghi **kiểu cũ**. Danh sách gộp tải một lần toàn bộ (không có "Xem thêm") và không so kết quả kiểm với bản hiện tại của dự án; mở một việc thì việc đó được so như trước.

**Phiên Claude** (`#phien`):

- **Dải Việc**: các việc chưa nghiệm thu và chưa đóng của các sổ đang xem. Việc kiểu cũ không nằm ở dải này (lệnh đóng việc không đóng được chúng); chúng vẫn ở tab Công việc.
- **Thẻ lưới phiên**: mỗi phiên đã quan sát, tên, trạng thái (đang làm: bước cuối dưới 2 phút; rảnh: dưới 1 giờ; còn lại đã kết thúc), bước cuối, số bước.
- **Claude đã làm gì**: làn và dải số của phiên quan sát gần nhất. Token và chi phí ở trang riêng của phiên (bấm "mở làn, số, token"), vì nhật ký chỉ được mở cho phiên bạn chọn.
- **Luồng giao việc**: các lần giao việc và nhắn tin, mới nhất trước, chia theo ngày. "việc (đoán)" là tên việc tìm thấy trong dòng tóm tắt hay ba dòng đầu của tin; đó là đoán, không phải sổ ghi.
- **Bước agent tự báo**: các dòng `BƯỚC:`.
- **Đề xuất chờ bạn**: gạch đầu dòng của tệp `de_xuat_tu`.

## Dòng BƯỚC

Agent viết một dòng riêng bắt đầu bằng `BƯỚC: <định làm gì>` trước mỗi bước lớn. Trang đọc dòng đó trong chữ của phiên chính và agent con, **chỉ** ở các thư mục trong `phien_claude_thu_muc`, và hiện cạnh lệnh ngay sau nó, nhãn **agent tự báo, chưa xác thực**. Dòng này chỉ để xem: không tính đạt, xong hay tiến độ. Worker của engine không áp luật này (sản phẩm của họ phải nguyên văn).

## Che dữ liệu

Mọi chữ lấy từ nhật ký, từ sổ và từ tệp đề xuất được che trước khi hiện: khóa, mật khẩu, token, thư điện tử và đường dẫn. Lời bạn gõ, kết quả công cụ và chữ thường của agent không được đưa lên trang. Việc che dựa theo mẫu, không bảo đảm tuyệt đối: chỉ liệt kê thư mục dự án bạn chấp nhận hiện trên màn hình.

Trang gộp chỉ mở cho trình duyệt trên chính máy này. Nhật ký chỉ đọc các tệp sửa trong 14 ngày, tối đa 60 tệp mới nhất.

## Quay lại

Xóa ba khóa `so`, `de_xuat_tu`, `phien_claude_thu_muc` khỏi `tracking.json` (hoặc xóa tệp nếu tệp chỉ có chúng) và mở lại không có `--so`.
