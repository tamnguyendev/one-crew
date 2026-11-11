# Bắt đầu lại OneCrew v2.1 (đổi tài khoản / đổi máy)

## 1. OneCrew v2.1 là gì
Hợp đồng công việc cho AI: AI chỉ làm trong một hợp đồng (plan) mà chủ sở hữu đã duyệt, mọi mốc phải có verdict độc lập, và chỉ con người nghiệm thu. Sáu bất biến cứng:
1. Không có hợp đồng đã duyệt thì không chạy. 2. Ngoài phạm vi thì bị chặn. 3. Hết ngân sách thì dừng. 4. Mốc chưa có verdict thì không qua. 5. Tác giả không tự duyệt việc của mình. 6. Chỉ con người mới nghiệm thu.

Có gì trong v2.1 và giới hạn: [CHANGELOG.md](CHANGELOG.md). Chi tiết: `v2-step0.vi.md`, `v2-reviewer.vi.md`, `v2-advisor.vi.md`, `v2-l2-hooks.vi.md`, `v2-report.vi.md`.

## 2. Sổ cái và hook nằm đâu
- **State-root thật của máy này: `D:\OneCrewRuns\state-v2-real`** = `ledger.sqlite3` (sổ cái), `plans\` (hợp đồng, `owner-rules.md`, `policy.json`), `snapshots\blobs` (biên lai).
- Trong mỗi project: `.claude/settings.json` (hook + `permissions.deny`, sinh bằng `hook install --print`) và `.onecrew/active-plan.json` (bản xuất của plan đang chạy, hook đọc file này).
- Hook (PreToolUse, UserPromptSubmit, Stop, SessionStart) chặn ngoài phạm vi, nhắc, và không cho nói "xong" khi mốc thiếu verdict.

## 3. Cách chạy
Từ thư mục gốc repo (python của venv: `D:\TamNT\Workspace\9.VMAgent\onecrew\.venv\Scripts\python.exe`):
```
<python> -X utf8 onecrew_cli.py --project <repo> --state-root <state-root> plan|verdict|hook ...
```
- `plan`: `propose, show, approve, accept, amend, precheck, unknown, poc, brainstorm, enforce, advise, rules (init|show), report, digest, lint`.
- `verdict`: `run, record`. `hook`: `install --print, mode, check, prompt, stop, session, sync`.
- Dán hook: `hook install --print` rồi chép kết quả vào `<repo>\.claude\settings.json` (lệnh chỉ in, không sửa file).
- Reviewer và cố vấn gọi Claude CLI (`claude.exe`) không giao diện: phải đăng nhập `claude login` trên tài khoản đang dùng, nếu không `verdict run` (mốc reviewer) và `plan advise` sẽ lỗi.
- Xem tình hình: `plan digest` (mỗi plan một dòng) và `plan report <tên>`.

## 4. Quy trình một việc
**Bước 0** (hỏi MỘT lần trước khi viết hợp đồng, mỗi điều chưa rõ kèm mặc định đề xuất): (a) đúng yêu cầu — làm nhiều hơn hay ít hơn lời chủ sở hữu? (b) phạm vi và file; (c) môi trường kiểm có giống thật không; (d) sản phẩm giao ở đâu (trong repo; ngoài repo cần người điều phối); (e) loại build theo vòng đời; (f) thay đổi giữa chừng có thể thấy trước (ghi thành `decisions`); (g) chủ sở hữu nghiệm thu thế nào (đường bấm).

**Các bước:** bước 0 → viết hợp đồng JSON có `origin` (lời nguyên văn của chủ sở hữu), `decisions`, `items[].source`, trường trình bày → `plan lint --file <json> --author <model id>` → `plan propose <tên> --file <json> --author <model id>` → `plan advise <tên>` khi `decisions` không rỗng hoặc cỡ M/L → MỘT tin "Xin duyệt" → chủ sở hữu `approve` + `enforce` (terminal của họ) → phiên worker có hook → `verdict run --plan <tên> --milestone <Mx>` → `plan report` / `plan digest` → MỘT tin "Xin nghiệm thu" → chủ sở hữu `accept`.

**Sáu quy tắc của chủ sở hữu** (file đầy đủ: `<state-root>\plans\owner-rules.md`, mẫu: `examples/owner-rules.vi.md`):
R1 chỉ build DEBUG khi đang phát triển, RELEASE là bước giao riêng sau khi test đạt và chủ sở hữu thử trên thiết bị thật; R2 đúng hai tin mỗi việc; R3 mọi sản phẩm bàn giao đi qua một hợp đồng v2; R4 chẩn đoán chỉ đọc dưới ~5 lệnh và động từ của chủ sở hữu nằm ngoài v2 nhưng phải có log; R5 việc khác ngoài v2 cần chủ sở hữu đồng ý trước; R6 không "Xin nghiệm thu" tính năng giao diện khi chưa chạy trên thiết bị thật.

**Hai tin duy nhất**, mỗi tin theo 5 mục: *Yêu cầu / Người dùng sẽ thấy / Cách bạn nghiệm thu / Không làm / Rủi ro*, cộng "Quyết định của tôi mà bạn chưa yêu cầu" và dòng của cố vấn. Lựa chọn trả lời là câu đầy đủ, kèm hệ quả. Tối đa 6 dòng cho báo cáo.

## 5. Động từ chỉ chủ sở hữu được gõ
`plan approve`, `plan accept`, `plan enforce on|off` / `hook mode`, `verdict record --by owner`, `plan unknown close --by owner` (và `plan poc record --by owner`). Phiên AI bị từ chối (biến `CLAUDE_CODE_CHILD_SESSION`; từ 2.5.0.dev25 cả tiến trình do bộ kiểm hay lệnh tiền điều kiện của OneCrew khởi chạy, `ONECREW_VERIFIER`, trên sổ ngoài thư mục tạm, và tiến trình khai `ONECREW_ACTOR` không phải `user|owner`; vẫn là lớp mềm, xem `LOI-DA-BIET.vi.md`) và `permissions.deny` cùng hook cũng chặn chữ của các lệnh này: đúng bất biến 5–6 — người viết hợp đồng không tự duyệt, AI không tự nghiệm thu. Chủ sở hữu gõ trong terminal của chính mình; mẫu có sẵn ở `scripts/owner/`: `approve.ps1`, `enforce.ps1` (hook mode), `accept.ps1`, `record.ps1` (tham số: `-Plan -Reference [-ArtifactSha] [-StateRoot] [-Python]`; `--by owner` luôn cố định). Cổng `plan enforce on|off` của cả state-root gõ tay.

## 6. Giới hạn đã biết và 11b
Danh sách đầy đủ ở [CHANGELOG.md](CHANGELOG.md) và `v2-parking-lot.vi.md`. **11b (việc kế tiếp):** sự kiện `verdict.run_started` cho hook Stop; kho quy tắc hai tầng (lõi theo chuẩn, theo từng project); waiver; contingency; ma trận thẩm quyền A/B/C với đường nhanh cho việc XS chỉ đọc; cố vấn theo loại quyết định; thiết kế phải được duyệt trước khi viết code.

## 7. Đổi tài khoản / đổi máy: chép gì
- **State-root** `D:\OneCrewRuns\state-v2-real` nguyên thư mục (sổ cái, hợp đồng, quy tắc, biên lai) — mất nó là mất toàn bộ lịch sử và plan đã duyệt.
- **Repo** (nhánh `claude/v2-ai-work-contract-5af485`, đã có tag v2.1.0 trên máy cũ) và `outputs\onecrew-as-qc\` (đặc biệt `v2-real\*.ps1`, `memory-backup-20261020`).
- **Bộ nhớ Claude**: khôi phục từ `outputs\onecrew-as-qc\memory-backup-20261020` vào thư mục memory của project trong `~\.claude\projects\`.
- Máy mới: tạo lại venv, chạy `claude login`, chạy `hook install --print` với đường dẫn mới và dán vào `.claude/settings.json`; đường dẫn máy cũ nằm trong plan đã duyệt/`active-plan.json` (trường `project`, `state_root`), nên đổi đường dẫn nghĩa là chủ sở hữu duyệt lại plan đang mở.
- Phiên mới của Claude: đọc `CLAUDE.md` ở gốc repo, rồi `plan digest`.
