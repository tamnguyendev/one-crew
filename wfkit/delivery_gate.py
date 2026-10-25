"""CG-<release> delivery gate for R01 ... RX2:  python -m wfkit.delivery_gate R01 --snapshot <snapshot gate decision.json>
    --bundle <release-check.json of that release> [--review review.json] --out <new receipt.json>

Rule (03-HOP-DONG-DRAFT.vi.md section 4): "Mỗi cổng giao do AI chạy, không cần chủ sở hữu." The gate needs no owner
acceptance and never records one. It judges, on ONE build identity (commit + wheel sha256 of the development snapshot gate):
  - acceptance: every acceptance testcase of the release in the snapshot gate's registry snapshot is `complete` (a partial/blocked part
    REFUSES the gate; nothing is relabelled);
  - implementation: the snapshot gate is intact and every registered implementation check is receipted with none failed;
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

from wfkit import release_check
from wfkit.finalgate import identity

RELEASES = tuple(release_check.PARTS)
NOT_JUDGED = ['counterexamples of every check caught (T38a doccheck)', 'v1/v2 test groups not newly broken', 'HD-05 decision-log completeness',
              'kit-guard manifest only added, never weakened', 'no owner question outside U1-U4', 'total budget not reset']


def _now():
    return _dt.datetime.now(_dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def decide(release, snapshot, bundle, review=None, sources=None):
    reasons = []

    def why(code, detail, testcase=None):
        reasons.append({'code': code, 'testcase': testcase, 'detail': detail})

    if release not in RELEASES: why('unknown-release', f'{release} has no CG delivery gate here (R00 uses wfkit.gate)')
    try:
        ident = identity(snapshot)
    except (ValueError, TypeError) as error:
        ident = {'commit': snapshot.get('commit') if isinstance(snapshot, dict) else None, 'wheel_sha256': None}; why('identity', str(error))
    acceptance = (snapshot.get('acceptance') or {}).get(release) if isinstance(snapshot, dict) else None
    if not isinstance(acceptance, dict) or not acceptance:
        why('acceptance-missing', f'the snapshot gate carries no acceptance for {release}')
    else:
        for tc, criterion in sorted(acceptance.items()):
            status = criterion.get('status') if isinstance(criterion, dict) else None
            if status != 'complete':
                why('acceptance-' + str(status), f'{tc} is {status}: ' + '; '.join(g.get('detail', '') for g in (criterion or {}).get('gaps', []))[:300], tc)
    snap = snapshot.get('snapshot', {}) if isinstance(snapshot, dict) else {}
    if snap.get('intact') is not True: why('snapshot', 'the snapshot gate tree is not recorded intact')
    checks = snapshot.get('implementation_checks', {}) if isinstance(snapshot, dict) else {}
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
        if review.get('commit') != ident.get('commit'): why('independent-review', 'the review is for another commit')
    return {'gate': 'CG-' + str(release), 'release': release, 'decision': 'refused' if reasons else 'pass', 'reasons': reasons, **ident,
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
