# Verifier khai `inputs`: hotfix cho repo lớn

**Từ `2.5.0.dev24`, `inputs` có trong dòng 2.5** (gộp từ mep7). Bản thử, chưa nghiệm thu. Các mục «Thêm từ mep…» dưới đây là lịch sử của dòng hotfix. Mục «Trên 2.5» ngay sau đây là cái đang áp.

## Trên 2.5 (từ 2.5.0.dev24)
- **Bản chép là đúng byte git lưu** (quyết định của chủ, 09/11): không áp kiểu xuống dòng, filter hay `.gitattributes`. Symlink là tệp thường. Giờ sửa tệp cố định 01/01/2000. Cần git 2.40 trở lên. Mục «Checkout không giống cây làm việc» bên dưới vì vậy **đã đổi**: EOL không còn lệch, mtime không còn theo lúc chép.
- **Mọi mốc kiểm bằng lệnh đều ghi chương trình nó đã chạy**, có hay không có `inputs` (review dev24c; chủ 11/11: "Sửa cả lỗi cũ"). Pass cũ chỉ được dùng tiếp khi chương trình, gói Python và `env_inputs` của nó **vẫn y như lúc chạy**. Quy tắc này áp ở: `plan show` và trang theo dõi, nghiệm thu, dùng lại bằng chứng, và với plan workflow ở mọi chỗ quyết định một phần việc (node) "đã kiểm": node phụ thuộc có được bắt đầu không, nghiệm thu nội bộ node, handoff, và "sẵn sàng nghiệm thu" của root (review dev24d). Node đã kiểm mà chương trình đổi thì thành "cần kiểm lại" (`engine verify`). Bộ kiểm bằng mô hình (reviewer) **không** thuộc quy tắc này.
- **Chương trình được ghi hai đường:**
  - đường dùng để khởi động (`invoked`), giữ nguyên, không giải liên kết;
  - tệp thật sự chạy (`path`): giải hết symlink tệp và thư mục, junction, hay alias Windows. Kèm sha256 của tệp đó.
  - Lúc kiểm lại, OneCrew tìm lại đường khởi động (tên trần thì tìm trên PATH, đường tuyệt đối thì giữ nguyên), giải lại liên kết, rồi so cả hai đường và byte. Một liên kết nay trỏ sang bản khác (ví dụ `python` → `python-3.12` trong khi `python-3.11` vẫn còn) là "đổi".
- **Tên trần như `python`:**
  - được tìm MỘT lần trên PATH của bộ kiểm, chỉ trên PATH đó, không bao giờ trong thư mục hiện tại của OneCrew;
  - tiến trình được khởi động từ đúng tệp tìm thấy, nhưng vẫn thấy `argv[0]` như hợp đồng viết (ví dụ `python`). Riêng tệp `.bat`/`.cmd` trên Windows được khởi động bằng đường tuyệt đối của nó.
  - PATH của bộ kiểm là PATH của máy, **bỏ** mọi thư mục nằm trong repository chứa project (so theo từng thành phần đường, không theo tiền tố chữ: `C:\repo-tools` vẫn giữ khi repo là `C:\repo`) và trong thư mục tạm. Vì vậy **một `.venv` nằm trong repo không được dùng**, kể cả khi shell đã kích hoạt nó, và kể cả khi mốc chạy trong một thư mục con. Muốn dùng venv: ghi đường tuyệt đối tới python của venv trong `argv`, hoặc để venv ngoài repo.
- **Chương trình không có thật** (tên trần không có trên PATH đó, đường tuyệt đối đã mất, hay đường tương đối có thư mục như `tools/check` mà bản chép không có) thì lượt kiểm bị từ chối trước khi lệnh chạy ("chưa chạy", không giữ run, không tính là một lần kiểm), với mọi mốc. Trước đây mốc không có `inputs` nhận một receipt "không kết luận được".
- **Gói Python** (review dev24, P1; chủ 10/11: "Sửa ngay"):
  - Khi chương trình là trình thông dịch Python (tên đường khởi động hay tên tệp chạy bắt đầu bằng `python`), OneCrew đọc thêm từ đĩa, không chạy gì: mọi `*.dist-info` / `*.egg-info` trong site-packages (tên kèm phiên bản và sha256 của `RECORD`), mọi tệp `.pth`, và `pyvenv.cfg`.
  - Site-packages được tìm **như Python tìm:** có `pyvenv.cfg` cạnh đường khởi động thì đó là venv, dùng site-packages của venv, kể cả khi `bin/python` của venv là symlink tới Python hệ thống (venv trên Linux/macOS). Không có thì tìm theo tệp thật sự chạy. Venv có `include-system-site-packages = true` thì site-packages của bản cài gốc cũng tính.
  - Cài thêm, gỡ hay nâng một gói là "đổi": pass cũ không được dùng, chạy lại mốc.
- **`env_inputs`:** tệp hay thư mục ngoài repo mà lệnh dựa vào (plugin, thư mục công cụ, cấu hình).
  - Khai trong hợp đồng, ví dụ `"env_inputs": ["C:/tools/plugin", "C:/tools/rules.txt"]`: từ 1 đến 20 đường tuyệt đối. Từ vòng này dùng được **cả khi không có `inputs`**.
  - Byte của chúng được băm vào receipt. Đổi, thêm, mất một tệp, hay thêm hoặc bớt một thư mục con là "đổi". Đổi `env_inputs` là thay đổi nghiệm thu, như `inputs`.
  - **Phải ở ngoài repository chứa project** sau khi giải đường thật (`..`, hoa/thường trên Windows, junction, symlink). Đường nằm trong repo, hay thư mục chứa cả repo, bị từ chối lúc `plan propose`/`plan amend` và lúc chạy, theo cùng một cách. Tệp của repo thì khai vào `inputs`. Hai tên cùng trỏ một chỗ cũng bị từ chối, cả lúc `propose`/`amend`.
  - **Thiếu hay không đọc được:** lượt kiểm bị từ chối trước khi lệnh chạy ("chưa chạy", không giữ run). Lúc `plan show` hay nghiệm thu, đường thiếu làm pass "cần kiểm lại", nghiệm thu bị chặn.
  - **Liên kết bên trong một thư mục `env_inputs`** (symlink, junction): OneCrew ghi nó trỏ đi đâu, nhưng không đọc thứ nó trỏ tới. Xem `LOI-DA-BIET.vi.md`.
- **Đường có `.` hay `..`** (ví dụ `D:\work\.\repo\out.txt` hay `/home/a/x/../repo/cfg`) được chuẩn hóa trước khi kiểm, cả trên dòng lệnh lẫn trong nội dung các input: đường trỏ vào cây làm việc thật bị từ chối như cách viết thường, kể cả khi tệp chưa có (review dev24d).
- **`inputs_unscanned` không bao giờ miễn được thứ dòng lệnh gọi tới,** dù viết khác (`tool/./check.py`, `tool/x/../check.py`, khác hoa/thường trên Windows), và cả khi dòng lệnh gọi **thư mục chứa nó** (ví dụ `pytest tool` hay `pytest .` thì mọi tệp trong `tool`, hay trong cả repo, đều được quét): hợp đồng từ chối, và lúc chạy các tệp đó vẫn được quét (review dev24e).
- **Dấu vân tay được nhớ** theo đường, kích thước, giờ sửa (tới nano giây) và mã tệp: xem lại plan hay trang theo dõi không đọc lại tệp không đổi. Danh sách thư mục vẫn được đọc lại mỗi lần.
- **Giới hạn băm, đếm ngay trong lúc duyệt** (mỗi tệp, mỗi thư mục, mỗi liên kết là một mục):
  - tối đa 20 000 mục và 512 MB cho cả `env_inputs`;
  - cũng 20 000 mục và 512 MB cho môi trường Python của chương trình, kể cả các thư mục `lib/python3*` được dò;
  - một `RECORD`, `.pth` hay `pyvenv.cfg` tối đa 16 MB.
  - Quá giới hạn thì lượt kiểm bị từ chối trước khi lệnh chạy; lúc `plan show`/nghiệm thu thì pass không được mang sang.
- **Receipt không ghi chương trình,** hay ghi môi trường không đọc được, không được mang sang. Cách chép đổi sang `exact-blob-bytes/3`, nên mọi pass làm trước bản này, trên plan **chưa nghiệm thu**, phải chạy lại một lần (mốc chính sách, `NANG-RUNTIME.vi.md` mục C0). Plan đã nghiệm thu giữ nguyên.
- **Còn chưa phủ:** DLL hay thư viện chương trình tự nạp từ chỗ khác ngoài site-packages và ngoài `env_inputs` (ví dụ thư mục hệ thống, PATH); site-packages riêng từng người dùng của Python cài từ Microsoft Store (gọi qua alias); trình thông dịch không mang tên `python*` (ví dụ `py.exe`). Cần thì khai các thư mục đó vào `env_inputs`. Xem thêm `docs/obs2/su-dung/LOI-DA-BIET.vi.md`.
- **Đổi `inputs` hay `inputs_unscanned` là thay đổi nghiệm thu:** `plan amend` cần chủ duyệt lại.
- **Mốc chính sách:** receipt `inputs` làm trước khi đổi cách chép là "cần kiểm lại", như mọi receipt khác. Xem `docs/obs2/su-dung/NANG-RUNTIME.vi.md`, mục C0.
- **Lỗi trước khi lệnh chạy** (thư mục làm việc, dọn hay tạo thư mục tạm, checkout, scope, hạn chót) đều là "chưa chạy": run không bị giữ, chạy lại được ngay, không cần `verdict release-run`.
- **`inputs` không dùng trên plan workflow** (sequential-engine): handoff của nó xét cả artifact.
- mep2 = mep1 cộng ba điểm ở mục «Thêm từ mep2».
- mep3 = mep2 cộng hai điểm ở mục «Thêm từ mep3».
- mep4 = mep3 cộng mục «Thêm từ mep4»; mep5 cộng mục «Thêm từ mep5»; mep7 cộng mục «Thêm từ mep7» (mep6 chỉ đổi trang theo dõi).

## Vấn đề

Với verifier lệnh, `verdict run` băm toàn bộ cây làm việc, ghi object vào `.git` của project, chép toàn cây ra thư mục tạm, rồi băm lại. Repo nhiều dữ liệu chưa commit tốn thời gian và đĩa, dù lệnh chỉ đọc vài file.

## Cách dùng

Trong hợp đồng, khai đúng những gì lệnh đọc:

```json
{"type": "command", "config": {"argv": ["python", "tool/check.py"], "max_minutes": 15, "inputs": ["tool", "spec/a.txt"]}}
```

- `inputs`: file hoặc thư mục, đường dẫn tương đối từ gốc repo, không wildcard, tối đa 200.
- **Không khai `inputs` thì giữ nguyên đường cũ:** toàn cây, hợp đồng và receipt như trước.
- Thêm `inputs` vào plan đang có là sửa hợp đồng: `plan amend`, rồi chủ duyệt lại.
- `owned` là phạm vi được sửa, không phải input. Lệnh đọc gì thì phải khai cái đó, kể cả cấu hình và dữ liệu.

## Thay đổi khi có `inputs`

| | Đường cũ | Có `inputs` |
|---|---|---|
| Chụp trước và sau | Toàn cây | Chỉ input và các `.gitattributes` phía trên chúng |
| Object ghi vào `.git` | Toàn bộ dữ liệu chưa commit | Chỉ input |
| Checkout | Toàn cây | Chỉ input |
| Bằng chứng còn hiệu lực | Khi cả cây không đổi | Khi input, `.gitattributes` phía trên và file chương trình không đổi |
| Duyệt (khi mọi mốc đều khai) | Duyệt toàn cây, ghi object | Không duyệt toàn cây (vẫn băm file đang theo dõi) |

Receipt có thêm `input_scope`: đường dẫn, số file, số byte, HEAD, và hash chương trình mà lệnh khởi động. Chỉ runtime bản này đọc được plan có `inputs`.

## Khi nào bị từ chối, verifier chưa chạy, chạy lại được ngay

- Input không có, hoặc toàn bộ bị Git ignore.
- Lệnh nêu một đường dẫn có thật trong repo mà không thuộc `inputs`, kể cả `.`.
- Lệnh nêu đường dẫn tuyệt đối vào cây thật.
- Hard link hoặc junction trong input.
- Thư mục làm việc không nằm trong input.
- Root workflow (engine): chưa hỗ trợ `inputs`, vì handoff và test integrity xét toàn artifact.
- Không đủ đĩa cho checkout. Kiểm này áp dụng cho cả đường cũ.

## Thêm từ mep2

- **Đường dẫn tuyệt đối vào cây thật bị từ chối trước khi verifier chạy, không chỉ cảnh báo.** Hai chỗ bị xét:
  - mọi từ của dòng lệnh, kể cả đường dẫn chưa tồn tại và dạng `--ra=<đường dẫn>`;
  - nội dung mọi tệp văn bản trong checkout của inputs.

  Các cách viết được nhận ra:
  - `\` và `/`, cả `\\` trong chuỗi mã nguồn;
  - ổ đĩa viết `C:`, `/c`, `/mnt/c` hoặc `/cygdrive/c`;
  - tên 8.3;
  - không phân biệt hoa thường trên Windows.

  Thư mục anh em cùng tiền tố (`...\mep-cu`) không bị tính là cây thật. Tệp nhị phân (có byte NUL, không có BOM UTF-16) không được quét; receipt ghi số tệp đã quét và số tệp không quét trong `input_scope.live_tree_scan`.
- **Windows: lệnh và mọi tiến trình con nằm trong một job object** (`KILL_ON_JOB_CLOSE`).
  - Lệnh khởi động ở trạng thái treo, được đưa vào job rồi mới chạy.
  - OneCrew chết, kể cả bị giết cứng, thì hệ điều hành kết thúc cả cây.
  - Hết giờ hoặc bị ngắt thì job bị kết thúc.
  - Tiến trình con còn chạy khi lệnh chính đã thoát cũng bị kết thúc.
  - `snapshot.contained` và `snapshot.left_running` của receipt ghi việc này.
  - Áp dụng cho cả đường cũ.
- Bộ test có thêm ca input bị người khác đổi trong lúc lệnh chạy **trên đường `inputs`** (mep1 chỉ thử trên đường cũ): kết quả inconclusive, không phải pass.

## Thêm từ mep3

Cả hai điểm áp dụng cho đường cũ lẫn đường `inputs`.

- **Thư mục tạm của checkout được xoá hết, kể cả tên dài quá 260 ký tự và tệp chỉ đọc.**
  - Trước đây việc xoá bỏ qua lỗi một cách im lặng. Dấu chủ `owner.json` (tên ngắn) bị xoá trước, nên lần chạy sau cũng không dọn.
  - Trong lab, mỗi lượt đường cũ để lại 646 tệp, 65 MB.
  - Phần vẫn không xoá được (ví dụ tệp đang bị mở) được gắn lại dấu chủ, để lần `verdict run` sau dọn khi tiến trình này đã kết thúc.
- **`snapshot.left_running` không còn đếm nhầm.**
  - Lệnh console chạy không cửa sổ để lại tiến trình console host của hệ điều hành trong job vài mili giây sau khi thoát. mep2 vì vậy ghi `1` cho mọi lượt sạch.
  - mep3 chờ tối đa 0,5 s để số này về 0 rồi mới ghi.
  - Tiến trình con thật sự còn chạy vẫn được đếm và bị kết thúc.

## Thêm từ mep4: `inputs_unscanned`

**Vì sao cần.** Trên repo MEP thật, 4 input của bộ kiểm M1 nhắc đường dẫn của chính repo: sổ cycle, register giới hạn, một review, một script phát lại. Bộ kiểm chỉ kiểm các tệp đó có tồn tại, không đọc nội dung, nhưng mep3 vẫn từ chối cả lượt.

```json
{"type": "command", "config": {"argv": ["python", "tool/check.py", "spec/a.md"], "inputs": ["tool", "spec"], "inputs_unscanned": ["spec/so.md"]}}
```

**Quy tắc:**
- Chỉ dùng được khi có `inputs`. Mỗi mục là một input hoặc nằm trong một input; tối đa 200 mục, không trùng.
- **Không được miễn thứ dòng lệnh nêu**, kể cả thư mục chứa nó, tính cả `cwd`: chương trình và đối số luôn được quét. Dòng lệnh cũng luôn được quét.
- **Chủ duyệt từng mục:** mỗi mục nằm trong hợp đồng, nên `owner approve` cũng là chấp nhận việc miễn đó. Thêm hay bớt mục là sửa hợp đồng.
- **Receipt ghi lại:** `input_scope.live_tree_scan` có `unscanned` (số tệp bỏ qua) và `unscanned_paths`.
- Tệp được miễn vẫn là input: đổi nó thì bằng chứng cũ hết hiệu lực.
- Chỉ miễn tệp mà lệnh **không đi theo đường dẫn trong đó**: văn bản, ghi chép, tệp chỉ kiểm tồn tại. Miễn một tệp cấu hình mà lệnh đọc đường dẫn từ đó sẽ mở lại đường đạt giả của mep1.

## Thêm từ mep5: nghiệm thu plan nhiều mốc khai `inputs`

**Vì sao cần.** Một plan bản 4 trên một dự án dùng thử có M1, M2, M3 đều đạt, mỗi mốc khai `inputs` riêng. Hai điều sau gặp nhau:
- `artifact_sha` trong receipt chỉ là cây input của **riêng mốc đó**.
- `owner accept` xét **mọi** mốc trong một cây duy nhất.

Vì vậy, nghiệm thu bằng sha của receipt M3 bị từ chối với lý do «M1: a declared input changed», dù không có gì đổi. `verdict artifact` lúc đó chụp toàn cây, mà trên repo MEP toàn cây cỡ hàng chục GB.

**Thay đổi:**
- `verdict artifact --plan <tên>`: khi **mọi** mốc của bản mới nhất là lệnh có khai `inputs` (repo Git, không phải workflow root), lệnh trả cây của **hợp** các inputs. Hàm dùng để lập cây là `scoped_tree`, cùng hàm `verdict run` dùng. Kết quả có thêm `"scope": "inputs"` và danh sách `inputs`.
  - Chỉ cần một mốc không khai, hoặc không phải mốc lệnh, là lệnh chụp toàn cây như trước.
- Lời từ chối của `owner accept` thêm câu chỉ sang `verdict artifact --plan <tên>` khi plan có mốc khai `inputs`.

**Không đổi:**
- Một input của bất kỳ mốc nào đổi thì `owner accept` vẫn từ chối mốc đó.
- Tệp ngoài mọi input đổi thì cây hợp không đổi.
- Cây hợp vẫn ghi object vào `.git`, nhưng chỉ cho các input.

## Thêm từ mep7: alias Python của Windows, lời từ chối chỉ đường, checkout

**Alias thực thi của Windows** (`%LOCALAPPDATA%\Microsoft\WindowsApps\python.exe`, issue #2):
- Trước mep7, `verdict run` ném `OSError [Errno 22]` khi đọc byte của alias để lấy dấu vân tay chương trình. Run bị giữ «unknown outcome» và phải `verdict release-run` bằng tay.
- Từ mep7, OneCrew đọc đích của alias từ reparse data và băm exe đích.
  - `input_scope.tool.path` là exe đích.
  - `input_scope.tool.alias` là đường alias.
- Chương trình không đọc được thì không còn ném lỗi. Receipt ghi `sha256: null` cùng `unreadable`, và pass của mốc đó không được mang sang bản sau.
- **Mọi lỗi xảy ra trước khi gọi bộ kiểm giờ là kết quả đã biết** (`phase: before_dispatch`): chạy lại được ngay, không cần `release-run`.

**Dùng đường alias, đừng dùng đường đích có số phiên bản** (issue #3):
- Đường đích nằm trong thư mục cài đặt của Store, dạng `…\WindowsApps\<gói Python, có số phiên bản>\python3.13.exe`, và mất khi Store cập nhật. Ghi nó vào hợp đồng thì mỗi lần cập nhật phải amend và duyệt lại.
- Ghi đường alias thì hợp đồng không đổi. Khi Store cập nhật, dấu vân tay đổi, pass cũ báo «the program the command starts changed», và chỉ cần chạy lại mốc.

**Lời từ chối «spells the live tree» cho một input** giờ chỉ thêm sang `inputs_unscanned`, kèm mẫu (issue #5). Bỏ tệp khỏi `inputs` thì checkout thiếu tệp; bỏ hẳn `inputs` thì OneCrew quét cả cây.

**Checkout không giống cây làm việc ở mtime và EOL** (issue #4; mep7 chỉ ghi lại, chưa đổi hành vi; **trên 2.5 đã đổi**, xem mục «Trên 2.5»):
- **mtime:** mọi tệp trong checkout có mtime bằng lúc chép. Điều kiện «tệp mới hơn X» luôn đúng trong checkout, nên không phải bằng chứng.
- **EOL:** tệp chưa commit đi qua `update-index` rồi `checkout-index`, theo `.gitattributes` và `core.autocrlf`. Một tệp LF trên đĩa có thể thành CRLF trong checkout, nên sha256 của byte thô lệch.
- **Bộ kiểm nên:** lấy thời điểm từ nội dung (ví dụ timestamp trong XML junit), và so sha trên nội dung đã chuẩn hoá EOL hoặc trên blob git (`git hash-object`), không trên byte thô.

## Giới hạn phải biết

- **Khai thiếu là trách nhiệm của người viết hợp đồng.** Lệnh đọc file không khai qua đường tương đối sẽ không thấy file, nên thường báo lỗi.
  - Từ mep2, đường dẫn tuyệt đối vào cây thật **viết sẵn** trong dòng lệnh hoặc trong tệp văn bản của inputs bị từ chối.
  - Vẫn không chặn được đường dẫn mà chương trình **tự dựng lúc chạy** từ nơi khác: biến môi trường, tệp ngoài repo (ví dụ sổ đăng ký hook liệt kê đường dẫn dự án), tên qua junction, hay chuỗi nằm trong tệp nhị phân. Lý do: verifier không chạy trong sandbox hệ điều hành.
- **Lệnh ghi ra ngoài input trên cây thật:** đường cũ phát hiện qua chụp sau, đường `inputs` thì không. Ghi bằng đường dẫn viết sẵn bị từ chối như trên; ghi bằng đường dẫn dựng lúc chạy thì không. Chỉ dùng `inputs` cho lệnh chỉ đọc hoặc chỉ ghi trong thư mục làm việc của nó.
- **Đường dẫn tuyệt đối ra ngoài repo** (ví dụ `<thư mục làm việc ngoài repo>`) không bị từ chối, và không nằm trong bằng chứng trừ khi khai vào `env_inputs` (từ 2.5.0.dev24). Ở đường cũ cũng vậy. Không khai thì bằng chứng không hết hiệu lực khi các tệp đó đổi.
- **Chương trình:** dấu vân tay phủ tệp exe được khởi động, và với Python thì các gói đã cài (xem mục «Trên 2.5»). Thư viện nạp từ chỗ khác chỉ được phủ khi khai vào `env_inputs`. Thứ gì trong repo thì khai vào `inputs`.
- **Dữ liệu ngoài input đổi không làm bằng chứng cũ hết hiệu lực,** đó chính là mục đích. Chỉ dùng khi chắc lệnh không phụ thuộc phần đó.
- **Nghiệm thu:** `--artifact-sha` phải là một cây chứa input của **mọi** mốc, đúng như lúc kiểm; `artifact_sha` của một receipt chỉ đủ khi plan có một mốc. Từ mep5, `verdict artifact` trả đúng cây đó khi mọi mốc khai `inputs`; plan trộn thì lệnh vẫn chụp toàn cây.
- **Plan trộn** mốc có và không có `inputs`: mốc không khai vẫn chụp toàn cây, và lúc xem trạng thái vẫn phải đi cả cây.
- **Tiến trình bị giết cứng:**
  - Thư mục tạm có dấu chủ được dọn ở lần `verdict run` sau.
  - Trên Windows từ mep2, tiến trình con của verifier kết thúc theo OneCrew.
  - Ngoài Windows, hoặc khi hệ điều hành từ chối job (`contained: false`), tiến trình con vẫn có thể còn chạy.
- **Tiến trình con giữ ống ra của lệnh** (thừa hưởng stdout/stderr): lượt chờ nó tới khi nó thoát hoặc hết `max_minutes`, như bản cũ. Chỉ tiến trình con không giữ ống ra mới được kết thúc ngay khi lệnh chính thoát.
  - Thư mục tạm của bản cũ không có dấu, không được dọn tự động.

## Thử cách ly

1. Cài wheel vào venv riêng. Không đổi hook hay runtime của repo thật.
2. Tạo bản sao nhỏ chứa đúng các input, hoặc repo tổng hợp; không chạy trên repo thật ở lượt đầu.
3. Theo dõi `.git`, thư mục tạm, và `snapshot` trong receipt.
