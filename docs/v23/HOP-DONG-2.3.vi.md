# OneCrew 2.3 — hợp đồng triển khai, truy vết và kiểm chứng

Người lập: Claude (Opus 5.5), đầu mối triển khai, 28/10/2026, theo chỉ thị người dùng ngày 28/10 ("Tiếp quản và hoàn thành toàn bộ OneCrew 2.3 … A1, A2 và B") dán trong phiên Claude Code. Đây là hồ sơ thực thi, không phải roadmap: phạm vi lấy từ `outputs/onecrew-as-qc/ROADMAP.vi.md` §0.2 (bản cập nhật 28/10 của Codex), thiết kế §2.4c, §2.4d (MEM-01…05), §2.5, §4 (L1, L2), §7, và bàn giao Claude. Không sửa roadmap, không cộng vào 92 task beta, không đổi DoD của chúng.

## 1. Baseline và cách ly

| Mục | Giá trị |
|---|---|
| Baseline code | `34eb7c4` (2.2.0.dev18); nhánh 2.3 tách từ commit tài liệu `95bb7a6` (code giống từng byte `34eb7c4`) |
| Worktree / nhánh | `D:\TamNT\Workspace\11.OneCrew\wf-v23`, `claude/onecrew-2.3` (local, không push) |
| Beta giữ nguyên | checkout `wf-codex` (`95bb7a6`, sạch), gói `D:\OneCrewRuns\wf-handover-34eb7c4-hs2`, wheel `0346577e…07323ef9bd2` |
| Thư mục chạy 2.3 | `D:\OneCrewRuns\v23\` (venv, project fixture, state root, tmp, gói); công cụ phụ `D:\OneCrewRuns\wf-dev-tools\v23\` |
| Cấu hình người dùng | mọi lệnh `init`/hook/test chạy với `LOCALAPPDATA`, `APPDATA`, `TEMP` riêng cho process thử; không đổi biến toàn máy |
| Version | prerelease `2.3.0.devN`: dev1 = gói A1, các dev sau cho A2/B/cuối |

Tài nguyên đang dùng lúc bắt đầu (28/10 ~13:40, chỉ quan sát): host OneCrew thật `pythonw -m onecrew.host run` (PID 6804), các phiên Claude/Codex khác, KiroCrew. Không dừng, không đọc/ghi sổ `state-v2-real`.

## 2. Phân loại tái sử dụng (trước code)

| Năng lực | Nền có thật (đã đọc) | Phân loại | Phần bổ sung |
|---|---|---|---|
| Kho tri thức có nguồn, nhãn, 2 phạm vi | `onecrew/v2/context.py` (`add`, `observe`, `retrieve`), sự kiện lớp A `context.entry` | Đã có, dùng trực tiếp | payload thêm trường tùy chọn (khả năng áp dụng, phạm vi hiển thị, thay thế/dẫn xuất); không bảng mới, không kind mới |
| Lesson sau sửa đã kiểm, thu hồi, guard root mở | `onecrew/v2/lessons.py` (`record`, `withdraw`, `refine_context`, `_still_open`) | Đã có, thiếu đường nối | dùng lại qua root mới cùng project; thu hồi qua bản dẫn xuất |
| Trang dữ liệu có offset/next/eof, không cắt JSON | `onecrew/paging.py` (v1) | Đã có, thiếu đóng gói | đưa vào wheel (chỉ phụ thuộc `ledger`); dùng cắt trang mục dài |
| Gói có revision/provenance, từ chối ghi theo context cũ | `onecrew/entry.py` (v1) | Đã có, ngữ nghĩa dùng lại | gói tri thức mang revision; cập nhật kèm base, lệch base → mâu thuẫn được giữ |
| Tóm tắt không xác minh ngữ nghĩa | `onecrew/conversations.py` `summarize` (v1: `event_ids`, `covered_seq`, `semantic_verification=unverified`) | Đã có, ngữ nghĩa dùng lại | tóm tắt tri thức giữ `derived_from`, nhãn không cao hơn nguồn (không đóng gói conversations: phụ thuộc lười vào module v1 ngoài wheel) |
| Không suy cause từ test xanh | `onecrew/v2/incidents.py` `finalize` | Đã có | giữ `cause` = chưa xác lập khi chỉ có test xanh |
| Giao cho worker có receipt | `onecrew/common_executor.py` `NativeExecutor.prepare/finish`, receipt `native-node-receipt` | Đã có, thiếu đường nối | gói tri thức trong prompt, blob gói trong receipt, kiểm khai báo sử dụng |
| Phân bổ context, không bỏ authority khi nén | `onecrew/owned.py` `_fit_work` (v1) | Đã có, ngữ nghĩa dùng lại | mục bắt buộc không bị cắt âm thầm; vượt trần → dừng trước khi gọi model |
| Đối chứng cùng điều kiện | `onecrew/evaluation.py` `replay/compare` (v1), `onecrew/evaluation_core.py` | Đã có, thiếu đường nối | harness ba điều kiện wiki |
| Resume pack phiên mới | `onecrew/v2/resume_pack.py` | Đã có | hiển thị gói tri thức theo cùng bộ chọn |
| Cleanup/tiếp quản (2.3-B) | process_core, host, managed_executor, Control, recovery | Khảo sát riêng: `D:\OneCrewRuns\v23\survey-B.md` | theo kết quả khảo sát |

Không tạo memory store, ledger, router, scheduler hay engine thứ hai. Wiki là lớp trình bày/truy xuất; ledger/Control giữ quyền và trạng thái.

## 3. Thiết kế đã chọn (tóm tắt; chi tiết trong docstring module)

- **Nguồn tri thức chuẩn:** (1) trang wiki Markdown của project (mặc định `docs/wiki/`, cấu hình `wiki.paths` trong `.onecrew/config.json`; thư mục ngoài repo được ghim bằng sha256, nội dung lưu blob khi giao); (2) `context.entry`/`learning.lesson` trong sổ. Một bộ đọc chuẩn hóa cả hai thành cùng mô hình mục. Trang wiki xuất từ sổ là bản dẫn xuất mang `ledger_id`/`derived_from`; khi đọc lại, trạng thái trong sổ thắng (thu hồi không sống lại từ bản sao).
- **Quyền:** ranh giới project; phạm vi `general` theo luật cũ; mục `root` (bộ nhớ làm việc) chỉ cho root đó; mục `project` cho root khác cùng project chỉ khi mọi nguồn file nằm trong quyền đọc của consumer (read ∪ write của node).
- **Khả năng áp dụng (MEM-01):** nguồn file đổi (blob khác, kể cả thay đổi chưa commit), điều kiện kiểm được sai, hoặc điều kiện không kiểm được → không dùng như sự thật hiện hành: `recheck` (đầu mối) hoặc `not_applicable` (lịch sử). Refuted có nguồn đổi được mở lại thành đầu mối. Không TTL chung; mục không đổi dùng lại ngay.
- **Chọn và trần (MEM-04):** điểm theo đường dẫn (applies_to/nguồn giao scope node) và từ khóa (goal/acceptance/checks); mục bắt buộc đi trước; mục bắt buộc vượt trần → dừng trước khi gọi model (known not-started); mục tùy chọn bị bỏ được liệt kê kèm lý do, tổng và con trỏ đọc tiếp.
- **Đọc tiếp:** CLI `onecrew wiki read --cursor`; worker native trả `knowledge.requests` cùng `continuation` → lần tiếp tục nhận đúng các mục yêu cầu.
- **Giao và bằng chứng:** gói tri thức (blob `knowledge-package`) là đúng phần chữ đưa vào prompt; receipt node ghi khóa blob, id đã giao, số ký tự. Không có kind sự kiện mới.
- **Kiểm sử dụng:** worker khai `knowledge.used/rejected`; core kiểm id có được giao, mục bắt buộc có được xác nhận, đầu mối có bị dùng như sự thật; kết quả ghi `knowledge_use` trong receipt. Đây là kiểm cấu trúc; hành vi đúng do checks của node chứng minh.
- **A2 ghi có bằng chứng:** `context.entry` với `evidence.status`, `verified_property`, `cause`, `visibility`, `conditions`, `supersedes`/`withdraws`, `derived_from`, `base`; ghi tự động tại điểm có bằng chứng; tri thức worker tự khai chỉ là quan sát/giả thuyết cho tới khi check xác nhận. Ghi dựa trên base cũ → giữ thành mâu thuẫn, không mất bản nào. Sau khi root kết thúc không ghi vào root đó; đính chính ghi trên root đang mở có quyền, dẫn nguồn.

## 4. Requirement → tái dùng → task → testcase → bằng chứng

Cột "Bằng chứng" là lượt chạy trên code cuối `bba3da6` (số đo trên `4182ee5`, cùng code): log 2.3 = `D:\OneCrewRuns\v23\logs\final-bba3da6-v23.txt` (mọi module `tests/test_v23_*` + `test_g1_core` + `test_wf_r7_t51b` + `test_wf_r03a_executors`: 154/154); số đo trong `docs/v23/evidence/` mang id commit.

Sau review Codex ngày 28/10 trên gói `2.3.0.dev2` (§7), code cuối là `6a8421d` (gói `2.3.0.dev3`). Bảng dưới giữ bằng chứng của bản dev2; bằng chứng bổ sung cho A1-R3, A1-R4, A1-R9, A1-R10, A2-R5, A2-R6, A2-R8 và PK-R1 nằm ở §7, kết quả gói và gate ở `BAO-CAO-2.3-DEV3-2026-10-29.vi.md`.

| Req | Yêu cầu (rút gọn từ chỉ thị + thiết kế) | Tái dùng | Task | Testcase / phản chứng | Bằng chứng |
|---|---|---|---|---|---|
| A1-R1 | Truy xuất có nguồn theo task, revision | context.retrieve, snapshots | T23-A1-1 | KA-01 nguồn/revision/blob trên mọi mục; KA-02 trang wiki đổi → revision mới | KA-01, KA-02 (`test_v23_a1_knowledge`) — log 2.3; gói V4 (receipt niêm phong gói) |
| A1-R2 | Theo quyền consumer; không lộ root/project khác | context scopes, namespaces | T23-A1-1 | KA-03 project khác không thấy; KA-04 nguồn ngoài quyền đọc không giao; KA-05 mục root riêng không sang root khác | KA-03…05; T51b dựng lại 4/4 (`test_wf_r7_t51b`); review r1 p03/p05, r3 R3-1 — log 2.3; gói V5a |
| A1-R3 | Mức liên quan + giới hạn context; không bỏ ràng buộc âm thầm | owned._fit_work (ngữ nghĩa) | T23-A1-2 | KA-06 >200 mục không liên quan không đẩy mất mục bắt buộc cũ; KA-07 bắt buộc vượt trần → dừng trước model; KA-08 bỏ tùy chọn có danh sách + tổng | KA-06…08; review r1 p13a/p13b/p18 — log 2.3; gói V5c (dừng trước model, fake 0 lượt) |
| A1-R4 | Lịch sử ≠ áp dụng hiện tại; xét lại khi nguồn/điều kiện đổi | context._stale_reason, lessons.refine_context | T23-A1-2 | KA-09 refuted với nguồn đổi → đầu mối; KA-10 nguồn không đổi nhưng cấu hình/dependency đổi → không dùng như sự thật; KA-11 điều kiện chưa kiểm được → đầu mối; KA-12 không đổi → dùng lại, không đánh dấu kiểm lại | KA-09…12; review r1 p12/p19/p24 — log 2.3; gói V5b (lead/recheck) |
| A1-R5 | Đường đọc tiếp khi thiếu | paging v1 | T23-A1-3 | KA-13 con trỏ trả trang kế, không báo hết khi còn; KA-14 nguồn đổi làm con trỏ cũ mất hiệu lực; KA-15 worker yêu cầu mục bị bỏ → lần tiếp tục nhận đúng mục | KA-13…15; review r1 p14/p15 — log 2.3 |
| A1-R6 | Giao qua adapter hỗ trợ, lưu bằng chứng giao thực | NativeExecutor, receipt | T23-A1-3 | KA-16 receipt trỏ blob gói = đúng phần chữ trong prompt; KA-17 lỗi lớp wiki, nguồn gốc đủ → node vẫn chạy, có ghi lỗi | KA-16, KA-17; `test_v23_a1_installed` (wheel cài, process claude giả thật) — log 2.3; gói V4 |
| A1-R7 | Không coi đọc là đã dùng đúng | — | T23-A1-3 | KA-18 khai dùng id không được giao → vi phạm ghi lại; KA-19 dùng đầu mối như sự thật → cảnh báo; checks node quyết định đạt | KA-18/19 — log 2.3; KE-01 `evidence/ke01-4182ee5.json` (`violations` của model thật) |
| A1-R8 | Đối chứng không wiki / wiki đúng / wiki sai-cũ | evaluation v1 | T23-A1-5 | KE-01 harness 3 điều kiện cùng task/input/acceptance/config; số đo thời gian, ký tự context, số lần làm lại, lần bị dẫn sai; provider thật trong quyền có sẵn, ghi riêng | KE-01 `evidence/ke01-4182ee5.json` (claude giả + Claude Code CLI thật) |
| A1-R9 | Kho tăng: đo chi phí truy xuất thực | context.retrieve | T23-A1-4 | KS-01 đo 1k/10k/50k mục, nhiều project; ghi ngưỡng; không tuyên bố khi chưa đo | KS-01 `evidence/ks01-scale-4182ee5.json` |
| A1-R10 | Gói cài chạy không cần checkout v1/wiki máy tác giả | tests/wf_wheel, verify_package | T23-A1-6 | KP-01 venv sạch, `-I`, cwd ngoài, đường dẫn có khoảng trắng, origin module trên đường wiki; KP-02 cp1252 console | `test_v23_a1_installed` (2 test), `test_g1_core` — log 2.3; gói V2, V3, V6 |
| A1-R11 | A1 chưa tự cập nhật nội dung wiki | — | T23-A1-3 | KA-20 chạy A1 không tạo/sửa trang wiki hay mục tri thức mới (chỉ receipt) | KA-20 — log 2.3; gói V4 (`page_unchanged`) |
| A2-R1 | Ghi khi có bằng chứng, không đợi feedback/kết thúc root | engine context hooks, incidents→lessons | T23-A2-1 | KB-01 sửa đã kiểm giữa root → lesson project có nguồn trước khi root kết thúc; KB-02 khai của worker chỉ là quan sát/giả thuyết | KB-01, KB-02, KB-02b; review r1 extra 24/25/32/10b, r2 N3 — log 2.3; gói V8 |
| A2-R2 | Project/general, phạm vi, nguồn, trạng thái bằng chứng, điều kiện | context scopes, propose_general | T23-A2-1 | KB-03 general không mang chi tiết riêng; project không tự thành general | KB-03; review r1 p02/p11 — log 2.3 |
| A2-R3 | Tóm tắt không nâng độ chắc chắn; test xanh không chứng minh nguyên nhân | conversations.summarize, incidents.finalize | T23-A2-2 | KB-04 tóm tắt nhiều lần vẫn "cause chưa xác lập"; KB-05 nguồn lẫn verified/hypothesis → không thành verified; KB-06 bản sao cùng nguồn không tăng nhãn | KB-04/05, KB-06; review r1 p04, extra 33b, r2 N1 — log 2.3 |
| A2-R4 | Revision/provenance; chống mất cập nhật đồng thời | ledger BEGIN IMMEDIATE, entry v1 | T23-A2-2 | KB-07 hai process ghi cùng mục trên base cũ → không mất bản nào, mâu thuẫn giữ rõ | KB-07 (hai process OS); review r1 p05–p08, r2 N13, r3 R3-3; CLI `test_cli_correction_after_a_withdrawal_uses_state_version` — log 2.3 |
| A2-R5 | Sửa/thu hồi có hiệu lực qua wiki/tóm tắt ở lần truy xuất tiếp; không sống lại từ bản sao/cache | lessons.refine_context | T23-A2-3 | KB-08 L thu hồi sau khi vào tóm tắt S → root mới không nhận S như hiệu lực; KB-09 trang wiki xuất ra chứa L → không giao L; KB-10 đối chứng nguồn hợp lệ vẫn truy xuất | KB-08/10, KB-09, NoResurrection; review r1 p22, extra 26, r2 N16 — log 2.3 |
| A2-R6 | Vòng đời: gom trùng/thay thế/lưu trữ; không xóa ledger/receipt | — | T23-A2-3 | KB-11 lưu trữ không cắt nguồn, không hồi sinh mục thu hồi; số sự kiện/receipt không giảm | KB-11; CLI `test_record_history_summarize_withdraw_archive_export`; review r2 N2 — log 2.3 |
| A2-R7 | Root A kết thúc → root B mới, process mới tự truy xuất và dùng | lessons guard, resume | T23-A2-4 | KB-12 ca bắt buộc trên wheel cài: hai process, hai root, ngân sách riêng, không chép tay, không cache A; KB-13 hai node cùng root không được tính là ca này | KB-12 + KB-13 (`test_v23_a2_installed`: hai interpreter `-I`, hai root, B tạo sau khi A kết thúc) — log 2.3; gói V8 |
| A2-R8 | Không đọc/lộ ngoài quyền giữa root/project | context scopes | T23-A2-4 | KB-14 B thiếu quyền nguồn không nhận; project P2 không thấy; mục root riêng của A không sang B | KB-14; KB-12 root hẹp; review r2 N5/N19, r3 R3-1/R3-2 — log 2.3 |
| A2-R9 | Đối chứng hiệu quả mở rộng (tự ghi rồi dùng qua root mới) | harness KE | T23-A2-5 | KE-02 thêm điều kiện tri thức tự ghi; ghi ca dẫn sai/chi phí | KE-02 `evidence/ke02-4182ee5.json` |
| A2-R10 | Guard ghi sau root kết thúc giữ nguyên | lessons._still_open | T23-A2-1 | KB-15 ghi vào root A đã kết thúc bị từ chối; đính chính qua root đang mở | KB-15; KB-12 (ghi muộn bị từ chối); review r1 extra 24 — log 2.3 |
| B-R1…R7 | Cleanup/tiếp quản an toàn (L1) | theo khảo sát | T23-B-* | thiết kế §7: ca 1–7, 14, 15 trên process thật | `test_v23_b_takeover` (T1, T2, T3, T3b, T5, T6, T8, T9, Q4, F1–F5, F10, N1–N4, R3-1, R3-2), `test_v23_b_apply` (T7b), `test_v23_b_copy` (T10, Q6, khai executor), `test_v23_b_installed` — log 2.3; gói V9; review B 4 vòng (`D:\OneCrewRuns\v23\review-b*.md`) |
| PK-R1 | Mỗi mốc: snapshot, version, artifact; kiểm từ wheel thật | build_package/verify_package | T23-PK-* | KP-03 hướng dẫn cài/hash; task đầu tiên chạy được; quay về 2.2 theo bằng chứng tương thích | gói `D:\OneCrewRuns\v23\pkg\onecrew-2.3.0.dev2-final`: kiểm từ artifact V1–V9 (`D:\OneCrewRuns\v23 thu final\verify\verify-report.json`), diễn tập README; gate snapshot 2.2 trên cùng commit (`(gate: xem BAO-CAO-2.3 §4)`) |

## 5. Task, dependency, timebox

| Task | Đầu ra kiểm được | Phụ thuộc | Ước lượng | Thực tế / ghi chú |
|---|---|---|---|---|
| T23-0 | Worktree/thư mục riêng, hợp đồng này | — | 0,5 h | xong 13:45; ~0,2 h |
| T23-A1-1 | Bộ đọc chung (wiki + sổ), quyền consumer | T23-0 | 2 h | xong `4eb76b7` 14:59 (gộp A1-1…3 thành một bộ chọn) |
| T23-A1-2 | Áp dụng/chọn/trần | A1-1 | 2 h | xong `4eb76b7` 14:59 |
| T23-A1-3 | Giao qua NativeExecutor, receipt, kiểm sử dụng, đọc tiếp, CLI | A1-2 | 2,5 h | xong `4eb76b7`/`22e596d` 15:11; sửa theo review r1–r4 đến `9307ade` 18:21 |
| T23-A1-4 | Đo chi phí truy xuất khi kho tăng | A1-1 | 1 h | xong 15:53 (`ks01-scale-41ad32e`); đo lại trên bản cuối `ks01-scale-4182ee5` 19:42 |
| T23-A1-5 | Harness đối chứng 3 điều kiện (fixture + thật trong quyền) | A1-3 | 2 h | xong 15:53 (`ke01-41ad32e`, 8 lượt Claude thật); đo lại `ke01-4182ee5` 19:46 (8 lượt) |
| T23-A1-6 | Gói thử A1 (2.3.0.dev1), kiểm từ artifact | A1-3, A1-4 | 2 h | gói `2.3.0.dev1` lúc 16:08 (`1077c7d`), kiểm 7/7; review sau đó thấy lỗi → gói A1 đánh dấu không dùng tiếp (BAO-CAO-A1 §9) |
| T23-A2-1…5 | Ghi có bằng chứng, tóm tắt, đồng thời, thu hồi, vòng đời, ca 2 root | A1 | 7 h | xong `eb13cba` 15:38 … `e7a2aa9` 16:15; 4 vòng review đến `9307ade` 18:21; ~3 h |
| T23-B-* | Theo khảo sát | T23-0 | 6–8 h | agent riêng (worktree `wf-v23-b`): `72b1b22` 17:39, 4 vòng review đến `3c393d0` 19:29; ~5 h |
| T23-PK-F | Gói cuối 2.3, hồi quy, kiểm từ artifact, báo cáo | tất cả | 4 h | đo lại 19:42–19:54; gói, kiểm từ artifact, gate: BAO-CAO-2.3 §4 |
| T23-CX-1 | P2-01: gói tiếp tục, `context retrieve`, `wiki history` dùng cùng quyết định với gói tri thức | T23-PK-F | 2 h | `581fbca` 22:3x; vòng review sửa đến `6a8421d` |
| T23-CX-2 | P2-02: ràng buộc bắt buộc không mất vì giới hạn đọc, thứ tự tên, trang hỏng; giữ node trước model khi không xác lập được | T23-PK-F | 3 h | `581fbca`; review r1 18 điểm → `989eb9c`, r2 10 → `522a6c9`, r3 3 → `6a8421d` |
| T23-CX-3 | P2-03: task đầu tiên chạy được chỉ với gói (hợp đồng/node mẫu, lệnh, đường dẫn, diễn tập từ gói) | T23-PK-F | 2 h | agent riêng (worktree `wf-v23-ft`): `263cd3b`; gộp `ff8452b` |
| T23-PK-F3 | Gói `2.3.0.dev3`: hồi quy, kiểm từ artifact (11 bước), diễn tập README + task đầu tiên, gate snapshot 2.2 | T23-CX-* | 4 h | BAO-CAO-2.3-DEV3 |
| T23-CX-4 | Review Codex dev3 P2: bản ghi general không áp dụng hoặc chưa kiểm được điều kiện không hiện như sự thật trong `context retrieve` | T23-PK-F4 | 2 h | `6a8e400`; phản chứng `tests/test_v23_codex_review_dev3.py`, V12 |
| T23-U1 | U1 hẹp cho 3 test ghim 2.2 đã sửa cho 2.3 (chủ sở hữu ủy quyền bằng văn bản 29/10) | — | 0,5 h | `26a51c5` |
| T23-PK-F4 | Gói `2.3.0.dev4`: hồi quy, kiểm từ artifact (12 bước), diễn tập README + task đầu tiên, gate snapshot 2.2 | T23-CX-4, T23-U1 | 4 h | BAO-CAO-2.3-DEV4 |

## 6. Nhật ký tiến độ

| Thời điểm | Việc | Ghi chú |
|---|---|---|
| 28/10 ~13:45 | T23-0: worktree `wf-v23` từ `95bb7a6`, thư mục `D:\OneCrewRuns\v23` | beta không đổi |
| 28/10 14:59–16:20 | A1 (bộ đọc, giao, receipt, CLI, gói A1) và A2 (ghi có bằng chứng, vòng đời, ca hai root) | `4eb76b7` … `3312f61` |
| 28/10 16:37–18:21 | review độc lập A1/A2 bốn vòng: 22 → 7 → 3 → 0 phát hiện P1/P2 (vòng 1 tổng 33 kể cả P3) | `a9b1d1d`, `8709bfa`, `1db1507`, `9307ade` |
| 28/10 17:39–19:29 | 2.3-B và bốn vòng review B: 3 → 1 → 0 → 0 phát hiện P1/P2 | `72b1b22`, `d55e4a7`, `f38d118`, `3c393d0`; gộp `bba3da6` |
| 28/10 19:42–19:54 | đo lại KS-01, KE-01, KE-02 trên code cuối (16 lượt Claude thật) | `4182ee5` |
| 28/10 ~21:45 | Codex review gói `2.3.0.dev2` (`38981bd`): 3 finding P2 (P2-01…P2-03); verifier của Codex 9/9 từ gói | `D:\OneCrewRuns\codex-v23-review-20261028` |
| 28/10 22:04–22:30 | testcase đỏ cho P2-01/P2-02 trên `38981bd` (9/12 fail, 3 đối chứng đạt); sửa | `581fbca` |
| 28/10 ~23:00 | dừng gate baseline trên `38981bd` ở 155/286 (đều pass, không có decision; không tính là đạt) | `logs\gate-38981bd-stopped.txt` |
| 28/10 23:00–29/10 00:40 | ba vòng review độc lập bản sửa: 18 → 10 → 3 điểm (P1 0; P2 11 → 3 → 0) | `989eb9c`, `522a6c9`, `6a8421d` |
| 29/10 00:38–01:40 | gói `2.3.0.dev3` từ `0594a43`: kiểm từ artifact 11/11, diễn tập README 9/9, task đầu tiên 23/23; KS-01 song song, KE-01/KE-02 | `66eed3a`, `cbc18d9`; BAO-CAO-2.3-DEV3 §5 |
| 29/10 00:45–04:19 | gate snapshot 2.2 trên `0594a43`: 286/286 check đạt (2 097 test, 0 skip); quyết định `refused`: 23 khoảng trống ngoài như beta + kit-guard (3 test ghim đã sửa, cần chủ sở hữu) | `D:\OneCrewRuns\v23\gates-tmp\wf-snapshot-gate-20261029-0594a43`; BAO-CAO-2.3-DEV3 §5.5 |

## 7. Review Codex 28/10 và sửa

Nguồn finding: chỉ thị người dùng đêm 28/10 (dán trong phiên), bằng chứng của Codex ở `D:\OneCrewRuns\codex-v23-review-20261028` (`installed-continue-probe.json`, `knowledge-probes.json`, `artifact\verify-report.json`). Kết quả 9/9 của Codex chỉ chứng minh các ca đã chạy, không khép các phản chứng này.

| Finding | Requirement chạm | Sửa (code) | Testcase đỏ trước → xanh sau | Bằng chứng từ gói |
|---|---|---|---|---|
| P2-01 gói tiếp tục đưa tri thức cũ ra như đã xác minh | A1-R4, A2-R5, A2-R6, A2-R8 | `context.for_pack`/`judged`, `knowledge.for_root` (cùng `_collect`/`_decide` với gói), `records` theo vòng đời của root, `context retrieve` theo root/commit | `tests/test_v23_codex_review` (Continue, ContinueCli): đỏ trên `38981bd` (log `D:\OneCrewRuns\v23\logs\codex-red-38981bd.txt`), xanh sau | V11 (`verify/scenario_codex.py continue`, CLI cài từ wheel) |
| P2-02 giới hạn số trang làm mất ràng buộc `must` | A1-R3, A1-R9, A1-R6 | `wiki.pages/parse` dò mọi trang, `undelivered`; `knowledge._established` (KnowledgeIncomplete), `declares_mandatory`, đo trang | `tests/test_v23_codex_review` (Mandatory): đỏ 6/8 trên `38981bd`, xanh sau; KS-01 chuỗi số trang | V10 (`scenario_codex.py beyond_pages / undeliverable / optional_broken`, đường dispatch thật, claude giả) |
| P2-03 task đầu tiên chưa tự chạy được từ gói | A1-R10, PK-R1 | `docs/v23/examples/first-task/` (contract.json, nodes.json, fake-policy.json, README), `tools/first_task_drill.py` | đỏ: README cũ từ gói dev2 dừng ở bước đường dẫn (`D:\OneCrewRuns\v23\p2-03\red`); xanh: diễn tập 23/23 (`D:\OneCrewRuns\v23\p2-03\drill run 2`) | diễn tập trên gói cuối (BAO-CAO-2.3-DEV3) |

Review độc lập bản sửa (agent Opus 5.5, probe ghi thành test, chạy đối chứng trên bản trước):

| Vòng | Trên | Kết quả | Sửa | Probe |
|---|---|---|---|---|
| r1 | `581fbca` | 18 điểm: 11 P2, 7 P3, 0 P1; 6 do chính bản sửa gây ra | `989eb9c` (+ hướng dẫn `930bcf0`) | `tests/test_v23_review_codex_r1.py` 23/25 fail trước → 25/25 |
| r2 | `989eb9c` | 10 điểm: 3 P2, 7 P3; 4 do r1 gây ra | `522a6c9` | `tests/test_v23_review_codex_r2.py` 11/14 fail trước → 14/14 |
| r3 | `522a6c9` | 3 P3, 0 P1/P2; cả 3 do r2 gây ra | `6a8421d` | `tests/test_v23_review_codex_r3.py` 3/4 fail trước → 4/4 |

Báo cáo review: `D:\OneCrewRuns\v23\review-codex-r1.md`, `-r2.md`, `-r3.md`. Quyết định thiết kế đã chốt qua các vòng: ràng buộc bắt buộc đã biết mà không giao được, hoặc vượt giới hạn dò, thì giữ node trước model; lỗi làm không biết nội dung (thư mục cấu hình mất, config hỏng, trang không đọc được) thì báo trong gói/receipt, không chặn task độc lập; lỗi bất ngờ của lớp chọn chỉ giữ node khi project có khai báo tri thức bắt buộc. Hai probe được chỉnh có ghi lý do: r1-17 (không có `--plan`, `context retrieve` là danh sách cấp project như 2.2 và `wiki history`), r1-c2 (mục 2.2 giữ nhãn khi bước xét lỗi, theo R2-09); KB-06 và R2-04b cùng đạt (tiêu đề chỉ tính vào chữ ký bản sao với mục bắt buộc).

## 8. Review Codex 29/10 trên gói `2.3.0.dev3` và sửa

Nguồn finding: chỉ thị người dùng 29/10 (dán trong phiên), bằng chứng của Codex ở `D:\OneCrewRuns\codex-v23-dev3-review-20261029` (`installed-general-condition-probe.json`, `installed-general-condition-control.json`, `general-condition-probe.json`). Đính chính: §7 hàng P2-01 và báo cáo dev3 §2 nói các đường đọc dùng "cùng một quyết định" — chỉ đúng với tri thức của project/root; bản ghi general chỉ được xét vòng đời.

| Finding | Requirement chạm | Nguyên nhân | Sửa (code) | Testcase đỏ trước → xanh sau | Bằng chứng từ gói |
|---|---|---|---|---|---|
| P2 general: `context retrieve` trả bản ghi general có điều kiện sai/không kiểm được là `verified` | A1-R4, A2-R2 | `context.judged` chỉ lấy kết quả `knowledge.for_root` cho mục scope project; mục general chỉ được so với `status_by_id` (vòng đời) | `knowledge.for_root` xét cả bản ghi general cho người đọc (root của `--plan`, hoặc project không root khi không có `--plan`; nhớ kết quả mỗi root trong memo); `context.judged(plan=)` dùng kết quả đó cho mục general; bản ghi 2.3 không được xét thì không hiện như hiện hành; CLI truyền `--plan` | `tests/test_v23_codex_review_dev3.py`: 4 phản chứng đỏ trên code dev3 (12 subtest, `'verified' != 'stale'`; log `D:\OneCrewRuns\v23\dev4\logs\red-0594a43.txt`), 4 đối chứng đạt cả hai bản; CLI wheel dev3 đã cài: 8 lỗi, đối chứng đạt (`D:\OneCrewRuns\v23\dev4\cli red dev3\general-cli.json`) | V12 (`verify/scenario_codex.py general`, CLI cài từ wheel của gói) |

U1 (ngoại lệ kit-guard) cho đúng ba test ghim 2.2 mà 2.3 đã sửa, theo ủy quyền bằng văn bản của chủ sở hữu trong chỉ thị 29/10 (mục 3): `wfkit/u1/U1-20261029-V23-PIN-1..3.json` (`26a51c5`), chỉ trên nhánh 2.3. Trước khi ghi đã kiểm: hash bản `95bb7a6` và bản hiện hành khớp với kit-guard, mỗi file chỉ có một commit sửa từ `95bb7a6` (`f045a0b`, `72b1b22`, `3d96f5b`), diff không xóa kiểm tra, không nới oracle. kit-guard development: từ chối đúng 3 file đó trước, đạt sau (`D:\OneCrewRuns\v23\dev4\u1\kitguard-before.json`, `kitguard-after.json`).
