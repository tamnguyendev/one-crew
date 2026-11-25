# Bắt đầu lại OneCrew 2.5.0.dev31 (phiên mới / đổi tài khoản / đổi máy)

## 1. OneCrew là gì
Hợp đồng công việc cho AI: AI chỉ làm trong một hợp đồng (plan) mà chủ sở hữu đã duyệt, mọi mốc phải có verdict độc lập, và chỉ con người nghiệm thu. Sáu bất biến cứng:
1. Không có hợp đồng đã duyệt thì không chạy. 2. Ngoài phạm vi thì bị chặn. 3. Hết ngân sách thì dừng. 4. Mốc chưa có verdict thì không qua. 5. Tác giả không tự duyệt việc của mình. 6. Chỉ con người mới nghiệm thu.

Có gì trong từng bản và giới hạn: [CHANGELOG.md](CHANGELOG.md) và [ghi chú phát hành trên GitHub](https://github.com/tamnguyendev/one-crew/releases). Lỗi đã biết: [LOI-DA-BIET.vi.md](obs2/su-dung/LOI-DA-BIET.vi.md). Chi tiết thiết kế: `v2-step0.vi.md`, `v2-reviewer.vi.md`, `v2-advisor.vi.md`, `v2-l2-hooks.vi.md`, `v2-report.vi.md`.

## 2. Chương trình, sổ và hook nằm đâu (máy này)
- **Chương trình:** `D:\OneCrewRuns\runtime-dev31\Scripts\onecrew.exe` — venv Python 3.13 cài wheel 2.5.0.dev31 đã phát hành (tag `v2.5.0.dev31`). Không xoá hay sửa venv này: hook người dùng chạy nó, và hook hỏng thì mọi lệnh của mọi phiên Claude trên máy bị chặn. `D:\OneCrewRuns\runtime-dev30` (bản 2.5.0.dev30) được giữ để quay lại, và vì hook của một số dự án vẫn chạy nó.
- **Sổ thật:** `D:\TamNT\Workspace\11.OneCrew\state-v2-real` = `ledger.sqlite3` (sổ cái), `plans\` (hợp đồng, `owner-rules.md`), `snapshots\blobs` (biên lai). Các dự án thật (SRM, cts-port, PhòngKhám…) ghi vào sổ này; mỗi dự án có hook riêng chạy runtime của nó, nâng runtime cho dự án là một việc riêng.
- **Sổ phát triển OneCrew:** `D:\OneCrewRuns\onecrew-development\state`, dùng cho các hợp đồng sửa chính OneCrew. Khi chạy lệnh cho sổ này, đặt `LOCALAPPDATA=D:\OneCrewRuns\onecrew-development\machine\local` và `APPDATA=D:\OneCrewRuns\onecrew-development\machine\roaming` để registry tách khỏi registry thật.
- **Trong mỗi dự án:** `.onecrew/config.json` (sổ của dự án), `.onecrew/active-plan.json` (bản xuất của plan đang chạy, hook đọc file này), `.claude/settings.local.json` (hook dự án). Các tệp này do `onecrew init` ghi, git bỏ qua.
- **Hook người dùng** (cài 18/11/2026 với dev30, chuyển sang dev31 ngày 19/11/2026): `~\.claude\settings.json` có hook PreToolUse trỏ tới runtime ở trên, cài bằng `hook user install`. Mọi phiên Claude Code trên máy, kể cả subagent và phiên mở ngoài dự án, bị plan của dự án đích xét khi ghi vào một dự án đang enforce. Xem trạng thái: `hook user status`. Trỏ hook về lại dev30: chủ chạy `D:\OneCrewRuns\trien-khai-31\quay-ve-dev30.ps1`. Gỡ hẳn: chủ chạy `D:\OneCrewRuns\trien-khai-25\go-hook-nguoi-dung-dev30.ps1`.
- **Registry dự án:** `%LOCALAPPDATA%\OneCrew\hook-projects.json` (dự án → sổ); hook tự ghi dự án có `.onecrew/config.json` mà nó gặp.

## 3. Cách chạy
```
D:\OneCrewRuns\runtime-dev31\Scripts\onecrew.exe --project <repo> --state-root <sổ> <nhóm> <lệnh> ...
```
- Gắn một repo vào sổ: `onecrew init` (ghi `.onecrew/config.json`, hook dự án, khung wiki; hỏi trước khi ghi). Kiểm máy và repo: `onecrew doctor` (mỗi dòng PASS/WARN/FAIL).
- Nhóm chính: `plan` (`lint`, `propose`, `show`, `advise`, `amend`, `report`, `digest`), `verdict` (`run`, `artifact`, `status`), `owner` (động từ của chủ, mục 5), `hook` (`check`, `export`, `user`), `track` (`open`: trang theo dõi), `wiki`. Xem hết: `onecrew --help` và `<nhóm> --help`.
- Reviewer và cố vấn gọi Claude CLI (`claude.exe`) không giao diện: phải `claude login` trên tài khoản đang dùng, nếu không `verdict run` (mốc reviewer) và `plan advise` sẽ lỗi.
- Xem tình hình: `plan digest` (mỗi plan một dòng), `plan report <tên>`, `track open`.

## 4. Quy trình một việc
**Bước 0** (hỏi MỘT lần trước khi viết hợp đồng, mỗi điều chưa rõ kèm mặc định đề xuất): (a) đúng yêu cầu — làm nhiều hơn hay ít hơn lời chủ sở hữu? (b) phạm vi và file; (c) môi trường kiểm có giống thật không; (d) sản phẩm giao ở đâu (trong repo; ngoài repo cần người điều phối); (e) loại build theo vòng đời; (f) thay đổi giữa chừng có thể thấy trước (ghi thành `decisions`); (g) chủ sở hữu nghiệm thu thế nào (đường bấm).

**Các bước:** bước 0 → viết hợp đồng JSON có `origin` (lời nguyên văn của chủ sở hữu), `decisions`, `items[].source`, trường trình bày bằng lời thường → `plan lint --file <json> --author <model id>` → `plan propose <tên> --file <json> --author <model id>` → `plan advise <tên>` khi `decisions` không rỗng hoặc cỡ M/L → MỘT tin "Xin duyệt" → chủ sở hữu chạy `owner approve` + `owner enforce` (script `.ps1` do người điều phối soạn, ghim bản và sha) → làm việc dưới hook → `verdict run --plan <tên> --milestone <Mx>` → `plan report` / `plan digest` → MỘT tin "Xin nghiệm thu" → chủ sở hữu `owner record` (mốc thủ công) và `owner accept`.

**Sáu quy tắc của chủ sở hữu** (file đầy đủ: `<sổ>\plans\owner-rules.md`, mẫu: `examples/owner-rules.vi.md`):
R1 chỉ build DEBUG khi đang phát triển, RELEASE là bước giao riêng sau khi test đạt và chủ sở hữu thử trên thiết bị thật; R2 đúng hai tin mỗi việc; R3 mọi sản phẩm bàn giao đi qua một hợp đồng v2; R4 chẩn đoán chỉ đọc dưới ~5 lệnh và động từ của chủ sở hữu nằm ngoài v2 nhưng phải có log; R5 việc khác ngoài v2 cần chủ sở hữu đồng ý trước; R6 không "Xin nghiệm thu" tính năng giao diện khi chưa chạy trên thiết bị thật.

**Hai tin duy nhất**, mỗi tin theo 5 mục: *Yêu cầu / Người dùng sẽ thấy / Cách bạn nghiệm thu / Không làm / Rủi ro*, cộng "Quyết định của tôi mà bạn chưa yêu cầu" và dòng của cố vấn. Lựa chọn trả lời là câu đầy đủ, kèm hệ quả. Tối đa 6 dòng cho báo cáo.

Với hợp đồng có nhiều mốc lệnh, xem [mẫu khai tệp phụ thuộc và bộ kiểm unittest](../onecrew/templates/command-inputs.vi.md). Khi các lệnh có đích kiểm khác nhau, lint nhắc tác giả xem xét `inputs`. Với đường dẫn ngoài repo trên dòng lệnh, lint nhắc khai `env_inputs`. Hai cảnh báo giữ nguyên hợp đồng và mã thoát của lint.

Thử giao diện đang phát triển với `onecrew --project <dự-án-nguồn> --state-root <sổ-nguồn> track copy-view --clone <bản-clone-Git> --scratch <thư-mục-tạm>`. Dùng một clone riêng và thư mục tạm có sẵn, cả hai tách khỏi dự án và sổ nguồn. Lệnh chụp sổ rollback journal, hiển thị việc của dự án với đường dẫn clone, rồi mở trang trên máy này. Trang có nhãn “Đã tắt so với bản hiện tại”. Dừng bằng Ctrl+C để dọn bản sao. Dùng `--no-browser` để chỉ in URL. Khi cần số liệu mới từ sổ, mở lại bản sao.

## 5. Động từ chỉ chủ sở hữu được gõ

Trong phiên AI, dùng `onecrew owner help approve` hoặc `onecrew owner help accept` để đọc đúng cú pháp, kể cả khi công cụ shell đang áp dụng luật chặn lệnh duyệt.

Phiên đang chờ kết quả chạy `onecrew notifications follow-owner --plan P --revision N --host claude --session ID` trên đúng dự án và sổ, với ID phiên do Claude Code cung cấp. Khi chủ duyệt, trả lời hoặc ghi kết quả, hook kế tiếp của phiên đưa tin và lệnh xác nhận kèm receipt. Chủ chỉ cần chạy lệnh ban đầu. Sau khi hợp đồng đổi bản, phiên đăng ký bản mới.

Mở **Phiên Claude → Kết quả lệnh chủ** để xem sự kiện đã ghi, đã gửi, đã được phiên xác nhận và đã làm tiếp. Bước cuối cần một công cụ của phiên bắt đầu sau xác nhận và một sự kiện `PostToolUse` tương ứng từ hook nền hoặc hook quan sát. Khi phiên rỗi hoặc host chưa hỗ trợ, kết quả chờ trong sổ.

Mục **Phút so ngân sách** trong `plan report` ghi khoảng thời gian lịch từ lúc đề xuất, phần chờ chủ, số phút tính vào ngân sách sau duyệt và tổng thời gian các lệnh có số đo. Các khoảng chờ trùng nhau chỉ tính một lần. Hai lệnh chạy song song có thể đóng góp vào tổng thời gian lệnh trong cùng một phút lịch.

Khi cần ghim lời gốc trước khi cố vấn đọc bản 1, chủ gõ `onecrew plan goal-pin <tên> --words "<mục tiêu>"` khi bản 1 còn chờ duyệt. Chủ chỉ ghim được một lần. Lệnh này tự nó không duyệt bản 1. Với hợp đồng cũ chỉ có trích dẫn do người soạn ghi, nguồn lời gốc hiện là “chưa rõ”.

Khi sửa kế hoạch, người soạn có thể thêm `--goal-source <số sự kiện>` vào `plan amend` để dẫn lại lời gõ hoặc lựa chọn trong phiên Claude trên cùng việc. Trang duyệt, Hướng đi và Phiên Claude ghi “Ghi nhận trong phiên Claude (chưa xác thực)” và kèm câu AI hỏi nếu có. Lời chủ đã ghim và phương án chủ chọn khi duyệt là mục tiêu gốc, không phải lời xin đổi: `plan amend` từ chối dẫn chúng làm nguồn. Vì OneCrew chưa xác thực được lời chủ cho một bản sửa, mọi bản sau bản 1 đều giữ cảnh báo “Bản sửa chưa rõ nguồn lời chủ”; trích dẫn từ hook chỉ cho chủ thấy lời được dẫn. Lời gửi từ chế độ in (`claude -p`), SDK hay lịch chạy mang nhãn “Máy gửi trong phiên Claude” và không dùng được làm nguồn cho bản sửa. Nhãn này dựa vào cách Claude Code tự khai lúc khởi chạy, không chứng minh ai đã gõ: app desktop cũng khai là desktop cho lời do chính nó gửi (tác vụ theo lịch, gửi vào phiên). Xem phần đối chiếu với bản 1 bằng `plan present <tên>` trước khi duyệt.

Hook quan sát do `hook user install --observe` cài mang một khóa riêng của lần cài (OneCrew chỉ giữ mã băm của khóa). Thiếu khóa thì `hook observe`, phần nhập dòng quan sát của `hook sync` và lệnh gọi thẳng hàm quan sát không ghi gì, và dòng chèn tay vào hộp chờ không vào sổ. Lần cài đó cũng chặn công cụ Read của Claude đọc tệp cấu hình chứa khóa. Khóa chỉ chặn việc giả dòng vô ý hay vụng (11 cách người soát đã chạy). Nó không chặn được một AI cố ý né, vì AI chạy cùng tài khoản máy. Các cách đã biết: sửa phép kiểm ngay trong tiến trình Python của nó; trỏ `LOCALAPPDATA` sang một thư mục (kể cả trong `.onecrew/scratch`) có tệp khóa giả và bản sao sổ đăng ký dự án; viết script tự xóa các biến `CLAUDE*` rồi gọi hàm cài hook quan sát trên một tệp cấu hình của chính nó để tự tạo khóa; tự dựng đường tới tệp cấu hình lúc chạy để đọc khóa; đọc khóa trên dòng lệnh của tiến trình hook đang chạy; và hook người dùng không xét công cụ Read ở phiên mà quy tắc chặn Read chưa có. Điều giới hạn tác hại là: mọi dòng từ phiên Claude đều mang nhãn “chưa xác thực”, và không dòng nào từ phiên Claude xóa được cảnh báo “Bản sửa chưa rõ nguồn lời chủ”, duyệt, nghiệm thu hay ghi verdict. Hook cài trước thay đổi này không ghi gì nữa, và các dòng nó đã xếp chờ không được nhập sổ: `doctor` báo điều đó và chủ chạy lại `hook user install --observe`. Phiên AI không cài được hook quan sát.

Trong chế độ enforce, Claude chạy hook quan sát qua cấu hình hook. Nếu lệnh Bash hoặc PowerShell gọi một script ở thư mục tạm ngoài dự án, bộ kiểm có thể từ chối vì nội dung script có thể thay đổi trước lúc chạy.
`owner approve`, `owner accept`, `owner enforce`, `owner record`, `owner answer`, cùng `hook mode` và `hook user`. Phiên AI bị từ chối: CLI nhận ra phiên AI (biến `CLAUDE_CODE_CHILD_SESSION`), tiến trình do bộ kiểm hay lệnh tiền điều kiện của OneCrew khởi chạy (`ONECREW_VERIFIER`), và tiến trình khai `ONECREW_ACTOR` không phải `user|owner`; đây vẫn là lớp mềm, xem LOI-DA-BIET. Đúng bất biến 5–6: người viết hợp đồng không tự duyệt, AI không tự nghiệm thu.
- Chủ sở hữu gõ trong terminal của chính mình; thêm `--human` để đọc được. `--human` có lúc báo "Chưa xác nhận được kết quả" dù sổ đã ghi: đọc lại `plan show` trước khi chạy lại.
- Script ngắn cho bốn động từ, trong `scripts/owner/`: `approve.ps1` (duyệt), `enforce.ps1` (bật giám sát hay chỉ ghi), `record.ps1` (ghi kết quả một mốc thủ công kèm tệp biên nhận), `accept.ps1` (nghiệm thu trên artifact đã kiểm). Mỗi script gọi `onecrew owner …` của runtime dev30, mặc định sổ thật và dự án là thư mục đang đứng (`-Project`, `-StateRoot`, `-OneCrew` để đổi; `-MachineDir D:\OneCrewRuns\onecrew-development\machine` cho sổ phát triển), rồi đọc lại sổ và báo ĐẠT/KHÔNG ĐẠT theo sổ; trong phiên AI thì dừng, không ghi gì. Hướng dẫn và ví dụ ở đầu mỗi script. Với từng việc, người điều phối vẫn có thể soạn script riêng ghim bản và sha.

## 6. Phát triển chính OneCrew

Trong đúng dự án và sổ đang dùng, chạy `onecrew track open --plan RM1` để mở việc RM1. Lưu lại lệnh này để dùng sau khi trang tự thoát. Nếu dùng sổ riêng, giữ `--project` và `--state-root` trước `track`. Thêm `--port 8765` để giữ một cổng cho bookmark. Với `--no-browser`, trường `task_url` dẫn tới việc, `url` dẫn tới đầu trang. Lệnh chỉ mở viewer cục bộ.

Khi engine chờ tài nguyên đã khai báo, vị trí trong hàng đợi gắn với sổ, việc và thế hệ của bước. Mở phần tài nguyên dùng chung hoặc chạy `python -m onecrew.resource_lease status` để xem ai giữ và ai chờ. Nếu một lượt đã mất liên lạc, Supervisor ghi xác nhận cây tiến trình đã dừng qua `Control.finish` cho đúng attempt và generation. `python -m onecrew.resource_lease reconcile` đối chiếu sổ và chuyển lượt khi có bằng chứng. Việc chạy lại reconcile giữ nguyên kết quả đã ghi.
- Chỗ làm việc: worktree `D:\TamNT\Workspace\11.OneCrew\wf-dev30` (nhánh `claude/dev30`, tách từ `main` = 2.5.0.dev30; `main` hiện là 2.5.0.dev31), đã `onecrew init` vào sổ phát triển. Hook dự án của worktree chạy runtime dev30 đã phát hành, hook người dùng chạy runtime dev31; không hook nào chạy mã đang sửa.
- Thư mục `D:\TamNT\Workspace\11.OneCrew\onecrew` giữ nhánh `main`. Các worktree cũ đã gỡ ngày 18/11/2026; thay đổi dở của chúng lưu ở `D:\OneCrewRuns\luu-tru-worktree-20261118`.
- Phát hành: commit phát hành đổi version, dựng wheel một lần, chủ chạy script phát hành (push, tag, prerelease); AI không push hay tag.
- Việc đang chờ: chặn `pkill`/`killall` và `perl -i` trong hook; chạy lại bước 3–5 của `docs/GETTING-STARTED.en.md` trên dev31; phần còn lại của #55, #32 (xem ghi chú phát hành dev31); đã cất ngày 23/11/2026 (đóng, not planned): #36, #41 cùng 12 issue roadmap khác, xem mục lục #54.

## 7. Đổi tài khoản / đổi máy: chép gì
- **Hai sổ** nguyên thư mục: sổ thật `D:\TamNT\Workspace\11.OneCrew\state-v2-real` và sổ phát triển `D:\OneCrewRuns\onecrew-development\state` — mất sổ là mất lịch sử, hợp đồng và biên lai.
- **Mã nguồn:** clone `https://github.com/tamnguyendev/one-crew` (nhánh `main`, tag `v2.5.0.dev31`). **Wiki dùng chung:** `D:\TamNT\Workspace\11.OneCrew\outputs\onecrew-as-qc\wiki`.
- **Bộ nhớ Claude:** thư mục memory của project trong `~\.claude\projects\`.
- Máy mới: tải wheel từ trang phát hành, kiểm SHA256 với `SHA256SUMS`, tạo venv và cài wheel; chạy `claude login`; `onecrew init` cho từng dự án; `hook user install` nếu muốn hook người dùng. Đường dẫn máy cũ nằm trong plan đã duyệt và `active-plan.json` (trường `project`, `state_root`), nên đổi đường dẫn nghĩa là chủ sở hữu duyệt lại plan đang mở.
- Phiên mới của Claude: đọc `CLAUDE.md` ở gốc repo, rồi `plan digest`.

## 8. Gắn phiên điều phối: plan thường trực (standing) và nhắc lời giao việc

Có từ bản chứa GSDP-A (#63 lượt đầu); runtime đã phát hành trước đó không có.
- **Plan thường trực:** hợp đồng ghi `"standing": true`.
  - Hạn = lúc chủ duyệt + `budget.time` phút (tối đa 28800 phút, tức 20 ngày). Xuất lại (verdict, `hook export`, `owner enforce`, mở phiên) không kéo dài hạn; chỉ lần duyệt mới đặt hạn mới.
  - Dừng lượt (Stop) không chặn và không ghi dòng nhật ký vi phạm (`violations.jsonl`) mỗi lượt. Phần theo dõi việc nền vẫn ghi một dòng `parent_stop` mỗi lượt vào `.onecrew/background.jsonl`, như với mọi phiên.
  - Sửa và lệnh vẫn bị xét như plan thường. Hết hạn ở chế độ chặn thì mọi sửa và lệnh của phiên bị chặn tới khi chủ duyệt lại.
  - Plan thường giữ hạn 24 giờ và Stop chặn như cũ. `budget.time` cũng là giới hạn giờ làm của job dưới plan: hai việc dùng chung một số.
  - `owner approve --human` in rõ plan thường trực, giờ hết hạn và việc Stop không chặn.
- **Cách gắn:**
  1. Phiên điều phối có dự án riêng (một repo git) và sổ riêng.
  2. Chạy `onecrew --project <dự-án> --state-root <sổ> init --remind on`. Lệnh thêm một mục PreToolUse riêng `hook remind`, chỉ nhắc, không bao giờ chặn. Nó cũng ghi tệp mẫu `<sổ>\plans\mau-giao-viec.md` nếu chưa có.
  3. Hợp đồng có `standing`; chủ duyệt.
  4. Chủ bật chế độ ghi: `onecrew owner enforce <plan> --mode log`. Mấy ngày đầu chỉ ghi; chủ đọc nhật ký rồi mới chuyển sang chặn.
- **Nhắc lời giao việc:** áp dụng khi plan của phiên là thường trực và lời giao qua Agent, Task, SendMessage, start_session hay send_message thiếu mục của tệp mẫu.
  - Hook ghi một dòng `reminded` và Claude nhận danh sách mục thiếu.
  - Lời nhắc đến SAU khi công cụ đã chạy.
  - Hook so bằng từ khóa, không phân biệt hoa thường, trong mọi chuỗi của lời giao. Nó chỉ biết có tiêu đề, không biết nội dung đúng hay sai.
  - Chủ sửa tệp mẫu bất cứ lúc nào; tệp không còn mục nào thì không nhắc.
  - Gỡ bằng `init --remind off`; `init` không cờ giữ nguyên mục đang có.
  - Runtime cũ không biết `hook remind`, nên phải gỡ mục nhắc trước khi trỏ hook về runtime cũ.
- **Cách thoát đúng:** chủ gõ trong terminal của mình `onecrew owner enforce <plan> --mode log` (về chỉ ghi).
  - Nếu plan có câu hỏi đang mở: `onecrew owner answer <mã câu hỏi> --revision <bản> --choice stop`.
  - Xóa khối hook trong thư mục dự án KHÔNG phải cách thoát: hook người dùng vẫn tìm plan qua bản sao trong sổ.
- **Thử trước:** `scripts/owner/gan-dieu-phoi.ps1` dựng thư mục thử `D:\OneCrewRuns\gsdp-a\thu-gan`, có sổ thử và plan thử thường trực (chủ duyệt trong script). Thư mục điều phối không đổi.
  - Mặc định là chạy thử, không ghi gì; `-ApDung` mới chạy thật.
  - `-TomTat` tóm tắt nhật ký của thư mục thử.
  - `-QuayVe` gỡ mục nhắc và trỏ hook về runtime đã phát hành.

## 9. Mô hình 3 vai: chủ sở hữu, phiên trao đổi, phiên điều phối

Có từ bản chứa VAI3; runtime đã phát hành trước đó không có phần nhắc dưới đây.

| Vai | Việc | Mẫu `CLAUDE.md` |
|---|---|---|
| Chủ sở hữu | Nêu yêu cầu, duyệt, trả lời, nghiệm thu | (người, không cần mẫu) |
| Phiên trao đổi | Nơi chủ nói chuyện; ghi lời chủ; chuyển việc | [trao-doi.vi.md](vai3/trao-doi.vi.md) |
| Phiên điều phối | Chạy dưới plan thường trực; mặc định chỉ giao việc | [dieu-phoi.vi.md](vai3/dieu-phoi.vi.md) |

Thêm một phiên kiểm độc lập khi cần: [kiem.vi.md](vai3/kiem.vi.md). Bản tiếng Anh nằm cạnh (`*.en.md`). Ba vai là tài liệu và mẫu: OneCrew không nhận vai bằng mã, không tự đẩy tin giữa các phiên, và quyền quyết không đổi.

**Nhắc khi chủ gõ thẳng vào phiên điều phối:**
- Áp dụng khi plan của phiên là thường trực (mục 8). Cần hook `hook prompt` mà `onecrew init` vẫn ghi; không cần `--remind on`.
- Mỗi lượt chủ gõ: Claude nhận lời nhắc "ghi lời này vào sổ yêu cầu, báo phiên trao đổi một dòng, rồi làm", và `violations.jsonl` có một dòng `reminded` luật `owner_prompt`. Dòng này không chứa chữ chủ gõ. Không chặn gì.
- Không nhắc: tin của phiên khác và sự kiện của app, tức chữ bắt đầu bằng lớp bọc `<cross-session-message>`, `<system-reminder>`, `<task-notification>`, `<side-sessions-event>` hay `<ci-monitor-event>`. Chữ khác, kể cả lớp bọc lạ, nội dung dán hay đính kèm, đều coi là lời chủ.
- Giới hạn: việc nhận nguồn dựa vào lớp bọc chữ của app. App đổi định dạng thì tin phiên khác có thể bị nhắc thừa. Lời chủ mà app chèn sau một lớp bọc kể trên trong cùng lượt thì không được nhắc.
- Chữ nhắc: tệp `<sổ>\plans\mau-loi-chu.md` (chủ sửa bất cứ lúc nào; cả tệp là lời nhắc). Không có tệp thì dùng chữ mặc định (`ONECREW_LANG=vi` cho tiếng Việt, còn lại tiếng Anh). **Tệp rỗng là tắt.**

Trang `plan present` của hợp đồng thường trực có dòng "THƯỜNG TRỰC" để chủ thấy cờ trước khi duyệt.

**Dòng nhắc trong sổ.** Mỗi lần nhắc là một dòng JSON trong `<dự-án>\.onecrew\violations.jsonl`: `event` = `reminded`, `rule` = `owner_prompt`, `tool` = `UserPromptSubmit`, kèm giờ `at`, `plan`, `revision`, `mode`, mã phiên `session`; `reason` là một câu cố định, `subject` để trống. Muốn đối chiếu "chủ đã gõ gì" thì so giờ của dòng với sổ yêu cầu `YEU-CAU-CHU.vi.md`. `hook sync` nhập các dòng này vào sổ cái như mọi dòng `reminded` khác. Dòng này chỉ cho biết hook đã nhắc, không cho biết Claude đã làm theo.

**Sửa hay tắt lời nhắc.** Chủ tự mở (hoặc tạo) `<sổ>\plans\mau-loi-chu.md`, viết lời nhắc bằng chữ của mình, lưu UTF-8. Cả tệp được đưa nguyên cho Claude (tối đa 4000 ký tự; dòng bắt đầu bằng `#` cũng được đưa). Tệp rỗng hoặc chỉ có dòng trống: tắt. Xóa tệp: về chữ mặc định. Tệp có tác dụng từ lượt kế tiếp, không cần duyệt lại hay mở lại phiên. Tệp không đọc được thì hook im.

**Công tắc "tự làm" của phiên điều phối.** Mặc định phiên điều phối chỉ giao việc. Muốn nó tự sửa mã, chủ thêm đúng một dòng vào `CLAUDE.md` của phiên: `Điều phối được tự làm: bật` (bản tiếng Anh: `Coordinator self-work: on`); bỏ dòng đó là tắt. Đây là luật bằng chữ trong mẫu: chưa có hook kiểm hay chặn, và hợp đồng, phạm vi, quyền của chủ vẫn áp dụng như cũ.

**Giới hạn chung.** Chỉ nhắc, không bao giờ chặn; Claude vẫn có thể bỏ qua. Không chứng minh được chữ do chủ gõ. Không tự đẩy tin sang phiên trao đổi. Chưa có sổ yêu cầu của chủ trong sổ OneCrew (tệp yêu cầu là tệp tay).

**Cách thử.**
- Thử nhanh ở dự án có hợp đồng thường trực đã duyệt: gõ một câu vào phiên, rồi đọc `.onecrew\violations.jsonl` thấy một dòng `owner_prompt`; cho một phiên khác gửi một tin vào phiên đó, không có dòng mới.
- Thử ở thư mục riêng khi phát triển chính OneCrew: `scripts/owner/thu-vai3.ps1`, chạy trong terminal của chủ từ checkout VAI3 đã qua mốc M1. Không công tắc là chạy thử, không ghi gì; `-ApDung` dựng gói và thư mục thử `D:\OneCrewRuns\vai3\thu` rồi hỏi lời duyệt plan thử; `-TomTat` đếm dòng nhắc; `-QuayVe -ApDung` trỏ hook của dự án thử về runtime đã phát hành. Script ghim đường dẫn máy phát triển; đổi bằng tham số `-ThuGoc`, `-Python`, `-RuntimeCu`, `-SoPhatTrien`.

## Nhập review ngoài và kiểm lại finding

Trên plan đang duyệt xong có năng lực `finding-register`, chạy `onecrew findings import-review P1 --file review.json`. Lấy `task_id` từ `anchor_task`, lấy `revision`, `milestone`, `receipt` và `artifact_sha` từ `onecrew plan show P1`. Ví dụ một báo cáo có dạng sau.

```json
{"id":"review-7","reference":"Báo cáo độc lập số 7","result":"changes_requested",
 "task_id":"<anchor_task>","revision":1,"milestone":"M1","receipt":"<receipt>","artifact_sha":"<artifact_sha>",
 "findings":[{"criterion":"M1","paths":["src/output.py"],"claim":"Kết quả làm tròn sai ở biên 0.5","severity":"major"}]}
```

Với mốc reviewer, dùng ID tiêu chí đã duyệt. Mỗi đường dẫn phải thuộc phạm vi sửa và phạm vi phép kiểm. Sổ giữ nguồn review, lời nhận xét và biên nhận kiểm ban đầu. Nhập cùng nội dung và ID lần nữa trả lại các finding đã ghi. Nội dung khác cùng ID bị từ chối.

`onecrew findings list P1 --open-only` liệt kê các điểm đang chặn nghiệm thu. Workflow có engine dùng đường giao sửa hiện có cho node sở hữu tệp. Sau khi sửa, chạy lại mốc và dùng `onecrew findings recheck P1 RF1 --receipt <receipt>`. Bản sửa phải thay đổi trong phạm vi finding và biên nhận phải đạt đúng tiêu chí trên bản hiện hành. Báo cáo và trang theo dõi tiếp tục hiện các finding khác còn mở.
