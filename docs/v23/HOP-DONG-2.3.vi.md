# OneCrew 2.3 — hợp đồng triển khai, truy vết và kiểm chứng

Người lập: Claude (Opus 5.5), đầu mối triển khai, 28/10/2026, theo chỉ thị người dùng ngày 28/10 ("Tiếp quản và hoàn thành toàn bộ OneCrew 2.3 … A1, A2 và B") dán trong phiên Claude Code. Đây là hồ sơ thực thi, không phải roadmap: phạm vi lấy từ `outputs/onecrew-as-qc/ROADMAP.vi.md` §0.2 (bản cập nhật 28/10 của Codex), thiết kế §2.4c, §2.4d (MEM-01…05), §2.5, §4 (L1, L2), §7, và bàn giao Claude. Không sửa roadmap, không cộng vào 92 task beta, không đổi DoD của chúng.

## 1. Baseline và cách ly

| Mục | Giá trị |
|---|---|
| Baseline code | `34eb7c4` (2.2.0.dev18); nhánh 2.3 tách từ commit tài liệu `95bb7a6` (code giống từng byte `34eb7c4`) |
| Worktree / nhánh | `D:\TamNT\Workspace\11.OneCrew\wf-v23`, `claude/onecrew-2.3` (local tới dev6; dev7 push lên `origin` cùng tag khi phát hành, §10.5) |
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
| T23-PK-F4 | Gói `2.3.0.dev4`: hồi quy, kiểm từ artifact (12 bước), diễn tập README + task đầu tiên, gate snapshot 2.2 | T23-CX-4, T23-U1 | 4 h | dựng và kiểm, không bàn giao (review tìm thêm lỗi; gate dừng) |
| T23-CX-5 | Review độc lập bản sửa T23-CX-4: F1/F1b (mục general bị thay thế lại hiện), F2/F3/r03 (kết quả xét bị cho mượn giữa bản ghi trùng id) | T23-PK-F5 | 1,5 h | `9a2b453`; `tests/test_v23_review_dev4.py`; F4 (id trùng giữa project) còn mở |
| T23-PK-F5 | Gói `2.3.0.dev5`: hồi quy, kiểm từ artifact (12 bước), diễn tập README + task đầu tiên, gate snapshot 2.2 | T23-CX-5 | 4 h | BAO-CAO-2.3-DEV5 |
| T23-CX-6 | Codex review gói `2.3.0.dev5`: P2-A script thử, P2-B trùng khóa tri thức giữa project, P2-C `.env.example`, P2-D `[S1][S2]` | T23-PK-F6 | 6 h | §9; BAO-CAO-2.3-DEV6 §2 |
| T23-CX-7 | Review độc lập bản sửa T23-CX-6 (ba vòng): R1–R15, D1–D8 | T23-PK-F6 | 4 h | §9; `D:\OneCrewRuns\v23\review-dev6\review-p2b.md` |
| T23-PK-F6 | Gói `2.3.0.dev6`: hồi quy, kiểm từ artifact (14 bước), diễn tập README + task đầu tiên + script thử, phản chứng trên wheel cài, dữ liệu cũ, gate snapshot 2.2 | T23-CX-7 | 5 h | BAO-CAO-2.3-DEV6 §5 |
| T23-WI-1 | `init` tạo hoặc dùng lại wiki an toàn (WI-01…05, KW-01…15); `onecrew --version` | §10.3 | 3 h | `33a4064` 21:57; sửa theo review dev7 `1c0c0f4`, `89b01eb` 01:09 |
| T23-WI-2 | Task đầu tiên dùng wiki do init tạo (không tự tạo thư mục, không chép trang) | T23-WI-1 | 0,5 h | `7633bb6`, `2dc19e9` |
| T23-WI-3 | Kiểm gói: V15 (init → wiki → reader), V16 (việc 2.2 chạy dở được 2.3 chạy tiếp) | T23-WI-1 | 1 h | `33a4064`, `7633bb6`; gói thử `7633bb6`: kiểm 16/16, README 9/9, task đầu tiên dừng ở bước `init` (dòng CRLF của PowerShell) → `2dc19e9` |
| T23-KN | KN-1…KN-4 | §10.4 | 1,5 h | `fb9a0b2` 22:07; review dev7 |
| T23-R15B | R15 B1, B2, B4, B6 (4 file giống `e432be2`) | §10.4 | 0,5 h | `f865ee2` 22:57 (agent Sonnet), gộp `845c714` |
| T23-FX | FX-1…FX-4 | §10.4 | 3 h | `04ae80b` 01:18 (agent Sonnet; 3 vòng review agent riêng), gộp `4f6a707` |
| T23-DX | Nguồn viết trần giữ dấu chấm đầu (lỗi có từ 2.2, thấy lúc làm FX) | T23-FX | 0,5 h | `1cc9419` 30/10 ~03:00; review cùng FX |
| T23-RFX | Sửa theo review verifier: FX-R01 hard link trong artifact Git, FX-R02 kiểm `ids` đạt rỗng, FX-R04 `(?i)`, FX-R05 tên không phải Unicode, DX-R01 `./x`, DX-R02 chữ có dấu chấm | T23-RV7 | 1 h | `7a1ce5c` 03:41; FX-R03, R06, R07, R08 thành giới hạn |
| T23-RFX2 | Sửa theo lượt soát lại `7a1ce5c`: D-R01 trạng thái mốc, D-R02 duyệt plan, D-R03 junction, D-R04 index thật, D-R05 `.onecrew` và lần định danh sau, D-R06, D-R08, D-R09 | T23-RFX | 1 h | `376654d`; D-R07 thành ghi chú phát hành, clean filter thành giới hạn |
| T23-RFX3 | Sửa theo lượt soát lại `376654d`: E-R01 giữ kết quả lượt kiểm, E-R02 chỉ junction, E-R04 tên dài, E-R05 chọn đường dẫn có thật | T23-RFX2 | 0,5 h | `726aacf` 05:17; E-R03 thành giới hạn |
| T23-RFX4 | Sửa theo lượt soát lại `726aacf` và lần kiểm `3f3edb7`: F-R01 dòng có đường dẫn thì kiểm đúng đường dẫn đó; G-R01, G-R02 | T23-RFX3 | 0,3 h | `3f3edb7` 05:31, `0c6074f` 05:41 |
| T23-RV7 | Review độc lập theo rủi ro: WI/KN hai vòng, FX và DX sau khi gộp, soát lại `7a1ce5c`, `376654d`, `726aacf` | T23-WI-1, T23-KN, T23-FX, T23-DX | 2 h | `D:\OneCrewRuns\v23\review-dev7\review-wi.md`, `review-fx.md` |
| T23-RACE | Race `.onecrew` của index tạm khi tính artifact (gate trên snapshot thứ nhất thấy) | T23-PK-F7 | 0,2 h | `01c5831` 09:26 |
| T23-PK-F7 | Gói `2.3.0.dev7`: hồi quy tích hợp, kiểm từ gói (16 bước), diễn tập README + task đầu tiên + script thử, phản chứng, dữ liệu cũ, gate snapshot 2.2, phát hành bản thử | tất cả | 5 h | BAO-CAO-2.3-DEV7 |

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
| 29/10 ~09:00 | Codex review gói `2.3.0.dev3` (`0594a43`): 1 finding P2 (tri thức general chưa xét khả năng áp dụng trong `context retrieve`) | chỉ thị 29/10 |
| 29/10 09:18–09:34 | testcase đỏ trên `0594a43` (8 test, 12 subtest đỏ); sửa | `6a8e400` |
| 29/10 09:37 | ghi 3 ngoại lệ U1 theo ủy quyền bằng văn bản 29/10 (chỉ nhánh 2.3) | `26a51c5` |
| 29/10 09:41–10:55 | gói `2.3.0.dev4` kiểm 12/12; gate trên `84940f7` dừng ở 16/286 vì review độc lập tìm F1–F3 | không bàn giao |
| 29/10 10:55–11:41 | sửa F1–F3, hồi quy 331 test (3 expected failure F4), công cụ gói dev5, snapshot | `9a2b453`, `cecc09b`, `b3ecc57` |
| 29/10 11:41–11:50 | gói `2.3.0.dev5`: kiểm từ artifact 12/12, diễn tập README 9/9, task đầu tiên 23/23; CLI cài dev3 8 → dev4 2 → dev5 0 lỗi | BAO-CAO-2.3-DEV5 §5 |
| 29/10 11:41–15:43 | gate snapshot 2.2 trên `b3ecc57`: 286/286 check đạt (2 097 test, 0 skip); quyết định `refused`: 23 khoảng trống ngoài như beta, kit-guard đạt (U1) | `D:\OneCrewRuns\v23\gates-tmp\wf-snapshot-gate-20261029-b3ecc57`; BAO-CAO-2.3-DEV5 §5.5 |
| 29/10 15:58–16:02 | chủ sở hữu tự chạy thử gói `2.3.0.dev5` từ terminal của mình: kiểm 12/12, task đầu tiên 21/21 với bước duyệt plan chạy thật trên sổ tạm (không phải nghiệm thu) | `D:\OneCrewRuns\v23 thu cua anh dev5 20261029-155825` |
| 29/10 17:02 | Codex review gói `2.3.0.dev5` (`b3ecc57`): 4 finding P2 (P2-A script thử, P2-B khóa tri thức giữa project, P2-C `.env.example`, P2-D `[S1][S2]`) | chỉ thị 29/10; §9 |
| 29/10 17:11–20:26 | sửa P2-A…P2-D, ba vòng review độc lập và một lượt soát; snapshot version `2.3.0.dev6` | `b32ae19` … `ab25e1c`, `4bb41b3`; §9 |
| 29/10 20:30–21:14 | hồi quy trên `4bb41b3` (304 + 246 test); gói `2.3.0.dev6`: kiểm từ gói 14/14, README 9/9, task đầu tiên 23/23, script thử `DAT`/0 và dùng lại thư mục → 2, ca Codex qua CLI cài 0 lỗi, sổ dev5 đạt | BAO-CAO-2.3-DEV6 §5 |
| 29/10 21:16–30/10 00:02 | gate trên `4bb41b3` dừng ở 155/286: `metered_verifier` (test có hạn thời gian) hỏng hai lần khi máy chạy song song các agent dev7; không tính là đạt; gói dev6 không bàn giao | `D:\OneCrewRuns\v23\gates-tmp\wf-snapshot-gate-20261029-4bb41b3`; BAO-CAO-2.3-DEV6 §5 |
| 29/10 21:16–21:32 | tiếp quản theo chỉ thị tối 29/10: kiểm điểm tiếp quản (§10.1); §10 hợp đồng trước code | `dededc5` |
| 29/10 21:39 / 23:00 | một lượt test của Claude không đặt `LOCALAPPDATA` riêng, thêm một mục vào `hook-projects.json` thật; agent R15 phát hiện; bỏ đúng mục đó, file trở lại từng byte | BAO-CAO-2.3-DEV7 §5 |
| 29/10 21:57–23:11 | WI-01…05 + `--version`, KN-1…KN-4, V15/V16, task đầu tiên dùng wiki của init (gói thử `7633bb6`: 16/16); R15 B1, B2, B4, B6 (agent Sonnet) | `33a4064`, `fb9a0b2`, `7633bb6`, `2dc19e9`; `f865ee2` |
| 29/10 22:49–30/10 00:56 | review độc lập WI/KN trên `7633bb6` (14 điểm: 5 P2, 9 P3) và soát lại `1c0c0f4` (không P1/P2, 6 P3 mới) | `review-dev7\review-wi.md`; sửa `1c0c0f4`, `89b01eb` |
| 29/10 23:25 / 30/10 02:35 | một probe của agent review không đặt `LOCALAPPDATA` riêng, thêm một mục vào `hook-projects.json` thật; Claude phát hiện khi đối chiếu SHA256; bỏ đúng mục đó, file trở lại từng byte | `D:\OneCrewRuns\v23\dev7\incidents` |
| 30/10 01:18 | FX-1…FX-4 (agent Sonnet, 3 vòng review agent riêng); ~01:51 một test của `tests.test_v2_reviewer` gọi Claude thật một lần (subscription, ước 0,066 USD) | `04ae80b`; BAO-CAO-2.3-DEV7 §5 |
| 30/10 01:09–02:23 | gộp WI/KN, R15, FX vào `claude/onecrew-2.3` | `845f7cd`, `845c714`, `4f6a707` |
| 30/10 ~03:00 | DX: nguồn viết trần mất dấu chấm đầu (có từ 2.2; agent FX thấy, để nguyên); 5 test đỏ trên `4f6a707` → 7/7; gộp sau hồi quy tích hợp | `1cc9419`; `D:\OneCrewRuns\v23\dev7\logs\dx-red-4f6a707.txt` |
| 30/10 02:24–03:51 | hồi quy tích hợp trên `4f6a707`, tuần tự: 460 test 2.3 đạt (8 bỏ qua); 965 test 2.2, chỉ test ghim version cũ hỏng | `D:\OneCrewRuns\v23\dev7\logs` (`int-v23-4f6a707.txt`, `int-22-4f6a707.txt`) |
| 30/10 02:23–03:24 | review độc lập FX (sau khi gộp) và DX: không P1; 3 P2 (FX-R01, FX-R02, DX-R01), 7 P3 | `review-dev7\review-fx.md` |
| 30/10 03:24–03:41 | sửa theo review: probe của reviewer giữ thành test, đỏ trên `1cc9419` (23 fail + 3 lỗi kể cả subtest) → xanh; FX-R03, R06, R07, R08 thành giới hạn | `7a1ce5c`; `D:\OneCrewRuns\v23\dev7\logs\rfx-red-1cc9419.txt` |
| 30/10 03:52 | gộp DX và lượt sửa hai vào `claude/onecrew-2.3` | `fdcc2e9` |
| 30/10 03:53–04:37 | hồi quy trên `fdcc2e9`: 489 test 2.3, 8 subtest đỏ của một test đối chứng FX-1 (đúng lỗi D-R09 reviewer thấy cùng lúc); phần 2.2 dừng ở 04:37 vì code đổi tiếp | `D:\OneCrewRuns\v23\dev7\logs\int-v23-fdcc2e9.txt` |
| 30/10 03:42–04:28 | soát lại `7a1ce5c`: không P1; 4 P2 (D-R01, D-R02, D-R03, D-R09), 5 P3 | `review-dev7\review-fx.md` |
| 30/10 04:29–04:55 | sửa lượt ba: probe của reviewer giữ thành test, 10 đỏ trên `7a1ce5c` → xanh; D-R07 thành ghi chú phát hành, clean filter thành giới hạn | `376654d`; `D:\OneCrewRuns\v23\dev7\logs\rfx2-red-7a1ce5c.txt` |
| 30/10 04:56 | gộp lượt sửa ba vào `claude/onecrew-2.3`; hồi quy trên đó dừng hai lần (05:01, 05:10) vì lượt soát kế tiếp đổi code | `10bdfb7`; `D:\OneCrewRuns\v23\dev7\logs\int-v23-10bdfb7-stopped2.txt` |
| 30/10 04:57–05:07 | soát lại `376654d`: không P1; 1 P2 (E-R01: lần định danh sau lượt kiểm bị từ chối làm mất kết quả và giữ mốc), 4 P3 | `review-dev7\review-fx.md` |
| 30/10 05:08–05:17 | sửa lượt bốn: 5 test đỏ trên `376654d` → xanh; E-R03 thành giới hạn | `726aacf`; `D:\OneCrewRuns\v23\dev7\logs\rfx3-red-376654d.txt` |
| 30/10 05:17 | gộp lượt sửa bốn vào `claude/onecrew-2.3` | `1c09994` |
| 30/10 05:18–05:24 | soát lại `726aacf`: không P1; 1 P2 (F-R01: dòng nguồn ghi mô tả trước có đường dẫn thiếu vẫn đạt nhờ một chữ khác có thật); E-R01, E-R02, E-R04 khép | `review-dev7\review-fx.md` |
| 30/10 05:25–05:31 | sửa F-R01: 6 dòng đỏ trên `726aacf` → xanh | `3f3edb7`; `D:\OneCrewRuns\v23\dev7\logs\rfx4-red-726aacf.txt` |
| 30/10 05:17–06:10 | hồi quy trên `1c09994`, tuần tự: 504 test 2.3 đạt (9 bỏ qua, 3 expected failure); 361 test của 11 module 2.2 ngoài gate, chỉ test ghim version cũ hỏng | `D:\OneCrewRuns\v23\dev7\logs\int-v23-1c09994.txt`, `int-22-1c09994.txt` |
| 30/10 05:32–05:38 | kiểm `3f3edb7`: F-R01 khép; không P1/P2; 2 P3: G-R01 chữ có `/` (CI/CD, km/h) trước đường dẫn bị lấy làm đường dẫn (báo sai, không bao giờ đạt sai), G-R02 `.env.example` thiếu vẫn đạt nhờ `.gitignore` có thật | `review-dev7\review-fx.md` |
| 30/10 05:36–05:41 | sửa G-R01, G-R02: 6 dòng đỏ trên `3f3edb7` → xanh; probe check4 của reviewer chạy trên bản sửa: g01–g03 đạt, 18 dòng g04 như trên `3f3edb7`; không review lại (chỉ P3) | `0c6074f`; `D:\OneCrewRuns\v23\dev7\logs\rfx5-red-3f3edb7.txt`, `check4-on-round5.log` |
| 30/10 06:11 | gộp `3f3edb7` và `0c6074f` vào `claude/onecrew-2.3` (code cuối); chạy lại các module verifier tài liệu và test giữ từ review: 255 test đạt (3 expected failure) | `30f65c9`; `D:\OneCrewRuns\v23\dev7\logs` (`final-doc-*.txt`) |
| 30/10 06:18–06:28 | snapshot thứ nhất `c6d8477` (version `2.3.0.dev7`); module đọc version và tài liệu: 264/265 (test ghim version cũ) | `c6d8477`; `D:\OneCrewRuns\v23\dev7\logs\snap-c6d8477.txt` |
| 30/10 06:28–06:44 | gói từ `c6d8477` (wheel `82bc6e25…`): kiểm từ gói 16/16, README 9/9, task đầu tiên 25/25, script thử `DAT`/0 và dùng lại thư mục → 2, ca Codex qua CLI cài 0 lỗi, dữ liệu dev5 đạt, V15 qua CLI cài: dev6 11 lỗi → dev7 0. Không bàn giao: thay bằng gói của snapshot thứ hai | `D:\OneCrewRuns\v23\pkg\onecrew-2.3.0.dev7-final-c6d8477-superseded` |
| 30/10 06:45–09:22 | gate trên `c6d8477` dừng ở 179/286: `R03/check.t41_gaps` hỏng (chạy riêng: hỏng 2 trong 3 lần). Nguyên nhân: hook ghi lại `.onecrew/active-plan.json` giữa `git add` và `git rm --cached .onecrew` của index tạm, git từ chối, lượt kiểm bị bỏ dở (race có từ 2.2; bước kiểm hard link mới làm khoảng hở rộng ra) | `D:\OneCrewRuns\v23\gates-tmp\wf-snapshot-gate-20261030-c6d8477`; `D:\OneCrewRuns\v23\dev7\logs\t41-alone-c6d8477.txt` |
| 30/10 09:22–09:26 | sửa race: `git rm --cached -f` trên index tạm (`artifact_sha`, `tracked_tree`); test race đỏ trên `0c6074f` → xanh; `t41_gaps` chạy riêng 6/6 | `01c5831`, gộp `7e91d8c`; `D:\OneCrewRuns\v23\dev7\logs\t41-after-fix.txt` |

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

Review độc lập bản sửa đầu (`6a8e400`), agent Opus 5.5, probe chạy trên bản sửa và trên bản trước sửa (`D:\OneCrewRuns\v23\review-dev4\review-dev4.md`):

| Điểm | Mức | Mới/cũ | Sửa | Testcase đỏ trước → xanh sau |
|---|---|---|---|---|
| F1/F1b: mục general bị bản ghi project dẫn file thay thế lại hiện khi người đọc không đọc được bản thay thế (không `--plan`) | P1/P3 | mới | `9a2b453`: `context.judged` xét vòng đời của project trước cho mục dùng chung | `tests/test_v23_review_dev4.py` r01/r01b/r01c: đỏ trên `6a8e400`, xanh; CLI cài: wheel gói dev4 2 lỗi → wheel dev5 đạt; V12 |
| F2/F3/r03/r03b: kết quả xét của bản ghi khác cùng id tri thức được áp nhầm | P1/P2 | cũ + mới | `9a2b453`: kết quả xét mang `version`/`scope`, chỉ áp đúng bản ghi; bản trùng id → `stale` "not judged" | r02a/r03/r03b: đỏ trên `6a8e400`, xanh |
| F4: hai project dùng cùng `--key` cho bản ghi general chung một id (che nhau, thu hồi lẫn nhau, không thu hồi được) | P2 | cũ | chưa sửa (đổi hợp đồng id); không bao giờ hiện như hiện hành | r02b/r02c/r02d: expected failure, mở |

## 9. Review Codex 29/10 trên gói `2.3.0.dev5` và sửa

Nguồn finding: chỉ thị người dùng 29/10 (dán trong phiên), bằng chứng của Codex ở `D:\OneCrewRuns\codex-dev5-handover-review-20261029` (`wrapper-reused-log.txt`, `installed-collision.json`, `installed-verifier.json`). Đính chính: báo cáo dev5 §1 ("phần local đã khép") không đúng; F4 ở đó là lỗi local, không phải giới hạn.

| Finding | Requirement chạm | Nguyên nhân | Sửa (code) | Testcase đỏ trước → xanh sau | Bằng chứng từ gói |
|---|---|---|---|---|---|
| P2-A: script thử báo đạt bằng log cũ | gói/PL (cách thử của chủ sở hữu) | script dev5 đọc báo cáo không gắn với lần chạy | `fca2813`: `verify\thu-goi.ps1` (từ `docs/v23/tools/thu_goi.ps1`) | `tests/test_v23_owner_wrapper.py` 22 test; bản sao script dev5: `DAT`/0 → script mới: từ chối/2 | diễn tập script từ gói (§5 báo cáo dev6) |
| P2-B: hai project dùng chung một `--key` cho bản ghi general là một chủ thể | A2-R2, A2-R4 (vòng đời), A1-R4 | `ledger_id` không có project | `ebcfa20`, `926bdcf`, `4516cc5`, `3cfe327`, `ab25e1c` | r02b–d (expected failure trên `b3ecc57`) → đạt; `test_v23_codex_review_dev5` 10, `test_v23_review_dev6` 17, `test_v23_review_dev6_delta` 14 | V13 qua CLI cài; sổ do wheel dev5 ghi đọc bằng wheel mới |
| P2-C: `.env.example` làm dừng verifier tài liệu | RX1 doc (2.2, nhận vào 2.3) | `Port.files()` từ chối mọi tên bị cấm đọc lúc liệt kê | `b32ae19` (= R15 `e432be2`, 3 file), `a87389f` | `test_v23_r15_port` 22 (9F+7E → 0), `test_v23_review_dev6_port` 20 (15 → 0) | V14 qua wheel cài |
| P2-D: `[S1][S2]` bị báo là reference link | RX1 doc | kiểm link không biết mẫu trích dẫn | `b32ae19`, `a87389f` | như P2-C | V14 |

Không nhận từ R15 (ngoài các finding trên): B1, B2, B4, B6 (hook, plan lint).

Review độc lập (agent Opus 5.5, probe chạy trên bản sửa và bản trước sửa; `D:\OneCrewRuns\v23\review-dev6\review-p2b.md`):

| Vòng | Trên | Kết quả | Sửa |
|---|---|---|---|
| 1 | `ebcfa20`, `b32ae19` | 15 điểm: 1 P1, 9 P2, 5 P3 (7 do bản sửa, 8 có từ trước) | `926bdcf` (R1–R8, R11, R12, R15), `a87389f` (R9, R10, R13, R14) |
| 2 | `926bdcf` | 8 điểm mới: 2 P2, 6 P3 (D1–D8) | `4516cc5` |
| 3 | `4516cc5`, `a87389f` | không còn P1/P2; 4 điểm P3 (E1–E4) | E1–E3 ở `3cfe327`; E4 (hard link, có từ trước) là giới hạn |
| soát | `3cfe327` | không có P1/P2; 1 điểm P3 hiển thị (F1) | `ab25e1c` |

## 10. Hoàn tất 2.3 và phát hành bản thử (chỉ thị người dùng 29/10 tối)

Nguồn: chỉ thị dán trong phiên Claude Code 29/10 ("Tiếp quản công việc hiện tại, hoàn thành toàn bộ phạm vi OneCrew 2.3 đã chốt và phát hành bản 2.3 sau khi tự kiểm chứng đạt…"). Phạm vi theo ba tài liệu chung bản Codex sửa 29/10 17:31–17:36: [roadmap §0.2 và mục wiki-init](../../../outputs/onecrew-as-qc/ROADMAP.vi.md#wiki-init), [thiết kế WI-01…05](../../../outputs/onecrew-as-qc/ROADMAP-DESIGN-20261026.vi.md#wiki-init), [bàn giao](../../../outputs/onecrew-as-qc/ROADMAP-CLAUDE-HANDOFF.vi.md#wiki-init-handoff); Claude đọc lúc ~21:20 29/10. Ngoài phạm vi: OA-01…OA-04 (chủ sở hữu 29/10: chưa sửa), MR-WORKSPACE, 2.4 trở đi, các đề xuất mới về báo tiến triển, bản đồ tool/harness, giảm bước điều phối, fast mode.

### 10.1 Điểm tiếp quản (kiểm 29/10 21:16)

| | |
|---|---|
| Nhánh / HEAD | `claude/onecrew-2.3` ở `4bb41b3`, không có thay đổi chưa commit |
| Gói hiện có | `2.3.0.dev6` (`4bb41b3`, wheel `f4819c5a…`): kiểm từ gói 14/14, README 9/9, task đầu tiên 23/23, script thử `DAT`/0 và từ chối thư mục dùng lại (2), ca của Codex qua CLI cài 0 lỗi, sổ dev5 → dev6 → 2.2 đạt; hồi quy 304 test 2.3 + 246 test 2.2 liên quan đạt. Gate trên `4bb41b3` chạy làm kiểm sớm, không là bằng chứng của bản cuối |
| Beta | checkout `wf-codex` ở `1753f77`, sạch; gói `2.2.0.dev18` và `2.2.0.dev19` không đụng |
| Worktree lượt này | `wf-v23-wi` (WI, tri thức), `wf-v23-r15b` (R15), `wf-v23-fx` (verifier), cùng từ `4bb41b3`, gộp vào `claude/onecrew-2.3` trước snapshot cuối |

### 10.2 Còn thiếu (phân loại A thiếu code, B thiếu đường nối/cấu hình, C thiếu bằng chứng, E điều kiện ngoài)

| Mục | Loại | Task |
|---|---|---|
| WI-01…05: `init` tạo hoặc dùng lại wiki an toàn | A | T23-WI-1 |
| Bài thử task đầu tiên còn tự tạo thư mục wiki và chép trang | B | T23-WI-2 |
| Kiểm gói chưa có bước init → wiki → reader | C | T23-WI-3 (bước V15) |
| `onecrew --version` thiếu (ma sát người test beta ghi ở báo cáo R15 §3) | B | T23-WI-1 |
| Sửa beta R15 B1, B2, B4, B6 chưa có trong 2.3 (B3, B5 đã nhận ở `b32ae19`) | A | T23-R15B |
| Verifier: mẫu `ids` có neo; tên 8.3 lúc đề xuất; hard link tới file bị cấm (E4); thư mục không Git có `.env` (D8 của beta) | A | T23-FX |
| Tri thức: requests qua nâng cấp; mục `context add` 2.2 khóa `lesson-`; `wiki history` hiện mã project đầy đủ của project khác; thu hồi mục wiki ở trang ngoài ngân sách đọc | A | T23-KN |
| 23 khoảng trống nghiệm thu, pilot và provider của 2.2 | E | không làm trong lượt này; §10.5 |

### 10.3 Testcase WI (chốt trước code)

| ID | WI | Ca | Kỳ vọng |
|---|---|---|---|
| KW-01 | WI-01 | repo mới chưa có wiki → `init --yes` | tạo `docs/wiki/README.md`, `project.md`, `lessons.md`, dòng đầu là dấu khung; `wiki pages`: 3 trang, 0 mục, không lỗi; kế hoạch của init có dòng wiki; trả lời N thì không ghi gì |
| KW-02 | WI-02 | init lần hai sau khi sửa `project.md` | không ghi file nào; hash trang đã sửa giữ nguyên; "không có gì để đổi" |
| KW-03 | WI-02 | `docs/wiki` đã có trang của người dùng | dùng lại, không thêm file khung |
| KW-04 | WI-02 | `wiki.paths` là một thư mục trong repo | chưa có thì tạo khung ở đó, có rồi thì dùng lại; không tạo `docs/wiki` |
| KW-05 | WI-02 | nhiều thư mục, hoặc thư mục ngoài repo (tuyệt đối, hoặc `/x`: gốc của ổ đĩa, như bộ đọc hiểu) | chỉ dùng lại; thiếu một thư mục thì init từ chối (mã 2), không ghi gì; không bao giờ ghi ngoài repo |
| KW-06 | WI-02 | `config.json` không đọc được hoặc `wiki` sai dạng | từ chối (mã 2); bytes `config.json` giữ nguyên; không tạo sổ, hook hay wiki |
| KW-07 | WI-02 | `docs/wiki` hoặc thư mục cha là link/junction | tới thư mục rỗng hay chưa có: từ chối (mã 2), không ghi trong hay ngoài repo; tới một wiki đã có trang: dùng nguyên, không ghi gì (review dev7 R7-09); không bao giờ ghi xuyên qua link |
| KW-08 | WI-02 | `docs/wiki` là file; tên file khung là thư mục | từ chối (mã 2), hoặc bỏ qua tên đó; không ghi đè |
| KW-09 | WI-02 | khởi tạo dở (chỉ có một phần khung) | trang mang tên khung mà đúng chữ init viết, hoặc là phần đầu của chữ đó (ghi dở, kể cả rỗng): tạo các trang còn thiếu, giữ bytes trang đã có (không viết lại trang dở); trang khung đã sửa là của người dùng (R7-10, R7-15) |
| KW-10 | WI-02 | ghi khung lỗi giữa chừng (giả lập) | các bước khác xong; mã thoát 3, in file đã ghi và lỗi; chạy lại thì hoàn tất |
| KW-11 | WI-03 | khung trống | không mục nào được giao (không fact, không must); trang khung không sinh mục, kể cả ví dụ trong README của khung |
| KW-12 | WI-03 | thêm một mục có nguồn vào wiki do init tạo → task đầu tiên | node có quyền đọc nhận đúng mục (diễn tập task đầu tiên); node không có quyền không nhận (KA-04, V5) |
| KW-13 | WI-05 | project đã init bằng 2.2 → init 2.3 | giữ `config.json` (các khóa khác giữ nguyên), sổ không đổi byte, plan và ngân sách giữ; hook gộp sang lệnh mới; thêm khung wiki |
| KW-14 | WI-05 | cài hoặc nâng wheel | không sửa project hay sổ nào (pip không chạy init) |
| KW-15 | WI-04 | root A ghi → root B mới dùng lại (V8, KB-12) | trang khung không đổi sau khi A ghi; tri thức nằm trong sổ, không có kho thứ hai |

Kiểm trên wheel cài trong venv sạch, cwd ngoài checkout, đường dẫn có dấu cách, `LOCALAPPDATA`/`APPDATA` riêng (bước V15 của bộ kiểm gói và diễn tập task đầu tiên); test đơn vị `tests/test_v23_wiki_init.py` cho cả ca giả lập lỗi ghi.

### 10.4 Lỗi mở khác: kỳ vọng (người sửa tự chọn giải pháp)

| ID | Lỗi | Kỳ vọng |
|---|---|---|
| R15-B1/B2/B4/B6 | sửa của beta dev19 (`e432be2`) chưa có trong 2.3 | 4 file `hook_cli`, `active_plan`, `lint`, `plan_cli` giống `e432be2`; test của beta cho B1, B2, B4, B6 đỏ trên `4bb41b3`, xanh sau |
| FX-1 | mẫu `ids` có neo (`^REQ-\d+$`) làm kiểm `ids` không thấy id nào | id dùng mà chưa định nghĩa, hoặc định nghĩa hai lần, luôn bị báo với mọi mẫu hợp lệ; mẫu không dùng được thì bị từ chối lúc đề xuất; không bao giờ đạt rỗng |
| FX-2 | `validate_config` của data/ops nhận tên ngắn 8.3 | xử lý ngay lúc đề xuất (từ chối, nêu lý do); không từ chối tên dài hợp lệ |
| FX-3 | file bị cấm đọc được qua hard link (E4) | không đọc file bị cấm dưới bất kỳ tên nào mà hệ điều hành cho biết là cùng một file; báo chưa kiểm, không làm hỏng cả lượt |
| FX-4 | thư mục không Git có `.env` không định danh được (D8 của beta) | như `Port.files()` sau B5: bỏ tên bị cấm khỏi định danh (không đọc, không băm), ghi rõ đã bỏ; link/junction vẫn dừng; giới hạn 200 file giữ nguyên |
| KN-1 | requests ghi trước nâng cấp xin bản general của project khác bằng id cũ | lần tiếp tục giao đúng chủ thể worker đã xin (qua sự kiện gốc của gói niêm phong, như lần từ chối), không giao bản cùng khóa của chính project |
| KN-2 | mục general ghi bằng `context add` 2.2 với khóa `lesson-` được đọc như lesson | mục đó là chủ thể của project đã ghi; không trùng id với lesson thật hay với mục của project khác |
| KN-3 | `wiki history` hiện mã project đầy đủ của bản ghi project khác | project khác chỉ hiện dấu 12 ký tự (như trong id), không hiện mã đầy đủ |
| KN-4 | thu hồi mục wiki ở trang ngoài ngân sách đọc 2 000 trang bị từ chối | id có thật thì nhận, id không trỏ gì vẫn bị từ chối |
| DX (thêm 30/10, sau khi thấy lỗi) | nguồn viết trần trong mục nguồn mất dấu chấm đầu (`../x` thành `/x`, `.github/x` thành `github/x`); có từ 2.2 | `../x`, `./x`, `.github/x`, `.env.example` giữ nguyên; nguồn thiếu không bao giờ đạt nhờ file cùng tên ở chỗ khác; tên bị cấm vẫn là "chưa kiểm", không bị đọc |

### 10.5 Điều kiện phát hành

| Điều kiện | Nguồn | Trạng thái lúc chốt (điền khi phát hành) |
|---|---|---|
| Mọi requirement 2.3 (§4, §10.3, §10.4) có code, test và bằng chứng trên snapshot cuối | §4, §10 | — |
| Hồi quy 2.3 và module 2.2 liên quan đạt trên snapshot cuối | roadmap §8.2 | — |
| Gate 2.2 trên snapshot cuối: mọi check thực thi đạt, kit-guard đạt | §1, quy ước các bản trước | — |
| Kiểm từ gói dựng từ snapshot đó: V1–V15, README, task đầu tiên, script thử, dữ liệu cũ, quay về 2.2 | roadmap §3.3, §8.3–5 | — |
| Release note, lệnh cài/thử, giới hạn, hướng quay về | roadmap §8.5 | — |
| Nghiệm thu của chủ sở hữu, pilot thật, provider thật đầy đủ | roadmap §3.2, §10; R1 của chủ sở hữu | chưa có: không đủ điều kiện bản stable |

Loại bản: prerelease `2.3.0.devN` theo quy ước của §1 ("prerelease 2.3.0.devN … các dev sau cho A2/B/cuối"). Test ghim `tests/test_g1_core.py` chỉ nhận `2.3.0.devN` (U1-20261029-V23-PIN-1), và ủy quyền của U1 đó ghi rõ không bao gồm phát hành; lượt này không tự cấp U1 mới để đổi nhãn sang `b`/`rc`. Đích phát hành: như `v2.1.0` (commit version + changelog, tag có chú thích, push nhánh và tag lên `origin` `git@github.com:tamnguyendev/one-crew.git`, repo private); không có registry, PyPI hay GitHub Release nào được cấu hình.

### 10.6 Sửa, test và bằng chứng

| Mục | Commit | Test đỏ trước → xanh sau | Bằng chứng từ gói |
|---|---|---|---|
| KW-01…KW-12 (WI-01…03) | `33a4064`, `7633bb6`, `1c0c0f4`, `89b01eb` | `tests/test_v23_wiki_init.py` (18), `tests/test_v23_review_dev7.py` (34), `tests/test_v23_review_dev7_delta.py` (18): ca của init đỏ trên code `4bb41b3` (`D:\OneCrewRuns\v23\dev7\logs\wi-red-4bb41b3.txt`) | V15; task đầu tiên (`init`, `wiki-empty`) |
| KW-13, KW-14 (WI-05) | `33a4064`, `7633bb6` | `tests/test_v23_wiki_init.py` | V15, V16 |
| KW-15 (WI-04) | đường có sẵn | KB-12 | V8 |
| KN-1…KN-4 | `fb9a0b2`, `1c0c0f4`, `89b01eb` | `tests/test_v23_open_knowledge.py` (7): đỏ trên `4bb41b3` (`kn-red-4bb41b3.txt`) | hồi quy |
| R15 B1, B2, B4, B6 | `f865ee2` | `tests/test_v23_r15_hooks.py` (14): 10 đỏ trên `4bb41b3` (`r15b-red-4bb41b3.txt`) | hồi quy |
| FX-1…FX-4 | `04ae80b` | `tests/test_v23_open_verifier.py` (65): 44 đỏ trên `4bb41b3` (`fx-red-4bb41b3.txt`) | hồi quy, gate, V14 |
| DX | `1cc9419` | `tests/test_v23_doc_locators.py` (7): 5 đỏ trên `4f6a707` (`dx-red-4f6a707.txt`) | hồi quy, gate |
| Review verifier (FX-R01, R02, R04, R05, DX-R01, R02) | `7a1ce5c` | `tests/test_v23_review_fx.py` (22): đỏ trên `1cc9419` (`rfx-red-1cc9419.txt`); FX-R03, R06, R08 là expected failure (giới hạn) | hồi quy, gate |
| Soát lại `7a1ce5c` (D-R01…R06, R08, R09) | `376654d` | `tests/test_v23_review_fx.py` (thêm 10): đỏ trên `7a1ce5c` (`rfx2-red-7a1ce5c.txt`); `tests/test_v23_open_verifier.py` xanh lại (D-R09) | hồi quy, gate |
| Soát lại `376654d` (E-R01, R02, R04, R05) | `726aacf` | `tests/test_v23_review_fx.py` (thêm 5): đỏ trên `376654d` (`rfx3-red-376654d.txt`) | hồi quy, gate |
| Soát lại `726aacf` (F-R01) | `3f3edb7` | `tests/test_v23_review_fx.py` RoundFourDocs.test_f01: đỏ trên `726aacf` (`rfx4-red-726aacf.txt`) | hồi quy, gate |
| Kiểm `3f3edb7` (G-R01, G-R02) | `0c6074f` | `tests/test_v23_review_fx.py` RoundFiveDocs: đỏ trên `3f3edb7` (`rfx5-red-3f3edb7.txt`); probe check4 của reviewer đạt | hồi quy, gate |
| Race `.onecrew` (gate trên `c6d8477`, `R03/check.t41_gaps`) | `01c5831` | `tests/test_v23_review_fx.py` OnecrewRace: đỏ trên `0c6074f` (`race-red-0c6074f.txt`); `t41_gaps` riêng: 2/3 hỏng → 6/6 | gate |

FX-3 (§10.4) với artifact Git: theo review FX-R01 và D-R03, một tên là hard link hay đi qua junction làm lượt kiểm (và `plan approve`) bị từ chối kèm lý do thay vì "báo chưa kiểm, không làm hỏng cả lượt"; đây là giới hạn đã ghi (`docs/v23/tools/limits-final.md`), không phải kỳ vọng mới. Tương tự FX-R08 với thư mục không Git có tên bị cấm.

Review độc lập (theo rủi ro: định danh, quyền, vòng đời tri thức, logic chấm đạt): BAO-CAO-2.3-DEV7 §8. R15 không review riêng: 4 file giống từng byte `e432be2` (đã qua gate 2.2 ở beta dev19), 2.3 không sửa chúng.
