# Proposal Coverage

Proposal source: `docs/spec-review-cli.vi.md`
Last reviewed implementation commit: `14f22cff2293d4b8e91b6072acff9937d5380c97`
Current iteration: 1

Review update: 2026-10-08; overall review reopened SR02/SR03/SR06. No runtime fixes were made in the documentation update.

Scope of the requirement counts below: the local spec review CLI only. The broader orchestration roadmap remains unimplemented and is summarized separately below.

## Summary

| Status | Count |
|---|---:|
| Complete | 5 |
| Partial | 3 |
| Missing | 0 |
| Blocked | 0 |
| Not applicable | 0 |

## Requirements

| ID | Proposal section | Requirement | Type | Implementation evidence | Test evidence | Status | Notes |
|---|---|---|---|---|---|---|---|
| SR01 | Requirements | One spec, brief and detailed views | Data | `onecrew/specs.py:Spec.parse`; `specs/SPEC-001-duyet-spec.md` | `test_brief_and_full_share_revision_without_creating_state`, `test_invalid_specs_fail_without_state` | Complete | Seven sections, 350-word bound; no silent truncation |
| SR02 | Requirements | List and pending filter with per-spec errors | Functional | `onecrew/specs.py:execute`, `Project.status`; `Project.specs` currently aborts on a malformed file | Existing pending tests pass; mixed valid/invalid inventory case is not in the suite | Partial | Keep valid entries visible while reporting invalid drafts separately |
| SR03 | Requirements | Brief/full read-only review isolated from unrelated invalid drafts | UI | `onecrew/specs.py:execute`; `Project.find` parses every spec | Existing brief/full test passes; manual sandbox reproduced valid SPEC-001 review failing on incomplete SPEC-002 | Partial | No LLM/state creation; target lookup still needs error isolation |
| SR04 | Requirements | Approve the viewed content revision | Reliability | `onecrew/specs.py:Project.decide` | stale code, open/resolved questions, idempotency and newline tests | Complete | Local attribution, not authenticated identity |
| SR05 | Requirements | Request changes with comment | Functional | `Project.decide`, append-only decision records | `test_change_request_retains_previous_approval_and_comment`, `test_wrong_code_empty_actor_or_comment_do_not_write` | Complete | Preserve prior decisions |
| SR06 | Requirements | Brief/full diff and history independent of current file validity | Functional | `execute` diff/history branches; unconditional `Project.find` before history | Diff/history tests pass for valid files; manual sandbox retained one DB decision but history failed when current spec became malformed | Partial | Read history from the ledger without parsing the current file; corrupt state must still fail |
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
- These scenarios used temporary test fixtures only. The real sample spec was not approved. Fixes and permanent regression tests remain outstanding.
- Proposal now explicitly requires error isolation for list/review and ledger-based history. SR02/SR03/SR06 stay Partial until implementation and regression evidence exist.

Verified requirement coverage for the current CLI slice: 5/8 Complete, 3/8 Partial. This count does not measure overall OneCrew product completion.

| Product capability / references | Status | Evidence or gap |
|---|---|---|
| Local spec review / SR01–SR08 | Partial | Working CLI and 16 passing tests; gaps above |
| Conversation and Conductor / CN01–CN03 | Missing | Architecture/backlog only |
| Enforced scope, budget and dispatch authority / R17, R22, R25, CN04, CN06 | Missing | No controller/worker boundary or live host integration |
| Stop/recover without duplicate work / R04, R16, R19 | Missing | Runtime/adapter not implemented or exercised |
| Evidence-backed delivery and acceptance / R07–R11, R20, CN05 | Missing | No end-to-end delivery run |
| Multiple repositories and Claude/Kiro/Codex / R01, R12 | Missing | Product requirement retained; backend contracts not yet demonstrated |

Next sequence: repair the CLI gaps → prove one controlled task on one host/backend/repository → connect Conductor from discussion to user acceptance → extend repositories/backends one at a time. DeepSeek, multi-machine registry and dashboard are later work. The old overall 2–4 week estimate is not an active planning baseline. See `docs/mvp-backlog.vi.md`.
