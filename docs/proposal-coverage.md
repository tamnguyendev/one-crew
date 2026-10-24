# Proposal Coverage

## WF development — Codex integration, 2026-10-24

Source: `outputs/onecrew-as-qc/workflow-chung/00` through `06` in the parent workspace;
task IDs and deferred boundaries remain those of `docs/wf/FEATURE-SCOPE.md`.
Baseline `d3120c6`; isolated branch `codex/wf-development`, worktree `wf-codex`.
The user authorized direct development and parallel model-specific work. No live
ledger approval, acceptance, deployment, provider switch or old-job restart is part of this run.

| ID | Requirement | Implementation evidence | Test evidence | Status | Remaining |
|---|---|---|---|---|---|
| W23c core extraction | Reuse the v1 evidence classifications in the wheel | `evaluation_core`, imported by v1 `eval_observe` and `eval_scorecard`; exact function-body extraction | Five scorecard tests before and after; shared-function identity tests | Complete | W23c runtime report and installation validation tracked separately |
| W30a, W47 | Shared decision cards and sufficient proposals | Reused `e1b906b`, `5ecc038` as `ed91471`, `a9e54a5` | R01 card/proposal/compat tests in integration run | Partial | Recheck combined artifact and installed wheel; other R01 features remain |
| W09/T31 | Keep Git evidence through GC; owner-scoped cleanup | `v2/retention.py`, approval/receipt/verdict/accept wiring, CLI and hook | 10 real-Git unit tests; 14 integration tests; missing-pin wiring mutant rejected | Partial | Final namespace-aware regression and wheel; opaque manual artifact hashes remain blob evidence, historical refs are not backfilled |
| W17 | One finding lifecycle shared with v1 | `finding_core`, v1 `review_evidence`, v2 `findings`; transactional runtime hook and immutable capability opt-in | 21 reviewer/register tests; v1 register 26 before +26 after; 4 adapter finding tests; 5 reviewer regressions | Partial | Final integrated installation check; generic passes never implicitly close a finding |
| W38d/T45d/T55 | Compute KQ1–KQ7 from evidence and actual wheel changes | `wfkit/finalgate.py`, shared `dependency_core` extracted from v1 amendment; commit `53e07f1` | 42 pinned-fixture validator tests, 2 focused identity regressions, 5 v1 amendment tests | Partial | Full release/pilot bundles remain to be produced; no real pilot claim |
| W02 | Enforce root authority and reuse v1 authority fields | Reused `baf85c2` and hardened in `038a0b3` | 20 authority tests including actual gate/enforce counterexamples; installed module boundary passes | Complete | Root writer/budget/plan engine is separate work, not implied by this grant check |
| W11b/W12b | Explicit capabilities, per-project namespaces, legacy selectors | `namespaces`, sealed `plan_binding`, gate/intake; default schema2 retains old semantics | 9 namespace +7 binding tests; default schema2 vs explicit finding workflow regression; hook namespace regression | Partial | One-writer and solution linkage remain separate unfinished W12b portions |
| RP identity | An unreadable CLI executable cannot be claimed verified | `providers.cli_identity`: explicit missing hash and identity_errors; `230089a` | 2 targeted Windows identity tests; finalgate rejects incomplete CLI identity | Complete | No real provider capability claimed |
| W26 | Rule-based optional review decisions | `review_policy`, approved optional policy, shared `routing.validate_decision`, CLI | 11 tests: four outcomes, mandatory milestone, cache input/revision/artifact, race, no request/model call | Partial | Engine consumer remains; this API alone does not execute, skip a mandatory gate, or grant authority |
| W23a/W23d | Present/handover by acceptance, open findings visible | Stable hash snapshot from Claude R01 report, namespace and register integration | 40 combined report/compat/policy tests passed; repair-first installed tests passed; open finding stays visible after pass | Partial | Installed Git and non-Git present paths passed; full release fixtures remain |
| W31a | Bounded discovery with scoped unknowns | Reuse Claude survey snapshot, shared step0, bounded read-only context | 72 T27/L3/proposal/closure tests plus 2 focused hardening tests passed | Partial | Actual executor adapter invocation remains; no live model or OS process containment claimed |
| W46b | Namespace-aware rollback diagnostics | `compat_scan` / `compat_cli`; required class-0 field types, old-validator contract support | 17 namespace/legacy cases plus 8 type prerequisite tests; actual archived d3120c6 comparator | Partial | Full installed upgrade/rollback exercise still pending; source ledgers untouched |
| W10 | Root budget survives keys/retries/revisions/restarts | Existing budget.group + Control counters, sealed memberships, approval hook | 9 root cases +2 reservation/cap checks +10 v1 goal tests; two bypass mutants detected | Partial | Engine integration and final wheel still pending; unknown reservation never refunded |
| W44/W33a | Sourced verifier running/ended/lost observations | Reused R03a snapshot; run_started/run_abandoned; capability-driven observations | 34 initial tests; 7 focused interface/read-only repairs; 4 cross-feature regressions | Partial | Managed control/pause/recovery is W33b, not claimed by observation adapter |
| W23c runtime | Separate wait/execution/owner evidence metrics | Installed shared v1 evaluation_core; readonly plan-metrics | 20 source/preservation tests passed; stale-artifact and overlapping-wait regressions | Partial | Installed workflow path passed with module boundary; unknown data is never inferred as zero |
| W30b | Owner-only request answer in wheel | `questions`, owner answer routing, same v1 Ledger.reply | 4 API tests + actual CLI owner/AI and hash revision test | Partial | Installed CLI and notification-card integration pending; no root transition claimed |
| W32a | Immutable baseline, sourced forecast and additional work | `estimates`, approval/CLI/report; mandatory-only additions, unknown observations | 5 core tests, 9 combined estimate/question tests, report range/reason/read-only test | Partial | Automatic task-progress reforecast and U2 branch holds require engine; no calibrated ETA claim |
| W22/W39 | Same verifier lifecycle for docs/data/operations evidence | Stable RX1 snapshot hardened; port/artifact/data/ops; shared finding proof | RX1 75 initial +4 repair tests; RX2 10+large-write, Git/non-Git lifecycle; generic adapter finding4 | Partial | Installed Git workflow passed; actual non-Git approval initially failed, explicit snapshot target fixed and installed retry passed; bounded local evidence only |
| W23b/W48 | Outcomes/context/resume shared with v1 | Stable R02 snapshot; outcome_core, historical replay, contract_diff | 57 R02 cases accounted after focused fixture/help repairs; v1 learning 3 before +3 after; installed workflow cross-feature case passed | Partial | Terminal-gap replay and installed workflow path verified; full release rollback drills remain |
| WF remainder | All other agreed feature IDs | Existing source inventory in FEATURE-SCOPE; concurrent source branches are not evidence of completion here | No combined final-artifact evidence yet | Missing | Continue development/integration; do not call this roadmap complete |
| PL-A/PL-B real pilot | Actual user jobs and final human acceptance | Development tooling only | Simulated fixtures explicitly labeled | Blocked | Requires actual selected jobs and owner acceptance, outside this development run |
| RD/RR/RL/Digital Twin | Deferred roadmap programs | Existing roadmap boundary | Not in WF development scope | Not applicable | No opportunistic expansion |

Workflow/model split: Sol implements bounded modules and tests; Astra examines
cross-cutting authority/evidence invariants and repairs demonstrated failures;
parent integrates shared files and runs cross-module/installed-package checks.
Three agents maximum in this session. Test providers are fakes; model names in
fixture receipts are not evidence of real provider support. Original v1 and active
Claude worktrees remain unchanged.

Combined package checkpoint: 39 G1/routing/install-boundary tests passed, including
an offline temporary venv and actual installed CLI. These describe that tested
snapshot, not future edits. The first long quiet mixed-source test batch was
cancelled while implementation changed; it is not counted as a pass. Later tests
use verbose output and bounded diagnostic tracebacks. Namespace changes intentionally
update fresh-root fixture paths; historical R00 duplicate-name refusal is still
tested using unmodified `d3120c6`, not removed or weakened.

Foundation integration checkpoint: 51 existing v2 core/event-class tests passed (174.429s) after the shared hooks; 5 isolated-module closure tests passed. Offline wheel tests executed both the Git workflow and non-Git data lifecycle with install-boundary validation. The first non-Git install test exposed a real approval gap; explicit `target.ref=snapshot` was implemented, then that failing case passed from a rebuilt wheel. No actual ledger was approved or accepted.

### WF cycle 2 — runtime connections, evidence and learning

| IDs | Implementation and verification | Status | Remaining |
|---|---|---|---|
| W04/W06/W14a/W21 | Internal revisions preserve root contract and acceptance; shared v1 `ready_batch`, node state helpers and Control admission; one slot, dependency states, bounded advance and integration checks. Native checkout executor pins provider/model per node, reuses provider workers and scoped snapshot artifacts. Engine9/native6/owner-answer4 passed together, including closing a root during execution and retaining but not publishing its late result. | Partial | Candidate-aware configured checker, authorized CAS handoff, connected CLI and whole-root delivery still required; callback checks and fake provider tests do not prove live provider support. |
| W24/W24b | Shared v1 notification/outbox/window/locking cores, current-state projection, question revision deduplication and forecast exceptions. V1 24 before and25 after; shared-hook44; offline wheel pull/replay/ACK/owner-answer/fake-window lifecycle passed30.304s. | Partial | Actual user display/delivery is not exercised; remaining integrated release and rollback drills. |
| W30c | Real recorded owner answer drives idempotent close or resumes exact held generations inside the existing grant; stale revisions and unknown attempts cannot resume. Ten original answer/question cases; four workflow cases; actual archived d3120c6 comparator; installed stop/progress passed20.281s. | Partial | Finding/repair/unknown lifecycle integration remains; no answer increases grants or accepts results. |
| W07/W08 | Verifier receipts bind observed input, acceptance, configuration and environment; precise stale reasons; explicit neutral-scope reuse has an atomic persisted basis. Twelve source cases plus nonGit corruption counterexample; offline installed input-change/stale/rerun/corrupt-retention case passed18.915s. | Partial | Environment fingerprint covers observed interpreter/platform and effective env hashes, not every OS library; whole engine candidate and release coverage remains. |
| W51/W20 shared cores | Extracted the exact v1 progress/recovery decisions; v1 imports the shared implementation. Twenty progress cases before/after; nine new progress cases plus recovery identity; sixteen executor regression cases. Durable observation distinguishes wait/unknown, command output liveness and bounded repeated hypotheses. | Partial | Repair/replan consumer and managed process pause/recovery still required; a diagnostic observation itself cannot control an external worker. |
| W49a/W49b | Authentic fail/environment/fix/pass receipts create one incident and a project lesson before root completion; refuted hypotheses stay separate from cause. Four whole-flow cases, v1 learning3 and actual1b4f4c6 neutral-event comparator pass. Offline wheel automatic repair→lesson→CLI read passed48.592s with clean module boundary. | Partial | Remaining release checks; no automatic global promotion, policy injection or finding closure. |

Integrated cycle check: 55 answer/progress/engine/native/G1 tests passed111.003s.
The later closed-root publication fence passed the targeted19-case integration.
These counts overlap; they are not an aggregate completion percentage. Code in
this checkpoint reuses the v1 cores instead of introducing parallel stores or
dispatch schedulers. New source modules and adapter fixtures do not certify the
unimplemented remainder or external provider cells.

## Windows completion/blocker window — 2026-10-10

Proposal source: user requests one result on completion/blocker without recurring scheduler; user selected the Windows OneCrew window. Baseline: 392ca42. Cycle DN01–DN05. Contract: docs/desktop-notifications.vi.md.

| ID | Requirement | Type | Implementation evidence | Test/verification evidence | Status | Notes |
|---|---|---|---|---|---|---|
| DN01 | Runtime emits one window per actionable outcome, no AI/scheduler | Functional | desktop_notifications; delivery hook; Owned and legacy workflow checkpoints | complete/dedup/restart/concurrent claim, block/resume/complete, running/disabled silence | Complete | Checkpoint workflows; same pending question is one outcome |
| DN02 | Durable outbox independent of full state disk, honest recovery | Reliability | D outbox, atomic records, per-outcome claim/UI locks, pending/uncertain/retry | sink disk failure, outbox failure, launch/UI failure, explicit retry, stale outcome suppression | Complete | Ambiguous crashes never auto-replay; next event or explicit retry recovers known failure |
| DN03 | Report current evidence and questions without answering or executing content | Security | read-only latest checkpoint/questions, filtered plain text, report button | REQ/CREQ revisions stay pending, secrets filtered, close does not mutate execution | Complete | Worker claims are separate from independent verification; no widget/device/server inference |
| DN04 | Actual window receipt and no duplicate on this machine | UI | desktop_window Tk Map receipt, Windows visible window handle | Live notice 84c92ce5ec4abfc5238bf3da5e08ef20 shown 09:05:22Z; PID 42052; HWND 34873020; second show launched=[] | Complete | Mapping is not proof of attention; no chat callback |
| DN05 | Replace active notification channel and leave old schedule off | Deployment | configured real state-root since event 970; AGENTS/docs override | automation.toml status PAUSED; real blocked task shown once from checkpoint 967 | Complete | No task resume, disk cleanup, approval or budget change |

Summary: 5 Complete, 0 Partial/Missing/Blocked for the selected notification implementation. The separate Cloud Auth task remains blocked on disk space and a pending CREQ; this feature does not claim its completion.

## Native timeout continuation — 2026-10-10

Proposal: user requests recovery of 600-second timeout within the existing root grant, then runtime-owned execution through handoff/notification. Baseline b3bf5c8; cycle TC01–TC04. Contract: docs/native-timeout-continuation.vi.md.

| ID | Requirement | Evidence | Status | Boundary |
|---|---|---|---|---|
| TC01 | Persist settled timeout and resume same session/workspace exactly once | checkpoint_timeout; immediate exception and restart regression; preserved used_calls/grant and fresh scoped test command | Complete | Workspace Claude only; no replay of terminal results or unknown live processes |
| TC02 | Keep grant, scope, approval and progress constraints | 14 timeout regressions including budget exhaustion, pending decision/guard, session mismatch, unowned/drift changes, duplicate source/test progress | Complete | No automatic budget/deadline increase; same/cyclic checkpoint blocks |
| TC03 | Independent verification/review/apply and readable handoff remain required | Timeout-to-apply fixture; 89 existing handoff/workflow/owned/native/workspace/watch/receipt/MCP tests pass; 14 timeout tests pass after correcting test setup ordering | Complete | Model/gate/host receipts simulated; no product tests run by entry |
| TC04 | Real resumed task completes and scheduled receipt confirms delivery | On 019af9e, same task resumed at 2026-10-10T08:35:41Z, runner 26164 alive; one durable timeout checkpoint, same session 498574f1-5f4b-4349-baaa-82684a9149e9 and second paid attempt ATT-d895e167675d400695345a9ed1399bae running. Root grant/deadline unchanged; bounded receipt automation ACTIVE | Partial | Real outcome pending; explicitly assisted trial, not unseen-task or device/server evidence |

The earlier HO04 fresh trial stopped at a 600-second invocation timeout. Its failure notification was delivered, receipt confirmed, cursor ACKed through 949 and the idle schedule paused. This repair resumes that task without erasing the failure or resetting its grant.

## Owned handoff compatibility — 2026-10-10

Proposal: user requests fixing backlog KeyError, reporting the result and validating the complete execution-to-notification flow. Baseline ef54ea7; cycle HO01–HO04. Preserve existing task evidence and pending delivery; never count a manual status message as scheduled delivery.

| ID | Requirement | Evidence | Status | Boundary |
|---|---|---|---|---|
| HO01 | Read owned outputs through work/job/MCP without legacy schema assumptions | Workflow.outputs delegates owned checkpoints to the shared output_card; bounded native metadata retains report, checks, attempts, applied paths and review | Complete | No rewriting checkpoints or model calls |
| HO02 | Human output/status cards handle owned snapshots and honest acceptance | Owned renderer supports running/audit/native completion, diff truncation, tests/review; legacy renderer unchanged | Complete | No unsupported legacy review command suggested |
| HO03 | Completion → outputs → receipt → ACK → idle gate regression | tests/test_owned_handoff.py exercises a native candidate through apply and all CLI views plus notification receipt; no new worker calls or checkpoint mutation during reads; 89 related tests pass | Complete | Fixture gate/host evidence are simulated in tests, not live host receipts |
| HO04 | Live handoff and fresh trial after repair | Old task TASK-8c1aa25368cc4b119b9275803cc3c986 now readable through work outputs: 6 changes, 25 tests, accepted review. Proposed lesson f0960f9e11981ff00141be83c61ed455afc38168c6b3cf413dcfb885b387c02c references outcome 932 | Partial | Fresh task TASK-b9a0c151d7274e97b5515f8318ad44e2 started on 920d000 at 2026-10-10T07:36:38Z in ca-e2e-1010; runner 51112 alive and terminal reused. Host schedule ACTIVE: settle old receipt before switching attachments. New end-to-end result pending |

The earlier trial completed computation without entry edits/tests after dispatch: 569 seconds, 2 managed invocations (50+5 native turns), 25 offline tests. Handoff failed afterward on the legacy output adapter. This is known-case evidence with prepared SDK/cache, not unseen-task, device/server, full Save-widget or long-duration reliability evidence. Worker-reported ASCII workaround is not a recommended product requirement: preserve UI language and investigate UTF-8 transport separately. No automatic skill/routing promotion.

Validation: 89 tests across owned handoff, workflow, owned/native/workspace execution, notification watch/receipts and MCP; existing subprocess ResourceWarning remains. The real completed task was read without restarting execution.

## Native permission and receipt recovery — 2026-10-10

User requests fixing the failed replay. Baseline 56ce2fb; cycle PF01–PF04. Preserve task, original grant, paid result and original product files; classify this replay as assisted after runtime repair.

| ID | Requirement | Evidence | Status | Boundary |
|---|---|---|---|---|
| PF01 | Parse heterogeneous CLI events without masking unknown tools | Real permission_denied string shape regression; malformed top-level/message/content cases raise LedgerError | Complete | Malformed assistant/tool payloads fail closed |
| PF02 | Exact write scope survives Windows paths and cwd changes | Absolute Windows POSIX Edit rules, escaped literals; nested live probe after cd: Edit/Write/Python work, unowned Edit/touch denied | Complete | No broad Edit, arbitrary Bash or bypass permissions |
| PF03 | Controller exceptions persist a truthful blocked checkpoint | Runner AttributeError injection records blocked, one invocation, no extra model calls | Complete | Retain pending attempt; no implicit redispatch |
| PF04 | Recover paid permission failure and retry within existing authority | Paid ATT-204cc8e32c9b445999ea1f800a1727d8 recovered without inference; same task/cap with 1 used call; runner PID 28776 alive at 2026-10-10T06:00:32Z, grouped terminal reused, bounded watch ACTIVE | Complete | Existing scoped permissions only; product completion still requires test/review |

Validation: 66 related tests passed; final focused rerun including the added pending-request regression passed all 24 tests. Live nested probe `nested-4305b09849`: 11 native turns, synthetic fixtures only; product task remains stopped until dispatch. Runtime assistance is persisted in outcomes instead of being described as autonomous.

Live recovery on 30db4b4 retains the original question/response, usage, session and task TASK-2e7fc730eee44122a5eb3543ab3f7e2c. No files changed in the failed attempt; no product edits or tests executed by entry. `assistance=entry-runtime-repair` is explicit. Scope/budget unchanged; product outcome pending in background. The following NW04 unassisted acceptance gate was not met by the first trial; restarting after this repair does not erase that failure.


## Scoped native workspace worker — 2026-10-10

Proposal: approved entry explanation and architecture-kiro-cao.vi.md P0.1. Baseline dc749d9. Cycle NW01–NW05. Preserve the completed product fix; replay pre-fix inputs in a separate project. No runtime repair during the acceptance run may be called unassisted.

| ID | Requirement | Implementation / verification | Status | Boundary |
|---|---|---|---|---|
| NW01 | Claude edits and tests within one native session | workspace_worker; live Claude 2.1.286 probe: Edit, Write and Python bridge succeed; unowned Edit and touch denied; ten new unit tests | Complete | Claude/Flutter opt-in recipe; CLI also permits built-in read-only shell operations; not OS sandbox |
| NW02 | Runtime recovers authorized environment metadata/cache | Existing graph/compiler staging; exact public lock version/hash cache recovery; mismatched hash remains blocked on retry | Complete | Mocked cache download tests, no private/Git/SDK installation or dependency upgrades |
| NW03 | Scope, caps and independent acceptance remain enforced | Disk collection, unowned hash checks, eight test runs, duplicate checkpoint stop; pending/consumed context reuse; independent test/review/CAS | Complete | 60 related tests pass; native turns are distinct from managed model call budget |
| NW04 | Unassisted Cloud Auth replay | TASK-2e7fc730eee44122a5eb3543ab3f7e2c dispatched on ecebf0b, runner PID 43952 alive; terminal reused, bounded watch ACTIVE | Partial | Isolated pre-fix known-case replay; outcome pending, not unseen-task or eight-hour soak evidence |
| NW05 | Record evidence and lessons without auto-promotion | Pending live outcome | Missing | No automatic skill/routing approval |

Validation: 60 tests pass with the existing subprocess ResourceWarning. Two live capability probes were setup checks, separate from the product acceptance trial. The first exposed that new-file Write also needs the path's Edit permission and that built-in read-only echo is permitted by the CLI; the second verified the corrected permissions and external Python bridge. No product fix or product test was performed by entry during these probes. Runtime acceptance still requires the separate NW04 trial.

Replay starts 2026-10-10T05:39:58Z in `C:\Users\NUC\.onecrew\replays\cloud-auth-native-20261010`, 2426 captured/compiler files with owned bytes restored from the original pre-fix blobs. Claude Sonnet, 100 managed calls / 7200 seconds, new approved replay solution SOL-9927d46589154e958888648a20ba3075. The completed source task and customer working files are preserved. Runtime is frozen for this trial; any subsequent entry repair or product operation must invalidate an unassisted claim. Host monitoring is a bounded scheduled check, not an immediate callback. Outcome retrospectives are proposed automatically by the existing learning pipeline; task-specific lessons await actual evidence.


## Cloud Auth environment recovery — 2026-10-10

User requests entry/runtime cooperation through a verified result. Cycle ER01–ER03; baseline 1da68b4. Preserve existing task/scope/candidate and prior receipts. The entry fixes orchestration; OneCrew owns Flutter verification and independent review/application.

| ID | Requirement | Implementation / verification evidence | Status | Boundary |
|---|---|---|---|---|
| ER01 | Prepare complete offline Flutter package metadata | Validate original remapped package_config against captured config, pubspec/lock bytes and graph package names; copy only missing package_graph, preserve conflicts | Complete | No pub get, dependency upgrade, SDK or product code edits |
| ER02 | Environment errors do not trigger AI code repair | Explicit test result failure_kind; keep verify stage/candidate and repair count | Complete | Environment recovery uses existing trusted-native recipe; no tool expansion |
| ER03 | Existing Cloud Auth task reaches test/review/application evidence | TASK-44d35ce00853409aa0631179ecd79b2d completed; final 36 tests pass, independent review accepted, all six applied source hashes match snapshot a5bd5acff7c5e24ceaeba27a507448bd4159418ae41bef5e0d7e7739e0649202; outcome event 878 | Complete | Local code completion only; APK/device/server/full Save-widget acceptance unverified |
| ER04 | Detect missing dependency cache before launching compiler | Validate local file roots and pubspec for every captured package; missing-cache recovery regression | Complete | No automatic downloads or dependency resolution in the gate; operator can restore lockfile versions |
| ER05 | Separate filtered AI context from complete local compiler inputs | native_test_workspace stages captured candidate plus omitted Dart library inputs from authorized roots only; separate directory, bounded traversal, hashes checked after tests and before apply | Complete | Trusted native test execution, not OS isolation; omitted bytes are never added to worker context or prompt blobs; source drift blocks |
| ER06 | Content rejection must not exhaust product correctness repair allowance | Separate two-round content/product caps; legacy history classified from rejection receipts without resetting cumulative repairs/calls; explicit resume reuses rejected review feedback; 37 native/owned regression tests pass | Complete | Same total call grant and scope; no repeat paid review just to recover feedback |

Validation: 42 native/scanner/tool-receipt/owned tests pass (existing subprocess ResourceWarning). Original graph and captured config both contain 242 identical package names. Prior test failed before test execution because only package_config was staged.

ER04 cycle: 33 native-change/owned tests pass. The next live attempt exposed 33 absent cache packages and stopped on the existing 2 MB output bound. Preflight now reports the missing package names before compiler execution; no repair round or model call is consumed. Entry is restoring the exact hosted versions/hash receipts and pinned printing Git revision. Live product verification remains pending.

ER05 cycle: 35 native-change/owned tests pass, including separate compiler inputs, original-source CAS, compiler tampering and symlink rejection. All 242 configured package roots now exist. Existing package_config pins matcher/vector_math differently from pubspec.lock; they are preserved and the test receipt identifies the actual configuration. The private hosted package hash lookup is excluded from public cache verification. No dependency upgrade is inferred or performed. Entry-assisted cache restoration and runtime repairs must not be reported as an unassisted OneCrew run.

Final live result: reviewer rejected the initially green candidate for reversing AUTH_TOKEN precedence. The same worker corrected it; the final candidate passed 36 offline tests and independent review, then OneCrew applied six scoped files locally. Six of 20 cumulative managed calls consumed; no product Git publication. Three proposed lessons reference outcome 878 (assisted-run limits, environment/build context separation, bounded repair and compatibility review); no skill or routing rule was automatically promoted. Original device report 01014DEV is not proven resolved without a real build/server test.

## New-task budget and learning policy — 2026-10-10

Proposal: docs/budget-learning-policy.vi.md; approved by the user's “ok” after the 100-call/two-hour/70% discussion. Baseline 306bc3c. Existing Cloud Auth grant remains unchanged. Cycle BP01–BP04.

| ID | Requirement | Implementation / verification evidence | Status | Boundary |
|---|---|---|---|---|
| BP01 | New defaults shared by CLI/Python/MCP; replay and explicit values preserved | owned_intake / owned_cli / mcp_entry; defaults/legacy/replay tests | Complete | 100 calls / 7200 seconds; only new jobs |
| BP02 | 70% evidence-based assessment; early no-progress gates retained | effort_watch v2 snapshot policy; exact call/time thresholds, continue remaining budget, legacy and hard-budget tests | Complete | Human decision; no auto-extension or arbitrary progress percentage |
| BP03 | Durable outcome metrics and proposed retrospective | learning record; honest wall/attempt time, unknown active/wait time, dedup/stale lesson tests | Complete | Proposed facts; no automatic skill or model promotion |
| BP04 | Bounded historical advice with task evidence | budget_policy.recommend; unique tasks, latest outcomes, failures and exact match tests | Complete | Advisory only; no JEV invocation; exact goal, same project/mode/provider/model |

Validation: 85 focused regression tests pass (existing subprocess ResourceWarning); compileall and CLI help checks pass. Historical advice remains explicitly advisory, with no live benchmark or automatic model promotion. No worker dispatch or changes to the active product task in this cycle.

## Cloud Auth retry / rejected candidate recovery — 2026-10-10

Baseline ce6806a. User requests retrying the existing Cloud Auth task. Scope: repair the runtime blocker, retain task identity/scope/call budget, then resume in the background. No application code is edited by the entry.

| ID | Requirement | Implementation / verification evidence | Status | Boundary |
|---|---|---|---|---|
| CR01 | Distinguish Dart symbol assignment from credential literal | dart_scan.py only exempts complete bare reference assignments outside strings/comments; byte-preserving; literal/token/binary and nested-comment tests | Complete | Generic discovery policy unchanged; ambiguous syntax remains blocked |
| CR02 | Recover rejected candidate through bounded worker repair | native_change CandidateContentRejected; digest/reason evidence, no raw credential feedback; entire patch preflight before installation; two existing repair rounds | Complete | No exemption for test credentials; no tests/application until candidate accepted; same session and budget |
| CR04 | Explicit retry of expired task after original eight-hour wall-clock horizon | Optional restart-expired flag; default bound unchanged; preserve cumulative calls, immutable original grant, CAS/idempotency and no auto-resume; reject shared goal or pending/unknown attempts; 43 budget/goal/control/triage tests pass | Complete | New window capped at eight hours from operator action; Cloud Auth requests only 30 minutes |
| CR03 | Retry existing task with actual background runner and notification watch | TASK-44d35ce00853409aa0631179ecd79b2d resumed 2026-10-10T01:38:37Z; runner PID 28376 alive, monitor reused; host automation ACTIVE confirmed | Complete | Keep 20-call cumulative cap, explicit new deadline, no task recreation or approval changes |

Validation: 77 scanner/native/tool receipt/owned/solution/effort regression tests passed (existing subprocess ResourceWarning). Stored Cloud Auth output remains evidence, not an approved or tested fix.

## Proactive notification receipt correction — 2026-10-09

Baseline da41047. User explicitly requests fixing the false delivery acknowledgement and seeing an automatic notification. The prior current-turn ACK is NOT evidence of proactive delivery.

| ID | Requirement | Implementation / verification evidence | Status | Boundary |
|---|---|---|---|---|
| ND05 | Reading/preparing cannot consume a proactive notice | notification_receipts.py; watch consumer guard in notifications.ack including raw pull bypass; negative ACK tests | Complete | Empty batches and local-file sink retain ordinary ACK |
| ND06 | Verify an actual completed scheduled final before ACK/pause | Bound automation/thread/message body; read_thread JSON receipt validation; reject manual reply, commentary, tool output, stale/truncated/wrong-thread/duplicate evidence | Complete | Trusted local host adapter evidence, not cryptographic receipt or proof of OS toast/user read |
| ND07 | Recover/requeue safely without duplicate inference or endless empty checks | Idempotent begin/confirm, three missing checks then explicit error pause; user-authorized redeliver retains cursor/history; recovery tests | Complete | No automatic replay of uncertain sends or task resume |
| ND08 | Actual scheduler sends notification, next tick validates and pauses | Scheduled final msg_0afbd902fd520c21016ac919728af48191bc4befdf1545160b observed by read_thread; confirm-delivery accepted 2026-10-09T16:44:47Z, ACK then host PAUSED | Complete | Proves chat final and bounded lifecycle, not OS toast or user read |

Validation: 50 focused tests pass. Updated entry contract and notification-watch.vi.md. No customer task restarted, no approvals answered, no model called by OneCrew to test receipts. ND08 subsequently verified by actual scheduled final, host receipt and ACK/pause (see row above).

## Notification delivery / bounded host watch — 2026-10-09

User authorized fixing missing completion notifications and stopping idle monitoring. Baseline 326c58b. Implementation cycle ND01–ND04; no customer code edits, task resumes, quota changes or approvals are part of notification delivery.

| ID | Requirement | Implementation / verification evidence | Status | Boundary |
|---|---|---|---|---|
| ND01 | Recover Windows delivery without losing batch | Short atomic temp filename in snapshots.py; Store-length path regression; real handover batch persisted and ACKed | Complete | File sink receipt is not a chat callback |
| ND02 | Visible failures, durable ACK, current questions | delivery pending_batch/last_error; retry tests; CREQ uses conversation_questions | Complete | ACK never approves/replies/resumes |
| ND03 | Watch only attached tasks, stop when idle/required input | notification_watch.py; multi-task, dead/unknown runner, paused execution, active standalone build, completion/CONV race after ACK, dedup tests | Complete | TASK IDs only; no autonomous CONSULT watch |
| ND04 | Configure actual host lifecycle and notify current chat | Existing heartbeat updated via host tool; entry contract rearms at submit/resume; real Cloud Auth event 814 read, ACK returned should_pause=true, host confirmed PAUSED | Partial | Actual future scheduled wakeup/self-pause not yet observed; current-turn host operations verified. No immediate callback or auto-arming from plain CLI |

Validation: 82 regression tests passed; after the final pause/build/conversation-race changes, 23 focused tests passed. Existing process-test ResourceWarnings did not fail assertions. Details and evidence: notification-watch.vi.md. Notifications for handover and the newly blocked Cloud Auth result were consumed without starting a model or modifying either task's authority. Remaining ND04 validation: the next actual entry-dispatched task must produce a scheduled message and the host must pause after final ACK; do not infer this from configuration acceptance.

## Native tool receipt recovery — 2026-10-09

Approved scope: user requested fixing the Cloud Auth task blocker and running the existing task again after the recorded diagnosis. Baseline a1bfd70. This repairs OneCrew infrastructure; application acceptance remains separate.

| ID | Requirement | Implementation / verification evidence | Status | Boundary |
|---|---|---|---|---|
| NR01 | Distinguish disabled tool attempts from executed/unknown calls | native_audit.check_native_tools; exact CLI denial, ordered unique IDs, advertised capability; six receipt tests with adversarial variants | Complete | Unknown errors, successful calls, missing/duplicate receipts remain blocked; no new tool grants |
| NR02 | Recover settled patch without repeat inference; clarify tool use | native_change read-only prompt; native recovery test retains one call and records denied attempts; real ATT-39dfd79f76914fd8b8beafa9916439d8 parses six files / four denied Edit attempts offline | Complete | Original transcript and budget counters retained |
| NR03 | Preserve source and test/review gates | Snapshot check before patch installation; mutation masking test; 88 native/owned/workflow/solution/effort tests pass | Complete | A parsed patch is not a verified Cloud Auth fix |
| NR04 | Explicit restart excludes prior blocked idle time from next warning interval | Owned.resume renews baseline only after settled block and without pending requests; regression preserves hard budget and pending warning | Complete | No automatic reply or resume; prior checkpoints and cumulative calls retained |

Evidence: Claude CLI 2.1.286 advertised only Read/Glob/Grep/StructuredOutput. Four Edit attempts each returned an exact disabled-tool error; terminal result was successful after 200.316 seconds. All 2,414 captured source files matched the manifest. No model called during offline replay. The existing task will resume through fixed Flutter tests, independent review and guarded application; no production endpoint or device testing is implied. Regression suite emits an existing subprocess ResourceWarning; 88 tests complete successfully.

## Revision 9 implementation — current tracking

Sources: architecture.vi.md, shared-conversation.vi.md, solution-approval.vi.md, discussion-routing.vi.md. Baseline 15d1cbe; conversation foundation 48e579b. User authorized implementation of this architecture, not blanket approval of future product solutions. Current cycles 2–4 completed: runtime gate, consultation/adapters, slice/outbox integration. Historical tables below retain their original baseline dates/statuses.

| ID | Requirement | Implementation / evidence | Status | Boundary / remaining |
|---|---|---|---|---|
| CS01 | Conversation before task, project isolation | conversations.py; no-task/read-only/isolation tests | Complete | Local same-OS-user boundary |
| CS02 | Durable provenance, cursor, ACK/idempotency | Concurrent append, replay/collision/restart tests | Complete | No private transcript import |
| CS03 | Referenced summary/delta preserving decisions | Stale summary, references, bounded delta and current questions | Complete | Semantic summary explicitly unverified |
| CS04 | CLI/MCP with actual host read/write | conversation_cli/mcp; Claude and Codex CLI durable ACKs in revision9-live-evidence.json | Complete | Kiro MCP/Desktop automatic sync unverified; host must call tools |
| CS05 | Solution approval/task binding | Owned submit transaction; legacy spec gate; solution bind for sealed DAG | Complete | Existing pre-upgrade authority retained |
| CS06 | Events/recovery/compatibility | Same notification batch/ACK plus conversation cursor, no AI polling; receipt replay tests | Complete | No unsolicited Desktop callback |
| SG01 | Solution before new write job | Intake rejects missing approval; read-only audit works | Complete | Native execution still needs explicit recipe grant |
| SG02 | Exact approval at entry/admission/mutation | Control, owned, native, sandbox/action gates; stale/reaffirmation/stop tests | Complete | Local attribution, not multi-user authentication |
| SG03 | Required change holds across entries | CREQ persistence, affected same-contract closure; stop/continue/revise; bound answers enter prompts | Complete | Applying a revision waits for settled attempts; published changes need reconciliation |
| SG04 | Shared contract and first-slice gate | One live owned writer/SOL; bound sealed DAG tests A → user review → B/C → D; existing amendment closure | Complete | No automatic native multi-repo graph synthesis; legacy DAG must be sealed |
| SG05 | Solution-aware review and outputs | Full brief/detail/hash in worker/reviewer; output events carry SOL/revision/snapshot | Complete | Tests/review do not prove every semantic expectation |
| DR01 | Current entry vs actual pin/auto | discussion.py; default no invocation; structured explicit intent, mentions remain data | Complete | Entry interprets actual user intent; no keyword auto-dispatch |
| DR02 | Separate discussion/execution preference | No model_preferences dependency; provider/model pin and verified default aliases | Complete | Kiro model must be explicit |
| DR03 | JEV after hard gates, bounded shadow | Rule filtering/revalidation, persisted evaluator intent, uncertain call not retried; pin wins | Complete | Initial shadow rollout only; benchmark and operator policy required before auto-apply |
| DR04 | Bounded recoverable consultation | Separate CONSULT storage, same runner/supervisor/global capacity; crash/cancel/stale/oversize tests + real Claude review | Complete | One native invocation is not a cap on provider internal model turns |
| DR05 | Return to CONV and supported entry | Result event, conversation delta, CLI/MCP show and existing outbox ACK | Complete | Pull is supported; Desktop push unavailable |
| DR06 | Routing outcome assessment | Feedback/evidence/first-acceptance/missed issues/rework, usage/latency/provider metadata retained per consultation | Complete | Collection/evaluation plumbing only; no calibrated policy promotion claimed |

Validation: full regression **443 tests passed** (289.772 s), then **81 focused tests passed** (28.069 s) after final gate/recovery changes. An additional 19 solution-gate tests passed; the final frozen-context recovery pass ran **83 tests successfully** (35.710 s), proving replies cannot change a reserved prompt or trigger duplicate inference. Compileall and diff checks pass. Wheel packaging succeeded: onecrew-0.1.0-py3-none-any.whl (isolated build; runtime dependencies unchanged). Existing process-containment tests emit ResourceWarning for subprocess objects, but cleanup and stop assertions pass. Synthetic live evidence: one Claude solution review; Claude and Codex CLI read/append the same CONV with independent durable MSG ACKs. Earlier MCP setup failures are retained in evidence; provider completion alone is not treated as tool success. No customer source modified, no old worker automatically resumed, no heartbeat re-enabled.

An earlier full run found one Windows receipt sharing race; android_jobs read and durable atomic replace now retry only PermissionError on Windows, at most five attempts/200 ms total wait. Focused build tests and the subsequent full regression pass. The new shared discussion and decision gates are ready for a bounded real-task trial, not evidence of eight-hour soak or universal model-routing quality. Instructions: [revision9-implementation.vi.md](revision9-implementation.vi.md).

## Discussion routing — revision 9

Contract: `docs/discussion-routing.vi.md`; documentation only, no model dispatch or preference changes.

| IDs | Requirement | Existing foundation | Status / required evidence |
|---|---|---|---|
| DR01–DR02 | Explicit user pin / current-entry default / independent discussion policy | Provider preference and explicit job pin | Pending discussion integration; intent examples, no duplicate host worker, no execution policy override |
| DR03 | Optional JEV after hard gates; shadow before auto | JEV connection and shadow proposal receipts | Pending discussion benchmark; no authority from confidence, quota or model-name guesses |
| DR04–DR05 | Bounded revision-bound consultation and return to CONV | Provider supervisor and local outbox | Pending; live provider review, crash/idempotency, stale result, cancel, host callback or explicit pull |
| DR06 | Routing quality/usage evaluation | Outcome history and proposed lessons | Pending; workload-specific evidence includes evaluator cost and failures |

Rules/explicit consultation precede JEV auto-routing. This document does not claim runtime tests or live cross-provider discussion has passed.


## Shared conversation and solution gates — revision 8

Architecture: `docs/architecture.vi.md`; contracts: `docs/shared-conversation.vi.md`, `docs/solution-approval.vi.md`. Documentation update only; existing implementation evidence below is unchanged.

| IDs | Requirement | Existing foundation | Status / required evidence |
|---|---|---|---|
| CS01–CS02 | Conversation before tasks, durable contributions/ACK/cursors | SQLite and task-bound entry notes | Pending; concurrent append/retry/restart and scope tests |
| CS03 | Source-backed summary + delta preserving decisions/questions | Bounded task context packet | Pending; stale/truncated summary recovery tests |
| CS04 | MCP/CLI discussion read/write and host adapters | Task MCP status/outputs/inbox/control; note available via CLI | Pending; two live hosts sharing CONV without copy/paste |
| SG01–SG02, CS05 | Approved solution revision gates all applicable execution paths | Spec approval hashes, intake/grants | Pending runtime binding; entry policy documented; stale/CAS/submit-race tests required |
| SG03, SG05, CS06 | Change requests/output return to conversation, revision-aware review, event lifecycle | Task inbox/outbox/runner/reviewer | Pending conversation linkage/holds/host delivery; no idle model polling |
| SG04 | Contract-first parallelism after early review | Legacy DAG/ownership/amend/integration | Pending owned/native solution integration and live quality evidence |

No new runtime tests claimed by this documentation change. CS/SG APIs are proposed, not installed CLI commands; no model call, task restart or host connection is authorized by editing these documents.

## Native Flutter change — NC01–NC04

Proposal: `docs/native-change.vi.md`; follow-up request delegates Cloud Auth repair through OneCrew.

| ID | Requirement | Evidence | Status | Limits |
|---|---|---|---|---|
| NC01 | Native whole-unit scoped patches | native_change, intake/CLI, scope tests | Implemented | Claude only; structured patches, native read tools |
| NC02 | Fixed Flutter verification tied to candidate | command/receipt checks, failed-exit regression | Implemented | Trusted host tests, no device/server verification; live task pending |
| NC03 | Independent diff review, bounded session repair/checkpoints | native-change and native-audit fixtures | Implemented | Native quota failover remains pending |
| NC04 | Apply only checked/reviewed bytes, preserve dirty edits | conflict, idempotency, full-cycle fixtures | Implemented | Atomic per file, partial apply recoverable; live task pending |

35 targeted tests passed. Runtime integration was prepared by Codex; product fix is delegated to Claude through OneCrew.


## Native audit trial — NA01–NA04

Proposal: `docs/native-audit-trial.vi.md`; baseline e0285c3. User approved trial, not removal of scope or evidence standards.

| ID | Requirement | Evidence planned | Status | Limits |
|---|---|---|---|---|
| NA01 | One native tool loop per work unit, reuse session for repair | Claude adapter/phase state, fixture and live native tools | Complete | Claude audit only; live repair continuity not yet demonstrated |
| NA02 | Read-only scoped snapshot and tool restrictions | snapshot/filter/escape tests and live denied read | Complete | Provider boundary, not OS sandbox; one live outside-read case |
| NA03 | Independent review, citation verification, usage and bounded recovery | session repair/restart/failure tests | Complete | Native turns differ from managed calls; 30 turns/600 seconds per invocation, no implicit fallback |
| NA04 | Same Cloud Auth task, real result and lessons | live task outcome and evidence | Complete | Outcome 739: source audit accepted; APK unverified, report qualifications documented |


Native trial validation: 41 native/owned/effort/review tests passed; native fixture completed with actual outside read denied. Production trial completed with independent acceptance, 54 cumulative calls; details, token breakdown, preparation failures and report limitations in `docs/native-audit-trial.vi.md`. Credential JSON-key regression added after observed gap. General multi-provider native mode and native quota failover remain outside this slice.

## Review repair and autonomous audit — RV01–RV04

User asks to keep repairing OneCrew until it finishes the Cloud Auth audit, then record lessons. Baseline `7c5c70a`; retain task ID, prior attempts and source workspace. This explicit request authorizes following the bounded verification run through its outcome, while worker execution remains detached. Missing user/device evidence still requires an inbox question; no invented approvals.

| ID | Requirement | Evidence planned | Status | Limits |
|---|---|---|---|---|
| RV01 | Typed review rejection cannot become quota/auth/environment failure from feedback text | ReviewRejected, classifier regression with 429/OAuth/SDK strings | Complete | Existing real provider handling unchanged |
| RV02 | Full bounded immutable review evidence plus explicit receipt retrieval | review_evidence manifest/full receipts, bounded retrieval rounds and restart tests | Complete | 45,000 receipt chars, max 4 requested indices/round, 3 retrieval rounds, same root budget |
| RV03 | Source/read and Git metadata retained; explicit resume adopts warning policy without retroactive auto-answers | read cursor/start_line, branch/dirty status, evidence index, resume tests | Complete | No reset of historical calls/usage; pending requests remain pending |
| RV04 | OneCrew completes actual audit with checked evidence; proposed lessons tied to outcomes | live task checkpoint/report, lesson evidence | Complete | Completed via native audit outcome 739; application/device correctness not implied; assisted runtime migration |

New review protocol counts its genuine rejected reports separately from legacy reviews that received truncated evidence; preserves the legacy total and the existing three-rejection limit for new-protocol reviews. This is a protocol migration, not erasing failure history or relaxing acceptance. No requirement removed from the original task.

Validation: 57 targeted tests passed (review/owned/revision5/effort/fallback); the final seven review tests passed in 1.725s, including real Git branch/detached/index preservation. Existing native fixture ResourceWarning remains with cleanup assertions passing. Live audit acceptance is still pending.

Follow-up: live resume reached 52 total calls (20 new) in ~5 minutes and correctly opened effort REQ `REQ-4c43f23b52ce47d59220cff6943f4817`; no additional inference until user answer. Two protocol-2 reviews rejected reports that forgot already-observed dirty/endpoint facts. RV02 now also supplies the decision worker a deduplicated 36,000-character receipt budget, compact manifest and persistent latest review feedback, replacing last-three-only context. Read failures retain path/cursor without exposing withheld files. Test evidence: 31 owned/search/review regressions passed; 23 final review/effort/history tests passed in 22.794s. RV04 remains pending; warning is not auto-approved.

## Effort-warning cycle — EW01–EW03

Source: user asks to warn when work takes too long so the user chooses; follows explicit expansion of the Cloud Auth task budget. Cycle baseline `d583219`. Soft warnings do not revoke the existing hard grant or silently extend it.

| ID | Requirement | Evidence planned | Status | Limits |
|---|---|---|---|---|
| EW01 | At a settled owned checkpoint, warn after 20 calls or 600 elapsed seconds since tracking baseline with progress/usage | effort_watch deterministic request; clock/call tests | Complete | Elapsed time can include waits; no interruption of a live worker or build |
| EW02 | Durable continue/pause/stop decision; silence/defer/ack never answer; restart dedup | revision-bound inbox + reply consumption, restart/crash-gap, silence/pause/stop tests | Complete | Continue does not increase hard grant/deadline; pause adjustment requires discussion |
| EW03 | Surface through output card/monitor/local notification feed without AI polling | existing request delivery and output card; notification delivery/ack test | Complete | No automatic callback to this chat; old running Python processes need restart to load code |

Validation plan: deterministic threshold/reply/restart/crash-gap tests, relevant owned/runner/inbox/delivery regressions. Existing blocked/terminal jobs are not silently resumed. No new worker calls needed for this implementation.

Validation: effort-watch/owned/runner/notifications/delivery/fallback subset passed 53 tests in 22.349s; existing native-process ResourceWarning remains, with cleanup assertions passing. No product inference or task resume performed. Cloud Auth task observed blocked at 32 calls after evidence review rejection; the raised hard budget did not cause this stop. Terminal and inbox use existing request lifecycle; no chat callback or legacy workflow/build-midflight warning is claimed.

## Search recovery cycle — SR01–SR04

Source: Cloud Auth task `TASK-0236a265d0ef4dd19d5cd14f8e600e95`, user request to fix OneCrew and rerun; baseline `1f2c89b`. Eleven successful Claude attempts stopped on three different empty searches; only one app configuration file had been read. Scope is runtime repair, not application code repair.

| ID | Requirement | Evidence planned | Status | Limits |
|---|---|---|---|---|
| SR01 | Recursive bounded paginated search with explicit coverage and Flutter ARB support | discovery + tests for nested dependency, paging, exclusions and truncation; real source match at page cursor 200 | Complete | 10,000 enumerated entries, depth 32, 100 candidate files/page; unchanged secret/link policy |
| SR02 | Distinguish empty search scopes and credit new source evidence without removing repetition/root caps | progress + empty/positive repeat, read progress, root cap tests | Complete | Different searches still hit exploration limit; positive repeated evidence still stops |
| SR03 | Persist search arguments and compact search history; guide manifest dependency discovery | owned receipts, evidence index, worker contract + restart test | Complete | Legacy receipts remain without invented query metadata |
| SR04 | Sum Claude terminal usage without adding nested counters twice | usage + strict counter/dedup tests; 11 persisted Claude records now measured | Complete | Observed tokens only, no subscription quota/cost inference |

Validation plan: focused regressions, existing owned/revision-5/usage/fallback suites, read-only search on real source. Then commit, retain original task and cumulative usage, explicitly record a bounded deadline extension if needed under the user's rerun instruction, and resume detached with grouped terminal. No waiting loop in chat after dispatch. This rerun is assisted by runtime repairs, not an unassisted acceptance pass.

Claude usage semantics: [official prompt caching documentation](https://platform.claude.com/docs/en/build-with-claude/prompt-caching): three disjoint input fields; cache duration and iteration breakdowns are not additional usage.

Validation: targeted search/revision-5/usage/owned/fallback run passed 71 test executions in 50.243s (included imported fixture tests). After restricting discovery to the intended test class, final seven search-recovery tests passed in 0.488s. Existing native-process ResourceWarnings appeared; explicit cleanup assertions passed. Read-only real-source search paged through cursors 0/100/200 and found `flutter_base/lib/usr/admin/setting_page.dart:371`. Stored Claude records now show 58,180 input (58,158 cache creation, 0 cache reads), 2,396 output, 60,576 total observed tokens, 11 measured and no unknown attempts. No new inference used for this validation. Full suite and application/device tests were not run; bug diagnosis remains the resumed task's work.

## Quota fallback increment — FB01–FB03

User request: prefer Claude, switch to Codex or Kiro when exhausted. Cycle 1, baseline `b85ab17`; no user product job or live quota exhaustion trial authorized by this validation plan.

| ID | Requirement | Implementation / planned evidence | Status | Limits |
|---|---|---|---|---|
| FB01 | Persist ordered explicit fallback models in new default owned jobs; preserve replay and explicit overrides | model_preferences, intake, provider CLI; preference/replay/explicit pin/CLI tests | Complete | Existing jobs stay sealed; no automatic JEV selection |
| FB02 | Recognize native quota exhaustion and forward handoff only after settlement | provider_limits, provider_fallback, owned; adapter envelopes, chain, restart, unavailable provider and unknown-process tests | Complete | Conservative known envelopes only; no arbitrary log keyword/429 routing |
| FB03 | Preserve evidence, review state, grants, root budget, cancellation and history | checkpoint + existing admission + learning; budget, pending approval, deadline, account binding, review continuation and outcome tests | Complete | No fresh Claude/Kiro quota feed; no automatic reset/loop back or paid API |

Validation: owned/provider/advisor/learning/subscription/MCP subset **53 tests passed in 28.555s**; workflow/quota-budget/usage/entry/intake/revision-5 subset **51 passed in 17.750s**; final fallback/provider subset **18 passed in 3.698s**, including CLI persistence, native nonzero-exit adapters and extra deadline guard. The second subset needs `tests` on `sys.path` because existing tests use unqualified fixture imports. Existing detached-process ResourceWarning remains in the first subset; cleanup assertions pass. Full suite not rerun. Synthetic native receipts and runtime fixtures cover Claude → Codex → Kiro, exhausted chain, restart and review continuation. Real subscription exhaustion is not deliberately induced; no user product task or live model inference performed.

Active shared state preference saved/read back as Claude `sonnet` → Codex `gpt-6.1-sol` → Kiro `claude-sonnet-5`; default state-root resolution reads the same policy. All three pinned CLI/auth probes available. Kiro model catalog lists the selected model; Codex local model cache lists the selected slug. These checks do not measure current remaining quota or prove quality equivalence. This increment completes only FB01–FB03's bounded behavior, not the broader routing/soak roadmap.

## Revision 6 — recurring skills and model preference

Source: user discussion and [skills-routing.vi.md](skills-routing.vi.md), baseline `081307d`. This scope adds skills after recurring work is evidenced; it does not close unrelated revision 5 gaps. Preserve user edits below SPEC-005.

| ID | Requirement | Evidence | Status | Limits |
|---|---|---|---|---|
| SK01 | Persist history signatures, procedure, skill provenance; count latest outcome per distinct task | learning.py, skills.latest; duplicate checkpoint/retry tests | Complete | Last 200 outcome events/project; no private chat import or invented backfill |
| SK02 | Propose only after recurrence plus successful evidence; no idle/model loop | skills.refresh; independent-task/failure/unrelated-goal tests | Complete | 3 tasks, 2 successes, lexical match; requires captured source extensions |
| SK03 | Review candidate/evidence/SKILL.md; revision-bound approval/rejection | skills CLI; stale revision/evidence/tamper/restart tests | Complete | Local operator trust; generated procedure scaffold requires human suitability review |
| SK04 | Load approved relevant skill within scope/permissions; record provenance | owned worker context + outputs + outcome; real runtime with fixture worker | Complete | One skill; no native script execution or semantic suitability guarantee |
| MR01 | Persistent Claude preference for new jobs; explicit override and replay stability | model_preferences + intake/CLI/MCP; persistence/replay/override tests; active state preference verified Claude/sonnet | Complete | Does not switch active jobs; defaults are explicit operator choices, not auto routing |
| MR02 | Provider priority after quota/capability/risk gates; reset hint not quota | routing.choose + provider CLI; quota/risk/capability regression; user hint 2026-10-09 23:00+07 | Complete | Claude quota feed remains unavailable; insufficient/unknown data still blocks automatic recommendation |
| MR03 | Bounded typed JEV shadow recommendation, failure fallback and evidence | model_advisor, provider choose --jev; malformed/timeout/abstain/filter tests; revision6-jev-evidence.json | Complete | One opt-in preflight call, separately recorded; no automatic dispatch or calibrated quality claim |

Cycle 1: 26 owned/skills/learning tests passed in 41.495s. Runtime fixtures use zero live model calls. Detached-process fixture emitted ResourceWarning, and its explicit stop/liveness assertions passed. No new user task dispatched.

Cycle 1 commit: `c762516`. Cycle 2 also refines SK02 to exclude tool operations with error receipts from learned procedures, adds a readable candidate title and rejection/no-reproposal tests. Eight skill tests now cover these paths. Approval/user acceptance is never inferred from recurrence or tests; no real skill was approved during implementation.

Validation: full discovery passed **342 tests in 380.133s** at the cycle-2 checkpoint. Final owned/skills/learning/advisor/MCP/intake subset passed **44 tests in 78.156s**, including the later procedure/title fixes and two added skill tests. Final preference-default compatibility adjustment passed **12 advisor/routing tests** separately. Python 3.10 syntax checks pass for changed modules; no lint/typecheck command configured. Full suite was not rerun after these targeted final fixes. Live JEV smoke: 1 request, 557 input/43 output observed tokens, 828 ms, sonnet proposal with confidence .88; synthetic quota/cost/tier, no worker dispatch or performance benchmark. Claude doctor verifies subscription auth; preference read back from active shared state-root. Existing detached-process ResourceWarnings remained; liveness/cleanup assertions passed.

Coverage for this bounded revision-6 slice: **7 Complete, 0 Partial, 0 Missing, 0 Blocked**. This does not complete revision-5 autonomy, semantic clustering, skill edit/import/version promotion, skill effectiveness trials, Claude quota observation, or calibrated automatic routing. Manual skill approval and the user's next product acceptance task remain future actions, not fabricated verification.

## Revision 5 implementation — KiroCrew + CAO

Source: [architecture-kiro-cao.vi.md](architecture-kiro-cao.vi.md), baseline `0f3d514`. Cycle 1 (`2117dce`): owned recipes, progress/evidence gates and local event sink. Cycle 2: common MCP entry, outcome/lesson evidence, delivery-specific worker/reviewer contracts and an isolated live trial. See [implementation contracts](revision5-implementation.vi.md). Existing evidence below remains scoped to its original trials. No CAO installation, heartbeat reactivation or SRM modification implied.

| ID | Proposal section | Requirement / mapping | Type | Implementation evidence | Test evidence | Status | Notes |
|---|---|---|---|---|---|---|---|
| V5-01 | 3–4 | Runtime-owned recipe dispatch/wait and root limits; OE/BG | Functional | owned_recipes + grant-bound Android dispatch/wait + root guard | test_revision5 (12 cases) and Android regression | Partial | Fixed historical Android recipe first; no arbitrary shell |
| V5-02 | 5 | Persistent exploration/repair caps and error classification; OC09/12 | Reliability | progress.py counters, error taxonomy, persisted owned checkpoints | test_revision5 + test_owned repetition/auth cases | Partial | Same root budget after resume |
| V5-03 | 7 | Evidence completion and immutable artifact checks; OC08/11 | Functional | owned_verification all captured tests on current snapshot; APK hash recheck | test_revision5 stale/failing/tampered evidence | Partial | User acceptance separate; broader AC coverage pending |
| V5-04 | 6 | Delivery lifecycle with no idle AI calls; BG/IN | Observability | delivery.py driven by owned checkpoints/runner stop/build finish; bridge PAUSED | test_delivery 4 cases + notification regressions | Partial | Local file sink implemented; direct chat callback unavailable |
| V5-05 | 4,8 | Single scheduler, CAO capability spike; OC04 | Architecture | Native adapters retained; native cao/tmux absent, WSL only docker-desktop | Read-only prerequisite probe 2026-10-09 | Blocked | Live spike needs suitable authenticated CAO environment; adapter not implemented |
| V5-06 | 3,6 | Common entry surface and durable cross-entry questions; OC01/05/06 | API | mcp_entry stdio, project-bound controls, durable CLI | 5 MCP tests: real stdio, read-only, revision, schema, launch failure/replay | Partial | No authenticated multi-user endpoint or verified connections from all hosts |
| V5-07 | 3,8 | Dependencies, writer isolation and integration; OC07/08/11 | Reliability | Existing DAG/merge/vector | Existing scoped fixtures/live; owned-job integration pending | Partial | Dynamic multi-repo scheduling not complete |
| V5-08 | 7 | Outcomes, lessons and evaluated routing policy; LR01–04 | Data | learning.py transactional outcomes and proposed lessons; existing routing | 3 learning tests; benchmark pending | Partial | Unknown quality/assistance retained; no automatic JEV promotion |
| V5-09 | 8 | Restart/network/quota/sleep/8-hour endurance; OC03/09 | Testing | Existing checkpoints/supervisor | Full fault matrix and live soak pending | Partial | Do not claim 8-hour verification |
| V5-10 | 1,8 | Fresh real task without external repairs | Testing | Isolated Codex trial completed in 8 calls, original source preserved | revision5-live-evidence-d2151ab1.json; prior 12-call failure retained | Partial | Tiny function only; user will provide acceptance task after readiness report |

Completed slices (parent requirements above deliberately remain Partial where broader gates are open):

| Slice | Status | Evidence |
|---|---|---|
| V5-01a fixed historical Android operation with root limits and no model polling | Complete | owned_recipes.py; active-parent/queue/deadline/artifact fixtures, existing Android regressions |
| V5-02a persisted repeat/exploration/write/test/review limits and infra/auth classification | Complete | progress.py; test_revision5 + test_owned; real initial trial stopped at call cap |
| V5-03a current captured tests and artifact integrity, delivery-specific action/review contract | Complete | owned_verification.py, owned.contract; stale/tampered fixtures; second live trial |
| V5-04a local event sink with retry/dedup/pending revision checks and no AI scheduler | Complete | delivery.py; 4 tests; Codex heartbeat remains PAUSED |
| V5-06a local stdio operator entry | Complete | mcp_entry.py; 5 tests; no installed host connection claimed |
| V5-08a durable outcomes and source-bound proposed lessons | Complete | learning.py; 3 tests; no policy promotion claimed |

Validation: full discovery passed **328 tests in 319.210s**. The subsequent delivery-contract fix passed all **12 revision5 tests and 17 owned tests**, and the final MCP launch-failure fix passed **8 MCP/learning tests**. Full-suite count refers to the earlier checkpoint, not a second full run of the final tree. Windows subprocess ResourceWarnings occurred during detached-process fixtures; their explicit stop/liveness assertions passed. No lint/type-check command is configured. Live evidence records both trials; observed token counts are not a pricing estimate or proof of routing efficiency. The successful trial used 8 managed calls and 70,113 observed tokens including repeated context; token optimization remains open.

Remaining mandatory roadmap gaps: broader AC coverage/discovery, generic framework recipes/workspace mode, bounded transient backoff, authenticated host integration/chat callbacks, owned-task dynamic DAG/integration, calibrated routing/lesson promotion and full fault/8-hour soak. The user acceptance task has not been dispatched. Readiness means a controlled trial on currently supported capabilities, not all revision 5 requirements completed.

## Background handoff — BG01–BG03 / IN01–IN03 / UX01

Contract: [background-handoff.vi.md](background-handoff.vi.md). Implementation phases: native detached Android execution, then durable deferred questions and acknowledged notification feed. Baseline b60469e; implementation commit `698b97f`. No product/SRM edits or live worker calls in this change.

| ID | Status | Evidence |
|---|---|---|
| BG01 | Complete | android_jobs.py, android_build.py default background CLI; native launcher exits while queued child remains alive; bounded handshake and separate status/cancel |
| BG02 | Complete | Shared OS lock for foreground/background across projects in one state-root; queue fixture and cross-project slot test prevent command execution; wait uses zero model calls |
| BG03 | Complete | Exact request/key conflict checks, process creation identity, durable job/recipe receipts, separate cancel marker, queue timeout, interrupted detection/reconciliation, no replay, duplicate artifact tamper rejection; eight background tests plus seven recipe tests |
| IN01 | Complete | request defer persists pending/revision without answers or deadline extension; stale/answered defer rejected; reply from another entry retains revision checks; AGENTS.md requires durable create before chat card; no interception of arbitrary third-party UI cards claimed |
| IN02 | Complete | notifications.py bounded persisted batch/explicit ack; independent consumer/scope, restart/retry, pagination, stale question filtering, transition deduplication, killed-build reconciliation; seven notification tests; no ack grants authority |
| IN03 | Blocked | Codex heartbeat `onecrew-k-t-qu-v-c-u-h-i` is PAUSED after idle wakeups; do not reactivate. CLI pull/ack exists, lifecycle-aware local delivery planned under V5-04; direct chat callback remains unverified |
| UX01 | Complete | Monitor merges job/build events, prioritizes parents of active builds, shows process death and request options/reply revision; nine monitor tests including real console independence; logical project/task/unit grouping |

Targeted evidence: initial 28 build/notification/monitor tests pass; added artifact-success/pagination/monitor-priority cases pass in 17-test subset. Three runner and 24 entry/branch-inbox/native-gate/intake regressions pass, plus ledger regressions. Full discovery ran 306 tests in 632.726s: 305 passed, one pre-existing containment fixture failed because its 0.4-second startup/timeout budget expired before printing a descendant PID. The unchanged test passed alone (0.560s); fixture timeout was then raised to 3 seconds, retaining real timeout/descendant-death/budget assertions. All 18 control tests passed after that fix (4.643s). No production timeout was weakened. Other 288 tests passed in the full run; no second full pass is claimed. The final required-input build guard passed separately. Changed Python modules also parse with Python 3.10 syntax; git diff checks pass. No configured lint/type-check command exists. Native subprocess ResourceWarnings indicate intentionally detached live children at Popen finalization; fixtures cancel/observe process death and clean up. One initial direct import invocation failed on legacy `test_workflow` module lookup; rerun with repository test discovery/import path passed, no weakened tests.

Bridge limits: polling can consume Codex usage and requires the host application to run; existing unchanged state is quiet. Consumer starts at real ledger cursor 332, so no historical notification flood. Feed ack means delivery consumption, not a cryptographic proof the UI rendered; failures between delivery and ack can cause replay, or host acknowledgement before UI failure can need manual inbox review. Required questions remain durable independently. Claude/Kiro use shared CLI context/replies; no verified push bridge to those UI clients. Workflow deadlines still include user wait and do not auto-extend. Foreground build is explicit; one slot is per state-root, not per physical machine. Native build remains a trusted recipe, not a filesystem sandbox. Coverage: 6 Complete, 1 Blocked (first scheduled host UI delivery), 0 Partial/Missing; no unqualified completion claim. Existing user changes below SPEC-005 retained.

## Grouped terminal monitor — TM01–TM03 / 09/10/2026

User requested a terminal at OneCrew start with verbose work and grouped agents. [Contract and usage](terminal-monitor.vi.md). No new scheduler, model role or budget group is added.

| ID | Requirement | Evidence | Status |
|---|---|---|---|
| TM01 | Detached visible console on job submit/start/resume or work start; reuse same viewer scope | monitor.py + CLI hooks; native Windows test confirms console attached, independent process, duplicate reuse; closing viewer leaves paused background runner alive, then explicit cancel stops runner | Complete |
| TM02 | Group project → task → actual worker units with provider/model/status | Read-only ledger snapshots; two active unit fixture with different providers, project/global filters, selected-model provenance; separate observed runner liveness from persisted task phase | Complete |
| TM03 | Verbose bounded tool/event/build activity; viewer never invokes model or approves | Timeline and tool receipt metadata, bounded build log tails, console/secret filtering, pending questions; byte-identical ledger read test, zero calls, Ctrl+C/console termination independent of worker | Complete |

Validation: eight monitor tests and five intake tests pass; three detached-runner regressions pass. Native test launches a paused fixture runner and a visible console, terminates only the viewer, verifies worker still alive and zero model usage, then explicitly cancels and verifies runner stopped. Terminal spawn failure is isolated from successful dispatch. CLI flags use argument arrays without shell interpolation. Same scope reuses existing viewer; changed scope can open another. Legacy `work start --terminal` uses the same viewer hook. Default view caps at 12 tasks with header count, active/checkpoint-unfinished tasks first. Logical grouping only, not Windows Terminal tabs. Android build remains foreground; its persisted activity can be observed but detached Android execution and chat callbacks are outside this slice. Existing user changes below SPEC-005 retained.

## Historical branch tools — GH01–GH03 / 09/10/2026

User assigned OneCrew to inspect flutter_vimes UI history and create a pre-UI branch. Existing job tools lacked history and historical ref creation; adding generic capabilities is recorded separately from worker execution, not claimed as unassisted capability already present.

- GH01 Complete: git_history.py provides pinned-HEAD first-parent pagination/literal search, commit metadata/file lists and policy-filtered historical diffs; full-SHA ancestry/path guards.
- GH02 Complete: branch mode grants local ref creation only; actual selected-commit diff and AI evidence review before action, exact first-parent target, fresh HEAD, new-ref CAS, receipt/reconcile and final ref observation. No checkout/reset/push. Five history tests pass, including dirty file/index preservation and lost acknowledgement without replay; 22 owned/intake regressions pass.
- GH03 Complete (historical branch only): TASK-aeb5446a96ec4edd9133bf41da39aec6 completed with a verified local ref `onecrew/pre-ui-20261009` at `5e6a89767678008c12d9988d5641c2f779d929a2`, before `468fea0` and `04e20fb`. User clarified both UI changes. Original checkout/index unchanged; no push. **42 managed calls**, not an unassisted success: initial 30-call cap exhausted while repeatedly inspecting history; eight additional calls exposed circular pre-action review requiring a post-action receipt; four further calls completed after runtime fixes. Extensions retained cumulative usage and the original deadline. Chat repaired generic infrastructure but did not select the commit or create the source branch manually. Compact durable history evidence, core-tool instructions, current budget context, empty-path normalization, safe prompt refresh on resume, and distinct pre-execution/completion reviews added. Six history tests and 17 owned runtime tests pass; the historical end-to-end test verifies the pre-action review has no receipt and the completion review has the verified receipt. APK is tracked separately and is not claimed by GH03.

## Historical Android APK build — AB01–AB03 / 09/10/2026

User requested Android APK from the pre-UI baseline; later explicitly selected historical internal dependencies and identified `7.SRM/flutter_hmscore`. [Build contract and CLI](android-build.vi.md).

| ID | Requirement | Evidence | Status |
|---|---|---|---|
| AB01 | Official build adapter uses verified branch commit and isolated source copy | android_build.py; original/index preservation, moved-ref refusal, archive escape/link tests; short Windows build path | Complete |
| AB02 | Fixed bounded native debug build, durable logs/receipts, artifact checks, reproducible dependency selection | Seven Android fixture tests including failure/missing artifact/idempotency/tamper/authority, path and Git dependency pinning; seven native/container gate regressions; extra override-preservation test | Complete |
| AB03 | Real UI-old Android APK | [Live evidence](android-build-evidence.json): attempt 07 succeeded, exit 0; APK 263720252 bytes; ZIP/manifest/classes and SHA-256 verified again without rebuilding | Complete |

Native build is an explicit operator capability, NOT filesystem sandbox or an agent shell. Foreground CLI owns the fixed process recipe; no automatic product repairs or detached build recovery. Existing worker container authority unchanged. Interventions retained: attempt 01 hit Windows path length; 02 missing PATHEXT environment; 03 reached Flutter and failed unpinned hmscore resolution; 04 local repository matching missed an SSH remote; 05 pinned hmscore but exposed override preservation bug; 06 retains original overrides and builds with base `436226fb7d4ad16686429dc77ed6a2ff815f2d4e` and hmscore `100a7800ae9b9e6766563e583f7634ceb809169b` (1.0.12). Attempt 06 reached Gradle/Dart compilation and failed because hmscore used `storageId` absent from the lockfile base revision. The selected as-of policy now also selects local moving-ref Git dependencies (while preserving explicit pubspec SHAs); attempt 07 uses base `ecac13a669c5b768f72609c1c98e2c3a64ec7ab3` and the same hmscore, both 1.0.12. Seven Android tests pass after this correction, including local as-of selection superseding an older lockfile revision and retaining original overrides. These are seven bounded build attempts, not seven model calls; branch task remains 42 managed model calls. No source checkout/reset/push, SDK installation, or license acceptance. Attempt 07 ran 06:52:01–07:03:18 UTC (Gradle 638.2 seconds) and produced APK SHA-256 `83bb80cd349f85d91497ff3b2f8ed709e9a4b2da1ca50bfd80696507c7c356a7`. Original app source remains at its historical commit in the export; build-only dependency overrides and Flutter SDK migrations are confined to that export. APK has not been installed or exercised on an Android device; user UI acceptance is separate. Native Java build children had exited after completion. This completes the requested build artifact, not device validation or an unassisted autonomy claim. Native SDK discovery alone did not prove build impossibility.

## Runtime-owned execution — SPEC-007 / revision 3

Baseline `ab25eeb`. CTS audit/delivery were assisted: chat host selected files, gathered evidence and wrote task-local adapters. Their successful receipts do not complete OE requirements. Current iteration 1; proposal `specs/SPEC-007-owned-execution.md`, plan `docs/owned-execution.vi.md`.

| ID | Requirement | Implementation evidence | Test evidence | Status |
|---|---|---|---|---|
| OE01 | Natural goal intake, no prepared profile/spec/file set | owned_intake.py, owned_cli.py; dc5c940 | Five intake/CLI/discovery tests, duplicate/conflict and queued output | Complete |
| OE02 | Policy-bound dynamic discovery/read/search | discovery.py; root/cursor/credential/link rules, persisted inventory | Nested discovery, pagination, escape/content tests; live agent-selected reads | Complete |
| OE03 | Runtime owns generic observe/act loop | owned.py; durable response, frozen invocation context, receipts, plan, bounded retry/no-progress | Fake/live workers; replay without new model; final evidence review rejection; original/candidate distinction | Complete |
| OE04 | Isolated candidate edits and tests | Dynamic snapshots; original tests immutable; ContainerGate; exact snapshot gate | Fixture and live fail→repair→pass; stale test rejection; partial-state rollback; source preserved | Complete |
| OE05 | Reusable Git delivery and completion receipts | owned_git.py; sealed remote, temp index, new-ref lease, action journal, final ref observation | Real bare remote; candidate bytes, tracked deletion, source race, lost ack and runtime resume without duplicate model/effect | Complete |
| OE06 | Background/inbox/recovery | Existing runner mode dispatch, entry context and request consumption | Native detached pause/cancel; question/reply/restart; unknown-effect replay; live runners stop after completion | Complete |
| OE07 | Three tasks without host-prepared evidence/adapters | tests/live_owned.py and read-only evidence collector | [Live evidence](owned-execution-evidence.json): audit 7 calls, change 9 calls, delivery 7 calls; final runtime audit 11 calls | Complete |

Cycle 1: dc5c940. Cycle 2 committed as `4983005`; runtime/tools/delivery implementation; full regression **267 tests pass in 324.012s**. The final queued-output CLI guard and fifth intake test pass separately (five intake tests, 0.837s). Subsequent changes are the queued-output guard and the Git optional-index guard documented below. Sixteen owned-runtime tests cover regular, failed, ambiguous and resumed execution. A final Git read-only guard additionally disables optional index refresh writes; its dedicated case compares exact index bytes after a file stat change. The resulting 17-test owned suite is validated separately; no further live calls. Documentation links/fences and SPEC-007 parse pass. The earlier full suite passed 259 tests; direct package invocation of two legacy suites initially failed because their historical test_workflow import requires discovery, subsequently corrected without product/test weakening.

Complete 7, Partial 0, Missing 0, Blocked 0; OE01–OE07 milestone verified within the documented capability envelope. This is bounded OE coverage, not all OC/LR requirements. Native full access, additional sandbox frameworks, authenticated native entry, routing/KB and eight-hour soak remain outside this milestone. No SRM/source task was used as an implementation sandbox.

Cycle 3 / OE07: read-only evidence collector independently confirms original source preservation, fail→repair→pass candidate, exact remote commit and excluded unrelated file. **51/60 managed calls** across all six live trials, **373251 observed total tokens** (cached input is included, not added twice). Initial audit/change reports were rejected during development despite completed execution; corrected trials and a final-runtime audit passed evidence review. No host prepared file list, evidence or plan and no task-time host intervention in accepted runs. Local Git remote only, not GitHub-network authentication. Live Python tests ran in the pinned Linux container. Final audit validates the runtime after durability fixes; those fixes also pass deterministic regression. Native process runner survived the submitting CLI and stopped after completion/cancel. User real task remains unassigned as requested.

## Portable local entry context — EC01–EC03

Baseline `80a542b` (WT01–WT03 committed). EC01 Complete: read-only bounded packet from one ledger transaction, pinned/amended spec, current task budget/worker, plan/progress/output refs and pending question revisions. EC02 Complete: proposal/decision notes persist with revision CAS, idempotent request IDs, actor/source attribution and no execution authority; restart preserves notes without dispatch. EC03 Complete: CLI connect/note, readable view, bounded recent answers/notes and detail cursors; documentation distinguishes chat continuation from worker switching and explicit amendments.

Implementation: `entry.py`, `entry_cli.py`, CLI routing. Seven focused tests cover persistence, stale/conflicting writes, concurrent entry decisions, project isolation, read-only/no-dispatch behavior, bounded results and CLI. Nineteen ledger and 24 spec regression tests pass. These slices support OC01/OC06/T18; authenticated native entry integration and the LR02 lesson lifecycle remain incomplete. Zero live model calls; user will describe the real trial task.

## Bounded worker tools through the core — WT01–WT03

Baseline `92ac908`. WT01 Complete: sealed read/search/check policy, explicit grant, scoped immutable files, owned candidate edits and normal final artifact gates. WT02 Complete: durable tool intent/receipts, task-wide cap and identical-request stop; restart resumes readonly tools without another model call, cancellation discards late results, and handoff/amendment/reorder cannot invalidate pending intent. WT03 Complete: bounded tool results, CLI status/output receipts and operator guide. Implementation: `worker_tools.py`, workflow and mutation guards; eight focused tests. Full regression: 240 tests pass in 206.036 seconds before the final reorder guard; eight tools and eight triage tests pass after the final guards.

[Docker evidence](worker-tools-evidence.json) verifies candidate check and final checks with deterministic workers, zero live model calls, unchanged original source and acceptance pending. Native provider shell/browser/MCP remain disabled. Serial profiles only; live model-selected tools remain unverified until the user's real task. This closes a bounded tool transport slice, not all OC04/OC11 or the learning/routing backlog. [Guide](worker-tools.vi.md).

## Model selection, knowledge and outcome learning — proposal addendum 09/10/2026

Baseline `fc01c35`. User requested recording the discussion into OneCrew documentation. Architecture 9.1–9.3, SPEC-006 LR01–LR05, backlog T31–T35 and routing guide now define the intended learning loop. This cycle changes documentation only; it does not enable tools, automatic routing, JEV decisions, a knowledge service or new model calls.

| ID | Parent requirements | Intended implementation | Existing evidence / gap | Status |
|---|---|---|---|---|
| LR01 | OC09, OC10 | Versioned route/outcome records across all attempts and costs | Ledger/usage records exist; normalized task features, decision evidence and full outcome record remain | Partial |
| LR02 | OC06, OC12 | Project knowledge and evidence-backed lessons with lifecycle and scoped retrieval | No implemented lesson promotion/retrieval contract; snapshots are supporting evidence only | Missing |
| LR03 | OC02, OC10 | Outcome evaluation and evidence-based failure attribution | AC/gates/review exist; structured root-cause evaluation and route effectiveness scoring remain | Partial |
| LR04 | OC10, OC12 | Representative benchmark, held-out validation, policy promotion and rollback | No calibrated policy lifecycle or comparative evaluation suite | Missing |
| LR05 | OC06, OC09, OC10 | Validated reuse before invocation; bounded JEV shadow evaluation | JEV connectivity only; no task-reuse validity or routing benchmark loop | Missing |

These five slices elaborate existing OC groups; they are not added to the 12-group aggregate counts below. Passing rule tests does not establish optimal model selection. Measurements must retain uncertainty, failed attempts, internal turns and project/configuration context. New acceptance cases are planned, not executed. Validation: SPEC-006 parses with a 324/350-word brief; six documents pass local-link/fence checks; all five IDs have architecture/spec/backlog mappings and the routing guide links the LR01–LR05 range. An initial overly strict validator expected each ID literally in the range-only guide; corrected validation passes without weakening document requirements. No runtime tests or model calls were needed for this documentation-only change. Proposal changes committed as `f567d62`; this coverage update records implementation gaps separately. Live-provider milestone committed as `fc01c35`.

## Claude subscription execution, checkpoint handoff and cancellation

Baseline `8506028`; [live evidence](claude-live-evidence.json), native Windows Claude Code 2.1.286, subscription auth. CL02 Complete: Claude Haiku generated a bounded timesheet function from an operator-supplied plan; final snapshot passes four functional Docker tests plus an exact documentation check. CL03 Complete: restart and Claude→Codex handoff preserve snapshot, deadline, previous calls and original source; final execution completed, verification passed, acceptance pending. CL04 Complete: a separate native Claude invocation was cancelled while running; supervisor confirmed tree stopped, worker identity dead, attempt settled and its used call retained.

Total: three managed calls (two for task/handoff, one for cancellation), zero retries. Claude reported three internal turns in its one implementation invocation; internal model-call cap remains unsupported. Cancel evidence covers local process termination, not server-side rollback/refund. Six subscription, four provider and 17 workflow tests pass after evidence registration. No claim of Claude planning, authenticated entry, full crash-transition coverage or eight-hour soak. Earlier no-login evidence remains historical and is superseded by this successful CLI login/trial. Diagnostic cycle committed as `8506028`.

## Claude CLI authentication diagnostics

Baseline `fa0f4ef`. CL01 Complete: doctor identifies the actual native executable and subscription login argv, distinguishes Desktop/browser login from CLI authentication, rejects malformed/non-object auth payloads and never returns auth payload identities/tokens. Six subscription tests, four provider tests and five quota tests pass. Direct normal/clean/restricted/safe/worker probes on 2026-10-09 all reported no CLI login; user confirmed the earlier login was Desktop/browser and is now logging into Claude Code. Claude execution/cancellation/handoff verification remains Blocked until CLI authentication succeeds. No model calls in this diagnostic cycle.

## Confirmed cancellation across a fixed goal group

Baseline `f19a489`; [CLI behavior](goal-budget.vi.md). GC01 Complete: cancelling an approved group's owner atomically marks every member across projects; member-only cancellation remains local and duplicate cancellation does not reset reservations. GC02 Complete: owner status, task connect, runner outcome and human status retain cancelling while any member attempt is reserved/running/unknown. Final settlement is required before reporting cancelled.

Ten focused goal tests pass, including a real native Windows worker in the other project, unknown state across restart, no new admission, rollback, local-only cancellation and the work cancel CLI. Three runner and two readable-view tests pass after final CLI/status changes. Full regression: 229 tests pass in 219.613 seconds; the subsequently added CLI case and final runner/view changes pass the focused tests above. No model calls were made. Subscription admission cycle committed as `f19a489`.

## Subscription admission and worker environment

Baseline `0e58aab`; [contract](subscription-auth.vi.md). SA01 Complete: pinned Codex now requires confirmed ChatGPT login; Claude requires a successful subscription auth receipt using the same restricted settings as its worker. SA02 Complete: worker and quota child environments remove API credentials/provider overrides without modifying user settings, Codex pins ChatGPT/OpenAI and Claude preserves OAuth-compatible restricted/safe mode. Managed policy remains authoritative; this does not independently disable subscription Extra Usage.

Four subscription tests, four provider tests, five quota tests and 18 native control tests pass. Read-only live probes on 2026-10-09 confirm Codex subscription and quota (zero model calls); Claude unavailable because authentication is absent. Claude live remains Blocked. Prior full regression: 222 tests pass. Commit-vector cycle committed as `0e58aab`.

## Multi-repository commit-vector verification

Baseline `0e49852`; [contract](commit-vector.vi.md).

| ID | Requirement | Evidence | Verification | Status |
|---|---|---|---|---|
| CV01 | Bind an exact approved goal set to verified Git delivery commits and immutable scoped bytes | vector.verify_vector, task locks, receipt/ref/tree checks, combined snapshot | four focused real-Git fixture tests pass; native Docker positive trial | Complete |
| CV02 | Verify a sealed readonly compatibility test before certifying the vector; independent pass is insufficient | container_test contract, refs checked after gate, durable vector receipt and output history | native Docker negative trial: each repo passes alone, combined contract fails; mid-gate ref race fixture | Complete |
| CV03 | Reuse immutable successful evidence only while current task/delivery/refs match; no cross-repo ref mutation or automatic acceptance | recipe hash and cached receipt checks, refs_updated=false and acceptance pending | duplicate request runs gate once; stale snapshot/missing member/unverified delivery/owned-test rejection | Complete |

[Native Git/Docker evidence](commit-vector-evidence.json) contains one passing and one failing vector, with source prepared by deterministic fixture workers; zero live model calls. It is not evidence of AI automatically decomposing a multi-repo feature. Both gate containers were cleaned. Full regression: 222 tests pass in 453.524 seconds. No atomic multi-repo publish or automatic acceptance is claimed.

## Usage identity correction

Baseline `f5140ec`. US02 Complete: receipt dedup uses the verified attempt ID, while repeated equal counters inside one receipt remain unknown without a verified provider event/session identity. This avoids silently undercounting distinct turns that happen to consume equal amounts. The earlier US01 counter-value dedup assumption is superseded by this stricter rule. Four usage tests, two CLI view tests and four provider parser tests pass; no model calls. Full 217-test regression passed before this isolated summary correction. Goal-budget milestone committed as `f5140ec`.

## Fixed cross-project goal budgets

Baseline `bf2fc13`; [guide and boundaries](goal-budget.vi.md).

| ID | Requirement | Evidence | Verification | Status |
|---|---|---|---|---|
| GB01 | A reviewed fixed task set shares finite calls without erasing prior local counters | goal_budget create/group, transactional Control admission across one ledger | two-project race, prior spend, unknown holds and restart tests | Complete |
| GB02 | Preserve every local grant and enforce earliest applicable deadline; no regroup/reset shortcut | budget current/remaining, immutable group event, owner grant and earliest submission checks | stale/project/active/overlap/cap rejection, reserve/launch deadline, rollback, local extension cannot increase group | Complete |
| GB03 | Expose lineage/remaining calls and prevent misleading retry offers | ledger root_task_id/group, work status, triage/branch/feedback remaining checks | exhausted shared goal offers inspect with zero remaining calls; no worker invocation | Complete |

Six focused fixture tests pass; full regression: 217 tests pass in 290.366 seconds. No model calls. This is an immutable budget grouping, not a cross-repo scheduler; each task retains its own pause/cancel/worker and scope. Adding members/group extension, cross-repo DAG and compatibility vectors remain separate. Target integration milestone committed as `bf2fc13`.

## Verified local target integration

Baseline `5b77dcc`; [guide](target-integration.vi.md).

| ID | Requirement | Evidence | Verification | Status |
|---|---|---|---|---|
| IM01 | Merge scoped candidate against known descendant target without touching checkout/index or losing target files | merge.entry/merge, dedicated Git index, whole-file three-way and explicit parents | real Git fixture retains target-only file and staged/unstaged bytes | Complete |
| IM02 | Test actual merged tree before CAS; preserve conflicts and stale-target evidence | immutable gate_snapshot, sealed container-entry check, expected-ref update | actual text gate fails on target contract change; conflict paths stored; target changed during test rejected | Complete |
| IM03 | Refuse checked-out/cancelled delivery and reconcile lost update acknowledgment without replay | worktree target guard, action broker exact-ref observe, output integration history | cancellation/checked-out guard and lost-ack Git fixture | Complete |

Seven focused real-Git tests and the full 211-test suite pass (94.857 seconds), including the final source-race guard. No model calls. This is conservative single-repo integration; line-level conflict resolution/rebase and multi-repo vector/compatibility gates remain. External Git checkout operations are outside OneCrew's task locks. Quota/usage milestone committed as `5b77dcc`.

## Transactional account quota admission and observed usage

Baseline `f00e5dc`; [limits and operation](account-reservations.vi.md).

| ID | Requirement | Evidence | Verification | Status |
|---|---|---|---|---|
| QB01 | Optional current-worker binding reserves account windows with root admission across one ledger | quota_budget bind/reserve, Control transaction and prelaunch checks, serial/parallel operations | concurrent roots only one admitted; real workflow fixture creates three reservations; failed checkpoint rollback | Complete |
| QB02 | Preserve uncertain/charged estimates, require fresh windows and prevent mapping-reset shortcuts | state binding history, settled/refund checks and conservative cross-reset handling | known-not-started refund, unknown/settled holds, launch expiry, old-window reset and pinned aliases/windows | Complete |
| US01 | Deduplicate observed attempt receipts and avoid adding cached input twice | usage.record/summarize, serial/parallel result paths, CLI status/output | replay vs distinct attempts, conflicting/missing/cumulative unknown, token types and separate Kiro credits | Complete |

Focused tests: six account-admission and three usage cases. Full suite: 204 tests pass in 85.139 seconds. No model calls. Optional alias/bucket mapping is local operator input, not authenticated account identity; all participating projects must share ledger/mapping. Estimates are intentionally conservative and can double-reserve spend already reflected by a fresh observation. Cross-reset unknown usage remains held. General cumulative event settlement and automatic routing remain Partial. Review-correction milestone committed as `f00e5dc`.

## Scoped review corrections and current-status reconciliation

Baseline `9751b6d`; [guide](review-corrections.vi.md).

| ID | Requirement | Evidence | Verification | Status |
|---|---|---|---|---|
| RF01 | Request a bounded correction before the entire task finishes, preserving independent output | feedback.request_changes, scoped repair prompt/schema, continue unfinished DAG | partial config correction then doc; completed sibling bytes retained; dependency closure | Complete |
| RF02 | Bind review/workflow revisions and idempotency; preserve existing scope, gates and budgets | request hash, reviewed bytes check, repair/root/deadline guards, stale output invalidation | dedup/conflict, stale source, scope escape, unchanged gate failure, cancel/unknown, exhausted cap, rollback | Complete |
| RF03 | Resume a settled correction receipt without another call and prohibit bypass by recheck/amend | durable feedback_repair and checkpoint, existing attempt recovery, verification/acceptance guard | crash-after-receipt fixture calls unchanged; correction remains pending until processed | Complete |

Seven focused tests and full 195-test suite pass (66.596 seconds). No new live model calls. Human comments may be saved while a sibling runs; scheduling a source correction requires a settled checkpoint and local operator authority. Semantic scope is still governed by sealed requirements/gates, not guaranteed by path allowlists alone. Quota feed is committed as `9751b6d`. README/spec status/backlog/architecture current-state notes were reconciled with code; historical cycle evidence remains unchanged.

## Read-only Codex quota feed

Baseline `2a7a0cf`; [guide and timestamped live observation](quota-feed.vi.md).

| ID | Requirement | Evidence | Verification | Status |
|---|---|---|---|---|
| QF01 | Read subscription quota without starting a model turn, reset consumption, credentials export or paid API fallback | quota.ReadOnlyRPC allowlist and codex account handshake, provider quota CLI | live Codex 0.160.0 read; fixture verifies method sequence and API-key rejection | Complete |
| QF02 | Prefer bucket map, preserve unknown windows and reject stale/missing/blocked quota | normalize/routing_quota, existing choose policy | five focused tests including weekly exhaustion, strict types, stale observation and invalid timestamp | Complete |

Full regression: 188 tests pass in 62.402 seconds. This closes the read-only feed slice only; OC10 remains Partial pending atomic account reservations, usage dedup and bounded automatic routing. No model calls in this cycle. Previous branch-wait milestone committed as `2a7a0cf`.

## Branch-local waiting and reply consumption

Baseline `a24ea54`; [guide](branch-inbox.vi.md).

| ID | Requirement | Evidence | Verification | Status |
|---|---|---|---|---|
| BI01 | Failed DAG unit blocks affected dependencies/owners while independent ready units continue | branch_inbox, unit-scoped admission/launch, parallel failure records | A→(B,C)→D plus C→E: B/D wait, C/E complete under one root | Complete |
| BI02 | Durable branch reply resumes only after stop/reconcile and within shared root limits | plan/failure/budget-bound question, atomic checkpoint/effect, no-progress/cap guard | restart/reply exactly one retry; unknown writer retains slot and prevents duplicate; second failure offers inspect | Complete |
| BI03 | Background wait spends no model calls and global questions retain authority | runner wait state, blocks root/scheduler/unit distinctions | pending polls unchanged calls; background reply then completion; global question blocks E | Complete |

Five branch tests pass in 2.238 seconds and existing five DAG tests pass. Full suite: 183 tests pass in 60.378 seconds. No new live model calls; fixture branch fault coverage is separate from earlier native Kiro parallel evidence. Local operator provenance remains; no claim of authenticated host reply. Amendment milestone is committed as `a24ea54`.

## Requirement amendment and dependent invalidation

Baseline `74bde44`; [guide](requirement-amendment.vi.md).

| ID | Requirement | Evidence | Verification | Status |
|---|---|---|---|---|
| AM01 | Explicit in-scope spec/profile revision invalidates selected/changed-AC descendants and overlapping owners | amendment.apply/affected_tasks; effective profile/spec used in serial/parallel and integration | A→(B,C)→D B/D rerun preserves A/C; mandatory changed check and overlap closure | Complete |
| AM02 | Keep counters, deadline, dirty source and immutable history; reject stale/running/user-source conflict | workflow lock/CAS, scope/cap guards, baseline capture/overlay, stale output/plan revisions | no counter reset, old acceptance/reorder rejection, running and user-edit guards, persistence rollback | Complete |
| AM03 | Refresh operator-owned readonly context and expose acknowledged amendment to another entry | refreshed baseline, ledger accepted_amendment, spec_for/profile_for | changed readonly contract survives snapshot and next worker prompt sees new spec | Complete |

Five focused tests pass in 3.338 seconds; full suite: 178 tests pass in 66.374 seconds. CLI amend help and Git whitespace checks pass. No live model calls in this cycle. Semantic dependencies absent from the graph still require operator-selected affected tasks; no new paths/AC IDs/tools or automatic budget extension. Branch-local waiting/triage remains separate. Prior review/live functional milestone committed as `74bde44`.

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
| OC02 | Planning | Spec and real repo to general plan | Functional | scope/AC planner, owned artifacts, functional container gates, in-scope amendment | WF01–WF03; live JSON and order/CSV functional trials; AM01–AM03 | Partial | Semantic ambiguity triage and full provenance across entry changes remain |
| OC03 | Core | Durable authority, recovery, one writer | Reliability | Control reservations/receipts, Job supervisor, workflow locks, detached runner | CB01–CB04 / WF02 / BG01; crash and lost-ack tests | Partial | Unidentified launch needs manual reconciliation; full transition coverage remains |
| OC04 | Workers | Replaceable verified adapters | API | Codex/Kiro/Claude artifact adapters with subscription admission | PA01–PA03 plus CL02–CL04 native Claude execution/cancel and Claude→Codex checkpoint handoff | Partial | Full provider fault/authority matrix and mid-write handoff remain |
| OC05 | Inbox | Durable requests and trusted revision replies | Security | durable request revisions, root/branch triage and atomic effect receipts | TI01–TI03, BI01–BI03; independent branches proceed while blockers wait | Partial | Reply effects reuse existing rights; authenticated cross-entry caller provenance remains |
| OC06 | Memory | Shared decisions/checkpoints/provenance | Data | ledger events, immutable spec/profile, content-addressed working/index snapshots | CP01–CP03 dirty/binary/deletion recovery; live handoff preserves source | Partial | Authenticated entry connectors, full transcript-free continuation and LR02 knowledge/lesson lifecycle remain |
| OC07 | DAG | Parallel dependency/ownership scheduling | Architecture | two disjoint units/global capacity, branch waits, amendment descendant/ownership invalidation | PD01–PD04 native parallel Kiro plus BI/AM fixture closures | Partial | Full parallel crash matrix and multi-repo execution remain |
| OC08 | Integration | Verified merged result across branches/repos | Testing | review branches, conservative target integration/CAS, explicit commit vectors and container compatibility gates | IB/IM/CV real-Git tests; native container branch and positive/negative multi-repo evidence | Partial | Automatic rebase/conflict repair and dynamic cross-repo integration orchestration remain |
| OC09 | Long jobs | Root budgets, recovery and optional 8h | Reliability | absolute max-8h grants, durable counters, finite extensions, fixed multi-project shared goal cap and confirmed group cancellation | CB/BG/CQ/BU/GB/GC tests; live handoff preserves deadline/counters | Partial | Eight-hour soak, authenticated grants and dynamic cross-repo goal orchestration remain |
| OC10 | Routing | Task/risk/capability plus account quota | Performance | typed recommendation, read-only Codex feed, opt-in transactional account estimates and attempt usage dedup | RP/QF/QB/US tests, timestamped feed probe | Partial | Authoritative cumulative settlement, automatic calibrated routing/fallback, Claude/Kiro feed and LR01–LR05 learning loop remain |
| OC11 | Review | Partial review, feedback and reorder | UI | readable cards, concurrent feedback, revision accept/reorder/pause and bounded corrections | WF04/PD02/RV01/RF01–RF03; B feedback while C runs | Partial | Full authenticated multi-entry and multi-repo review/integration evidence remain |
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

## Solution delivery V1 — approved 2026-10-11

Proposal source: `docs/solution-delivery-approved.json`, SOL-1009292296e1485ebd645a874042eb13,
revision `5864e6c9497efb7a8dea18dac0bc2ee5dbb98ec9f2a916fdb70b9fe4c1a7fe32`,
actual user decision DEC-cdf0a630869d4165b2ccc4ca4055492e. Base: `3c3de4a`.
Implementation by Codex entry in an isolated worktree; not a claim that OneCrew built itself.

| ID | Requirement | Implementation evidence | Verification evidence | Status | Limits |
|---|---|---|---|---|---|
| SD01 | Durable parent/children/sealed DAG | solution_delivery.py, delivery_plan.py, delivery_store.py | Idempotent submit, restart, child lifecycle integration fixture | Complete | Serial Flutter changes; no session-memory scheduler |
| SD02 | One root budget/deadline | goal_budget.py, owned_intake.py, control.py, effort_watch.py | Concurrent reservations for last slot; aggregate charges; pause/cancel and pre-enable crash tests | Complete | No automatic extension; effort-warning remains a real decision |
| SD03 | Required AC and provenance gates | solution_delivery.py, structured review in delivery_steps.py | Missing/stale receipt and conditional acceptance rejected; source/tool drift tests | Complete | AI semantics remain fallible; objective receipts also mandatory |
| SD04 | Read-only regression and red/green evidence | capture/preflight/regression in delivery_steps.py | JSON counts/skip rejection, baseline package rebasing, full typed pipeline fixture | Complete | Behavioral red only when declared and reproduced; unsupported baseline seam blocks |
| SD05 | Private debug/release build and APK audit | delivery_steps.py build, delivery_android.py audit | Fixture release build, secret/log removal, signer/hash/size/ELF/ZIP checks | Blocked | Real build from a newly dispatched parent not yet exercised; optional version_code policy must be set when required |
| SD06 | Pinned device/scenario/cleanup | delivery_android.py | Fixture install/hash/assert/cleanup, wrong app/APK/scenario and unknown install rejection | Blocked | No physical A54/server dispatch grant for this runtime implementation; no live-device claim |
| SD07 | Bounded repair, invalidation and safe restart | solution_delivery.py, existing child timeout/cache policy | Repair history/cap/invalidation, unknown native operation cannot replay, clean workspace per build | Complete | Unknown effects, unconfigured cache/runtime repairs hold for explicit reconciliation; never arbitrary self-patching |
| SD08 | Parent report and Windows outbox | delivery_steps.py handover, desktop_notifications.py, delivery status | Parent handover fixture; child suppression and existing standalone/dedup tests | Complete | Technical AC verification, user product acceptance and Windows receipt are distinct; no exactly-once crash guarantee |
| SD09 | Opt-in compatibility and entry transfer | additive backed-up lineage tables; delivery_cli.py; mcp_entry.py | Migration backup, legacy suites, read-only MCP does not launch; example schema validates | Complete | Existing task evidence is not imported as a passing gate; old jobs stay independent |
| SD10 | End-to-end validation, including live known case | tests/test_solution_delivery.py, tests/test_delivery_android.py | Full parent → native child apply → regression → review → release → APK audit → device → report fixture; crash/concurrency/security tests | Blocked | Provider/Flutter/ADB are explicit test doubles; A54 pilot requires a separate pinned dispatch and an idle device |

Current validation: 40 delivery tests passed; 70 adjacent legacy tests passed
(goal budget, solution gate, intake, desktop notifications, MCP, effort warning, runner).
Full repository suite: 649 tests, OK with 1 environment skip (no venv redirector),
352.609 seconds. Subsequent focused hardening is verified by the current 40 delivery tests.
An existing monitor test failed on both baseline and branch when the installed Codex
capability was unavailable; its provider is now a fixture while dispatch assertions remain.
Verified acceptance rows: 7 Complete / 10 = 70%; 3 Blocked on live verification.
This is not an unqualified full-proposal or production-readiness claim.

Implementation cycle 1 covers the connected SD01–SD09 runtime contracts plus fixture SD10.
The stages share imports/admission state and are committed together as one tested change.
Cycle 2 validates compatibility, integrates without overwriting concurrent entry work, and
records handover/remaining live pilot. No current product task, APK, phone or server is restarted.
Cycle 1 commit: `54c6653`. Cycle 2 also seals foreground/viewport input, bounded manifest
storage, unchanged-wait checkpoint deduplication, stage grants and outcome-specific Windows receipts.


## Eval-driven evidence — 12/10/2026

Proposal: [eval-plan.vi.md](eval-plan.vi.md). Iteration 3; baseline runtime `4e8253f`; harness `d24cc52`.

| ID | Requirement | Type | Implementation evidence | Verification evidence | Status | Notes |
|---|---|---|---|---|---|---|
| EV01 | Versioned historical corpus | Data | onecrew/eval_corpus.py | Catalog selectors verified; 20 pinned probes | Complete | Known-case, never held-out |
| EV02 | Pinned isolated replay | Reliability | evaluation.py / eval_probe.py | Isolated real subprocess/git before-after tests | Complete | No product dispatch |
| EV03 | Comparable before/after grading | Testing | evaluation.compare | Reject mismatched/partial/tampered/duplicate/skip results | Complete | Missing/skip distinct |
| EV04 | Read-only real task observations | Observability | eval_observe.py | Read-only DB, unknown assistance, stale receipts, privacy tests | Complete | Unknown is not unassisted |
| EV05 | Evidence reports and conservative promotion | Functional | CLI eval; docs/evals.vi.md | 113 related tests passed; CLI help checked | Complete | No automatic skill/routing mutation |
| EV06 | Run paired historical cases and observe real tasks | Testing | docs/eval-results/2026-10-12/REPORT.vi.md and 6 digest-verified JSON artifacts | 60 case-trials / 120 probe executions; 4 real tasks observed read-only | Complete | 6/10 to 10/10 release cases; history 2 reproduced bugs + 8 unavailable APIs |
| EV07 | Held-out/live autonomy measurement | Testing | docs/evals.vi.md live protocol and assistance recording | No equivalent pinned live dispatch/held-out corpus | Blocked | Fixtures cannot satisfy this requirement; product_autonomy_rate=null |

Verified coverage: 6/7 (85.7%); EV07 live/held-out Blocked. No claim of complete product autonomy evaluation.

Cycle 1: 113 tests passed in 28.258 seconds. No product tasks/devices were run.

Cycle 1 commit: `fb14591`. First replay exposed a Windows Store executable-alias fingerprint error before any probe; no result scored. Fixed to hash the installed interpreter; 22 eval tests pass, including the alias regression.

Cycle 2: isolated USERPROFILE/temp storage and short scratch paths; expected-failure/import-origin guards; idempotent assistance notes and parent/child call/assistance aggregation. 118 related tests passed (33.727s), then all 28 eval tests passed (6.079s) after the intervention reader additions. Initial valid replay measured 6/10 to 10/10 runtime cases twice; final frozen harness rerun pending.

Cycle 3: code `d24cc52`, harness identical on each side. Final historical run `1db6e59f95374f5ca9bfed8ff4f9f785`, release-before `517c537c2c3f4164a8d4684d4a4a0b5f`, after `a3220f670ef448f79fa9aea5f439fd67`. Runtime after: 20/20 case-trials; release before: 12/20 with 8 unavailable; historical before: 2 errors + 2 assertion failures + 16 unavailable. Not a product autonomy rate. Four completed task records: 2 with known assistance, 2 unknown; physical verification is entry evidence. Final 120 tests pass (39.662s), six JSON digests and both comparison recomputations verified. Failed preliminary harness runs retained separately, excluded from final comparisons. No product dispatch, no model calls, no live ADB/server, no push.

WF preservation note: the long pre-extraction v1 run had 113/114 passes; existing P6 tight prompt-cap assertion failed before extraction (824 vs1000 minimum page). The finding-register 26-before/26-after subset passed. This unrelated baseline failure is retained, not hidden or scored as a pass.
