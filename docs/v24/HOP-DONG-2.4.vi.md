# OneCrew 2.4 — hợp đồng triển khai, truy vết và kiểm chứng

Người lập: Claude (Fable 5.1, đầu mối; agent Opus/Sonnet theo việc), 01/11/2026, theo chỉ thị người dùng ngày 01/11 ("Tiếp quản và hoàn thành toàn bộ feature đã chốt của OneCrew 2.4 theo roadmap chung: 2.4-S1, S2, A, B, C") dán trong phiên Claude Code. Đây là hồ sơ thực thi, không phải roadmap: phạm vi lấy từ `outputs/onecrew-as-qc/ROADMAP.vi.md` §0.2 và §0.8 (bản 31/10 của Codex), thiết kế §2.1, §2.2, §2.4a, §2.4b, §2.4e, §2.9, §3, §7, và `ROADMAP-CLAUDE-HANDOFF.vi.md` (các mục 2.4-S1/S2, mốc mới, bước 0 31/10). Không sửa roadmap, không cộng vào 92 task beta, không đổi DoD của chúng; task 2.4 có ID riêng `T24-*`.

## 1. Baseline và cách ly

| Mục | Giá trị |
|---|---|
| Baseline code | `fb3333b` (2.3.0.dev10, tag `v2.3.0.dev10`); nhánh 2.4 tách từ commit hồ sơ `fe0a044` (code giống từng byte `fb3333b`) |
| Worktree / nhánh | `D:\TamNT\Workspace\11.OneCrew\wf-v24`, `claude/onecrew-2.4` (local; không push/tag theo nhiệm vụ này — §8) |
| 2.2 và 2.3 giữ nguyên | checkout `wf-codex` (`1753f77`), `wf-v23` (`fe0a044`); gói `D:\OneCrewRuns\wf-handover-34eb7c4-hs2` (beta 2.2), `D:\OneCrewRuns\v23\pkg\onecrew-2.3.0.dev10-beta` (wheel `8ab065c3…`); tag `v2.3.0.dev8/dev9/dev10` và receipt trong `D:\OneCrewRuns\v23` |
| Thư mục chạy 2.4 | `D:\OneCrewRuns\v24\` (venv `venv` Python 3.13.15, `state` sổ thử, `projects` project bản sao, `tmp`, `pkg`, `logs`, `design`); công cụ phụ `D:\OneCrewRuns\wf-dev-tools\v24\` |
| Cấu hình người dùng | mọi lệnh `init`/hook/test chạy với `LOCALAPPDATA`, `APPDATA`, `TEMP` riêng cho process thử; không đổi biến toàn máy, không đụng `%LOCALAPPDATA%\OneCrew\hook-projects.json` thật (SHA256 `884335df…` lúc bắt đầu) |
| Runtime đang dùng | không nâng; mọi kiểm cài/nâng/quay về/tiếp tục chạy trên venv và sổ bản sao trong `D:\OneCrewRuns\v24` |
| Version | prerelease `2.4.0.devN`: mỗi gói alpha của một mốc tăng N; beta 2.4 chỉ khi đủ S1/S2/A/B/C (§8) |
| v1 tham chiếu | `e76c703` (`D:\TamNT\Workspace\11.OneCrew\onecrew`): đối chiếu lịch sử; code v1 cùng tên trong `wf-v24/onecrew/*.py` được đọc thật trước khi tái dùng |

Tài nguyên đang dùng lúc bắt đầu (01/11 ~02:15, chỉ quan sát): các phiên Claude/Codex khác, KiroCrew, host OneCrew thật. Không dừng, không đọc/ghi sổ `state-v2-real`.

Quan sát 01/11 08:11: sổ đăng ký hook thật `%LOCALAPPDATA%\OneCrew\hook-projects.json` đổi lúc 08:01 (842 byte, SHA256 `23ec9033…`): thêm hai mục `d:\onecrewruns\copies\signsdk-dev10-test` và `…\signsdk-dev10-upgrade` trỏ tới `D:\OneCrewRuns\states\…` — do một phiên khác (thử gói dev10 trên bản sao signsdk, thư mục tạo 07:59–08:04), không phải lượt 2.4 (mọi lượt chạy 2.4 dùng `LOCALAPPDATA` riêng `D:\OneCrewRuns\v24\tmp-int\lad`). Không đụng, không khôi phục; hash này là mốc so sánh cho các lượt sau của 2.4.

### 1.1 Tồn đọng 2.3 đã biết, phân loại cho 2.4

| Tồn đọng | Phân loại | Xử lý trong 2.4 |
|---|---|---|
| Test hạn 2 giây `tests.test_wf_metered_verifier…root_deadline…` nhạy tải máy (dev9 và dev10 cùng hỏng khi máy chậm) | ảnh hưởng trực tiếp bộ kiểm 2.4 (gate chạy module này) | ghi nhận; chỉ sửa khi bộ kiểm 2.4 cần, theo U1 hẹp mà người dùng cho phép ngày 01/11 (hash, lý do, phản chứng), không nới guard runtime |
| 23 khoảng trống nghiệm thu/pilot/provider của 2.2 | điều kiện ngoài (E) | giữ trạng thái; không là lý do hoãn 2.4 |
| B4/B5: hai test 2.2 đã khóa gọi Claude thật / ghi sổ hook thật khi không cô lập | độc lập | giữ trạng thái; mọi lượt chạy 2.4 cô lập `LOCALAPPDATA`; không chạy `tests.test_v2_reviewer` |
| F4 (id tri thức trùng giữa project), giới hạn P1 POSIX, khe junction init | độc lập, đã ghi ở giới hạn dev10 | không backport; B đọc tri thức qua cùng bộ đọc nên kế thừa giới hạn này, ghi lại ở §9 |
| Test ghim version `tests/test_g1_core.py` chỉ nhận `2.3.0.devN` | dependency trực tiếp (gói 2.4 cần version `2.4.0.devN`) | U1 hẹp trên nhánh 2.4 cho đúng một dòng regex, cùng cơ chế `wfkit/u1` như `U1-20261029-V23-PIN-1` |

## 2. Chiến lược alpha/beta và điều kiện kiểm (chốt trước code)

- **Alpha từng mốc:** mỗi mốc S1, S2, A, B, C có gói thử riêng `2.4.0.devN` dựng bằng `docs/v24/tools/build_milestone.py` (kế thừa 2.3), kiểm từ artifact trong venv/cwd ngoài checkout (bộ kiểm V1–V16 của 2.3 giữ làm hồi quy, thêm bước V17+ của mốc). Alpha nêu giới hạn rõ, không tuyên bố hotfix tự động, không tuyên bố model thật hiểu context.
- **Trước mỗi nhóm thay đổi:** ca lỗi/phản chứng trước (test đỏ trên baseline `fb3333b` khi phản chứng là lỗi hiện có), rồi code, rồi kiểm lại ca đó, rồi module bị ảnh hưởng (danh sách ở §4 từng mốc), rồi tích hợp cần thiết.
- **Không full gate nhiều giờ cho mỗi thay đổi nhỏ.** Gate snapshot 2.2 đầy đủ chạy đúng một lần trên snapshot beta 2.4 (và lại chỉ khi snapshot đổi). Alpha dùng: hồi quy 2.3 (`tests/test_v23_*`, `tests/test_v24_*`) + module 2.2 chạm vùng sửa + kiểm gói.
- **Kế thừa bằng chứng:** chỉ khi commit code, wheel hash, harness và điều kiện giống hệt và được ghi; không chép PASS snapshot cũ cho snapshot mới.
- **Fixture, provider thật, giả định:** worker trong mọi kiểm là `claude` giả (`tests/v23_fake_claude.py`); không gọi provider trả phí; mục cần model thật ghi là chưa chứng minh.
- **Beta 2.4:** chỉ khi cả năm mốc có code tích hợp, test/phản chứng đạt, gói dùng được, hồi quy đủ, gate 2.2 đạt mọi check thực thi trên snapshot cuối.

## 3. Phân loại tái sử dụng (trước code)

Nguồn: ba bản đồ đọc code trước khi viết, trên `fe0a044` (code `fb3333b`): `D:\OneCrewRuns\v24\design\map-s.md`, `map-ab.md`, `map-c.md` (ghi xong 08:08–08:09); cột "Phần thêm" đối chiếu với code cuối `7767982`. Loại: **A** thiếu code, **B** thiếu đường nối, **C** thiếu bằng chứng, **E** điều kiện ngoài; "có sẵn" = dùng nguyên, không sửa. Không thêm bảng, kho, scheduler hay engine thứ hai. Module mới nằm trong `onecrew/v2/` (trừ `onecrew/paging.py` có sẵn) và vào `py-modules` của `pyproject.toml`: `paging`, `support`, `support_cli`, `support_spool`, `diagnostics`, `hotfix`, `source_tools`, `working_context`, `execution_mode`.

### 3.1 S1, S2 (báo lỗi, bản vá)

| Năng lực | Có sẵn trước 2.4 (map-s) | Loại | Phần thêm |
|---|---|---|---|
| Báo lỗi một lần, một mã | `Ledger.create_request` ledger.py:333, `key_field` ledger.py:63; `feedback.py:8` là v1, ngoài wheel, chỉ mượn ngữ nghĩa idempotent | A | `support.report`; một task neo mỗi project, khóa `support:records` (support.py:26); sự kiện `support.feedback` lớp A |
| Tự gắn plan/attempt/phiên bản | `plans.derive`, bảng `attempts`, `importlib.metadata`, `interventions.runtime_revision` interventions.py:101 | B | `_derive`, probe runtime; phiên bản của lần chạy cũ không có trong sổ 2.3 nên ghi `unknown` (map-s §6) |
| Hồ sơ chẩn đoán local | sổ, `attempts/<id>/stdout|stderr.txt`, blob receipt, `violations.jsonl`, `install.doctor` install.py:522, `display_core.safe` display_core.py:9 (bộ lọc hiển thị) | A | `diagnostics.py`: allow-list từ refs, manifest từng nguồn, lọc từng dòng, trần 256 KB / 200 sự kiện / 8 MB; `install.doctor_facts()` (`1407528`) |
| Lưu tạm khi sổ hay runtime hỏng | mẫu spool của `hook_cli.record` hook_cli.py:83; `durable_write` snapshots.py:133 | A | `support_spool.py` chỉ stdlib; `support import-spool` |
| Phân loại, nối việc sửa | `recovery_core.POLICY` (`runtime_bug` chỉ v1 dùng), `findings.record_review` | A | sự kiện `support.classified`, `support.linked`; không sửa `POLICY` |
| Trạng thái tách cột, thông báo | `notification_core.pull` :24, `exceptions.message` :195, outbox desktop | B | `support.status`; `support.message` ghép sau `exceptions.message` trong `notification_cli` |
| Định danh, cài, chuyển, quay lui bản vá | `compat_scan.scan` (chỉ reader `d3120c6`), `wfkit/rollback_cli`, `upgrade_drill` (ngoài wheel, import `tests.*`, luôn `swapped: false`), `package_check` | A | `hotfix.py`: target, artifact, install, recheck, resume, rollback, learn, cleanup; phần nhỏ cần dùng viết lại trong `onecrew/v2`, không import `wfkit`/`tests` |
| Quyền cài | `authority.decide/enforce` :359/:421, `granted_actions` | B | handler `_support_install` (authority.py): chỉ quyền `support_install:<đích>` của plan sửa |
| Tiếp tục việc cũ | `engine.resume_held` :961, `reconcile_orphans` :471, `Control.reserve/finish` | có sẵn | `support resume` chỉ đi qua đường này |
| Bằng chứng gói | `build_milestone.py`, `verify_milestone.py` của 2.3 (V1–V16) | C | `docs/v24/tools/*`: bước V17–V19 (S1), V20–V22 (S2) |
| Người dùng thật, model thật, nghiệm thu | — | E | không làm trong lượt này (§8) |

### 3.2 A (worker tự đọc nguồn)

| Năng lực | Có sẵn (map-ab) | Loại | Phần thêm |
|---|---|---|---|
| Quyền đọc của root | không có: `read` của node không được kiểm với quyền nào của root (map-ab §2 mục 7) | A | khóa tùy chọn `authority.read` (authority.py `READ`); không khai thì `scope.owned` ∪ `understanding.target.paths`, không bao giờ cả project |
| Đọc trên nguồn đã ghim | `discovery` (đọc cây sống, cursor số nguyên), `command.artifact_sha` :44, `worker_tools` (v1, bị cấm vào wheel) | A | `source_tools.py`: `ls-tree`/`cat-file` trên cây ghim một lần cho mỗi chuỗi |
| Trang kết quả, không cắt JSON | `paging.py` đủ nhưng chưa vào wheel (hợp đồng 2.3 §2 ghi "đưa vào wheel"; map-ab dòng 13: chưa làm) | B | `onecrew.paging` vào wheel, không sửa |
| Vòng xin → trả | vòng continuation của engine (`node.resumed`); `REPORT_SCHEMA` không có `continuation` | B | `source.requests` đi kèm `continuation`; node báo cáo cũng tiếp tục được |
| Trần theo provider | `owned._cap` (v1); Kiro 16 000 trong adapter, executor chỉ tính 80 000 | B | trần Kiro 15 000 − khung − schema |
| Đếm lượt, chống lặp qua restart | `progress_core`; trần task con đặt lại mỗi generation | A | `max_rounds` đếm trên mọi receipt của node |
| Model thật dùng đúng giao thức | — | E | chưa chứng minh |

### 3.3 B (working context theo consumer)

| Năng lực | Có sẵn (map-ab) | Loại | Phần thêm |
|---|---|---|---|
| Chọn, giao, xét nguồn đổi, thu hồi ở lần đọc mới | `knowledge.py` 2.3 (`_collect`, `_decide`, `for_native`) | có sẵn (hồi quy) | — |
| Định danh gói đã giao theo attempt | `receipt.knowledge`, intent `dispatching` của executor có quản lý | B | sự kiện `knowledge.delivered` lớp A, một lần mỗi attempt |
| Consumer bị ảnh hưởng | không có | A | `knowledge.affected_consumers`; `onecrew wiki consumers --plan` (chỉ đọc) |
| Delta ở điểm an toàn | chọn lại toàn bộ mỗi attempt | A | `delta` trong gói (`withdrawn`, `changed`, `added_mandatory`) |
| Kiểm lại trước công bố hay kiểm | không có (`rebuild_context` công bố không kiểm lại, map-ab §4) | A | `working_context.decide` trong `engine.step`, lúc nhận candidate, `engine.verify` |
| Giữ phiên model | không adapter nào | E | không thuộc mốc B |

### 3.4 C (bước 0, cách chạy)

| Năng lực | Có sẵn (map-c) | Loại | Phần thêm |
|---|---|---|---|
| Thẻ bước 0 | `step0.evaluate` :290, `proposal.check` :260, `survey` | B | ba trường tùy chọn trên đề xuất W47, `step0.card`, `plan step0 show`; `contract.FIELDS` giữ nguyên |
| Trần điều tra cho cả plan | trần từng khảo sát; `DEFAULT_SPEC` đọc `.` | A | `survey.open_in` kiểm tổng trần, từ chối `.` |
| Chọn cách chạy có lý do | `engine._ready`, `dependency_core.ready_batch` (chỉ so file ghi; `resources` không ai đọc) | A | `execution_mode.choose`, capability `execution-mode`, sự kiện `workflow.mode` lớp B |
| Kiểm không cần model, chạy cạnh worker | verifier `command` | B | chế độ `tools`, cờ `--checks` |
| Số đo | sự kiện, receipt sẵn có | B | `engine measure` (chỉ đọc) |
| Giữ phiên model | mọi adapter chạy không phiên (`--no-session-persistence`) | E | luôn `reuse: false` |

## 4. Thiết kế đã chọn (đã triển khai; chi tiết trong docstring và `docs/v24/HUONG-DAN-*.vi.md`)

- **S1:** báo cáo là sự kiện trên task neo `support:records` của project (support.py:26), tạo qua `task_intake.submit`; `Control.configure` từ chối task này nên nó không bao giờ chạy (`b6b300c`, test p3a). Root đã đóng không bị ghi. Khóa mặc định khi không có `--key` lấy từ chữ, kết quả mong đợi, refs, phiên bản runtime và sha ảnh: map đề xuất mã mới mỗi lần; review S1-R08 ghi đây là việc chủ sở hữu quyết; bản cài chọn khóa theo nội dung (`b6b300c`), rồi sửa theo S2-R05 để tái phát sau bản vá và khác phiên bản thành báo cáo mới (`58c740d`) — xem §8. Bộ lọc bí mật rộng hơn `display_core.safe`, thay đúng phần bí mật của dòng (S1-R01). Router vào spool trước `route()`.
- **S2:** `hotfix.py`. Quyền cài và quyền quay lui chỉ từ plan sửa đã duyệt, còn mở, ghi `support_install:<đích>`; ngân sách được kiểm, không bị trừ (limits-s2.md). Sau review S2-R01, `support artifact` kiểm nội dung wheel so với commit đã kiểm (từng file, RECORD, METADATA), không chỉ sha; không build lại wheel. Venv mới `<venv>-<version>-<sha8>` cạnh venv cũ; một claim mỗi đích, hết hạn 15 phút (hotfix.py:59 `CLAIM_SECONDS = 900`); `support rollback` là lệnh của chủ (S2-R03); "đã cài, đã kiểm tại đích" tính theo hook đang chạy (S2-R04). Liệt kê process chỉ có trên Windows; nơi khác là `unknown` nên việc chuyển bị từ chối.
- **A:** một module `source_tools.py`; cây ghim = `artifact_sha(verified=True)` (có file chưa commit, từ chối hard link và junction) — map để ngỏ giữa cây tracked và cây làm việc. `authority.read` là khóa tùy chọn mới của `authority.normalize` (mở rộng schema; wheel 2.3 từ chối hợp đồng có khóa này, HUONG-DAN-SOURCE §6). Giao thức là vòng continuation: worker trả `continuation` + `source.requests` (tối đa 8), receipt niêm phong yêu cầu, attempt sau chạy chúng trên cây ghim rồi đưa trang kết quả vào prompt. Sau review: `max_rounds` là trần cứng (A-R02), đếm trên mọi receipt của node (A-R04); khi root khai `authority.read`, `read` của node cũng bị ràng (A-R03). Node không khai `sources` giữ prompt và receipt giống từng byte 2.3 (sa11, sa11b).
- **B:** `working_context.py`. `knowledge.delivered` ghi trước khi khởi chạy, một lần mỗi attempt; delta chỉ đến ở điểm an toàn (không có kênh giữa lúc chạy). Một hàm `decide` dùng cho cổng công bố, kiểm trước khi giao và lệnh xem (B-R01, B-R07); xét trên đúng các file worker đã thấy (bản đầu xét trên cây làm việc, B-R01); kiểm lại ngay trong giao dịch ghi `node.verification` (B-R02); đầu vào đổi thì giữ ngay, không gọi model (B-R03); tối đa 2 lần kiểm lại mỗi node (working_context.py:29), quá thì `node.held` `knowledge_changed`.
- **C:** không thêm trường hợp đồng; ba trường tùy chọn `preserve`, `investigation`, `estimate` bật luật trong `proposal.RULES`, nên cổng duyệt cũ tự áp dụng, không có lượt duyệt thứ hai. Trần điều tra cố định ở lần kiểm hợp lệ đầu tiên (C-R02); unknown đã ghi mở không được bỏ khi sổ không có bằng chứng đóng (C-R01). `execution_mode.choose` là hàm thuần; capability `execution-mode` opt-in, cần `sequential-engine` (namespaces.py); bản ghi ở Q2, `node.started`, `workflow.mode`. Khác map: bỏ chờ `budget_exhausted`, ngân sách hẹp chạy như 2.3 và ghi `budget_tight` (C-R05); `tools` giữ node bằng claim (C-R03); giữ phiên cần attempt trước cùng chuỗi, cùng mã phiên, cùng pin (C-R06).
- **Chung:** hai gói thử S1, S2 cùng version `2.4.0.dev1` (§2 hẹn tăng N mỗi gói alpha); hai gói phân biệt bằng commit và sha wheel — xem §8. Mọi lượt kiểm dùng `LOCALAPPDATA`, `APPDATA`, `TEMP` riêng (`D:\OneCrewRuns\wf-dev-tools\v24\run_regress.sh`); hash sổ hook thật `23ec9033…` giống nhau trước và sau mỗi lượt (dòng cuối từng log).

## 5. Requirement → tái dùng → task → testcase → bằng chứng

Log ở `D:\OneCrewRuns\v24\logs\` (tên ghi ngắn, bỏ `reg-` và `.txt`). "Đỏ trước" = test viết trước code, hỏng trên bản trước. Mọi worker là `claude` giả; không có bằng chứng model thật.

| Req | Yêu cầu (rút gọn) | Tái dùng | Task | Testcase / phản chứng | Bằng chứng |
|---|---|---|---|---|---|
| SF-01 | Một đầu vào, một mã; chưa có task hay root đã đóng vẫn nhận; không gộp, không tạo lỗi giả | ledger requests, `task_intake` | T24-S1 | `test_v24_s1_intake` (8: gửi lại/khởi động lại một bản, cùng khóa khác nội dung, root đóng, revision cũ, khác version không gộp, không receipt giả, chỉ gắn refs chứng minh được); review r02, r08, s2_r05 | đỏ trước `s1-red` (27/28 hỏng trên `913e798`); gói V17 |
| SF-02 | Hồ sơ local có manifest, lọc, trần; spool khi hỏng | sổ, log attempt, receipt, doctor | T24-S1 | `test_v24_s1_bundle` (9), `test_v24_s1_spool` (5); review r01 ×2, r03, p3e, r05, r06, r13, p3c, s2_r11 | `s1-red`; gói V17, V18 |
| SF-03 | Phân loại; nối việc sửa đúng grant; chữ trong log không đổi quyền | findings, authority | T24-S1, T24-S2 | `test_v24_s1_status` (lớp lỗi, chữ trong log, finding có receipt); review r04, r07, p3a; `test_v24_s2_apply` (quyền sửa project không cho cài; policy hợp lệ không hỏi lại) | gói V19, V21 |
| SF-04 | Bản vá → artifact → cài tại đích → kiểm lỗi gốc → tiếp tục; không phát lại effect unknown, không reset ngân sách | engine, Control, compat_scan | T24-S2 | `test_v24_s2_apply` (12: hash hay nguồn sai, venv giả, scan baseline khác, process/effect/consumer/dữ liệu đổi chặn chuyển, crash giữa các bước, rollback không đọc được, nhánh độc lập, recheck tại đích hay bản sao, bài học); `test_v24_s2_installed` (1) | đỏ trước `s2-red` (16/16 lỗi trên `1c81f5d`); ca review `s2r-h1` (12/12 hỏng, HEAD `65ef023`, cây đang sửa); gói V20–V22 |
| SF-05 | Trạng thái tách cột có bằng chứng; thông báo chỉ khi đổi; xác nhận của chủ là tín hiệu riêng | notification_core, outbox | T24-S1, T24-S2 | `test_v24_s1_status` (một thông báo mỗi lần chuyển; pull/restart/ACK không trả lời; confirm bị từ chối trong phiên AI); s2_apply (recheck, bài học) | gói V19, V22 |
| S-gói | Chạy từ wheel ngoài checkout; bản cũ đọc được sổ có bản ghi support | `wf_wheel`, `boundary` | T24-S1, T24-S2 | `test_v24_s1_installed` (2), `test_v24_s1_oldreaders` (1, wheel 2.2.0.dev18 và 2.3.0.dev10 thật), `test_v24_s2_installed` (1) | review-s2.md mục "S1 review fixes — checked" (P3b); gói V2, V3 |
| 2.4a-1 | Quyền đọc tách quyền ghi; root ∧ node; dependency trong quyền tự đọc | — (mới) | T24-A | sa01, sa01b, sa01c; a_r03; a_r13 (grant mặc định) | đỏ trước `v24a-red`, `v24a-red2` (16/17 lỗi trên `5c34f4a`) |
| 2.4a-2 | Nguồn ghim; đổi cây thì cursor cũ hết hiệu lực | `command.artifact_sha` | T24-A | sa04, sa04b, sa02c (junction → `unavailable`), a_r04b | `aff-test_v24_a_sources-br` (18/18, `c5b78e9`) |
| 2.4a-3 | Kết quả có nguồn, dòng, blob, coverage; phần bị giữ không thành "không có" | luật đọc của `discovery` | T24-A | sa02, sa02b, sa03, sa05; a_r01, a_r01b, a_r06, a_r11, a_r13 (đường dẫn tuyệt đối) | `aff-test_v24_a_review-br` (17/17); đỏ review `v24a-review-red` (14/17) |
| 2.4a-4 | Trang; receipt đủ; chỉ trang liên quan vào prompt | paging | T24-A | sa03, sa09, a_r07 | như trên |
| 2.4a-5 | Mỗi lượt tính vào ngân sách root; trần lượt và bộ nhớ lặp qua restart; trang kế không bị chặn | `progress_core`, Control | T24-A | sa06, sa07; a_r02, a_r02b, a_r04, a_r05, a_r08, a_r13 (hai continuation đồng thời) | như trên |
| 2.4a-6 | Giới hạn riêng theo provider, lượt, yêu cầu | công thức `owned._cap` | T24-A | sa10, sa10b, a_r09 | như trên |
| 2.4a-7 | Nội dung nguồn không đổi quyền | khung prompt 2.3 | T24-A | sa08 | như trên |
| 2.4a-8 | Một giao thức cho việc code và phi-code; opt-in; wheel không import v1 | — | T24-A | sa09, sa11, sa11b, a_r10; sa12 (wheel cài, `claude` giả) | `aff-test_v24_a_installed-br` (1/1) |
| 2.4b-1 | Gói thực giao có định danh theo attempt và consumer; restart không ghi lại, không reset ngân sách | receipt, `executor.managed` | T24-B | sb01, sb01b, sb05, b_r04b | đỏ trước `v24b-red` (11/13 trên `26a86e7`; sb01b, sb09 đã giữ từ 2.3); `aff-test_v24_b_context-br` (21/21) |
| 2.4b-2 | Nguồn đổi → kiểm lại, chỉ node đã đọc file đó | applicability 2.3 | T24-B | sb07, b_r05, b_r06 | như trên; đỏ review `v24b-review-red` (7/21 trên `58b863f`) |
| 2.4b-3 | Thu hồi hay thay thế báo đúng consumer bị ảnh hưởng; nhánh độc lập chạy tiếp | `dependency_core` | T24-B | sb02, sb08, b_r07, `test_wiki_consumers_lists_delivery_and_delta_status` | như trên |
| 2.4b-4 | Delta ở điểm an toàn, hoặc kiểm lại trước khi nhận/công bố; mục đã thu hồi không sống lại | cổng engine | T24-B | sb03, sb04, sb04b, sb06, b_r01, b_r02, b_r03, b_r04 | như trên; `aff-test_v24_b_installed-br` (sb04 trên wheel cài) |
| 2.4b-5 | Kết quả muộn sau khi đổi thế hệ không được công bố; hai root (hồi quy 2.3) | thế hệ của engine | T24-B | sb09, sb10 | như trên |
| 2.1 | Thẻ bước 0: mục tiêu, cách nhỏ nhất, điều giữ, phép kiểm, unknown, ước lượng hay "chưa đủ dữ liệu"; trần điều tra có điểm dừng | step0, proposal, survey | T24-C | `test_v24_c_step0_card` (13); `test_v24_c_review` r01 ×3, r02, r02_r16 | `c-after-review-extra-fix1` (63 OK, `21b6a56`); đỏ review `c-review-red-a67bb19` (20/23) |
| 2.2 | Chọn tiếp tục worker, chồng lấp, tool hay chờ, có lý do; không reset ngân sách hay pin; không giả giữ phiên; opt-in | engine, Control, executors | T24-C | `test_v24_c_execution_mode` (15); `test_v24_c_review` r03–r18 (19) | đỏ trước ca 4 `c-case4-baseline5c34f4a-red` (3/3 trên `5c34f4a`); `merge-c-65ef023` (72 OK sau gộp) |
| U1 | Hai test của bộ kiểm cần đổi cho 2.4 | `wfkit/u1` | T24-0, T24-U1-DL | `test_g1_core` (ghim version); `test_wf_metered_verifier` (hạn root) | `u1-pin-red` → `u1-pin-green`; `D:\OneCrewRuns\v24\probe-mv\bde505b\probe-mv.json` (4/4 hỏng) → `deadline-green1-dirty`, `deadline-green2-dirty`, `deadline-module-dirty` (4/4) |
| Tích hợp | Cả năm mốc trên một cây; hồi quy 2.3 và 2.2 liên quan | — | T24-INT | `tests/test_v24_*` (170 test) và 34 module 2.2/2.3 bị ảnh hưởng | `int-v24-bde505b`: `Ran 170 tests in 2346.975s`, `OK`; `int-aff-bde505b`: `Ran 448 tests in 3151.847s`, `OK (skipped=1)`; gói cuối `2.4.0.dev2` 25/25 từ artifact (`D:\OneCrewRuns\v24 thu 2.4.0.dev2\verify\verify-report.json`) |

## 6. Task, dependency, thực tế

Giờ lấy từ commit (`git log --format="%h %ci"`), lúc tạo nhánh (`git reflog`) và giờ ghi file/log, ngày 01/11. Không task 2.4 nào có ước lượng ghi trước code, nên cột ước lượng ghi "không ghi". Mọi commit mang tác giả `NUC`; commit không ghi agent nào viết, chỉ báo cáo review tự ghi người review.

| Task | Đầu ra | Phụ thuộc | Worktree / nhánh | Ước lượng | Thực tế |
|---|---|---|---|---|---|
| T24-0 | Cách ly, version `2.4.0.dev1`, U1 ghim version, hợp đồng §1–2, ba bản đồ | — | `wf-v24` / `claude/onecrew-2.4` (tạo 07:54 từ `fe0a044`) | không ghi | thư mục chạy 07:54; `5c34f4a` 08:04; bản đồ 08:08–08:09; `913e798` 08:15 |
| T24-S1 | `support report/show/status/classify/link/bundle/import-spool/confirm`, hướng dẫn | T24-0 | `wf-v24` | không ghi | đỏ 08:20; `1407528`, `97306c9`, `1c81f5d` 08:54 |
| T24-S1R | Review độc lập + sửa | T24-S1 | review: agent Opus 5.5 trên bản `git archive`; sửa: `wf-v24` | không ghi | review ghi 09:21 (P1 1, P2 7, P3 14); sửa `b6b300c` 09:52 |
| T24-S2 | Chuỗi bản vá `hotfix.py` | T24-S1 | `wf-v24` | không ghi | đỏ 09:16; `8577db4` 10:24 |
| T24-S2R | Review độc lập + sửa | T24-S2 | review: agent Opus 5.5; sửa: `wf-v24` | không ghi | review ghi 11:21 (P1 5, P2 7, P3 9); sửa `58c740d` 12:04 |
| T24-A | `source_tools`, `authority.read`, paging vào wheel, sa12 | T24-0 | `wf-v24-a` / `claude/onecrew-2.4-a` (tạo 08:11) | không ghi | đỏ 08:30; `5c7da07`–`a4d7924` 08:57; `1074e61` 09:05; `2ec0904` 09:13; `26a86e7` 09:35 |
| T24-AR | Review độc lập + sửa | T24-A | review: agent độc lập (báo cáo không ghi model); sửa: `wf-v24-a` | không ghi | review ghi 11:03 (P1 1, P2 3, P3 9); `dd3e2c4`, `cb42bfa` 11:27 |
| T24-B | `working_context`, `knowledge.delivered`, delta, cổng, `wiki consumers` | T24-A | `wf-v24-a` | không ghi | đỏ 10:56; `ab59b54` 11:00; `0609eef` 11:07; `58b863f` 11:31 |
| T24-BR | Review độc lập + sửa | T24-B, T24-AR | review: agent độc lập (báo cáo không ghi model); sửa: `wf-v24-a` | không ghi | review ghi 12:14 (P1 1, P2 3, P3 7); `4eb72bf` 12:20; `c5b78e9` 12:31 |
| T24-C | Thẻ bước 0, `execution_mode`, `engine measure`, `--checks` | T24-0 | `wf-v24-c` / `claude/onecrew-2.4-c` (tạo 08:11) | không ghi | đỏ ca 4 08:32; `a303713` 08:33 … `a67bb19` 08:42; hồi quy ảnh hưởng 08:42–09:42 (`c-affected-t1`, 315 OK) |
| T24-CR | Review độc lập + sửa | T24-C | review: agent độc lập (báo cáo không ghi model); sửa: `wf-v24-c` | không ghi | review ghi 10:14 (P1 1, P2 5, P3 12); `4648f21` 10:33; `21b6a56` 10:54 |
| T24-PKG | Bộ dựng và kiểm gói 2.4; gói thử S1 và S2 | T24-S1 (S2 cho V20–V22) | `wf-v24-pkg` / `claude/onecrew-2.4-pkg` (tạo 09:06 từ `1c81f5d`) | không ghi | `1cc0940` 09:16; gói S1 09:16, kiểm 09:17–09:31 (19/19), script thử 09:32–09:44; `281747a` 09:32; `0c94f9a` 12:13; gói S2 12:13, kiểm 12:13–12:18 (22/22) |
| T24-U1-DL | U1 cho test hạn root | T24-INT | `wf-v24` | không ghi | probe đỏ 12:40–12:42; xanh 12:45–12:47; `7767982` 12:47 |
| T24-INT | Gộp, hồi quy tích hợp | mọi task trên | `wf-v24` | không ghi | `ba42e22`, `65ef023` 11:01 (72 OK, 11:01–11:04); `bde505b` 12:40; hai lượt song song trên `bde505b`: 2.4 12:41–13:20 (170/170), module ảnh hưởng 12:41–13:34 (448, 1 skip) |
| T24-FINAL | Gói cuối, gate 2.2 một lần, hồ sơ bàn giao | T24-INT | `wf-v24-pkg` (gộp vào `claude/onecrew-2.4` bởi người điều phối) | không ghi | bước V23–V25 `a039d1f` 13:02; sửa giới hạn và `ships_paging` `d9d3075` 13:20 (gộp `d5f0815`); snapshot `61862e6` (`2.4.0.dev2`) 13:34; dựng, kiểm 25/25 và script thử `DAT`/0 13:34–13:45; gate 2.2 13:46:05–16:39:35 trên `61862e6`: 286/286 check thực thi, `refused` chỉ vì 23 khoảng trống nghiệm thu trùng dev10 (BAO-CAO-2.4 §4) |
| T24-CX-F1 | Codex F1 (P1): danh tính venv từ nội dung file và mốc tạo venv, không chạy gì trước kiểm tĩnh; `support cleanup --venv` | T24-FINAL | `wf-v24` / `claude/onecrew-2.4` | không ghi | đỏ 21:22 trên `953096a` (`s2/red-953096a.txt`); `58cfb24` 21:53 (code), `0af3482` 21:53 (docs); vòng 2 `7253969`, `a7964a3` 22:55; vòng 3 `9c2600a`, `550f40a` 23:53; vòng 4 `f171ac9`, `daa3caa` 01:04 (02/11); vòng 5 `bb19222` 01:29 (02/11); review r2 22:11 (P1 3, P2 5, P3 5), r3 23:05 (2/3/4), r4 00:02 (2/2/4), r5 01:09 (0/1/4) |
| T24-CX-F2 | Codex F2 (P1): quyết định chuyển/quay lui gắn với dữ liệu đã diễn tập; cửa sổ chuyển hai phía; vi phạm không là ngõ cụt; claim có thời hạn | T24-CX-F1 (cùng `hotfix.py`) | `wf-v24` / `claude/onecrew-2.4` | không ghi | cùng các commit và review của T24-CX-F1 (một lượt sửa cho cả hai finding) |
| T24-CX-F3 | Codex F3 (P2): duyệt đủ chuỗi đầu vào, không bao giờ mặc định `publish`; attempt sinh lấy từ sổ | T24-FINAL | `wf-v24-a` / `claude/onecrew-2.4-a` | không ghi | đỏ 21:44 (`b/red-test_v24_b_review2-12-953096a.txt`); `3bc739e`, `3cf5b30`, `155ed60` 21:46; review 21:57 (P1 1, P2 0, P3 4); P1-1: `8ed6040` (đỏ), `8424336`, `31baabf` 22:26; review lại 23:13 (0/0/4); vòng P3 `5b24fca`, `d2f1c5f` 23:25 |
| T24-CX-F4 | Codex F4 (P3): đồng bộ báo cáo, hợp đồng, giới hạn, wiki với dev3; bước gói V26–V28; hợp nhất; snapshot `2.4.0.dev3` | T24-CX-F1, -F2, -F3 | `wf-v24-pkg` / `claude/onecrew-2.4-pkg` (docs phần 1 `9e9de4d` 21:06 ở `claude/onecrew-2.4`) | không ghi | `9151e86` 22:16 (V26–V28), `576ba00` 00:13 (kiểm lại với `fe495c1`); gộp `da9c913` 21:56, `830af1a` 22:56, `fe495c1` 23:53, `34709d5` 01:05; snapshot `5a7a8ef` 01:30 (02/11); tài liệu phần 2 (commit này); gói và gate dev3 chưa có (§7) |

## 7. Nhật ký

| Lúc (01/11) | Việc | Bằng chứng |
|---|---|---|
| ~02:10 | Chỉ thị người dùng: tiếp quản và hoàn thành 2.4-S1/S2/A/B/C | chat Claude Code; trích ở đầu hồ sơ |
| ~02:15 | Quan sát tài nguyên đang dùng; sổ hook thật SHA256 `884335df…` | §1 |
| 02:15–07:54 | Không có commit hay log 2.4; hồ sơ không ghi nguyên nhân | `git reflog`, giờ tạo thư mục |
| 07:54–08:04 | T24-0: worktree `wf-v24`, thư mục `D:\OneCrewRuns\v24`, version `2.4.0.dev1`, U1 PIN-1 | `5c34f4a`; `u1-pin-red`, `u1-pin-green` |
| 08:01 | Phiên khác đổi sổ hook thật (SHA256 `23ec9033…`); không đụng | §1, `913e798` |
| 08:08–08:09 | Ba bản đồ tái sử dụng S, A/B, C | `D:\OneCrewRuns\v24\design\map-*.md` |
| 08:11 | Tạo worktree A và C từ `5c34f4a` | `git reflog` |
| 08:20–08:54 | S1: test đỏ 27/28 → code → hướng dẫn | `s1-red`; `97306c9`, `1c81f5d` |
| 08:29–08:42 | C: test đỏ ca 4 → `execution_mode`, thẻ bước 0, `engine measure` | `c-case4-baseline5c34f4a-red`; `a303713` … `a67bb19` |
| 08:30–09:35 | A: test đỏ 16/17 → `source_tools` → sa12 → hướng dẫn | `v24a-red`; `909b757` … `26a86e7` |
| 09:06–09:44 | Bộ dựng/kiểm gói; gói thử S1 (code `1cc0940` = S1 trước khi sửa review) 19/19; script thử: kiểm 19/19, task đầu tiên 23/23, luồng alpha 5/5 | `D:\OneCrewRuns\v24\pkg-trial\logs\verify-trial1.txt`, `thugoi-trial1.txt` |
| 09:21 | Review S1: P1 1, P2 7, P3 14 | `D:\OneCrewRuns\v24\review-s1\review-s1.md` |
| 09:52 | Sửa S1-R01…R08 và P3a–e | `b6b300c` |
| 09:16–10:24 | S2: test đỏ 16/16 → `hotfix.py` | `s2-red`; `8577db4` |
| 10:14 | Review C: P1 1, P2 5, P3 12 | `D:\OneCrewRuns\v24\review-c\review-c.md` |
| 10:19–10:54 | Probe review C thành test (đỏ 20/23) → sửa C-R01…R18 | `c-review-red-a67bb19`; `4648f21`, `21b6a56` |
| 10:56–11:31 | B: test đỏ 11/13 → `working_context` → sb04 trên wheel cài | `v24b-red`; `ab59b54`, `0609eef`, `58b863f` |
| 11:01 | Gộp nhánh gói (`ba42e22`) và nhánh C (`65ef023`); hồi quy sau gộp 72 OK | `merge-c-65ef023` |
| 11:03 | Review A: P1 1, P2 3, P3 9 | `D:\OneCrewRuns\v24\review-a\review-a.md` |
| 11:13–11:27 | Probe review A thành test (đỏ 14/17) → sửa A-R01…R13 | `v24a-review-red`; `dd3e2c4`, `cb42bfa` |
| 11:21 | Review S2 và bản sửa S1: P1 5, P2 7, P3 9 | `D:\OneCrewRuns\v24\review-s2\review-s2.md` |
| 11:36–12:04 | Ca review S2 (12/12 hỏng, cây đang sửa) → sửa S2-R01…R12, S1-R21/R22 | `s2r-h1`; `58c740d` |
| 12:13–12:18 | Bước V20–V22; gói thử S2 (code `0c94f9a`) 22/22 | `D:\OneCrewRuns\v24\pkg-trial\work-verify-s2\verify-report.json` |
| 12:14 | Review B và bản sửa A: P1 1, P2 3, P3 7 | `D:\OneCrewRuns\v24\review-b\review-b.md` |
| 12:16–12:31 | Probe review B thành test (đỏ 7/21) → sửa B-R01…R08; 11 module đạt trên `c5b78e9` | `v24b-review-red`; `4eb72bf`, `c5b78e9`; `aff-*-br` |
| 12:40 | Gộp A/B (`bde505b`): cả năm mốc trên một cây | `bde505b` |
| 12:40–12:47 | Test hạn root 4/4 hỏng dưới tải trên `bde505b` → U1 DEADLINE-1 → 2/2 và module 4/4 đạt | `probe-mv.json`; `deadline-*-dirty`; `7767982` |
| 12:41–13:34 | Hồi quy tích hợp trên `bde505b`: 170/170 test 2.4 (xong 13:20); 448 test của 34 module 2.2/2.3: 447 đạt, 1 skip, 0 fail (xong 13:34) | `int-v24-bde505b`, `int-aff-bde505b` |
| 13:02 | Bước gói V23–V25 (A, B, C), giới hạn A/B/C và bản gộp | `a039d1f` |
| 13:20 | Giới hạn S1 viết lại theo code hiện hành; `ships_paging` đọc từ `py-modules`; README nói rõ gói `pkg-trial` là bản thử công cụ | `d9d3075`, gộp `d5f0815` |
| 13:34 | Snapshot cuối `61862e6`: version `2.4.0.dev2` (chỉ đổi version và CHANGELOG so với `d5f0815`) | `61862e6` |
| 13:34–13:45 | Gói `D:\OneCrewRuns\v24\pkg\onecrew-2.4.0.dev2-beta` (wheel `383df81d…`, `SHA256SUMS` 62/62); kiểm từ gói 25/25 (13:34–13:39, máy rảnh); script thử `DAT`/0 (13:39–13:45); chạy lại cùng thư mục → mã 2 | `pkg-build-2.4.0.dev2`, `pkg-verify-2.4.0.dev2`, `pkg-wrapper-2.4.0.dev2`, `pkg-wrapper-2.4.0.dev2-reuse` |
| 13:46:05–16:39:35 | Gate snapshot 2.2 trên `61862e6`, chạy một mình: 286/286 check thực thi đạt, 2.097 test đạt (0 skip, 0 expected failure), `refused` chỉ vì 23 khoảng trống nghiệm thu (trùng dev10); kit-guard `ok` | `gate-snapshot-61862e6`, `gates-tmp\wf-snapshot-gate-20261101-61862e6\gate\decision.json` |
| 14:08:57 | Sổ hook thật đổi lần hai bởi phiên khác (thêm bản sao `signsdk-dev10-thu-20261101`); không phải lượt 2.4, không khôi phục | §1 |

### Review Codex vòng 1 trên dev2 → dev3 (01/11 20:55 – 02/11)

Giờ lấy từ `git log --date=format:%H:%M` trong `wf-v24-pkg`, giờ ghi file của báo cáo review và log dưới `D:/OneCrewRuns/v24/codex-r1/`, `D:/OneCrewRuns/v24/logs/`. Cột "Lúc" ghi cả ngày.

| Lúc | Việc | Bằng chứng |
|---|---|---|
| 01/11 ~20:55 | Chỉ thị chủ: sửa 2 P1 (F1 runtime bị sửa vẫn qua danh tính, F2 rollback lấy mốc sau diễn tập), 1 P2 (F3 `INPUT_DEPTH=3`), 1 P3 (F4 báo cáo/giới hạn sai hoặc cũ) từ review Codex vòng 1 trên `2.4.0.dev2` (code `61862e6`, tài liệu `953096a`) | chat Claude Code; probe Codex `D:/OneCrewRuns/codex-v24-progress-29e140be/` |
| 01/11 21:03–21:12 | Bảng finding → ca thử → kỳ vọng; tái hiện baseline `953096a`: `rollback_probe` ra `rolled_back` với `data_changed_since_drill true`; `depth_probe` và `chain_integration` ra `E publish` | `codex-r1/plan.md`; `baseline/rollback_probe-953096a.json`; `b/probe-before-953096a.txt` |
| 01/11 21:06 | F4 phần 1: số gate `61862e6`, 447 + 1 skip, `limits-s2` | `9e9de4d` |
| 01/11 21:22–21:46 | Test đỏ trên baseline: S2 20 test (16 hỏng, 1 lỗi); B 12 test (10 hỏng, 2 lỗi) | `s2/red-953096a.txt`; `b/red-test_v24_b_review2-12-953096a.txt`; `3bc739e` |
| 01/11 21:46–21:53 | F3 sửa và docs; F1/F2 sửa và docs; gộp | `3cf5b30`, `155ed60`; `58cfb24`, `0af3482`; `da9c913` 21:56 |
| 01/11 21:57 | Review độc lập F3: P1 1, P2 0, P3 4 (P1-1: biên nhận nêu attempt của node khác thì chuỗi bị bỏ lọt) | `review-b/review-f3.md` |
| 01/11 22:11 | Review độc lập S2 r2: P1 3, P2 5, P3 5 | `review-s2/review-s2-r2.md` |
| 01/11 22:13–22:16 | Bước gói V26–V28 viết; cả ba FAIL trên gói dev2 | `9151e86`; `pkg/v26-on-dev2.txt`, `v27-on-dev2.txt`, `v28-on-dev2.txt` |
| 01/11 22:26 | F3 P1-1: test đỏ trên `155ed60`, sửa (attempt sinh luôn lấy từ sổ), docs | `8ed6040`, `8424336`, `31baabf` |
| 01/11 22:55–23:22 | S2 vòng 2 (mốc tạo venv, kiểm tĩnh trước khi chạy, vi phạm khôi phục được, claim có thời hạn); gộp `830af1a`; hồi quy tích hợp 2.4 228/228 (22:56:30–23:22:36) | `7253969`, `a7964a3`; `logs/reg-int-v24-830af1a.txt` |
| 01/11 23:05 | Review độc lập S2 r3: P1 2, P2 3, P3 4 | `review-s2-r3/review-s2-r3.md` |
| 01/11 23:13–23:25 | Review lại F3: P1 0, P2 0, P3 4; vòng P3 của F3 | `review-b-r2/review-f3-r2.md`; `5b24fca`, `d2f1c5f` |
| 01/11 23:53 | S2 vòng 3 (không ngõ cụt, cửa sổ giữa file hook đầu và cuối, không tiếp tục venv không có mốc, mỗi sổ một venv); gộp `fe495c1` | `9c2600a`, `550f40a` |
| 01/11 23:54 – 02/11 00:29 | Hồi quy tích hợp 2.4 trên `fe495c1`: 238/238, 0 skip | `logs/reg-int-v24-fe495c1.txt` |
| 02/11 00:02 | Review độc lập S2 r4: P1 2, P2 2, P3 4 | `review-s2-r4/review-s2-r4.md` |
| 02/11 00:10–00:13 | V26–V28 kiểm lại với `fe495c1` (dạng lệnh rollback, venv đã chuyển bị sửa); FAIL trên gói dev2, đạt trên wheel dựng từ `fe495c1` | `576ba00`; `pkg/v26-on-dev2-r2.txt` … `v28-on-dev2-r2.txt`; `D:/OneCrewRuns/v24 thu v2x fe495c1` |
| 02/11 01:04–01:05 | S2 vòng 4 (`cleanup --venv` đúng đường dẫn đưa và hai dạng thư mục, kiểm trước ghi trong một lượt đọc, luật chặn cho chủ); gộp `34709d5` | `f171ac9`, `daa3caa` |
| 02/11 01:09 | Review độc lập S2 r5 (cuối): P1 0, P2 1 (viết tắt `--ven` lọt luật chặn), P3 4 | `review-s2-r5/review-s2-r5.md` |
| 02/11 01:29 | S2 vòng 5: `allow_abbrev=False`, luật chặn mọi tùy chọn bắt đầu `--v`; module S2 183 test, 1 hỏng có từ trước (`test_g2_install`) | `bb19222`; `s2/round5-green.txt` |
| 02/11 01:30 | Snapshot `2.4.0.dev3` (version và CHANGELOG) | `5a7a8ef` |
| 02/11 (tài liệu) | Báo cáo §8, hợp đồng §6–§8, `limits-final.md`, wiki | commit "2.4 docs: Codex round 1 (F1–F4) section ..." |
| chưa có | Gói `onecrew-2.4.0.dev3-beta` (28 bước), kiểm từ gói, script thử | <!-- v24:dev3-pkg --> |
| chưa có | Gate 2.2 và hồi quy 2.4 trên `5a7a8ef` | <!-- v24:dev3-gate --> |

### Review Codex trên dev3 → dev4 (02/11, Claude Opus 5.5, tài khoản mới)

| Lúc | Việc | Bằng chứng |
|---|---|---|
| 02/11 ~01:55 | Chỉ thị chủ: sửa 1 P1 (bytecode sai chạy trước khi bị từ chối) và 1 P3 (tài liệu trong gói dev3 không đồng bộ). Tiếp quản từ wiki, `wf-v24-pkg` HEAD `7e61b46` (tài liệu sau `5a7a8ef`), không tiến trình kiểm 2.4 nào đang chạy | bằng chứng Codex `D:/OneCrewRuns/codex-dev3-review-c2a9a088/` |
| 02/11 02:03 | Phản chứng P1 trên venv thật: 7/8 đỏ trên `7e61b46` | `logs/reg-p1-bytecode-red-7e61b46.txt` |
| 02/11 02:04–02:06 | Sửa P1 (`identity` dừng trước `entry_run`, runtime cũ khi quay lui), 8/8 xanh | `logs/reg-p1-bytecode-green-p1fix3.txt` |
| 02/11 02:09–02:10 | V30, V29 viết; cả hai FAIL trên gói dev3 | `logs/pkg-red-dev3-V30-s2-docs.txt`, `pkg-red-dev3-V29-s2-bytecode.txt` |
| 02/11 02:20:51 | Sổ hook thật đổi: thêm mục `d:\tamnt\workspace\1.vimes\9.signsdk\sources\signsdk` → `D:\OneCrewRuns\projects\signsdk-9SignSDK\state-23`, của phiên khác (lượt 2.4 ghi bản riêng `tmp-int\lad`, lần ghi cuối 01:26). Không khôi phục | `logs/reg-v24-all-p1fix3.txt` (hash trước/sau) |
| 02/11 02:38–02:43 | `test_v24_s2_installed` hỏng (bản fix không đổi version từ dev3); sửa test; danh sách cache qua stdin (tempfile dir cũ của tiến trình); 12/12 | `logs/reg-s2-installed-fix-stdin.txt` |
| 02/11 02:43 | Commit `0b4f539` (P1), `704857c` (P3 + V29/V30), snapshot `4f03e54` (`2.4.0.dev4`); `claude/onecrew-2.4` fast-forward | git |
| 02/11 02:43–03:18 | Hồi quy 2.4 trên `4f03e54` sạch 259/259; gói dev4 30/30, script thử DAT, hash 62/62 | `logs/reg-v24-all-4f03e54.txt`, `logs/pkg-*-2.4.0.dev4.txt` |
| 02/11 03:10 | Probe Codex trên wheel dev4: `marker_created false`, `entrypoint_exit null` | `D:/OneCrewRuns/v24/codex-probe-dev4b/bytecode-result.json` |
| 02/11 03:18–06:02 | Gate 2.2 trên `4f03e54` (chạy một mình): 286/286 check thực thi đạt, 2.097/2.097 test, 0 skip; `refused` chỉ vì 23 khoảng trống nghiệm thu như gate `61862e6` | `logs/gate-snapshot-4f03e54.txt`, `gates-tmp/wf-snapshot-gate-20261102-4f03e54/decision.json` |

### Review Codex trên dev4 → dev5 (02/11, Claude Opus 5.5)

| Lúc | Việc | Bằng chứng |
|---|---|---|
| 02/11 ~07:15 | Chỉ thị chủ: khép P1 rollback (bytecode bị thay sau phép kiểm chạy trong bước đọc sổ/phân loại), hoàn tất checklist local, gói beta mới. HEAD `a0ac49d` sạch ở `wf-v24-pkg`, `wf-v24`; không lượt kiểm 2.4 nào đang chạy | `D:/OneCrewRuns/codex-dev4-review-af11587c/` |
| 02/11 07:26–07:32 | Phản chứng qua caller `_rollback` thật; 4/14 đỏ trên `hotfix.py` dev4 (marker). Lộ thêm cùng lớp: `PYTHONPATH` của terminal làm bước đọc sổ nạp onecrew khác | `logs/reg-p1rb-red-final-a0ac49d.txt` |
| 02/11 07:31 | Sửa (`checked_run` cho mọi chương trình của venv đã kiểm), 14/14 | `logs/reg-p1rb-green2-p1rb-fix1.txt` |
| 02/11 07:32–07:47 | Nhóm S2 + tài liệu 93/93; V31 FAIL trên gói dev4 | `logs/reg-s2-group-p1rb-fix1.txt`, `logs/pkg-red-dev4-V31-s2-rollback-bytecode.txt` |
| 02/11 07:48 | Commit `ad3b970` (P1), snapshot `387d3cb` (`2.4.0.dev5`, V31, tài liệu); `claude/onecrew-2.4` fast-forward | git |
| 02/11 07:48–08:22 | Hồi quy 2.4 trên `387d3cb` sạch 265/265; gói dev5 31/31, script thử DAT, hash 62/62 | `logs/reg-v24-all-387d3cb.txt`, `logs/pkg-*-2.4.0.dev5.txt` |
| 02/11 ~08:15 | Probe Codex trên wheel dev5 (venv sạch, đường dẫn có khoảng trắng): `marker_created false`, `marker_after_classifier false` | `logs/codex-probes-dev5.txt` |
| 02/11 08:22–11:27 | Gate 2.2 trên `387d3cb` (từ 10:17 chạy song song gói hotfix 2.3 theo lựa chọn của chủ): 286/286 check thực thi đạt, 2.107/2.107 test, 0 skip; `refused` với 23 vấn đề trùng từng mục gate dev4 | `logs/gate-snapshot-387d3cb.txt`, `gates-tmp/wf-snapshot-gate-20261102-387d3cb/decision.json` |

### Beta 2.4.0.dev6 (02/11 19:10–03/11 ~02:00, Claude Fable 5.1)

| Lúc | Việc | Bằng chứng |
|---|---|---|
| 02/11 ~19:10 | Chỉ thị chủ (ủy quyền một lần): tích hợp hotfix 2.3, gói beta kèm bộ thử, diễn tập nâng cấp/quay về, snapshot một lần, gate, phát hành; kết thúc ở trạng thái A hoặc B | chat |
| 19:2x–20:0x | Cherry-pick `a3d6a15` → `ddec0e3`; phản chứng key phản chiếu 3/5 đỏ → `8dbaf1c` 5/5, auth 17/17 | `logs/reg-auth-redaction-*.txt` |
| 20:xx | Bộ thử tổng quát hóa vào gói, template hướng dẫn, V32; snapshot `dafbb87`; gói lần 1: V32 lỗi khóa facts, V27 hỏng khi chạy cùng hồi quy (đạt khi chạy riêng) → sửa V32, snapshot cuối **`01b6f62`** | `logs/pkg-*-dev6*.txt` |
| 21:02–22:19 | Hồi quy trên `01b6f62` sạch: `tests/test_v24_*` 270/270; module 2.3 ảnh hưởng 282, 1 skip (CLI thật) | `logs/reg-v24-all-01b6f62.txt`, `reg-affected23-01b6f62.txt` |
| ~21:20 | **Chủ duyệt** smoke model thật (`claude-sonnet-5-5`, key User): advisor usable, reviewer pass, worker `held` (tổ chức tắt subscription; adapter worker chỉ subscription); 0 file chứa key; $0,027 | `logs/smoke-sonnet*-dev6.txt`, lab `D:/OneCrewRuns/v24 smoke sonnet/smoke/` |
| 2x:xx | Gói `onecrew-2.4.0.dev6-beta` 32/32 (chạy riêng), script thử DAT, chạy lại bị từ chối, SHA256SUMS 68/68; script lab trong gói 11/11; diễn tập dev11→dev6→dev11→dev6 đạt; `release check` ok | `logs/pkg-*-2.4.0.dev6.txt`, `thu-tay-tests-pkg-dev6.txt`, `upgrade-dev11-to-dev6.txt`, `release/release-check.json` |
| 22:19–01:48 | Gate 2.2 trên `01b6f62`: 286/286, 2.097 test, 0 skip; `refused` với 23 problems trùng dev5 | `logs/gate-snapshot-01b6f62.txt`, `gates-tmp/wf-snapshot-gate-20261102-01b6f62/` |
| 03/11 01:49–01:50 | **Phát hành**: tag `v2.4.0.dev6` → `01b6f62`, push nhánh + tag lên origin private; verify đạt; không GitHub Release | `release/release-{tag,push,verify}.json` |
| 03/11 ~02:00 | Hồ sơ: báo cáo §11, mục này, wiki CURRENT + LL-42; commit docs, fast-forward, push nhánh | git |

Không đụng: gói/snapshot/receipt đã đóng băng (dev4, dev5, hotfix 2.3), nhánh `claude/onecrew-2.3-hotfix-auth` (`9e022fe`), runtime SDK `venv-23` (2.3.0.dev11), venv/hook/registry/sổ thật, cấu hình tài khoản; không reset/stash của phiên khác (OBS-1 chạy song song trên `wf-obs1`).

## 8. Quyết định vượt quyền và điều cần Codex hay chủ sở hữu

- **Không phát hành 2.4.** Không push nhánh, không tag, không publish gói 2.4 nào; không nâng runtime đang dùng (`%LOCALAPPDATA%\OneCrew`, venv và hook thật); không đọc/ghi `state-v2-real`. Phát hành là quyết định của chủ sở hữu sau Codex review.
- **Chưa chạy model thật.** Mọi bằng chứng dùng `claude` giả (`tests/v23_fake_claude.py`) và sổ tạm. Worker thật dùng đúng giao thức đọc nguồn, hiểu delta, đề xuất bước 0 đúng: chưa chứng minh.
- **Mở rộng schema hợp đồng:** khóa tùy chọn `authority.read` (authority.py). Hợp đồng không khai khóa này giữ nguyên; hợp đồng có khóa này bị wheel 2.3 từ chối (`authority: unknown fields read`), nên quay về 2.3 cần root không dùng nó. Cần Codex xem đây có phải đổi hợp đồng phải để chủ duyệt.
- **Task neo `support:records` hiện với bản cũ:** mới kiểm phần đọc. Wheel 2.2.0.dev18 và 2.3.0.dev10 thật chạy `plan show`, `compat scan`, `notifications pull` trên sổ có bản ghi S1 (`test_v24_s1_oldreaders`; review-s2 P3b). Chưa kiểm: bản cũ đọc bản ghi S2 (`support.install_*`), `knowledge.delivered`, `workflow.mode`; công cụ v1 cũ liệt kê task neo như một job (S1-R14).
- **Khóa mặc định của báo cáo** (S1-R08, reviewer ghi là việc của chủ sở hữu): đã chọn khóa theo nội dung, phiên bản và ảnh (§4) theo quyền tự quyết kỹ thuật; đây chưa phải quyết định của chủ.
- **Capability `execution-mode` trong fixture:** 7 bộ test 2.3 tạo root bằng `list(namespaces.CAPABILITIES)` nay chạy đường 2.4-C (C-R17); đường không capability giữ bằng test riêng và `OptIn`. Không sửa các test 2.3 đó.
- **Hai U1 hẹp trên nhánh 2.4,** theo mục 6 chỉ thị 01/11: `U1-20261101-V24-PIN-1` (`tests/test_g1_core.py`, một regex version) và `U1-20261101-V24-DEADLINE-1` (`tests/test_wf_metered_verifier.py`, cửa sổ hạn đo từ một lượt định danh; không bỏ assertion, không đổi guard runtime). Không cấp U1 nào khác; test ghim template `2.2.0.dev3` của `test_g2_install` không sửa.
- **Version:** hai gói thử cùng `2.4.0.dev1`, khác §2 ("mỗi gói alpha tăng N"). Gói bàn giao: `2.4.0.dev2` (`61862e6`); hai gói `2.4.0.dev1` trong `pkg-trial` là bản thử công cụ, không bàn giao.
- **Cần Codex hoặc chủ sở hữu:** Codex review gói cuối (danh sách điểm rủi ro ở báo cáo bàn giao); quyết định phát hành; thử với model thật trong quyền; nghiệm thu. Lượt này không ghi review hay nghiệm thu nào thay họ.
- **Vòng Codex 1 trên dev2 (02/11): không có việc mới nào ngoài quyền.** Cả bốn finding sửa được ngay trong quyền của lượt này và đã sửa. Việc của chủ sở hữu giữ nguyên: Codex review dev3; quyết định push/tag/phát hành; nghiệm thu. Test `test_g2_install` (ghim `2.2.0.dev3`) vẫn hỏng từ trước và không có U1; lỗi mới của code 2.4 không bao giờ ghi là ngoài quyền.
