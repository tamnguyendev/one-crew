# R00 - WF 2.2.x foundation: DONE

Release **R00** (the WF 2.2.x foundation) built end-to-end in worktree `D:\TamNT\Workspace\11.OneCrew\wf-r00`
on branch `wf/r00`, cut from baseline `ee46539` (claude/v22-trust-fixes, 2.2.0.dev3, the v2-wheel baseline carrying onecrew/v2/).

All 8 R00 WF tasks are implemented, wired into the installed wheel path (pyproject py-modules), their named testcases pass on the final
commit, and the baseline suite still passes. The "old version" in every compatibility test is the UNMODIFIED archive of `ee46539`
(the rollback target), run via `git archive ee46539` + PYTHONPATH - no edits, no wrapper, no separate wheel. Tests use stdlib unittest.

## Tasks

### W03 - decision record; wire interventions into the wheel (T20)
- Files: `onecrew/v2/decisions.py` (new), `onecrew/interventions.py` (owner-actor guard), `pyproject.toml` (ship onecrew.interventions + onecrew.v2.decisions), `tests/test_wf_decisions.py`
- `decisions.record` writes a decision with a real subject (component, model), authority basis (grant_id, revision) and non-empty evidence; `by=owner` from an AI session is refused and nothing is written. `interventions.record` refuses an owner/user actor from an AI session. `decision.recorded` is a class-A neutral event.
- Tests: `tests/test_wf_decisions.py` DecisionRecordTests (E1 subject/authority/evidence; E2/E3 by=owner refused + nothing written; E4 no-authority refused; counters) and InterventionActorGuardTests (E5 owner-actor refused + count unchanged, AI actor +1).
- commit 28bcf48e934734239ebcba56fc0da220062588b8

### W11a - event-type ledger + old-version comparator (T13a)
- Files: `onecrew/v2/compat.py` (new: class 0/A/B ledger, class-0 required fields, `check_write`), `onecrew/v2/plan.py` (guard `emit`), `pyproject.toml`, `tests/wf_oldversion.py` (new: reusable old-binary harness + S/G/C/H/V comparator), `tests/test_wf_events.py`
- The boundary is judged by event CLASS, not by derive()'s KINDS tuple. `plan.emit` refuses a class-B event or a shape-changed class-0 payload on a `plan:` anchor; it is a no-op on `plan-ns:` and non-plan tasks. The S/G/C/H/V comparator (reused by T35a/T41b/T49) runs the real archived old binary.
- Tests: `tests/test_wf_events.py` EventClassLedgerTests (E1 every written kind class 0/A; E13 task.submitted class-0 though outside KINDS; E12 class-B refused; E14 intent class-B; E6 class-0 missing field = read block; unknown-kind refused) and OldVersionComparatorTests (real ee46539: R0+A keeps S/G/C; plan.revoked read wrong; malformed plan.accepted crashes old reader).
- commit fa35f8d4e10b247189db9d63ed8de20da29771c6

### W46a - read-only `compat scan` (T49a)
- Files: `onecrew/v2/compat_scan.py` (new), `onecrew/v2/compat_cli.py` (new), `onecrew/v2/cli.py` (route the `compat` group), `onecrew/v2/compat.py` (narrow class-0 read-block fields to what old derive() dereferences), `pyproject.toml`, `tests/test_wf_compat_scan.py`
- `onecrew compat scan` reports per `plan:` root: 3 properties (unchanged / old_readable / old_continuable), status by old rules, event classes, and block conditions SPLIT into read-block B4 (even when accepted) and continue-block B2 (released by accepted, not by paused), plus a per-command prediction matching the real old binary. Read-only (report._Reader mode=ro); `--out` refused inside the state root; defensive (never derives, so it survives a B4 root).
- Tests: `tests/test_wf_compat_scan.py` CompatScanTests (E1 rows/properties; E3 blocks named with type+release; E23 accepted does not release B4; E2 predictions match the real old binary; E24 per-command; E4/E15 read-only; E18 paused does not release; installed-CLI path + --out refusal).
- commit 43359ac4dccfca965b5137ddc412ff5c81471382

### W12a - plan-name validation + same-name refusal (T48a)
- Files: `onecrew/v2/plan.py` (`valid_plan_name`, wired into `propose`), `tests/test_wf_plan_names.py`. Lịch sử: `refuse_duplicate_name` (từ chối trùng tên giữa hai project) là hành vi R00 tại commit cũ của lineage; R04/W12b thay bằng không gian tên theo project (`plan-ns:`, `plans/<project_id>/<tên>`) và hàm này được gỡ khỏi mã hiện hành (24/10, succession ghi ở `wfkit/namespace-lineage.json`, E10 của T48a vẫn chạy trên binary cũ trong `tests/test_wf_plan_names.py`).
- A plan name with `:`, a path separator, `..`, a drive form or an absolute/rooted path is refused before any write. In a shared state root, a second project reusing a name is refused (naming the other project), writing nothing. Storage path unchanged (W12b/R04 adds per-project namespacing).
- Tests: `tests/test_wf_plan_names.py` PlanNameValidationTests (E1 forbidden names rejected before any write; E5 drive form writes nothing outside; valid name accepted) and SameNameAcrossProjectsTests (E10/E11 second project refused, P1 untouched; same-project re-create = already exists).
- commit aa2c54d3215b447d65521e91a83df36302adb8a2

### W27a - typed advisor provider errors (T09a)
- Files: `onecrew/v2/verifiers/advisor.py` (classify provider_unavailable/timeout/invalid_response, record on plan.advised), `onecrew/v2/step0.py` (provider-error advice is inconclusive, not advice_missing), `tests/test_wf_advisor_errors.py`
- A typed advisor provider error becomes an inconclusive verdict with its reason, and does NOT block approval with `advice_missing`; the owner is not forced into a second round; the pinned provider/model is unchanged. Red on the pre-fix code (step0.py:265-270), green on the fix.
- Tests: `tests/test_wf_advisor_errors.py` AdvisorProviderErrorTests (E1 each kind typed inconclusive; E2/E12 approval not blocked + no advice_missing; counter: genuinely missing advice still blocks; E3/E14 pinned model unchanged, no fallback). RED-on-baseline verified by stashing the fix (6 errors + 1 failure) then GREEN with the fix.
- commit 1cb048d6dc05ad9b1c26db7626c5356f825dd837

### W40 - packaging + runtime install-boundary check (T33a)
- Files: `onecrew/v2/boundary.py` (new: the module-boundary classification), `pyproject.toml` (ship onecrew.v2.boundary), `tests/wf_wheel.py` (new: hand-build the wheel without setuptools + offline venv install + ctx from the installed RECORD + interpreter stdlib markers), `tests/test_wf_packaging.py`
- At the end of an installed-command run, every module in sys.modules must be a valid group: onecrew (shipped name + file in RECORD), stdlib (markers from `python -I -S` + find_spec, not hard-coded Lib), declared dependency (RECORD), or `__main__`. Startup-loaded modules are NOT exempt (only the clean-venv base packages). R00 scenarios run from the INSTALLED command.
- Tests: `tests/test_wf_packaging.py` InstallBoundaryTests, built on a real offline-installed wheel: M1 parents PASS, M2 _sqlite3/_socket in DLLs PASS, M3 built-in/frozen PASS, M4 checkout-shadow FAIL, M5 v1 module FAIL, M6 undeclared pip FAIL, M7 fake csv FAIL, M8 startup checkout FAIL; the previous rule misflags M1/M2 (counter); an installed R00 scenario runs clean.
- commit 05bdb7679c42137688d08b6a30f7385080229710

### W41 - upgrade / rollback / roll-forward drill (T13b, T49b)
- Files: `tests/wf_rollback.py` (new: the drill on a ledger COPY, gated by compat scan), `tests/test_wf_rollback.py`
- The drill runs on a COPY of a ledger (never a real state root). `compat scan` is the gate: the rollback script refuses while any block (read B4 or continue B2) holds and runs only when the last scan reports 0, on the same ledger hash. Reject and success branches are separate. Roll-forward preserves ids, revision, evidence and spent budget.
- Tests: `tests/test_wf_rollback.py` RollbackDrillTests - T13b (upgrade preserves ids/budget/evidence/unreconciled-attempt; old root reads old semantics) and T49b (N8 B2 refuses; N9 B4 refuses though X1 accepted; N10 B4 refuses with X1 paused; N11 scan=0 runs and old binary reads R1/X2/digest; diagnosis source is the scan hash; roll-forward preserves everything).
- commit c3ad00a4749be1e6a4a756d3a7cabc0a439950ad

## Testcase runs (stdlib unittest; dots+OK go to STDERR on this shell, so read the OK line)

Run from the worktree root with tests/ on the path (the suite's sibling-import convention):
`set PYTHONPATH=D:\TamNT\Workspace\11.OneCrew\wf-r00;D:\TamNT\Workspace\11.OneCrew\wf-r00\tests`

| Testcase | Command | Result |
|---|---|---|
| T20  | `python -m unittest tests.test_wf_decisions`     | Ran 8 tests ... OK |
| T13a | `python -m unittest tests.test_wf_events`        | Ran 10 tests ... OK |
| T49a | `python -m unittest tests.test_wf_compat_scan`   | Ran 9 tests ... OK |
| T48a | `python -m unittest tests.test_wf_plan_names`    | Ran 5 tests ... OK |
| T09a | `python -m unittest tests.test_wf_advisor_errors`| Ran 7 tests ... OK |
| T33a | `python -m unittest tests.test_wf_packaging`     | Ran 10 tests ... OK |
| T13b, T49b | `python -m unittest tests.test_wf_rollback`| Ran 8 tests ... OK |

Total: 57 WF R00 tests, OK.

## Baseline suite still passes (regression; the changed modules are plan.py, step0.py, advisor.py, interventions.py, pyproject.toml)

| Suite | Result |
|---|---|
| `tests.test_g1_core`       | Ran 23 tests ... OK  (closure/packaging intact with the 6 new shipped modules) |
| `tests.test_g2_install`    | Ran 46 tests ... OK |
| `tests.test_v2_l1`         | Ran 41 tests ... OK |
| `tests.test_v2_l2`         | Ran 54 tests ... OK |
| `tests.test_v2_l3`         | Ran 31 tests ... OK |
| `tests.test_v2_advisor`    | Ran 44 tests ... OK |
| `tests.test_v2_fix`        | Ran 47 tests ... OK |
| `tests.test_v2_report`     | Ran 25 tests ... OK |
| `tests.test_v2_reviewer`   | Ran 32 tests ... OK |
| `tests.test_v2_trust_fixes`| Ran 80 tests ... OK |
| `tests.test_interventions` | Ran 13 tests ... OK |
| `tests.test_control`       | Ran 18 tests ... OK (skipped=1) |
| `tests.test_ledger`        | Ran 19 tests ... OK |

## New shipped wheel modules (pyproject py-modules)
onecrew.interventions, onecrew.v2.decisions, onecrew.v2.compat, onecrew.v2.compat_scan, onecrew.v2.compat_cli, onecrew.v2.boundary

## Reuse (per 02-TAI-SU-DUNG-V1-V2)
- Extended v2 plan.emit / step0.check_provenance / advisor (TD03), reused report._Reader + report._anchors/_gather for the read-only scan, reused ownership.refuse_in_ai_session + interventions.record (TD26). No second event store, scheduler or finding register was created.

## Non-goals respected
No P0/P0b content, no R01+ features, no deferred branches (RD/RR/RL; T09b/T09c local-fallback/cache/init explicitly out of scope), no doc-checker expansion, no new framework. No testcase or kit-guard weakened. No push, tag, deploy, or force-push; the real ledger/state-root and other worktrees untouched; branch claude/delivery-runtime-recovery never touched.
