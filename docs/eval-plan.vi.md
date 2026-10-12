# Eval OneCrew — phạm vi được người dùng giao 12/10/2026

Nguồn phê duyệt: người dùng yêu cầu triển khai hướng eval đã thảo luận, lấy case
đã gặp, đo trước–sau khả năng tự hoàn thành và chỗ còn cần Codex hỗ trợ. Đây là
quyền triển khai harness, chạy replay local và đọc bằng chứng task được giao;
không tự restart task sản phẩm, cài điện thoại hoặc gọi server đang do entry khác dùng.

## Hợp đồng

- EV01: corpus versioned từ lỗi bàn giao backlog, timeout/checkpoint, metadata >2 MB,
  review >80k, cache thiếu, thông báo một lần, workflow tổng và APK/device gates.
  Mỗi case có nguồn commit/task, tiêu chí, lớp đo, baseline và nhu cầu hỗ trợ.
- EV02: cùng harness đóng băng chạy trên Git revision bất biến, workspace riêng,
  process có timeout và log; không sửa checkout/task thật, không gọi model/ADB thật.
  Import thiếu, skip, lỗi harness và timeout phải hiện riêng; không tính là pass.
- EV03: so sánh chỉ khi corpus/harness/môi trường/case/repeat khớp. Có chế độ
  historical (baseline riêng ngay trước fix) và release (cùng một baseline).
  Historical không phải phép đo tăng trưởng giữa hai bản release; thời gian harness
  không phải latency model. Regression/suite nhỏ không được gọi là product autonomy.
- EV04: observe đọc snapshot ledger transaction nhất quán theo đúng task, deduplicate
  checkpoint/outcome, giữ hash/seq và giới hạn; không parse report tự do để suy pass.
  Đếm calls, timeout checkpoint, repair, recorded gates và assistance; unknown giữ unknown.
  Read-only không start, ACK, resume, migrate hoặc sửa budget. Không xuất credentials/raw prompts.
- EV05: báo cáo máy đọc và Markdown gồm trước–sau, regressions, gaps, hướng hỗ trợ;
  thay đổi skill/routing chỉ là đề xuất, không auto-promote. Tests kiểm grader chống
  false-pass, đổi mẫu số, sai revision/corpus/environment và dữ liệu thiếu.
- EV06: chạy benchmark thật của runtime trên các case lịch sử; quan sát ít nhất
  các task cloud-auth đã biết; publish kết quả local, CLI, hướng dẫn cho entry khác.
- EV07: đo product autonomy trên bài chưa thấy và live solution→APK→A54/server.
  Không dùng bài đã phát triển làm held-out, không dùng fixture thay model/device thật.
  Chưa có bộ task held-out niêm phong hoặc dispatch thiết bị rảnh cho phép chạy cặp
  tương đương; giữ yêu cầu này Blocked, không tuyên bố đã đo tổng quát hóa.

## Vòng thực hiện

1. EV01–EV05: harness, reader, rubric và unit/integration checks; commit riêng.
2. EV06: chạy replay trước/sau, đọc ledger thật, đối chiếu bằng chứng và ghi report;
   sửa lỗi harness nếu có, chạy lại các cặp bị ảnh hưởng, commit report.
3. EV07 giữ tách biệt: chuẩn bị hướng dẫn nghiệm thu live; không bịa số liệu.

Không sửa các artifacts lịch sử chưa commit của người dùng. Số test của harness
không cộng vào số case benchmark. Result không tự trở thành lesson/skill đã duyệt.
