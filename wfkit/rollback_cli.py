"""T49d [E5]/[E16] — the per-state rollback SCRIPT (exit code + message) and its per-root rollback REPORT.

    python -m wfkit.rollback_cli --state-root <disposable copy> --out <new dir under OS temp> [--venv <venv python>]

It adds no rule of its own. The decision is the existing gate: tests.wf_rollback.rollback_drill (checkout `compat scan`), and, when
--venv names the installed NEW build, wfkit.upgrade_drill.guard_swap with that build's own `compat scan --json` (W41: both must show zero
blocks on the same fenced ledger). Exit codes:
    0  allowed: the last scan reports 0 block conditions on this ledger hash (the swap itself stays wfkit.upgrade_drill's job);
    3  refused: message "refused: B1, B3 ..." names the exact remaining block set; NOTHING is uninstalled or installed;
    2  error: the state cannot be read safely (never a zero-block permission), or the venv package list changed.
With --venv the package list of that venv (pip list + the installed onecrew RECORD hash) is taken before and after and written to the
receipt.

The report (report.json + report.txt in --out) has one line per scanned root. Its label is derived from the SAME scan output the gate
decided on (`properties.old_readable` of compat_scan, W46b): "đọc OK" when the scan says the old binary reads it, otherwise "chỉ được bảo
toàn" (data intact, old binary cannot read it; T49c E13). The scan never says a root is lost and the old binary diagnoses nothing
(05 T49 boundary, 00 §6.1: diagnosis comes from the new build's scan), so "mất" and "đã chẩn đoán bởi bản cũ" are never produced and the
report check (wfkit.rollback_report_check) refuses them. The diagnosis source of every line is the content hash of scan.json.
This is fixture tooling on a COPY of a state root; it is not a release gate, a pilot or owner acceptance.
"""
import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from onecrew.ledger import LedgerError, content_hash

READ_OK = 'đọc OK'
PRESERVED_ONLY = 'chỉ được bảo toàn'
LOST = 'mất'
DIAGNOSED_BY_OLD = 'đã chẩn đoán bởi bản cũ'
LABELS = (READ_OK, PRESERVED_ONLY)               # what the scan can justify
FORBIDDEN = (LOST, DIAGNOSED_BY_OLD)             # never justified by the scan (E13/E16; 00 §6.1)
DIAGNOSIS_SOURCE = 'compat scan of the new build (not the old binary)'
EXIT_ALLOWED, EXIT_ERROR, EXIT_REFUSED = 0, 2, 3


def label_for(root):
    """The single mapping from one compat_scan root to a report label (used by the report AND the report check)."""
    return READ_OK if root['properties']['old_readable'] else PRESERVED_ONLY


def root_key(root):
    return (root['project_id'], root['anchor'])


def scan_sha(scan):
    return content_hash(scan)


def build_report(scan, decision):
    """One line per scan root, from the scan the gate decided on."""
    sha = scan_sha(scan)
    lines = [{'project_id': r['project_id'], 'anchor': r['anchor'], 'name': r['name'], 'label': label_for(r), 'status': r['status'],
              'blocks': [b['id'] for b in r['blocks']], 'properties': dict(r['properties']),
              'diagnosis_source': {'kind': DIAGNOSIS_SOURCE, 'scan_sha': sha}} for r in scan['roots']]
    return {'schema': 1, 'kind': 'rollback-report', 'decision': decision, 'scan_sha': sha, 'ledger_sha': scan.get('ledger_sha'),
            'old_version': scan.get('old_version'), 'lines': lines,
            'warnings': [w.get('message') for w in scan.get('warnings', [])]}


def report_text(report):
    out = [f"rollback: {report['decision']['message']}",
           f"scan {report['scan_sha']} (ledger {report['ledger_sha']}, old version {report['old_version']})"]
    for line in report['lines']:
        blocks = ', '.join(line['blocks']) or '-'
        out.append(f"{line['project_id']} {line['anchor']}: {line['label']}; status {line['status']}; blocks {blocks}")
    out += ['WARNING ' + w for w in report['warnings'] if w]
    return '\n'.join(out) + '\n'


_RECORD = ('import hashlib,json\nfrom importlib.metadata import distribution\n'
           'try:\n    d=distribution("onecrew"); r=d.read_text("RECORD") or ""\n'
           '    print(json.dumps({"version":d.version,"record_sha256":hashlib.sha256(r.encode()).hexdigest()}))\n'
           'except Exception:\n    print(json.dumps({"version":None,"record_sha256":None}))\n')


def venv_packages(python):
    """Package list of the venv: `pip list --format=json` plus the bytes of the installed onecrew RECORD (no partial uninstall)."""
    listed = subprocess.run([str(python), '-I', '-m', 'pip', 'list', '--format=json', '--disable-pip-version-check'],
                            capture_output=True, text=True, timeout=180)
    if listed.returncode:
        raise LedgerError('pip list failed in ' + str(python) + ': ' + listed.stderr[-400:])
    record = subprocess.run([str(python), '-I', '-c', _RECORD], capture_output=True, text=True, timeout=120)
    return {'pip_list': sorted(json.loads(listed.stdout), key=lambda p: p['name'].lower()),
            'onecrew': json.loads(record.stdout or '{}')}


def installed_scan(python, state_root):
    """The installed NEW build's own `compat scan --json` (guard_swap's second decider)."""
    result = subprocess.run([str(python), '-I', '-X', 'utf8', '-m', 'onecrew.v2.compat_cli', '--state-root', str(state_root), 'scan', '--json'],
                            capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=180)
    if result.returncode:
        raise LedgerError('installed compat scan failed: ' + (result.stdout + result.stderr)[-600:])
    return json.loads(result.stdout)


def decide(state_root, python=None):
    """The existing gate; returns (gate result, the scan it decided on)."""
    from tests import wf_rollback
    if python is None:
        gate = wf_rollback.rollback_drill(state_root)
        return gate, gate['scan']
    from wfkit import upgrade_drill
    expected = installed_scan(python, state_root)
    return upgrade_drill.guard_swap(state_root, expected), expected


def run(state_root, out, python=None):
    """Returns (exit code, message, receipt). Writes scan.json, report.json, report.txt, receipt.json into `out`."""
    out = Path(out).resolve()
    if not out.is_relative_to(Path(tempfile.gettempdir()).resolve()) or out.exists():
        raise LedgerError('--out must be a NEW directory under OS temp.')
    state_root = Path(state_root).resolve()
    if out.is_relative_to(state_root):
        raise LedgerError('--out must not be inside the state root.')
    before = venv_packages(python) if python else None
    gate, scan = decide(state_root, python)
    conditions = sorted({b['id'] for r in scan['roots'] for b in r['blocks']})
    if gate['ran']:
        code, message = EXIT_ALLOWED, f"allowed: 0 block conditions on ledger {scan['ledger_sha']}"
    else:
        remaining = gate.get('conditions') or conditions
        code, message = EXIT_REFUSED, 'refused: ' + ', '.join(remaining) + ' (remaining block conditions; the new build stays installed)'
    after = venv_packages(python) if python else None
    if python and before != after:
        code, message = EXIT_ERROR, 'error: the venv package list changed during the rollback decision'
    out.mkdir(parents=True)
    (out / 'scan.json').write_text(json.dumps(scan, ensure_ascii=False, sort_keys=True, indent=1), encoding='utf-8')
    decision = {'result': {EXIT_ALLOWED: 'allowed', EXIT_REFUSED: 'refused'}.get(code, 'error'), 'exit_code': code, 'message': message,
                'conditions': conditions, 'gate': 'upgrade_drill.guard_swap' if python else 'wf_rollback.rollback_drill'}
    report = build_report(scan, decision)
    (out / 'report.json').write_text(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=1), encoding='utf-8')
    (out / 'report.txt').write_text(report_text(report), encoding='utf-8')
    receipt = {'schema': 1, 'state_root': str(state_root), 'decision': decision, 'scan_sha': report['scan_sha'],
               'venv_python': str(python) if python else None, 'packages_before': before, 'packages_after': after,
               'packages_equal': (before == after) if python else None, 'swapped': False,
               'release_gate': False, 'owner_acceptance': False}
    (out / 'receipt.json').write_text(json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=1), encoding='utf-8')
    return code, message, receipt


def main(argv=None):
    parser = argparse.ArgumentParser(prog='python -m wfkit.rollback_cli', description=__doc__.split('\n')[0])
    parser.add_argument('--state-root', required=True)
    parser.add_argument('--out', required=True)
    parser.add_argument('--venv', default=None, help='python of the venv holding the installed NEW build')
    args = parser.parse_args(argv)
    try:
        code, message, _ = run(args.state_root, args.out, args.venv)
    except (LedgerError, OSError, ValueError, subprocess.SubprocessError) as error:
        print('error: ' + str(error), file=sys.stderr)
        return EXIT_ERROR
    print(message, file=sys.stdout if code == EXIT_ALLOWED else sys.stderr)
    return code


if __name__ == '__main__':
    raise SystemExit(main())
