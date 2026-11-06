# Sol6 — khép S5-1…S5-8 và N1…N7 để Codex kiểm lại

Commit code `39d47be07679a91b0c7835e43049913cb04e83d9`, nhánh `claude/sol6-close-s5`, worktree `C:/OneCrewRuns-sol6/wf`. Baseline `38fe8e7` (code Sol5 `8f53170`). Version `2.5.0.dev10+sol6.3`. Gói `C:/OneCrewRuns-sol6/final3`. Wheel `wheel/onecrew-2.5.0.dev10+sol6.3-py3-none-any.whl`, SHA256 `50d3d4bde87a7814027754501972b9fb201b826a6d9d61cbc9addbedab2e7c90`.

> **Đính chính:** S5-4 chưa khép hoàn toàn ở bản này. Nhánh lỗi của kho object tạm vẫn ghi vào project, và có ca báo đạt giả. "`engine next`" dưới đây là sai tên, đúng là `engine.next_action`. Xem [Sol6.4](SOL6-4-CODEX-HANDOFF.vi.md).

**Kết luận: S5-1…S5-8 và N1…N7 đã khép trên wheel này, sẵn sàng để Codex kiểm lại.** Chưa push, tag, phát hành, nâng runtime hay nghiệm thu thật. Chưa có review độc lập của Codex cho bản này.

## Bảng issue

"Log" nằm trong `final3/logs/probes`. Log lỗi của baseline nằm trong `C:/OneCrewRuns-rv3/logs`; đối chiếu từng dòng ở `final3/probe-assessment.json`. Test nằm ở `tests/test_sol6_recovery.py`, chạy trên wheel cuối.

| Mục | Trạng thái | Thay đổi | Test | Log wheel cuối |
|---|---|---|---|---|
| S5-1 | Đã khép | Mỗi finding được giải phóng theo đúng thất bại của nó; repair chuẩn bị lại khi có thất bại mới, lặp lệnh không tăng generation (`finding_scope.py`, `repair_tasks.py`) | `RepairChains`, `TwoMilestones`, `UnrelatedHold`, `EvidenceChecks` | `s5a.log` S4, S5; `s5d.log` S32; phản chứng `s5b.log` S10 |
| S5-2 | Đã khép | Replan chạy được tới nghiệm thu; sau replan vẫn đỏ thì dừng có lý do, không lặp (`recovery_policy.py`, `engine.py`) | `RepairChains`, `EvidenceAndNodeFailures` | `s5b.log` S6b, S6c |
| S5-3 | Đã khép | Câu hỏi chỉ nêu lựa chọn làm được (`amend_plan`, `stop`); continue không cấp Q5 ngầm; amendment được duyệt thay câu hỏi cũ (`engine.py`, `answer_effects.py`, `plan.py`) | `NoQ5`, `NoQ5AtNode` | `s5d.log` S9b, S9c, S9d |
| S5-4 | Đã khép, một giới hạn nêu dưới | Track, digest, list, detail, overview: 0 lần băm. `plan show`, `engine next` và báo cáo vẫn kiểm cây thật nhưng không ghi object nào vào project, qua kho object tạm (`command.leaves_no_objects`) | `ReadsAndStates` | `s5c.log` S18; `big.log` S20; phản chứng `s5e.log` S34 |
| S5-5 | Đã khép | Hướng dẫn nêu đúng lệnh sửa khi mốc chỉ ở node tích hợp, `owned` là thư mục, và sau dừng rồi amend (`engine.py`, `common_handoff.py`) | `IntegrationOnly`, `FolderScope`, `Stopped` | `s5a.log` S3; `s5d.log` S28, S31b |
| S5-6 | Đã khép bằng dừng rõ, không thêm cửa gia hạn | Hết hạn hoặc thiếu call mà chưa đủ bằng chứng: trạng thái `stopped` có lý do, nói rõ hạn được niêm phong; không hứa cửa không có. Đủ bằng chứng thì vẫn nghiệm thu được | `ReadsAndStates` (s5_6) | `s5f.log` S16; `deadline2.log`; đối chứng `deadline.log` |
| S5-7 | Đã khép | Khôi phục guard capability: root `plan:` cũ không báo lỗi sau verdict xanh, không đổi namespace (`verdict.py`) | `LegacyRoot` | `s5d.log` S33 |
| S5-8 | Đã khép | Phạm vi chạy lại theo ảnh hưởng thật: B giữ nguyên nếu không đọc file của A; node đọc phải chạy lại có giải thích và tính đủ chi phí; thiếu call từ chối trước khi đổi gì (`repair_tasks.py`) | `ManyWriters`, `ManyWritersWithReader` | `s5a.log` S2; `s5e.log` S25 |
| N1 | Đã khép | Ngay lần đọc đầu sau verdict không rõ kết quả, hướng dẫn nêu `verdict release-run` (`verdict.runs_to_hold`, `engine.py`) | `ReadsAndStates` (n1) | `s5e.log` S21 |
| N2 | Đã khép | Check node bị giữ nêu `release-check` | `ReadsAndStates` (n2) | `s5e.log` S30 |
| N3 | Đã khép | `plan show` ở terminal chủ đọc verdict đã ghi như nghiệm thu; thực thi mới vẫn so môi trường nghiêm ngặt (`plan.py`, `verification_evidence.py`) | `ReadsAndStates` (n3), `test_wf_evidence_binding` | `ownerenv.log`; phản chứng `s5e.log` S34 |
| N4 | Đã khép | Thiếu call: không còn gợi ý `engine revise` | `ReadsAndStates` (s5_6) | `f8.log` N23 |
| N5 | Đã khép | Verdict xanh trên cây không đổi: in `findings reject` chạy được, không in lệnh bị từ chối | `RepairChains` (n5) | `s5e.log` S22 |
| N6 | Đã khép | Mốc thứ hai băm như Sol4 (4 lần) | `ReadsAndStates` (n6) | `s5c.log` S19 |
| N7 | Đã khép | Lỗi snapshot lúc nghiệm thu chỉ nêu giới hạn đang áp dụng | `ReadsAndStates` (n7) | `s5c.log` S17 |

Trạng thái: CLI, track và digest phân biệt đang làm, bị chặn, đã dừng, chờ nghiệm thu, đã nghiệm thu (`test_status_words_tell_the_five_states_apart`; `s5b.log` S6c).

**Nguyên nhân chung.** Đường sửa chỉ được thiết kế và kiểm cho một vòng, một node ghi, một finding. Một marker chỉ giải phóng một finding, nên trạng thái sau lần đỏ tiếp theo không có cửa nào làm được. Bản sửa dùng lại repair, finding, recovery policy, CAS và request đã có; không thêm engine, ledger hay cơ chế review.

## Kết quả kiểm trên đúng snapshot

Một lượt duy nhất trên wheel trên, `final3/logs/reg`, không cộng từ lượt khác.

| | Kết quả |
|---|---|
| Hồi quy | 67 nhóm (53 module và 14 lớp của `test_sol6_recovery`): **727 passed, 0 failures, 0 errors, 0 skipped**, `wrong_origin` 0. Module có trong wheel nạp từ venv; 32 helper chỉ thuộc v1 nạp từ cây nguồn cùng commit |
| Ba nhóm setUpClass thiếu baseline Git | 3 lớp từng lỗi trong `test_wf_r02_outcome` và `test_wf_r03a_run_started`: setUpClass chạy được. Hai module chạy đủ 18 và 18 test, 0 đỏ |
| Probe | 24/24 chương trình thoát mã 0; log được đọc theo từng issue. Probe nhạy thời gian chạy riêng khi không có việc khác |
| Đối chiếu baseline và wheel cuối | 31/31 dòng đạt; 27 dòng tìm thấy đúng lỗi hoặc đối chứng trong log baseline, 4 dòng là ca mới không có baseline |
| Smoke | 38/38 trên gói; `thu-goi.ps1` đạt 38 điều kiện trên venv mới (`C:/OneCrewRuns-sol6/try-20261106-083957`). Đây là fixture |
| Định danh gói | Payload 145/145 khớp `git archive`, cài đúng từng file, 142/142 module nạp từ venv, không PYTHONPATH (`identity-result.json`) |
| Mốc bảo vệ | 6/6 giữ hash (registry, hook và config SignSDK, wheel Sol3, Sol4, Sol5); `C:/OneCrewRuns-sol/wf` sạch ở `38fe8e7` |

Thời gian đọc, project 5.000 file, máy rảnh (`big.log`). Số Sol4 và Sol5 lấy từ `REVIEW-SOL5.vi.md`, không phải đo trong lượt này.

| Lệnh | Sol4 | Sol5 | Sol6 |
|---|---|---|---|
| `track show` | 0,9 s | 5,3 s | 0,9 s |
| `plan digest` | 0,6 s | 4,9 s | 0,6 s |
| `track list` | 0,7 s | 5,0 s | 0,8 s |
| `tracking.detail` | 0,4 s | 4,6 s | 0,4 s |
| `tracking.overview` | 0,3 s | 4,5 s | 0,3 s |
| `plan show` | 4,6 s | 4,7 s | 4,8 s |

Chưa chạy toàn gate; 67 nhóm trên là phạm vi chịu ảnh hưởng.

`final` (`sol6.1`, `2a66b9e`) và `final2` (`sol6.2`, `7ed1b40`) là gói trung gian, không bàn giao. Đọc log trên chúng phát hiện N1, trạng thái dừng và `plan show` ghi object trên cây lệch, dù test và mã thoát đều xanh. Kết quả của hai gói đó không được tính cho wheel này.

## Giới hạn còn lại và ảnh hưởng tới phát hành

| Giới hạn | Ảnh hưởng thực tế |
|---|---|
| `plan show` và `engine next` vẫn băm 1 lần mỗi lần gọi, như Sol4. Chúng là lệnh kiểm cây hiện tại: lời từ chối nghiệm thu dẫn tới `plan show`, và `engine next` phải biết cây đổi | Repo lớn sẽ chậm ở hai lệnh này, không ở trang theo dõi. Không chặn phát hành |
| Chưa đo trên repo cỡ MEP (108.897 file) | Số đo chỉ tới 5.000 file. Nên đo khi thử thật |
| Chưa chạy provider thật, terminal thật của chủ, hook trong phiên thật. Worker là tiến trình cục bộ; chủ là fixture | Cần thử có giám sát trước khi tuyên bố ổn định |
| Trạng thái dừng trên trang web mới kiểm test và cú pháp JS, chưa kiểm bằng trình duyệt; làn của thẻ vẫn là "Đang xử lý", nhãn là "Đã dừng · chờ bạn quyết định" | Hiển thị, không ảnh hưởng quyền. Không chặn |
| Root hết hạn mà chưa đủ bằng chứng thì dừng hẳn, không có lệnh gia hạn | Đúng chỉ thị. Chủ phải mở việc mới nếu muốn đi tiếp |
| `verdict artifact` vẫn ghi object: đây là cửa đưa ra mã cây để nghiệm thu nên phải giữ được cây | Có chủ ý |
| Việc phát triển bản này không có hợp đồng v2 và OneCrew không giám sát, vì chỉ thị cấm đụng sổ thật | Bằng chứng lấy từ wheel và lab, không từ sổ thật |

Làm sau, không chặn bàn giao: root engine có mốc `owner-manual` không tới được handoff (có từ Sol4); `engine replan` thiếu tham số trả `TypeError` dạng JSON, mã 2.

## Test cũ đã đổi kỳ vọng

Không bỏ test nào. Mỗi thay đổi có lý do hành vi:

- `test_wf_findings` (2 test), `test_obs2_work` (1 test): kỳ vọng đã cũ từ trước Sol6. Đã chạy lại bản test `38fe8e7` trên wheel Sol5: cả 3 đỏ (`C:/OneCrewRuns-sol6/base-tests/base.log`, `base2.log`). Cập nhật theo luật 2.5-A.
- `test_wf_evidence_binding`: `plan show` ở môi trường khác nay báo `execution_environment_changed`, không báo `stale` (đúng N3). Phần đánh giá nghiêm ngặt trong cùng test giữ nguyên.
- `test_v2_report`, `test_sol4_operator_flow`: root đã dừng nằm trong danh sách việc mở và mang chữ "đã dừng" (đúng yêu cầu tách trạng thái).
- `wf_oldversion`: thêm `ONECREW_BASELINE_REPO` để đọc baseline Git khi test chạy từ cây trích xuất. Đây là cách sửa ba nhóm setUpClass.

## Đính chính kết luận cũ

- **"L1–L15: 14 Closed, L3 Partial"** (`REVIEW-SOL5.vi.md`, memory): đúng theo từng mục L, nhưng cùng báo cáo nêu rõ root engine bị kẹt ở S5-1…S5-3, nên không được đọc là Sol5 sẵn sàng. **"Đã khép L1–L15"** (`docs/SOL5-CLAUDE-HANDOFF.vi.md`, wiki 05/11) không đúng với root engine: test của Sol5 chỉ đi một vòng, một node ghi, `owned` là file. Coverage nay ghi L3 là Partial trên Sol5, L6 và L10 kèm hồi quy S5-7, S5-4.
- **"480 test, 0 fail, 0 skip"**: số đó loại trừ 3 lỗi setUpClass (2 ở `test_wf_r02_outcome`, 1 ở `test_wf_r03a_run_started`), nên các test trong các lớp đó không chạy. Không được đọc là toàn bộ xanh. Trên wheel này cả hai module chạy đủ.

## Thử gói

```bash
powershell -ExecutionPolicy Bypass -File "C:/OneCrewRuns-sol6/final3/thu-goi.ps1"
```

Lệnh kiểm SHA256, cài wheel vào venv mới trong `C:/OneCrewRuns-sol6/try-*`, chạy smoke. Đạt khi dòng cuối bắt đầu bằng `DAT:` và có `38 dieu kien smoke`. Lệnh không đụng gói, runtime thật, hook, registry hay sổ thật. Đây là fixture, không phải nghiệm thu.

## Codex kiểm lại

1. Đọc diff: `git -C C:/OneCrewRuns-sol6/wf diff 38fe8e7..39d47be`.
2. Đừng ghi vào `final3`. Chạy phản chứng bằng lab riêng:

```bash
source /c/OneCrewRuns-sol6/final3/env.sh; export RV2_LAB='C:\codex-sol6-lab' TEMP='C:\codex-sol6-lab\tmp' TMP='C:\codex-sol6-lab\tmp' LOCALAPPDATA='C:\codex-sol6-lab\may\local' APPDATA='C:\codex-sol6-lab\may\roaming'; mkdir -p /c/codex-sol6-lab/tmp /c/codex-sol6-lab/may/local /c/codex-sol6-lab/may/roaming; cd /c/OneCrewRuns-sol6/final3/probes; "$VPY" -B -X utf8 p_s5.py second_attempt
```

3. Đổi tên probe theo issue:

| Issue | Lệnh |
|---|---|
| S5-1 | `p_s5.py second_attempt second_final_red forged_inputs`; `p_s5b.py repair_breaks_other` |
| S5-2 | `p_s5.py exhaust_replan replan_then_red` |
| S5-3 | `p_s5b.py no_q5_final no_q5_stop no_q5_node` |
| S5-4 | `p_s5.py views_walk big_read`; `p_s5b.py strict_parts` |
| S5-5 | `p_s5.py integration_only`; `p_s5b.py dir_owned stopped_amend_revise` |
| S5-6, N4 | `p_s5.py deadline_chain`; `p_deadline2.py`; `p_f8.py` |
| S5-7 | `p_s5b.py legacy_root` |
| S5-8 | `p_s5.py multi_writer multi_writer_direct`; `p_s5b.py split_budget` |
| N1, N2, N5 | `p_s5b.py held_final held_check env_red` |
| N3 | `p_ownerenv.py` |
| N6, N7 | `p_s5.py walks_verdict snapshot_fail_accept` |

Trọng tâm nên soi: đọc log theo từng hướng dẫn in ra, không chỉ mã thoát, vì Sol6 đã hai lần có test xanh mà hướng dẫn chưa đúng. `command.leaves_no_objects` là thay đổi rộng nhất ở lớp git, chỉ có hiệu lực trong lệnh xem.
