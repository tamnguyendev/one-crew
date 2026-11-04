# Round 7 — Branch D notes (wf/r7-d, base 60d797c)

Four local product gaps from the R05/RP/PL acceptance audit (docs/wf/r7-c2-matrix.json). Each gap: counter-example first (red on
60d797c, failing text kept below), then the fix, then green. No assertion was weakened. Not edited: wfkit/development-testcases.json,
wfkit/development-manifest.json, wfkit/u1/*. No provider was called, nothing was pushed.

## GAP 1 — T17c [E4]: the workflow-hold card carries evidence, scope and a decide-by deadline

- Cause: `engine.request_action` built the `v2.workflow_hold` request with problem/options/recommendation/impact only; no evidence
  pointer and no decide-by moment (cards.CARD_FIELDS evidence, decide_by missing).
- Fix: `onecrew/v2/engine.py:646` keeps the HD-05 decision returned by `authority.record`; `engine.py:666` adds `parameters.card`
  and `parameters.decide_by_deadline` built by the new `_hold_card` (`engine.py:673`). The card is validated by the one card schema
  `cards.validate_card(card, ledger)` (six fields, evidence must resolve). Evidence = a content-addressed blob
  `workflow-hold-evidence` (requested action, its HD-05 decision record, the first `node.held` event seq of every held node at this
  generation, attempt, artifact, retained candidate, receipts) followed by the node's own receipt blobs. `decide_by` =
  `milestone:<node>`; `decide_by_deadline.at` = the root's sealed deadline (`ip.ceilings` -> `budget_core.group`) minus the upper
  execution estimate of the held nodes, with `root_deadline`, `reserved_execution_seconds` and `basis`; no deadline -> `at: null`
  with the reason (never invented). The request key is computed on the unchanged parameters (same key as before) and every card
  value is stable for the same hold, so asking again still returns the one request. Engine change confined to the hold-card code.
- Test: `tests.test_wf_r7_t17c.T17cOneCardTests.test_e4_the_one_hold_card_carries_evidence_scope_and_a_decide_by_deadline_inside_the_root_deadline`
  (one card after asking twice; all six fields; evidence resolves as blobs; the blob names the U2 action, the out-of-authority
  decision and the node.held events of A and I; deadline <= root deadline and derived from it).
- Red: `AssertionError: 'card' not found in {'affected': ['A', 'I'], ... 'reason_class': 'U2', ...} : the workflow hold request carries no decision card (evidence, scope, decide_by)`
- Green: tests.test_wf_r7_t17c (3), tests.test_wf_r7_t17b, tests.test_wf_answer_effects, tests.test_wf_answer_atomicity,
  tests.test_wf_finding_scope, tests.test_wf_hook_holds_generation.

## GAP 2 — T16b [E6]: an HD-05 record for Q5, Q8 and Q10

- Cause: Q1/Q2/Q4/Q9 go through `internal_plan.decide` (authority.decide -> authority.record -> decisions.record); the repair
  (`repair_tasks.prepare`), the finding hold (`findings.record_node_verification` / engine finding_blockers) and the outcome
  (`outcome.record`) decided silently.
- Fix (one implementation): `onecrew/v2/internal_plan.py:88` `decide` takes an optional idempotency `key`;
  `internal_plan.py:97` `self_decided` loads the root's APPROVED revision (an ended root keeps it, so Q10 works after
  `plan.closed`), returns None when the root does not delegate the class in `self_decide`, else calls the same `decide`. Callers:
  Q5 `onecrew/v2/repair_tasks.py:86` (after `recovery_policy.authorize_repair`, scope = affected nodes, evidence = failed receipt
  + repair blob, key `q5-repair-<blob>`); Q8 `onecrew/v2/findings.py:318` `hold_decided`, called after the register commit from
  `record_node_verification` (`findings.py:175`) and `record_verification` (`findings.py:359`): scope = the nodes
  `finding_scope.blockers` holds for the newly opened findings, key `q8-hold-<receipt>`, failure reported on stderr like
  `after_change` (never undoes the committed register change); Q10 `onecrew/v2/outcome.py:156` when a `learning.outcome` row was
  written, key `q10-outcome-<event>`.
- Q3: no ledger record by design — the testcase puts it in the task artifact/commit; the worker is the engine fixture, so the test
  asserts the interface (every produced node P, C, D carries artifact + receipt) and documents why (test module docstring).
- Behaviour kept: a root that does NOT delegate Q5/Q8/Q10 records nothing new and behaves as before (most engine fixtures delegate
  only Q1-Q4/Q9/Q12). Whether an undelegated Q5 repair must be refused (U3) is a behaviour/architecture decision for the owner, not
  made here.
- Test: `tests.test_wf_r7_t16b.T16bRootRunTests.test_e6_recorded_classes_carry_hd05_fields_and_a_onecrew_subject` now asserts a
  record per Q1, Q2, Q4, Q5, Q8, Q9, Q10 (HD-05 fields, `onecrew.*` subject, not owner, in authority), 0 requests, Q5 scope = the
  repair's affected nodes, Q8 scope = {C, D, I} citing the finding, Q10 citing the outcome id.
- Red: `AssertionError: 'Q5' not found in {...} : Q5: no HD-05 decision record in the root run` (same for Q8 and Q10), then
  `KeyError: 'Q5'`.
- Green: tests.test_wf_r7_t16b (2) and the modules listed under "Verification".

## GAP 3 — T40c [E29]/[E30]/[E33]: per-cell reason, rendering and the x6 message

- Cause: `finalgate.evidence_status` returned only the status for a non-usable cell; the RP notes check compared the structured
  states/subset only and refused x6 as "RP notes disagree with shared provider evidence" without naming the cell.
- Fix: `wfkit/finalgate.py:152-184` every non-usable state carries `reason` (unverified: the blocked receipt's reason, e.g.
  "thiếu tài khoản"; recheck: both wheel hashes + "no inheritance comparison" / "comparison <id> marks this cell affected" /
  "does not cover this build pair"; failed: the receipt reason or the build). `wfkit/provider_evidence.py:42-56` `STATUS_WORDS`
  and `render(states)`: one line per cell — usable with validity (and comparison) + origin hash/commit, any other
  `- <cell>: chưa dùng được: <reason> (<status words>, <status>)`; a non-usable state without reason is refused.
  `wfkit/release_check.py:340-360` (RP branch): x6 refused first as
  "RP subset contains a cell that has not passed (subset chứa ô chưa đạt): <cell> (<status>)"; a claimed non-usable cell without
  reason refused naming it; a state mismatch names the differing cells; the notes receipt must carry `matrix_markdown` containing
  every rendered line (missing line -> refused naming the cell). `wfkit/release_bundle.py:647-652` writes the rendering to
  `provider-matrix/cells.md` (the matrix file delivered with RP) and into the notes receipt (`matrix_markdown`).
- Fixture update (strengthened rule, not weakened): `tests/test_wf_release_check.py:206` the RP notes now also carry
  `matrix_markdown=render(states)`.
- Tests (tests/test_wf_r7_t40c.py): `test_e29_e30_every_cell_that_is_not_usable_carries_its_status_and_reason`,
  `test_e29_e30_the_notes_render_each_cell_with_its_status_and_reason_and_a_dropped_reason_is_refused`,
  `test_e29_an_unusable_cell_without_its_reason_is_refused_naming_the_cell`,
  `test_e33_x6_refusal_says_the_subset_contains_a_cell_not_passed_and_names_it`.
- Red: `AttributeError: module 'wfkit.provider_evidence' has no attribute 'render'`; `AssertionError: None != 'thiếu tài khoản' : {'status': 'unverified'}`;
  `AssertionError: 'pass' != 'refused'` (reason stripped); `AssertionError: 'subset chứa ô chưa đạt' not found in 'RP notes disagree with shared provider evidence'`.
- Green: tests.test_wf_r7_t40c (7), tests.test_wf_release_check (22) and the modules listed under "Verification".

## GAP 4 — T45d [E13]: hook/config hashes per phase, U2 counted once in AC1

- Cause: KQ5 (`wfkit/finalgate.py` hooks_check) compared one before/after pair per file over the whole program: a change made in
  PL-A and reverted before the end passed, a change could not be located in a phase, and the U2 was not tied to AC1.
- Fix: `wfkit/finalgate.py:361` hooks_check: an UNCHANGED row keeps the old two-hash format (every other fixture); a changed row
  without per-phase hashes is refused ("per-phase hook/config hashes missing"). `finalgate.py:186-224` `HOOK_SEGMENTS` /
  `_hook_changes`: `phases` {PL-A, PL-B: before/after} must join the program pair; each moved segment (inside PL-A, between the
  phases, inside PL-B) needs `changes[segment]` with `changed_at` inside the segment's window and an owner U2 covering exactly
  that path and pair, granted before the change. `finalgate.py:227-248` `_ac1_counts`: every authorising U2 is counted in AC1 of
  the pilot report on the PL-B T35c completion receipt (`owner_decisions`, the wfkit.pilot_report schema): exactly one U2 action
  with `authorization` = the U2 receipt sha256, the job's `per_job[...]['U2']` counts its U2 actions, and one U2 authorises one
  change (no double counting).
- Fixture update (strengthened rule): `tests/test_wf_finalgate.py` `test_kq5_valid_prior_u2_and_late_u2` now gives the changed
  row its per-phase hashes/segment and the report's AC1 U2 action; its two assertions (pass, then refused when the U2 is late) are
  unchanged. Unchanged rows (base fixture, T55 cases) are untouched.
- Tests (tests/test_wf_r7_t45d.py, 8): U2 identity/coverage/timing per segment; change without per-phase hashes refused; PL-A
  change reverted in PL-B refused without U2; between-phase change needs its own U2; per-phase ends must join the program pair;
  change time inside the phase window; U2 counted once in AC1 (missing, twice, table not counting it, report section missing);
  one U2 cannot authorise two changes.
- Red (60d797c): `AssertionError: 'pass' != 'refused'` (no per-phase hashes; PL-A revert), `AssertionError: False is not true : ["'authorization'"]`
  (between-phase U2, window, join), `AssertionError: 'refused' != 'pass'` (per-segment U2 forms not understood).
- Green: tests.test_wf_r7_t45d (8), tests.test_wf_finalgate (42), tests.test_wf_t55_cases, tests.test_wf_t45_entry_gates.

## Files changed

- onecrew/v2/engine.py (hold card only), onecrew/v2/internal_plan.py, onecrew/v2/repair_tasks.py, onecrew/v2/findings.py,
  onecrew/v2/outcome.py
- wfkit/finalgate.py, wfkit/provider_evidence.py, wfkit/release_check.py (all three pinned in wfkit/development-manifest.json:
  REPIN NEEDED by the registry owner), wfkit/release_bundle.py
- tests/test_wf_r7_t16b.py, tests/test_wf_r7_t17c.py, tests/test_wf_r7_t40c.py, tests/test_wf_r7_t45d.py (extended C2 modules),
  tests/test_wf_finalgate.py, tests/test_wf_release_check.py (fixtures moved to the stricter rule)
- docs/wf/r7-c2-matrix.json (T16b, T17c, T40c, T45d entries), docs/wf/r7-d-notes.md (this file)

New test modules to register: none (only the four C2 modules were extended).

## Verification

Small unit modules, one at a time, on the worktree (no wheel, venv, full suite or engine/parallel heavy suite), all OK:
tests.test_wf_r7_t16b (2), test_wf_r7_t17c (3), test_wf_r7_t17b, test_wf_r7_t40c (7), test_wf_r7_t45d (8), test_wf_answer_effects,
test_wf_answer_atomicity (18), test_wf_finding_scope (5), test_wf_hook_holds_generation (12), test_wf_release_check (22),
test_wf_finalgate (42), test_wf_t55_cases (44), test_wf_t45_entry_gates (20), test_wf_repair_tasks (6), test_wf_recovery_policy (4),
test_wf_r02_outcome (18), test_wf_t11_integration_finding (3), test_wf_findings (25), test_wf_managed_hold (2),
test_wf_t07a_e14_request_holds (2), test_wf_r04a_authority (20), test_wf_w30a_audit (5), test_wf_t13a_emitted_kinds (2),
test_wf_decisions (8), test_wf_context_wiring (3), test_wf_r02_context (9), test_wf_provider_matrix (19), test_wf_release_bundle (9),
test_wf_test_preparation (3).

Not run (heavy, left to the staging gate): tests.test_wf_engine, tests.test_wf_parallel_engine, the scenario modules
(tests/wf_scenarios_r05_rx2.py references workflow holds and Q5/Q8/Q10), pilot_tools/pilot_report suites, the full suite.
