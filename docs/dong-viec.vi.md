# Đóng việc cũ: `onecrew owner close`

Sổ có thể còn nhiều việc mở mà bạn không định làm tiếp: việc đã đề xuất nhưng chưa duyệt, việc đã duyệt rồi bỏ dở, việc đã dừng chờ bạn quyết. Lệnh `owner close` để bạn đóng từng việc như vậy, kèm lời của bạn. Đóng không xóa gì: sổ chỉ thêm một dòng ghi bạn đã đóng việc đó.

## Lệnh

```
onecrew --project <repo> --state-root <sổ> owner close <tên việc> --reference "<lời của bạn>" [--dry-run] [--human]
```

- `<tên việc>`: tên plan, như trong `plan digest`.
- `--reference`: bắt buộc. Viết vì sao bạn đóng, bằng lời của bạn, ví dụ "dọn sổ 26/11: việc cũ không làm nữa". Lời này được ghi vào sổ.
- `--dry-run`: chạy thử. Lệnh kiểm như thật rồi in việc sẽ đóng và trạng thái hiện tại của nó, nhưng không ghi gì: sổ và tệp hook đều không đổi.
- `--human`: in kết quả bằng câu tiếng Việt thay cho JSON.

Lệnh này giống `plan close --by owner`.

## Ai chạy được

Chỉ bạn, trong terminal của chính bạn. Lệnh bị từ chối khi chạy trong phiên AI (Claude Code, Codex…) hay trong tiến trình tự khai là AI. Bản chạy thử cũng bị từ chối trong phiên AI. AI không tự đóng được việc nào.

## Việc gì đóng được

| Trạng thái của việc | `owner close` |
|---|---|
| đang đề xuất (proposed) | đóng được |
| đã duyệt (approved) | đóng được |
| đã dừng, chờ bạn quyết (stopped_with_report) | đóng được |
| đã nghiệm thu (accepted) | từ chối, không ghi gì |
| đã đóng (closed) | từ chối, không ghi gì |

Hai trường hợp khác cũng bị từ chối, không ghi gì:

- Việc rất cũ, tạo bởi bản OneCrew trước khi có gốc `plan-ns:`. Các bản OneCrew cũ vẫn đọc loại việc này, nên lệnh không ghi lên đó.
- Sai tên việc.

## Sau khi đóng thì sao

- Sổ có thêm một sự kiện `plan.closed`. Sự kiện ghi do chủ đóng, lời của bạn, trạng thái trước khi đóng, và dấu `closed_by: owner_close`.
- Lịch sử, bằng chứng và tệp của việc vẫn giữ nguyên. `plan show` và `plan report` vẫn đọc được, và có dòng "ĐÃ ĐÓNG".
- `plan digest` không còn liệt kê việc đó trong danh sách việc mở. Dòng cuối đếm nó trong "… chủ sở hữu đóng".
- Trang theo dõi hiện việc đó là đã đóng, không còn nằm trong các việc đang chạy hay đang chờ bạn.
- Không chạy gì thêm cho việc đó: engine không chạy việc con nào; `verdict run`, `plan amend` và `plan approve` đều từ chối.
- Đóng không phải nghiệm thu. Việc đã đóng không mở lại được. Muốn làm lại thì lập một việc mới.
- Hook thôi giữ việc đó:
  - Lệnh đóng ghi lại tệp hook đọc (`active-plan.json`) với trạng thái đóng và dấu `owner_close`. Từ đó hook không còn chặn sửa tệp hay chạy lệnh trong repo của việc đó, như với việc đã nghiệm thu.
  - Repo làm việc bình thường cho tới khi bạn duyệt hay bật hook cho một việc khác của repo đó (`owner approve`, `owner enforce`).
- Việc đóng bằng cách trả lời "dừng" cho câu hỏi của OneCrew (`owner answer … --choice stop`) giữ cách cũ: hook vẫn từ chối mọi sửa trong repo của nó.

## Đóng nhiều việc một lần: script của bạn

`owner close` đóng một việc mỗi lần. Muốn dọn nhiều việc, bạn viết một script PowerShell gọi lệnh này cho từng việc trong danh sách bạn đã chọn. Chạy thử trước, xem đủ rồi mới đóng thật:

```powershell
$onecrew = 'D:\OneCrewRuns\runtime-moi\Scripts\onecrew.exe'     # bản OneCrew đã có lệnh owner close
$so = 'D:\duong\dan\so'                                         # sổ cần dọn
$loi = 'dọn sổ 26/11: việc cũ không làm nữa'
$viec = @(
    @{ ten = 'viec-cu-1'; repo = 'D:\repo\mot' },
    @{ ten = 'viec-cu-2'; repo = 'D:\repo\hai' }
)
$that = $args -contains '-ApDung'                                # không có -ApDung thì chỉ chạy thử
foreach ($v in $viec) {
    $them = if ($that) { @('--human') } else { @('--dry-run', '--human') }
    & $onecrew --project $v.repo --state-root $so owner close $v.ten --reference $loi @them
    if ($LASTEXITCODE -ne 0) { Write-Host ('KHONG DAT: ' + $v.ten) -ForegroundColor Red }
}
```

- Lần đầu chạy không có `-ApDung`. Mỗi việc in một dòng "Chạy thử: sẽ đóng …" hay lý do từ chối. Chưa ghi gì.
- Đủ đúng rồi thì chạy lại với `-ApDung`. Mỗi việc in "Đã đóng …".
- Sau đó chạy `plan digest`: danh sách việc mở giảm đúng số việc vừa đóng.
- Script phải chạy trong terminal của bạn, không trong phiên AI.

## Giới hạn

- Không mở lại được việc đã đóng.
- Không có lệnh đóng nhiều việc trong một lần gọi; dùng script như trên.
- Đóng không dọn tệp tạm, nhánh hay worktree của việc; những thứ đó vẫn ở chỗ cũ.
- Bản OneCrew cũ hơn bản có lệnh này không biết dấu `owner_close`. Nó vẫn coi việc chưa có engine là đang mở, kể cả hook toàn máy nếu hook đó còn chạy bản cũ. Nên cài bản mới trước khi dọn sổ thật.
- Hook thôi giữ việc đã đóng chỉ khi việc đó đang là việc hook của repo đó theo. Nếu repo đang theo một việc khác, việc khác ấy vẫn giữ repo như cũ.
