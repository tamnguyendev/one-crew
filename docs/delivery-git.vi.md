# Git cục bộ cho delivery: `onecrew/delivery_git.py`

Ngày 12/10/2026, bước S5 trong thiết kế node delivery (synthesis §3.5 mục 1 và 4, §3.7). Module này **chưa được nối vào plan**; delivery sẽ gọi nó ở preflight (baseline), node `version`, node `commit` và lệnh `delivery restore-baseline`.

## Các hàm
| Hàm | Việc làm |
|---|---|
| `baseline(project, paths)` | Ghi trạng thái repo trước khi OneCrew sửa: `head`, `branch`, `detached`, `operation` (merge/rebase đang dở), `status` (porcelain v2 đã parse), `dirty` và `untracked` (sha256 của byte working, có giới hạn, `truncated`), `autocrlf`, `ignorecase`. Với `paths` (file plan sở hữu): thuộc tính eol (`text`, `eol`, `filter`, `working-tree-encoding`, eol của index và working) và byte gốc (`files`). |
| `check_paths(baseline, paths, deny_globs)` | Trả danh sách lỗi có kiểu: `dirty_at_baseline`, `staged_at_baseline`, `ignored`, `denied`, `outside_repo`, `external_filter`, `not_a_file`, `case_mismatch`. Danh sách rỗng nghĩa là được commit. `.gitattributes`, `.gitmodules`, `.git`, `.env*` luôn bị từ chối. |
| `version_bump(project, relpath, field, bump, expected_sha)` | Tăng chuỗi version cấp cao nhất của file JSON (major/minor/patch) bằng compare-and-swap. Chỉ thay đúng token chuỗi đó; thụt lề, thứ tự khoá, CRLF/LF và BOM giữ nguyên byte. Trả `{old, new, sha_before, sha_after}`. |
| `commit(project, baseline, paths, message, intent_id, expected_head, deny_globs, applied)` | Xem mục dưới. Trả receipt `{commit, parent, branch, paths, intent, author, pushed: false, reconciled, verified}`. |
| `reconcile(project, intent_id, expected_head)` | Tìm commit có trailer `OneCrew-Intent: <intent_id>` nằm ngay trên `expected_head` và tới được từ HEAD (mất ack). Receipt luôn có `verified: false`. |
| `restore_baseline(project, baseline, applied)` | Đưa các path trong `applied` (`{path: sha256 OneCrew đã ghi, hoặc null nếu OneCrew đã xoá}`) về byte baseline, chỉ khi byte hiện tại vẫn đúng là byte OneCrew đã ghi. Có lỗi ở bất kỳ path nào thì không ghi gì (`changed_since_applied`, `not_in_baseline`). |
| `render_message(template, fields)` | Dựng message từ `{subject, body, trailers}` với trường `{name}`; thiếu trường, subject nhiều dòng hoặc trailer `OneCrew-Intent` tự đặt đều bị từ chối. |

## Hoa thường của path
Repo Windows thường có `core.ignorecase=true`: git và hệ thống file coi `Extension/src/app.ts` là `extension/src/app.ts`. Vì vậy mọi path (ở `baseline`, `check_paths`, `commit`, `version_bump`, `restore_baseline`) phải viết đúng như trên đĩa và trong index:
- Thành phần nào đang tồn tại trên đĩa thì tên phải có đúng như vậy trong danh sách của thư mục cha. Cách viết khác (hoa thường, tên 8.3) bị từ chối `case_mismatch`.
- Khi `core.ignorecase=true`, path hoặc thư mục cha trùng (không phân biệt hoa thường) với một path trong index hoặc HEAD baseline mà viết khác cũng bị `case_mismatch`. Điều này bắt cả file đã bị xoá trên đĩa.
- Deny glob (kể cả `.gitattributes`) luôn so khớp không phân biệt hoa thường, nên `.GITATTRIBUTES` hay `extension/Secret/**` vẫn bị `denied`. Trạng thái baseline cũng được tra không phân biệt hoa thường khi repo bỏ qua hoa thường.

Mọi từ chối này xảy ra trước lệnh git ghi đầu tiên. Nếu commit hỏng sau `git add --intent-to-add`, mục intent-to-add được gỡ theo tên git đã ghi vào index, không theo cách viết được yêu cầu.

## Commit
1. Nếu đã có commit mang cùng intent ngay trên head mong đợi thì không commit lần hai. Lúc này chỉ lặp lại được các kiểm tra không cần trạng thái trước commit:
   - nhánh là nhánh baseline;
   - commit cha là head mong đợi và trailer có mặt;
   - các path của commit nằm trong `paths` và vẫn qua `check_paths`;
   - byte working vẫn là byte `applied` (nếu có truyền);
   - `git status` của các path đó rỗng.

   Sai một điểm thì báo `verification_failed`. Qua hết thì trả receipt `reconciled: true, verified: false`: không thể chứng minh lại rằng mọi path khác vẫn giữ nguyên byte.
2. HEAD phải bằng `expected_head` (mặc định là head baseline) và nhánh phải là nhánh baseline; không có merge/rebase đang dở. Sai thì báo `head_moved`, `branch_changed`, `detached` hoặc `operation_in_progress`, không ghi gì.
3. Mọi path phải qua `check_paths`; nếu truyền `applied` thì byte working phải đúng byte OneCrew đã ghi. Path mới được thêm bằng `git add --intent-to-add` (commit hỏng thì gỡ lại).
4. Chạy `git commit --only -- :(literal)<path>...`. Hook của repo chạy bình thường, không bao giờ dùng `--no-verify`. Author và committer lấy từ config của repo. Message kết thúc bằng trailer `OneCrew-Intent: <intent_id>`.
5. Sau commit, kiểm tra:
   - `HEAD^` bằng head mong đợi;
   - trailer có mặt;
   - commit chỉ đổi các path được chọn;
   - `git status` của các path đó rỗng, tức blob đã commit bằng file working sau bộ lọc eol của chính git, nên không có thay đổi CRLF với `core.autocrlf=true`;
   - index, status và byte working của mọi path khác giống hệt trước khi commit.

   Sai một điểm thì báo `verification_failed` kèm commit id. Commit đã tạo không bị tự động gỡ. Qua hết thì receipt có `verified: true` (kể cả khi mất ack rồi tìm lại ngay trong cùng lần gọi, `reconciled: true`).

**Khi nối vào plan:** node commit phải lưu bền kết quả `verification_failed` (commit id, `failed`) trước khi hỏi hay thử lại. Một receipt `verified: false` không bao giờ được coi là đã giao: nếu ledger không có receipt `verified: true` cho intent đó thì đây là blocker, kể cả khi người dùng trả lời "thử lại".

Mọi lỗi là `GitRefusal` (một `LedgerError`) có `kind` và `problems`, nên `Delivery.run` sẽ chuyển thành recovery có kiểu.

## Không push
Module không có đường gọi nào tới repo khác. `tests/test_delivery_git.py::test_no_push_code_path` quét mã nguồn và theo dõi argv của mọi lệnh `git` để khẳng định điều này.
