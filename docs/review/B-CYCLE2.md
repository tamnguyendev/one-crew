# 2.5-B cycle 2 — one check lifecycle across the doors

Base `01b10e1`, branch `claude/r2-b`. A's identity comes from `review_request.build_check` (`claude/r2-a`). No new engine, ledger,
queue, store or reviewer system: the cycle-1 `review.run_*` events (class A) carry every check; `verdict.run` keeps its W37a/W44
records and shares the request id.

## 1. Map of the doors: keep / connect / add

| Door | Entry | Run record before this cycle | Duplicate protection before | Decision |
|---|---|---|---|---|
| Hook Stop | `hook_cli.stop` | reads the `active_plan` export (`waiting.run_in_progress` from `verdict.live_runs`) | never dispatches (reminder only) | KEEP as a reminder. CONNECT: it also sees running engine/candidate checks (`review_dispatch.active_checks`), lets the session go and names door + run. It never runs a check. |
| `verdict run` | `verdict.run` → `_begin_run` | `verdict.run_started/run_abandoned/receipt_issued`, markers, `run_reconciled/run_held/run_released` | same milestone + revision live → refused; passed → refused before the verifier; held → refused | KEEP all of it. CONNECT: `verdict.run_started` carries the milestone `request_id`, `request`, `candidate`; `_begin_run` refuses when the same request runs through another door. |
| `engine verify` | `engine.verify` | none | none: two calls ran the checker twice and could publish twice (red: 2 calls) | ADD: claim of the node request, result issued before publication, publication + end of run in one transaction. |
| `engine step --checks`, `engine batch --checks` | `engine._tools` → `engine.verify` | `workflow.mode` claimed/released (fence only among tools runs) | none against `engine verify` | KEEP the fence. CONNECT: goes through the same `verify` claim (door `engine.step-checks`); a pending/held answer is released as such. |
| CandidateChecker milestones | `common_verification.CandidateChecker` (from `engine.verify` and `common_handoff`) | none (only the metered provider call) | none against `verdict run` | ADD: one claim per milestone request on the candidate tree, atomically for all selected milestones, child of the node run. Reuses an authentic pass of the same request (no second model/command call). States the execution identity from the approved contract. |
| `review-optional` | `review_dispatch.optional` | `review.run_*` | yes (cycle 1) | KEEP. Same helpers; its rows have no `check` field and read as `optional`. |
| Recovery | none for engine checks | `verdict release-run` for the verdict door only | — | ADD `engine reconcile-check` / `engine release-check`: same rule as `verdict release-run` (recorded reason and actor, no budget reset, no exactly-once promise). |

## 2. What the door answers

`status`: `pending` (same request running, same `check_run.run_id`), `held` (unknown outcome, with `reason` and `next`), `late` (the
result arrived after a hold: kept as `review.run_result`, not published), `published` (completed from the issued receipt). A normal
`engine verify` still returns the `node-verifier-receipt` body, now with `check_run`.

## 3. Identity and reuse rules

- Node check request: `build_check(kind='node', review_id='node-verification', required=True, inputs=None)` (the v1 node descriptor).
  Milestone request: `build_check(kind='milestone')`, subject `{plan, milestone, candidate, plan_sha}`; the evidence dimensions come
  from the approved verifier config and `verification_evidence.environment(command.verifier_env(project))`.
- Execution identity is computed by the production port (`CandidateChecker.execution_identity`, `InvestigationChecker.execution_identity`,
  `review_dispatch._milestone_execution`), chosen by exact type in `engine._execution_of`. A look-alike or plain callable gets none:
  it can still run, its result is never reusable by identity. `independence` on a run row is always `not_established`; the actual
  judgement stays `reviewer.check_independence` on real producer pins, recorded in the reviewer receipt.
- In-flight: same work (`_work_key`: identity without execution/environment/configuration fingerprints) = observe. Another shell with a
  different TEMP is one piece of work while it runs.
- Reuse: exact request, `evidence_status == applies`, then the proof must pass `proof_mismatch` and `expected_result == pass`; a reused
  row is a new wrapper of the current node with `reused_from_run` / `reused_from_door`. A reviewer proof is reused only with the same producers and no
  weaker independence. Non-passing results are never reused (a recheck after a fail dispatches again).
- `verdict run` after a candidate pass on the same tree still dispatches: `record()` accepts only receipts `verdict.run` issued (F1). Kept on purpose, see limits.

## 4. Crash and recovery

| Situation | Result | Next step |
|---|---|---|
| Refused before any verifier (`NotDispatched`, `error.not_dispatched`) | run finished `not_dispatched`; the error or `pending` is returned | call again |
| Exception while the verifier ran, no receipt | `held`, also its unfinished child milestone claim | `engine release-check PLAN RUN --reason` |
| Process gone or past its deadline (twice the node cap + grace), no receipt | `held` at the next claim/reconcile, never replayed | same |
| Result issued, publication lost | next `engine verify` or `engine reconcile-check` publishes from that receipt; `check_run.reconciled` | none |
| Result arrives after the run was held | `late`: `review.run_result` kept, not published | `reconcile-check` publishes it if the request still matches, otherwise `stale` |
| Input/criteria/policy changed before publication | run finished `stale`, retained, no `node.verification` | new generation = new request |
| Release | `review.run_finished {outcome:'released', reason, actor, budget_reset:false}` | next call dispatches; used budget stays used, exactly-once is not promised |

Run ends are `review.run_finished` outcomes, so no new event kind was needed. The provider port keeps its own Control-attempt guard (`metered_verifier`).

## 5. What A can authenticate (`close_from_recheck`, `review_trace`)

Read with `review_dispatch.check_runs(ledger, selector)` or `review_dispatch.run_of_receipt(conn, task_id, receipt)`; both are read-only.

| Door | Result record | Receipt blob kind and binding fields |
|---|---|---|
| `engine.verify`, `engine.step-checks` | `review.run_finished {run_id, request_id, receipt, outcome:'published', applicable:true, door}`; `node.verification {receipt, run_id}` | `node-verifier-receipt`: `root, node, generation, artifact, internal_revision, checks_sha, result, observed.checks[{id,result,evidence}]` |
| `candidate` (child of a node run, or the handoff door) | `review.run_finished {outcome:'observed', proof, result}`; `subject {milestone, candidate, node}` | `command-receipt`, `reviewer-receipt`, adapter receipt: `milestone, revision, plan_sha, artifact_sha, artifact_sha_after` |
| `verdict.run` | `verdict.run_started {run_id, request_id, request, candidate}`, `verdict.receipt_issued {run_id, receipt}`, `verdict.recorded` | same receipt kinds |
| `optional` | `review.run_finished {receipt, applicable}` | `optional-review-observation`, `authority:'none'`: never a pass and must not close a finding |

An authentic recheck is a receipt returned by `run_of_receipt` with `outcome` `published`/`observed`/`recorded`, `request.id` equal to the request bound to the repaired output, and the blob's own result. Not authentic: a held, stale, released or not-dispatched run; `late` until reconciled.

## 6. Investigation review (RV-T6)

`engine review-optional PLAN NODE REVIEW --investigate config.json` uses `common_verification.InvestigationChecker` through the existing
optional door, so the review ID must be sealed in the approved `review_policy`.

- Config: `provider`, `model`, `question`, `paths` (1-20, validated by `survey_worker.validate`), optional `probes` (at most 5 argv lists), `max_minutes`.
- Read: only the named paths, only inside the node's `read` + `write`; credential paths are refused and credential-looking content is withheld (`source_tools`).
- Run: only with the contract's `commands` grant, through the Q4 decision, in a disposable checkout of the sealed tree, with `command.verifier_env`. Whatever a probe writes dies with that checkout.
- Judge: one metered call through `ProviderCall` (a verifier child task on the root budget, no owner contract). The provider has no tools: OneCrew reads and runs, the model judges that bounded evidence.
- Result: `optional-review-observation`, `authority:'none'`, `full_review:false`, `label`, what was read, withheld and not investigated, `independence` computed from actual producers or `not_established`.

Not done: an agent that chooses its own reads and commands. That needs a provider tool capability proven from the artifact first.

## 7. Evidence

Tests: `tests/test_review_b2_lifecycle.py`, `test_review_b2_candidate.py`, `test_review_b2_hook.py`, `test_review_b2_investigation.py`, `test_review_b2_e2e.py`. Wheel smoke:
`docs/review/verify_b2_wheel.py` (run on the final wheel by the integrating session; source run passed). Logs: `D:\OneCrewRuns\cycle2\b\logs` (`red-*` = base code).

Red on base `01b10e1`, behaviour failures:

| Case | Base result |
|---|---|
| Two `engine verify` on one node | checker ran 2 times |
| Same milestones on the same tree in two nodes | 6 executions instead of 3 |
| Result issued, publication lost | a second call ran the checker again |
| Unknown outcome, lost controller | a second call ran the checker again |
| Stop hook on a delivered workflow root | told the session to run `verdict run` |
| Two doors on one reviewer milestone | the command milestone ran twice and the second door got a raw "Verifier outcome is unknown" from the metered guard; the guard did stop a second provider call |

## 8. Limits

- No real provider ran. Provider behaviour after a lost connection, and whether an investigation answer is useful, are unproven. Exactly-once is not promised across a provider boundary.
- A milestone whose verifier returned while the process died before its claim settled stays held (unknown), although a reviewer receipt blob may exist: it is not linked until settled.
- `verdict run` does not reuse a candidate pass: `record()` accepts only receipts `verdict.run` issued, and candidate receipts carry the clamped cap and the selector. On a workflow root acceptance needs the engine handoff, not verdicts, and the hook no longer points to `verdict run`. On a plain root there is no candidate door.
- `verdict.run` fingerprints the environment at claim time; the verifier takes its own snapshot just after. The candidate door uses one snapshot for the request, the binding and the process.
- In-flight dedupe needs writers of this version on one state root; an older runtime does not take part.
- Reuse is exact-request only. The neutral-change route in `evidence_status` is not used by a door yet: a changed candidate is checked again.
- A run from another machine is observed until its deadline, then held; liveness is only known on this host.
