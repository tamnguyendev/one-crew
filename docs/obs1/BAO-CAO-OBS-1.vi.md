# OBS-1 — báo cáo bàn giao: màn hình theo dõi chỉ đọc, `2.4.0.dev10` (timeline Gantt/waterfall làm trung tâm + hai P2 của dev9) — LOCAL, chưa phát hành

Người lập: Claude (Fable 5.1), 03/11/2026. Lượt 1 `bf6994f`; lượt 2 `c3c8361` = dev7; lượt 3 `e9c02de` = dev8 (tag/nhánh trên origin); lượt 4 `b070559` = dev9 (local); **lượt 5 (này, `@@SNAP@@` = `2.4.0.dev10`)**: chủ chốt hướng thiết kế (03/11 ~13:30) — màn chi tiết lấy **timeline Gantt/waterfall** làm trung tâm theo bố cục ảnh Blazo, sửa hai P2 còn mở trên dev9 (P2-A mục câu hỏi bám chỉ số; P2-B mẫu lệnh quote sai trong PowerShell). Hướng thiết kế áp dụng "frontend design defaults" của tài liệu Anthropic (đọc được bằng WebFetch: nêu rõ kiểu cần tránh, kiểm trực quan lặp): bảng điều khiển dữ liệu dày, tránh nền kem/chữ nghiêng trang trí/nhãn 01-02/nút viên thuốc/log có thanh trang trí. **Chưa push/tag/phát hành/nghiệm thu, chưa Codex review lại.**

## 1. Kết quả ngắn

- **Snapshot:** `@@SNAP@@` = `2.4.0.dev10` trên `claude/onecrew-obs1` (local; HEAD hồ sơ = commit kế sau snapshot). Origin vẫn dev8 (`e9c02de`/`6050b89`); dev6–dev9 và `claude/onecrew-2.4` không đổi.
- **Gói:** `D:\OneCrewRuns\obs1\pkg\onecrew-2.4.0.dev10-obs1-beta` — wheel `onecrew-2.4.0.dev10-py3-none-any.whl` SHA256 `@@WHEEL_SHA@@` (claims đều false); `verify\` V1–V16.
- **Kiểm từ gói (venv sạch ngoài checkout, server từ wheel, origin import = venv — V3):** `thu-goi-obs1.ps1` → @@VERIFY@@ (`@@WORK@@`, tên thư mục dài). V14 = @@V14@@ lượt kịch bản (thêm `gantt` desktop/mobile, `p2a`); lặp thêm @@V14_REPEATS@@ lượt: @@V14_REPEAT_RESULT@@. V16 = mẫu lệnh qua **PowerShell thật** từ wheel: P1 (thiếu `--reference` → exit 2, sổ không đổi; điền → ghi sổ thử) và project `demo$SDK 'q' (a)&b``t` với `$SDK = "CHANGED"` → đường dẫn nguyên vẹn, trả lời ghi sổ thử. Độ trễ ghi→trang `@@LAT@@` s.
- **Test trên checkout:** @@REG@@ (log `D:\OneCrewRuns\obs1\logs\`). Ảnh unit: `D:\OneCrewRuns\obs1\ux\@@SNAP@@\`.
- **Phản chứng trên dev9 (wheel đóng băng `111bb1ee…`):** @@RED9@@ (`D:\OneCrewRuns\obs1\red-on-dev9\results.json`).
- **Không đổi:** SignSDK `venv-23` (2.3.0.dev11) và `ui-obs1` (vẫn wheel dev8), sổ/hook/registry thật (hash `aacad058f478898d…` không đổi ở mọi lượt), wf-v24*, wf-v23-hf, gói/tag dev6–dev9. Không model trả phí; gate 2.2 không chạy lại.

## 2. Hai P2 của dev9 — trước / sau / bằng chứng trên wheel

| # | Tái hiện trên dev9 | Nguyên nhân | Sửa (dev10) | Bằng chứng sau |
|---|---|---|---|---|
| P2-A | trang dev9 (thẻ câu hỏi khóa theo chỉ số `need:i`): mở thẻ thứ hai, câu hỏi thứ nhất được trả lời qua CLI dev9 trong lúc trang poll → thẻ đang mở chuyển sang câu khác: @@RED9A@@ | `data-k` theo chỉ số; snapshot/restore khôi phục theo chỉ số | `data-k = need:<REQ id>:<revision>`; `knownNeeds` ghi nhớ thẻ đang mở; request biến mất/đổi bản → ghi chú "không còn chờ / đã đổi bản: mẫu lệnh cũ không còn hiệu lực" (ẩn được), bỏ trạng thái sao chép | harness `p2a` xanh từ wheel dev10 (trả lời câu 1 khi đang mở câu 2 → thẻ mở/focus/sao chép vẫn là câu 2; trả lời chính câu 2 → ghi chú, mẫu cũ biến mất) |
| P2-B | dev9 `--project "D:\…\demo$SDK …"` qua `powershell.exe` với `$SDK = "CHANGED"` → đường dẫn thành `demoCHANGED…`, parser từ chối: @@RED9B@@ | nháy kép bị PowerShell nội suy | shell hỗ trợ = **PowerShell**; nháy đơn (`'`→`''`); `& '<venv>\Scripts\onecrew.exe' --project '…' --state-root '…' question answer … --reference '<…>'`; `reply_shell` | unit `PowerShellTemplate` (powershell.exe thật, file .ps1, `$SDK = "CHANGED"`, đường dẫn có `$`, `'`, backtick, `&`, `(`, khoảng trắng → trả lời ghi sổ; dạng dev9 → từ chối); V16 từ wheel |

## 3. Timeline Gantt/waterfall — nguồn dữ liệu và cách kiểm

- **Nguồn (chỉ dữ liệu đã có, thêm trường đọc `detail.gantt`):** `attempts.created_at` (đặt chỗ), sự kiện `attempt.launched` (bắt đầu thực thi), `attempts.updated_at` của lượt đã settled (kết thúc), `executor.observed` có `observed_at` (mốc dữ liệu mới nhất; wait có `until` → đoạn chờ; progress blocked → dấu mốc), `node.produced`→`node.verification` (đoạn kiểm), `node.started/held/resumed/result_retained`, `plan.approved/accepted/closed/revised`, `request.created/consumed` (dấu mốc). Trục = min/max các mốc; còn lượt active → trục kéo tới "hiện tại" (`generated_at` của server) và lượt đó có đoạn sọc **tới hiện tại, chưa xác nhận** từ mốc dữ liệu mới nhất. Thiếu mốc → không vẽ, ngăn chi tiết ghi "chưa xác định". Không ETA/phần trăm/khoảng chờ suy đoán; khoảng trống không gọi là chờ; tổng lịch không cộng chồng lấp.
- **Bố cục:** đầu (tên, trạng thái, bước hiện tại, "n câu hỏi chờ bạn") → Cần bạn (gập) → **Timeline**: cây *phần việc → lượt* (trái, gập/mở; lịch sử cũ gập, mờ) · thanh trên cùng trục (giữa; 5 vạch giờ; đường "hiện tại"; ◆ dấu mốc) · ngăn chi tiết bước (phải ≥ 1100 px, dưới ở màn hẹp) → thẻ số liệu → bảng phần việc → nhật ký sự kiện (gập) → kỹ thuật. Chú giải đủ loại đoạn; chọn khoảng toàn bộ / 1 giờ / 15 phút; cuộn ngang chỉ trong vùng timeline (390 px: `scrollWidth` = 390).
- **Kiểm (T, harness `gantt`):** left/width của **mọi** đoạn so với mốc JSON của `/api/task` trên cửa sổ trục ≤ 0,6 % (@@GANTT_WORST@@); P8 hai lượt chạy đồng thời (engine `run_batch(slots=2)`, executor isolate) → hai thanh thực thi giao nhau trên trục; P4 lượt đang chạy có đoạn xác nhận + đoạn `to_now` + đường hiện tại, lượt cũ gập "lịch sử (1)" mờ, dấu mốc blocked; dấu mốc đúng vị trí; chú giải đủ; Enter chọn thanh → ngăn chi tiết có mốc chính xác; lựa chọn giữ qua 3 poll và đổi cỡ 1280→640 (cuộn trong hộp riêng, trang không tràn); P3/PB không vẽ gì; P5 có đoạn chờ; khoảng "15 phút" thu trục. (F) `GanttSpans`: lượt đang chạy → `to_now` tới `axis.now`, `confirmed=false`, `execution_seconds` chưa xác định; lượt xong → `reserved`+`execution`, kết thúc = `settled_at`.

## 4. Ảnh toàn màn hình (gói) và lệnh mở UI thử

`@@WORK@@\evidence\`: `ux-detail-P4-desktop.png` (cây + trục chung + ngăn chi tiết, 1280×720), `ux-detail-P1-split.png` (640), `ux-detail-P4-mobile.png` (390: timeline cuộn trong vùng riêng, ngăn chi tiết dưới), `ux-overview-desktop.png`, `ux-overview-mobile.png`, `ux-detail-P1-questions-*.png`. So với ảnh Blazo (`dashboard-mockup.png`): cùng phân cấp cây trái / thanh giữa / chi tiết phải và chú giải; khác: không sidebar/KPI/thẻ chi phí (không có nguồn), màu chỉ là dấu hiệu phụ, nhãn tiếng Việt. Tôi tự xem ảnh (@@VISUAL@@).
Mở UI thử (sổ thử của lượt kiểm, server từ wheel): `powershell -ExecutionPolicy Bypass -File "D:/OneCrewRuns/obs1/mo-trang-obs1-dev10.ps1"`; dừng: `dung-trang-obs1-dev10.ps1`.

## 5. Kết quả kiểm — tách ba lớp

- **Chức năng (unittest):** @@FUNC@@.
- **Tương tác (harness Chrome headless, thao tác do script phát):** V14 @@V14@@ + lặp @@V14_REPEATS@@ lượt (@@V14_REPEAT_RESULT@@); unit `test_obs1_browser` @@BROWSER@@.
- **Trực quan (tự xem ảnh):** @@VISUAL@@.

## 6. Giới hạn còn lại (tách khỏi đề xuất)

`docs/obs1/limits-obs1.md`: thao tác kiểm do harness phát (không tay người/screen-reader); Chrome headless (clipboard `readText` không khả dụng); `claude` giả; đoạn "tới hiện tại" theo đồng hồ server lúc poll; hai lượt đồng thời trong dữ liệu thử là lượt đã kết thúc (Control giới hạn 2 worker toàn sổ); trục 5 vạch, chưa thu phóng tự do; shell mẫu lệnh chỉ PowerShell; gate 2.2 không chạy lại; chưa Codex review, chưa nghiệm thu, chưa phát hành. Đề xuất chưa làm: —.

## 7. Việc thật sự cần chủ quyết

1. Đưa Codex review diff `b070559..@@SNAP@@`; sau đó quyết định phát hành dev10 (tag/push) hay gộp.
2. SignSDK `ui-obs1` giữ wheel dev8 cho đến khi chủ quyết (`cai-ui-signsdk.ps1 -Package <gói dev10>`).
