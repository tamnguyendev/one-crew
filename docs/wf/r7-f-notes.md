# Round 7 branch F — T49d [E5] and [E16] (wf/r7-f, base e61b2c2, 2.2.0.dev7)

Scope: the last two local evidence ids of R04/T49d. No pinned file, no registry/manifest, no `wfkit/u1/*` was changed. Fixture only
(S2 of `tests.test_wf_namespace_compat`, disposable copies, archived old code d3120c6); no provider, no owner verb, no real ledger.

## [E5] rollback SCRIPT: exit code + message per N case; venv package list before/after

- Before: the gate existed only as functions returning dicts (`tests/wf_rollback.py:22 rollback_drill`,
  `wfkit/upgrade_drill.py:51 guard_swap`); `python -m wfkit.upgrade_drill` runs only its own generated fixture.
- Now: `python -m wfkit.rollback_cli --state-root <copy> --out <new temp dir> [--venv <venv python>]`
  (`wfkit/rollback_cli.py:111 run`, `:145 main`). No second rule set: without `--venv` it calls `rollback_drill`; with `--venv` it takes
  the installed NEW build's own `compat scan --json` (`:91 installed_scan`) and calls `guard_swap` (`:100 decide`). Exit 0 = allowed,
  3 = refused with `refused: <exact remaining block set> (remaining block conditions; the new build stays installed)`, 2 = unreadable
  state or venv package list changed. It never installs/uninstalls (the swap stays `wfkit.upgrade_drill`'s job); `receipt.json` records
  `swapped: false` and, with `--venv`, `pip list` + the installed onecrew RECORD hash before and after (`:80 venv_packages`).
- Tests `tests/test_wf_r7_t49d_e5.py` (script driven by subprocess on S2; CASES = the N-table as in `test_n1_to_n7_gate_branches`):
  - `RollbackScript.test_e5_refused_cases_exit_3_and_name_the_exact_remaining_block_set` — N1 `refused: B1`, N2 `refused: B3`,
    N3 `refused: B2, B3`, N4 `refused: B1, B3`, N7 `refused: B2`, exit 3, exact message equality.
  - `test_e5_n5_allowed_exit_0` — exit 0, message carries the ledger hash of the scan.
  - `test_e5_n4_pause_and_stopped_with_report_release_neither_b1_nor_b3` — R2 stopped_with_report keeps B1, DUPk paused keeps B3.
  - `test_e5_counter_a_script_whose_gate_skips_b2_goes_red_at_n3_and_n7` — red: a gate that ignores B2 makes N7 exit 0 and N3 name only
    B3, i.e. the per-case assertion above fails on it.
  - `test_e5_unreadable_state_is_an_error_never_a_permission` — malformed ledger: exit 2, `error: ...`.
  - `InstalledVenv` (ONE wheel of this checkout via `tests/wf_wheel.build_wheel`, reusing WF_WHEEL under a gate, ONE venv per class):
    `test_e5_installed_refusals_leave_the_new_venv_package_list_unchanged` — for N1-N4/N7 via `--venv`: exit 3, exact message, the
    test's OWN `pip list` + RECORD hash before == after for every case, receipt gate = `upgrade_drill.guard_swap`;
    `test_e5_installed_n5_allowed` — exit 0 through guard_swap.
- Observed messages: see "Runs" below.

## [E16] rollback REPORT with one line per root + report-check script

- Before: no rollback report with per-root lines; the only receipt was the drill's on its own fixture.
- Now: the script writes `scan.json` (the scan the gate decided on), `report.json` and `report.txt`: one line per scan root with
  project_id, anchor, label, status, blocks, properties and `diagnosis_source.scan_sha` = content hash of scan.json
  (`wfkit/rollback_cli.py:53 build_report`). Label: `label_for` (`:40`) — `"đọc OK"` when the scan's `properties.old_readable`
  (`onecrew/v2/compat_scan.py:308`) is true, otherwise `"chỉ được bảo toàn"`.
- Check: `python -m wfkit.rollback_report_check <report.json> <scan.json>` (`wfkit/rollback_report_check.py:16 violations`, `:55 main`),
  exit 0 ok / 1 refused (one `refused:` line per offending root, naming anchor + project) / 2 unreadable. It uses the same `label_for`;
  it refuses a missing root, an extra or duplicate line, a label/status/block set different from the scan, a diagnosis source that is not
  this scan, and the labels `"mất"` and `"đã chẩn đoán bởi bản cũ"` by name.
- Deviation from the brief, on purpose (spec wins, no weakening): the brief defined "mất" = not readable by the old binary and
  "đã chẩn đoán bởi bản cũ" = old binary diagnoses a block. 05 T49 forbids both: [E13] (T49c) says a root whose data the old binary
  cannot read must NOT be called "mất" (correct label "chỉ được bảo toàn"), and the boundary (00 §6.1) says the old binary diagnoses
  nothing — diagnosis comes from the new build's `compat scan`. So the scan can never justify either label; the report never emits them
  and the check refuses them. E16's defect ("ghi ... trái với scan") is exactly what the check catches.
- Tests `tests/test_wf_r7_t49d_e16.py` (real report = the script's output on S2 at N5):
  - `test_e16_real_report_one_line_per_root_and_the_check_passes` — 7 lines = 7 scan roots; R1/R4/DUPa "đọc OK", R2/R3/DUPb/DUPk
    "chỉ được bảo toàn"; the check script exits 0 `ok: 7 lines match scan <sha>`.
  - `test_e16_real_report_labels_agree_with_the_archived_old_binary` — the unmodified d3120c6 `plan show` exits 0 for every "đọc OK"
    root and non-zero for every "chỉ được bảo toàn" root.
  - three wrong samples, each refused (exit 1) with only the offending root named:
    `..._read_ok_for_a_root_the_scan_keeps_preserved_only` (R2),
    `..._root_missing` (R3), `..._diagnosed_by_old_for_a_root_the_old_binary_reads_fine` (R1); plus `..._lost_for_a_root_whose_data_is_kept`
    (R2 "mất").
- Red text (actual check output):
  - `refused: plan-ns:r2 (project 7437…): labelled "đọc OK", the scan says "chỉ được bảo toàn" (old_readable=False)`
  - `refused: plan-ns:r3 (project 1f44…): missing from the report`
  - `refused: plan:r1 (project 1f44…): labelled "đã chẩn đoán bởi bản cũ" but the diagnosis is the new build's scan (old_readable=True); the scan says "đọc OK"`

## Runs (one module/class at a time)

- `tests.test_wf_r7_t49d_e5.RollbackScript` — 5 OK (before 22:40, no venv).
- `tests.test_wf_r7_t49d_e16` — 6 OK.
- `tests.test_wf_r7_t49d_e5.InstalledVenv` — 2 OK in 118.6 s (run alone at 22:40, after the gate window; one wheel + one venv in setUpClass). Every refused case: exit 3, exact message, `pip list` + onecrew RECORD hash before == after; N5 allowed through guard_swap.
- Script messages observed on S2: N1 `refused: B1`, N2 `refused: B3`, N3 `refused: B2, B3`, N4 `refused: B1, B3`, N7 `refused: B2`
  (each exit 3); N5 `allowed: 0 block conditions on ledger <sha>` (exit 0).

## Files

- New: `wfkit/rollback_cli.py`, `wfkit/rollback_report_check.py`, `tests/test_wf_r7_t49d_e5.py`, `tests/test_wf_r7_t49d_e16.py`,
  `docs/wf/r7-f-notes.md`.
- Changed: `docs/wf/r7-c1-matrix.json` (T49d entry only). Pinned files changed: none (`wfkit/upgrade_drill.py`, `tests/wf_rollback.py`
  are called, not edited). The new modules are not yet in `wfkit/development-manifest.json` / the registry checks (not ours to edit).

## Still missing

- The rollback script refuses or allows; it does not perform the uninstall/reinstall itself on the allowed case (that is the existing
  installed drill on its own generated fixture). E5 asks only for the refused cases not to touch the new build, so this is not an E5 gap.
- Registry/manifest: `check.r7_t49d` etc. do not yet include the two new modules; the integrator must pin them and add them to T49d's
  checks before the registry can mark E5/E16 covered.
