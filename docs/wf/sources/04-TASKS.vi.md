# Task breakdown — chương trình workflow chung (WF), chia theo release

**Trạng thái:** mọi task ở trạng thái `thiết kế` (đã lập, chưa làm). **Bản 3, 23/10:** chia lại theo release của [ROADMAP](../ROADMAP.vi.md#7-dependency-và-ánh-xạ-wf-cũ) (R00…R08, RP, RX), sửa theo review 23/10 F1–F6 ([06 §0d](06-TRUY-VET-VA-TU-KIEM.vi.md#0d-checklist-đồng-bộ-roadmap-chung-2310-f1f6)). Thứ tự mốc WF-M1…WF-M5 của bản 2 không còn dùng; mọi ID task cũ có dòng ánh xạ ở [cuối file](#ánh-xạ-62-id-task-cũ).
- **Một quyền chương trình, một nghiệm thu tổng** ([03 §2](03-HOP-DONG-DRAFT.vi.md#2-bốn-lớp-quyền-và-quyền-cấp-của-chương-trình)). Release là phạm vi giao, không phải một hợp đồng: giao bản dùng thử của một release, qua cổng giao hay qua kiểm tích hợp **không** tạo lần duyệt hay request mới. Task chỉ bắt đầu sau khi hợp đồng chương trình được duyệt, trừ WK0 (viết trong bước trình vì sha256 của nó nằm trong hợp đồng).
- File này là **kế hoạch nội bộ**. Sau khi chương trình được duyệt, người điều phối được chia, gộp, đổi thứ tự task hay đổi thứ tự release trong dependency (Q1) mà không cần duyệt, với điều kiện ghi nhật ký lý do và không đổi acceptance, quyền, tổng ngân sách hay cổng bắt buộc ([03 §2.3](03-HOP-DONG-DRAFT.vi.md#23-chế-độ-chuyển-tiếp-chạy-chương-trình-bằng-năng-lực-v2-hiện-có)).
- Task không đồng nhất với một agent hay một lần gọi model. Worker chọn cách làm trong task (Q3).
- Ước lượng là **khoảng thời gian thực thi** của một worker. Trần **2 giờ mỗi task** (HD-13) là chính sách đề xuất, đo lại ở pilot, **không phải benchmark**. Task có cận trên bằng trần phải ghi cách chia ở cột "Dừng/chia khi".
- Không task nào reset ngân sách hay deadline (HD-14).

## Quy ước chung

**Phụ thuộc vào bộ kiểm.** Mỗi task triển khai phụ thuộc (bắc cầu) bộ kiểm có phần testcase DoD của nó: phần đó phải là test chạy được trước khi code (HD-39). Mỗi release có bộ kiểm riêng (WKnn); không chép cả kit vào mọi task.
- Chuẩn bị test chỉ phụ thuộc acceptance, nên bộ kiểm của release chạy **song song** với khảo sát và với release khác.
- Review độc lập chạy trên artifact `produced` của release (HD-16), không đợi mọi task của chương trình.

**Bốn loại thay đổi và bằng chứng hợp lệ (HD-39).** Mỗi phần testcase ở [05](05-TESTCASES.vi.md) khai một loại. Bằng chứng đòi theo loại, không theo một khuôn chung "đỏ trước".

| Loại thay đổi | Bằng chứng hợp lệ | Không phải bằng chứng |
|---|---|---|
| `sửa lỗi` | Đỏ trên mã trước sửa **vì đúng lỗi** (assert hành vi hay thông điệp của lỗi), xanh sau sửa trên artifact của commit | Đỏ vì import, thiếu môi trường, harness hỏng hay timeout hạ tầng |
| `năng lực mới` | Xanh trên bản triển khai; **đỏ trên ít nhất một bản phản chứng** vi phạm đúng assertion (mutant, stub trả sai) | "Đỏ vì chưa có module"; chỉ xanh trên fixture mà không có phản chứng |
| `tái sử dụng/hồi quy` | Test hiện có của thành phần xanh trước và sau. Nếu có nối mới: kiểm tích hợp xanh, và đỏ khi nối sai hoặc không gọi hàm được dùng lại | Ép tạo baseline đỏ cho hành vi vốn đúng; chép logic sang module mới rồi gọi là tái sử dụng |
| `kiến trúc/tài liệu` | Phương pháp kiểm đã đặc tả (rà có tiêu chí, script), và phản chứng chèn vi phạm bị bắt | "Đã rà" mà không có tiêu chí hay phản chứng |

- ERROR (lỗi import, môi trường, harness, hạ tầng) không bao giờ được tính là đỏ hay xanh.
- Phản chứng của **bộ kiểm** (selftest: bản sửa thiếu, bản sửa quá mức) là bằng chứng về chất lượng bộ kiểm. Nó tách khỏi lỗi sản phẩm và không thay bằng chứng của sản phẩm.

**DoD chung cho task triển khai:**
1. Mọi phần testcase của task đạt theo loại thay đổi của phần đó, trên artifact của commit đó.
2. Test hiện có của các thành phần chạm vào (cột "Dùng lại", xem [02 §3](02-TAI-SU-DUNG-V1-V2.vi.md#3-hành-vi-và-bất-biến-phải-giữ-khi-dùng-lại)) không hỏng mới. Lỗi baseline đã biết ghi riêng.
3. Tài liệu của thành phần (docs, CHANGELOG) mô tả đúng hành vi mới.
4. Quyết định trong task ghi theo HD-05. Trong chế độ chuyển tiếp, ghi ở nhật ký quyết định của chương trình.
5. Task dùng lại thành phần v1/v2 **không** bị buộc viết lại hay tạo baseline đỏ. Nó done khi test hiện có xanh và kiểm tích hợp (nếu có nối mới) đạt, kể cả phản chứng "nối sai".
6. Phần đóng gói của release (W40-Rnn, hay W40, W41 ở R00) chạy sau mọi task khác của release đó; release không giao được khi task đóng gói chưa xong.

**Không được đánh dấu done khi:**
- thiếu bằng chứng đúng loại thay đổi;
- bằng chứng thuộc artifact khác;
- testcase bị nới, hoặc bộ kiểm bị worker triển khai sửa;
- ERROR được tính là xanh hay đỏ;
- mock được tính là bằng chứng tích hợp.

Task done **không** có nghĩa là release giao được. Release cần cổng giao của nó ([03 §4](03-HOP-DONG-DRAFT.vi.md#4-release-và-cổng-nội-bộ)).

**Bằng chứng chung cần thu:** commit; artifact; biên nhận bộ kiểm (gồm hash bộ kiểm hay manifest); danh sách test đã chạy và kết quả; bản ghi quyết định.

**DoD cho task khảo sát (S):**
- Câu hỏi được trả lời bằng bằng chứng, hoặc xác định được blocker (HD-10).
- Có giới hạn thời gian, chỉ đọc, không cài đặt, không gọi model trả phí.
- Kết quả ghi vào tài liệu nguồn (file 00, 01 hoặc 02), kèm `file:dòng`.
- Kết luận khác giả thuyết ban đầu vẫn là thành công.

**DoD cho task bộ kiểm (WK):**
- Mỗi phần testcase của release thành test chạy được, đòi bằng chứng đúng loại thay đổi của phần (bảng trên).
- Selftest có phản chứng: với phần `sửa lỗi` và `năng lực mới`, một bản sửa thiếu và một bản sửa quá mức đều bị bắt; với phần `tái sử dụng/hồi quy`, bản "nối sai" bị bắt.
- ERROR không tính là đỏ.
- Kit đăng ký với kit-guard (WK0): manifest sha256, chỉ được thêm sau khi đóng băng, có provenance.
- Mỗi lệnh kit xong trong 50 phút trên máy này (trần của v2 là 60 phút một lệnh; quá thì timeout, thành `inconclusive`). Vượt thì chia kit thành hai lệnh của cùng release, không bỏ ca và không dời ca sang release khác.
- Phần ghi "chỉ chứng minh giao diện/quyền" được dùng mock. Phần ghi "tích hợp" phải chạy thành phần thật.
- Không sửa mã sản phẩm.
- Người làm: người điều phối hoặc worker kit, **không phải** worker triển khai của release.

**Điều kiện dừng mặc định của mọi task** (cột "Dừng/chia khi" ghi "mặc định" hay ghi thêm điều kiện riêng):
1. Đạt DoD trên artifact của commit: dừng, không làm thêm ngoài acceptance (cải thiện tùy chọn ghi vào backlog).
2. Chạm trần thời gian: dừng ở điểm an toàn, ghi phần đã làm và bằng chứng, chia task theo gợi ý ở cột đó (Q1, không cần duyệt).
3. Blocker có bằng chứng (thiếu quyền, unknown chặn, lỗi môi trường): giữ đúng phần phụ thuộc, tiếp tục phần độc lập; chỉ hỏi chủ sở hữu khi là U1–U4.
4. Hàm định tái dùng không đáp ứng: ghi bằng chứng vì sao, replan trong quyền; không viết engine hay store thứ hai.

**Ai sở hữu một phần testcase.** Mỗi phần testcase có **đúng một chủ**, thuộc một trong bốn loại:
- **DoD của một task**: ghi ở đầu cột "Testcase trước". Phần đó phải đạt khi task xong. Mọi task khác trong "Năng lực cần" của phần phải nằm trong bao đóng phụ thuộc của task (xong trước nó). Chính task được kiểm thì được phép có mặt.
- **Cổng vào của một giai đoạn pilot** (PL-A, PL-B): ghi sau chữ "cổng vào:". Phần đó phải đạt **trước khi** giai đoạn bắt đầu; nó không được cần chính task đó hay task nào phụ thuộc task đó.
- **Cổng giao của một release** (CG-Rnn) hay cổng cuối (CG-KET): bảng "Cổng" ở dưới. Phần kiểm chung nhiều task của cùng release, chạy sau khi mọi task nó cần đã xong.
- **Kiểm tích hợp** (KN-…): phần cần năng lực của hai release mà không release nào là tổ tiên của release kia. Nó không thuộc DoD hay cổng giao của release nào, chạy khi bản dựng có đủ hai release, và cổng cuối đòi nó.
Task chỉ góp năng lực cho một phần do chủ khác sở hữu thì ghi phần đó sau chữ "kiểm chung:". Mỗi task triển khai có ít nhất một phần DoD riêng. Kiểm bằng K-DOD ([06 §5](06-TRUY-VET-VA-TU-KIEM.vi.md#5-kết-quả-tự-kiểm-tài-liệu)).

**Dependency giữa release.** Task của release X chỉ phụ thuộc task của X hay của release tổ tiên của X (bảng dưới). Phần testcase của X chỉ cần task của X hay tổ tiên. Không release sớm nào phụ thuộc ngầm release sau; không release nào của chương trình phụ thuộc nhánh hoãn. Kiểm bằng K-REL. Cột "Phụ thuộc" ghi task cụ thể; "—" là không phụ thuộc.

---

## Release và dependency

Bảng này phải khớp [ROADMAP §7](../ROADMAP.vi.md#7-dependency-và-ánh-xạ-wf-cũ) (K-REL so hai chiều). RX được chia thành hai lát giao độc lập: RX1 (tài liệu), RX2 (dữ liệu, vận hành). Phần P0/P0b của R00 là hai hợp đồng đang chạy, không phải task ở đây.

| Release | Loại | Cần trước | Kết quả dùng được | Cổng |
|---|---|---|---|---|
| R00 | release | — (P0/P0b ngoài WF) | Phần WF của R00: sổ loại sự kiện, kiểm tên plan, `compat scan` cho root `plan:`, lỗi cố vấn có kiểu, ghi quyết định đúng chủ thể; đóng gói và diễn tập 2.1 → 2.2.x trên bản sao sổ. P0/P0b (hợp đồng riêng) đóng phần còn lại của R00 | CG-R00 |
| R01 | release | R00 | Bước 0 ngắn: một đề xuất vừa đủ có căn cứ, thẻ quyết định chung, khảo sát có trần, `plan present` và bàn giao theo acceptance | CG-R01 |
| R02 | release | R00 | Ngữ cảnh cập nhật trong lúc làm, có nguồn và nhãn tin cậy; hai phạm vi tri thức một cơ chế; outcome, can thiệp, gói tiếp tục | CG-R02 |
| R03 | release | R00, R01 | `verdict.run_started` và bốn kết cục; quan sát có nguồn; baseline, phần còn lại, phát sinh, ETA có lý do; thông báo việc cần chủ sở hữu và thông báo ngoại lệ; câu trả lời được ghi kèm lựa chọn (áp thành trạng thái ở R05); số đo từ sổ | CG-R03 |
| R04 | release | R00 | Quyền cấp và kế hoạch nội bộ trong một root; root chạy task tuần tự theo trạng thái; unknown có phạm vi; ngân sách không reset; namespace `plan-ns:`, một nguồn duyệt, một writer | CG-R04 |
| R05 | release | R04, R03 | Kiểm trước implementation; finding theo artifact; sửa ca hỏng trước rồi phần ảnh hưởng; dừng vòng không tiến triển mà không dừng nhầm; quyết định review theo quy tắc; reconcile trước retry; câu trả lời áp thành trạng thái trên root `plan-ns:` | CG-R05 |
| R06 | release | R02, R05 | Incident nối finding, attempt, giả thuyết bị bác bỏ; lesson sau khi sửa đã kiểm, dùng được trước khi root kết thúc | CG-R06 |
| R07 | release | R02 | Ảnh hay mô tả issue thành danh sách nghi phạm (file, method) có nguồn và phép kiểm tiếp; biết trả "chưa đủ dữ liệu" | CG-R07 |
| R08 | release | R03, R04, R05 | DAG dev/test/review chạy song song; review trên snapshot cố định; generation, kết quả muộn; interface executor đầy đủ; intent bền qua crash | CG-R08 |
| RP | release | R00 | Reviewer và cố vấn theo provider (Claude, Codex, Kiro) bằng CLI chỉ đọc, pin provider/model; ma trận sáu ô chạy thật | CG-RP |
| RX1 | release | R00 | RX, loại tài liệu: adapter kiểm nguồn, cấu trúc, link/ID dạng verifier của v2; lõi chặn adapter vượt quyền | CG-RX1 |
| RX2 | release | R00, RX1 | RX, loại dữ liệu và vận hành: adapter schema, đối soát, mẫu; pre/postcondition, receipt, reconcile; danh tính artifact không phải Git | CG-RX2 |
| KN-R01-R02 | kiểm tích hợp | R01, R02 | Gói tiếp tục và `plan present` dùng chung hàm so revision | KN-R01-R02 |
| KN-R02-R03 | kiểm tích hợp | R02, R03 | Gói tiếp tục không cho phiên AI quyền trả lời câu hỏi | KN-R02-R03 |
| KN-R03-R04 | kiểm tích hợp | R03, R04 | ETA còn lại dùng ước lượng task của kế hoạch nội bộ; replan trong quyền giữ baseline và ghi phát sinh | KN-R03-R04 |
| PL-A | pilot tích lũy | R02, R03, RX1 | Ba việc thật đầu tiên (code, tài liệu) trên một bản dùng thử đã qua cổng giao; báo cáo giữa kỳ theo phiên bản | cổng vào T45b |
| PL-B | pilot tích lũy | PL-A, R05, RP, RX2 | Đủ ít nhất 10 việc thật, đủ bốn loại đầu ra, có reviewer khác hãng; báo cáo AC tổng hợp | cổng vào T45c |
| KET | cổng cuối | R06, R07, R08, KN-R01-R02, KN-R02-R03, KN-R03-R04, PL-B | Chạy lại phần kiểm tự động của mọi bộ kiểm trên artifact cuối; bằng chứng dùng thật hợp lệ theo luật hiệu lực HL (trực tiếp hay kế thừa qua đối chiếu); trình nghiệm thu chương trình một lần | CG-KET |
| RD | nhánh hoãn | R05 | Decider dùng model (Jev, local), chạy bóng, quyền `SKIP` của model, `init` hỏi model local | — |
| RR | nhánh hoãn | R08 | Tài nguyên, reservation, WIP, ưu tiên | — |
| RL | nhánh hoãn | R06, PL-B | Đánh giá và kích hoạt rule có phạm vi, thu hồi | — |

---

## R00 — Nền 2.2.x: tương thích, kiểm tên, lỗi cố vấn, đóng gói

Cần trước: — (bắt đầu sau khi P0, P0b được nghiệm thu; sổ đọc 23/10: P0 rev 8 chờ M5 và nghiệm thu, P0b rev 8 `proposed`). Cổng giao: CG-R00.

| ID | Release | Gap | Kết quả cụ thể | Dùng lại | Phạm vi sửa dự kiến | Phụ thuộc | Ước lượng / trần | Testcase trước | Dừng/chia khi | Không done khi (riêng) |
|---|---|---|---|---|---|---|---|---|---|---|
| WK0 | R00 | G01, G05 | Làm trong bước trình, trước khi duyệt (03 §6). Khung kit của chương trình: kit-guard (manifest sha256, chỉ thêm sau khi đóng băng, provenance; làm yếu thì từ chối trừ khi có bản ghi U1); bộ tự kiểm tài liệu ([06 §7](06-TRUY-VET-VA-TU-KIEM.vi.md#7-phụ-lục-tái-lập-bộ-tự-kiểm)) thành lệnh kit (T38a); kiểm T39 (đếm yêu cầu gửi chủ sở hữu từ sổ và nhật ký) | Mẫu `kit-manifest-r8.json`, kiểm manifest của `g4_m1_r8.py`, `handover_check.py` | `verify-kit\wf\` | — | 1,5–2 h / 2 h | T38a, T39 | mặc định | Kit-guard cho qua một lần sửa làm yếu kỳ vọng |
| WK00 | R00 | G07, G10, G01 | Bộ kiểm R00: T09a, T13a, T13b, T20, T33a, T45a, T48a, T49a, T49b | mẫu kit, `g1_check` (wheel trong venv sạch) | `verify-kit\wf\r00_check.py` | WK0 | 1,5–2 h / 2 h | — | vượt 50 phút một lệnh → tách phần tích hợp nặng thành lệnh riêng của cùng release | Phần `năng lực mới` hay `sửa lỗi` không có phản chứng |
| W03 | R00 | G01 | Bản ghi quyết định (chủ thể thật, căn cứ, bằng chứng, phạm vi, hiệu lực); `interventions` vào wheel; từ chối `by=owner` trong phiên AI | TD26, TD01, `v2/ownership.py` | `onecrew/v2/` (module quyết định mới, nhỏ), `pyproject.toml` | WK00 | 1–1,5 h / 2 h | T20; kiểm chung: T16a | mặc định | Còn đường ghi quyết định AI mang danh owner |
| W11a | R00 | G10 | Sổ loại sự kiện trên anchor bản cũ thấy ([00 §6.1](00-THIET-KE-WORKFLOW-CHUNG.vi.md#61-ranh-giới-tương-thích-và-rollback-r2)): chỉ ghi lớp 0 (giữ mọi trường cũ, cùng kiểu) hay lớp A lên anchor `plan:`, không dùng `KINDS` của `derive()` làm danh sách cho phép; bộ so bản cũ (S, G, C, H, V) để T35a, T41b, T52 và mọi T54 dùng lại. Không crash không có nghĩa là đọc đúng | TD03 | `onecrew/v2/plan.py`, `contract.py`, bộ so trong kit | WK00 | 1–1,5 h / 2 h | T13a | mặc định | Sự kiện lớp B hay payload lớp 0 đổi dạng trên anchor `plan:` |
| W12a | R00 | G10, G01 | Kiểm tên plan trước khi ghi (từ chối `:`, ký tự đường dẫn, dạng ổ đĩa, đường dẫn tuyệt đối) ở mọi đường tạo; hai project cùng state root mà trùng tên plan thì lệnh tạo thứ hai **từ chối** và nêu project kia, không ghi gì (thay vì va nhau). Không đổi đường dẫn lưu; hỗ trợ trùng tên đầy đủ ở W12b (R04) | TD17, TD03 | `onecrew/v2/contract.py`, `plan.py` | WK00 | 1–1,5 h / 2 h | T48a | mặc định | Một tên thử ghi ra ngoài state root; hai project trùng tên ghi chung một thư mục |
| W46a | R00 | G10 | Lệnh chỉ đọc `compat scan` trong wheel: mỗi root anchor `plan:` có ba tính chất (giữ nguyên, bản cũ đọc được, bản cũ tiếp tục được), trạng thái theo luật bản cũ, loại sự kiện theo lớp, và điều kiện chặn **tách hai loại**: chặn đọc (B4: lịch sử bản cũ không đọc được, kể cả root `accepted`) và chặn tiếp tục (B2); dự đoán cho từng lệnh của bản cũ theo bảng lệnh của T49. Bản cũ là bản rollback, không sửa, không wrapper; chạy từ venv song song; không sửa sổ, không xoá lịch sử | TD03 (reader của v2) | `onecrew/v2/` (lệnh chỉ đọc mới) | W11a, WK00 | 1,5–2 h / 2 h | T49a | vượt trần → tách: ba tính chất và lớp; điều kiện chặn | Báo "đọc thành công" cho root mà bản cũ không đọc được; coi `accepted` hay tạm dừng là đã giải phóng điều kiện chặn đọc; ghi vào sổ |
| W27a | R00 | G07 | Lỗi provider của **cố vấn** có kiểu (không dùng được, quá giờ, sai schema): verdict `inconclusive` kèm lý do, **không** còn thành `advice_missing` chặn duyệt (`v2:step0.py:265-270`); không đổi provider đã pin | TD19, TD21 | `onecrew/v2/step0.py`, `verifiers/` | WK00 | 1–1,5 h / 2 h | T09a | mặc định | Lỗi provider làm người dùng phải chạy thêm một vòng duyệt |
| W40 | R00 | G10 | Khung đóng gói và kiểm bản cài, dùng lại cho mọi release: module cần thiết vào wheel (hoặc tách module mới để tránh `V1_ONLY`); kịch bản của R00 chạy bằng lệnh của bản cài đặt; kiểm ranh giới module lúc chạy (T33a): tên theo `shipped()` của `test_g1_core` (gồm package cha) và `RECORD`, mốc stdlib suy từ interpreter, không miễn module nạp lúc khởi động | TD18, TD22, TD26, TD27; `tests/test_g1_core.py` | `pyproject.toml`, module tách, kịch bản trong kit | W03, W11a, W12a, W46a, W27a, WK00 | 1,5–2 h / 2 h | T33a | mặc định | Kịch bản chỉ chạy từ checkout; báo nhầm package cha hay extension chuẩn ngoài `Lib` |
| W41 | R00 | G10 | Khung diễn tập nâng cấp, rollback và roll-forward trên **bản sao** sổ, dùng lại cho mọi release; ở R00 là 2.1 → 2.2.x. `compat scan` (W46a) chạy từ venv song song; kịch bản rollback từ chối khi còn bất kỳ điều kiện chặn nào (đọc hay tiếp tục) và chỉ chạy khi lần scan cuối báo 0; nhánh từ chối và nhánh thành công tách riêng (T49b) | TD03 | kịch bản trong bộ kiểm | W40, W46a | 1–2 h / 2 h | T13b, T49b | mặc định | Đụng tới sổ thật; rollback khi còn điều kiện chặn hay dựa vào lần scan cũ |

---

## R01 — Bước 0 ngắn, giải pháp vừa đủ, bàn giao dễ đọc

Cần trước: R00. Cổng giao: CG-R01.

| ID | Release | Gap | Kết quả cụ thể | Dùng lại | Phạm vi sửa dự kiến | Phụ thuộc | Ước lượng / trần | Testcase trước | Dừng/chia khi | Không done khi (riêng) |
|---|---|---|---|---|---|---|---|---|---|---|
| WK01 | R01 | G02, G11 | Bộ kiểm R01: T24a, T27, T33b, T38b, T42, T50a, T50b, T54a | mẫu kit | `verify-kit\wf\r01_check.py` | WK0 | 1,5–2 h / 2 h | — | mặc định | Phần `năng lực mới` không có phản chứng |
| W47 | R01 | G02 | Đề xuất vừa đủ ở bước 0: một phương án ưu tiên, kết quả trước–sau, căn cứ chọn phương án ít tác động mà đủ đạt; mỗi thay đổi nối với một acceptance, ràng buộc hay dependency; cải thiện tùy chọn vào backlog; luật ngữ nghĩa phá hủy (xóa vĩnh viễn không thành ẩn; ẩn menu không đủ khi URL còn dùng được), dựa trên khai báo bắt buộc của đề xuất: loại thay đổi (xóa, ẩn, sửa) và đường vào (menu, URL, API); việc rõ trong quyền thì làm, không sinh duyệt mới | TD03 (`step0`: provenance, `options`, unknowns), TD08 (acceptance, `preserve` của `work_contract`), `solution_gate` | `onecrew/v2/step0.py`, `contract.py` | WK01, W27a | 1,5–2 h / 2 h | T50a | vượt trần → tách: nối thay đổi–acceptance; luật ngữ nghĩa phá hủy | Đề xuất bỏ một acceptance mà vẫn ghi đủ đạt; có thay đổi không nối với acceptance nào mà không vào backlog |
| W23a | R01 | G11 | Báo cáo bàn giao theo acceptance (HD-31) và `plan present` tối giản (P1.2): một trang sinh từ sổ, không gọi model (yêu cầu, kết quả bàn giao, rủi ro, cách nghiệm thu, bằng chứng còn thiếu); khi có revision chờ duyệt thì nêu phần đổi so với bản đã duyệt và lý do amend; đọc được plan cũ; khớp view chính thức (`plan show`). Finding còn mở trong bàn giao ở W23d (R05); dòng trạng thái và ETA ở W32a (R03) | TD05 | `onecrew/v2/report.py` | WK01 | 1,5–2 h / 2 h | T42, T24a, T38b | mặc định | Báo cáo ghi "đạt" cho acceptance thiếu evidence; trang không khớp `plan show` |
| W30a | R01 | G02 | Một schema thẻ quyết định (REQ/CREQ/`decisions`): vấn đề, lựa chọn, đề xuất, bằng chứng, phạm vi, mốc phải quyết; bước 0 chỉ trình lựa chọn quan trọng và gộp vào một thẻ; lựa chọn kỹ thuật trong quyền ghi bản ghi HD-05 (W03) | TD01, TD17, TD19 | `ledger.py` (registry kiểu), `v2/step0.py` | WK01, W03 | 1–1,5 h / 2 h | T50b | mặc định | Hai thẻ rời cho cùng một quyết định |
| W31a | R01 | G02, G08 | Khảo sát/PoC ở bước 0 có trần, điều kiện kết thúc, phạm vi chỉ đọc; unknown ghi `affected`, `required_by` ngay khi đề xuất | TD03 (`step0` unknown, PoC) | `onecrew/v2/step0.py`, `contract.py` | WK01 | 1–1,5 h / 2 h | T27 | mặc định | Khảo sát không có trần hay điều kiện kết thúc |
| W40-R01 | R01 | G10 | Phát hành R01: module mới vào wheel, kịch bản R01 chạy từ bản cài với kiểm ranh giới module của T33a; diễn tập nâng cấp R00 → R01 và rollback trên bản sao sổ bằng W41; diễn tập đầu-cuối một root code trên bản cài, sổ tạm, dữ liệu giả (thay P-0 cũ); ghi chú phát hành, giới hạn, cách quay lại | W40, W41 | kịch bản trong kit | W47, W23a, W30a, W31a, W40, W41 | 1–2 h / 2 h | T54a, T33b | mặc định | Kịch bản chỉ chạy từ checkout; diễn tập không chạy lại scan |

---

## R02 — Ngữ cảnh trong lúc làm, hai phạm vi tri thức

Cần trước: R00. Cổng giao: CG-R02.

| ID | Release | Gap | Kết quả cụ thể | Dùng lại | Phạm vi sửa dự kiến | Phụ thuộc | Ước lượng / trần | Testcase trước | Dừng/chia khi | Không done khi (riêng) |
|---|---|---|---|---|---|---|---|---|---|---|
| WK02 | R02 | G11 | Bộ kiểm R02: T35a, T46a, T51a, T51b, T54b | mẫu kit | `verify-kit\wf\r02_check.py` | WK0 | 1,5–2 h / 2 h | — | mặc định | Phần `năng lực mới` không có phản chứng |
| W23b | R02 | G11 | Ghi outcome (A1, cùng định dạng `learning.outcome`) cho mọi kết cục, can thiệp (A4, `control.intervention` qua `interventions.record`), gói tiếp tục chỉ đọc (A5). `learning.outcome` và `control.intervention` là lớp A của sổ loại sự kiện: chứng minh với bản cũ và với consumer v1 trên cùng sổ là DoD của task này (T35a). Số đo hiệu quả ở W23c (R03); lesson ở W49b (R06) | TD22, TD26 | module ghi outcome, CLI gói tiếp tục | W03, W11a, WK02 | 1,5–2 h / 2 h | T35a, T46a | mặc định | Outcome của root v2 làm consumer v1 lỗi hay đổi kết quả của task v1; gói tiếp tục ghi vào sổ |
| W48a | R02 | G11, G04 | Ngữ cảnh ghi trong lúc làm bằng sự kiện `context.entry` (lớp A) trên anchor, không thêm bảng hay đổi version schema của sổ (`ledger.py:183`): mỗi mục có nguồn (file:dòng@revision, symbol, biên nhận, ID sự kiện), nhãn tin cậy (quan sát / giả thuyết / đã xác minh / stale / bác bỏ), cập nhật khi có thay đổi đáng kể (quyết định, symbol đã xác minh, giả thuyết bị bác bỏ, task xong), khử trùng; root, revision, artifact, việc còn lại. Thu bằng mã, không gọi model sau mỗi thao tác | TD02 (packet có hash, `native_review_context`), TD22 (định dạng và cách ly project của `learning`; stale của v1 dựa vào `workflow.checkpoint` của runner, `learning.py:91-93`, nên stale theo revision và symbol là phần mới) | module ngữ cảnh trong wheel | W23b, WK02 | 1,5–2 h / 2 h | T51a | mặc định | Mục ngữ cảnh không có nguồn; ghi lại sau mỗi lệnh dù không có thay đổi đáng kể |
| W48b | R02 | G11 | Truy xuất ngữ cảnh hai phạm vi bằng một cơ chế: project (dữ kiện riêng) và chung (nội dung đã khái quát, có điều kiện và nguồn); không tự chuyển dữ liệu riêng sang chung; khi truy xuất kiểm revision và symbol, lệch thì "stale"; nội dung nhớ là dữ liệu, không phải lệnh hay quyền, không ghi đè hợp đồng; phiên sau tiếp tục đúng từ gói | TD22 (`learning` reader: cách ly project; stale theo revision và symbol là phần mới), TD02 | module ngữ cảnh trong wheel | W48a, WK02 | 1,5–2 h / 2 h | T51b | mặc định | Một mục của project khác xuất hiện trong truy xuất; nội dung nhớ đổi được quyền, scope hay acceptance |
| W40-R02 | R02 | G10 | Phát hành R02: theo quy trình chung của T54 (khung W40, W41 ở R00) cho phần của R02; lớp A mới (`learning.outcome`, `control.intervention`) được chứng minh trên bản cài với bản cũ là R00 | W40, W41 | kịch bản trong kit | W23b, W48a, W48b, W40, W41 | 1–2 h / 2 h | T54b | mặc định | Diễn tập dùng sổ thật |

---

## R03 — Tiến độ, phát sinh, ETA và thông báo ngoại lệ

Cần trước: R00, R01. Cổng giao: CG-R03.

| ID | Release | Gap | Kết quả cụ thể | Dùng lại | Phạm vi sửa dự kiến | Phụ thuộc | Ước lượng / trần | Testcase trước | Dừng/chia khi | Không done khi (riêng) |
|---|---|---|---|---|---|---|---|---|---|---|
| WK03 | R03 | G03, G08, G09, G11 | Bộ kiểm R03: T12, T15b, T35d, T36b, T41a, T41b, T43a, T43b, T43c, T47a, T54c | mẫu kit | `verify-kit\wf\r03_check.py` | WK0 | 1,5–2 h / 2 h | — | mặc định | Có ca gọi model thật |
| W44 | R03 | G03, G09 | `verdict.run_started` (P1.1): ghi sự kiện bắt đầu chạy khi `verdict run` bắt đầu; Stop hook coi mốc đang chạy là đang chạy; thiết kế và kiểm đủ bốn kết cục hoàn thành / lỗi / quá giờ (bằng `verdict.receipt_issued`, `verdict.recorded` sẵn có) / tiến trình chết (`verdict.run_abandoned`, không tính vào `max_repairs`); một lần chạy mất dấu không treo trạng thái "đang kiểm" mãi; hai loại mới là lớp A của sổ loại sự kiện (T41b); không theo dõi tiến độ từng phần, không thông báo tiến độ. Không cần interface executor (W33b) | TD04 (`verifiers/command.py`), TD05 (`hook_cli.py`) | `onecrew/v2/verdict.py`, `hook_cli.py` (Stop) | WK03, W11a | 1,5–2 h / 2 h | T41a, T41b | mặc định | Một lần chạy bị giết để lại "đang kiểm"; Stop hook còn nhắc khi mốc đang chạy; lần chạy bỏ dở làm bản cũ đổi trạng thái hay số lần sửa |
| W33a | R03 | G10 | Quan sát có nguồn: adapter khai capability (bắt đầu, dừng, pause tại điểm an toàn, cô lập, đo, recovery); ghi start/end/wait theo attempt, nguồn thời gian và thời điểm nhận; thiếu dữ liệu là unknown; phiên ngoài chỉ báo từ biên nhận, tool hay hook có thật, không suy số call, suy luận nội bộ hay trạng thái treo; không hứa pause | TD11, TD05 | interface trong wheel; adapter hook | WK03 | 1–1,5 h / 2 h | T15b | mặc định | Báo "đã pause" hay số call cho executor không khai capability |
| W32a | R03 | G08 | Baseline ước lượng theo khoảng, ghi một lần ngay sau `plan.approved` bằng sự kiện `estimate.baseline` (lớp A; hợp đồng v2 không có trường ước lượng, `v2:contract.py:15-16, 104-106`); ETA và lý do bằng `estimate.eta`, phát sinh bằng `work.additional` (lớp A); thời gian thực thi, chờ, deadline riêng; phần còn lại; phát sinh phân loại bắt buộc / tùy chọn / vượt quyền, mỗi mục có lý do và acceptance; lịch sử ETA và lý do đổi; restart không reset baseline; thiếu quan sát là unknown, không phải 0 hay "không tiến triển"; dòng trạng thái trên `plan present` và report | TD29 (budget advice, không phải dự báo), TD06, `effort_watch` (cảnh báo 70% không thành request trong workflow mới) | `onecrew/v2/report.py`, module ước lượng | W33a, W44, W23a, WK03 | 2 h / 2 h | T36b | vượt trần → tách: baseline và ETA; phát sinh | Báo cáo tính thời gian chờ là thời gian làm; restart làm mất baseline |
| W23c | R03 | G11 | Số đo hiệu quả lấy từ sổ bằng hàm đánh giá v1 qua adapter ([02](02-TAI-SU-DUNG-V1-V2.vi.md), TD27): thời gian tới đầu ra, rework, quyết định của người dùng theo động từ và request, chi phí kiểm, lần hỏi trạng thái; chờ tách khỏi phút chủ động | TD27 | adapter số đo | W44, WK03 | 1,5–2 h / 2 h | T35d | mặc định | Chép logic phân loại của v1 sang module mới thay vì gọi qua adapter |
| W24 | R03 | G11 | Ba trạng thái riêng `verified` / `accepted` / thông báo đã giao (HD-31); đúng một thông báo cho mỗi sự kiện cần chủ sở hữu (duyệt, câu hỏi, plan dừng, xong), bấm vào mở đúng việc; tái dùng kênh desktop Windows của v1 (outbox, chống trùng); không bật lại heartbeat | TD24, TD25 | adapter thông báo, `v2/report.py` | W23a, WK03 | 1,5–2 h / 2 h | T12, T43a | mặc định | Thông báo lỗi làm chạy lại sản phẩm; một sự kiện hai thông báo |
| W24b | R03 | G11, G08 | Thông báo ngoại lệ (đổi có chủ đích so với W24 cũ), ghi bằng `notice.exception` (lớp A) để outbox v1 đọc từ sổ: lệch đáng kể so với baseline, blocker, mốc đã hẹn; mỗi thông báo có lý do, bằng chứng, ETA mới và việc người dùng cần làm (nếu có); ngưỡng theo policy chốt trước; khử trùng theo nguyên nhân; thông báo đến muộn vẫn nêu thời điểm sự kiện và trạng thái hiện tại, bản đã bị thay thì gộp; không có thông báo "đang làm" định kỳ | TD24, TD25 | adapter thông báo | W24, W32a, WK03 | 1,5–2 h / 2 h | T43c | mặc định | Thông báo định kỳ không có ngoại lệ; hai thông báo cho cùng một nguyên nhân |
| W30b | R03 | G02, G06 | Câu trả lời được ghi đúng (A6, phần không đổi trạng thái): lệnh đọc và lệnh trả lời câu hỏi trong wheel (động từ của chủ sở hữu); lựa chọn ghi vào `request.answered` (lớp 0, chỉ thêm trường `choice`); trả lời "amend" đi qua amend và duyệt sẵn có; thông báo của câu hỏi mở đúng thẻ. Không ghi sự kiện đổi trạng thái: root `plan:` của R03 vẫn theo luật trạng thái cũ (lớp B chỉ có trên root `plan-ns:`, R04) | TD01, TD17, TD19 | `ledger.py`, `v2/cli.py` | W24, W30a, WK03 | 1,5–2 h / 2 h | T47a, T43b | mặc định | Ghi sự kiện đổi trạng thái lên anchor `plan:`; đọc câu hỏi bị tính là trả lời |
| W40-R03 | R03 | G10 | Phát hành R03: theo quy trình chung của T54 (khung W40, W41 ở R00) cho phần của R03; `verdict.run_started`, `verdict.run_abandoned` chứng minh lớp A trên bản cài | W40, W41 | kịch bản trong kit | W44, W33a, W32a, W23c, W24, W24b, W30b, W40-R01, W40, W41 | 1–2 h / 2 h | T54c | mặc định | Diễn tập dùng sổ thật |

---

## R04 — Quyền rõ, kế hoạch nội bộ, chạy tuần tự

Cần trước: R00. Cổng giao: CG-R04.

| ID | Release | Gap | Kết quả cụ thể | Dùng lại | Phạm vi sửa dự kiến | Phụ thuộc | Ước lượng / trần | Testcase trước | Dừng/chia khi | Không done khi (riêng) |
|---|---|---|---|---|---|---|---|---|---|---|
| WK04a | R04 | G01, G08 | Bộ kiểm R04, nhóm quyền và kế hoạch: T02, T03, T04a, T16a, T17a, T19, T21, T36a, T37 | mẫu kit | `verify-kit\wf\r04a_check.py` | WK0 | 1,5–2 h / 2 h | — | mặc định | Phần `năng lực mới` không có phản chứng |
| WK04b | R04 | G03, G10 | Bộ kiểm R04, nhóm trạng thái và tương thích: T05, T25, T26, T32, T48b, T49c, T49d, T54d | mẫu kit | `verify-kit\wf\r04b_check.py` | WK0 | 1,5–2 h / 2 h | — | mặc định | Phần `năng lực mới` không có phản chứng |
| W01 (S) | R04 | G01 | Câu trả lời: ánh xạ từng trường `authority` của v1 (`edit`, `commands`, `local_branches`, `branch_at`, `apply_to_project`, `edit_tests`, `unconfined_commands`) sang root v2: trường nào thi hành ở `gate`, trường nào chỉ ghi. Hình thức đã chọn ở [00 §7](00-THIET-KE-WORKFLOW-CHUNG.vi.md#7-quyết-định-còn-mở-và-cách-đã-giải) (O2); W01 kiểm lại với mã lúc làm | TD08, TD14 `covers()` | tài liệu 00/02 | — | 0,5–1 h / 1 h | — | mặc định | Kết luận không có `file:dòng` |
| W02 | R04 | G01 | Hợp đồng root có quyền cấp (ghi, lệnh, nhánh, sửa test, trần ngân sách/deadline, danh sách tự quyết); lint và niêm phong; kiểm "kế hoạch ⊆ quyền" kiểu `covers()`; phân loại hành động ngoài quyền thành U1–U4 | TD03, TD07, TD08, TD14 | `onecrew/v2/contract.py`, `step0.py`, `work_contract.py` | W01, W03, WK04a | 1,5–2 h / 2 h | T17a; kiểm chung: T16a, T37 | mặc định | Quyền cấp không được thi hành ở `gate` |
| W04 | R04 | G01 | Revision kế hoạch nội bộ (`plan.revised`) tách khỏi revision hợp đồng; trong quyền thì không cần duyệt | TD03 | `onecrew/v2/plan.py` | W02, W03, WK04a | 1,5–2 h / 2 h | T16a; kiểm chung: T03 | mặc định | Chia task tạo request cho người dùng |
| W05 | R04 | G01, G05 | Phân loại đổi acceptance (HD-04) và phát hiện làm yếu bộ kiểm qua hash/manifest | TD03, mẫu `kit-manifest-r8` | `onecrew/v2/` (so sánh revision), bộ kiểm | W04 | 1–2 h / 2 h | T21, T19 | mặc định | Ca (c)–(f) của T21 không ra U1 |
| W06 | R04 | G03 | Ba trạng thái node; dependency khai `requires`; hàm "đủ điều kiện chạy" theo trạng thái | TD03; trường output v1 (`v1:owned.py:393-394`); luật `passed` của delivery | `onecrew/v2/plan.py` (view), `contract.py` | WK04b, W02 | 1,5–2 h / 2 h | T05, T37 | mặc định | `verified` bị coi như `accepted` |
| W10 | R04 | G08, G09 | Ngân sách và deadline không reset qua chia/retry/restart; đóng lỗ "khoá khác thì ngân sách mới" trong cùng root | TD06, TD10 (bất biến), `goal_budget` | `onecrew/budget_core.py`, `task_intake.py`, `v2/gate.py` | W02, W04, WK04a | 1,5–2 h / 2 h | T03; kiểm chung: T32 | mặc định | Một đường tạo ngân sách mới còn mở |
| W11b | R04 | G10 | Version workflow và capability khai trong root; plan schema 2 giữ semantics | TD03 | `onecrew/v2/contract.py`, `plan.py`, `report.py` | W11a, WK04b | 1–1,5 h / 2 h | T25 | mặc định | Root schema 2 bị áp luật mới |
| W12b | R04 | G01, G10 | Một nguồn duyệt (SOL liên kết như solution revision); một writer mỗi root; không gian tên theo project (A8): root mới (schema 2 và workflow mới) ở `plans/<project_id>/<tên>` với anchor `plan-ns:<tên>` (vẫn tạo bằng `task_intake.submit`), bản sao trạng thái active plan ở `plans/<project_id>/active-plan.json`; project có cả `plan:<tên>` và `plan-ns:<tên>` thì lệnh theo tên từ chối và đòi anchor tường minh ([00 §6.1](00-THIET-KE-WORKFLOW-CHUNG.vi.md#61-ranh-giới-tương-thích-và-rollback-r2)); hai project trùng tên được hỗ trợ (thay luật từ chối của W12a) | TD17, TD14 (one live writer), TD03 | `onecrew/v2/plan.py`, `contract.py`; `solution_gate.py` (nguồn ràng buộc) | W02, W10, W11b, W12a | 1,5–2 h / 2 h | T26, T32, T48b | vượt trần → tách: một nguồn duyệt và một writer; không gian tên | Hai bản duyệt cùng cho phép ghi; root mới mang anchor `plan:` (bản cũ amend rẽ nhánh hay ghi sang project khác) |
| W46b | R04 | G10 | `compat scan` mở rộng cho anchor `plan-ns:` (đóng băng khi rollback), tên trùng, B1 (active plan trỏ root bản cũ không thấy), B3 (anchor `plan:` có file ở đường dẫn mới, trùng tên project khác); dự đoán từng lệnh của bản cũ cho các root đó theo bảng lệnh của T49 | TD03 | `onecrew/v2/` (lệnh chỉ đọc) | W46a, W12b, WK04b | 1–1,5 h / 2 h | T49c | mặc định | Báo "đọc được" cho root `plan-ns:`; coi tạm dừng là đã giải phóng |
| W13 (S) | R04 | G05 | Câu trả lời: engine cho lát tuần tự R04 (mô hình node/cạnh/generation của delivery, `parallel.ready_batch` với một slot, hay mở rộng item/mốc v2) và điều kiện mở song song ở R08 | TD12, TD13, TD14 | tài liệu 02 | — | 0,5–1 h / 1 h | — | mặc định | Kết luận không có `file:dòng` |
| W14a | R04 | G05, G03 | Root chạy task tuần tự theo engine đã chọn, dependency theo trạng thái (HD-15), một slot. **Lớp mỏng nối các hàm tái dùng** (`ready_batch`, mô hình node/cạnh/generation, `control.reserve`). **Không viết scheduler thứ hai**: nếu W13 kết luận phải viết thêm thì ghi bằng chứng vì sao từng hàm tái dùng không đáp ứng | TD13, TD14 (mô hình), TD10, TD03 | lớp nối trong `onecrew/v2/` | W13, W06, WK04a | 1,5–2 h / 2 h | T04a; kiểm chung: T16b, T17b | mặc định | Engine có luật theo nghiệp vụ |
| W31b | R04 | G02, G08 | Unknown trong thực thi có `affected`, `required_by`, chủ thể giải; giữ cục bộ hoặc toàn cục trên engine tuần tự; unknown chặn ước lượng thì thành node khảo sát có trần trước implementation (luật PoC của `step0`, không cần W31a) | TD03 (`step0` unknown, PoC), TD13 (`blocks`) | `onecrew/v2/contract.py`, điều phối | W14a, WK04a | 1,5–2 h / 2 h | T02 | mặc định | Một unknown cục bộ giữ cả root |
| W32b | R04 | G08 | Trường ước lượng (khoảng) cho task của kế hoạch nội bộ; trần mỗi task; luật chia (chia khi vượt trần; việc không chia được có lý do và trần riêng) | TD29, TD06 | `onecrew/v2/contract.py`, `budget_core.py` | W31b, W10, W04, WK04a | 1–1,5 h / 2 h | T36a | mặc định | Task vượt trần không có lý do |
| W40-R04 | R04 | G10 | Phát hành R04: theo quy trình chung của T54 (khung W40, W41 ở R00) cho phần của R04; root mới mang anchor `plan-ns:`, nên diễn tập rollback xử lý B1, B3, đóng băng và trùng tên trong cùng project (T49d) | W40, W41 | kịch bản trong kit | W01, W02, W04, W05, W06, W10, W11b, W12b, W46b, W13, W14a, W31b, W32b, W40, W41 | 1,5–2 h / 2 h | T54d, T49d | vượt trần → tách: đóng gói và kiểm bản cài; diễn tập namespace | Rollback khi còn điều kiện chặn hay dựa vào lần scan cũ |

---

## R05 — Kiểm trước, sửa đúng phần, dừng vòng không tiến triển

Cần trước: R04, R03. Cổng giao: CG-R05.

| ID | Release | Gap | Kết quả cụ thể | Dùng lại | Phạm vi sửa dự kiến | Phụ thuộc | Ước lượng / trần | Testcase trước | Dừng/chia khi | Không done khi (riêng) |
|---|---|---|---|---|---|---|---|---|---|---|
| WK05a | R05 | G04, G06 | Bộ kiểm R05, nhóm evidence và finding: T06, T07a, T11, T15a, T17b, T22, T24b, T28, T31, T38c | mẫu kit | `verify-kit\wf\r05a_check.py` | WK0 | 1,5–2 h / 2 h | — | mặc định | Phần `năng lực mới` không có phản chứng |
| WK05b | R05 | G06, G07, G09 | Bộ kiểm R05, nhóm vòng sửa, quyết định, tích hợp: T04c, T08a, T16b, T16c, T17c, T18a, T18b, T29, T43d, T47c, T54e | mẫu kit | `verify-kit\wf\r05b_check.py` | WK0 | 1,5–2 h / 2 h | — | mặc định | Có ca gọi model thật |
| W07 | R05 | G04 | Biên nhận gắn thêm input, cấu hình, môi trường; stale nêu đúng thứ đổi | TD04, TD02 | `onecrew/v2/verifiers/command.py`, `reviewer.py`, `plan.py` | W06, WK05a | 1–2 h / 2 h | T06 | mặc định | Môi trường vẫn không được ghi |
| W08 | R05 | G04 | Căn cứ tái dùng evidence được ghi; căn cứ chỉ là `scope.neutral` đã khai hay căn cứ theo hành vi có bằng chứng, không theo đường dẫn; không rõ thì kiểm rộng hơn | TD03 (`covers`, `_signature`), luật fingerprint `v1:work_tools.py:1453-1470` | `onecrew/v2/plan.py` | W07 | 1–1,5 h / 2 h | T22 | mặc định | Tái dùng không ghi căn cứ |
| W09 | R05 | G04 | Retention: ref cục bộ giữ cây và blob mà evidence tham chiếu; không push; không tự xoá ref, chỉ chủ sở hữu dọn; hook chặn `git push` có `refs/onecrew` (A10; mặc định ở `verify-kit\DE-XUAT-P0B-PHAN-B.md`, chốt trong `decisions` của hợp đồng chương trình, O6) | TD02 | `onecrew/v2/verifiers/command.py`, `snapshots.py`, `hook_cli.py` | WK05a | 1–2 h / 2 h | T31 | mặc định | Cây bị `gc` dọn mất |
| W16 | R05 | G05 | Node chuẩn bị test từ acceptance chạy trước implementation | TD03 | điều phối | W14a, WK05b | 1–1,5 h / 2 h | T04c | mặc định | Node chuẩn bị test bị chặn chờ code |
| W17 | R05 | G06 | Finding register cho plan v2 (A3; phần "không thêm cổng" của đề xuất `DE-XUAT-LO3-A3-A5` không theo, vì HD-25 giữ nhánh bị ảnh hưởng): tách hàm thuần của `review_evidence` sang module mới; thêm mức độ và phạm vi | TD18 | module mới trong wheel, `v2/verifiers/reviewer.py`, `verdict.py` | WK05a | 2 h / 2 h | T28; kiểm chung: T07a | vượt trần → tách: lưu trữ; mức độ/phạm vi | Đổi code hay "accept" đóng được finding |
| W18 | R05 | G06 | Phạm vi ảnh hưởng theo dependency + phạm vi đọc/ghi; giữ nhánh (tuần tự: không chạy task bị ảnh hưởng; executor bên ngoài: chặn ghi; worker được quản lý dừng tại điểm an toàn ở R08) | TD13 | điều phối, `hook_cli.py` (giữ theo phạm vi) | W14a, W17 | 1,5–2 h / 2 h | T07a, T15a, T17b; kiểm chung: T16b | mặc định | Giữ cả root vì một nhánh |
| W19 | R05 | G06 | Repair task; chạy lại ca từng hỏng trước, rồi phần bị ảnh hưởng; vô hiệu hoá theo generation | TD14 (`_repair`), TD31 (mẫu) | điều phối | W18 | 1,5–2 h / 2 h | T38c; kiểm chung: T11, T18a, T16b | mặc định | Chạy lại toàn suite khi phạm vi xác định được |
| W51 | R05 | G06 | Không dừng nhầm việc đang tiến triển. Tách phần dùng chung của `progress.observe` (đếm lặp theo hash kết quả công cụ; luật khảo sát: nguồn mới đặt lại đếm, đọc lặp thì dừng) thành hàm thuần trong wheel, `progress.observe` của v1 gọi lại hàm đó (một nguồn). Phần mới: liveness của lệnh dài (output hay biên nhận mới trong cửa sổ quan sát), trần số giả thuyết rồi thành blocker, phân biệt chờ và quan sát unknown (W33a). Không suy tiến triển từ số dòng sửa | `progress.observe` (`v1:progress.py:42`, phần đếm lặp và khảo sát), `discovery.search` (v1), TD15 | module trong wheel; `progress.py` gọi lại hàm tách | W33a, W19, WK05b | 1,5–2 h / 2 h | T18b | mặc định | Chép logic đếm lặp sang module mới thay vì tách một nguồn; nạp `progress.observe` nguyên khối vào wheel (nó nạp lười `work_tools`, `sandbox_gate`, `owned_git`, `review_evidence` của V1_ONLY và tự đặt `phase=blocked`, `v1:progress.py:9-11, 48, 105, 69-70, 159-160`); dừng một lệnh dài còn output mới |
| W20 | R05 | G06 | Vòng sửa không tiến triển → tự chẩn đoán, replan trong quyền, hoặc blocker có bằng chứng | TD15 | điều phối | W19, W51 | 1–1,5 h / 2 h | T18a | mặc định | Hỏi người dùng sau mỗi vòng |
| W21 | R05 | G05 | Node tích hợp: unit xanh mà tích hợp đỏ thì root chưa `verified` | TD03 | điều phối, mẫu hợp đồng | W14a, W19 | 1–1,5 h / 2 h | T11 | mặc định | Root `verified` khi tích hợp đỏ |
| W23d | R05 | G11, G06 | Bàn giao theo finding: báo cáo và `plan present` liệt kê finding còn mở lấy từ register (W17), finding đã đóng có bằng chứng thì không | TD05, TD18 | `onecrew/v2/report.py` | W23a, W17, WK05a | 1–1,5 h / 2 h | T24b | mặc định | Báo cáo thiếu một finding còn mở |
| W26 | R05 | G07, G10 | Lớp quyết định **theo quy tắc**: `SKIP`/`DEFER`/`REVIEW`/`HOLD` có lý do, bằng chứng, phạm vi, hiệu lực; cache theo (input, revision, policy); lõi giữ cổng bắt buộc; độ sâu theo policy đã duyệt ở root (HD-35; chỉ phần độ sâu của P2.2, không phải đường nhanh việc XS chỉ đọc). `SKIP` chỉ áp cho review tùy chọn theo policy đã duyệt, không theo ý kiến model | TD15, `triage`, `effort_watch`, `routing.validate_decision` | module quyết định trong wheel | WK05b, W03, W31b | 2 h / 2 h | T29, T16c | vượt trần → tách: bốn kết quả + cache; độ sâu | Cổng bắt buộc bị bỏ |
| W30c | R05 | G02, G06 | Áp câu trả lời thành trạng thái trên root `plan-ns:`: trả lời "dừng" đóng root có lý do (`plan.closed`, lớp B); trả lời "tiếp tục" mở lại đúng phần bị giữ (`request.applied`, lớp B); root `plan:` tạo trước R04 giữ `stopped_with_report` và chỉ có lựa chọn đã ghi | TD01, TD17, TD18 (giữ theo phạm vi) | `v2/plan.py`, `v2/verdict.py`, điều phối | W30b, W12b, W18, WK05b | 1–1,5 h / 2 h | T47c, T43d | mặc định | Request `answered` mà root `plan-ns:` vẫn chờ chủ sở hữu; ghi `plan.closed` lên anchor `plan:` |
| W37a | R05 | G09 | Reconcile tối thiểu trong vòng sửa tuần tự: lệnh có kết quả chưa rõ (crash sau dispatch, trước biên nhận) được reconcile trước mọi retry; không xác định được thì giữ và báo, không tự chạy lại | TD16 (`action.*` của `control`) | `v2/verdict.py`, điều phối | W19, WK05b | 1–1,5 h / 2 h | T08a | mặc định | Chạy lại thao tác chưa rõ kết quả |
| W40-R05 | R05 | G10 | Phát hành R05: theo quy trình chung của T54 (khung W40, W41 ở R00) cho phần của R05; sự kiện lớp B (`HOLD`, `DEFER`, intent) chỉ trên root `plan-ns:`; roll-forward reconcile intent chưa rõ trước khi root tiếp tục | W40, W41 | kịch bản trong kit | W07, W08, W09, W16, W17, W18, W19, W51, W20, W21, W23d, W26, W30c, W37a, W40-R03, W40-R04, W40, W41 | 1,5–2 h / 2 h | T54e | mặc định | Roll-forward tiếp tục root trước khi reconcile |

---

## R06 — Học ngay từ lỗi đã xác minh

Cần trước: R02, R05. Cổng giao: CG-R06.

| ID | Release | Gap | Kết quả cụ thể | Dùng lại | Phạm vi sửa dự kiến | Phụ thuộc | Ước lượng / trần | Testcase trước | Dừng/chia khi | Không done khi (riêng) |
|---|---|---|---|---|---|---|---|---|---|---|
| WK06 | R06 | G11 | Bộ kiểm R06: T52a, T52b, T54f | mẫu kit | `verify-kit\wf\r06_check.py` | WK0 | 1–1,5 h / 2 h | — | mặc định | Phần `năng lực mới` không có phản chứng |
| W49a | R06 | G11, G06 | Incident trong root: nối finding, các attempt, giả thuyết bị bác bỏ; phân biệt test đỏ có chủ đích, lỗi môi trường, lỗi sản phẩm; một incident nhiều attempt, khử trùng; ghi `learning.incident` (lớp A) qua adapter có nguồn đúng nghĩa | TD18 (finding), TD22 (khử trùng, cách ly project), TD15 | module incident trong wheel | W17, W19, W48a, WK06 | 1,5–2 h / 2 h | T52a | mặc định | Mỗi lần fail sinh một incident mới; lỗi môi trường được ghi là lỗi sản phẩm |
| W49b | R06 | G11 | Lesson sau khi sửa đã kiểm, trước khi root kết thúc: bản project giữ vị trí, revision, test; bản chung là ứng viên đã khái quát có điều kiện và nguồn, bỏ chi tiết riêng; task sau trong cùng root truy xuất được qua W48b; revision đổi thì cần kiểm lại; thu hồi lesson sai. **Không** gọi `learning.record` (cần kết cục cuối, tạo lesson `proposed`) bằng một outcome giả: adapter ghi `learning.lesson` (lớp A) với nguồn incident. Lesson không tự thành rule bắt buộc (RL) | TD22 (định dạng, khử trùng, cách ly project của `learning`; stale theo revision là phần mới), TD23 (skills chỉ đọc) | adapter lesson trong wheel | W49a, W48b, WK06 | 1,5–2 h / 2 h | T52b | mặc định | Root bị đánh dấu xong hay giả `completed` để gọi writer v1; lesson đổi quyền, cổng hay acceptance |
| W40-R06 | R06 | G10 | Phát hành R06: theo quy trình chung của T54 (khung W40, W41 ở R00) cho phần của R06; `learning.incident`, `learning.lesson` của root v2 chứng minh lớp A với bản cũ và với consumer v1 (`skills`, `learning`) trên bản cài | W40, W41 | kịch bản trong kit | W49a, W49b, W40-R02, W40-R05, W40, W41 | 1–2 h / 2 h | T54f | mặc định | Diễn tập dùng sổ thật |

---

## R07 — Ảnh hay mô tả issue → file, method cần kiểm

Cần trước: R02. Cổng giao: CG-R07.

| ID | Release | Gap | Kết quả cụ thể | Dùng lại | Phạm vi sửa dự kiến | Phụ thuộc | Ước lượng / trần | Testcase trước | Dừng/chia khi | Không done khi (riêng) |
|---|---|---|---|---|---|---|---|---|---|---|
| WK07 | R07 | G06 | Bộ kiểm R07: T53a, T53b, T54g | mẫu kit | `verify-kit\wf\r07_check.py` | WK0 | 1–1,5 h / 2 h | — | mặc định | Tập đánh giá chứa lời giải của ca |
| W50a | R07 | G06 | Mô tả issue → nghi phạm: tìm chuỗi, route, symbol, thay đổi gần đây; bản đồ project tăng dần; lesson liên quan (W48b); danh sách nghi phạm (file, method) có lý do, nguồn và phép kiểm tiếp; symbol phải tồn tại ở revision đã ghim; tách quan sát khỏi giả thuyết; thiếu căn cứ thì trả "chưa đủ dữ liệu" kèm thứ cần thêm | TD22, TD02 (biên nhận tìm kiếm), TD03 (`step0` evidence) | module tra cứu trong wheel | W48b, WK07 | 1,5–2 h / 2 h | T53a | mặc định | Nghi phạm trỏ symbol không có ở revision ghim; sửa code chỉ vì giống một issue cũ |
| W50b | R07 | G06 | Ảnh issue: chỉ đọc ảnh khi provider khai capability vision; không có thì giữ luồng văn bản và không tuyên bố đã hiểu ảnh; đánh giá trên code trước bản sửa, tập giữ riêng, không đưa lời giải vào trí nhớ; đo top-k và thời gian tới nguyên nhân | W50a, TD19 (capability provider) | adapter ảnh, kịch bản đánh giá | W50a, WK07 | 1,5–2 h / 2 h | T53b | mặc định | Báo đã đọc ảnh khi provider không có vision; tập đánh giá lộ lời giải |
| W40-R07 | R07 | G10 | Phát hành R07: theo quy trình chung của T54 (khung W40, W41 ở R00) cho phần của R07 | W40, W41 | kịch bản trong kit | W50a, W50b, W40-R02, W40, W41 | 1–2 h / 2 h | T54g | mặc định | Diễn tập dùng sổ thật |

---

## R08 — Review có chiến lược, dev/test/review theo DAG

Cần trước: R03, R04, R05. Cổng giao: CG-R08.

| ID | Release | Gap | Kết quả cụ thể | Dùng lại | Phạm vi sửa dự kiến | Phụ thuộc | Ước lượng / trần | Testcase trước | Dừng/chia khi | Không done khi (riêng) |
|---|---|---|---|---|---|---|---|---|---|---|
| WK08 | R08 | G05, G06, G09, G10 | Bộ kiểm R08: T01, T04b, T04d, T07b, T08b, T15c, T30, T54h | mẫu kit | `verify-kit\wf\r08_check.py` | WK0 | 1,5–2 h / 2 h | — | mặc định | Có ca gọi model thật |
| W14b | R08 | G05 | DAG song song: nhiều slot qua `ready_batch` sau khi một slot đã đúng (W14a); phần độc lập chạy tiếp khi một nhánh bị giữ; không scheduler thứ hai | TD13, TD14, TD10 | lớp nối trong `onecrew/v2/` | W14a, W18, WK08 | 1,5–2 h / 2 h | T04d | mặc định | Hai node ghi cùng phạm vi chạy đồng thời |
| W15 | R08 | G05, G04 | Review và test chạy trên snapshot cố định; code tiếp tục trên phiên bản khác | TD04 | `onecrew/v2/verifiers/reviewer.py`, điều phối | W14b, W26 | 1–2 h / 2 h | T04b, T01 | mặc định | Diff review lẫn thay đổi mới |
| W33b | R08 | G10 | Interface executor đầy đủ: dừng, pause tại điểm an toàn, cô lập, recovery theo capability đã khai (W33a); adapter Windows (supervisor) và adapter hook (Claude Code) | TD11, TD05 | interface trong wheel; adapter v1 | W33a, WK08 | 1,5–2 h / 2 h | T15c | mặc định | Gửi lệnh pause tới executor không khai capability |
| W36 | R08 | G06, G09 | Generation; kết quả muộn hay trùng được ghi và bỏ qua; pause tại điểm an toàn cho worker được quản lý | TD10 (fencing), TD18 (closure muộn) | `control.py` (phần tách), điều phối | W33b, W18 | 1,5–2 h / 2 h | T07b | mặc định | Tính phí hai lần |
| W37b | R08 | G09, G03 | Intent bền, idempotency, reconcile qua bốn điểm crash; khôi phục checkpoint khác tự khởi động sau reboot | TD16, TD11 (`host` không hồi sinh) | `v2/verdict.py`, điều phối | W33b, W37a | 1,5–2 h / 2 h | T08b, T30 | mặc định | Chạy lại thao tác chưa rõ kết quả; mất biên nhận đã lưu |
| W40-R08 | R08 | G10 | Phát hành R08: theo quy trình chung của T54 (khung W40, W41 ở R00) cho phần của R08; tạm dừng mới (lớp B) chỉ trên root `plan-ns:` | W40, W41 | kịch bản trong kit | W14b, W15, W33b, W36, W37b, W40-R03, W40-R04, W40-R05, W40, W41 | 1–2 h / 2 h | T54h | mặc định | Diễn tập dùng sổ thật |

---

## RP — Reviewer và cố vấn đa provider

Cần trước: R00. Cổng giao: CG-RP.

| ID | Release | Gap | Kết quả cụ thể | Dùng lại | Phạm vi sửa dự kiến | Phụ thuộc | Ước lượng / trần | Testcase trước | Dừng/chia khi | Không done khi (riêng) |
|---|---|---|---|---|---|---|---|---|---|---|
| WKP | RP | G07 | Bộ kiểm RP: T40a, T40b, T40c, T54i | mẫu kit | `verify-kit\wf\rp_check.py` | WK0 | 1–1,5 h / 2 h | — | mặc định | Tính ô CLI giả là ô thật |
| W43 | RP | G07 | Reviewer và cố vấn theo nhà cung cấp (P1.0): hợp đồng khai `provider` (`claude`, `codex`, `kiro`) kèm `model`; mỗi provider là một lệnh CLI chỉ đọc; biên nhận ghi provider và model; luật độc lập xét theo hãng; không tự chuyển provider khi hết hạn mức (verdict không kết luận và báo); giữ mốc owner-manual. Bước đầu là PoC ngắn: CLI chạy không giao diện, trả JSON, không ghi file. **Không** phải decider (RD) | TD04 (`verifiers/reviewer.py`), TD19, TD21 | `onecrew/v2/verifiers/`, `contract.py` | WKP, W27a | 2 h / 2 h | T40a; kiểm chung: T40b | vượt trần → tách: PoC + Codex; Kiro + luật độc lập | Đổi provider cần sửa mã thay vì một trường hợp đồng; biên nhận không ghi provider |
| W45 | RP | G07 | Kiểm thật ma trận provider (R3): chạy **mỗi ô** của ma trận provider × vai trò (`claude`, `codex`, `kiro` × reviewer, cố vấn) một lần bằng CLI thật trên một artifact mẫu chỉ đọc, từ bản cài đặt, với provider/model đã pin trong hợp đồng chương trình; ghi biên nhận và hash bản dựng của từng ô. Thiếu tài khoản, hạn mức hay công cụ thì ô đó là "chưa kiểm chứng", không đổi provider đã pin. Xong khi ma trận đủ sáu dòng và trung thực; số ô `đạt` không phải điều kiện xong ([03 §5.1](03-HOP-DONG-DRAFT.vi.md#51-provider-ba-điều-kiện-tách-riêng)) | W43 | kịch bản trong bộ kiểm | W43, W40, WKP | 1–2 h / 2 h | T40b | mặc định | Tính ô CLI giả là đạt; ô thiếu ghi `đạt`; ma trận thiếu dòng hay thiếu hash bản dựng; ghi P1.0 đủ khi còn ô chưa `đạt` |
| W40-RP | RP | G10 | Phát hành RP: theo quy trình chung của T54 (khung W40, W41 ở R00) cho phần của RP; giao **subset** đã kiểm thật (T40c): ghi chú phát hành và file ma trận giao kèm nêu "dùng được" đúng các ô `dùng được` cho bản giao theo luật hiệu lực HL ([03 §5.2](03-HOP-DONG-DRAFT.vi.md#52-bằng-chứng-qua-nhiều-phiên-bản-và-artifact-cuối)), ô khác ghi trạng thái cho bản giao và lý do; giao được khi subset có ít nhất một ô; P1.0 đủ không phải điều kiện giao. Giao kèm **bộ đánh giá hiệu lực chung** (HL, NL) trong kit, dùng lại ở mọi cổng sau, không nhánh theo provider | W40, W41 | kịch bản trong kit | W43, W45, W40, W41 | 1–2 h / 2 h | T54i, T40c | mặc định | Ghi chú phát hành nhận ô chưa kiểm chứng là đạt; subset chứa ô có biên nhận của bản dựng khác; RP bị giữ chỉ vì còn ô chưa `đạt` |

---

## RX1 — Adapter kiểm đầu ra tài liệu

Cần trước: R00. Cổng giao: CG-RX1.

| ID | Release | Gap | Kết quả cụ thể | Dùng lại | Phạm vi sửa dự kiến | Phụ thuộc | Ước lượng / trần | Testcase trước | Dừng/chia khi | Không done khi (riêng) |
|---|---|---|---|---|---|---|---|---|---|---|
| WKX1 | RX1 | G10 | Bộ kiểm RX1: T14a, T23, T54j | mẫu kit | `verify-kit\wf\rx1_check.py` | WK0 | 1–1,5 h / 2 h | — | mặc định | Phần `năng lực mới` không có phản chứng |
| W22 | RX1 | G10 | Adapter kiểm cho đầu ra tài liệu dạng verifier của v2 (nguồn, cấu trúc, link/ID); lõi chặn adapter vượt quyền; không cần engine của R04 | TD04 (dạng plugin) | `onecrew/v2/verifiers/` (adapter mới) | WKX1 | 1,5–2 h / 2 h | T14a, T23 | mặc định | Lõi có nhánh `if loại == tài liệu` |
| W40-RX1 | RX1 | G10 | Phát hành RX1: theo quy trình chung của T54 (khung W40, W41 ở R00) cho adapter tài liệu; diễn tập đầu-cuối một root tài liệu trên bản cài (phần tài liệu của P-0 cũ) | W40, W41 | kịch bản trong kit | W22, W40, W41 | 1–2 h / 2 h | T54j | mặc định | Diễn tập chạy từ checkout |

---

## RX2 — Adapter kiểm đầu ra dữ liệu và vận hành

Cần trước: R00, RX1. Cổng giao: CG-RX2.

| ID | Release | Gap | Kết quả cụ thể | Dùng lại | Phạm vi sửa dự kiến | Phụ thuộc | Ước lượng / trần | Testcase trước | Dừng/chia khi | Không done khi (riêng) |
|---|---|---|---|---|---|---|---|---|---|---|
| WKX2 | RX2 | G10, G04 | Bộ kiểm RX2: T14b, T54k | mẫu kit | `verify-kit\wf\rx2_check.py` | WK0 | 1–1,5 h / 2 h | — | mặc định | Phần `năng lực mới` không có phản chứng |
| W39 | RX2 | G10, G04 | Adapter kiểm cho đầu ra dữ liệu (schema, đối soát, mẫu) và vận hành (pre/postcondition, receipt, reconcile); danh tính artifact không phải Git | TD04, TD32 (hình dạng lease) | `onecrew/v2/verifiers/` (adapter) | W22, WKX2 | 2 h / 2 h | T14b | vượt trần → tách: dữ liệu; vận hành | Lõi có nhánh theo loại việc |
| W40-RX2 | RX2 | G10 | Phát hành RX2: theo quy trình chung của T54 (khung W40, W41 ở R00) cho adapter dữ liệu và vận hành; artifact ngoài Git có định danh | W40, W41 | kịch bản trong kit | W39, W40-RX1, W40, W41 | 1–2 h / 2 h | T54k | mặc định | Artifact ngoài Git không có định danh |

---

## Kiểm tích hợp, pilot tích lũy và cổng cuối

- **Kiểm tích hợp (KN):** chạy ngay khi bản dựng có đủ hai release của phần đó, trong cổng giao của release xong sau; kết quả ghi riêng, không làm DoD của release nào đỏ hay xanh. Cổng cuối đòi mọi KN.
- **Dùng thử theo release:** sau cổng giao của một release, bản dựng đó được cài vào venv và state-root cô lập theo quyền pilot (03 §2.2) và dùng cho việc thật phù hợp; mỗi việc ghim phiên bản, dữ liệu tự thu khi có thể. Dùng thử không chặn release sau.
- **PL-A, PL-B:** hai điểm đo chính thức của pilot tích lũy (≥ 10 việc thật, đủ bốn loại đầu ra). Không chặn release nào; cổng cuối đòi PL-B.

| ID | Release | Gap | Kết quả cụ thể | Dùng lại | Phạm vi sửa dự kiến | Phụ thuộc | Ước lượng / trần | Testcase trước | Dừng/chia khi | Không done khi (riêng) |
|---|---|---|---|---|---|---|---|---|---|---|
| WKN | KN | G11, G08 | Bộ kiểm tích hợp giữa release: T36c, T46b, T47b. Mỗi phần chạy khi bản dựng có đủ hai release của nó | mẫu kit | `verify-kit\wf\kn_check.py` | WK0 | 1–1,5 h / 2 h | — | mặc định | Phần tích hợp bị tính vào DoD của một release |
| WKPL | PL | G10, G11 | Bộ kiểm pilot và cổng cuối: T14c, T35b, T35c, T45b, T45c, T45d, T45e, T40d, T55a | mẫu kit, script kiểm báo cáo | `verify-kit\wf\pl_check.py` | WK0 | 1,5–2 h / 2 h | — | mặc định | Biên nhận giả lập được tính là kết quả pilot |
| W38b | PL-A | G11 | **PL-A**: 3 việc thật đầu tiên (code, tài liệu) do chủ sở hữu chọn, trên bản cài đặt cô lập (venv + state-root riêng) của một bản dùng thử có R02, R03, RX1 đã qua cổng giao; mỗi việc ghim phiên bản; đo theo [00 §9](00-THIET-KE-WORKFLOW-CHUNG.vi.md#9-số-đo-hiệu-quả-và-baseline). Việc thật dùng thử ở các bản trước được ghi kèm phiên bản, không thay PL-A | W23b, W23c, TD27 | bảng đo `DO-10-VIEC.csv` | W40-R01, W40-R02, W40-R03, W40-RX1, WKPL | trải nhiều ngày; mỗi lần ghi ≤ 0,5 h | T35b; cổng vào: T45b | việc thật hỏng vì bản dùng thử → ghi, quay lại bản trước theo hướng dẫn của release, không sửa trong việc pilot | Tính thời gian chờ là phút của người dùng; nhận AC3 đủ bốn loại |
| W38c | PL-B | G11 | **PL-B**: đủ ít nhất 10 việc thật tích lũy, có ít nhất một việc dữ liệu và một việc vận hành; reviewer khác hãng dùng ô `đạt` thật trong subset của RP (T40b, T40c) cho những việc chủ sở hữu chọn; báo cáo AC theo phiên bản và giai đoạn (03 §5); mỗi bằng chứng ghi hash bản dựng đã chạy (03 §5.2) | W23b, W23c, TD27 | bảng đo | W38b, W40-RX2, W40-RP, W40-R05, WKPL | trải nhiều ngày | T35c, T14c; cổng vào: T45c | như W38b | Báo cáo nhận đạt một AC mà giai đoạn đã chạy không chứng minh |
| W38d | KET | G11, G10 | Đối chiếu bằng chứng pilot với artifact cuối ([03 §5.2](03-HOP-DONG-DRAFT.vi.md#52-bằng-chứng-qua-nhiều-phiên-bản-và-artifact-cuối)), rồi cho mọi cổng chạy trên artifact cuối dùng kết quả đó qua bộ đánh giá hiệu lực chung của W40-RP, và cho CG-KET kết hợp đủ điều kiện KQ1–KQ7 của 03 §5.3 (thử trên các ca CK của T55): phân tích ảnh hưởng từ hash bản pilot tới artifact cuối (file đổi trong wheel × bản đồ phụ thuộc của từng mục acceptance, lan theo hàm closure ảnh hưởng đã tách từ v1); mục không bị ảnh hưởng giữ bằng chứng với hash cũ; mục bị ảnh hưởng chạy kiểm bổ sung trên artifact cuối; mục còn thiếu được ghi. Không chạy lại toàn bộ pilot; không đổi hash của bằng chứng | TD13 (`v1:amendment.py:23` `affected_tasks`, phần tách ở W14a), W41 (T13b, T49b trên bản sao sổ pilot), W45 (chạy lại ô provider bị ảnh hưởng) | `verify-kit\wf\pl_check.py` (đối chiếu), bản đồ phụ thuộc trong báo cáo pilot | W38c, W40-R06, W40-R07, W40-R08 | 1–2 h / 2 h | T45e, T55a | vượt trần → tách: phân tích ảnh hưởng; kiểm bổ sung | Kế thừa bằng chứng khi chưa có phân tích; đổi hash của bằng chứng lịch sử; bỏ kiểm bổ sung của mục bị ảnh hưởng; mặc định chạy lại cả pilot |

---

## Hoãn: nhánh có điều kiện, giữ yêu cầu và testcase

Các nhánh dưới đây **không** thuộc phạm vi nghiệm thu chương trình và không nằm trong bao đóng phụ thuộc của task nào của chương trình (K-REL). Yêu cầu, điều khoản và testcase vẫn giữ, trạng thái `thiết kế`. Mỗi nhánh mở bằng một root riêng khi đủ điều kiện ([ROADMAP §5](../ROADMAP.vi.md#5-nhánh-sau-và-điều-kiện-mở)). DT1–DT3, RF, RW của roadmap chưa có task ở đây; dữ liệu cho DT1 được thu từ R02, R03.

| ID | Release | Gap | Kết quả cụ thể | Dùng lại | Phụ thuộc | Testcase trước | Điều kiện mở / lý do hoãn |
|---|---|---|---|---|---|---|---|
| WK-D | RD | G07 | Bộ kiểm: T09b, T09c, T44a, T44b (adapter giả cho test; benchmark thật tách riêng) | mẫu kit | W26 | — | Như W25 |
| W25 (S) | RD | G07 | Khảo sát ứng viên model/runtime local theo cấu hình máy; lập kế hoạch benchmark theo [00 §8](00-THIET-KE-WORKFLOW-CHUNG.vi.md#8-decider-dùng-model-jev-local-fallback-và-false-skip). Không cài, không tải, không gọi trả phí | TD20 | W26 | — | Chương trình WF nghiệm thu, và pilot cho thấy số review tùy chọn đủ lớn để đáng giảm |
| W25b | RD | G07 | Chạy benchmark thật trên tập có nhãn (cần quyền cài runtime và tải model: U2, cấp khi mở RD) | — | W25, WK-D | T44a | Như W25, cộng quyền cài/tải |
| W27b | RD | G07 | Adapter decider theo cấu hình của người dùng (ví dụ Jev chính, model local dự phòng: thứ tự là lựa chọn cấu hình, không phải nhận định chất lượng), pin theo vai trò decision; chuỗi fallback hữu hạn; lỗi có kiểu; intent trước khi gọi | TD19, TD20, TD21, TD09 | W25, W26, WK-D | T09b | Như W25 |
| W28 | RD | G07 | Chạy bóng: decider chạy song song với quy tắc, đo false-SKIP theo 00 §8; quyền `SKIP` của model chỉ bật khi dưới ngưỡng đặt trước | TD27 (mô hình trục) | W27b, W25b | T44b | Như W25 |
| W29 | RD | G07 | `init` hỏi **một lần** về model local, lưu lựa chọn; xử lý chưa có runtime/model, tải thất bại, người dùng từ chối; không tải model trong test | TD05 (`install.py`) | W27b | T09c | Như W25 |
| WK-R | RR | G09 | Bộ kiểm: T10a, T10b | mẫu kit | W33b | — | Như W34 |
| W34 | RR | G09 | Admission/reservation dùng chung: lần gọi model khác lệnh chỉ dùng CPU; trần CPU/RAM/provider/thiết bị; WIP; hàng đợi kiểm chứng; ngân sách theo item đo ở biên executor (A7b) | TD10, TD32, TD06 | W33b, WK-R | T10a | Máy một người chạy đúng với một slot và thứ tự `ready_batch`. Mở khi pilot ghi nhận chờ tài nguyên hay chạy song song thật |
| W35 | RR | G09 | Ưu tiên: gỡ blocker trước, tăng ưu tiên theo thời gian chờ, giữ tài nguyên theo thứ tự cố định; một slot vẫn đúng | TD13 (`ready_batch`) | W34 | T10b | Như W34 |
| WK-L | RL | G11 | Bộ kiểm: T34a, T34b | mẫu kit | W49b | — | Như W42 |
| W42 | RL | G11 | Đánh giá rule trước khi kích hoạt; rule gợi ý tự kích hoạt khi quyền cho phép (O5); rule đổi quyền/ngân sách/cổng thành U2 | TD23, TD22 | W49b, W38c, WK-L | T34a, T34b | Sau PL-B, và chỉ khi đánh giá cho thấy cùng một lỗi hay luật vẫn phải nhắc lại (ROADMAP §5 hàng RL, điều kiện của A2). Ghi lesson ở R06 không chờ RL |

Gộp kho revision SOL/plan cũng hoãn (tránh migration giữa chừng, HD-37; ROADMAP §9).

---

## Cổng

Phần testcase dưới đây kiểm chung nhiều task hay hai release, nên chủ của nó là cổng, không phải DoD của task nào. Mỗi cổng giao CG-Rnn ngoài ra luôn đòi: bộ kiểm của release xanh trên bản `git archive`, phần đóng gói W40-Rnn (hay W40, W41 ở R00) đạt trên cùng hash bản dựng, review độc lập trên diff của release, bộ tự kiểm tài liệu `PROBLEMS: 0` ([06 §6](06-TRUY-VET-VA-TU-KIEM.vi.md#6-checklist-cổng)).

| Cổng | Phần kiểm ở cổng | Chạy khi |
|---|---|---|
| CG-R00 | T45a | Cổng giao R00: biên nhận T33a, T13b, T49b có và cùng hash bản dựng trước khi giao bản dùng thử |
| CG-R05 | T16b, T17c | Mọi task R05 đã xong (T16b cần W14a, W17, W18, W19 cùng lúc; T17c cần giữ nhánh W18 và áp câu trả lời W30c) |
| KN-R01-R02 | T46b | Bản dựng có cả R01 và R02 |
| KN-R02-R03 | T47b | Bản dựng có cả R02 và R03 |
| KN-R03-R04 | T36c | Bản dựng có cả R03 và R04 |
| CG-KET | T45d, T40d | Cổng cuối = phép kết hợp KQ1–KQ7 (03 §5.3): mọi cổng giao, mọi kiểm tích hợp, PL-B và đối chiếu artifact cuối (W38d) đã đạt, bằng chứng dùng thật hợp lệ cho artifact cuối theo HL, lịch sử cổng vào đúng, hook không đổi; năng lực provider bắt buộc (KQ6) có đủ; công bố không vượt bằng chứng; dòng P1.0 ghi đủ hay chỉ phần đúng ma trận (T40d), không giữ cổng |

## Đồ thị và đường tới bản dùng thử đầu tiên

```
P0/P0b (hợp đồng đang chạy) ─▶ R00 ─┬─▶ R01 ─┬─▶ R03 ─┬─▶ R05 ─┬─▶ R06 (cần R02)
                                    │        │        │  (R04)─┘  └─▶ R08 (cần R03, R04)
                                    ├─▶ R02 ─┴─ KN-R01-R02, KN-R02-R03 (kiểm tích hợp)
                                    │   └──▶ R07
                                    ├─▶ R04 ─── KN-R03-R04
                                    ├─▶ RP
                                    └─▶ RX1 ─▶ RX2

Pilot tích lũy: (R02, R03, RX1) ─▶ [T45b] PL-A ─▶ (R05, RP, RX2) ─▶ [T45c] PL-B ─▶ (R06, R07, R08) ─▶ W38d đối chiếu artifact cuối ─▶ CG-KET (T45d, T40d) ─▶ nghiệm thu chương trình
Hoãn, nhánh bên: R05 ─▶ RD;  R08 ─▶ RR;  R06 + PL-B ─▶ RL
```

- **Đường tới bản dùng thử đầu tiên có tính năng WF (R01):** bao đóng phụ thuộc của W40-R01, 15 task, chỉ thuộc R00 và R01 (bản 2 cần 47 task, gồm cả executor và recovery, trước P-A):
  WK0 → WK00 → W03 → W11a → W12a → W46a → W27a → W40 → W41 → WK01 → W47 → W23a → W30a → W31a → W40-R01 → cổng giao CG-R01 → cài bản dựng vào venv cô lập (quyền pilot) và dùng thử. Không duyệt thêm.
- **Bản dùng thử của R00** (2.2.x có `compat scan`, kiểm tên, lỗi cố vấn có kiểu): sau CG-R00, cùng cách giao.
- **Thứ tự thực hiện mặc định** theo ưu tiên của roadmap: R00 → R01 → R02 → R03 → R04 → R05 → R06 → R07 → R08; RP chen sau R00 nếu provider là blocker thực; RX1, RX2 khi bắt đầu dùng loại đầu ra đó. Thứ tự là lựa chọn của người điều phối trong dependency (Q1), không phải dependency.
- **Một nguồn sửa mỗi lúc:** các task cùng chạm `onecrew/v2/plan.py` chạy **tuần tự**, kể cả khi thuộc release khác nhau đang làm song song: W11a → W46a (R00); W06 → W04 → W11b → W12b (R04); W08 (R05).
- Task khảo sát (S) chỉ đọc, chạy được sớm hơn.

## Ánh xạ 62 ID task cũ

Mỗi ID task của bản 2 (22/10 đêm) có đúng một dòng. "Giữ" là cùng ID, cùng chỗ; "chuyển" là cùng ID sang release khác; "tách" là chia thành nhiều task (ID mới liên hệ ID cũ bằng hậu tố); "thay thế" là nghĩa vụ chuyển sang task khác; "hoãn" là nhánh có điều kiện. Không bỏ acceptance nào: phần testcase của task cũ đi theo task mới ([06 §3](06-TRUY-VET-VA-TU-KIEM.vi.md#3-chiều-ngược-phần-testcase--release--task--điều-khoản--gap--yêu-cầu-sinh-bằng-script)). K-MAP62 kiểm bảng này và cột tương ứng ở ROADMAP §7.

| ID cũ | Mốc cũ | Hành động | ID mới | Release mới | Lý do |
|---|---|---|---|---|---|
| WK-D | WF-D | hoãn | WK-D | RD | Nhánh hoãn RD: không thuộc chương trình; điều kiện mở ở ROADMAP §5 và cột điều kiện mở ở trên |
| WK-L | WF-L | hoãn | WK-L | RL | Nhánh hoãn RL: không thuộc chương trình; điều kiện mở ở ROADMAP §5 và cột điều kiện mở ở trên |
| WK-R | WF-R | hoãn | WK-R | RR | Nhánh hoãn RR: không thuộc chương trình; điều kiện mở ở ROADMAP §5 và cột điều kiện mở ở trên |
| WK0 | WF-M1 | giữ | WK0 | R00 | Kit-guard và bộ tự kiểm tài liệu là nền của mọi bộ kiểm; vẫn làm trong bước trình |
| WK1a | WF-M1 | tách | WK00, WK04a, WK04b | R00, R04 | Bộ kiểm chia theo release của phần nó kiểm: T20, T48a ở R00; quyền ở R04 |
| WK1b | WF-M1 | tách | WK00, WK04a, WK04b, WK05a | R00, R04, R05 | T13a, T49a ở R00; T03, T05, T25 ở R04; T06, T22, T31 ở R05 |
| WK2a | WF-M2 | tách | WK03, WK04a, WK05a, WK05b, WK08 | R03, R04, R05, R08 | T41 ở R03; T04a ở R04; finding, sửa ở R05; T04b, song song ở R08 |
| WK2b | WF-M2 | tách | WK01, WK02, WK03, WK05a, WKX1, WKP, WKN | R01, R02, R03, R05, RX1, RP, KN | Trình ở R01; outcome, gói tiếp tục ở R02; thông báo ở R03; finding trong bàn giao ở R05; tài liệu ở RX1; provider ở RP; nối R01–R02 ở KN |
| WK3 | WF-M3 | tách | WK00, WK01, WK03, WK04a, WK05b, WK08, WKN | R00, R01, R03, R04, R05, R08, KN | T09a ở R00; T27 ở R01; T43b, T47a ở R03; T02, T36a ở R04; quyết định ở R05; T01 ở R08; T36c, T47b ở KN |
| WK4 | WF-M4 | tách | WK03, WK05b, WK08 | R03, R05, R08 | T15b ở R03; T08a ở R05; T07b, T08b, T15c, T30 ở R08 |
| WK5 | WF-M5 | tách | WK00, WK01, WK04b, WKP, WKX2, WKPL | R00, R01, R04, RP, RX2, PL | Đóng gói và diễn tập theo từng release; pilot và cổng cuối ở WKPL |
| W01 | WF-M1 | chuyển | W01 | R04 | R04: quyền cấp trong root là nền của R04; khảo sát chỉ đọc |
| W02 | WF-M1 | chuyển | W02 | R04 | R04: hợp đồng root có quyền cấp và lint, phần lõi của R04 |
| W03 | WF-M1 | chuyển | W03 | R00 | R00: R01 (bản ghi HD-05 ở T50b), R02, R03, R04 cùng cần ghi quyết định đúng chủ thể; R00 là tổ tiên chung duy nhất (ROADMAP §7 cập nhật) |
| W04 | WF-M1 | chuyển | W04 | R04 | R04: revision kế hoạch nội bộ tách khỏi hợp đồng |
| W05 | WF-M1 | chuyển | W05 | R04 | R04: kiểm làm yếu acceptance đi cùng quyền |
| W06 | WF-M1 | chuyển | W06 | R04 | R04: ba trạng thái node và `requires` cho engine tuần tự |
| W07 | WF-M1 | chuyển | W07 | R05 | R05: evidence theo artifact; lát trước chỉ đọc evidence của v2 hiện có |
| W08 | WF-M1 | chuyển | W08 | R05 | R05: căn cứ tái dùng evidence đi với finding và kiểm lại |
| W09 | WF-M1 | chuyển | W09 | R05 | R05: release đầu dùng evidence dài hạn (finding, repair) |
| W10 | WF-M1 | chuyển | W10 | R04 | R04: ngân sách không reset qua chia, retry, restart |
| W11 | WF-M1 | tách | W11a, W11b | R00, R04 | Sổ loại sự kiện và bộ so bản cũ ở R00 (mọi release sau ghi sự kiện cần chúng); version workflow ở R04 |
| W12 | WF-M1 | tách | W12a, W12b | R00, R04 | Kiểm tên và từ chối trùng tên ở R00 (an toàn, không đổi đường dẫn); namespace, một nguồn duyệt, một writer ở R04 |
| W13 | WF-M2 | chuyển | W13 | R04 | R04: chọn engine cho lát tuần tự trước khi mở song song |
| W14 | WF-M2 | tách | W14a, W14b | R04, R08 | Tuần tự một slot ở R04; song song ở R08 |
| W15 | WF-M2 | chuyển | W15 | R08 | R08: snapshot khi code chạy song song; tuần tự đã có ghim artifact của v2 |
| W16 | WF-M2 | chuyển | W16 | R05 | R05: node chuẩn bị test trước implementation trên engine tuần tự |
| W17 | WF-M2 | chuyển | W17 | R05 | R05: finding register cho plan v2 |
| W18 | WF-M2 | chuyển | W18 | R05 | R05 (tuần tự); dừng worker tại điểm an toàn thuộc W33b, W36 ở R08 |
| W19 | WF-M2 | chuyển | W19 | R05 | R05: sửa ca hỏng trước rồi phần ảnh hưởng |
| W20 | WF-M2 | chuyển | W20, W51 | R05 | R05; phần không dừng nhầm việc đang tiến triển tách thành W51 |
| W21 | WF-M2 | chuyển | W21 | R05 | R05: node tích hợp chặn `verified` |
| W22 | WF-M2 | chuyển | W22 | RX1 | RX1: adapter tài liệu dạng verifier của v2, không cần engine |
| W23a | WF-M2 | tách | W23a, W32a, W23d | R01, R03, R05 | Trình và bàn giao theo acceptance ở R01; dòng trạng thái/ETA ở R03 (W32a); bàn giao theo finding ở R05 |
| W23b | WF-M2 | tách | W23b, W48a, W48b, W23c, W49a, W49b | R02, R03, R06 | Outcome, can thiệp, gói tiếp tục và ngữ cảnh ở R02; số đo ở R03; incident và lesson ở R06 |
| W24 | WF-M2 | tách | W24, W24b | R03 | R03; thông báo ngoại lệ là chính sách mới (RV08) |
| W25 | WF-D | hoãn | W25 | RD | Nhánh hoãn RD: không thuộc chương trình; điều kiện mở ở ROADMAP §5 và cột điều kiện mở ở trên |
| W25b | WF-D | hoãn | W25b | RD | Nhánh hoãn RD: không thuộc chương trình; điều kiện mở ở ROADMAP §5 và cột điều kiện mở ở trên |
| W26 | WF-M3 | chuyển | W26 | R05 | R05: quyết định review theo quy tắc; R08 dùng lại |
| W27a | WF-M3 | chuyển | W27a | R00 | R00: sửa lỗi của 2.2; RP và R01 cùng dùng |
| W27b | WF-D | hoãn | W27b | RD | Nhánh hoãn RD: không thuộc chương trình; điều kiện mở ở ROADMAP §5 và cột điều kiện mở ở trên |
| W28 | WF-D | hoãn | W28 | RD | Nhánh hoãn RD: không thuộc chương trình; điều kiện mở ở ROADMAP §5 và cột điều kiện mở ở trên |
| W29 | WF-D | hoãn | W29 | RD | Nhánh hoãn RD: không thuộc chương trình; điều kiện mở ở ROADMAP §5 và cột điều kiện mở ở trên |
| W30 | WF-M3 | tách | W30a, W30b, W30c | R01, R03, R05 | Thẻ quyết định ở R01; ghi câu trả lời và lựa chọn ở R03; áp lựa chọn thành trạng thái ở R05 (cần sự kiện lớp B, chỉ có trên root `plan-ns:` từ R04) |
| W31 | WF-M3 | tách | W31a, W31b | R01, R04 | Khảo sát có trần ở bước 0 (R01); unknown có phạm vi trong thực thi (R04) |
| W32 | WF-M3 | tách | W32a, W32b | R03, R04 | Baseline, ETA, phát sinh ở R03; trần và luật chia task ở R04 |
| W33 | WF-M4 | tách | W33a, W33b | R03, R08 | Quan sát và khai capability ở R03; interface executor đầy đủ ở R08 |
| W34 | WF-R | hoãn | W34 | RR | Nhánh hoãn RR: không thuộc chương trình; điều kiện mở ở ROADMAP §5 và cột điều kiện mở ở trên |
| W35 | WF-R | hoãn | W35 | RR | Nhánh hoãn RR: không thuộc chương trình; điều kiện mở ở ROADMAP §5 và cột điều kiện mở ở trên |
| W36 | WF-M4 | chuyển | W36 | R08 | R08: generation và kết quả muộn cần chạy song song |
| W37 | WF-M4 | tách | W37a, W37b | R05, R08 | Reconcile trước retry ở R05; intent bền qua crash ở R08 |
| W38a | WF-M5 | thay thế | W40-R01, W40-RX1 | R01, RX1 | Diễn tập mỗi build: root code ở W40-R01 (T33b), root tài liệu ở W40-RX1; mỗi W40-Rnn diễn tập phần của nó |
| W38b | WF-M5 | chuyển | W38b | PL-A | PL-A: ba việc thật đầu tiên trên bản dùng thử có R02, R03, RX1 |
| W38c | WF-M5 | chuyển | W38c | PL-B | PL-B: pilot tích lũy đủ 10 việc và bốn loại |
| W39 | WF-M5 | chuyển | W39 | RX2 | RX2: adapter dữ liệu và vận hành, thêm khi dùng loại đó |
| W40 | WF-M5 | tách | W40, W40-R01, W40-R02, W40-R03, W40-R04, W40-R05, W40-R06, W40-R07, W40-R08, W40-RP, W40-RX1, W40-RX2 | R00, R01, R02, R03, R04, R05, R06, R07, R08, RP, RX1, RX2 | Khung ở R00; mỗi release đóng gói và kiểm bản cài phần của nó |
| W41 | WF-M5 | tách | W41, W40-R01, W40-R02, W40-R03, W40-R04, W40-R05, W40-R06, W40-R07, W40-R08, W40-RP, W40-RX1, W40-RX2 | R00, R01, R02, R03, R04, R05, R06, R07, R08, RP, RX1, RX2 | Khung diễn tập ở R00 (2.1 → 2.2.x); mỗi release diễn tập nâng cấp/quay lại phần của nó |
| W42 | WF-L | hoãn | W42 | RL | Nhánh hoãn RL: không thuộc chương trình; điều kiện mở ở ROADMAP §5 và cột điều kiện mở ở trên |
| W43 | WF-M2 | chuyển | W43 | RP | RP: reviewer và cố vấn theo provider, nhánh phát hành sớm sau R00 |
| W44 | WF-M2 | chuyển | W44 | R03 | R03: `verdict.run_started` và bốn kết cục (P1.1) |
| W45 | WF-M5 | chuyển | W45 | RP | RP: sáu ô provider × vai trò chạy thật |
| W46 | WF-M1 | tách | W46a, W46b | R00, R04 | Scan root `plan:`, chặn đọc và chặn tiếp tục ở R00; namespace, B1, B3 ở R04 |
