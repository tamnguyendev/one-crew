# 2.5-A cycle 1 — request identity adapter

Baseline: `bdb13bf` (OBS-2 product `6cb2fa9`). Isolated branch `codex/review-a-cycle1`.
User authorized parallel work while Claude repairs OBS-2. This cycle does not change
the UI, its packages, production hooks, runtime, provider settings or ledger.

Proposal: shared `ROADMAP-DESIGN-20261026.vi.md` sections
`review-responsibilities-20261104`, §2.6, and 2.5-A impact/evidence requirements.
The selected cycle implements the small data adapter for B's existing optional
review consumer, not all review convergence or cross-entrypoint execution.

## Reuse map and ownership

- Keep `verification_evidence.bind/assess/receipt_assessment/record_reuse` for
  verification evidence and explicit applicability records.
- Keep `findings`, v1 `finding_core`, and `repair_tasks` for fail/repair/recheck.
- Keep `review_policy` as authority over optional versus mandatory obligations.
- Add only pure `review_request.build/applicability`, using ledger's
  `canonical/content_hash`. No new table, run manager, reviewer or policy.
- B owns consumption in `review_dispatch.optional`, atomic claim/receipt/reconcile
  and authentic receipt validation. This A commit does not edit that module.
- OBS-2B can later project request/result links; UI files are not touched.

## API for B

```python
request = review_request.build(
    root={'project_id': ledger.project_id, 'task_id': root['task_id']},
    contract_revision=root['approved']['revision'],
    contract_sha=root['approved']['sha'], review_id=review_id, required=False,
    facts=facts,  # existing review_dispatch._context snapshot, not invented input
    scope={key: item[key] for key in ('read', 'write', 'acceptance')},
    criteria=item['checks'], policy=normalized_approved_policy,
    authority=contract.get('authority', {}), budget=contract['budget'],
    execution=execution_metadata)
assessment = review_request.applicability(recorded_request, request)
```

`build` returns `version`, `id`, `identity`, `execution_complete`, `missing`.
Root/project, obligation, current context, scope, criteria, policy, grant and
original budget cannot collapse to another request. Mutable context includes
state/phase and unknown/finding lists: a conservative applicability bound, not
an inference that unchanged file names imply equivalent work. Generation zero
is valid because real first engine generations start at zero.

Execution metadata fields:

- `method`: `command`, `adapter`, `reviewer`, or `investigation`.
- `implementation`: caller-declared version/identity of the implementation.
- `configuration`: explicit mapping, possibly empty.
- `environment`, `provenance`: explicit nonempty mappings.
- `provider`, `model`: required for reviewer/investigation; optional otherwise.

Incomplete execution metadata can describe an observation but cannot authorize
cached reuse. Configuration/environment/provenance are fingerprinted, never
copied raw into the descriptor. Metadata is still a caller declaration; the
adapter does not authenticate a provider or establish reviewer independence.

`applicable=True` means an exact valid request match. `reusable=True` additionally
requires complete execution metadata. Neither grants authority, validates the
stored result, passes a check, closes a finding, or reserves budget. B must check
authentic receipt/provenance, current policy/grant/budget and run lifecycle.
Malformed/legacy descriptors return not applicable/not reusable. No historical
receipt is rewritten or silently upgraded to the new identity.

Pass original approved budget limits, not changing remaining time/usage. Known
volatile budget keys are rejected; dispatch retains the existing live budget
checks. Arrays whose ordering matters (checker config, criteria) preserve that
ordering; scope lists and unknown/finding name sets are normalized deterministically.

## Verification

Tests were written first. Baseline red was an import failure because the new
module did not exist; it is not counted as ten executed failing cases.
The first real `_context` test then exposed the generation-zero boundary, fixed
without weakening that test. Final focused run:

```powershell
python -B -X utf8 -m unittest tests.test_review_request tests.test_wf_evidence_binding.BindingPolicyTests -v
```

14 tests pass, zero skip. Log: `D:/OneCrewRuns/review-a-cycle1/tests.txt`.
Coverage includes each identity dimension, unknown execution, malformed and
recomputed-hash descriptors, nonfinite data, sensitive metadata fingerprinting,
first generation, real temporary ledger/context and hold transition. Constructing
the descriptor writes no ledger events. Existing evidence reuse policy controls
remain unchanged and pass.

Peer review follow-up: whitespace around `unknown` / `unverified` was initially
accepted as a known execution identifier. New counterexamples ran red on the
initial helper (three tests, 13 failing and five error subtests), preserved in
`D:/OneCrewRuns/review-a-cycle1/sentinels-red.txt`. The narrow correction trims
outer whitespace before case-insensitive sentinel detection for method,
implementation, provider and model; actual identifier case remains meaningful.
Stored normalized descriptors with outer whitespace or unknown sentinels are
invalid even with a recomputed hash. Final focused suite: **16/16**, zero skip,
21.679 seconds, `D:/OneCrewRuns/review-a-cycle1/sentinels-green.txt`.

## Limits and handoff

This is a helper cycle. B consumer integration, concurrency/recovery and tests on
the final assembled wheel remain required before a usable backend handover.
No full gate, real provider, UI, production ledger/hook or existing package changed.
No release/version bump, push, tag or owner acceptance. Broader milestone/candidate
cross-entrypoint unification, investigative review and UI metadata remain outside
this selected cycle and must not be marked complete from this commit.
