# Chạy công việc theo spec và review từng phần

Đã có luồng Windows/Codex/Kiro: spec đã lưu → profile giới hạn → plan → file artifacts → snapshot từng phần → gate → output chờ review. Hai bài JSON ở [general-workflow-evidence.json](general-workflow-evidence.json); kiểm thử hành vi đơn hàng và nhập CSV trong container ở [functional-evidence.json](functional-evidence.json). Các bằng chứng có phạm vi riêng, không bảo đảm mọi ứng dụng đều chạy được.

## Giao việc

Tạo spec theo mẫu CLI hiện có trong project đích. Profile là hợp đồng của operator: `context` liệt kê file được đọc, `owned` là tập con được sửa, `acceptance` là các tiêu chí, `checks` là kiểm tra do host giữ. `model`, timeout và số lần repair được chốt trước khi chạy. File chưa tồn tại được khai báo trước trong context/owned. Không cho worker tự thêm file ngoài danh sách hoặc tự thay checks.

Ví dụ [profile](../examples/workflow-profile.json) và [grant](../examples/workflow-grant.json) dành cho spec tạo file routing JSON. Sửa nội dung cho khớp spec trước khi submit; không dùng profile mẫu để kiểm chứng một feature khác.

```powershell
# Đặt --project và --state-root trước nhóm lệnh; state phải nằm ngoài project.
.\onecrew.ps1 --project D:\MyProject spec review SPEC-101 --json
.\onecrew.ps1 --project D:\MyProject task submit --spec SPEC-101 --revision <spec-sha256> --request-id routing-v1 --grant .\examples\workflow-grant.json
.\onecrew.ps1 --project D:\MyProject work enable TASK-... --revision <task-sha256> --profile .\examples\workflow-profile.json
.\onecrew.ps1 --project D:\MyProject work run TASK-...
```

Lấy `task-sha256` từ submit/status; khác với hash của spec. `enable` là hành động local operator cấp quyền chạy profile cụ thể theo `artifact.generate`, không tự nâng lời trả lời inbox thành quyền thực thi. Hiện entry CLI dùng quyền tài khoản OS local, chưa là xác thực đa người dùng.

`run` chạy trong terminal cho tới kết thúc, blocker hoặc giới hạn đã cấp. `--steps 1` dừng tại checkpoint kế tiếp, thuận tiện review. Để độc lập với terminal/chat, dùng [work start — controller chạy nền](background-runner.vi.md). Mỗi worker vẫn do supervisor native Windows quản lý; chưa cài Windows service tự restart sau reboot.

## Xem, review và điều chỉnh

`work status` hiện bản ngắn: tiến độ, calls, deadline, việc ready, vấn đề và các revision cần thao tác. `work outputs` hiện từng card có summary/revision/gate/review; thêm `--full` để xem diff/evidence hoặc `--json` cho connector. Không gọi model để tóm tắt lại.

```powershell
.\onecrew.ps1 --project D:\MyProject work status TASK-...
.\onecrew.ps1 --project D:\MyProject work outputs TASK-...
.\onecrew.ps1 --project D:\MyProject work review TASK-... --revision <output-sha256> --decision feedback --comment "Phần A cần đổi nhãn."
.\onecrew.ps1 --project D:\MyProject work pause TASK-...
.\onecrew.ps1 --project D:\MyProject work resume TASK-...
.\onecrew.ps1 --project D:\MyProject work run TASK-...
.\onecrew.ps1 --project D:\MyProject work reorder TASK-... --revision <plan-sha256> --order task-b task-a
.\onecrew.ps1 --project D:\MyProject work review TASK-... --revision <latest-verified-output-sha256> --decision accept --comment "Đã review các checks được cấu hình."
.\onecrew.ps1 --project D:\MyProject work export TASK-... --revision <output-sha256> --to D:\Review\new-directory
```

Output card chứa summary, diff, snapshot, verification, acceptance và backlog. Feedback gắn revision được ghi kể cả khi controller đang chạy phần khác. Muốn giao sửa, dùng [work request-changes](review-corrections.vi.md) ở checkpoint: core giữ scope/caps và đưa feedback vào một repair có giới hạn. Acceptance chỉ nhận snapshot hiện tại đã pass gate. Export tạo thư mục mới; không ghi đè repo nguồn. `reorder` cần toàn bộ ID chưa hoàn thành, chỉ thực hiện giữa checkpoint; dù ưu tiên task phụ thuộc lên đầu, core vẫn chờ dependency.

Pause dừng worker đang chạy và giữ snapshot đã công bố, calls/deadline. Resume là explicit retry có giới hạn: phải biết attempt cũ đã dừng; không tiếp tục kết quả JSON viết dở. Trường hợp launch mất identity vẫn giữ reservation, cần reconcile trước khi có worker mới. Với crash sau khi receipt đã lưu, runtime đọc lại output cũ thay vì gọi model lần nữa.

## Phạm vi gate và giới hạn

Đã thêm [container_test](container-gates.vi.md) cho test chức năng theo snapshot; có live Docker evidence. `work recheck TASK-... --revision <snapshot>` chỉ kiểm lại candidate đã đủ implementation, không gọi model repair. Lỗi hạ tầng không được coi là lỗi code để đốt thêm token.

Gate v1: `json_equal`, `text_equal`, `text_contains`, `python_syntax`, `absent`. Tất cả AC phải có check; kiểu dữ liệu strict, `true` khác `1`. Syntax/text check không chứng minh chương trình chạy đúng. `completed` nghĩa đã hoàn tất pipeline và pass **checks được cấu hình**; acceptance vẫn `pending`. Chưa chạy lệnh test tùy ý do AI cung cấp trên host.

Planner dùng schema enum cho đúng AC/path. JSON/schema sai được sửa trong trần; repair không tiến triển hoặc lặp failure dừng. Out-of-scope output bị từ chối. Cấu hình execution và ngân sách root không được reset bằng enable/retry; deadline tính từ submit, gồm thời gian chờ. `max_calls` giới hạn managed CLI invocations, không phải mọi request nội bộ provider. Usage có nguồn từ event CLI; chưa có bộ routing theo quota subscription.

Adapter pin Codex CLI 0.160.0 trên Windows, read-only và tắt shell/apps/plugins/hooks/multi-agent. CLI chạy ở thư mục IO riêng, context được gửi qua stdin; worker chỉ trả JSON. Code core là bên duy nhất áp dụng bytes vào snapshot. Không cấp ledger/control tool cho model. Phiên bản khác cần kiểm chứng trước khi bật, không tự fallback full-access.

Đã bổ sung Kiro worker/handoff, controller nền, nhánh Git review, branch inbox, amendment và repair theo review; xem các hướng dẫn trong README. DAG hai nhánh độc lập đã có qua parallel=true. Còn thiếu merge vào target, Claude live (chờ login), entry có xác thực, atomic quota reservation/fallback và soak 8 giờ. Codex quota feed chỉ đọc đã có, chưa tự dispatch. Không dùng các trial hiện tại để đánh dấu toàn bộ P1–P4 hoàn tất.
