"""CG-<release> delivery gate for R01 ... RX2:  python -m wfkit.delivery_gate R01 --snapshot <snapshot gate decision.json>
    --bundle <release-check.json of that release> [--review review.json] --out <new receipt.json>

Rule (03-HOP-DONG-DRAFT.vi.md section 4): "Mỗi cổng giao do AI chạy, không cần chủ sở hữu." The gate needs no owner
acceptance and never records one. It judges, on ONE build identity (commit + wheel sha256 of the development snapshot gate):
  - acceptance: every acceptance testcase of the release in the snapshot gate's registry snapshot is `complete` (a partial/blocked part
    REFUSES the gate; nothing is relabelled);
  - implementation: the snapshot gate is intact and every registered implementation check is receipted with none failed;
  - the whole snapshot (Codex round 6 P1-2): EVERY entry of its `problems` is classified by development_gate.problem_scope. A GLOBAL
    problem (kit-guard, installed-origin, document-selfcheck, dirty/missing build, selected-only, implementation-checks, snapshot moved)
    refuses every release; another release's acceptance problem does not block this one (03 section 4) but is cross-checked; an
    unclassified problem, a missing field or contradictory information refuses (fail-closed, never defaulted to clean);
  - packaging (W40-Rnn): the release's T54 bundle verdict (wfkit.release_check) passed on this same build, by INPUTS or INPUTS(bootstrap);
  - independent review: a review record by a model other than the author's, on this commit, with result pass.
The other section 4 items that this producer does not judge are listed in `not_judged`; the receipt says so instead of claiming them.
The receipt has the shape of wfkit.gate's CG-R00 decision ({gate, release, decision, commit, wheel_sha256, at}) so that
wfkit.release_check accepts a PASSING one as gate_history of the next release.
"""
import argparse
import datetime as _dt
import hashlib
import json
from pathlib import Path

from wfkit import development_gate, release_check
from wfkit.finalgate import identity

RELEASES = tuple(release_check.PARTS)
NOT_JUDGED = ['counterexamples of every check caught (T38a doccheck)', 'v1/v2 test groups not newly broken', 'HD-05 decision-log completeness',
              'kit-guard manifest only added, never weakened', 'no owner question outside U1-U4', 'total budget not reset']


def _now():
    return _dt.datetime.now(_dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _detail(problem):
    if problem.get('kind') == 'implementation-checks':
        text = 'failed implementation checks: ' + '; '.join(f"{f.get('check')}: {f.get('reason')}" if isinstance(f, dict) else str(f) for f in problem.get('failures') or [])
    else:
        text = str(problem.get('detail') or problem.get('error') or problem)
    return text[:600]


def _read_snapshot(release, snapshot, why):
    """Fail-closed reading of a snapshot-gate decision.json (wfkit.development_gate snapshot). EVERY entry of `problems` is evaluated with the
    snapshot gate's own classification (development_gate.problem_scope): a global problem refuses this gate whatever release it is; an
    acceptance problem of ANOTHER release is cross-checked against that release's acceptance and then left to that release's own gate
    (03 section 4); an unclassified problem, a missing required field or contradictory information refuses. Returns (fields, others)."""
    def contradictory(detail): why('snapshot-contradictory', detail)
    def malformed(detail): why('snapshot-malformed', detail)
    if not isinstance(snapshot, dict): malformed('the snapshot gate decision is not an object'); snapshot = {}
    decision, problems, releases = snapshot.get('decision'), snapshot.get('problems'), snapshot.get('releases')
    snap, checks, acceptance = snapshot.get('snapshot'), snapshot.get('implementation_checks'), snapshot.get('acceptance')
    if decision not in ('pass', 'refused'): malformed(f'decision is {decision!r}, not pass or refused')
    if not isinstance(snapshot.get('release_delivery'), bool): malformed('release_delivery missing')
    elif snapshot['release_delivery'] is not (decision == 'pass'): contradictory(f"release_delivery {snapshot['release_delivery']} with decision {decision!r}")
    if not isinstance(problems, list): malformed('problems list missing'); problems = []
    if not isinstance(releases, list) or not releases or not all(isinstance(r, str) for r in releases): malformed('releases list missing'); releases = []
    elif release not in releases: why('release-not-in-snapshot', f'{release} is not among the releases this snapshot gate ran: {",".join(releases)}')
    if not isinstance(snap, dict) or not isinstance(snap.get('intact'), bool): malformed('snapshot.intact missing'); snap = snap if isinstance(snap, dict) else {}
    if not isinstance(snap.get('commit'), str): malformed('snapshot.commit missing')
    elif snap['commit'] != snapshot.get('commit'): contradictory(f"snapshot tree commit {snap['commit']} is not the decision commit {snapshot.get('commit')}")
    if not (isinstance(checks, dict) and all(isinstance(checks.get(k), int) and not isinstance(checks.get(k), bool) for k in ('expected', 'receipted'))
            and isinstance(checks.get('failed'), list)):
        malformed('implementation_checks {expected, receipted, failed} missing'); checks = checks if isinstance(checks, dict) else {}
    if not isinstance(acceptance, dict): malformed('acceptance missing'); acceptance = {}
    if decision == 'pass' and problems: contradictory(f'decision pass with {len(problems)} problems')
    if decision == 'refused' and not problems: contradictory('decision refused with no problem recorded' + (': ' + str(snapshot['error'])[:200] if snapshot.get('error') else ''))

    kinds, own, others, failures = set(), set(), {}, []
    for problem in problems:
        scope = development_gate.problem_scope(problem)
        if scope is None:
            why('problem-unknown', 'unclassified snapshot problem (refused, never treated as clean): ' + json.dumps(problem, ensure_ascii=False, default=str)[:300]); continue
        kind = problem['kind']; kinds.add(kind)
        if scope == 'global':
            why(kind, _detail(problem))
            if kind == 'implementation-checks': failures += list(problem.get('failures') or [])
            continue
        rel, tc = problem['release'], problem['testcase']
        criterion = acceptance.get(rel, {}).get(tc) if isinstance(acceptance.get(rel), dict) else None
        if rel not in releases: contradictory(f'{kind} of {rel}/{tc}: {rel} is not among the releases of this snapshot')
        elif not isinstance(criterion, dict) or 'acceptance-' + str(criterion.get('status')) != kind:
            contradictory(f'{kind} of {rel}/{tc} disagrees with its acceptance status {criterion.get("status") if isinstance(criterion, dict) else None!r}')
        if rel == release: own.add(tc)
        else: others[rel] = others.get(rel, 0) + 1
    moved = kinds & development_gate.SNAPSHOT_PROBLEMS
    if snap.get('intact') is False and not moved: contradictory('snapshot not intact but no snapshot problem recorded')
    if snap.get('intact') is True and moved: contradictory('snapshot recorded intact with ' + ', '.join(sorted(moved)))
    if isinstance(checks.get('failed'), list) and checks['failed'] != failures:
        contradictory(f"implementation_checks.failed {checks['failed']} differs from the implementation-checks problem {failures}")
    return {'snapshot': snap, 'checks': checks, 'acceptance': acceptance.get(release), 'own': own}, others


def decide(release, snapshot, bundle, review=None, sources=None):
    reasons = []

    def why(code, detail, testcase=None):
        reasons.append({'code': code, 'testcase': testcase, 'detail': detail})

    if release not in RELEASES: why('unknown-release', f'{release} has no CG delivery gate here (R00 uses wfkit.gate)')
    try:
        ident = identity(snapshot)
    except (ValueError, TypeError) as error:
        ident = {'commit': snapshot.get('commit') if isinstance(snapshot, dict) else None, 'wheel_sha256': None}; why('identity', str(error))
    fields, others = _read_snapshot(release, snapshot, why)
    acceptance = fields['acceptance']
    if not isinstance(acceptance, dict) or not acceptance:
        why('acceptance-missing', f'the snapshot gate carries no acceptance for {release}')
    else:
        for tc, criterion in sorted(acceptance.items()):
            status = criterion.get('status') if isinstance(criterion, dict) else None
            if status != 'complete':
                why('acceptance-' + str(status), f'{tc} is {status}: ' + '; '.join(g.get('detail', '') for g in (criterion or {}).get('gaps', []))[:300], tc)
                if tc not in fields['own']: why('snapshot-contradictory', f'{release}/{tc} is {status} but the snapshot records no problem for it', tc)
    if fields['snapshot'].get('intact') is not True: why('snapshot', 'the snapshot gate tree is not recorded intact')
    checks = fields['checks']
    if not (isinstance(checks.get('expected'), int) and checks.get('expected') > 0 and checks.get('receipted') == checks.get('expected') and checks.get('failed') == []):
        why('implementation', f"implementation checks {checks.get('receipted')}/{checks.get('expected')} receipted, failed {checks.get('failed')}")
    inputs = release_check.inputs_summary(bundle or {})
    if not isinstance(bundle, dict) or bundle.get('decision') != 'pass':
        why('packaging', 'the T54 bundle verdict did not pass: ' + '; '.join(f"{r.get('code')}: {r.get('detail')}" for r in (bundle or {}).get('reasons', []))[:400])
    elif bundle.get('release') != release or {'commit': bundle.get('commit'), 'wheel_sha256': bundle.get('wheel_sha256')} != ident:
        why('packaging', 'the T54 bundle verdict is for another release or build')
    if not isinstance(review, dict):
        why('independent-review', 'no independent review record (agent of another model than the author, on the release diff)')
    else:
        if review.get('result') != 'pass': why('independent-review', 'the review did not pass: ' + str(review.get('result')))
        if not review.get('reviewer_model') or review.get('reviewer_model') == review.get('author_model'):
            why('independent-review', 'reviewer model missing or equal to the author model')
        if not isinstance(review.get('commit'), str) or review.get('commit') != ident.get('commit'): why('independent-review', 'the review is for another commit')
        if 'wheel_sha256' in review and review['wheel_sha256'] != ident.get('wheel_sha256'): why('independent-review', 'the review is for another wheel')
    return {'gate': 'CG-' + str(release), 'release': release, 'decision': 'refused' if reasons else 'pass', 'reasons': reasons, **ident,
            'other_release_problems': others,
            'inputs_rule': inputs['code'], 'first_release': inputs['first_release'], 'not_judged': NOT_JUDGED,
            'owner_acceptance': False, 'delivered': False, 'sources': sources or {}, 'simulated': False,
            'provenance': {'kind': 'real', 'source': 'wfkit.delivery_gate decide'},
            'rule': '03 section 4: each delivery gate is run by the AI and needs no owner', 'at': _now()}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('release'); parser.add_argument('--snapshot', required=True); parser.add_argument('--bundle', required=True)
    parser.add_argument('--review'); parser.add_argument('--out', required=True)
    args = parser.parse_args(argv)
    out = Path(args.out)
    if out.exists(): raise SystemExit('the receipt must be a new file: ' + str(out))
    paths = {'snapshot': args.snapshot, 'bundle': args.bundle, **({'review': args.review} if args.review else {})}
    data = {k: json.loads(Path(p).read_text(encoding='utf-8')) for k, p in paths.items()}
    result = decide(args.release, data['snapshot'], data['bundle'], data.get('review'), {k: {'path': str(Path(p).resolve()), 'sha256': _sha(p)} for k, p in paths.items()})
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=1, sort_keys=True), encoding='utf-8')
    print(json.dumps({k: result[k] for k in ('gate', 'decision', 'commit', 'wheel_sha256')} | {'reasons': len(result['reasons'])}, ensure_ascii=False))
    return 0 if result['decision'] == 'pass' else 1


if __name__ == '__main__':
    raise SystemExit(main())
