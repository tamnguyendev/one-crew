# OneCrew v2.1 — hướng dẫn cho Claude

OneCrew là hợp đồng công việc cho AI: AI chỉ làm trong plan đã được chủ sở hữu duyệt, mốc cần verdict độc lập, chỉ con người nghiệm thu.

## Khi vào phiên mới
1. Đọc `docs/BAT-DAU-LAI.vi.md` (là gì, chạy thế nào, quy trình, động từ của chủ sở hữu, đổi máy).
2. Chạy `plan digest` trên state-root thật để biết plan nào đang mở:
   `<python> -X utf8 onecrew_cli.py --project <repo> --state-root D:\OneCrewRuns\state-v2-real plan digest`
   (python: `D:\TamNT\Workspace\9.VMAgent\onecrew\.venv\Scripts\python.exe`).
3. Nếu repo có `.onecrew/active-plan.json`, đọc nó trước: hook chặn mọi thứ ngoài hợp đồng đó.
4. Đọc `D:\OneCrewRuns\state-v2-real\plans\owner-rules.md` trước khi đề xuất hay trình bày bất cứ gì.

## Sáu quy tắc của chủ sở hữu
- R1. Đang phát triển thì chỉ build DEBUG; RELEASE chỉ khi phát triển xong, test đạt và chủ sở hữu đã thử trên thiết bị thật, như một bước giao riêng.
- R2. Mỗi việc đúng hai tin gửi chủ sở hữu: "Xin duyệt" và "Xin nghiệm thu", mẫu 5 mục (Yêu cầu / Người dùng sẽ thấy / Cách bạn nghiệm thu / Không làm / Rủi ro) + "Quyết định của tôi mà bạn chưa yêu cầu" + dòng của cố vấn. Lựa chọn trả lời là câu đầy đủ kèm hệ quả.
- R3. Mọi sản phẩm bàn giao (code, mockup, tài liệu, build) đi qua một hợp đồng v2.
- R4. Chẩn đoán chỉ đọc dưới ~5 lệnh và động từ của chủ sở hữu nằm ngoài v2 nhưng phải có log.
- R5. Việc khác nằm ngoài v2 cần chủ sở hữu đồng ý trước.
- R6. Không "Xin nghiệm thu" tính năng giao diện khi chưa chạy thử trên thiết bị thật.

## Cách làm một việc
- Bước 0 hỏi MỘT lần, mỗi điều chưa rõ kèm mặc định: đúng yêu cầu (nhiều/ít hơn lời chủ sở hữu), phạm vi và file, môi trường kiểm có giống thật, nơi giao (trong repo; ngoài repo cần người điều phối), loại build theo vòng đời, thay đổi giữa chừng thấy trước (ghi thành decisions), cách chủ sở hữu nghiệm thu (đường bấm).
- Hợp đồng JSON có `origin` (lời nguyên văn), `decisions`, `items[].source`, trường trình bày. Luôn `plan lint --file <json> --author <model id>` trước `plan propose`.
- `plan advise` khi `decisions` không rỗng hoặc cỡ M/L. Rồi MỘT tin "Xin duyệt".
- Chủ sở hữu gõ `plan approve`, rồi `hook mode enforce --plan <tên>`, trong terminal của chính họ (mẫu `scripts/owner/approve.ps1` rồi `enforce.ps1`). AI không gõ các động từ đó (`plan approve|accept|enforce`, `hook mode`, `verdict record --by owner`).
- Làm trong phạm vi hợp đồng, rồi `verdict run --plan <tên> --milestone <Mx>`; không nói "xong" trước verdict. Kết bằng `plan report` / `plan digest` và MỘT tin "Xin nghiệm thu". Báo cáo cho chủ sở hữu tối đa 6 dòng.
- Không `git push`, không `git tag` từ phiên AI.

Hợp đồng nhập cũ (OneCrew v1, chuỗi job) vẫn nằm ở `AGENTS.md`.
