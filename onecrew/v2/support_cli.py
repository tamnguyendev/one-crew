"""`onecrew support ...` (2.4-S1): report once, then show / status / list / classify / link / bundle / import-spool / confirm.

Reached through support_spool.entry, which the router calls before anything else is imported. Output is JSON with --json (bundle, classify,
link, list, import-spool, confirm always print JSON); errors print {'error', 'type'} and exit 2, like notification_cli. A report that cannot be
written to the ledger (unreadable or locked ledger, disk error, any failure past the input checks) is written to the spool instead and the output
says where (support_spool.py). `support confirm` is the owner's verb: refused inside an AI tool session.
"""
import argparse
import json
import sqlite3
import sys
from pathlib import Path

from ..ledger import Ledger, LedgerError
from . import support, support_spool
from .ownership import refuse_argv
from .where import state_root_for


def _parser():
    parser = argparse.ArgumentParser(prog='onecrew', allow_abbrev=False)
    parser.add_argument('--project', type=Path, default=Path.cwd())
    parser.add_argument('--state-root', type=Path)
    groups = parser.add_subparsers(dest='group', required=True)
    commands = groups.add_parser('support', help='report an error once; feedback id, status and a local diagnostic bundle').add_subparsers(
        dest='command', required=True)
    p = commands.add_parser('report', help='record what went wrong; prints the feedback id (spools it when the ledger is broken)')
    p.add_argument('--text', required=True); p.add_argument('--expected'); p.add_argument('--image', type=Path)
    p.add_argument('--plan'); p.add_argument('--task'); p.add_argument('--attempt'); p.add_argument('--key')
    p.add_argument('--json', action='store_true')
    for name in ('show', 'status'):
        p = commands.add_parser(name); p.add_argument('feedback'); p.add_argument('--json', action='store_true')
    commands.add_parser('list').add_argument('--json', action='store_true')
    p = commands.add_parser('classify', help='task_result | environment | provider | onecrew_runtime | new_requirement | unclear')
    p.add_argument('feedback'); p.add_argument('--class', dest='cls', required=True, help=' | '.join(support.CLASSES))
    p.add_argument('--basis', nargs='+', required=True, help='evidence references of the class'); p.add_argument('--by')
    p = commands.add_parser('link', help='link to a plan (the OneCrew project for onecrew_runtime), a finding with a receipt, or a request')
    p.add_argument('feedback'); p.add_argument('--finding'); p.add_argument('--plan'); p.add_argument('--project-id'); p.add_argument('--request')
    p.add_argument('--by')
    p = commands.add_parser('bundle', help='collect the local diagnostic bundle (manifest + redacted files); never uploads')
    p.add_argument('feedback'); p.add_argument('--out', type=Path, help='export folder (not inside the state root)')
    commands.add_parser('import-spool', help='import the spooled reports of this project, once each')
    p = commands.add_parser('confirm', help='owner only: the problem is gone for you')
    p.add_argument('feedback'); p.add_argument('--reference', required=True)
    return parser


def _say(value):
    print(json.dumps(value, ensure_ascii=False, indent=2))


def _text_status(state):
    lines = [f'{state["feedback"]}: {state["stage"]}' + (f' (class {state["class"]})' if state.get('class') else '')]
    for name in ('reported', 'reproduced', 'in_progress', 'workaround', 'trial_build', 'installed', 'verified_at_target', 'still_blocked',
                 'user_confirmed'):
        item = state[name]
        lines.append(f'  {name:<19} {item["value"]}' + (f'  [{", ".join(item["evidence"])}]' if item['evidence'] else ''))
    return '\n'.join(lines)


def _report(args, argv, ledger):
    try:
        result = support.report(ledger, text=args.text, expected=args.expected, image=args.image, plan=args.plan, task=args.task,
                                attempt=args.attempt, client_key=args.key)
    except support.ReportRefused as error:
        _say({'error': str(error), 'type': type(error).__name__, 'recorded': False})
        return 2
    except Exception as error:                  # the ledger could not be opened or written: the report goes to the spool, never lost
        tried = [{'path': str(ledger.path), 'error': f'{type(error).__name__}: {error}'[:300]}]
        return support_spool.spool_report(argv, reason=f'the ledger could not be opened or written ({type(error).__name__}: {error})'[:500],
                                          error=error, tried=tried)
    if args.json: _say(result)
    else:
        print(f'{result["id"]}: ' + ('already recorded' if result['duplicate'] else 'recorded') +
              (f'; similar earlier reports (not merged): {", ".join(result["possible_duplicates"])}' if result['possible_duplicates'] else ''))
    return 0


def main(argv, index=None):
    argv = list(argv)
    if index is None: index = next((i for i, w in enumerate(argv) if w == 'support'), 0)
    refused = refuse_argv(argv[index:])           # `support confirm` is an owner verb (ownership.OWNER_VERBS)
    if refused: return refused
    args = _parser().parse_args(argv)
    try:
        ledger = Ledger(args.project, state_root_for(args.project, args.state_root))
        if args.command == 'report': return _report(args, argv, ledger)
        if args.command == 'show':
            value = support.show(ledger, args.feedback)
            if args.json: _say(value)
            else:
                feedback = value['feedback']
                print(f'{feedback["id"]} ({feedback["recorded_at"]}): {feedback["text"][:300]}\n' + _text_status(value['status']))
        elif args.command == 'status':
            value = support.status(ledger, args.feedback)
            _say(value) if args.json else print(_text_status(value))
        elif args.command == 'list': _say(support.list_feedback(ledger))
        elif args.command == 'classify': _say(support.classify(ledger, args.feedback, args.cls, args.basis, args.by))
        elif args.command == 'link':
            _say(support.link(ledger, args.feedback, finding=args.finding, plan=args.plan, project_id=args.project_id, request=args.request,
                              by=args.by))
        elif args.command == 'bundle':
            from . import diagnostics
            _say(diagnostics.bundle(ledger, args.feedback, args.out))
        elif args.command == 'import-spool': _say(support.import_spool(ledger))
        elif args.command == 'confirm': _say(support.confirm(ledger, args.feedback, args.reference))
        return 0
    except (LedgerError, OSError, ValueError, sqlite3.Error) as error:
        print(json.dumps({'error': str(error), 'type': type(error).__name__}, ensure_ascii=False))
        return 2


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
