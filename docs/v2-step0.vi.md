# Bước 0 của hợp đồng v2 (lát L3)

Chưa xong bước 0 thì `plan approve` từ chối, nên cổng dispatch (L1) không mở. Cưỡng bức bằng mã, không bằng lời dặn.

## Hợp đồng có thêm gì
- `size`: `S` | `M` | `L`. **S** được bỏ `options`, `understanding` ngắn (≤600 ký tự, ≤3 giả định). **M/L** cần `options` (2–5 phương án) và ≥1 giả định. Mọi cỡ đều cần ≥1 `preconditions`.
- `understanding`: `restated_goal`, `target {repo, ref, paths[]}`, `assumptions[{text, evidence}]`, `confidence` (high|medium|low), `unknowns[{id, question, status, closed_by, evidence}]`.
- `options` (M/L): `{recommended, reason, items[{id, summary, evidence[], strengths[], weaknesses[], unknowns[], cost, risk}]}`. Không có `chosen`: lựa chọn của chủ sở hữu chỉ nằm trong sự kiện `plan.approved`.
- `preconditions[]`: `{id, check, args, why}`; `check` ∈ `repo_exists`, `ref_resolves`, `path_exists`, `command_ok` (argv, trần phút), `sdk_version` (argv + regex).
- `milestones[].covers`: id output (`O1`, `O2`… theo thứ tự). Output nào không mốc nào phủ → `propose` bị từ chối.

## Lệnh
```
onecrew plan precheck <plan>                       # chạy tiền kiểm + kiểm đích, 0 call AI, không duyệt
onecrew plan brainstorm table <plan>               # bảng options ≤30 dòng
onecrew plan unknown close <plan> <id> --by doc|poc|owner --evidence <blob|url|file:dòng|lời của owner>
onecrew plan poc record <plan> <id> --answer ... --evidence <file> --confidence high|medium|low [--by poc|owner] [--poc-contract f.json]
onecrew plan approve <plan> --by owner --reference ... [--choose <option>]
```
`unknown close` và `poc record` ghi sự kiện (`unknown.closed`, `poc.answered`) **và** tạo revision mới ("unknown <id> closed") trong cùng một giao dịch; verdict của revision cũ mất hiệu lực như mọi amend. PoC độ chắc `low` chỉ ghi câu trả lời, unknown vẫn mở. PoC có `apply_to_project`/`local_branches`/`push` bị từ chối.

## Khi nào `plan approve` từ chối (trả TẤT CẢ lý do)
`confidence_low` · `unknown_open` · `unknown_unrecorded` (file ghi đóng mà sổ cái không có sự kiện) · `assumption_no_evidence` / `assumption_evidence_invalid` · `options_not_chosen` / `choose_unknown` / `option_no_evidence` / `option_evidence_invalid` / `choose_without_options` · `target_repo` / `target_ref` / `target_path` · `precondition_red`.
Thành công ghi `plan.step0_closed` (unknown đã đóng + bằng chứng, lựa chọn, receipt tiền kiểm). Mỗi lần chạy tiền kiểm ghi `precondition.recorded` kèm receipt blob (cả khi đỏ). Chọn lại sau khi đã duyệt bị từ chối; chỉ `plan amend` (CREQ) rồi duyệt revision mới.

## Sau review Opus (gói v2-fix: C11, C12, C13)
- **Bằng chứng của giả định và phương án** (C12): `understanding.assumptions[].evidence` và **mọi** `options.items[].evidence[]` đi qua cùng luật với bằng chứng đóng unknown (`step0.evidence_kind`): blob có trong kho, URL, hoặc `file:dòng`. Câu chữ ("trust me") bị từ chối, lý do nêu rõ trường (`understanding.assumptions[1].evidence`, `options.items[A].evidence[1]`). Câu chữ chỉ được khi **owner** là người viết nội dung revision (`content_author` trong sự kiện `plan.proposed`/`plan.amended`); `unknown close` giữ nguyên `content_author` của revision trước (đóng một unknown không biến chữ của AI thành chữ của owner). Phiên AI không được ghi `--author owner|user` (`plan propose|amend` từ chối).
- **Ai chạy lệnh** (C11): `plan.require_owner` từ chối khi biến `CLAUDE_CODE_CHILD_SESSION` có mặt, nên `plan approve|accept`, `plan unknown close --by owner`, `plan poc record --by owner`, `verdict record --by owner`, `plan enforce`, `hook mode` bị từ chối cả khi gọi `python -m onecrew.v2.plan_cli` hoặc gọi hàm Python. AI vẫn được `plan unknown close --by doc|poc` và `plan poc record` (mặc định `--by poc`, file bằng chứng là chứng cứ). Sự kiện `plan.approved`, `plan.accepted`, `unknown.closed`, `poc.answered` ghi `actor_env` (giá trị `ONECREW_ACTOR`) và `ai_session`: `true` (có biến phiên AI), `false` (không có biến và tiến trình tự khai `ONECREW_ACTOR=user|owner`), `"unknown"` (không có biến, không khai: AI đã gỡ biến cũng trông như vậy nên không khẳng định gì).
- **Hook/permission** (C13): `bash_deny` có luật cho `plan unknown close … --by owner`, `plan poc record … --by owner` (cả `--by=owner`, `--b owner` là tiền tố argparse chấp nhận, ngoặc kép, xuống dòng) và cho `python -c "import onecrew.v2…; approve(…)"`; `permissions.deny` sinh ra có `plan unknown close*owner*`, `plan poc record*owner*`.

## Giới hạn đã biết
Tiền kiểm `command_ok` chạy lệnh của hợp đồng với quyền của người gõ `plan approve`/`precheck`; chủ sở hữu đọc `plan show` trước khi duyệt. Bằng chứng chỉ được kiểm là *có trỏ tới đâu đó* (blob có trong kho, URL, `file:dòng`), không kiểm là *đúng*; người duyệt đọc nó. Xem `docs/v2-parking-lot.vi.md`.

## Bãi đỗ L3 (phát hiện, chưa làm)
- L2/L4: `size` do AI tự khai; AI có thể khai `S` để bỏ `options`. Chủ sở hữu thấy `size` ở `plan show`, nhưng chưa có luật ngoài (ví dụ cỡ suy từ số file/ngân sách) hoặc màn hình duyệt nhắc rõ.
- L2: `command_ok`/`sdk_version` chạy argv do hợp đồng viết, không bị hộp cát, với quyền người gõ approve/precheck; chưa có allowlist hoặc ghim hash lệnh.
- L3.1: `unknown close`/`poc record` đọc revision mới nhất rồi mới amend; một amend chen giữa hai bước bị ghi đè (amend chỉ kiểm "giống hệt", không kiểm revision gốc).
- L3.1: sự kiện `unknown.closed` khớp theo (id, evidence), không theo nội dung câu hỏi; sửa câu hỏi sau khi đóng vẫn "đóng".
- L3.1: bằng chứng chỉ kiểm có trỏ tới (blob/URL/file:dòng), không kiểm trúng; không đọc lại file:dòng để so.
- L3.1: PoC độ chắc `low` ghi `poc.answered` nhưng `plan show` chưa hiện câu trả lời đó.
- L3.1: `plan.step0_closed`, `precondition.recorded`, `unknown.closed`, `poc.answered` không nằm trong `plan.KINDS`/`derive`; `show` đọc riêng. Báo cáo L5 phải đọc chúng.
- L3.1: `target.paths` phải tồn tại; file sẽ tạo mới nằm ở `scope.owned`, chưa đối chiếu hai khối.
- L3.1: tái dùng `native_change.prepare_test_environment` (kiểm Flutter offline) bỏ qua vì chỉ chạy được trong workspace native; CTS cần công thức `command_ok`/`sdk_version` riêng (ví dụ `flutter --version` + regex).
- L3.1: hết giờ lệnh tiền kiểm chỉ diệt cây tiến trình trên Windows bằng `taskkill`; Linux/macOS dựa `Popen.kill` (cây con có thể còn).
- L3.1: bảng `brainstorm table` cắt chữ ở 112 ký tự; phương án dài bị mất chi tiết (đọc `plan show`).
