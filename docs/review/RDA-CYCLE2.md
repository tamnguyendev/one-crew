# RD-A2 — nối lời khuyên vào vòng đời (chu kỳ 2)

Base `01b10e1` (adapter RD-A1 `suggest` + client Jev v1 dùng chung). Phạm vi: `review_advice.py`, `decision_client_core.py`, `step0.py`, một khối CLI trong `cli.py`, một dòng neutral trong `compat.py`. Không sửa dispatcher/engine/verdict/hook (2.5-B). Chỉ fake provider; chưa gọi Jev thật.

## Kiểm kê (cái đã có, cái thiếu)

| Yêu cầu | Đã có ở RD-A1 | Thiếu (làm ở RD-A2) |
|---|---|---|
| Gợi ý tại bước 0 / trước review tùy chọn | `suggest(stage=step0\|review)`, stateless | hàm gọi theo gốc: `advise`, `advise_step0`, `advise_optional` đọc gốc đã duyệt, dựng validity thật |
| Giới hạn phương án theo quyền/chính sách/dữ liệu | mandatory/standard không gửi SKIP; option exact-fields, không có provider/model | lọc theo grant của gốc (`command` cần `authority.commands`, `investigation` cần `authority.read`), ghi `withheld` + lý do; quyền gọi ngoài = `granted_actions: review_advice:suggest` |
| Ngân sách | caller truyền `remaining_calls` (không phải bằng chứng) | admission + charge qua `metered_verifier.ProviderCall` (Control attempt, ngân sách chung của gốc); không có ngân sách chung / chưa duyệt = không gọi; không bao giờ lấy cuộc gọi cuối |
| Vòng đời/idempotency | không | event trung tính `review.advice_started` / `review.advice`, khóa theo (stage,node,review,validity); cùng đầu vào = trả lại bản ghi; started không có kết quả = unknown, không phát lại |
| Cache/lưu | không | receipt blob (`review-advice`) + event; dùng lại chỉ khi revision/input/policy/budget còn khớp; bản cũ = `stale`, không dùng lại |
| Lối vào | không | `onecrew review advise` (`--show`, `--stage`, `--refresh`) một khối trong cli.py |
| Timeout/lỗi/thiếu cấu hình | fallback giữ policy | giữ nguyên + không retry, không hỏi người dùng; `advise_optional` không bao giờ ném lỗi vận hành vào dispatcher |
| Provenance + lý do ngắn | `model`, `context_sha` | `provenance` đủ (revision, contract/policy/input/budget id, attempt Control, actor), `explain` tiếng Việt ngắn |
| Đánh giá có kiểm soát | 28 test | bộ ca có nhãn, đo false-SKIP/số gọi/độ trễ (test `test_review_rda2_eval`) |

## Hành vi mong đợi (viết trước khi code)

1. Gốc đã duyệt, có ngân sách chung, `granted_actions` có `review_advice:suggest`, ≥2 phương án hợp lệ, còn ≥2 lượt: đúng 1 cuộc gọi, 1 lượt tính vào ngân sách gốc, ghi `started` rồi `review.advice` + receipt; trả `status=proposal`, `effective_action` = policy nền.
2. Gọi lại cùng đầu vào: 0 cuộc gọi, `cache=hit`, cùng receipt.
3. Đổi revision/hợp đồng, policy, đầu vào (facts/options/brief) hoặc ngân sách (group revision): khóa mới, bản cũ báo `stale`, không dùng lại.
4. Mandatory/standard/deep: không bao giờ có lựa chọn SKIP gửi đi; model đòi SKIP (id không được cung cấp) = schema sai = fallback.
5. Option cần quyền gốc không cấp (command khi `commands=false`) bị loại trước khi gửi, ghi lý do; còn <2 hữu ích = không gọi, không tính phí.
6. Không `granted_actions`, không ngân sách chung, gốc chưa duyệt, chưa cấu hình khóa, còn <2 lượt: 0 cuộc gọi, 0 ledger event cuộc gọi, trả `skipped` + lý do; policy nền tiếp tục.
7. Timeout/lỗi/schema xấu: `fallback`, tính 1 lượt (đã thử HTTP), không retry, lần gọi lại cùng đầu vào trả bản ghi cũ; `--refresh` mới gọi lại, và chỉ khi lần trước không phải unknown.
8. Tiến trình chết giữa chừng (có `started`, không có kết quả): trạng thái `unknown`, không bao giờ phát lại (cũng bị chặn bởi attempt unknown của Control).
9. Gốc đổi trong lúc đang gọi: bản ghi ghi `current=false`, không bao giờ được dùng lại.
10. Mọi bản ghi: `grants_authority=false`, `authority=proposal_only`, không có đường tự-đạt, đổi reviewer hay đổi provider.

## Phản chứng (counterexample) phải có

- SKIP đòi cho milestone bắt buộc/policy standard; option có field `provider`/`model`/`PASS`; model trả option ngoài tập; xác suất sai tổng; response chứa khóa API.
- Hai người gọi đồng thời cùng khóa: 1 cuộc gọi.
- Cache từ revision cũ không được dùng sau khi hợp đồng đổi (không chỉ khác khóa: kiểm cả lúc đọc).
- Receipt blob sai hash: không dùng, không gọi lại ngầm.
- Ngân sách còn 1 lượt: không gọi (giữ lượt cuối cho việc thật).
- Không ghi `review.advice*` lên gốc `plan:` cũ (kind neutral class A, `compat.check_write` chấp nhận).

## Giới hạn, nói thẳng

- Fake provider không chứng minh chất lượng gợi ý của model thật; false-SKIP = 0 ở đây chứng minh **cấu trúc** (SKIP không có đường tới `effective_action`), không phải khả năng phán đoán của Jev.
- Bước 0 trước phê duyệt chưa có ngân sách gốc để tính phí: `advise_step0` chỉ chạy được trên gốc đã duyệt có ngân sách chung; còn lại trả `skipped: root_not_approved` (xem quyết định mở D-RDA2-1).
- Ghi nhãn Control: lượt gọi Jev đi qua `ProviderCall` nên Control ghi nhãn provider `claude` / model `jev-advice` làm chỗ giữ; transport thật là Jev. Nên khái quát nhãn này ở 2.5-B/chủ phiên (không sửa `metered_verifier.py` ở đây).

## Điểm nối cho phiên chính (không sửa file của 2.5-B ở đây)

`review_dispatch.optional`, ngay sau khi `decision['action'] == 'REVIEW'` và kiểm lại facts, trước `_request(...)`:

```python
result['advice'] = review_advice.compact(review_advice.advise_optional(ledger, root['selector'], node, review_id, facts=facts))
```

(thêm `review_advice` vào dòng `from . import ...` của file). Hàm không bao giờ ném lỗi vận hành và không đổi quyết định của dispatcher; thiếu quyền/ngân sách/khóa thì trả `skipped` kèm lý do mà không gọi gì. `tests/test_review_rda2_dispatch.py` chạy đúng chuỗi này bằng facts thật của engine (`review_dispatch._context`) rồi gọi `optional` thật.

Bước 0: `step0.advise_checks(ledger, name)` (gọi tay hoặc từ `plan_cli` sau `plan step0 show`); thẻ bước 0 (`step0.show_card`/`render_card`) chỉ hiển thị bản lưu gần nhất, không gọi mạng và không đổi `enough`/`not_enough`.

CLI: `onecrew review advise show --plan P [--node N]` (đọc), `onecrew review advise request --plan P --stage step0|review [--node N --review-id R --facts-file F] [--refresh]` (tốn tối đa 1 lượt của ngân sách gốc, chỉ khi hợp đồng đã duyệt cấp `granted_actions: review_advice:suggest`). Cần khóa Jev (`TYPESAFE_API_KEY` hoặc credential v1): chưa chạy thật ở chu kỳ này.

## Kết quả kiểm (fake provider; log trong `D:\OneCrewRuns\cycle2\rda\logs`)

- Trước code: `red-old-base.log` — chạy bộ test lifecycle trên mã base: 23 lỗi `AttributeError` (hàm chưa có, **không phải** phản chứng hành vi) + 1 fail hành vi (không có đường gọi lifecycle để bắt `entered`). Phản chứng hành vi thật của lõi cũ: `StatelessLeaf` — hai yêu cầu giống nhau của `suggest` là hai cuộc gọi, không để lại dấu vết (hành vi cũ, giữ nguyên, đây là lý do cần `advise`).
- Sau code: `tests.test_review_rda2_lifecycle` 25, `_dispatch` 5, `_surface` 7, `_eval` 13 (kể cả test tổng). Hồi quy hẹp xem bảng ở báo cáo cuối.
- Đánh giá có nhãn (`rda2-eval.json`): 14 ca, 12 cuộc gọi, 2 lần model đòi SKIP bị chặn, false-SKIP 0, stale-reuse 0; mọi cuộc gọi đều qua ngân sách gốc (charged == calls). Độ trễ thêm (máy đang tải): ca gọi 230–1600 ms (đa phần là ghi ledger + một attempt Control), ca lấy lại bản lưu ~15 ms. **Không ngoại suy cho model thật.**

## Quyết định mở (ngoài phạm vi được giao)

- D-RDA2-1: bước 0 **trước phê duyệt** chưa có ngân sách gốc; muốn gợi ý ở đó cần chủ cho một hạn mức gọi riêng trước duyệt (sẽ là ngân sách thứ hai nếu làm vội) hoặc chấp nhận chỉ gợi ý sau duyệt. Hiện: `skipped: root_not_approved`.
- D-RDA2-2: nhãn Control `claude/jev-advice` cho lượt gọi Jev (xem Giới hạn); nên cho phép nhãn provider tường minh ở `ProviderCall` khi 2.5-B xong.
- D-RDA2-3: mức giữ lại `KEEP_CALLS=1` và quyền `review_advice:suggest` là chọn mặc định của tôi; chủ có thể đổi.
