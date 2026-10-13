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

## Kết quả nghiệm thu (13/10/2026) và giới hạn

Bàn giao đầy đủ: `D:\TamNT\Workspace\9.VMAgent\HANDOVER-CODEX-REVIEW-ONECREW-GENERIC-EXECUTION-2026-10-13.txt`. Bàn giao này chưa
được Codex review.

Kết quả 16 lượt chạy trên các revision đã đóng băng (sandbox ở D:\OneCrewRuns\gx-acc):
- **Hoàn thành:** SRM `production` (Kiro), nhánh tên chỉ định tại commit chỉ định, sửa lỗi kèm test hồi quy, tự tìm cách test/build,
  lỗi môi trường phục hồi được (sau 2 lượt thất bại đã sửa runtime), tiếp tục sau khi coordinator bị ngắt.
- **Từ chối đúng:** đòi push/deploy khi không có quyền → OneCrew hỏi 1 câu.
- **Held-out:** H2 và H3 đạt ngay lượt đầu; H1 không đạt lượt đầu (đã sửa runtime, chạy lại đạt nhưng không còn tính là held-out).
- **Chi phí:** 143 lượt gọi, 7,23 credit Kiro. Mỗi lượt có 1 can thiệp môi trường của entry.

Giới hạn:
- Runner tách rời không khởi chạy được từ công cụ của Claude Desktop (Job không cho breakaway, WinError 5). Entry phải khởi chạy
  `python -m onecrew.runner`, và đóng chat sẽ dừng runner.
- Lệnh chạy trên host không phải sandbox OS.
- Fact của project chưa làm giảm số lượt gọi.
- Kiro tự cập nhật nên mỗi phiên bản mới phải kiểm chứng lại; prompt Kiro bị giới hạn 16.000 ký tự.
