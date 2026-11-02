# Giới hạn của lát OBS-1 (gói thử)

- **Worker giả.** Mọi kiểm (unit, cài wheel, kiểm từ gói) dùng `claude` giả (`tests/v24_fake_claude.py`): chứng minh đường đi root → node → attempt → sổ → màn hình, không chứng minh model thật làm việc hữu ích. Chưa chạy provider thật (tổ chức tắt subscription cho worker native; API chỉ cho advisor/reviewer).
- **Chỉ theo dõi những gì có trong sổ.** Root `sequential-engine` có node/thế hệ/attempt/quan sát tiến độ; root không engine chỉ có mốc và verdict; task ngoài plan (v1) chỉ có phase checkpoint. Phiên Claude/Codex không chạy qua OneCrew ghi "chưa được theo dõi" — màn hình không suy, không bịa.
- **Liveness là quan sát, không phải kết luận.** Không có quan sát tiến độ không có nghĩa là worker kẹt (im lặng không phải "không tiến triển"); attempt `unknown` hiển thị "chưa xác định". Màn hình không phát hiện worker treo.
- **ETA** chỉ khi sổ có ước lượng (baseline/eta của kế hoạch nội bộ hoặc reforecast); không có thì "chưa xác định" kèm lý do; chưa hiệu chỉnh; là công, không phải thời gian lịch. Không có phần trăm.
- **Độ trễ cập nhật** đo trên sổ thử nhỏ (vài chục sự kiện): trần 5 s đặt trước, số đo ghi trong `verify-report.json` (`measures`). Sổ lớn (hàng nghìn sự kiện, nhiều plan) chưa đo; mỗi lần poll dựng lại toàn bộ overview.
- **Trang web**: lắng nghe `127.0.0.1`, không xác thực (máy cá nhân); chỉ GET; HTML một file, không tài nguyên ngoài. Trình duyệt kiểm: Chrome headless (Edge headless trên máy này không dump DOM khi Edge đang mở). Chưa kiểm trên trình duyệt khác hay màn hình nhỏ.
- **Lọc bí mật** theo mẫu (`diagnostics.redact_line` của S1): không phải bảo đảm; bằng chứng mở qua trang vẫn cần đọc trước khi chia sẻ.
- **`track open`** mở trình duyệt mặc định của máy và chạy server tách rời (tự thoát sau 30 phút không request); marker `tracking/server.json` ghi trong sổ. Chưa kiểm `track open` với trình duyệt thật trong bộ tự động (chỉ `open_page(browser=False)`).
- **Version** `2.4.0.dev6+obs1` là nhãn local của lát (PEP 440), không phải version phát hành; nhánh `claude/onecrew-2.4` và gói `2.4.0.dev6` không đổi. Số version chính thức của OBS-1 do chủ/Codex chốt.
- **Chưa Codex review, chưa nghiệm thu.** Gate 2.2 đầy đủ không chạy lại cho lát này (chỉ các module liên quan).
