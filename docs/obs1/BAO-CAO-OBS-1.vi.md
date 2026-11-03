# OBS-1 — báo cáo bàn giao: màn hình theo dõi chỉ đọc, `2.4.0.dev9` (vòng UI/UX thứ hai theo review Codex trên dev8) — LOCAL, chưa phát hành

Người lập: Claude (Fable 5.1), 03/11/2026. Lượt 1 `bf6994f`; lượt 2 `c3c8361` = dev7 (4 P2); lượt 3 `e9c02de` = dev8 (UX-01…08 + định danh server; tag/nhánh trên origin); **lượt 4 (này, `b070559` = `2.4.0.dev9`)**: review Codex UX trên dev8 → hai P2 (đồng hồ "Từ khi duyệt", mẫu lệnh trả lời thiếu `--reference`), tràn 402 px ở 390 px (phát hiện độc lập của phiên điều phối), UX A–D; kiểm trên wheel cài sạch ở 1280/640/390; **chưa push/tag/phát hành/nghiệm thu, chưa Codex review lại** (chủ sẽ đưa Codex review).

## 1. Kết quả ngắn

- **Snapshot:** `b070559` = `2.4.0.dev9` trên `claude/onecrew-obs1` (local; HEAD hồ sơ `commit hồ sơ ngay sau snapshot (docs)`). Origin vẫn: tag `v2.4.0.dev8` → `e9c02de`, nhánh `6050b89`; dev6/dev7/`claude/onecrew-2.4` không đổi. Không tag, không push.
- **Gói:** `D:\OneCrewRuns\obs1\pkg\onecrew-2.4.0.dev9-obs1-beta` — wheel `onecrew-2.4.0.dev9-py3-none-any.whl` SHA256 `111bb1ee790bf40b1af8afd1e0b46adc5c2048f16ee7483ba3bec9d02db431d5` (claims: delivered/accepted/reviewed đều false); `verify\` V1–V16.
- **Kiểm từ gói (venv sạch ngoài checkout, `claude` giả):** `thu-goi-obs1.ps1` → `DAT` 16/16 (V1–V16; 12:44:48–12:53:16 03/11) (`D:\OneCrewRuns\obs1\thu-goi-dev9-b070559 voi ten thu muc dai de kiem tra tran chieu ngang 390px`). V14 = 17/17 lượt kịch bản UX (thêm `clock`, `ux03b`); V16 = mẫu lệnh trả lời qua CLI cài từ wheel (thiếu `--reference` → exit 2, sổ không đổi; điền → ghi sổ thử, câu hỏi rời "cần bạn"); độ trễ ghi→trang `0,3` s. Lặp V14 thêm 2 lượt (`17/17 và 17/17 (`ux-repeat-1.json`, `ux-repeat-2.json`, có poll và ghi sổ trong lúc đọc); tổng 3 lượt V14 đều 17/17 trên gói cuối`).
- **Test trên checkout (code = snapshot):** test_obs1_ux + browser + tracking + p2 48/48 (`test-dev9-r5-123249.txt`, code = b070559 trừ 0 dòng), web + installed + g1_core + console utf8/entry + docs_sync 54/54 trên b070559 (`test-dev9-reg-final-124451.txt`); trên 10f3bc2 (khác b070559 một câu lý do + cắt chữ thẻ): browser/ux/web 27/27 (`test-dev9-final-121556.txt`) (log `D:\OneCrewRuns\obs1\logs\`). Ảnh unit: `D:\OneCrewRuns\obs1\ux\b070559\`.
- **Phản chứng trên dev8 (wheel đóng băng `169ef77a…`, server của gói dev8 trên sổ thử dev8):** harness `clock` ĐỎ (s0 2422 → s1 2423 sau 4,15 s thật; đổi task +2 s sau 6,3 s), `ux03` ĐỎ (mẫu lệnh thiếu `--reference`/project/sổ), `ux03b` ĐỎ (câu hỏi không gập, không đếm); lệnh trả lời dev8 chạy qua `onecrew` dev8 → `error: the following arguments are required: --reference` (exit 2) — `D:\OneCrewRuns\obs1\red-on-dev8\results.json`.
- **Không đổi:** runtime SignSDK `venv-23` (2.3.0.dev11), `ui-obs1` đã bàn giao (vẫn wheel dev8; bản dev9 KHÔNG cài vào đó), sổ/hook/registry thật (hash `aacad058f478898d…` không đổi ở mọi lượt), wf-v24*, wf-v23-hf, gói/tag dev6–dev8. Không model trả phí; gate 2.2 không chạy lại.

## 2. Hai P2 — tái hiện trước, kết quả sau, bằng chứng trên wheel

| # | Tái hiện trên dev8 | Nguyên nhân | Sửa (dev9) | Bằng chứng sau |
|---|---|---|---|---|
| P2-A đồng hồ | harness `clock` trên server wheel dev8: sau 3 poll không đổi seq, thẻ "Từ khi duyệt" không tiến (s0 2422 → s1 2423 sau 4,15 s thật; đổi task +2 s sau 6,3 s); Codex: 16m44s đứng, reload mới 17m07s | `tick()` cộng `(now − poll cuối)` vào giá trị đã dựng; poll không dựng lại nhưng dời mốc → kéo về giá trị cũ | giá trị mang mốc dựng `data-live-at`; tiến theo đồng hồ máy; dựng lại/đổi task/reload lấy giá trị có nguồn mới + mốc mới; task kết thúc/chưa duyệt không chạy | V14 `clock@desktop` từ wheel dev9: ±2 s qua 3 poll (seq không đổi), reload không cộng đôi, đổi task đúng, P3 đứng, PB "chưa xác định"; unit `ElapsedClock` (giờ giả +90 s → +90 s; đóng → đứng) |
| P2-B mẫu lệnh | `onecrew question answer REQ… --revision … --choice keep` qua wheel dev8 → `required: --reference` (exit 2); không có project/sổ | model sinh lệnh tối thiểu | mẫu đầy đủ `onecrew --project "<p>" --state-root "<s>" question answer <id> --revision <rev> --choice <id> --reference "<lý do hoặc bằng chứng của bạn>"`; placeholder đánh dấu, gọi là mẫu; guard chủ sở hữu/bản/AI-session giữ | V16 từ wheel: thiếu `--reference` → 2 + sổ không đổi; điền → exit 0, câu hỏi rời "cần bạn" (sổ thử, từ cwd có khoảng trắng); unit `QuestionCommands` qua `onecrew.console`; `ux03` clipboard (trong Chrome headless `navigator.clipboard` từ chối và `execCommand('copy')` trả false → trang báo "không sao chép được" kèm ô chép tay (V14 `ux03`: kiểm nhánh hỏng đạt); trên trình duyệt có người dùng chưa kiểm `readText` (NotAllowedError trong headless)) |

## 3. Tràn 402 px ở 390 px (lượt 11:06 của phiên điều phối; không tái lập ở lượt 10:50)

Nguyên nhân: `<select>` project có option = đường dẫn dài (`…obs1 thu 2.4.0.dev8 20261103-110652\project with space`); `max-width:100%` của select tính theo `label` cha, mà label (flex item, `min-width:auto`) rộng theo nội dung → trang 402 px. Lượt 10:50 dùng thư mục `thu-goi-dev8-e9c02de` ngắn nên không tràn: kết quả "đạt" của dev8 ở UX-08 chỉ đúng với tên thư mục ngắn. Sửa gốc: `label{min-width:0;max-width:100%}`, `select{min-width:0}`; fixture và scenario dùng tên thư mục project dài; harness `ux08` liệt kê phần tử vượt mép phải (không chỉ `scrollWidth`), kiểm cả khi mở mẫu lệnh. dev9: V14 `ux08@mobile` 390/390 với tên thư mục kết quả dài 74 ký tự và project 'du an thu nghiem … 2026' (option dài nhất > 40 ký tự), cả khi mở mẫu lệnh; lặp 3 lượt đều đạt; dev8 đỏ trên cùng dữ liệu (`red-on-dev8/results.json`: `ux08@mobile` tràn).

## 4. UX A–D — thay đổi và lợi ích

- **A.** Chip lọc nhanh "cần bạn (n) / bị chặn (n) / đang thực hiện (n)" trong header; khi đang đọc chi tiết (≥ 900 px) cột danh sách thu gọn và ẩn dòng ID/đường dẫn → màn đầu cho biết task nào cần mình mà không cần đọc từng dòng.
- **B.** Vùng đầu chi tiết: tên + trạng thái + **bước hiện tại** + "n câu hỏi chờ bạn" (liên kết); thẻ số liệu đứng trước; mục "Cần bạn (n)" với từng câu hỏi gập (tiêu đề riêng, không gộp), mở ra thấy lý do/ảnh hưởng/lựa chọn/mẫu lệnh; trạng thái mở giữ qua poll → 3 câu hỏi không đẩy tóm tắt xuống (`ux03b` ở 1280 và 390).
- **C.** Bảng attempt có thanh thời lượng chỉ khi attempt có mốc kết thúc và số đo; đang chạy = "chưa xác định" (không thanh, không ETA/phần trăm).
- **D.** Pha/đầu ra phần việc tiếng Việt (mã gốc ở `title`), lý do giữ ghi "lý do (engine)"; badge có ký hiệu ▶ ◔ ■ ✔ ✓ □ ? ngoài màu; `current_step` "chờ bạn trả lời n câu hỏi".
- Giữ hành vi dev8: đổi project, poll giữ chỗ đọc, Enter/Esc/URL/reload/Back, mobile, ba kiểu "xong", lịch sử cũ, evidence đúng task, đóng UI không dừng worker, định danh server (V15) — các kịch bản cũ chạy lại xanh.

## 5. Ảnh và lệnh mở UI thử

Ảnh gói: `D:\OneCrewRuns\obs1\thu-goi-dev9-b070559 voi ten thu muc dai de kiem tra tran chieu ngang 390px\evidence\ux-overview-desktop.png`, `ux-detail-P1-questions-desktop.png` (3 câu hỏi gập), `ux-detail-P1-questions-mobile.png`, `ux-detail-P4-desktop.png`, `ux-detail-P1-split.png`, `ux-overview-mobile.png`, `ux-detail-P4-mobile.png`. Trước/sau: dev8 `D:\OneCrewRuns\obs1 thu 2.4.0.dev8 20261103-110652\evidence\` (của phiên điều phối) so với dev9 ở trên.
Mở UI thử (sổ thử của lượt kiểm dev9, server qua `track open`): `powershell -ExecutionPolicy Bypass -File "D:/OneCrewRuns/obs1/mo-trang-obs1-dev9.ps1"`; dừng: `dung-trang-obs1-dev9.ps1`.

## 6. Giới hạn (chưa kiểm) — tách khỏi đề xuất

`docs/obs1/limits-obs1.md`: thao tác do harness phát (không tay người/screen-reader); Chrome headless (`readText` clipboard: trong Chrome headless `navigator.clipboard` từ chối và `execCommand('copy')` trả false → trang báo "không sao chép được" kèm ô chép tay (V14 `ux03`: kiểm nhánh hỏng đạt); trên trình duyệt có người dùng chưa kiểm `readText` (NotAllowedError trong headless)); `claude` giả; đồng hồ theo đồng hồ máy mở trang; đường dẫn có dấu nháy kép không hỗ trợ trong mẫu lệnh; chưa thử font/độ phóng khác; gate 2.2 không chạy lại; dev9 chưa Codex review, chưa nghiệm thu, chưa phát hành. Đề xuất (không làm trong lượt này): —.

## 7. Việc thật sự cần chủ quyết

1. Đưa Codex review diff `e9c02de..b070559`; sau đó quyết định phát hành dev9 (tag/push) hay gộp.
2. SignSDK `ui-obs1` giữ wheel dev8; cài dev9 chỉ sau khi chủ quyết (`cai-ui-signsdk.ps1 -Package <gói dev9>`).
