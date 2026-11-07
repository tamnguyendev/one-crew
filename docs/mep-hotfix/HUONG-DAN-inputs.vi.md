# Verifier khai `inputs`: hotfix cho repo lớn

Bản `2.5.0.dev10+sol6.4.mep4`, bản thử. Chưa phát hành, chưa nghiệm thu.
- mep2 = mep1 cộng ba điểm ở mục «Thêm từ mep2».
- mep3 = mep2 cộng hai điểm ở mục «Thêm từ mep3».
- mep4 = mep3 cộng mục «Thêm từ mep4».

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

## Giới hạn phải biết

- **Khai thiếu là trách nhiệm của người viết hợp đồng.** Lệnh đọc file không khai qua đường tương đối sẽ không thấy file, nên thường báo lỗi.
  - Từ mep2, đường dẫn tuyệt đối vào cây thật **viết sẵn** trong dòng lệnh hoặc trong tệp văn bản của inputs bị từ chối.
  - Vẫn không chặn được đường dẫn mà chương trình **tự dựng lúc chạy** từ nơi khác: biến môi trường, tệp ngoài repo (ví dụ sổ đăng ký hook liệt kê đường dẫn dự án), tên qua junction, hay chuỗi nằm trong tệp nhị phân. Lý do: verifier không chạy trong sandbox hệ điều hành.
- **Lệnh ghi ra ngoài input trên cây thật:** đường cũ phát hiện qua chụp sau, đường `inputs` thì không. Ghi bằng đường dẫn viết sẵn bị từ chối như trên; ghi bằng đường dẫn dựng lúc chạy thì không. Chỉ dùng `inputs` cho lệnh chỉ đọc hoặc chỉ ghi trong thư mục làm việc của nó.
- **Đường dẫn tuyệt đối ra ngoài repo** (ví dụ `<thư mục làm việc ngoài repo>`) không bị từ chối, và không nằm trong bằng chứng. Ở đường cũ cũng vậy. Bằng chứng không hết hiệu lực khi các tệp đó đổi.
- **Chương trình:** chỉ băm đúng file được khởi động, không băm thư viện nó nạp. Thứ gì trong repo thì khai vào `inputs`.
- **Dữ liệu ngoài input đổi không làm bằng chứng cũ hết hiệu lực,** đó chính là mục đích. Chỉ dùng khi chắc lệnh không phụ thuộc phần đó.
- **Nghiệm thu:** `--artifact-sha` nhận một cây hoặc commit chứa đúng các input đã kiểm, không cần chụp toàn cây. `verdict artifact` vẫn chụp toàn cây và ghi object; trên repo lớn hãy truyền commit thay vì gọi lệnh này.
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
