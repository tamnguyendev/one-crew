# Lượt 10 — agent C: console UTF-8, lệnh PowerShell, README/ma trận, AUDIT-92

## 1. Console cp1252

- Tái hiện (wheel dev9 cài sẵn `D:\OneCrewRuns\sdk-trial\venv dev9`, không PYTHONUTF8, `PYTHONIOENCODING=cp1252`, `ONECREW_LANG=vi`): `onecrew.exe --help` thoát 1:
  `File "...\onecrew\v2\cli.py", line 106, in main` (`print(... help_lines() ...)`) rồi
  `UnicodeEncodeError: 'charmap' codec can't encode character '\u1ed9' in position 1632: character maps to <undefined>`.
  (Một số verb như `plan present` đã tự cấu hình lại luồng nên không lỗi; lỗi lộ ở `--help` tiếng Việt và các verb in bằng `print` thường.)
- Sửa: `onecrew/console.py` (`force_utf8` + `main`): `reconfigure(encoding='utf-8', errors='replace')` cho `sys.stdout`/`sys.stderr` một lần ở đầu console script rồi gọi `onecrew.v2.cli.main`; `pyproject.toml`: `onecrew = "onecrew.console:main"` và module `onecrew.console` trong `py-modules`; `onecrew/__main__.py` (checkout) gọi `force_utf8` trước `onecrew.cli.main`; `tests/test_g1_core.py` đổi dòng ghim entry script. Không đổi mã hóa file nào; dưới `PYTHONUTF8=1` đầu ra giống từng byte (có test).
- Đỏ trước: `tests.test_wf_r10_console_utf8` — `Ran 6 tests ... FAILED (failures=3, errors=1)` (chưa có `onecrew.console`; `python -m onecrew --help` crash). Xanh sau: `Ran 6 tests ... OK`.
- Registry: `check.r10_console_utf8` (R02, `installed: false`).
- Kiểm trên wheel thật: dựng wheel từ bản sao worktree vào `D:\OneCrewRuns\r10c-tmp\wheel`, cài vào venv MỚI `D:\OneCrewRuns\r10c-tmp\venv` (không đụng `venv dev9`): `--help` với cp1252 + vi thoát 0 (dev9: thoát 1); `plan show/present/report` trên BẢN SAO sổ `state-sdk-trial` thoát 0.
- Ngoài phạm vi C: `tests.test_g1_core` còn 2 test đỏ không do thay đổi này — `test_every_v2_module_is_shipped` (`onecrew.v2.verifiers.output_refs` do agent khác thêm, chưa vào `py-modules`) và `test_the_model_id_is_written_in_one_module_only` (`docs/wf/TAKEOVER-CLAUDE-2026-10-24.md` còn id model; BAO-CAO đã bỏ id ở lượt này, TAKEOVER là tài liệu lịch sử, không thuộc phạm vi C).

## 2. Lệnh PowerShell (Windows PowerShell 5.1, `powershell -NoProfile -File`)

Quét byte điều khiển trong `docs/wf/**` và `README.md`: còn đúng 2 ký tự TAB trong đường dẫn `...\wf-dev-logs\t28-e1-before-split` (TAKEOVER, AUDIT-92.md) và 2 escape `\t` trong JSON (audit-92.json, overrides.json) làm thư mục thành `wf-dev-logs<TAB>28-e1...`; đã sửa thành chữ `\t28-e1-before-split`. Không có `\v` hay byte < 0x20 khác. Quét lại: sạch.

Các khối lệnh trong BAO-CAO mục 2 và mục 6 từng là bash (đường dẫn `D:/...`, `sha256sum`, chuỗi trong ngoặc kép đứng đầu dòng — PowerShell hiểu là biểu thức nên không chạy). Đã viết lại thành khối powershell: `$py` đường dẫn đầy đủ (không dùng `python` trần), `& "..."` cho mọi đường dẫn có dấu cách, `Get-FileHash`, `Set-Location`, `$env:PYTHONUTF8 = "1"` cho wheel dev8/dev9. README có thêm mục dựng wheel và thử (PowerShell).

| # | Lệnh (rút gọn) | Mã thoát | Ghi chú |
|---|---|---|---|
| A1 | `Get-FileHash -Algorithm SHA256 $pkg\wheel\onecrew-2.2.0.dev8-py3-none-any.whl` | 0 | `C3692AA11D71D6E8...` khớp báo cáo |
| A2 | `& $py -m venv "...\r10c-tmp\venv wf 4b1b7b1"` (đường dẫn có dấu cách, venv tạm thay `D:\OneCrewRuns\venv wf 4b1b7b1`) | 0 | |
| A3 | `& "$venv\Scripts\python.exe" -m pip install --no-index --no-build-isolation $whl` | 0 | |
| A4 | `& "$venv\Scripts\onecrew.exe" --help` (`PYTHONUTF8=1`) | 0 | |
| A5 | `& $py -I "$pkg\verify\verify_package.py"` (không tham số = usage) | 2 | usage, đúng thiết kế |
| A6 | `& $py -I "$pkg\verify\legacy_continuation.py"` (không tham số) | 2 | usage, đúng thiết kế |
| A7 | `& $py -I "$pkg\verify\verify_package.py" --self-check-only` | 0 | `self-check-ok` |
| A8 | `& $py -I "$pkg\verify\legacy_continuation.py" --self-check-only` | 0 | `self-check-ok` |
| B1 | wheel mới: `onecrew.exe --help` (cp1252, `ONECREW_LANG=vi`, không PYTHONUTF8) | 0 | dev9: 1 |
| B2 | `onecrew.exe --project ...\vn-sign-sdk --state-root ...\state-sdk-trial plan show sdk-trial-vn-sign-sdk-20261026-engine` | 0 | sổ BẢN SAO |
| B3 | `... plan present <plan>` | 0 | |
| B4 | `... plan report <plan>` | 0 | |
| B5 | `... plan lint --file examples\v2-plan-l1.json` | 1 | lint đỏ có chủ ý (fixture), không crash |
| B6 | `... plan show --help` | 0 | |
| R1-R4 | README: `pip wheel . --no-deps -w $out`, `venv`, `pip install`, `onecrew --help` (chạy trong bản sao worktree) | 0, 0, 0, 0 | |
| - | `plan approve ... --state-root D:\TamNT\Workspace\11.OneCrew\state-v2-real` (BAO-CAO mục 6, hai lệnh) | không chạy | not executed (writes the live ledger) |
| - | `verify_package.py <pkg> <work dir mới>` và `legacy_continuation.py <pkg> <work dir mới>` đầy đủ (BAO-CAO mục 2) | không chạy | chạy dài, tạo venv và sổ tạm; chỉ kiểm cú pháp bằng usage và `--self-check-only` |

(Mã thoát -1 khi nối `| Select-Object -First n` là do PowerShell đóng pipe, không phải lỗi lệnh; bảng đo lại bằng `| Out-Null`.)

## 3. README / ma trận provider / so sánh W45

Sự thật (log `D:\OneCrewRuns\wf-dev-logs\w45-matrix-6366137.txt`, `w45-matrix.txt`, `D:\OneCrewRuns\wf-w45-matrix-6366137\matrix.md`): ma trận W45 đã chạy hai lần — trên wheel `ceb46c6` và trên wheel `6366137` (25/10 02:22Z) — cùng kết quả 4/6 (claude reviewer/advisor đạt, kiro reviewer/advisor đạt, codex 2 ô "chưa kiểm chứng" vì CLI không có). Chưa có ma trận hay so sánh cho wheel dev8 (`4b1b7b1`) hoặc dev9 (`da96db8`); bundle RP ở `4b1b7b1` bị từ chối T54.5 "comparison missing". Không chạy provider mới, không bịa so sánh.

Sửa:
- `docs/wf/release-notes/` (11 file release): dòng Limits "Dạng lệnh thật của codex/kiro CHƯA KIỂM CHỨNG" sai với claude/kiro đã chạy thật → nêu đúng wheel `6366137`, 4/6, không phải wheel của bản dựng này, codex chưa kiểm chứng; dòng RP "Sáu ô ... chỉ có bằng CLI giả" → 4/6 chạy CLI thật trên `6366137`, chưa có so sánh với wheel hiện hành, T54.5 "comparison missing". `tools/gen_release_notes.py` sửa cùng hai câu. Không chạy lại generator: tham số vòng 8 (gate, bundle index trong %TEMP%) không được ghi lại ở đâu, chạy lại sẽ đổi commit/gate/bundle; thay đúng hai chuỗi trong 11 file đầu ra, tương đương một lần sinh lại với cùng đầu vào.
- `README.md`: thêm mục "Bản test workflow chung (2.2.0.dev9)" — trạng thái development, lệnh PowerShell dựng/cài wheel, ghi chú UTF-8, phạm vi chính xác của ma trận W45.
- BAO-CAO mục 5 (bullet W45): ghi rõ ma trận thuộc `6366137` (và trước đó `ceb46c6`), không có cho dev8/dev9. Mục 6 điểm 5 (lỗi cp1252): từ "chưa sửa" thành "đã sửa trong mã nguồn, chưa nằm trong wheel dev8/dev9 đã cài". Bỏ id model review khỏi báo cáo (test g1 cấm id model ngoài `claude_cli.py`).
- `wfkit/provider_evidence.py`: không sửa (không có sai lệch ma trận/README trong mã).

## 4. AUDIT-92

Đường sinh: `overrides.json` -> `tools/audit_merge.py 4b1b7b1 D:/OneCrewRuns/wf-handover-4b1b7b1/gate D:/OneCrewRuns/wf-handover-4b1b7b1` -> `AUDIT-92.md` + `audit-92.json`. Chạy lại audit_merge trên đầu vào cũ cho kết quả byte-giống bản đã commit (kiểm trước khi sửa). Số liệu không đổi: 92 ID, Done 62, Partial 26, Blocked 4; không đổi trạng thái nào, không nâng Partial lên Done.

| Dòng | Thay đổi | Lý do |
|---|---|---|
| W32a (Done) | `missing` "E17 'ETA trễ' chưa có test riêng" -> none + tham chiếu `tests.test_wf_exceptions...test_approved_upper_bound_same_cause_dedup_and_six_hours_quiet`; loại D | registry T36b E17 đã trích đúng test đó (tồn tại trong tests/); Done không thể kèm "thiếu test" |
| W33b (Done) | "race 'held' một lần, cần xem thêm" -> none + `tests.test_wf_w33b_evidence` (`test_t15c_e8_an_attempt_admitted_by_another_caller_is_never_dispatched_again`); loại D | race đã sửa lượt 6b (DEV-LOG 25/10; BAO-CAO mục 3) |
| W07, W08, W09, W18 (Done) | `missing` "Registry Txx: partial -> complete" -> none + "registry Txx complete" (đã kiểm: T06, T22, T31, T17b = complete); loại D | việc cần làm đã xong |
| W17 (Done) | `missing` "Registry T28: partial -> complete" -> làm rõ: DoD W17 xong; T28 acceptance partial-by-construction (E1 chạy tay 114/114, không là check gate); loại D | registry T28 vẫn partial; mâu thuẫn với WK05a |
| WK01...WKX2 (13 dòng Partial) | `evidence` viết lại từ registry hiện tại và `release-check.json` thật trong gói; `missing`/`next` thêm kết quả bundle; sửa các câu "Chạy bundle trên artifact cuối" (đã chạy), "E5/E16 chưa làm lượt 7" (WK04b, đã làm), "Ghi E1 vào registry" (WK05a, đã ghi) | ghi chú cũ mâu thuẫn với `missing` cùng dòng và với gói đã kiểm |
| W40-R01...RX2 (11 dòng Partial) | `evidence` từ `release-check.json` thật (10 pass, RP refused T54.5), bỏ câu "INPUTS false" của 6366137 | INPUTS(bootstrap) đạt từ 4b1b7b1 |
| Loại nguyên nhân | dòng chỉ thiếu review/nghiệm thu/giao: C -> E (25 dòng); C giữ ở WK04a, WK05a, WKP, W40-RP, WKPL | BAO-CAO nói "E: toàn bộ 30, C: 0" còn JSON nói C; thống nhất C 5 dòng, E 30 |
| W40-RP, WKP | thêm: không có so sánh W45 cho wheel hiện hành (T54.5) | khớp release-notes và README |
| "ROUND6-PENDING" | không có trong md/json/overrides/fill (chỉ chuỗi `pending` thông thường trong tên test) | - |
| "toàn bộ local xong" | không tìm thấy trong AUDIT-92; BAO-CAO mô tả C/E đúng | - |

Phân loại phần thiếu của các dòng chưa Done (sau sửa): A 0, B 0, C 5, D 0, E 30. Mười tám dòng Done mang nhãn D là ghi chú đã sửa (7 dòng sửa lượt này).

Không làm: không sửa `wfkit/development-manifest.json` (các tệp tôi đổi sẽ báo lệch ghim cho tới khi chủ manifest đóng băng lại); không sửa `TAKEOVER-CLAUDE-2026-10-24.md` ngoài ký tự TAB trong đường dẫn.
