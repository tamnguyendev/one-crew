# OBS-1 — báo cáo bàn giao: màn hình theo dõi chỉ đọc, `2.4.0.dev12` (beta; các bản sửa R1–R5 theo review phát hành độc lập của Codex trên dev11)

Người lập: Claude (Opus 5.5), 04/11/2026, theo chỉ thị 03/11 tối ("Hoàn thiện OBS-1 và triển khai song song MR-R"). Lịch sử các lượt trước: dev7 `c3c8361` và dev8 `e9c02de` đã phát hành; dev9 `b070559`, dev10 `5e66903` (Codex review), dev11 `7c8bfca` (Codex review độc lập 03/11 ~20:57 → R1–R5) chỉ ở local.

## 1. Kết quả ngắn

- **Snapshot:** `commit snapshot ghi trong `manifest.json` của gói (báo cáo này nằm trong chính snapshot đó nên không tự ghi mã commit của mình)` = `2.4.0.dev12` trên `claude/onecrew-obs1` (nhánh gộp `claude/obs1-r15-int`, chỉ ở local, fast-forward vào `claude/onecrew-obs1`). HEAD hồ sơ = commit tài liệu ngay sau snapshot.
- **Gói:** `D:\OneCrewRuns\obs1\pkg\onecrew-2.4.0.dev12-obs1-beta` — wheel `onecrew-2.4.0.dev12-py3-none-any.whl`, SHA256 trong `manifest.json`; `verify\` V1–V17.
- **Bản phát hành beta:** tag `v2.4.0.dev12` trên origin private (`git@github.com:tamnguyendev/one-crew.git`), nhánh `claude/onecrew-obs1`; không force, không đổi tag/gói cũ. Beta **không** phải nghiệm thu, không phải stable, không nâng runtime nào. Trạng thái phát hành thực tế: chưa phát hành tại lúc dựng gói — tag/push chỉ làm sau khi kiểm gói đạt; trạng thái thật ghi ở bản báo cáo tại HEAD hồ sơ.
- **Kết quả kiểm từ gói (venv sạch ngoài checkout):** chạy `verify\thu-goi-obs1.ps1` trên máy của bạn để có `verify-report.json` của chính lần chạy; kết quả lượt kiểm của người dựng gói ghi ở bản báo cáo tại HEAD hồ sơ (commit tài liệu ngay sau snapshot).
- **Không đổi:** SignSDK `venv-23` (2.3.0.dev11), `ui-obs1\venv` (wheel dev8), sổ `state-23`, hook/registry thật (hash registry không đổi ở mọi lượt), nhánh `claude/onecrew-2.4`, tag và gói dev6–dev11. Không gọi model trả phí; gate 2.2 không chạy lại (chỉ module tracking/cli nhập lát này).

## 2. Năm finding — nguyên nhân, cách khép, bằng chứng

| # | Finding (Codex, dev11 `7c8bfca`) | Nguyên nhân | Cách khép (dev12) | Đỏ trước → xanh |
|---|---|---|---|---|
| R1 (P2) | bằng chứng lẫn nguồn gốc giữa thế hệ/lượt; cùng khóa vừa kế thừa vừa tạo mới bị lọc; 340 sự kiện với cửa sổ 300 → "lượt này không có đầu ra" | trang gán nhãn theo khóa (một mục mỗi khóa); chỉ mục dựng từ cửa sổ 300; ngăn bước bỏ khóa đã kế thừa; `attempt.*` mang thế hệ điều khiển; kế thừa chỉ ở dòng hiện hành; mọi chuỗi 64-hex bị coi là blob; đầu ra manifest của engine thật bị coi là "không có trong kho" | một mục cho mỗi lần dùng (seq, khóa) từ toàn bộ lịch sử, vai trò + thế hệ/lượt của chính sự kiện; kế thừa của mọi dòng từ `node.resumed`; chỉ khóa có trong kho (blob hoặc ảnh chụp manifest) là bằng chứng, mở được; `estimate.*` không phải lần dùng; nhật ký nói phần chưa tải | U `tests/test_obs1_r1_provenance.py` (test_a…test_i); T `prov`; gói V17; log trong `D:\OneCrewRuns\obs1\logs\r15\` (`test-r1-red-*`, `test-r1-red2/3-*`, `test-int-red-r1r3-*`) |
| R2 (P2) | server chỉ một project trả đường dẫn và sổ của project khác ở `untracked.registry_projects_without_plan` | `_untracked` liệt kê cả registry, so chuỗi | phạm vi áp cho toàn mô hình; so theo định danh sổ | U `tests/test_obs1_r23_scope_secrets.py` R2 (đỏ 6/6); gói V17; probe Codex chạy lại |
| R3 (P2) | `password=…` đi nguyên ra ở `waits[].ref`, `executor_waits[].ref` | vài trường thô không qua `clean` | trường thô qua `clean`; một chốt đầu ra `outward` (`diagnostics.redact_line`) cho mọi chuỗi trả ra; sổ không đổi | U R3 (đỏ 2/4, hai ca dương tính xanh từ đầu; tăng cường lúc gộp); gói V17; probe Codex chạy lại |
| R4 (P2) | mất `/api/task`: URL/dòng chọn là P8 nhưng nội dung + mẫu lệnh của P1 | dữ liệu chi tiết không gắn lựa chọn; lỗi bị nuốt | dữ liệu gắn lựa chọn; đang tải/lỗi/cũ/khôi phục; `#conn` tổng quan tách `#dconn` chi tiết; gộp: chi tiết chậm hơn chu kỳ poll vẫn hiện, lỗi vẽ vào đường lỗi giữ nguyên trạng thái, sao chép muộn, ô "Từ khi duyệt" không nhảy lùi | T `stale_detail` desktop + mobile (đỏ 35/59 mỗi cỡ); T `slow_detail` (đỏ trên nhánh gộp trước bản sửa); gói V14 |
| R5 (P3) | script mở/dừng của chủ chọn thư mục mới nhất, độc lập nhau | quét thư mục theo LastWriteTime, không ghim, không kiểm biên nhận | cặp script ghim cứng sinh từ gói + lần chạy đã nghiệm (kiểm wheel đã cài đúng từng byte); `-PinFile` ở script chung; `track stop --url/--instance/--pid` dừng theo định danh; `track open` chờ 30 s, không để lại server khi thất bại; mở từ chối trước khi khởi động khi phiên ghim cùng sổ không dùng lại được | U `test_obs1_ux` (đỏ 8 test mới); PS `test_loi_vao_obs1.ps1` (đỏ 26 kiểm, xanh 110/110); gói V15 + V17 |

Các lỗi review độc lập tìm thêm lúc gộp (vòng review rủi ro trên ứng viên tích hợp, đã phản biện từng finding) và cách khép: review rủi ro 4 hướng trên ứng viên tích hợp `06370da` (gộp nhánh; vòng đời viewer R5; logic PASS của bộ kiểm; đối chiếu với expected output), mỗi finding chặn/lớn có một người phản biện độc lập. Chặn: V14 của gói không trả lời tín hiệu `prov_more` của harness → sửa ở verifier; version và báo cáo trong gói chưa là dev12 → sửa ở snapshot này. Lớn: `/api/health` đi qua proxy HTTP của máy; `--state-root` tương đối hỏng vì tiến trình con chạy ở thư mục temp; chốt lọc R3 làm hỏng so định danh khi đường dẫn sổ trông như bí mật → R5 vòng 5 (không proxy cho loopback, đường dẫn tuyệt đối, dấu vân tay `state_root_id`). Nhỏ đã sửa: đọc lại marker/ghim trước khi ghi; ghim không ghi được thì dừng server vừa mở; báo cáo đúng khi mở thất bại; trả lời không vẽ được giữ nguyên trạng thái trang; server đọc thân request trước khi trả 405 (WinError 10053); V17 không còn chỗ đạt suông; manifest gói mô tả đúng bản dựng. Review cuối của nhóm R1 vòng 3: đầu ra của engine thật là ảnh chụp manifest (vòng 2 gọi là "không có trong kho") → người điều phối sửa, test đỏ trước. Kết quả review: `C:\Users\NUC\AppData\Local\Temp\claude\…\tasks\wuwcbk04l.output` (đã chép vào `D:\OneCrewRuns\obs1\r15-review\final-review-result.json`).

## 3. Lối vào: thử, mở, dừng, quay về

- **Thử gói:** `powershell -ExecutionPolicy Bypass -File "D:\OneCrewRuns\obs1\pkg\onecrew-2.4.0.dev12-obs1-beta\verify\thu-goi-obs1.ps1"` (17 bước; `DAT` = đạt).
- **Mở UI thử (sổ của lần kiểm đã nghiệm):** cặp ghim cứng `D:\OneCrewRuns\obs1\mo-trang-obs1-dev12.ps1` / `dung-trang-obs1-dev12.ps1`.
- **Script chung:** `verify\mo-trang-obs1.ps1 -Venv … -Project … -StateRoot … -PinFile …`, dừng bằng `verify\dung-trang-obs1.ps1` cùng `-PinFile`.
- **Quay về:** xóa venv thử là xong (sổ không bị ghi); SignSDK vẫn dùng `mo-ui-signsdk.ps1` (dev8) cho tới khi chủ quyết nâng (`nang-ui-signsdk-dev12.ps1` đã chuẩn bị, diễn tập trên bản sao, chưa chạy trên môi trường thật).

## 4. Kết quả kiểm — tách lớp

- **Chức năng (unittest trên checkout, commit `fc60513` = snapshot trừ đổi version/báo cáo):** 153/153 (test_obs1_tracking, test_obs1_p2, test_obs1_r1_provenance, test_obs1_r23_scope_secrets, test_obs1_ux, test_obs1_web, test_obs1_installed, test_g1_core, test_wf_r10_console_utf8, test_wf_r14_console_entry, test_v24_docs_sync, test_wf_engine; log D:\OneCrewRuns\obs1\logs\r15\test-int-fc60513-unit-025614.txt).
- **Tương tác (harness Chrome headless trên checkout, thời gian ảo nên mọi số đo thời gian so với đồng hồ server):** test_obs1_browser 2/2 (26 lượt kịch bản ux01…ux08, race, disc, clock, ux03b, gantt desktop/mobile, p2a, gantt_now, evid, stale_detail desktop/mobile, slow_detail, prov; 362/362 kiểm; 8 ảnh; log D:\OneCrewRuns\obs1\logs\r15\test-int-fc60513-browser-030615.txt).
- **Đỏ trước khi sửa:** từng finding và từng bản sửa lúc gộp có log đỏ trên code trước bản sửa (§2; `D:\OneCrewRuns\obs1\logs\r15\`), V17 chạy trên wheel dev11 đóng băng: 68 vấn đề đúng nguyên nhân finding (`D:\OneCrewRuns\obs1\tmp-r15\red-dev11-b2f6819\red-dev11.log`).
- **Từ gói (wheel cài ngoài checkout), kiểm độc lập (probe Codex chạy lại trên wheel dev12, xem UI bằng trình duyệt, diễn tập SignSDK trên bản sao):** ghi ở bản báo cáo tại HEAD hồ sơ sau lần chạy.

## 5. Giới hạn còn lại

`docs/obs1/limits-obs1.md` (các mục dev12). Tóm tắt: `claude` giả; harness Chrome headless chạy thời gian ảo; dữ liệu chi tiết lớn dần theo lịch sử (chưa phân trang); chốt lọc bí mật theo mẫu; `track open` không ghim (chỉ script `-PinFile` và cặp ghim cứng mới ghim); thời điểm tạo tiến trình chỉ đọc được trên Windows; chưa Codex review lại dev12; chưa nghiệm thu.

## 6. Việc thật sự cần chủ quyết

1. Đưa Codex review lại dev12 (diff `7c8bfca..` snapshot dev12): các bản sửa dev12 chưa được Codex xem.
2. Nghiệm thu (hay không) beta OBS-1 sau khi thử bằng cặp ghim cứng; beta không phải stable.
3. Có nâng UI SignSDK lên dev12 không: `nang-ui-signsdk-dev12.ps1` (cài cạnh dev8, đã diễn tập trên bản sao; chưa chạy trên SignSDK thật).
4. Gộp `claude/onecrew-obs1` vào dòng 2.4 hay giữ nhánh riêng (không tự gộp).
5. MR-R (đọc đa repo) là luồng riêng trên `claude/onecrew-mrr`: xem artifact phát triển riêng; tích hợp quyết định sau.
