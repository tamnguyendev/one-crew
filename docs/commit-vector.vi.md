# Kiểm chứng tương thích giữa nhiều repo

```powershell
.\onecrew.ps1 --project D:\RepoA work vector TASK-A --revision <goal-budget-revision> --file vector-recipe.json
.\onecrew.ps1 --project D:\RepoA work outputs TASK-A --full
```

Các task phải thuộc cùng [budget group](goal-budget.vi.md), đã hoàn thành/verify và dừng toàn bộ worker. Mỗi repo cần delivery receipt đã verify từ `work branch` hoặc `work merge`; không nhận một commit tự khai chưa có evidence.

Recipe có `members` và `check`. Mỗi member gồm `task_id`, `project`, `alias`, `snapshot`, `ref`, `commit`. Danh sách phải bao phủ đúng group. Alias ngắn, duy nhất; file `settings.json` của alias `left` xuất hiện trong container ở `/work/left/settings.json`. Tổng scope vẫn tối đa 200 files/16 MB theo snapshot contract.

`check` là container_test như workflow, có `acceptance: ["AC-VECTOR"]`. Test entry phải ở read-only context đã seal của owner; ví dụ `left/compat.py`, argv chứa `/work/left/compat.py`, image ghim SHA-256. Code test không thể do worker sửa để tự pass. Operator chọn image/command khi giao lệnh vector; vẫn chịu network-none, read-only mount và resource limits của gate container.

Core đọc lại bytes từ đúng Git tree của từng commit, tạo snapshot chung có commit vector, chạy compatibility gate rồi đối chiếu lại refs. Ref đổi trong lúc kiểm thì báo stale, không lưu receipt pass. Các task pass riêng nhưng compatibility fail sẽ có receipt vector failed riêng; không giả rằng mọi repo đã tương thích.

Recipe và vector bất biến là khóa evidence. Gọi lại bộ đã pass chỉ dùng lại receipt khi task/delivery/refs vẫn đúng; không chạy lại container không cần thiết. Output thể hiện bằng chứng tại thời điểm ghi; Git refs vẫn có thể đổi sau đó và cần đối chiếu trước dùng. Không cập nhật refs, push, tự nghiệm thu hoặc hứa transaction Git nguyên tử xuyên repo.

Đây là bước kiểm chứng một bộ commit được chọn rõ. Chưa tự phân rã spec đa repo, tạo dependency graph giữa repo hoặc triển khai đồng thời. Model calls của lệnh này bằng zero; các model calls tạo member outputs vẫn nằm trong budget chung, không bị xóa khỏi tổng.

[Evidence Git/Docker thật](commit-vector-evidence.json): hai repo cùng contract thì pass; mỗi repo pass riêng nhưng `workers` lần lượt 2 và 3 thì compatibility fail. Source được tạo bằng fixture worker xác định, không phải model thật, và không có live model calls. Image ghim, network none, mount read-only; cả hai container được cleanup. Bốn unit/integration tests kiểm binding, cache, ref race và các điều kiện từ chối.
