"""Operator inspection/migration; does not expose arbitrary subprocess execution."""
import argparse
import json
from pathlib import Path
import sqlite3
import sys

from .control import Control, migrate
from .ledger import Ledger
from .supervisor import Supervisor


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(prog='onecrew')
    parser.add_argument('--project', type=Path, default=Path.cwd())
    parser.add_argument('--state-root', type=Path)
    core = parser.add_subparsers(dest='group', required=True).add_parser('core')
    commands = core.add_subparsers(dest='command', required=True)
    migration = commands.add_parser('migrate', help='Backup ledger and migrate v1 to v2 without enabling tasks.')
    migration.add_argument('--json', action='store_true')
    for name in ('status', 'cancel', 'reconcile'):
        command = commands.add_parser(name)
        command.add_argument('id')
        command.add_argument('--json', action='store_true')
    args = parser.parse_args(argv)
    try:
        ledger = Ledger(args.project, args.state_root)
        control = Control(ledger)
        if args.command == 'migrate':
            result = migrate(ledger)
        elif args.command == 'status':
            result = control.status(args.id)
        elif args.command == 'cancel':
            control.cancel(args.id)
            result = control.status(args.id)
        else:
            result = Supervisor(control).reconcile(args.id)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError, sqlite3.Error) as error:
        print(json.dumps({'error': str(error)}, ensure_ascii=False))
        return 2
