# Round 7 — branch B notes (wf/r7-b, base 734acdc)

Synthetic fixtures only; nothing here is a pilot or pilot evidence. No wheel, venv or full suite was run (machine gate).

## Finding 3 — tier-1 composite mixed job sets (Codex P2)

- **Cause.** `build_aggregate` (wfkit/pilot_tools.py, `comparisons` loop) took `computed_from` = intersection of the jobs that have
  every part, but `pilot_count` = sum of every part over ALL jobs with that part, and `pilot_jobs` = min k of the parts. The checker
  (wfkit/pilot_report.py `Checker.tiers`) recomputed the same formula from the same aggregated numbers, so it passed the wrong report
  ("1/9" when J3 lacks `amend_authoring_error` but has `amend_requirement_change` 1).
- **Fix.**
  - Generator `wfkit/pilot_tools.py:581-597` (comparisons loop): one job set per composite = jobs with a value for every part;
    `pilot_count` = sum over that set, `pilot_jobs` = its size; new fields `parts`, `per_job` {job: sum of parts}, `missing`
    {part: [jobs]}, `pilot_denominator` (AGG_N = 10), `complete`; no data when the set is empty. Render (`render_aggregate`, the
    "Tầng 1" loop, ~line 730) adds `tính từ k/10 việc: …` and, when k < 10, `so sánh một phần, thiếu <part>: <jobs>`.
  - Checker `wfkit/pilot_report.py:425-465` (`Checker.tiers`): recomputes the job set, per-job sums, total, missing and complete
    directly from the parts' per-job cells in the report's `metrics` (not from the comparison's numbers), cross-checks `computed_from`,
    `per_job`, `pilot_count`/`pilot_jobs`/`pilot_per_job`, `missing`, `pilot_denominator`/`complete`, and the rendered line (count over
    k, `tính từ k/10 việc`, `so sánh một phần` + every missing job by word boundary when k < 10; "một phần" forbidden when complete;
    "không có dữ liệu" when k = 0). Docstring schema updated.
- **Composite-metric rule (two sentences).** A composite is counted over ONE job set: the jobs that have a value for every part, so a
  job missing any part is excluded from numerator and denominator alike (a missing cell is never read as 0 and no job outside the
  published `computed_from` is added) and is named per part under `missing`. A valid observed 0 is a real value and counts; with
  fewer than 10 jobs the comparison is labelled "so sánh một phần" with the missing jobs, never a full baseline comparison.
- **Single-metric path** (`m['computed_from']`, `m['missing']`, `target_status`): checked, already one job set (computed_from = jobs
  with a value, summary = their sum, target_status from that total and k). No change; pinned by
  `tests.test_wf_pilot_tier1.SingleMetricJobSetTests.test_single_metric_figures_use_the_jobs_with_a_value` (passes on old and new).
- **Tests added** (all literals hand-computed from the fixture observations):
  - `tests.test_wf_pilot_tier1.Tier1CompositeTests` (NEW module, pure, generator `build_aggregate` → `render_aggregate` → `write_named`
    → `pilot_report.check_files`): `test_full_data` (4 over 10, 0.4), `test_component_missing_for_the_same_job_across_parts`
    (3 over 9), `test_codex_case_one_part_missing_and_another_part_present_for_that_job` (0 over 9), `test_missing_in_different_jobs_for_different_parts`
    (4 over 7), `test_all_missing`, `test_parts_present_but_no_job_has_all_of_them`, `test_valid_zero_counts` (0 over 10),
    `test_checker_refuses_a_count_from_outside_the_published_job_set`, `test_checker_refuses_a_partial_comparison_rendered_as_full`;
    `SingleMetricJobSetTests.test_single_metric_figures_use_the_jobs_with_a_value`.
  - `tests.test_wf_pilot_tools.AggregateGeneratorTests.test_aggregate` new sub-case `tier1_composite_uses_one_job_set` (real ledger
    generator `generate_aggregate`, Codex's exact repro: delete `observations.amend_authoring_error.J3` → 0 over 9, J3 missing,
    `check_report` pass; full manifest → 1 over 10).
  - `tests/test_wf_pilot_report.py` fixture helpers `comparison()`/`render()` moved to the new comparison shape (they build input
    reports; no assertion changed).
- **Red evidence (old code, 734acdc):** `tests.test_wf_pilot_tier1` → FAILED (failures=5, errors=3):
  - codex case: `AssertionError: Tuples differ: (1, 9, 0.111) != (0, 9, 0.0)`
  - different jobs: `AssertionError: Tuples differ: (9, 9, 1.0) != (4, 7, 0.571)`
  - no job has all parts: `AssertionError: Tuples differ: (3, 5, []) != (None, 0, [])`
  - both checker counter-examples: `AssertionError: 'pass' != 'refused'`
  - full / same-job / zero: `KeyError: 'missing'` / `KeyError: 'complete'` (counts matched; transparency fields absent).
  The ledger sub-case was added after the fix and not run on old code (same arithmetic as the pure Codex case, which is red above).
- **Green:** `tests.test_wf_pilot_tier1` 10 OK; `tests.test_wf_pilot_report` 30 OK; `tests.test_wf_pilot_tools.AggregateGeneratorTests` OK
  (all 12 sub-cases, 132 s); `ReportGeneratorTests`/`RerunPlanTests`/`SupplementRunTests` 15 OK; `tests.test_wf_t45_entry_gates` 20 OK.

## Finding 4 — T35c E29: SKIP → finding link had no product record

- **Cause.** `aggregate_facts` linked a finding to a SKIP when `finding.node == skip.scope` (coincidence; in practice never true: the
  SKIP scope is an optional review id, a finding's node is a milestone), and no product record of the relation existed.
- **Fix (reuses decisions, findings, evidence; no new store).**
  - Write path `onecrew/v2/findings.py:503` `link_skip(ledger, name, finding_id, skip_record, *, review, reason, by=None)`: reads the
    HD-20 SKIP record (`_skip_records`, line 467: `decision.recorded`, subject review_policy/rules, validity.action SKIP, by key) and the
    finding from this root's register; refuses (`_link_problem`, line 486) unless same root, same revision + contract sha, same artifact
    the SKIP applied to, opened after the SKIP, and `review` = the SKIP's scope; refuses a finding already attributed to another SKIP;
    writes one `decision.recorded` through `decisions.record` (subject `finding_skip_link`/rules, authority = root's approved grant,
    evidence = finding, skip record, finding receipt, artifact, contract; deterministic key → same link twice recorded once, returns
    `duplicate: True`). W03 guards unchanged (by=owner refused in an AI session; AI writes under its own actor).
  - Read path `findings.skip_view` (line 552) + `skip_view_links` (541): SKIP records and link records, each link re-validated against
    its SKIP record and the register; failing ones listed under `invalid`, never counted. Works on legacy roots (no register → no links).
  - Measure `wfkit/pilot_tools.py:519` `skip_leak_of(ledger, selector, late)`: count = valid links, with (finding id, SKIP record id)
    per link; a late defect after a SKIP that is not linked keeps the cell "không có dữ liệu" (old conservative rule kept, now by
    finding id). `aggregate_facts` (line ~449) calls it. `false_pass` unchanged.
  - Report: `skip_leak` section gains `job` on each link, `invalid_links`, `source`, `target: 0`; the "SKIP (HD-20):" line shows
    `k/n SKIP`, `mục tiêu 0`, the source and every `finding F <- SKIP S`.
  - Checker `wfkit/pilot_report.py:527` `Checker.skip_link_records` (registered in `run`): skip_count = jobs_detail SKIP records; each
    link names a SKIP record of its own job; a (job, finding) counts once; source and target 0; the rendered line carries the
    denominator, target, source and both IDs; each job's skip_leak cell = its number of links.
- **Attribution rule chosen:** a SKIP covers exactly (root, approved revision + contract sha, artifact sha, optional review id). A
  finding on a later artifact is not linkable even if the defect may be older (conservative: under-attribution shows as "no link",
  never as an invented one); nothing is attributed automatically.
- **Tests added:** `tests.test_wf_findings.SkipLinkTests` (temporary ledger; SKIP via real `review_policy.decide`, finding via
  `record_review`): `test_measure_reads_the_link_record_and_points_at_the_skip_and_finding_ids` (0 before link, 1 after, both IDs,
  also through `aggregate_facts` on the `measure_all` root), `test_counter_example_a_measure_that_does_not_read_the_hd20_record_goes_red`
  (HD-20 reader patched away → not 1, link invalid; a forged link naming a REVIEW record not counted),
  `test_wrong_root_is_not_linked`, `test_wrong_revision_is_not_linked`, `test_wrong_artifact_is_not_linked`,
  `test_unrelated_finding_is_not_linked` (opened before the SKIP / review not covered / unknown id),
  `test_duplicate_link_is_recorded_once_and_a_second_skip_is_refused`, `test_ai_session_cannot_sign_the_link_as_the_owner`;
  `tests.test_wf_pilot_report.AggregateT35c.test_e29_link_must_name_a_skip_record_of_its_job_once_and_be_rendered`.
- **Red evidence (old code, 734acdc, worktree removed after):** all 8 SkipLinkTests ERROR
  `AttributeError: module 'onecrew.v2.findings' has no attribute 'link_skip'` (measure test:
  `AttributeError: module 'wfkit.pilot_tools' has no attribute 'skip_leak_of'`); the checker test FAIL
  `AssertionError: 'pass' != 'refused'` (old checker passed a link to another job's SKIP record).
- **Green:** `tests.test_wf_findings` (incl. SkipLinkTests) + `tests.test_wf_review_policy` 35 OK; pilot modules as above.

## Files changed

- `wfkit/pilot_tools.py` (F3 generator + render; F4 `skip_leak_of`, `aggregate_facts`, report section/line, docstring)
- `wfkit/pilot_report.py` (F3 `tiers`; F4 `skip_link_records`, `run`; docstring)
- `onecrew/v2/findings.py` (F4 `SKIP_LINK`, `_skip_records`, `_opened_seq`, `_link_problem`, `link_skip`, `skip_view_links`, `skip_view`)
- `tests/test_wf_pilot_tier1.py` (NEW)
- `tests/test_wf_pilot_tools.py`, `tests/test_wf_pilot_report.py`, `tests/test_wf_findings.py`
- `docs/wf/r7-b-notes.md` (this file)
- Not changed: `onecrew/v2/review_policy.py`, `onecrew/v2/decisions.py`, registry/manifest/U1 files.

## New test module to register

- `tests/test_wf_pilot_tier1.py` (pure, ~1 s, no ledger, no subprocess).
