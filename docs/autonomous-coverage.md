# SPEC-004 coverage and execution evidence

Proposal: `specs/SPEC-004-autonomous-local-run.md`.
Baseline: `1e18059`. Runtime implementation cycle: AR01–AR08.

Controller implementation commit: `678bb55` — `feat(runtime): add bounded Codex orchestration (AR01-AR07)`. This commit records verified controller behavior; it does not claim AR08 live delivery succeeded. Validation: 51 tests passed and staged whitespace checks passed. Existing unrelated documentation changes were preserved outside this commit.

| ID | Requirement | Type | Implementation evidence | Verification evidence | Status | Limits |
|---|---|---|---|---|---|---|
| AR01 | Immutable grant, bounded plan and DAG | Architecture | runtime.py, profiles.py | Invalid plan, schema, grant and path tests; live Conductor plan | Complete | Fixed CV profile only |
| AR02 | Task/risk model routing | Functional | profiles.route, immutable policy snapshot | Risk floor tests; live plan/backend dispatch | Complete | No optimal-cost benchmark or Jev integration |
| AR03 | Structured artifacts and checkpoints | Security | validate_artifacts, apply, checkpoint | Ownership/size/schema and archive tests | Complete | JSON-only worker contract |
| AR04 | Deadline, calls, repair, cancel and usage | Reliability | command, invoke, check, terminal accounting | Real timeout and parent/child cancellation tests; live 240-second timeout | Complete | Timeout usage is unknown; no auto crash recovery |
| AR05 | Independent sealed gate and sandbox | Security | cv_gate.py, sealed host hashes | Native read/write/spawn probes; OS outside-write probe; preflight failure tests | Complete | Docker live execution unavailable; native adapter is not a malicious-code VM |
| AR06 | Gate/review repair within scope | Functional | execute verification loop | Simulated gate/reviewer failure, scoped backlog and no-delivery tests | Complete | Actual generated product verification tracked separately in AR08 |
| AR07 | Delivery evidence and separate acceptance | Observability | manifest, delivery, task CLI | Simulated full lifecycle with real Git commit; read-only CLI tests | Complete | Product acceptance remains human; no deployment |
| AR08 | Live from-empty run without manual product edits | Testing | examples/cv-autonomous-brief.vi.md | Runs listed below | Blocked | Provider returned no artifacts within bounded live attempts |

Verified controller coverage: 7/8 Complete, 1/8 Blocked. This is not overall OneCrew roadmap coverage or product security certification.

## Validation

`.venv\Scripts\python.exe -m unittest discover -s tests -q`: **51 passed** on Windows/Python 3.13 (24 existing spec CLI, 27 runtime).

Runtime lifecycle tests inject a model provider and HTTP gate fixture. They verify controller decisions, real subprocess termination and real Git delivery, but do not prove the generated application works. Live HTTP gate evidence must be reported separately.

## Live attempts

- `RUN-20261008-211020-297f61`: Docker preflight blocked, zero model calls. No engine reset/configuration changes performed by this task.
- `RUN-20261008-212331-59676f`: native preflight passed; Conductor completed; backend returned no artifact before its 240-second timeout. Controller stopped at 251.35 seconds. Two model calls, 11,129 reported input tokens and 314 output tokens for the completed plan only; backend usage unknown. No delivery. Earlier state format retained `usage_pending_attempt=2` after timeout; runtime now marks terminal attempts as missing usage, covered by a regression test. Original evidence remains unchanged.
- `RUN-20261008-213208-d753f3`: one explicitly documented retry with step ceiling 600 seconds, unchanged total ceiling 1,200 seconds / 8 calls / 2 repairs; output `D:\TamNT\Workspace\9.VMAgent\cv-guard-onecrew`. Failed at 113.47 seconds: Windows transient reader lock prevented atomic state replacement. Worker tree stopped; two model calls, plan usage 11,129 input / 318 output, backend usage unknown. No artifacts. Fixed bounded atomic-replace retry and added transient/permanent lock tests. Original run remains unchanged.

Machine-readable records reside under `.onecrew/runs/<run-id>/`: state, grant, events, per-attempt prompts/schema/output, checkpoints, HTTP gate, review, and delivery when successful. Ignored local logs are not committed because they can contain task data.

## External and broader gaps

Real Turnstile keys/domain/edge, AV, operational retention, and human/agent efficacy testing remain blocked or unverified. Multi-repo scheduling, Claude/Kiro execution adapters, free-form Conductor conversation, pause/resume/reorder and decision calibration remain outside this slice. The prior manually written Next.js application at `cv-guard` is not evidence of autonomous delivery.

Replacement run `RUN-20261008-213551-e40cd3` uses only 1,000 seconds / 6 calls / 2 repairs (600 seconds per model), below the unused budget of the preceding run. This is a manual runtime recovery, not autonomous crash recovery. Output: `D:\TamNT\Workspace\9.VMAgent\cv-guard-onecrew-recovered`. Stopped at 610.41 seconds: backend exceeded 600 seconds without returning an artifact. Two calls; reported plan usage 11,129 input / 317 output tokens; backend usage unknown. No product files edited manually, no HTTP gate or review reached, no delivery. No further model retries were dispatched.

Final local repair after the live run: state persistence now occurs inside the subprocess cleanup guard, so even a permanent state-write failure immediately after spawning cannot leave its child running. A real subprocess regression test verifies termination. This final controller change was unit-tested; it was not exercised in another paid live run.

Known reported totals across the three native attempts: 33,387 input tokens, 949 output tokens, six model calls. All three interrupted backend attempts have unknown usage. These totals are a lower bound, not a cost estimate. The Docker-blocked attempt had zero calls.

AR08 is blocked on obtaining a valid provider artifact within the execution policy and then validating the actual generated app. No evidence currently supports autonomous delivery, frontend quality, HTTP gate success on generated code or bot-blocking efficacy. Next diagnostic should examine provider latency/task granularity before authorizing another bounded live run; this report does not grant new budget.
