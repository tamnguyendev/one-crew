# Báo lỗi một lần với `onecrew support` (2.4-S1)

Bản `2.4.0.dev1` (alpha, chưa nghiệm thu). Mục tiêu: bạn báo lỗi **một lần**, nhận **một mã phản hồi** `FB-…`, và có một **hồ sơ chẩn đoán nằm trên máy bạn**. Bạn không phải tự đi tìm log, mã task hay phiên bản.

## 1. Báo lỗi

```
onecrew support report --text "Bước kiểm M1 báo sai dù file đúng" --expected "M1 đạt" --plan P1
```

- Lệnh in ra mã `FB-…`. Thêm `--json` để nhận kết quả dạng máy đọc.
- Các tùy chọn khác: `--task TASK-…`, `--attempt ATT-…`, `--image anh.png`, `--key K`.
- Gửi lại cùng `--key` thì không tạo bản ghi mới, mà trả về đúng mã cũ. Cùng `--key` nhưng nội dung khác thì lệnh từ chối.
- Không có `--key`: cùng một lần gửi (chữ mô tả và kết quả mong đợi, không phân biệt hoa thường và khoảng trắng, cùng `--plan/--task/--attempt`, cùng phiên bản OneCrew đang chạy, cùng ảnh) trong một project nhận lại đúng mã cũ. Khác một trong các thứ đó là báo cáo mới: phiên bản khác thì báo cáo mới ghi `same_text_other_runtime`; cùng nội dung sau khi bản vá đã kiểm đạt tại đích thì là báo cáo mới ghi `recurrence_of` (tái phát), không bao giờ gộp. Báo cáo nằm trong spool giữ mã spool của nó làm khóa, nên một file spool cài cắm không chiếm được khóa của báo cáo thật; hai báo cáo giống nhau chỉ được gợi ý `possible_duplicates`.
- `--task` chỉ nhận root của plan hoặc task con của nó; task "support" và task khác bị ghi vào `refs_unresolved`, không gắn.
- Không có task, hoặc root đã đóng, vẫn báo được. Báo cáo được ghi trên một task "support" riêng của project. Root đã đóng không bị ghi thêm gì.

**OneCrew tự gắn những gì đã chứng minh được:**
- plan → revision và trạng thái lúc báo;
- attempt → task con, root và node;
- node đang bị giữ hoặc hỏng, khi plan có đúng một node như vậy;
- phiên bản bản cài và sha256 của RECORD (không lấy được thì ghi `unknown`, kèm lý do);
- hash code đang chạy, đường dẫn interpreter, và đang chạy checkout hay bản cài.

`refs_source` ghi rõ từng mục là bạn khai (`user`) hay OneCrew suy ra (`derived:…`). Những gì không gắn được nằm trong `refs_unresolved`, ví dụ attempt của một project khác.

**Một báo cáo không phải là lỗi đã tái hiện.** Báo cáo không ghi kết quả kiểm, finding, receipt hay attempt nào. Trạng thái của nó là `reported`, cột tái hiện là `unknown`.

Các lỗi giống nhau chỉ được *gợi ý* là có thể trùng (`possible_duplicates`), không bao giờ bị gộp. Nếu khác phiên bản hoặc khác plan/node, OneCrew không gợi ý trùng.

## 2. Xem, phân loại, liên kết

- `onecrew support show FB-… [--json]`: báo cáo, phân loại, liên kết, hồ sơ và trạng thái.
- `onecrew support status FB-… [--json]`: các cột tách riêng, mỗi cột kèm bằng chứng: đã nhận, đã tái hiện, đang xử lý, có cách tránh, có bản thử, đã cài, đã kiểm tại đích, còn bị chặn, bạn đã xác nhận. Ở S1, các cột bản thử, đã cài và đã kiểm tại đích luôn là `false`; S2 sẽ ghi các cột này.
- `onecrew support classify FB-… --class task_result|environment|provider|onecrew_runtime|new_requirement|unclear --basis <bằng chứng>…`: lần phân loại sau thay lần trước, lịch sử vẫn được giữ.
- `onecrew support link FB-…` với một trong các dạng sau:
  - `--plan P [--project-id ID]`: nối với một plan.
  - `--finding RF1 [--plan P]`: chỉ nối được khi finding có receipt thật. Khi đó cột "đã tái hiện" thành `yes`.
  - `--request REQ-…`: nối với một câu hỏi.
- Lỗi thuộc runtime OneCrew (`onecrew_runtime`) chỉ được nối với plan của project OneCrew, có duyệt và ngân sách riêng. Nó không bao giờ được nối với plan, finding hay ngân sách của project đang báo lỗi.
- Chữ trong báo cáo hay trong log chỉ là dữ liệu. Không có đường code nào biến chữ đó thành quyền, pin hay câu trả lời.
- `onecrew support confirm FB-… --reference "…"` là tín hiệu riêng của chủ dự án: "với tôi, lỗi đã hết". Lệnh bị từ chối khi chạy trong phiên AI, và `onecrew init` ghi thêm luật chặn `support confirm` cho Claude Code (project đã init trước đó: `doctor` báo hook khác bản hiện hành cho tới khi chạy lại `init`). Xác nhận này không có nghĩa là OneCrew đã kiểm tại đích.
- `--by owner` (hay `user`) của `classify`/`link` bị từ chối trong phiên AI (`CLAUDE_CODE_CHILD_SESSION` hoặc `CLAUDECODE`).
- "Đang xử lý" chỉ đúng khi plan được nối đã được duyệt và còn mở; plan mới đề xuất, đã dừng, đã nghiệm thu hay đã đóng hiện trong `linked` với trạng thái thật.

Thông báo (`notifications pull`, cửa sổ desktop) chỉ phát khi trạng thái thật sự đổi: phân loại mới, đang xử lý, đã tái hiện, đã xác nhận. Việc nhận lại thông báo, khởi động lại, ACK hay đóng cửa sổ không trả lời câu hỏi nào, không nghiệm thu gì, và không làm mất thông báo mới hơn.

## 3. Hồ sơ chẩn đoán

```
onecrew support bundle FB-… --out D:\chia-se
```

Hồ sơ chỉ lấy những nguồn suy ra từ refs của báo cáo:
- probe runtime;
- tối đa 200 sự kiện mới nhất của root và các task con, cùng các dòng attempts/requests của chúng;
- phần cuối, tối đa 256 KB, của `attempts/<id>/stdout|stderr.txt`;
- các receipt mà những sự kiện đó nhắc tới;
- 200 dòng cuối của `.onecrew/violations.jsonl` thuộc plan;
- kết quả `doctor`, trừ bước gọi Claude CLI.

`manifest.json` ghi từng nguồn với trạng thái `included`, `missing`, `truncated`, `withheld`, `unreadable`, `not_applicable` hoặc `unknown`, kèm số byte và sha256 của bản gốc. Log của runner/host v1 có trạng thái `not_applicable`, vì thành phần đó không có trong bản cài.

Từng dòng được lọc bằng mẫu: phần bí mật được thay bằng `[withheld]`, phần còn lại của dòng giữ nguyên. Mẫu gồm header `Authorization`/`Cookie`/`X-Api-Key`, giá trị `Bearer`/`Basic`, user-info trong URL (có hay không có mật khẩu), phép gán có tên kiểu `*SECRET*`, `*TOKEN*`, `*PASSWORD*`, `*API_KEY*`, `sig=` (kể cả `export X=`, `$env:X =`, query string), giá trị của `--password`/`--token`, dạng khóa AWS/GCP/GitHub/Slack/OpenAI/Anthropic và JWT, và cả khối PEM private key. Báo cáo (`feedback.json`) cũng được lọc như vậy. Số dòng bị che nằm ở `lines_withheld` trong manifest. **Bộ lọc theo mẫu không phải là bảo đảm**, nên hãy đọc file trước khi gửi cho ai.

Ảnh không bao giờ được chép vào hồ sơ; chỉ có sha256 của ảnh. Thư mục `--out` không được nằm trong state root, không được là link, và không được chứa `..`. Hồ sơ lớn hơn 8 MB thì OneCrew bỏ cả nguồn, nguồn cũ nhất trước (sự kiện, attempts, requests, log, receipt, hook đều tính), và đánh dấu nguồn đó `truncated` kèm lý do. Chỉ bốn file nhỏ (runtime, báo cáo, bản ghi support của chính báo cáo này, doctor) không bao giờ bị bỏ; nếu chỉ chúng thôi đã vượt giới hạn thì manifest ghi `over_cap: true`. Hồ sơ chỉ chứa bản ghi support của chính báo cáo này, không chứa báo cáo khác.

OneCrew không đọc toàn bộ source, sổ, biến môi trường hay hội thoại. Hồ sơ không chạy chương trình nào, không gọi model và không gửi gì lên mạng.

## 4. Khi runtime hoặc sổ bị hỏng

Nếu sổ `ledger.sqlite3` không đọc được, hoặc `onecrew` không import được module của chính nó, báo cáo được ghi vào spool. Lệnh in `spooled: true` và đường dẫn thật của file. OneCrew thử các chỗ theo thứ tự:
1. `<state-root>\support-spool\`
2. `<project>\.onecrew\support-spool\`
3. `%TEMP%\onecrew-support-spool\`

Nếu không chỗ nào ghi được, lệnh trả mã khác 0, in **NOT recorded** và liệt kê mọi chỗ đã thử cùng lỗi của từng chỗ (ví dụ đĩa đầy).

Khi chính file `onecrew.exe` hỏng, chạy:

```
python -I -m onecrew.v2.support_spool --project <project> report --text "…"
```

Sửa xong sổ thì chạy `onecrew support import-spool`. Mỗi file spool được nhập đúng một lần, với chính mã `FB-…` đã in lúc báo, rồi được chuyển vào `imported\`. Phiên bản lúc báo được giữ (`runtime_at_report`), phiên bản lúc nhập ghi riêng (`runtime_at_import`). File hỏng hoặc trường quá cỡ bị chuyển vào `rejected\` kèm file `.reason.txt`; các file khác vẫn được nhập. File spool là dữ liệu không xác thực (ai ghi được thư mục spool thì ghi được file), nên chỉ những trường có giới hạn mới được nhập. Báo cáo spool từ thư mục con của repo vẫn được tìm thấy khi nhập từ gốc repo. Spool chỉ là chỗ ghi dự phòng, không phải nơi giữ trạng thái thứ hai.

Lý do spool nêu đúng loại lỗi: `DatabaseError` (sổ không đọc được), `LedgerError`, `OSError` (đĩa, quyền, đường dẫn), `ImportError` (runtime không import được) hoặc `RuntimeError` (lỗi code; báo cáo vẫn được giữ).

## 5. Bản vá OneCrew (2.4-S2): sửa, cài tại đích, kiểm lại lỗi gốc, tiếp tục

Dùng khi lỗi được phân loại `onecrew_runtime`. Việc sửa nằm trong một plan của project OneCrew, có duyệt và ngân sách riêng. Plan và ngân sách của project báo lỗi không bao giờ được dùng cho việc này.

1. **Chủ dự án khai báo đích cài** (lệnh của chủ, bị từ chối khi có `CLAUDE_CODE_CHILD_SESSION` hoặc `CLAUDECODE`):
   ```
   onecrew support target add --id lab --venv D:\venvs\onecrew [--python C:\...\python.exe] [--consumers <project> ...]
   ```
   Mã đích không đổi được: khai báo lại bị từ chối, trừ khi chủ dùng `--replace` (bản khai trước được ghi lại). `--consumers` nêu các project dùng venv này ngoài sổ đăng ký hook; chúng cũng được kiểm.
2. **Nối plan sửa:** `onecrew support link FB-… --plan FIX1 --project-id <id project OneCrew>`. Quyền cài (và quyền quay lui) chỉ có khi hợp đồng đã duyệt của plan sửa ghi `authority.granted_actions: ["support_install:lab"]` và plan còn ngân sách. Quyền sửa project, một báo cáo, một dòng log, một manifest hay một mã hash viết trong chữ đều không cho quyền cài.
3. **Gắn bản vá:** `onecrew support artifact FB-… --wheel <file.whl> --manifest <manifest.json>`. Manifest chỉ là bằng chứng, chỉ cho biết commit nào cần kiểm. OneCrew kiểm chính **nội dung** wheel:
   - sha256 tính từ byte của wheel phải khớp sha trong manifest;
   - mọi file wheel mang dưới `onecrew/` phải giống từng byte file đó ở `code_commit` trong repo OneCrew (cho phép dạng CRLF của một checkout Windows), và tập file phải đúng bằng những gì `pyproject.toml` của commit đó khai báo (py-modules, `__init__` của các package, `onecrew/templates/*.md`): không thừa, không thiếu;
   - RECORD liệt kê đúng các file đó với hash đúng; METADATA ghi `onecrew` và đúng version của pyproject ở commit đó;
   - cây git của `code_commit` phải là cây OneCrew đã kiểm cho plan sửa: `plan.accepted.artifact_sha` nếu plan đã nghiệm thu (nhưng plan đã nghiệm thu là đã đóng nên không cài được nữa), nếu chưa thì `milestone.passed.artifact_sha` của **mọi** milestone thuộc revision đã duyệt.

   Giới hạn: bước build không được lặp lại. Điều được chứng minh là "wheel này chứa đúng các file của commit đã kiểm".
4. **Cài:** `onecrew support install FB-… --target lab [--keep]`.
   - Venv **mới** nằm cạnh venv cũ: `<venv>-<version>-<8 ký tự đầu sha wheel>-<8 ký tự sha của state root>`: mỗi sổ (mỗi project có state root riêng) có venv và mốc của riêng nó, nên hai project cài cùng một wheel vào cùng một đích được hai venv (review r3). Venv cũ không bị sửa. OneCrew cài đúng byte wheel đã lưu, bằng `pip install --no-index --no-deps`.
   - Thư mục đó đã có sẵn thì chỉ dùng lại khi đúng là wheel đã gắn. OneCrew đọc **nội dung** từng file của wheel trong `site-packages` của venv và so hash với RECORD của wheel đã kiểm ở bước artifact; RECORD và metadata do venv tự ghi không bao giờ là bằng chứng (review Codex r1 F1). Thêm vào đó: không có link hay junction thay cho file; thư mục gói không có file nào wheel không chứa; không có file `.pth` chạy code khi khởi động (đọc như `site.py`, UTF-8 có BOM; không đọc được cũng bị từ chối).
   - **Mốc lúc tạo (review r2):** OneCrew tự tạo venv. Ngay sau `python -m venv`, `pip install` và lần kiểm đầu tiên đạt (`pyvenv.cfg` có `include-system-site-packages = false` và `home` đúng thư mục của python gốc đã dùng để tạo), OneCrew ghi vào sổ một mốc: sha256 của mọi file trong venv mà wheel không cho, gồm `pyvenv.cfg`, mọi file trong `Scripts\` (`python.exe`, `pythonw.exe`, `onecrew.exe`, launcher của pip) và mọi mục khác của `site-packages` (pip, `__pycache__`, `.pth`…). Mọi lần xét venv đó về sau (dùng lại, lệnh cài thấy đã chuyển rồi, recheck, và ngay trước khi ghi hook) phải khớp đúng mốc này. Venv không có mốc trong sổ này thì không bao giờ được dùng lại và không chương trình nào của nó được chạy, dù có marker hay không: từ chối, không xóa gì. Nếu lần cài trước của chính sổ này dừng giữa chừng (giữa `python -m venv` và lần kiểm đầu tiên), chủ chạy `onecrew support cleanup --venv <thư mục>` (lệnh của chủ, bị từ chối trong phiên AI). Lệnh làm việc trên đúng đường dẫn được đưa, không đi theo link (review r4). Lệnh chỉ xóa khi: thư mục đúng là venv mà lần cài của sổ này tạo (`<venv đích>-<version>-<sha8>-<state root8>` của một đích đã khai và một artifact của sổ này, hoặc `support-work\<key>\trial-venv`), không bao giờ là venv đích đã khai; nó và các thư mục từ nó tới thư mục gốc của nó không phải link hay junction, và nó không trỏ đi nơi khác; marker sổ này đã ghi cho nó (đúng tên file và đúng khóa) còn đó; sổ chưa có mốc của nó; trong cây của nó không có link hay junction; không có process nào chạy từ nó và không có file hook nào trỏ vào nó. Lệnh giữ claim của đích trong lúc xóa (có lượt cài hay quay lui đang chạy thì từ chối), ghi việc xóa vào sổ trước, rồi mới xóa. Trong phiên AI lệnh bị từ chối, cả ở lớp quyền của hook (`support cleanup*--venv`); `support cleanup` không có `--venv` vẫn dùng được. Lần cài sau tạo lại venv.
   - **Không chạy gì của venv trước khi các phép kiểm tĩnh đạt.** Chỉ khi file của wheel, `.pth`, `pyvenv.cfg` và mốc lúc tạo đều khớp, OneCrew mới chạy chương trình của venv: trình thông dịch (`-I -S`) so từng file `.pyc` với bản biên dịch của nguồn, và `onecrew --version` (`PYTHONVERBOSE`) phải đúng version và chỉ nạp onecrew từ các file đó, ngoài ra chỉ thư viện chuẩn.
   - **Ranh giới tin cậy:** python gốc ghi trong đích (`--python`, nếu không thì `home` trong `pyvenv.cfg` của venv đích, đọc như `site.py`) và thư viện chuẩn của nó được tin. `pyvenv.cfg` của đích không đọc được hay không có `home` thì lệnh từ chối, không dùng python đang chạy OneCrew; khai báo lại đích với `--python`. Mỗi lần xét venv, `home` của nó được so lại với python gốc đó. Mọi thứ trong venv được kiểm, hoặc với wheel đã kiểm, hoặc với mốc lúc tạo. Một chương trình nói dối về những gì nó nạp (`PYTHONVERBOSE`) không bị bắt; vì thế mới có mốc của `Scripts\`.
   - Chỉ một lần cài, quay lui hay chuyển cho mỗi đích tại một thời điểm (một claim ghi trong sổ, hạn 15 phút). Lần thứ hai bị từ chối "in progress". Claim được gia hạn trước mỗi bước (diễn tập, điểm an toàn, ghi hook); nếu claim đã mất (hết hạn và một lượt khác đã giành) thì lượt này bị từ chối trước khi ghi hook. Claim được tiếp quản khi đã hết hạn, hoặc khi tiến trình giữ nó (ghi kèm máy và thời điểm tạo tiến trình) không còn chạy trên chính máy này; việc tiếp quản được ghi trong claim mới và trong bản ghi cài hay quay lui (`claim_taken_over_from`). Claim của máy khác, hoặc không ghi tiến trình giữ, được tôn trọng tới khi hết hạn.
   - Diễn tập trên **bản sao** của mọi state root dùng chung bản cài. Bản sao gồm sổ, `plans/` và đúng các blob mà các root đó tham chiếu; số byte được ghi; bản sao bị xóa sau khi diễn tập đạt (trừ khi có `--keep`). Runtime mới chạy `compat scan`, `plan show` mọi root và `engine state`/`engine ready` mọi root engine còn mở. Hai trường hợp bị từ chối: scan không phải của bản sao này, hoặc scan có `read` block. `continue` block được chấm cho reader baseline của scan (d3120c6), nên chỉ được ghi lại.
   - Project dùng chung (consumer): các project trong sổ đăng ký hook, project đang báo lỗi và `--consumers` của đích. Có file settings hay sổ đăng ký không đọc được, hoặc có handler không xác định được chương trình, thì việc chuyển bị từ chối (`consumer unknown`), không bỏ qua. Dịch vụ host, cấu hình MCP hay Codex chạy bản cũ không được liệt kê; bản ghi nói rõ điều này (`not_enumerated`).
   - **Chỉ chuyển tại điểm an toàn**, kiểm ngay trong claim, khi mọi điều sau đều đúng:
     - trong mọi state root dùng chung, không còn attempt `reserved|running|unknown` và không còn action `executing|unknown`;
     - không còn process nào chạy từ venv cũ (trừ chính tiến trình đang cài và cha của nó). Không liệt kê được process thì kết quả là `processes: unknown` và việc chuyển bị từ chối. Danh sách rỗng chỉ có nghĩa là không thấy process nào qua launcher của venv; OneCrew không dừng process nào;
     - dữ liệu không đổi so với lúc diễn tập (fence). Fence của mỗi state root được lấy **trước** khi sao chép (một lần cho mỗi state root, kể cả khi nhiều project dùng chung nó), và bản sao phải chứa đúng dữ liệu đã fence; dữ liệu đổi ở bất kỳ lúc nào giữa fence và điểm an toàn thì bị từ chối, chạy lại lệnh để diễn tập lại.
   - Ngay trước khi ghi file hook đầu tiên, OneCrew kiểm lại: fence vẫn đúng dữ liệu đã diễn tập, venv mới vẫn khớp wheel và mốc lúc tạo, claim vẫn là của lượt này. Một điều sai thì `refused_unsafe`, chưa file nào bị ghi. Một file settings mà trong lúc đó đã chuyển sang một chương trình thứ ba (không phải bản cũ, không phải bản mới) thì không bị ghi đè: lệnh dừng và báo file đó.
   - Trước mỗi lần ghi lại dòng hook của một project, OneCrew ghi một `intent`; sau khi ghi xong là một `switched_one`. OneCrew chụp attempt và action ngay trước lần ghi file hook đầu tiên và ngay sau lần ghi cuối cùng (review r3). Attempt hay action xuất hiện hoặc đổi giữa hai lần chụp đó, process của runtime cũ còn chạy, hoặc claim đã mất thì kết quả là `switch_window_violation`: không dừng gì, coi như vẫn bị chặn. Những gì xuất hiện sau lần chụp thứ hai thuộc runtime mà hook đang chạy: chỉ được đếm (`events_after_repoint`, `attempts_after_repoint`), không phải vi phạm. Bản ghi mang cả fence lúc diễn tập và lúc chuyển (`fences`). Khi chạy lại `support install` sau một vi phạm mà mọi file hook đã chạy runtime mới, lệnh không ghi file nào nên không có bước kiểm ngay trước lần ghi đầu: việc chuyển được gắn với fence ở điểm an toàn (review r4). Bước kiểm ngay trước lần ghi đầu đọc fence và attempt/action trong cùng một lần đọc lúc bắt đầu và lúc kết thúc; có gì đổi giữa hai lần đọc đó thì `refused_unsafe`, chưa ghi gì. Vi phạm không bao giờ là ngõ cụt: trạng thái nói đúng hook đang chạy runtime nào, kèm lý do thật của vi phạm; chủ chạy lại `support install` (diễn tập dữ liệu hiện tại bằng runtime mới và gắn việc chuyển vào đó) hoặc `support rollback` (diễn tập bằng runtime cũ). Recheck bị từ chối cho tới lúc đó. Sau mỗi lần chuyển, trạng thái nhắc khởi động lại các phiên Claude Code đang mở.
   - Bị ngắt giữa chừng thì chạy lại đúng lệnh đó. Đang chuyển dở (`partially_switched`) thì lần chạy lại hoàn tất việc chuyển theo quyết định quyền đã ghi lúc đó, kể cả khi quyền đã đổi sau đó (bản ghi nói rõ). Không tạo venv thứ hai, không cài hai lần.
   - Thiếu quyền hoặc hết ngân sách: phần chuẩn bị vẫn làm xong (venv thử dưới `<state-root>\support-work\`, diễn tập, hồ sơ). Kết quả là `blocked_by_authority`, **không phải PASS**. OneCrew không hỏi lại và không tạo câu hỏi.
5. **Kiểm lại lỗi gốc:** `onecrew support recheck FB-… [--keep]`. Runtime mới chạy lại đúng check của node đã báo, qua engine (một `node.verification` thật). Recheck chạy tại đích chỉ khi các dòng hook **lúc này** đang chạy đúng runtime đã chuyển; nếu không, nó chạy trên một bản sao có tên (`environment: copy`, bản sao bị xóa sau đó trừ khi có `--keep`). Một `intent` được ghi trước: nếu bị ngắt sau khi engine đã chạy, lần chạy lại dùng kết quả đó chứ không chạy lại lần hai.
6. **Trạng thái:** "đã cài" và "đã kiểm tại đích" được tính theo những gì các dòng hook đang chạy **lúc này**. Sau khi quay lui: `installed: false`, `rolled_back: true`; lần kiểm đạt trước đó chỉ còn là lịch sử (`at_runtime`, `current: false`), và cột "còn bị chặn" thành đúng.
7. **Tiếp tục:** `onecrew support resume FB-…`, chỉ khi recheck đạt tại đích với đúng runtime đang chạy.
   - Node không bị giữ: root tự chạy tiếp bằng các bước engine của nó.
   - Node bị giữ: chỉ chạy tiếp qua `engine.resume_held`, tức phải có câu trả lời `continue` của chủ (OneCrew không bao giờ trả lời thay), attempt đã settle, còn ngân sách và không còn finding mở.
   - Root đã kết thúc hoặc đã dừng không bao giờ được mở lại hay gia hạn. Ngân sách không bị đặt lại.
8. **Quay lui:** `onecrew support rollback FB-… [--keep]`. Đây là lệnh của chủ (bị từ chối trong phiên AI), và cần đúng quyền `support_install:<đích>` của plan sửa. OneCrew chỉ trỏ hook về venv cũ khi chính runtime cũ, trên bản sao của dữ liệu hiện tại:
   - đọc được mọi root (`compat scan` không có `read` block, `plan show`);
   - chạy được `engine state` và `engine ready` cho mọi root engine còn mở;
   - biết mọi loại sự kiện đã được ghi từ lúc chuyển (đọc từ chính bản sao đó).

   Quyết định quay lui gắn với đúng dữ liệu đã diễn tập (review Codex r1 F2): fence được lấy trước khi sao chép, bản sao phải đúng dữ liệu đã fence, fence được so lại tại điểm an toàn và sau khi trỏ hook. Dữ liệu đổi trước điểm an toàn thì `refused` (runtime mới, sổ, quyền, ngân sách giữ nguyên); đổi sau điểm an toàn thì `switch_window_violation` (hook đã về runtime cũ, không dừng gì; chạy lại `support rollback` để diễn tập dữ liệu hiện tại và gắn vào đó, hoặc `support install` để chuyển lại sang runtime mới). Không bao giờ trả `rolled_back` cho dữ liệu chưa được diễn tập; bản ghi `rolled_back` mang `fences` (lúc diễn tập và lúc chuyển, bằng nhau).

   Bản ghi nói đúng điều đã chứng minh: "đọc và tính được trạng thái bằng runtime cũ; việc chạy tiếp đến cuối chưa được chứng minh". Không đạt thì từ chối, giữ nguyên runtime mới và sổ mới.
9. **Bài học:** `onecrew support learn FB-… --text "…"`, chỉ sau recheck đạt tại đích với runtime đang chạy, một bài học cho mỗi báo cáo. Bài học ghi trên root của **plan sửa**, kèm receipt của recheck, mức `verified`, nguyên nhân `not_established`. Không có luật nào tự nâng lên.
10. **Dọn:** `onecrew support cleanup` xóa các bản sao diễn tập, quay lui và recheck đã xong dưới `support-work` (giữ venv, wheel và bản ghi). Đây là cơ chế giữ/xóa duy nhất của S2; bị từ chối khi đang có claim.

Thông báo của bản vá (đã cài, quay lui, kiểm đạt, còn bị chặn) mang số vòng cài, nên cài lại sau một lần quay lui vẫn có thông báo mới.

**Giới hạn S2:**
- Cổng outbox desktop của venv cũ (`site-packages\.onecrew\desktop`) ở lại với venv cũ. Đặt `ONECREW_DESKTOP_HOME` để hai runtime dùng chung một outbox.
- Việc liệt kê process chỉ có trên Windows (Toolhelp). Trên hệ khác kết quả là `unknown`, nên việc chuyển bị từ chối. Một process chạy code của venv cũ bằng python gốc (không qua launcher của venv) không nhận ra được.
- Claim chỉ loại trừ nhau trong cùng một state root. Claim của tiến trình khác còn chạy, của máy khác, hoặc không ghi tiến trình giữ, được tôn trọng cho tới khi hết hạn (15 phút); claim của tiến trình đã dừng trên chính máy này được tiếp quản ngay.
- Khi một bản vá thứ hai cho cùng đích được cài sau lần chuyển trước, các hook đang chạy bản trước chứ không chạy venv của đích, nên OneCrew không thấy project nào dùng đích: cần quay lui trước, hoặc khai báo lại đích (`--replace`).
- Lệnh ghi lại dòng hook dùng mẫu settings của runtime đang chạy lệnh cài, không phải của runtime mới.

## 6. Chưa làm

- Không tải hồ sơ lên đâu cả và không tự gửi log ra ngoài.
- Không build lại wheel từ commit (không có build tái lập); không cài ngoài đích đã khai báo; không publish.
- Không đổi pin, quyền hay ngân sách, và không gia hạn root cũ.
- Không tự mở plan sửa lỗi. Việc sửa vẫn đi qua plan có duyệt của project tương ứng.
