# CHANGELOG

## v2.2.0.dev3 (v22-trust-fixes: sửa các lỗi Codex tìm ở 8383446, không thêm tính năng)

- **Hook di động** (P0.1): không có `--project`, hook gom các plan áp dụng cho một lời gọi và chặn nếu **bất kỳ plan enforce nào chặn**, theo hai vai: **plan của phiên** (`CLAUDE_PROJECT_DIR`) xét cả lời gọi; **plan của repo khác mà lời gọi chạm tới** (repo chứa đường dẫn Edit/Write ghi — cwd không phải nơi tìm của Edit/Write —; với lệnh shell: repo chứa cwd và repo của mọi đường dẫn ghi đọc được) chỉ xét những gì lời gọi làm trong chính repo đó (đường dẫn ghi nằm trong repo ấy, cộng `bash_deny` và luật nhắc tên); plan `stopped_with_report` của nó chỉ từ chối lời gọi có ghi vào repo của nó. Mỗi nơi tìm chỉ lên tới gốc repo của nó. Plan chưa duyệt (accepted, proposed), ở chế độ log hay vắng mặt không bao giờ nới lệnh chặn của plan khác. Luật nhắc tên của hook xét từng đoạn của lệnh. (Bản dev3 đầu chỉ xét `CLAUDE_PROJECT_DIR`; bản thứ hai cho "plan tìm thấy đầu tiên thắng" rồi gom mọi plan xét cả lời gọi, nên plan của một repo anh em hay của checkout cha khóa nhầm một phiên worker.) Hệ quả có chủ ý: thư mục scratch hay worktree lồng nằm trong repo khác có plan enforce vẫn bị plan đó chặn. Giới hạn (bãi đỗ): phiên mở ở thư mục con của project mà AI ghi một `.git` giả trong thư mục con thì mất plan của project; khóa sổ đăng ký không nguyên tử tuyệt đối; chi phí tìm plan mỗi lần gọi hook chưa tối ưu. Mất `<project>/.onecrew/active-plan.json`, hay cả `.onecrew/` (mất `config.json`), mà bản sao state-root của chính project còn thì vẫn tìm thấy và vẫn chặn: sổ `hook-projects.json` (project → state-root, trong state-root mặc định, ngoài project) do **hook tự ghi mỗi khi đọc được `config.json`** và `onecrew init` cũng ghi; sổ nằm trong `permissions.deny` và danh sách đường dẫn được bảo vệ, ghi bằng khóa + file tạm đổi tên, và không xóa mục của ổ đĩa không gắn.
- **Reviewer** (P0.2, P0.3): cây reviewer = index thật + sửa đổi của file đã có trong index (file mới đã `git add` có trong diff); cây đó phải trùng artifact (so bằng danh sách đường dẫn của git): chỗ khác nhau — file chưa theo dõi không ignore, `git rm --cached`, `git add -f` file ignore chưa commit, assume-unchanged/skip-worktree, submodule chưa stage — làm mốc `inconclusive`, lý do nêu đường dẫn và các nguyên nhân (`not_shown` trong biên nhận); artifact lấy trước, cây chụp một lần, diff cắt từ đúng cây đó (biên nhận có `base_tracked` và `tracked_tree`); thay đổi trong lúc review → `inconclusive`; artifact không dựng được → biên nhận `inconclusive` có lý do, không làm `verdict run` lỗi. Diff cắt với `--ignore-submodules=none` (cấu hình `ignore=all` không giấu một submodule đổi commit, và nó không bao giờ là thay đổi trung lập), `--submodule=short` (`diff.submodule=log` không làm mất dòng tiêu đề), `--no-renames`, tiền tố cố định; mỗi đường dẫn đổi phải có đúng dòng `diff --git a/<path> b/<path>` (so cả dòng, theo cách git viết tên có ký tự đặc biệt). Đường dẫn git chỉ hiện `Binary files differ`: file **nhị phân thật** — MỌI bản đang có (cũ và mới) có byte NUL và không bản nào bắt đầu bằng BOM UTF-16/32 (ảnh, jar) — đã được diff nêu tên và **không** chặn pass; mọi trường hợp khác (chữ bị `-diff`, diff driver binary hay `core.bigFileThreshold` giữ ra khỏi diff; nhị phân bị thay bằng script; chữ bị chèn NUL; chữ UTF-16/32) → `inconclusive` kèm tên. Giới hạn: phép thử là byte NUL nên file chữ chỉ có NUL (không BOM, một bản) bị coi là nhị phân. Các lệnh git liệt kê đường dẫn chạy ở gốc repo (`diff.relative=true` không giấu file khi chạy từ thư mục con).
- **Trung lập** (P0.4): bỏ danh sách mặc định (`NEUTRAL_DEFAULT`); chỉ `scope.neutral` hợp đồng tự khai mới trung lập. Đổi hành vi so với 2.2.0.dev2: commit chỉ sửa `docs/**`, `*.md`, `CHANGELOG*` nay chạy lại mốc `command` nếu hợp đồng không khai.
- **Kế thừa** (P0.6): chữ ký gồm tiêu đề, verifier, `covers` và toàn văn từng output mốc phủ (sửa chữ output không phủ vẫn giữ pass); mốc `reviewer` kiểm lại luật độc lập cho revision mới. Giới hạn còn lại (bãi đỗ): output được nhận biết bằng vị trí (`O<n>`), nên chèn một output lên đầu đổi chữ của mọi `O<n>` sau nó và các mốc phủ chúng chạy lại; chưa phân biệt đổi chữ với đổi nghĩa.
- **Report** (P0.5): `plan report` dùng cùng view mốc với `plan show` và in đúng trạng thái đó (mốc `stale` hiện `cũ`, mốc kế thừa hiện `pass (kế thừa từ bản N)`, kể cả dòng kết luận), không in kết quả verdict cuối; ghi chú reviewer của lần pass được kế thừa có trong report. Plan đã nghiệm thu được đọc **từ bản ghi `plan.accepted`** (verdict ghi sau cùng của mỗi `receipts`), không tính lại bằng luật mới và **không có chữ `kế thừa`/`trung lập`/`stale`** (cái đã mang pass qua nằm trong `carried` của sự kiện), nên một plan đã nghiệm thu bằng 2.1 hay luật cũ vẫn đọc đúng như lúc nghiệm thu và report của nó **không đổi byte**. Ngoại lệ duy nhất: plan đã nghiệm thu bằng bản dev2 nhờ verdict kế thừa — report cũ ghi sai "chưa có verdict" cho mốc đó, nay hiện pass mà nó được nghiệm thu bằng. `accept` từ chối artifact toàn số 0. `plan digest` không đổi.
- **UTF-8** (P0.7): mọi lệnh hook ép stdout/stderr UTF-8 (module và `onecrew hook <verb>`); `init`/`merge_settings` chỉ thay handler do OneCrew cài, giữ handler của công cụ khác có nhắc tên module.
- **Mã cây** (D3): mã cây đọc từ biên nhận/sổ phải là hex 40/64 và đứng sau `--end-of-options`; plan không có cây tracked-only dùng được → biên nhận `inconclusive` có lý do, không làm `verdict run` lỗi.
- Tests: `tests/test_v2_trust_fixes.py` (mỗi lỗi có test thất bại trên mã có lỗi, `8383446` hoặc bản dev3 đầu `38e1703`; vài test bảo vệ hành vi không được đổi xanh cả trên mã cũ). Bốn test của `tests/test_v3_verify_cost.py` đổi kỳ vọng theo D4/D5 (`test_the_default_neutral_paths_are_read_not_written`, `test_neutral_globs_do_not_cross_a_slash_except_double_star`, `test_an_untracked_file_is_never_in_the_diff_and_verdict_diff_makes_no_call_and_writes_nothing`, `test_the_same_after_a_pass_the_pass_remembers_the_tracked_tree_not_the_untracked_files`); hai kiểm version đổi sang `2.2.0.dev3`. `docs/v2-verify-cost.vi.md`.

## v2.2.0.dev2 (đợt 1: kiểm rẻ hơn, giữ sáu bất biến)

- Verdict được **kế thừa** sang revision mới đã duyệt khi mốc (tiêu đề + verifier) byte-giống và artifact giống, hoặc (mốc `command`) chỉ khác ở `scope.neutral`; `plan show` có `carried_from`, `neutral_diff`, `stale`; `verdict run` kiểm thứ tự và "đã đạt" trước khi chạy. Không thêm sự kiện/bảng. `docs/v2-verify-cost.vi.md`.
- `scope.neutral` (mặc định đọc là `docs/**`, `*.md`, `CHANGELOG*`, không ghi vào hợp đồng); `accept` nhận verdict kế thừa qua khác biệt trung lập và ghi `carried`.
- Reviewer chỉ đọc file có theo dõi: diff giữa hai cây tracked-only ghi sẵn trong sổ (`base_tracked` ở `plan.approved` đầu tiên, `tracked_tree` ở biên nhận reviewer; cơ sở = lần pass gần nhất của chính mốc đó với cùng cấu hình, chưa có thì `base_tracked`; thiếu cả hai thì lỗi rõ, không có đường dự phòng); `verdict diff --plan P --milestone M`, `verdict artifact --plan P`. `owner accept --artifact-sha` chỉ nhận mã hex 40/64 và git nhận mã sau `--end-of-options`.
- `plan lint`: `criterion_literal_present`, `criterion_vs_non_goal` (cảnh báo), `criterion_no_fail_clause` (từ chối), `--ack-criteria`; `unknowns_missing` + `understanding.no_unknowns_because` ở lint và approve. `examples/contract-template.json`.
- `plan report`: mục "Reviewer ghi chú ngoài tiêu chí".
- Tests: `tests/test_v3_verify_cost.py`. Hai assert cũ đổi theo luật mới (nêu ở đây để không lẫn): `test_a_verdict_does_not_survive_an_amendment` nay đổi chính mốc M1 (mốc không đổi thì kế thừa); `test_a_diff_over_the_cap_is_not_reviewed_in_part` nay commit file lớn (file chưa theo dõi không vào diff); hai kiểm version đổi sang `2.2.0.dev2`.

## v2.2.0.dev1 (G2: cài xong là có sổ, hook và lệnh chủ sở hữu)

- `onecrew init [--state-root P] [--shared] [--yes]`: tạo sổ, `plans/owner-rules.md` (mẫu trong wheel), `.onecrew/config.json`, và gộp hook vào `.claude/settings.local.json` (`--shared`: `settings.json`) theo khóa; có `.bak`, hỏi y/N, chạy lần hai không đổi byte nào. Kiểm Claude CLI (tìm thấy + đã đăng nhập), không tự đăng nhập; thiếu thì vẫn ghi và exit 1.
- Hook do init ghi dùng chính file `onecrew` đã cài (`onecrew hook <verb>`), không ghi đường dẫn python, repo hay `--project/--state-root`; hook lấy project từ `CLAUDE_PROJECT_DIR` và sổ từ `.onecrew/config.json`. `permissions.deny` thêm `owner approve|accept|enforce|record`. `hook install --print` (checkout) giữ dạng cũ, dùng chung danh sách deny.
- `onecrew doctor`: một dòng PASS/WARN/FAIL cho Python, git, Claude CLI, đăng nhập, sổ, config.json, hook, plan đang mở; exit 1 khi có FAIL.
- `onecrew owner approve|accept|enforce|record`: thay bốn script `scripts/owner/*.ps1`; cố định `--by owner`, bị từ chối trong phiên AI như các động từ cũ.
- Ba lệnh mới nói tiếng Anh, `ONECREW_LANG=vi` đổi sang tiếng Việt (`onecrew/v2/messages.py`); output cũ không đổi. `docs/README.en.md`.
- Mẫu quy tắc `owner-rules.vi.md` + `owner-rules.en.md` là package data của wheel (`onecrew/templates`); `plan rules init` đọc từ đó (mặc định bản vi như trước, `ONECREW_LANG=en` cho bản en). Lệnh `plan`/`verdict`/`owner` không có `--state-root` thì đọc `.onecrew/config.json` của project.
- `tests/test_g2_install.py`.

## v2.2.0.dev0 (G1: lõi v2 cài được bằng pip)

- Wheel chỉ gồm lõi + `onecrew.v2` + `onecrew.v2.verifiers` (danh sách `py-modules` trong `pyproject.toml`); lệnh `onecrew` của wheel là router v2 (`plan`, `verdict`, `hook`), `onecrew_cli.py` ở checkout vẫn là router đầy đủ v1 + v2. Chi tiết: `docs/v2-core.vi.md`.
- Tách lõi khỏi v1 bằng cách dời phần dùng chung (một nguồn; v1 import lại): `budget_core` (đọc ngân sách), `independence`, `task_intake` (`submit` của task neo, `outcomes`, `recommend`), `onecrew/v2/changes.py` → `onecrew/solution_changes.py`. Sổ cái, loại và payload sự kiện không đổi; sổ cũ đọc y nguyên.
- Tìm Claude CLI theo hệ điều hành (PATH, rồi `~/.local/bin`, npm global...), lỗi nêu mọi nơi đã tìm; model mặc định (Opus 5.5) ở một module (`onecrew/v2/claude_cli.py`), ghi đè bằng `ONECREW_DEFAULT_MODEL`.
- `tests/test_g1_core.py`: closure import, tìm CLI (posix/nt giả lập), metadata đóng gói, model mặc định.
- Không còn trong wheel: `onecrew-entry-mcp` (chạy từ checkout).

## v2.1.0 (20/10/2026) có gì

v2 = **hợp đồng công việc cho AI**: AI chỉ chạy trong một hợp đồng đã được chủ sở hữu duyệt. Sáu bất biến cứng: không có hợp đồng đã duyệt thì không chạy; ngoài phạm vi thì bị chặn; hết ngân sách thì dừng; mốc chưa có verdict thì không qua; tác giả không tự duyệt việc của mình; chỉ con người mới nghiệm thu.

Phần lõi v2 (lát L1–L2, item 3, item 4):
- Sổ cái (ledger) ghi biên lai và verdict cho từng mốc (L1).
- Hook cho Claude Code: PreToolUse, UserPromptSubmit, Stop; `hook install --print` in cấu hình (L2).
- Verifier `command`: chạy lệnh kiểm trên checkout sạch (L1).
- Verifier `reviewer`: model độc lập duyệt diff theo 3 tiêu chí (item 3).
- Mốc `owner-manual`: chủ sở hữu tự đọc và nghiệm thu (L1).
- `plan report` (kết luận tiếng Việt 4 dòng + 7 mục) và `plan digest` (item 4).

v2.1 bổ sung:
- Job 9: trường `origin`, `decisions`, `items[].source`, trường trình bày; cổng `approve` chặt khi có `<state-root>/plans/owner-rules.md`; `plan advise` (cố vấn Opus, 3 câu hỏi cố định so với file quy tắc; bắt buộc khi `decisions` không rỗng hoặc cỡ M/L); `plan rules init|show`.
- Job 11a: `plan lint`; verifier `command` fail-closed (đầu ra rỗng, chạy nhanh mà im lặng, ký tự điều khiển, thiếu file thực thi → `inconclusive`); hook Stop nhả khi có biên lai chưa verdict hoặc câu hỏi chủ sở hữu đang mở; `amend` sau khi duyệt chỉ đóng băng lại các mốc bị đổi.

Bằng chứng: 14 job thật trong `state-v2-real` (11 đã nghiệm thu), khoảng 290 test.

## Giới hạn đã biết

- Hook Stop chỉ thấy biên lai sau khi lệnh chạy xong; cần sự kiện "bắt đầu chạy" — **dự kiến 11b**.
- `contract.validate` vẫn nhận ký tự điều khiển trong `argv`; chỉ `plan lint` và verifier bắt được.
- Mốc `command` im lặng luôn `inconclusive` dù đạt: lệnh kiểm phải in kết quả.
- Verifier `command` của Flutter không giải được path dependency anh em trên checkout sạch; chạy kiểm trong worktree (như `run_flutter_checks.py`).
- Tỉ lệ bắt lỗi của cố vấn chưa được đo.
- Quy tắc R1 trong `examples/owner-rules.vi.md` ghi sai ("debug cho chạy thử"); đúng: build debug khi đang phát triển, chỉ release khi đã xong, test đạt và chủ sở hữu đã thử trên thiết bị — **dự kiến sửa ở 11b**.
- Hook chỉ đọc chữ của lệnh; script Python dựng lệnh bằng ghép chuỗi vẫn qua lớp hook (xem `docs/v2-parking-lot.vi.md`).
- Reviewer: mỗi lần gọi tốn khoảng 9k token cache; diff quá 120 KB không được review (`inconclusive`); chưa kiểm `evidence.file` có nằm trong diff.
- `plan report` chưa đếm số lệnh/token, chưa có HTML.
- Một số test v1 đỏ sẵn có (ví dụ `test_sandbox_gate` khi đường dẫn worktree dài); không do v2.

## Cách chạy

CLI (từ thư mục repo):

```
<python> -X utf8 onecrew_cli.py --project <repo> --state-root <state-root> plan|verdict|hook ...
```

- Hook: `hook install --print` in cấu hình, dán vào `.claude/settings.json` của project.
- Chạy verifier: `verdict run --plan <tên> --milestone <Mx>`.
- Báo cáo: `plan report`, `plan digest`.
- Các động từ của chủ sở hữu (`approve`, `accept`, `enforce`, `verdict record --by owner`) chỉ gõ từ terminal của chính chủ sở hữu, không từ phiên AI.
- Sổ cái và hợp đồng nằm trong `<state-root>` (`ledger.sqlite3`, `plans/`, `policy.json`); `.onecrew/active-plan.json` trong project là bản xuất để hook đọc.
