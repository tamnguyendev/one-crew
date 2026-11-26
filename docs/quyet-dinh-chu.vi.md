# Sổ quyết định của chủ theo repo

Mỗi repo có một sổ ghi những điều chủ sở hữu đã quyết: áp cho đâu, ghi ngày nào, đúng lời chủ nói. Phiên làm việc đọc sổ để không quên quyết định, và không áp một quyết định rộng hơn phạm vi của nó. Sổ chỉ nhắc, không chặn gì.

## Khi nào ghi

Ghi ngay khi chủ nói ra một quyết định. Phiên điều phối là bên ghi; đây không phải động từ của chủ, chủ không phải gõ lệnh. Chủ xem sổ bất cứ lúc nào, thấy ghi sai thì bảo thay bằng một quyết định mới.

## Cách ghi

```powershell
onecrew --project <repo> --state-root <thư mục sổ> decision add --scope "onecrew/v2/" --title "Giữ nguyên tên lệnh cũ" --quote "đừng đổi tên lệnh nào hết" --source "chủ gõ ở phiên điều phối, 26/11 16:00"
```

| Tùy chọn | Ý nghĩa |
|---|---|
| `--scope` | Bắt buộc. `*` là cả repo; hoặc mẫu đường dẫn tính từ gốc repo: đúng tệp (`pyproject.toml`), thư mục (`onecrew/v2/`) hay glob (`docs/*.md`). So không phân biệt hoa thường. Ghi đúng phạm vi chủ nói, không ghi rộng hơn. |
| `--title` | Bắt buộc. Một dòng ngắn, tối đa 120 ký tự. Danh sách và lời nhắc chỉ hiện dòng này. |
| `--quote` | Bắt buộc. Lời chủ nguyên văn, không diễn lại, tối đa 500 ký tự. |
| `--source` | Nên có. Lời đó nói ở đâu, lúc nào. |
| `--replaces SQD-n` | Khi quyết định này thay một quyết định còn hiệu lực. |

Máy tự đặt mã (`SQD-1`, `SQD-2`, ...) và ngày giờ. Thiếu phạm vi, tiêu đề hay lời, quá dài, phạm vi nằm ngoài repo, hoặc `--replaces` chỉ một mã không có hay đã bị thay: lệnh từ chối và không ghi gì.

Ghi xong thì chạy `decision show SQD-n` để đối chiếu lời nguyên văn. Windows PowerShell 5.1 có thể làm mất dấu ngoặc kép nằm bên trong tham số khi gọi chương trình.

## Xem

```powershell
onecrew --project <repo> --state-root <thư mục sổ> decision list
```

```powershell
onecrew --project <repo> --state-root <thư mục sổ> decision list --path onecrew/v2/cli.py
```

```powershell
onecrew --project <repo> --state-root <thư mục sổ> decision show SQD-1
```

- `list` hiện các quyết định còn hiệu lực, mỗi cái một dòng: mã, tiêu đề, phạm vi, ngày.
- `list --path <tệp>` chỉ giữ quyết định có phạm vi trùng tệp đó. Đường dẫn tương đối tính từ gốc repo.
- `list --all` hiện cả quyết định đã bị thay, ghi rõ bị thay bởi mã nào.
- `show SQD-n` in đủ: phạm vi, ngày giờ, nguồn, trạng thái, người ghi và lời chủ nguyên văn.

"Người ghi" cho biết ai ghi (phiên AI hay không, và actor đã khai nếu có). Đây không phải mã phiên.

## Đổi ý: thay quyết định

Ghi một quyết định mới kèm `--replaces SQD-n`. Quyết định cũ ra khỏi danh sách còn hiệu lực, nhưng dòng cũ trong sổ không đổi. Không có lệnh sửa hay xóa.

## Phiên mới thấy gì

Phiên có plan, lúc mở, được thêm danh sách quyết định còn hiệu lực của repo: mỗi cái một dòng gồm mã, tiêu đề, phạm vi. Tối đa 10 dòng (10 cái mới nhất, kèm tổng số). Lời nguyên văn không nằm trong danh sách; cần thì chạy `decision show`. Repo chưa có quyết định thì không thêm gì.

## Lời giao việc

Lời giao việc nói rõ quyết định nào áp cho việc đó, bằng mã: "Áp dụng: SQD-2, SQD-5". Không có cái nào áp thì ghi đúng câu "không có quyết định liên quan".

Với plan thường trực đã bật nhắc giao việc (`onecrew init --remind on`): repo có quyết định còn hiệu lực mà lời giao không có mã `SQD-n` hay câu trên thì được nhắc một dòng, kèm mã và tiêu đề. Việc giao vẫn đi. Lời nhắc này không phụ thuộc tệp mẫu giao việc `mau-giao-viec.md`.

## Sổ nằm ở đâu

`<thư mục sổ>/plans/quyet-dinh/<tên repo>-<mã>.jsonl`, mỗi dòng một quyết định dạng JSON, chỉ ghi thêm. `decision add` in ra đường dẫn đầy đủ.

- Mọi worktree của cùng một repo dùng chung một sổ.
- Sổ nằm ngoài repo; không có gì được ghi vào repo của dự án.
- Dùng đúng `--state-root` mà plan của repo đang dùng, nếu không phiên sẽ không thấy quyết định. Không đưa `--state-root` thì lệnh dùng thư mục sổ trong `.onecrew/config.json`, rồi tới thư mục mặc định.
- Sổ gắn với vị trí thư mục git của repo. Chuyển repo sang chỗ khác thì sổ cũ vẫn còn trên đĩa nhưng repo mới không tự nhận.
- Dòng hỏng bị bỏ qua (lệnh xem có cảnh báo); sổ không đọc được thì hook im lặng.

## Những gì sổ không làm

- Không chặn việc nào.
- Không kiểm quyết định được áp có đúng không: chỉ biết lời giao có nêu mã hay câu "không có quyết định liên quan".
- Không tự nhập quyết định cũ (sổ yêu cầu viết tay, luật chung của chủ).
- Không thay luật chung của chủ (`owner-rules.md`) hay hợp đồng.
- Không chống được việc sửa tay tệp sổ.
- Không hiện trên trang theo dõi.
- Lời nhắc và danh sách theo repo của plan phiên đang chạy, không theo repo mà việc được giao sẽ sửa.
- Lệnh `decision` có ở lệnh `onecrew` đã cài. Chạy từ bản mã nguồn thì dùng `python -m onecrew.v2.cli decision ...`, vì ở đó chữ `decision` là lệnh cũ của JEV.
- Hook của plan xét cả chữ nằm trong dòng lệnh. Nếu lời chủ chứa cụm bị cấm (ví dụ một lệnh đẩy mã), lệnh ghi có thể bị chặn: khi đó dừng và báo chủ, không tìm cách lách.
