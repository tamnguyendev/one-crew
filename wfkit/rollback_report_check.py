"""T49d [E16] — check a rollback report against the scan it claims to come from.

    python -m wfkit.rollback_report_check <report.json> <scan.json>      exit 0 ok, 1 refused (one line per offending root), 2 unreadable

Every scan root must have exactly one line; no line may name a root the scan does not have; each line's label, status and block set must
equal what wfkit.rollback_cli.label_for derives from the scan (the same mapping the report uses, no second rule); "mất" and
"đã chẩn đoán bởi bản cũ" are refused by name because the scan never justifies them; the diagnosis source must be the scan's own hash.
"""
import json
import sys
from pathlib import Path

from wfkit.rollback_cli import DIAGNOSED_BY_OLD, LABELS, LOST, label_for, root_key, scan_sha


def violations(report, scan):
    bad = []
    sha = scan_sha(scan)
    if report.get('scan_sha') != sha:
        bad.append(f'report scan_sha {report.get("scan_sha")} != hash of the scan {sha}')
    roots = {root_key(r): r for r in scan['roots']}
    seen = {}
    for line in report.get('lines', []):
        key = (line.get('project_id'), line.get('anchor'))
        where = f'{key[1]} (project {key[0]})'
        if key in seen:
            bad.append(f'{where}: more than one line')
            continue
        seen[key] = line
        root = roots.get(key)
        if root is None:
            bad.append(f'{where}: not a root of the scan')
            continue
        want, got = label_for(root), line.get('label')
        readable = root['properties']['old_readable']
        if got == LOST:
            bad.append(f'{where}: labelled "{LOST}" but the scan keeps its data (old_readable={readable}); the scan says "{want}"')
        elif got == DIAGNOSED_BY_OLD:
            bad.append(f'{where}: labelled "{DIAGNOSED_BY_OLD}" but the diagnosis is the new build\'s scan (old_readable={readable}); '
                       f'the scan says "{want}"')
        elif got not in LABELS or got != want:
            bad.append(f'{where}: labelled "{got}", the scan says "{want}" (old_readable={readable})')
        if line.get('status') != root['status']:
            bad.append(f'{where}: status {line.get("status")!r}, the scan says {root["status"]!r}')
        if line.get('blocks') != [b['id'] for b in root['blocks']]:
            bad.append(f'{where}: blocks {line.get("blocks")}, the scan says {[b["id"] for b in root["blocks"]]}')
        if (line.get('diagnosis_source') or {}).get('scan_sha') != sha:
            bad.append(f'{where}: diagnosis source is not this scan')
    for key in roots:
        if key not in seen:
            bad.append(f'{key[1]} (project {key[0]}): missing from the report')
    return bad


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 2:
        print('usage: python -m wfkit.rollback_report_check <report.json> <scan.json>', file=sys.stderr)
        return 2
    try:
        report, scan = (json.loads(Path(p).read_text(encoding='utf-8')) for p in argv)
    except (OSError, ValueError) as error:
        print('error: ' + str(error), file=sys.stderr)
        return 2
    bad = violations(report, scan)
    for item in bad:
        print('refused: ' + item, file=sys.stderr)
    if not bad:
        print(f'ok: {len(report["lines"])} lines match scan {scan_sha(scan)}')
    return 1 if bad else 0


if __name__ == '__main__':
    raise SystemExit(main())
