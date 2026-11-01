# CHANGELOG

## v2.4.0.dev1 (đang làm) — mốc 2.4-C: bước 0 đủ để làm, chọn cách chạy node

**Chưa phải bản giao; chưa chạy gate 2.2.** Hướng dẫn: `docs/v24/HUONG-DAN-BUOC-0.vi.md`.
- Đề xuất bước 0 (W47) có ba trường tùy chọn `preserve`, `investigation`, `estimate`; dùng một trường là bật luật thẻ (điều giữ nguyên khi sửa/xoá, ước lượng có căn cứ hoặc "chưa đủ dữ liệu", điều tra có đường dẫn rõ và trần, unknown mà việc duyệt chờ). Đề xuất không dùng thì kiểm như cũ. `plan step0 show <plan> [--json]` xem thẻ, chỉ đọc.
- Khảo sát bước 0 bị từ chối khi trần điều tra đã hết, và chỉ đọc trong đường dẫn điều tra; unknown còn mở thì vẫn giữ việc duyệt.
- Capability tùy chọn `execution-mode`: engine chọn và ghi `run_now` / `overlap` / `continue_worker` / `tools` / `wait` kèm lý do (Q2, `node.started`, sự kiện mới `workflow.mode` lớp B); đọc↔ghi cùng file và nhãn `resources` chung không được chạy song song; chi phí bàn giao chưa đo là `unknown`, không phải 0; kiểm không cần model chạy cạnh worker không tạo task con. Không adapter nào giữ phiên model (`session.reuse: false`). Root không khai capability chạy như 2.3.
- `engine measure <plan>`: số đo từ sổ (chỉ đọc), thiếu quan sát là `unknown`.

## v2.3.0.dev10 (31/10/2026) — beta 2.3 sau review Codex trên dev9

**Bản beta (prerelease), chưa nghiệm thu, chưa được Codex review lại; không phải bản ổn định `2.3.0`.** Kết quả, giới hạn và lệnh thử: `docs/v23/BAO-CAO-2.3-DEV10-2026-10-31.vi.md`.

So với beta `2.3.0.dev9`:
- **P1:** một file đổi thành hard link hay một thư mục đổi thành junction giữa lúc OneCrew kiểm và lúc đọc không còn lọt vào kho Git, kho snapshot, cây bàn giao hay trang wiki. Git không tự duyệt cây làm việc khi tính danh tính nữa: mỗi file được mở, xét trên handle và giữ mở trong lúc git đọc.
- **P2:** gate tách đạt, hỏng, bỏ qua, expected failure và unexpected success; expected failure không bao giờ được tính là đạt (chỉ được chấp nhận khi testcase khai rõ). Ngoại lệ U1 hẹp `U1-20261031-V23-GATECOUNT-1..3` theo quyền chủ sở hữu 31/10.
- Báo cáo dev9 đính chính nguồn thực thi của gate (source trên snapshot; 22/217 lượt có ghi nhận dùng wheel) và số test B2 (13).

## v2.3.0.dev9 (30/10/2026) — bản beta 2.3

**Bản beta (prerelease), chưa nghiệm thu, chưa được Codex review lại; không phải bản ổn định `2.3.0`.** Dùng trên bản sao project và sổ riêng. Gate 2.2 đầy đủ chạy trên đúng snapshot của gói; kết quả, giới hạn và lệnh thử: `docs/v23/BAO-CAO-2.3-DEV9-2026-10-30.vi.md`.

So với alpha `2.3.0.dev8`:
- **B2:** các lệnh chỉ xem trạng thái (`plan show`, báo cáo, so evidence, handoff) không còn băm nội dung tên có hard link hay nằm sau junction vào kho object của repo; chỗ đó là marker từ dữ liệu stat, nên artifact đổi vẫn thấy đổi. Sparse checkout không mở lại đường đọc này.
- Ảnh chụp phạm vi node chỉ lưu byte khi hai lần đọc khớp nhau (một thư mục thành junction giữa hai lần không để lại gì trong sổ).

## v2.3.0.dev8 (30/10/2026) — bản alpha 2.3

**Bản alpha (prerelease), chưa nghiệm thu, chưa được Codex review lại; gate 2.2 đầy đủ chưa chạy trên snapshot này.** Dùng trên bản sao project và sổ riêng. Hồ sơ alpha: `docs/v23/ALPHA-2.3.0.dev8.vi.md` (bước thử, kết quả mong đợi, giới hạn, danh sách blocker A/B/C, phần còn lại cho beta).

So với `2.3.0.dev7` (không bàn giao):
- **Không đọc file có tên khác trên đĩa (AL-01):** ảnh chụp phạm vi node cho worker (và định danh thư mục không Git) từ chối file có hard link, vì tên kia có thể là `.env`, thư mục home hay sổ; trước đây nội dung đó vào snapshot và prompt của worker. Node không chạy, lý do nêu tên file.
- **Trình đọc wiki không đi theo link (AL-02):** trang là hard link hay symlink không được đọc, junction trong wiki không được đi vào, thư mục wiki là link không được đọc; mỗi tên được nêu trong `problems` của `wiki pages`.
- **Script thử một lệnh có luồng alpha:** `verify/thu-goi.ps1` chạy thêm `verify/alpha_flow.py` (init và wiki, tri thức cho task, kết quả đã kiểm thành tri thức, root mới dùng lại, guard hard link) và để lại `feedback-alpha.zip` để gửi lại.
- Race `.onecrew` của index tạm khi tính artifact (có từ 2.2) đã sửa (`git rm --cached -f`).

## v2.3.0.dev7 (30/10/2026, không bàn giao: thay bằng 2.3.0.dev8) — bản thử 2.3: wiki của project, tri thức có bằng chứng, dọn và tiếp quản

**Bản thử (prerelease), chưa nghiệm thu, chưa được Codex review lại.** Dùng trên bản sao project và sổ riêng. Chưa có nghiệm thu của chủ sở hữu, pilot thật và provider thật đầy đủ, nên đây không phải bản ổn định `2.3.0`. Bản này dựng trên beta 2.2 (`2.2.0.dev18`). Các bản 2.2.0.dev4…dev19 không có mục ở đây; ghi chú của chúng nằm trong báo cáo và gói bàn giao từng bản.

Người dùng có gì:
- **Wiki khi init (2.3-A1, WI-01…05):** `onecrew init` tạo khung wiki `docs/wiki/` (`README.md`, `project.md`, `lessons.md`), hoặc dùng lại wiki đã có hay thư mục `wiki.paths`. Chạy lại không đổi byte nào. Init không ghi đè, không ghi ra ngoài repo hay qua link/junction. `config.json` hỏng thì init dừng và không ghi gì (bản trước ghi đè nó). Project đã init bằng 2.2: init lại giữ sổ, config, plan, ngân sách và hook. Hướng dẫn: `docs/HUONG-DAN-WIKI.vi.md` §0.
- **Đọc và giao tri thức (2.3-A1):** worker của engine nhận gói tri thức có nguồn từ wiki và sổ, theo quyền đọc của node, độ liên quan và trần. Mục bắt buộc không bị cắt âm thầm. Worker đọc tiếp bằng con trỏ. Receipt niêm phong đúng gói đã giao. Lệnh: `onecrew wiki show|read|pages`.
- **Ghi tri thức có bằng chứng và dùng lại (2.3-A2):** điều check của node chứng minh được thì được ghi cho project. Root mới, process mới dùng lại. Sửa, thay thế, thu hồi, lưu trữ có hiệu lực ở lần truy xuất sau. Cập nhật đồng thời không mất bản nào. Chủ thể tri thức thuộc project đã ghi: hai project cùng `--key` là hai chủ thể. Lệnh: `onecrew wiki record|withdraw|archive|summarize|export|history`.
- **Dọn và tiếp quản (2.3-B):** controller `engine step` chết thì `onecrew executor recover` xác nhận đã dọn trước. Bước sau giữ node, chạy lại đúng một lần trong ngân sách cũ.
- **Hook và plan lint** (sửa của beta R15 B1, B2, B4, B6, như `2.2.0.dev19`): `Remove-Item Env:X -ErrorAction SilentlyContinue` không bị coi là ghi file; `<`, `>`, `|` trong chuỗi có dấu nháy không bị đọc là chuyển hướng; `plan lint` nói rõ `budget.max_calls` không được đếm cho phiên AI dưới hook; hook Stop nhắc một lần khi mốc chờ chủ sở hữu.
- **Sửa lỗi:**
  - các finding Codex review dev2 (P2-01…03), dev3 (bản ghi general không áp dụng), dev5 (P2-A script thử, P2-B khóa tri thức giữa project, P2-C `.env.example`, P2-D `[S1][S2]`);
  - verifier: mẫu `ids` có neo hay cờ; với `(?i)` hai id chỉ khác chữ hoa/thường là một id; kiểm `ids` không thấy id nào thì không đạt; tên 8.3 bị từ chối ngay lúc đề xuất; thư mục không Git có `.env` định danh được; file bị cấm không bị đọc dưới tên khác (artifact Git có một tên là hard link hay đi qua junction thì lượt kiểm và `plan approve` dừng, nêu lý do, trước khi Git đọc nội dung); nguồn viết trần giữ dấu chấm đầu và `./x`, `../x` chỉ tính cạnh trang: trước đây nguồn thiếu ở thư mục cha có thể đạt nhờ file cùng tên ở gốc repo (lỗi có từ 2.2);
  - tri thức: yêu cầu đọc tiếp qua nâng cấp giao đúng chủ thể; mục 2.2 khóa `lesson-` không trùng lesson thật; `wiki history` không lộ mã project khác; thu hồi được mục ở trang ngoài ngân sách đọc.
- `onecrew --version`.

Thay đổi hành vi cần biết: kiểm `ids` không thấy id nào thì không đạt, kể cả với plan đã duyệt trước bản này (bỏ kiểm `ids` khỏi mốc hoặc thêm id); `plan approve` và verifier từ chối cây làm việc Git có hard link hay junction, kể cả repo cố ý giữ file trùng bằng hard link (tách thành bản sao rồi duyệt, kiểm lại).

Cài, thử, giới hạn và cách quay về 2.2: `docs/v23/BAO-CAO-2.3-DEV7-2026-10-30.vi.md` (§3.1, §4), `docs/v23/tools/limits-final.md`, `README.md` của gói.

## v2.2.0.dev3 (v22-trust-fixes: sửa các lỗi Codex tìm ở 8383446, không thêm tính năng)

- **Hook di động** (P0.1): không có `--project`, hook gom các plan áp dụng cho một lời gọi và chặn nếu **bất kỳ plan enforce nào chặn**, theo hai vai: **plan của phiên** (`CLAUDE_PROJECT_DIR`) xét cả lời gọi; **plan của repo khác mà lời gọi chạm tới** (repo chứa đường dẫn Edit/Write ghi — cwd không phải nơi tìm của Edit/Write —; với lệnh shell: repo chứa cwd và repo của mọi đường dẫn ghi đọc được) chỉ xét những gì lời gọi làm trong chính repo đó (đường dẫn ghi nằm trong repo ấy, cộng `bash_deny` và luật nhắc tên); plan `stopped_with_report` của nó chỉ từ chối lời gọi có ghi vào repo của nó. Mỗi nơi tìm chỉ lên tới gốc repo của nó. Plan chưa duyệt (accepted, proposed), ở chế độ log hay vắng mặt không bao giờ nới lệnh chặn của plan khác. Luật nhắc tên của hook xét từng đoạn của lệnh. (Bản dev3 đầu chỉ xét `CLAUDE_PROJECT_DIR`; bản thứ hai cho "plan tìm thấy đầu tiên thắng" rồi gom mọi plan xét cả lời gọi, nên plan của một repo anh em hay của checkout cha khóa nhầm một phiên worker.) Hệ quả có chủ ý: thư mục scratch hay worktree lồng nằm trong repo khác có plan enforce vẫn bị plan đó chặn. Luật nhắc tên chỉ khớp `.onecrew` (và `onecrew/plans`) khi đó là một thành phần đường dẫn, không phải đuôi của `11.OneCrew`. Khi phiên không có plan enforce của riêng nó, plan của repo chứa cwd từ chối cả đích ghi không giải được (`$PWD/x`), như 2.1. Giới hạn (bãi đỗ): phiên mở ở thư mục con của project mà AI ghi một `.git` giả trong thư mục con thì mất plan của project; khóa sổ đăng ký không nguyên tử tuyệt đối; chi phí tìm plan mỗi lần gọi hook chưa tối ưu; cách hook đọc lệnh shell là văn bản nên còn các ca: `cd x && …`, `Set-Location` hay `git -C` trong cùng lệnh (cwd đổi giữa lệnh), một junction tạo ngay trong cùng lệnh, lệnh con trong `$(...)`, dấu backtick, `Get-Content (...)` hay `where { }`, và ký tự thoát backtick của PowerShell. Mất `<project>/.onecrew/active-plan.json`, hay cả `.onecrew/` (mất `config.json`), mà bản sao state-root của chính project còn thì vẫn tìm thấy và vẫn chặn: sổ `hook-projects.json` (project → state-root, trong state-root mặc định, ngoài project) do **hook tự ghi mỗi khi đọc được `config.json`** và `onecrew init` cũng ghi; sổ nằm trong `permissions.deny` và danh sách đường dẫn được bảo vệ, ghi bằng khóa + file tạm đổi tên, và không xóa mục của ổ đĩa không gắn.
- **Reviewer** (P0.2, P0.3): cây reviewer = index thật + sửa đổi của file đã có trong index (file mới đã `git add` có trong diff); cây đó phải trùng artifact (so bằng danh sách đường dẫn của git): chỗ khác nhau — file chưa theo dõi không ignore, `git rm --cached`, `git add -f` file ignore chưa commit, assume-unchanged/skip-worktree, submodule chưa stage — làm mốc `inconclusive`, lý do nêu đường dẫn và các nguyên nhân (`not_shown` trong biên nhận); artifact lấy trước, cây chụp một lần, diff cắt từ đúng cây đó (biên nhận có `base_tracked` và `tracked_tree`); thay đổi trong lúc review → `inconclusive`; artifact không dựng được → biên nhận `inconclusive` có lý do, không làm `verdict run` lỗi. Diff cắt với `--ignore-submodules=none` (cấu hình `ignore=all` không giấu một submodule đổi commit, và nó không bao giờ là thay đổi trung lập), `--submodule=short` (`diff.submodule=log` không làm mất dòng tiêu đề), `--no-renames`, tiền tố cố định; mỗi đường dẫn đổi phải có đúng dòng `diff --git a/<path> b/<path>` (so cả dòng, theo cách git viết tên có ký tự đặc biệt). Đường dẫn git chỉ hiện `Binary files differ`: file **nhị phân thật** — MỌI bản đang có (cũ và mới) có byte NUL và không bản nào bắt đầu bằng BOM UTF-16/32 (ảnh, jar) — đã được diff nêu tên và **không** chặn pass; mọi trường hợp khác (chữ bị `-diff`, diff driver binary hay `core.bigFileThreshold` giữ ra khỏi diff; nhị phân bị thay bằng script; chữ bị chèn NUL; chữ UTF-16/32) → `inconclusive` kèm tên. Giới hạn: phép thử là byte NUL nên file chữ chỉ có NUL (không BOM, một bản) bị coi là nhị phân. Các lệnh git liệt kê đường dẫn chạy ở gốc repo (`diff.relative=true` không giấu file khi chạy từ thư mục con).
- **Trung lập** (P0.4): bỏ danh sách mặc định (`NEUTRAL_DEFAULT`); chỉ `scope.neutral` hợp đồng tự khai mới trung lập, và một submodule (gitlink) đổi commit không bao giờ là thay đổi trung lập, kể cả khi đường dẫn của nó nằm trong `scope.neutral`. Đổi hành vi so với 2.2.0.dev2: commit chỉ sửa `docs/**`, `*.md`, `CHANGELOG*` nay chạy lại mốc `command` nếu hợp đồng không khai.
- **Kế thừa** (P0.6): chữ ký gồm tiêu đề, verifier, `covers` và toàn văn từng output mốc phủ (sửa chữ output không phủ vẫn giữ pass); mốc `reviewer` kiểm lại luật độc lập cho revision mới. Giới hạn còn lại (bãi đỗ): output được nhận biết bằng vị trí (`O<n>`), nên chèn một output lên đầu đổi chữ của mọi `O<n>` sau nó và các mốc phủ chúng chạy lại; chưa phân biệt đổi chữ với đổi nghĩa.
- **Report** (P0.5): `plan report` dùng cùng view mốc với `plan show` và in đúng trạng thái đó (mốc `stale` hiện `cũ`, mốc kế thừa hiện `pass (kế thừa từ bản N)`, kể cả dòng kết luận), không in kết quả verdict cuối; ghi chú reviewer của lần pass được kế thừa có trong report. Plan đã nghiệm thu được đọc **từ bản ghi `plan.accepted`** (verdict ghi sau cùng của mỗi `receipts`), không tính lại bằng luật mới và **không có chữ `kế thừa`/`trung lập`/`stale`** (cái đã mang pass qua nằm trong `carried` của sự kiện), nên một plan đã nghiệm thu bằng 2.1 hay luật cũ vẫn đọc đúng như lúc nghiệm thu và report của nó **không đổi byte**. Ngoại lệ duy nhất: plan đã nghiệm thu bằng bản dev2 nhờ verdict kế thừa — report cũ ghi sai "chưa có verdict" cho mốc đó, nay hiện pass mà nó được nghiệm thu bằng. `accept` từ chối artifact toàn số 0. `plan digest` không đổi.
- **UTF-8** (P0.7): mọi lệnh hook ép stdout/stderr UTF-8 (module và `onecrew hook <verb>`); `init`/`merge_settings` chỉ thay handler do OneCrew cài, giữ handler của công cụ khác có nhắc tên module.
- **`init` nhận handler của mình theo cấu trúc** (sau review thứ năm và thứ sáu): `is_ours` không còn tìm chuỗi `from onecrew.v2.hook_cli import main` + `hook check` trong cả dòng lệnh (một `echo` hay `audit-tool python -c "<mã OneCrew>" hook check` bị `merge_settings` xóa nhầm). Nay tách dòng lệnh như shell (dấu nháy kép/đơn gom từ, `\"` trong nháy kép là một nháy, `\` còn lại là ký tự thường như trong đường dẫn Windows; chương trình lấy tên file sau khi bỏ nháy) và chỉ nhận các dạng OneCrew tự sinh: `onecrew[.exe|.cmd] hook <verb>` (chuỗi lệnh hay `args`), và `python [-u|-B|-E|-I|-s|-S] [-X <x>|-X<x>] -c "<đúng mã checkout>" [--project P] [--state-root S] hook <verb>` (mã sau `-c` phải khớp từng chữ với mã `hook install --print` sinh, 2.1 và 2.2; cả dạng `-X utf8` và `-Xutf8` của verify-kit, dạng cũ có `--project`/`--state-root`, đường dẫn python có dấu cách); mỗi tùy chọn tối đa một lần. Ở dạng chuỗi lệnh (không có `args`, nên một shell đọc nó), từ nào có `;` `&` `|` `<` `>` `$` hay backtick, hoặc dòng có xuống dòng, thì không phải của ta (`--project D:/p;audit-tool hook check`, `--project "$(audit-tool --log)"`); riêng từ mã sau `-c`, vốn có `;` và `(`, chỉ bị từ chối khi có `$` hay backtick. Không nhận: `echo`, công cụ audit/wrapper đứng trước, mã có thêm gì, verb lạ, tham số thừa hay lặp, handler chỉ nhắc tên module, handler khác trong cùng entry. Giới hạn: dạng lệnh OneCrew sinh ở bản sau phải được thêm vào `is_ours` (trước đó handler ấy được giữ, không bị xóa nhầm). `onecrew doctor` nay tìm chương trình của handler dạng chuỗi lệnh (từ đầu của dòng), không coi cả dòng là đường dẫn file (trước đó báo `hook_stale`).
- **Luật nhắc tên `.onecrew`** (sau review thứ năm và thứ sáu): `.onecrew` được tính là nhắc tới khi sau nó (và sau các dấu chấm cuối) KHÔNG có chữ, số, `_` hay `-`: nên `.onecrew.` và `.onecrew..` (Windows bỏ dấu chấm cuối), `.onecrew{,.bak}`, `.onecrew*`, `.onecrew,x`, `.onecrew)`, `.onecrew::$INDEX_ALLOCATION` đều là thư mục được bảo vệ, còn `.onecrew.bak`, `.onecrew-old`, `.onecrew_old`, `.onecrew.bak.`, `11.OneCrew/x` vẫn là tên khác. Phần miễn trừ `.onecrew/scratch/` không còn là `replace` mù: một đường dẫn `.onecrew/…` chỉ được miễn khi đọc được theo CẢ HAI cách — từ shell (tới khoảng trắng, ngoặc, `;`, `&`, `|`, `<`, `>`, nháy) và chuỗi dài nhất có thể (tới nháy hoặc backtick kế tiếp, hay hết đoạn lệnh; một đường dẫn trong chuỗi có thể chứa khoảng trắng, ngoặc và `;`) — mà vẫn nằm dưới `.onecrew/scratch/` theo từng thành phần, sau khi đổi `\` thành `/`, bỏ khoảng trắng và dấu chấm cuối của mỗi thành phần như Windows (một thành phần chỉ toàn dấu chấm là `.`/`..`) và gấp `..` như `posixpath.normpath`. Vì vậy `.onecrew/scratch/../config.json`, `.onecrew\scratch\..\config.json`, `.onecrew/scratch/a/../../config.json`, `.onecrew/scratchy/..`, `.onecrew/scratch /..`, `.onecrew/scratch/a(/../../config.json`, `.onecrew/scratch/a;/../../config.json` bị chặn, còn `.onecrew/scratch/x`, `.onecrew/scratch/a/../b`, đường dẫn scratch có khoảng trắng hay ngoặc mà không thoát ra, `pytest -o cache_dir=.onecrew/scratch/cache` vẫn qua. Chỉ từ chứa đường dẫn đó được cắt khỏi văn bản, nên một tên được bảo vệ khác đứng cạnh (`cp .onecrew/scratch/x policy.json`) vẫn bị bắt. Hệ quả: `.onecrew/scratch,out` (thư mục `scratch,out`, không phải scratch) bị chặn, và một đường dẫn scratch trong chuỗi không nháy, theo sau bởi một chuỗi khác mà gấp `..` lên khỏi scratch, có thể bị chặn thừa (đó là hai ca chặn thừa đã biết). Ca bỏ sót còn lại là giới hạn (cách hook đọc lệnh shell là văn bản, không chạy nó): đường dẫn tính lúc chạy (`'\x2e\x2e'`, `os.path.join('.onecrew/scratch/', '..', 'config.json')`, `'.one' + 'crew'`) và tên ngắn 8.3 không thấy được.
- **Mã cây** (D3): mã cây đọc từ biên nhận/sổ phải là hex 40/64 và đứng sau `--end-of-options`; plan không có cây tracked-only dùng được → biên nhận `inconclusive` có lý do, không làm `verdict run` lỗi.
- Tests: `tests/test_v2_trust_fixes.py` (mỗi lỗi có test thất bại trên mã có lỗi, `8383446` hoặc bản dev3 đầu `38e1703`; vài test bảo vệ hành vi không được đổi xanh cả trên mã cũ). Bốn test của `tests/test_v3_verify_cost.py` đổi kỳ vọng theo D4/D5 (`test_the_default_neutral_paths_are_read_not_written`, `test_neutral_globs_do_not_cross_a_slash_except_double_star`, `test_an_untracked_file_is_never_in_the_diff_and_verdict_diff_makes_no_call_and_writes_nothing`, `test_the_same_after_a_pass_the_pass_remembers_the_tracked_tree_not_the_untracked_files`); hai kiểm version đổi sang `2.2.0.dev3`. `docs/v2-verify-cost.vi.md`.

## v2.2.0.dev2 (đợt 1: kiểm rẻ hơn, giữ sáu bất biến)

- Verdict được **kế thừa** sang revision mới đã duyệt khi mốc (tiêu đề + verifier) byte-giống và artifact giống, hoặc (mốc `command`) chỉ khác ở `scope.neutral`; `plan show` có `carried_from`, `neutral_diff`, `stale`; `verdict run` kiểm thứ tự và "đã đạt" trước khi chạy. Không thêm sự kiện/bảng. `docs/v2-verify-cost.vi.md`.
- `scope.neutral` (mặc định đọc là `docs/**`, `*.md`, `CHANGELOG*`, không ghi vào hợp đồng); `accept` nhận verdict kế thừa qua khác biệt trung lập và ghi `carried`.
- Reviewer chỉ đọc file có theo dõi: diff giữa hai cây tracked-only ghi sẵn trong sổ (`base_tracked` ở `plan.approved` đầu tiên, `tracked_tree` ở biên nhận reviewer; cơ sở = lần pass gần nhất của chính mốc đó với cùng cấu hình, chưa có thì `base_tracked`; thiếu cả hai thì lỗi rõ, không có đường dự phòng); `verdict diff --plan P --milestone M`, `verdict artifact --plan P`. `owner accept --artifact-sha` chỉ nhận mã hex 40/64 và git nhận mã sau `--end-of-options`.
- `plan lint`: `criterion_literal_present`, `criterion_vs_non_goal` (cảnh báo), `criterion_no_fail_clause` (từ chối), `--ack-criteria`; `unknowns_missing` + `understanding.no_unknowns_because` ở lint và approve. `examples/contract-template.json`.
- `plan report`: mục "Reviewer ghi chú ngoài tiêu chí".
- Tests: `tests/test_v3_verify_cost.py`. Hai assert cũ đổi theo luật mới (nêu ở đây để không lẫn): `test_a_verdict_does_not_survive_an_amendment` nay đổi chính mốc M1 (mốc không đổi thì kế thừa); `test_a_diff_over_the_cap_is_not_reviewed_in_part` nay commit file lớn (file chưa theo dõi không vào diff); hai kiểm version đổi sang `2.2.0.dev2`.

## v2.2.0.dev1 (G2: cài xong là có sổ, hook và lệnh chủ sở hữu)

- `onecrew init [--state-root P] [--shared] [--yes]`: tạo sổ, `plans/owner-rules.md` (mẫu trong wheel), `.onecrew/config.json`, và gộp hook vào `.claude/settings.local.json` (`--shared`: `settings.json`) theo khóa; có `.bak`, hỏi y/N, chạy lần hai không đổi byte nào. Kiểm Claude CLI (tìm thấy + đã đăng nhập), không tự đăng nhập; thiếu thì vẫn ghi và exit 1.
- Hook do init ghi dùng chính file `onecrew` đã cài (`onecrew hook <verb>`), không ghi đường dẫn python, repo hay `--project/--state-root`; hook lấy project từ `CLAUDE_PROJECT_DIR` và sổ từ `.onecrew/config.json`. `permissions.deny` thêm `owner approve|accept|enforce|record`. `hook install --print` (checkout) giữ dạng cũ, dùng chung danh sách deny.
- `onecrew doctor`: một dòng PASS/WARN/FAIL cho Python, git, Claude CLI, đăng nhập, sổ, config.json, hook, plan đang mở; exit 1 khi có FAIL.
- `onecrew owner approve|accept|enforce|record`: thay bốn script `scripts/owner/*.ps1`; cố định `--by owner`, bị từ chối trong phiên AI như các động từ cũ.
- Ba lệnh mới nói tiếng Anh, `ONECREW_LANG=vi` đổi sang tiếng Việt (`onecrew/v2/messages.py`); output cũ không đổi. `docs/README.en.md`.
- Mẫu quy tắc `owner-rules.vi.md` + `owner-rules.en.md` là package data của wheel (`onecrew/templates`); `plan rules init` đọc từ đó (mặc định bản vi như trước, `ONECREW_LANG=en` cho bản en). Lệnh `plan`/`verdict`/`owner` không có `--state-root` thì đọc `.onecrew/config.json` của project.
- `tests/test_g2_install.py`.

## v2.2.0.dev0 (G1: lõi v2 cài được bằng pip)

- Wheel chỉ gồm lõi + `onecrew.v2` + `onecrew.v2.verifiers` (danh sách `py-modules` trong `pyproject.toml`); lệnh `onecrew` của wheel là router v2 (`plan`, `verdict`, `hook`), `onecrew_cli.py` ở checkout vẫn là router đầy đủ v1 + v2. Chi tiết: `docs/v2-core.vi.md`.
- Tách lõi khỏi v1 bằng cách dời phần dùng chung (một nguồn; v1 import lại): `budget_core` (đọc ngân sách), `independence`, `task_intake` (`submit` của task neo, `outcomes`, `recommend`), `onecrew/v2/changes.py` → `onecrew/solution_changes.py`. Sổ cái, loại và payload sự kiện không đổi; sổ cũ đọc y nguyên.
- Tìm Claude CLI theo hệ điều hành (PATH, rồi `~/.local/bin`, npm global...), lỗi nêu mọi nơi đã tìm; model mặc định (Opus 5.5) ở một module (`onecrew/v2/claude_cli.py`), ghi đè bằng `ONECREW_DEFAULT_MODEL`.
- `tests/test_g1_core.py`: closure import, tìm CLI (posix/nt giả lập), metadata đóng gói, model mặc định.
- Không còn trong wheel: `onecrew-entry-mcp` (chạy từ checkout).

## v2.1.0 (20/10/2026) có gì

v2 = **hợp đồng công việc cho AI**: AI chỉ chạy trong một hợp đồng đã được chủ sở hữu duyệt. Sáu bất biến cứng: không có hợp đồng đã duyệt thì không chạy; ngoài phạm vi thì bị chặn; hết ngân sách thì dừng; mốc chưa có verdict thì không qua; tác giả không tự duyệt việc của mình; chỉ con người mới nghiệm thu.

Phần lõi v2 (lát L1–L2, item 3, item 4):
- Sổ cái (ledger) ghi biên lai và verdict cho từng mốc (L1).
- Hook cho Claude Code: PreToolUse, UserPromptSubmit, Stop; `hook install --print` in cấu hình (L2).
- Verifier `command`: chạy lệnh kiểm trên checkout sạch (L1).
- Verifier `reviewer`: model độc lập duyệt diff theo 3 tiêu chí (item 3).
- Mốc `owner-manual`: chủ sở hữu tự đọc và nghiệm thu (L1).
- `plan report` (kết luận tiếng Việt 4 dòng + 7 mục) và `plan digest` (item 4).

v2.1 bổ sung:
- Job 9: trường `origin`, `decisions`, `items[].source`, trường trình bày; cổng `approve` chặt khi có `<state-root>/plans/owner-rules.md`; `plan advise` (cố vấn Opus, 3 câu hỏi cố định so với file quy tắc; bắt buộc khi `decisions` không rỗng hoặc cỡ M/L); `plan rules init|show`.
- Job 11a: `plan lint`; verifier `command` fail-closed (đầu ra rỗng, chạy nhanh mà im lặng, ký tự điều khiển, thiếu file thực thi → `inconclusive`); hook Stop nhả khi có biên lai chưa verdict hoặc câu hỏi chủ sở hữu đang mở; `amend` sau khi duyệt chỉ đóng băng lại các mốc bị đổi.

Bằng chứng: 14 job thật trong `state-v2-real` (11 đã nghiệm thu), khoảng 290 test.

## Giới hạn đã biết

- Hook Stop chỉ thấy biên lai sau khi lệnh chạy xong; cần sự kiện "bắt đầu chạy" — **dự kiến 11b**.
- `contract.validate` vẫn nhận ký tự điều khiển trong `argv`; chỉ `plan lint` và verifier bắt được.
- Mốc `command` im lặng luôn `inconclusive` dù đạt: lệnh kiểm phải in kết quả.
- Verifier `command` của Flutter không giải được path dependency anh em trên checkout sạch; chạy kiểm trong worktree (như `run_flutter_checks.py`).
- Tỉ lệ bắt lỗi của cố vấn chưa được đo.
- Quy tắc R1 trong `examples/owner-rules.vi.md` ghi sai ("debug cho chạy thử"); đúng: build debug khi đang phát triển, chỉ release khi đã xong, test đạt và chủ sở hữu đã thử trên thiết bị — **dự kiến sửa ở 11b**.
- Hook chỉ đọc chữ của lệnh; script Python dựng lệnh bằng ghép chuỗi vẫn qua lớp hook (xem `docs/v2-parking-lot.vi.md`).
- Reviewer: mỗi lần gọi tốn khoảng 9k token cache; diff quá 120 KB không được review (`inconclusive`); chưa kiểm `evidence.file` có nằm trong diff.
- `plan report` chưa đếm số lệnh/token, chưa có HTML.
- Một số test v1 đỏ sẵn có (ví dụ `test_sandbox_gate` khi đường dẫn worktree dài); không do v2.

## Cách chạy

CLI (từ thư mục repo):

```
<python> -X utf8 onecrew_cli.py --project <repo> --state-root <state-root> plan|verdict|hook ...
```

- Hook: `hook install --print` in cấu hình, dán vào `.claude/settings.json` của project.
- Chạy verifier: `verdict run --plan <tên> --milestone <Mx>`.
- Báo cáo: `plan report`, `plan digest`.
- Các động từ của chủ sở hữu (`approve`, `accept`, `enforce`, `verdict record --by owner`) chỉ gõ từ terminal của chính chủ sở hữu, không từ phiên AI.
- Sổ cái và hợp đồng nằm trong `<state-root>` (`ledger.sqlite3`, `plans/`, `policy.json`); `.onecrew/active-plan.json` trong project là bản xuất để hook đọc.
