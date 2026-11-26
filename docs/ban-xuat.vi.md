# Bản xuất kế hoạch cho hook phải khớp sổ

Hook không đọc sổ khi xét một lệnh bình thường. Nó đọc **bản xuất** `active-plan.json`, có hai bản giống nhau: một trong `.onecrew/` của repo, một trong thư mục sổ. Khi hai bản khác nhau, hook theo bản ở thư mục sổ. Sổ mới là thẩm quyền; bản xuất chỉ là bản chép.

## Vì sao từng có repo bị khóa

Trước dev33, lệnh nghiệm thu không ghi lại bản xuất. Bản xuất cũ vẫn ghi `approved`. Khi quá hạn, hook chặn mọi lệnh AI của repo, trong khi `onecrew doctor` đọc sổ, thấy đã nghiệm thu (accepted) và báo ổn.

## Bản xuất khớp sổ ở mỗi đường kết thúc

| Việc xảy ra | Bản xuất ghi |
|---|---|
| nghiệm thu, kể cả nghiệm thu lại cùng kết quả | `accepted` |
| chủ đóng việc (`owner close`) | `closed`, đánh dấu do chủ đóng; hook thôi giữ |
| dừng có báo cáo | `stopped_with_report`; hook vẫn giữ |
| duyệt bản sửa | bản mới, `approved` |

Nghiệm thu việc X trong khi việc Y đang giữ repo **không** thay bản xuất của Y.

## doctor báo gì

`onecrew doctor`, mục "plan đang mở":

- **FAIL** (chế độ `log`: WARN) khi file cho hook còn giữ repo mà sổ ghi đã nghiệm thu (accepted) hoặc chủ đã đóng. Dòng báo nêu việc nào, file ghi gì, hạn, sổ ghi gì và lệnh sửa.
- WARN khi hai bản xuất ghi trạng thái khác nhau.
- PASS khi bản xuất khớp sổ.
- Việc còn mở mà bản xuất hết hạn (expired) vẫn FAIL như trước.

`doctor` chỉ đọc sổ, không ghi gì.

## Cách sửa

```
onecrew --project <repo> --state-root <sổ> hook export <plan>
```

Lệnh ghi lại cả hai bản xuất theo sổ.

## Hook tự thả bản xuất hết hạn

Chỉ khi bản xuất đã hết hạn (expired) và hook sắp chặn vì thế, `hook check` mở sổ **chỉ đọc**. Nó cho lệnh đi qua khi sổ nói **đúng việc đó** (cùng mã việc và cùng mã bản hợp đồng) đã nghiệm thu hoặc chủ đã đóng. Hook không ghi sổ và không ghi lại bản xuất.

Mọi trường hợp khác vẫn chặn như cũ:

- việc còn mở, đã dừng có báo cáo, hoặc đóng bằng câu trả lời "dừng";
- sổ không có, không đọc được, hoặc đang bị khóa quá lâu;
- bản xuất ghi mã bản hợp đồng khác với bản đã nghiệm thu;
- bản xuất trỏ sang một sổ khác với sổ hook đang dùng cho repo (`--state-root` của hook, không có thì `.onecrew/config.json`, rồi bảng đăng ký, rồi sổ mặc định): bản xuất không được tự chọn sổ thả cho nó;
- bản xuất thiếu thông tin để đối chiếu (bản xuất rất cũ).

## Giới hạn

- Bản xuất cũ **chưa hết hạn** vẫn giữ repo theo luật của nó; `doctor` báo và `hook export` sửa.
- Khi một lệnh chỉ chạy từ trong repo đó mà không ghi gì vào nó, hạn không được xét, nên các luật cấm lệnh của bản xuất cũ vẫn áp dụng cho tới khi có người xuất lại.
- Mỗi lệnh sau khi hết hạn đọc sổ lại cho tới khi có người xuất lại.
- Nếu việc khác đang giữ repo thì nghiệm thu hay xuất lại không thay được bản xuất của nó; chỉ chủ sở hữu đổi việc giữ repo.
- Ghi tệp lỗi lúc xuất chỉ in cảnh báo; `doctor` là cách phát hiện.
- Hook đã cài của bản OneCrew cũ hơn không có phần tự thả này.
