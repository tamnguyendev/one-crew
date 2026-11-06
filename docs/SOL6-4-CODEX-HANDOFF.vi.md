# Sol6.4 — khép P2 còn lại của S5-4

Code `16b47d7453aa5a59d7a9986c737d4e579b4d7ef9` (kèm commit chỉ sửa test `c040450`), nhánh `claude/sol6-close-s5`, worktree `C:/OneCrewRuns-sol6/wf`. Trước đó: `39d47be` (`sol6.3`). Version `2.5.0.dev10+sol6.4`. Gói `C:/OneCrewRuns-sol6/final4`. Wheel `wheel/onecrew-2.5.0.dev10+sol6.4-py3-none-any.whl`, SHA256 `4f25c3991dc503aaa61ab31573fa99e948670b66e591e0e2bf68dbecd024a64f`.

**Kết luận: lớp lỗi "cách ly thất bại thì rơi về ghi vào project" đã khép trên wheel này; sẵn sàng để Codex xác nhận bản vá.** Chưa push, tag, phát hành, nâng runtime hay nghiệm thu thật. Gói `final3` giữ nguyên.

## Nguyên nhân và cách khép cả lớp lỗi

**Nguyên nhân.** Trên `sol6.3`, `_object_env` coi mọi lỗi khi xác định kho object là "không phải repo" và trả `{}`, nên git tiếp tục ghi vào project. Lỗi lập kho tạm thì không được bắt: có đường đọc nuốt lỗi và báo đạt mà không kiểm cây.

**Cách khép** (`onecrew/v2/verifiers/command.py`), không thêm cơ chế mới:

| Nhánh | `sol6.3` | `sol6.4` |
|---|---|---|
| Timeout, không khởi chạy được git, mã lỗi khác, đầu ra rỗng, đường dẫn hỏng | Rơi về ghi vào project | Lệnh đọc dừng, `ReadIsolationFailed` |
| `verdict diff` khi cây đổi | Ghi object dù tài liệu ghi "nothing written" | Lệnh đọc, cùng cơ chế |
| Git nêu một thư mục `objects` không có; không tạo được thư mục tạm | Lệnh đọc báo đạt mà không kiểm cây | Lệnh đọc dừng |
| Đường dẫn có ký tự điều khiển; backslash trong đường dẫn alternate | Chưa xét | Dừng; có escape đúng |
| Code bên trong nuốt lỗi (`plan.now`, `covers`, báo cáo) | Thành kết quả "không đánh giá" | Lỗi được giữ: mọi lệnh git sau đó bị từ chối, và cuối lệnh vẫn báo lỗi |
| Thư mục chắc chắn không phải repo, hoặc không tồn tại | Đi tiếp | Đi tiếp, git tự trả lời như cũ |
| Repo hỏng (`.git` trỏ sai) | Bị coi là không phải repo | Dừng, không nhầm với không phải repo. Nhận dạng ở `LC_ALL=C`, không phụ thuộc ngôn ngữ git |

**Kết quả trả về.** `plan show`, `plan report`, `plan present` trả lỗi rõ, mã 2. `engine.next_action` trả `inspect/blocked` kèm lý do, không có lệnh. `verdict diff` là lệnh đọc, nay dùng cùng cơ chế.

**Hồi quy trực tiếp đã chặn.** Các cửa hành động (`propose`, `amend`, `approve`, `accept`, `verdict.record`, `advise`) gọi `plan.show` để trả kết quả sau khi đã ghi, nên lỗi đọc có thể làm một hành động đã ghi trông như thất bại. Chúng nay dùng `_show`. Trên cây lệch, các cửa này có thể ghi object như trước `sol6.3`.

## Đỏ trên baseline, xanh trên wheel cuối

Cùng một chương trình `probes/p_read_fault.py` chạy trên venv `final3` và venv `final4`, mỗi bên một lab, trên root đã bàn giao có verdict và cây đã đổi.

| | Baseline `sol6.3` | Wheel `sol6.4` |
|---|---|---|
| Probe gốc Codex, `plan.show`: object mới bình thường / timeout / mã lỗi | 0 / 2 / 2 | 0 / 0 / 0 |
| Probe gốc Codex: kết quả hai ca lỗi | returned (báo thành công) | `ReadIsolationFailed` |
| API, 6 loại lỗi × 5 lệnh đọc: số lần ghi object | 20/30 | 0/30 |
| API: số lần báo thành công dù lỗi | 28/30 | 0/30 |
| CLI, 3 loại lỗi × 5 lệnh: số lần ghi object | 15/15 | 0/15 |
| CLI: số lần báo thành công dù lỗi | 15/15 | 0/15 |
| Báo đạt giả trên cây đã đổi | 4/45 | 0/45 |
| `verdict diff` khi cây đổi (`test_the_diff_is_a_read…`) | đỏ: 2 object mới (`base-tests/diff-on-sol63.log`) | xanh: 0 object, có lỗi thì dừng |
| `.git` trỏ sai, không tiêm lỗi | bị coi là không phải repo | `ReadIsolationFailed` |

Log: `logs/probes/read-fault-baseline-final3.{json,log}`, `read-fault-final.{json,log}`. Probe gốc của Codex chạy trên wheel mới: `codex-read-fault.log`, `codex-read-fault-result.json`; chỉ đổi hai đường dẫn (thư viện probe và nơi ghi kết quả), không đổi điều kiện. Xem thêm mục sự cố bằng chứng. CLI thật: `onecrew.exe` khi bình thường; có lỗi thì `onecrew.console.main` trong một tiến trình riêng (`probes/fault_cli.py`), chỉ làm hỏng đúng bước xác định kho object.

## Đối chứng giữ nguyên hành vi

- **Đọc bình thường trên cây đổi:** 10/10 dòng cùng kết quả với baseline, 0 object mới.
- **Mã cây:** Lệnh đọc và cửa hành động ra cùng mã cây; `plan show` vẫn báo `stale`.
- **Cửa lưu khi lỗi đang bật:** Verdict `passed`, verifier chạy thêm 0 lần (bằng chứng được dùng lại), cây nằm trong project, `verdict artifact` giữ cây lệch, nghiệm thu `accepted`; giống baseline.
- **Thư mục không phải repo:** Không có kho tạm, đi tiếp; git tự trả lời như cũ.
- **Đường dẫn có `;`, khoảng trắng, tiếng Việt:** Kho tạm chạy đúng, cùng mã cây (`test_s5_4_the_store_works_for_a_path…`).
- **Chuỗi tới nghiệm thu:** S1, S4 (nhiều vòng sửa), S23 (reviewer), S33 (root cũ), nghiệm thu sau hạn.
- **Phản chứng từ chối:** S34 cây đổi thì nghiệm thu từ chối; S17 lỗi snapshot; S21 verdict không rõ kết quả nêu `release-run`.

## Kết quả kiểm trên đúng wheel này

| Kiểm | Kết quả |
|---|---|
| Test chịu ảnh hưởng | Lượt 1, 30 nhóm: **395 passed, 0 failures, 1 errors, 0 skipped**, `wrong_origin` 0, không lỗi setUpClass (`logs/reg`). Error duy nhất là lỗi bộ kiểm, nêu ở mục dưới. Lượt 2, cùng wheel, 4 module gồm `test_v2_report` đã sửa bộ kiểm và 3 module khác giả lập `subprocess`: **65 passed, 1 failures, 0 errors, 0 skipped** (`logs/reg2`). Failure duy nhất có từ trước, nêu ở mục dưới. Hai lượt không cộng thành một |
| Đối chiếu | 21/21 điều kiện đạt (`probe-assessment.json`); 5/5 chương trình probe thoát 0, log được đọc theo từng dòng |
| Smoke | 38/38 trên gói; `thu-goi.ps1` đạt 38 điều kiện trên venv mới. Đây là fixture |
| Định danh gói | Payload 145/145 khớp `git archive`, cài đúng từng file, 142/142 module nạp từ venv (`identity-result.json`) |
| Mốc bảo vệ | 5/5 giữ hash (registry, hook và config SignSDK, wheel Sol5, wheel `sol6.3`); `final3` khớp `SHA256SUMS` của nó |
| Thời gian đọc, 5.000 file, máy rảnh | `track show` 1,1 s, `plan digest` 0,8 s, `plan show` 6,2 s |

Phạm vi và lý do ở [affected.md](affected.md). Không chạy toàn gate và không chạy lại 727 test.

**Error ở lượt 1 là lỗi bộ kiểm, không phải lỗi sản phẩm.** `test_the_reader_refuses_to_write_and_needs_no_model` giả lập `subprocess.run` trên toàn tiến trình để làm hỏng bước `git log` của báo cáo, nên làm hỏng luôn bước xác định kho object, với đầu ra dạng chuỗi mà tiến trình thật không bao giờ trả. Commit `c040450` chỉ thu hẹp phần giả lập về đúng bước `git log`; hai assertion giữ nguyên. `git diff 16b47d7..c040450 -- onecrew pyproject.toml` rỗng, nên wheel không đổi.

**Failure ở lượt 2 có từ trước, không do bản này.** `test_v24_s1_bundle…test_version_hash_unknown_when_not_installed` có assertion `probe['checkout']` (chú thích trong test: "these tests run the checkout's code"), nên sai khi chạy trên wheel. Cùng test đỏ với cùng lỗi trên wheel `sol6.3` (`C:/OneCrewRuns-sol6/base-tests/bundle-on-sol63.log`). Không sửa test này.

**Thay đổi hành vi cần biết:** repo thật sự hỏng trước đây vẫn in được `plan report`, có thể ghi "mọi mốc đạt" mà không kiểm cây. Nay lệnh báo lỗi rõ, kèm nguyên nhân.

**Không lấy PASS của `sol6.3` cho wheel này.** Các issue khác đã được Codex tái kiểm trên `sol6.3`, không mở lại vì thay đổi của bản này chỉ ở nhánh lỗi của kho tạm và view sau hành động. Trên wheel này chỉ chạy lại các chuỗi chịu ảnh hưởng nêu trên.

## Giới hạn còn lại và trạng thái phát hành

| Giới hạn | Ảnh hưởng |
|---|---|
| `plan show` và `engine.next_action` vẫn băm 1 lần mỗi lần gọi, như Sol4, và không ghi gì vào project | Repo lớn chậm ở hai đường này, không ở trang theo dõi; không chặn |
| Lỗi kho tạm được tiêm ở bước xác định kho object; ca thật không tiêm chỉ có `.git` trỏ sai | Đủ cho logic; không chặn |
| Chưa có repo cỡ MEP, provider thật, terminal chủ thật, hook phiên thật; trạng thái dừng trên web chưa kiểm bằng trình duyệt | Như `sol6.3`; nên thử có giám sát |
| Việc phát triển bản này không có hợp đồng v2, OneCrew không giám sát, vì chỉ thị cấm đụng sổ thật | Bằng chứng lấy từ wheel và lab |

**Trạng thái:** chờ Codex xác nhận bản vá rồi quyết định release. Theo đánh giá của tôi, các giới hạn trên không chặn beta thử có giám sát, nhưng chưa đủ để gọi là ổn định.

## Sự cố bằng chứng trong lượt này

Lúc 09:05, bản copy probe của Codex do tôi tạo vẫn giữ đường dẫn cũ vì lệnh `sed` đổi đường dẫn không khớp, và tôi không để ý. Lượt chạy trên wheel mới đã **ghi đè** `C:/OneCrewRuns-sol6/codex-review-20261106-c/read-fault-result.json`, trái yêu cầu giữ nguyên bằng chứng baseline. Tôi phát hiện khi đọc bảng đỏ/xanh và đã khôi phục file: các dòng lấy từ `read-fault.log` gốc (không bị đụng), `root` lấy từ nội dung đã đọc trước đó, ghi theo đúng cách probe ghi. File trở về đúng 613 byte và cho `0 / 2 / 2`. Thời gian sửa đổi của file đặt theo `read-fault.log`, nên đây là bản khôi phục, không phải file gốc nguyên vẹn. Bản bị ghi đè giữ ở `logs/probes/codex-result-overwritten-by-my-run.json`. Bản copy `probes/probe_read_fault.py` đã sửa, được kiểm bằng cách so từng byte với probe gốc ngoài hai đường dẫn, rồi chạy lại vào `logs/probes/codex-read-fault-result.json`. Nếu Codex còn bản riêng của file này, nên đối chiếu.

## Đính chính

- **"S5-4 đã khép" ở `sol6.3`** là quá sớm: đường bình thường đúng, nhưng nhánh lỗi vẫn ghi vào project và có ca báo đạt giả. S5-4 chỉ khép ở `sol6.4`, nếu Codex xác nhận.
- **"`engine next`"** trong hồ sơ `sol6.3` là sai tên: CLI không có lệnh này. Đúng là hàm `engine.next_action`, hiện ra qua `engine step` và `engine diagnose`.
- `verdict diff` ghi "nothing written" nhưng trên `sol6.3` vẫn ghi object khi cây đổi; đã sửa.

## Thử gói

```bash
powershell -ExecutionPolicy Bypass -File "C:/OneCrewRuns-sol6/final4/thu-goi.ps1"
```

Đạt khi dòng cuối bắt đầu bằng `DAT:` và có `38 dieu kien smoke`. Đây là fixture, không phải nghiệm thu.

## Codex kiểm lại phần thay đổi

Diff: `git -C C:/OneCrewRuns-sol6/wf diff 39d47be..16b47d7`. Trọng tâm là `_object_env`, `_objects_of`, `leaves_no_objects` trong `command.py` và việc đổi `show` sang `_show`.

Chạy phản chứng bằng lab riêng, không ghi vào `final4`:

```bash
source /c/OneCrewRuns-sol6/final4/env.sh; export RV2_LAB='C:\codex-sol64-lab' TEMP='C:\codex-sol64-lab\tmp' TMP='C:\codex-sol64-lab\tmp' LOCALAPPDATA='C:\codex-sol64-lab\may\local' APPDATA='C:\codex-sol64-lab\may\roaming'; mkdir -p /c/codex-sol64-lab/tmp /c/codex-sol64-lab/may/local /c/codex-sol64-lab/may/roaming; cd /c/OneCrewRuns-sol6/final4/probes; "$VPY" -B -X utf8 p_read_fault.py 'C:\codex-sol64-lab\result.json'
```

Đạt khi mọi dòng có lỗi tiêm đều `obj 0` trong `result.json` (`new_git_objects: 0`), và kết quả là `ReadIsolationFailed` hoặc `This read stopped`.
