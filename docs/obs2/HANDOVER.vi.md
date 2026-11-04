# Bàn giao OBS-2 dev9 — khép P3 focus của review dev8 và đính chính báo cáo dev8, 05/11/2026

**Sẵn sàng để Codex kiểm tra độc lập.** Chưa phát hành, chưa nghiệm thu, chưa push/tag, không nâng runtime thật. Chưa có review của Codex trên dev9.
- Người làm: Claude (Opus 5.5).
- Nguồn issue: review Codex trên dev8, `D:/OneCrewRuns/obs2-codex-review-dev8-20261105-001551` (`focus_probe.py`: 15/16, focus về SUMMARY).

## Snapshot

| Mục | Giá trị |
|---|---|
| Nhánh | `claude/obs2-dev8` (tiếp tục), worktree `D:/TamNT/Workspace/11.OneCrew/wf-obs2-claude` |
| Product snapshot | `cd567d3e99a5b895b12ae13a6d17cda96dd61a5c`, version `2.5.0.dev9`. Là 1 commit sau `47ec37d`: sửa focus, ca kiểm, README gói, version. |
| Gói | `D:/OneCrewRuns/obs2/pkg/onecrew-2.5.0.dev9-obs2-cd567d3`; SHA256SUMS 18/18; 142 file trong wheel trùng commit; manifest đúng commit/version |
| Wheel SHA256 | `dd1fdce4dd8c1c23f29256e2584049ae36c7ed7828c2da084a3640d0889081df` |
| Bản thử | `D:/OneCrewRuns/obs2/trial-cd567d3-1` |
| Bằng chứng | `D:/OneCrewRuns/obs2-dev9` |
| Gói dev8 | giữ nguyên `D:/OneCrewRuns/obs2/pkg/onecrew-2.5.0.dev8-obs2-1380006` |

## Mở và dừng bản thử

```powershell
powershell -ExecutionPolicy Bypass -File "D:/OneCrewRuns/obs2/mo-obs2-dev9.ps1"
```

```powershell
powershell -ExecutionPolicy Bypass -File "D:/OneCrewRuns/obs2/dung-obs2-dev9.ps1"
```

Dữ liệu tổng hợp, chỉ đọc. Không dùng lệnh của bản thử để duyệt công việc thật. Lifecycle đã chạy qua đúng hai script này: mở → mở lại cùng instance → dừng đúng phiên → dừng lần nữa exit 2. Project, sổ, gói và registry thật không đổi byte (`trial-cd567d3-1/lifecycle-report.json`).

## Kết quả

| ID | Trạng thái | Vị trí (snapshot `cd567d3`) | Nguyên nhân | Sửa |
|---|---|---|---|---|
| P3 — mất focus sau sao chép | **Closed** | `onecrew/v2/tracking_web.py:1141` (`snapshot`), `:1146-1153` (`restore`), `:1210-1211` (`copyText`) | 1. `restore` cho thẻ `<details>` thắng trước nút sao chép, nên focus về SUMMARY. 2. Nhánh nút sao chép lấy nút đầu tiên của thẻ, không phải nút đã bấm. 3. `copyText` khôi phục ảnh chụp lúc bấm, nên kết quả về muộn kéo focus và vị trí đọc về chỗ cũ. **Lỗi sản phẩm có từ trước dev8** (cùng đỏ ở dev7 và dev8 trong ux03, stale_detail), không phải hồi quy của dev8. | `restore` ưu tiên đúng phần tử người dùng đang đứng: nút có **cùng lệnh** (không bao giờ nút của lựa chọn khác), nút bằng chứng, nút "Thử lại", link; chỉ khi không có mới về summary của thẻ. Nút không còn (mất binding, đổi bản) thì về tiêu đề thẻ; thẻ không còn thì về tiêu đề task. `copyText` chụp vị trí ngay lúc kết quả về. Cùng thứ tự này cũng khép lỗi tương tự với nút bằng chứng nằm trong `<details>`. |
| Đính chính dev8 | **Done** | phần dev8 bên dưới (bảng "Liên quan B", mục bộ trình duyệt OBS-1, mục giới hạn thời gian cập nhật) | Bàn giao dev8 gọi cả 13 kịch bản OBS-1 đỏ là lỗi kỳ vọng chữ/bố cục chỉ vì dev7 và dev8 cùng đỏ, và hứa "tối đa một chu kỳ poll". | Phân loại lại theo bằng chứng (mục dưới); bỏ cam kết thời gian. Giữ nguyên lịch sử, đánh dấu "Đính chính 05/11". |

## Đỏ trên dev8 → xanh trên wheel cuối (các ca đã thực sự chạy)

**Ca `focus-desktop` / `focus-mobile` mới** trong `verify/check_binding_live.py`.
- Fixture: task P3 có 2 thẻ câu hỏi, mỗi thẻ 2 lựa chọn đã gắn hook.
- Clipboard giả có kiểm soát: `writeText` trả Promise do kịch bản quyết định; ca thất bại ép `execCommand` trả false.
- Tiền điều kiện được assert trước khi đánh giá: đủ thẻ và lệnh, trang thật sự dùng clipboard giả, người dùng thật sự cuộn.
- Các ca:
  - A: thẻ 2, lựa chọn 2, sao chép thành công.
  - B: thẻ 1, lựa chọn 1, sao chép thất bại.
  - C: kết quả về muộn trong lúc người dùng đã chuyển focus sang tab "Thay đổi" và cuộn.
  - D: kết quả về muộn sau khi đã đổi sang P2.
  - E: kết quả về muộn sau khi mất binding, rồi gắn lại.

Kết quả:
- **Wheel dev8** (venv `trial-1380006-1`): **134/142**.
  - Mọi tiền điều kiện đạt; 8 ca R7-1 cũ vẫn đạt.
  - Đỏ đúng ở A và B (focus về SUMMARY), và ở C: focus bị kéo về thẻ, vị trí đọc bị kéo từ 2179 về 176 (desktop), từ 3594 về 476 (mobile).
  - Log `D:/OneCrewRuns/obs2-dev9/red-dev8/run/browser-binding-live.json`.
- **Wheel cuối** (venv `trial-cd567d3-1`): **142/142**, focus 20/20 mỗi cỡ.
  - Focus ở lại đúng nút của đúng lựa chọn trong đúng thẻ; thông báo sao chép chỉ ở thẻ đó.
  - Kết quả về muộn không kéo focus hay vị trí đọc.
  - D: không lẫn nội dung P3 vào P2; quay lại P3 không còn thông báo cũ.
  - E: không hồi sinh lệnh hay thông báo; focus về tiêu đề thẻ.
  - Log `D:/OneCrewRuns/obs2-dev9/final/binding-live/browser-binding-live.json`.

**Probe gốc của Codex** `focus_probe.py` (chỉ đổi đường dẫn checker): dev8 **15/16** (Codex) → wheel cuối **16/16**, focus ở BUTTON với đúng lệnh (`D:/OneCrewRuns/obs2-dev9/final/codex-focus-probe/`).

**Bộ trình duyệt OBS-1 có binding** (source, cùng môi trường): dev8 392/435 → dev9 **403/435**.
- 11 kiểm chuyển xanh: ux03 "giữ focus trên nút sao chép"; stale_detail desktop/mobile (giữ mục mở, focus và vị trí đọc qua 3 poll cũ, HTTP 503 và lúc hồi phục).
- Không kiểm nào xấu đi (`D:/OneCrewRuns/obs2-dev9/obs1-browser-dev9-bound/`).

## Phân loại các kịch bản OBS-1 còn đỏ (thay cho kết luận dev8)

Việc cùng đỏ trên dev7 và dev8 chỉ chứng minh không phải hồi quy, chưa chứng minh là test lỗi thời. Phân loại theo từng kiểm, đối chiếu dòng assert trong `tests/obs1_ux_harness.py`. Không nới hay bỏ assertion nào.

**Lỗi sản phẩm đã xác nhận** (có từ trước, đã khép ở dev9): focus sau sao chép hoặc sau khi vẽ lại, ở ux03 và stale_detail×2. Các kiểm này nay đạt.

**Test lỗi thời có bằng chứng**: kỳ vọng mô tả hành vi OBS-1 mà OBS-2 đã cố ý đổi.
- ux03 (4 kiểm), stale_detail (bước chuẩn bị):
  - Kiểm đòi mẫu `question answer REQ-…`, nhãn kèm "(id)", chữ "BẠN tự điền", "Cần bạn (N)".
  - OBS-2 (`025c8ca`) đưa lệnh `owner answer '…' --human` riêng cho từng lựa chọn, vẫn giữ `<mark class="ph">`.
- slow_detail (bước chuẩn bị): kiểm đòi P6 có thẻ need không có mẫu lệnh. Từ dev6 (P2-2), P6 không còn việc nghiệm thu khi chưa đủ bằng chứng.
- ux05 (3 kiểm chữ):
  - Badge P6 "đã kiểm, chờ nghiệm thu" đã thành "Chờ bước tiếp theo" theo dev6.
  - Chữ "đã đóng"/"đã nghiệm thu" đã đổi sang `workStatus`.
- ux03b (3 kiểm chữ): "Cần bạn (N)", bước hiện tại trong dải tóm tắt (OBS-2 hiện trạng thái thẻ), "Vì:" (OBS-2 viết "Vì sao:").
- ux07 (1 kiểm): "N task", "cần bạn (N)" đã thành "N công việc", "Cần bạn quyết định (N)".

**Chưa phân loại đủ**: chưa đủ bằng chứng để gọi là test lỗi thời hay lỗi sản phẩm; cần task riêng.
- ux05: thẻ "đóng" và "đã nghiệm thu" cùng màu, badge không có ký hiệu (yêu cầu UX-05 của OBS-1). Cần quyết định thiết kế.
- ux03b: thẻ câu hỏi gập cao hơn một dòng; dải tóm tắt và timeline nằm dưới màn đầu.
- ux07: đường dẫn và ID hiển thị dạng chữ phụ.
- ux08 mobile/split: chi tiết bắt đầu ở 354/276 px trên màn hẹp; OBS-1 đòi nằm phần trên.
- ux01×2: bước chuẩn bị (focus ở tóm tắt bằng chứng) không dựng được trên bố cục OBS-2.
- prov: kịch bản không chọn được thanh Gantt ("no bar") sau đợt đổi timeline. Nguồn theo từng thế hệ chưa kiểm được qua kịch bản này.

## Hồi quy

**Tự chạy trên wheel cuối** (venv bản thử hoặc venv riêng, ngoài checkout):
- verify gói 9/9 (registry thật trước = sau);
- trình duyệt OBS-2 150/150 (75 + 75, không tràn ngang);
- binding tĩnh 8 ca 56/56;
- binding đổi giữa phiên + focus 10 ca 142/142;
- từ chối lệnh chủ trong phiên AI 2/2;
- lifecycle 4/4;
- R7-2 trên 5 sổ: kết quả như dev8 (mốc chỉ thất bại là "Đang xử lý", chưa verdict là "Chưa khởi chạy", nghiệm thu không đổi);
- 13 kịch bản OBS-1 (chậm, đổi task, timeout, mất kết nối, overview chậm, thời gian thực): 13/13, 70/70, gồm `rt_slow` thời gian thực (`D:/OneCrewRuns/obs2-dev9/harness-dev13-on-dev9/summary.json`).

**Tự chạy trên source dev9:**
- 6 module 66/66: `test_obs2_review_dev7`, `test_obs2_review_dev6`, `test_obs2_cards`, `test_obs2_web`, `test_obs2_timeline`, `test_obs1_web`.
- Bộ trình duyệt OBS-1: 27/40 kịch bản (403/435).

**Kế thừa từ dev8, không chạy lại:** nhóm OBS-2 103/103 và nhóm OBS-1 96/96 trên `1380006`. Lý do: ở dev9 chỉ đổi JS `snapshot/restore/copyText` trong `tracking_web.py` (cùng checker, README, version); `tracking.py`, `tracking_work.py`, `tracking_work_web.py` không đổi so với dev8.

**Không chạy:** probe `check_review_fixes.py` (fixture duyệt ngay trong tiến trình, bị chặn trong phiên AI; không gỡ marker), gate 2.2.

Số kiểm đạt chỉ nói về các ca đã liệt kê. Không suy ra toàn bộ sản phẩm đã được chứng nhận.

## Giới hạn

- **Clipboard:** headless không cho clipboard thật. Ca thành công/thất bại dùng clipboard giả có kiểm soát, nên không chứng minh hành vi clipboard của trình duyệt thật.
- **Bàn phím:** headless không giả lập được phím kích hoạt native. Ca kiểm xác nhận focus nằm trên đúng nút, để người dùng bàn phím tiếp tục được bằng Tab/Enter; không kiểm phím thật.
- **Thời gian cập nhật:** không có cam kết thời gian. Trang đổi sau khi nhận và xử lý dữ liệu chi tiết mới; phản hồi chậm, lỗi kết nối hoặc cơ chế thử lại (hạn chờ, số lần thử, chờ bấm "Thử lại") có thể kéo dài khoảng đó. Trong lúc ấy trang vẫn hiện dữ liệu đã nhận lần cuối.
- **Chưa kiểm:** lệnh chủ chạy thành công từ terminal của anh, sổ lớn, provider thật, pilot SignSDK, mutation test, gate 2.2 toàn bộ.

## Cách ly

So với kiểm cách ly lúc kết thúc dev8 (`D:/OneCrewRuns/obs2-dev8/logs/baseline-after.json` → `D:/OneCrewRuns/obs2-dev9/logs/baseline-after.json`): registry thật SHA256 `AACAD058F478898D41EB0294B619BE21191B83B488544961C080F4BFA0AEE01C` không đổi; SignSDK `venv-23` vẫn `2.3.0.dev11`, `state-23` không đổi; sổ bản thử dev7 `trial-6cb2fa9-1` không đổi; checkout `wf-obs2` của Codex (`codex/obs2`, HEAD `bdb13bf`) sạch; SHA256SUMS gói dev6, dev7 không đổi, gói dev8 vẫn 18/18; không còn tiến trình của lượt làm. Fixture binding chỉ ghi `.claude/settings.local.json` trong project tạm; không chạy init, không đăng ký registry. Không gọi provider, không push/tag, không ghi duyệt hay nghiệm thu.

---

# Bàn giao OBS-2 dev8 — khép R7-1/R7-2 của review dev7, 04/11/2026

**Sẵn sàng để Codex kiểm tra độc lập.** Chưa phát hành, chưa nghiệm thu, chưa push/tag, không nâng runtime thật.
- Người làm: Claude (Opus 5.5), tiếp quản theo chỉ thị chủ ngày 04/11: tự review, sửa, tự kiểm chứng.
- Nguồn issue: [review dev7](../../../outputs/onecrew-as-qc/REVIEW-OBS2-DEV7-20261104.vi.md); Codex đã tái hiện trong `D:/OneCrewRuns/obs2-codex-review-dev7` (`4435ec71/unbind`, `milestone`).
- **Đính chính:** bàn giao dev7 bên dưới ghi F1/F2 "Complete". Review dev7 xác định cả hai mới khép một phần (R7-1, R7-2). Dev8 khép hai điểm đó.

## Snapshot

| Mục | Giá trị |
|---|---|
| Nhánh | `claude/obs2-dev8`, worktree `D:/TamNT/Workspace/11.OneCrew/wf-obs2-claude`, tách từ `bdb13bf` của `codex/obs2`. Checkout `wf-obs2` của Codex không bị đụng. |
| Product snapshot | `138000603828e919cd3472cb6fc4556ee0342146`, version `2.5.0.dev8` |
| Commit sau `bdb13bf` | `672cf91` code + test + checker; `9914711` README gói; `1380006` binding fixture cho 2 test OBS-1 |
| Code `onecrew/` | `1380006` trùng byte `672cf91` (`git diff 672cf91 1380006 -- onecrew/` rỗng) |
| Gói | `D:/OneCrewRuns/obs2/pkg/onecrew-2.5.0.dev8-obs2-1380006`, SHA256SUMS 18/18 |
| Wheel SHA256 | `d5917af6678c260bbd414abf5e9af8a591d941137f7e8a3c162089b6da478fa2` |
| Bản thử | `D:/OneCrewRuns/obs2/trial-1380006-1` |
| Bằng chứng của lượt này | `D:/OneCrewRuns/obs2-dev8` |

## Mở và dừng bản thử

```powershell
powershell -ExecutionPolicy Bypass -File "D:/OneCrewRuns/obs2/mo-obs2-dev8.ps1"
```

```powershell
powershell -ExecutionPolicy Bypass -File "D:/OneCrewRuns/obs2/dung-obs2-dev8.ps1"
```

Dữ liệu tổng hợp CODE/DOC, chỉ đọc. Không dùng lệnh của bản thử để duyệt công việc thật. Lifecycle qua đúng hai script này: mở → mở lại cùng instance (cờ `reused` false→true) → dừng đúng phiên → dừng lần nữa exit 2. Project, sổ, gói và registry thật không đổi byte (`trial-1380006-1/lifecycle-report.json`, oracle như dev7).

## Kết quả

| ID | Trạng thái | Vị trí (snapshot `1380006`) | Nguyên nhân | Sửa |
|---|---|---|---|---|
| R7-1 (P2) | **Closed** | `onecrew/v2/tracking_web.py:1182`, `:1054-1056`, `:1002`, `:1219-1221` | Trang chỉ vẽ lại chi tiết khi `last_seq` của sổ đổi. Binding hook nằm ngoài sổ, nên khi gỡ hoặc đổi hook, lệnh ghi và thông báo sao chép cũ vẫn còn tới khi chọn lại task. | Ngoài `last_seq`, so thêm "bề mặt sao chép" của need (`needsSig`: lệnh, lệnh xem, binding, lý do); khác thì vẽ lại qua `paint` (giữ task, tab, mục mở, vị trí đọc). Thông báo sao chép chỉ còn khi dữ liệu mới nhất vẫn cung cấp đúng lệnh đó (`copiedStillValid`), nên mất binding thì bỏ, gắn lại cũng không hiện lại. Bấm sao chép trên thẻ vẽ trước khi dữ liệu đổi thì không chép mà vẽ lại. |
| R7-2 (P3) | **Closed** | `onecrew/v2/tracking.py:955`, `:976`, `:496-503`; `tracking_work_web.py:55`, `:65` | Root dạng mốc không bao giờ ghi `node.started`. Bản dev7 dựa vào `m.last_verdict`, nhưng API không trả trường này, nên mốc chỉ có verdict thất bại vẫn bị gọi "Chưa khởi chạy". | `has_started` tính thêm attempt, verdict đã ghi (mọi revision) và lượt chạy kiểm. `workStage` dùng chính trạng thái mốc từ API. Thẻ của root dạng mốc nói đúng bước của nó; lý do trạng thái tách "mốc X kiểm chưa đạt, chờ sửa và kiểm lại" khỏi "chờ verdict của mốc Y". Điều kiện nghiệm thu không đổi. |
| Liên quan A | **Closed** | `tests/test_obs1_web.py:189-204` | Test trang của OBS-1 đã đỏ từ OBS-2A (`025c8ca`): vẫn đòi badge "đang chờ", "cần bạn", "Sao chép mẫu lệnh", lệnh `question answer` và không có binding. Đỏ y hệt trên `6cb2fa9` cùng môi trường. | Cấp binding thật cho project tạm (`tests/obs2_binding_fixture.py`, exe fixture không bao giờ chạy). Đổi chữ kỳ vọng sang thẻ OBS-2 ("Chờ bạn trả lời", "1 quyết định cần bạn", lệnh `owner answer` cho từng phương án có `--reference`). Giữ đủ các kiểm: task, trạng thái, kết nối, không lộ bí mật. |
| Liên quan B | **Partial**, nợ test có sẵn, ngoài phạm vi R7 | `tests/test_obs1_browser.py:43-47` | Bộ 40 kịch bản trình duyệt OBS-1 chưa được cập nhật từ khi OBS-2 đổi giao diện; fixture không có binding nên các ca mẫu lệnh dừng ở bước chuẩn bị. | Đã cấp binding để ux03, stale_detail, slow_detail, p2a chạy qua bước chuẩn bị (p2a giờ đạt). 13 kịch bản vẫn đỏ, **đỏ y hệt trên dev7** (xem Hồi quy). **Đính chính 05/11:** cùng đỏ chỉ chứng minh không phải hồi quy; trong đó có lỗi sản phẩm focus có từ trước (khép ở dev9) và các ca chưa phân loại đủ, xem phân loại ở bàn giao dev9. Không nới kỳ vọng; đề xuất một task riêng chuyển bộ này sang OBS-2. |

## Đỏ trên dev7 → xanh trên wheel cuối

Mỗi ca tự xác nhận tiền điều kiện; ca nào tiền điều kiện hỏng thì tính là đỏ.

- **R7-1, trình duyệt** (`verify/check_binding_live.py`, sổ mới chỉ propose, 2 task, hook ghi/gỡ thật). 6 ca đổi binding giữa phiên (thiếu hook / khác runtime / khác sổ × desktop 1280 / mobile 390) và 2 ca thời gian thực (đọc chi tiết P1 chậm 2,5 s, gỡ hook, đổi P1→P2→P1, gắn lại).
  - Wheel dev7: **76/102**, mọi tiền điều kiện đạt (đã gắn hook, có lệnh, có thông báo sao chép; 3 lần poll không đổi thì không vẽ lại). Đỏ đúng ở: lệnh ghi còn sau khi mất binding, thông báo sao chép cũ còn, không thấy lý do binding, gắn lại thì thông báo cũ quay lại; ca chậm: gắn lại mà lệnh không tự hiện. Log `D:/OneCrewRuns/obs2-dev8/red-dev7/run/browser-binding-live.json`.
  - Wheel cuối (venv của bản thử): **102/102**. `last_seq` giữ nguyên trong mọi ca; API báo "không lệnh, chưa xác minh" rồi "có lệnh, đã xác minh". Trang theo sau ở lần poll kế tiếp mà không cần chọn lại task, không còn thông báo cũ, vẫn đúng task, tab "Thay đổi" và mục đang mở. Không lúc nào câu hỏi của task này hiện dưới tên task kia. Sổ và registry không đổi. Log `D:/OneCrewRuns/obs2-dev8/final/binding-live/browser-binding-live.json`, ảnh `live-other-state-*-lost.png`.
- **R7-1, R7-2, unit** (`tests/test_obs2_review_dev7.py`, sổ thật qua fixture repo): trên export `6cb2fa9` đỏ **3/7** (2 helper chưa có, `has_started=False` khi mốc chỉ có verdict thất bại); trên snapshot cuối xanh **7/7**.
- **R7-2 qua API của wheel trên cùng 5 sổ** (`D:/OneCrewRuns/obs2-dev8/ledgers`, `wheel_board.py`). Đọc `/api/overview` + `/api/task` của server wheel, chạy chính `workStage/workStatus` của wheel đó:
  - Chưa verdict → "Chưa khởi chạy" ở cả hai bản.
  - **Chỉ M1 thất bại: dev7 "Chưa khởi chạy" → dev8 "Đang xử lý"**, lý do "mốc M1 kiểm chưa đạt (verdict gần nhất không đạt), chờ sửa và kiểm lại; chờ verdict của mốc M2".
  - M1 đạt một phần → "chờ verdict của mốc M2". Các mốc đạt trên artifact khác nhau → "Chờ bộ thực thi kiểm các mốc trên cùng bản bàn giao", lệnh nghiệm thu từ chối. Đủ điều kiện → "Chờ nghiệm thu", nghiệm thu được.
  - Overview trùng detail; sổ không đổi. Log `logs/r72-board-dev7.json`, `logs/r72-board-final.json`.

## Hồi quy

- **Wheel cuối đã cài, ngoài checkout:**
  - verify gói 9/9 (registry thật trước = sau);
  - trình duyệt OBS-2 150/150 (75 desktop + 75 mobile, không tràn ngang);
  - binding tĩnh 8 ca 56/56;
  - từ chối lệnh chủ trong phiên AI 2/2;
  - lifecycle 4/4;
  - 13 kịch bản OBS-1 (slow/switch/timeout/mất kết nối/overview chậm/thời gian thực) 13/13, 70/70.
  - Kết quả trong `D:/OneCrewRuns/obs2-dev8/final/` và `harness-dev13-on-dev8/summary.json`.
- **Source, export snapshot cuối `1380006`, Python của venv có wheel:** nhóm OBS-2 103/103 (`test_obs2_review_dev7`, `_dev6`, `_dev5`, `test_obs2_cards`, `_web`, `_work`, `_owner_human`, `_timeline`, `test_wf_observed_handoff`); nhóm OBS-1 96/96 (`test_obs1_ux`, `test_obs1_tracking`, `test_obs1_p2`, `test_obs1_r23_scope_secrets`, `test_obs1_web`, `test_obs1_r1_provenance`); test công cụ đóng gói 2/2; 0 skip (`logs/final-reg-{obs2,obs1,tools}.log`). Trước đó trên ứng viên `672cf91` (cùng code): OBS-2 103/103, OBS-1 84/85 với 1 test đỏ có sẵn (Liên quan A, đã sửa ở `1380006`).
- **Bộ trình duyệt OBS-1 `test_obs1_browser`** (40 kịch bản, chạy cả hai bản cùng môi trường):
  - Chưa gắn binding: dev7 26/40 = dev8 26/40 (340/370).
  - Đã gắn binding: dev7 27/40 = dev8 27/40 (392/435).
  - **Không kịch bản nào khác nhau giữa dev7 và dev8**, nên bản sửa không gây hồi quy. 13 kịch bản đỏ có sẵn từ trước (ux01, ux03, ux03b×2, ux05, ux07, ux08×2, stale_detail×2, slow_detail, prov). **Đính chính 05/11:** câu cũ gọi tất cả là kỳ vọng chữ/bố cục/định dạng lệnh của OBS-1 là chưa đúng. Kiểm "giữ focus trên nút sao chép sau khi vẽ lại" (ux03) và các kiểm giữ mục mở/focus/vị trí đọc của stale_detail là **lỗi sản phẩm có từ trước** (khép ở dev9); phần còn lại đã tách thành test lỗi thời có bằng chứng và ca chưa phân loại đủ, xem bàn giao dev9. Log `D:/OneCrewRuns/obs2-dev8/obs1-browser-dev{7,8}{,-bound}/`.

## Giới hạn và chưa kiểm

- `verify/check_review_fixes.py` (probe 24 ca) không chạy được trong phiên AI: fixture của nó gọi `plan.approve` ngay trong tiến trình. Tôi không gỡ marker AI. Các ca F1–F5 tương ứng đã phủ bằng kiểm trên wheel (trình duyệt 150, binding tĩnh 56, R7-2 qua API) và test nguồn. Codex có thể chạy lại probe trong môi trường của Codex.
- **Đính chính 05/11:** bỏ cam kết "tối đa một chu kỳ poll". Trang chỉ đổi sau khi nhận và xử lý dữ liệu chi tiết mới; phản hồi chậm, lỗi kết nối hoặc cơ chế thử lại có thể kéo dài khoảng đó, và trong lúc ấy trang vẫn hiện dữ liệu đã nhận lần cuối. Từ lần đọc mới trở đi, thẻ và nút sao chép theo dữ liệu mới.
- Chưa kiểm: clipboard thật (headless từ chối clipboard, phần "đã sao chép" chỉ đọc mã), lệnh chủ chạy thành công từ terminal của anh, sổ lớn, provider thật, pilot SignSDK, mutation test, gate 2.2 toàn bộ (không chạy theo chỉ thị).

## Cách ly

Trước và sau lượt làm, so `D:/OneCrewRuns/obs2-dev8/logs/baseline-{before,after}.json`: registry thật SHA256 `AACAD058F478898D41EB0294B619BE21191B83B488544961C080F4BFA0AEE01C` không đổi; SignSDK `venv-23` vẫn `2.3.0.dev11`, `state-23` không đổi (mtime 03/11 13:45); sổ bản thử dev7 `trial-6cb2fa9-1` 109 sự kiện, hash không đổi; checkout `wf-obs2` (`codex/obs2`, HEAD `bdb13bf`) sạch; SHA256SUMS gói dev6 và dev7 không đổi. Thay đổi duy nhất ở repo dùng chung: nhánh mới `claude/obs2-dev8` và worktree `wf-obs2-claude`.

Fixture binding chỉ ghi `.claude/settings.local.json` trong project tạm; không chạy init, không đăng ký registry. Không gọi provider, không push/tag, không ghi duyệt hay nghiệm thu.

---

# Bàn giao OBS-2 dev7 — khép review dev6, 04/11/2026

Bản thử **2.5.0.dev7**, product `6cb2fa9e7eea2f5f88a394be5cc5c291f7031d98`. Phạm vi đúng 2 P2 + 3 P3 từ review dev6; không thêm feature roadmap. Các bàn giao cũ bên dưới là lịch sử, đặc biệt claim dev6 khép đủ 7 finding đã được đính chính bởi review độc lập.

## Mở bản thử

Trang thử đã kiểm health: http://127.0.0.1:53495/ — dev7, read_only, pid10936, instance `336853f849a24542`. Nếu tự thoát sau 30 phút không request, dùng lệnh mở lại bên dưới.

```powershell
powershell -ExecutionPolicy Bypass -File "D:/OneCrewRuns/obs2/mo-obs2-dev7.ps1"
```

Dừng đúng viewer thử:

```powershell
powershell -ExecutionPolicy Bypass -File "D:/OneCrewRuns/obs2/dung-obs2-dev7.ps1"
```

Dữ liệu tổng hợp CODE/DOC, project/sổ/venv riêng. Không cần duyệt để xem; UI vẫn chỉ đọc. Không dùng lệnh của trial để duyệt công việc thật.

## Các finding

| Finding | Kết quả và cách kiểm |
|---|---|
| F1 P2 — copy rỗng khi hook thiếu/lệch | Phương án vẫn đọc được; không dựng khối/nút copy, hướng dẫn chạy hay feedback copy cũ nếu không có lệnh. Có binding thì vẫn đủ lệnh. Kiểm 4 chế độ missing/other-runtime/other-state/bound, mỗi chế độ desktop/mobile |
| F2 P3 — plan dạng mốc chưa khởi chạy giả | Có verdict hoặc mốc passed thì đã có công việc diễn ra; giữ Chờ kiểm/Chờ nghiệm thu theo điều kiện thật. Test hai mốc trên hai artifact khác nhau: đang xử lý, chưa có việc nghiệm thu; đối chứng untouched và eligible |
| F3 P3 — finding dài JSON thô | Preview bị cắt của object/list hiển thị tiêu chí không đạt; giữ nguyên head/blob/source để tra. Đối chứng mô tả văn bản thường vẫn giữ |
| F4 P3 — initial còn gọi điều chỉnh | Nội dung kế hoạch, nội dung ban đầu và căn cứ quyền riêng; không dựng cặp trước/sau cho bản đầu. Các thay đổi sau vẫn có diff và lý do |
| F5 P2 — 5 test cũ gãy | Ba fixture tạo binding settings thật trong project tạm, chỉ mock vị trí executable fixture (không chạy file giả), vẫn qua check_hooks. Giữ kiểm PowerShell ký tự đặc biệt/không tự trả lời/không che nhầm. Hai kỳ vọng nghiệm thu cũ đổi sang đợi root proof, giữ kiểm trạng thái accepted và lịch sử wait |

Không thay engine, quyền, hook thật, schema hay ledger. Tái dùng renderer, milestone/verdict, finding preview và check_hooks. Fixture không chạy init hoặc đăng ký registry; khi cần test CLI, executable fixture được thay bằng Python console cùng arguments như test gốc.

## Bằng chứng snapshot

- Gói `D:/OneCrewRuns/obs2/pkg/onecrew-2.5.0.dev7-obs2-6cb2fa9`.
- Wheel SHA256 `af63b151eed65c874865d0d40adc34cb577717d41809ea94d691725eb89282ba`.
- Trial `D:/OneCrewRuns/obs2/trial-6cb2fa9-1`: verify **9/9**, browser **150/150** (75 mỗi cỡ), identity stop đạt. Đã xem ảnh results và ảnh mobile hook lệch.
- `lifecycle-report.json` trong trial: **4/4** mở/dùng lại/dừng/dừng lần nữa, identity ổn định và cờ reused false→true; state/project/package/registry không đổi. Gói **17/17 checksum** khớp.
- `D:/OneCrewRuns/obs2/dev7-browser-binding/browser-binding.json`: **8 ca, 56/56 kiểm**, chạy renderer thật từ wheel trên project mới. Sổ và registry không đổi. Ảnh `other-state-mobile.png`, `other-state-desktop.png`.
- Cùng checker browser trên dev6: `dev7-browser-binding-dev6-red/browser-binding.json`, missing-desktop đỏ **4/7**, không phải lỗi tải/setup; checker dừng có chủ đích tại ca đỏ đầu, không tuyên bố đã chạy đủ 8 ca cũ.
- Cùng probe API/renderer trên hai wheel: `dev7-probe-dev6/probe/review-fixes.json` **18/24**, dev7 `dev7-probe-dev7/probe/review-fixes.json` **24/24**. Sáu assertion đỏ gồm ba chế độ binding và F2/F3/F4; các đối chứng dev6 vẫn đạt.
- Poll/response hồi quy tập trung: `dev7-poll-regression/summary.json`, slow25/đổi task/timeout phục hồi **3 ca,14/14**, dùng harness dev13 và wheel dev7. Không chạy lại toàn bộ 13 ca; receipt dev6 70/70 là lịch sử, không gắn thành bằng chứng mới cho dev7.
- `dev7-owner-refusal/owner-human-report.json`: **2/2**, JSON/human exit2 trong phiên AI, không ghi quyết định.
- Source trước commit: 4 phản chứng presentation đỏ trên dev6 (lượt đầu có thêm10test được import, không tính thành14test mới); nhóm sửa tập trung **9/9**; kiểm liên quan **41/41**; sau thêm chặn feedback copy cũ, riêng presentation **4/4**. Lượt focused đầu lỗi3fixture do executable giả có basename không được nhận diện là OneCrew; sửa fixture thành `onecrew.exe`, giữ log cũ tại `obs2-codex-review-dev6/dev7-focused.log`.
- Hồi quy snapshot cuối: `D:/OneCrewRuns/obs2/dev7-regression/tests.log`, **116/116, 0 skip**, 367.827s, runnerexit0. Export nguyên commit6cb2fa9, dùng venv cài đúng wheeldev7; TEMP/APPDATA/LOCALAPPDATA riêng. Chạy toàn module `test_obs1_ux`, `test_obs1_tracking`, `test_obs1_p2`, `test_obs1_r23_scope_secrets`, `test_obs2_review_dev6`, `test_obs2_review_dev5`, `test_obs2_cards`, `test_obs2_web`. Cả5test từng gãy và ca decoy environment đều đạt. Không bỏ ca hoặc biến lỗi thành skip.

## Giới hạn

Chưa push/tag/nghiệm thu hoặc nâng runtime; không gọi provider, không full gate. Chưa kiểm clipboard và lệnh chủ thành công từ terminal người dùng, pilot hay sổ lớn. Thành công lệnh chủ trong unit là fixture. Kết quả này chỉ cho phạm vi bản vá UI; không chứng nhận toàn bộ roadmap2.5. Gói dev6 giữ nguyên; MR-R/CP-1 không là điều kiện bàn giao.

Runtime SignSDK vẫn **2.3.0.dev11**. Registry thật SHA256 `AACAD058F478898D41EB0294B619BE21191B83B488544961C080F4BFA0AEE01C` giữ nguyên sau kiểm.

---

# Bàn giao OBS-2 dev6 — sửa cross-review dev5, 04/11/2026

**Đã sửa đủ 3 P2 và 4 P3 trong phạm vi local.** Bản thử `2.5.0.dev6`, product `693f11493b53d4089077d6f06f2a13084e097e5a`. Chưa phát hành/nghiệm thu; không nâng runtime thật. Các bàn giao dev5 trở xuống là lịch sử.

## Mở và thử

Trang thử: http://127.0.0.1:56815/ — health xác nhận dev6, read_only, pid27592, instance `cad819733d1c8c7f`. Nếu tự thoát sau 30 phút không request, mở lại bằng lệnh dưới.

```powershell
powershell -ExecutionPolicy Bypass -File "D:/OneCrewRuns/obs2/mo-obs2-dev6.ps1"
```

Dừng đúng viewer này:

```powershell
powershell -ExecutionPolicy Bypass -File "D:/OneCrewRuns/obs2/dung-obs2-dev6.ps1"
```

Dữ liệu mẫu cách ly; không cần duyệt để xem UI. Chọn CODE → Kết quả & kiểm chứng để xem finding dễ đọc; Thay đổi phân biệt kế hoạch ban đầu. Chọn DOC → Tiến độ để xem timeline. Các nút sao chép không tự thực hiện quyết định.

| Finding | Kết quả bản sửa |
|---|---|
| P2 — cột Chờ kiểm sai | Chỉ vào cột khi có đầu ra thực sự chờ kiểm; node đã kiểm + node chưa chạy không đủ điều kiện |
| P2 — giao nghiệm thu quá sớm | Trạng thái, cột và việc cần chủ cùng dựa vào bằng chứng mốc/handoff; mọi node verified chưa đủ |
| P2 — lệnh ghi dùng runtime viewer khác project | Chỉ cung cấp khi hook xác nhận đúng executable và sổ; thiếu/lệch thì ẩn mẫu lệnh, giải thích, vẫn xem được dữ liệu |
| P3 — finding JSON | Hiện mô tả/check không đạt, giữ nguồn gốc để tra |
| P3 — evidence văn bản | Không gọi văn bản hợp lệ là JSON hỏng; blob mất vẫn cảnh báo |
| P3 — kế hoạch ban đầu | Nhãn riêng, không gọi là điều chỉnh |
| P3 — Gantt nhiều ngày | Vạch theo số ngày dễ đọc; có phản chứng biên 4.01–3650 ngày |

Tái sử dụng `check_hooks`, `milestone_views`, finding register và bộ xác minh handoff v1. Tách helper đọc `handoff_evidence` khỏi `root_ready`; đường nghiệm thu thật vẫn kiểm working tree. Viewer chỉ phản ánh bằng chứng đã ghi, không tự xác nhận working tree hiện tại hay ghi sự kiện nghiệm thu.

## Snapshot và kiểm chứng

- Gói: `D:/OneCrewRuns/obs2/pkg/onecrew-2.5.0.dev6-obs2-693f114`; SHA256SUMS **16/16** khớp.
- Wheel SHA256: `28d11a3f768ddc26286226254182b0b34e2aa94f866a203795e0cdf3956d7052`.
- Trial: `D:/OneCrewRuns/obs2/trial-693f114-1`.
- `verify-report.json`: **9/9**, cài wheel ngoài checkout, đối chiếu 9 module gồm engine; CLI/API và bảo toàn project/sổ/registry.
- `browser/browser-report.json`: **146/146 assertion**, desktop 1280×720 và mobile 390×844, 73 mỗi cỡ. Đã xem ảnh kết quả và timeline mobile từ wheel; không tràn ngang cả trang.
- Hồi quy OBS-1 trên wheel cuối: **13 ca, 70/70 assertion**, runner exit0; `D:/OneCrewRuns/obs2/dev6-obs1-regression/summary.json`. Tái dùng nguyên harness gói dev13 (SHA256 `b65423fc1c98c5023665b6c05c9a55022bdfd225b3388a3245971ac6548b47ff`): slow25, timeout desktop/mobile, đổi task, ngắt/kết nối lại, dữ liệu hỗn hợp, overview chậm và ca thời gian thật. Server test riêng đã dừng; viewer bàn giao vẫn mở trên sổ mẫu.
- Cùng probe `check_review_fixes.py`: wheel dev5 **2/18 đạt, 16 đỏ** tại `dev6-counterexample-dev5-v2/probe/review-fixes.json`; wheel dev6 **18/18** tại `dev6-final-probe/probe/review-fixes.json` (đều dưới `D:/OneCrewRuns/obs2`). Bao phủ cả 7 finding, có đối chứng binding đúng và sổ không đổi.
- `lifecycle-final.json`: mở/dùng lại/dừng/dừng lần nữa **4/4 đúng**, cùng server identity; project/state/package/registry giữ nguyên. Bản `lifecycle-report.json` ban đầu báo false vì so toàn bộ pin, gồm cờ `reused` phải đổi false→true. Giữ nguyên báo cáo cũ; bản cuối đánh giá lại chính phản hồi đã ghi theo identity ổn định và kiểm riêng chuyển cờ, có hash báo cáo gốc.
- `dev6-owner-refusal/owner-human-report.json`: **2/2**, lệnh JSON/human vẫn bị từ chối trong phiên AI, không ghi sổ.
- Source: 9 ca mới đỏ trên baseline (5 failure + 4 error vì helper mới chưa có), xanh **9/9** sau sửa. Hồi quy liên quan **86/87**, lỗi còn lại là kỳ vọng cũ tạo việc nghiệm thu dù chưa đủ bằng chứng; sửa kỳ vọng và chạy nhóm cuối **20/20** gồm ca này, handoff hợp lệ/giả và toàn bộ 9 ca mới. Tooling **2/2**. Không mô tả lượt 86/87 thành một lượt 87/87.
- Lượt probe dev5 đầu bị lỗi schema fixture câu hỏi, giữ tại `dev6-counterexample-dev5` và không tính bằng chứng; bản v2 hoàn tất không exception.

## Giới hạn và cách ly

Không chạy toàn gate, không push/tag, không gọi provider thật, không nâng runtime. Chưa thử thành công lệnh chủ từ terminal người dùng, clipboard thật, pilot hoặc sổ lớn. Các ca chủ thành công trong source là fixture, không phải nghiệm thu. Mobile cho phép cuộn ngang bên trong Gantt.

SignSDK vẫn **2.3.0.dev11**. Registry thật giữ SHA256 `AACAD058F478898D41EB0294B619BE21191B83B488544961C080F4BFA0AEE01C`. Gói dev5 giữ nguyên. Không chờ MR-R, không triển khai thêm OBS-2C/CP-1, không coi toàn bộ feature 2.5 đã hoàn tất.

---

# Bàn giao timeline OBS-2 dev5 — 04/11/2026

**Bản thử hiện hành 2.5.0.dev5**, code `d2e592a4e99c3a79e69d7f627105200a92268803`. Đã khép 5 finding trong phạm vi local và kiểm wheel cuối; chưa phát hành/nghiệm thu/provider thật. Các phần dev4/dev3 bên dưới là lịch sử.

## Mở bản thử

http://127.0.0.1:55268/ — health đã xác nhận pid 27604, instance 9648ed48bb2ea612, read_only, đúng dev5. Nếu viewer tự thoát sau 30 phút không request:

```powershell
powershell -ExecutionPolicy Bypass -File "D:/OneCrewRuns/obs2/mo-obs2-dev5.ps1"
```

Dừng đúng viewer thử này:

```powershell
powershell -ExecutionPolicy Bypass -File "D:/OneCrewRuns/obs2/dung-obs2-dev5.ps1"
```

Chọn **DOC hoặc CODE → Tiến độ**. Sổ/project là dữ liệu mẫu, không cần duyệt để xem UI; các nút sao chép không ghi quyết định.

| Thử | Kết quả mong đợi |
|---|---|
| Mở Tiến độ | Thấy Gantt trước; bảng từng lượt và nhật ký kỹ thuật thu gọn phía dưới |
| Dóng thanh theo nhãn | Đường lưới thẳng hàng với chính mốc0/50ms/…; không chia 25% cố định |
| Bấm tên hoặc thanh | Tên bước, trạng thái/thời lượng chính xác và đầu ra lên trước ID/thế hệ |
| Mở Chi tiết lượt → Thời điểm chính xác | Có timestamp ISO gốc; mở/đóng được giữ khi poll |
| Xem đầu ra DOC | Cùng artifact hiện 1 lần; mở Nguồn vẫn thấy 2 lần ghi nhận với nguồn riêng |
| Chọn Toàn bộ lịch sử | Các lượt cũ mở ngay; khung lịch sử đứng yên |
| Bấm Về hiện hành | Thu gọn lịch sử, trở về lượt hiện hành và tiếp tục theo dữ liệu mới |

## Snapshot và bằng chứng

- Gói `D:/OneCrewRuns/obs2/pkg/onecrew-2.5.0.dev5-obs2-d2e592a`.
- Wheel SHA256 `6122d0a5ec3c1b979e11a95ea73ef82f4ce0e25f6a873993055cdccbed7bc20f`.
- Receipt root `D:/OneCrewRuns/obs2/trial-d2e592a-1`.
- `verify-report.json`: **9/9**, wheel/import đúng 8 module, CLI/API/evidence, project/sổ và registry không đổi.
- `browser/browser-report.json`: **140/140 assertion**,70 desktop1280×720 và70 mobile390×844. Bao gồm disclosure qua poll, vị trí Gantt ngay sau click, grid/tick, lịch sử, nguồn đầu ra và cửa evidence. Đã xem `browser/timeline.png` và `timeline-mobile.png`; harness không tự cuộn đến Gantt để chụp.
- `lifecycle-report.json`: **4/4**, mở/dùng lại/dừng/dừng lần nữa; đúng mã thoát, cùng instance khi reuse; state/project/package/registry không đổi.
- Source: **49/49 unit**;4 phản chứng mới đỏ trên dev4 trước khi sửa, xanh sau sửa. Source browser 140/140 đạt.
- Phản chứng browser cùng harness trên wheel dev4: `D:/OneCrewRuns/obs2/dev5-counterexample-dev4/report-complete.json`, **14/70 assertion đỏ**, không exception, bao phủ cả5finding. `report.json` trước đó giữ nguyên, có exception vì harness giả định disclosure mới tồn tại; bản hoàn chỉnh ghi fail thay vì dừng ở phần tử thiếu.
- OBS-1 hồi quy source tập trung: Gantt 22 desktop + 20 mobile (`dev5-gantt-final`), clock 10, evidence 8, slow25s 5, switch 6 (`dev5-obs1-regression`): **71 assertion đạt**. Lượt Gantt trước đỏ 2 assertion/cỡ vì kỳ vọng lịch sử vẫn gập khi chọn all; đã đổi đúng hành vi được giao, giữ oracle vị trí thanh/thời gian/nguồn và chạy lại riêng Gantt. Không cộng số assertion thành số testcase độc lập.

Không chạy toàn gate; không thay schema, quyền, engine hoặc cửa evidence. Tái sử dụng snapshot/restore, dữ liệu tracking, renderer và bộ dựng/kiểm gói. Gói/bản thử cũ giữ nguyên. SignSDK vẫn 2.3.0.dev11, registry thật giữ SHA256 `AACAD058F478898D41EB0294B619BE21191B83B488544961C080F4BFA0AEE01C`.

Giới hạn: fixture tổng hợp, chưa pilot/sổ lớn/provider hoặc clipboard thật của người dùng; mobile cuộn ngang trong biểu đồ, không tràn cả trang. Phản chứng poll inject cờ live-axis trong phản hồi thử, không ghi sổ. Source/time/duration là khoảng quan sát có nguồn, không suy checker-CPU hoặc ETA chắc chắn. Chưa push/tag/nghiệm thu; không chờ MR-R.

---

# Bàn giao timeline OBS-2 dev4 — 04/11/2026

Bản thử hiện hành: **2.5.0.dev4**, product `525c36138eaf77d5d4ef482e193322ce4be7bf3d`. Đã kiểm trên wheel cuối, chưa phát hành/nghiệm thu. Nội dung dev3 bên dưới là lịch sử, không phải lệnh mở bản mới.

## Mở và thử timeline mới

Trang: http://127.0.0.1:51281/ (pid30604, instance `7a758b5c5d6572ce`, đã kiểm health đúng dev4). Nếu server đã tự thoát sau 30 phút không request:

```powershell
powershell -ExecutionPolicy Bypass -File "D:/OneCrewRuns/obs2/mo-obs2-dev4.ps1"
```

Dừng riêng viewer này:

```powershell
powershell -ExecutionPolicy Bypass -File "D:/OneCrewRuns/obs2/dung-obs2-dev4.ps1"
```

Chọn **DOC hoặc CODE → Tiến độ**. Đây là dữ liệu mẫu, không phải công việc/provider thật; không cần duyệt để xem.

| Thao tác | Mong đợi |
|---|---|
| Mở Tiến độ | Mỗi phần việc có tên, trạng thái và thời lượng; các ID lượt không chiếm hàng chính |
| Bấm tên phần việc hoặc thanh | Xem chi tiết, người thực hiện nếu có nguồn, bằng chứng đúng lượt/thế hệ và timestamp gốc |
| Mở mũi tên | Xem các lượt; lịch sử cũ mở riêng, có nguồn, không chứng nhận đầu ra mới |
| Chọn toàn bộ lịch sử | Cửa sổ thời gian đứng yên khi poll; chọn Vừa khung để trở lại phần hiện hành |
| Xem lượt dưới một giây | Trục tương đối có mili giây, không lặp nhãn giây; độ rộng cửa sổ không phải thời lượng thực thi |
| Xem trên màn hẹp | Cuộn ngang bên trong biểu đồ; chi tiết nằm dưới, trang không tràn ngang |

Nhãn **Từ đầu ra đến kết quả kiểm** diễn tả khoảng quan sát, có thể gồm thời gian chờ; không gọi đó là thời gian checker thực sự chạy. Thiếu dữ liệu vẫn ghi chưa xác định. Ngăn chi tiết chỉ xuất hiện sau khi chọn; chú giải chỉ hiện loại đang có.

## Snapshot và kiểm chứng dev4

- Gói: `D:/OneCrewRuns/obs2/pkg/onecrew-2.5.0.dev4-obs2-525c361`.
- Wheel SHA256: `e19b6639af8a266d68d1d0b57ff3f587a38c9b0c203e5b7bab50c7d2a52382d8`.
- Receipt: `D:/OneCrewRuns/obs2/trial-525c361-1`.
- `verify-report.json`: **9/9**, nhập tám module đúng hash từ venv, CLI/API/evidence và cách ly.
- `browser/browser-report.json`: **108/108 assertion** trên wheel cuối, 54 ở desktop1280×720 và 54 ở mobile390×844. Đã xem ảnh `browser/timeline.png` và `browser/timeline-mobile.png`.
- `lifecycle-report.json`: **4/4**, mở/dùng lại/dừng/dừng lần nữa; exit0/0/0/2 đúng dự kiến, state/project/gói/registry không đổi trong kiểm.
- Source cuối: **45/45 test** timeline/cards/web/clock. OBS-1 hồi quy có phạm vi: Gantt desktop22, mobile20, phản hồi chậm25s5, chuyển task6 và đồng hồ/mất-kết-nối10 assertion đạt. Hai assertion lượt clock đầu dùng setup lịch sử đóng/nhãn cũ; đã sửa setup phù hợp UI mới, giữ kiểm hình học và chạy lại10/10 tại `dev4-live-clock`.
- Không chạy toàn gate. Không nhận bằng chứng provider thật, clipboard người dùng, sổ lớn hay nghiệm thu từ dữ liệu mẫu. Không kiểm lại owner-success ở lượt này; quyền/backend không đổi.

Gói trung gian `...dev4-obs2-1dcb7c7` giữ nguyên, không phải bản giao cuối. Bổ sung cuối ở525c361 giữ timestamp ISO gốc có offset/mili giây trong chi tiết. Gói dev3 và viewer cũ không bị thay. Báo cáo sau build nằm ngoài gói đóng băng.

Runtime SignSDK vẫn `2.3.0.dev11`. Registry thật giữ SHA256 `AACAD058F478898D41EB0294B619BE21191B83B488544961C080F4BFA0AEE01C` trong lượt dev4; không nâng runtime/hook/sổ thật. Không push/tag, không chờ MR-R, không mở rộng OBS-2C/CP-1. Lịch sử sự cố registry dev3 và khôi phục vẫn giữ bên dưới.

---

# Lịch sử: Bàn giao UI/UX OBS-2 dev3 — 04/11/2026

Bản thử local đã kiểm từ wheel cuối. Có OBS-2A/2B trên nền OBS-1; không chờ MR-R. Chưa nâng SignSDK, chưa push/tag hoặc nghiệm thu.

## Mở bản thử

Trang hiện hành: http://127.0.0.1:64836/ . Khi trang tự thoát sau 30 phút không có request, chạy:

```powershell
powershell -ExecutionPolicy Bypass -File "D:/OneCrewRuns/obs2/mo-obs2-dev3.ps1"
```

Dừng đúng viewer này, không dừng worker:

```powershell
powershell -ExecutionPolicy Bypass -File "D:/OneCrewRuns/obs2/dung-obs2-dev3.ps1"
```

CODE và DOC là dữ liệu thử; không cần duyệt để xem UI. Giữ nguyên các bản dev1/dev2 và OBS-1 dev13 đã giao.

## Những gì đã đổi

- Bảng thẻ theo giai đoạn: Chưa bắt đầu → Đang xử lý → Chờ kiểm → Chờ nghiệm thu → Hoàn tất; Đã đóng/Chưa xác định tách riêng. Chỉ đọc, không kéo thả để đổi sổ. Cột **Đang xử lý** là giai đoạn; bộ đếm **Đang chạy** chỉ tính thực thi đang hoạt động.
- Trạng thái nói chờ ai: chờ bạn duyệt kế hoạch, chờ bạn trả lời, đã có đầu ra chờ kiểm, đã kiểm đạt chờ nghiệm thu. Nhãn **quyết định cần bạn** độc lập với giai đoạn. Phương án mới chưa duyệt không được xếp chờ nghiệm thu chỉ vì bản cũ đã pass.
- Sắp xếp được ghi rõ: cần xử lý trước, cập nhật, ngày tạo, hạn. Thiếu hạn xếp sau, không biến ngân sách giờ thành ngày hẹn.
- Thẻ quyết định thu gọn; mở ra thấy nội dung, vì sao, ảnh hưởng, nút xem thay đổi và khối PowerShell có **Sao chép lệnh**. Đường runtime/project/sổ/revision được ghim. Phần lý do/lựa chọn cần điền được đánh dấu; sao chép không duyệt.
- Lệnh `owner ... --human` có kết quả ngắn và mã thoát đúng; mặc định JSON cũ giữ nguyên. Không tự duyệt trong phiên AI. Chỉ đưa lệnh nghiệm thu khi đủ artifact/revision có nguồn; thiếu thì giải thích và đưa lệnh xem báo cáo.
- Tổng quan, Solution, Thay đổi, Kết quả & kiểm chứng, Tiến độ/Gantt dùng lại dữ liệu sẵn có. Đầu ra hiện hành đứng trước lịch sử; chuỗi kiểm → giao sửa → kiểm lại có liên kết. Pass cũ không chứng nhận đầu ra mới.

## Thử nhanh

| Thao tác | Mong đợi |
|---|---|
| Bảng → CODE | Đang xử lý, nhãn chờ duyệt kế hoạch; 1 quyết định cần bạn |
| Bảng → DOC | Chờ kiểm, không có quyết định dành cho bạn |
| CODE → thẻ Duyệt kế hoạch | Thấy bản 2, nội dung/lý do/ảnh hưởng; mở Thay đổi trước khi quyết định |
| Sao chép lệnh | Có phản hồi sao chép; sổ vẫn chờ duyệt. Điền phần đánh dấu rồi tự chạy trong PowerShell khi muốn thử quyết định trên sổ mẫu |
| CODE → Solution/Thay đổi | Bản đề xuất 2 khác bản đã duyệt/có thể thực hiện 1; lịch sử nội bộ có số riêng |
| CODE → Kết quả & kiểm chứng | Mở đầu ra; cuộn xem fail/finding/giao sửa/kiểm lại; không coi số lượt kiểm là số bug |
| DOC → Kết quả & kiểm chứng | Đầu ra mới chưa kiểm, pass cũ nằm trong lịch sử |

## Snapshot và bằng chứng

- Product commit: `ff81554de7f3a99ae0bdc9d0fc9ef1cfc0f791c9`; version `2.5.0.dev3`.
- Gói: `D:/OneCrewRuns/obs2/pkg/onecrew-2.5.0.dev3-obs2-ff81554`.
- Wheel SHA256: `a3ef09d2c5ac16da2631dfafe0a078b084a0a89a83e0debc61adf95002fc3869`.
- Trial: `D:/OneCrewRuns/obs2/trial-ff81554-1`.
- `verify-report.json`: **9/9**; tám module nhập từ venv đúng hash, CLI/API/evidence, read-only, mở/dùng lại/dừng; mười lượt đọc fixture nhỏ p50 0,053s, max 0,073s. Không suy hiệu năng sổ lớn.
- `browser/browser-report.json`: **90/90**, 45 mỗi cỡ 1280×720 và 390×844. Ảnh board/overview/solution/results/decision đã xem trực tiếp. Browser stop đúng instance.
- `lifecycle-report.json`: **4/4**, mở/dùng lại/dừng/dừng lần nữa với mã thoát mong đợi; state/project/gói/registry không đổi trong khoảng kiểm.
- `D:/OneCrewRuns/obs2/owner-human-wheel-ff81554-1/owner-human-report.json`: hai entrypoint JSON/human từ chối đúng trong phiên AI, exit2, không ghi approval hoặc đổi sổ. Thao tác chủ thành công được kiểm qua fixture ở source, chưa có thao tác người thật trên wheel này.
- Source cuối: renderer/cards **25/25**, cộng ca G2 được sửa cách ly **1/1**. Các suite owner13/13, dữ liệu/acceptance/replay/phản chứng A-pass/B-fail đã đạt qua các lượt tập trung; không cộng các lượt trùng thành số test duy nhất.
- Hồi quy OBS-1 Source/Engine **18/18** và sáu lượt Gantt/slow25/switch/timeout đạt trước các chỉnh cuối về nhóm thẻ, nhãn và thu gọn. Đường timeout/poll không đổi sau đó; final browser ở trên kiểm trên wheel cuối. Không chạy full gate 2.2.

Manifest giữ nguyên trạng thái lúc build; receipt sau build nằm ngoài gói. Hai gói dev3 trước `025c8ca` và `47fc8f3` giữ làm bằng chứng trung gian, không phải bản giao này. Review ảnh phát hiện trường hợp pending amendment bị xếp theo pass cũ và khối quyết định chiếm màn hình; đã thêm phản chứng và kiểm bản cuối.

## Cách ly và sự cố test đã khôi phục

Runtime SignSDK vẫn `2.3.0.dev11`; không nâng hook/venv/sổ công việc. Một test G2 lịch sử đã đăng ký project tạm vào registry host vì không cô lập LOCALAPPDATA. Đã xác định đường gọi, chỉ loại đúng mục fixture và khôi phục byte-for-byte hash ban đầu `AACAD058F478898D41EB0294B619BE21191B83B488544961C080F4BFA0AEE01C`. Fixture G2 nay cô lập LOCALAPPDATA/APPDATA; chạy lại ca gây rò đạt, hash host không đổi. Báo cáo: `D:/OneCrewRuns/obs2/isolation-recovery/recovery-report.json`. Không tuyên bố registry chưa từng bị chạm; kiểm gói/lifecycle cuối xác nhận hash ban đầu ổn định.

Giới hạn: dữ liệu mẫu, chưa provider/pilot/sổ lớn, chưa chứng minh clipboard của trình duyệt thật của người dùng (harness kiểm nội dung đúng hoặc thông báo thất bại rõ), chưa thao tác duyệt thật trên wheel. UI chỉ theo dõi nguồn có trong sổ; không tự theo dõi mọi phiên chat. Cột/thẻ không là cơ chế đổi quyền. MR-R giữ checkpoint riêng; CP-1 chưa triển khai trong lượt này.
