# Round 7 branch A (wf/r7-a, base 734acdc) — notes

Red logs (old code, kept verbatim): `D:\OneCrewRuns\wf-dev-logs\r7a-red\` (red-f1-packaging-734acdc.txt, red-f1-chain-734acdc.txt,
red-f2-734acdc.txt). The original gate evidence `D:\OneCrewRuns\wf-dev-logs\evidence-734acdc\R03-check.t36b_gaps.log` was read, not changed.

## Finding 1 — delivery gate accepted a failing / empty T54 verdict (Codex P1)

- **Cause**: `wfkit/delivery_gate.py` (old line 126) only checked `bundle['decision'] == 'pass'` plus release/commit/wheel. A verdict
  with decision pass and `conditions['T54.1'] = False` (reason "installed scenario failed"), or with no `conditions` at all, passed.
- **Fix**: one shared rule in `wfkit/release_check.py`, used by the gate:
  - `condition_codes(bootstrap)` (line 41): the mandatory conditions (INPUTS or INPUTS(bootstrap), then T54.1..T54.5). `decide()` now
    writes its conditions from it (line 347), so writer and judge cannot drift.
  - `judge_verdict(result, release)` (line 359): re-judges a recorded verdict. Refuses: not an object; decision not pass/refused;
    reasons not a list of {code}; another release or testcase (`PARTS`); owner_acceptance not False; simulated_receipts_used not False
    (new: the CG receipt says `simulated: False`, so a fixture verdict cannot back it); conditions missing/empty/not a dict; both or
    neither INPUTS branch; any mandatory condition missing, False or non-bool; unknown condition; first_release not a bool or not equal to
    "INPUTS(bootstrap) branch and it held" (decide's own rule); first_release_baseline missing/malformed (keys = BASELINE_KEYS, valid
    identity, role compat-baseline, delivered/accepted False) when first, or present when not first; any reason whose code is not a
    condition or whose condition holds; decision pass with a failed condition or reason; decision refused (stays refused; flagged
    contradictory when nothing failed). The branch is read from the fields (conditions keys, first_release, baseline), not a sentence.
  - `wfkit/delivery_gate.py`: packaging block (lines 136-141) emits one `packaging` reason per `judge_verdict` problem; the identity check
    (release/commit/wheel) is kept and now always runs; `_inputs()` (line 102) feeds `inputs_summary` a sanitised copy so a malformed
    verdict is reported, never crashes; `first_release` in the receipt is true only when packaging has no problem. Snapshot reading and
    GLOBAL_PROBLEMS classification untouched.
- **Limit**: the gate judges the recorded verdict, not the evidence behind it. A forger rewriting every field consistently (e.g.
  first_release + baseline + all true) is not detectable from the verdict alone; gate_history is not in the verdict. Re-running
  `release_check.decide` on the bundle + evidence root would be the stronger check (CLI interface change; not done).
- **Tests added** (tests/test_wf_delivery_gate.py):
  - `PackagingVerdictTests.test_valid_verdicts_of_both_branches_and_every_release_pass`
  - `PackagingVerdictTests.test_codex_repro_decision_pass_with_a_false_condition_is_refused`
  - `PackagingVerdictTests.test_codex_repro_conditions_missing_entirely_is_refused`
  - `PackagingVerdictTests.test_each_missing_condition_key_is_refused`
  - `PackagingVerdictTests.test_a_failure_reason_with_decision_pass_is_refused`
  - `PackagingVerdictTests.test_a_refused_verdict_stays_refused_even_when_every_condition_holds`
  - `PackagingVerdictTests.test_the_inputs_branch_is_read_from_the_verdict_fields`
  - `PackagingVerdictTests.test_other_malformed_or_contradictory_verdicts_are_refused`
  - `PackagingVerdictTests.test_identity_checks_are_kept`
  - `PackagingVerdictTests.test_the_cli_refuses_a_verdict_without_conditions` (CLI subprocess)
  - `GateReceiptRoundTripTests.test_r7_a_release_check_output_is_accepted_by_the_shape_rule_and_only_the_fixture_mode_refuses_it`
    (real `release_check.decide` output, both branches: the only problem is the simulated flag — shape compatibility, anti-drift)
  - `GateReceiptRoundTripTests.test_r7_b_a_failed_installed_scenario_relabelled_pass_is_refused` (real T54.1 failure, relabelled pass /
    reasons dropped / conditions deleted)
  - `GateReceiptRoundTripTests.test_r7_c_first_release_claim_with_gate_history_is_refused_on_the_inputs_bootstrap_branch`
  - `GateReceiptRoundTripTests.test_r7_d_cli_receipt_of_a_forged_verdict_is_not_history_and_the_next_release_check_refuses_it`
    (chain: CLI receipt -> `gate_history.select_previous` raises -> next `release_check` INPUTS refused)
  - `PackagingVerdictTests` added to `load_tests`. `bundle_verdict()` fixture now carries every field `release_check.decide` writes
    (testcase, owner_acceptance, simulated_receipts_used, proves, first_release_baseline); it is also used by test_wf_delivery_gate_real.
- **Red on 734acdc** (61 FAIL/ERROR in PackagingVerdictTests, 4 chain tests red). Exact old-code assertion texts:
  - `AssertionError: 'pass' != 'refused'` (x50: false condition, missing conditions, missing key, failure reason, inputs branch, malformed)
  - `AssertionError: Tuples differ: (0, 'pass') != (1, 'refused')` (CLI without conditions; and chain r7_d)
  - `AttributeError: 'list' object has no attribute 'get'` / `'str' object has no attribute 'get'` (old gate crashed on a list verdict /
    string reasons)
  - `AssertionError: 'decision' not found in 'the T54 bundle verdict did not pass: '` (refused verdict: old code refused, but blind)
  - `AttributeError: module 'wfkit.release_check' has no attribute 'judge_verdict'` (r7_a)
  - r7_b `[decision pass]`, `[decision pass, reasons dropped]`, `[conditions deleted]` and r7_c `[relabelled: decision pass, condition
    true]`: `AssertionError: 'pass' != 'refused'`
- **Green**: `tests.test_wf_delivery_gate.PackagingVerdictTests` + `DeliveryGateTests` 21 OK; every `GateReceiptRoundTripTests` test
  (8, run one per process) OK; `tests.test_wf_release_check` 22 OK; `tests.test_wf_release_bundle.FirstReleaseFieldTests` 2 OK.
  Not run (machine constraint): `ProducerHistoryTests` (builds a wheel), `ReleaseBundleTests` (Producer).
- **Pre-existing, not fixed**: `tests.test_wf_delivery_gate_real.RealSnapshotTests.test_the_real_c18c46e_snapshot_...` fails identically
  on 734acdc and on this branch (11 subtests: `'R05/check.t07a_e14_request_holds' not found in 'failed implementation checks: ...'`):
  `delivery_gate._detail` truncates the failure list at 600 chars. Unregistered module; outside both findings.

## Finding 2 — false failure R03/check.t36b_gaps on gate 734acdc

- **Cause**: `test_e18_present_and_report_never_claim_calibration_p85_or_probability` casefolded the whole page and searched substrings;
  the page heading prints the project path `...\Temp\tmp90_k9lpz\project`, so 'p90' matched an identifier, not an estimate claim.
- **Fix**:
  - `onecrew/v2/report.py:870` `forecast_lines(state_root, name, revision=None, project_id=None)`: public wrapper over the
    `_forecast_lines` that both `render_present` and `render_report` already call (the estimate block: ước lượng, công còn lại, thực
    thi/chờ/deadline, thời gian lịch, thời điểm hoàn thành, lý do đổi, phát sinh). No renderer change.
  - `tests/test_wf_t36b_gaps.py:154` `no_estimate_claim()`: the estimate block must appear verbatim on both pages and carry '6–8 giờ' and
    'chưa hiệu chỉnh'; the same banned list (unchanged: 'đã hiệu chỉnh', 'p85', 'p90', 'p50', 'xác suất', 'probability',
    'calibrated eta') and percent regex are applied (a) to the estimate block with no masking and (b) to the WHOLE page after masking
    only the identifiers the heading prints (`identifiers()`: project_path, title, plan name, request_key, task_id, revision sha, read from
    `report._lookup`). Nothing was removed from the banned list; no temp-dir rename.
- **Tests** (tests/test_wf_t36b_gaps.py):
  - `T36bGaps.test_e18_present_and_report_never_claim_calibration_p85_or_probability` (now through `no_estimate_claim`)
  - `T36bIdentifierPaths.test_e18_identifiers_with_p90_p85_are_not_estimate_claims` (temp prefix `tmp90_P85_`, plan name `P90-p85`,
    title `Kiểm P85 và P90 mẫu`; asserts they are really on the page)
  - `T36bIdentifierPaths.test_e18_a_real_claim_in_the_estimate_or_elsewhere_on_the_page_is_caught` (patches `_forecast_lines` to add
    "P90: 9 giờ.", "đã hiệu chỉnh", "Xác suất ...", "80% khả năng ...", "p85 = 8 giờ", and `_present_risk` to add a P90/đã hiệu chỉnh
    claim outside the block: each must raise the banned-word/percent assertion; unpatched passes)
- **Red on 734acdc logic** (old e18 body run on the `tmp90_P85_` fixture):
  `AssertionError: 'p85' unexpectedly found in 'trình: p1 — bản 1/1, trạng thái approved\ntiêu đề: «sample»\ndự án:
  c:\users\nuc\appdata\local\temp\tmp90_p85_4kjh_91g\project ...` — same failure mode as the gate log (`'p90' unexpectedly found ...
  tmp90_k9lpz\project`).
- **Green**: `T36bGaps.test_e18_...` OK; `T36bIdentifierPaths` 2 OK; `T36bGaps.test_e4_e7_*` 2 OK. Not run: e9 (restart subprocess) and
  e21 (old-version archive), both unchanged.

## Files changed

- `wfkit/release_check.py` (CONDITIONS, condition_codes, SIMULATED, judge_verdict; decide uses condition_codes)
- `wfkit/delivery_gate.py` (docstring, _inputs, packaging block, receipt first_release)
- `onecrew/v2/report.py` (forecast_lines wrapper only)
- `tests/test_wf_delivery_gate.py` (pinned: BASELINE, full bundle_verdict, r7 chain tests, PackagingVerdictTests, load_tests)
- `tests/test_wf_t36b_gaps.py` (pinned: e18 helper, T36bIdentifierPaths class; imports tempfile, mock, plan_json)
- `docs/wf/r7-a-notes.md` (this file)

No new test module. New classes inside registered modules: `PackagingVerdictTests` (test_wf_delivery_gate, via load_tests) and
`T36bIdentifierPaths` (test_wf_t36b_gaps). `wfkit/release_check.py`, `wfkit/delivery_gate.py` and `onecrew/v2/report.py` changed, so the
kit-guard / development manifest entries that pin them need the coordinator's update.
