"""W30b: read v1 request cards and record owner replies without applying state."""
import argparse
import json
from pathlib import Path

from ..ledger import Ledger, LedgerError, text_field
from . import namespaces, plan


def list_for_plan(ledger, selector, pending=False):
    with ledger.transaction() as conn:
        state = plan.anchor_events(ledger, conn, selector)
    return ledger.requests(state['task_id'], pending=pending)


def show(ledger, request_id):
    row = ledger.request(request_id)
    with ledger.transaction() as conn:
        task = ledger._task(conn, row['task_id'])
        if not task['request_key'].startswith((namespaces.LEGACY, namespaces.NAMESPACED)):
            raise LedgerError('This is not a plan question.')
    return row


def answer(ledger, request_id, revision, choice, reference):
    plan.require_owner('owner', 'Answering a plan question')
    text_field(reference, 'reference', 500)
    row = show(ledger, request_id)
    # v1 atomically verifies request revision, choice and replay conflicts.
    receipt = ledger.reply(request_id, revision, choice, source='owner-terminal',
                           reference=reference, decided_by='user', by='user')
    with ledger.transaction() as conn:
        task = ledger._task(conn, row['task_id'])
    from . import active_plan
    active_plan.export(ledger, task['request_key'])
    return receipt


def main(argv):
    parser = argparse.ArgumentParser(prog='onecrew question', allow_abbrev=False)
    parser.add_argument('--project', type=Path, default=Path.cwd())
    parser.add_argument('--state-root', type=Path)
    groups = parser.add_subparsers(dest='group', required=True)
    sub = groups.add_parser('question').add_subparsers(dest='command', required=True)
    p = sub.add_parser('list'); p.add_argument('--plan', required=True); p.add_argument('--pending', action='store_true')
    p = sub.add_parser('show'); p.add_argument('request')
    p = sub.add_parser('answer'); p.add_argument('request'); p.add_argument('--revision', required=True)
    p.add_argument('--choice', required=True); p.add_argument('--reference', required=True)
    args = parser.parse_args(argv)
    try:
        from .lint import ReadOnlyLedger
        from .where import state_root_for
        if args.command == 'answer':
            plan.require_owner('owner', 'Answering a plan question')
            ledger = Ledger(args.project, state_root_for(args.project, args.state_root))
            result = answer(ledger, args.request, args.revision, args.choice, args.reference)
        else:
            ledger = ReadOnlyLedger(args.project, args.state_root)
            result = list_for_plan(ledger, args.plan, args.pending) if args.command == 'list' else show(ledger, args.request)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (LedgerError, OSError) as error:
        print(json.dumps({'error': str(error), 'type': type(error).__name__}, ensure_ascii=False))
        return 2
