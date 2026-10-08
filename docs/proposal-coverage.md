# Proposal Coverage

## Architecture revision 2 — source-informed design, 2026-10-09

User request: update OneCrew architecture using the reviewed upstream designs. Baseline: `9a8e0cf`; scope is documentation, not implementation of SPEC-006. Canonical artifacts: [architecture](architecture.vi.md) sections 12–13, [SPEC-006](../specs/SPEC-006-portable-orchestration.md), [backlog](mvp-backlog.vi.md) and [README](../README.md).

| ID | Requirement | Type | Evidence | Verification | Status |
|---|---|---|---|---|---|
| OA01 | Record lessons and adopt/defer decisions for all nine reviewed repositories | Documentation | Architecture section 12: commit-pinned source matrix, review limits and no implicit framework adoption | Verified nine distinct repositories with full commit-pinned links; each row maps to a contract and planned test | Complete |
| OA02 | Turn lessons into explicit execution contracts while keeping one small core | Architecture | Sections 3–9 and 13: admission, handoff, approval, reservation, checkpoint, integration, schemas and capabilities | Reviewed nine contracts against source findings and OC01–OC12; kept runtime guarantees separate from design | Complete |
| OA03 | Connect design to readable spec and staged acceptance evidence | Documentation | SPEC-006 OC01–OC12 crosswalk, backlog P1a–P1d and T20–T30, README | Spec.parse and CLI brief/full pass; all OC/T IDs mapped; five-document links/fences/UTF-8 and git diff --check pass | Complete |

These OA requirements measure this design update only. OC01–OC12 runtime coverage remains 0 Complete / 10 Partial / 2 Missing: the contracts below do not change that assessment. T01–T30 are planned acceptance scenarios, not passing tests. The source review read selected code/test paths and ran three offline Athena probes; it did not execute upstream full suites or prove live cross-provider/8-hour behavior.

Revision 2 supersedes the previous documentation-cycle wording about T01–T19 being the entire matrix; those cases remain and T20–T30 extend them. Existing runtime evidence and historical records below are retained. No spec approval, worker execution, new runtime dependency or paid API request is part of this documentation cycle. Pre-existing working-tree edits are outside its commit.

Documentation coverage: OA01–OA03 = 3/3 Complete. Validation used the existing `.venv` Python, `Spec.parse`, and read-only `python -X utf8 -m onecrew spec review SPEC-006` (brief and `--full`); no runtime source changed, so runtime/upstream suites and live workers were not run for this cycle. Commit subject: `docs(architecture): adopt reviewed orchestration contracts OA01-OA03`; the resulting hash is reported in the delivery message/Git history.

## Portable orchestration architecture — SPEC-006, 2026-10-09

Proposal source: `specs/SPEC-006-portable-orchestration.md`.
Last reviewed implementation: `bf2e673` (runtime), with evidence documentation at `6f6d44a`.
Current cycle: documentation/architecture only, requested review and update; no new runtime implementation or paid worker run.

The current baseline is [architecture](architecture.vi.md) and [implementation sequence](mvp-backlog.vi.md). It replaces the Kiro Crew-first host exploration and broad DecisionEvaluator-first sequence in the historical 08/10 documents. One independent core owns state, budgets and dispatch; entry connectors and worker adapters are separate; JEV is optional after evidence. Historical R/CN/DF rows below are not the current implementation plan. Existing SPEC-005 and spec-CLI achievements remain valid within their original scope.

| Status | Count |
|---|---:|
| Complete | 0 |
| Partial | 10 |
| Missing | 2 |
| Blocked | 0 |
| Not applicable | 0 |

These counts measure the new SPEC-006 implementation requirements, not documentation completion or regression of the earlier profile. No requirement is Complete merely because its design is written.

| ID | Proposal section | Requirement | Type | Implementation evidence | Test evidence | Status | Notes |
|---|---|---|---|---|---|---|---|
| OC01 | Entry | Portable submit/connect/query | API | No general entry connector/submit/attach contract | Planned T01/T06/T18; no live multi-entry evidence | Missing | Current task CLI is profile-specific |
| OC02 | Planning | Spec and real repo to general plan | Functional | specs.py review; incremental_profile.py fixed CV DAG | SR tests and IA01 only; planned T01/T02/T19 | Partial | General decomposition missing |
| OC03 | Core | Durable authority, recovery, one writer | Reliability | runtime.py bounded controller/cancel/checkpoints | IA03 within-process retry; planned T03/T04/T10/T14 | Partial | No restart reconcile or independent service |
| OC04 | Workers | Replaceable verified adapters | API | Current Codex read-only artifact worker | SPEC-005 live Codex; planned T04/T07 | Partial | Claude/Kiro adapters and cross-provider handoff missing |
| OC05 | Inbox | Durable requests and trusted revision replies | Security | No operational multi-entry request/reply inbox | Planned T05/T06/T08/T12/T19 | Missing | spec approval ledger is not this capability |
| OC06 | Memory | Shared decisions/checkpoints/provenance | Data | Spec snapshots, run logs and file checkpoints | SR history, IA02; planned T03/T06/T07/T18 | Partial | Portable memory/ack/isolation semantics missing |
| OC07 | DAG | Parallel dependency/ownership scheduling | Architecture | Fixed sequential CV graph validation | IA01 fixed-profile checks; planned T09/T10/T13 | Partial | General parallel scheduler missing |
| OC08 | Integration | Verified merged result across branches/repos | Testing | Host CV gates and independent review | SPEC-005 19 live checks; planned T11 | Partial | No multi-worktree integration owner |
| OC09 | Long jobs | Root budgets, recovery and optional 8h | Reliability | Run deadline/calls/repair counters; CLI capped at 1h | Bounded runtime/IA03 tests; planned T07/T09/T13/T14/T15/T17 | Partial | Durable cross-attempt/parallel grants and 8h validation missing |
| OC10 | Routing | Task/risk/capability plus account quota | Performance | incremental model rules; JEV connection only | Routing regressions, connectivity probe; planned T15/T16/T18 | Partial | No quota windows/reservation/routing benchmark |
| OC11 | Review | Partial review, feedback and reorder | UI | outputs/checkpoints/preview | IA02/IA05; planned T10/T12/T13 | Partial | Revision feedback/acceptance/pause/reorder missing |
| OC12 | Authority | Scope/grant enforcement separate from acceptance | Security | Fixed CV sealed gates and worker artifact validation | SPEC-004 boundary tests/IA04; planned T01/T08/T11/T16/T19 | Partial | Trusted multi-entry caller/worker authority isolation missing |

Documentation cycle: updated canonical architecture, readable SPEC-006, four delivery phases and T01–T19 acceptance scenarios; preserved dated architecture/backlog snapshots. Validation for this cycle is spec parsing/brief limit, current CLI read-only smoke, requirement coverage, local links/fences and Git whitespace checks. Runtime tests recorded above belong to prior cycles; they were not rerun as evidence for new runtime capabilities. The new proposal remains unapproved. The review/update task does not authorize implementing the entire new roadmap.

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
