# OneCrew tự vận hành task tổng (delivery autopilot) — kế hoạch và nghiệm thu

Ngày 12/10/2026. Phạm vi: nâng runtime để OneCrew tự lập kế hoạch, thực thi, phục hồi lỗi
kỹ thuật trong quyền đã cấp và bàn giao, sau khi người dùng thống nhất yêu cầu/phạm vi/ngân
sách với entry. Không resume TASK-5f472cdf, không dùng A54, không push.

## Hiện trạng (khảo sát 356fb82)

Entry đang làm thay: soạn toàn bộ plan JSON (27 `REPLACE_*`: owned, test, red, SDK, signer,
serial, scenario+hash); chẩn đoán mọi blocker vì `Delivery.run` biến mọi lỗi thành `blocked`
kèm chuỗi tự do; gọi `delivery resume` sau mỗi blocker kể cả lỗi thoáng qua; xử lý node
`uncertain` (không có lệnh reconcile, kể cả khi chưa có side effect); khởi động lại coordinator
chết (không ai phát hiện); sửa môi trường; tự ghi can thiệp (`assistance=unknown`); viết báo
cáo; build/E2E bằng script riêng. Approval SOL chỉ là văn bản tự do nên không bao phủ đúng
plan/ngân sách/thiết bị được chạy.

## Thiết kế

1. **Envelope trong SOL** (`solution.envelope`, tùy chọn, version 1). Revision SOL là hash của
   payload nên duyệt SOL là duyệt envelope: `source_roots`, `write` (prefix được ghi),
   `acceptance` `{id,text,evidence[]}` (text phải nằm trong `acceptance` của SOL), `stages`
   (`build`, `apk_audit`, `device` với `serial`, `scenario: pinned|planned`, `valid_until`,
   `required`), `budget` `{max_calls,max_seconds,max_repairs}`, `worker`.
2. **Planner** (`delivery submit --solution SOL --revision R`, không cần plan): khám phá môi
   trường xác định (`delivery_env`: Flutter/Android SDK, build-tools, adb, java, package,
   applicationId, versionCode, activity, test sẵn có) → một lượt model chỉ đọc (Read/Glob/Grep,
   JSON schema) đề xuất change/owned/test/red/scenario → code biên dịch thành DAG mẫu và kiểm
   bằng `delivery_plan.validate` + `covers(envelope, plan)`. Lỗi validator được sửa cùng session
   tối đa 2 lần. Nhu cầu ngoài envelope → **một** câu hỏi gộp. Plan được niêm phong vào
   `delivery_roots` cùng `derived_from` (SOL, revision, envelope hash, discovery, attempt).
   Plan do entry viết vẫn dùng được (legacy) nhưng nếu SOL có envelope thì phải qua `covers`.
3. **Chính sách phục hồi** (`delivery_recovery`): mọi lỗi của coordinator/receipt/child được
   phân loại (`transient, interrupted, environment, product, review, side_effect_unknown,
   permission, budget, drift, runtime_bug`), có chữ ký (không chứa source hash) và progress
   fingerprint (source, môi trường, runtime, node đã đạt). Bảng hành động: thử lại có backoff
   (≤3/chữ ký), phát lại node an toàn bị ngắt (1/generation), reconcile chỉ đọc cho side effect
   thiết bị, sửa có giới hạn (`max_repairs`, ≤2/chữ ký), còn lại hỏi **một lần** qua request
   (phase `waiting`). Không hành động hai lần trên cùng (chữ ký, progress). Bộ đếm không reset
   khi resume/restart. Phục hồi tự động giữ phase không-actionable nên không bật cửa sổ.
4. **Ranh giới side effect**: node ghi `effect` ngay trước side effect đầu tiên. Lỗi trước đó
   không bao giờ thành `uncertain`. Build ghi vào capture mới nên phát lại an toàn; thiết bị bị
   ngắt được đối chiếu bằng `pm path`/`sha256sum` rồi phát lại kịch bản chỉ khi envelope khai
   `replay_safe`, ngược lại hỏi. Attempt model bị ngắt (`supervisor_interrupted`) được tiêu thụ
   và gọi lại một lần trong ngân sách.
5. **Tiếp tục theo câu trả lời**: khi người dùng trả lời request của root/child, runner (đang chờ
   không tốn call) tự áp dụng; nếu runner đã chết thì lệnh reply khởi động lại. Không cần entry
   gọi `resume`.
6. **Coordinator bền vững**: `runner.started` ghi hash runtime và người khởi động; keeper
   (`onecrew.keeper`, một tiến trình/state-root, không phải scheduler nhắc) khởi động lại runner
   root đã chết tối đa 3 lần/giờ có backoff, ghi `coordinator.restarted`; quá giới hạn thì
   blocker `runtime_bug` báo một lần. Không tự chạy lại sau reboot: keeper ghi
   `coordinator.lost_report` (`cause: reboot`) và hỏi một request `coordinator_lost` (một cửa sổ);
   exception khác trong `Delivery.run`/runner thành một request `runtime_bug` thay vì `blocked`
   không phân loại. Trả lời `retry` thì runtime tự chạy tiếp, không cần `resume`. Câu trả lời
   đã ghi mà coordinator chết trước khi áp dụng được áp dụng trước (`stop` thì hủy, báo
   `not_raised`), rồi mới hỏi lỗi mới; không còn câu hỏi pending thì runner chặn `blocked` như cũ.
7. **Can thiệp và báo cáo**: mọi lệnh CLI/MCP thay đổi task ghi `control.intervention`
   (actor từ `ONECREW_ACTOR`/nguồn MCP, mặc định `unknown`); đổi hash runtime giữa các
   checkpoint là can thiệp runtime. Báo cáo handover liệt kê từng AC `passed/failed/blocked/
   not_run` với receipt, mục thiếu/skip, lịch sử lỗi, phục hồi tự động, can thiệp.
8. **Eval**: corpus v3 thêm P1/P2 (đỏ bằng assertion trên 356fb82) và các case autopilot; probe
   phân biệt thiếu API (`capability_unavailable`) với lỗi hành vi; `observe` sửa crash
   `repairs`, chấm `apk_audit`, chấm notice khi chờ quyết định; `eval scorecard` chấm riêng 3 trục.

## Envelope v1

```json
{"version": 1, "source_roots": ["app"], "write": ["app/lib/", "app/test/"],
 "acceptance": [{"id": "AC1", "text": "<đúng nguyên văn một mục acceptance của SOL>", "evidence": ["regression", "red", "review"]},
                {"id": "AC2", "text": "...", "evidence": ["build", "apk_audit"]},
                {"id": "AC3", "text": "...", "evidence": ["device"]}],
 "stages": {"build": {"variant": "debug", "config_reference": null, "config_version": "none", "signer": "debug"},
            "apk_audit": {"require_16kb": false, "max_bytes": 250000000},
            "device": {"serial": "emulator-5554", "scenario": "planned", "scenario_ref": null, "scenario_sha256": null,
                       "private_reference": "D:/private/inputs.json", "private_version": "v1",
                       "valid_until": "2026-10-13T00:00:00+07:00", "replay_safe": true, "required": false}},
 "budget": {"max_calls": 40, "max_seconds": 7200, "max_repairs": 2},
 "worker": {"provider": "claude", "model": "sonnet"}}
```

`signer: "debug"` chỉ dùng cho build debug (chữ ký đọc từ debug keystore); release phải ghim
SHA-256. `scenario: planned` cho phép OneCrew soạn kịch bản trong DSL có kiểu; báo cáo ghi
`scenario_authored_by: onecrew`. `required: false` nghĩa là thiết bị không sẵn sàng thì AC ghi
`not_run` và kết quả là `verification: partial`, không bao giờ là `passed`.

Tuỳ chọn `device.emulator: {"avd": "<tên AVD>", "avd_home": "<thư mục tuyệt đối hoặc null>"}` (đợt 2):
OneCrew được tự boot (headless, đúng port của `serial`), khởi động lại một lần khi emulator kẹt,
và tắt emulator do chính nó boot sau khi stage thiết bị đạt. Chỉ hợp lệ với serial
`emulator-<port chẵn 5554–5682>`; thiết bị thật không bao giờ bị reboot/cấu hình lại.

## Thiết bị: môi trường và selector trên UI thật (đợt 2, `delivery_device_env.py`, `delivery_calibrate.py`)

- **Môi trường.** Trước khi cài APK và khi app mất focus giữa kịch bản, OneCrew đọc `dumpsys window/power`
  và chỉ dùng các hành động không đổi dữ liệu: đánh thức màn hình, `wm dismiss-keyguard` (khóa không mật
  khẩu), bấm **Wait** (`android:id/aerr_wait`) trên hộp thoại "not responding" của hệ thống — không bao giờ
  "Close app". Sau khi boot, System UI có thể treo lặp lại 1–2 phút vì tải boot (smoke 12/10): OneCrew trả lời
  Wait mỗi lần và chỉ coi là dùng được sau 3 lần đọc sạch liên tiếp (tối đa 240 s sau boot, 60–90 s nếu không boot).
  Còn kẹt thì: emulator có trong envelope → khởi động lại một lần; thiết bị khác → lỗi
  `environment` (thử lại có giới hạn rồi hỏi). Mọi hành động ghi vào `receipt.environment.actions`.
  adb server được khởi động ngoài lệnh có thu luồng (server sinh từ client bị thu sẽ giữ khóa file).
- **App phải còn sống (trial 5).** `am start` trả `Status: ok` cả khi app crash ngay. Mỗi lần mở app (đầu kịch bản,
  thao tác `restart`) OneCrew chờ app giữ focus và kiểm tiến trình còn chạy; khi app biến mất (cả lúc chờ UI hay khi
  bị từ chối nhập vì cửa sổ khác giữ focus) nó đọc crash buffer từ lúc mở app và chỉ giữ cấu trúc (loại, tín hiệu
  hoặc lớp exception, luồng, thư viện native) — không giữ thông điệp hay dòng log thô. Crash Java của app → lỗi
  sản phẩm (sửa code có giới hạn). Crash native trên emulator đã duyệt → khởi động lại emulator đó một lần rồi mở
  lại đúng bản đã cài và kiểm hash; nếu crash xảy ra giữa kịch bản thì lần thử lại kế tiếp khởi động lại emulator
  trước khi cài. Trên thiết bị thật không khởi động lại; hộp thoại crash của chính app không bị coi là System UI treo.
- **Selector theo tầng, có bằng chứng.** Một selector phải trúng đúng một node; tầng đầu tiên có kết quả
  quyết định: `exact` (thuộc tính đúng như viết; `text` cũng trúng nhãn Flutter ở `content-desc`) →
  `label` (bằng một trong text/content-desc/hint) → `label_part` (bằng một phần của nhãn gộp, tách theo
  xuống dòng hoặc `, `) → `label_casefold`. Tầng dùng được ghi vào từng bước (`selector_tier`). Thêm khoá
  `hint` và thao tác `assert_absent` (không node nào của app nhắc tới nhãn, kể cả chuỗi con không phân biệt
  hoa thường). `wait_for` hết giờ là lỗi selector (`reason: timeout`), không còn bị đọc nhầm thành hết giờ
  toàn kịch bản.
- **Bằng chứng khi trượt.** Bước có selector không trúng lưu ảnh chụp đã làm sạch các node của app
  (`ui-<bước>.json`, giá trị nhập riêng tư bị che) và `receipt.failure_kind = selector`.
- **Hiệu chỉnh (chỉ kịch bản OneCrew tự lập, rerun an toàn).** Lớp `scenario_selector` → hành động
  `calibrate` (tối đa 2 lần/node). Code quyết định trước: assertion mà nhãn mong đợi không có ở đâu trên
  màn hình là **lỗi sản phẩm** → sửa code có giới hạn (không gọi model, không đổi kịch bản). Ngược lại,
  một phiên model chỉ đọc đề xuất selector mới; validator chỉ chấp nhận khi giữ nguyên id/thao tác/thứ
  tự/đối số khác, không đổi bước đã đạt, assertion giữ nguyên nhãn mong đợi, và selector mới của bước
  trượt trúng đúng một node trong ảnh chụp. Bản kịch bản mới có hash, `revision`, bước đã đổi và nguồn
  gốc trong lịch sử; stage thiết bị chạy lại từ đầu. Kịch bản người dùng ghim không bao giờ bị hiệu chỉnh.

## Bảng phục hồi (policy v1, `onecrew/delivery_recovery.py`)

| Lớp | Hành động tự động | Giới hạn/chữ ký | Sau giới hạn |
|---|---|---|---|
| transient (ADB, deadline lệnh, daemon) | thử lại, backoff 15/60/180 s | 3 | hỏi |
| interrupted (coordinator chết, attempt bị ngắt) | phát lại node an toàn; bỏ attempt đã settle | 1 | hỏi |
| environment (SDK, cache, thiết bị, đường dẫn) | thử lại đọc-lại môi trường | 2 | hỏi (thiết bị optional → not_run) |
| product / review | sửa trong change đã duyệt; child lỗi → generation mới | 2 và `max_repairs` | hỏi |
| side_effect_unknown | reconcile chỉ đọc (`pm path`, `sha256sum`, intent) | 1 | hỏi |
| product chỉ ở bằng chứng red (mọi test đạt, red không đỏ do hành vi — trial 6) | sửa **chỉ test**: task con có phạm vi `tests`, mã sản phẩm phải giữ nguyên byte, phản hồi nêu rõ pattern và lý do | 2 và `max_repairs` | hỏi |
| scenario_selector (selector kịch bản OneCrew lập không trúng UI thật) | hiệu chỉnh từ ảnh chụp UI; nhãn mong đợi vắng → product | 2 và ≤2 bản/node | hỏi |
| decision_pending (CREQ) | chờ, không tạo request mới | — | — |
| permission, budget, drift, artifact, runtime_bug, unknown | — | 0 | hỏi |

Cùng chữ ký trên cùng progress fingerprint (source, môi trường, runtime, node đã đạt,
generation) không được sửa/phát lại lần hai. Chờ attempt đang chạy settle không tính là lần
thử. Trả lời `retry` cho thêm đúng một lượt tự động; `stop` hủy và giữ bằng chứng.

## Tiêu chí nghiệm thu

| ID | Tiêu chí | Bằng chứng |
|---|---|---|
| AP01 | Từ SOL có envelope, submit không kèm plan → OneCrew tự khám phá, lập, kiểm và niêm phong plan trong envelope; entry không viết node/recipe/test/đường dẫn | test fixture + trial thật |
| AP02 | SOL có envelope: plan (tự lập hoặc entry viết), quyền và ngân sách phải nằm trong envelope | test |
| AP03 | Preflight môi trường trước mọi lượt model; lỗi môi trường nêu đúng thứ thiếu | test |
| AP04 | Mọi lỗi có bản ghi phân loại; áp dụng đúng bảng hành động | test theo lớp |
| AP05 | Không lặp cùng lỗi khi không có tiến triển; bộ đếm sống qua resume/restart | test |
| AP06 | Lỗi trước side effect không thành `uncertain`; build ngắt phát lại; thiết bị đối chiếu chỉ đọc | test |
| AP07 | Giết coordinator giữa node rồi khởi động lại: node đã đạt không chạy lại, side effect ≤1 lần/generation, giữ ngân sách/lịch sử/source; keeper tự khởi động lại | test tiến trình + trial |
| AP08 | Trả lời request → runtime tự tiếp tục, không cần `delivery resume` | test |
| AP09 | Chỉ hoàn thành khi mọi AC có receipt gắn source; báo cáo nêu thiếu/skip/not_run | test |
| AP10 | Một cửa sổ Windows cho mỗi kết quả cuối hoặc mỗi đợt chờ quyết định; phục hồi tự động không bật cửa sổ | test |
| AP11 | Can thiệp CLI/MCP và đổi runtime được ghi tự động, xuất hiện trong báo cáo/observe | test |
| AP12 | Hai lỗi review (IME, pubspec `path:`) đỏ bằng hành vi trên 356fb82, xanh sau sửa | eval |
| AP13 | Replay trước (356fb82) – sau (bản cuối) cùng harness, repeat 2, giữ thất bại | eval |
| AP14 | Giao một mục tiêu cấp công việc trên project thử, không kèm kế hoạch; chấm 3 trục, gồm kill/restart coordinator | trial |
| AP15 | Quyết định được quy nguồn: người dùng tự trả lời / entry chuyển lời người dùng / entry tự quyết; thiếu bằng chứng → unknown; entry tự quyết hoặc chuyển lời → assisted | test + eval |
| AP16 | OneCrew tự kiểm tra và phục hồi thiết bị trong quyền (ANR → Wait, emulator trong envelope → boot/khởi động lại), không reboot thiết bị thật | test + trial |
| AP17 | Selector được xác minh trên UI thật (tầng ghi lại), trượt → ảnh chụp + hiệu chỉnh có giới hạn không làm yếu assertion | test + trial |

Không dùng số test xanh thay cho bằng chứng tự hoàn thành (AP14 chấm riêng).
