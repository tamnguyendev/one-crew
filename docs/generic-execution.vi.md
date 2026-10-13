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
