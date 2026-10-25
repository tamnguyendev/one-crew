# Round 8 G: Q5 / Q8 / Q10 outside the delegated authority

Branch `wf/r8-g`, base `ae8a67f` (2.2.0.dev7). Source: Codex finding, confirmed in the owner's night directive (item 1).

## Defect

`onecrew/v2/internal_plan.py` `self_decided` returned `None` when the root's grant did not list the class in `self_decide`, and all
three callers carried on. So a WORKFLOW root with an explicit grant that does not delegate Q5 still had its repair created
(`repair_tasks.prepare`): OneCrew took a decision outside its authority, without the U3 route that Q1/Q2 already follow.

## Common change: one verdict, three behaviours

- `internal_plan.self_decided` (`onecrew/v2/internal_plan.py:97-130`) now returns `{'delegation', 'decision', 'result', 'action', 'ctx'}`
  and never decides what the caller does next:
  - `NO_GRANT`: no approved revision, or a contract with no `authority` field (`authority.effective(...)['declared']` is False). Nothing
    is recorded, so the old behaviour stays (compatibility).
  - `DELEGATED`: the HD-05 record through `decide()`, as before. A delegated class that is still out of authority (for example U2 at the
    repair ceiling) raises, as before.
  - `NOT_DELEGATED`: the U3 verdict from `authority.decide` is RECORDED with `authority.record`, keyed so a repeat writes nothing new, and
    then RETURNED. It is not raised. Each caller acts on it according to its own class.
- `authority.decide` (`onecrew/v2/authority.py:368-370`): the U3 "not delegated" result now carries `nodes`, so the record's scope names
  the nodes it is about. Before, the scope was the literal word `decision`.
- `engine.hold_out_of_authority` (`onecrew/v2/engine.py:652`) is the hold-plus-card code that used to sit inside `request_action`, moved
  out without changes. The Q5 repair uses it too, so there is still only one implementation. `request_action` calls it
  (`engine.py:648`). One new parameter: `affected`, which defaults to the old closure.

## Q5: repair, re-check, redirect (an ACTION that changes the plan)

- Contract: 00 §2.2 Q5 "Sửa lỗi, mở repair task, kiểm lại, đổi hướng — trong ngân sách, trần vòng sửa". The table's rows are what the
  owner delegates through `self_decide`. 00 §2.3 U3 covers a choice nobody delegated, and `authority.decide` already classifies an
  undelegated Q as U3. A repair rewrites the internal plan (new generations, failed-first order), so it is an action, not a record.
- Behaviour: when `prepare` gets `NOT_DELEGATED` (`onecrew/v2/repair_tasks.py:83-98`):
  - the U3 verdict is recorded (component `onecrew.repair_tasks`, key `q5-repair-<id>`, scope = the affected nodes);
  - nothing of the repair is written: the receipt id is computed with `bytes_hash` BEFORE any write, the blob is stored only after the
    authority check passes, and there is no `plan.revised`;
  - the affected nodes are held and ONE `v2.workflow_hold` card is created through `engine.hold_out_of_authority`;
  - `prepare` raises `LedgerError('U3: Q5 is not delegated ...; the repair was not created, C, I is held for the owner (request REQ-...)')`.
  - Recovery goes on only through the answered request. An owner `continue` (`answer_effects` -> `engine.resume_held`) resumes the held
    nodes in a new generation inside the existing grant. It never runs the refused repair (`grants_authority False`,
    `original_unauthorized_action_executed False`). If the owner wants OneCrew to repair by itself, they amend the grant to list Q5.
  - When Q5 is delegated, the HD-05 record and the repair are written exactly as before.
- No-grant root: `NO_GRANT` means no change. In practice the engine never reaches a repair on such a root, because
  `internal_plan.revise` already needs Q1 and that root delegates nothing. Both facts are pinned by test 5b.
- Ordering: `recovery_policy.authorize_repair` still runs first, so a blocked or ceiling-reached failure stops the same way as before,
  and the owner is not asked about a repair that policy would refuse anyway.
- Tests (`tests/test_wf_r8_authority_q5q8q10.py`): `Q5NotDelegatedTests.test_1_*` (U3 recorded, no partial write, held {C, I} but not B,
  one card, an idempotent repeat) and `test_1b_*` (no move without an answer; the owner's `continue` resumes C and I with
  generation + 1, and the repair is still not created). `Q5DelegatedTests.test_2_*`: repair, in-authority HD-05 record, no request.
- Red on ae8a67f: `AssertionError: LedgerError not raised` in test_1 and test_1b. The repair WAS created.
- Green: 9/9.

## Q8: hold or continue a branch (the hold is a SAFETY move)

- Contract: Q8 "Giữ hoặc tiếp tục nhánh theo dependency và policy — unknown và finding giữ đúng phạm vi (HD-09, HD-25)". HD-25: "Nhánh
  bị ảnh hưởng ngừng nhận việc mới", and a finding closes only by being fixed (repair, then a passing receipt) or rejected with evidence.
  "Đổi code, hay reviewer nói 'accept', không tự đóng finding". HD-09: an unknown cannot be closed falsely to pass a gate.
- Reading:
  - Holding is never something to skip for lack of delegation. In the code it is already a projection of the committed register
    (`finding_scope.blockers`), in force before `hold_decided` runs.
  - The move that would need authority is continuing despite a finding, and OneCrew has no such move. The branch reopens only when the
    register closes the finding, and `engine.resume_held` refuses ("An unresolved finding still holds the affected work.").
  - So Q8 needs a RECORD, not a gate.
- Behaviour (`onecrew/v2/findings.py:318-344`):
  - The hold is unchanged.
  - Delegated: an in-authority HD-05 record, as before.
  - A grant that does not delegate Q8: the U3 out-of-authority record of the same safety hold, carrying the scope, `hold: safety` and
    `reopen: REOPEN` (the contract's "phạm vi bị giữ, điều kiện mở lại").
  - No grant: nothing new.
- Deviation from the brief: NO request card for Q8. The only card the engine has is `v2.workflow_hold` (continue/stop), and its
  `continue` cannot reopen a finding-held branch. A card would therefore show the owner an option that does not work, and it would add
  an owner interruption for a move nobody has to make. The finding itself is the owner-visible object (register, report).
- Tests: `Q8NotDelegatedTests.test_3_*`, through the real `engine.verify` -> `findings.record_node_verification` path. {C, D, I} is still
  held, verification is not ready, the U3 record has scope {C, D, I} and cites the finding and `hold: safety`, and no request exists.
  `Q8DelegatedTests.test_3b_*`: the same hold with an in-authority record.
- Red on ae8a67f: `ValueError: not enough values to unpack (expected 1, got 0)`. No record was written: the hold happened silently.

## Q10: record the outcome, propose a lesson or rule (EVIDENCE)

- Contract: Q10 "Ghi outcome, đề xuất lesson/rule — lesson/rule mới chỉ là đề xuất cho tới khi được đánh giá (HD-32)". HD-32 says
  "Tự ghi outcome": the outcome is evidence that OneCrew writes itself. Activating a rule is Q11 (granted_actions), not Q10.
- Checked: `outcome.record` writes only the `learning.outcome` row (the v1 merge rule). It writes no lesson, no rule and no skill state
  (module docstring, lines 9-11), and nothing is applied. The new test pins this: the only new events are `learning.outcome`,
  `decision.recorded` and `context.entry`.
- Behaviour (`onecrew/v2/outcome.py:153-164`):
  - The outcome is always written, whatever the grant says. Its v1 payload is unchanged: no new key, same pure `id`.
  - The HD-05 record carries `recorded: evidence`, `proposals: proposal_only` and `applied: []`. It is in authority when Q10 is
    delegated, and U3 out of authority when the grant does not delegate Q10. That U3 record is the explicit "evidence only, proposals
    only, nothing applied" marker.
  - No grant: nothing new.
  - `record()` also returns `q10: {delegation, proposal_only: True, applied: []}`.
- Tests: `Q10NotDelegatedTests.test_4_*` and `Q10DelegatedTests.test_4b_*`.
- Red on ae8a67f: `KeyError: 'q10'`. No marker and no record were written.

## Roots with no workflow grant (test 5)

`LegacyRootTests`: a workflow root whose contract has no `authority` field. `outcome.record` writes the outcome with no
`decision.recorded`. `self_decided` returns `NO_GRANT` for Q5, Q8 and Q10 and records nothing. `revise` is still refused with
"Q1 is not delegated", as before.

- Red on ae8a67f: `KeyError: 'q10'` and `AttributeError: ... no attribute 'NO_GRANT'`. Only the API is new here; the behaviour is the
  same.

## Existing (pinned) test files changed: fixture grants only, no assertion changed

The rule is now "a grant without Q5 means no repair". Fixtures that run a repair as their subject must therefore delegate Q5 in their
grant. Each file below gains `'Q5'` in its fixture `self_decide`. Without it, the tests fail with the U3 refusal above.

| File | Pin | Run here |
|---|---|---|
| tests/test_wf_engine.py | R04 | yes (EngineFixture) |
| tests/test_wf_candidate_handoff.py | R05 | yes |
| tests/test_wf_parallel_engine.py | R08 | yes |
| tests/test_wf_t11_integration_finding.py | R05 | yes |
| tests/test_wf_installed_node_actions.py | R05 | NOT run (it needs the wheel venv) |
| tests/test_wf_installed_node_learning.py | R06 | NOT run (it needs the wheel venv) |
| tests/wf_scenarios_r05_rx2.py | (not pinned; source of the installed scenarios) | NOT run (wheel venv) |

The pinned sha256 values in `wfkit/development-manifest.json` must be re-pinned by whoever owns the manifest. This branch does not
touch it, and does not touch `development-testcases.json` or `wfkit/u1/*`.

## Files changed

- Code:
  - `onecrew/v2/internal_plan.py`
  - `onecrew/v2/authority.py`
  - `onecrew/v2/engine.py` (`hold_out_of_authority` extracted from `request_action`)
  - `onecrew/v2/repair_tasks.py`
  - `onecrew/v2/findings.py`
  - `onecrew/v2/outcome.py`
- New test module: `tests/test_wf_r8_authority_q5q8q10.py`.
- No new code module.

## Runs (one process at a time)

| Group | Modules | Result |
|---|---|---|
| Listed modules | test_wf_repair_tasks, test_wf_recovery_policy, test_wf_findings, test_wf_finding_scope, test_wf_r02_outcome, test_wf_r7_t16b, test_wf_r7_t17c, test_wf_engine, test_wf_answer_effects, test_wf_r04a_authority, test_wf_w30a_audit | all OK |
| New module | test_wf_r8_authority_q5q8q10 | OK (9 tests) |
| Wider sweep | every test module that uses the engine, finding or outcome fixtures | see "Sweep" below |

## Sweep
45 more modules were run one at a time: every `tests/test_*.py` that uses the engine, finding or outcome fixtures, minus the modules in
the table above and minus `test_wf_installed_*`. All 45 are OK (225 tests).

| Module | Reason it was in the sweep |
|---|---|
| test_wf_candidate_handoff | repair under its own grant |
| test_wf_parallel_engine | repair under its own grant |
| test_wf_t11_integration_finding | repair under its own grant |
| test_wf_t04d_finding_holds_branch | the Q8 record is now written when Q8 is not delegated |
| test_wf_managed_hold | the Q8 record is now written when Q8 is not delegated |
| test_wf_t07a_e14_request_holds, test_wf_t17b, test_wf_t36a/b, test_wf_r02_boundaries, test_wf_r7_t35a, test_wf_pilot_tools | the rest of the sweep set |

## Not done

- The installed-wheel scenarios (`test_wf_installed_node_actions`, `test_wf_installed_node_learning`, `wf_scenarios_r05_rx2`) were not
  run: no wheel builds or venvs tonight. Only their fixture grants were edited.
- The pins in `wfkit/development-manifest.json` were not re-pinned (the file is off limits here).
- No full suite was run.
