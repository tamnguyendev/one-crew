# W01 (khảo sát, R04) — ánh xạ `authority` của v1 sang root v2: trường nào thi hành ở gate, trường nào chỉ ghi

Câu trả lời đối chiếu với implementation đã chọn (hình thức ở 00 §7, O2): root v2 giữ nguyên bảy trường v1 cộng ba danh sách
(`self_decide`, `granted_actions`, `auto_accept`); không có bậc, lớp hay bảng quyền riêng trong hợp đồng (`onecrew/v2/authority.py:3-8, 26-28`).

| Trường v1 | Ý nghĩa giữ nguyên | Thi hành ở đâu (v2) | Ghi nhận |
|---|---|---|---|
| `edit` | Được ghi trong `scope.owned` | `authority._write` (`authority.py:243-249`) qua `covers()` (`:125-150`): mọi hành động ghi/candidate ngoài `scope.owned` thành U2 với `findings`; root cũ không có grant thì `edit=True` vì chủ sở hữu đã duyệt `scope.owned` (`:119`); hook ngoài (`hook_cli.judge_path`) chặn Edit/Write/Bash theo cùng `owned` | `plan.approved` niêm phong grant (`authority.seal`, `:105`); `decision.recorded` khi OneCrew tự quyết |
| `commands` | Được chạy lệnh trong workspace | `_simple_grant('commands')` (`:251-259`); child thực thi: `PERMISSION_FIELDS` (`:154-156`) ánh xạ `workspace.run`, `sandbox.test`, `native.test`, `android.build` → `commands` và `child_reason` (`:195-211`) từ chối job con vượt grant trước khi dispatch (`v2/gate.py`) | như trên |
| `unconfined_commands` | Lệnh không bị OS giới hạn | `_simple_grant('unconfined_commands')` đòi cả `commands` (`:255`); `child_wanted` suy `unconfined_commands=True` cho native trusted-project tests (`:183-188`) | |
| `local_branches` | Tên nhánh cục bộ được tạo | `covers()` đòi tên tường minh, không chấp nhận wildcard (`:130-136`); `child_reason`: `git.branch` không có tên nhánh → U2 (`:204-208`) | |
| `branch_at` | Điểm cắt nhánh (`pinned_head`) | `covers()` so với grant (`:137-138`) | |
| `apply_to_project` | Áp candidate vào cây dự án | `PERMISSION_FIELDS` `project.apply`/`workspace.apply` → `apply_to_project`; `common_handoff.handoff` chỉ áp khi grant có (`onecrew/common_handoff.py`, quyết định Q4 qua `internal_plan.decide`) | `workflow.handoff` (lớp B, root `plan-ns:`) |
| `edit_tests` | Được sửa test | `_simple_grant('edit_tests')`; `child_wanted` bật khi job con đụng test (`:188`); W05 phát hiện làm yếu bộ kiểm qua hash/manifest (`wfkit/kitguard.py`, T19/T21) | |
| `push` | — | **Không bao giờ cấp**: `git.push` ở child → U2 (`:206`); không phải trường hợp đồng | |
| `self_decide` | Q1–Q12 OneCrew được tự quyết | `internal_plan.decide` (`v2/internal_plan.py:88-94`): Q ngoài danh sách → request cho chủ sở hữu; trong danh sách → bản ghi quyết định (`decision.recorded`, W03) | chỉ ghi |
| `granted_actions`, `auto_accept` | Hành động đã cấp; không auto-accept | `normalize` (`:86-102`) cố định `auto_accept=[]`: nghiệm thu luôn là động từ owner | chỉ ghi |

Kết luận khảo sát: không thêm trường mới; bốn trường bool + `local_branches`/`branch_at` thi hành ở gate (`authority.decide` → U2 khi vượt),
`self_decide` quyết định hỏi hay tự quyết, `apply_to_project` thi hành ở bước handoff, `push` không tồn tại. Dùng lại TD08 (`work_contract` của v1)
và TD14 `covers()`. Kiểm: `tests/test_wf_r04a_authority.py` (T17a, T16a, T37), `tests/test_wf_engine.py` (T04a), hook `tests/test_v2_l2.py`.
