# 2.5-A cycle 2 — one check identity, evidence validity, finding loop

Base `01b10e1` (backend cycle 1 `e715669` + UI dev10 product `c4951f6`). Branch `claude/r2-a`.
Interface with 2.5-B: `D:/OneCrewRuns/cycle2/INTERFACE-AB.md`. No UI file, no B-owned file touched.

## 1. Inventory: keep / connect / add

| Area | Exists (cycle 1 or older) | Decision |
|---|---|---|
| Identity | `review_request.build/applicability` (node facts only, v1) | KEEP unchanged (stored ids stay stable, proven against a descriptor generated on the base). ADD `build_check` (node + milestone, v2), `evidence_status`, `kind_of`. `applicability` now also reads v2 and names `evidence.<dimension>`. |
| Evidence binding | `verification_evidence.bind/assess/receipt_assessment/record_reuse` (artifact, revision, acceptance, inputs, configuration, environment, checks; neutral only by declared globs) | KEEP and CONNECT: `build_check` takes a binding (or its raw args, hashed) and stores fingerprints; `evidence_status` delegates the neutral-change proof to `assess`, never re-implements it. |
| Findings | `findings.py` register (record_review / record_verification / record_node_verification / resolve), `finding_core` | KEEP. ADD `close_from_recheck` (explicit closure bound to a request and an authentic receipt), recur link in `_new`. No second store: same `finding.registered` event + snapshot. |
| Repair | `repair_tasks.prepare` (repair plan receipt in node inputs), `verification_order`, `rerun_order` | KEEP. CONNECT `rerun_order` to `evidence_status` (impact rerun, widen when there is no basis). |
| Data for OBS-2B | `tracking_work` (checks/outputs/findings/repairs projection, UI-bound) | KEEP. ADD `review_trace` (read-only, `unknown` for missing links). |
| v1 `finding_core` | closure transition `close_finding` | unchanged. |

## 2. What was added (step 2: identity and evidence status)

See the docstrings of `review_request.build_check` / `evidence_status`; evidence: `tests/test_review_a2_identity.py`.

## 3. Contract (what B and OBS-2B can rely on)

- `build_check(kind='node'|'milestone', ...)`: node with `inputs=None` returns exactly `build(...)` (v1, same id, golden test against a descriptor generated on the base). With `inputs` (a `verification_evidence` binding or its raw args, hashed) the descriptor is **v2**: adds `kind`, `target` (readable echo: node/generation/internal_revision or plan/milestone/plan_sha, plus `criteria_ids`) and `evidence` (candidate, revision, acceptance, inputs, configuration, environment, checks fingerprints). Secrets are never stored raw (tested). Added optional kwarg `review_id` (INTERFACE CHANGE REQUEST, additive; defaults `node-check:<node>` / milestone id).
- v2 node `facts` = validity subset (node, contract_sha, dependency inputs, checks_sha, unknowns). state/phase/finding blockers/internal revision/generation are NOT evidence validity: a repair elsewhere does not make an untouched node's evidence "changed". This differs from v1 `facts` on purpose; v1 is untouched.
- `evidence_status`: `applies` (identity equal + execution complete, or only the candidate changed and `verification_evidence.assess` proves it neutral from an explicit basis `{neutral, kind, submodule_changed, assertion}` with both bindings bound to the descriptors) / `recheck` (names the changed dimension) / `insufficient` (malformed, v1-vs-v2, incomplete or `unknown` execution, candidate changed with no basis). Only `applies` has `reusable=True`; it still needs the caller's own receipt/grant/budget checks.
- `findings.close_from_recheck(ledger, selector, finding_id, *, run_receipt, request)`: v2 request required; receipt authenticated by the existing core events (`node.verification` / `verdict.receipt_issued+recorded`); request must agree on root, contract revision/sha, node or milestone+plan, criterion, criteria hash, candidate and generation; receipt must pass the finding's criterion, be later than the finding, be on a candidate different from the failed one and (node) on the node's current generation with a `node.produced` event. If a receipt carries `request_id` it must equal the request. Refusals are durable (`finding.registered` action `recheck-close`, `refused` list). Closure records `resolution.recheck` and the repair-assignment link when found.
- Recurrence: a failure identical to a RESOLVED finding opens a new finding with `recurrence_of` and the old one gets `recurred_as`. Rejected findings are not linked.
- `repair_tasks.rerun_order(..., evidence={node: evidence_status kwargs})`: statuses are computed inside (a supplied status is never trusted); `applies` nodes skipped (listed in `reusable` with request ids), `recheck` rerun, `insufficient` or a finding without a recorded dependency scope widens to the whole suite (`widened`). Without `evidence` the result is the old one plus empty `widened/reusable`.
- `tracking_work.review_trace(ledger, selector)`: read-only; requests, runs (door, actor, status), receipts, findings with repair / output / recheck links, `{'link': 'unknown', 'reason'}` where no event or receipt establishes the link. Door is the recorded `door` or the event-kind writer (`door_source`); actor is `unknown` until an event records it (B may add `actor`/`door` to `review.run_started`).

For B: run receipts become closable when they are the existing node/verdict receipts; to bind a receipt to a request, add `request_id` to the receipt body (checked when present). No file of B was edited.

## 4. Evidence

Environment: TEMP/TMP/LOCALAPPDATA/APPDATA under `D:/OneCrewRuns/cycle2/a`, Python 3.13 `-B -X utf8`, no full gate. Logs in `D:/OneCrewRuns/cycle2/a`.

| Test | Result | Log |
|---|---|---|
| `tests.test_review_a2_identity` | 17 OK | step2-green.txt (re-run in reg3) |
| `tests.test_review_a2_findings` | 15 tests: 14 OK in step3-green.txt, the 15th (reuse provenance assertion) fixed afterwards and re-run alone: OK. The whole file was not re-run once more after that one-line edit | step3-green.txt |
| `tests.test_review_a2_trace` | 5 OK | trace1.txt |
| base-code reds | recurrence: `KeyError 'recurrence_of'`; unscoped rerun: widened set missing check-N1/N2/X (behaviour reds) | step3-red-base.txt, step3-rerun-red-base.txt |
| regression by impact | reg1 (findings, scope, adapter findings) 36 run, 2 import errors in the two files that import `tests.test_v2_reviewer` (pre-existing: it does `from test_v2_l1`, needs `tests/` on the path); those two re-run with `PYTHONPATH=<this checkout>/tests`: 6 OK. reg2 (repair/r10 d6/t11/t04d/t35d) 24 OK. reg3 (review_request, dispatch lifecycle, wf_review_dispatch, evidence_binding, optional cli, a2 identity) 76 OK | reg1..4.txt |

The first runs of the new function tests failed on an import of a not-yet-written module/function, which is not a behaviour red; the two behaviour reds are listed. Skips: 0.
Registry `hook-projects.json` SHA256 before/after: `AACAD058...EE01C` (unchanged).

## 5. Limits

- Node `target` (generation, internal_revision) is a readable echo and not cross-checked against the `facts` hash; a self-consistent forged descriptor is just another request (authenticity comes from where it is stored). `criteria_ids` is compared but cannot be derived from the criteria hash.
- `evidence_status` neutrality is only as strong as `verification_evidence.assess` (declared globs, command verifier); no behavioural-neutrality evaluator exists.
- Receipt-to-request binding relies on candidate/generation/criteria agreement unless B writes `request_id` into receipts; until then an engine-issued receipt names no request (`review_trace` shows `unknown`).
- Milestone closure was tested with the reviewer-receipt fixture, not a live reviewer; node closure with the engine fixture (fake executor/checker). No real provider, UI or wheel run.
- Heavy suites were slow on the loaded machine (reg3 ~20 min).
