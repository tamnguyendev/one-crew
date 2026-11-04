# Timeline dev5 — đóng 3 P2 và 2 P3 của review dev4

Nguồn: review và yêu cầu người dùng ngày04/11/2026; baseline525c361. Phạm vi UI trên OBS-2A/B, tái sử dụng tracking/evidence, snapshot/restore và bộ dựng/kiểm wheel hiện có. Không đổi quyền, ledger, engine, runtime thật; không full gate, push/tag hoặc nghiệm thu.

| ID | Issue / expected output | Phản chứng |
|---|---|---|
| U5-1 | Poll không đóng disclosure nguồn/timestamp đang đọc, cùng task/lượt | API trial bật extends_to_now qua fetch test; mở disclosure rồi chờ poll thật; giữ open/focus |
| U5-2 | Lưới và nhãn cùng mốc chia thời gian | Khoảng không chia hết,21/111ms; đối chiếu tỷ lệ tick với mỗi hàng |
| U5-3 | Tab Tiến độ thấy ngay Gantt; chi tiết kỹ thuật thu gọn | Kiểm viewport1280x720/390x844 sau click, không test-scroll; bảng từng lượt folded |
| U5-4 | Toàn bộ lịch sử mở ngay lượt cũ; Về hiện hành nói đúng tác dụng | Chọn all có old rows; return thu gọn old rows, trở lại cửa sổ hiện hành |
| U5-5 | Chi tiết ưu tiên tên/kết quả/thời lượng/đầu ra; giữ toàn bộ provenance | Cùng artifact qua2event chỉ1output,2nguồn; current/old/inheritance không trộn; ms thống nhất |

Không xây lại hệ thống evidence. Gom artifact chỉ trong phần trình bày của node/lượt đã lọc phạm vi; giữ nguồn, vai trò, thế hệ và cửa mở chỉ đọc. ID/trạng thái kỹ thuật vẫn tra được trong disclosure.

Kiểm source trước wheel:49 unit,70 assertion mỗi cỡ màn, hồi quy OBS-1 Gantt/clock/evidence/slow25/switch theo phạm vi. Handover và coverage ghi snapshot/receipt cuối; tài liệu này không tự chứng nhận nghiệm thu.
