# v2 việc 4: báo cáo một trang từ sổ (`plan report`, `plan digest`)

Chủ sở hữu hỏi ba điều: **đến đâu, vì sao, còn gì**. Hai lệnh dưới đây trả lời bằng một trang chữ, sinh từ sổ, không gọi mô hình, không gọi mạng.

```
onecrew --state-root <state-root> plan report <tên> [--revision N] [--out FILE]
onecrew --state-root <state-root> plan digest [--out FILE]
```

- **Chỉ đọc.** Sổ mở bằng sqlite `mode=ro`; lệnh không ghi sự kiện, yêu cầu hay tệp nào trong state root (kể cả `sync_refusals`, vốn ghi sổ, không chạy ở đây). Thứ duy nhất ghi ra là `--out`, và `--out` trong state root bị từ chối.
- Tìm kế hoạch theo tên trong cả state root; thư mục của biên nhận (không phải `--project`) cho biết nhật ký hook và repo nằm ở đâu.
- Nhãn bằng tiếng Việt. Chữ lấy từ sổ/hợp đồng được trích nguyên văn trong «…»; **không cắt**, dòng dài xuống dòng ở 110 ký tự. Giờ là giờ máy này, dạng `2026-10-18 22:54`. Nguồn thiếu thì in "không có dữ liệu" / "không có nhật ký hook", không đoán.

## Bốn dòng kết luận (đầu trang, trước mục 1)

Suy ra chỉ từ sổ: `Kết luận: XONG | HỎNG | DỪNG | ĐANG CHỜ` (đã nghiệm thu → XONG; một mốc hỏng hết lượt sửa → HỎNG; kế hoạch đã dừng → DỪNG; còn lại ĐANG CHỜ); `Vì sao:` mốc hỏng + dòng exit/lý do của biên nhận (mã thoát, hết giờ, dòng cuối của stderr/stdout, hoặc kết luận của reviewer), hay "mọi mốc đạt"; `Còn gì:` output chưa đạt, mục should chưa có mốc đạt, unknown còn mở, hay "không còn gì"; `Bạn cần làm:` nghiệm thu | duyệt bản N | trả lời câu hỏi | không gì.

## Bảy mục (đúng thứ tự, thường dưới 60 dòng)

| # | Mục | Đọc từ đâu |
|---|-----|-----------|
| 1 | Output đạt tới đâu | Hợp đồng có `presentation` (request, user_sees, acceptance_steps) thì in lời tiếng Việt của chủ sở hữu rồi dòng `Tiến độ`; không có thì in nguyên các `output` (tiếng Anh) kèm mốc phủ và verdict cuối. ĐẠT khi mọi mốc phủ nó đang `passed`. |
| 2 | Mốc và verdict | Mỗi mốc: kết quả, `by`, sha artifact (7 ký tự), số lần sửa đã dùng/`max_repairs`. |
| 3 | Phút so ngân sách | Từ sự kiện đầu đến sự kiện cuối của kế hoạch (mọi bản) so với `budget.time`; dòng `Lệnh: chưa đếm được`. |
| 4 | Lần chặn | `<thư mục biên nhận>/.onecrew/violations.jsonl`, lọc theo kế hoạch: *chờ kiểm* (lý do bắt đầu bằng "Milestone " hoặc có "stop block cap"), *ngoài phạm vi* (nhắc scope/owned/outside/refused; in 3 lý do gần nhất), *khác*. |
| 5 | Câu hỏi | Mọi `requests` của kế hoạch: mở/đã trả lời, câu hỏi và câu trả lời nguyên văn; hạn mức đã dùng. |
| 6 | Chạy ngoài kiểm soát | `git log HEAD` ở repo của biên nhận trong khoảng *lần duyệt đầu → sự kiện cuối*; commit có tree không khớp `artifact_sha` của biên nhận nào in là **nghi ngờ** (sha ngắn + tiêu đề). |
| 7 | Bãi đỗ | Mục *should* chưa có mốc đạt phủ nó, số lần `attention.exceeded`, unknown còn mở (đóng bằng sự kiện `unknown.closed`). |

## `plan digest`

Một dòng mỗi kế hoạch: tên, trạng thái, mốc đạt/tổng (bản mới nhất), `cần bạn làm gì:` (nghiệm thu | duyệt bản N | trả lời câu hỏi | không gì; kế hoạch dừng không có câu hỏi mở thì "quyết định việc đã dừng"). Việc mở xếp trước, sự kiện cuối mới nhất trước, tối đa 10 dòng (thừa thì một dòng "còn N việc mở nữa"). Việc đã đóng gộp một dòng: `N việc đã đóng: a nghiệm thu, b dừng, c hỏng`; *hỏng* = đang `approved` nhưng một mốc đã hỏng và hết lượt sửa.

"Cần bạn làm gì" suy từ trạng thái, bản chờ duyệt, câu hỏi mở và mốc owner-manual; mốc AI sửa hay mốc command/reviewer chưa chạy đều là "không gì" (sổ không biết AI còn đang làm hay không).

## Giới hạn đã biết

- **Lệnh chưa đếm được** (không có số cuộc gọi trong sổ); không đếm token.
- **Chạy ngoài kiểm soát là xấp xỉ**: chỉ nhánh `HEAD`, theo giờ commit trong khoảng lần duyệt đầu → sự kiện cuối (giây); commit hợp lệ làm sau lần verdict cuối, hoặc cây làm việc khác cây commit, đều có thể bị gọi là nghi ngờ; `.onecrew/` không nằm trong artifact nhưng có thể nằm trong tree commit. Không có thư mục biên nhận hay git đọc lỗi thì in "không có dữ liệu".
- Mục 3 tính cả các bản sửa (amend) của kế hoạch, có thể dài hơn thời gian làm việc thật.
- "Vì sao" chỉ nói được điều biên nhận ghi (mã thoát, dòng cuối của đầu ra); không giải thích nguyên nhân.
- Hợp đồng đọc không được (tệp bản đã đổi) thì mục 1, 2, 7 và các dòng Còn gì/Vì sao in "không có dữ liệu" còn các mục từ sổ vẫn ra.
