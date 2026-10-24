# FEATURE-SCOPE — chương trình workflow chung (dev)

Nguồn sự thật: `outputs/onecrew-as-qc/workflow-chung/04-TASKS.vi.md` (task, kết quả, dependency, testcase) và `05-TESTCASES.vi.md` (acceptance). Hash nguồn khi sinh: 03 99410bcc4923, 04 c1d8f8ae40cd, 05 0e208d2fb77c. File này chỉ thêm cột trạng thái dev; sinh lại bằng `gen_scope.py`, không sửa tay phần bảng.

Trạng thái: `DONE` = đủ hành vi, nối vào đường dùng, test đạt trên revision tích hợp ghi ở cột; `TÍCH HỢP` = agent xong, chờ ghép/kiểm lại; `ĐANG LÀM` (owner); `CHƯA`; `CHƯA KIỂM CHỨNG` = cần provider/tài khoản/thiết bị bên ngoài; `NGOÀI DEV` = dùng thật/nghiệm thu, ngoài nhiệm vụ development.

## R00

| ID | Kết quả bắt buộc (rút gọn từ 04) | Phụ thuộc | Testcase | Trạng thái | Code / test / bằng chứng |
|---|---|---|---|---|---|
| WK0 | Làm trong bước trình, trước khi duyệt (03 §6). Khung kit của chương trình: kit-guard (manifest sha256, chỉ thêm sau khi đóng băng, … | — | T38a, T39 | CHƯA | R00 dùng unittest trong tests/; chưa có kit-guard và lệnh cổng |
| WK00 | Bộ kiểm R00: T09a, T13a, T13b, T20, T33a, T45a, T48a, T49a, T49b | WK0 | — | CHƯA | chưa có lệnh cổng R00 (T45a chưa có test) |
| W03 | Bản ghi quyết định (chủ thể thật, căn cứ, bằng chứng, phạm vi, hiệu lực); `interventions` vào wheel; từ chối `by=owner` trong phiên AI | WK00 | T20; kiểm chung: T16a | DONE | KiroCrew wf/r00 28bcf48; `onecrew/v2/decisions.py`; tests/test_wf_decisions.py 8 OK (chạy lại c3ad00a) |
| W11a | Sổ loại sự kiện trên anchor bản cũ thấy (00 §6.1): chỉ ghi lớp 0 (giữ mọi trường cũ, cùng kiểu) hay lớp A lên anchor `plan:`, không dùng … | WK00 | T13a | DONE | fa35f8d; `onecrew/v2/compat.py`, guard plan.emit; tests/test_wf_events.py 10 OK |
| W12a | Kiểm tên plan trước khi ghi (từ chối `:`, ký tự đường dẫn, dạng ổ đĩa, đường dẫn tuyệt đối) ở mọi đường tạo; hai project cùng state root mà … | WK00 | T48a | DONE | aa2c54d; plan.py valid_plan_name; tests/test_wf_plan_names.py 5 OK |
| W46a | Lệnh chỉ đọc `compat scan` trong wheel: mỗi root anchor `plan:` có ba tính chất (giữ nguyên, bản cũ đọc được, bản cũ tiếp tục được), trạng … | W11a, WK00 | T49a | DONE | 43359ac; `onecrew compat scan`; tests/test_wf_compat_scan.py 9 OK |
| W27a | Lỗi provider của cố vấn có kiểu (không dùng được, quá giờ, sai schema): verdict `inconclusive` kèm lý do, không còn thành `advice_missing` … | WK00 | T09a | DONE | 1cb048d; verifiers/advisor.py, step0.py; tests/test_wf_advisor_errors.py 7 OK |
| W40 | Khung đóng gói và kiểm bản cài, dùng lại cho mọi release: module cần thiết vào wheel (hoặc tách module mới để tránh `V1_ONLY`); kịch bản … | W03, W11a, W12a, W46a, W27a, WK00 | T33a | DONE | 05bdb76; v2/boundary.py, tests/wf_wheel.py; tests/test_wf_packaging.py 10 OK |
| W41 | Khung diễn tập nâng cấp, rollback và roll-forward trên bản sao sổ, dùng lại cho mọi release; ở R00 là 2.1 → 2.2.x. `compat scan` (W46a) … | W40, W46a | T13b, T49b | DONE | c3ad00a; tests/wf_rollback.py; tests/test_wf_rollback.py 8 OK |

## R01

| ID | Kết quả bắt buộc (rút gọn từ 04) | Phụ thuộc | Testcase | Trạng thái | Code / test / bằng chứng |
|---|---|---|---|---|---|
| WK01 | Bộ kiểm R01: T24a, T27, T33b, T38b, T42, T50a, T50b, T54a | WK0 | — | CHƯA |  |
| W47 | Đề xuất vừa đủ ở bước 0: một phương án ưu tiên, kết quả trước–sau, căn cứ chọn phương án ít tác động mà đủ đạt; mỗi thay đổi nối với một … | WK01, W27a | T50a | CHƯA |  |
| W23a | Báo cáo bàn giao theo acceptance (HD-31) và `plan present` tối giản (P1.2): một trang sinh từ sổ, không gọi model (yêu cầu, kết quả bàn … | WK01 | T42, T24a, T38b | CHƯA |  |
| W30a | Một schema thẻ quyết định (REQ/CREQ/`decisions`): vấn đề, lựa chọn, đề xuất, bằng chứng, phạm vi, mốc phải quyết; bước 0 chỉ trình lựa chọn … | WK01, W03 | T50b | CHƯA |  |
| W31a | Khảo sát/PoC ở bước 0 có trần, điều kiện kết thúc, phạm vi chỉ đọc; unknown ghi `affected`, `required_by` ngay khi đề xuất | WK01 | T27 | CHƯA |  |
| W40-R01 | Phát hành R01: module mới vào wheel, kịch bản R01 chạy từ bản cài với kiểm ranh giới module của T33a; diễn tập nâng cấp R00 → R01 và … | W47, W23a, W30a, W31a, W40, W41 | T54a, T33b | CHƯA |  |

## R02

| ID | Kết quả bắt buộc (rút gọn từ 04) | Phụ thuộc | Testcase | Trạng thái | Code / test / bằng chứng |
|---|---|---|---|---|---|
| WK02 | Bộ kiểm R02: T35a, T46a, T51a, T51b, T54b | WK0 | — | CHƯA |  |
| W23b | Ghi outcome (A1, cùng định dạng `learning.outcome`) cho mọi kết cục, can thiệp (A4, `control.intervention` qua `interventions.record`), gói … | W03, W11a, WK02 | T35a, T46a | CHƯA |  |
| W48a | Ngữ cảnh ghi trong lúc làm bằng sự kiện `context.entry` (lớp A) trên anchor, không thêm bảng hay đổi version schema của sổ … | W23b, WK02 | T51a | CHƯA |  |
| W48b | Truy xuất ngữ cảnh hai phạm vi bằng một cơ chế: project (dữ kiện riêng) và chung (nội dung đã khái quát, có điều kiện và nguồn); không tự … | W48a, WK02 | T51b | CHƯA |  |
| W40-R02 | Phát hành R02: theo quy trình chung của T54 (khung W40, W41 ở R00) cho phần của R02; lớp A mới (`learning.outcome`, `control.intervention`) … | W23b, W48a, W48b, W40, W41 | T54b | CHƯA |  |

## R03

| ID | Kết quả bắt buộc (rút gọn từ 04) | Phụ thuộc | Testcase | Trạng thái | Code / test / bằng chứng |
|---|---|---|---|---|---|
| WK03 | Bộ kiểm R03: T12, T15b, T35d, T36b, T41a, T41b, T43a, T43b, T43c, T47a, T54c | WK0 | — | CHƯA |  |
| W44 | `verdict.run_started` (P1.1): ghi sự kiện bắt đầu chạy khi `verdict run` bắt đầu; Stop hook coi mốc đang chạy là đang chạy; thiết kế và … | WK03, W11a | T41a, T41b | CHƯA |  |
| W33a | Quan sát có nguồn: adapter khai capability (bắt đầu, dừng, pause tại điểm an toàn, cô lập, đo, recovery); ghi start/end/wait theo attempt, … | WK03 | T15b | CHƯA |  |
| W32a | Baseline ước lượng theo khoảng, ghi một lần ngay sau `plan.approved` bằng sự kiện `estimate.baseline` (lớp A; hợp đồng v2 không có trường … | W33a, W44, W23a, WK03 | T36b | CHƯA |  |
| W23c | Số đo hiệu quả lấy từ sổ bằng hàm đánh giá v1 qua adapter (02, TD27): thời gian tới đầu ra, rework, quyết định của người dùng theo động từ … | W44, WK03 | T35d | CHƯA |  |
| W24 | Ba trạng thái riêng `verified` / `accepted` / thông báo đã giao (HD-31); đúng một thông báo cho mỗi sự kiện cần chủ sở hữu (duyệt, câu hỏi, … | W23a, WK03 | T12, T43a | CHƯA |  |
| W24b | Thông báo ngoại lệ (đổi có chủ đích so với W24 cũ), ghi bằng `notice.exception` (lớp A) để outbox v1 đọc từ sổ: lệch đáng kể so với … | W24, W32a, WK03 | T43c | CHƯA |  |
| W30b | Câu trả lời được ghi đúng (A6, phần không đổi trạng thái): lệnh đọc và lệnh trả lời câu hỏi trong wheel (động từ của chủ sở hữu); lựa chọn … | W24, W30a, WK03 | T47a, T43b | CHƯA |  |
| W40-R03 | Phát hành R03: theo quy trình chung của T54 (khung W40, W41 ở R00) cho phần của R03; `verdict.run_started`, `verdict.run_abandoned` chứng … | W44, W33a, W32a, W23c, W24, W24b, W30b, W40-R01, W40, W41 | T54c | CHƯA |  |

## R04

| ID | Kết quả bắt buộc (rút gọn từ 04) | Phụ thuộc | Testcase | Trạng thái | Code / test / bằng chứng |
|---|---|---|---|---|---|
| WK04a | Bộ kiểm R04, nhóm quyền và kế hoạch: T02, T03, T04a, T16a, T17a, T19, T21, T36a, T37 | WK0 | — | CHƯA |  |
| WK04b | Bộ kiểm R04, nhóm trạng thái và tương thích: T05, T25, T26, T32, T48b, T49c, T49d, T54d | WK0 | — | CHƯA |  |
| W01 (S) | Câu trả lời: ánh xạ từng trường `authority` của v1 (`edit`, `commands`, `local_branches`, `branch_at`, `apply_to_project`, `edit_tests`, … | — | — | CHƯA |  |
| W02 | Hợp đồng root có quyền cấp (ghi, lệnh, nhánh, sửa test, trần ngân sách/deadline, danh sách tự quyết); lint và niêm phong; kiểm "kế hoạch ⊆ … | W01, W03, WK04a | T17a; kiểm chung: T16a, T37 | CHƯA |  |
| W04 | Revision kế hoạch nội bộ (`plan.revised`) tách khỏi revision hợp đồng; trong quyền thì không cần duyệt | W02, W03, WK04a | T16a; kiểm chung: T03 | CHƯA |  |
| W05 | Phân loại đổi acceptance (HD-04) và phát hiện làm yếu bộ kiểm qua hash/manifest | W04 | T21, T19 | CHƯA |  |
| W06 | Ba trạng thái node; dependency khai `requires`; hàm "đủ điều kiện chạy" theo trạng thái | WK04b, W02 | T05, T37 | CHƯA |  |
| W10 | Ngân sách và deadline không reset qua chia/retry/restart; đóng lỗ "khoá khác thì ngân sách mới" trong cùng root | W02, W04, WK04a | T03; kiểm chung: T32 | CHƯA |  |
| W11b | Version workflow và capability khai trong root; plan schema 2 giữ semantics | W11a, WK04b | T25 | CHƯA |  |
| W12b | Một nguồn duyệt (SOL liên kết như solution revision); một writer mỗi root; không gian tên theo project (A8): root mới (schema 2 và workflow … | W02, W10, W11b, W12a | T26, T32, T48b | CHƯA |  |
| W46b | `compat scan` mở rộng cho anchor `plan-ns:` (đóng băng khi rollback), tên trùng, B1 (active plan trỏ root bản cũ không thấy), B3 (anchor … | W46a, W12b, WK04b | T49c | CHƯA |  |
| W13 (S) | Câu trả lời: engine cho lát tuần tự R04 (mô hình node/cạnh/generation của delivery, `parallel.ready_batch` với một slot, hay mở rộng … | — | — | CHƯA |  |
| W14a | Root chạy task tuần tự theo engine đã chọn, dependency theo trạng thái (HD-15), một slot. Lớp mỏng nối các hàm tái dùng (`ready_batch`, mô … | W13, W06, WK04a | T04a; kiểm chung: T16b, T17b | CHƯA |  |
| W31b | Unknown trong thực thi có `affected`, `required_by`, chủ thể giải; giữ cục bộ hoặc toàn cục trên engine tuần tự; unknown chặn ước lượng thì … | W14a, WK04a | T02 | CHƯA |  |
| W32b | Trường ước lượng (khoảng) cho task của kế hoạch nội bộ; trần mỗi task; luật chia (chia khi vượt trần; việc không chia được có lý do và trần … | W31b, W10, W04, WK04a | T36a | CHƯA |  |
| W40-R04 | Phát hành R04: theo quy trình chung của T54 (khung W40, W41 ở R00) cho phần của R04; root mới mang anchor `plan-ns:`, nên diễn tập rollback … | W01, W02, W04, W05, W06, W10, W11b, W12b, W46b, W13, W14a, W31b, W32b, W40, W41 | T54d, T49d | CHƯA |  |

## R05

| ID | Kết quả bắt buộc (rút gọn từ 04) | Phụ thuộc | Testcase | Trạng thái | Code / test / bằng chứng |
|---|---|---|---|---|---|
| WK05a | Bộ kiểm R05, nhóm evidence và finding: T06, T07a, T11, T15a, T17b, T22, T24b, T28, T31, T38c | WK0 | — | CHƯA |  |
| WK05b | Bộ kiểm R05, nhóm vòng sửa, quyết định, tích hợp: T04c, T08a, T16b, T16c, T17c, T18a, T18b, T29, T43d, T47c, T54e | WK0 | — | CHƯA |  |
| W07 | Biên nhận gắn thêm input, cấu hình, môi trường; stale nêu đúng thứ đổi | W06, WK05a | T06 | CHƯA |  |
| W08 | Căn cứ tái dùng evidence được ghi; căn cứ chỉ là `scope.neutral` đã khai hay căn cứ theo hành vi có bằng chứng, không theo đường dẫn; không … | W07 | T22 | CHƯA |  |
| W09 | Retention: ref cục bộ giữ cây và blob mà evidence tham chiếu; không push; không tự xoá ref, chỉ chủ sở hữu dọn; hook chặn `git push` có … | WK05a | T31 | CHƯA |  |
| W16 | Node chuẩn bị test từ acceptance chạy trước implementation | W14a, WK05b | T04c | CHƯA |  |
| W17 | Finding register cho plan v2 (A3; phần "không thêm cổng" của đề xuất `DE-XUAT-LO3-A3-A5` không theo, vì HD-25 giữ nhánh bị ảnh hưởng): tách … | WK05a | T28; kiểm chung: T07a | CHƯA |  |
| W18 | Phạm vi ảnh hưởng theo dependency + phạm vi đọc/ghi; giữ nhánh (tuần tự: không chạy task bị ảnh hưởng; executor bên ngoài: chặn ghi; worker … | W14a, W17 | T07a, T15a, T17b; kiểm chung: T16b | CHƯA |  |
| W19 | Repair task; chạy lại ca từng hỏng trước, rồi phần bị ảnh hưởng; vô hiệu hoá theo generation | W18 | T38c; kiểm chung: T11, T18a, T16b | CHƯA |  |
| W51 | Không dừng nhầm việc đang tiến triển. Tách phần dùng chung của `progress.observe` (đếm lặp theo hash kết quả công cụ; luật khảo sát: nguồn … | W33a, W19, WK05b | T18b | CHƯA |  |
| W20 | Vòng sửa không tiến triển → tự chẩn đoán, replan trong quyền, hoặc blocker có bằng chứng | W19, W51 | T18a | CHƯA |  |
| W21 | Node tích hợp: unit xanh mà tích hợp đỏ thì root chưa `verified` | W14a, W19 | T11 | CHƯA |  |
| W23d | Bàn giao theo finding: báo cáo và `plan present` liệt kê finding còn mở lấy từ register (W17), finding đã đóng có bằng chứng thì không | W23a, W17, WK05a | T24b | CHƯA |  |
| W26 | Lớp quyết định theo quy tắc: `SKIP`/`DEFER`/`REVIEW`/`HOLD` có lý do, bằng chứng, phạm vi, hiệu lực; cache theo (input, revision, policy); … | WK05b, W03, W31b | T29, T16c | CHƯA |  |
| W30c | Áp câu trả lời thành trạng thái trên root `plan-ns:`: trả lời "dừng" đóng root có lý do (`plan.closed`, lớp B); trả lời "tiếp tục" mở lại … | W30b, W12b, W18, WK05b | T47c, T43d | CHƯA |  |
| W37a | Reconcile tối thiểu trong vòng sửa tuần tự: lệnh có kết quả chưa rõ (crash sau dispatch, trước biên nhận) được reconcile trước mọi retry; … | W19, WK05b | T08a | CHƯA |  |
| W40-R05 | Phát hành R05: theo quy trình chung của T54 (khung W40, W41 ở R00) cho phần của R05; sự kiện lớp B (`HOLD`, `DEFER`, intent) chỉ trên root … | W07, W08, W09, W16, W17, W18, W19, W51, W20, W21, W23d, W26, W30c, W37a, W40-R03, W40-R04, W40, W41 | T54e | CHƯA |  |

## R06

| ID | Kết quả bắt buộc (rút gọn từ 04) | Phụ thuộc | Testcase | Trạng thái | Code / test / bằng chứng |
|---|---|---|---|---|---|
| WK06 | Bộ kiểm R06: T52a, T52b, T54f | WK0 | — | CHƯA |  |
| W49a | Incident trong root: nối finding, các attempt, giả thuyết bị bác bỏ; phân biệt test đỏ có chủ đích, lỗi môi trường, lỗi sản phẩm; một … | W17, W19, W48a, WK06 | T52a | CHƯA |  |
| W49b | Lesson sau khi sửa đã kiểm, trước khi root kết thúc: bản project giữ vị trí, revision, test; bản chung là ứng viên đã khái quát có điều … | W49a, W48b, WK06 | T52b | CHƯA |  |
| W40-R06 | Phát hành R06: theo quy trình chung của T54 (khung W40, W41 ở R00) cho phần của R06; `learning.incident`, `learning.lesson` của root v2 … | W49a, W49b, W40-R02, W40-R05, W40, W41 | T54f | CHƯA |  |

## R07

| ID | Kết quả bắt buộc (rút gọn từ 04) | Phụ thuộc | Testcase | Trạng thái | Code / test / bằng chứng |
|---|---|---|---|---|---|
| WK07 | Bộ kiểm R07: T53a, T53b, T54g | WK0 | — | CHƯA |  |
| W50a | Mô tả issue → nghi phạm: tìm chuỗi, route, symbol, thay đổi gần đây; bản đồ project tăng dần; lesson liên quan (W48b); danh sách nghi phạm … | W48b, WK07 | T53a | CHƯA |  |
| W50b | Ảnh issue: chỉ đọc ảnh khi provider khai capability vision; không có thì giữ luồng văn bản và không tuyên bố đã hiểu ảnh; đánh giá trên … | W50a, WK07 | T53b | CHƯA |  |
| W40-R07 | Phát hành R07: theo quy trình chung của T54 (khung W40, W41 ở R00) cho phần của R07 | W50a, W50b, W40-R02, W40, W41 | T54g | CHƯA |  |

## R08

| ID | Kết quả bắt buộc (rút gọn từ 04) | Phụ thuộc | Testcase | Trạng thái | Code / test / bằng chứng |
|---|---|---|---|---|---|
| WK08 | Bộ kiểm R08: T01, T04b, T04d, T07b, T08b, T15c, T30, T54h | WK0 | — | CHƯA |  |
| W14b | DAG song song: nhiều slot qua `ready_batch` sau khi một slot đã đúng (W14a); phần độc lập chạy tiếp khi một nhánh bị giữ; không scheduler … | W14a, W18, WK08 | T04d | CHƯA |  |
| W15 | Review và test chạy trên snapshot cố định; code tiếp tục trên phiên bản khác | W14b, W26 | T04b, T01 | CHƯA |  |
| W33b | Interface executor đầy đủ: dừng, pause tại điểm an toàn, cô lập, recovery theo capability đã khai (W33a); adapter Windows (supervisor) và … | W33a, WK08 | T15c | CHƯA |  |
| W36 | Generation; kết quả muộn hay trùng được ghi và bỏ qua; pause tại điểm an toàn cho worker được quản lý | W33b, W18 | T07b | CHƯA |  |
| W37b | Intent bền, idempotency, reconcile qua bốn điểm crash; khôi phục checkpoint khác tự khởi động sau reboot | W33b, W37a | T08b, T30 | CHƯA |  |
| W40-R08 | Phát hành R08: theo quy trình chung của T54 (khung W40, W41 ở R00) cho phần của R08; tạm dừng mới (lớp B) chỉ trên root `plan-ns:` | W14b, W15, W33b, W36, W37b, W40-R03, W40-R04, W40-R05, W40, W41 | T54h | CHƯA |  |

## RP

| ID | Kết quả bắt buộc (rút gọn từ 04) | Phụ thuộc | Testcase | Trạng thái | Code / test / bằng chứng |
|---|---|---|---|---|---|
| WKP | Bộ kiểm RP: T40a, T40b, T40c, T54i | WK0 | — | CHƯA |  |
| W43 | Reviewer và cố vấn theo nhà cung cấp (P1.0): hợp đồng khai `provider` (`claude`, `codex`, `kiro`) kèm `model`; mỗi provider là một lệnh CLI … | WKP, W27a | T40a; kiểm chung: T40b | CHƯA |  |
| W45 | Kiểm thật ma trận provider (R3): chạy mỗi ô của ma trận provider × vai trò (`claude`, `codex`, `kiro` × reviewer, cố vấn) một lần bằng CLI … | W43, W40, WKP | T40b | CHƯA |  |
| W40-RP | Phát hành RP: theo quy trình chung của T54 (khung W40, W41 ở R00) cho phần của RP; giao subset đã kiểm thật (T40c): ghi chú phát hành và … | W43, W45, W40, W41 | T54i, T40c | CHƯA |  |

## RX1

| ID | Kết quả bắt buộc (rút gọn từ 04) | Phụ thuộc | Testcase | Trạng thái | Code / test / bằng chứng |
|---|---|---|---|---|---|
| WKX1 | Bộ kiểm RX1: T14a, T23, T54j | WK0 | — | CHƯA |  |
| W22 | Adapter kiểm cho đầu ra tài liệu dạng verifier của v2 (nguồn, cấu trúc, link/ID); lõi chặn adapter vượt quyền; không cần engine của R04 | WKX1 | T14a, T23 | CHƯA |  |
| W40-RX1 | Phát hành RX1: theo quy trình chung của T54 (khung W40, W41 ở R00) cho adapter tài liệu; diễn tập đầu-cuối một root tài liệu trên bản cài … | W22, W40, W41 | T54j | CHƯA |  |

## RX2

| ID | Kết quả bắt buộc (rút gọn từ 04) | Phụ thuộc | Testcase | Trạng thái | Code / test / bằng chứng |
|---|---|---|---|---|---|
| WKX2 | Bộ kiểm RX2: T14b, T54k | WK0 | — | CHƯA |  |
| W39 | Adapter kiểm cho đầu ra dữ liệu (schema, đối soát, mẫu) và vận hành (pre/postcondition, receipt, reconcile); danh tính artifact không phải … | W22, WKX2 | T14b | CHƯA |  |
| W40-RX2 | Phát hành RX2: theo quy trình chung của T54 (khung W40, W41 ở R00) cho adapter dữ liệu và vận hành; artifact ngoài Git có định danh | W39, W40-RX1, W40, W41 | T54k | CHƯA |  |

## KN

| ID | Kết quả bắt buộc (rút gọn từ 04) | Phụ thuộc | Testcase | Trạng thái | Code / test / bằng chứng |
|---|---|---|---|---|---|
| WKN | Bộ kiểm tích hợp giữa release: T36c, T46b, T47b. Mỗi phần chạy khi bản dựng có đủ hai release của nó | WK0 | — | CHƯA |  |

## PL

| ID | Kết quả bắt buộc (rút gọn từ 04) | Phụ thuộc | Testcase | Trạng thái | Code / test / bằng chứng |
|---|---|---|---|---|---|
| WKPL | Bộ kiểm pilot và cổng cuối: T14c, T35b, T35c, T45b, T45c, T45d, T45e, T40d, T55a | WK0 | — | CHƯA |  |

## PL-A

| ID | Kết quả bắt buộc (rút gọn từ 04) | Phụ thuộc | Testcase | Trạng thái | Code / test / bằng chứng |
|---|---|---|---|---|---|
| W38b | PL-A: 3 việc thật đầu tiên (code, tài liệu) do chủ sở hữu chọn, trên bản cài đặt cô lập (venv + state-root riêng) của một bản dùng thử có … | W40-R01, W40-R02, W40-R03, W40-RX1, WKPL | T35b; cổng vào: T45b | CHƯA |  |

## PL-B

| ID | Kết quả bắt buộc (rút gọn từ 04) | Phụ thuộc | Testcase | Trạng thái | Code / test / bằng chứng |
|---|---|---|---|---|---|
| W38c | PL-B: đủ ít nhất 10 việc thật tích lũy, có ít nhất một việc dữ liệu và một việc vận hành; reviewer khác hãng dùng ô `đạt` thật trong subset … | W38b, W40-RX2, W40-RP, W40-R05, WKPL | T35c, T14c; cổng vào: T45c | CHƯA |  |

## KET

| ID | Kết quả bắt buộc (rút gọn từ 04) | Phụ thuộc | Testcase | Trạng thái | Code / test / bằng chứng |
|---|---|---|---|---|---|
| W38d | Đối chiếu bằng chứng pilot với artifact cuối (03 §5.2), rồi cho mọi cổng chạy trên artifact cuối dùng kết quả đó qua bộ đánh giá hiệu lực … | W38c, W40-R06, W40-R07, W40-R08 | T45e, T55a | CHƯA |  |

## Loại khỏi chương trình (đã hoãn trước, có nguồn)

04 mục "Hoãn: nhánh có điều kiện" và ROADMAP: RD (decider dùng model), RR (tài nguyên), RL (kích hoạt rule) là nhánh hoãn, mở theo điều kiện riêng; không thuộc phạm vi dev này.

| ID | Release | Lý do hoãn (04) |
|---|---|---|
| WK-D | RD | Như W25 |
| W25 (S) | RD | Chương trình WF nghiệm thu, và pilot cho thấy số review tùy chọn đủ lớn để đáng giảm |
| W25b | RD | Như W25, cộng quyền cài/tải |
| W27b | RD | Như W25 |
| W28 | RD | Như W25 |
| W29 | RD | Như W25 |
| WK-R | RR | Như W34 |
| W34 | RR | Máy một người chạy đúng với một slot và thứ tự `ready_batch`. Mở khi pilot ghi nhận chờ tài nguyên hay chạy song song thật |
| W35 | RR | Như W34 |
| WK-L | RL | Như W42 |
| W42 | RL | Sau PL-B, và chỉ khi đánh giá cho thấy cùng một lỗi hay luật vẫn phải nhắc lại (ROADMAP §5 hàng RL, điều kiện của A2). Ghi lesson ở R06 không chờ RL |
