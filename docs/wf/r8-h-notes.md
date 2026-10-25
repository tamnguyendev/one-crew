# Round 8 H — T40c [E30]: contract decisions before/after the RP delivery decision

Base `ae8a67f`, branch `wf/r8-h`. Acceptance: 05-TESTCASES §T40 [E30] — "`decisions` của hợp đồng trước/sau: không đổi".

## Cause
Round 7 (docs/wf/r7-c2-matrix.json, T40c) left E30 uncovered: the RP bundle carried no contract decisions, so "before/after unchanged"
could not be checked locally. Only the six provider rows were compared with a test-side deepcopy.

## Design
- **Pin source (unchanged, not duplicated):** the provider/model decision of each cell is the pin the W45 matrix ran with
  (`wfkit.provider_matrix.pins()` → matrix.json `rows`). Each cell receipt records the provenance in `pins_source`
  ("program kit (tests/test_wf_rp_providers MODELS/ADVISOR_MODELS); program contract not yet approved"). The record carries that
  text as is, so it says honestly that the pins come from the program kit, not an approved contract.
- **Record** (`provider_evidence.decisions`): `{pins_source, decisions: [{cell, provider, role, model, vendor}] (six cells, sorted), sha256}`;
  sha256 = canonical JSON (sorted keys, UTF-8) of `pins_source` + `decisions`.
- **Producer** (`release_bundle.Producer.provider_bundle`, RP only): `before` taken from matrix.json rows right after reading the matrix
  (before evaluation and subset); `after` taken from the delivered rows after the shared evaluator verdict and the subset. A difference
  stops the producer (LedgerError naming the cell). Both go into `bundle.provider_bundle.decisions` and `provider-matrix/decisions.json`;
  the notes `matrix_markdown` (and `cells.md`) end with the line
  `- quyết định hợp đồng trước/sau: không đổi (sha256 <hash>; nguồn pin: <pins_source>)`.
  After `release_check.decide`, `execute()` re-reads matrix.json once more (`decisions_after_verdict`) and writes
  `contract_decisions {before_sha256, after_verdict_sha256, unchanged}` into release-check.json; a change turns the verdict to refused (T54.5).
- **Check** (`release_check` RP branch, T54.5): requires `decisions.before` and `.after` ("E30 evidence missing"); verifies each record's
  hash and six cells; refuses any before/after difference naming cell, field and both values; requires the record's `pins_source` to be
  the one every cell receipt names; re-derives the record from the delivered `providers` rows and refuses a difference; requires the
  notes line with the hash.

Real W45 matrix (6366137): decision hash `be84aa5bd86339f81e09dba78b21e283883adfe468a338ea29fc8dcf5d7ba27c`; kiro pins reviewer/advisor
`claude-haiku-4.5`.

## file:line
- wfkit/provider_evidence.py:61-107 — `DECISION_FIELDS`, `DECISION_CHANGED`, `decisions`, `verify_decisions`, `decision_changes`, `decisions_line`.
- wfkit/release_check.py:361-378 — E30 rules in the RP notes check (T54.5).
- wfkit/release_bundle.py:50 (import), 629-631 (before), 652-659 (after + decisions.json + bundle field), 663 (notes line),
  669-684 (`matrix_pins_source`, `decisions_after_verdict`), 356-361 (after the verdict, in `execute`).

## Tests
- tests/test_wf_r7_t40c.py — fixture receipts carry `pins_source`; the fixture bundle carries `decisions` and the notes line (helpers
  `record`/`line` are an independent oracle of the format). New class `T40cContractDecisionTests` (5 tests) and
  `T40cProducerDecisionTests` (2 tests, real W45 matrix read only, skipped if absent).
- tests/test_wf_release_check.py — `test_rp_uses_shared_matrix_rule_without_requiring_future_pilot_reviewer` fixture updated to the
  stricter rule only (receipts `pins_source`, `decisions` before/after, notes line); assertions unchanged.

## Red on ae8a67f (exact)
```
FAIL test_e30_valid_case_k_passes_and_the_notes_carry_the_unchanged_decisions_line_with_the_hash: AssertionError: 'pass' != 'refused'
FAIL test_e30_kiro_pins_changed_between_before_and_after_are_refused_naming_kiro: AssertionError: 'pass' != 'refused'
FAIL test_e30_bundle_without_the_before_after_decision_record_is_refused: AssertionError: 'pass' != 'refused'
FAIL test_e30_a_record_whose_hash_or_provenance_disagrees_is_refused: AssertionError: 'pass' != 'refused'
FAIL test_e30_the_delivered_rows_must_equal_the_recorded_decisions: AssertionError: 'pass' != 'refused'
FAIL test_e30_a_pin_changed_during_the_rp_decision_stops_the_producer_naming_the_cell: AssertionError: LedgerError not raised
ERROR test_e30_the_producer_records_before_and_after_and_the_notes_line: KeyError: 'decisions'
```

## Green (refusal texts)
- kiro pins changed: `RP: contract decisions changed between before and after the delivery decision (quyết định hợp đồng trước/sau đã đổi): kiro:advisor provider 'claude' -> 'kiro'; kiro:reviewer model 'claude-haiku-4.5' -> 'fixture-model-kiro'`
- no record: `RP: E30 evidence missing: the contract decisions before/after the RP delivery decision (provider_bundle.decisions.before/after)`
- notes line missing: `RP notes: the line "quyết định hợp đồng trước/sau: không đổi" with the decision hash <sha256> is missing`
- valid case K: pass; notes line `- quyết định hợp đồng trước/sau: không đổi (sha256 040d3031…; nguồn pin: program kit (tests/test_wf_rp_providers MODELS/ADVISOR_MODELS); program contract not yet approved)`

Runs (one module at a time): test_wf_r7_t40c 14 OK; test_wf_release_check 22 OK; test_wf_provider_matrix 19 OK;
test_wf_release_bundle.FirstReleaseFieldTests 2 OK; test_wf_finalgate 42 OK; test_wf_delivery_gate 32 OK.
Not run: test_wf_release_bundle.ReleaseBundleTests (builds wheels / full R01 drill; forbidden tonight). The RP `execute()` path
(`decisions_after_verdict` inside a real drill) is exercised only through the direct method call on the W45 matrix.

## Files changed (pinned in wfkit/development-manifest.json → repin needed; manifest not edited)
- wfkit/provider_evidence.py (pinned)
- wfkit/release_check.py (pinned)
- tests/test_wf_release_check.py (pinned)
- tests/test_wf_r7_t40c.py (pinned in the manifest, although round 7 called it unpinned)
- wfkit/release_bundle.py (not pinned)
- docs/wf/r7-c2-matrix.json, docs/wf/r8-h-notes.md
