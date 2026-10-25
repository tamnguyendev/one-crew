# W13 (khảo sát, R04) — engine cho lát tuần tự R04 và điều kiện mở song song ở R08

Câu trả lời đối chiếu với implementation đã chọn:

- **Không viết scheduler thứ hai.** Lát tuần tự dùng chính `dependency_core.ready_batch` của v1 (`onecrew/dependency_core.py:ready_batch`, `:19`) làm
  bộ chọn thứ tự và quyền sở hữu rời nhau; engine chỉ dịch trạng thái node thành token `done`/`depends_on`/`branch_errors` và cấp số slot
  (`onecrew/v2/engine.py:_ready`, `:153`). Trạng thái node ban đầu từ `dependency_core.initial_node_states` (`engine.py:_fresh`, `:23`); phạm vi ảnh hưởng
  khi fail/finding/repair từ `dependency_core.affected_tasks` (`engine.py:state`, `:102`; `engine.request_action`, `:639`;
  `finding_scope.py` `:32`, `:84`; `repair_tasks.py` `:73`, `:151`).
  Quy ước trích dẫn (làm mới theo mã hiện tại, HEAD 2bba0f0 cộng thay đổi chưa commit): ưu tiên `tệp:hàm`; số dòng chỉ là vị trí của hàm lúc làm mới
  và có thể lệch khi mã đổi — khi lệch, tìm theo tên hàm.
- **Admission và vòng đời attempt của v1.** Mỗi node là một job con `task_intake.submit` với ngân sách/deadline của root (`engine.step`, lời gọi `submit(...)` ở `engine.py:365`),
  reserve/launched/finish/unknown qua `Control` (`engine.step`, `engine.py:328`; `control.configure` `:369`, `control.reserve` `:379`,
  `control.unknown` `:433`); không có hàng đợi riêng. Kết quả về muộn bị fence bằng
  generation của `Control` và `valid_internal_revisions` (`engine.state`, `engine.py:30`; `engine._publication_current`, `:189`).
- **Một slot ở R04** (`engine._slot_limit`, `engine.py:146-151`): `slots=1` mặc định; mô hình node/cạnh/generation của delivery được giữ qua
  `plan.revised` (kế hoạch nội bộ, `internal_plan.py`) thay vì mở rộng item/mốc v2.
- **Điều kiện mở song song ở R08** (`W14b`): root khai capability `parallel-engine` và executor khai `isolate` (`engine.step`, nhánh `slots==2` ở `engine.py:335-338`,
  `engine._slot_limit` `:146-151`); khi đó `slots=2` qua cùng `ready_batch` (`engine.run_batch`, `engine.py:458`); hai node ghi cùng phạm vi không
  bao giờ cùng chiếm hai slot (`engine._ready` loại trừ `owned` đang hoạt động, `engine.py:160-168`, so trùng bằng
  `dependency_core.owned_overlap` không phân biệt hoa thường; T15c [E8], `tests/test_wf_parallel_engine.py`; trên executor không khai `isolate`:
  `tests/test_wf_w33b_evidence.py`).
  Managed worker (W33b/W36) pause tại điểm an toàn qua `managed_executor.py`; tài nguyên/WIP (RR) không thuộc engine này.

Kiểm: `tests/test_wf_engine.py` (T04a, T16b, T17b), `tests/test_wf_parallel_engine.py` (T04d), `tests/test_wf_failed_dependency.py` (T05),
`tests/test_wf_engine_cli.py`. Không có đường nào tạo scheduler, hàng đợi hay bộ đếm generation riêng ngoài `Control` và `dependency_core`.
