# Run the T54 bundle producer for every release (W40-R01 … W40-RX2) and write an index release -> release-check.json for the release-notes
# generator and the package builder.   python docs/wf/audit/tools/run_bundles.py <out root (new, under OS temp)> [--gate decision.json] [--only R05,R08] [--first-release] [--baseline-wheel stored.whl] [--gate-history CG-receipt.json ...]
import argparse, json, os, subprocess, sys, tempfile
from pathlib import Path

R = Path(os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..', '..')))
RELEASES = ['R01', 'R02', 'R03', 'R04', 'R05', 'R06', 'R07', 'R08', 'RP', 'RX1', 'RX2']


def keep_result(target, rel, result, done):
    """-> the path that goes in the index for this release. A produced bundle is its release-check.json; a release the producer refused or that failed
    (no release-check.json, e.g. RP without --matrix) is NOT dropped: its decision and reason are written to <target>/bundle-result.json (round 11 D)."""
    check = target / 'release-check.json'
    if check.exists():
        return check
    target.mkdir(parents=True, exist_ok=True)
    reason = result.get('reason') or (done.stderr or done.stdout or '')[-600:] or 'the producer wrote no release-check.json'
    path = target / 'bundle-result.json'
    path.write_text(json.dumps({'release': rel, 'decision': result.get('decision') if result.get('decision') in ('refused', 'blocked') else 'error', 'produced': False,
                                'conditions': result.get('conditions') or {}, 'reasons': result.get('reasons') or [{'code': 'PRODUCER', 'detail': reason}], 'reason': reason,
                                'producer_exit': done.returncode}, ensure_ascii=False, indent=1), encoding='utf-8')
    return path


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('out'); ap.add_argument('--gate'); ap.add_argument('--only'); ap.add_argument('--matrix', help='W45 matrix dir (RP)')
    ap.add_argument('--baseline-wheel', help='stored baseline wheel (with sidecar) every producer reuses instead of rebuilding d3120c6')
    ap.add_argument('--gate-history', action='append', help='CG- delivery gate receipt (repeatable) passed to every producer: the normal INPUTS rule')
    ap.add_argument('--first-release', action='store_true', help='pass --first-release to every producer (first delivery; judged as INPUTS(bootstrap))'); a = ap.parse_args()
    out = Path(a.out).resolve()
    if not out.is_relative_to(Path(tempfile.gettempdir()).resolve()): sys.exit('out must be under the OS temp dir (the producer refuses anything else)')
    out.mkdir(parents=True, exist_ok=True)
    env = {k: v for k, v in os.environ.items() if k not in ('CLAUDE_CODE_CHILD_SESSION', 'CLAUDECODE', 'ONECREW_ACTOR')}
    env['PYTHONPATH'] = os.pathsep.join(['.', 'tests'])
    index, summary = {}, {}
    for rel in (a.only.split(',') if a.only else RELEASES):
        target = out / rel
        cmd = [sys.executable, '-X', 'utf8', '-m', 'wfkit.release_bundle', rel, '--out', str(target)] + (['--gate', a.gate] if a.gate else []) + (['--matrix', a.matrix] if a.matrix and rel == 'RP' else []) + (['--first-release'] if a.first_release else []) + (['--baseline-wheel', str(Path(a.baseline_wheel).resolve())] if a.baseline_wheel else []) + [x for h in (a.gate_history or []) for x in ('--gate-history', str(Path(h).resolve()))]
        done = subprocess.run(cmd, cwd=str(R), env=env, capture_output=True, text=True, encoding='utf-8', errors='replace')
        line = next((l for l in done.stdout.splitlines() if l.startswith('{')), None)
        result = json.loads(line) if line else {'decision': 'error', 'reason': (done.stdout + done.stderr)[-600:]}
        summary[rel] = {k: result.get(k) for k in ('decision', 'conditions', 'reasons', 'reason')}
        index[rel] = str(keep_result(target, rel, result, done))
        print(rel, result.get('decision'), result.get('conditions') or result.get('reason', '')[:300], flush=True)
    (out / 'bundles-index.json').write_text(json.dumps(index, ensure_ascii=False, indent=1), encoding='utf-8')
    (out / 'bundles-summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding='utf-8')
    print(json.dumps({'index': str(out / 'bundles-index.json'), 'bundles': len(index)}))


if __name__ == '__main__':
    main()
