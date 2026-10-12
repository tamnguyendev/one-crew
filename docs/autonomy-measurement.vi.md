# Đo tự chủ v2: nguồn quyết định, can thiệp, trọn luồng, trial (A2, 12/10/2026)

Mục tiêu của người dùng: tách rõ **người dùng tự quyết**, **Claude chuyển lời người dùng**
và **Claude tự quyết (có hoặc không có ủy quyền)**. Có hỗ trợ là `assisted`; thiếu bằng
chứng là `unknown`. Làm một phần, bỏ qua E2E hoặc chỉ xanh test **không bao giờ** là trọn luồng.
Mọi bản ghi dưới đây chỉ là bằng chứng: không cấp quyền, không trả lời request, không resume.

## 1. Nguồn quyết định (provenance v2)

Mỗi bản ghi quyết định (request reply, SOL approve/request-changes, CREQ reply) có:

| Trường | Giá trị |
|---|---|
| `by` | actor gửi: lấy từ `ONECREW_ACTOR` (CLI) hoặc `--source` của MCP |
| `decided_by` | `user` / `entry` / không rõ |
| `channel` | `user_direct`, `entry_relay`, `entry_delegated`, `entry_undelegated`, `runtime_observed` |
| `user_reference` | `{kind: chat/window/cli, quote_sha256, quoted_at}` — **chỉ lưu hash** lời người dùng |
| `delegation` | `DLG-...` khi entry quyết theo ủy quyền |
| `decision_class` | lớp quyết định suy từ request (vd. lớp recovery), SOL/CREQ là `business` |

`eval_observe.decision_source` trả về: `user`, `relayed`, `delegated`, `undelegated`,
`observed`, `unknown`.

- `relayed` cần `user_reference` hợp lệ; chuyển lời **không có** trích dẫn → `unknown`.
- `delegated` cần ủy quyền đã ghi bao trùm lớp và thời điểm quyết định, chưa thu hồi trước đó;
  không bao giờ cho `business`, `architecture`, `permission`, `budget`. Ngược lại → `undelegated`.
- Bản ghi cũ `decided_by=entry` không có thông tin ủy quyền → `undelegated`.
- `observed` (runtime thấy điều kiện tự hết, vd. đã đăng nhập) không phải quyết định, không là hỗ trợ.

```powershell
$env:ONECREW_ACTOR='claude'
# Chuyển lời người dùng: phải kèm đúng lời của họ (chỉ lưu hash).
python -m onecrew --project <P> --state-root <S> request reply REQ-... --revision <R> --choice retry --decided-by user --user-quote "<nguyên văn lời người dùng>"
# Entry tự quyết trong phạm vi ủy quyền đã ghi; ủy quyền không bao trùm thì lệnh bị từ chối.
python -m onecrew --project <P> --state-root <S> request reply REQ-... --revision <R> --choice retry --decided-by entry --delegation DLG-...
# SOL approve và CREQ reply có cùng cờ --decided-by / --user-quote / --quote-kind.
python -m onecrew --project <P> --state-root <S> solution approve SOL-... --revision <R> --source chat --reference "<mốc tin nhắn>" --decided-by user --user-quote "<nguyên văn>"
```

MCP `reply` nhận `user_quote`, `quote_kind`, `delegation`; `solution_decide`, `conversation_reply`
nhận `decided_by`, `user_quote`, `quote_kind`.

## 2. Ủy quyền (`delegation`)

```powershell
python -m onecrew --project <P> --state-root <S> delegation grant --reference "<nguyên văn lời người dùng>" --classes transient,environment --until 2026-10-13T08:00:00+07:00
python -m onecrew --project <P> --state-root <S> delegation list [--all]
python -m onecrew --project <P> --state-root <S> delegation revoke DLG-...
```

Bản thân lệnh grant là chuyển lời người dùng nên **bắt buộc** `--reference` (lưu hash).
Lớp `business`/`architecture`/`permission`/`budget` bị từ chối. Thời hạn phải có múi giờ, ở tương lai,
tối đa 30 ngày. Thu hồi không hồi tố: quyết định trước thời điểm thu hồi vẫn là `delegated`.
Quyết định `delegated` vẫn làm task `assisted` (lý do `entry_delegated_decision`).

## 3. Ghi can thiệp cho mọi lệnh CLI làm thay đổi

Mọi lệnh mutating của `task`/`request`, `job`, `delivery`, `work`, `core`, `conversation`/`solution`/
`consultation`, `eval assistance|trial`, `delegation`, `desktop` ghi `control.intervention` qua
`interventions.record` với actor từ `ONECREW_ACTOR` (`unknown` nếu không đặt). Lệnh gắn task ghi
trên task (CREQ ghi trên các task bị ảnh hưởng); lệnh không có task (tạo hội thoại, đề xuất/duyệt SOL,
ủy quyền, trial, `core migrate`, `desktop enable`) ghi vào `project_interventions` theo phạm vi.
Lệnh lặp lại idempotent (submit cùng key, create cùng request) chỉ ghi một lần.

`tests/test_intervention_coverage.py` duyệt cây argparse: mỗi lệnh lá phải nằm trong
`READ_ONLY` hoặc `RECORDED` của module; lệnh mới chưa phân loại làm test đỏ.
`eval assistance` có vai trò `evidence` (ghi nhận hỗ trợ không phải là hỗ trợ thêm);
`desktop show/retry` do entry chạy là can thiệp (thông báo cuối không còn là của OneCrew).

## 4. Bàn giao chỉ tính lần đầu

Chỉ **lần duyệt SOL đầu tiên** và **lần submit/start đầu tiên** của task là bàn giao.
Submit/start lặp lại, hoặc duyệt lại SOL không do chính người dùng gõ → `repeat_handoff` (assisted).
Lần duyệt đầu không rõ người quyết → `decision_provenance_unknown`; entry tự duyệt → `entry_undelegated_decision`.

## 5. Mức hoàn thành và lớp kết quả

`COMPLETION_LEVELS = full_loop, plan_complete, partial, tests_only, blocked, incomplete, unknown`;
`OUTCOMES = autonomous_full_loop, assisted_full_loop, plan_complete, partial_complete, tests_only,
correct_block, incomplete, unknown`.

| Loại dự án | Các bước LOOP |
|---|---|
| `node_extension` | change, regression, review, build, e2e_mock, e2e_live, commit, handover, notice |
| `flutter_android` (plan v1) | change, regression, review, build, apk_audit, device, handover, notice |

Node kind → bước: `node_regression`→regression, `node_build`/`node_build_live`→build, `e2e_mock`,
`e2e_live`, `commit`, `handover` giữ tên; `version` không phải bước LOOP.

- `full_loop`: mọi bước LOOP có trong plan, đã pass, không skip, receipt gắn **source cuối**
  (trừ change); receipt commit có `verified: true`, `pushed: false` và commit hash hợp lệ; file
  báo cáo bàn giao tồn tại đúng sha256; thông báo kết quả cuối đã `shown`.
- `plan_complete`: plan chạy xong nhưng thiếu bước (`loop_stage_missing:<bước>`, `commit_missing`,
  `commit_unverified`, `handover_report_missing`, `notice_not_shown`, `loop_stage_stale:<bước>`).
- `partial`: có việc chưa chạy/skip (`<bước>_not_run`, `nodes_skipped`, `criteria_not_run`...).
- `tests_only`: không có build/E2E nào pass; job `native_change` độc lập tối đa là mức này.
- Chỉ `full_loop` + `autonomous` mới là `autonomous_full_loop`; `assisted_full_loop` chỉ do chuyển lời
  vẫn báo đúng như vậy, không làm tròn lên.

## 6. Trial được ghim (`eval trial`)

```powershell
python -m onecrew --project <TARGET> --state-root <S> eval trial open --key <ROOT_KEY> [--target <repo>] [--predecessor TRIAL-...]
python -m onecrew --project <TARGET> --state-root <S> eval trial close TRIAL-...
python -m onecrew --project <TARGET> --state-root <S> eval trial show TRIAL-...
python -m onecrew --state-root <S> eval scorecard --task TASK-... --trial --output <DIR>
```

Mở trial **trước** khi submit task gốc với đúng `<ROOT_KEY>`. Trial ghi trial_id, root key, git
sha + tree + dirty của runtime, state root, HEAD/branch repo đích, thời điểm mở, trial trước.
Trong cửa sổ trial: `runner.started` có tree khác hoặc runtime dirty → `runtime_changed_in_trial`;
commit trên branch đích không nằm trong receipt commit của OneCrew → `external_commit` (cả hai là
assisted). Trial thiếu các bản ghi này, task tạo trước khi mở trial, hoặc không đọc được cửa sổ Git
→ `trial_unpinned` (unknown). `--trial` khi chấm nghĩa là khẳng định task là trial: không có trial →
`trial_unpinned`. Đóng trial lưu cửa sổ commit và dòng scorecard; kết quả được giữ cả khi assisted;
trial sau trỏ `--predecessor` tới trial đã đóng và cần root key mới.

## 7. Môi trường eval có node

`evaluation.environment()` ghi `node: {path, version, sha256}` (khác node là khác môi trường khi
`compare`). `clean_environment` đặt thư mục node đã ghim đầu `PATH` và `ONECREW_EVAL_NODE`, nên probe
Node không âm thầm skip. Thứ tự chọn: `ONECREW_EVAL_NODE`, `PATH`, `%ProgramFiles%\nodejs\node.exe`.

## Lưu ý so sánh

Oracle của các case `scorecard-levels` và `decision-provenance` trong corpus v3 đổi theo quy tắc mới
(trọn luồng, nguồn v2): cần tăng phiên bản corpus và chạy lại **cả hai phía** trên cùng harness.
