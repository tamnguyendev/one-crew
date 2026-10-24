# W13 (khảo sát, R04) — engine cho lát tuần tự R04 và điều kiện mở song song ở R08

Câu trả lời đối chiếu với implementation đã chọn:

- **Không viết scheduler thứ hai.** Lát tuần tự dùng chính `dependency_core.ready_batch` của v1 (`onecrew/dependency_core.py:5-12`) làm
  bộ chọn thứ tự và quyền sở hữu rời nhau; engine chỉ dịch trạng thái node thành token `done`/`depends_on`/`branch_errors` và cấp số slot
  (`onecrew/v2/engine.py:150-170`, `_ready`). Trạng thái node ban đầu từ `dependency_core.initial_node_states` (`engine.py:24`); phạm vi ảnh hưởng
  khi fail/finding/repair từ `dependency_core.affected_tasks` (`engine.py:100`, `finding_scope.py`, `repair_tasks.py:72-73`).
- **Admission và vòng đời attempt của v1.** Mỗi node là một job con `task_intake.submit` với ngân sách/deadline của root (`engine.py:264-270`),
  reserve/launched/finish/unknown qua `Control` (`engine.step`, `engine.py:246-351`); không có hàng đợi riêng. Kết quả về muộn bị fence bằng
  generation của `Control` và `valid_internal_revisions` (`engine.state`, `engine.py:30-111`).
- **Một slot ở R04** (`_slot_limit`, `engine.py:143-147`): `slots=1` mặc định; mô hình node/cạnh/generation của delivery được giữ qua
  `plan.revised` (kế hoạch nội bộ, `internal_plan.py`) thay vì mở rộng item/mốc v2.
- **Điều kiện mở song song ở R08** (`W14b`): root khai capability `parallel-engine` và executor khai `isolate` (`engine.step`, `engine.py:252-254`,
  `_slot_limit` `:145-146`); khi đó `slots=2` qua cùng `ready_batch` (`engine.run_batch`, `engine.py:352-368`); hai node ghi cùng phạm vi không
  bao giờ cùng chiếm hai slot (`_ready` loại trừ `owned` đang hoạt động, `engine.py:157-168`; T15c [E8], `tests/test_wf_parallel_engine.py`).
  Managed worker (W33b/W36) pause tại điểm an toàn qua `managed_executor.py`; tài nguyên/WIP (RR) không thuộc engine này.

Kiểm: `tests/test_wf_engine.py` (T04a, T16b, T17b), `tests/test_wf_parallel_engine.py` (T04d), `tests/test_wf_failed_dependency.py` (T05),
`tests/test_wf_engine_cli.py`. Không có đường nào tạo scheduler, hàng đợi hay bộ đếm generation riêng ngoài `Control` và `dependency_core`.
