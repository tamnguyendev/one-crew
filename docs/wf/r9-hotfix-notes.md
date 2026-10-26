# Round 9 — hotfix D1–D4 từ bài thử SDK 26/10

Ủy quyền: chủ sở hữu, chat Claude Code 26/10/2026 ~09:50: "Làm hợp đồng hotfix OneCrew cho D1–D4 trên wf-codex, qua gate, rồi chạy lại bài thử SDK trên wheel mới."
Nguồn lỗi: `docs/wf/SDK-TRIAL-2026-10-26.vi.md` §3, bằng chứng `D:\OneCrewRuns\sdk-trial\evidence\`.

## Phạm vi
- D1–D3 (`onecrew/common_verification.py`, có thể `onecrew/v2/verifiers/command.py`): so cây ứng viên không dùng `git add -A` của repo mới;
  dựng index từ cây niêm phong rồi làm mới nội dung với `core.filemode=false`, không áp ignore (kể cả global), giữ entry gitlink.
  File sửa thật vẫn phải làm cây khác (phản chứng).
- D4 (`onecrew/common_executor.py` / `onecrew/artifact_core.py`): lượt resume sau `continuation` trả `files: []` không có continuation = ứng viên
  một phần đã đủ → produced với file của resume artifact; lượt không resume trả rỗng vẫn bị từ chối.
- Test mới đăng ký: `tests/test_wf_r9_candidate_tree_fidelity.py`, `tests/test_wf_r9_resume_empty_files.py` (check `check.r9_candidate_fidelity_resume`).
- Không đổi hợp đồng, acceptance hay registry khác; không chạm sổ thật.

## Quy trình
1. Sonnet implement red-first (agent), Fable review diff + chạy test nhắm đích.
2. U1 record cho từng file sửa (`wfkit/u1/U1-20261026-R9-*`).
3. Snapshot 2.2.0.dev9, gate đầy đủ nền (không sửa code khi gate chạy), package + verify từ artifact.
4. Chạy lại bài thử SDK trên wheel dev9 (venv mới), cùng hai root đã duyệt rev 4.

## Kết quả
(điền khi có kết quả thật)

## Phát hiện thêm khi chạy lại trên dev9 (10:38–10:50)
- D1–D4 đã hết: `engine verify` chạy được trên cả hai repo (biên nhận node-verifier-receipt), lệnh M1 thực thi trong checkout.
- M1 fail đúng thiết kế: worker ghi `publish.yml:32` (tên file cụt) → "file:dong khong ton tai". Sửa chỉ dẫn node (đường dẫn đầy đủ y như khoá trong source).
- **D6 (mới, runtime):** sau khi verify fail mở finding RF1, một `engine revise` làm đổi thế hệ node đã xoá `verification_receipt` → `engine repair` từ chối ("Repair requires the latest node verification receipt"), `findings resolve` cần biên nhận pass mới hơn nhưng mọi node bị RF1 chặn → kẹt. Lối ra dùng được: đổi dấu câu/hoa thường trong spec check của node (wording-only, không phải U1) để register đánh dấu finding stale. Cần sửa: repair/resolve phải chấp nhận biên nhận fail cuối cùng của thế hệ trước, hoặc revise sau fail phải tự chuyển finding sang stale/superseded.
- Deadline root không nới theo revision 4 (budget.group giữ `source_approval` rev 1): sdk đến 12:55, sample đến 11:55; estimate phải ép xuống [30,200]/[30,150].
