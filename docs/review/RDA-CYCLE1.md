# RD-A1 — adapter gợi ý, chưa nối runtime

Baseline `bdb13bf` (product dev7 `6cb2fa9`). Phạm vi được giao: một lát callable cách ly, dùng lại client Jev v1, fake provider khi kiểm; không đổi CLI/hook/engine/UI hoặc runtime thật. Căn cứ: roadmap/design/handoff `review-responsibilities-20261104`, design `work-history-jev-20261104` §RD-A và RV-T5. Không coi lát này là RD-A hoàn chỉnh.

## Kết quả

`onecrew.v2.review_advice.suggest` gợi ý phương pháp/mốc kiểm trong các phương án controller cung cấp, dùng chung cho bước 0 (`stage='step0'`) và ranh giới review (`stage='review'`). Không phải chức năng chọn toàn bộ solution, không đọc source/tự điều tra, không kết luận công việc đạt. Không có đường runtime nào tự gọi nó trong lát này.

- Policy nền vẫn do `review_policy.evaluate` tính; `effective_action` luôn giữ giá trị đó. Model chỉ có `proposal_only`, không dispatch, không áp dụng tự động, chưa hiệu chỉnh chất lượng.
- Mandatory và policy standard/deep không gửi lựa chọn SKIP cho model. Unknown/finding/not-ready giữ HOLD/DEFER và không gọi. Policy light được gợi ý REVIEW thận trọng hơn nhưng không tự áp dụng, cũng không dùng gợi ý để giảm số review.
- Thiếu cấu hình/quyền/ngân sách hoặc dưới hai lựa chọn hữu ích: không đọc credential, không gọi mạng. Có quyền/ngân sách là thông tin caller truyền, không phải adapter xác minh grant hay đặt chỗ ngân sách.
- Một request tối đa 16KB, response64KB, timeout15s, không redirect/retry. Lỗi auth/timeout/schema dẫn fallback giữ policy; không lộ thông báo provider hoặc key. Call count là số lần thử HTTP, không phải chứng minh charge của provider.
- Trả revision/contract/input/policy/budget identity và context hash để caller truy nguồn. Chưa cache/persist/reconcile; caller không được coi trả về một identity là bằng chứng identity còn hiệu lực ở thời điểm áp dụng.

## Tái sử dụng

`decision_client_core.py` tách credential reader/DPAPI, transport và choice validator từ Jev/model_advisor v1; `jev.py` còn configure/doctor wrapper, `model_advisor.py` giữ lựa chọn model và API cũ, dùng chung core. Không đưa CLI v1 vào wheel, không bỏ guard v1-only. Adapter dùng `routing.validate_decision`, `review_policy.evaluate`, `discovery.scan_text`, canonical/hash hiện có. Quét field thô trước JSON, bổ sung chặn Authorization/credential URL ở ranh giới outbound của adapter.

Tập option chỉ gồm `{id,label,action,method,checkpoint}`, tối đa16; method là command/bounded_review/investigation. Đây là phương án được cung cấp, **không chứng nhận khả năng thực thi**. Không có field đổi provider/model pin của task. Sources tối đa64, brief2000 ký tự, context tổng12KB. Validity gồm revision dương, contract/input/policy SHA256 và budget_revision; policy hash phải khớp policy thật đưa vào hàm.

## Kiểm chứng của nhánh

- Trước code: test mới không import được adapter (Missing), không gọi đó là phản chứng hành vi trên dev7.
- Lượt đầu 23 test:22 đạt, ca generic Authorization Bearer chưa bị bộ lọc có sẵn bắt. Đã bổ sung kiểm outbound trước network, giữ ca đó.
- Sau sửa: `python -B -X utf8 -m unittest tests.test_review_advice tests.test_decision_client_core tests.test_model_advisor tests.test_jev -v`: 28/28, 0 skip. Provider/credential đều giả; ca DPAPI v1 chỉ roundtrip giá trị giả trong bộ nhớ, không đọc hay ghi credential thật.
- Hồi quy hẹp `test_wf_review_policy.PurePolicyTests`, `test_discussion`, `test_routing`: 33 lượt test đạt, 0 skip (discovery của discussion gồm cả base conversation tests; không gọi đây là33 test mới). Giữ hành vi no-replay sau Jev outcome chưa rõ của v1.
- `docs/review/verify_rda.py`: script độc lập10check, chỉ import module được ship; parent chạy bằng Python wheel ngoài checkout. Không gắn nhãn wheel đã đạt chỉ vì source đạt.
- Không chạy full gate, provider thật, migration hoặc kiểm UI; không sửa sổ/registry/runtime thật.

## Tích hợp do parent sở hữu

Thêm đúng `onecrew.decision_client_core` và `onecrew.v2.review_advice` vào py-modules, chạy closure và script wheel. Không ship `onecrew.jev` hoặc `onecrew.model_advisor`; shared core chỉ phụ thuộc standard library, adapter phụ thuộc core/v2 đã có. Không cần bỏ guard `test_g1_core.V1_ONLY`.

## Phần chưa làm, không báo hoàn tất

- Runtime caller xác minh grant, reserve/charge ngân sách, idempotency và unknown-outcome/restart qua lifecycle hiện có (nối 2.5-A/B).
- Lưu lời khuyên vào decision/receipt có provenance, cache/revalidation theo input/revision/policy/budget và xử lý input đổi trong lúc gọi. Adapter hiện không có cache riêng.
- Chọn solution đầy đủ, gắn đề xuất với step0/advisor và UI, API/CLI người dùng.
- Benchmark có nhãn/false-SKIP, đo latency/chi phí/chất lượng trước tự động giảm review; provider thật, local backup.

Không phải dependency của bản vá OBS-2; không đổi thứ tự release, version sản phẩm, quyền publish hoặc 92 task.
