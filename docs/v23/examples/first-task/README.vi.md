# Task đầu tiên với wiki (2.3-A1)

Mục tiêu: một node engine viết `a.txt` theo quy ước trong wiki; check của node kiểm kết quả.

1. Tạo repo thử (bản sao, không phải project thật), có `a.txt` và chép `docs/wiki/rules.md` từ thư mục này vào `docs/wiki/`; commit; thay `"HEAD"` trong khối `onecrew` bằng commit đầy đủ vừa tạo rồi commit lại (để `HEAD` thì `wiki pages` báo lỗi và mục chỉ là đầu mối).
2. Xem wiki được đọc thế nào: `onecrew --project <repo> --state-root <sổ thử> wiki pages`.
3. Tạo plan (engine root) như `../../tools/scenario_a1.py` làm: hợp đồng có milestone `M1` là command check `a.txt == "right"`, node `C` ghi `a.txt`, pin worker `claude`. Người duyệt plan là chủ sở hữu, chạy trong terminal của mình (`onecrew owner approve …`); AI không duyệt thay.
4. Xem gói node C sẽ nhận: `onecrew --project <repo> --state-root <sổ thử> wiki show --plan <plan> --node C --text`.
5. Chạy node: `onecrew --project <repo> --state-root <sổ thử> engine step <plan>` (cần Claude Code CLI đã đăng nhập subscription; adapter chỉ chạy đúng bản CLI đã ghim). Sau đó `engine verify <plan> C`.
6. Kiểm: receipt của attempt (`knowledge.package`, `knowledge_use`) và kết quả check M1. Hướng dẫn đọc: `../../HUONG-DAN-WIKI.vi.md` §5.

`verify/scenario_a1.py` trong gói chạy đúng các bước 1–6 trên sổ tạm với `claude` giả (không gọi model).
