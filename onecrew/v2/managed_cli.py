"""Public managed controls; recovery reconciles evidence, never starts a job."""
import argparse
import json
import sys
from pathlib import Path

from ..ledger import LedgerError
from . import executors
from .evidence_cli import _ledger

COMMANDS = ('state', 'pause', 'stop', 'recover', 'isolate')


def _parser():
    parser = argparse.ArgumentParser(prog='onecrew executor')
    parser.add_argument('--project', type=Path, default=Path.cwd())
    parser.add_argument('--state-root', type=Path)
    sub = parser.add_subparsers(dest='command', required=True)
    for command in COMMANDS:
        p = sub.add_parser(command)
        p.add_argument('attempt')
        if command in ('pause', 'stop'): p.add_argument('--reason', default='The managed branch is held')
    return parser


def main(argv=None):
    args = _parser().parse_args(executors._without_group(sys.argv[1:] if argv is None else argv))
    try:
        from .managed_executor import ManagedExecutor
        # Read commands connect existing ports without initialization/migration.
        ledger = _ledger(args, args.command in ('state', 'isolate'))
        adapter = ManagedExecutor(ledger, initialize=False)
        if not adapter._history(args.attempt):
            raise LedgerError('The attempt has no managed executor journal; controls are not sent to an undeclared executor.')
        dispatcher = executors.Dispatcher()
        if args.command == 'state': result = adapter.state(args.attempt)
        else:
            command = 'pause_at_safe_point' if args.command == 'pause' else args.command
            values = (args.attempt, args.reason) if args.command in ('pause', 'stop') else (args.attempt,)
            result = dispatcher.send(adapter, command, *values)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (LedgerError, OSError, ValueError, TypeError) as error:
        print(json.dumps({'error': str(error), 'type': type(error).__name__}, ensure_ascii=False))
        return 2


if __name__ == '__main__':
    sys.exit(main())
