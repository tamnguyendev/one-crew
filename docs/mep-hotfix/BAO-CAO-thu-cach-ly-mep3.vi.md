# Thử cách ly hotfix `inputs` trên máy MEP, 07/11/2026

Chế độ: **Delivery**, thử cách ly. Không đụng runtime, source, hook, sổ hay plan MEP thật.
Nền: nhánh `claude/mep-hotfix-verifier-inputs-m2`, tách từ `f204a33` (`claude/hotfix-verifier-inputs`).

Đây là kết quả **thử cách ly**, không phải MEP đã nâng cấp. MEP vẫn chạy `onecrew 2.5.0.dev10`. Plan M1 thật chưa khai `inputs`.

## Kết luận

- **M1 qua `verdict run` có `inputs`, có receipt.**
  - Trên lab (bản chép một phần repo MEP): 2,5 đến 4,3 s, so với 131 đến 146 s ở đường cũ.
  - `.git` thêm 3 đến 14 object; thư mục tạm còn 0 byte sau lượt.
  - Duyệt plan có `inputs`: 2,1 s, so với 240 s ở đường cũ.
- **Tái sử dụng bản sửa `f204a33` (mep1); không viết lại.** Có bảy chỗ thêm:
  - mep2: bốn chỗ;
  - mep3: hai lỗi tìm thấy khi đo trên lab;
  - một test cũ sai lý do đã được viết lại.
- **Ca phản chứng chạy thật qua CLI của wheel:**
  - mep1 cho **đạt giả** khi lệnh đọc hoặc ghi cây thật bằng đường dẫn tuyệt đối;
  - mep2 và mep3 từ chối trước khi gọi verifier.

## Số đo (lab, máy MEP, cùng lab, cùng ổ C:)

Lab:
- 11.237 tệp, 2,30 GB, 129 tệp được theo dõi.
- Lấy mẫu 10% tên tệp của repo MEP, cộng đủ input của M1.
- Ngoài cây harness, không worktree, không hardlink.

M1 có 26 input khai báo, checkout ra 27 tệp, 5,3 MB.

| Lượt | Bản | Tổng (s) | Chụp trước | Checkout | Verifier | Chụp sau | Tệp checkout | `.git` thêm | Tạm còn lại |
|---|---|---|---|---|---|---|---|---|---|
| Đường cũ | mep1 | 131,5 | 19,5 | 26,1 | 0,1 | 66,1 | 11.246 | 0 | **65 MB** |
| Đường cũ, lặp liền | mep1 | 145,7 | 20,1 | 26,0 | 0,1 | 57,6 | 11.249 | 0 | **67,5 MB** |
| Đường cũ, lặp liền | mep3 | 140,8 | 19,9 | 25,6 | 0,1 | 56,3 | 11.249 | 0 | 0 |
| `inputs` | mep1 | 2,5 | 0,41 | 0,20 | 0,09 | 0,31 | 27 | +14 object | 0 |
| `inputs` | mep2 | 4,3 | 0,36 | 0,19 | 0,05 | 0,30 | 27 | +3 object | 0 |
| `inputs` | mep3 | 7,8 | 0,38 | 0,19 | 0,09 | 0,33 | 27 | +3 object | 0 |

- **Bộ đệm:** ấm. `owner approve` của chủ dự án vừa băm toàn cây lab, nên chưa đo lạnh: muốn đo lạnh phải khởi động lại máy.
- **mep3, lượt `inputs` 7,8 s:** đây là lượt đầu của venv mới. Các bước bên trong OneCrew ngang mep2; phần chênh nằm ngoài các bước đó.
- **Lượt đường cũ mep3 đầu tiên** đo 256,7 s, trong đó chụp sau 173 s.
  - Chạy lại liền nhau với mep1 thì hai bản ngang nhau (bảng trên); mep3 không đổi mã chụp.
  - Lượt 256,7 s được giữ trong `bang-chung-mep3/luot.json`.
- **Duyệt plan:** do chủ dự án chạy với mep1.
  - `lab-m1-inputs` 2,1 s; `lab-tien-trinh` 0,6 s; `lab-m1-cu` 240 s.
  - Sau ba lần duyệt, `.git` của lab từ 6,4 MiB lên 17.267 object rời, 722 MiB. Gần như toàn bộ là lần duyệt đường cũ.
- **Mỗi lượt có:** `LOCALAPPDATA`, `APPDATA`, `TEMP` riêng; số object `.git` trước và sau; kích thước thư mục tạm sau lượt.

Số liệu đầy đủ từng lượt, đã làm sạch: `bang-chung-mep3/luot.json` (44 lượt, gồm 17 lượt E2E).

## Ca kiểm qua CLI của wheel đã cài

| Ca | mep1 (`f204a33`) | mep2 / mep3 |
|---|---|---|
| M1 có `inputs`, receipt hợp lệ | đạt, `input_scope` 27 tệp | đạt; mep3: `live_tree_scan` 27/0, `contained` true, `left_running` 0 |
| Đổi một input | chưa thử trên lab | mep2: M1 về `pending` |
| Đổi kịch bản kiểm (cũng là input) | chưa thử trên lab | mep2: M1 về `pending` |
| Đổi tệp có sẵn hoặc thêm tệp ngoài input | chưa thử trên lab | mep2: M1 vẫn `passed` (mục đích của hotfix) |
| Lệnh **đọc** cây thật bằng đường dẫn tuyệt đối | **đạt**; tệp được đọc đổi sang nội dung làm lệnh trượt mà mốc vẫn `passed` (đạt giả) | từ chối trước verifier |
| Lệnh **ghi** cây thật bằng đường dẫn tuyệt đối | **đạt**, tệp ngoài input bị ghi, không bằng chứng nào thấy | từ chối trước verifier |
| Input khai mà không có | từ chối trước verifier | từ chối trước verifier |
| Input bị đổi trong lúc lệnh chạy (ngủ 25 s) | `inconclusive`, không đạt | `inconclusive`, không đạt |
| Hết giờ (1 phút), lệnh có tiến trình con ngủ 600 s | cả hai tiến trình kết thúc | như mep1; mep3 ghi `left_running` 3 |
| Giết cứng tiến trình OneCrew giữa lượt | **2 tiến trình mồ côi** còn chạy sau 10 s; phải dừng tay | mep2: 0 tiến trình còn sống sau 10 s |
| `verdict run` lại sau khi giết cứng | từ chối: run không rõ kết quả bị giữ, không tự chạy lại | như mep1 |

- **Phát hành run bị giữ:** cả hai run bị giết cứng được phát hành bằng `verdict release-run`, có lý do ghi trong sổ lab; actor là AI.
- **Plan `lab-tien-trinh` tự dừng:** sau ba lượt hết giờ `inconclusive` (mep1, mep2, mep3), nó chuyển `stopped_with_report` theo `max_repairs` của nó. Ca giết cứng trên mep3 được chạy trong plan `lab-e2e-mep3` (mục E2E).
- **Plan không `inputs`:** giữ đường cũ (toàn cây, không `input_scope`). Có kiểm trên lab (bảng số đo) và test `test_without_inputs_the_old_path_is_unchanged`.

## E2E đủ ca trên wheel mep3 (08/11, plan lab `lab-e2e-mep3`)

Theo yêu cầu của chủ dự án: chạy E2E đủ ca trên bản cuối rồi mới push.
- Plan lab mới: rev 1, sha `83b29e48c61248258726ae482c81b3b7b730ef1ba99a698628defc3e5a275538`.
- Chủ dự án duyệt bằng mep3: 0,7 s.
- Mọi lượt chạy qua `onecrew.exe` của venv cài wheel mep3.
- **Kết quả: cả 5 mốc `passed`.**

| Mốc | Ca | Kết quả |
|---|---|---|
| M1 | Bộ kiểm M1 của MEP (bản chép), 26 input | đạt 4,6 s; 27 tệp; `live_tree_scan` 27/0; `left_running` 0; tạm 0 byte |
| M1 | Đổi tệp ngoài input / đổi input / đổi kịch bản | vẫn `passed` / `pending` / `pending`; chạy lại đạt 4,2 s và 4,1 s |
| M2 | Lệnh đọc cây thật bằng đường dẫn tuyệt đối | từ chối trước verifier; sửa sang đường tương đối thì đạt |
| M3 | Lệnh ghi cây thật bằng đường dẫn tuyệt đối | từ chối trước verifier, không tệp nào bị ghi vào cây; sửa sang ghi trong thư mục làm việc thì đạt |
| M4 | Input khai mà không có | từ chối trước verifier; tạo tệp thì đạt |
| M5 | Hết giờ (1 phút), lệnh có tiến trình con | `inconclusive`; cả hai tiến trình kết thúc; `left_running` 3 |
| M5 | Giết cứng tiến trình OneCrew giữa lượt | sau 10 s không còn tiến trình verifier nào; chạy lại bị từ chối (run bị giữ); phát hành bằng `verdict release-run` có lý do |
| M5 | Lần chạy sau trong cùng `TEMP` | thư mục tạm có dấu của lượt bị giết được dọn trong khoảng 1 s; sau lượt `TEMP` trống |
| M5 | Input bị đổi giữa lượt | `inconclusive`, không đạt |
| M5 | Lệnh thoát 0, tiến trình con còn chạy | đạt; `left_running` 2 (tiến trình con và console host của nó); sau lượt không còn tiến trình nào |

Sự cố của người thử, không phải của mep3:
- **M3:** lần chạy lại đầu trượt (thoát 1) vì `printf` của tôi làm hỏng `ghi.py`. Tốn 1/3 lần sửa; viết lại tệp thì đạt.
- **M5:** một lượt giết cứng không được giết, vì lệnh chạy sai thư mục, nên thành lượt hết giờ thứ hai.
- **Công cụ đo giết cứng tự đếm chính nó:** dòng lệnh của nó chứa mẫu tên. Hai tiến trình «còn sống» trong `giet_cung_e2e_mep3.json` là chính công cụ đó. Đã loại tiến trình của công cụ rồi chạy lại: `giet_cung_e2e_mep3_c.json` ghi 0 tiến trình còn sống.
- **`seconds` của receipt:** có cả thời gian chờ đếm (tối đa 0,5 s) khi còn tiến trình con. Lượt `con_roi_thoat` ghi 0,58 s.

Bằng chứng:
- `bang-chung-mep3/luot.json`: 44 lượt, trong đó 17 lượt `E_*`.
- `bang-chung-mep3/giet_cung/`: bốn lần giết cứng (mep1, mep2, hai lần mep3).
- Lượt «input đổi giữa lượt» chạy thẳng CLI với `TEMP` của lượt bị giết, nên không có trong `luot.json`. Receipt `50750e8b2c2a2766e032fbaf05f01365a78977790e14b1186c92b4e1d3e89b9c`.

## Thay đổi so với `f204a33`

**mep2**
1. **Đường dẫn tuyệt đối vào cây thật bị từ chối trước verifier.** Áp dụng cho:
   - từ dòng lệnh, kể cả đường chưa tồn tại và dạng `--ra=`;
   - nội dung tệp văn bản trong checkout của inputs.

   Nhận cả `\`, `/`, `\\`, `/c/…`, `/mnt/c`, `/cygdrive/c`, tên 8.3, và không phân biệt hoa thường. mep1 chỉ xét đường có thật trong dòng lệnh.
2. **Windows: lệnh và mọi tiến trình con trong một job object** (`KILL_ON_JOB_CLOSE`). Lệnh khởi động treo, vào job rồi mới chạy. OneCrew chết thì cả cây chết.
3. **Test mới: input bị đổi giữa lượt trên đường `inputs`.** mep1 chỉ thử ca này trên đường cũ.
4. **`os.uname`** không có trên Windows: dùng `COMPUTERNAME` hoặc `platform.node()`.

**mep3** (tìm thấy khi đo trên lab)

5. **Xoá thư mục tạm của checkout không còn để lại rác.** Lỗi có từ trước hotfix (cùng dòng ở `9df359a`):
   - mỗi lượt đường cũ để lại 646 tệp, 65 MB, tên dài quá 260 ký tự;
   - `rmtree(ignore_errors=True)` bỏ qua im lặng;
   - dấu chủ bị xoá trước nên lần sau cũng không dọn.

   mep3 xoá qua tiền tố `\\?\` và gỡ thuộc tính chỉ đọc. Phần không xoá được thì gắn lại dấu chủ để lần chạy sau dọn.
6. **`left_running` của mep2 ghi 1 cho mọi lượt sạch.** Đó là tiến trình console host của hệ điều hành, còn trong job dưới 50 ms sau khi lệnh thoát.
   - mep3 chờ tối đa 0,5 s cho số này về 0 rồi mới ghi.
   - Đo: không chờ thì test trượt 3/3 lần.
7. **Test `tiến trình con còn chạy` của mep2 đạt sai lý do:**
   - tiến trình con thừa hưởng ống stdout nên lượt chờ nó 120 s;
   - số 1 trong receipt là console host, không phải tiến trình con.

   Test được viết lại với tiến trình con không giữ ống ra, và kiểm lượt không chờ nó.

**Test đột biến:**
- trả lại cách xoá cũ: 3/3 test mới trượt;
- bỏ phần chờ đếm: test mới trượt 3/3 lần chạy.

## Wheel

| Bản | Tên | sha256 | Đối chiếu với checkout |
|---|---|---|---|
| mep1 (dựng lại từ `f204a33`) | `onecrew-2.5.0.dev10+sol6.4.mep1-py3-none-any.whl` | `fcfa66c28f3d829c07dc1360fdab940831fe141ac44770751b7569cd5d5ddae3` | 145/145 tệp khớp |
| mep2 (chỉ dùng trong lab) | `onecrew-2.5.0.dev10+sol6.4.mep2-py3-none-any.whl` | `4dcd6c703f6ce6631f432a54f679252512688f473dacfed482fee177b29236d2` | 145/145 tệp khớp |
| **mep3 (cuối)** | `onecrew-2.5.0.dev10+sol6.4.mep3-py3-none-any.whl` | `964029b2df9b94ab52fd69cc696524c859626fe1049c43f44c28017e271d0330` | 145/145 tệp khớp |

- **sha mep1 khác bản tác giả nêu** (`431f7696…`). Nội dung 145 tệp trùng `f204a33`. Không có wheel của tác giả để so: khả năng chênh do dấu thời gian trong zip, chưa kiểm.
- **Bản build** dùng build isolation của pip, tải `setuptools` từ PyPI.
- **Không có bản nào được phát hành hay gắn tag.**

## Test tập trung

Tám module:
- `test_hf_mep2_live_tree`, `test_hf_verifier_inputs`, `test_hf_snapshot_budget`;
- `test_sol_snapshot_cleanup`, `test_v2_verifier_rules`, `test_v2_l1`;
- `test_v2_trust_fixes`, `test_sol6_recovery`.

Kết quả:
- **mep2:** 245 test, 1 trượt.
- **mep3:** 249 test trong 1.459 s, 1 trượt; tóm tắt ở `bang-chung-mep3/test_tap_trung.txt`.

Test trượt là `test_v2_l1.LatestVerdictTests.test_accept_needs_every_milestone_to_pass_on_the_accepted_artifact` («M1: artifact changed» thay vì «M1 passed on …»). Nó trượt y hệt trên `f204a33` và `9df359a`: có từ trước hotfix, không sửa ở đây.

Không chạy full gate.

## Chưa kiểm, giới hạn còn lại

- **Đường dẫn ngoài lab:**
  - đường tuyệt đối ra ngoài repo (ví dụ thư mục dữ liệu khác trên ổ C:) không bị từ chối, và không nằm trong bằng chứng; đường cũ cũng vậy;
  - M1 thật kiểm sự tồn tại của bảy đường dẫn như thế.
- **Đường dẫn dựng lúc chạy không bị bắt:** từ biến môi trường, từ tệp ngoài repo, qua junction, hay chuỗi trong tệp nhị phân.
- **Ngoài Windows:** không có job object, nên tiến trình con có thể còn sau khi OneCrew bị giết cứng. Chưa thử Linux hay macOS.
- **Tiến trình con giữ ống ra của lệnh:** lượt chờ nó tới `max_minutes`, như bản cũ.
- **Chưa đo:** lạnh bộ đệm; repo MEP thật.
- **Plan trộn** mốc có và không có `inputs`: chưa thử trên lab.
- **Còn lại trong `%TEMP%`:** ba thư mục do lần chạy test đột biến tạo. Tên dài, chưa xoá, vì quy tắc phiên cấm xoá.

## Tác động lên MEP thật

- **So mốc bảo vệ trước và sau** (07/11 16:44; sau đo 07/11 21:53; sau E2E 08/11 00:16):
  - runtime thật vẫn `onecrew 2.5.0.dev10`;
  - HEAD và số tệp tracked đang đổi không đổi;
  - plan thật, cấu hình hook và sổ thật không đổi.
- **Tệp duy nhất đổi:** `.onecrew/active-plan.json`, do hook thật (chế độ `log`) tự xuất lại trong phiên. Chỉ trường `exported_at` đổi, cùng kích thước. Lab không ghi tệp này.

## Bước tiếp, cần chủ dự án

1. Xem nhánh này; quyết có gộp hay không. AI không gộp, không gắn tag.
2. Nếu muốn M1 thật dùng `inputs`:
   - `plan amend` plan M1 với 26 input như lab;
   - chủ dự án duyệt lại;
   - cài wheel mep3 vào một venv mới rồi đổi hook sang đó. Đây là việc riêng, chưa làm.
3. Quyết việc với lỗi có từ trước của `test_v2_l1`.
