# OBS-1 — báo cáo bàn giao: màn hình theo dõi chỉ đọc, `2.4.0.dev11` (bốn bản sửa theo review Codex trên dev10) — LOCAL, chưa phát hành

Người lập: Claude (Fable 5.1), 03/11/2026. Lượt 1 `bf6994f`; lượt 2 `c3c8361` = dev7; lượt 3 `e9c02de` = dev8 (tag/nhánh trên origin); lượt 4 `b070559` = dev9 (local); lượt 5 `5e66903` = dev10 (Codex review; gói `fcd6ecf` = dev10 + retry Chrome trong verifier, mã sản phẩm như `5e66903`); **lượt 6 (này, `@@SNAP@@` = `2.4.0.dev11`)**: ba P2 + một P3 của review Codex trên dev10 (`D:\OneCrewRuns\codex-obs1-dev10-review\evidence\review.json`), giữ hướng Gantt/waterfall. Không push/tag/phát hành/nghiệm thu; Codex chưa review dev11.

## 1. Kết quả ngắn

- **Snapshot:** `@@SNAP@@` = `2.4.0.dev11` trên `claude/onecrew-obs1` (local; HEAD hồ sơ = commit kế sau snapshot). Origin vẫn dev8 (`e9c02de`/`6050b89`); dev6–dev10, gói `onecrew-2.4.0.dev10-obs1-beta` (Codex đã xem) và `claude/onecrew-2.4` không đổi.
- **Gói:** `D:\OneCrewRuns\obs1\pkg\onecrew-2.4.0.dev11-obs1-beta` — wheel `onecrew-2.4.0.dev11-py3-none-any.whl` SHA256 `@@WHEEL_SHA@@` (claims đều false); `verify\` V1–V16 (V14 = 22 lượt kịch bản, thêm `gantt_now`, `evid`).
- **Kiểm từ gói (venv sạch ngoài checkout, server từ wheel, origin import = venv — V3), ba lần chạy trọn bộ với tên thư mục dài:** @@RUNS@@.
- **Bốn finding trên wheel cuối:** đỏ trên wheel dev10 `93ae9f31…` (`D:\OneCrewRuns\obs1\red-on-dev10\results.json`): @@RED10@@; xanh trên wheel dev11 (V14 `gantt_now`/`evid`/`gantt`, V1–V16) ở cả ba lần.
- **Test trên checkout:** @@REG@@ (log `D:\OneCrewRuns\obs1\logs\`). Ảnh unit: `D:\OneCrewRuns\obs1\ux\dev11-full\`.
- **Không đổi:** SignSDK `venv-23` (2.3.0.dev11) và `ui-obs1` (vẫn wheel dev8), sổ/hook/registry thật (hash `aacad058f478898d…` không đổi ở mọi lượt), wf-v24*, wf-v23-hf, gói/tag dev6–dev10. Không model trả phí; gate 2.2 không chạy lại.

## 2. Bốn finding — trước (wheel dev10) / sau (wheel dev11)

| # | Đỏ trên dev10 (`93ae9f31…`, cùng harness/unit của dev11) | Nguyên nhân | Sửa (dev11) | Xanh trên dev11 |
|---|---|---|---|---|
| P2-A | @@RED10A@@ | `loadDetail` bỏ qua reply không đổi seq; đồng hồ timeline nằm trong reply | poll không đổi seq vẫn nhận reply và chỉ dựng lại timeline (giữ chọn/gập/focus/cuộn); mất kết nối → đứng + nhãn; nối lại → theo reply, không cộng đôi | `gantt_now` 10/10 ở cả ba lần gói; `data-to` tăng theo đồng hồ server, bằng `axis.now` của reply; thanh cũ dịch trái; đứng + nhãn khi chặn; tiến lại khi mở |
| P2-B | @@RED10B@@ | `evidence_index` không có thế hệ, một mục mỗi khóa, lọc theo node | mục theo (khóa, phần việc, thế hệ, lượt); lọc theo lượt / (phần việc, thế hệ); đầu ra ↔ bằng chứng khác; "chưa có đầu ra"; `inherits` có nguồn | `evid` 8/8: P4 lượt hiện hành không có đầu ra thế hệ 0; lượt cũ + dấu mốc → đúng thế hệ 0; P9 đầu ra riêng + kế thừa `nodes[C].resume_artifact` từ thế hệ 0, mở được |
| P2-C | @@RED10C@@ | so chuỗi ISO | mọi so sánh trên `_at()` (UTC), phát ra `_iso` | unit `TimelineClock` 3/3 trên checkout; từ wheel: V14 `gantt` pixel ≤ 0,6 % (P5 chờ ghi `+00:00`); không có offset khác trong sổ thử ngoài unit |
| P3-D | @@RED10D@@ | danh sách 1fr/2.4fr, cây 210, min-width 640, ngăn phải 280 | 1fr/3.4fr; cây 170; bỏ min-width ≥ 900; ngăn dưới tới 1400; nhãn vạch trong biểu đồ | `gantt` desktop: `scrollWidth ≤ clientWidth` cho P8/P4; ux08 390/390; ảnh §4 |

## 3. Mô hình đã đổi (đọc-only, cùng nguồn cho CLI/JSON)

- `evidence_index[]`: thêm `generation`; một mục mỗi (khóa, phần việc, thế hệ, lượt); mục mức task không có thế hệ.
- `gantt.rows[].inherits[]`: `{kind, key, label, from_attempt, from_generation, source}` chỉ cho lượt hiện hành, từ `resume_artifact`/`retained_candidate`/`continues` của view phần việc (engine ghi khi `node.resumed`).
- `gantt.axis.basis` ghi "mọi mốc so theo giá trị thời gian (UTC)"; chuỗi giữ offset như sổ.
- Trang: `__track.state().axisNow`; nhãn `#gstale`; `#evnone`; mục `#inherit`.

## 4. Ảnh toàn màn hình (gói, lần @@SHOT_RUN@@) và lệnh mở UI thử

`@@WORK@@\evidence\`: `ux-detail-P4-desktop.png` (1280×720: cây 170 px + trục trọn + ngăn chi tiết dưới), `ux-detail-P1-split.png` (640), `ux-detail-P4-mobile.png` (390: timeline cuộn trong vùng riêng), `ux-overview-desktop.png`, `ux-overview-mobile.png`, `ux-detail-P1-questions-*.png`. Tự xem: @@VISUAL@@.
Mở UI thử (sổ thử của lần kiểm mới nhất, server từ wheel dev11): `powershell -ExecutionPolicy Bypass -File "D:/OneCrewRuns/obs1/mo-trang-obs1-dev11.ps1"`; dừng: `dung-trang-obs1-dev11.ps1`.

## 5. Kết quả kiểm — tách ba lớp

- **Chức năng (unittest):** @@FUNC@@.
- **Tương tác (harness Chrome headless, thao tác do script phát, thời gian ảo nên mọi số đo thời gian so với đồng hồ server):** V14 22 lượt × 3 lần gói: @@V14@@; unit `test_obs1_browser` @@BROWSER@@. Timeout/retry Chrome: @@TIMEOUTS@@.
- **Trực quan (tự xem ảnh):** @@VISUAL@@.

## 6. Giới hạn còn lại

`docs/obs1/limits-obs1.md` (mục dev11): blob cùng byte → cùng khóa giữa thế hệ; kế thừa chỉ theo trường engine ghi; thời gian ảo của harness; bố cục 1280 đo với dữ liệu thử; `ServerIdentity` flake khi hai server chạy song song (đạt khi chạy riêng); `claude` giả; chưa Codex review lại.

## 7. Việc thật sự cần chủ quyết

1. Đưa Codex review diff `5e66903..@@SNAP@@` (hoặc `fcd6ecf..@@SNAP@@`); sau đó quyết định phát hành dev11 (tag/push) hay gộp.
2. SignSDK `ui-obs1` giữ wheel dev8 cho đến khi chủ quyết (`cai-ui-signsdk.ps1 -Package <gói dev11>`).
