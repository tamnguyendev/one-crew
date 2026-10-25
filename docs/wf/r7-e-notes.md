# Round 7 / Branch E — DUPk readable by the new code (T49d E7)

Branch `wf/r7-e`, base `c9b1e97`. One compatibility defect in legacy anchor resolution, found by the R04 acceptance audit (C1,
`docs/wf/r7-c1-matrix.json`, T49d `uncovered.E7`).

## Cause

`onecrew/v2/namespaces.py` `plan_dir` (at c9b1e97) mapped EVERY `plan:<name>` anchor to the shared `plans/<name>/`, whatever project the
anchor belongs to. On the T49 S2 fixture, DUPk is P3's `plan:dup` whose files sit in the per-project layout `plans/<P3>/dup/` ("root đường
dẫn mới mang anchor cũ", EV-J); the shared `plans/dup/` holds DUPa (P1's `plan:dup`). So the new code read P1's `plans/dup/v1.json` for
DUPk: `plan show` failed and `plan digest` printed `mốc ?/?`, before any rollback. That breaks T49d [E7] ("mọi root đọc được bằng bản mới"),
N5 (DUPk accepted, rollback succeeds) and T49c "tên trùng, không chặn".

Red text on c9b1e97 (recorded by `tests/test_wf_r7_dupk.py` run with the two product files stashed):

    onecrew.ledger.LedgerError: Plan plan:dup revision 1 does not match the recorded hash; the file was changed.
    AssertionError: 'mốc 0/1' not found in 'plan:dup [625506d68d7f]                proposed     mốc ?/?   cần bạn làm gì: duyệt bản 1'

and the mutant "P1's directory holds a same-hash copy of DUPk's file, DUPk's own file removed" was read successfully from P1's file
(`AssertionError: LedgerError not raised`). Result on c9b1e97: 10 tests, failures=4, errors=5 (the 10th, the DUPa-shared-path check, errors
only because `legacy_location` does not exist yet).

## Fix

- `onecrew/v2/namespaces.py:61` `legacy_location(ledger, name)` -> `(directory, note)`: the shared `plans/<name>/` belongs to the earliest
  `plan:<name>` anchor of the whole ledger (ORDER BY created_at, id — the old version refused a second `plan:<name>` across projects).
  - this project's anchor is that owner -> shared path (DUPa, R1, R4, P2's new `plan:r2`: unchanged). Only if its revision 1 there does not
    hash to the ledger's revision-1 sha while `plans/<pid>/<name>/v1.json` does, and no `plan-ns:<name>` of this project owns that
    directory, the per-project path is used;
  - another project's `plan:<name>` (DUPk) -> `plans/<its project_id>/<name>/`, never the shared one, even when the shared file has the
    same hash; if that project also has a `plan-ns:<name>` (which owns `plans/<pid>/<name>/`) the read is refused with "has no directory of
    its own".
  Read-only: one `mode=ro` read transaction, file hashing only.
- `onecrew/v2/namespaces.py:94` `plan_dir` uses it for `plan:` selectors; `:101` `active_file` of a per-project legacy root is
  `plans/<pid>/active-plan.json` (the file the hooks glob `plans/*/active-plan.json` sees), the owner keeps `plans/<name>/active-plan.json`.
- `onecrew/v2/contract.py:441` `read_revision`: a missing file of a per-project legacy root raises
  `Plan plan:dup of project <P3> revision 1 is unreadable: <path under plans/<P3>/dup> is missing; plans/dup/ belongs to plan:dup of project <P1> (...), which is not read.`
  Every other error text is unchanged.

Not changed: `compat_scan` (the OLD binary's view: DUPk still B3, DUPa's `plan report` still the `reads_other_root` WARNING, not blocking),
the old-binary S/G/C comparisons, writes of `plan-ns:` roots.

## Tests

New module `tests/test_wf_r7_dupk.py` (`DupkReadable`, S2 fixture of `tests.test_wf_namespace_compat`, real archived d3120c6):
- counter-example: the pre-fix rule patched in reproduces the exact hash text and `mốc ?/?`;
- DUPk `plan show` reads `plans/<P3>/dup/v1.json` (sha = ledger sha = file content_sha, title `P3-dup`), P1's `plans/dup/` untouched;
- DUPa and R1/R4 still resolve to `plans/<name>/` (note None), DUPa sha = `plans/dup/v1.json`;
- `plan digest` lists DUPk with `mốc 0/1`, no `?/?` anywhere;
- DUPk approved -> `verdict run` M1 (1 run) -> accepted (N5) on its own files; DUPa unaffected;
- DUPk `plan amend` writes `plans/<P3>/dup/v2.json` only; active file `plans/<P3>/active-plan.json`;
- W46b: DUPa's `reads_other_root` stays one non-blocking warning pointing at P3; DUPk still B3 for the old binary;
- mutants: per-project file absent -> error names P3 and its own path, not P1's hash; same-hash copy in P1's directory is not read;
  legacy root with a `plan-ns:` peer in its project -> refused.

Extended `tests/test_wf_r7_t49d.py` (created this round, unpinned): `forward_problems` no longer exempts DUPk (it is checked like every other
root: readable, same id, reading unchanged across the rollback), and `test_e7_roll_forward_keeps_ids_revisions_evidence_and_budget` asserts
DUPk readable and accepted before and after, with latest revision 1.

Green (one module at a time, worktree root): test_wf_r7_dupk 10 OK, test_wf_r7_t49d 11 OK, test_wf_namespace_lineage 3 OK,
test_wf_t49_counterexamples 3 OK, test_wf_plan_name_audit 6 OK, test_wf_w46b_evidence 7 OK, test_wf_namespace_compat 10 OK,
test_wf_t13a_emitted_kinds 2 OK (old-binary S/G/C identical), test_wf_namespace 9 OK, test_wf_audit_w12b_writer 5 OK,
test_wf_compat_scan 9 OK, test_wf_events 10 OK, test_wf_plan_binding 7 OK, test_wf_r01_step0_compat 2 OK, test_v2_report 25 OK.
None of these installs a wheel or venv; nothing was skipped. Full suite, gate and test_wf_upgrade_drill not run (machine window).

## Files changed

- `onecrew/v2/namespaces.py` (product: `_file_sha`, `legacy_location`, `plan_dir`, `active_file`)
- `onecrew/v2/contract.py` (product: `read_revision` missing-file message)
- `tests/test_wf_r7_t49d.py` (extended; unpinned)
- `tests/test_wf_r7_dupk.py` (new module)
- `docs/wf/r7-c1-matrix.json` (T49d: E7 covered, `e7_fix`, new module and product fixes listed; E5/E16 stay uncovered with their reasons;
  status stays partial)
- `docs/wf/r7-e-notes.md` (this file)

Pinned files changed: none. Not touched: wfkit/development-testcases.json, development-manifest.json, wfkit/u1/*. The registry
(development-testcases.json) does not yet list tests.test_wf_r7_dupk for T49d E7: that is for the integrator.
