"""Plan projections over the shared v1 notification/desktop outbox protocols."""
import argparse
import json
from pathlib import Path

from .. import desktop_core, notification_core
from ..ledger import Ledger, LedgerError
from . import exceptions, support
from .where import state_root_for


def message(conn, row):
    """Plan notices first, then 2.4-S1 support notices (a status transition of a feedback); never an answer or an acceptance."""
    return exceptions.message(conn, row) or support.message(conn, row)


def desktop_snapshots(ledger, after=0, task=None):
    return exceptions.desktop_snapshots(ledger, after, task) + support.desktop_snapshots(ledger, after, task)


def pull(ledger, consumer, all_projects=False, from_now=False):
    return notification_core.pull(ledger, consumer, all_projects, from_now,
        message=message, projection='plan-only', allow_unbound=False,
        reconcile=lambda current, all_projects: exceptions.observe_project(current, all_projects=all_projects),
        refresh=lambda current, batch: notification_core.refresh_plan_notices(current, batch, message=exceptions.message))


def ack(ledger, consumer, batch_id, all_projects=False):
    return notification_core.ack(ledger, consumer, batch_id, all_projects, projection='plan-only', allow_unbound=False)


configure = desktop_core.configure
status = desktop_core.status


def text_report(item):
    return item['open_text']


def publish(ledger, task=None):
    return desktop_core.publish(ledger, task, snapshots=desktop_snapshots,
        text_report=text_report, launcher=desktop_core.launch, observe=exceptions.observe_project)


def best_effort(ledger):
    return desktop_core.best_effort(ledger, publish=publish)


def retry(ledger, key):
    return desktop_core.retry(ledger, key, publish=publish)


def main(argv):
    parser = argparse.ArgumentParser(prog='onecrew', allow_abbrev=False)
    parser.add_argument('--project', type=Path, default=Path.cwd())
    parser.add_argument('--state-root', type=Path)
    groups = parser.add_subparsers(dest='group', required=True)
    notices = groups.add_parser('notifications', help='plan notices using the shared v1 delivery envelope').add_subparsers(dest='command', required=True)
    for name in ('pull', 'ack'):
        p = notices.add_parser(name)
        p.add_argument('--consumer', required=True, help='dedicated consumer for plan notices')
        p.add_argument('--all-projects', action='store_true')
        if name == 'pull': p.add_argument('--from-now', action='store_true')
        else: p.add_argument('--batch', required=True)
    desktop = groups.add_parser('desktop').add_subparsers(dest='command', required=True)
    for name in ('enable', 'disable', 'status', 'show', 'retry'):
        p = desktop.add_parser(name)
        if name == 'show': p.add_argument('--task', required=True)
        if name == 'retry': p.add_argument('--id', required=True)
    args = parser.parse_args(argv)
    try:
        ledger = Ledger(args.project, state_root_for(args.project, args.state_root))
        if args.group == 'notifications':
            result = (pull(ledger, args.consumer, args.all_projects, args.from_now) if args.command == 'pull'
                      else ack(ledger, args.consumer, args.batch, args.all_projects))
        elif args.command in ('enable', 'disable'): result = configure(ledger, args.command == 'enable')
        elif args.command == 'show': result = publish(ledger, args.task)
        elif args.command == 'retry': result = retry(ledger, args.id)
        else: result = status(ledger)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (LedgerError, OSError, ValueError) as error:
        print(json.dumps({'error': str(error), 'type': type(error).__name__}, ensure_ascii=False))
        return 2
