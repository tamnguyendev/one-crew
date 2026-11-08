# 2.5-B cycle 1 — optional review coordination

Baseline: `bdb13bf` / product `6cb2fa9`. This isolated branch does not modify the
OBS-2 patch, published packages or a real runtime. Dependency: 2.5-A's pure
`review_request.py` from `740fd2f`; parent integrates that file first.

## Selected requirement and result

The existing optional review consumer reused a completed observation sequentially,
but two concurrent calls both passed its read-before-call check. The baseline
counterexample used the real `DeepReviewDispatchTests` fixture and a barrier in a
local checker: two invocations, two `executed: true` observations for the same key.
No provider was used.

`review_dispatch.optional` now records an atomic per-request claim on the existing
root events ledger. A matching active invocation returns `pending` and the original
run ID. A lost/exceptional invocation without an issued result is `held`; elapsed
time is never permission to invoke the checker again. Different request identities
remain independent. No queue, schema, lease, worker or model call is added.

The result blob is issued before publication. `reconcile_optional(ledger, selector,
run_id)` can finish publication only from that issued blob after validating its
hash, request, root and original input binding. It accepts no caller-supplied
outcome. Missing/corrupt evidence is not a reason to silently redispatch. A result
whose inputs changed remains a stale observation, never a node verification.

## Identity and existing callers

- New optional keyword `execution` on `review_dispatch.optional` and the existing
  `engine.review_optional` wrapper carries a trusted adapter's declaration. The
  shared 2.5-A helper fingerprints configuration, environment and provenance.
  Raw values are not persisted in lifecycle events.
- Complete metadata permits exact-key, authenticated *observation* reuse; it is
  not proof that the declared reviewer is independent or that the observation is
  a mandatory pass. Consumers must not accept model-supplied identity as trusted.
- Legacy callable-only consumers still execute and return observations. They
  explicitly report missing identity and do not reuse a completed request as an
  authenticated cache hit. This may perform another requested optional check;
  it deliberately avoids claiming two unknown checkers are equivalent.
- `engine_cli` currently supplies CandidateChecker without this metadata. This
  experimental backend slice therefore does not claim completed-cache reuse for
  the production CLI; connecting its actual selected verifier/environment is a
  later integration task, not a fabricated function-name identity.
- Recovering the issued result of the original run is `reconciled`, distinct from
  `cached_observation` on a new fully identified invocation.
- Existing injected checkers keep responsibility for actual calls, time budgets,
  isolation and receipts. The coordinator does not reserve a second Control call:
  that would double charge the provider and consume an unnecessary worker slot.

The four lifecycle event kinds are neutral class A additions. They do not change
milestone/node state, mandatory checks, approval, acceptance or human requests.
Unknown event kinds retain the old refusal. An older runtime does not participate
in the new coordination guarantee; do not claim deduplication across mixed old/new
writers.

## Verification

- `tests/test_review_dispatch_lifecycle.py`: concurrent requests, completed reuse,
  unknown outcome/restart, issued-result recovery, changed input, incomplete
  checker identity, corrupt receipt, distinct checker identity, secret-free
  fingerprints and event compatibility.
- `tests/test_wf_review_dispatch.py`: existing SKIP/DEFER/HOLD/mandatory invariants;
  its cache fixture now supplies explicit local checker metadata.
- `docs/review/verify_optional_wheel.py`: standalone installed-wheel smoke. Invoke
  using the final wheel venv's Python, outside checkout:

  `python -I -B -X utf8 verify_optional_wheel.py <new-output-directory>`

  It imports no checkout test package. It creates a temporary Git project, sổ,
  synthetic approval and synthetic candidate; callbacks simulate local checks.
  It exercises the real optional consumer and records source of the imported
  module, eleven assertions and preservation of the real hook registry. Synthetic
  approval is not evidence of a human approval or provider pilot.

Source smoke passed 10/10. Final source test totals and installed-wheel evidence
are recorded by the integrating parent; checkout success alone is not artifact
acceptance.

## Deliberately unfinished 2.5-B work

- No common run mapping between `verdict.run`, CandidateChecker and engine.verify
  yet. Hook Stop remains a reminder, not a reviewer dispatcher.
- No investigation-worker executor, cross-entry receipt reuse or pipeline changes.
- Unknown outcomes without issued evidence remain held. This slice has no release
  verb or inferred retry; an actual recovery policy must establish the original
  effect before a later slice adds that path.
- Process liveness is conservative: a live/reused PID may remain pending; timeout
  does not authorize duplicate work. This is not a claim of exactly-once provider
  execution across network/crash boundaries.
- No real provider, UI changes, full gate, version bump, runtime upgrade, push/tag
  or release. Full 2.5-B remains Partial.
