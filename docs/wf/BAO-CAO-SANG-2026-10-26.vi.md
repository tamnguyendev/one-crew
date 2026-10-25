# Báo cáo sáng 26/10/2026 — OneCrew workflow chung, bản test lượt 8

**Trạng thái một dòng:** **Bản test cài được ĐÃ SẴN và ĐÃ KIỂM từ artifact** (`D:\OneCrewRuns\wf-handover-4b1b7b1`, 2.2.0.dev8, commit `4b1b7b1`, wheel `c3692aa…`): gate 268/268 check đạt, bundle 10/11 (RP chờ W45 mới), verify 26/26 + legacy 15/15 trong venv sạch. Bài thử SDK: hai plan workflow đã được OneCrew (bản dev8) tiếp nhận trên sổ thật ở trạng thái **proposed, chờ anh duyệt** — AI không được duyệt; sau khi anh gõ lệnh approve (mục 6) engine chạy. Chưa Codex review bản cuối, chưa nghiệm thu, chưa giao.

## 1. Bản bàn giao

| Mục | Giá trị |
|---|---|
| Commit snapshot | `4b1b7b1` (nhánh `codex/wf-development`, worktree `D:\TamNT\Workspace\11.OneCrew\wf-codex`) |
| Phiên bản | 2.2.0.dev8 |
| Gói | `D:\OneCrewRuns\wf-handover-4b1b7b1` (642 file, `manifest.json` kind development-handover-package, `SHA256SUMS`, verifier trong `verify/`) |
| Wheel sha256 | `c3692aa11d71d6e81b5ad2aaf6f57ddcb22679fc5ae0beba5b12d09c940e2929` (`wheel/onecrew-2.2.0.dev8-py3-none-any.whl`; wheel bản trước ghim `wheel/previous/onecrew-2.2.0.dev3-py3-none-any.whl`, baseline d3120c6) |
| Gate snapshot | `refused` theo thiết kế vì acceptance 14 partial / 10 blocked; **kiểm hiện thực 268/268 biên nhận, 0 đỏ, 0 skip**, 2 143 lượt test, 1 756 test id, snapshot nguyên vẹn (`gate/decision.json`; chạy 00:50–03:25 26/10) |
| Bundle T54 (11 release) | **10/11 pass** T54.1–T54.5 + INPUTS(bootstrap) (R01–R08, RX1, RX2); **RP refused T54.5 "comparison missing"**: ma trận W45 là của wheel 6366137, chưa chạy lại trên wheel này (provider trả phí, ngoài quyền) → ô provider ghi "cần kiểm lại". R05/R07 chạy lại một lần vì task OneCrew khác ghi vào sổ thật trong lần 1 (mục 5). `bundles/<R>/release-check.json` |
| Kiểm gói từ artifact | **PASS** — `verify/verify_package.py` 26/26 bước (venv sạch cài wheel từ gói, hash khớp SHA256SUMS, root code propose → approve → `verdict run` M1 qua console script của venv, mọi module `onecrew.*` nạp từ venv, rollback bị từ chối đúng trên bản sao có blocker — 0 lệnh pip, bản cài không đổi; roll-forward giữ dữ liệu; bản cũ đọc root cũ, không đọc root `plan-ns:`), `verify/legacy_continuation.py` 15/15 (root schema 2 cũ chạy theo semantics cũ trên wheel mới, baseline ghi một lần, commit không có bị từ chối); cả hai exit 0, chạy bằng `python -I` từ `D:\OneCrewRuns\wf v` (không PYTHONPATH, đường dẫn có dấu cách), `verifier-origin.json` xác nhận module nạp từ `verify/` của gói. Test thật `tests.test_wf_package_check_real` + `test_wf_legacy_continuation_real` với WF_PACKAGE: 2 OK. Báo cáo: `D:\OneCrewRuns\wf-handover-4b1b7b1erification\` |

Bản này là **bản test development**: chưa Codex review, chưa nghiệm thu, chưa giao. Mọi số liệu lấy từ biên nhận trong gói.

## 2. Cài và thử (chỉ dùng file trong gói, sổ tạm)

Kiểm hash rồi cài vào venv sạch ngoài checkout (đường dẫn có dấu cách được hỗ trợ):

```bash
cd D:/OneCrewRuns/wf-handover-4b1b7b1
sha256sum wheel/onecrew-2.2.0.dev8-py3-none-any.whl
python -m venv "D:/OneCrewRuns/venv wf 4b1b7b1"
"D:/OneCrewRuns/venv wf 4b1b7b1/Scripts/python" -m pip install --no-index --no-build-isolation "wheel/onecrew-2.2.0.dev8-py3-none-any.whl"
"D:/OneCrewRuns/venv wf 4b1b7b1/Scripts/onecrew" --help
```

Kịch bản thử ngắn trên sổ TẠM (không chạm `state-v2-real`): verifier của gói tự tạo venv, cài wheel, chạy một root code (propose → approve → `verdict run` → `plan present`) trên project git tạm + sổ tạm, kiểm mọi module nạp từ venv, rồi diễn tập rollback/roll-forward trên BẢN SAO sổ; chạy từ thư mục trống bất kỳ, không PYTHONPATH:

```bash
cd "D:/OneCrewRuns/wf v"
python -I verify_package.py D:/OneCrewRuns/wf-handover-4b1b7b1 "D:/OneCrewRuns/wf v/thu-cua-anh"
```

(thay `verify_package.py` bằng `D:/OneCrewRuns/wf-handover-4b1b7b1/verify/verify_package.py`; thư mục làm việc phải MỚI). Tiếp tục root cũ trên bản sao sổ: `python -I D:/OneCrewRuns/wf-handover-4b1b7b1/verify/legacy_continuation.py D:/OneCrewRuns/wf-handover-4b1b7b1 "D:/OneCrewRuns/wf v/lc-cua-anh"`. Kết quả của đêm nay cho hai lệnh này: mục 1 (dòng Kiểm gói từ artifact) và `D:\OneCrewRuns\wf vb1b7b1\`.

## 3. Finding đã khép đêm nay (lượt 7 + 8)

| Finding | Sửa | Phản chứng đỏ trước → xanh |
|---|---|---|
| P1 cổng giao nhận bundle sai (`decision=pass`, `T54.1=False`; xóa conditions vẫn pass) | một luật `release_check.judge_verdict` dùng chung cho writer và cổng; identity luôn kiểm; tên mọi check đỏ trong lý do | 61 ca `'pass' != 'refused'` → xanh |
| Test p90 báo lỗi giả (tên thư mục `tmp90_…`) | kiểm khối ước lượng + trang đã che định danh; tuyên bố thật vẫn bị bắt | log gate 734acdc → xanh, định danh chứa p90 đạt |
| P2 số liệu ghép tầng 1 (J3: 1/9) | một tập job cho tử/mẫu/computed_from; checker tính lại từ ô theo-job | `(1, 9, 0.111) != (0, 9, 0.0)` → xanh |
| T35c E29 liên kết SKIP → finding không có bản ghi | `findings.link_skip` (decision.recorded, một transaction), `skip_view`, hàm đo trả 2 ID | `no attribute link_skip` → xanh |
| Quyền Q5/Q8/Q10 (Codex 23:44) | Q5 không giao → U3 + hold + card, không repair; Q8 giữ an toàn + U3; Q10 bằng chứng proposal-only | `LedgerError not raised` → xanh |
| T40c E30 quyết định hợp đồng trước/sau | bundle RP ghi 6 ô + nguồn pin + hash trước/sau; T54.5 so | `'pass' != 'refused'` ×5 → xanh |
| Race engine hai thân executor một attempt (gate 73be6ee) | `step` không dispatch attempt mình không admit | `['A','B'] != ['A']` → xanh |
| DUPk không đọc được bằng mã mới | anchor cũ đọc file của đúng project | `revision 1 does not match the recorded hash` → xanh |
| Card hold thiếu evidence/hạn; thiếu HD-05 Q5/Q8/Q10; ô RP thiếu lý do; hash hook không theo pha | nhánh D | từng ca đỏ → xanh |
| T49d E5/E16 | `rollback_cli` mã thoát + báo cáo rollback + check | — (mới) |

Chi tiết file:line, test, chữ đỏ: `docs/wf/TAKEOVER-CLAUDE-2026-10-24.md` §11–§13 và `docs/wf/r7-*-notes.md`, `docs/wf/r8-*-notes.md`.

## 4. 92 task

Bảng 92 task trên commit `4b1b7b1` (`docs/wf/audit/AUDIT-92.md`, một nguồn: registry + overrides): **Done 62 · Partial 26 · Blocked 4**.

| Nhóm | Done | Partial | Blocked | Còn lại vì |
|---|---|---|---|---|
| Feature (60) | 59 | 1 | 0 | W06: T37 E3/E6 chờ quyết định O4 (ngoài) |
| Bộ kiểm WK (17) | 3 | 14 | 0 | mỗi WK liệt kê T54x trong DoD → chờ bundle trên artifact (release-evidence); WK01 thêm T33b (verb nghiệm thu thật), WK04a T37 (O4), WK05a T28 E1 (bằng chứng chạy tay), WKP T40b (W45) |
| Phát hành W40-Rnn (11) | 0 | 11 | 0 | cổng CG-Rnn cần acceptance complete + bản ghi review độc lập (Codex) — ngoài |
| Provider thật (1) | 0 | 0 | 1 | W45: codex CLI chưa cài, pin từ program kit vì hợp đồng chưa duyệt |
| Pilot/nghiệm thu (3) | 0 | 0 | 3 | W38b/c/d: pilot thật, nghiệm thu U3/U4 |

Phân loại nguyên nhân còn lại: **A thiếu code: 0 · B chưa nối đường dùng: 0 · C thiếu test/bằng chứng local: 0** (T28 E1 có bằng chứng chạy tay, chưa thể là check gate) · **D trạng thái cũ: 0** (6 dòng WK ghi chú cũ đã cập nhật lượt 7) · **E điều kiện ngoài: toàn bộ 30 dòng còn lại** (bundle trên artifact → sẽ có sau bước bundle của bản này; review độc lập; O4; W45; pilot; verb nghiệm thu).
Partial: WK01, W40-R01, WK02, W40-R02, WK03, W40-R03, WK04a, WK04b, W06, W40-R04, WK05a, WK05b, W40-R05, WK06, W40-R06, WK07, W40-R07, WK08, W40-R08, WKP, W40-RP, WKX1, W40-RX1, WKX2, W40-RX2, WKPL. Blocked: W45, W38b, W38c, W38d.

Phân biệt: task Done ≠ acceptance complete ≠ gate pass ≠ package verified ≠ pilot/owner acceptance. Registry acceptance: 74 complete / 14 partial / 10 blocked (trước đêm: 55/33/10). 14 partial = 11 T54a–k (đo bằng bundle trên artifact, ngoài gate), T33b (verb nghiệm thu thật), T37 (O4), T28 (E1 bằng chứng chạy tay 114/114 trước–sau tách). 10 blocked = T40b (W45 ngoài) + 9 case PL (pilot thật).

## 4b. Bài thử SDK (OneCrew dev8, sổ thật `state-v2-real`)

| Mục | Giá trị |
|---|---|
| Runtime | venv `D:\OneCrewRuns\sdk-trialenv dev8` cài từ wheel `c3692aa…` (cùng bytes gói); chỉ nhóm v2 (`plan/engine/...`) — nhóm `job` v1 không có trong bản cài (`owned` không trong wheel) nên hợp đồng v1 `job --mode work` không dùng được từ artifact; dùng workflow chung v2 |
| Plan 1 | `sdk-trial-vn-sign-sdk-20261026` — TASK-c7ebc86471a2438caa4590b8cbf0d9f5, bản 1 sha `ea675cb6…`, **proposed** (lint clean, `--workflow`); project clone sạch `D:\OneCrewRuns\sdk-trialn-sign-sdk` @ bef6476 |
| Plan 2 | `sdk-trial-vn-sign-sample-20261026` — TASK-2197a8c7fd194096bf9b541f57337cce, bản 1 sha `b1b8bb8b…`, **proposed**; clone sạch `…n-sign-sample` @ 9344983 |
| Provider/model | worker `claude` (preference mặc định codex/gpt-6-luna nhưng codex CLI chưa cài — không cài thêm), reviewer M2 `claude-opus-5-5`, M1 verifier lệnh (kiểm hai báo cáo có đủ mục và mọi file:dòng tồn tại) |
| Repo cập nhật được | không repo local nào: signsdk dirty + 10 stash + phân kỳ 105/165; vn-sign-sample conflict UU/UD; vn-sign-sdk remote force-push → dùng checkout riêng (clone) cho cả hai remote; local giữ nguyên |
| hms_signature_sign | khảo sát đầu mối: không có trong file tracked/lịch sử; biến thể chỉ trong snapshot IDE không tracked — plan yêu cầu OneCrew tìm biến thể và báo phạm vi, không suy đoán |
| Trạng thái thật | **chưa chạy**: chờ verb approve của anh (mục 6); runner engine không tự tiếp tục sau khi chat kết thúc (cần `engine step` hoặc OneCrew host) |
| Checkpoint | plan JSON: `D:\OneCrewRuns\sdk-trial\plan-*.json`; hợp đồng v1 dự phòng (validate OK, không submit được từ artifact): `contract-*.json`; khảo sát: `<clone>/docs/onecrew-review/SURVEY-DAU-MOI.md` |

## 5. Giới hạn thực tế và điều kiện ngoài

- W45: ma trận provider là của wheel 6366137 (4/6 dùng được, codex thiếu CLI); chưa chạy lại trên wheel mới vì là provider trả phí ngoài quyền → trạng thái "cần kiểm lại" trong bundle RP.
- Pilot thật PL-A/PL-B, T14c, nghiệm thu U3/U4: chưa có; công cụ local (generator, checker, liên kết SKIP) đã kiểm trên fixture synthetic.
- Gate `ae8a67f` bị dừng 23:47 (interrupted/partial, 137/266) — chỉ là bằng chứng regression của snapshot đó.
- Windows MAX_PATH: dùng thư mục làm việc ngắn khi kiểm gói.
- Bundle lần 1 trên 4b1b7b1: R05 và R07 refused `INPUTS(bootstrap): live state or monitor changed` vì một task OneCrew KHÁC (`ux-review-3`, TASK-4dfecc…, cwd `D:\OneCrewRuns\cts-portpplutter_vimes`, phiên khác) ghi verdict vào sổ thật lúc 03:38–03:44 trong lúc hai bundle đo "sổ thật không đổi" — không phải lỗi sản phẩm; chạy lại đúng hai bundle đó trên cùng wheel gate (kết quả ở mục 1). Sổ thật không bị bản này chạm.

## 6. Quyết định thực sự cần anh

1. **Duyệt hai plan bài thử SDK** (verb owner, chạy từ terminal của anh, không phải trong phiên AI). Mỗi plan: bản 1, sha ghi trong `plan present`. Lệnh (PowerShell/cmd, một dòng mỗi lệnh):

```bash
"D:\OneCrewRuns\sdk-trialenv dev8\Scripts\onecrew.exe" --project D:\OneCrewRuns\sdk-trialn-sign-sdk --state-root D:\TamNT\Workspace	.OneCrew\state-v2-real plan approve sdk-trial-vn-sign-sdk-20261026 --revision 1 --by owner --reference "chat Claude Code 26/10: duyệt bài thử SDK"
```

```bash
"D:\OneCrewRuns\sdk-trialenv dev8\Scripts\onecrew.exe" --project D:\OneCrewRuns\sdk-trialn-sign-sample --state-root D:\TamNT\Workspace	.OneCrew\state-v2-real plan approve sdk-trial-vn-sign-sample-20261026 --revision 1 --by owner --reference "chat Claude Code 26/10: duyệt bài thử SDK"
```

   Sau đó bảo tôi (hoặc anh gõ) `… engine step sdk-trial-vn-sign-sdk-20261026` lặp tới khi mốc đạt; worker provider `claude` (codex CLI không có trên máy), reviewer `claude-opus-5-5`. Nếu anh muốn đổi nguồn (review bản local dirty thay vì clone sạch) thì không duyệt và nói rõ.
2. **O4 (T37)**: bước 3 chỉ chạy khi anh trả lời 'có' — chưa trả lời, W06/T37 giữ partial.
3. **W45**: cài codex CLI + chạy lại hai ô codex và cả ma trận trên wheel dev8 (provider trả phí) — hay chấp nhận "cần kiểm lại" cho bản test này.
4. **Q5/Q8/Q10 trên root không ủy quyền**: đã sửa theo luật authority (U3 + hold + card, không repair); Codex đã chạy 23 test đạt. Không cần quyết định thêm, chỉ cần anh biết hành vi mới.
5. **Lỗi mới ghi nhận, chưa sửa**: console script `onecrew` trên Windows cp1252 crash khi in tiếng Việt (`plan lint` UnicodeEncodeError) — cần `PYTHONUTF8=1` hoặc sửa entry point ép UTF-8 (lượt sau; không ảnh hưởng gate vì gate chạy `-X utf8`).

## 7. Không ghi

Codex đã review, anh đã nghiệm thu, release đã giao, W45 6/6 trên wheel mới, pilot thật: chưa xảy ra.
