# Ngân sách task mới và bài học sau thực thi

Ngày 10/10/2026. Người dùng đã chốt đề xuất 100 lượt / 2 giờ, đánh giá ở 70% và dùng lịch sử để đề xuất mức cho lần sau. Đây là mức khởi đầu, không phải ước lượng đã được benchmark hoặc cam kết hoàn thành. Cycle BP01–BP04 dùng proposal-driven-development; không đổi grant của Cloud Auth đang chạy.

## Chính sách đã triển khai

- BP01: `job submit` qua CLI, Python và MCP mặc định 100 managed invocations / 7.200 giây khi không truyền hạn mức. Tham số explicit luôn được ưu tiên. Replay cùng key dùng grant/model/policy đã lưu, không đổi task theo default mới hoặc lịch sử vừa có. Task cũ không có budget_policy tiếp tục chính sách cũ.
- BP02: policy version 2 được đóng trong payload khi submit. Tại checkpoint không còn attempt chạy, nếu đã dùng 70% calls hoặc 70% thời gian, tạo REQ để đánh giá: snapshot, test đạt/lỗi, outputs, stage/repair rounds và kế hoạch worker. Đây không phải chứng minh 70% công việc đã xong. Mặc định 100/2 giờ nghĩa là 70 calls hoặc 84 phút; policy cũ 20 calls/10 phút chỉ còn cho task cũ. Hard deadline tính cả thời gian chờ. Hết hard budget thì gate chặn dispatch; không tạo lời mời tiếp tục thiếu ngân sách.
- BP02: REQ vẫn có continue/pause/stop. Continue chỉ đặt mốc đánh giá kế tiếp ở 70% ngân sách còn lại; không tăng grant, trả lời approval hay tự đổi solution. Im lặng/defer không là câu trả lời. Lặp dữ liệu, vòng sửa thất bại và thay đổi solution vẫn chịu gate hiện có, không chờ tới 70%. Cảnh báo effort không ngắt model call hoặc build đang chạy.
- BP03: outcome lưu grant hiệu lực, model, usage quan sát, số calls, test, repair rounds và thời gian. `wall_seconds` từ submit tới checkpoint chứa cả chờ; `settled_attempt_seconds` từ reservation tới settle, gồm startup. Chưa có đo active compute hoặc phân rã từng wait reason, nên các trường đó là null. Checkpoint cùng kết quả không nhân đôi history. Mỗi outcome tự sinh một retrospective có status proposed, liên kết outcome event và snapshot. Không coi thông tin này là chẩn đoán nguyên nhân, model tối ưu hay skill đã duyệt.
- BP04: `learning budget` đề xuất theo tối đa 200 outcome cùng project, mỗi task lấy outcome mới nhất. Cần ít nhất ba task có cùng goal chính xác/mode/provider/model, tất cả completed và verification passed/evidence_collected, không bị yêu cầu sửa lại. Khuyến nghị lấy mức lớn nhất đã quan sát cộng 50% dự phòng, sàn 20 calls/10 phút, trần 10.000 calls/8 giờ. Dữ liệu thiếu hoặc có failure trả 100/2 giờ và classification insufficient_history. Chưa khẳng định môi trường giống nhau hay khách hàng đã nghiệm thu. Đây chỉ là advice có evidence, không tự giảm/tăng budget của job. Entry chọn mức khác bằng tham số explicit sau khi review.

Task mới lưu budget_advice để giải thích lựa chọn và hỗ trợ review sau này. JEV chưa được dùng để tính budget trong policy này; không gọi AI cho từng tool hoặc mỗi lần đọc status. Job không tự dùng hết ngân sách đã cấp. Task lớn chia mốc có đầu ra kiểm chứng và root budget chung, không tạo nhiều task để reset trần. Chỉ khi một quy trình lặp đủ điều kiện mới đề xuất skill theo chính sách skills hiện có.

## CLI

```text
onecrew job submit --goal "Yêu cầu đã làm rõ" --key unique-key
onecrew job submit --goal "Yêu cầu đã làm rõ" --key another-key --max-calls 150 --max-seconds 10800
onecrew learning outcomes
onecrew learning lessons
onecrew learning budget --goal "Yêu cầu đã làm rõ" --mode audit --provider claude --model sonnet
```

Ví dụ submit audit chỉ minh họa ngân sách; job ghi source vẫn cần solution approval và quyền runtime theo entry contract. Hạn mức managed calls không phải giới hạn token cứng của các CLI bên dưới.
