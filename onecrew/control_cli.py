"""Operator inspection/migration; does not expose arbitrary subprocess execution."""
import argparse
import json
from pathlib import Path
import sqlite3
import sys

from .control import Control, migrate
from .ledger import Ledger
from .supervisor import Supervisor


READ_ONLY = {('core', 'status')}
RECORDED = {('core', 'migrate'): 'core.migrate', ('core', 'cancel'): 'core.cancel', ('core', 'reconcile'): 'core.reconcile'}


def parser():
    parser = argparse.ArgumentParser(prog='onecrew')
    parser.add_argument('--project', type=Path, default=Path.cwd())
    parser.add_argument('--state-root', type=Path)
    core = parser.add_subparsers(dest='group', required=True).add_parser('core')
    commands = core.add_subparsers(dest='command', required=True)
    migration = commands.add_parser('migrate', help='Backup ledger and migrate v1/v2 to v3 without enabling tasks.')
    migration.add_argument('--json', action='store_true')
    for name in ('status', 'cancel', 'reconcile'):
        command = commands.add_parser(name)
        command.add_argument('id')
        command.add_argument('--json', action='store_true')
    return parser


def execute(args, ledger):
    control = Control(ledger)
    if args.command == 'migrate':
        return migrate(ledger)
    if args.command == 'status':
        return control.status(args.id)
    if args.command == 'cancel':
        control.cancel(args.id)
        return control.status(args.id)
    return Supervisor(control).reconcile(args.id)


def record(args, ledger):
    """cancel names a task, reconcile an attempt of one; migrate has no task (project scope)."""
    command = RECORDED.get((args.group, args.command))
    if command:
        from .interventions import cli_note
        task = getattr(args, 'id', None)
        if args.command == 'reconcile':
            try: task = Control(ledger).attempt(task)['task_id']
            except (ValueError, OSError, sqlite3.Error, KeyError): task = None
        cli_note(ledger, command, [task])


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')
    args = parser().parse_args(argv)
    try:
        ledger = Ledger(args.project, args.state_root)
        result = execute(args, ledger)
        record(args, ledger)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError, sqlite3.Error) as error:
        print(json.dumps({'error': str(error)}, ensure_ascii=False))
        return 2
