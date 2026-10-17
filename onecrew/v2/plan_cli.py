"""`onecrew plan propose|show|approve|accept|amend|enforce` and `onecrew verdict record|run` (v2). Output is JSON; exit 2 on refusal."""
import argparse
import json
import sys
from pathlib import Path

from ..ledger import Ledger, LedgerError, read_json


def _parser():
    parser = argparse.ArgumentParser(prog='onecrew')
    parser.add_argument('--project', type=Path, default=Path.cwd())
    parser.add_argument('--state-root', type=Path)
    groups = parser.add_subparsers(dest='group', required=True)
    plan = groups.add_parser('plan', help='AI work contract: propose, owner approval, amendments, owner acceptance.').add_subparsers(dest='command', required=True)
    p = plan.add_parser('propose', help='Register revision 1 of a plan (not approved).')
    p.add_argument('name', help='Plan name = the request key of the job that will carry it out.')
    p.add_argument('--file', required=True, type=Path)
    p.add_argument('--author', required=True, help='Who wrote it (recorded, never trusted).')
    p = plan.add_parser('show'); p.add_argument('name'); p.add_argument('--revision', type=int)
    p = plan.add_parser('approve', help='Owner only.')
    p.add_argument('name'); p.add_argument('--by', required=True, help='Must be: owner'); p.add_argument('--reference', required=True, help='Where the owner said yes.')
    p.add_argument('--revision', type=int); p.add_argument('--tick', action='append', default=[], metavar='ITEM', help='Run this should item.')
    p = plan.add_parser('accept', help='Owner only; refused while a milestone lacks a passing verdict.')
    p.add_argument('name'); p.add_argument('--by', required=True); p.add_argument('--reference', required=True)
    p.add_argument('--artifact-sha', required=True, help='The artifact accepted; must be what the final milestone verified.')
    p = plan.add_parser('amend', help='A new revision (needs a new approval); the old one is kept.')
    p.add_argument('name'); p.add_argument('--file', required=True, type=Path)
    p.add_argument('--reason', required=True, help='At most 200 characters.'); p.add_argument('--author', required=True)
    p = plan.add_parser('enforce', help='Owner only: require an approved plan before any job of this state root can run.')
    p.add_argument('state', choices=['on', 'off']); p.add_argument('--by', required=True); p.add_argument('--reference', required=True)
    verdict = groups.add_parser('verdict').add_subparsers(dest='command', required=True)
    p = verdict.add_parser('record', help='Record a verifier result with its receipt blob.')
    p.add_argument('--plan', required=True); p.add_argument('--milestone', required=True)
    p.add_argument('--result', required=True, choices=['pass', 'fail', 'inconclusive'])
    p.add_argument('--by', required=True, help='The milestone\'s verifier (command, or owner for owner-manual).')
    p.add_argument('--artifact-sha', required=True)
    receipt = p.add_mutually_exclusive_group(required=True)
    receipt.add_argument('--receipt', help='64-hex blob key in this state root.')
    receipt.add_argument('--receipt-file', type=Path, help='Store this file as the receipt blob. Owner-manual milestones only; command milestones use verdict run.')
    p = verdict.add_parser('run', help='Run the milestone\'s command verifier and record its verdict.')
    p.add_argument('--plan', required=True); p.add_argument('--milestone', required=True)
    p.add_argument('--cwd', type=Path, help='Workspace to verify (default: the verifier\'s cwd, else the project).')
    return parser


def _dispatch(ledger, args):
    from . import gate, plan as plans, verdict
    if args.group == 'plan':
        if args.command == 'propose': return plans.propose(ledger, args.name, read_json(args.file), args.author)
        if args.command == 'show': return plans.show(ledger, args.name, args.revision)
        if args.command == 'approve': return plans.approve(ledger, args.name, args.by, args.reference, args.revision, args.tick)
        if args.command == 'accept': return plans.accept(ledger, args.name, args.by, args.reference, args.artifact_sha)
        if args.command == 'amend': return plans.amend(ledger, args.name, read_json(args.file), args.reason, args.author)
        plans.require_owner(args.by, 'Changing enforcement')
        return gate.set_enforced(ledger, args.state == 'on', args.by, args.reference)
    if args.command == 'run': return verdict.run(ledger, args.plan, args.milestone, args.cwd)
    data = args.receipt_file.read_bytes() if args.receipt_file else None
    return verdict.record(ledger, args.plan, args.milestone, args.result, args.by, args.receipt, args.artifact_sha, data)


def main(argv=None):
    args = _parser().parse_args(argv)
    ledger = Ledger(args.project, args.state_root)
    try:
        from .gate import sync_refusals
        sync_refusals(ledger)
        result = _dispatch(ledger, args)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except Exception as error:
        import sqlite3
        if not isinstance(error, (ValueError, OSError, sqlite3.Error)): raise
        print(json.dumps({'error': str(error), 'type': type(error).__name__}, ensure_ascii=False))
        return 2


if __name__ == '__main__':
    sys.exit(main())
