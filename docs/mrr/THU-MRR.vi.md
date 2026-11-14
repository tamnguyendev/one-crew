# Thử MR-R (đọc nhiều repo) — không cần `git init` thư mục cha

**Trạng thái: bản phát triển `2.4.0.dev6+mrr.3`. Chưa phát hành, chưa nghiệm thu, chưa thử với model thật.** Mọi thử dưới đây dùng claude giả
(có trong gói, không gọi model, không mạng). Không dùng cho dự án thật.

## 1. Thử nhanh bằng gói (một lệnh)

Gói tự tạo repo mẫu, venv mới từ wheel của gói, rồi chạy 12 kịch bản qua CLI đã cài (có 3 lần **kill process thật** giữa chừng):

```
powershell -ExecutionPolicy Bypass -File "<thư mục gói>/verify/thu-mrr.ps1" -Work "D:/OneCrewRuns/mrr-thu-3"
```

Thư mục `-Work` phải **chưa tồn tại**. Đạt khi dòng cuối là `DAT: ...` (hết ≈10–15 phút). Dòng `KHONG DAT: ...` nêu kịch bản lỗi;
bằng chứng ở `<Work>\evidence\thu`. Script không ghi gì ngoài `-Work`, không đụng sổ OneCrew thật.

## 2. Thử trên hai repo của bạn (thư mục cha không phải Git)

Bạn có một thư mục điều phối, ví dụ `D:\work`, chứa `repo-a` và `repo-b` (mỗi cái là repo Git). **Không** `git init` `D:\work`, **không** `onecrew init`.

1. Chép `mau/hop-dong.mau.json` và `mau/nodes.mau.json` của gói ra ngoài `D:\work`. Trong hợp đồng, sửa `authority.repos`
   (`alias`, `path` dưới `D:\work` hoặc đường dẫn tuyệt đối có ổ đĩa, `read` = phần được đọc); sửa `understanding.target` cho đúng một file có thật.
   `scope.owned` là nơi ghi báo cáo, phải nằm **ngoài** mọi repo. Trong `nodes.mau.json`, `sources.read` dạng `alias:thư-mục/`.
2. Chọn thư mục sổ **ngoài** `D:\work` và ngoài mọi repo, ví dụ `D:\onecrew-state`. Chạy (4 lệnh, bằng `onecrew` của venv đã cài từ gói):

```
onecrew --project D:/work --state-root D:/onecrew-state plan propose P1 --file hop-dong.mau.json --author codex --workflow --capability namespaced-storage --capability root-budget --capability internal-plan --capability sequential-engine
onecrew --project D:/work --state-root D:/onecrew-state plan approve P1 --by owner --reference "thử MR-R"
onecrew --project D:/work --state-root D:/onecrew-state engine revise P1 --file nodes.mau.json
onecrew --project D:/work --state-root D:/onecrew-state engine step P1
```

3. Lặp `engine step P1` (mỗi lần một tiến trình mới) tới khi node `R` ra `produced`. Xem kết quả:

```
onecrew --project D:/work --state-root D:/onecrew-state plan report P1
```

Báo cáo ghi, từng repo: quyền, tree/HEAD đã ghim, dirty, khoảng trống (`PHỦ THIẾU`, lý do), và nội dung candidate; mỗi nhận xét trích dẫn dạng
`alias@tree12:file:dòng`. Đây là **candidate phân tích**, chưa phải kết quả đã kiểm hay nghiệm thu.

Worker thật (`claude` CLI với model) chưa được thử trong bản này: cần máy có `claude` đăng nhập; mọi bằng chứng hiện có dùng worker giả.

## 3. Điều cần biết khi đọc kết quả

- Repo nguồn chỉ được đọc, kể cả thư mục `.git` (kiểm từng byte trước/sau trong thử nhanh). Repo thiếu, đang merge dở, có filter/LFS chưa kéo, sparse index,
  partial clone thiếu object... là **khoảng trống có tên** cho repo đó; repo khác vẫn được đọc. Báo cáo không bao giờ coi “đã khai quyền” là “đã đọc”.
- Hai repo cùng một thư mục (hai cách viết đường dẫn) chỉ đọc một lần, alias còn lại là khoảng trống `same_repository`.
- **Chưa làm (cố ý):** ghi/sửa mã nhiều repo, commit/push, deploy, rollback nguyên tử xuyên repo; verify/accept/handoff của engine trong thư mục điều phối
  không Git; kiểm tự động trích dẫn trong văn bản của worker (thử nhanh tự đối chiếu bằng git, đó là bộ kiểm chứ không phải tính năng).
