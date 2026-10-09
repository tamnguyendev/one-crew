# Đọc quota Codex

```powershell
.\onecrew.ps1 provider quota codex --json
```

Lệnh đọc tài khoản ChatGPT đã đăng nhập qua Codex CLI 0.160.0. Không chạy model, không dùng API key dự phòng, không mua credits hoặc tiêu lượt reset. Client chỉ cho phép initialize, account/read và account/rateLimits/read; timeout 20 giây và process tree có containment.

Output chỉ chứa các bucket, mức đã dùng/còn lại, độ dài cửa sổ và thời điểm reset. Không xuất email, token hoặc reset credits. Ưu tiên bản đồ nhiều bucket; giá trị thiếu là unavailable. Không suy primary luôn là 5 giờ: phản hồi thực tế có thể đặt cửa sổ tuần ở primary.

Quan sát live lúc 2026-10-09T01:46:38Z: bucket codex, primary 10080 phút, used 57%, remaining 43%, reset 2026-10-15T04:15:34Z; secondary unavailable. Đây là bằng chứng đọc được giao thức tại thời điểm đó, **không phải quota hiện tại**. Observation hết hạn sau hai phút.

Hàm `routing_quota` yêu cầu chọn rõ bucket và các cửa sổ bắt buộc, dự toán dương và phần giữ cho chat. Nó chuyển tất cả cửa sổ quan sát được sang policy; một cửa sổ hết quota đủ để chặn lựa chọn. Thiếu cửa sổ bắt buộc hoặc spend-control observation thì từ chối. `provider choose` tiếp tục kiểm freshness/reset và quyền/capability/tier.

Feed này chưa tự chọn model hoặc dispatch. Có thể đưa observation đã ánh xạ vào [binding quota của workflow](account-reservations.vi.md), để admission giữ dự toán giữa workers dùng cùng ledger. Dự toán chưa phải hard cap hoặc settlement thực. Claude/Kiro chưa có feed đã xác minh, không coi là unlimited. Dữ liệu không được dùng để cộng phần trăm quota với token hoặc managed calls.

Đối chiếu schema được sinh từ CLI cài tại máy và [giao thức App Server chính thức](https://learn.chatgpt.com/docs/app-server). Test fixture kiểm bucket, tuần hết dù cửa sổ ngắn còn, stale/missing/strict types, subscription-only và danh sách RPC chỉ đọc. Live probe riêng ghi zero model calls.
