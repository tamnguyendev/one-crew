# Proposal Coverage

Proposal source: `docs/spec-review-cli.vi.md`
Last reviewed commit: initial implementation tree; cycle commit recorded below after creation
Current iteration: 1

Scope: the local spec review CLI only. The broader orchestration roadmap is outside this cycle and remains unimplemented.

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
| SR02 | Requirements | List and pending filter | Functional | `onecrew/specs.py:execute`, `Project.status` | `test_approve_pending_filter_and_idempotent_repeat`, `test_changed_scope_rejects_old_review_code_and_preserves_decision` | Complete | Content-specific approval state |
| SR03 | Requirements | Brief/full read-only review | UI | `onecrew/specs.py:execute`, readonly DB connection | `test_brief_and_full_share_revision_without_creating_state` | Complete | No LLM or state creation on read |
| SR04 | Requirements | Approve the viewed content revision | Reliability | `onecrew/specs.py:Project.decide` | stale code, open/resolved questions, idempotency and newline tests | Complete | Local attribution, not authenticated identity |
| SR05 | Requirements | Request changes with comment | Functional | `Project.decide`, append-only decision records | `test_change_request_retains_previous_approval_and_comment`, `test_wrong_code_empty_actor_or_comment_do_not_write` | Complete | Preserve prior decisions |
| SR06 | Requirements | Brief/full diff and history | Functional | `execute` diff/history branches | `test_details_only_change_is_visible_and_invalidates_approval`, change request history test | Complete | Explicit details-only flag |
| SR07 | Requirements | Invalid input/state and stale revision handling | Reliability | `Spec.parse`, `contained`, `Project._validate`, error exit 2 | invalid/duplicate/unknown spec, corrupt DB/snapshot, path guard, changed scope tests | Complete | No security boundary against same-user worker |
| SR08 | Usage | Windows launcher and working example | Documentation | `onecrew.ps1`, `onecrew_cli.py`, package entry points, README and CLI guide | real module subprocess and PowerShell launcher tests on Unicode/space paths; local launcher smoke | Complete | Standard library only |

## Cycle 1 result

- All eight requirements of this slice are supported by implementation and verification evidence.
- `python -m unittest discover -s tests -v`: 16 tests passed on Windows/Python 3.13.
- Module and PowerShell entry points exercised; CLI reads the actual example without approving it.
- The first test run found a test-fixture SQLite handle left open during Windows cleanup. The fixture now closes it explicitly; the full suite passed after the repair.
- No configured lint/type-check suite existed. Python import/entry-point tests and TOML/JSON/link validation cover the local packaging/documentation surfaces.
- Broader orchestration, external adapters, authenticated approvals and writer isolation remain outside this slice, not implicitly completed by these tests.
- Pre-existing review/audit documents and tools not changed by this cycle remain outside its Git staging set.

Verified coverage for this slice: 8/8. This is not user acceptance or production readiness of the broader OneCrew roadmap.
