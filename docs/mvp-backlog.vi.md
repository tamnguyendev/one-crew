# Kế hoạch triển khai OneCrew — 09/10/2026, revision 6

**Bổ sung theo yêu cầu mới:** [SK01–SK04 / MR01–MR03](skills-routing.vi.md) triển khai trước task nghiệm thu tiếp theo: history→recurrence→candidate skill có duyệt, provider preference cho job mới và JEV shadow. Routing calibrated, tự cập nhật skill và những khoảng P0/P1/P2 bên dưới không được coi đã đóng bởi nâng cấp này.

**Thứ tự hiện hành:** [revision 5 — KiroCrew + CAO, mục 8](architecture-kiro-cao.vi.md#8-thứ-tự-triển-khai-và-điều-kiện-nghiệm-thu). P0: runtime tự thực thi trọn task → chống lặp/phục hồi hữu hạn → completion gate → observer/notification không gọi AI lúc idle. P1: entry chung và spike CAO một worker → dependency/integration → routing/lessons được đánh giá. P2: fault matrix và soak dài. [Implementation](revision5-implementation.vi.md) ghi phần đã triển khai, [coverage](proposal-coverage.md) phân biệt từng gate còn thiếu; không tính toàn roadmap đã hoàn tất.

Milestone OE01–OE07 có ba loại task live và giữ evidence cũ. Task lịch sử UI/build sau đó vẫn cần Codex hỗ trợ sửa hạ tầng, nên chưa chứng minh autonomy cho luồng đó. Ưu tiên tiếp theo là đóng P0 trên nền hiện có rồi chạy một task thực tế không hỗ trợ ngoài runtime. Entry không chuẩn bị evidence/plan/adapter riêng cho task. P1–P4 bên dưới giữ contract nền và các năng lực chưa hoàn tất, không phải thứ tự ưu tiên mới.

Đích: giao yêu cầu đã làm rõ từ Codex/Claude/Kiro cho một core local; tiếp tục qua đổi entry/worker, review từng phần và chạy công việc liên quan trong scope/budget. [Kiến trúc](architecture.vi.md) và [SPEC-006](../specs/SPEC-006-portable-orchestration.md) là baseline. [Backlog 08/10](mvp-backlog-2026-10-08.vi.md) giữ lịch sử; không triển khai song song hai roadmap.

Revision 2 chuyển bài học từ chín repo thành contract kiến trúc mục 13 và T20–T30. Revision 5 giữ các contract này, thay thứ tự ưu tiên bằng P0/P1/P2 nêu trên và bổ sung nguồn KiroCrew/CAO cố định. Không cài thêm framework hoặc mở phase riêng cho từng repo.

## 0. Điểm xuất phát và nguyên tắc nghiệm thu

Điểm xuất phát của baseline: CLI spec và runtime CV/Codex, SPEC-005 có live delivery/69 tests. Cập nhật triển khai 09/10: đã có general planner, supervisor/checkpoint recovery, Codex/Kiro handoff, DAG hai worker, branch inbox, amendment, review correction, extension hữu hạn, Docker gates/local review branch và quota Codex chỉ đọc. Coverage/evidence ghi riêng fixture và live. Đã bổ sung target merge mức file, gate bộ commit đa repo, account reservation, ngân sách nhóm và hủy cả nhóm. Authenticated entry, điều phối đa repo động, routing/fallback tự động và soak tám giờ vẫn còn thiếu; JEV chưa semantic routing.

Mỗi mốc cần một kết quả người dùng thử được, code/commit/evidence và giới hạn còn lại; không tính tài liệu kiến trúc là feature hoàn tất. Mốc đang chờ approval chỉ giữ nhánh phụ thuộc. Không kéo thêm dashboard/roles/JEV vào đường găng. Gate phù hợp từng thay đổi; không lặp full suite khi không có thay đổi hoặc nghi vấn mới.

## 1. P1 — Một task tổng quát, lưu bền và tiếp tục được

Phạm vi: nền OC02/OC03/OC05/OC06/OC09/OC12 và CLI contract OC01; một Codex worker tuần tự.

- Xây core local một instance, schema SQLite versioned, event/outbox, task/attempt/grant/request/checkpoint và root counters. Mutation có idempotency/revision checks; query không gọi model.
- Nối profile mới từ spec được giao và repo thực tế sang plan có AC coverage/ownership; hai feature khác profile CV để chứng minh không hardcode.
- Thêm inbox CLI; lỗi kỹ thuật trong scope tự sửa có giới hạn; ambiguity/out-of-scope tạo request ngắn. Core giữ thẩm quyền, workers không được sửa ledger/grant/gate.
- Dispatch intent/lease/process identity, stop/reconcile và checkpoint gồm dirty diff. Resume sau crash giữ budget, không lặp side effect chưa rõ. Đóng chat không dừng core.
- Output card đầu tiên có snapshot/diff/checks/cách thử; chưa cần UI dashboard.

Điều kiện qua mốc: một task có thể dừng chờ câu trả lời, core restart, trả lời qua CLI rồi tiếp tục; một task khác cấu trúc cũng sinh plan đúng repo. Fault tests chứng minh một writer, duplicate/stale event bị chặn, cancel có xác nhận. Không tuyên bố hỗ trợ mọi backend hoặc 8 giờ ở P1.

**Lát code đầu tiên:** task ledger + submit/status/request-reply bằng CLI, một task tuần tự, persistence và revision/idempotency. Sau đó nối Codex và crash reconciliation trên cùng contract. Không bắt đầu bằng thêm evaluator hoặc dashboard.

Chia P1 thành các lát bàn giao, mỗi lát có demo/coverage riêng:

P1a–P1d đã có ledger, budget/action/supervisor, snapshot và [workflow artifact](general-workflow.vi.md). Ngoài hai bài JSON còn có gate ứng dụng Docker và inbox triage. Trusted entry authority và đầy đủ recovery transitions chưa đạt toàn bộ chuẩn; xem coverage. Các điều kiện dưới đây vẫn là chuẩn nghiệm thu, không tự coi cả mốc đã xong.

| Lát | Kết quả thử được | Gate trước khi sang lát sau |
|---|---|---|
| P1a | Submit/status/inbox/reply CLI trên ledger bền vững, chưa chạy worker | T01/T05/T18 và phần core/inbox của T22: idempotency, revision, durable pending/reply, restart |
| P1b | Admission + budget/action broker và supervisor qua fake adapter có fault injection | T03/T04/T14/T20/T25: không vượt managed-call cap, không dispatch lại effect unknown, một owner |
| P1c | Một Codex worker artifact mode, snapshot giữ dirty bytes, pause/recovery có bằng chứng | T08/T23/T24/T27/T30; runtime/process tests riêng với fake; checkpoint failure không completed |
| P1d | Spec-to-plan tổng quát và output card đầu tiên, bounded repair | T02/T19/T28/T29: hai feature khác CV, schema strict, no-progress dừng đúng |

CLI các lát sau P1a vẫn ghi là đề xuất. P1a không tự tuyên bố trusted multi-entry approval; boundary thực cần P1c/P2. P1 kết thúc khi tất cả gate của P1 đạt, không coi fake adapter là bằng chứng live Codex.

## 2. P2 — Giao và tiếp tục việc từ ba công cụ

Phụ thuộc P1 đạt; hoàn thiện OC01/OC04/OC05/OC06 và ranh giới OC12.

- Thin connector/skill/agent configuration cho entry Codex, Claude, Kiro; CLI chung trước. MCP chỉ thêm nếu host cần. Ghi rõ entry nào/phiên bản nào đã kiểm chứng.
- Worker adapters Codex, Claude Code, Kiro CLI; capability registry có version, account/auth mode, cancel/reconcile và usage source. Không giả native session chuyển qua provider khác.
- Handoff entry Kiro→Claude cùng task/request; không restart worker. Handoff worker qua stop/reconcile/snapshot với budget giữ nguyên.
- Caller provenance/capability, trusted reply path; không chuyển local spec approval thành authenticated grant bằng nhãn actor.
- Handoff state machine từ admitted tới completed, recovery tại từng transition, CAS ownership; target chưa rõ trạng thái phải reconcile trước fallback về source. Kiểm T21/T22/T27 trên tổ hợp OS/CLI/auth thực; native Windows và WSL ghi evidence riêng.

Điều kiện qua mốc: từng entry submit/connect/query/reply thật; từng worker chạy, verify và cancel thật; ít nhất một cross-provider handoff. Thiếu auth/capability ghi Blocked cho adapter liên quan, không gọi fixture là integration live. Chứng minh worker không thể giả reply qua đường điều khiển được cấp.

## 3. P3 — Hai việc song song, review và ghép kết quả

Phụ thuộc core/authority/recovery P1; dùng adapters đã đạt P2. Hoàn thiện OC07/OC08/OC11.

- Hai worker toàn core, DAG/ownership/worktree; contract trước, overlap tuần tự. Capacity và reservation kiểm cả nhiều root.
- Integration owner ghép tuần tự, gate bản ghép và commit vector đa repo; bảo toàn phần sửa của người dùng.
- Snapshot review/feedback/accept riêng theo revision, human gates đã thỏa thuận; việc độc lập tiếp tục.
- Reorder việc chờ không bypass dependency; pause/resume rõ ràng cho việc đang chạy. Contract đổi chỉ invalidate nhánh liên quan.
- Integration test chạy đúng candidate trước cập nhật target; missing worktree không fallback sang repo chính, base đổi phải ghép/verify lại. Evidence bind source/gate/environment; thêm T26.

Điều kiện qua mốc: A→(B,C)→D, xem/review B khi C chạy, reorder queued tasks; duplicate/stale reports và conflict integration không làm sai trạng thái. Test fail bản ghép phải dừng delivery dù nhánh riêng pass.

## 4. P4 — Tối ưu quota và kiểm chứng công việc dài

Phụ thuộc P1–P3; hoàn thiện OC09/OC10.

- Policy theo task/risk/capability rồi quota, nhiều windows, freshness, reserve cho chat/review, đồng bộ usage có dedup.
- Chuyển provider ở checkpoint khi được phép; fallback/escalation có trần root, không ping-pong hoặc tự chuyển paid API.
- Trần tùy chọn tới 8 giờ, deadline tuyệt đối gồm waits; hiển thị active/queue/user/quota time. Extension rõ ràng giữ used counters.
- Fault injection dùng clock giả trước; soak run live có mục tiêu/giới hạn được cấp riêng, báo thời gian thật và usage, không gọi model 8 giờ chỉ để tiêu thời gian.
- Đo tổng usage đến kết quả đạt, tỷ lệ AC đạt, latency và can thiệp theo loại việc. JEV chỉ vào shadow benchmark nếu rule baseline cho thấy cần semantic classifier.

Bổ sung từ trao đổi 09/10/2026, triển khai theo contract kiến trúc 9.1–9.3 và LR01–LR05 của SPEC-006:

1. LR01: chuẩn hóa hồ sơ task/route/outcome theo revision, bao gồm fail/unknown và toàn bộ chi phí; tận dụng ledger hiện có.
2. LR03: outcome evaluator bằng code và phân loại nguyên nhân có evidence; AI chỉ cho ca cần ngữ nghĩa, không thêm một lượt tổng kết mặc định cho mọi task.
3. LR02: knowledge project và lessons có provenance/lifecycle/context budget; Markdown cho người đọc, SQLite cho tra cứu. Có dữ liệu nguồn mới promote bài học.
4. LR04: bộ task benchmark có version/tập kiểm chứng riêng, thống kê theo loại việc/cấu hình, policy revision và rollback; chưa đủ mẫu thì báo chưa đủ bằng chứng.
5. LR05: reuse script/template/kết quả còn hợp lệ, sau đó thử JEV ở chế độ chỉ ghi đề xuất nếu cần. Auto-routing chỉ dùng policy đã qua tiêu chí chất lượng/risk/chi phí và có quyền áp dụng.

Không mở thêm dashboard/vector DB/framework, không tự fine-tune, không sửa gate để cải thiện điểm. Bộ thử nghiệm có ngân sách giới hạn riêng; không nhân chi phí bằng cách cho mọi model làm mọi task. Các lát này chưa được triển khai đầy đủ; status nằm trong coverage.

Điều kiện qua mốc: các tình huống deadline/restart/quota trong ma trận đạt; soak live có evidence riêng. Chưa có soak thì ghi chưa kiểm chứng vận hành dài, dù virtual-clock tests đạt. Không cam kết mọi feature xong trong 8 giờ hoặc chạy khi máy sleep.

## 5. Ma trận nghiệm thu

Các ca dưới đây là kế hoạch test, chưa phải kết quả đã pass. Dùng fixture cho lỗi khó tái hiện; ghi riêng live capability/authority evidence.

| Ca | Tình huống và kết quả bắt buộc | Yêu cầu | Mốc |
|---|---|---|---|
| T01 | Submit lặp cùng request/spec tạo đúng một root; spec đổi không dùng approval cũ | OC01, OC02, OC12 | P1/P2 |
| T02 | Hai feature khác CV đọc source và tạo plan phù hợp, AC đầy đủ, non-goals giữ nguyên | OC02 | P1 |
| T03 | Crash trước/sau launch, sau write trước ack: reconcile, không hai writer/side effect lặp | OC03, OC06 | P1 |
| T04 | Worker treo; status/cancel không gọi LLM, cancel chỉ confirmed khi đã dừng | OC03, OC04 | P1/P2 |
| T05 | Pending request sống qua restart; duplicate/stale/conflicting reply xử lý đúng; silence không approve | OC05, OC12 | P1/P2 |
| T06 | Kiro entry hết usage, Claude connect cùng ID, trả lời request; worker không bị restart | OC01, OC05, OC06 | P2 |
| T07 | Worker hết usage: old writer dừng, dirty diff giữ, adapter mới tiếp tục cùng budget | OC03, OC04, OC06, OC09 | P2 |
| T08 | Worker giả actor/approval hoặc sửa grant/gate bị boundary thực chặn | OC05, OC12 | P1/P2 |
| T09 | A→(B,C)→D; nhiều root không vượt 2 workers; overlap/cycle không dispatch sai | OC07, OC09 | P3 |
| T10 | Contract đổi chỉ stale descendants; report cũ không hoàn thành task mới/reopen canceled | OC03, OC07, OC11 | P3 |
| T11 | Nhánh riêng pass, bản ghép fail/conflict: không delivery; bảo toàn dirty user work | OC08, OC12 | P3 |
| T12 | Review B khi C chạy; feedback có revision; stale accept/move bị từ chối | OC05, OC11 | P3 |
| T13 | Reorder không bypass dependencies/interrupt/reset; pause/resume giữ checkpoint | OC07, OC09, OC11 | P3 |
| T14 | Restart/handoff/subtask giữ counters/deadline; grant extension giữ đã tiêu | OC03, OC09 | P1/P4 |
| T15 | Quota unknown/stale, ngắn còn nhưng tuần hết; reserve khi parallel; usage cumulative dedup | OC09, OC10 | P4 |
| T16 | Model ít rủi ro tiết kiệm, risk floor giữ; fallback bounded, không tự dùng paid API | OC10, OC12 | P4 |
| T17 | Fault clock + soak thật riêng: deadline chặn call mới, waits không tự kéo dài | OC09 | P4 |
| T18 | Read-only query không model call; đổi project không lẫn memory; stale facts hiện rõ | OC01, OC06, OC10 | P1/P2 |
| T19 | Sửa trong scope tự làm; phát sinh ngoài scope tạo request/backlog; pass khác acceptance | OC02, OC05, OC12 | P1/P3 |
| T20 | Budget=1 gồm intake/planner/reviewer: chỉ một managed invocation; concurrent reserve không vượt cap; timeout unknown không hoàn quota; extension hữu hạn giữ used | OC03, OC07, OC09, OC10 | P1/P3/P4 |
| T21 | Crash từng transition handoff, source stop chưa rõ, target launch mất ack, PID reuse và hai switch đồng thời: chưa xác nhận dừng thì không writer mới; không rollback gây hai writer | OC03, OC04, OC06, OC07 | P2 |
| T22 | Kill cả core/runner rồi restore inbox; hai entry reply trái nhau chỉ một áp dụng; action hash/grant đổi làm approval stale; giả actor không có quyền bị chặn | OC01, OC05, OC12 | P1/P2 |
| T23 | Disk/DB lỗi, crash giữa blob/manifest/reference: không completed hoặc advance durable; hash mismatch bị từ chối; bảo toàn workspace | OC03, OC06, OC09 | P1 |
| T24 | Restore staged/unstaged/deleted/untracked/binary thuộc scope ra snapshot mới đúng bytes/hash; không tự lấy secret/ngoài scope; checkpoint thiếu dữ liệu báo không portable | OC04, OC06 | P1/P2 |
| T25 | Side effect đã xảy ra nhưng receipt chưa lưu: recovery unknown và reconcile/idempotency; không replay mù; duplicate receipt không tính budget hai lần | OC03, OC06, OC09, OC12 | P1 |
| T26 | Thiếu worktree không chạy test repo chính; đúng source nhưng base target đổi làm stale; chỉ candidate đã verify mới cập nhật target; nhiều repo có commit vector | OC08, OC11, OC12 | P3 |
| T27 | Capability thiếu hoặc CLI/OS đổi không quảng cáo hỗ trợ; Windows/WSL identity riêng; không tự full-access; internal CLI-call cap không enforce phải hiển thị giới hạn | OC04, OC09, OC10, OC12 | P1/P2/P4 |
| T28 | Reviewer/evaluator trả chuỗi false, enum sai, thiếu field/evidence, timeout: invalid/unknown, không pass; retry parse tính root budget | OC02, OC10, OC12 | P1/P4 |
| T29 | Repair không đổi source, failure fingerprint lặp, đổi provider không có AC tiến triển: dừng theo policy; output/status nêu lý do và không gọi model để poll | OC02, OC09, OC11, OC12 | P1/P4 |
| T30 | Migration/backup-restore giữ ID/hash/approval provenance/root counters; in-flight unknown vẫn reconcile; snapshot còn reference không bị cleanup | OC03, OC06, OC09, OC12 | P1 |
| T31 | Decision/outcome gắn task/source/policy/model/tools revision; duplicate/restart không nhân usage; giữ fail/cancel/unknown và internal turns riêng | LR01, OC09, OC10 | P4 |
| T32 | Knowledge/lesson đúng project và context budget; nguồn đổi thành stale; AI self-report không thành verified, credential không thành memory | LR02, OC06, OC12 | P4 |
| T33 | AC/test/acceptance tách biệt; lỗi môi trường/thiếu context không tự quy lỗi model; unknown giữ unknown; không gọi evaluator AI khi rule đủ | LR03, OC02, OC10 | P4 |
| T34 | Benchmark cùng điều kiện, tập kiểm chứng riêng; mẫu ít không chứng minh model thắng; chất lượng/risk regression chặn promotion, rollback giữ history/grant | LR04, OC10, OC12 | P4 |
| T35 | Reuse đúng input/source/contract/tools revision; stale phải kiểm lại; JEV proposal không dispatch và chi phí đánh giá nằm trong budget | LR05, OC06, OC09, OC10 | P4 |

T20–T30 xuất phát từ contract mục 13 của kiến trúc, không phải kết quả test upstream hoặc test OneCrew đã chạy. Case nhiều mốc phải tách evidence fixture/live theo capability thực; mọi acceptance ID ở đây cần được link tới test cụ thể khi implement.

T31–T35 bổ sung cho vòng học từ kết quả ở mục 9.1–9.3, mới là tiêu chí nghiệm thu dự kiến. Việc ghi các ca này không có nghĩa đã chạy hoặc đạt test.

## 6. Migration và giao hàng

Giữ nhóm lệnh spec và task hiện có. Profile CV giữ làm regression, không đổi hash/evidence run cũ. General profile có version riêng. Migration DB có backup/schema version, không tự coi attempt đang chạy là đã dừng hoặc tạo writer mới. Local approval cũ giữ provenance/giới hạn; chỉ cấp quyền mới khi đủ nguồn và authority, không tự nâng cấp bằng cách copy record.

Lát migration chạy thử trên bản sao trước, restore kiểm hash/reference/counters; không convert live in-flight record sang queued. Capability chưa chứng minh thì giữ adapter disabled/limited. Rollback schema phải nêu version tương thích và bảo toàn ledger, không drop history để ứng dụng khởi động được. Không cleanup dirty worktree khi stop chưa confirmed.

Mỗi mốc cập nhật coverage bằng code + test/evidence, rồi commit phạm vi đó. Không approve SPEC-006 hay chạy workers trong lượt chỉ cập nhật kiến trúc. Run live cần giới hạn rõ, dùng lại quyền đã cấp nếu còn phù hợp; không hỏi lại từng lựa chọn kỹ thuật. Không ghi API keys vào spec, logs hoặc Git.

Chưa nằm trong P1–P4: dashboard/chat app, distributed/multi-user, vector DB, marketplace, Kiro Crew host bắt buộc, Antigravity/DeepSeek adapter chưa kiểm chứng, JEV trên mọi bước, production deploy. Các tài liệu review lịch sử vẫn dùng làm dữ liệu tham khảo, không tự sinh thêm scope.
