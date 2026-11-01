# Bước 0 đủ để làm và cách chạy node (mốc 2.4-C)

Hướng dẫn ngắn cho mốc 2.4-C trên nhánh `claude/onecrew-2.4-c`. Thiết kế: `outputs/onecrew-as-qc/ROADMAP-DESIGN-20261026.vi.md` §2.1, §2.2, §2.9, §7 (dòng 2.4-C). Bước 0 gốc: `docs/v2-step0.vi.md`.

## 1. Thẻ bước 0

Hợp đồng không thêm trường nào (`contract.FIELDS` giữ nguyên). Thẻ là một **cách xem chỉ đọc** từ kết quả `plan proposal check` (W47) và các khảo sát của plan.

Đề xuất W47 có thêm ba trường **tùy chọn**:

```json
{"preserve": [{"id": "K1", "text": "Báo cáo mới và API của nó giữ nguyên"}],
 "investigation": {"cap": {"minutes": 4, "calls": 4}, "paths": ["src/report", "docs/report.md"], "stop_when": "có câu trả lời trỏ file:dòng, hoặc hết trần"},
 "estimate": {"range": [600, 1800], "evidence": ["src/report/export.py:12"]}}
```

`estimate` cũng có thể là `{"status": "not_enough_data", "missing": "chưa có lần gỡ export nào được đo"}`.

Đề xuất không dùng trường nào trong ba trường này thì được kiểm **y như trước**. Dùng một trường là bật thêm các luật thẻ (nằm trong `proposal.RULES`, nên cổng `plan approve` hiện có tự áp dụng; không có lượt duyệt thứ hai):

| Mã | Khi nào bị từ chối |
|---|---|
| `preserve_missing` | có thay đổi `modify`/`delete` mà không nêu điều giữ nguyên |
| `estimate_missing` / `estimate_unsourced` / `estimate_zero` | thiếu ước lượng; số trần không có khoảng; khoảng không có căn cứ trỏ được; khoảng bắt đầu từ 0; đưa khoảng trong lúc còn unknown mà ước lượng phải chờ |
| `investigation_unscoped` / `investigation_cap` / `investigation_over_cap` / `investigation_missing` | điều tra cả project (`.`); trần ngoài 1–120 phút, 1–50 lượt; khảo sát đã tiêu quá trần; có unknown chặn lựa chọn mà không khai điều tra |
| `unknown_open` | còn unknown mà việc duyệt phải chờ (`required_by: approval`) |

**Khi nào thẻ đủ để làm** (`enough: true`): kết quả kiểm là `ok` (một phương án ưu tiên có lý do, mọi acceptance có thay đổi, ngữ nghĩa phá hủy đúng, điều giữ nguyên, ước lượng có căn cứ hoặc "chưa đủ dữ liệu"), không còn unknown đổi được quyết định (`option_choice`, `approval`) đang mở, và khảo sát chưa tiêu quá trần. Việc rõ, trong quyền (`in_authority`) không cần thêm phương án, mockup hay câu hỏi cho chủ (`owner_requests: 0`).

Xem thẻ (không ghi gì vào sổ):

```
onecrew plan step0 show <plan>          # vài dòng tiếng Việt
onecrew plan step0 show <plan> --json   # đủ trường
```

Ước lượng trên thẻ **không bao giờ** thành trần chạy hay ngân sách: `plan approve` vẫn ghi `estimate.baseline` theo `--estimate-file` như cũ.

## 2. Trần điều tra và điểm dừng

Khi đề xuất khai `investigation`, mỗi khảo sát của bước 0 chỉ đọc trong `paths` đã khai, kết thúc theo `stop_when`, và trần mặc định của khảo sát được thu lại bằng phần còn lại. Khảo sát bị từ chối (không ghi gì) khi tổng trần các khảo sát đã mở trên plan không còn chỗ. Tổng tính trên cả plan, không trên một revision: một khảo sát có câu trả lời đóng unknown bằng một revision mới.

Điều tra dừng khi không còn unknown đổi được quyết định, khi hết trần, hoặc khi một khảo sát kết thúc `blocked`; thẻ ghi `stopped_because`. Unknown rủi ro cao còn mở thì **vẫn mở**: duyệt vẫn bị giữ ở bước 0, còn sau khi duyệt thì `onecrew unknown open --plan <plan> <key> --file <f.json>` (trường `required_by` liệt kê node) giữ đúng các node cần nó, node độc lập vẫn chạy. Không có gì tự đóng unknown.

## 3. Chọn cách chạy node (capability `execution-mode`)

Root khai thêm capability `execution-mode` (cần `sequential-engine`; `parallel-engine` cho 2 slot) khi `plan propose --workflow`. Root không khai thì engine chạy y như 2.3, không ghi thêm gì.

Với root có capability, trước mỗi lần chạy node worker engine chọn và **ghi lý do**:

| Chế độ | Nghĩa |
|---|---|
| `run_now` | chạy một node như thường; với slot thứ hai nghĩa là "chưa, chờ lượt" |
| `overlap` | chạy song song với node khác trong 2 slot, khi hai node độc lập: khác file ghi, không đọc file node kia ghi, không chung nhãn `resources` |
| `continue_worker` | tiếp tục chuỗi attempt của chính node đó (sau một kết quả dở dang): không reset ngân sách, giữ bằng chứng; **không phải** giữ phiên model |
| `tools` | chạy phần kiểm không cần model (milestone `command`/adapter) của node đã produced, không tạo task con, không chiếm slot; phần kiểm cần reviewer model không bao giờ là `tools` |
| `wait` | đang bị chặn; `reasons` nêu điều chặn (dependency, tài nguyên độc quyền, attempt cũ chưa rõ, hết ngân sách, hết capacity) |

Thứ tự xét: quyền/dependency/tài nguyên độc quyền/ngân sách/attempt cũ/capacity → gói context có đủ → lợi chồng lấp so với chi phí bàn giao → chạy qua admission hiện có. Chi phí bàn giao chỉ tính khi đo được (tốc độ chuẩn bị quan sát trên root × context của node trước); chưa đo thì là `unknown`, không phải 0, nên không nhận lợi (`handover_unknown`). Node nhỏ nhận context lớn thì không chiếm slot thứ hai (`handover_exceeds_gain`) và bản ghi khuyên gộp node khi lập plan. Một nhánh không nhận gì từ node khác có thể chạy song song theo giả định ghi rõ.

Bản ghi nằm ở: action Q2 trong `decision.recorded` (khóa `mode-<inputs_sha>`), `node.started` (`mode`, `mode_reasons`, `mode_inputs_sha`, `session`, `context.restored_from`), và sự kiện `workflow.mode` (lớp B) cho lần chờ, chờ capacity, slot thứ hai không dùng và lần chạy `tools`. Chỉ xét lại ở mốc step/batch.

Lệnh: `onecrew engine step <plan> [--checks]`, `onecrew engine batch <plan> [--slots 1|2] [--checks]`, `onecrew engine measure <plan>` (chỉ đọc: thời gian tới kết quả hữu ích đầu tiên, các đoạn admission/chuẩn bị/thực thi, chờ, kiểm, làm lại; thiếu quan sát là `unknown`, các nhánh chồng lấp lấy hợp, không cộng).

## 4. Giữ phiên model

Hiện **không** adapter nào giữ phiên: mọi bản ghi có `session.reuse: false`, và `context.restored_from` nói context được dựng lại từ đâu (`source_snapshot`, `input_artifacts`, `resume_artifact`, `knowledge`). Không bao giờ ghi là khôi phục "từ resume_pack" (đó là gói cấp plan). `reuse: true` chỉ được ghi khi adapter khai capability `resume_session` và trả về đúng mã phiên nó đã ghi lúc launch; chưa adapter nào được giao có điều này.

## 5. Giới hạn

- Fixture chứng minh luật và bản ghi, không chứng minh model thật đề xuất đúng hay chạy nhanh hơn; chưa đo trên provider thật.
- `size`, `in_authority` vẫn do AI tự khai; thẻ không coi đó là bằng chứng "nhỏ nhất".
- Capacity tính theo state root (tối đa 2 attempt); không xét CPU/RAM. Pipeline theo dependency là mốc 2.5-B.
