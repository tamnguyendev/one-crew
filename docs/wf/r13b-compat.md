# R13b — Tương thích: làm tiếp việc tạo bởi bản trước R13 (mục review 2), 27/10/2026

Phạm vi: chỉ kiểm và ghi bằng chứng; không sửa runtime, không migration, không tính năng phục hồi mới. Không gọi model (executor giả), không đụng sổ thật, không sửa dữ liệu cũ (mọi thao tác trên bản sao). Code chạy: checkout `5b1fd7a` (2.2.0.dev15), `onecrew/` sạch lúc chạy, Python 3.13.15. **Chưa chạy trên wheel dev15** (chưa có wheel); lệnh chạy lại trên wheel ở §4.

## 1. Kết luận
- Không thấy lỗi hồi quy code. R13 làm đúng thiết kế: attempt/candidate trước R13 **đọc được, giữ nguyên, nhưng không bao giờ được xác thực**: kết quả là `candidate provenance unverifiable: no engine-recorded source capture for this attempt (node.started written before R13)` → fail, không phải pass. Receipt R12 không được tái dùng.
- Làm tiếp được bằng **attempt mới** trên root còn hạn: attempt mới có capture (`node.started.source`) và verify pass. **Không làm tiếp được chính attempt cũ**: candidate cũ verify lại vẫn fail, node đã verified thì engine từ chối verify lại, step nhắm node cũ trả `waiting` (không chạy lại).
- Root hết hạn vẫn bị chặn: `The shared workflow root deadline is exhausted.` (task_intake.py:236) trước khi có attempt; không gia hạn.
- Giới hạn cần biết (không phải hồi quy): node **không phải integration** đã `verified` bởi bản cũ vẫn được coi là verified (node phụ thuộc chạy tiếp trên nó). Hàng rào là integration chạy lại trên R13 (có capture) + handoff kiểm lại integration theo luật R13. Trong drill, candidate cũ của C đã hoàn nguyên thay đổi chưa commit của người dùng (lỗ P1-S, dev14 cho pass) — thay đổi đó **không** lọt vào integration R13 (b.txt của I = nội dung người dùng) và handoff không chạm project.

## 2. Bảng bằng chứng — 4 mức của (e)
| Dữ liệu | (1) Sổ đọc được | (2) Lịch sử/artifact/thay đổi chưa commit giữ nguyên | (3) Làm tiếp được (attempt mới) | (4) Làm tiếp CHÍNH attempt cũ |
|---|---|---|---|---|
| dev9 SDK trial — root `sdk-trial-vn-sign-sdk-20261026-engine` (35 node), `…-sample-…` (22 node) | **Có**: `engine.state` 35/22 node, 0 có capture; CLI `engine state`/`engine ready`/`plan report`/`plan digest` (64 kế hoạch)/`compat scan` exit 0 | **Có**: bản sao sổ: mọi dòng + mọi file gốc còn nguyên (chỉ thêm 1 event `workflow.recovery_decided`); project gốc không đổi (hash toàn cây trước/sau bằng nhau) | **Không** (không thực hiện được, không phải lỗi): `ready=[]` (node còn lại `held`, KZ chờ), step → `waiting`; hạn sdk 26/10 05:55Z, sample 04:55Z đã qua → `stop_at_ceiling` = `blocked` deadline, "only the owner can extend"; dùng 41/60 và 25/40 call, không đổi | **Không**: 55/55 node có artifact → OUT fail unverifiable (R13 §10, `D:\OneCrewRuns\sdk-trial\reverify-r13\{sdk,sample}\inventory.*`) |
| dev14 mới — A (root đang chạy: C verified-bởi-dev14 [candidate hoàn nguyên b.txt], E partial, F produced chưa verify, D/I pending; project có b.txt sửa chưa commit + u.txt untracked) | **Có**: state, CLI 5 lệnh exit 0; bản dev14 đọc lại sổ SAU khi dev15 ghi: ok | **Có**: 49/49 event gốc, 3 attempt, 4 task, mọi file state gốc còn nguyên (thêm 87 event, 4 attempt); b.txt = `USER UNCOMMITTED CONTENT`, u.txt còn, HEAD không đổi | **Có**: D (mới), E (attempt mới `continues` = attempt cũ, mang nội dung partial), F (fail → repair W19 → thế hệ 1), I — mỗi node 1 attempt mới có capture, verify pass; C không chạy lại; call 3 → 7 / 100, trước hạn. Handoff từ chối `Candidate includes changes outside its internal write provenance.` vì b.txt chưa commit nằm trong vùng đọc — luật cũ, common_handoff.py không đổi từ f71ba51 | **Không**: verify F cũ ×2 → fail unverifiable (recovery = `repair`); checker R13 trên C cũ → fail; `engine.verify C` → "Only the current produced node can be verified."; step nhắm F/C → `waiting` |
| dev14 mới — B (root xong: C, I verified bởi dev14, chưa handoff) | **Có** (+ dev14 đọc lại sau: ok) | **Có** (mọi dòng/file gốc còn) | **Có**: `internal_plan.revise` chỉ đổi node integration → I thế hệ 1 → step (attempt mới có capture) → verify pass → handoff `delivered`; C không chạy lại; call 2 → 3 | **Không**: handoff integration cũ → "The actual final candidate failed its approved root checks; project unchanged." (project kiểm lại: không đổi) |
| dev14 mới — X (hạn 1 phút, chưa chạy gì) | **Có** | **Có** | **Không**: step → `The shared workflow root deadline is exhausted.`, 0 attempt, executor không được gọi; `stop_at_ceiling` = blocked deadline, `grants_authority: false`, `resets_budget: false` | — |

Ghi chú X: step đã ghi `decision.recorded` (Q2) + `context.entry` trước khi bị từ chối ở submit — bản ghi quyết định cho một lần nhận việc không xảy ra; vô hại, thứ tự này không do R13 đổi.

## 3. Legacy-continuation đã ship chứng minh gì / không
`verify/legacy_continuation.py` (15 bước, chạy từ gói): root **schema-2 kiểu cũ (không phải workflow)** do wheel cũ tạo chạy tiếp trên wheel mới theo nghĩa cũ (`verdict run` → M1 passed, không integrity), trang bàn giao O1, guard `verdict baseline` (AI bị từ chối, commit lạ bị từ chối, owner ghi một lần), danh tính root không đổi, bản cũ đọc lại được, module từ venv.
**Không** phủ: root workflow (sequential-engine), `node.started.source`, attempt/partial/repair/handoff, candidate trước R13. Phần đó = drill này (từ checkout, chưa từ gói) + `tests/test_wf_r13b_compat.py`.

## 4. Lệnh, script, kết quả
Script: `D:\OneCrewRuns\wf-dev-tools\compat\` — `compat_common.py` (executor giả = cách NativeExecutor.prepare dựng base), `gen_dev14.py`, `run_dev15.py`, `read_dev14.py`, `run_all.sh`, `show.py`, `mutant_fallback.py`.
Kết quả: `D:\OneCrewRuns\wf v\compat-r13b\` — `dev14-orig\gen-report.json` (dev14 = 2.2.0.dev14 từ `wf-handover-f71ba51\wheel`, C verify **pass** dù hoàn nguyên b.txt: tái hiện lỗ P1-S trên wheel thật), `dev14-pristine\` (bản gốc không bao giờ mở bằng engine), `dev9-pristine\`/`dev9-work\` (hai bản sao sổ dev9), `results-checkout\{A,B,X,dev9}.json` + `*-read-by-dev14.json` + `run-*.log`.
```
# tạo dữ liệu trước R13 (một lần; venv có sẵn: "D:\OneCrewRuns\wf v\compat-r13b\venv-dev14")
"D:/OneCrewRuns/wf v/compat-r13b/venv-dev14/Scripts/python.exe" -I -X utf8 D:/OneCrewRuns/wf-dev-tools/compat/gen_dev14.py "D:/OneCrewRuns/wf v/compat-r13b/dev14-orig"
# rồi copy dev14-orig -> dev14-pristine (shutil.copytree). Mỗi lượt run khôi phục dev14-orig từ pristine.
# chạy drill trên checkout
sh D:/OneCrewRuns/wf-dev-tools/compat/run_all.sh D:/TamNT/Workspace/11.OneCrew/wf-codex C:/Users/NUC/AppData/Local/Programs/Python/Python313/python.exe results-checkout
# chạy lại trên wheel dev15 (khi có): venv mới cài wheel, rồi
sh D:/OneCrewRuns/wf-dev-tools/compat/run_all.sh installed "<venv-dev15>/Scripts/python.exe" results-wheel
```
Lưu ý thời hạn: root A/B hết hạn 27/10 13:54Z/13:55Z (120 phút sau khi tạo); chạy lại sau giờ đó phải tạo lại dữ liệu bằng `gen_dev14.py` vào thư mục mới.
Test: `tests/test_wf_r13b_compat.py` — 5 test, OK (≈40 s), không skip, không dữ liệu ngoài. Mô phỏng engine trước R13 bằng `_source_capture → (None, None)` (payload không có capture, không có lỗi capture — như dev14) và verdict dev14 bằng event `node.verification` luật R12. Đỏ thử: `mutant_fallback.py` (verifier lấy capture mới của project khi thiếu capture) → 3/5 fail.

### Lặp lại trên wheel cuối dev16 (27/10 21:50)
Dữ liệu trước R13 tạo mới bằng wheel dev14 vào `D:\OneCrewRuns\wf v\compat-r13b-wheel-b71cea4\` (dev14-orig + pristine; dev9 copy từ dev9-pristine), venv mới cài `onecrew-2.2.0.dev16` từ gói `wf-handover-b71cea4` (`onecrew` nạp từ venv), chạy bằng `run_all_d.sh installed <venv-dev16 python> results-wheel <drill dir>`. A, B, X, dev9: exit 0; kết quả từng bước trùng lần chạy từ checkout (0 khác biệt); mọi dòng sổ và file state bản pristine giữ nguyên; project SDK gốc không đổi; dev14 đọc lại A/B/X sau drill exit 0.

## 5. Hướng dẫn tương thích cho beta (và giới hạn)
1. **Attempt/candidate cũ**: đọc được, giữ nguyên, không sửa. Kiểm theo R13 = *unverifiable* (fail), **không phải pass**; không có cách hợp lệ làm nó pass (không tái dùng receipt R12, không chọn baseline khác). Kiểm hàng loạt: `docs/wf/audit/tools/reverify_nodes.py <state> <project> <plan> --mode out` trên **bản sao**.
2. **Làm tiếp = attempt mới trên root còn hạn**, bằng cơ chế có sẵn: node pending → `engine step`; node partial → `engine step` (attempt mới tiếp từ candidate partial, `continues` = attempt cũ); node produced chưa verify → `engine verify` (fail) → repair W19 (`repair_tasks.prepare`, trong grant, tốn call); integration đã verified bởi bản cũ → `engine revise` chỉ đổi node integration → step → verify → handoff. Call đã tiêu vẫn tính; mỗi attempt mới 1 call của root.
3. **Node thường đã verified bởi bản cũ**: được giữ là verified (không bị đánh lại, cũng không được "hợp thức hoá" — kiểm lại vẫn fail). An toàn giao hàng dựa vào integration R13 + handoff. Muốn mọi node có provenance R13 thì phải re-issue node đó bằng internal revision — kéo theo chạy lại node phụ thuộc (tốn call); repair W19 không dùng được vì kiểm lại trực tiếp không ghi `node.verification` fail.
4. **Root hết hạn/hết call**: vẫn bị chặn, không gia hạn, không tạo root mới thay; `stop_at_ceiling` ghi blocked; gia hạn là quyết định của chủ sở hữu (guard D9, chưa có verb gia hạn). Hai root dev9 thuộc diện này.
5. Thay đổi chưa commit của người dùng nằm trong vùng đọc chặn handoff (như trước R13): commit/stash trước khi bàn giao. Executor không phải NativeExecutor tự dựng base sẽ bị stale nếu không dùng `source_snapshot`.
6. Không thực hiện được trong drill: NativeExecutor thật trên dữ liệu cũ (node dev14 không ghim executor; drill dùng executor giả dựng base như NativeExecutor.prepare), root held cần owner trả lời (dev9), wheel dev15.

## 6. Hồi quy
Không có. Không đề xuất sửa code.
