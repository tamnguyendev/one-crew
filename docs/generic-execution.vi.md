# Nền thực thi chung: hợp đồng công việc (`job --mode work`) — 13/10/2026

Người dùng giao **mục tiêu, phạm vi, điều phải giữ nguyên, tiêu chí đầu ra, ngân sách và quyền áp dụng kết quả**.
OneCrew tự khảo sát, lập kế hoạch, chọn công cụ, thực hiện, xử lý lỗi kỹ thuật, kiểm chứng và bàn giao.
Một chế độ chung thay cho việc mỗi loại việc cần một mode hoặc recipe riêng. Các mode cũ (audit/change/delivery/branch)
và delivery autopilot giữ nguyên.

## Khảo sát: năng lực đã có và điểm chặn quá cứng (trước đợt này, c3a35dc)

Đã có:
- vòng observe/act: worker (Codex/Claude/Kiro, không tool native) trả về một hành động JSON, core thực thi;
- checkpoint CAS, receipt bất biến, action ghi bền kèm reconcile (không lặp tác dụng), runner nền, inbox câu hỏi;
- review hoàn tất bằng model, phát hiện không tiến triển, ngân sách call/deadline, Job object khi chạy tiến trình.

Điểm chặn:
1. Quyền gắn với mode. Sửa file chỉ có ở `change`, kèm điều kiện image Docker; test chỉ là Python unittest trong
   container; không có công cụ chạy lệnh/build trên host.
2. Git cứng:
   - tên nhánh phải là `onecrew/...`;
   - nhánh chỉ được tạo trước một commit lịch sử (`branch_before`), không tại HEAD;
   - push chỉ có trong delivery.
   SRM `production` bị từ chối ngay ở intake.
3. Kiro bị ghim đúng 2.28.0; máy đang có 2.29.0 nên provider này không dùng được.
4. Không có kiểm chứng độc lập theo hợp đồng: core không chạy lại lệnh kiểm chứng và không kiểm tính toàn vẹn của test.

## Phương án

1. **Hợp đồng công việc** (`--contract FILE`, schema 1), được niêm phong vào payload task:
   - `goal`, `scope` (repo con trong project, các tiền tố đường dẫn được sửa), `preserve`, `acceptance`;
   - `checks` (tuỳ chọn, máy kiểm được: ref/lệnh);
   - `authority`: `edit`, `commands`, `local_branches` (tên chính xác), `branch_at`, `apply_to_project`, `edit_tests`;
   - `authorized_by` (nguồn và tham chiếu; chỉ để ghi nhận, không phải xác thực).
   Ngân sách dùng `--max-calls/--max-seconds` như cũ.
   Hợp đồng do người dùng uỷ quyền thay cho bước duyệt SOL riêng của mode này. Nếu có SOL thì vẫn bind như cũ.
2. **Ghim** lúc enable: HEAD, nhánh đang checkout, băm trạng thái chưa commit và băm stash của repo. Kết thúc phải kiểm lại
   (giữ nguyên checkout/source/stash, trừ thay đổi do action `apply` đã ghi receipt).
3. **Workspace riêng:** `git clone --shared` tại commit đã ghim, gỡ remote. Repo gốc không bị đổi. Các công cụ chạy trong
   workspace này:
   - list/search/read/write/edit;
   - `run` (argv, cwd trong workspace, Job object, deadline, giới hạn output, chặn đối số trỏ vào project gốc hoặc ledger);
   - tiến trình nền (`process`).
4. **Git qua core, có receipt:**
   - `create_branch`: tên trong `local_branches`, tại commit đã ghim, compare-and-swap, không bao giờ ghi đè; ref đã có thì chỉ
     báo SHA;
   - `workspace_commit` + `export_branch`: đưa thay đổi ra nhánh local;
   - `apply`: chép vào project, có CAS và bản để quay lại; chỉ khi được quyền;
   - push không có trong mode này, bị từ chối.
   Receipt ghi đúng nguồn: thực thi là OneCrew core, yêu cầu là worker provider/model.
5. **Kiểm chứng độc lập khi `finish`:**
   - core tự chạy lại lệnh kiểm chứng mà worker khai báo, và các check của hợp đồng;
   - test có số lượng > 0 khi nhận dạng được framework;
   - test có sẵn không bị xoá/sửa (trừ khi được quyền), không thêm skip;
   - repo gốc giữ nguyên theo ghim; mọi action đã verified.
   Sau đó là review bằng model như cũ. Bàn giao gồm diff, file đổi, kết quả chạy lại, cách quay lại.
6. **Tái sử dụng có phạm vi:** lệnh đã được core kiểm chứng trong một task hoàn tất được ghi thành fact của project. Task sau
   cùng project thấy chúng như gợi ý (dữ liệu, không phải quyền).
7. **Lỗi kỹ thuật:**
   - exit code khác 0 là kết quả để worker chẩn đoán và sửa;
   - core phân loại quyền / môi trường / sản phẩm;
   - từ chối quyền lặp lại → blocked `permission`;
   - lệnh và kết quả lặp → blocked `no_progress`.
8. **Kiro 2.29.0:** kiểm cờ CLI, validate agent, một lần gọi tối thiểu qua đúng argv và parser của adapter. Có bằng chứng thì
   mới thêm vào danh sách phiên bản được hỗ trợ, không chỉ đổi số. Prompt Kiro ≤ 16.000 ký tự: core co phần bằng chứng
   theo provider.

## Tiêu chí nghiệm thu

- Regression đỏ trên c3a35dc và xanh sau sửa:
  - tạo nhánh tên tuỳ ý tại commit ghim (đã có thì không ghi đè, sai tên thì từ chối);
  - run/edit trong workspace không chạm project gốc;
  - kiểm chứng độc lập bắt được báo cáo giả, test bị xoá/skip, lệnh kiểm chứng đỏ;
  - restart giữa chừng không lặp tác dụng;
  - provider đã ghim không đổi.
- Eval trước/sau cùng harness, oracle và môi trường. Giữ kết quả cũ.
- Đóng băng revision, rồi chạy việc thật chỉ bằng hợp đồng:
  - SRM `production` (Kiro);
  - nhánh tên chỉ định tại commit ghim;
  - sửa lỗi kèm test;
  - tự tìm cách test/build;
  - lỗi môi trường phục hồi được;
  - tiếp tục sau khi coordinator bị ngắt;
  - từ chối vì vượt quyền;
  - bài giữ lại chưa dùng khi phát triển.
- Báo số việc hoàn thành, số câu hỏi, số lần entry can thiệp, chi phí và giới hạn. Sửa runtime giữa lượt thì giữ failure và
  chạy lượt mới.

## Đợt sửa theo review Codex 13/10/2026 (GX-P1-01..03, GX-GAP-04) — thiết kế, quyết định, tiêu chí

Bốn probe của Codex tái hiện đúng trên 8603e74 (`D:\OneCrewEvals\gxp1-20261013\probes\baseline-8603e74.txt`). Nguyên tắc chung:
**core kiểm hệ quả, không kiểm công cụ** — mọi đường tạo thay đổi đi qua cùng một cổng, mọi bằng chứng gắn với đúng thứ được giao.

1. **Ranh giới thực thi (GX-P1-01).** Lệnh của worker (`run`, tiến trình nền, lệnh kiểm chứng của core) mặc định chạy
   *contained*: token hạn chế (nhóm Administrators chỉ còn deny-only, bỏ mọi privilege), mức toàn vẹn Low, trong Job object.
   Chỉ workspace, thư mục tạm và cache của task được gắn nhãn Low, nên hệ điều hành chỉ cho ghi ở đó; project, state/ledger
   OneCrew, hồ sơ người dùng và mọi repo khác bị từ chối ghi. Đã thử trên máy này: Python, Node, npm, Git, dart.exe chạy được;
   `flutter.bat` treo vì Flutter ghi vào cache của chính SDK. Công cụ cần ghi ngoài workspace chỉ chạy được khi người dùng cấp
   `authority.unconfined_commands` trong hợp đồng (quyền của người dùng, không do model tự cấp). Không có fallback ngầm.
   Giới hạn còn lại, ghi rõ: tiến trình contained vẫn **đọc** được file người dùng và **dùng mạng**; đây là ranh giới ghi, không
   phải sandbox đọc/mạng (AppContainer hoặc tài khoản riêng là bước sau, cần cấp quyền ACL/tài khoản).
2. **Cổng thay đổi theo delta (GX-P1-01).** Core tính delta của workspace so với commit ghim bằng index riêng của core, không phụ
   thuộc lệnh nào tạo ra nó. Một đường dẫn chỉ được giao khi có `edit`, nằm trong `scope.paths` và (với test có sẵn) có
   `edit_tests`. Receipt của mỗi `run` ghi các đường dẫn lệnh đã đổi và phần vượt quyền; `workspace_commit`, `export_branch`,
   `apply` từ chối nếu delta có phần vượt quyền; `finish` coi đó là finding. Hành động `restore` đưa đường dẫn về bản ghim
   (dùng được khi chỉ có quyền chạy lệnh). Output do chính lệnh kiểm chứng sinh ra bị loại bỏ; nếu lệnh kiểm chứng sửa file của
   candidate thì file được trả về candidate và đó là finding. File bị `.gitignore` của repo bỏ qua là output sinh ra, không được giao.
   Cấu hình Git của workspace (config, info/, hooks) thuộc core: lệnh thay đổi chúng thì core khôi phục và ghi lại.
3. **Ý định bền và reconcile (GX-P1-02).** Trước mọi hành động có tác dụng phụ, core ghi `intent` vào checkpoint (bước, hành
   động, băm đối số, runner, log, cây workspace trước đó). Khởi động lại mà thấy intent chưa có receipt thì *reconcile, không
   replay*: `run` không bao giờ chạy lại tự động — core xác nhận cây tiến trình cũ đã chết, đọc log và delta, ghi receipt
   `outcome_unknown` để worker quyết định; lệnh kiểm chứng bị ngắt thành finding, worker phải finish lại; write/edit chỉ chạy lại
   khi CAS chứng minh chưa có tác dụng; `restore`, Git/apply dùng reconcile sẵn có. Không tốn lượt gọi model, không đổi ngân sách,
   không hỏi người dùng.
4. **Kiểm chứng gắn với output thực (GX-P1-03).** `verify` tính fingerprint candidate (cây Git), chạy kiểm chứng trên đúng cây
   đó, rồi đối chiếu *giá trị thực tại thời điểm đó*: ref của mọi nhánh đã giao (commit và cây phải bằng candidate), mọi file
   project của mọi đường dẫn trong candidate và mọi file đã apply (nội dung phải bằng candidate), phần còn lại của repo người
   dùng so theo từng đường dẫn với ghim (apply chỉ miễn đúng các file đã apply, không miễn toàn bộ). `finish` sau review kiểm lại
   lần nữa: candidate, ref, file đã apply và ghim phải y như lúc kiểm chứng, nếu khác thì bằng chứng mất hiệu lực và phải kiểm lại.
   `apply` được cập nhật file do chính job này đã apply (CAS từ blob đã ghi receipt), như `export_branch` với nhánh job tự tạo.
   Bàn giao lấy patch từ cây candidate đã kiểm chứng.
5. **Host bền ngoài vòng đời chat (GX-GAP-04).** `onecrew host` là bộ điều phối theo user (một instance, lease có heartbeat),
   do Task Scheduler của Windows khởi chạy lúc đăng nhập (task theo user, mức LeastPrivilege, không cần admin) — không phải
   tiến trình con của chat. Entry chỉ ghi yêu cầu `host.dispatch` vào ledger; host nhận (admission: task chưa kết thúc, chưa có
   runner sống, runtime hợp lệ), khởi chạy runner, giám sát, khởi động lại có giới hạn khi runner chết (checkpoint + reconcile),
   tôn trọng cancel/pause/câu hỏi đang chờ, và cửa sổ Windows báo một lần như cũ. Không có host thì `job start` báo rõ, không giả
   vờ chạy nền. Cài task Windows là cấu hình bền trên máy người dùng nên phải hỏi một lần; phần còn lại làm độc lập.

Tiêu chí nghiệm thu:
- Probe Codex và biến thể (lệnh kiểm chứng, tiến trình nền, formatter, file mới, đổi cấu hình exclude, ref đổi sau
  export/trong review, apply sai rồi sửa, file ngoài receipt, crash trước/sau tác dụng của run và của kiểm chứng) đỏ trên 8603e74,
  xanh sau sửa; positive control: việc hợp lệ (sửa trong scope, test, export, apply, apply lại sau sửa) vẫn hoàn thành.
- Eval cùng harness hai phía, giữ mọi failure/capability_unavailable.
- Đóng băng revision; task mới chưa dùng khi phát triển (sửa code + test + bàn giao) chạy qua host; đóng entry thật
  (Job của entry bị huỷ) và kill runner ở ranh giới tác dụng/receipt; ghi assistance tách entry/setup/task/model.

### Kết quả đợt sửa (13/10/2026, runtime cuối 6028118, chưa được Codex review)

Bàn giao đầy đủ: `D:\TamNT\Workspace\9.VMAgent\HANDOVER-CODEX-REVIEW-ONECREW-GX-P1-FIXES-2026-10-13.txt`.
- Commit runtime: b01a5b8 (GX-P1-01..03), 808610b (host, GX-GAP-04), rồi bốn bản sửa xuất phát từ lượt nghiệm thu: d45fb68 (host ở
  ngoài AppData — Claude Desktop là gói MSIX, ghi vào %LOCALAPPDATA% bị chuyển hướng), 02199f6 (runner chưa đăng ký không bị coi là
  chết), bbef812 (token contained có owner/DACL mặc định là user — dưới Task Scheduler với UAC tắt mọi lệnh contained chết
  0xC0000142; tên mã thoát Windows), 6028118 (không chạy lại lệnh đã thất bại khi lệnh và workspace không đổi; gọi tên đường dẫn
  không tồn tại; che thời gian chạy khi so kết quả lặp).
- Probe Codex: cả 4 tái hiện trên 8603e74 và đều bị bắt trên runtime mới (`D:\OneCrewEvals\gxp1-20261013\probes`).
- Đóng entry thật: entry chạy trong Job kill-on-close không cho breakaway (đúng ràng buộc của Claude Desktop) rồi bị đóng; runner do
  host (Task Scheduler) khởi chạy không thuộc Job đó và chạy tiếp. Trước sửa: `job start` trong Job đó → WinError 5, không runner.
- Kill runner thật ở ranh giới: khi lệnh `run` đang chạy (receipt `outcome: unknown`, không chạy lại), sau intent `export_branch`,
  `workspace_commit` (tác dụng thực hiện đúng một lần), `apply` (xem bàn giao). Host khởi động lại trong 1–3 giây.
- Nghiệm thu live và giới hạn còn lại: xem bàn giao (bảng từng lượt, credit Kiro, câu hỏi pending không trả lời thay).

## Đợt 2 theo review Codex trên 6028118 (13/10/2026) — thiết kế, quyết định, tiêu chí

Tái hiện trên 6028118 (`D:\OneCrewEvals\gxp2-20261013\repro`): (1) lệnh contained của task A ghi được vào workspace task B, receipt A
`changed_paths=[]`; (2) package `calc/` bị .gitignore che `calc.py` sai → findings=[] nhưng nhánh giao chứa `a*b`; (3) hai yêu cầu
+ một retry trước khi runner đăng ký → launch 3 lần; (4) 76 regression với token có owner mặc định = Administrators (dạng token của
tiến trình Codex Desktop và host Task Scheduler trên máy này) → đúng 9 failures + 6 errors Codex báo.

1. **Ranh giới ghi theo task.** Token contained có restricting SIDs = các nhóm đang bật của chính token + user + `S_task` (SID tài
   nguyên `S-1-9-1-1-…` suy ra từ state root + task) + `C` (`S-1-9-1-0`, mọi tiến trình contained). Thư mục của task (workspace,
   tmp, cache, thư mục kiểm chứng) có DACL được bảo vệ, theo thứ tự: ALLOW `S_task` toàn quyền, DENY `C` mọi quyền ghi, ALLOW
   user/SYSTEM/Administrators, nhãn Low. Task X ghi được thư mục của X (ACE đầu khớp), không ghi được của Y (gặp DENY `C`), core ghi
   được cả hai (core không mang `C`). Quyền không còn phụ thuộc owner mặc định hay ACL kế thừa của thư mục cha, nên cùng hoạt động khi
   owner mặc định là user (entry Claude) hay Administrators (Codex, Task Scheduler) — đó là nguyên nhân gốc của (4). Token được
   kiểm lại sau khi tạo: thiếu `S_task`/`C` (ví dụ token cha đã bị hạn chế) thì từ chối chạy, không chạy với ranh giới yếu hơn.
   Đọc vẫn không bị giới hạn; thư mục Low dùng chung của Windows (LocalLow) vẫn là kênh chung giữa các task (ghi rõ giới hạn).
2. **Kiểm chứng từ candidate sạch.** Core dựng thư mục kiểm chứng mới từ đúng cây candidate (checkout-index từ index riêng), không
   chép gì từ workspace bẩn. Dependency/file sinh ra mà test cần phải được tạo lại bằng lệnh `setup` worker khai báo; core chạy
   chúng trong thư mục kiểm chứng và ghi nguồn gốc (lệnh, exit, các đường dẫn ignored được tạo). Bàn giao ghi rõ đã kiểm chứng ở
   đâu và bằng những đầu vào nào.
3. **Admission bền.** Mỗi task có bản ghi launch trong state root, ghi TRƯỚC khi khởi chạy và cập nhật danh tính runner ngay sau;
   admission từ chối khi: runner đã đăng ký và sống, runner do host khởi chạy còn sống dù chưa đăng ký, khoá runner của task đang bị
   giữ, hoặc một launch đang dở trong thời gian chờ. Nhiều yêu cầu cùng task trong một lượt quét chỉ khởi chạy một lần.
4. **Gói bằng chứng review (N4).** Review nhận `core_facts` bắt buộc do core lập từ candidate đã giao: danh sách file đổi so với
   ghim, diff từng file (có giới hạn, ghi rõ khi bị cắt kèm băm), test có sẵn không đổi, test mới, kết quả kiểm chứng (ở đâu, lệnh,
   số test, setup), output đã giao, preserve. Phần receipt thô bị co trước; `core_facts` không bao giờ bị bỏ. Reviewer vẫn quyết.
5. **Khảo sát manifest (N2).** Core đọc các manifest/CI phổ biến (package.json scripts, pyproject/setup.cfg/tox, Makefile,
   pubspec, go.mod, Cargo.toml, Maven/Gradle, .github/workflows) và đưa vào prompt như dữ kiện "dự án khai báo" (không phải quyền).
   Gợi ý lỗi phân biệt "đường dẫn không tồn tại" với "thư mục được truyền ở chỗ cần file/module" và chỉ về lệnh dự án khai báo.

Tiêu chí: các probe trên đỏ trước sửa và xanh sau sửa; positive control (việc hợp lệ, toolchain chạy được) xanh; 76+ regression xanh
cả với token owner=user và owner=Administrators; eval trước–sau cùng harness; nghiệm thu live trên revision đóng băng với task Node
mới, task cần gói review lớn, dispatch trùng, đóng entry, crash ở ranh giới tác dụng/receipt; ghi mọi hỗ trợ của entry.

**Sau ba vòng review đối kháng (56 phát hiện được giữ, 10 P1, đều đã sửa kèm test đỏ ở revision trước) — runtime cuối 07d7ad6:**
- Kiểm chứng: checkout sạch là một Git work tree riêng ở commit của cây candidate; temp/cache kiểm chứng tạo mới mỗi lần; nội dung
  file candidate được so sau MỖI lệnh (kể cả đổi cùng kích thước rồi trả lại thời gian); entry không thuộc candidate che khuất một
  module được giao (thư mục/link cùng tên, module biên dịch, pyc không được Python tự kiểm) là finding; đối số đường dẫn ra ngoài
  checkout (kể cả `..`, dạng không ổ đĩa, dạng tương đối theo ổ) bị từ chối; lệnh bị từ chối là check thất bại, không làm hỏng lượt.
- **Quyết định người dùng 13/10/2026:** không dùng danh tính kiểm chứng riêng. Lý do đo được: Python 3.13 cần quyền sửa ACL trên
  thư mục của chính task để tạo thư mục riêng (tempfile, pip, venv), cũng là quyền đủ để gỡ mọi chặn đọc đặt theo file. Kiểm chứng
  chạy dưới danh tính task trong checkout sạch; giới hạn: mã kiểm chứng tự mở workspace bằng đường dẫn trong mã thì đọc được.
- Host: admission nguyên tử giữa các tiến trình, launch không thực hiện được thì task bị block kèm lý do (entry có thể đã đóng),
  restart không launch được vẫn được đếm, chờ khoá runner là tuỳ chọn để lệnh khác không bị chậm.
- Review: `core_facts` có giới hạn kích thước (300 file vẫn vừa trần Kiro), diff tách riêng và gắn nhãn untrusted, bản kiểm chứng
  của runtime/quy tắc khác không được dùng lại, prompt review cũ bị bỏ khi kiểm chứng lại; luật nhận diện file test mở rộng.

## Kết quả nghiệm thu (13/10/2026) và giới hạn

Bàn giao đầy đủ: `D:\TamNT\Workspace\9.VMAgent\HANDOVER-CODEX-REVIEW-ONECREW-GENERIC-EXECUTION-2026-10-13.txt`. Bàn giao này chưa
được Codex review.

Kết quả 17 lượt chạy trên các revision đã đóng băng (4e00059 → 8603e74) (sandbox ở D:\OneCrewRuns\gx-acc):
- **Hoàn thành:** SRM `production` (Kiro), nhánh tên chỉ định tại commit chỉ định, sửa lỗi kèm test hồi quy, tự tìm cách test/build,
  lỗi môi trường phục hồi được (sau 2 lượt thất bại đã sửa runtime), tiếp tục sau khi coordinator bị ngắt.
- **Từ chối đúng:** đòi push/deploy khi không có quyền → OneCrew hỏi 1 câu.
- **Held-out:** H2 và H3 đạt ngay lượt đầu; H1 không đạt lượt đầu (đã sửa runtime, chạy lại đạt nhưng không còn tính là held-out).
- **Chi phí:** 163 lượt gọi, 7,23 credit Kiro. Mỗi lượt có 1 can thiệp môi trường của entry.
- **Eval cuối** (harness 11a30da): c3a35dc 100/106 → 8603e74 106/106, không case nào thụt lùi. Eval cũng bắt được lỗi bytecode Python
  cũ (xanh giả có thể xảy ra), đã sửa ở 5b4370e.

Giới hạn:
- Runner tách rời không khởi chạy được từ công cụ của Claude Desktop (Job không cho breakaway, WinError 5). Entry phải khởi chạy
  `python -m onecrew.runner`, và đóng chat sẽ dừng runner.
- Lệnh chạy trên host không phải sandbox OS.
- Fact của project chưa làm giảm số lượt gọi.
- Kiro tự cập nhật nên mỗi phiên bản mới phải kiểm chứng lại; prompt Kiro bị giới hạn 16.000 ký tự.

## Đợt P4 (14/10/2026): deep review P3 của Codex

- **Host đọc file hàng đợi:** phân biệt file thiếu, file hỏng và file tạm thời không đọc được (khoá Windows, lỗi I/O). Sự kiện
  `host.dispatch` trong ledger (ghi trước file) là bản bền của yêu cầu: file không đọc được hoặc hỏng thì host đối soát theo ledger;
  quyết định đã có (admitted/refused/failed) thì chỉ dọn file, không quyết lại. `supervised.json` không đọc được thì lượt quét chờ,
  không ghi đè; launch record không đọc/ghi được thì không launch và không block. Hết lượt thử thì block kèm lý do.
- **Phân trang:** model nhận một trang của kết quả (chỉ cắt giá trị, JSON vẫn hợp lệ) với `page`: offset, delivered, total, eof và
  `next` là lời gọi chính xác lấy phần tiếp theo (`read` theo cursor file; `receipt {index, field, offset}` cho mọi kết quả khác,
  stdout/stderr đọc từ log đầy đủ, phần cuối trước). `_fit` thu evidence trước rồi tới trang; prompt luôn trong trần Kiro.
- **Một khoá workspace chung:** cây candidate + file bị Git ignore (đường dẫn, kích thước, nội dung có giới hạn), bỏ log/cache/bytecode.
  Dùng cho guard tiến triển, chốt chạy lại lệnh lỗi (chỉ input bị ignore đổi thì cho chạy lại tối đa 2 lần trên cùng cây) và cache lỗi
  đọc. Lệnh lỗi giống hệt kết quả với argv đổi hình thức vẫn là lặp.
- **Resume là phục hồi:** prompt luôn có `recovery` dựng từ checkpoint (lần chặn trước, hành động lặp, lỗi gần đây, kiểm chứng/review,
  deadline, bộ đếm guard so với ngưỡng); guard cảnh báo ở ngưỡng−1; resume không reset bộ đếm, không đổi ngân sách/quyền, từ chối
  job đã huỷ. Mỗi lần block, core tự viết bàn giao blocker (`handover/blocker-<bước>.{md,json,patch}`) và checkpoint trỏ tới nó, nên
  cửa sổ Windows sẵn có của job bị block hiện báo cáo đó một lần.

## Đợt P5–P6 (14–15/10/2026): ngân sách prompt, phân trang và bằng chứng cho reviewer

Nguyên nhân: live S1 bị chặn vì phần cố định của prompt Kiro (contract 6.120 ký tự) không để chỗ cho nội dung kết quả công cụ.

- **P5 (1e3d27a): ngân sách toàn bộ prompt.** `_fit_work` dựng phần cố định trước (contract dài bị cắt có con trỏ; hành động `contract
  {section,index}` trả nguyên văn; scope, checks, authority không bao giờ bị cắt) rồi dành toàn bộ chỗ còn lại cho kết quả mới nhất. Một
  *trang hợp lệ* mang ít nhất `paging.MIN_PAGE` (1.000) ký tự nội dung của chính kết quả (hoặc toàn bộ phần còn lại); page entry, ghi
  chú và số receipt không tính. Không có trang hợp lệ thì chặn TRƯỚC lời gọi (`PromptBudgetError`, `recovery.kind=prompt_budget`, nêu
  thành phần chiếm chỗ); prompt không bao giờ mang ghi chú `does_not_fit`. Có kiểm tra trước lời gọi đầu cho cả prompt làm việc lẫn
  prompt review cuối. Receipt của receipt không lồng nhau.
- **P5b (d83b834):** `contract plan` trả đúng plan mà prompt đã hiển thị (`state['plan_before']`, mỗi bước một lần, bền qua restart);
  continuation trong một mục danh sách (`item_offset`) luôn đi tiếp từ ký tự đã giao, bất kể ngân sách đổi.
- **P6, trang không được là mảnh vụn:** trang danh sách mà các mục nguyên vẹn mang < `MIN_PAGE` ký tự thì mang thêm đầu của mục kế tiếp
  (`page.item.index` gọi tên mục đó); `next` trỏ `{offset: item.index, item_offset: số ký tự đã giao}`. Trang hoàn tất một mục (phần còn
  lại) có thể ngắn hơn `MIN_PAGE`, tối đa một trang cho mỗi mục bị tách. Trước đây một mục nhỏ đứng trước mục lớn cho trang 27 ký tự và
  core chặn job. Quy tắc này chỉ được thử SAU khi trang gồm các mục nguyên vẹn đã ngắn, và chỉ giữ khi nó làm trang đó hợp lệ (cuối cùng,
  hoặc ≥ `MIN_PAGE`): phần đầu mục kế lấy chỗ của các trường cùng kết quả, nên trang mà P5b đã phục vụ hợp lệ không bao giờ bị thay bằng
  trang xấu hơn (L1 của probe), và lần cấp phát lại vượt ngân sách vài ký tự được thử lại với phần dư trừ đi thay vì bị bỏ, để trang
  không nhỏ đi khi ngân sách lớn lên (L2). `paging.content` là định nghĩa duy nhất của "nội dung" mà `MIN_PAGE` được so với.
- **P6, bằng chứng lớn cho reviewer:** `evidence_requests` nhận chỉ số receipt hoặc `{index, field, offset, item_offset}` chép từ `next` của
  trang đã nhận. Receipt không vừa nguyên vẹn đến theo từng trang qua cùng `paging.view` của worker (`evidence.requested_pages`: trang,
  `blob` của receipt, `field_sha256` của từng trường nguyên). Mỗi vòng phải xin một trang chưa xin (`review_seen`), tối đa `MAX_ROUNDS`=10.
  Hết giới hạn hoặc xin lại trang đã nhận → `ReviewEvidenceIncomplete`: công việc KHÔNG được chấp nhận và KHÔNG bị coi là có lỗi, job
  bị chặn (`recovery.kind=review_evidence`), không tốn lời gọi worker; resume review lại từ đầu. Reviewer đã có bằng chứng mà thấy sản
  phẩm sai thì trả lời không kèm yêu cầu: đó là rejection thật, về worker như cũ. Chế độ khác `work` giữ luật cũ (3 vòng).
- **P6, trí nhớ của một lần review (F2/F3 của probe).** Reviewer không có trạng thái; trước đây lời `feedback` ở các vòng trước quay lại
  là 3 ghi chú gần nhất, mỗi ghi chú tới 700 ký tự: lỗi ghi ở trang đầu rời prompt vài vòng sau và review chấp nhận (F3); ba ghi chú
  dài làm không còn chỗ cho một trang hợp lệ và review bình thường bị chặn (F2). Nay core GIỮ NGUYÊN VĂN trong checkpoint
  (`review_findings`, `review_notes`): mã định danh (`RF<n>`, `N<n>`), vòng, bằng chứng reviewer đang nhìn (các trang của vòng đó, receipt
  nó trích), trạng thái (`open`/`resolved`, kèm `resolution` và lý do bị từ chối nếu có), độ dài gốc. Reviewer báo lỗi trong `findings`
  (chuỗi, tiền tố `r<receipt>:` tùy chọn) và đóng một lỗi bằng `resolved` `"RF<n>:<receipt>:<lý do>"`; core chỉ đóng khi lỗi đang mở
  và receipt đó đã được đưa cho reviewer trong CHÍNH review này (`review_shown`). Prompt nhận bản kết xuất có giới hạn
  (`MEMORY_TIERS`: 900/400/120 ký tự, bậc giàu nhất mà trang reviewer đã xin vẫn hợp lệ): lỗi mở luôn có mặt (id, rồi phần claim vừa
  chỗ; khi rất chật chỉ còn id), ghi chú mới nhất trước, ghi chú không vừa được nêu tên chứ không bị bỏ im lặng; nội dung đầy đủ ở
  checkpoint. Quyết định không phụ thuộc prompt: reviewer trả `accepted=true` khi còn lỗi mở → core KHÔNG chấp nhận; review là một rejection
  mang các lỗi (đặt TRƯỚC `feedback`, nguyên văn, kèm lý do một lần đóng bị từ chối) về worker, được quyết định ngay trên câu trả lời đó.
  Không có vòng hỏi lại: câu hỏi thêm làm trang vừa đọc bị cắt lại theo chỗ còn lại, và reviewer không trạng thái sẽ đọc một trang cuối
  khác (đã quan sát ở eval); prompt đã nói "đóng bằng resolved trong chính câu trả lời chấp nhận" ở mọi vòng có trang hoặc có lỗi.
  Review không có phán quyết (thiếu bằng chứng, chặn ngân sách, core từ chối trước) giữ các lỗi
  mở sang lần review kế của cùng ứng viên. Giới hạn trung thực: core không đọc được lỗi mà reviewer chỉ viết vào `feedback` mà không đưa
  vào `findings`; cái nó bảo đảm là mọi lỗi ĐÃ được khai báo không biến mất và không thể bị chấp nhận qua mặt.
- **P6, ngân sách review (F1 của probe).** Prompt đầu của một review chỉ được gửi khi receipt lớn nhất mà reviewer có thể xin (trường
  phân trang lớn nhất, xin như các vòng sau: có `field`) vẫn có một trang hợp lệ, với trí nhớ ở bậc nhỏ nhất. Trước đây finish có report
  dài vừa prompt vòng 1 nhưng không vừa trang vòng 2 chỉ bị từ chối SAU khi reviewer đã bị gọi, như một rejection. Nay bị từ chối trước
  lời gọi, và thông điệp nêu số ký tự tối đa của report (đo trong trạng thái mà review kế tiếp sẽ có, cộng một biên an toàn): văn bản
  từ chối là receipt của worker và nằm trong manifest của reviewer suốt review sau, nên nó được giữ ngắn.
