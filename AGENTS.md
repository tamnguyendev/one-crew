# OneCrew entry contract

## Delivery autopilot — 12/10/2026

For new aggregate work, agree requirement, scope, acceptance, stages, device permission
window and budget with the user, then record them as a typed `envelope` inside the solution
payload (docs/delivery-autopilot.vi.md). Approving that SOL revision approves the envelope.
Dispatch at goal level: `delivery submit --solution SOL --revision REV --goal "..." --key K
--start`. Do not write the plan, recipes, owned files, tests, red patterns, SDK paths, signer
or scenario: OneCrew discovers the environment, plans inside the envelope, recovers technical
failures within the grant and asks one typed request when a user decision is needed. Answer
that request (`request reply`); the runtime continues by itself, so do not call `delivery
resume` for it. Mutating CLI/MCP commands are recorded as interventions automatically; set
`ONECREW_ACTOR=claude|codex|user` in the entry shell. When relaying the user's answer or SOL
approval pass `--decided-by user --user-quote "<their words>"` (only a hash is stored); a decision
the entry makes itself is undelegated unless a recorded `delegation grant` covers its class and time
(docs/autonomy-measurement.vi.md). Entry-written plans remain supported
and must fit the envelope when the SOL has one. Never widen the envelope on the user's behalf.

## Evidence-driven changes — 12/10/2026

For runtime/recipe/skill improvements, use `eval cases/replay/compare` as documented
in `docs/evals.vi.md`. Pin the same harness and environment for before/after; retain
failures, skips and unavailable APIs. Do not count fixture gates as product autonomy
or claim held-out performance on the known historical corpus. Use `eval observe`
for selected real task evidence; unknown assistance stays unknown. No eval result
automatically approves skills, routing, budget changes or device/server dispatch.
Add a recurring real failure to the corpus with its oracle and provenance; rerun
both sides if the oracle changes. Keep product execution with its existing parent.
Record actual entry interventions with `eval assistance` (actor/category/reason and
an idempotent key on the affected task); this only records evidence, never grants
execution authority. Parent observations aggregate child calls and assistance.

## Solution delivery V1 — opt-in 11/10/2026

For a new approved solution whose goal includes child implementation, aggregate tests,
review, APK build and device E2E, use the parent `delivery submit --file ... --start`
workflow described in `docs/solution-delivery.vi.md` and `examples/solution-delivery.json`.
Pin the actual solution revision, source baseline, write envelope, immutable regression
tests, private references, signer, package, serial and typed scenario before dispatch.
One parent owns child creation and the shared budget; the entry must not manually
chain independent jobs or build/install on its behalf and then call it autonomous.
Read/resume the same parent ID through `delivery status/resume` or MCP status/outputs/
inbox/resume. Never reset its budget, reparent old jobs or consume unanswered questions.
Keep the chat heartbeat paused. Use the existing event-driven Windows channel; root
notices replace child notices. A changed entry/session does not change execution ownership.
Standalone jobs retain their existing CLI and behavior. The new end-to-end path has
fixture coverage; do not claim a live A54/server pilot until that parent has real receipts.

## Overnight authority — night of 10–11/10/2026

For completing the Cloud Auth work assigned in this conversation, the user has
delegated approvals to the entry for tonight and requested a written record for
morning review. This supersedes the requirement below to ask again about decisions
within that assigned work during this night. Record each actual approval with its
reason, scope, evidence, consequences and user-authorization provenance. Do not
represent delegated approval as the user having personally reviewed that decision.
Keep changes recoverable, retain failure evidence and report verification gaps.
This does not require restarting completed jobs or reviving superseded UI baselines.

## Delegated completion — user authorization 10/10/2026

For the current Cloud Auth old-UI task, the user authorizes the entry to coordinate
OneCrew through completion, repair runtime/environment blockers and approve routine
technical recovery without asking again. Preserve candidate, tests, review, prior
failure evidence and the existing budget. OneCrew owns product execution and APK
handoff. Escalate business decisions or architecture changes; this is not authority
to weaken acceptance, reset budgets, publish externally or discard user changes.
Keep the recurring chat scheduler paused and use the existing Windows result channel.

## Windows result channel — user selected 10/10/2026

The user chose a OneCrew Windows window as the replacement for recurring chat reminders. See `docs/desktop-notifications.vi.md`. `desktop enable` is configured for the real state-root; workflow checkpoint hooks show completion or actionable blockers once, with durable reports/receipts on D:. Keep the Codex heartbeat PAUSED on dispatch/resume. `desktop status` inspects delivery; `desktop show --task` uses the same deduplication for an existing result. Do not retry an ambiguous delivery without an explicit need; a mapped window is not proof of user attention. Closing a window never answers, approves or resumes a task. No direct runner-to-chat callback exists. This section supersedes the scheduler activation instructions below.

## Notification preference override — 10/10/2026 15:52 Asia/Saigon

The user rejected repeated scheduled chat checks because the prompts were visible but results were easy to miss. The existing `onecrew-k-t-qu-v-c-u-h-i` heartbeat is PAUSED at the user's request. Do not automatically reactivate it on dispatch/resume under the older rules below. Desired delivery is one clear result at completion, or one actionable blocker/question when intervention is necessary; no repeated idle/status reminders. The existing receipt verifies chat history only, not visible app/OS notification or user attention. A direct runner-to-chat completion callback is not implemented; do not promise automatic delivery without a supported and verified transport. Preserve pending questions and evidence; disabling the schedule does not answer, cancel or resume a task. This preference supersedes the automatic heartbeat activation steps below until the user chooses a replacement.

For user-assigned OneCrew jobs (including work in other repositories), the chat is an entry/review surface; OneCrew owns execution.

- Discussion routing (revision 9): default to the assistant already answering in the current host; do not spawn another worker just to preserve the provider default. An actual user request to ask a provider/model pins that consultation only, not the next chat turn or implementation worker. Examples, quotes and mentions are not dispatch authorization. Auto/JEV selection requires an explicit applicable policy; never override user pins, infer quota, or silently use paid API fallback. Use `consultation submit --file <request.json> --start` or MCP consultation_submit; read the pinned result through CONV. See `docs/discussion-routing.vi.md`.

- Revision 8 architecture separates conversation (before tasks), versioned solution/approval, and execution tasks. Follow `docs/shared-conversation.vi.md` and `docs/architecture.vi.md` when implementing this design. Conversation CLI/MCP are implemented. Use conversation create/list/read/append, solution propose/review/approve, and consultation submit/show. Claude/Codex CLI live ACKs are verified; other hosts require connection evidence. Do not create fake execution tasks for discussion, import private chat histories, or claim sync without a durable ACK. Read/append operations must not implicitly launch workers.

- Entry is provider-neutral: the user may discuss, compare proposals and approve through Codex, Claude, Kiro or another connected tool. Codex is not a required intermediary or privileged approver. Keep one shared solution/task ID and revision; carry decisions and pending questions across entries without assuming access to private chat histories. Concurrent proposals must retain their base revision and provenance, not overwrite each other. Changing the discussion tool does not change the execution provider or authorize automatic cross-chat messaging. Report unsupported adapters honestly.

- Solution-first entry policy (user preference, 09/10/2026): for NEW implementation work, have OneCrew inspect and propose a concise solution before submitting a write-authorized job. Explain expected behavior/examples, approach, assumptions, scope and verification in the entry chat; record the user's actual approval of the current revision before implementation. Reuse a solution already explicitly approved; do not ask again for the same decision. Discussion alone is not approval. Existing authorized jobs are not retroactively paused by this policy. New write jobs require --solution-id/--solution-revision; admission and mutation gates enforce binding. See `docs/solution-approval.vi.md`.
- When implementation requires changing approved behavior, architecture/API/data contracts, scope or acceptance, preserve evidence and pause the affected work for a solution change request. Entry may clarify and recommend; it must not silently approve the change on the user's behalf. Routine implementation choices within the approved solution remain delegated. Unanswered required decisions stay pending; independent unaffected work may continue.
- For one feature, default to one implementation worker until shared contracts, dependencies, ownership and an early review milestone are clear. Do not split into parallel writers merely for speed. Never promise OneCrew can proactively wake Codex/chat until a host callback is implemented and verified.

- Submit a clarified goal with the authorized scope/budget. Use `job submit --start --terminal` or `job start --terminal`. Android builds default to background; use `--terminal`. Do not use `job run` or `android build --foreground` for a long job unless the user explicitly wants a foreground session.
- Read the bounded dispatch response and attach the task to this chat's bounded notification watch before ending the turn. See docs/notification-watch.vi.md: use a dedicated consumer, preserve previously attached active tasks, and update the existing host heartbeat through automation_update. Enable it only for dispatched tasks or undelivered notices; for a nonempty watch, only ACK after confirm-delivery validates a completed scheduled final through read_thread; then if should_pause=true, PAUSE it. A CLI runner cannot activate a Desktop schedule by itself. Report actual runner and bridge configuration separately. Do not poll a long job repeatedly in the same turn. On a status question, read once.
- A required decision/approval must be persisted with `request create` before displaying a chat question. Show the returned request ID and revision. User silence, timeout, a preselected option, a dismissed card, and a delivery acknowledgement are not answers. Use `request defer` to record dismissal and leave the request pending. Record only an actual user answer with `request reply` and its current revision/source/reference.
- Optional preferences may use an explicitly stated assumption within existing authority after allowing reasonable response time. Do not turn required approvals into optional questions. Independent work may continue only when it does not depend on the unanswered decision.
- When changing chat tools, use `entry connect` against the same project/state-root. Do not recreate the task or reset its budget. Expired deadlines need authorized extension before resume; no implicit extension while waiting.
- For a new job, honor the OneCrew `provider preference` in the shared state-root; an explicit user provider/model overrides it. A user-reported quota reset is a hint, not observed remaining quota. Jev recommendations are opt-in shadow proposals, never dispatch authority. Do not change models or reset budgets on existing jobs implicitly.
- Inspect `skills list/review` when a recurring-task candidate is surfaced. Approve/reject only from an actual operator decision at the reviewed revision. Candidate generation, a green test or a notification acknowledgement never grants skill approval. Skill guidance cannot expand task scope, tools or budget.
- A default owned job may inherit an operator-configured quota fallback chain at submission. Runtime may move forward only after a recognized native quota error and settled process, retaining scope, budget and checkpoints. This is preauthorized handoff, not permission for arbitrary model changes. Explicit provider/model jobs stay pinned; existing jobs never inherit later preference edits.
- Owned checkpoints/runner/build deliver events to a local file feed without model calls. Read `notifications feed` on demand; pending_batch/last_error exposes failed delivery. For this configured Codex chat use `notifications watch --consumer <chat-consumer> --all-projects --task TASK-ID` and ACK with the same task list. The bounded host heartbeat is enabled only for attached work/unread notices, then pauses when idle or awaiting an operator. It is scheduled checking, not an immediate callback; never reactivate unbounded idle polling or claim that plain CLI starts automatically enable the host schedule.
- Reading status/outputs/watch in an ordinary user turn NEVER confirms proactive delivery. For a nonempty watch, the scheduled turn calls begin-delivery and emits the exact returned message as its final answer without ACK/pause. A subsequent scheduled turn uses read_thread evidence with the matching heartbeat automation, target thread, final message ID and complete text; confirm-delivery records the receipt, then ACK/pause is allowed. Do not fabricate receipt JSON or count this maintenance turn as an automatic send. Missing receipt checks are bounded; uncertainty retains the batch. Explicit user-requested replay uses notifications redeliver without resetting the cursor.
- Closing the grouped monitor does not cancel execution. Use the explicit job/build cancellation command. Do not claim an unassisted run if the chat repaired infrastructure during it.
- New owned jobs use 100 calls / 7200 seconds unless explicitly overridden. The sealed budget policy v2 requests evidence review at 70% of calls or elapsed deadline window; old jobs retain 20 calls / 10 minutes. Historical budget advice remains advisory with evidence; proposed retrospectives are not approved skills. See docs/budget-learning-policy.vi.md. Effort warnings occur at a settled checkpoint. Show its REQ/revision/options. Continue resets only the warning baseline; pause requires explicit later resume; stop preserves evidence. Never auto-answer a warning from a previous blanket budget increase or from silence. Warnings use the local inbox/feed, not an idle Codex heartbeat.

Implementation contracts and evidence: `docs/background-handoff.vi.md`, `docs/proposal-coverage.md`. Preserve unrelated changes and use focused tests/commits. Do not push unless requested.
