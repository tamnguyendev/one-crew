"""`onecrew outcome record|show|missing|intervene` and `onecrew continue <plan>` (W23b, R02) — and, from W48, `onecrew context add|observe|retrieve`.

`continue`, `outcome show|missing` and `context list|retrieve` are read-only (the ledger handed to them refuses a write). None of these is an owner verb:
an AI session may run them; none of them approves, accepts or answers anything. Output is JSON (text for `continue` unless --json); exit 2 on refusal.
"""
import argparse
import json
import sys
from pathlib import Path

from ..ledger import Ledger


def _parser():
    parser = argparse.ArgumentParser(prog='onecrew')
    parser.add_argument('--project', type=Path, default=Path.cwd())
    parser.add_argument('--state-root', type=Path)
    groups = parser.add_subparsers(dest='group', required=True)
    out = groups.add_parser('outcome', help='The outcome of a plan root (learning.outcome) and the orchestrator interventions.').add_subparsers(dest='command', required=True)
    p = out.add_parser('record', help='Write the outcome of the root end if it is not there yet (idempotent).'); p.add_argument('name')
    p = out.add_parser('show', help='The outcomes of a root (read-only).'); p.add_argument('name')
    out.add_parser('missing', help='Roots that ended without an outcome (read-only).')
    out.add_parser('reconcile', help='Idempotently repair missing terminal outcomes after a crash or earlier write failure.')
    p = out.add_parser('intervene', help='Record one reason-bearing intervention on a root (control.intervention, via interventions.record).')
    p.add_argument('name'); p.add_argument('--kind', required=True); p.add_argument('--reason', required=True)
    p.add_argument('--actor'); p.add_argument('--key')
    p = groups.add_parser('continue', help='The read-only resume pack of a plan: data from the ledger, not authority.')
    p.add_argument('name'); p.add_argument('--json', action='store_true', dest='as_json')
    ctx = groups.add_parser('context', help='Context written while working (context.entry): add, observe, retrieve. Entries are data, never authority.').add_subparsers(dest='command', required=True)
    p = ctx.add_parser('add', help='Write one entry on a root: a source and a label are required.')
    p.add_argument('name'); p.add_argument('--kind', required=True); p.add_argument('--label', required=True); p.add_argument('--text', required=True)
    p.add_argument('--source', required=True, help='event:<id> | receipt:<blob key> | file:<path>:<line>@<revision> | symbol:<name>:<path>@<revision>')
    p.add_argument('--scope', default='project', choices=['project', 'general']); p.add_argument('--condition', action='append', help='A condition a general entry holds under (repeat).')
    p.add_argument('--key', help='The subject of the entry (an update of the same subject replaces the earlier entry on retrieval).')
    p = ctx.add_parser('observe', help='Report one operation of the session as JSON; only a decision, a verified symbol, a refuted hypothesis or a finished task is written.')
    p.add_argument('name'); p.add_argument('--op', required=True, help='JSON object with "type".')
    p = ctx.add_parser('retrieve', help='Entries of the project and of the shared scope, checked at a revision (read-only).')
    p.add_argument('--plan'); p.add_argument('--scope', default='both', choices=['project', 'general', 'both']); p.add_argument('--revision')
    return parser


def parse_source(text):
    """`event:12`, `receipt:<key>`, `file:<path>:<line>@<revision>`, `symbol:<name>:<path>@<revision>` -> a source dict."""
    import re
    kind, _, rest = text.partition(':')
    if kind == 'event' and rest.isdigit(): return {'type': 'event', 'id': int(rest)}
    if kind == 'receipt' and rest: return {'type': 'receipt', 'key': rest}
    match = re.fullmatch(r'(.+?):(\d+)@(.+)', rest) if kind == 'file' else re.fullmatch(r'(.+?):(.+?)@(.+)', rest) if kind == 'symbol' else None
    if kind == 'file' and match: return {'type': 'file_line', 'path': match.group(1), 'line': int(match.group(2)), 'revision': match.group(3)}
    if kind == 'symbol' and match: return {'type': 'symbol', 'name': match.group(1), 'path': match.group(2), 'revision': match.group(3)}
    raise ValueError(f'source {text!r}: expected event:<id>, receipt:<key>, file:<path>:<line>@<revision> or symbol:<name>:<path>@<revision>.')


def _ledger(args, read_only):
    from . import where
    state_root = where.state_root_for(args.project, args.state_root)
    if read_only:
        from . import lint
        return lint.ReadOnlyLedger(args.project, state_root)
    return Ledger(args.project, state_root)


def _run(args):
    from . import outcome, resume_pack
    if args.group == 'context':
        from . import context
        if args.command == 'retrieve': return context.retrieve(_ledger(args, True), plan=args.plan, scope=args.scope, revision=args.revision)
        if args.command == 'observe': return context.observe(_ledger(args, False), args.name, json.loads(args.op))
        return context.add(_ledger(args, False), args.name, kind=args.kind, label=args.label, text=args.text, source=parse_source(args.source),
                           scope=args.scope, conditions=args.condition, key=args.key)
    if args.group == 'continue':
        pack = resume_pack.build(_ledger(args, True), args.name, context=_context())
        return json.dumps(pack, ensure_ascii=False, indent=2) if args.as_json else resume_pack.render(pack)
    if args.command == 'record': return outcome.record(_ledger(args, False), args.name)
    if args.command == 'show': return {'plan': args.name, 'outcomes': outcome.outcomes(_ledger(args, True), args.name)}
    if args.command == 'missing': return {'missing': outcome.missing(_ledger(args, True))}
    if args.command == 'reconcile': return outcome.reconcile(_ledger(args, False))
    if args.command == 'intervene': return outcome.intervene(_ledger(args, False), args.name, args.kind, args.reason, actor=args.actor, key=args.key)
    raise AssertionError(args.command)


def _context():
    from . import context
    return context.for_pack


def main(argv=None):
    args = _parser().parse_args(argv)
    try:
        result = _run(args)
        print(result if isinstance(result, str) else json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except Exception as error:
        import sqlite3
        if not isinstance(error, (ValueError, OSError, sqlite3.Error)): raise
        print(json.dumps({'error': str(error), 'type': type(error).__name__}, ensure_ascii=False))
        return 2


if __name__ == '__main__':
    sys.exit(main())
