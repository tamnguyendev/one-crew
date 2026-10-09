# Duyệt solution trước implement — SG01–SG05

Nguồn: người dùng yêu cầu giảm hiểu sai/rework, trao đổi với Codex trước khi chốt solution, kiểm soát thay đổi khi triển khai và chất lượng task song song. Đây là thiết kế bổ sung ngày 09/10/2026. Hướng dẫn entry áp dụng cho việc giao task mới; runtime gates dưới đây CHƯA triển khai đầy đủ. Không thu hồi quyền của task đã được giao trước thay đổi này.

## Luồng người dùng

1. Người dùng mô tả kết quả cần có, Codex làm rõ tình huống và tiêu chí nghiệm thu.
2. OneCrew khảo sát source trong phạm vi/budget đọc được cấp và đề xuất solution. Chưa cấp quyền sửa sản phẩm. Nếu cần spike chạy code, nêu riêng mục tiêu, giới hạn và quyền cần có; không coi khảo sát là quyền triển khai.
3. Codex trình bày bản duyệt nhanh, giải thích lựa chọn, phản biện giả định và cùng người dùng điều chỉnh. Thảo luận chưa phải approval.
4. Người dùng chốt solution hiện hành. Entry ghi quyết định đúng revision và provenance; core mới cấp/kiểm quyền implement trong scope đã chốt. Approval solution không tự cấp shell, publication, budget hay quyền khác.
5. OneCrew triển khai từng lát, test và review theo acceptance của solution. Bàn giao lát đầu để kiểm tra sớm trước khi nhân rộng cùng pattern.
6. Nếu phát hiện solution không khả thi hoặc cần đổi hợp đồng, dừng phần bị ảnh hưởng, lưu checkpoint và đề nghị thay đổi; chỉ tiếp tục sau quyết định đúng revision.

Không cần viết lại tài liệu dài sau mỗi câu chat. Một solution có bản nhanh cho người dùng và chi tiết triển khai cho worker, cùng revision; phần chi tiết không được thêm nghĩa vụ ẩn. Spec đã được người dùng chốt và đủ nội dung solution thì tái sử dụng, không yêu cầu duyệt lại cùng quyết định.

## Bản duyệt nhanh

Giữ khoảng 200–350 từ, ưu tiên ví dụ cụ thể:

- **Tôi hiểu yêu cầu:** người dùng nào, thao tác gì, kết quả quan sát được; 2–3 ví dụ nghiệm thu gồm lỗi/ngoại lệ quan trọng.
- **Cách giải quyết:** luồng từ đầu vào tới kết quả, phần tái sử dụng, phần cần thay; lý do chọn cách này.
- **Giả định và bằng chứng:** điều đã xác minh trong source, điều chưa biết, ràng buộc backend/SDK/data; không trình bày suy đoán thành sự thật.
- **Phạm vi và giới hạn:** nội dung lần này, điều để sau, thay đổi tương thích hoặc dữ liệu nếu có.
- **Kiểm chứng và lát đầu:** test nào chứng minh gì, phần cần thiết bị/môi trường thật; mốc người dùng có thể review sớm.
- **Quyết định cần chốt:** khuyến nghị và phương án thay thế chỉ khi có trade-off đáng kể; giới hạn thời gian/lượt sửa đang áp dụng.

Ví dụ Cloud Auth: thống nhất credential kiểm tra và credential gửi; lỗi thiếu cấu hình khác lỗi mạng; giữ tương thích caller/config đã hỗ trợ. Nêu rõ source fix/test khác với xác nhận lỗi trên APK. Nếu backend thực tế yêu cầu cơ chế khác thì phải mở change request, không tự chuyển auth protocol.

## Trách nhiệm và thay đổi solution

| Tình huống | Xử lý |
|---|---|
| Sửa compile error, đổi tên helper, thêm test, retry trong giới hạn đã chốt | Worker tự làm, ghi evidence; không hỏi lại người dùng |
| Khó khăn kỹ thuật, chưa biết có thể giữ nguyên solution không | OneCrew giữ checkpoint, tạo yêu cầu technical review cho entry; Codex khảo sát/giải thích trong quyền hiện có |
| Đổi hành vi người dùng, UX chính, API contract, schema/migration, bảo mật, dependency nền tảng, phạm vi hay tiêu chí nghiệm thu | Solution change request; Codex trình bày và người dùng quyết định trước khi chạy phần bị ảnh hưởng |
| Muốn bỏ tính năng, thay bằng mock/stub, giảm test để pass, hoặc coi yêu cầu không khả thi là completed | Không được tự làm; báo bằng chứng và phương án cho người dùng |
| Vượt quyền, budget, số lần phục hồi hoặc cần nguồn lực bên ngoài | Dùng request/grant tương ứng; technical review không cấp quyền thay người dùng |

Change card gồm: solution/revision gốc; vướng mắc và bằng chứng; vì sao không thể tiếp tục theo cách cũ; phương án đề xuất và lựa chọn; ảnh hưởng hành vi/file/task/test/thời gian; phần nào đang dừng, phần nào độc lập còn chạy. Không yêu cầu người dùng đọc toàn bộ log.

Codex được phản biện và đề xuất, không tự approve thay đổi sản phẩm. Chưa có câu trả lời thì vẫn chờ; timeout/skip/ack không là đồng ý. Chỉ worker trong phần độc lập, còn đúng hợp đồng đã duyệt, mới tiếp tục. Approval cũ không hợp lệ với revision solution đã đổi; evidence của các nhánh phụ thuộc phải được kiểm lại.

## Song song có điều kiện

Mặc định thiết kế cho một feature là một implementation worker. Chỉ chia song song sau khi interface/data contract và acceptance chung đã chốt, ownership không chồng nhau, dependency rõ và có một người/worker chịu trách nhiệm ghép kết quả. Quyền đọc/review có thể riêng; reviewer không đồng thời sửa cùng candidate đang được xét.

Lát đầu chứng minh pattern bằng test/demo; các lát tương tự mới được mở rộng sau mốc review đã thống nhất. Core không cho mỗi worker tự chọn lại kiến trúc chung. Chia file khác nhau chưa đủ chứng minh độc lập về ngữ nghĩa. Task độc lập ở repo khác có thể song song trong capacity hiện có.

Theo dõi tỉ lệ đạt acceptance ở lần review đầu, số vòng sửa do hiểu sai yêu cầu, số đổi solution và lỗi khi tích hợp. Nếu chất lượng giảm, giảm concurrency/lát công việc và làm rõ contract trước khi tăng model/budget. Chưa có số đo để kết luận concurrency là nguyên nhân lỗi của Kiro Crew.

## Nối vào runtime hiện có

Không thêm scheduler/service/AI điều phối cho mọi thao tác. Tái sử dụng spec revision, ledger request, entry packet, outbox và amendment/dependency closure.

| ID | Phần bổ sung | Tiêu chí kiểm chứng | Hiện trạng |
|---|---|---|---|
| SG01 | Khảo sát → solution review → implement | Job mới không nhận quyền viết sản phẩm khi solution chưa được duyệt; audit thuần đọc không bị buộc duyệt solution implement | Thiết kế; entry policy đã ghi |
| SG02 | Ràng buộc solution ID/hash vào job/candidate | CLI/MCP/start/resume đều từ chối approval thiếu/cũ; technical detail đổi cũng làm revision đổi; không tự duyệt từ feedback | Spec CLI đã có revision; binding owned/native job còn thiếu |
| SG03 | Typed technical review/solution change và phần phụ thuộc | Lưu request trước thông báo; restart/chuyển chat giữ pending; stop/quarantine writer bị ảnh hưởng; không apply candidate lệch solution | Inbox có sẵn; native question hiện còn generic; detection/gate chưa đầy đủ |
| SG04 | Contract chung và kiểm tra từng lát trước song song | Scope/ownership + semantic contract IDs; invalidation nhánh phụ thuộc khi đổi solution; integration gate | Legacy DAG/amend có nền tảng; owned/native integration còn thiếu |
| SG05 | Review đầu ra theo solution, thông báo đúng khả năng | Reviewer kiểm acceptance/solution revision; outbox có revision/diff; ACK không approve; không inference lúc idle | Reviewer/feed có sẵn; solution binding và chat callback chưa có |

Thứ tự triển khai: SG01–SG02 trước; SG03 và review SG05 sau; SG04 sau khi luồng một worker được thử. Chưa cung cấp lệnh solution giả như thể đã chạy được. `spec review/approve/diff` hiện có; `job submit` vẫn chưa bị cưỡng chế bởi solution approval nên entry phải giữ chốt duyệt.

Runtime thực thi hash/quyền/phase bằng code; worker/reviewer hỗ trợ phát hiện lệch ý nghĩa. Không thể đảm bảo phát hiện mọi lệch solution chỉ bằng prompt hoặc text similarity. Test theo ví dụ nghiệm thu và người dùng xem lát đầu vẫn cần thiết.

Local inbox/terminal/feed hiện có thể giữ thông báo. Chưa có host adapter được kiểm chứng để đánh thức Codex hoặc tự chèn thông báo vào chat; không hứa “OneCrew sẽ tự gọi Codex” ở trạng thái hiện tại. Khi entry kết nối/đọc status, nó phải đưa change card đang pending lên trước kết quả thường. Không bật lại heartbeat AI khi idle.
