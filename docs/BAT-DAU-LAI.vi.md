# Bắt đầu lại OneCrew 2.5.0.dev30 (phiên mới / đổi tài khoản / đổi máy)

## 1. OneCrew là gì
Hợp đồng công việc cho AI: AI chỉ làm trong một hợp đồng (plan) mà chủ sở hữu đã duyệt, mọi mốc phải có verdict độc lập, và chỉ con người nghiệm thu. Sáu bất biến cứng:
1. Không có hợp đồng đã duyệt thì không chạy. 2. Ngoài phạm vi thì bị chặn. 3. Hết ngân sách thì dừng. 4. Mốc chưa có verdict thì không qua. 5. Tác giả không tự duyệt việc của mình. 6. Chỉ con người mới nghiệm thu.

Có gì trong từng bản và giới hạn: [CHANGELOG.md](CHANGELOG.md) và [ghi chú phát hành trên GitHub](https://github.com/tamnguyendev/one-crew/releases). Lỗi đã biết: [LOI-DA-BIET.vi.md](obs2/su-dung/LOI-DA-BIET.vi.md). Chi tiết thiết kế: `v2-step0.vi.md`, `v2-reviewer.vi.md`, `v2-advisor.vi.md`, `v2-l2-hooks.vi.md`, `v2-report.vi.md`.

## 2. Chương trình, sổ và hook nằm đâu (máy này)
- **Chương trình:** `D:\OneCrewRuns\runtime-dev30\Scripts\onecrew.exe` — venv Python 3.13 cài wheel 2.5.0.dev30 đã phát hành (tag `v2.5.0.dev30`). Không xoá hay sửa venv này: hook người dùng chạy nó, và hook hỏng thì mọi lệnh của mọi phiên Claude trên máy bị chặn.
- **Sổ thật:** `D:\TamNT\Workspace\11.OneCrew\state-v2-real` = `ledger.sqlite3` (sổ cái), `plans\` (hợp đồng, `owner-rules.md`), `snapshots\blobs` (biên lai). Các dự án thật (SRM, cts-port, PhòngKhám…) ghi vào sổ này; mỗi dự án có hook riêng chạy runtime của nó, nâng runtime cho dự án là một việc riêng.
- **Sổ phát triển OneCrew:** `D:\OneCrewRuns\onecrew-development\state`, dùng cho các hợp đồng sửa chính OneCrew. Khi chạy lệnh cho sổ này, đặt `LOCALAPPDATA=D:\OneCrewRuns\onecrew-development\machine\local` và `APPDATA=D:\OneCrewRuns\onecrew-development\machine\roaming` để registry tách khỏi registry thật.
- **Trong mỗi dự án:** `.onecrew/config.json` (sổ của dự án), `.onecrew/active-plan.json` (bản xuất của plan đang chạy, hook đọc file này), `.claude/settings.local.json` (hook dự án). Các tệp này do `onecrew init` ghi, git bỏ qua.
- **Hook người dùng** (cài 18/11/2026): `~\.claude\settings.json` có hook PreToolUse trỏ tới runtime ở trên, cài bằng `hook user install`. Mọi phiên Claude Code trên máy, kể cả subagent và phiên mở ngoài dự án, bị plan của dự án đích xét khi ghi vào một dự án đang enforce. Xem trạng thái: `hook user status`. Gỡ: chủ chạy `D:\OneCrewRuns\trien-khai-25\go-hook-nguoi-dung-dev30.ps1`.
- **Registry dự án:** `%LOCALAPPDATA%\OneCrew\hook-projects.json` (dự án → sổ); hook tự ghi dự án có `.onecrew/config.json` mà nó gặp.

## 3. Cách chạy
```
D:\OneCrewRuns\runtime-dev30\Scripts\onecrew.exe --project <repo> --state-root <sổ> <nhóm> <lệnh> ...
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
`owner approve`, `owner accept`, `owner enforce`, `owner record`, `owner answer`, cùng `hook mode` và `hook user`. Phiên AI bị từ chối: CLI nhận ra phiên AI (biến `CLAUDE_CODE_CHILD_SESSION`), tiến trình do bộ kiểm hay lệnh tiền điều kiện của OneCrew khởi chạy (`ONECREW_VERIFIER`), và tiến trình khai `ONECREW_ACTOR` không phải `user|owner`; đây vẫn là lớp mềm, xem LOI-DA-BIET. Đúng bất biến 5–6: người viết hợp đồng không tự duyệt, AI không tự nghiệm thu.
- Chủ sở hữu gõ trong terminal của chính mình; thêm `--human` để đọc được. `--human` có lúc báo "Chưa xác nhận được kết quả" dù sổ đã ghi: đọc lại `plan show` trước khi chạy lại.
- Script ngắn cho bốn động từ, trong `scripts/owner/`: `approve.ps1` (duyệt), `enforce.ps1` (bật giám sát hay chỉ ghi), `record.ps1` (ghi kết quả một mốc thủ công kèm tệp biên nhận), `accept.ps1` (nghiệm thu trên artifact đã kiểm). Mỗi script gọi `onecrew owner …` của runtime dev30, mặc định sổ thật và dự án là thư mục đang đứng (`-Project`, `-StateRoot`, `-OneCrew` để đổi; `-MachineDir D:\OneCrewRuns\onecrew-development\machine` cho sổ phát triển), rồi đọc lại sổ và báo ĐẠT/KHÔNG ĐẠT theo sổ; trong phiên AI thì dừng, không ghi gì. Hướng dẫn và ví dụ ở đầu mỗi script. Với từng việc, người điều phối vẫn có thể soạn script riêng ghim bản và sha.

## 6. Phát triển chính OneCrew
- Chỗ làm việc: worktree `D:\TamNT\Workspace\11.OneCrew\wf-dev30` (nhánh `claude/dev30`, tách từ `main` = 2.5.0.dev30), đã `onecrew init` vào sổ phát triển; hook giám sát chạy runtime dev30 đã phát hành, không chạy mã đang sửa.
- Thư mục `D:\TamNT\Workspace\11.OneCrew\onecrew` giữ nhánh `main`. Các worktree cũ đã gỡ ngày 18/11/2026; thay đổi dở của chúng lưu ở `D:\OneCrewRuns\luu-tru-worktree-20261118`.
- Phát hành: commit phát hành đổi version, dựng wheel một lần, chủ chạy script phát hành (push, tag, prerelease); AI không push hay tag.
- Việc đang chờ: chặn `pkill`/`killall` và `perl -i` trong hook; chạy lại bước 3–5 của `docs/GETTING-STARTED.en.md` trên dev30.

## 7. Đổi tài khoản / đổi máy: chép gì
- **Hai sổ** nguyên thư mục: sổ thật `D:\TamNT\Workspace\11.OneCrew\state-v2-real` và sổ phát triển `D:\OneCrewRuns\onecrew-development\state` — mất sổ là mất lịch sử, hợp đồng và biên lai.
- **Mã nguồn:** clone `https://github.com/tamnguyendev/one-crew` (nhánh `main`, tag `v2.5.0.dev30`). **Wiki dùng chung:** `D:\TamNT\Workspace\11.OneCrew\outputs\onecrew-as-qc\wiki`.
- **Bộ nhớ Claude:** thư mục memory của project trong `~\.claude\projects\`.
- Máy mới: tải wheel từ trang phát hành, kiểm SHA256 với `SHA256SUMS`, tạo venv và cài wheel; chạy `claude login`; `onecrew init` cho từng dự án; `hook user install` nếu muốn hook người dùng. Đường dẫn máy cũ nằm trong plan đã duyệt và `active-plan.json` (trường `project`, `state_root`), nên đổi đường dẫn nghĩa là chủ sở hữu duyệt lại plan đang mở.
- Phiên mới của Claude: đọc `CLAUDE.md` ở gốc repo, rồi `plan digest`.
