# Bản vá cross-review dev5 → dev6

Nguồn: review độc lập Claude ngày 04/11 và Codex xác minh trên wheel dev5 `6122d0a5…7bc20f`; chủ giao sửa hết 3 P2 và 4 P3. Không mở rộng OBS-2, không nâng runtime thật, không push/tag hoặc chạy toàn gate.

| ID | Expected output | Cách kiểm |
|---|---|---|
| U6-1 | Chờ kiểm chỉ khi có đầu ra chờ kiểm; phần đã kiểm + phần chưa chạy không bị gộp sai | WAIT: C verified, I pending, câu hỏi mở; đối chứng DOC produced |
| U6-2 | Không giao chủ việc nghiệm thu khi thiếu mốc/handoff; đủ bằng chứng vẫn trình nghiệm thu | CHECKED; handoff có action thật / giả thiếu action; milestone pass; không gọi artifact_sha từ viewer |
| U6-3 | Lệnh ghi chỉ hiện khi runtime và sổ khớp hook project | Missing / executable khác / state khác / cùng binding; cả approve và mọi option answer |
| U6-4 | Finding đọc được, evidence gốc vẫn mở được | CODE finding structured và mô tả plain text |
| U6-5 | Blob văn bản hợp lệ không bị báo lỗi JSON | Text evidence; blob mất vẫn có cảnh báo |
| U6-6 | Kế hoạch ban đầu khác sửa kế hoạch | internal_revision=1 và lịch sử thay đổi sau đó |
| U6-7 | Khoảng nhiều ngày có vạch dễ đọc | 4.01, 4.7, 5, 6, 12, 100, 3650 ngày; ms/giờ hồi quy |

Tái dùng: doctor/check_hooks và portable_settings để xác minh binding, không gọi executable do project cung cấp; milestone_views và finding register; tách đọc handoff evidence khỏi root_ready hiện có. root_ready vẫn kiểm working tree trước nghiệm thu. Viewer chỉ mô tả điều kiện theo bằng chứng đã ghi, không xác nhận working tree hiện tại và không ghi sổ.

Chính sách bảo thủ khi binding thiếu: vẫn xem task, solution, output, câu hỏi; ẩn toàn bộ mẫu ghi và giải thích vì sao. Không đổi hook hay nâng runtime để mở nút copy. UI đặt cạnh SignSDK 2.3 vẫn chỉ đọc; nâng runtime là việc riêng.

Kiểm theo lớp: phản chứng source → hồi quy ảnh hưởng → chốt commit → wheel cài ngoài checkout → cùng bộ phản chứng cũ/mới → browser desktop/mobile và slow/switch/timeout → bàn giao. Script thử chỉ tạo state/project mới; hook fixture không đăng ký vào registry. Test owner thành công là fixture, không phải nghiệm thu của người dùng.

Không tính các giới hạn sổ lớn, clipboard của chủ hay provider thật là đã kiểm. Không coi mọi feature 2.5 đã xong chỉ vì số wheel là 2.5.0.dev6. Kết quả và hash cuối được ghi trong HANDOVER sau khi chạy xong.
