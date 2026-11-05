# Sol5 — bản sửa local L1–L15 để Claude kiểm lại trước phát hành

Code `8f53170cd846ade7bf599345ede196f780755561`, version `2.5.0.dev10+sol5.2`, baseline `40d7ba7` (Sol4.1). Gói `C:/OneCrewRuns-sol/final5c`. Wheel SHA256 `0e0a1def6828f66a663cf4a23dbd994be07e08908ecf1f80c7ac6a3c6bbe9513`.

**Đã khép các lỗi local trong phạm vi review L1–L15 bằng code và kiểm trên wheel. Chưa push/tag, chưa nâng runtime thật, chưa nghiệm thu và chưa có review độc lập của Claude cho Sol5.** Đây là bản giao để kiểm lại diff cuối, không phải tuyên bố toàn roadmap đã phát hành.

## Các thay đổi có bằng chứng

| Mục | Kết quả / đường đi tiếp | Bằng chứng |
|---|---|---|
| L1 | Chủ quan sát và nghiệm thu bằng chứng đã hoàn tất được sau deadline. Không dùng việc nghiệm thu để khởi chạy thêm worker/verifier. Snapshot đọc vẫn hữu hạn; cây đổi bị từ chối đúng lý do. | `test_sol5_review` L1 và probe gốc `p_deadline.py`: đợi hết một phút thật, owner API/CLI/human đạt trên sổ tạm. |
| L2 | Nghiệm thu dùng context của verifier đã ghi, không lấy PATH/TERM/SHELL của terminal chủ làm context thực thi mới. Python/platform, config, input và artifact vẫn được kiểm. Lần kiểm mới/tái sử dụng cho thực thi vẫn so môi trường hiện tại nghiêm ngặt. | L2; `p_ownerenv.py`; hồi quy binding và candidate reuse. Terminal chủ được mô phỏng bằng tiến trình con, chưa thao tác trong terminal thật của anh. |
| L3 | Verdict cuối đỏ có đường `engine diagnose` → repair hiện có → generation mới → verify → handoff CAS → verdict → nghiệm thu. Finding vẫn mở cho đến recheck thật; chỉ marker do cửa repair phát sau Q5 được dùng để giải phóng node sửa. | Các ca L3: vòng hoàn chỉnh, marker giả bị từ chối, thiếu Q5 bị giữ, sửa tay không bị ghi đè, bàn giao lần hai trả file về bản gốc. D6 kiểm repair/revise/recurrence cũ. |
| L4 | Node kiểm đỏ hướng tới diagnose/repair; thiếu ngân sách/quyền thì nêu owner decision, không bảo gọi verify đang bị giữ. | `p_f2.py failed_node/budgets`, test Q5 và operator. |
| L5 | Check đang giữ không bị wrapper đổi thành verification_required. Hướng reconcile trước; unknown cần release có lý do. | `test_r14` gốc Claude phát hiện, chạy trên wheel. |
| L6 | Command/doc/data xanh đóng finding qua cửa recheck đã có; trường hợp không đóng được trả lệnh cụ thể. Reviewer vẫn cần recheck riêng, không tự coi reviewer pass là đã sửa mọi finding. | AdapterClosure, `test_review_b2_e2e`; `finding_actions` trong output. |
| L7 | Worker kết thúc mã lỗi đã biết có exit code, stderr/process receipt, cleanup và hướng revise trong grant; không tự retry. | Probe gốc `p_f8b.py` (worker exit 7), kể cả lần chạy tiếp sau revise. |
| L8 | Hết deadline trước verify/handoff/final verdict báo owner decision, không in cửa thực thi không còn hợp lệ. Đủ proof rồi thì vẫn chờ nghiệm thu. | L1, operator budget guard và probe deadline thật. |
| L9 | Call còn lại không đủ cho recovery thì không hướng revise sai. | TimeoutOperator test bổ sung remaining_calls=0; probe budgets. |
| L10 | Project drift sau handoff không còn hướng tới nghiệm thu sai; root chưa có internal plan hướng `engine revise`; Q5 chưa giao nêu owner. | L1 drift, L3 CAS negative, `p_f2.py drift/no_internal_plan`, Q5 module. |
| L11 | Khôi phục receipt dùng lại trong môi trường khác vẫn từ chối nhưng nêu đường reconcile môi trường cũ / xử lý retained run. Không nới provenance. | Probe `p_f3.py crash_recover`: môi trường khác từ chối, về môi trường cũ khôi phục không chạy verifier thêm. |
| L12 | Crash sau verdict xanh trước đóng finding: gọi lại cửa verdict chỉ reconcile closure và export trạng thái, không chạy lại verifier. | ClosureRecovery mô phỏng đúng điểm crash, mock verifier cấm chạy lại. |
| L13 | Khi hạn root mới là giới hạn, thông báo không khuyên tăng snapshot limit để vượt root. | SnapshotDiagnostic dùng clock có kiểm soát; budget hồi quy Sol4. |
| L14 | Cập nhật kỳ vọng trạng thái đúng; sửa fixture T2 đọc lại prior proof trong đúng môi trường đã tạo proof. Giữ mọi assertion không publish/chạy trùng/nhận proof giả. | Module managed, authority, tracking và r14 chạy trên wheel cuối; T2 được kiểm đích danh trên wheel cuối. |
| L15 | Enforce preflight nói rõ chưa đổi mode; lỗi export nói rõ mode đã ghi nhưng export lỗi. Không báo giả “plan changed”. | EnforcePreflightTests + probe gốc `p_f5.py`, cả JSON/human và guard phiên AI. |

L2 là quan sát kết quả đã chạy trong một môi trường xác định, không chứng nhận kết quả đã được kiểm lại trong terminal khác. L3 tái sử dụng repair, dependency, ledger và CAS v1/v2; không thêm engine hay sổ mới. Khi ngân sách thật đã hết, bản sửa vẫn giữ chặn, không tự gia hạn hay reset.

## Kiểm chứng trên artifact

- Wheel cuối: **70/70 test đạt**, 0 skip, 675.123 giây; `wheel-tests.json` / `wheel-tests.log`.
- Ca T2 được kiểm riêng trên cùng wheel: **1/1 đạt**, không lặp trong bộ trên; `wheel-t2.json` / `.log`. Tổng **71 test**, 0 fail/error/skip.
- Smoke chỉ wheel: **38/38 kiểm đạt**, 51.095 giây, qua luồng managed → sửa → kiểm → bàn giao → nghiệm thu fixture.
- Probe gốc Claude: **37/37 điều kiện đầu ra đạt**, 6 script; `probe-assessment.json`, log và script nguyên byte trong evidence.
- Định danh: **145/145 payload** khớp archive snapshot và file cài; **5/5** mốc bảo vệ giữ nguyên hash.


`run_wheel_tests.py` lấy mọi module sản phẩm có trong distribution từ venv cài wheel. Một số helper fixture v1 không được phân phối nằm trong archive cùng snapshot, được liệt kê riêng; `wrong_origin` phải rỗng. Smoke riêng chỉ dùng wheel và worker tiến trình cục bộ. Việc approve/accept trong các bài thử chỉ là fixture trên sổ tạm, không phải nghiệm thu của chủ.

Probe Claude được sao chép nguyên byte vào `evidence/claude-original`, chạy với `RV2_LAB` mới và marker phiên AI trong process lab để ca guard của probe có đúng điều kiện; `probe-assessment.json` kiểm nội dung kết quả thay vì coi exit 0 là đạt. `p_f2.py` và `p_f3.py` dùng bộ chọn case gốc để chỉ chạy phần liên quan. Log source có các lần đỏ do fixture import/context-manager/newline; giữ lịch sử đó, không cộng vào số PASS của wheel cuối. Các lượt kiểm snapshot trung gian bị dừng khi thay thế không phải lượt PASS; chỉ số của wheel cuối nằm riêng trong `wheel-tests.json`. Script `large_wheel.py` giữ để tiện diễn tập nhưng không chạy lại ở lượt này.

## Giới hạn và phát hành

- Không chạy toàn gate theo phạm vi đã giao. Chưa chạy model/provider thật, phiên Claude thật, thông báo desktop thật hoặc benchmark MEP 108.897 file. Không suy ra tăng tốc tổng thể từ các bài thử local.
- Bản sửa này **chưa được OneCrew monitor trong lúc phát triển**. Các sổ lab là bài kiểm sản phẩm, không phải bằng chứng dogfood.
- Không đổi runtime SignSDK, hook, registry, sổ thật hay các gói Sol3/Sol4. Không cài wheel này đè vào runtime đang dùng khi chưa qua bước nâng cấp riêng.
- Không chạy lại gate chỉ vì thêm báo cáo. Code/phiên bản/wheel đóng băng theo `identity-result.json`; commit hồ sơ sau đó chỉ đổi tài liệu.
- Bước kế tiếp: Claude kiểm lại L1–L15 và delta `40d7ba7..8f53170` từ chính gói này. Nếu không còn lỗi local chặn, dùng kết quả đó cho quyết định phát hành. Không mở lại toàn roadmap hoặc yêu cầu anh duyệt từng sửa nhỏ.

## Prompt để Claude kiểm lại

```text
Review độc lập bản Sol5 đã sửa L1–L15, không điều tra lại từ đầu. Đọc C:/OneCrewRuns-sol/final5c/HANDOVER.vi.md, verification.json và probe-assessment.json. Snapshot 8f53170cd846ade7bf599345ede196f780755561, wheel SHA256 0e0a1def6828f66a663cf4a23dbd994be07e08908ecf1f80c7ac6a3c6bbe9513, baseline 40d7ba7. Đọc wiki entry và mục Sol5 liên quan, nhưng lấy code/test/receipt làm bằng chứng.

Tái sử dụng review C:/OneCrewRuns-rv2/REVIEW-SOL4.vi.md, probes gốc và kết quả wheel mới. Diff 40d7ba7..8f53170 là phạm vi sản phẩm; mọi module sản phẩm cần nạp từ wheel. Ưu tiên L1/L2 nghiệm thu sau deadline và terminal khác; L3 verdict cuối đỏ → Q5 repair → recheck → CAS handoff; marker giả/thiếu quyền/sửa tay vẫn bị từ chối; L12 crash trước closure không gọi verifier lại. Kiểm hướng dẫn L4–L15 qua các cửa thật và phản chứng đã có.

Không chạy toàn gate, không gọi provider tốn phí, không sửa runtime/hook/registry/sổ thật, không push/tag. Không coi owner fixture là nghiệm thu. Không mở rộng roadmap, không hỏi duyệt từng thao tác đọc/kiểm. Trả bảng Closed/Partial/Open có file:line và ca tái hiện; chỉ nêu lỗi mới có bằng chứng và tác động trong phạm vi. Nếu không còn lỗi local chặn, kết luận rõ bản này có thể chuyển sang bước phát hành nào và giới hạn còn lại. Chưa có yêu cầu tự sửa code trong lượt review này.
```
