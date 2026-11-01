- **Đây là bản thử FINAL của 2.4 (S1, S2, A, B, C), bản beta.** Chưa nghiệm thu, chưa được Codex review; chỉ dùng trên bản sao project và sổ thử. Các mục dưới đây là giới hạn của từng mốc, giữ nguyên như khi mốc đó được giao.

**2.4-S1**

- **Đây là mốc 2.4-S1 (báo lỗi một lần), bản alpha.** Chỉ có `onecrew support report|show|status|list|classify|link|bundle|import-spool|confirm`. S2 (nối bản vá với công việc cũ), A, B, C chưa có trong gói này; bộ kiểm không chạy bước nào của các mốc đó.
- **Không tải gì lên đâu cả.** `support bundle` chỉ ghi hồ sơ chẩn đoán ra một thư mục trên máy bạn (`uploaded: false` trong `manifest.json`). Gửi hồ sơ cho ai là việc của bạn, sau khi bạn đọc file.
- **Không cài hay đổi bản OneCrew (hotfix).** Không chuyển venv, không tiếp tục root, không đổi pin, quyền hay ngân sách, không gia hạn root cũ, không tự mở plan sửa lỗi. Phần nối bản vá với công việc cũ thuộc 2.4-S2; ở S1 các cột "có bản thử", "đã cài", "đã kiểm tại đích" luôn là `false`.
- **Lọc bí mật theo mẫu, không phải bảo đảm.** Từng dòng của hồ sơ được lọc bằng mẫu (`display_core.safe`): dòng có dạng bí mật bị thay, URL có mật khẩu bị che, dòng khác giữ nguyên. Bí mật không có dạng quen thuộc vẫn có thể lọt vào hồ sơ. Ảnh không bao giờ được chép (chỉ ghi sha256 và kích thước). Hồ sơ giới hạn 256 KB mỗi file, 200 sự kiện mỗi task, 8 MB cả hồ sơ; quá thì nguồn cũ nhất bị bỏ và đánh dấu `truncated`.
- **Phiên bản của lần chạy cũ là chưa biết.** Báo cáo ghi phiên bản của bản cài đang chạy lúc báo lỗi (và sha256 của RECORD, hash code, đường dẫn interpreter); không ghi và không suy ra được bản OneCrew đã chạy task cũ mà bạn đang báo lỗi. Không lấy được thì ghi `unknown` kèm lý do. Hai báo cáo giống nhau chỉ được *gợi ý* là có thể trùng, không bao giờ bị gộp, và không được gợi ý khi khác phiên bản.
- **Báo cáo không phải lỗi đã tái hiện.** Trạng thái là `reported`, cột tái hiện là `unknown` cho tới khi một finding có receipt thật được nối vào. `support confirm` là tín hiệu của riêng chủ dự án ("với tôi lỗi đã hết"), bị từ chối trong phiên AI; nó không có nghĩa OneCrew đã kiểm tại đích.
- **Spool không phải nơi giữ trạng thái.** Khi sổ hỏng hoặc runtime không import được, báo cáo được ghi vào `support-spool\` (thứ tự: state root, `<project>\.onecrew\`, thư mục tạm); không ghi được chỗ nào thì lệnh trả mã khác 0 và in NOT recorded. Một báo cáo trong spool chưa có trạng thái, phân loại hay liên kết nào cho tới khi `import-spool` nhập nó vào sổ (đúng một lần, với đúng mã `FB-…` đã in). Bộ kiểm chứng minh luồng này với một `ledger.sqlite3` rác; các kiểu hỏng khác (đĩa đầy, file bị khóa) chỉ có test đơn vị.
- **Bản cũ đọc sổ có báo cáo chưa được diễn tập.** Báo cáo ghi các sự kiện `support.*` trên một task neo riêng của project (không đụng root nào, không thêm bảng). Việc 2.3.0.dev10 (hay 2.2) mở sổ có task neo đó và `compat scan` có chấp nhận nó hay không **chưa được kiểm bằng harness phiên bản cũ**; bộ kiểm của gói này chỉ diễn tập quay về 2.2 trên sổ không có báo cáo (V7, V16). Trước khi quay về với sổ thật, chạy `compat scan` của bản cũ trên bản sao sổ.
- **Runner và host log của v1 không có trong bản cài.** Hồ sơ ghi hai nguồn này là `not_applicable`; thông báo chuyển trạng thái đi qua outbox sẵn có (nhận lại, khởi động lại, ACK hay đóng cửa sổ không trả lời hay nghiệm thu gì).
- **Bộ kiểm dùng `claude` giả và sổ tạm.** Các bước V17–V19 chạy bản cài trong venv mới, ngoài checkout, với ledger tạm; chúng chứng minh các lệnh và đường ghi của S1, không chứng minh trải nghiệm trên sổ thật hay với model thật. Lệnh `support confirm` trong bước V19 được chạy một lần như người dùng giả lập trên sổ tạm để đối chứng với lần bị từ chối; đó không phải xác nhận của chủ dự án.
- **Hồi quy 2.3 giữ nguyên các giới hạn của 2.3.0.dev10** (`docs/v23/BAO-CAO-2.3-DEV10-2026-10-31.vi.md`, `docs/CHANGELOG.md`): bản thử chưa nghiệm thu, chưa được Codex review, không dùng với sổ đang chạy việc thật.

**2.4-S2**

- **Đây là mốc 2.4-S2 (bản vá OneCrew: sửa, cài tại đích, kiểm lại, tiếp tục), bản alpha.** Gói có S1 và S2; A, B, C chưa có, bộ kiểm không chạy bước nào của các mốc đó. Chỉ dùng trên bản sao project và sổ thử, không dùng với sổ đang chạy việc thật.
- **Bước build không được lặp lại.** `support artifact` chứng minh "wheel này chứa đúng từng byte các file của commit đã kiểm, không thừa không thiếu, RECORD và METADATA đúng"; nó không build lại wheel từ commit. Manifest chỉ là bằng chứng, không cho quyền gì.
- **Quyền cài và quyền quay lui chỉ đến từ plan sửa.** Plan sửa đã duyệt, còn mở, ghi `support_install:<đích>` và còn ngân sách. Ngân sách của plan sửa được kiểm nhưng không bị trừ khi cài; mỗi lần chạy lại `install` ghi thêm một `decision.recorded` trên root plan sửa. Plan sửa đã nghiệm thu là đã đóng nên không cài được nữa.
- **Claim chỉ loại trừ nhau trong một state root.** Hai state root khác nhau trỏ cùng một venv không chặn nhau. Claim của tiến trình khác được tôn trọng tới khi hết hạn (15 phút); claim của tiến trình đã chết thì được tiếp quản.
- **Liệt kê process chỉ có trên Windows.** Trên hệ khác kết quả là `processes: unknown` nên việc chuyển bị từ chối. Danh sách rỗng chỉ có nghĩa là không thấy process nào chạy qua launcher của venv cũ; một python gốc chạy code của venv cũ không được nhận ra. OneCrew không bao giờ dừng process.
- **Chỉ hook của Claude Code được liệt kê.** Dịch vụ host, cấu hình MCP hay Codex chạy bản cũ không được liệt kê (`not_enumerated`); khai báo thêm bằng `support target add --consumers`. Settings hay sổ đăng ký không đọc được thì việc chuyển bị từ chối.
- **Bản vá thứ hai cho cùng đích.** Sau một lần chuyển, hook đang chạy venv mới chứ không chạy venv của đích, nên lần cài kế tiếp không thấy project nào: quay lui trước, hoặc khai báo lại đích với `--replace`.
- **Mẫu settings khi chuyển hook là của runtime đang chạy lệnh cài,** không phải của runtime mới; không có file `.bak`, chỉ có sha trước và sau trong bản ghi.
- **Quay lui chứng minh đọc được, không chứng minh chạy tiếp được.** Runtime cũ phải đọc mọi root, tính được trạng thái root engine (`engine state`, `engine ready`) và biết mọi loại sự kiện mới; bản ghi nói "việc chạy tiếp đến cuối chưa được chứng minh". Không quay lui được thì giữ nguyên runtime mới và sổ mới.
- **Outbox desktop của venv cũ ở lại với venv cũ.** Đặt `ONECREW_DESKTOP_HOME` để hai runtime dùng chung một outbox.
- **Bộ kiểm dùng sổ tạm, `claude` giả và một repo OneCrew dựng tạm từ chính wheel của gói.** Lỗi gốc trong bước V20–V22 là một check bị đánh hỏng giả lập ở runtime cũ; plan, duyệt và rollback của chủ được chạy như người dùng giả lập trên sổ tạm. Các bước chứng minh lệnh và bản ghi của S2, không chứng minh trải nghiệm với project thật hay model thật.
- **Giới hạn của S1 vẫn giữ nguyên** (`docs/limits-s1.md` trong gói này): lọc bí mật theo mẫu không phải bảo đảm, báo cáo không phải lỗi đã tái hiện, spool không phải nơi giữ trạng thái.
- **Hồi quy 2.3 giữ nguyên các giới hạn của 2.3.0.dev10** (`docs/v23/BAO-CAO-2.3-DEV10-2026-10-31.vi.md`, `docs/CHANGELOG.md`): bản thử chưa nghiệm thu, chưa được Codex review.

**2.4-A**

- **2.4-A, worker tự đọc nguồn theo quyền:** node khai `sources` xin `list`/`search`/`read`/`page` trên cây đã ghim, trong `authority.read` của root (hướng dẫn: `docs/HUONG-DAN-SOURCE.vi.md`).
- **Một lượt đọc là một lần chạy CLI của worker.** Không có vòng tool trong một attempt; worker nên gom yêu cầu (tối đa 8 mỗi lượt). Mỗi lượt là một attempt mới, tính vào ngân sách chung của root.
- **Cây được ghim một lần cho cả chuỗi.** Muốn thấy nguồn mới thì node cần thế hệ mới (revise plan); cursor cũ khi đó bị từ chối. Node bị giữ rồi được cho chạy tiếp, hay được thay sau khi controller chết, bắt đầu chuỗi mới như 2.3 (bản dở bị bỏ), nhưng bộ đếm lượt và bộ nhớ lặp vẫn theo node.
- **Quay về 2.3 trên sổ có root khai `authority.read`:** wheel 2.3 từ chối hợp đồng đó (`authority: unknown fields read`); quay về cần root không có khóa này.
- **Khôi phục "chết giữa yêu cầu và kết quả"** là chạy lại đúng attempt đã đặt chỗ; engine chưa tự chạy lại một attempt native còn ở trạng thái `reserved` (giới hạn có từ 2.3).
- **Bộ theo dõi tiến độ** thấy các lượt đọc không đổi file như "không có thay đổi"; engine chỉ xét nó ở kết quả cuối.
- **Adapter nguồn hiện chỉ có cây Git;** log hay dữ liệu ngoài repo để sau. Project không phải cây Git thì `source_tools` là `unavailable` và node chạy như 2.3.
- **Nội dung nguồn là dữ liệu, không phải quyền;** lọc bí mật theo tên và nội dung là theo mẫu, không phải bảo đảm.
- **Mọi kiểm ở mốc này dùng worker giả** (bước V23 dùng `claude` giả đọc theo yêu cầu và một worker theo kịch bản); chưa chứng minh model thật dùng tốt giao thức.

**2.4-B**

- **2.4-B, working context theo consumer:** mỗi attempt được giao tri thức có một `knowledge.delivered`; thay đổi tri thức hay nguồn đã giao chỉ đến node ở điểm an toàn (hướng dẫn: `docs/HUONG-DAN-CONTEXT.vi.md`).
- **Bản ghi giao, delta và ACK chỉ chứng minh đã giao gì,** không chứng minh worker đã hiểu hay đã dùng đúng; checks của node mới phán kết quả.
- **Không có phiên model giữ lâu.** Không tuyên bố xóa được thứ model đã "nhớ" trong lượt chạy cũ; chỉ bảo đảm lượt sau không nhận lại mục đã thu hồi và kết quả cũ không được công bố như hiện hành.
- **Tri thức được xét trên snapshot worker đã thấy;** file đã đọc qua 2.4-A được so với cây làm việc hiện tại. Cổng chạy trong giao dịch ghi sự kiện công bố; sửa trang wiki hay file nguồn không bị khóa chung (khoảng dưới một giây).
- **`MAX_RECHECKS` đếm mọi lần kiểm lại của node trong đời root** (kể cả trước một lần revise hay chủ dự án cho chạy tiếp); ghi bản giao lỗi thì attempt dừng trước khi chạy (đóng an toàn).
- **Mục chỉ có trong `omitted.index`** (tiêu đề) không được ghi, nên thu hồi chúng không gây kiểm lại. Commit trang wiki thêm mục `must` có thể làm mọi node đang chạy liên quan kiểm lại tới 2 lần rồi giữ.
- **Mẫu quyền đọc có `[` chữ** vẫn được đọc như glob.
- **`wiki consumers` và `affected_consumers` chỉ để xem,** không phải kênh báo tự động.
- **Mọi kiểm ở mốc này dùng worker giả** (bước V24 dùng `claude` giả); chưa có bằng chứng với model thật.

**2.4-C**

- **2.4-C, bước 0 đủ để làm và cách chạy node:** thẻ bước 0 là cách xem chỉ đọc của `plan proposal check`; capability `execution-mode` ghi chế độ chạy và lý do (hướng dẫn: `docs/HUONG-DAN-BUOC-0.vi.md`).
- **Fixture chứng minh luật và bản ghi,** không chứng minh model thật đề xuất đúng hay chạy nhanh hơn; chưa đo trên provider thật.
- **`size` và `in_authority` vẫn do AI tự khai;** thẻ không coi đó là bằng chứng "nhỏ nhất". Ước lượng trên thẻ không bao giờ thành trần chạy hay ngân sách.
- **Nhãn `resources` là độc quyền trong một root;** hai root khác nhau không thấy nhãn của nhau.
- **Fixture và kịch bản cũ dùng `list(namespaces.CAPABILITIES)`** nay bật cả `execution-mode`; đường không capability (mọi root thật hiện nay) được giữ bằng các test riêng của 2.3.
- **Chi phí bàn giao là mô hình** (tốc độ chuẩn bị quan sát × context của worker trước), không phải đo trực tiếp phần node sau nhận; chưa đo thì là `unknown`, không phải 0.
- **Capacity tính theo state root** (tối đa 2 attempt); không xét CPU/RAM. Pipeline theo dependency là mốc 2.5-B. Không adapter nào giữ phiên model (`session.reuse: false`).
- **Bộ kiểm (bước V25)** chạy hai node độc lập trong hai slot bằng executor có quản lý và một worker là process cục bộ (không gọi model), qua `engine.run_batch` của bản cài; `engine measure` được gọi qua CLI của bản cài.
