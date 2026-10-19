# v2 việc 4: báo cáo một trang từ sổ (`plan report`, `plan digest`)

Chủ sở hữu hỏi ba điều: **đến đâu, vì sao, còn gì**. Hai lệnh dưới đây trả lời bằng một trang chữ, sinh từ sổ, không gọi mô hình, không gọi mạng.

```
onecrew --state-root <state-root> plan report <tên> [--revision N] [--out FILE]
onecrew --state-root <state-root> plan digest [--out FILE]
```

- **Chỉ đọc.** Sổ mở bằng sqlite `mode=ro`; lệnh không ghi sự kiện, yêu cầu hay tệp nào trong state root (kể cả `sync_refusals`, vốn ghi sổ, không chạy ở đây). Thứ duy nhất ghi ra là `--out`, và `--out` trong state root bị từ chối.
- Tìm kế hoạch theo tên trong cả state root; thư mục của biên nhận (không phải `--project`) cho biết nhật ký hook và repo nằm ở đâu, nên đứng ở thư mục nào cũng ra cùng một trang.
- Nhãn bằng tiếng Việt; chữ lấy từ sổ/hợp đồng (tiêu đề, output, câu hỏi, lý do chặn) được trích nguyên văn trong «…», chỉ gộp khoảng trắng và cắt bằng "…" khi dài. Nguồn thiếu thì in "không có dữ liệu" / "không có nhật ký hook", không đoán.

## Bảy mục của `plan report` (đúng thứ tự, thường dưới 60 dòng)

| # | Mục | Đọc từ đâu |
|---|-----|-----------|
| 1 | Output đạt tới đâu | `output` của hợp đồng + mốc `covers` + verdict cuối của mốc. ĐẠT khi mọi mốc phủ nó đang `passed`. |
| 2 | Mốc và verdict | Mỗi mốc: kết quả, `by`, sha artifact (7 ký tự), số lần sửa đã dùng/`max_repairs`. |
| 3 | Phút so ngân sách | Từ sự kiện đầu đến sự kiện cuối của kế hoạch (mọi bản) so với `budget.time`; dòng `Lệnh: chưa đếm được`. |
| 4 | Lần chặn | `<thư mục biên nhận>/.onecrew/violations.jsonl`, lọc theo kế hoạch: *chờ kiểm* (lý do bắt đầu bằng "Milestone " hoặc có "stop block cap"), *ngoài phạm vi* (nhắc scope/owned/outside/refused; in 3 lý do gần nhất), *khác*. |
| 5 | Câu hỏi | Mọi `requests` của kế hoạch: mở/đã trả lời, câu hỏi và câu trả lời nguyên văn; hạn mức đã dùng. |
| 6 | Chạy ngoài kiểm soát | `git log HEAD` ở repo của biên nhận trong khoảng *lần duyệt đầu → sự kiện cuối*; commit có tree không khớp `artifact_sha` của biên nhận nào in là **nghi ngờ** (sha ngắn + tiêu đề). |
| 7 | Bãi đỗ | Mục *should* chưa có mốc đạt phủ nó, số lần `attention.exceeded`, unknown còn mở (đóng bằng sự kiện `unknown.closed`). |

## `plan digest`

Một dòng mỗi kế hoạch: tên, trạng thái, mốc đạt/tổng (bản mới nhất), `chờ: chủ sở hữu | kiểm | AI | —`. Việc mở xếp trước, sự kiện cuối mới nhất trước, tối đa 10 dòng (thừa thì một dòng "còn N việc mở nữa"). Việc đã đóng gộp một dòng: `N việc đã đóng: a nghiệm thu, b dừng, c hỏng`; *hỏng* = đang `approved` nhưng một mốc đã hỏng và hết lượt sửa.

*Chờ* là suy đoán từ sổ: đề xuất, mọi mốc đã đạt (chờ nghiệm thu), mốc owner-manual hoặc có câu hỏi mở → chủ sở hữu; mốc hỏng còn lượt sửa → AI; mốc command/reviewer chưa chạy → kiểm nếu đã có verdict, chưa có thì AI. Sổ không biết AI còn đang làm hay không.

## Giới hạn đã biết

- **Lệnh chưa đếm được** (không có số cuộc gọi trong sổ); không đếm token.
- **Chạy ngoài kiểm soát là xấp xỉ**: chỉ nhánh `HEAD`, theo giờ commit trong khoảng lần duyệt đầu → sự kiện cuối (giây); commit hợp lệ làm sau lần verdict cuối, hoặc cây làm việc khác cây commit, đều có thể bị gọi là nghi ngờ; `.onecrew/` không nằm trong artifact nhưng có thể nằm trong tree commit. Không có thư mục biên nhận hay git đọc lỗi thì in "không có dữ liệu".
- Mục 3 tính cả các bản sửa (amend) của kế hoạch, có thể dài hơn thời gian làm việc thật.
- Hợp đồng đọc không được (tệp bản đã đổi) thì mục 1, 2, 7 in "không có dữ liệu" còn các mục từ sổ vẫn ra.
