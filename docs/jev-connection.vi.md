# Kết nối JEV cho OneCrew

Phạm vi lượt này: người dùng cung cấp TypeSafe/JEV key để cấu hình kết nối cho lớp quyết định đã thiết kế. Chỉ lưu credential và kiểm tra API bằng dữ liệu tổng hợp; không bật decision policy, gửi source/CV/log thật hoặc chạy lại worker.

## CLI

```powershell
.\onecrew.ps1 decision configure
.\onecrew.ps1 decision doctor
```

`configure` nhập khóa qua prompt ẩn, mã hóa Windows DPAPI theo tài khoản hiện tại, lưu tại `%LOCALAPPDATA%\OneCrew\credentials\jev.dpapi`, ngoài repo. Không truyền key qua CLI argument. Trên nền tảng khác, cung cấp `TYPESAFE_API_KEY` qua cơ chế secret của môi trường; biến này được ưu tiên nếu có. Không lưu plaintext `.env`, không commit credential và không inject khóa đã lưu vào worker.

`doctor` gọi đúng một request tới `https://api.typesafe.ai/v1/systemone`, model `jev-latest`, câu hỏi Noul với task giả thay màu nút. API đọc khóa lúc gọi; khóa chỉ nằm trong Authorization header. Chặn redirect, timeout socket 15 giây, response tối đa 64 KiB, không retry, không in raw lỗi/provider body. Chỉ xuất trường model/xác suất/usage hợp lệ; thiếu usage giữ null. Không gửi source hay CV.

Endpoint/auth và schema đối chiếu [TypeSafe quickstart](https://docs.typesafe.ai/introduction/quickstart). DPAPI bảo vệ dữ liệu lưu theo tài khoản Windows; không phải cách ly khỏi tiến trình độc hại chạy cùng tài khoản. Không đưa file credential vào prompt/worker snapshot.

## Bằng chứng ngày 2026-10-08

Lượt live duy nhất: `status=connected`, observed model `jev-1.13.0`, latency 467 ms, input 304 token, output 21 token, Noul 0.02. Đây là phép thử kết nối với dữ liệu giả, không phải benchmark độ chính xác, chi phí tổng hoặc khả năng điều phối. Model alias có thể đổi; kết quả trên là model quan sát được của lượt này.

Full suite: 57 test đạt, gồm 51 test trước và 6 test JEV. JEV tests kiểm DPAPI thật với dữ liệu giả, schema/xác suất không hợp lệ, redirect, redaction và không retry. Khóa thật không nằm trong fixture.

| ID | Yêu cầu | Implementation | Verification | Status |
|---|---|---|---|---|
| JC01 | Lưu khóa ngoài repo, mã hóa theo user, đọc lúc cần | onecrew/jev.py: store_key/load_key/protect | DPAPI roundtrip test; live store + doctor | Complete |
| JC02 | Probe một lượt, synthetic data, bounded IO, không lộ credential | onecrew/jev.py: probe/NoRedirect/main | Schema/redirect/error/no-retry tests và live response | Complete |
| JC03 | CLI và hướng dẫn phân biệt kết nối với decision policy | onecrew/cli.py; tài liệu này | PowerShell decision doctor exit 0; full regression suite | Complete |

Connection slice: 3/3 Complete. DecisionEvaluator DF06/DF09/DF11, shadow benchmark và auto-apply vẫn chưa triển khai. Không dùng kết quả probe để bật routing. Kiến trúc yêu cầu kiểm chứng classifier trước khi cho policy áp dụng; key sẵn sàng không thay kiểm chứng đó. JEV không tạo code và kết nối này chưa sửa blocker backend của SPEC-004.
