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
