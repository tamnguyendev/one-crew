# OneCrew incremental runtime — SPEC-005

Đã hoàn thành lượt chạy từ thư mục trống `cv-guard-onecrew-v4`: OneCrew tự lập plan, tạo 10 file, test, sửa riêng router, review và commit `ad3c7481ad837445e1c66cb9ad1b67f255cdb877`. Run `RUN-20261008-232057-1d06d8` đạt `ready_for_review`; khách hàng chưa nghiệm thu. Không lấy source từ các app CV trước.

Demo local: http://127.0.0.1:3201/ (phải có process preview đang chạy). SPEC-005 IA01–IA05: 5/5 Complete trong phạm vi profile CV/local/Codex. Không phải toàn bộ roadmap OneCrew, JEV routing hay chứng nhận chống bot ngoài production.

## Cách chạy

```powershell
$env:ONECREW_PLAYWRIGHT_MODULE = 'C:\Users\NUC\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\node_modules\playwright'
.\onecrew.ps1 task run --autonomous --brief examples\cv-autonomous-brief.vi.md --output D:\TamNT\Workspace\9.VMAgent\cv-guard-next --max-seconds 1800 --max-calls 32 --max-repairs 4 --step-seconds 120
```

Output phải chưa tồn tại. Đường dẫn Playwright trên là runtime bundled của máy này; máy khác dùng module Playwright của mình và browser đã cài (`ONECREW_BROWSER_CHANNEL`, mặc định msedge trên Windows). Preflight xác nhận sandbox và browser trước model calls. Profile cũ chỉ còn qua `--profile cv-upload-legacy` để đối chiếu; mặc định mới là incremental.

Controller giữ nguyên API/nghiệm thu SPEC-004 và chia implementation thành 10 file có interface và dependency rõ ràng. Planner chọn ID/thứ tự hợp lệ trên graph; không được tự thêm tính năng. Mỗi lượt worker chỉ trả một file raw text, tối đa 24KB/400 dòng, không trả JSON chứa cả backend. Host kiểm cú pháp và lưu ZIP/manifest từng file; checkpoint chưa hoàn chỉnh không được xem là sản phẩm đã nghiệm thu.

Policy v4: planner, HTML/CSS/README dùng gpt-6-luna/medium. Module bảo mật, storage, router, client flow, mọi repair/triage và retry dùng gpt-6.1-sol/medium. Reviewer độc lập dùng gpt-6.1-sol/medium. Đây là policy thử nghiệm; model nhỏ không tự chứng nhận code của nó. HTTP + browser gate và reviewer độc lập vẫn bắt buộc. Chưa benchmark tối ưu chi phí; JEV chưa được cấp quyền dispatch.

Lỗi provider/JSON/syntax chỉ retry một lần cho unit đó; không chạy lại các file đã xong. Retry và repair dùng chung calls/deadline. Cancel, budget exhaustion, runtime/contract tamper không retry. Usage bị ngắt ghi unknown ngay. Đây là recovery trong một controller đang sống; chưa phải resume sau crash hoặc cân bằng nhiều máy.

Cycle 3 từ chối repair không đổi source trước checkpoint, kể cả log có đường dẫn/port thay đổi. Regression test kiểm no-op và routing theo task/retry. Windows DATA_DIR phải dùng filesystem path; contract làm rõ global quota cộng dồn và Secure theo APP_ORIGIN.

Gate fail → triage chỉ định tối đa 4 file → worker sửa từng file → chạy lại gate toàn hệ thống → review. Không đổi gate để xanh. Gate browser thực hiện thao tác form thật, kiểm mobile không tràn, preview/edit giữ file, gửi qua API thật và receipt khớp; có screenshots. External Turnstile/AV/edge không được coi đã kiểm chứng.

## Coverage

Proposal: `specs/SPEC-005-incremental-autonomy.md`. Baseline `fab38d2`.

| ID | Implementation | Verification | Status |
|---|---|---|---|
| IA01 | incremental_profile.py, plan validator | DAG/ownership/dependency tests | Complete |
| IA02 | incremental.py produce/accept_file; runtime raw output support | 10 checkpoint fixture; Node syntax reject/retry; size cap; raw CLI adapter test | Complete |
| IA03 | produce bounded retry + shared Runner controls | Timeout only retries failed file, permanent failure preserves checkpoint, cancel not retried | Complete |
| IA04 | repair triage and file workers; sealed HTTP/browser gates | Targeted repair fixture + live repair-1:server.mjs; 19 gates and independent review passed | Complete |
| IA05 | Live from-empty run, preview, manifest audit | RUN-20261008-232057-1d06d8; all 10 files match model outputs; preview HTTP200 | Complete |

Full suite after controller cycle 3: 69 tests passed (57 prior +12 incremental). Browser launch preflight passed with installed Edge. Simulated lifecycle tests are not live product delivery evidence. Local delivery evidence follows; runtime commit is recorded below.

## Các lượt kiểm chứng

- `RUN-20261008-225223-b59fc6`: từ thư mục trống `cv-guard-fresh`, 10 file do workers tạo; 24 model calls, 3 vòng sửa, 467.48 giây. HTTP/browser gate cũ đạt 13 checks; reviewer phát hiện 4 lỗi mandatory. Run dừng vì hết repair budget, không có delivery. Usage: 417,080 input / 22,380 output token, trong đó 120,576 cached input; không suy ra USD.
- Phép kiểm không gọi model `RUN-20261008-230504-b8c34a` chạy gate mới trên bản sao các artifact cũ trong thư mục regression riêng. Tái hiện 5 check đỏ ứng với 4 findings: SSR banner, private cache, body cap, nonce quota, global anonymous quota. Đây là regression fixture từ output cũ, không là nguồn của sản phẩm mới.
- `RUN-20261008-230744-48f5d2`: từ thư mục trống `cv-guard-delivery`, không copy code cũ; budget 1,800 giây / 32 calls / 4 repair, 120 giây/call. Dừng sau 372.57 giây, 21 calls / 4 repair; 17 gate checks đạt nhưng reviewer còn 2 lỗi mandatory (global quota không cộng dồn, cookie Secure phụ thuộc proxy). Không delivery. Usage 303,250 input / 20,977 output, cached input 53,760. Hai repair trả code giống cũ đã phí budget; không coi đó là tiến triển.

- `RUN-20261008-231956-b72c57`: regression không gọi model, tái hiện đúng 2 findings mới trên bản sao output thất bại; 17 checks cũ vẫn đạt, 2 checks mới đỏ. Không thay dữ liệu run gốc.
- `RUN-20261008-232057-1d06d8`: policy v4, source mới `cv-guard-onecrew-v4`, không copy artifact cũ. Cùng budget 1,800 giây / 32 calls / 4 repairs, 120 giây/call. Thành công sau 585.21 giây (9 phút 45 giây), 14 calls, 1 repair, 11 checkpoints; không có provider retry. Lần gate đầu 18/19 đạt, oversize upload bị đóng kết nối sớm. Triage tự chọn server.mjs, worker tự sửa, lần gate sau 19/19 đạt và independent review không có findings. Controller tự commit sản phẩm `ad3c7481ad837445e1c66cb9ad1b67f255cdb877`.
  Usage run thành công: 178,939 input / 19,959 output, cached input 31,488. Tổng 3 live runs SPEC-005: 59 calls, 899,269 input / 63,316 output, cached input 205,824; không có usage unknown. Cached input là phần nằm trong input, không cộng thêm. Không quy đổi USD hoặc gộp token của cuộc hội thoại điều phối này; các lượt SPEC-004 cũ có báo cáo riêng. Đây là chi phí sửa và kiểm chứng, chưa có benchmark tiết kiệm.

Cycle 2 làm rõ vai trò worker trả text; host giữ quyền ghi. Dùng `model_instructions_file` theo [Codex configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference), vẫn read-only và tắt tools. Không bỏ sandbox để chữa lỗi worker từ chối ghi. Candidate sai syntax không còn ghi đè file đang hợp lệ; test kiểm giữ nguyên file/checkpoint cũ. Gate chỉ được bổ sung sau khi lượt cũ kết thúc; lịch sử gate hash được giữ nguyên.

## Bằng chứng bàn giao

Trong `.onecrew/runs/RUN-20261008-232057-1d06d8/`:

- `state.json`, `grant.json`, `events.jsonl`: budget/model/timing/checkpoints; 4 calls dùng luna và 10 calls dùng sol, tất cả effort medium.
- `gate-00.json`, `repair-plan-01.json`, `gate-01.json`: failure thật → sửa đúng một file → 19 kiểm tra đạt; gate/runtime hashes không đổi trong run.
- `review-01.json`: findings rỗng; external services vẫn chưa kiểm chứng.
- `delivery.json`, `authorship-verification.json`: hash tất cả 10 file khớp chính xác output của workers. Host chỉ tạo package.json/.gitignore/.gitattributes và orchestration/gates; assistant không sửa file sản phẩm.
- `browser-01/ui-desktop.png`, `ui-mobile.png`, `ui-preview.png`, `ui-receipt.png`: UI thật, đã xem desktop/mobile, không tràn layout.
- `preview.json`: mở bằng OneCrew CLI, HTTP `/api/config` trả mode demo; Git sản phẩm sạch sau preview.

Logs chứa task data nên nằm ngoài Git; báo cáo này giữ kết quả tổng hợp. Source sản phẩm: `D:\TamNT\Workspace\9.VMAgent\cv-guard-onecrew-v4`.

Giới hạn: Windows local preview; chưa resume sau crash, đa repo, Claude/Kiro worker hay JEV semantic dispatch. Turnstile/domain/edge, AV/retention, benchmark hiệu quả chặn bot chưa triển khai/kiểm chứng. Quyền nghiệm thu thuộc khách hàng; `ready_for_review` không tự approve.

## Xem và dừng từng phần khi đang chạy

```powershell
.\onecrew.ps1 task list
.\onecrew.ps1 task status RUN-YYYYMMDD-HHMMSS-xxxxxx
.\onecrew.ps1 task outputs RUN-YYYYMMDD-HHMMSS-xxxxxx
.\onecrew.ps1 task cancel RUN-YYYYMMDD-HHMMSS-xxxxxx
```

`status` có phase, calls, repairs, deadline, task states và usage; `outputs` trả các checkpoint kèm archive/hash để xem từng phần trước khi toàn task xong. Các lệnh này không gọi model. Checkpoint chỉ là phần đã tạo, không đồng nghĩa gate/reviewer đã duyệt. `cancel` dừng cây process, không xóa artifact/lịch sử. Không hỗ trợ resume sau crash ở phiên bản này.

## Xem sản phẩm được bàn giao

```powershell
.\onecrew.ps1 task preview RUN-YYYYMMDD-HHMMSS-xxxxxx --demo --port 3201
```

Preview không gọi model, chỉ nhận `ready_for_review` và manifest còn đúng hash, chạy sandbox Windows trên loopback. Đây là demo với dữ liệu giả; dữ liệu preview riêng dưới `.data-preview` và không làm thay đổi source đã nghiệm thu. Dừng process bằng Ctrl+C. Manifest thay đổi thì từ chối mở để yêu cầu verify lại.

## Commit của chu kỳ

- OneCrew implementation và coverage IA01–IA05: `bf2e673cad3116fcd89891decc819363153a2f3c` — 69 tests passed; live run và preview evidence ở trên.
- Source sản phẩm do OneCrew tự commit: `ad3c7481ad837445e1c66cb9ad1b67f255cdb877` trong repo `cv-guard-onecrew-v4`.
- Đã đối chiếu lại toàn bộ SPEC-005: IA01–IA05 Complete; các hạn chế ngoài phạm vi giữ rõ. Không thay runtime/gate trong live run. Các thay đổi tài liệu có sẵn của người dùng giữ ngoài commit; không push.
