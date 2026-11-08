# Bàn giao sửa F1–F11 — Sol4, 05/11/2026

Phạm vi: sửa lỗi review Claude của Sol3; dùng lại engine, ledger, finding/recheck, snapshot, notification và learning hiện có. Không thêm feature roadmap; không chạy toàn gate; không cài vào runtime thật; không push/tag/nghiệm thu. Đây là bản để Claude review lại.

## Snapshot

- Code: `40d7ba7e5d431bb7f2b65c5175daca3f5746d6ad`, nhánh `sol/close-existing-workflow`, checkout `C:/OneCrewRuns-sol/wf`.
- Wheel: `2.5.0.dev10+sol4.1`, SHA256 `03293bd8a6149dc6fcb2674b9f58594ca04a59836ee4d9d95eebd49008c3e1e8`.
- Gói: `C:/OneCrewRuns-sol/final4b`. Source zip cùng commit; xem `identity-result.json`, `verification.json`, `SHA256SUMS`.
- `final3` và lab Claude `C:/OneCrewRuns-rv` giữ nguyên. `evidence/claude-original` là bản sao nguồn review/probe cũ, không phải lệnh chạy vào Sol4.

## Đối chiếu finding

| Finding | Hành vi sau sửa | Phản chứng/kiểm trên wheel |
|---|---|---|
| F1 | Command fail mở finding `check_failure`; receipt sửa đúng và còn hiệu lực đi qua `close_from_recheck` hiện có để đóng. Không tự đóng reviewer finding, không tự nghiệm thu. | `test_sol_command_findings`: receipt đỏ không đóng; xanh sau sửa đóng đúng finding và cho phép nghiệm thu trên sổ tạm; lỗi hạ tầng không suy ra bug. |
| F2 | Engine, digest và tracking dùng chung bước tiếp theo: kiểm node → handoff → verdict → chủ sở hữu nghiệm thu; nêu quyền apply còn thiếu. | `test_sol4_operator_flow`: C7 hết chuỗi, thiếu grant, hết ngân sách, guidance không ghi sổ. |
| F3 | Dùng lại proof candidate xác thực trên đúng request/tree/config/env và handoff hiện hành. Biên nhận verdict trỏ proof gốc, không gọi lại verifier hoặc tính lại ngân sách/thời gian; receipt reviewer giữ số call của proof gốc, new_calls/event calls bằng 0; vẫn kiểm integrity. | `test_sol4_verification`: command và doc/data tới nghiệm thu; đổi môi trường phải gọi lại; xác thực receipt sau publication. `R02OldPass`: fail mới hơn chặn pass cũ. |
| F4 | Snapshot lỗi có bằng chứng verifier chưa chạy thì đóng claim dạng `not_dispatched`, cho phép thử lại; kết quả chưa biết vẫn held. | Hai ca F4; hồi quy nhiều milestone giữ phần đã có receipt, không chạy trùng. |
| F5 | Kiểm plan trước đổi enforce; lỗi export sau khi đổi mode báo đúng phần đã ghi, không nói “chưa ghi”. | C15 JSON/human, plan không tồn tại/chưa duyệt, export lỗi và guard phiên AI. |
| F6 | Snapshot entrypoint dùng ngân sách hữu hạn đã cấu hình; root deadline vẫn giới hạn; cap thực thi verifier không bị trừ thời gian snapshot. Command/reviewer/adapter phân thời gian thực thi. | Ca F6 budget mặc định/giá trị sai, snapshot lâu hơn cap verifier; giới hạn root, pipe và view. Non-snapshot Git vẫn có giới hạn bước riêng. |
| F7 | Các projection trong một lần record dùng chung một quan sát mới; lần thao tác sau băm lại, không cache lâu dài và không thu hẹp xuống `owned`. | Ca F7 đếm tối đa 3 lần update-index cho verdict thường (trước là 5); thay dependency ngoài owned được nhận ra. Fixture 5.002 file kiểm riêng. |
| F8 | Timeout có nguyên nhân, receipt dừng tiến trình và hướng revise trong grant hoặc quyết định owner khi hết ngân sách; notice bền vững qua outbox cũ, không lặp và bị suppress sau revise. | C14 tiến trình thật trong lab; diagnose CLI; notice/outbox; không tự retry. Desktop hiện thông báo thật chưa kiểm. |
| F9 | `reuse-existing` từ chối plan stopped/terminal, không giả vờ tiếp tục thành công. | Ca F9 dừng đúng ngân sách sửa, kiểm không có event mới. |
| F10 | Snapshot lỗi ở preflight được trả ra trước khi mở run, không nuốt thành request rỗng và không dispatch. | Ca F10: identity gọi một lần, 0 command và 0 run_started. |
| F11 | Đính chính: lỗi Get-FileHash trước là môi trường PSModulePath của phiên test, không phải máy thiếu lệnh. | Test owner-wrapper cũ đỏ → wrapper đúng xanh; chạy Windows PowerShell với module path hệ thống trong process lab, không sửa cấu hình toàn máy. |

Các ca mới dựa trên C1/C2/C3/C7/C8/C11/C13/C14/C15 trong probe Claude. Không gọi tất cả là đỏ trên Sol3: F10 trước chỉ là đọc code; negative mới được bổ sung. Logs cả lượt đỏ do fixture và lượt sửa được giữ, không tính chúng là PASS. Ca kiểm view cũ dùng timeout ngầm được đổi sang ngân sách hữu hạn cấu hình theo F6; không bỏ kiểm timeout.

## Kiểm chứng

- Wheel cuối: **22/22 test đạt**, 0 skip, 647.236 giây; `wheel-tests.json` và `.log`.
- Smoke độc lập chỉ wheel: **38 kiểm đạt**, 124.164 giây; đi hết chuỗi managed trên sổ tạm. Số walk ở verdict root: 4.
- Fixture **5002 file**: đạt; dependency ngoài owned đổi làm bằng chứng cũ stale, hai lượt verifier thật được đếm bằng marker. Thời gian: {"admission_seconds": 49.993, "first_verdict_seconds": 61.293, "changed_dependency_verdict_seconds": 70.019}.
- Định danh: 145 file payload khớp Git archive, wheel/venv đúng version; 4 mốc bảo vệ giữ nguyên hash.
- Hồi quy source t08a/t08b cùng các ca adapter/F1: 9/9; source operator: 6/6. Không cộng các lượt này vào số test wheel.
- Gói trung gian `final4` không bàn giao: thiếu ca reviewer reuse; đã bổ sung và khép trên final4b. Kiểm hồi quy snapshot trung gian ghi riêng trong verification.json.

Các test wheel tải mọi module được phân phối từ venv của gói. Một số fixture cũ cần module v1 không nằm trong wheel, được đọc từ source zip cùng snapshot; `wheel-tests.json` liệt kê riêng các helper này và kiểm không có module sản phẩm đã phân phối nào bị thay bằng source. Smoke riêng chỉ dùng wheel và tiến trình local, đi hết fail → sửa → lesson → node tiếp → handoff → verdict → nghiệm thu **fixture**, không phải nghiệm thu của anh.

## Giới hạn trung thực

- Không có live provider/phiên Claude thật; không cài plugin, đổi hook hay runtime SignSDK.
- Task phát triển bản sửa này chưa được OneCrew monitor. Các sổ trong gói là bài thử sản phẩm, không được coi là bằng chứng dogfood.
- Fixture lớn có 5.002 file, không phải repo MEP 108.897 untracked; chưa chứng minh tốc độ trên MEP. Vẫn giữ toàn bộ dependency identity, không bỏ file ngoài owned để làm test nhanh.
- Số lượt băm giảm không đồng nghĩa đã chứng minh giảm wall time: lượt verdict đầu fixture cuối là 61,293 giây (verifier 0,22 giây); fixture Sol3 trước là 25,477 giây ở điều kiện chạy khác. Đây không phải benchmark kiểm soát tải; snapshot overhead còn đáng kể, không tuyên bố tăng tốc tổng thể.
- Không chạy toàn gate theo chỉ thị. Đây là kiểm hồi quy theo ảnh hưởng và bản giao để review, không tuyên bố đã release hoặc nghiệm thu.
- Đính chính `final3/verification.json`: dòng “host Windows PowerShell cannot resolve Get-FileHash” sai nguyên nhân; giữ gói cũ bất biến, thay kết luận bằng F11 ở đây.

## Prompt giao Claude

```text
Review độc lập bản sửa F1–F11 của Sol4. Đọc C:/OneCrewRuns-sol/final4b/HANDOVER.vi.md và verification.json trước; baseline Sol3 e6d58bb, code Sol4 40d7ba7, wheel SHA256 03293bd8a6149dc6fcb2674b9f58594ca04a59836ee4d9d95eebd49008c3e1e8.

Đọc wiki entry của OneCrew và chỉ mục Sol4 liên quan trong CURRENT; xác minh snapshot, không coi wiki là thay thế code/test hoặc quyền.

Đối chiếu từng F1–F11 với review/probe gốc của chính anh ở C:/OneCrewRuns-rv và bản sao evidence/claude-original. Tái sử dụng test/probe, không dựng lại toàn cuộc điều tra. Kiểm từ wheel cuối trong lab mới; dùng git diff e6d58bb..40d7ba7 để khoanh phạm vi. Không chạy toàn gate, không gọi provider tốn phí, không sửa final3/final4, runtime thật, hook, registry hoặc sổ thật. Không cần hỏi duyệt từng bước đọc/kiểm trong phạm vi này.

Ưu tiên: receipt reuse vẫn chặn proof cũ/khác environment/newer fail và không tự phủ định sau publication; command finding đóng đúng qua recheck; F2 đi hết handoff/verdict/owner acceptance; timeout trước dispatch khác unknown; snapshot/cap/root deadline; notice không trùng; enforce không báo sai phần đã ghi. Kiểm cả doc/data và lesson hiện có. Không coi fixture/provider giả là phiên thật hay nghiệm thu.

Trả bảng F1–F11 Closed/Partial/Open với file:line, ca tái hiện và kết quả; lỗi mới chỉ nêu nếu có bằng chứng và ảnh hưởng trong phạm vi. Nếu không còn lỗi local chặn thử, nói rõ bản này sẵn sàng thử cách ly cùng giới hạn thực tế. Chỉ review, chưa sửa code hay nâng runtime; không mở rộng roadmap.
```
