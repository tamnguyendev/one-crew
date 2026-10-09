# Proposal Coverage

## Readable review and live functional recovery

Baseline `1e4c33b`; [functional evidence](functional-evidence.json), [gate guide](container-gates.vi.md).

| ID | Requirement | Evidence | Verification | Status |
|---|---|---|---|---|
| RV01 | Human-readable status/output cards with exact revisions, optional diff/evidence and stable JSON | work_view, CLI --full/--json | two real CLI fixture tests; no model calls for display | Complete |
| FG04 | Distinguish container startup errors from product failure and recheck without AI repair | Docker startup state guard, log configuration, work recheck | regression test for logging error; recheck failure/acceptance/budget tests; live recheck zero extra calls | Complete |
| FG03 | Live functional gates and concrete container boundary checks | Docker 28.3.2, pinned official Python image, product tests on snapshot and Git candidate | order quote 5 test methods and CSV regression 4 methods pass; mount/rootfs/network/socket/env assertions; source/index preserved | Complete |

173 tests pass in 71.702 seconds. Three live trials total 7 managed calls: Kiro order 3 (completed after zero-call gate recheck), Kiro CSV 3 (retained as blocked for real Unicode defect), Codex CSV regression 1 (completed; supplied operator plan). Initial infrastructure misclassification and unnecessary repairs remain in evidence. No budget reset: separate regression is explicitly related and aggregate costs include all roots. Acceptance pending. All attempts settled and no gate containers remain. This does not prove eight-hour soak or authenticated entry integration.

## Explicit root budget extensions

Baseline `e94522c`; [guide](budget-extension.vi.md).

| ID | Requirement | Evidence | Verification | Status |
|---|---|---|---|---|
| BU01 | Finite revision-bound local extension with immutable original grant and retained usage | budget.current/extend; ledger/control effective budget; work extend CLI | exhausted root/restart/new dispatch; stale/idempotent/conflicting and concurrent extensions | Complete |
| BU02 | Preserve absolute eight-hour maximum and old/unknown/cancel boundaries | transactional checks, task lock, admission/launch/supervisor effective deadline | strict types/shrink/nine-hour/unknown rejection; failed commit rollback | Complete |
| BU03 | Extension never silently resumes or authorizes an old inbox answer | triage budget revision binding; explicit resume/start; runner resume_phase at expiry | changed-budget race rejected; expired wait resumes only after explicit extension | Complete |

Five budget tests, eight triage tests and three runner tests pass. Final full suite: 168 tests pass in 58.794 seconds. No model calls. Authority remains local operator; authenticated multi-entry grant and live eight-hour soak are still unverified. Budget lineage is append-only; no schema/data rewrite. Prior functional gate contract is committed at `e94522c` with 161 regression tests passing.

## Functional gate contract — isolated container tests

Baseline `2cdc632`; [guide](container-gates.vi.md).

| ID | Requirement | Evidence | Verification | Status |
|---|---|---|---|---|
| FG01 | Operator-sealed functional test command and immutable candidate/image | sandbox_gate.validate/evaluate, workflow and Git-candidate verify | six tests for owned-test rejection, immutable image, candidate-only mount, exit/cleanup, infrastructure failure without model repair | Complete |
| FG02 | Bounded native client, recovery cleanup and explicit unavailable result | Job Object client, deterministic resource marker, preflight before enable | real native timeout and contract cleanup/unknown tests; engine probe fails promptly | Complete |
| FG03 | Live application behavior and sandbox boundary | container configuration and receipts implemented | now verified in the live recovery cycle above after Docker startup | Complete |

FG01/FG02 are contract/client guarantees, not live container evidence. No new model calls. Abrupt controller death can leave a networkless container until recovery cleanup; no reboot cleanup guarantee. Initial broad suite found a transient Windows redirected-handle cleanup error; native client now always waits for exit and fixture uses the existing supervisor suite's bounded cleanup retry. Final full suite: 161 tests pass in 64.052 seconds. Python compilation and Git whitespace checks pass.

## Inbox triage — resume an existing grant from a durable reply

Baseline `3f31689`; [guide](inbox-triage.vi.md).

| ID | Requirement | Evidence | Verification | Status |
|---|---|---|---|---|
| TI01 | Automatically create a short durable blocker question and wait without model calls | triage.ensure_request; runner blocked-state loop; work triage | restart/poll and background-controller reply tests | Complete |
| TI02 | Resume only the same blocker within existing scope, retry cap, budget and deadline | locked fingerprint check, settled-attempt guard, unchanged sealed profile | changed-blocker race, expiry, conflict and budget preservation tests | Complete |
| TI03 | Commit controller effect with resume checkpoint and expose receipt separately from answer | workflow.persist transaction; request show controller_effect | receipt write rollback/retry and stop idempotence tests | Complete |

Full suite: 155 tests passed in 44.575 seconds; final atomic-unpause change additionally passes 7 triage and 15 workflow tests. No live model calls in this cycle. This is local operator triage, not authenticated multi-entry approval or branch-specific continuation. Existing execution authority is reused; no reply expands scope/budget/provider rights. Baseline DAG milestone committed as `3f31689`.

## P3 DAG slice — disjoint parallel units

Baseline `fb98e3a`; [guide](parallel-dag.vi.md), [live trials](parallel-evidence.json).

| ID | Requirement | Evidence | Verification | Status |
|---|---|---|---|---|
| PD01 | Two disjoint ready DAG units share root budget; overlap/dependencies remain ordered | parallel.ready_batch/round; schema-v3 work-unit admission, global capacity | A→(B,C)→D fixture; live Kiro peak_running_attempts=2; overlap test | Complete |
| PD02 | Publish per-unit checkpoints while sibling runs and preserve valid sibling on failure | coordinator-only snapshot merge/persist; independent feedback events | B reviewed before C finishes, invalid B retains C output, cancel waits for both units | Complete |
| PD03 | Atomic dispatch intent and backward-compatible migration preserve budgets/unknown ownership | Control reserve callback, v1/v2 backup to v3, root-owner exclusion | checkpoint failure rolls reservation back; v2 backup and unknown/counter preservation | Complete |
| PD04 | Reuse a supplied approved plan without paying for a new planning call | work plan, revision/phase/scope validators | stale replacement rejected, supplied-plan fixture completes in four calls instead of five; live plan_source recorded | Complete |

DAG tests: five passed in 1.390 seconds. Full suite after parallel prompt/schema repair: 147 tests passed in 42.050 seconds. The subsequent explicit receipt-revalidation fix passes all 15 workflow tests, including its new regression; it avoids another model call after a compatible parser/schema repair. Initial parallel live trial was correctly blocked at two-call cap because both workers exceeded assigned ownership. The repaired regression is a separate recorded trial: two calls, two simultaneous native Kiro attempts, two outputs, verification passed, acceptance pending and original source unchanged. No counter reset on failed task. Remaining P3 work: branch-specific triage/contract invalidation, all parallel crash transitions, integration across repo vectors and functional gates beyond configured JSON/text/syntax checks.

## Routing and review-branch slices

Baseline `94136f9`; [routing guide](routing-policy.vi.md), [review-branch guide](review-branch.vi.md).

| ID | Requirement | Evidence | Verification | Status |
|---|---|---|---|---|
| RP01 | Typed routing recommendation filters rights/capability/risk/complexity and every supplied fresh quota window | routing.choose; provider choose CLI | six tests: tier floor, short/week quota, stale/unknown/reserves, forbidden paid API, strict types | Complete |
| RP02 | Optional AI decision is only a bounded proposal using known actions/evidence | validate_decision | invalid action/evidence/confidence rejected; proposal_only retained | Complete |
| CQ01 | Independent roots share two-worker capacity and queue transient pressure without model calls | Control CapacityWait, Workflow admission wait, runner polling | two occupied slots queue third root with zero calls; releasing reservations lets it complete | Complete |
| IB01 | Build a local review branch from captured dirty baseline without mutating checkout/index | Integration.tree/branch, temporary index, no-filters, disabled hooks/signing | real Git tree/bytes/index preservation and hook denial test | Complete |
| IB02 | Verify actual Git candidate, reject stale source and reconcile lost ref-update ack | inspect_tree/verify, source CAS checks, action broker receipt | gate failure/no branch, existing ref/source change rejected, effect-then-error reconciled | Complete |

Final validation: 140 tests passed in 43.394 seconds on Windows, including routing (6), integration (4), workflow (14), and runner (2). Actual-tree checks and hook denial are included. Git diff whitespace check passed before commit. These slices do not complete OC08/OC10: recommendation is not quota reservation or automatic routing; review branch is not target merge, rebase, multi-repo commit vector or functional application verification. No external model calls in these slices.

## Background controller slice

Baseline `7b14ddc`; [guide](background-runner.vi.md).

| ID | Requirement | Evidence | Verification | Status |
|---|---|---|---|---|
| BG01 | Local controller survives launcher exit, duplicate start does not duplicate worker | runner.start/loop/status, detached native Python, process identity and runner lock | real subprocess launcher exit, duplicate identity, cancel termination | Complete |
| BG02 | User/pause waits do not consume model calls or extend root deadline | checkpoint loop with SQLite-only polling and absolute deadline | paused daemon used_calls=0; virtual clock crosses deadline by 8h, blocks without dispatch | Complete |

Two focused tests pass in 1.284 seconds. Full suite: 129 tests passed in 39.794 seconds on Windows. Not an OS boot service, authenticated messaging connector, automatic triage engine or live eight-hour soak. A blocked workflow still needs policy-compliant resume. Docker Engine remains unavailable to bounded info probes after starting installed Docker Desktop; no product runtime gate claimed from that environment.

## P2 adapter slice — Kiro artifacts and checkpoint handoff

Baseline `8b61305`. [Provider guide](providers.vi.md), [evidence](provider-evidence.json).

| ID | Requirement | Evidence | Verification | Status |
|---|---|---|---|---|
| PA01 | Separate native CLI artifact transports and bounded capability/auth inspection | providers.py, provider doctor, profile provider field | four parser/auth/capability tests; no identity or credentials printed | Complete |
| PA02 | Kiro typed artifact output with empty tools/MCP and terminal receipt | pinned Kiro V2 adapter, agent validate, stream checks | live two-call JSON task; parser fix reuses settled response; credit evidence | Complete |
| PA03 | Explicit revision-bound worker switch at settled checkpoint preserving scope/budget/source | Workflow.switch and CLI, handoff history, snapshot verification | stale/unreconciled rejection tests; Codex→Kiro live handoff, two calls, dirty bytes and deadline preserved | Complete |
| PA04 | Claude subscription worker live execution/authority/cancellation | restricted command and strict parser implemented | contract tests pass; CLI installed but loggedIn=false; requires subscription login | Blocked |

Focused provider tests (4) and workflow tests (13) pass. Full suite: 127 tests passed in 40.681 seconds on Windows. PA completion does not imply all P2 gates: authenticated entry connectors, provider-specific live cancel/host death and every handoff transition still need evidence. General workflow JSON-only limits remain. No automatic paid API fallback or native session transfer.

## P1c/P1d workflow — bounded Codex artifacts and incremental review

Baseline `08bdfb5`. Requirements below cover the small generic workflow, not every P1/P3 acceptance scenario.

| ID | Requirement | Evidence | Verification | Status |
|---|---|---|---|---|
| WF01 | Scope/AC-bound plan and owned artifacts from immutable task spec/profile | workflow.validate_profile/validate_plan/artifacts, dynamic enum schema, local enable | strict schema/scope/cycle tests; two live non-CV JSON task structures | Complete |
| WF02 | Resume acknowledged worker output without replay or budget reset | checkpoint events, stable controller lock, pending attempt receipts | crash after enable, crash after worker receipt, concurrent controller, disk failure tests | Complete |
| WF03 | Bounded repair, no-progress stop and separate verification/acceptance | workflow.run/verify; checks held by controller | parse retry budget, wrong JSON boolean, repair/no-progress tests; live invalid planner rejected then fixed | Complete |
| WF04 | Partial outputs, concurrent feedback, revision-bound review/reorder/export | workflow_cli, snapshot diff, feedback events | checkpoint review/restart, stale acceptance/reorder, dependency ordering, pause/resume; real CLI output card smoke | Complete |

Validation: 121 tests pass in 33.768 seconds on Windows (11 new workflow tests). [User guide](general-workflow.vi.md) and [live evidence](general-workflow-evidence.json). Codex 0.160.0/gpt-6-luna completed localization (4 calls) and routing (3 calls), including the initially invalid planner calls; counters and original deadlines survived resume. All seven attempts have CLI usage evidence: total 44,676 input and 613 output tokens, zero cached input. No user source edits, source integration or user acceptance. CLI command examples checked against parser; output card smoke executed against the real task.

Limitations: these are JSON configuration features with trusted content gates, not general application execution. P1 remains Partial for automatic inbox triage/authority proof, general functional gates, and full recovery transition coverage. P2/P3/P4 remain incomplete. Feedback is durable but does not auto-trigger repair; no daemon installed. Native Claude binary was found outside PATH; no Claude/Kiro worker execution claimed. Docker executable exists, but engine readiness was not confirmed. Snapshot/gate/provider evidence never substitutes for an eight-hour soak.

## P1c foundation — scoped portable snapshots

Baseline `983747a`. Scope is snapshot storage; provider dispatch remains separate.

| ID | Requirement | Evidence | Verification | Status |
|---|---|---|---|---|
| CP01 | Preserve scoped working and Git index bytes without changing source | snapshots.capture/materialize, content-addressed blobs | staged/unstaged/deleted/untracked/binary round trip; index unchanged | Complete |
| CP02 | Reject unsafe scope and corrupt/incomplete checkpoints | scope_list/safe_file, durable_write, load hashes | disk failure, corrupt blob/manifest, source race, path/case collision tests | Complete |
| CP03 | Immutable owned-file candidate and review diff | overlay/diff, fresh-only materialize | scope escape rejected, old revision unchanged, deletion and diff tests | Complete |

Six focused tests passed in 1.031 seconds. No external worker calls. [Limits and usage](snapshots.vi.md): file content/index snapshots, not whole-repo clones; no integration or restored OS executable permissions promised. Runtime checkpoint references still need integration. Snapshot fault evidence contributes to T23/T24; it does not alone complete P1c.

## P1b — durable admission, action receipts and Windows supervision

User requested continuing to completion. Current slice CB01–CB04 implements the local control primitives behind P1b; generic planner/worker delivery remains next. Baseline `f13f2fd`.

| ID | Requirement | Evidence | Verification | Status |
|---|---|---|---|---|
| CB01 | Explicit schema migration preserving v1 records and backup | control.migrate, schema v2, Ledger reads v1/v2 | backup/idempotent migration and legacy ledger tests | Complete |
| CB02 | Atomic reservation, root deadline/counters, generation and global capacity | Control reserve/launched/finish/unknown/cancel | concurrent reservation, restart, exhaustion, stale generation, unknown hold, pending question tests | Complete |
| CB03 | Stop process tree and reconcile before releasing ownership | Supervisor, native Windows Job Object, PID+creation time | real success/timeout/descendant and supervisor-death tests; Store alias rejection | Complete |
| CB04 | Revision-bound action authorization and non-replayed unknown outcome | Control action methods, receipt commit and reconciliation | action effect then exception, strict boolean verifier, stale authorization tests | Complete |

These are internal controller APIs plus core migrate/status/cancel/reconcile CLI, not a completed general worker runtime. Unidentified launches retain ownership/reservation for manual reconciliation; no lease-expiry restart. Native Windows containment is verified with direct native executables, not arbitrary shell launchers, WSL or hostile broker-assisted processes. Microsoft Store aliases/venv redirectors are refused because a real test showed an escaped descendant; using the direct native Python executable passes the descendant test. Job Objects are process containment, not a filesystem/network sandbox. Worker/tool authority isolation remains OC12 work.

Validation: 104 tests passed in 27.408 seconds on Windows, including 16 control/supervisor tests. No model call was made for this cycle. CB01–CB04 completion is limited to these internal primitives; live provider isolation, generic delivery and unidentified-launch recovery remain separate gates.

## P1a — durable local task ledger and inbox

Implementation baseline: `6a49444`; scope from SPEC-006 / backlog P1a, T01/T05/T18 and the persistence/reply subset of T22. User authorized starting the build. This slice records work and local answers; it does not dispatch workers or turn local attribution into trusted execution approval.

| ID | Requirement | Type | Evidence | Verification | Status |
|---|---|---|---|---|---|
| LE01 | Versioned SQLite outside workspaces, atomic mutations/events and crash-safe persistence | Reliability | ledger.py transaction: BEGIN IMMEDIATE, synchronous FULL, application/schema version checks, closed connections | test_failed_event_write_rolls_back_reply, test_failed_initial_commit_can_be_retried, test_process_death_before_commit_preserves_pending_question, test_unknown_schema_is_not_migrated_or_overwritten | Complete |
| LE02 | Submit bound to spec/grant content; duplicate key idempotent, different payload conflicts | API | Ledger.submit stores immutable spec/grant snapshot, full revision and unique per-project caller key | test_submit_retry_is_durable_and_retains_original_deadline, test_submission_key_conflict_and_stale_spec_do_not_add_tasks, test_concurrent_process_submissions_create_one_task_and_event, test_acknowledged_snapshot_survives_deleted_spec | Complete |
| LE03 | Project-scoped queue/status/connect and read-only event polling without model calls | Data | Ledger tasks/task/events; ledger_cli.py; cli.py preserves CV/spec routes; no provider dependency | test_project_isolation_in_shared_database, test_empty_queries_do_not_create_state, test_json_cli_errors_are_structured_and_legacy_spec_still_works, full legacy suite | Complete |
| LE04 | Durable questions, options, action revision and revision history | Functional | create_request/revise_request and transactional event history; pending/answered remain separate from applied | test_pending_reply_and_receipt_survive_fresh_cli_processes, test_revision_binds_action_and_rejects_old_reply, test_create_dedup_and_answered_request_cannot_be_rewritten, test_multiple_pending_questions_keep_task_waiting | Complete |
| LE05 | Atomic reply, duplicate receipt, conflicting reply rejection and explicit local provenance | Reliability | Ledger.reply serializes transitions and receipts; local_attribution_only, action_applied=false, dispatch_enabled=false | test_conflicting_process_replies_have_one_winner, test_duplicate_reply_returns_original_receipt_not_new_provenance, rollback/restart tests | Complete |

Full OC01/OC05 remain incomplete until trusted entry connectors and worker isolation are proven. P1b–P1d, worker execution, process recovery and the remaining roadmap are outside P1a completion.

P1a validation: 19 new tests pass; final `python -X utf8 -m unittest discover -s tests` passes 88 tests in 25.187 seconds on Windows. The first focused run exposed a test-only SQLite connection left open during Windows cleanup; explicit closing fixed it. A PowerShell smoke then exposed default-console encoding on Vietnamese output; the CLI now sets UTF-8 and a launcher regression test passes. Shipped JSON examples passed submit → create question → reconnect → reply → status/events through separate PowerShell processes in an isolated temporary project. Subprocess death test verifies rollback before commit; acknowledged data is read by new CLI processes. No external model/API was called by the new code/tests. Existing runtime tests use their established fixtures; this is not a live multi-provider or 8-hour run. Documentation links/fences/example schemas and Python compilation pass; no separate lint/type-check tool is configured.

LE01–LE05: 5/5 Complete for P1a only. [User guide and example commands](durable-ledger.vi.md). Entry provenance is declarative local attribution, not authentication; schema v1 rejects unknown versions but does not implement upgrade/backup automation. Pending questions are created manually through CLI until the planner/runtime integration exists. No supervisor daemon or worker is running for ledger tasks. Commit subject: `feat(ledger): persist tasks and revision-bound inbox LE01-LE05`.

## Architecture revision 2 — source-informed design, 2026-10-09

User request: update OneCrew architecture using the reviewed upstream designs. Baseline: `9a8e0cf`; scope is documentation, not implementation of SPEC-006. Canonical artifacts: [architecture](architecture.vi.md) sections 12–13, [SPEC-006](../specs/SPEC-006-portable-orchestration.md), [backlog](mvp-backlog.vi.md) and [README](../README.md).

| ID | Requirement | Type | Evidence | Verification | Status |
|---|---|---|---|---|---|
| OA01 | Record lessons and adopt/defer decisions for all nine reviewed repositories | Documentation | Architecture section 12: commit-pinned source matrix, review limits and no implicit framework adoption | Verified nine distinct repositories with full commit-pinned links; each row maps to a contract and planned test | Complete |
| OA02 | Turn lessons into explicit execution contracts while keeping one small core | Architecture | Sections 3–9 and 13: admission, handoff, approval, reservation, checkpoint, integration, schemas and capabilities | Reviewed nine contracts against source findings and OC01–OC12; kept runtime guarantees separate from design | Complete |
| OA03 | Connect design to readable spec and staged acceptance evidence | Documentation | SPEC-006 OC01–OC12 crosswalk, backlog P1a–P1d and T20–T30, README | Spec.parse and CLI brief/full pass; all OC/T IDs mapped; five-document links/fences/UTF-8 and git diff --check pass | Complete |

These OA requirements measure that design update only. At its baseline OC01–OC12 runtime coverage was 0 Complete / 10 Partial / 2 Missing; see P1a above and the updated matrix below for current implementation. T01–T30 describe planned acceptance scenarios, with only the P1a subsets now evidenced. The source review read selected code/test paths and ran three offline Athena probes; it did not execute upstream full suites or prove live cross-provider/8-hour behavior.

Revision 2 supersedes the previous documentation-cycle wording about T01–T19 being the entire matrix; those cases remain and T20–T30 extend them. Existing runtime evidence and historical records below are retained. No spec approval, worker execution, new runtime dependency or paid API request is part of this documentation cycle. Pre-existing working-tree edits are outside its commit.

Documentation coverage: OA01–OA03 = 3/3 Complete. Validation used the existing `.venv` Python, `Spec.parse`, and read-only `python -X utf8 -m onecrew spec review SPEC-006` (brief and `--full`); no runtime source changed, so runtime/upstream suites and live workers were not run for this cycle. Commit subject: `docs(architecture): adopt reviewed orchestration contracts OA01-OA03`; the resulting hash is reported in the delivery message/Git history.

## Portable orchestration architecture — SPEC-006, 2026-10-09

Proposal source: `specs/SPEC-006-portable-orchestration.md`.
Last reviewed implementation: `bf2e673` (runtime), with evidence documentation at `6f6d44a`.
Current implementation: P1a ledger/inbox, P1b control, scoped snapshots and WF01–WF04 generic Codex artifact workflow above. P1a/P1b had no paid worker runs; WF validation adds seven bounded Codex CLI invocations.

The current baseline is [architecture](architecture.vi.md) and [implementation sequence](mvp-backlog.vi.md). It replaces the Kiro Crew-first host exploration and broad DecisionEvaluator-first sequence in the historical 08/10 documents. One independent core owns state, budgets and dispatch; entry connectors and worker adapters are separate; JEV is optional after evidence. Historical R/CN/DF rows below are not the current implementation plan. Existing SPEC-005 and spec-CLI achievements remain valid within their original scope.

| Status | Count |
|---|---:|
| Complete | 0 |
| Partial | 12 |
| Missing | 0 |
| Blocked | 0 |
| Not applicable | 0 |

These counts measure the new SPEC-006 implementation requirements, not documentation completion or regression of the earlier profile. No requirement is Complete merely because its design is written.

| ID | Proposal section | Requirement | Type | Implementation evidence | Test evidence | Status | Notes |
|---|---|---|---|---|---|---|---|
| OC01 | Entry | Portable submit/connect/query | API | ledger.py / ledger_cli.py submit, queue, status, connect and events | P1a T01/T18 subsets via process/concurrency/isolation tests; no live entry connector evidence | Partial | CLI transport works; Claude/Kiro/Codex entry integration remains |
| OC02 | Planning | Spec and real repo to general plan | Functional | workflow.py scope/AC planner and owned artifacts | WF01–WF03 fixtures plus two live JSON tasks | Partial | General application functional gates and automatic ambiguity triage remain |
| OC03 | Core | Durable authority, recovery, one writer | Reliability | Control reservations/receipts, Job supervisor, workflow locks, detached runner | CB01–CB04 / WF02 / BG01; crash and lost-ack tests | Partial | Unidentified launch needs manual reconciliation; full transition coverage remains |
| OC04 | Workers | Replaceable verified adapters | API | Codex/Kiro artifact adapters, Claude transport blocked on login | PA01–PA03 live Kiro and Codex→Kiro checkpoint handoff | Partial | Claude live auth/authority/cancel and mid-write handoff remain |
| OC05 | Inbox | Durable requests and trusted revision replies | Security | ledger.py request create/revise/reply, revision history, transactional local receipts | P1a T05/T22 persistence/conflict subsets pass; trusted caller/worker isolation not proven | Partial | Local attribution only; replies never authorize or apply execution actions |
| OC06 | Memory | Shared decisions/checkpoints/provenance | Data | ledger events, immutable spec/profile, content-addressed working/index snapshots | CP01–CP03 dirty/binary/deletion recovery; live handoff preserves source | Partial | Authenticated entry connectors and full transcript-free continuation proof remain |
| OC07 | DAG | Parallel dependency/ownership scheduling | Architecture | Generic validated DAG, optional two disjoint units per root, two workers globally | WF/CQ01 tests, PD01–PD04 A→(B,C)→D and native parallel Kiro evidence | Partial | Branch-specific triage, descendant invalidation and full parallel crash matrix remain |
| OC08 | Integration | Verified merged result across branches/repos | Testing | Actual Git candidate checks and immutable local review branches | IB01–IB02 Git/dirty index/gate/lost-ref-ack tests | Partial | Target merge/rebase, application gates and multi-repo commit vector remain |
| OC09 | Long jobs | Root budgets, recovery and optional 8h | Reliability | Absolute max-8h grant, durable counters/reservations, background waits | CB02/BG02/CQ01; live handoff preserves deadline/counters | Partial | Live eight-hour soak and authenticated budget extension remain |
| OC10 | Routing | Task/risk/capability plus account quota | Performance | Typed risk/tier/quota recommendation and bounded AI proposal validator | RP01–RP02 multi-window/stale/unknown/type tests | Partial | Automatic quota feeds/reservation, calibrated routing and fallback remain |
| OC11 | Review | Partial review, feedback and reorder | UI | Output cards/diff, concurrent feedback, revision accept/reorder/pause | WF04 checkpoint/stale/feedback tests | Partial | Automatic feedback-to-repair and review alongside same-root parallel workers remain |
| OC12 | Authority | Scope/grant enforcement separate from acceptance | Security | Fixed CV sealed gates and worker artifact validation | SPEC-004 boundary tests/IA04; planned T01/T08/T11/T16/T19 | Partial | Trusted multi-entry caller/worker authority isolation missing |

Historical documentation-only cycle (implementation was authorized by later user requests): updated canonical architecture, readable SPEC-006, four delivery phases and T01–T19 acceptance scenarios; preserved dated architecture/backlog snapshots. Validation for this cycle is spec parsing/brief limit, current CLI read-only smoke, requirement coverage, local links/fences and Git whitespace checks. Runtime tests recorded above belong to prior cycles; they were not rerun as evidence for new runtime capabilities. The new proposal remains unapproved. The review/update task does not authorize implementing the entire new roadmap.

Validation result (2026-10-09): all seven changed/new documentation files pass local link/fence/encoding checks; brief is 233/350 whitespace-delimited words; OC01–OC12 and T01–T19 are present and mapped. Dated snapshots match the pre-edit drafts. `python -X utf8 -m onecrew spec review SPEC-006` (brief and `--full`) and `task run --help` exit 0. Initial strict question-section parsing failed on extra prose after “Không có.”; the proposal format was corrected, without changing the parser. No runtime source or tests changed.

## Incremental autonomy cycle — SPEC-005

Current cycle: IA01–IA05 Complete for the fixed CV/local/Codex profile. [Implementation and evidence](incremental-autonomy.vi.md): 69 tests passed; live run RUN-20261008-232057-1d06d8 delivered from an empty directory in 585.21 seconds, 14 model calls, one autonomous repair, 19 passing HTTP/browser/security checks and an independent review with no findings. All 10 source files match model artifacts; product commit ad3c748. Preview is available through OneCrew CLI. This supersedes the historical SPEC-004 live-delivery blocker below; broader roadmap and external bot-protection efficacy remain unverified.

## JEV credential and connectivity slice — JC01–JC03

The supplied credential is stored outside the repository using Windows current-user DPAPI. `onecrew decision doctor` made one successful synthetic request to TypeSafe: observed model `jev-1.13.0`, 467 ms, 304 input / 21 output tokens. No source/CV data was sent. Full suite: 57 tests passed.

See [connection coverage and guide](jev-connection.vi.md): JC01–JC03 Complete. This only establishes credential/API readiness. Semantic decision integration, shadow evaluation, auto-routing and the SPEC-004 live product delivery blocker remain outstanding; no worker was dispatched by this probe.

## Autonomous runtime cycle — SPEC-004

Controller implementation and requirement-level evidence for AR01–AR08 are maintained in [autonomous coverage](autonomous-coverage.md). Validation: 51 tests pass, including 24 existing spec CLI regressions and 27 runtime checks. Simulated lifecycle tests and actual provider/HTTP evidence are explicitly separated.

The previous "runtime missing" rows below describe the baseline before SPEC-004. The fixed-profile controller, task/risk router, budgets, checkpoint output, cancellation and repair loop now exist; the linked live report governs whether a real product delivery has been demonstrated. Multi-repo, Claude/Kiro adapters, conversation, recovery and reorder remain incomplete. No claim of complete OneCrew roadmap coverage.

Proposal source: `docs/spec-review-cli.vi.md`
Last reviewed implementation commit: `5f439bc27956eca67903a8b877035b24c55f5f84`
Current iteration: 2 (SR02/SR03/SR06 repaired, verified and committed)

Review update: 2026-10-08; overall review reopened SR02/SR03/SR06. Cycle 2 adds regression coverage and repairs only this CLI slice; runtime orchestration is outside the cycle.

Scope of the requirement counts below: the local spec review CLI only. The broader orchestration roadmap remains unimplemented and is summarized separately below.

## Summary

| Status | Count |
|---|---:|
| Complete | 8 |
| Partial | 0 |
| Missing | 0 |
| Blocked | 0 |
| Not applicable | 0 |

## Requirements

| ID | Proposal section | Requirement | Type | Implementation evidence | Test evidence | Status | Notes |
|---|---|---|---|---|---|---|---|
| SR01 | Requirements | One spec, brief and detailed views | Data | `onecrew/specs.py:Spec.parse`; `specs/SPEC-001-duyet-spec.md` | `test_brief_and_full_share_revision_without_creating_state`, `test_invalid_specs_fail_without_state` | Complete | Seven sections, 350-word bound; no silent truncation |
| SR02 | Requirements | List and pending filter with per-spec errors | Functional | `Project.specs` collects file errors; list exposes valid specs and errors, exits 2 when partial | `test_invalid_neighbor_does_not_block_review_or_decision`, `test_mixed_inventory_never_reports_invalid_spec_as_approved`, `test_plain_text_inventory_keeps_valid_and_invalid_entries`, invalid bytes/size test | Complete | Errors remain visible under pending; invalid/duplicate specs cannot appear approved |
| SR03 | Requirements | Brief/full read-only review isolated from unrelated invalid drafts | UI | `Project._spec_paths`, `_unique_path`, `find` read only the requested spec | neighbor isolation, duplicate target refusal, brief/full read-only and invalid bytes/size tests | Complete | Duplicate filename IDs refuse target approval even when one duplicate is incomplete |
| SR04 | Requirements | Approve the viewed content revision | Reliability | `onecrew/specs.py:Project.decide` | stale code, open/resolved questions, idempotency and newline tests | Complete | Local attribution, not authenticated identity |
| SR05 | Requirements | Request changes with comment | Functional | `Project.decide`, append-only decision records | `test_change_request_retains_previous_approval_and_comment`, `test_wrong_code_empty_actor_or_comment_do_not_write` | Complete | Preserve prior decisions |
| SR06 | Requirements | Brief/full diff and history independent of current file validity | Functional | `execute` history reads ledger before any spec lookup; diff remains content-bound | `test_history_survives_malformed_and_missing_current_spec`, `test_history_without_decisions_does_not_create_state`, `test_history_still_rejects_corrupt_ledger`, existing diff tests | Complete | Snapshot history preserved and corrupt ledger still rejected |
| SR07 | Requirements | Invalid input/state and stale revision handling | Reliability | `Spec.parse`, `contained`, `Project._validate`, error exit 2 | invalid/duplicate/unknown spec, corrupt DB/snapshot, path guard, changed scope tests | Complete | No security boundary against same-user worker |
| SR08 | Usage | Windows launcher and working example | Documentation | `onecrew.ps1`, `onecrew_cli.py`, package entry points, README and CLI guide | real module subprocess and PowerShell launcher tests on Unicode/space paths; local launcher smoke | Complete | Standard library only |

## Cycle 1 result

- Implementation commit: `14f22cff2293d4b8e91b6072acff9937d5380c97` — `feat(spec): add local review and approval CLI (SR01-SR08)`.
- At cycle 1, the original coverage recorded 8/8 based on the then-tested cases. The overall review below supersedes that current-completeness claim and clarifies the missing edge cases.
- `python -m unittest discover -s tests -v`: 16 tests passed on Windows/Python 3.13.
- Module and PowerShell entry points exercised; CLI reads the actual example without approving it.
- The first test run found a test-fixture SQLite handle left open during Windows cleanup. The fixture now closes it explicitly; the full suite passed after the repair.
- No configured lint/type-check suite existed. Python import/entry-point tests and TOML/JSON/link validation cover the local packaging/documentation surfaces.
- Broader orchestration, external adapters, authenticated approvals and writer isolation remain outside this slice, not implicitly completed by these tests.
- Pre-existing review/audit documents and tools not changed by this cycle remain outside its Git staging set.

## Overall review findings — 2026-10-08

- Re-ran `python -m unittest discover -s tests -v`: all 16 existing tests passed. This does not cover the two newly reproduced failure scenarios.
- Scenario 1: a valid SPEC-001 plus an unfinished SPEC-002 draft causes `review SPEC-001` to exit 2 because `Project.find` parses all files. The same all-file parse is used by list.
- Scenario 2: approve a valid spec in an isolated fixture, make its current file malformed, then request history. CLI exits 2 even though the ledger still contains the decision.
- These scenarios used temporary test fixtures only. The real sample spec was not approved. Fixes and permanent regression tests were outstanding at review time; cycle 2 below closes them.
- Proposal explicitly requires error isolation for list/review and ledger-based history. SR02/SR03/SR06 were reopened as Partial and are now Complete with the cycle 2 evidence.

## Cycle 2 result

- Implementation commit: `5f439bc27956eca67903a8b877035b24c55f5f84` — `fix(spec): isolate invalid drafts and preserve history (SR02 SR03 SR06)`.
- Scope: SR02/SR03/SR06 only, plus regression verification of the existing CLI requirements. No agent runtime or paid model calls were added.
- Added 8 regression tests. The two original failure scenarios were run against the old code and failed before the implementation change.
- Full suite: `python -X utf8 -m unittest discover -s tests -v` — 24 tests passed on Windows/Python 3.13, including real module and PowerShell launcher entry points.
- Valid entries remain available beside malformed, invalid-encoding or oversized files. Duplicate IDs are isolated and never approved. Partial inventory output returns exit 2 and a structured `errors` array.
- History reads ledger snapshots independently of the current spec file, including after deletion; empty history creates no state. Corrupt database/snapshot is still rejected.
- Documentation and evidence now describe partial-list exit semantics and ledger-only history. JSON/link/fence checks and Git whitespace checks are run before commit; no configured lint/type-check or runtime integration suite exists for this slice.
- The real example remains unapproved. Only isolated test fixtures were approved; fixture cleanup validates Windows target containment.

Verified requirement coverage for the current CLI slice: 8/8 Complete, 0 Partial. This count does not measure overall OneCrew product completion.

| Product capability / references | Status | Evidence or gap |
|---|---|---|
| Local spec review / SR01–SR08 | Complete | Working CLI and 24 passing tests; cycle 2 closes the two review findings |
| Conversation and Conductor / CN01–CN03 | Missing | Architecture/backlog only |
| Enforced scope, budget and dispatch authority / R17, R22, R25, CN04, CN06 | Missing | No controller/worker boundary or live host integration |
| Stop/recover without duplicate work / R04, R16, R19 | Missing | Runtime/adapter not implemented or exercised |
| Evidence-backed delivery and acceptance / R07–R11, R20, CN05 | Missing | No end-to-end delivery run |
| Incremental output review and scoped feedback / R27–R28 | Missing | Checkpoint/revision review, history/diff and dependency handling are specified in architecture/backlog only; no output CLI/runtime or tests yet |
| Reorder pending work with dependency and interruption rules / R29 | Missing | Conductor/CLI move semantics and host plan revision checks specified only; no task queue adapter or reorder command yet |
| Multiple repositories and Claude/Kiro/Codex / R01, R12 | Missing | Product requirement retained; backend contracts not yet demonstrated |

Next sequence after cycle 2: prove one controlled task on one host/backend/repository → connect Conductor from discussion to user acceptance → extend repositories/backends one at a time. DeepSeek, multi-machine registry and dashboard are later work. The old overall 2–4 week estimate is not an active planning baseline. See `docs/mvp-backlog.vi.md`.
