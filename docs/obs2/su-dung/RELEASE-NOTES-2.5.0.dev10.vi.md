# OneCrew 2.5.0.dev10 — beta UI OBS-2 (prerelease), 05/11/2026

**Đây là bản prerelease (beta) của giao diện theo dõi OBS-2**, không phải bản ổn định 2.5 và không phải toàn bộ lộ trình 2.5. MR-R, 2.5-A/B, RD-A và CP-1 không có trong bản này. Chưa nghiệm thu. Codex đã review dev10 và không phát hiện blocker mới trong phạm vi bản vá.

| Mục | Giá trị |
|---|---|
| Tag | `v2.5.0.dev10` → snapshot sản phẩm `c4951f6ee1bc8ab41d055e0091246d95233fae28` |
| Version | `2.5.0.dev10` |
| Gói đã kiểm (nguyên vẹn) | `onecrew-2.5.0.dev10-obs2-c4951f6.zip`: thư mục gói với `manifest.json`, `SHA256SUMS` (18 file), `wheel/`, `verify/` |
| Wheel | `onecrew-2.5.0.dev10-py3-none-any.whl`, SHA256 `57445419e7c616f8e7c9f00039c7ac1b8ccc384c4cf464a27e3bc04b9d6879a1` (cùng file với wheel trong gói) |
| Hướng dẫn sử dụng | `onecrew-2.5.0.dev10-su-dung-<commit tài liệu>.zip`: tài liệu và script, để ngoài gói đóng băng; định danh là commit tài liệu ghi trong `NGUON.json` |
| Checksum | `SHA256SUMS-release.txt`: SHA256 của từng file phát hành |

## Bắt đầu

- Repo chưa dùng OneCrew: [Bắt đầu sử dụng](BAT-DAU-SU-DUNG.vi.md).
- Repo đang dùng OneCrew: [Chỉ mở UI mới, hoặc nâng runtime](REPO-DANG-DUNG-ONECREW.vi.md).

## Có gì

Giao diện web local, **chỉ đọc**, mở bằng `onecrew track open` hoặc script mở/dừng có ghim trong gói:

- Bảng thẻ công việc theo giai đoạn. Lọc và sắp xếp chỉ để xem. Trạng thái và "quyết định cần bạn" hiển thị riêng.
- Mở một thẻ để xem: phương án (solution) và thay đổi, đầu ra hiện hành, kết quả kiểm, vòng kiểm/sửa.
- Timeline: mỗi phần việc một dòng, có tên, trạng thái và thời lượng. Bấm để xem từng lượt và bằng chứng của bước đó ngay trong trang.
- Thẻ "Quyết định cần bạn" có mẫu lệnh PowerShell để sao chép. Mẫu lệnh **chỉ hiện khi hook của project khớp đúng runtime của trang và sổ này**. Nếu không khớp, trang nêu lý do và không đưa lệnh ghi. Sao chép không ghi quyết định: bạn tự chạy lệnh trong terminal của mình.

## Đã khép trong vòng này

- P3 (dev9): sau khi sao chép, focus ở lại đúng nút của đúng lựa chọn. Kết quả về muộn không kéo focus hay vị trí đọc về chỗ cũ.
- P2 (dev10): lần sao chép cũ trả lỗi muộn không còn sao chép dự phòng lệnh cũ. Điều này đúng cả khi đã có lần sao chép mới hơn, đã đổi task, đã mất binding hoặc kế hoạch đã sang bản mới. Lần sao chép hiện hành vẫn chạy như cũ.

## Vấn đề đã biết (không chặn beta)

- Khi clipboard còn chờ trình duyệt trả kết quả mà trang vẽ lại (do dữ liệu khác đổi), thẻ có thể tạm báo "Không sao chép được". Khi có kết quả, thông báo cập nhật đúng.

## Phạm vi và giới hạn

- UI chỉ đọc: không duyệt, không trả lời, không dừng hay tiếp tục task. Đóng trang hay dừng UI không dừng worker.
- Chỉ hiển thị công việc có dữ liệu trong sổ OneCrew. Không tự theo dõi mọi phiên Claude hay Codex nằm ngoài OneCrew.
- Server chỉ nghe `127.0.0.1` và không xác thực: dùng trên máy cá nhân.
- **Chưa kiểm trong lượt này:** clipboard native của trình duyệt (chỉ kiểm bằng clipboard giả có kiểm soát); pilot thật và sổ lớn; provider/model thật; lệnh của chủ chạy thành công từ terminal của chủ (chỉ kiểm việc từ chối các lệnh đó trong phiên AI).
- Không chạy lại gate 2.2 toàn bộ; tiêu chí phát hành không đổi.
- `README.vi.md` trong gói đóng băng được viết cho máy dựng gói. Nó còn ví dụ đường dẫn của máy đó, và các đường dẫn ấy không bắt buộc với máy khác. Dùng hướng dẫn sử dụng thay cho các ví dụ đó. Gói không chứa sổ, log hay key: lượt phát hành đã quét bí mật và file sổ trong cả gói, wheel và hướng dẫn.

## Kiểm đã chạy

**Người dựng gói tự chạy trên gói và wheel cuối** (snapshot `c4951f6`):
- verify gói 9/9; 142/142 file trong wheel trùng commit;
- trình duyệt OBS-2 150/150; binding tĩnh 56/56;
- binding đổi giữa phiên + focus + sao chép muộn 196/196;
- từ chối lệnh của chủ trong phiên AI 2/2; mở/dừng đúng phiên 4/4;
- R7-2 (trạng thái mốc) trùng bản trước; OBS-1 ux03 và stale_detail trùng bản trước, từng kiểm.

**Codex tự kiểm khi review dev10:**
- 18/18 checksum; 140 file Python khớp snapshot và bản cài;
- binding, focus và sao chép muộn 196/196;
- probe độc lập từng làm dev9 đỏ: 46/46.

**Kế thừa, không chạy lại** (mã chúng chạy trùng byte với bản đã kiểm):
- 6 module nguồn 66/66 và 13 kịch bản OBS-1 70/70 của dev9;
- nhóm OBS-2 103/103 và OBS-1 96/96 của dev8.

**Diễn tập hướng dẫn khi phát hành:** 42/42 kiểm đạt trong phòng lab, đường dẫn có khoảng trắng, sổ đăng ký thật không đổi. Các phần đã diễn tập:
- repo mới;
- repo đang chạy runtime 2.3.0.dev11: chỉ mở UI, qua bản sao sổ và xem sổ chỉ đọc;
- nâng runtime và quay về hook, trên repo lab.

Các bước cần chủ hoặc model thật chưa diễn tập. Chi tiết ở mục "Đã diễn tập" của [Repo đang dùng OneCrew](REPO-DANG-DUNG-ONECREW.vi.md).

Nguyên nhân, cách sửa và bằng chứng chi tiết: hồ sơ bàn giao `docs/obs2/HANDOVER.vi.md` trong repo (các mục dev8, dev9, dev10).

## Góp ý

Gửi kèm:
- `onecrew --version` và commit trong `manifest.json` của gói;
- kết quả `onecrew doctor`;
- các bước đã làm và ảnh màn hình trang.

Có thể tạo gói chẩn đoán đã lọc bí mật, chỉ lưu trên máy bạn: `onecrew support report --text "<mô tả>"`, rồi `onecrew support bundle <mã báo lỗi> --out <thư mục ngoài sổ>`. Đọc lại gói đó trước khi gửi.

**Không gửi:** sổ (`ledger.sqlite3` hay cả thư mục state root), key/token, file `.env`, cấu hình tài khoản.
