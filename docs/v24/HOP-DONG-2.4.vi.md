# OneCrew 2.4 — hợp đồng triển khai, truy vết và kiểm chứng

Người lập: Claude (Fable 5.1, đầu mối; agent Opus/Sonnet theo việc), 01/11/2026, theo chỉ thị người dùng ngày 01/11 ("Tiếp quản và hoàn thành toàn bộ feature đã chốt của OneCrew 2.4 theo roadmap chung: 2.4-S1, S2, A, B, C") dán trong phiên Claude Code. Đây là hồ sơ thực thi, không phải roadmap: phạm vi lấy từ `outputs/onecrew-as-qc/ROADMAP.vi.md` §0.2 và §0.8 (bản 31/10 của Codex), thiết kế §2.1, §2.2, §2.4a, §2.4b, §2.4e, §2.9, §3, §7, và `ROADMAP-CLAUDE-HANDOFF.vi.md` (các mục 2.4-S1/S2, mốc mới, bước 0 31/10). Không sửa roadmap, không cộng vào 92 task beta, không đổi DoD của chúng; task 2.4 có ID riêng `T24-*`.

## 1. Baseline và cách ly

| Mục | Giá trị |
|---|---|
| Baseline code | `fb3333b` (2.3.0.dev10, tag `v2.3.0.dev10`); nhánh 2.4 tách từ commit hồ sơ `fe0a044` (code giống từng byte `fb3333b`) |
| Worktree / nhánh | `D:\TamNT\Workspace\11.OneCrew\wf-v24`, `claude/onecrew-2.4` (local; không push/tag theo nhiệm vụ này — §10) |
| 2.2 và 2.3 giữ nguyên | checkout `wf-codex` (`1753f77`), `wf-v23` (`fe0a044`); gói `D:\OneCrewRuns\wf-handover-34eb7c4-hs2` (beta 2.2), `D:\OneCrewRuns\v23\pkg\onecrew-2.3.0.dev10-beta` (wheel `8ab065c3…`); tag `v2.3.0.dev8/dev9/dev10` và receipt trong `D:\OneCrewRuns\v23` |
| Thư mục chạy 2.4 | `D:\OneCrewRuns\v24\` (venv `venv` Python 3.13.15, `state` sổ thử, `projects` project bản sao, `tmp`, `pkg`, `logs`, `design`); công cụ phụ `D:\OneCrewRuns\wf-dev-tools\v24\` |
| Cấu hình người dùng | mọi lệnh `init`/hook/test chạy với `LOCALAPPDATA`, `APPDATA`, `TEMP` riêng cho process thử; không đổi biến toàn máy, không đụng `%LOCALAPPDATA%\OneCrew\hook-projects.json` thật (SHA256 `884335df…` lúc bắt đầu) |
| Runtime đang dùng | không nâng; mọi kiểm cài/nâng/quay về/tiếp tục chạy trên venv và sổ bản sao trong `D:\OneCrewRuns\v24` |
| Version | prerelease `2.4.0.devN`: mỗi gói alpha của một mốc tăng N; beta 2.4 chỉ khi đủ S1/S2/A/B/C (§8) |
| v1 tham chiếu | `e76c703` (`D:\TamNT\Workspace\11.OneCrew\onecrew`): đối chiếu lịch sử; code v1 cùng tên trong `wf-v24/onecrew/*.py` được đọc thật trước khi tái dùng |

Tài nguyên đang dùng lúc bắt đầu (01/11 ~02:15, chỉ quan sát): các phiên Claude/Codex khác, KiroCrew, host OneCrew thật. Không dừng, không đọc/ghi sổ `state-v2-real`.

Quan sát 01/11 08:11: sổ đăng ký hook thật `%LOCALAPPDATA%\OneCrew\hook-projects.json` đổi lúc 08:01 (842 byte, SHA256 `23ec9033…`): thêm hai mục `d:\onecrewruns\copies\signsdk-dev10-test` và `…\signsdk-dev10-upgrade` trỏ tới `D:\OneCrewRuns\states\…` — do một phiên khác (thử gói dev10 trên bản sao signsdk, thư mục tạo 07:59–08:04), không phải lượt 2.4 (mọi lượt chạy 2.4 dùng `LOCALAPPDATA` riêng `D:\OneCrewRuns24	mp-int\lad`). Không đụng, không khôi phục; hash này là mốc so sánh cho các lượt sau của 2.4.

### 1.1 Tồn đọng 2.3 đã biết, phân loại cho 2.4

| Tồn đọng | Phân loại | Xử lý trong 2.4 |
|---|---|---|
| Test hạn 2 giây `tests.test_wf_metered_verifier…root_deadline…` nhạy tải máy (dev9 và dev10 cùng hỏng khi máy chậm) | ảnh hưởng trực tiếp bộ kiểm 2.4 (gate chạy module này) | ghi nhận; chỉ sửa khi bộ kiểm 2.4 cần, theo U1 hẹp mà người dùng cho phép ngày 01/11 (hash, lý do, phản chứng), không nới guard runtime |
| 23 khoảng trống nghiệm thu/pilot/provider của 2.2 | điều kiện ngoài (E) | giữ trạng thái; không là lý do hoãn 2.4 |
| B4/B5: hai test 2.2 đã khóa gọi Claude thật / ghi sổ hook thật khi không cô lập | độc lập | giữ trạng thái; mọi lượt chạy 2.4 cô lập `LOCALAPPDATA`; không chạy `tests.test_v2_reviewer` |
| F4 (id tri thức trùng giữa project), giới hạn P1 POSIX, khe junction init | độc lập, đã ghi ở giới hạn dev10 | không backport; B đọc tri thức qua cùng bộ đọc nên kế thừa giới hạn này, ghi lại ở §9 |
| Test ghim version `tests/test_g1_core.py` chỉ nhận `2.3.0.devN` | dependency trực tiếp (gói 2.4 cần version `2.4.0.devN`) | U1 hẹp trên nhánh 2.4 cho đúng một dòng regex, cùng cơ chế `wfkit/u1` như `U1-20261029-V23-PIN-1` |

## 2. Chiến lược alpha/beta và điều kiện kiểm (chốt trước code)

- **Alpha từng mốc:** mỗi mốc S1, S2, A, B, C có gói thử riêng `2.4.0.devN` dựng bằng `docs/v24/tools/build_milestone.py` (kế thừa 2.3), kiểm từ artifact trong venv/cwd ngoài checkout (bộ kiểm V1–V16 của 2.3 giữ làm hồi quy, thêm bước V17+ của mốc). Alpha nêu giới hạn rõ, không tuyên bố hotfix tự động, không tuyên bố model thật hiểu context.
- **Trước mỗi nhóm thay đổi:** ca lỗi/phản chứng trước (test đỏ trên baseline `fb3333b` khi phản chứng là lỗi hiện có), rồi code, rồi kiểm lại ca đó, rồi module bị ảnh hưởng (danh sách ở §4 từng mốc), rồi tích hợp cần thiết.
- **Không full gate nhiều giờ cho mỗi thay đổi nhỏ.** Gate snapshot 2.2 đầy đủ chạy đúng một lần trên snapshot beta 2.4 (và lại chỉ khi snapshot đổi). Alpha dùng: hồi quy 2.3 (`tests/test_v23_*`, `tests/test_v24_*`) + module 2.2 chạm vùng sửa + kiểm gói.
- **Kế thừa bằng chứng:** chỉ khi commit code, wheel hash, harness và điều kiện giống hệt và được ghi; không chép PASS snapshot cũ cho snapshot mới.
- **Fixture, provider thật, giả định:** worker trong mọi kiểm là `claude` giả (`tests/v23_fake_claude.py`); không gọi provider trả phí; mục cần model thật ghi là chưa chứng minh.
- **Beta 2.4:** chỉ khi cả năm mốc có code tích hợp, test/phản chứng đạt, gói dùng được, hồi quy đủ, gate 2.2 đạt mọi check thực thi trên snapshot cuối.

