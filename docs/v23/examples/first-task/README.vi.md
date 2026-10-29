# Task đầu tiên với wiki (2.3-A1)

Mục tiêu: một node của engine viết `a.txt` theo quy ước ghi trong wiki của project; check `M1` của node kiểm kết quả; receipt của lần chạy cho thấy gói tri thức nào đã được giao cho worker.

Chỉ cần **gói bàn giao** (thư mục có `README.md`, `wheel\`, `verify\`, `examples\`, `docs\`) và, trên Windows, Python 3.10+, Git và Windows PowerShell. File này nằm ở `<gói>\examples\first-task\`; mọi đường dẫn tương đối trong file này tính từ thư mục đó và nằm trong gói (hướng dẫn wiki: [`../../docs/HUONG-DAN-WIKI.vi.md`](../../docs/HUONG-DAN-WIKI.vi.md); luồng của bộ kiểm: [`../../verify/scenario_a1.py`](../../verify/scenario_a1.py); README của gói: [`../../README.md`](../../README.md)).

| File trong thư mục này | Là gì |
|---|---|
| `docs/wiki/rules.md` | trang wiki mẫu: 2 mục có kiểu (`a-value`, `no-two-lines`) và 1 ghi chú chưa có nguồn. Bước 2 thêm nó vào wiki mà `onecrew init` tạo, với `"revision": "HEAD"` thay bằng commit đầy đủ |
| `contract.json` | hợp đồng (plan `P1`): milestone `M1` là check bằng lệnh `a.txt == "right"`. Chứa `PYTHON_EXE`: bước 3 thay bằng Python của venv |
| `nodes.json` | định nghĩa node cho `engine revise`: `C` ghi `a.txt` (pin `claude` / `claude-haiku-5-5`), `I` tích hợp (chỉ đọc) |
| `fake-policy.json` | chính sách của `claude` giả (chỉ phần A) |

## Hai cách chạy — đừng nhầm

- **Phần A — diễn tập với `claude` giả.** Không gọi model, không cần đăng nhập. Chứng minh các lệnh dưới đây đúng và đường đi chạy: wiki → gói giao cho node → worker → receipt → check. `claude` giả luôn ghi đúng giá trị mà mục `a-value` nói, nên **không chứng minh một model thật hiểu wiki**. Kết quả `9/9` của `verify_milestone.py` cũng không phải bằng chứng rằng từng bước trong file này đúng; bằng chứng cho file này là `verify\first_task_drill.py` (cuối file), chạy chính các khối lệnh PowerShell ở đây.
- **Phần B — với model thật.** Cần Claude Code CLI đã đăng nhập subscription (bước 6B). Diễn tập tự động không chạy phần này; các lệnh sau bước 6B giống phần A.

Mỗi lần thử dùng một `$work` mới (phần A và phần B dùng hai thư mục khác nhau, hai cửa sổ PowerShell khác nhau): `engine step` ghi vào sổ, không chạy lại được trên cùng một sổ.

## 1. Chuẩn bị: biến, venv, cài wheel

PowerShell, trong cùng một cửa sổ cho tới hết file. Sửa ba dòng đầu cho máy của bạn.

<!-- drill: prelude id=vars -->
```powershell
$py   = "C:\Users\NUC\AppData\Local\Programs\Python\Python313\python.exe"
$pkg  = "D:\duong-dan\goi-onecrew"
$work = "D:\OneCrewRuns\task dau tien thu"
$ex      = "$pkg\examples\first-task"
$venv    = "$work\venv"
$proj    = "$work\project mau"
$ledger  = "$work\so thu"
$onecrew = "$venv\Scripts\onecrew.exe"
```

<!-- drill: run id=venv -->
```powershell
New-Item -ItemType Directory -Force $work | Out-Null
& $py -m venv $venv
$wheel = (Get-ChildItem "$pkg\wheel\onecrew-*.whl").FullName
& "$venv\Scripts\python.exe" -I -m pip install --no-index --no-build-isolation $wheel
& $onecrew --help
& "$venv\Scripts\python.exe" -I -c "import importlib.metadata as m; print(m.version('onecrew'))"
```

Kỳ vọng: `pip` báo `Successfully installed onecrew-...`, `--help` liệt kê nhóm `wiki`, dòng cuối là số phiên bản của gói.

## 2. Repo thử (bản sao, không phải project thật), `onecrew init` và wiki

Commit đầu có `a.txt` (`core.autocrlf false` để repo thử không phụ thuộc cấu hình xuống dòng của máy bạn). `.gitignore` bỏ qua `.onecrew/` và `.claude/`: hai thư mục máy này mà `init` ghi vào.

<!-- drill: run id=repo -->
```powershell
New-Item -ItemType Directory -Force $proj | Out-Null
git -C $proj init -q
git -C $proj config user.name "task dau tien"
git -C $proj config user.email "task-dau-tien@localhost"
git -C $proj config core.autocrlf false
[IO.File]::WriteAllText("$proj\a.txt", "base`n")
[IO.File]::WriteAllText("$proj\.gitignore", ".onecrew/`n.claude/`n")
git -C $proj add .
git -C $proj commit -q -m "base"
```

`onecrew init` cài project: sổ, quy tắc của chủ sở hữu, `.onecrew\config.json`, hook Claude Code trong `.claude\settings.local.json`, và **wiki**: chưa có thì tạo khung `docs\wiki\` (`README.md` cách viết, `project.md` ngữ cảnh project, `lessons.md` bài học); đã có thì dùng nguyên. Init không ghi đè file nào và không commit. Mã thoát 0 là xong; 1 là xong nhưng chưa thấy Claude CLI đã đăng nhập (phần A không cần nó); 2 là chưa ghi gì (lý do in ra); 3 là xong trừ khung wiki.

<!-- drill: run id=init -->
```powershell
& $onecrew init --project $proj --state-root $ledger --yes; $initCode = $LASTEXITCODE; $global:LASTEXITCODE = 0
"init: $initCode"
Get-ChildItem "$proj\docs\wiki" -Name
```

Kỳ vọng: init in kế hoạch có dòng `create the wiki skeleton in docs/wiki (README.md, project.md, lessons.md)`, rồi `init: 0` (hoặc `1`), rồi ba tên file đó. Wiki mới chưa có mục nào, nên chưa có gì được giao cho worker:

<!-- drill: run id=wiki-empty -->
```powershell
& $onecrew --project $proj --state-root $ledger wiki pages
```

Kỳ vọng: 3 trang, mỗi trang `"entries": []`, và `"problems": []`.

Thêm quy ước của project vào wiki: trang mẫu `rules.md` trích `a.txt` ở một **commit đầy đủ** (40 ký tự), nên `"HEAD"` trong trang được thay bằng commit vừa tạo; để nguyên `HEAD` thì `wiki pages` báo lỗi và mục chỉ là đầu mối.

<!-- drill: run id=wiki-page -->
```powershell
$sha = git -C $proj rev-parse HEAD
$page = [IO.File]::ReadAllText("$ex\docs\wiki\rules.md", [Text.Encoding]::UTF8).Replace('"revision": "HEAD"', '"revision": "' + $sha + '"')
[IO.File]::WriteAllText("$proj\docs\wiki\rules.md", $page, (New-Object Text.UTF8Encoding $false))
git -C $proj add docs
git -C $proj commit -q -m "wiki"
Select-String -Path "$proj\docs\wiki\rules.md" -Pattern '"revision"'
```

Kỳ vọng: hai dòng `"revision": "<40 ký tự hex>"`, không còn `HEAD`.

Xem wiki được đọc thế nào (chỉ đọc):

<!-- drill: run id=wiki-pages -->
```powershell
& $onecrew --project $proj --state-root $ledger wiki pages
```

Kỳ vọng: 3 mục, đều ở `rules.md` (`a-value` `verified`, `no-two-lines` `refuted`, một ghi chú `unverified`); ba trang khung vẫn `"entries": []`; `"problems": []`.

## 3. Hợp đồng (plan P1)

Chép `contract.json` ra `$work` và thay `PYTHON_EXE` bằng Python của venv (check `M1` chạy bằng chính Python đó), kiểm form rồi đăng ký bản 1 của plan (chưa duyệt):

<!-- drill: run id=contract -->
```powershell
$vpy  = "$venv\Scripts\python.exe".Replace('\', '/')
$text = [IO.File]::ReadAllText("$ex\contract.json", [Text.Encoding]::UTF8).Replace('PYTHON_EXE', $vpy)
[IO.File]::WriteAllText("$work\contract.json", $text, (New-Object Text.UTF8Encoding $false))
& $onecrew --project $proj --state-root $ledger plan lint --file "$work\contract.json"
```

<!-- drill: run id=propose -->
```powershell
& $onecrew --project $proj --state-root $ledger plan propose P1 --file "$work\contract.json" --author "first-task-example" --workflow --capability namespaced-storage --capability root-budget --capability internal-plan --capability sequential-engine
```

Vì `init` đã ghi quy tắc của chủ sở hữu (`<sổ>\plans\owner-rules.md`), bước duyệt đòi hợp đồng có `origin` (lời gốc của chủ sở hữu: ai, lúc nào, câu nào) và mỗi item có `source`; hợp đồng mẫu đã có hai trường đó. Kỳ vọng: `lint: clean`; `propose` in plan với `"status": "proposed"`. Hợp đồng cho `claude` quyền sửa `a.txt` (và chạy lệnh check); nó **không** cấp `apply_to_project`: kết quả là ứng viên trong sổ, `a.txt` của project vẫn là `base`.

## 4. Chủ sở hữu duyệt plan

Đọc trang quyết định (chỉ đọc), rồi duyệt:

<!-- drill: run id=present -->
```powershell
& $onecrew --project $proj --state-root $ledger plan present P1
```

Duyệt là việc của **chủ sở hữu**: chạy lệnh dưới đây **trong terminal của chính bạn**. Lệnh bị từ chối trong phiên của một công cụ AI (có biến `CLAUDE_CODE_CHILD_SESSION`), theo thiết kế; AI không duyệt thay. Nếu bạn đang làm theo file này trong một phiên AI, dừng ở đây, chạy khối này ở terminal của bạn (với cùng các biến của bước 1), rồi tiếp tục từ bước 5.

<!-- drill: owner id=approve -->
```powershell
& $onecrew --project $proj --state-root $ledger owner approve P1 --reference "owner approves the first-task example"
```

Kỳ vọng: `"status": "approved"`.

## 5. Định nghĩa node và gói node C sẽ nhận

<!-- drill: run id=revise -->
```powershell
& $onecrew --project $proj --state-root $ledger engine revise P1 --file "$ex\nodes.json"
```

<!-- drill: run id=show-package -->
```powershell
& $onecrew --project $proj --state-root $ledger wiki show --plan P1 --node C --text
```

Kỳ vọng: `a-value` là `[sự thật · bắt buộc]` (`verified; applies`), `no-two-lines` là `[hướng đã loại]`, ghi chú là `[đầu mối]`. Đây là gói xét trên working tree; lúc chạy thật engine xét trên đúng file trong prompt của node.

## 6. Chạy node

### 6A. Diễn tập: đặt `claude` giả lên đầu PATH (chỉ trong cửa sổ này)

`claude` giả là test double (`verify\onecrew_fake_claude.py`), không có model. Dựng wheel của nó, cài vào **venv của lần thử này** (không cài ở chỗ khác), rồi đặt `Scripts` của venv lên đầu `PATH` **của cửa sổ PowerShell này** — đóng cửa sổ là hết, không đụng PATH máy hay cấu hình Claude Code của bạn.

<!-- drill: run id=fake-install -->
```powershell
& $py -I "$pkg\verify\make_fake_claude_wheel.py" "$work\fake"
& "$venv\Scripts\python.exe" -I -m pip install --no-index --no-build-isolation "$work\fake\onecrew_fake_claude-0.1-py3-none-any.whl"
```

<!-- drill: prelude id=fake-env -->
```powershell
$env:PATH = "$venv\Scripts;" + $env:PATH
$env:ONECREW_FAKE_POLICY = "$ex\fake-policy.json"
$env:ONECREW_FAKE_LOG = "$work\fake.jsonl"
```

<!-- drill: run id=fake-check -->
```powershell
(Get-Command claude).Source
claude --version
```

Kỳ vọng: `claude` trỏ vào `...\venv\Scripts\claude.exe` và in `2.1.286 (Claude Code)` (số bản mà adapter đòi; bản giả khai đúng số đó).

**Nếu dòng đầu không phải `claude.exe` trong `venv\Scripts` của bạn thì dừng, đừng chạy 6.1.** Adapter tìm `claude` trên PATH rồi mới tới `%USERPROFILE%\.local\bin\claude.exe`; máy có Claude Code thật mà `claude` giả không đứng đầu PATH thì `engine step` gọi model thật qua subscription của bạn.

### 6B. Với model thật (không nằm trong diễn tập tự động)

Mở **cửa sổ PowerShell mới** (không có `claude` giả trên PATH), làm lại các bước 1–5 với `$work` khác (ví dụ `D:\OneCrewRuns\task dau tien that`), bỏ qua 6A. Adapter (`onecrew\artifact_provider_core.py`) tự kiểm ba điều đầu và chỉ chạy khi cả ba đúng; điều thứ tư là việc của tài khoản. Không có fallback sang API trả phí (biến `ANTHROPIC_*`, `OPENAI_*` bị bỏ khỏi môi trường của worker):

1. Windows, và có lệnh `claude` trên PATH (hoặc `%USERPROFILE%\.local\bin\claude.exe`).
2. `claude --version` in đúng `2.1.286 (Claude Code)`. Bản khác bị adapter từ chối trước khi chạy bất cứ gì: `engine step` in `"state": "held"` với `"reason": "claude: Pinned Windows CLI capability unavailable."` (mã thoát vẫn 0). Gói này không cài hộ Claude Code, bạn cài đúng bản đó theo cách bạn vẫn cài.
3. Đăng nhập **subscription** trong terminal: `claude auth login --claudeai`. `claude auth status --json` phải có `"loggedIn": true` và `"authMethod"` là `claude.ai` hoặc `oauth`. Đăng nhập chỉ ở desktop/trình duyệt thì chưa đủ.
4. Tài khoản dùng được model đã ghim trong `nodes.json`: `claude-haiku-5-5` (adapter không kiểm; đổi `provider`/`model` ở đó là đổi pin, adapter không tự đổi).

Kiểm trước khi chạy (không gọi model):

<!-- drill: real id=real-check -->
```powershell
(Get-Command claude).Source
claude --version
claude auth status --json
```

Lệnh `engine step` ở 6.1 sẽ gọi model 1 lần cho node `C` (và 1 lần nữa cho node `I`) qua subscription. Chưa có số liệu thời gian/độ ổn định của phần B trong diễn tập này; mỗi lần gọi bị cắt ở 180 giây (`execution_cap_seconds` trong `nodes.json`).

### 6.1 Chạy node C, xem receipt, kiểm

<!-- drill: run id=step-c -->
```powershell
$out = (& $onecrew --project $proj --state-root $ledger engine step P1) -join "`n"
$out
$step = $out | ConvertFrom-Json
$receipt = Get-Content -Raw -Encoding UTF8 "$ledger\snapshots\blobs\$($step.receipt)" | ConvertFrom-Json
$receipt.knowledge | Select-Object delivered, chars, omitted_total, problems | Format-List
$receipt.knowledge_use | Select-Object used, violations, leads_used, must_unacknowledged, proves_semantics | Format-List
$package = Get-Content -Raw -Encoding UTF8 "$ledger\snapshots\blobs\$($receipt.knowledge.package)" | ConvertFrom-Json
$package.entries | ForEach-Object { "{0,-30} {1,-9} {2}" -f $_.id, $_.use, $_.applicability.state }
```

Receipt là file trong sổ: `<sổ>\snapshots\blobs\<khóa>` (khóa in ở `receipt`). Đọc kết quả:

- `knowledge.delivered`: các id đã giao; `knowledge.package` là gói đúng như worker nhận (dòng cuối: mỗi mục với cách dùng `fact`/`rejected`/`lead`).
- `knowledge_use`: điều worker **khai** đã dùng/từ chối; `violations` rỗng nghĩa là không khai id nào ngoài gói; `proves_semantics` luôn `false`.
- Đúng hay sai do **check của node** quyết định, không phải lời khai. Phần A kỳ vọng `used: a-value`, `violations` rỗng; `a-value` là `fact`.

<!-- drill: run id=verify-c -->
```powershell
& $onecrew --project $proj --state-root $ledger engine verify P1 C
```

Kỳ vọng: `"result": "pass"` ở cuối và check `M1` `pass` (check chạy `a.txt == "right"` trên ứng viên của node).

Node `I` là node tích hợp (chỉ đọc, không ghi file); chạy nốt để kết thúc kế hoạch node:

<!-- drill: run id=step-i -->
```powershell
& $onecrew --project $proj --state-root $ledger engine step P1
```

<!-- drill: run id=verify-i -->
```powershell
& $onecrew --project $proj --state-root $ledger engine verify P1 I
```

<!-- drill: run id=state -->
```powershell
& $onecrew --project $proj --state-root $ledger engine state P1 | Select-String '"state"|verification_result'
Get-Content "$proj\a.txt"
```

Kỳ vọng: cả hai node `verified` / `pass`; `a.txt` trong project vẫn `base` (ứng viên nằm trong sổ; `engine handoff` bị từ chối vì hợp đồng không cấp `apply_to_project`). Ở phần A, `Get-Content "$work\fake.jsonl"` có đúng 2 dòng (node `C` với `"how": "fact"`, node `I` với `"how": "report"`).

## 7. Khi gặp lỗi

| Dấu hiệu | Nguyên nhân thường gặp |
|---|---|
| `wiki pages` có `problems` về revision | chưa thay `HEAD` bằng commit đầy đủ (bước 2) hoặc commit trước khi thay |
| `init` in `Nothing was changed` và mã 2 | `.onecrew\config.json` không đọc được, hoặc `wiki.paths` trỏ thư mục không dùng được (link, file, ngoài repo): sửa theo dòng init in ra |
| `owner approve refused: ... AI tool session` | chạy trong phiên AI; chạy ở terminal của chủ sở hữu |
| `engine step` in `"state": "held"` và `"reason": "claude: ..."` (mã thoát 0) | `claude` không phải bản `2.1.286` hoặc chưa đăng nhập subscription: điều kiện 2–3 của 6B |
| `engine step` báo node bị giữ vì tri thức bắt buộc | mục `must` quá trần gói; xem `docs\HUONG-DAN-WIKI.vi.md` §3 |
| `plan propose` báo plan `P1` đã tồn tại | sổ cũ đã có `P1` (làm lại trên cùng `$work`): dùng `$work` mới cho mỗi lần thử |

## Diễn tập tự động (phần A)

`verify\first_task_drill.py` lấy các khối lệnh PowerShell trong chính file này, chạy chúng trên một thư mục tạm (đường dẫn có dấu cách, venv mới, TEMP/APPDATA riêng, `claude` giả) và ghi từng lệnh, mã thoát và đầu ra chính vào một file JSON. Bước 4 (`owner approve`) trong phiên AI được thay bằng duyệt fixture trên sổ tạm và ghi rõ là bước thay; chạy ở terminal của chủ sở hữu thì lệnh trong file này chạy nguyên văn. Hướng dẫn: [`../../README.md`](../../README.md) (mục task đầu tiên).

<!-- drill: show id=drill-cmd -->
```powershell
& $py -I "$pkg\verify\first_task_drill.py" $pkg "D:\OneCrewRuns\task dau tien drill"
```

Sau đó đọc `first-task-drill-log.json` trong thư mục đó (`result` phải là `pass`). Diễn tập chỉ chứng minh phần A.
