# OneCrew 2.3 — bản beta 2.3.0.dev10: sau review Codex trên dev9, phát hành prerelease beta

Người viết: Claude (Opus 5.5), đầu mối triển khai 2.3, 31/10/2026 (bản dev9: 30/10/2026), theo chỉ thị người dùng tối 29/10 ("Tiếp quản công việc hiện tại, hoàn thành toàn bộ phạm vi OneCrew 2.3 đã chốt và phát hành bản 2.3 sau khi tự kiểm chứng đạt…"). Phạm vi: ba tài liệu chung bản Codex sửa 29/10 17:31–17:36 (roadmap §0.2, thiết kế và bàn giao mục wiki-init: WI-01…05) và [hợp đồng 2.3](HOP-DONG-2.3.vi.md) §10. Đây là **tự kiểm của tác giả và review của agent độc lập**, chưa phải Codex review lại hay nghiệm thu. Báo cáo trước: [BAO-CAO-2.3-DEV6](BAO-CAO-2.3-DEV6-2026-10-29.vi.md); gói dev6 không bàn giao, dev7 thay nó. Bản alpha `2.3.0.dev8` đã giao trước, theo chỉ thị 30/10 ~11:30 ("giao ALPHA dùng được sớm, rồi hoàn thiện BETA"; hồ sơ `ALPHA-2.3.0.dev8.vi.md`). Bản này là beta: thêm bản sửa B2 và gate 2.2 đầy đủ trên đúng snapshot của gói. Bản này xử lý review Codex trên beta `2.3.0.dev10` (`d35b810`), theo chỉ thị 31/10 ("Tiếp quản OneCrew 2.3 và xử lý các vấn đề Codex vừa review trên beta 2.3.0.dev10…"); đã đọc bàn giao chung Codex 31/10 (roadmap §0.8, thiết kế §2.9).

**Bản nào:** bản trong `docs/` của gói là bản lúc dựng gói. §1, §3 (kết quả), §5 (phần "sau") và §6 chỉ có ở bản trong checkout `D:\TamNT\Workspace\11.OneCrew\wf-v23\docs\v23\BAO-CAO-2.3-DEV10-2026-10-31.vi.md`, ghi sau khi kiểm. Gói không tự chứng nhận chính nó.

| | |
|---|---|
| Nhánh | `claude/onecrew-2.3`; push lên `origin` cùng tag khi phát hành (§1) |
| Version | `2.3.0.dev10`, prerelease **beta** theo quy ước `2.3.0.devN` của hợp đồng §1 |
| Gói | `D:\OneCrewRuns\v23\pkg\onecrew-2.3.0.dev10-beta` |
| Đích phát hành | tag `v2.3.0.dev10` và nhánh trên `origin` (`git@github.com:tamnguyendev/one-crew.git`, repo private), như các bản trước |

## 1. Đã phát hành loại bản nào, ở đâu

<!-- dev10:release -->
_Ghi sau khi kiểm gói (bản trong checkout)._

## 2. Người dùng dùng được gì

- **Từ alpha `2.3.0.dev8`:** ảnh chụp phạm vi node cho worker và trình đọc wiki không đọc file có tên khác trên đĩa (hard link), symlink hay junction (AL-01, AL-02): node không chạy, trang không được đọc, kèm lý do. Trước đó nội dung một `.env` có thể vào prompt của worker. Script thử một lệnh chạy thêm luồng alpha 5 chặng (init và wiki, tri thức cho task, kết quả đã kiểm thành tri thức, root mới dùng lại, guard hard link) và để lại `feedback-alpha.zip`.
- **B2 (beta):** các lệnh chỉ xem trạng thái (`plan show`, báo cáo, so evidence, handoff) không còn băm nội dung tên có hard link hay nằm sau junction: chỗ đó trong cây là một marker làm từ size, thời điểm sửa và file id, nên artifact đổi vẫn thấy đổi mà nội dung không vào kho object của repo.
- **Sau review Codex trên dev9 (P1):** một file đổi thành hard link hay một thư mục đổi thành junction giữa lúc OneCrew kiểm và lúc đọc không còn lọt vào kho Git, kho snapshot, cây bàn giao hay trang wiki. Git không tự duyệt cây làm việc khi tính danh tính: mỗi file được mở, xét trên handle và giữ mở trong lúc `git update-index` đọc.
- **Sau review Codex trên dev9 (P2):** gate tách đạt, hỏng, bỏ qua, expected failure, unexpected success; expected failure không được tính là đạt.

- **Wiki ngay khi init (2.3-A1, WI-01…05).** `onecrew init` tạo khung `docs/wiki/` gồm `README.md` (cách viết), `project.md` và `lessons.md`. Nếu đã có wiki, thư mục `wiki.paths` hay wiki dùng chung qua link đã có trang, init dùng lại. Chạy lại không đổi byte nào. Init không ghi đè, không ghi ra ngoài repo hay qua link, không ghi vào `.git`/`.onecrew`/`.claude` dù viết tên theo cách nào. `config.json` hỏng thì init dừng và không ghi gì (bản trước ghi đè nó). Khung không sinh mục tri thức nào. Hướng dẫn: `docs/HUONG-DAN-WIKI.vi.md` §0.
- **Đọc và giao tri thức (2.3-A1).** Worker của engine nhận gói tri thức có nguồn từ wiki và sổ, theo quyền đọc của node, độ liên quan và trần. Mục bắt buộc không bị cắt âm thầm. Worker đọc tiếp bằng con trỏ. Receipt niêm phong đúng gói đã giao. Lệnh: `onecrew wiki show|read|pages`.
- **Ghi tri thức có bằng chứng và dùng lại qua root mới (2.3-A2).** Khi check của node chứng minh được một điều, điều đó được ghi cho project. Root mới, process mới dùng lại. Sửa, thay thế, thu hồi, lưu trữ có hiệu lực ở lần truy xuất sau. Cập nhật đồng thời không mất bản nào. Chủ thể tri thức thuộc project đã ghi: hai project cùng `--key` là hai chủ thể. Lệnh: `onecrew wiki record|withdraw|archive|summarize|export|history`.
- **Dọn và tiếp quản (2.3-B).** Controller `engine step` chết thì `onecrew executor recover` xác nhận đã dọn trước. Bước sau giữ node, chạy lại đúng một lần trong ngân sách cũ.
- **Việc cũ.** Project đã `init` bằng 2.2: chạy `onecrew init` của bản này một lần. Sổ, config, plan, ngân sách giữ nguyên; hook được trỏ sang lệnh mới; khung wiki được thêm. Plan duyệt và chạy dở bằng 2.2 được bản này chạy tiếp (bước V16 của bộ kiểm). Quay về 2.2 bằng wheel trong gói (§4).
- **Hook và plan lint** (sửa của beta R15, như bản `2.2.0.dev19`): `Remove-Item Env:X -ErrorAction SilentlyContinue` không còn bị coi là ghi file; `<`, `>`, `|` trong chuỗi có dấu nháy không còn bị đọc là chuyển hướng; `plan lint` nói rõ `budget.max_calls` không được đếm cho phiên AI dưới hook; hook Stop nhắc một lần khi mốc chờ chủ sở hữu và không bảo chạy lại verdict không thể đổi.
- **Sửa lỗi** từ các lượt Codex review (dev2, dev3, dev5) và từ verifier:
  - mẫu `ids` có neo hay cờ; với `(?i)` hai id chỉ khác chữ hoa/thường là một id; kiểm `ids` không thấy id nào thì không đạt (trước đây đạt mà không kiểm gì);
  - tên ngắn 8.3 bị từ chối ngay lúc đề xuất; thư mục không Git có `.env` định danh được;
  - file bị cấm không bị đọc dưới tên khác: với artifact Git, một tên trong cây làm việc là hard link hoặc đi qua junction (kể cả tên trong index thật và trong `.onecrew`) làm dừng lượt kiểm và làm lệnh duyệt plan dừng, nêu lý do, trước khi Git đọc nội dung (trước đây nội dung `.env` hay của `~/.ssh` có thể vào receipt và cây được ghim);
  - nguồn viết trần (`- [S1] ../x.md — …`) giữ dấu chấm đầu, và `./x`, `../x` chỉ tính cạnh trang: nguồn thiếu không còn đạt nhờ file cùng tên ở gốc repo (lỗi có từ 2.2).

  Tri thức: yêu cầu đọc tiếp qua nâng cấp giao đúng chủ thể; mục 2.2 khóa `lesson-` không trùng lesson thật; `wiki history` không lộ mã project khác; thu hồi được mục ở trang ngoài ngân sách đọc. Thêm `onecrew --version`.

## 3. Kết quả kiểm và giới hạn còn lại

### 3.0 Tóm tắt

- **Kiểm từ gói `2.3.0.dev10`** (snapshot `fb3333b`, wheel `8ab065c3…`): bộ kiểm 16/16; README 9/9; task đầu tiên 25/25 bước bắt buộc; script thử một lệnh in `DAT` và thoát 0, chạy lại vào cùng thư mục thì từ chối, thoát 2.
- **Phản chứng qua CLI cài:** init tạo wiki (V15): wheel gói dev6 11 lỗi → wheel dev10 0; ca của Codex dev5: wheel dev5 14 + 4 lỗi → wheel dev10 0.
- **P1 trên wheel cài, không phải checkout:** 22 test race và 13 test danh tính của snapshot chạy với `onecrew` nhập từ một venv cài wheel: wheel dev9 race FAILED (failures=13, errors=5, skipped=1) → wheel dev10 race OK (skipped=1), danh tính OK (r16 chỉ chạy trên POSIX nên bỏ qua ở đây). Phía dev9: 5 lỗi là vì bản đó không có bước giữ file mà test móc vào; bằng chứng đỏ chính của P1 là ca tái hiện trên source `d705001` (§7). Nơi nạp `onecrew` (venv, không phải checkout) ghi ở `wheel-where.json`: dòng kiểm của `wheel_tests.py` tách đường dẫn có dấu cách nên ghi sai, test không bị ảnh hưởng.
- **Dữ liệu và việc cũ:** sổ do wheel dev5 ghi được wheel dev10 đọc và dùng tiếp, rồi wheel 2.2 đọc được; plan 2.2 chạy dở được 2.3 chạy tiếp (V16).
- **Hồi quy trên snapshot `fb3333b`:** 565 test 2.3 và 467 test của 24 module 2.2 (11 ngoài gate, 13 dùng kho snapshot nhiều nhất); 56 module 2.2 khác chạm vùng sửa chạy trong gate trên cùng snapshot (§3.5); 4 module gate không chạy được chạy riêng trên snapshot: 49 chạy, 49 đạt. Hai lỗi của hồi quy 2.2 đều có từ trước: một test ghim version, một lỗi môi trường của phiên này (§3.4).
- **Gate 2.2 trên `fb3333b`:** 286/286 check đạt; quyết định `refused` chỉ vì 23 khoảng trống nghiệm thu như beta.

### 3.2 Gói

`D:\OneCrewRuns\v23\pkg\onecrew-2.3.0.dev10-beta`: 47 file (46 dòng `SHA256SUMS` + chính nó), dựng 2026-10-31 14:21:23 từ snapshot `fb3333b` bằng `docs/v23/tools/build_milestone.py` trong checkout tách riêng `wf-v23-dev4`. `manifest.json`: version `2.3.0.dev10`, commit `fb3333ba1f27`, wheel `onecrew-2.3.0.dev10-py3-none-any.whl` SHA256 `8ab065c3bc6d2863888314952e3743b031d44ea44c1e92cd740abba385a1b4f7`, wheel quay về `onecrew-2.2.0.dev18-py3-none-any.whl` SHA256 `0346577e…ef9bd2` (giống từng byte gói beta), `claims` đều `false`. Gói dev5 và dev6 giữ nguyên (39/39 và 41/41 dòng `SHA256SUMS` khớp sau khi làm).

### 3.3 Kiểm từ gói

- **Bộ kiểm — 16/16** (14:21–14:27, `python -I`, thư mục `D:\OneCrewRuns\v23 thu dev10\verify` ngoài checkout và có dấu cách, `LOCALAPPDATA`/`APPDATA` riêng; báo cáo `D:\OneCrewRuns\v23 thu dev10\verify\verify-report.json`). V1–V14 như dev6. Mới:
  - **V15 init-wiki:** `pass`. CLI của wheel cài: repo mới có khung 3 trang và 0 mục; init lần hai không đổi byte; dùng lại wiki đã có, thư mục `wiki.paths`, nhiều thư mục; từ chối `config.json` hỏng, junction ra ngoài, file ở chỗ thư mục mà không ghi gì; hoàn tất khung dở; giữ trang khung đã sửa; project 2.2 init lại giữ sổ, config và hook.
  - **V16 old-work:** `pass`. Plan được duyệt và chạy dở bằng wheel 2.2, nâng lên wheel này, `init` lại, rồi chạy tiếp tới hết; sự kiện cũ giữ nguyên từng byte; `compat scan` của 2.3 như của 2.2.
- **README của gói — 9/9** (log `D:\OneCrewRuns\v23 drill dev10\drill.txt`): hash khớp, bộ kiểm 16/16, venv có dấu cách + cài wheel + `--help` có `wiki`, quay về `2.2.0.dev18`, lên lại `2.3.0.dev10`.
- **Task đầu tiên từ gói — 25/25 bước bắt buộc** (+ 2 bước chỉ ghi thông tin; log `D:\OneCrewRuns\v23 task dau tien dev10 ai\drill\first-task-drill-log.json`). Có bước `init` (khung wiki do init tạo) và `wiki-empty` (khung không sinh mục); mục người dùng thêm sau đó được giao cho node có quyền. Chạy trong phiên AI: bước duyệt plan `onecrew owner approve` được thay bằng fixture có nhãn (`owner_step_mode=fixture`); không phải hành động của chủ sở hữu.
- **Script thử một lệnh** (`verify\thu-goi.ps1`, 14:34–14:41, thư mục mới `D:\OneCrewRuns\v23 thu script dev10 claude`): `DAT: goi 2.3.0.dev10 qua bo kiem 16/16 buoc, task dau tien tu goi 25/25 buoc bat buoc va luong alpha 5/5 chang (buoc duyet plan: fixture). Day khong phai nghiem thu.`, thoát 0; log `D:\OneCrewRuns\v23\beta2\logs\wrapper-dev10.txt`. Chạy lại vào cùng thư mục: `KHONG DAT`, "Chua chay gi", thoát 2; log `D:\OneCrewRuns\v23\beta2\logs\wrapper-dev10-reuse.txt`.
- **Phản chứng init qua CLI cài, cùng oracle V15 của gói:** wheel gói dev6 (`f4819c5a…`, chưa có wiki khi init) 11 lỗi; wheel gói dev10 0 lỗi. Kết quả `D:\OneCrewRuns\v23\beta2\pair v15 dev6\v15-pair.json`, `D:\OneCrewRuns\v23\beta2\pair v15 dev10\v15-pair.json`.
- **Ca của Codex dev5 qua CLI cài:** cùng kịch bản `scenario_codex.py` như lần đỏ trên wheel dev5 (BAO-CAO-2.3-DEV6): wheel dev5 collision 14, docverify 4, general 0 lỗi; wheel dev10 0, 0, 0 (module nạp từ `site-packages`). Kết quả `D:\OneCrewRuns\v23\beta2\cli green dev10 package\cases-cli.json`.
- **Dữ liệu cũ:** sổ tạm hai project ghi bằng wheel dev5, đọc và dùng bằng wheel dev10, rồi đọc bằng wheel 2.2: `pass`. Kết quả `D:\OneCrewRuns\v23\beta2\compat dev5 ledger dev10 package\compat-dev5-ledger.json`.

### 3.4 Hồi quy

Môi trường như gate (bỏ `CLAUDECODE`, `CLAUDE_CODE_CHILD_SESSION`; `TEMP`, `LOCALAPPDATA`, `APPDATA` của lượt chạy), các lượt nối tiếp, không chạy chồng:
- Mọi module `tests/test_v23_*` trên snapshot `fb3333b`: 565 chạy, 553 đạt, 10 bỏ qua, 2 lỗi đã biết (expected failure), 12:41–13:22; log `D:\OneCrewRuns\v23\dev7\logs\int-v23-fb3333b.txt`. 10 test bỏ qua vì điều kiện máy (không có phiên Windows thứ hai, không có quyền tạo symlink, ổ không có tên 8.3).
- 24 module 2.2 (11 chạm vùng sửa mà gate không chạy: install, plan, verifier, lint, snapshot; 13 dùng kho snapshot nhiều nhất), trên snapshot `fb3333b`: 467 chạy, 465 đạt, 2 hỏng, 13:22–14:19; `test_native_owned_runner_survives_launcher_and_cancel`: lỗi môi trường: phiên AI này không cho tạo process tách khỏi Job object (`Access is denied`); hỏng y hệt trên `6cbcaa9`, log D:\OneCrewRuns\v23\alpha\logs\owned-6cbcaa9.txt; không tính là đạt; `test_the_templates_are_package_data_and_the_examples_keep_a_copy`: ghim `version = "2.2.0.dev3"` từ bản 2.2.0.dev3; hỏng y như vậy trên beta `2.2.0.dev18` (`34eb7c4`) và trên `4bb41b3`, log D:\OneCrewRuns\v23\dev7\logs\pin-g2-install.txt; không thuộc gate; log `D:\OneCrewRuns\v23\dev7\logs\int-22-fb3333b.txt`. 56 module 2.2 khác chạm vùng sửa có trong gate: chúng chạy một lần, trên snapshot, trong gate (§3.5), không chạy lại ở đây. 4 module tưởng có trong gate mà gate không chạy (`tests.test_v2_report`, `tests.test_wf_compat_scan`, `tests.test_wf_packaging`, `tests.test_wf_plan_names`) được chạy riêng trên snapshot: 49 chạy, 49 đạt, log `D:\OneCrewRuns\v23\dev7\logs\int-22c-fb3333b.txt`; lượt alpha và các lượt trước không chạy chúng. Bỏ `tests.test_v2_reviewer` (gọi Claude thật khi có `claude.exe`).
- Lượt trước trên `1c09994` (trước hai bản sửa cuối: `3f3edb7` của verifier tài liệu, `01c5831` race `.onecrew`): 504 test 2.3 `OK (skipped=9, expected failures=3)`, 361 test 2.2 với cùng một test ghim version hỏng; log `D:\OneCrewRuns\v23\dev7\logs\int-v23-1c09994.txt`, `D:\OneCrewRuns\v23\dev7\logs\int-22-1c09994.txt`.
- Lượt đầu trên `4f6a707` (trước bản sửa DX và các bản sửa sau review verifier): 460 test 2.3 `OK (skipped=8)`, 965 test 2.2 với cùng một test ghim version hỏng; log `D:\OneCrewRuns\v23\dev7\logs\int-v23-4f6a707.txt`, `D:\OneCrewRuns\v23\dev7\logs\int-22-4f6a707.txt`.

### 3.5 Gate snapshot 2.2

Lượt được tính là lượt thứ hai: 31/10 23:06 – 01/11 02:02 (2 h 56 m), chạy một mình. Lệnh `wfkit.development_gate snapshot` trên commit `fb3333b` trong worktree tách riêng.
- Kết quả: `D:\OneCrewRuns\v23\gates-tmp\wf-snapshot-gate-20261031-fb3333b-run2`; log lệnh `D:\OneCrewRuns\v23\dev7\logs\gate-snapshot-fb3333b-run2.txt`.
- **Lượt gate thứ nhất trên cùng snapshot, giữ nguyên, không tính:** 31/10 14:52–22:49, `D:\OneCrewRuns\v23\gates-tmp\wf-snapshot-gate-20261031-fb3333b`, log `D:\OneCrewRuns\v23\dev7\logs\gate-snapshot-fb3333b.txt`. 286/286 check có receipt, 283 đạt; 3 check hỏng (`R04`, `R05`, `RP` `check.metered_verifier`) là một lượt chạy module `tests.test_wf_metered_verifier`: test `test_root_deadline_blocks_command_before_dispatch_and_caps_a_running_command` cho 2 giây từ lúc đặt hạn tới lúc chạy lệnh, và hạn đã hết trước khi lệnh chạy (`LedgerError: The original root deadline elapsed before verifier command dispatch`); 2 096/2 097 test đạt, 1 lỗi. Máy lúc đó chậm: tổng thời gian các module 7.9 h, gate dev9 3.8 h.
  - Tải máy: Nguyên nhân máy chậm trong lượt 1 không xác định hết. Tìm thấy 13 vòng chờ `until ...; do sleep 3–5; done` của chính phiên này (27–28/10, chờ file không bao giờ có dòng cần chờ) vẫn chạy, mỗi vòng mở tiến trình mới mỗi vài giây (chúng cũng đã chạy trong gate dev9 30/10, khi máy nhanh hơn), và tiến trình chờ của một lượt test race lúc 11:59 bị bỏ lại; ngoài ra là tải của các ứng dụng khác trên máy. Đo sau gate, trước khi dừng chúng (chỉ có trên màn hình, file đo bị lượt đo sau ghi đè): `git -C <repo> rev-parse` trung vị 0,12 s, p90 0,78 s; test hạn 2 giây hỏng 3/3 lần trên dev9 và 3/3 trên dev10; bước lấy danh tính trước khi chạy lệnh trên fixture của test mất 1,2–7,8 s mỗi lần trên cả hai bản (dev9 13 lệnh git, dev10 15). Dừng các tiến trình đó lúc 23:01 (chỉ tiến trình của phiên này; tiến trình của ứng dụng khác không đụng); đo lại: trung vị 0,04 s, p90 0,06 s.
  - Đối chứng sau khi dừng các vòng chờ đó, cùng máy, chạy xen kẽ: dev9 `d35b810` đạt 7/8, dev10 đạt 6/8 lần (`D:\OneCrewRuns\v23\beta2\probe-mv\ab-20261031-2306.json`). Test không sửa (đã khóa, không có U1); không ghép receipt: lượt hai chạy lại toàn bộ gate trên cùng snapshot. Trước khi chạy lệnh, dev10 gọi git 15 lần để lấy danh tính, dev9 13 lần (chi phí P1 đã ghi trong giới hạn).
- **Snapshot:** `intact: true`; build `dirty: []`; Python 3.13.15.
- **Check:** 286/286 có receipt, `failed: []`; 217 lượt chạy module khác nhau, 2 097 test đạt, 0 skip, 0 lỗi. Mọi receipt mang commit `fb3333b` và wheel của gate.
- **Wheel của gate và wheel của gói:** wheel của gate `e92a78d32b484279dc86691182478629eec7c6e417ddfd8c066b8722dc778ff5`, wheel của gói `8ab065c3…`; cùng commit và version; 132/132 file bên trong giống từng byte (khác về byte ở thời điểm nén).
- **Nguồn thực thi, tách riêng:** (a) 217 lượt unittest của gate chạy mã nguồn của snapshot bằng Python hệ thống (`wfkit/gate.py` đặt `PYTHONPATH` và `cwd` vào checkout của snapshot): đây là hồi quy trên source; (b) 22/217 lượt trong đó có ghi nhận dùng wheel của gate (`wheel_used`); các lượt còn lại không có ghi nhận đó, không có nghĩa là hỏng; (c) bước cài riêng của gate: module nạp từ venv của gate, bản checkout bị từ chối đúng như đối chứng; kiểm trên package và CLI đã cài là §3.3; (d) mọi worker là fixture (`claude` giả), không có provider thật.
- **Đếm:** 2 097 đạt trên 2 097 test chạy; 0 bỏ qua, 0 expected failure, 0 unexpected success (bộ đếm mới ghi riêng từng loại, receipt nào cũng có hai trường mới).
- **Tự kiểm tài liệu T38a:** đạt, 155 phản chứng và 18 đối chứng.
- **kit-guard: đạt.** Ngoại lệ U1 được dùng: `U1-20261029-V23-PIN-1`, `U1-20261029-V23-PIN-2`, `U1-20261029-V23-PIN-3`, `U1-20261031-V23-GATECOUNT-1`, `U1-20261031-V23-GATECOUNT-2`, `U1-20261031-V23-GATECOUNT-3` (`U1-20261029-V23-PIN-1..3` cho ba file ghim như dev5; `U1-20261031-V23-GATECOUNT-1..3` cho bộ đếm của gate, quyền chủ sở hữu 31/10 chỉ cho P2); namespace lineage đạt.
- **Quyết định gate: `refused`, 23 vấn đề**, đều là khoảng trống nghiệm thu: 13 `acceptance-partial` và 10 `acceptance-blocked`, giống từng chữ gate beta. "Check thực thi đạt" khác quyết định cuối của gate.

### 3.1 Giới hạn còn lại (đã ghi, không tính là đã khép)

- **Bản thử:** chưa nghiệm thu, chưa pilot thật, chưa Codex review lại. 23 khoảng trống nghiệm thu, pilot và provider của 2.2 giữ nguyên.
- **Worker giả:** diễn tập dùng `claude` giả. Nó chứng minh đường đi, nhãn và receipt, không chứng minh model thật hiểu wiki. Phần B (model thật) của task đầu tiên chưa chạy trong lượt này.
- **Init và wiki:** vẫn còn một khoảng rất ngắn giữa lần xét đường dẫn cuối và lúc tạo file; một junction đổi vào đúng lúc đó không bị chặn. Mục 2.2 ghi đúng khóa `lesson-<mã>` của lesson general của project khác thì lấy id của lesson đó (phải biết trước mã băm). Chi tiết: `docs/HUONG-DAN-WIKI.vi.md` §7.
- **Verifier:**
  - artifact Git có một tên là hard link hoặc đi qua junction: lượt kiểm doc/data/ops/command bị từ chối kèm lý do (reviewer: `inconclusive`; link xuất hiện trong lúc kiểm: receipt `inconclusive` có lý do), và `plan approve` bị từ chối, thay vì chỉ báo "chưa kiểm" file đó rồi kiểm tiếp. Từ chối cả khi plan không có mốc nào đọc cây (chỉ owner-manual), và cả repo cố ý giữ hai file trùng bằng hard link. Cách xử lý: thay link bằng bản sao (hoặc đưa ra khỏi cây làm việc) rồi chạy lại;
  - các lệnh chỉ xem trạng thái (`plan show`, báo cáo) và verifier: tên có hard link hay nằm sau junction là marker từ size, thời điểm sửa và file id (B2); marker giả được bằng một file thường có đúng nội dung đó, và đổi nội dung mà giữ nguyên size và thời điểm sửa thì không thấy (chỉ ảnh hưởng các lệnh xem: verifier từ chối cây có link). Khe giữa lúc xét và lúc git đọc đã đóng (P1): git chỉ đọc file đang được giữ handle; trong khoảnh khắc đó một file đang giữ không đổi tên hay xóa được (công cụ lưu bằng cách thay file có thể báo lỗi); trên POSIX tên không khóa được, chỉ kiểm lại dev/ino. `.gitignore` nằm sau junction vẫn được git đọc khi liệt kê. Thư mục không Git có hard link thì định danh bị từ chối, kèm lý do;
  - một clean filter trong `.git/config` có thể đưa nội dung khác vào cây (có từ 2.2; cần sửa cấu hình của repo, nơi worker không được ghi);
  - thư mục không Git: một hard link bất kỳ làm dừng định danh, kèm lý do (từ `2.3.0.dev8`, AL-01; trước đó chỉ khi thư mục có tên bị cấm); `.onecrew` không được đọc như trước; junction nằm sâu trong một thư mục bị cấm (sau file đầu tiên) không dừng định danh, không có gì được đọc qua nó;
  - kiểm `ids` trên tài liệu chưa có id nào thì không đạt, kể cả với plan đã duyệt trước bản này (thay đổi hành vi): bỏ kiểm `ids` khỏi mốc hoặc thêm id; với `(?i)` ở đầu mẫu, id được so theo chữ thường như cờ của regex, còn `(?i:..)` trong mẫu thì so đúng như viết;
  - mẫu `ids` có neo nằm trong nhóm lựa chọn (`(?:^|\W)REQ-\d+`) đọc cả ký tự đứng trước vào id, nên báo sai "id chưa định nghĩa" (không bao giờ đạt sai): viết `\bREQ-\d+`; mẫu có backreference đánh số, hay có cờ giữa mẫu, bị từ chối lúc đề xuất (thông báo nêu cách viết lại); mẫu `^\s+REQ-\d+` báo lỗi rõ thay vì đạt rỗng;
  - file thật có tên dạng 8.3 (`data~1.csv`) không khai được trong hợp đồng;
  - nguồn viết trần không có `./`, `../` (như `README.md`) được tìm cạnh trang, không có thì ở gốc repo: viết `./README.md` để chỉ tính cạnh trang. Dòng nguồn không có link mà có đường dẫn (từ đầu dòng có `/` hay có đuôi file, hoặc một từ sau có `/`, hoặc một tên có đuôi file) thì OneCrew kiểm đúng đường dẫn đó, kể cả khi dòng còn nhắc tên khác; dòng không có đường dẫn nào thì thử lần lượt các từ bắt đầu bằng dấu chấm (`.env`, `.gitignore`) và lấy cái có thật, không cái nào có thật thì báo cái đầu tiên là không thấy.
- **Ảnh chụp phạm vi node cho worker và trình đọc wiki:** không đọc file có hard link, symlink hay junction; từ `2.3.0.dev10` một file hay trang được xét trên đúng handle đọc nó (đường dẫn thật phải là đường dẫn đã xét), kể cả khi thư mục đổi thành junction sau lúc liệt kê.
- **Test hạn 2 giây của verifier đo giờ (`tests.test_wf_metered_verifier`, test đã khóa):** nhạy với tải máy. Trên máy này, khi tải cao, nó hỏng trên cả dev9 lẫn dev10 (gate lượt 1, §3.5); dev10 gọi git 15 lần trước khi chạy lệnh, dev9 13 lần. Không sửa test; gate được tính là lượt chạy lại toàn bộ trên máy đã dọn.
- **Gói tiếp tục niêm phong bởi bản dev1–dev5** (bản test, chưa phát hành): yêu cầu đọc tiếp được giải theo tiêu đề. Không giải được thì bị từ chối, không giao nhầm chủ thể.

## 4. Lệnh cài và bài thử ngắn

Một lệnh làm cả bốn việc: kiểm hash, chạy bộ kiểm 16 bước, chạy task đầu tiên và luồng alpha 5 chặng trên thư mục mới với sổ tạm. Đạt khi in `DAT:` và thoát 0:

```powershell
powershell -ExecutionPolicy Bypass -File "D:\OneCrewRuns\v23\pkg\onecrew-2.3.0.dev10-beta\verify\thu-goi.ps1"
```

Cài vào venv thử và khởi tạo một bản sao project:

```powershell
$py = "C:\Users\NUC\AppData\Local\Programs\Python\Python313\python.exe"; $pkg = "D:\OneCrewRuns\v23\pkg\onecrew-2.3.0.dev10-beta"
$venv = "D:\OneCrewRuns\v23 thu beta2\venv"; & $py -m venv $venv; & "$venv\Scripts\python.exe" -I -m pip install --no-index --no-build-isolation "$pkg\wheel\onecrew-2.3.0.dev10-py3-none-any.whl"
& "$venv\Scripts\onecrew.exe" --version
& "$venv\Scripts\onecrew.exe" init --project "<bản sao project>" --yes
& "$venv\Scripts\onecrew.exe" --project "<bản sao project>" wiki pages
```

Quay về 2.2: `& "$venv\Scripts\python.exe" -I -m pip install --no-index --no-build-isolation --force-reinstall "$pkg\wheel\previous\onecrew-2.2.0.dev18-py3-none-any.whl"`. Wheel này giống từng byte wheel của gói beta. 2.2 đọc được sổ do 2.3 ghi trong phạm vi bước V7 đã diễn tập. Ngoài phạm vi đó không có cam kết quay về dữ liệu.

## 5. Beta 2.2 và công việc đang chạy

- **Trước khi làm (29/10 17:05):** gói `D:\OneCrewRuns\wf-handover-34eb7c4-hs2` khớp 687/687 dòng `SHA256SUMS`; `hook-projects.json` thật có SHA256 `884335df…`; checkout `wf-codex` ở `1753f77`, sạch.

- **Sau khi làm (02:03 01/11):** gói `D:\OneCrewRuns\wf-handover-34eb7c4-hs2` 687/687 dòng `SHA256SUMS` khớp, 0 file sửa sau 28/10 13:30; `hook-projects.json` thật SHA256 `884335df…` như lúc 17:05, sửa lần cuối 30/10 02:35 (lần khôi phục thứ hai, bên dưới); checkout `wf-codex` ở `1753f77` như lúc 17:05 (thay đổi trong đó là của phiên khác, tôi không đụng vào).
- **Bằng chứng dev5 của chủ sở hữu:** thư mục `D:\OneCrewRuns\v23 thu cua anh dev5 20261029-155825` không có file nào ghi sau 16:02 29/10.
- **Việc đang chạy:** không dừng, không đổi tiến trình của phiên khác; không đọc/ghi sổ `state-v2-real`; không đổi PATH, cấu hình provider, hook đang dùng.

- **Hai lần ghi nhầm vào sổ đăng ký hook thật, đã khôi phục từng byte:**
  - 29/10 21:39: một lượt chạy `tests.test_g2_install` + `tests.test_v2_trust_fixes` do tôi chạy, không đặt `LOCALAPPDATA` riêng, thêm vào `%LOCALAPPDATA%\OneCrew\hook-projects.json` một mục trỏ vào thư mục tạm `v23\dev7\tmp-wi`. Agent R15 phát hiện; 23:00 tôi bỏ đúng mục đó.
  - 29/10 23:25: một probe của agent review WI cũng chạy không có `LOCALAPPDATA` riêng và thêm một mục trỏ vào `v23\review-dev7\tmp`. Tôi phát hiện lúc 30/10 02:35 khi đối chiếu SHA256 và bỏ đúng mục đó ngay (bản lỗi và biên bản: `D:\OneCrewRuns\v23\dev7\incidents`).
  - Sau mỗi lần, file trở lại đúng 636 byte, SHA256 `884335df…` như lúc 17:05; chỉ thời gian sửa file đổi. Hai mục thừa trỏ vào thư mục tạm đã xóa. Sổ này chỉ dùng để hook tìm state root khi project mất `config.json`; các mục của project thật trong đó không đổi.
- **Một lần gọi Claude thật ngoài ý muốn:** 30/10 ~01:51, agent sửa verifier chạy hồi quy có `tests.test_v2_reviewer`. Test `RealCliTests` của module đó gọi Claude CLI thật khi máy có `claude.exe`: một lần, `claude-haiku-5-5`, đăng nhập subscription, CLI tự báo chi phí ước 0,066 USD. Việc này ngoài yêu cầu "không gọi model" của lượt; thư mục rỗng mà lần gọi tạo trong `~/.claude/projects` đã gỡ. Gate không chạy module này; các lượt hồi quy sau bỏ nó ra.

## 6. Quyết định vượt quyền

- **Cần chủ sở hữu (ngoài quyền phát triển):**
  - Ngoại lệ U1 cho các test 2.2 đã khóa, nếu muốn sửa: `tests.test_v2_reviewer.RealCliTests` tự gọi Claude thật khi có `claude.exe` (B5); `test_g2_install`, `test_v2_trust_fixes` ghi sổ hook thật khi chạy không cô lập (B4). B3 (bộ đếm gate) đã khép trong lượt này bằng U1 `GATECOUNT` theo quyền 31/10. Lượt này không tự cấp U1 nào khác; test hạn 2 giây của `test_wf_metered_verifier` (§3.5) không sửa.
  - Codex review lại gói `2.3.0.dev10`, rồi nghiệm thu nếu muốn. Lượt này không tự ghi nghiệm thu.
  - Phần B của task đầu tiên và luồng alpha với Claude thật: bước duyệt plan `onecrew owner approve` là hành động của chủ sở hữu trong terminal của mình (lệnh ở `README.md` của gói).
  - Nhãn ổn định `2.3.0` cần thêm nghiệm thu, pilot thật và provider thật đầy đủ (23 khoảng trống của 2.2 vẫn mở).
- **Không cần quyết định thêm** cho bản beta này: version, tag và đích phát hành theo hợp đồng §1 và §10.5, như alpha `v2.3.0.dev8`.

## 7. Truy vết yêu cầu → code → test → bằng chứng

| Yêu cầu (hợp đồng §10) | Code | Test (số test) | Bằng chứng từ gói |
|---|---|---|---|
| KW-01…KW-12 (WI-01…03): init tạo hoặc dùng lại wiki, từ chối an toàn, khung không sinh mục | `onecrew/v2/install.py` (`wiki_plan`, `_path_problem`, `write_wiki`), `messages.py`, `wiki.py`, `cli.py` (`--version`) | `tests/test_v23_wiki_init.py` (18), `tests/test_v23_review_dev7.py` (34), `tests/test_v23_review_dev7_delta.py` (18) | V15 (repo mới, dùng lại, chạy lại, từ chối); task đầu tiên: bước `init`, `wiki-empty`, rồi mục người dùng thêm được giao |
| KW-13, KW-14 (WI-05): project 2.2 init lại; cài wheel không đổi project | `install.py` (đường init có sẵn) | `tests/test_v23_wiki_init.py` | V15 (project 2.2), V16 (plan 2.2 chạy dở, nâng cấp, 2.3 chạy tiếp) |
| KW-15 (WI-04): root A ghi, root B mới dùng lại | sổ (có sẵn) | KB-12 (`test_v23_a2_*`) | V8 |
| KN-1…KN-4: tri thức qua nâng cấp, khóa `lesson-`, `wiki history`, thu hồi ngoài ngân sách đọc | `onecrew/v2/knowledge.py`, `context.py` | `tests/test_v23_open_knowledge.py` (7), `tests/test_v23_review_dev7*.py` | hồi quy; V12–V14 (đường cũ không đổi) |
| R15 B1, B2, B4, B6: hook, plan lint | `onecrew/v2/hook_cli.py`, `active_plan.py`, `lint.py`, `plan_cli.py` (giống từng byte `e432be2`) | `tests/test_v23_r15_hooks.py` (14) | hồi quy (test này chưa thuộc gate: `wfkit` không đổi) |
| FX-1…FX-4: verifier | `onecrew/v2/verifiers/doc.py`, `port.py`, `data.py`, `ops.py`, `artifact.py`, `onecrew/snapshots.py` | `tests/test_v23_open_verifier.py` (65) | hồi quy; gate (các check verifier của 2.2); V14 |
| DX: nguồn viết trần giữ dấu chấm đầu | `onecrew/v2/verifiers/doc.py` (`_entries`) | `tests/test_v23_doc_locators.py` (7) | hồi quy; gate (các check verifier tài liệu của 2.2) |
| Review verifier: FX-R01 hard link trong artifact Git, FX-R02 kiểm `ids` không thấy id, FX-R04 `(?i)`, FX-R05 tên không phải Unicode, DX-R01 `./x`, DX-R02 chữ có dấu chấm; soát lại: D-R01 trạng thái mốc, D-R02 duyệt plan, D-R03 junction, D-R04 index thật, D-R05 `.onecrew` và lần định danh sau, D-R06, D-R08, D-R09; lần soát sau: E-R01 kết quả lượt kiểm được giữ, E-R02 chỉ junction, E-R04 tên dài, E-R05 chọn đường dẫn có thật, F-R01 dòng có đường dẫn thì kiểm đúng đường dẫn đó | `onecrew/v2/verifiers/command.py` (`hard_links`, `refuse_hard_links`, `verified_sha`, `_lstat`), `artifact.py` (`verified_identity`), `port.py`, `reviewer.py`, `doc.py` (`_bare_candidates`), `onecrew/v2/plan.py` (duyệt plan) | `tests/test_v23_review_fx.py` (37: 3 expected failure cho FX-R03, FX-R06, FX-R08) | hồi quy; gate |
| Race `.onecrew` khi tính artifact (gate trên snapshot thứ nhất `c6d8477`) | `onecrew/v2/verifiers/command.py` (`artifact_sha`, `tracked_tree`: `git rm --cached -f` trên index tạm) | `tests/test_v23_review_fx.py` OnecrewRace; `tests/test_wf_t41_gaps.py` | gate (`R03/check.t41_gaps`) |
| AL-01: ảnh chụp phạm vi node không đọc file có tên khác trên đĩa (blocker alpha) | `onecrew/snapshots.py` (`_alone`) | `tests/test_v23_alpha_links.py` a01–a06; `tests/test_v23_review_fx.py` x04 (FX-R06 khép); `tests/test_v23_open_verifier.py` hai đối chứng theo quyết định mới | luồng alpha S5 (đỏ trên gói dev7, xanh trên gói này) |
| AL-02: trình đọc wiki không theo link, junction, hard link (blocker alpha) | `onecrew/v2/wiki.py` (`_listing`, `_through`, `_is_link`, `pages`) | `tests/test_v23_alpha_links.py` w01–w05; `tests/test_v23_review_codex_r2.py` c1 | luồng alpha S5 |
| Luồng alpha trong script thử | `docs/v23/tools/alpha_flow.py`, `thu_goi.ps1` | `tests/test_v23_owner_wrapper.py` (bước 4, các ca hỏng) | script thử `DAT`, luồng alpha 5/5 |
| B2: danh tính cho các lệnh xem không đọc tên có hard link hay sau junction | `onecrew/v2/verifiers/command.py` (`artifact_sha`, `_add_markers`; ở dev9 là `_add_without`) | `tests/test_v23_beta_identity.py` (13): b01–b03, b06 đỏ trên `1c378e6`; b07–b13 từ review (b12 sparse checkout; b13 cone sparse, bản sửa cuối `d705001`) | hồi quy; gate (các check verifier, evidence, handoff của 2.2) |
| P1 review Codex dev9: khe giữa lúc kiểm và lúc đọc | `onecrew/v2/verifiers/command.py` (`artifact_sha`, `_Pins`, `_open_judged`, `_stage`, `_repositories_for_files`, `_repository`, `tracked_tree`), `onecrew/snapshots.py` (`check_alone`, `final_path`), `onecrew/v2/wiki.py` (`pages`) | `tests/test_v23_beta2_race.py` (22): đỏ trên `d705001`, `3c1687a`, `26eb8fc`, `570c64e`, `1cf3112` theo từng vòng; ca của review độc lập là đối chứng; r16 chỉ chạy trên POSIX | hồi quy; gate; kiểm từ gói (luồng alpha S5) |
| P2 review Codex dev9: bộ đếm gate | `wfkit/gate.py` (`parse_unittest`, `_counts_pass`, `run_unittests`), `wfkit/namespace_lineage.py`; U1 `GATECOUNT-1..3` | `tests/test_v23_gate_counts.py` (7): đỏ trên `d705001`, c07 đỏ trên `563e0a4` | gate (receipt mang hai trường mới) |
| A1, A2, B, PK của các bản trước | như hợp đồng §4, §7–§9 | như hợp đồng | V1–V14 |

## 8. Review độc lập (theo rủi ro)

| Phần | Trên | Người review | Kết quả | Sửa |
|---|---|---|---|---|
| WI, KN, V15/V16 | `7633bb6` | agent Opus, chỉ đọc code | 14 điểm: 5 P2, 9 P3, không P1 | `1c0c0f4` |
| WI, KN (soát lại) | `1c0c0f4` | cùng agent | không P1/P2; 13/14 khép, R7-14 khép một phần; 6 P3 mới | `89b01eb`; R7-17 và khoảng hở junction thành giới hạn |
| FX (trong lúc làm) | các bản trước `04ae80b` | agent riêng, chỉ đọc, 3 vòng | vòng 1: 9 điểm, vòng 2: 3, vòng 3: 1 điểm câu chữ | trong `04ae80b` |
| FX (sau khi gộp) và DX | `4f6a707`, `1cc9419` | agent Opus khác | không P1; 3 P2 (FX-R01 hard link trong artifact Git, FX-R02 kiểm `ids` đạt rỗng, DX-R01 `./x` lấy file ở gốc), 7 P3 | `7a1ce5c`; FX-R03, FX-R06, FX-R07, FX-R08 thành giới hạn (§3.1) |
| Soát lại | `7a1ce5c` | cùng agent | không P1; 4 P2: D-R01 có hard link thì trạng thái mốc không còn biết artifact đổi, D-R02 duyệt plan khi có hard link làm mất base của reviewer, D-R03 junction đưa file ngoài repo vào cây (có từ 2.2), D-R09 một test đối chứng 2.3 đỏ; 5 P3 | lượt sửa ba (§7); D-R07 thành ghi chú phát hành, clean filter thành giới hạn |
| Soát lại | `376654d` (lượt sửa ba) | cùng agent | không P1; 1 P2: E-R01 khi lần định danh sau lượt kiểm bị từ chối thì mất kết quả và giữ mốc lại; 4 P3 | lượt sửa bốn `726aacf`; E-R03 thành giới hạn |
| Soát lại | `726aacf` (lượt sửa bốn) | cùng agent | không P1; 1 P2: F-R01 dòng nguồn ghi mô tả trước có đường dẫn thiếu vẫn đạt nhờ một chữ khác trùng tên file có thật; E-R01, E-R02, E-R04 khép | `3f3edb7` |
| Kiểm | `3f3edb7` | cùng agent | F-R01 khép; không P1/P2; 2 P3: G-R01 chữ có `/` (CI/CD, km/h) trước đường dẫn bị lấy làm đường dẫn (báo sai, không bao giờ đạt sai), G-R02 `.env.example` thiếu vẫn đạt nhờ `.gitignore` có thật | `0c6074f` |
| — | `0c6074f` (sửa G-R01, G-R02) | không review lại (chỉ P3) | probe check4 của reviewer chạy trên bản sửa: g01–g03 đạt, 18 dòng khác cho đúng kết quả như trên `3f3edb7` | — |
| R15 | `f865ee2` | không review riêng | 4 file giống từng byte `e432be2` (đã qua gate 2.2 287/287 ở bản beta dev19); 2.3 không sửa 4 file này; kiểm bằng 14 test của R15 | — |

| B2: danh tính cho các lệnh xem | bản sửa chưa commit trên `1c378e6` | agent Opus riêng, chỉ đọc code, probe trong thư mục tạm | không P1; 1 P2: P2-1, tên có hard link nằm trong vùng bị ignore làm danh tính báo lỗi; 6 P3 | `a0354ff`; P3-4, P3-6, P3-7 thành giới hạn |
| Soát lại B2, review AL-01/AL-02 | bản sửa vòng 1; `6d504c0` | cùng agent | 4 điểm cũ khép; 1 P1 mới: bật sparse checkout thì file sau hard link lại bị băm; AL: không P1/P2, 3 P3 | `a0354ff` (sparse checkout, snapshot); khoảng hở junction khi đọc wiki và việc thư mục không Git dừng khi có hard link thành giới hạn |
| Soát lại | `a0354ff` | cùng agent | P1 và P3 snapshot khép; 1 P2 mới: sparse checkout thật thì file ngoài vùng bị coi là đã xóa | `d705001` |
| — | `d705001` | không review lại: chỉ đổi một cấu hình git | probe15 của reviewer chạy lại: 4/4 cấu hình không lộ, file ngoài vùng giữ nguyên | — |

| P1, P2 (review Codex dev9) | `06f55e5`, `563e0a4` | agent Opus riêng, chỉ đọc code, probe trong thư mục tạm | P1 bản đầu (ghi kho tạm rồi băm lại để so): 1 P1 (clean filter LFS vẫn thấy nội dung), 5 P2 (CRLF dưới `core.autocrlf`/`text=auto` bị từ chối oan, file lớn mất khỏi kho, đường dài và mọi thứ trên macOS bị từ chối, chậm 10 lần); P2 của gate: một test tự in `OK` che dòng tổng kết; 2 P3 (`;` trong đường dẫn, race khi chép object) | P1 thiết kế lại `6d48333` (giữ file mở trong lúc git đọc); P2 `e88b250`, U1 `GATECOUNT-3` |
| Soát lại | `3c1687a` | cùng agent | điểm cũ khép, chậm còn khoảng 1,5–2 lần (P3); 2 P2 mới: symlink và thư mục repo lồng đưa cho git mà không giữ nên vẫn lọt nội dung, đổi file↔thư mục làm danh tính lỗi; 1 P2 POSIX: giữ một descriptor mỗi file; 2 P3: `.onecrew` bị giữ làm OneCrew không ghi được, file bị chương trình khác giữ quyền xóa báo sai lý do | `26eb8fc`; hồi quy các module bị ảnh hưởng bắt thêm E-R02 (tên sau symlink thư mục bị từ chối), review không thấy: `570c64e` |
| Soát lại | `26eb8fc`, `570c64e` | cùng agent | không lỗ rò mới; 1 P2: file đã track đổi thành repo lồng có danh tính như file bị xóa; 1 P3: file đổi thành junction làm lỗi lệnh xem | `1cf3112` |
| Soát lại phần đổi | `1cf3112` | cùng agent | 2 điểm vòng trước khép; 1 P3 mới: thư mục có `.git` hỏng (gitfile sai, `.git` rỗng, repo chưa có commit) làm danh tính lỗi | `3265147`: probe p22 của reviewer khớp git ở mọi ca git chạy được; không review lại (P3, không đọc nội dung); repo lồng chưa có commit thành giới hạn |

Báo cáo review: `D:\OneCrewRuns\v23\review-dev7\review-wi.md`, `review-fx.md`, `D:\OneCrewRuns\v23\beta\review-b2.md`, `D:\OneCrewRuns\v23\beta2\review-p1p2.md`. Probe của reviewer được giữ thành test; probe nào đổi kỳ vọng theo quyết định thiết kế thì docstring nói lý do.

Bảng 92 task của beta (`wf-codex/docs/wf/audit/AUDIT-92.md`) không đổi: lượt này không có bằng chứng mới cho task 2.2 nào, tính năng 2.3 không thuộc bảng, và checkout beta không được sửa.
