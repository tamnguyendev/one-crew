"""W30b: read v1 request cards and record owner replies (with the mandatory workflow effect in the same transaction, P1-2)."""
import argparse
import json
from pathlib import Path

from ..ledger import Ledger, LedgerError, text_field
from . import namespaces, plan


def list_for_plan(ledger, selector, pending=False):
    with ledger.transaction() as conn:
        state = plan.anchor_events(ledger, conn, selector)
        if pending and state['status'] == 'closed': return []
    return ledger.requests(state['task_id'], pending=pending)


def show(ledger, request_id):
    row = ledger.request(request_id)
    with ledger.transaction() as conn:
        task = ledger._task(conn, row['task_id'])
        if not task['request_key'].startswith((namespaces.LEGACY, namespaces.NAMESPACED)):
            raise LedgerError('This is not a plan question.')
    return row


def answer(ledger, request_id, revision, choice, reference):
    """Record the owner's reply and, for a workflow root, its mandatory effect in ONE write transaction (P1-2).

    Uses answer_effects.reply_and_apply (the same path as `request reply` and the MCP reply): v1 `reply` verifies request
    revision, choice, provenance and replay conflicts, and the effect (plan.closed / node.resumed + request.applied) is
    written into the same transaction, so a crash leaves either nothing or both.
    A legacy/default root gets the reply only (apply returns applied=False and writes nothing). The active plan export
    and outcome note run after commit; their failure is reported in `post_commit_errors`, never half-applies state."""
    plan.require_owner('owner', 'Answering a plan question')
    text_field(reference, 'reference', 500)
    show(ledger, request_id)                     # refuses a request that is not a plan question
    from . import answer_effects
    return answer_effects.reply_and_apply(ledger, request_id, revision, choice, source='owner-terminal', reference=reference,
                                          decided_by='user', by='user', export=True)


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
