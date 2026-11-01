# Báo lỗi một lần với `onecrew support` (2.4-S1)

Bản `2.4.0.dev1` (alpha, chưa nghiệm thu). Mục tiêu: bạn báo lỗi **một lần**, nhận **một mã phản hồi** `FB-…`, và có một **hồ sơ chẩn đoán nằm trên máy bạn**. Bạn không phải tự đi tìm log, mã task hay phiên bản.

## 1. Báo lỗi

```
onecrew support report --text "Bước kiểm M1 báo sai dù file đúng" --expected "M1 đạt" --plan P1
```

- Lệnh in ra mã `FB-…`. Thêm `--json` để nhận kết quả dạng máy đọc.
- Các tùy chọn khác: `--task TASK-…`, `--attempt ATT-…`, `--image anh.png`, `--key K`.
- Gửi lại cùng `--key` thì không tạo bản ghi mới, mà trả về đúng mã cũ. Cùng `--key` nhưng nội dung khác thì lệnh từ chối.
- Không có `--key`: cùng nội dung (chữ mô tả và kết quả mong đợi, không phân biệt hoa thường và khoảng trắng, cùng `--plan/--task/--attempt`) trong một project được coi là **cùng một báo cáo** và nhận lại đúng mã cũ, kể cả khi lần trước nằm trong spool. Nội dung khác là báo cáo mới.
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

1. **Chủ dự án khai báo đích cài** (lệnh của chủ, bị từ chối trong phiên AI):
   ```
   onecrew support target add --id lab --venv D:\venvs\onecrew [--python C:\...\python.exe]
   ```
2. **Nối plan sửa:** `onecrew support link FB-… --plan FIX1 --project-id <id project OneCrew>`. Quyền cài chỉ có khi hợp đồng đã duyệt của plan sửa ghi `authority.granted_actions: ["support_install:lab"]`. Quyền sửa project, một báo cáo, một dòng log hay một mã hash viết trong chữ đều không cho quyền cài.
3. **Gắn bản vá:** `onecrew support artifact FB-… --wheel <file.whl> --manifest <manifest.json>`. OneCrew kiểm:
   - sha256 tính từ byte của wheel phải khớp sha trong manifest;
   - version trong wheel phải khớp version của manifest;
   - `code_commit` của manifest phải có cây git đúng là cây OneCrew đã kiểm cho plan sửa. Bản ghi được ràng là `plan.accepted.artifact_sha` nếu plan đã nghiệm thu; nếu chưa, là `milestone.passed.artifact_sha` của **mọi** milestone thuộc revision đã duyệt.

   Giới hạn: wheel không được build lại từ commit đó, nên OneCrew chỉ ràng được manifest → commit → cây đã kiểm.
4. **Cài:** `onecrew support install FB-… --target lab`.
   - Venv **mới** nằm cạnh venv cũ (`<venv>-<version>`). Venv cũ không bị sửa. Lệnh cài là `pip install --no-index --no-deps`, sau đó OneCrew đọc version và sha RECORD từ chính venv mới.
   - Diễn tập trên **bản sao** của mọi state root dùng chung bản cài: runtime mới chạy `compat scan` và `plan show` mọi root của project. Hai trường hợp bị từ chối: scan không phải của bản sao này (ledger sha khác), hoặc scan có `read` block. `continue` block được chấm cho reader baseline của scan (d3120c6), không cho cặp phiên bản đang chuyển, nên chỉ được ghi lại: không cấp phép và không chặn.
   - **Chỉ chuyển tại điểm an toàn**, khi mọi điều sau đều đúng:
     - trong mọi state root dùng chung, không còn attempt `reserved|running|unknown` và không còn action `executing|unknown`;
     - không còn process nào chạy từ venv cũ (trừ chính tiến trình đang cài). Không liệt kê được process thì kết quả là `processes: unknown` và việc chuyển bị từ chối; OneCrew không dừng process nào;
     - dữ liệu không đổi so với lúc diễn tập (fence).

     Chuyển nghĩa là ghi lại dòng hook OneCrew của mọi project dùng venv cũ (như `onecrew init` ghi).
   - Thiếu quyền hoặc hết ngân sách: phần chuẩn bị vẫn làm xong (venv thử dưới `<state-root>\support-work\`, diễn tập, hồ sơ). Kết quả là `blocked_by_authority`, **không phải PASS**. OneCrew không hỏi lại và không tạo câu hỏi.
   - Bị ngắt giữa chừng thì chạy lại đúng lệnh đó. OneCrew tiếp từ bản ghi cuối (khóa = báo cáo + sha wheel + đích); không tạo venv thứ hai và không cài hai lần.
5. **Kiểm lại lỗi gốc:** `onecrew support recheck FB-…`. Runtime mới chạy lại đúng check của node đã báo, qua engine (một `node.verification` thật). Nếu đã chuyển, recheck chạy tại đích; nếu chưa, chạy trên một bản sao có tên và `environment: copy`. Chỉ recheck đạt **tại đích** mới làm cột "đã kiểm tại đích" thành đúng. Test của bản vá xanh không có nghĩa là đã cài, đã hết lỗi hay đã được chấp nhận.
6. **Tiếp tục:** `onecrew support resume FB-…`, chỉ sau khi recheck đạt tại đích.
   - Node không bị giữ: root tự chạy tiếp bằng các bước engine của nó.
   - Node bị giữ: chỉ chạy tiếp qua `engine.resume_held`, tức phải có câu trả lời `continue` của chủ, attempt đã settle, còn ngân sách và không còn finding mở.
   - Root đã kết thúc hoặc đã dừng không bao giờ được mở lại hay gia hạn. Ngân sách không bị đặt lại.
7. **Quay lui:** `onecrew support rollback FB-…`. Chỉ trỏ hook về venv cũ khi runtime cũ đọc được bản sao của dữ liệu hiện tại (compat scan và `plan show` của chính runtime cũ). Đọc không được thì từ chối, giữ nguyên runtime mới và sổ mới.
8. **Bài học:** `onecrew support learn FB-… --text "…"`, chỉ sau recheck đạt tại đích. Bài học ghi trên root của **plan sửa**, kèm receipt của recheck, mức `verified`, nguyên nhân `not_established`. Không có luật nào tự nâng lên.

Một báo cáo mới cùng nội dung với lỗi đã cài hoặc đã kiểm lại được ghi `recurrence_of` trỏ về báo cáo cũ.

**Giới hạn S2:**
- Cổng outbox desktop của venv cũ (`site-packages\.onecrew\desktop`) ở lại với venv cũ. Đặt `ONECREW_DESKTOP_HOME` để hai runtime dùng chung một outbox.
- Việc liệt kê process chỉ có trên Windows (Toolhelp). Trên hệ khác kết quả là `unknown`, nên việc chuyển bị từ chối.
- Một process chạy code của venv cũ bằng python gốc (không qua launcher của venv) không nhận ra được.
- Bản sao diễn tập là bản sao đầy đủ của state root, nên state root lớn thì tốn chỗ.

## 6. Chưa làm

- Không tải hồ sơ lên đâu cả và không tự gửi log ra ngoài.
- Không build lại wheel từ commit (không có build tái lập); không cài ngoài đích đã khai báo; không publish.
- Không đổi pin, quyền hay ngân sách, và không gia hạn root cũ.
- Không tự mở plan sửa lỗi. Việc sửa vẫn đi qua plan có duyệt của project tương ứng.
