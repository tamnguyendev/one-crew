"""`onecrew compat scan` — the read-only compatibility scan (W46a). Prints one line per `plan:` root and a JSON body. The only optional
write is `--out <file>`, which is refused inside the state root (the scan must never write there).
Both legacy and namespaced roots are reported. Unreadable existing state is an
error, never an empty zero-block rollback permission."""
import argparse
import json
import sys
from pathlib import Path

from ..ledger import LedgerError
from . import compat_scan


def _parser():
    p = argparse.ArgumentParser(prog='onecrew compat', add_help=True)
    p.add_argument('--project', default=None)
    p.add_argument('--state-root', dest='state_root', default=None)
    sub = p.add_subparsers(dest='command', required=True)
    s = sub.add_parser('scan', help='read-only compatibility scan of legacy and namespaced roots (B1–B4)')
    s.add_argument('--out', default=None, help='write the JSON report to this file (refused inside the state root)')
    s.add_argument('--json', action='store_true', help='print only the JSON report')
    return p


def _state_root(args):
    if not args.state_root:
        raise LedgerError('compat scan needs --state-root <path>.')
    return Path(args.state_root).resolve()


def _strip_compat(argv):
    """Drop the leading global options and the 'compat' group token, leaving the subcommand and its options for the parser. The global
    --project / --state-root (and =form) are re-added so argparse sees them wherever they sat."""
    argv = list(argv or [])
    rest, i = [], 0
    while i < len(argv):
        tok = argv[i]
        if tok in ('--project', '--state-root'):
            rest += [tok, argv[i + 1] if i + 1 < len(argv) else '']; i += 2
        elif tok.startswith(('--project=', '--state-root=')):
            rest.append(tok); i += 1
        elif tok == 'compat':
            i += 1
        else:
            rest.append(tok); i += 1
    return rest


def main(argv=None):
    import sys as _sys
    args = _parser().parse_args(_strip_compat(argv if argv is not None else _sys.argv[1:]))
    try:
        if args.command == 'scan':
            state_root = _state_root(args)
            report = compat_scan.scan(state_root)
            if args.out:
                out = Path(args.out).resolve()
                if state_root == out or state_root in out.parents:
                    raise LedgerError('--out is inside the state root: the scan must not write there.')
                out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding='utf-8')
            if args.json:
                print(json.dumps(report, ensure_ascii=False, indent=1))
            else:
                _print_table(report)
            return 0
    except (LedgerError, OSError) as error:
        print(json.dumps({'error': str(error), 'type': 'LedgerError'}, ensure_ascii=False), file=sys.stderr)
        return 2
    return 2


def _print_table(report):
    b = report['blocking']
    print(f"compat scan — {report['state_root']}")
    print(f"ledger sha: {report['ledger_sha']}")
    print(f"old version: {report['old_version']}")
    print(f"blocking conditions: {b['total']} (read {b['read']}, continue {b['continue']})")
    for r in report['roots']:
        props = r['properties']
        flags = ('readable' if props['old_readable'] else 'NOT-readable') + ', ' + ('continuable' if props['old_continuable'] else 'NOT-continuable')
        print(f"  {r['anchor']:24s} status={r['status']:7s} classes={','.join(r['event_classes']) or '-':5s} {flags}"
              + (' [preserved-only]' if r['preserved_only'] else ''))
        for blk in r['blocks']:
            print(f"      {blk['id']} ({blk['type']}): {blk['why']}  | released by: {blk['released_by']}")
        if r.get('duplicate_note'):
            print('      duplicates: ' + r['duplicate_note'])


if __name__ == '__main__':
    sys.exit(main())
