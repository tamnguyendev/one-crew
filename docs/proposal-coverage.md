# Proposal Coverage

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
