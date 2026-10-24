"""Read-only pilot kit rules (kit task WKPL): the T14c same-core comparison and the T45b / T45c entry gates.

Nothing here runs a pilot, invokes a provider, or writes a ledger. Every result carries ``pilot_evidence: False``
and ``owner_acceptance: False``. On fixture inputs (``mode: fixture`` plus ``allow_simulated``) the functions prove
the RULES only, as 05 T45 says ("Biên nhận giả lập ở selftest: chỉ chứng minh luật cổng"); no pilot is claimed.

* ``same_core(state_root, roots, reference)`` -- T14c kit. Given a state root (a temporary ledger in the selftest; the
  real PL-B pilot ledger later) and named roots ``{label: (project_path, plan_name)}``, it compares, for every root
  against the reference (CODE) root: the lifecycle (first occurrence order of the lifecycle event kinds), the
  budget/estimate record fields (``estimates.read`` keys) and the handover page shape (section structure of
  ``report.render_handover``). It only opens read transactions (``Ledger`` readers never create or migrate state).
  It will be run on the pilot ledger after PL-B (T14c); running it here proves the comparison, not a pilot.
* ``pl_a_entry(bundle, root, allow_simulated)`` -- T45b [E2], [E9], [E10]: PL-A starts only when the build passed
  the delivery gates of every release it contains (T33b, T54b, T54c, T54j receipts ``pass``), on the exact build hash
  the phase will run, and the job's project is not under the 2.1 monitor (a copy of it, or an unmonitored project, is
  accepted; its OneCrew config must point at the pilot state root; a job that must change the monitored project's
  hooks/config needs an answered owner U2 on the anchor task). It does not ask T35b (PL-A's own result).
* ``pl_b_entry(bundle, root, allow_simulated)`` -- T45c [E3], [E4], [E14], [E16], [E22]: same exact-hash rule over the
  delivery gates of the releases PL-B contains, the T35b interim report receipt and the interim report itself
  (``wfkit.pilot_report.check_report`` must pass for kind ``interim``; per-AC status read from ``ac_status``), a data
  or ops job only when T14b passed on that hash, the same project rule as PL-A, and the provider capability NL judged
  by the shared evaluators (``wfkit.provider_evidence.evaluate`` then ``wfkit.finalgate.provider_capability``): at least
  one ``usable`` reviewer cell of another model vendor than the pilot author, and every cell a pilot job pins usable.
  Cells nobody pins never hold the gate (case K, T55 C1). It does not ask T35c or T14c (PL-B's own results).

Bundle (schema 1): ``mode`` fixture|real; ``artifact`` {commit, wheel_sha256}; ``receipts`` {name: {path, sha256}}
(receipt JSON as in wfkit.finalgate: commit, wheel_sha256, result, testcase, at, simulated, provenance);
``pilot_state_root``; ``monitored_projects`` [path]; ``jobs`` [{id, project, state_root, kind (code|doc|data|ops),
[changes_monitored_config], [u2]: ref, [pins]: [cell]}]. PL-B adds ``author_vendor``, ``providers`` (six rows as in
finalgate), ``provider_items`` [{id, original: ref, supplements: [ref]}], ``interim_report`` {json: ref, md: ref}.
"""
import hashlib
import json
import os
import re
from pathlib import Path

from wfkit.finalgate import CELLS, Evidence, identity, require

LIFECYCLE = ('task.submitted', 'plan.proposed', 'plan.approved', 'verdict.run_started', 'verdict.receipt_issued',
             'verdict.recorded', 'milestone.passed', 'plan.accepted')
PL_A_GATES = ('T33b', 'T54b', 'T54c', 'T54j')                                    # 05 T45b: R01, R02, R03, RX1
# PL-B contains R00-R05, RP, RX1, RX2 (05 T45 fixture, build A). T45c's "Năng lực cần" omits W40-R04, but
# wfkit.finalgate KQ4 re-checks CG-R04 for PL-B, so the R04 delivery receipt (T54d) is required here too.
PL_B_GATES = ('T33b', 'T54b', 'T54c', 'T54d', 'T54e', 'T54i', 'T54j', 'T54k')
AC_STATUS = ('đạt', 'chưa đạt')                                                  # or 'chỉ phần …' (05 T45 [E4])
NO_REDUCTION = 'chưa kết luận giảm'
CRITERION = re.compile(r'^  [A-Z]+\d+ ')


# ---- T14c kit: same core over a state root -------------------------------------------------------------------------

def _events(ledger, task):
    rows, after = [], 0
    while True:
        page = ledger.events(task, after)
        if not page:
            return rows
        rows += page
        after = page[-1]['seq']


def _lifecycle(kinds):
    seen = []
    for kind in kinds:                    # first occurrence order: a retry or an amendment does not change the lifecycle
        if kind in LIFECYCLE and kind not in seen:
            seen.append(kind)
    return seen


def handover_shape(text):
    """Section structure of a handover page: the heading word, then each unindented section label in order."""
    lines = text.splitlines()
    shape = [lines[0].split(':')[0]] if lines else []
    for line in lines[1:]:
        if line and not line[0].isspace() and not line.startswith('- ') and line.rstrip().endswith(':'):
            shape.append(line.rstrip())
    shape.append(sum(1 for line in lines if CRITERION.match(line)))           # one row per acceptance criterion (status words excluded)
    return shape


def observe_root(state_root, project, name):
    from onecrew.ledger import Ledger
    from onecrew.v2 import estimates, plan as plans, report
    ledger = Ledger(project, state_root)
    with ledger.transaction() as conn:
        task = plans.derive(ledger, conn, name)['task_id']
    kinds = [e['kind'] for e in _events(ledger, task)]
    return {'lifecycle': _lifecycle(kinds), 'budget_fields': sorted(estimates.read(ledger, name)),
            'handover_shape': handover_shape(report.render_handover(ledger.state_root, name, project_id=ledger.project_id))}


def same_core(state_root, roots, reference='CODE'):
    """Compare every root with the reference root. roots: {label: (project_path, plan_name)}. Read-only."""
    require(isinstance(roots, dict) and reference in roots and len(roots) >= 2, 'reference root and at least one other root needed')
    observed, differences = {}, []
    for label, (project, name) in roots.items():
        try:
            observed[label] = observe_root(state_root, project, name)
        except Exception as exc:                                  # an unreadable root is a refusal, never a pass
            differences.append({'root': label, 'field': 'readable', 'detail': f'{type(exc).__name__}: {exc}'})
    if reference in observed:
        ref = observed[reference]
        for label, value in observed.items():
            for field in ('lifecycle', 'budget_fields', 'handover_shape'):
                if label != reference and value[field] != ref[field]:
                    differences.append({'root': label, 'field': field, 'expected': ref[field], 'actual': value[field]})
    return {'check': 'T14c same core', 'ok': not differences, 'reference': reference, 'roots': observed,
            'differences': differences, 'pilot_evidence': False, 'owner_acceptance': False,
            'proves': 'the comparison over the given state root; a pilot only when that state root is the PL-B ledger'}


# ---- T45b / T45c entry gates ---------------------------------------------------------------------------------------

def _same(path):
    return os.path.normcase(str(Path(path).resolve()))


def _receipt(ev, bundle, name, artifact):
    ref = bundle.get('receipts', {}).get(name)
    require(ref is not None, f'{name}: receipt missing')
    rec = ev.read(ref)
    require(rec.get('testcase', rec.get('gate')) == name, f'{name}: wrong receipt name')
    require(identity(rec) == identity(artifact), f"{name}: build hash differs (receipt {rec['wheel_sha256'][:12]}, "
                                                 f"phase {artifact['wheel_sha256'][:12]})")
    require(rec.get('result', rec.get('decision')) == 'pass', f'{name}: not pass')
    return rec


def _projects(ev, bundle):
    monitored = {_same(p) for p in bundle.get('monitored_projects', [])}
    pilot_root = bundle.get('pilot_state_root')
    require(isinstance(pilot_root, str) and pilot_root, 'pilot state root missing')
    jobs = bundle.get('jobs')
    require(isinstance(jobs, list) and jobs, 'no pilot job to admit')
    for job in jobs:
        jid = job.get('id', '?')
        require(_same(job['project']) not in monitored, f'{jid}: project is under the 2.1 monitor (use a copy or an unmonitored project)')
        require(_same(job.get('state_root', '')) == _same(pilot_root), f"{jid}: OneCrew config does not point at the pilot state root")
        if job.get('changes_monitored_config'):
            require(job.get('u2') is not None, f'{jid}: changes the monitored hooks/config without an answered U2')
            u2 = ev.read(job['u2'])
            require(u2.get('kind') == 'U2' and u2.get('actor') == 'owner' and u2.get('state') == 'answered'
                    and u2.get('task') == job.get('anchor_task') and job.get('anchor_task'), f'{jid}: U2 not answered by the owner on the anchor task')


def _gate(gate, bundle, root, allow_simulated, steps):
    result = {'gate': gate, 'decision': 'refused', 'conditions': {}, 'reasons': [],
              'pilot_evidence': False, 'owner_acceptance': False}
    try:
        require(isinstance(bundle, dict) and bundle.get('schema') == 1, 'bundle schema must be 1')
        require(bundle.get('mode') in ('real', 'fixture'), 'bundle mode missing')
        require(bundle['mode'] != 'fixture' or allow_simulated, 'fixture bundle requires allow_simulated')
        artifact = identity(bundle['artifact'])
    except (ValueError, KeyError, TypeError) as exc:
        result['reasons'] = [{'code': 'INPUT', 'detail': str(exc)}]
        return result
    ev = Evidence(root, bundle['mode'] == 'fixture')
    for code, fn in steps:
        try:
            fn(ev, artifact)
            result['conditions'][code] = True
        except (ValueError, KeyError, TypeError, AttributeError, OSError, StopIteration) as exc:
            result['conditions'][code] = False
            result['reasons'].append({'code': code, 'detail': str(exc) or type(exc).__name__})
    result.update(artifact)
    result['decision'] = 'refused' if result['reasons'] else 'pass'
    result['proves'] = 'entry rules only; no pilot claim' if ev.fixture else 'supplied receipts admit the phase; not a pilot result'
    return result


def pl_a_entry(bundle, root='.', allow_simulated=False):
    """T45b: PL-A entry gate."""
    def gates(ev, artifact):
        for name in PL_A_GATES:
            _receipt(ev, bundle, name, artifact)
    return _gate('T45b', bundle, root, allow_simulated, [
        ('delivery-gates', gates),
        ('project', lambda ev, artifact: _projects(ev, bundle))])


def _pinned_file(root, ref):
    require(isinstance(ref, dict) and isinstance(ref.get('path'), str), 'report reference missing')
    raw = (Path(root) / ref['path']).read_bytes()
    require(hashlib.sha256(raw).hexdigest() == ref.get('sha256'), f"report hash changed: {ref['path']}")
    return raw.decode('utf-8')


def interim_status(bundle, root):
    """T45c [E4]/[E6]: the PL-A interim report, checked by wfkit.pilot_report, with one status per AC1-AC5."""
    from wfkit import pilot_report
    ref = bundle.get('interim_report')
    require(isinstance(ref, dict), 'interim report (T35b) missing')
    report = json.loads(_pinned_file(root, ref['json']))
    checked = pilot_report.check_report(report, _pinned_file(root, ref['md']))
    require(checked['kind'] == 'interim' and checked['result'] == 'pass', f"interim report refused: {checked['problems']}")
    status = report.get('ac_status')
    require(isinstance(status, dict) and set(status) == {f'AC{i}' for i in range(1, 6)}, 'interim report needs one status per AC1-AC5')
    for key, value in status.items():
        text = value.get('status') if isinstance(value, dict) else value
        require(isinstance(text, str) and (text in AC_STATUS or text.startswith('chỉ phần ')), f'{key}: status {text!r} not in the catalog')
    ac3 = status['AC3'] if isinstance(status['AC3'], str) else status['AC3'].get('status')
    require(ac3 != 'đạt', 'AC3: a narrow phase cannot record all four kinds of work as đạt')
    ac5 = status['AC5']
    require(isinstance(ac5, dict) and ac5.get('tier3') == NO_REDUCTION, f'AC5: tier 3 must read "{NO_REDUCTION}" after PL-A')
    require(ac5.get('status') != 'đạt', 'AC5: a narrow phase cannot record AC5 tier 3 as đạt')
    return status


def provider_nl(ev, bundle, artifact):
    """NL through the shared evaluators: no local re-implementation of cell states or of the capability rule."""
    from wfkit.finalgate import provider_capability
    from wfkit.provider_evidence import evaluate
    rows = bundle['providers']
    states = evaluate(rows, bundle['provider_items'], ev, artifact, artifact, None)
    pins = sorted({p for job in bundle['jobs'] for p in job.get('pins', [])})
    require(set(pins) <= CELLS, 'unknown pinned provider cell')
    capability = provider_capability(rows, states, bundle['author_vendor'], pins)
    require(capability['independent_reviewer'], f"no usable reviewer of another vendor than the author ({bundle['author_vendor']})")
    require(not capability['missing_pins'], f"pinned cells not usable: {', '.join(capability['missing_pins'])}")
    require(capability['ok'], 'provider capability NL not met')
    return capability


def pl_b_entry(bundle, root='.', allow_simulated=False):
    """T45c: PL-B entry gate."""
    def gates(ev, artifact):
        for name in PL_B_GATES:
            _receipt(ev, bundle, name, artifact)

    def interim(ev, artifact):
        _receipt(ev, bundle, 'T35b', artifact)
        interim_status(bundle, root)

    def t14b(ev, artifact):
        if any(job.get('kind') in ('data', 'ops') for job in bundle.get('jobs', [])):
            try:
                _receipt(ev, bundle, 'T14b', artifact)
            except ValueError as exc:
                raise ValueError(f'data/ops job needs T14b (W39) passed on this build: {exc}') from None
    return _gate('T45c', bundle, root, allow_simulated, [
        ('delivery-gates', gates),
        ('interim-report', interim),
        ('T14b', t14b),
        ('project', lambda ev, artifact: _projects(ev, bundle)),
        ('provider-NL', lambda ev, artifact: provider_nl(ev, bundle, artifact))])
