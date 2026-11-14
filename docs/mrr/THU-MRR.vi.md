# Thử MR-R (đọc và tìm nguồn trên nhiều repo) bằng wheel đã cài

**Trạng thái: bản thử `2.5.0.dev28+mrr.4`. Chưa phát hành, chưa nghiệm thu, chưa thử với model thật.** Mọi thử dưới đây dùng claude giả của bộ test
(không gọi model, không mạng). Chỉ dùng thư mục thử, không dùng repo thật.

## Chuẩn bị (người dựng gói làm sẵn)

- Wheel đã cài vào một venv ngoài checkout; lệnh `onecrew` dưới đây là của venv đó (`python -c "import onecrew; print(onecrew.__file__)"` phải trỏ vào venv, không phải checkout).
- Thư mục cha thử `D:\OneCrewRuns\dot-1411\lab-mrr`: **không phải Git**, chứa hai repo Git nhỏ `repo-a` và `repo-b`, có file trùng tên ở cả hai (ví dụ `src/main.py`).
- Thư mục sổ riêng ngoài cả hai repo, ví dụ `D:\OneCrewRuns\dot-1411\lab-mrr-state`. Không dùng sổ thật.

## Lệnh thử

Chạy trong thư mục chứa `hop-dong.mau.json` và `nodes.mau.json` (cạnh thư mục thử, không nằm trong repo nào):

```bash
onecrew --project D:/OneCrewRuns/dot-1411/lab-mrr --state-root D:/OneCrewRuns/dot-1411/lab-mrr-state plan propose P1 --file hop-dong.mau.json --author codex --workflow --capability namespaced-storage --capability root-budget --capability internal-plan --capability sequential-engine
```

Rồi (ba lệnh, mỗi lệnh một dòng, cùng `--project` và `--state-root` như trên): `plan approve P1 --by owner --reference "thử MR-R"`, `engine revise P1 --file nodes.mau.json`, và lặp `engine step P1` (mỗi lần một tiến trình mới) cho tới khi node `R` ra `produced`. Xem kết quả bằng `plan report P1`.

## Đạt khi thấy

1. Báo cáo ghi từng repo: quyền đọc, tree và HEAD đã ghim, dirty hay không; nguồn trích dạng `alias@tree:file:dòng`, hai file trùng tên ở hai repo không lẫn.
2. Làm hỏng một repo (đổi tên thư mục, hoặc để merge dở) rồi chạy lại: báo cáo ghi **khoảng trống có tên** (`PHỦ THIẾU`, lý do) cho repo đó; repo còn lại vẫn được đọc.
3. Đường dẫn ngoài quyền bị từ chối, và ngân sách còn lại không được cấp lại sau khi sửa quyền.
4. Hai repo nguồn không đổi byte nào (kể cả `.git`): so sánh trước/sau bằng `git -C <repo> status` và dung lượng thư mục `.git`; thư mục cha vẫn không có `.git`.

Đây là **candidate phân tích**, chưa phải kết quả đã kiểm hay nghiệm thu. Chưa làm (cố ý): ghi nhiều repo, commit/push, phát hành đa repo, nghiệm thu của engine trên thư mục cha không Git.
