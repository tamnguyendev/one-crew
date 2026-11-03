# OBS-1 — ma trận UX (viết trước khi sửa code, 03/11/2026)

Bố cục chốt (học cách phân cấp của Blazo, không mượn code/tài sản; gói vẫn stdlib): **tổng quan → chi tiết task → timeline theo phần việc/attempt → bằng chứng của từng bước**.
Màn rộng (≥ 900 px): hai cột, danh sách bên trái, chi tiết bên phải (cố định, cuộn riêng). Màn hẹp (< 900 px: cửa sổ chia đôi, 390 px): một cột, chọn task thì
chuyển sang màn chi tiết có nút "← Danh sách"; URL mang `?plan=&project_id=` nên reload/liên kết giữ ngữ cảnh. Một theme sáng mặc định (tối theo hệ điều hành),
nhãn chính tiếng Việt, thuật ngữ/ID/hash/lệnh nằm trong phần "Kỹ thuật" gập lại. Không có nút điều khiển task.

Ba lớp kiểm, tách nhau: **(F)** chức năng = unittest trên model/HTTP; **(T)** tương tác = trang thật trong Chrome headless, điều khiển bằng harness cùng origin
(`tests/obs1_ux_harness.py`: click, bàn phím, ≥ 3 lượt poll thật, reload, back, 3 kích thước), chạy trong unittest và trong gói (V14); **(B)** bố cục = đo
`scrollWidth`, vị trí chi tiết, focus, ảnh có chú thích ở `D:\OneCrewRuns\obs1\ux\<snapshot>\`.

| # | Tình huống | Thao tác người dùng | Expected output | Kiểm |
|---|---|---|---|---|
| UX-01 | Đang đọc bằng chứng/attempt, dữ liệu poll về | mở "Bằng chứng", mở "Attempt", cuộn timeline, đợi ≥ 3 lượt poll (có và không có sự kiện mới) | phần đã mở vẫn mở, phần tử focus vẫn focus, vị trí cuộn giữ; chỉ số liệu đổi | T: harness đếm poll qua badge `seq`/`đọc`, so `open`, `activeElement`, `scrollTop` trước/sau |
| UX-02 | Đang xem P1 của project A, đổi lọc sang B | chọn project B ở bộ lọc | danh sách chỉ B; chi tiết đóng, ghi "chọn một task của project B"; URL bỏ `plan` | T: harness; F: không có API (chỉ client) |
| UX-03 | Câu hỏi có nhiều lựa chọn | mở chi tiết P1 (request keep/drop) | thấy câu hỏi, từng lựa chọn (id + nhãn, khuyến nghị), mỗi lựa chọn một dòng lệnh đã điền `--choice <id>`, nút "Sao chép"; không nút trả lời | F: `needs_user[].options[].reply_command`; T: harness bấm Sao chép → clipboard/fallback trả đúng lệnh |
| UX-04 | Chọn task ở 1280×720 | click dòng; Tab tới dòng, Enter/Space; ↑/↓ đổi dòng; Esc hoặc "← Danh sách"; reload; Back | chi tiết hiện ngay trong tầm nhìn (cột phải / màn chi tiết), focus vào tiêu đề chi tiết khi chọn bằng bàn phím, Esc trả focus về dòng; reload giữ task; Back về danh sách | T: harness đo `getBoundingClientRect` của chi tiết, `activeElement`, `location.search`, `history.back()` |
| UX-05 | Plan đóng chưa có đầu ra; plan đã kiểm chưa nghiệm thu; đã nghiệm thu | nhìn danh sách | nhãn/màu khác nhau: "đã đóng" (xám), "đã kiểm, chờ nghiệm thu" (xanh ngọc), "đã nghiệm thu" (xanh lá); thời gian ghi đúng đại lượng: "từ khi duyệt (lịch)" ≠ "thực hiện (attempt)" ≠ "chờ" | F: `status.label/outcome`, `elapsed.label`; T: DOM có đúng chữ/lớp |
| UX-06 | Timeline có thế hệ/attempt cũ | mở chi tiết P4 | sự kiện nhóm theo phần việc → attempt, trong nhóm cũ → mới (seq tăng), nhóm attempt cũ gập "lịch sử (n)" và đánh dấu; sự kiện kỹ thuật (attempt.*, executor.managed…) gập "chi tiết kỹ thuật"; bấm một bước → bằng chứng của bước đó | F: `timeline[].stale_attempt`, `evidence_index`; T: harness kiểm thứ tự seq trong DOM, nhóm, click bước |
| UX-07 | Danh sách dày thông tin kỹ thuật | nhìn dòng task | mỗi dòng: trạng thái, tên/mục tiêu ngắn, bước hiện tại, cập nhật gần nhất (tương đối + tuyệt đối), "cần bạn"; ID/đường dẫn/adapter mờ, hash không hiện ở danh sách; bằng chứng có tên/loại/thời điểm ở chi tiết | F: `evidence_index[]` có `kind/at/node/label`; B: ảnh |
| UX-08 | Màn 390×844 và cửa sổ 640 px | mở trang, chọn task, mở bằng chứng | `scrollWidth` ≤ viewport (không cuộn ngang trang); bảng kỹ thuật cuộn trong vùng riêng; điều hướng dùng được | T: harness đo `document.documentElement.scrollWidth` ở 390/640/1280; B: ảnh |
| P2-srv | `track open` gặp marker cũ / cổng bị tiến trình khác dùng / server của wheel khác / hai lần mở cùng lúc | chạy `track open` (script hằng ngày, script SignSDK) | chỉ dùng lại server khi `/api/health` trả đúng `instance` (nonce marker) + version wheel + state-root + phạm vi project; sai → không coi là thành công, không kill tiến trình lạ, mở server mới; hai lần mở cùng lúc → một server, marker không mất; `track stop` chỉ dừng server đã khớp định danh | F: `tests/test_obs1_ux.py` (marker giả, server khác trên cùng cổng, wheel cũ không có `instance`, 2 thread); gói: V15 |
| Mất kết nối / sự kiện muộn / trả ngược thứ tự | server tắt rồi bật; hai request chi tiết về ngược thứ tự | badge "MẤT KẾT NỐI" rồi tự nối lại, dữ liệu cũ giữ nguyên; phản hồi của task đã bỏ chọn không ghi đè task đang chọn | T: harness (proxy chặn `/api/*`, token theo lựa chọn) |
| Đóng UI không dừng worker | tắt server giữa attempt | worker tiếp tục, node vẫn produced | F có sẵn (V8, test web) — giữ |

## 2. Vòng dev9 (review Codex trên dev8, 03/11 ~11:15) — bảng acceptance viết trước khi sửa

| # | Tình huống | Expected | Phản chứng / kiểm |
|---|---|---|---|
| P2-A | task đang chạy, nhiều poll mà seq không đổi | thẻ "Từ khi duyệt (lịch)" tiến theo thời gian thật (sai số ≤ 2 s sau ≥ 3 poll); reload/đổi task/mất-nối lại không cộng đôi; task đã kết thúc (accepted/closed) đứng yên; thiếu `elapsed.since` → "chưa xác định" | T `clock` (đo giá trị giây qua 3 poll, so với đồng hồ harness; đỏ trên dev8); F `_elapsed(now=…)` với giờ giả |
| P2-B | câu hỏi chờ trả lời | mẫu lệnh đầy đủ: `onecrew --project "<p>" --state-root "<s>" question answer <id> --revision <rev> --choice <id> --reference "<…>"`; phần người dùng phải điền được đánh dấu rõ và gọi là mẫu; parser của wheel chấp nhận khi điền reference, từ chối khi thiếu; đường dẫn có khoảng trắng, cwd khác, nhiều project/sổ | F `QuestionCommands`; gói V16 (CLI cài từ wheel: thiếu `--reference` → exit 2, có → ghi sổ thử; cwd khác); T `ux03` (sao chép đúng mẫu; copy thất bại không báo thành công) |
| UX-08b | đường dẫn project dài (tên thư mục > 40 ký tự) ở 390 px | không phần tử nào vượt mép phải; harness liệt kê phần tử tràn | T `ux08` liệt kê `right > innerWidth`; fixture dùng tên thư mục dài (tái hiện 402 px của lượt 11:06) |
| A | danh sách khi đang đọc chi tiết | cột danh sách thu gọn (≥ 900 px), dòng gọn; bộ lọc nhanh "cần bạn / bị chặn / đang chạy" có số đếm | T `ux07` (chip đếm, bấm chip lọc) |
| B | task có ≥ 3 câu hỏi | vùng đầu: tên, trạng thái, bước hiện tại, "n câu hỏi chờ bạn"; thẻ số liệu không bị đẩy xuống; từng câu gập, mở ra thấy lý do/tác động/lựa chọn/mẫu lệnh; không gộp request | T `ux03b` (3 request: 3 mục gập, tiêu đề mỗi mục khác nhau, stats ở trên câu hỏi) |
| C | attempt có `reserved_at`/`settled_at` | thanh thời gian attempt chỉ khi có cả hai mốc; thiếu → chữ "chưa xác định", không thanh | T `ux06` (bar có ở P2, không ở attempt đang chạy) |
| D | nhãn pha/trạng thái phần việc | tiếng Việt (đang chạy / bị giữ / chờ / xong…), mã gốc ở title; badge có ký hiệu kèm màu | T `ux05` |

## 3. Vòng dev10 (chủ chốt 03/11 ~13:30: timeline Gantt/waterfall làm trung tâm) — bảng acceptance viết trước khi sửa

Hướng thiết kế chốt (áp dụng "frontend design defaults" của tài liệu Anthropic: nêu rõ hướng và kiểu cần tránh, kiểm bằng ảnh): bảng điều khiển dữ liệu dày kiểu Blazo — màn chi tiết = đầu (tên, trạng thái, bước, cần bạn) → **cây phần việc → lượt (trái) · thanh trên CÙNG trục thời gian (giữa) · ngăn chi tiết bước (phải)** → thẻ số liệu → bảng/nhật ký kỹ thuật gập. Tránh: nền kem, chữ nghiêng trang trí, nhãn đánh số 01/02, nút viên thuốc, bảng log có thanh trang trí thay cho waterfall, số liệu không có nguồn.

| # | Tình huống | Expected | Kiểm (F chức năng / T tương tác / V trực quan) |
|---|---|---|---|
| G1 trục | task có nhiều lượt, có lượt đang chạy | mọi thanh trên một trục `[axis.start, axis.end]` từ mốc có nguồn (`attempts.created_at/updated_at`, `attempt.launched`, `executor.observed`, `node.*`); `end` = hiện tại khi còn attempt active (`extends_to_now`) | F `timeline_spans/axis` từ fixture; T `gantt`: left/width của thanh so với mốc JSON (±0,6 % trục) |
| G2 chồng lấp | P8 hai phần việc chạy song song | hai hàng có đoạn thực thi chồng lấp theo thời gian trên trục chung; tổng lịch không cộng | T `gantt` đo rect hai thanh giao nhau |
| G3 đại lượng | lượt có đặt chỗ/thực thi/chờ/kiểm | đoạn `reserved` (đặt chỗ) ≠ `execution` ≠ `wait` (từ executor wait có `until`) ≠ `verification` (produced→verification); đang chạy: đoạn xác nhận tới mốc dữ liệu mới nhất + đoạn `to_now` khác màu/sọc; thiếu mốc → "chưa xác định", không thanh | F + T (đoạn `to_now` có class riêng, P3/PB không có thanh) |
| G4 dấu mốc | sự kiện tức thời | ◆ cho node.started/produced/verification/held/resumed, quan sát blocked; plan.approved/accepted/closed trên hàng Plan; title = mốc chính xác | T đếm/so vị trí dấu mốc |
| G5 lịch sử | thế hệ/lượt cũ | gập dưới "lịch sử (n)", mờ; không đổi hàng hiện hành | T `gantt` (P4) |
| G6 chọn bước | bấm thanh/dấu mốc, bàn phím | ngăn phải: mốc chính xác, giây, lý do, đầu ra, bằng chứng (xem nội dung); giữ qua poll/đổi kích thước | T (chọn, 3 poll, resize 1280→640) |
| G7 khoảng | task dài | chọn "toàn khoảng / 1 giờ cuối / 15 phút cuối"; cuộn ngang chỉ trong vùng timeline; 390 px `scrollWidth` = 390 | T `ux08`, `gantt@mobile` |
| G8 chú giải | — | chú giải đủ loại đoạn/dấu mốc, có ký hiệu ngoài màu | T/V |
| P2-A | đang mở câu 2, câu 1 được trả lời; rồi chính câu 2 được trả lời/đổi bản | khóa theo `REQ id + revision`; mục mở/focus/trạng thái sao chép không nhảy sang câu khác; request biến mất → ghi chú "không còn chờ, mẫu lệnh cũ hết hiệu lực", không giữ mẫu cũ như hiệu lực | T `p2a` (đỏ dev9: poll với danh sách request thật sự đổi); gói V14 qua CLI cài |
| P2-B | đường dẫn có khoảng trắng, `'`, `$SDK`, backtick, `&`, `(` | shell hỗ trợ = **PowerShell**; nháy đơn (`'`→`''`), `& '<exe venv>' --project '…' --state-root '…' question answer … --reference '<…>'`; `$SDK='CHANGED'` không đổi đường dẫn; parser nhận, sổ thử ghi; thiếu reference từ chối | F unit qua `powershell -NoProfile -Command` thật; V16 từ wheel với thư mục `demo$SDK 'q' (a)&b``t`; đỏ dev9 trước |
| giữ | dev8/dev9 | mọi kịch bản cũ (ux01…08, clock, ux03b, race, disc, V15) xanh | T |

## 4. Vòng dev11 (review Codex trên dev10 `5e66903`, 03/11 ~16:00): 3 P2 + 1 P3 — bảng acceptance viết trước khi sửa

| # | Tình huống | Expected | Phản chứng (đỏ trên wheel dev10 `93ae9f31…`) / kiểm |
|---|---|---|---|
| P2-A | P4 đang chạy, ≥ 3 poll mà seq không đổi | đầu cuối đoạn `to_now`, đường "hiện tại" và cuối trục tiến theo `gantt.axis.now` của server mỗi poll; đoạn đã xác nhận không đổi; lượt kết thúc không kéo; mất kết nối → đóng băng + nhãn "dữ liệu cũ lúc …"; nối lại → theo server, không cộng đôi; giữ bước chọn/gập/focus/cuộn | T `gantt_now`: đo `data-to` và cạnh phải (px) của `.seg.to_now` qua 3 poll seq đứng yên (phải tăng ≥ 2 s và ≥ 1 px khi trục đủ rộng), `.seg.execution` của lượt đã xong không đổi; chặn `/api/*` → không đổi + nhãn; nối lại → tiến tiếp |
| P2-B | P4: lượt hiện hành thế hệ mới chưa có đầu ra; lượt cũ thế hệ 0 có receipt; P9: thế hệ mới kế thừa `resume_artifact` của thế hệ 0 | ngăn chi tiết lọc bằng chứng theo (node, thế hệ, attempt) của thanh/dấu mốc; lượt hiện hành chưa có đầu ra → "chưa có đầu ra"; chọn lượt cũ → đúng receipt thế hệ 0; kế thừa hợp lệ hiện riêng "kế thừa từ thế hệ 0: đầu ra dở" với khóa và nguồn | F `evidence_index[].generation`, `rows[].inherits`; T `evid` (P4 lượt hiện hành không có "thế hệ 0 đã tạo đầu ra", lượt cũ có; P9 có mục kế thừa) |
| P2-C | quan sát `+07:00`, hiện tại `+00:00`; offset âm; qua ngày; hai chuỗi cùng thời điểm; observed_at ≠ received | mọi min/max/so sánh theo giá trị thời gian (UTC); trục chứa đoạn đang chạy tới hiện tại; chuỗi cùng thời điểm → cùng thứ tự/thời lượng/pixel | F `_timeline_spans` trực tiếp với chuỗi trộn offset (axis end = now UTC, thứ tự, giây); P5 chờ ghi bằng `+07:00` thật qua `executors.observe` → T `gantt` đoạn chờ nằm trong trục, pixel khớp |
| P3-D | 1280×720, P8 "toàn khoảng" | thấy trọn trục và đầu cuối thanh không cuộn ngang; cây ≤ 170 px; ngăn chi tiết dưới biểu đồ (≥ 900 px) ; danh sách thu gọn hơn khi đọc chi tiết; chữ ≥ 12 px; 390 px vẫn `scrollWidth` = 390 | T `gantt@desktop`: `.gscroll.scrollWidth ≤ clientWidth` ở "toàn khoảng" cho P8 và P4; V ảnh 1280/640/390 |
| giữ | dev8–dev10 | mọi kịch bản cũ xanh (ux01…08, clock, ux03b, gantt, p2a, race, disc, V15, V16) | T |
