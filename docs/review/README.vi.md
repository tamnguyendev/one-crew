# Backend review — lát thử cách ly 1

Đây là nhánh phát triển song song với bản vá UI của Claude, không phải bản nâng runtime hoặc bản UI để người dùng cài thay. Baseline `bdb13bf` / sản phẩm `6cb2fa9`; UI cũ trong baseline còn R7-1/R7-2, bản sửa UI thuộc checkout `wf-obs2-claude`.

Phạm vi đã chọn từ roadmap chung ngày 04/11:

- **2.5-A:** định danh yêu cầu kiểm và so hiệu lực theo đầu vào/tiêu chí/config/quyền. Tái dùng hash và dữ liệu context hiện có.
- **2.5-B:** consumer review tùy chọn dùng ledger/events/receipt hiện có để chỉ có một lượt đang chạy cho cùng định danh, đối soát kết quả đã ghi và giữ lượt chưa rõ kết quả. Không tạo store hoặc engine mới.
- **RD-A1:** gợi ý cách/mốc kiểm qua client Jev dùng chung với v1. Chỉ là đề xuất; quyết định policy nền không đổi. Kiểm bằng client giả, không API thật.

Các điểm chưa phải sản phẩm hoàn chỉnh:

- Chưa nối mọi cửa hook/verdict/candidate về cùng yêu cầu; chưa điều phối worker review điều tra.
- Caller phải cung cấp metadata thực thi có căn cứ mới được dùng lại kết quả đã hoàn thành. CLI hiện chưa nối metadata đó: chống gọi trùng khi đang chạy, nhưng lần yêu cầu mới sau khi hoàn thành có thể chạy kiểm lại. Không tự suy identity từ tên hàm.
- Lượt có effect chưa rõ không tự retry, không hứa exactly-once qua provider. Không thêm lệnh vượt quyền để xóa trạng thái giữ.
- RD-A1 chưa tự reserve budget, cache, ghi lịch sử advice hoặc nối CLI/bước 0; chưa có benchmark false-SKIP, chưa chứng minh giảm latency/chi phí.
- Không đổi UI/OBS-2B hoặc cơ chế nghiệm thu; observation và proposal không là kết quả kiểm bắt buộc.

Các bài kiểm từ wheel dùng project/sổ tạm và approval/candidate tổng hợp có nhãn rõ. Không phải chủ đã duyệt, model đã review hoặc pilot SignSDK. Gói không được dùng nâng runtime thật. Hướng dẫn và bằng chứng cuối ở `HANDOVER.vi.md` sau khi kiểm artifact.
