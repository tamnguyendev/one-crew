# OneCrew 2.3 — bản beta 2.3.0.dev9: hoàn tất phạm vi 2.3, phát hành prerelease beta

Người viết: Claude (Opus 5.5), đầu mối triển khai 2.3, 30/10/2026, theo chỉ thị người dùng tối 29/10 ("Tiếp quản công việc hiện tại, hoàn thành toàn bộ phạm vi OneCrew 2.3 đã chốt và phát hành bản 2.3 sau khi tự kiểm chứng đạt…"). Phạm vi: ba tài liệu chung bản Codex sửa 29/10 17:31–17:36 (roadmap §0.2, thiết kế và bàn giao mục wiki-init: WI-01…05) và [hợp đồng 2.3](HOP-DONG-2.3.vi.md) §10. Đây là **tự kiểm của tác giả và review của agent độc lập**, chưa phải Codex review lại hay nghiệm thu. Báo cáo trước: [BAO-CAO-2.3-DEV6](BAO-CAO-2.3-DEV6-2026-10-29.vi.md); gói dev6 không bàn giao, dev7 thay nó. Bản alpha `2.3.0.dev8` đã giao trước, theo chỉ thị 30/10 ~11:30 ("giao ALPHA dùng được sớm, rồi hoàn thiện BETA"; hồ sơ `ALPHA-2.3.0.dev8.vi.md`). Bản này là beta: thêm bản sửa B2 và gate 2.2 đầy đủ trên đúng snapshot của gói.

**Bản nào:** bản trong `docs/` của gói là bản lúc dựng gói. §1, §3 (kết quả), §5 (phần "sau") và §6 chỉ có ở bản trong checkout `D:\TamNT\Workspace\11.OneCrew\wf-v23\docs\v23\BAO-CAO-2.3-DEV9-2026-10-30.vi.md`, ghi sau khi kiểm. Gói không tự chứng nhận chính nó.

| | |
|---|---|
| Nhánh | `claude/onecrew-2.3`; push lên `origin` cùng tag khi phát hành (§1) |
| Version | `2.3.0.dev9`, prerelease **beta** theo quy ước `2.3.0.devN` của hợp đồng §1 |
| Gói | `D:\OneCrewRuns\v23\pkg\onecrew-2.3.0.dev9-beta` |
| Đích phát hành | tag `v2.3.0.dev9` và nhánh trên `origin` (`git@github.com:tamnguyendev/one-crew.git`, repo private), như `v2.1.0` và alpha `v2.3.0.dev8` |

## 1. Đã phát hành loại bản nào, ở đâu

<!-- dev9:release -->
_Ghi sau khi kiểm gói (bản trong checkout)._

## 2. Người dùng dùng được gì

- **Từ alpha `2.3.0.dev8`:** ảnh chụp phạm vi node cho worker và trình đọc wiki không đọc file có tên khác trên đĩa (hard link), symlink hay junction (AL-01, AL-02): node không chạy, trang không được đọc, kèm lý do. Trước đó nội dung một `.env` có thể vào prompt của worker. Script thử một lệnh chạy thêm luồng alpha 5 chặng (init và wiki, tri thức cho task, kết quả đã kiểm thành tri thức, root mới dùng lại, guard hard link) và để lại `feedback-alpha.zip`.
- **B2 (beta):** các lệnh chỉ xem trạng thái (`plan show`, báo cáo, so evidence, handoff) không còn băm nội dung tên có hard link hay nằm sau junction: chỗ đó trong cây là một marker làm từ size, thời điểm sửa và file id, nên artifact đổi vẫn thấy đổi mà nội dung không vào kho object của repo.

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

<!-- dev9:results -->
_Ghi sau khi kiểm gói (bản trong checkout)._

### 3.1 Giới hạn còn lại (đã ghi, không tính là đã khép)

- **Bản thử:** chưa nghiệm thu, chưa pilot thật, chưa Codex review lại. 23 khoảng trống nghiệm thu, pilot và provider của 2.2 giữ nguyên.
- **Worker giả:** diễn tập dùng `claude` giả. Nó chứng minh đường đi, nhãn và receipt, không chứng minh model thật hiểu wiki. Phần B (model thật) của task đầu tiên chưa chạy trong lượt này.
- **Init và wiki:** vẫn còn một khoảng rất ngắn giữa lần xét đường dẫn cuối và lúc tạo file; một junction đổi vào đúng lúc đó không bị chặn. Mục 2.2 ghi đúng khóa `lesson-<mã>` của lesson general của project khác thì lấy id của lesson đó (phải biết trước mã băm). Chi tiết: `docs/HUONG-DAN-WIKI.vi.md` §7.
- **Verifier:**
  - artifact Git có một tên là hard link hoặc đi qua junction: lượt kiểm doc/data/ops/command bị từ chối kèm lý do (reviewer: `inconclusive`; link xuất hiện trong lúc kiểm: receipt `inconclusive` có lý do), và `plan approve` bị từ chối, thay vì chỉ báo "chưa kiểm" file đó rồi kiểm tiếp. Từ chối cả khi plan không có mốc nào đọc cây (chỉ owner-manual), và cả repo cố ý giữ hai file trùng bằng hard link. Cách xử lý: thay link bằng bản sao (hoặc đưa ra khỏi cây làm việc) rồi chạy lại;
  - các lệnh chỉ xem trạng thái (`plan show`, báo cáo) băm cây làm việc nhưng không đọc tên có hard link hay nằm sau junction: chỗ đó là marker từ size, thời điểm sửa và file id (B2). Marker giả được bằng một file thường có đúng nội dung đó, và đổi nội dung mà giữ nguyên size và thời điểm sửa thì không thấy; chỉ ảnh hưởng các lệnh xem, vì verifier từ chối cây có link. Tính danh tính chậm hơn khoảng 2,4 lần (3 000 file: 1,6 s → 3,7 s). Khoảng hở giữa lần xét link và lúc git đọc, và `.gitignore` nằm sau junction, có từ trước;
  - một clean filter trong `.git/config` có thể đưa nội dung khác vào cây (có từ 2.2; cần sửa cấu hình của repo, nơi worker không được ghi);
  - thư mục không Git: một hard link bất kỳ làm dừng định danh, kèm lý do (từ `2.3.0.dev8`, AL-01; trước đó chỉ khi thư mục có tên bị cấm); `.onecrew` không được đọc như trước; junction nằm sâu trong một thư mục bị cấm (sau file đầu tiên) không dừng định danh, không có gì được đọc qua nó;
  - kiểm `ids` trên tài liệu chưa có id nào thì không đạt, kể cả với plan đã duyệt trước bản này (thay đổi hành vi): bỏ kiểm `ids` khỏi mốc hoặc thêm id; với `(?i)` ở đầu mẫu, id được so theo chữ thường như cờ của regex, còn `(?i:..)` trong mẫu thì so đúng như viết;
  - mẫu `ids` có neo nằm trong nhóm lựa chọn (`(?:^|\W)REQ-\d+`) đọc cả ký tự đứng trước vào id, nên báo sai "id chưa định nghĩa" (không bao giờ đạt sai): viết `\bREQ-\d+`; mẫu có backreference đánh số, hay có cờ giữa mẫu, bị từ chối lúc đề xuất (thông báo nêu cách viết lại); mẫu `^\s+REQ-\d+` báo lỗi rõ thay vì đạt rỗng;
  - file thật có tên dạng 8.3 (`data~1.csv`) không khai được trong hợp đồng;
  - nguồn viết trần không có `./`, `../` (như `README.md`) được tìm cạnh trang, không có thì ở gốc repo: viết `./README.md` để chỉ tính cạnh trang. Dòng nguồn không có link mà có đường dẫn (từ đầu dòng có `/` hay có đuôi file, hoặc một từ sau có `/`, hoặc một tên có đuôi file) thì OneCrew kiểm đúng đường dẫn đó, kể cả khi dòng còn nhắc tên khác; dòng không có đường dẫn nào thì thử lần lượt các từ bắt đầu bằng dấu chấm (`.env`, `.gitignore`) và lấy cái có thật, không cái nào có thật thì báo cái đầu tiên là không thấy.
- **Ảnh chụp phạm vi node cho worker và trình đọc wiki** (từ `2.3.0.dev8`): không đọc file có hard link, symlink hay junction. Một tên được xét trên đúng handle được đọc; tên thành link sau lần đọc không ảnh hưởng nội dung đã đọc.
- **Gói tiếp tục niêm phong bởi bản dev1–dev5** (bản test, chưa phát hành): yêu cầu đọc tiếp được giải theo tiêu đề. Không giải được thì bị từ chối, không giao nhầm chủ thể.

## 4. Lệnh cài và bài thử ngắn

Một lệnh làm cả bốn việc: kiểm hash, chạy bộ kiểm 16 bước, chạy task đầu tiên và luồng alpha 5 chặng trên thư mục mới với sổ tạm. Đạt khi in `DAT:` và thoát 0:

```powershell
powershell -ExecutionPolicy Bypass -File "D:\OneCrewRuns\v23\pkg\onecrew-2.3.0.dev9-beta\verify\thu-goi.ps1"
```

Cài vào venv thử và khởi tạo một bản sao project:

```powershell
$py = "C:\Users\NUC\AppData\Local\Programs\Python\Python313\python.exe"; $pkg = "D:\OneCrewRuns\v23\pkg\onecrew-2.3.0.dev9-beta"
$venv = "D:\OneCrewRuns\v23 thu beta\venv"; & $py -m venv $venv; & "$venv\Scripts\python.exe" -I -m pip install --no-index --no-build-isolation "$pkg\wheel\onecrew-2.3.0.dev9-py3-none-any.whl"
& "$venv\Scripts\onecrew.exe" --version
& "$venv\Scripts\onecrew.exe" init --project "<bản sao project>" --yes
& "$venv\Scripts\onecrew.exe" --project "<bản sao project>" wiki pages
```

Quay về 2.2: `& "$venv\Scripts\python.exe" -I -m pip install --no-index --no-build-isolation --force-reinstall "$pkg\wheel\previous\onecrew-2.2.0.dev18-py3-none-any.whl"`. Wheel này giống từng byte wheel của gói beta. 2.2 đọc được sổ do 2.3 ghi trong phạm vi bước V7 đã diễn tập. Ngoài phạm vi đó không có cam kết quay về dữ liệu.

## 5. Beta 2.2 và công việc đang chạy

- **Trước khi làm (29/10 17:05):** gói `D:\OneCrewRuns\wf-handover-34eb7c4-hs2` khớp 687/687 dòng `SHA256SUMS`; `hook-projects.json` thật có SHA256 `884335df…`; checkout `wf-codex` ở `1753f77`, sạch.

<!-- dev9:beta -->
_Ghi sau khi kiểm gói (bản trong checkout)._

- **Hai lần ghi nhầm vào sổ đăng ký hook thật, đã khôi phục từng byte:**
  - 29/10 21:39: một lượt chạy `tests.test_g2_install` + `tests.test_v2_trust_fixes` do tôi chạy, không đặt `LOCALAPPDATA` riêng, thêm vào `%LOCALAPPDATA%\OneCrew\hook-projects.json` một mục trỏ vào thư mục tạm `v23\dev7\tmp-wi`. Agent R15 phát hiện; 23:00 tôi bỏ đúng mục đó.
  - 29/10 23:25: một probe của agent review WI cũng chạy không có `LOCALAPPDATA` riêng và thêm một mục trỏ vào `v23\review-dev7\tmp`. Tôi phát hiện lúc 30/10 02:35 khi đối chiếu SHA256 và bỏ đúng mục đó ngay (bản lỗi và biên bản: `D:\OneCrewRuns\v23\dev7\incidents`).
  - Sau mỗi lần, file trở lại đúng 636 byte, SHA256 `884335df…` như lúc 17:05; chỉ thời gian sửa file đổi. Hai mục thừa trỏ vào thư mục tạm đã xóa. Sổ này chỉ dùng để hook tìm state root khi project mất `config.json`; các mục của project thật trong đó không đổi.
- **Một lần gọi Claude thật ngoài ý muốn:** 30/10 ~01:51, agent sửa verifier chạy hồi quy có `tests.test_v2_reviewer`. Test `RealCliTests` của module đó gọi Claude CLI thật khi máy có `claude.exe`: một lần, `claude-haiku-5-5`, đăng nhập subscription, CLI tự báo chi phí ước 0,066 USD. Việc này ngoài yêu cầu "không gọi model" của lượt; thư mục rỗng mà lần gọi tạo trong `~/.claude/projects` đã gỡ. Gate không chạy module này; các lượt hồi quy sau bỏ nó ra.

## 6. Quyết định vượt quyền

<!-- dev9:decisions -->
_Ghi sau khi kiểm gói (bản trong checkout)._

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
| B2: danh tính cho các lệnh xem không đọc tên có hard link hay sau junction | `onecrew/v2/verifiers/command.py` (`artifact_sha`, `_add_without`) | `tests/test_v23_beta_identity.py` (11): b01–b03, b06 đỏ trên `1c378e6`; b07–b11 từ review | hồi quy; gate (các check verifier, evidence, handoff của 2.2) |
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

Báo cáo review: `D:\OneCrewRuns\v23\review-dev7\review-wi.md`, `review-fx.md`, `D:\OneCrewRuns\v23\beta\review-b2.md`. Probe của reviewer được giữ thành test; probe nào đổi kỳ vọng theo quyết định thiết kế thì docstring nói lý do.

Bảng 92 task của beta (`wf-codex/docs/wf/audit/AUDIT-92.md`) không đổi: lượt này không có bằng chứng mới cho task 2.2 nào, tính năng 2.3 không thuộc bảng, và checkout beta không được sửa.
