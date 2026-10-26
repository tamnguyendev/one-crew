# Báo cáo sáng 27/10/2026 — OneCrew workflow chung, khép phần local sau review Codex lượt 11

**Trạng thái một dòng:** **Có bản test cài được, ĐÃ KIỂM từ artifact**: gói `D:\OneCrewRuns\wf-handover-572fd18` (2.2.0.dev13, commit `572fd18`, wheel sha256 `b6c61aa4…d7a838`). Gate 275/275 check đạt (0 skip), tự kiểm tài liệu 0 vấn đề, bundle 10/11 (RP chờ W45), verify 26/26 + legacy 15/15 trong venv sạch chạy bằng bộ kiểm nằm trong gói, lệnh PowerShell cài thử 10/10 đúng kỳ vọng. Năm finding A–E của Codex đã sửa đỏ-trước/xanh-sau và **được xác nhận trên chính bản dựng cuối** (gate 572fd18 chạy 3 check R11 mới). Chưa Codex review bản cuối, chưa nghiệm thu, chưa giao; W45/pilot/acceptance là việc của anh và Codex.

Ủy quyền: chỉ thị lượt 11 anh dán 26/10 ~19:40 ("Tôi ủy quyền tự chia task, chọn cách sửa, chạy agent phù hợp, bổ sung test, xử lý lỗi, commit local và dựng/kiểm gói… Không hỏi tôi duyệt từng file, task, test hoặc commit."). Không push/tag/publish, không cài đè môi trường đang dùng, không ghi sổ thật, không đổi pin provider, không reset ngân sách, không tự ghi nghiệm thu.

## 1. Bản bàn giao

| Mục | Giá trị |
|---|---|
| Commit snapshot | `572fd18` (nhánh `codex/wf-development`, worktree `D:\TamNT\Workspace\11.OneCrew\wf-codex`); sửa R11 ở `1750c8d`, sửa test literal ở `572fd18` |
| Phiên bản | 2.2.0.dev13 |
| Gói | `D:\OneCrewRuns\wf-handover-572fd18` (647 file, `manifest.json` kind development-handover-package, `SHA256SUMS`, verifier 4 file trong `verify/`); gói cũ `wf-handover-73d6c77`, `-abb570a`, `-4b1b7b1` giữ nguyên |
| Wheel sha256 | `b6c61aa4f932ea1aaed8312ffe79a711d04bebd23ee581eeb4f8f3d2b4d7a838` (`wheel/onecrew-2.2.0.dev13-py3-none-any.whl`); wheel bản trước ghim `wheel/previous/onecrew-2.2.0.dev8-py3-none-any.whl` sha `c3692aa1…`, commit `4b1b7b1`, nguồn provenance = manifest.json của gói dev8 (không ghi tay) |
| Gate snapshot | `refused` theo thiết kế vì acceptance 14 partial / 10 blocked (pilot, provider thật, nghiệm thu); **kiểm hiện thực 275/275 biên nhận (272 cũ + 3 check R11), 0 đỏ, 0 skip, 2.265 lượt test, document-selfcheck pass (0 vấn đề), snapshot nguyên vẹn** — `gate/decision.json`, chạy 27/10 00:46–02:4x (giờ máy) |
| Bundle T54 (11 release) | **10/11 pass một lần** (R01–R08, RX1, RX2: T54.1–T54.5 + INPUTS(bootstrap), cùng wheel `b6c61aa4…`); **RP refused** "needs --matrix: six provider cells must be real receipts (W45)" — có trong gói tại `bundles/RP/bundle-result.json` và trong bảng README (không giấu) |
| Kiểm gói từ artifact | **verify_package PASS 26/26 bước**, **legacy_continuation PASS 15/15 bước** (đếm từ `steps` trong report JSON), chạy `python -I` từ `D:\OneCrewRuns\wf v\572fd18` bằng bản sao verifier trong gói, không PYTHONPATH, venv mới, sổ tạm; report: `D:\OneCrewRuns\wf v\572fd18\vp\verification\verify-report.json`, `…/lc/verification/legacy-continuation-report.json`; log `D:\OneCrewRuns\wf-dev-logs\vp-572fd18.txt`, `lc-572fd18.txt` |
| Kiểm chéo trong gói | 647/647 dòng SHA256SUMS khớp, không file thừa; wheel + wheel trước khớp sha; audit-92.json/AUDIT-92.md commit `572fd18`; gate decision/build.json commit + wheel khớp; 275/275 biên nhận cùng commit; 10/10 bundle cùng commit + wheel; verifier `source_commit` = 572fd18, 4 file khớp hash manifest; README trong gói ghi đúng 275/275, 62/26/4, 11 release / 10 bundle, RP refused |

## 2. Năm finding của Codex — trạng thái trên bản dựng cuối

| # | Finding | Sửa (file) | Đỏ trước → xanh sau | Trên gate 572fd18 |
|---|---|---|---|---|
| A | Guard output không chặn xoá/file rỗng | `common_verification.required_outputs/output_expectations/output_check`: write = quyền; đầu ra bắt buộc = đường dẫn nêu nguyên văn trong `output`; nội dung khai (kể cả "") phải khớp, `null` = phải vắng; ngoài quyền so với snapshot cha → fail | `tests.test_wf_r11_output_guard` 11 test: 10 đỏ → 11/11 (qua engine.step + artifact API thật) | R05/check.r11_output_guard_refs **pass** |
| B | `Dockerfile:999999` lọt M1 | `output_refs`: extension tùy chọn; token không chấm là tham chiếu khi là file trong cây / tên generic / neo cây / trùng basename (offender), còn lại `ignored` (đếm riêng) | `tests.test_wf_r11_output_refs` 12 đỏ → xanh; 55 artifact SDK kiểm lại: 31/55 không đổi, số tham chiếu từng node bằng baseline | cùng check trên, **pass** |
| C | D8 đếm node đã xong | `internal_plan._beyond_deadline(nodes, counted, remaining)` trên tập còn phải chạy; kiểm lúc quyết định và trong giao dịch publish, lệch → từ chối; không nới deadline | `tests.test_wf_r11_d8_deadline` 3 đỏ → 8/8; hồi quy d6/d7/d8/engine/root_budget xanh | R04/check.r11_d8_deadline **pass** |
| D | Gói lệch snapshot (audit abb570a, hardcode d3120c6, RP thiếu, trộn định danh, 60fdf15) | `build_package.check_one_build` (+`--audit`, `--previous-evidence`) từ chối audit/bundle/receipt/snapshot khác commit hoặc wheel; `previous_provenance` từ bằng chứng; `run_bundles.keep_result` ghi bundle-result.json; `package_check.identity_problems` trong judge; nhánh previous-wheel chọn theo METADATA + version khai | `tests.test_wf_r11_build_package`, `test_wf_package_check` (+PackageIdentityStepTests 8, PreviousWheelIsWhatItClaimsTests) đỏ → xanh; gói cũ 73d6c77 bị identity step từ chối (đúng thiết kế) | PL/check.r11_build_package **pass**; gói 572fd18 qua bước identity của chính nó |
| E | Anchor hỏng 00:469; K-OWNER báo nhầm ROADMAP:46/:345, HANDOFF:46 | Ngoài checkout (ngoại lệ một lần anh cho): `00-THIET-KE…:469` → anchor §2 mới; khối tự kiểm trong `06-TRUY-VET… §7`: bỏ mệnh đề phủ định hẹp, thêm `commit`, thu hẹp whitelist; +3 đối chứng, +5 phản chứng; pin `doc:wf-doc-check` đổi qua U1-20261027-DOCCHECK-OWNERNEG. ROADMAP/HANDOFF không đổi | PROBLEMS 4 → 0; 155/155 phản chứng, 18/18 đối chứng | **document-selfcheck pass** trên gate 1750c8d và 572fd18 |

Phát sinh trong đêm: gate dev12 `1750c8d` đỏ 1/275 — `test_build_package_no_longer_hard_codes_the_inputs_sentence` tìm chuỗi literal `inputs_sentence(bundles)` trong khi agent D đổi tên biến (hành vi đúng). Sửa test nhận cả hai tên (không nới), U1-20261027-R11-4-1, dev13, gate chạy lại → 275/275. Bài học cũ lặp lại: tiêu chí theo hành vi, không theo hình thức.

## 3. 92 task (bảng trong gói, cùng snapshot)
`audit_merge.py 572fd18 <gate 572fd18> D:\OneCrewRuns\wf-handover-572fd18` → **Done 62 · Partial 26 · Blocked 4**, 0 trạng thái đổi so với 73d6c77 (R11 sửa lỗi trong task đã Done, không đổi DoD). Phân loại 30 dòng chưa Done theo nguyên nhân: **thiếu code: 0**; **chỉ thiếu bằng chứng ngoài (E): 25** (21 Partial + 4 Blocked — pilot, provider thật, nghiệm thu, giao thật); **thiếu test/bằng chứng + ngoài (C+E): 5** (WK04a, WK05a, WKP, W40-RP, WKPL). Bảng: `docs/AUDIT-92.md` trong gói (commit kiểm `572fd18`).

## 4. Bài thử SDK (sổ riêng, không gọi model)
Kiểm lại 55 artifact bằng máy kiểm R11: **sdk 16/34, sample 15/21 = 31/55, không đổi**. Không đạt vì: 21 cụm tên file cụt, 3 cụm đường dẫn cắt giữa cây, 1 vượt EOF, 1 "316-ish". Mức đạt: output 55/55 · tham chiếu 31/55 · tích hợp KZ 0/2 · M2 0/55 · 7 file lớn (18 slice) chưa review. **Chặn:** hai root đã quá hạn, không có verb gia hạn hợp lệ (guard D9); theo chỉ thị không tạo root mới, không sửa SQL/approval. Chi tiết `docs/wf/SDK-TRIAL-2026-10-26.vi.md` §8, `D:\OneCrewRuns\sdk-trial\reverify-r11`.

## 5. W45 / pilot / nghiệm thu
W45 không chạy trên wheel mới: quyền trong phiên gắn với wheel 6366137 (25/10), ô claude tốn tiền → RP giữ Partial/Blocked, bundle RP refused đúng. Pilot và nghiệm thu không tự ghi.

## 6. Lệnh PowerShell đã chạy thật (venv riêng `D:\OneCrewRuns\ps-check 572fd18`, không chạm sổ thật)

| # | Lệnh | Mã thoát |
|---|---|---|
| A1 | `Get-FileHash -Algorithm SHA256 $whl` → `B6C61AA4F932EA1A…`, có trong SHA256SUMS | 0 |
| A2 | `& $py -m venv "…\venv wf 572fd18"` (đường dẫn có dấu cách) | 0 |
| A3 | `& "$venv\Scripts\python.exe" -m pip install --no-index --no-build-isolation $whl` | 0 |
| A4 | `& "$venv\Scripts\onecrew.exe" --help` (ONECREW_LANG=vi, KHÔNG đặt PYTHONUTF8) | 0 |
| A5/A6 | `verify_package.py` / `legacy_continuation.py` không tham số → usage | 2 (đúng thiết kế) |
| A7/A8 | `… --self-check-only` → self-check-ok | 0 / 0 |
| B1 | `onecrew.exe --project … --state-root <tạm> plan --help` | 0 |
| B2 | `python -c "import onecrew; version"` từ venv → 2.2.0.dev13 | 0 |

Khối để anh dán (PowerShell 5.1; dùng đường dẫn Python đầy đủ vì `python` trần có thể là stub Store):

```powershell
$py   = "C:\Users\NUC\AppData\Local\Programs\Python\Python313\python.exe"
$pkg  = "D:\OneCrewRuns\wf-handover-572fd18"
$venv = "D:\OneCrewRuns\venv wf 572fd18"
$whl  = "$pkg\wheel\onecrew-2.2.0.dev13-py3-none-any.whl"
Get-FileHash -Algorithm SHA256 $whl
& $py -m venv $venv
& "$venv\Scripts\python.exe" -m pip install --no-index --no-build-isolation $whl
& "$venv\Scripts\onecrew.exe" --help
```

Kiểm gói đầy đủ (dài, tạo venv + sổ tạm; thư mục làm việc phải MỚI):

```powershell
$py  = "C:\Users\NUC\AppData\Local\Programs\Python\Python313\python.exe"
$pkg = "D:\OneCrewRuns\wf-handover-572fd18"
Set-Location "D:\OneCrewRuns\wf v"
& $py -I "$pkg\verify\verify_package.py" $pkg "D:\OneCrewRuns\wf v\thu-cua-anh-572fd18"
& $py -I "$pkg\verify\legacy_continuation.py" $pkg "D:\OneCrewRuns\wf v\lc-cua-anh-572fd18"
```

## 7. Quyết định cần anh
1. **Gia hạn hai root bài thử SDK**: duyệt thiết kế verb owner-only `plan extend-budget <root> --max-calls --deadline --reason` (ghi budget.group mới, giữ used/reserved, không reset) — hay bỏ hai root, tạo root mới sau khi anh duyệt hợp đồng mới. Không có việc này thì 24 cụm + KZ + M2 + 7 file lớn không chạy tiếp được.
2. **W45 trên wheel dev13** (ô claude trả phí ~0,18 USD; codex CLI vẫn không có → tối đa 4/6): cho chạy hay giữ RP Partial.
3. **Codex review** bản 572fd18 (R11 + 60fdf15 đã kiểm lại) và hai tài liệu Codex quản lý tôi đã sửa tối thiểu theo ngoại lệ anh cho (00:469, khối tự kiểm 06 §7; ROADMAP/HANDOFF không đổi).
4. **Nghiệm thu / giao**: không tự ghi; gói là bản development.

Ghi chú trung thực: legacy_continuation có **15** bước (không phải 16); gate `refused` là do acceptance ngoài (pilot/provider/nghiệm thu), không phải lỗi mã; W45, pilot, nghiệm thu chưa có bằng chứng thật trên wheel này.
