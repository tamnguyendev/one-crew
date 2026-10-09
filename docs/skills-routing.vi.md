# Revision 6 — skill từ lịch sử và ưu tiên model

## Bổ sung FB01–FB03: chuyển provider khi hết quota

Yêu cầu operator mới: **Claude → Codex → Kiro**. `provider prefer` nhận các `--fallback PROVIDER:MODEL` theo thứ tự; lưu vào shared state và snapshot trong payload của **job mặc định mới**. Explicit provider/model pin lựa chọn; task cũ/replay không tự nhận chain mới. Bỏ các cờ fallback khi lưu preference sẽ tắt fallback cho job mới.

Runtime chỉ chuyển khi adapter nhận lỗi quota từ error envelope native và supervisor đã xác nhận attempt settled. Không suy quota từ nội dung model/source, HTTP 429 chung, timeout, lỗi đăng nhập hay SDK. Chuyển một chiều theo chain, bỏ qua CLI chưa sẵn sàng qua probe không gọi model, tối đa hai lần; hết chain thì blocked. Checkpoint giữ candidate, tool receipts, câu trả lời, bước review, quyền và root budget. Mọi lượt lỗi đã launch vẫn tính budget. Pending approval, cancel, deadline, quota binding riêng và process chưa reconcile không được vượt qua.

Lựa chọn mới ghi trong checkpoint trước dispatch; restart dùng đúng provider đã chuyển. Outcome ghi provider cuối cùng và handoff history; usage đã có provider/model theo attempt. Native error format không nhận diện được vẫn dùng đường lỗi hiện tại, không đoán exhaustion. Không có cam kết mọi phiên bản CLI đều được hỗ trợ; vẫn khóa pinned CLI capability. Chưa có live trial cố tình dùng hết subscription.

```text
onecrew provider prefer claude --model sonnet --fallback codex:gpt-6.1-sol --fallback kiro:claude-sonnet-5 --reset-hint 2026-10-09T23:00:00+07:00
```

Đây là default cụ thể cho yêu cầu mới, không phải kết luận model tối ưu từ JEV. Không gọi JEV cho mỗi tool hoặc mỗi lần lỗi; JEV vẫn shadow. Task mới tiếp theo lại ưu tiên Claude; không tự bật lại Claude giữa một task khi đồng hồ tới reset hint. Claude/Kiro remaining quota vẫn unknown trước inference nếu chưa có observation. Hết quota được nhận diện trong lần thực thi có giới hạn, không giả định còn quota.

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

## Vận hành đã triển khai

```text
onecrew --project <repo> --state-root <state> skills list
onecrew --project <repo> --state-root <state> skills review <skill-id>
onecrew --project <repo> --state-root <state> skills approve <skill-id> --revision <reviewed-hash> --reference "Câu trả lời thật của operator"
onecrew --project <repo> --state-root <state> skills reject <skill-id> --revision <reviewed-hash> --reference "Lý do không dùng"
onecrew --project <repo> --state-root <state> skills scan
onecrew --project <repo> --state-root <state> provider prefer claude --model sonnet --reset-hint 2026-10-09T23:00:00+07:00
onecrew --project <repo> --state-root <state> provider preference
onecrew --project <repo> --state-root <state> provider choose --file routing.json --jev --brief "Mô tả task đã loại dữ liệu nhạy cảm"
```

`scan` khôi phục đề xuất nếu chuyển outcome→candidate từng bị lỗi I/O; không phải cron. `job outputs` có skill đã dùng và candidate liên quan. Xem đề xuất qua CLI/terminal; callback chat chưa có. Không skill nào được approve trong lần triển khai này. Candidate bị reject không tự đề xuất lại cùng nhóm. V1 chưa có edit/promote phiên bản kế tiếp hoặc import kho bên ngoài.

`routing.json` dùng workload/candidates đúng schema trong [routing policy](routing-policy.vi.md). Model tier/cost_rank do operator cung cấp, chưa suy từ history. `--jev` chỉ gửi brief và metadata model. Một lệnh là một đánh giá độc lập ngoài root task, ghi receipt trong `<state>/routing-decisions/`; không tự gọi ở mỗi worker/tool step. Chi phí evaluator lưu riêng với Claude subscription. Receipt không submit job.

Preference ở `<state>/model-preference.json`, dùng chung các project cùng state-root. Job cũ/replay giữ model trong payload. Explicit `--provider codex` dùng default model của Codex; Kiro cần model explicit nếu chưa có preference phù hợp. MCP submit có thể bỏ provider/model để dùng preference. Không sửa cấu hình mặc định của ứng dụng Claude/Codex/Kiro.

Đã cấu hình state-root đang vận hành ưu tiên **Claude / sonnet**. Alias `sonnet` được CLI local hỗ trợ; provider resolve model thực tế, không khẳng định alias ghim một phiên bản. Reset hint hết hạn không reset quota hoặc đổi model. Explicit job là lựa chọn operator có root budget; auto recommendation vẫn cần quota mới, chưa có hard token cap.

Live [JEV smoke evidence](revision6-jev-evidence.json): một request, 557 input + 43 output tokens quan sát, 828 ms; đề xuất `sonnet` giữa hai ứng viên Claude tổng hợp, confidence 0.88. Tier/cost/quota của trial là **synthetic**, không là số liệu tài khoản. Không dùng để dispatch hoặc kết luận routing tối ưu. Claude doctor xác nhận CLI 2.1.286 đăng nhập subscription; chưa chạy task sản phẩm tiếp theo.
