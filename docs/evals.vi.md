# Đánh giá OneCrew bằng bằng chứng

`eval` là lớp đo độc lập. Không sửa task, tự trả lời request, tăng budget,
chuyển model, start worker, cài APK hoặc hiện lại thông báo. Không dùng scheduler.

## Hai lớp đo

1. **Runtime replay:** corpus trong `onecrew/eval_corpus.py` giữ case đã gặp,
   commit trước fix, oracle và giới hạn. Git archive tạo bản sao riêng; cùng test
   harness đã commit chạy trên cả hai revision. Provider, Flutter và ADB là fixture.
   Một số case kiểm **dừng đúng khi thiếu cache/side effect chưa rõ**; đạt oracle
   này không có nghĩa đã tự sửa cache hoặc hoàn thành sản phẩm.
2. **Task observation:** đọc checkpoint, outcome, entry evidence và Windows receipt
   thật. Chỉ chiếu trường có cấu trúc; không tìm chữ “pass” trong báo cáo model.
   `recorded_pass` là ledger đã ghi, không phải chạy kiểm lại. Test receipt không
   đồng nghĩa số test cases; thiếu số skip giữ unknown. Thiết bị do entry kiểm được
   ghi `entry_evidence_only`. `assistance=unknown/none` không chứng minh unassisted.

Các case hiện tại đều `known_case`. Không gọi chúng là held-out, không lấy tỷ lệ
test runtime làm tỷ lệ product autonomy. `product_autonomy_rate=null` nghĩa là
chưa đo được, không phải 0% và cũng không phải 100%.

## Chạy trước–sau

Chạy từ repo OneCrew. Harness phải là commit có `eval_probe.py`; harness-ref của
cả hai lượt phải giữ nguyên. Output nên đặt ở ổ còn đủ dung lượng.

```powershell
python -m onecrew eval cases
# Chọn một commit harness cố định, ví dụ hash trả về bởi git rev-parse HEAD.
python -m onecrew eval replay --ref historical --harness-ref <HARNESS_SHA> --repeat 2 --output D:\OneCrewEvals
python -m onecrew eval replay --ref <AFTER_SHA> --harness-ref <HARNESS_SHA> --repeat 2 --output D:\OneCrewEvals
python -m onecrew eval compare --before <BEFORE_RESULT.json> --after <AFTER_RESULT.json> --output D:\OneCrewEvals\comparison.json
```

`historical` chọn baseline riêng ngay trước commit sửa từng case. Đây là kiểm chứng
từng khả năng, **không phải** phần trăm tiến bộ giữa hai bản release. Để so release,
thay `historical` bằng một commit trước chung. Cùng corpus, harness, Python/OS,
timeout, danh sách case và số repeat mới được so. Có thể dùng `--case <id>` nhiều
lần; không so tập nhỏ với tập lớn hoặc âm thầm loại case thất bại.

Kết quả lưu từng probe/status/diagnostic, commit, hash corpus/harness/grader,
environment và partial checkpoint. Result JSON có digest kiểm lỗi; đây không phải
chữ ký chống người có quyền sửa cả file. `compare` kiểm consistency, từ chối partial,
case thiếu/lặp, fake pass, đổi revision hoặc oracle. `--ref` chỉ đọc Git commit,
không tính thay đổi chưa commit. Working tree/index/task ledger thật không bị sửa.

| Status | Ý nghĩa |
|---|---|
| `passed` | Mọi assertion đã chạy, không skip/error |
| `assertion_failed` / `runtime_error` | Probe đã load nhưng hành vi/assertion hoặc runtime lỗi; đọc diagnostic để phân biệt setup và lỗi thật |
| `capability_unavailable` | Không load được API/module của baseline; không khẳng định đã tái hiện lỗi hành vi |
| `skipped` | Chưa được kiểm, không tính pass |
| `timed_out` | Hết deadline probe, process tree bị dừng |
| `harness_error` | Hỏng oracle/runner, không được suy thành cải tiến runtime |

`recovered` là từ error/failure sang pass, cần đọc log trước khi kết luận nguyên nhân.
`capability_added` báo API/capability mới; `regressed` gồm cả pass trước → skip sau.
Không có model calls trong replay; thời gian probe không phải thời gian giải task.
Harness chỉ chạy các selector đã review trong corpus, không nhận shell từ case ngoài.
Git archive/test là code local được tin cậy, không phải sandbox bảo mật cho repo lạ.

## Quan sát các task thật

```powershell
python -m onecrew --state-root C:\path\to\OneCrew eval observe --task TASK-<FULL_ID> --task TASK-<OTHER_FULL_ID> --output D:\OneCrewEvals\observed.json
```

Read-only SQLite transaction giữ cùng mốc seq cho cả mẫu. Output chọn lọc có
task/project ID, event seq/hash, phase episodes, calls, timeout checkpoints, repairs,
gates và assistance. Không export raw report, prompt, cấu hình, mật khẩu hoặc log.
Các entry evidence sau checkpoint vẫn được giữ; outcome terminal cũ không được
lấy làm calls hiện tại nếu snapshot/phase đã đổi. Windows chỉ nhận receipt đúng
episode hiện tại; `shown` không chứng minh người dùng đọc. File output không ghi đè.

Khi entry phải làm hộ hoặc sửa môi trường/runtime, ghi can thiệp ngay vào đúng task
(nếu là child, parent sẽ tổng hợp cả child và shared calls):

```powershell
python -m onecrew --project D:\path\to\task-project --state-root C:\path\to\OneCrew eval assistance --task TASK-<FULL_ID> --key repair-cache-1 --actor codex --category environment --reason "Restored the approved cache; no product source changed."
```

Đây là event ghi nhận của operator, gắn checkpoint, không phải kiểm chứng độc lập,
không cấp quyền hoặc resume. Key idempotent; dùng lại key với nội dung khác bị từ chối.
`observe` không xuất reason tự do. Không có note vẫn **không** được suy là không can thiệp.

## Scorecard ba trục (autopilot, 12/10/2026)

```powershell
python -m onecrew --state-root C:\path\to\OneCrew eval scorecard --task TASK-<ID> --replay-compare D:\OneCrewEvals\comparison.json --output D:\OneCrewEvals\scorecard
```

Ba trục tách riêng, không gộp thành một số:
1. `runtime_tests`: chỉ lấy từ file compare (known-case fixture), không phải hoàn thành task.
2. `task_completion`: phase, AC, gate, mục `not_run`/thiếu, lớp kết quả `autonomous_complete`
   (hoàn thành, plan do OneCrew lập, không can thiệp entry, runtime không đổi), `assisted_complete`,
   `correct_block`, `incomplete`, `unknown`.
3. `entry_dependencies`: can thiệp `control.intervention` theo actor/lệnh, `eval assistance`,
   nguồn gốc plan, đổi runtime, khởi động lại coordinator theo người khởi động, quyết định đã trả
   lời theo nguồn (`decisions_by_source`).

Mức hoàn thành và mức hỗ trợ chấm riêng; chỉ `complete` + `autonomous` là `autonomous_complete`.
Nguồn của mỗi câu trả lời (đợt 2, Codex review 12/10): `user` — người dùng tự trả lời (actor `user`);
`relayed` — entry gửi quyết định của người dùng (`--decided-by user`, nên trích tin nhắn gốc ở
`--reference`); `entry` — entry tự quyết theo ủy quyền (`--decided-by entry`); `unknown` — không
chứng minh được ai quyết (bản ghi cũ, hoặc người gửi không quy được actor). `entry`/`relayed` làm task
thành `assisted`; `unknown` làm mức hỗ trợ `unknown` nếu không có bằng chứng hỗ trợ khác. Câu trả lời
của chính người dùng không phải hỗ trợ.

Can thiệp được ghi tự động từ CLI/MCP (`ONECREW_ACTOR`), runtime ghi hash mã ở `runner.started`.

**Thay thế từ A2 (12/10):** nguồn quyết định v2 (`user/relayed/delegated/undelegated/observed/unknown`),
ủy quyền `delegation`, mức `full_loop` và lớp `autonomous_full_loop`/`assisted_full_loop`/`plan_complete`/
`tests_only`, bàn giao chỉ tính lần đầu và `eval trial`: xem `docs/autonomy-measurement.vi.md`.
Corpus v3 thêm hai lỗi review Codex (đỏ bằng assertion trên 356fb82) và các case autopilot; probe
có module mới ở mức module được chấm `capability_unavailable`, không phải tái hiện hành vi.

## Mở rộng năng lực bằng eval

Với mỗi thay đổi runtime/recipe/skill: pin before/after, chạy corpus này, review
diagnostic của regressions/gaps, rồi mới cân nhắc dùng. Không tự approve hoặc inject
lesson/skill. Thêm case mới phải tăng version hoặc giữ hash mới; rerun cả baseline
và candidate với harness mới, không so hai rubric khác nhau.

Để đo **khả năng tự hoàn thành** ở lượt sau, cần một dispatch nghiệm thu riêng:

- Task chưa dùng để phát triển, baseline/source/test oracle/environment được niêm phong;
  phân biệt known-case với held-out; không cho worker sửa oracle.
- Cùng model/grant/calls/deadline và cache chuẩn bị cho cả before/after; chạy nhiều
  lần để thấy dao động, không kết luận từ một lần thành công.
- Parent OneCrew tự thực thi toàn bộ gates. Entry chỉ quan sát; nếu phải can thiệp,
  ghi ngay actor, lý do, trước/sau checkpoint, commit/config thay đổi và calls đã dùng.
  Không reset failure/budget để đẹp số liệu; chuẩn bị môi trường trước dispatch ghi riêng.
- Test/assertion độc lập đủ cả skip count; APK hash/signer/source gắn đúng lượt;
  device serial/scenario/config pin và thiết bị rảnh; server/tài khoản đúng scope.
- Chấm riêng: hoàn thành kỹ thuật, nghiệm thu sản phẩm, hỗ trợ đã biết/chưa biết,
  recovery, false acceptance, calls/time, report và Windows receipt.
- Không restart task đang do Claude quản hoặc tự lấy quyền thiết bị từ lịch sử cũ.

Hiện chưa có held-out/live paired pilot phù hợp: EV07 còn Blocked. Báo cáo lượt
đầu sẽ chỉ kết luận những gì replay và ledger thực sự chứng minh.
