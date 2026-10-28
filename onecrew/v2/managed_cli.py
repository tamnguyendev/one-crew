"""Public managed controls; recovery reconciles evidence, never starts a job."""
import argparse
import json
import sqlite3
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
        from .managed_executor import ManagedExecutor, contained_state, recover_contained, _token
        # Read commands connect existing ports without initialization/migration.
        ledger = _ledger(args, args.command in ('state', 'isolate'))
        adapter = ManagedExecutor(ledger, initialize=False)
        if not adapter._history(args.attempt):
            # 2.3-B (M4): a journal-less attempt that the Supervisor launched (`engine step`, NativeExecutor) can still be reconciled
            # as a process tree by the Supervisor itself - state and recover only, never a candidate or a replay. Pause/stop/isolate
            # stay refused: that executor did not declare them.
            if args.command in ('state', 'recover') and _token(adapter.control.attempt(args.attempt)).get('job_contained'):
                result = (recover_contained(adapter.control, args.attempt) if args.command == 'recover'
                          else contained_state(adapter.control, args.attempt))
                print(json.dumps(result, ensure_ascii=False, indent=2))
                return 0
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
    except sqlite3.OperationalError as error:
        # 2.3-B (Q4): e.g. a suspended controller holds the ledger lock. A termination never starts before its intent is recorded, but
        # a termination already confirmed may have lost only its settlement (review F6): claim nothing either way.
        print(json.dumps({'error': str(error), 'type': type(error).__name__, 'cleanup': 'pending',
                          'text': 'the ledger is locked and this step could not be recorded; nothing is claimed - '
                                  'run recover again once the ledger is free, it confirms and records the actual state'}, ensure_ascii=False))
        return 2


if __name__ == '__main__':
    sys.exit(main())
