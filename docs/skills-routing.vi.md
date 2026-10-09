# Revision 6 — skill từ lịch sử và ưu tiên model

Ngày 09/10/2026, Asia/Saigon. Bổ sung revision 5, không thay scheduler hoặc quyền hiện có. Yêu cầu nguồn: chỉ công việc lặp mới đáng tạo skill; đánh giá sau kết quả, ưu tiên Claude và dùng JEV để đề xuất model phù hợp.

## SK01–SK04: history → recurrence → skill

- SK01: Outcome mới lưu chữ ký công việc (mode, công nghệ từ file đã capture, từ mục tiêu), chuỗi loại thao tác, kết quả verification và skill đã dùng. Lịch sử theo project; mỗi task chỉ có một kết quả mới nhất khi đếm, retry/checkpoint không tăng tần suất. Không tự đọc private chat hoặc backfill bằng suy đoán.
- SK02: Sau outcome, code tìm nhóm tương tự trong tối đa 200 outcome gần nhất. Ngưỡng ban đầu: 3 task độc lập, ít nhất 2 task completed/verification passed, cùng mode/công nghệ và độ giao từ mục tiêu >= 0.6; hai thành công phải có cùng chuỗi loại thao tác. Nhóm đạt chỉ tạo candidate, không khẳng định semantic match hoàn hảo. Không gọi AI hoặc cron cho bước này. Cùng nhóm không sinh đề xuất lặp.
- SK03: CLI `skills list/review/approve/reject` hiển thị lý do, task evidence, giới hạn, nội dung SKILL.md và revision. Chỉ approval local của operator với đúng revision mới kích hoạt. Evidence stale hoặc task sau đó thất bại không được dùng làm evidence thành công. Kho nằm ngoài source, file phải khớp hash đã review; không tự thực thi script hoặc nâng grant.
- SK04: Task mới chọn tối đa một skill approved cùng project/mode/công nghệ/từ mục tiêu, đủ quyền tool và còn evidence hợp lệ. Nạp nội dung có giới hạn vào worker, ghi ID/revision/lý do trong checkpoint/output/outcome. Worker có thể báo không phù hợp; gate nghiệm thu của task vẫn độc lập. Không nạp candidate hoặc lấy tên giống nhau làm bảo đảm phù hợp.

Candidate v1 là quy trình khung được dựng từ các thao tác đã quan sát, không tự chép toàn prompt/source/log vào skill. Approval cần người đọc xác nhận tính hữu ích. Task một lần chỉ giữ history/lesson. Sự tương tự ở mức từ chưa nhận diện được paraphrase tốt; không tuyên bố đã có semantic clustering hay tự cải tiến nội dung skill.

## MR01–MR03: Claude và JEV

- MR01: Preference local cho job mới: provider/model mặc định do operator đặt; explicit provider/model luôn ưu tiên. Snapshot lựa chọn ở submit, replay cùng key giữ lựa chọn cũ, không đổi worker đang chạy. Ưu tiên Claude với model alias `sonnet` cho task chưa có đánh giá khác. Đây là lựa chọn operator, không là bằng chứng model tối ưu.
- MR02: Recommendation lọc quyền, capability, tier/risk và quota mới trước; chỉ sau đó ưu tiên provider đã đặt. Reset **2026-10-09 23:00 +07:00** là hint người dùng, không phải quan sát quota, không suy reset mọi giới hạn. Claude chưa có quota feed đã kiểm chứng; thiếu quota thì auto-recommendation vẫn blocked, explicit operator job giữ đường có ngân sách hiện tại. Không fallback trả phí hoặc đổi provider ngầm.
- MR03: JEV opt-in qua `provider choose --jev --brief ... --file ...`, tối đa một request/command, timeout 15 giây, response có schema/size bounds, không retry. Chỉ gửi brief do operator chọn và metadata các candidate đã qua hard gates; không gửi source/transcript/credential. Kết quả là proposal shadow, có confidence/abstain và usage, không thay selection/dispatch. Quota cũ/unknown không được JEV hợp thức hóa. Lỗi JEV giữ recommendation bằng rule và ghi unavailable. Chưa benchmark nên không bật auto-apply.

Nguồn API: [TypeSafe OpenAPI](https://api.typesafe.ai/openapi.json), `POST /v1/systemone`, typed choice với option abstain. Model alias cho evaluator là `jev-latest`; credential dùng DPAPI hiện có. Live smoke chỉ dùng mô tả tổng hợp để kiểm transport/schema, không chứng minh chất lượng chọn model cho task thực tế.

## Kiểm chứng trước task tiếp theo

Test phân biệt 3 task với 3 retry, nhóm sai công nghệ/mục tiêu, failures, approval stale/hash tamper, project isolation, quyền tool, bounded context, restart và automatic runtime injection. Routing kiểm preferred provider không vượt hard gates, explicit override/idempotent submit, hết quota/reset hint, JEV invalid/timeout/abstain. Chạy lại regression owned/learning/routing/entry. Không giao task sản phẩm trong lần nâng cấp này.
