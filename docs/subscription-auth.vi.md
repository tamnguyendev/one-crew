# Đăng nhập subscription trước khi dispatch

OneCrew kiểm tra phiên bản CLI và loại đăng nhập trước mỗi lượt worker. Codex phải trả về trạng thái ChatGPT; Claude phải trả về đăng nhập `claude.ai`/OAuth thành công. Thiếu đăng nhập, kết quả không hiểu được hoặc CLI đổi phiên bản đều chặn dispatch. Không lưu thông tin tài khoản hoặc credential vào kết quả doctor.

Tiến trình con nhận bản sao môi trường đã loại API key, endpoint OpenAI/Anthropic và các biến chọn nhà cung cấp Claude bên thứ ba. Môi trường, cấu hình và tài khoản của người dùng không bị sửa. OAuth subscription và thiết lập chính sách quản trị được giữ. Codex dùng `forced_login_method="chatgpt"`, `model_provider="openai"`; Claude dùng restricted/safe mode và yêu cầu `claudeai`. Không dùng Claude `--bare` vì chế độ đó bỏ OAuth. Công cụ đọc quota áp dụng cùng cấu hình.

Đây là rào chắn cấu hình cho các adapter đã ghim phiên bản, không phải công cụ kiểm toán hóa đơn. Chính sách quản trị vẫn có ưu tiên; Extra Usage/credits của chính tài khoản subscription và lượng gọi bên trong CLI chưa được OneCrew áp trần độc lập. Kiro tiếp tục cần `whoami` thành công; chưa có feed quota Kiro đã kiểm chứng.

Kiểm chứng ngày 2026-10-09: Codex đăng nhập ChatGPT và đọc quota thành công (0 model calls); Claude ban đầu chưa đăng nhập CLI nên bị chặn; sau khi người dùng đăng nhập đã vượt qua trial code/handoff/cancel trong [evidence mới](claude-live-evidence.json). Bốn test subscription, bốn provider, năm quota và 18 control tests qua. Claude live đã có bằng chứng giới hạn theo các trial đã ghi; không suy thành đầy đủ fault matrix.

Tham chiếu: schema cấu hình của Codex 0.160.0 và `claude --help` 2.1.286 tại máy; [Anthropic hướng dẫn loại API key khỏi môi trường để dùng subscription](https://support.claude.com/en/articles/12304248-manage-api-key-environment-variables-in-claude-code). CLI doctor có thể chạy bằng `onecrew provider doctor codex --json` hoặc `onecrew provider doctor claude --json`.
