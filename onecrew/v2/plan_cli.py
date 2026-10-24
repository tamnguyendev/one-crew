"""`onecrew plan propose|show|approve|accept|amend|enforce|precheck|unknown close|poc record|brainstorm table` and
`onecrew verdict record|run` (v2). Output is JSON (plain text for precheck and the brainstorm table); exit 2 on refusal."""
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
    p = plan.add_parser('lint', help='Every form refusal propose/approve would raise, one per line; exit 1 on any. Writes nothing (read-only ledger).')
    p.add_argument('--file', required=True, type=Path); p.add_argument('--author', help='Check it is a model id, as the reviewer needs.')
    p.add_argument('--ack-criteria', action='store_true', help='Silence the two criteria warnings (a quoted literal already in the base tree; a word shared with a non_goal). A missing "fail if" is still refused.')
    p = plan.add_parser('show'); p.add_argument('name'); p.add_argument('--revision', type=int)
    p = plan.add_parser('report', help='One page of text from the ledger (read-only, no model): seven sections, Vietnamese labels.')
    p.add_argument('name'); p.add_argument('--revision', type=int); p.add_argument('--out', type=Path, help='The only write: save the page here instead of printing it (refused inside the state root).')
    p = plan.add_parser('digest', help='One line per plan in the state root; open plans first (read-only, no model).')
    p.add_argument('--out', type=Path, help='Save the page here instead of printing it.')
    p = plan.add_parser('approve', help='Owner only.')
    p.add_argument('name'); p.add_argument('--by', required=True, help='Must be: owner'); p.add_argument('--reference', required=True, help='Where the owner said yes.')
    p.add_argument('--revision', type=int); p.add_argument('--tick', action='append', default=[], metavar='ITEM', help='Run this should item.')
    p.add_argument('--choose', metavar='OPTION', help='The owner choice among the plan options (recorded here, never in the contract).')
    p = plan.add_parser('accept', help='Owner only; refused while a milestone lacks a passing verdict.')
    p.add_argument('name'); p.add_argument('--by', required=True); p.add_argument('--reference', required=True)
    p.add_argument('--artifact-sha', required=True, help='The artifact accepted; must be what the final milestone verified.')
    p = plan.add_parser('amend', help='A new revision (needs a new approval); the old one is kept.')
    p.add_argument('name'); p.add_argument('--file', required=True, type=Path)
    p.add_argument('--reason', required=True, help='At most 200 characters.'); p.add_argument('--author', required=True)
    p = plan.add_parser('precheck', help='Run the preconditions and the target check (0 AI calls) without approving.'); p.add_argument('name')
    p = plan.add_parser('advise', help='One independent model call: three fixed questions about the latest revision, judged against the owner rules. Advice only.')
    p.add_argument('name'); p.add_argument('--model', help='Must differ from the model that wrote the plan (default: the contract advisor, else ONECREW_DEFAULT_MODEL, or DEFAULT_MODEL in claude_cli).')
    p.add_argument('--provider', choices=['claude', 'codex', 'kiro'], help='The advisor CLI (default: the contract advisor, else claude). Read-only; never changed on a quota error.')
    rules = plan.add_parser('rules', help='The owner-rules file the advisor reads (<state-root>/plans/owner-rules.md).').add_subparsers(dest='action', required=True)
    rules.add_parser('init', help='Copy examples/owner-rules.vi.md there if absent (never overwrites).')
    rules.add_parser('show', help='Print the owner-rules file.')
    unknown = plan.add_parser('unknown', help='Unknowns of the understanding.').add_subparsers(dest='action', required=True)
    p = unknown.add_parser('close', help='Close an unknown with evidence; makes a new revision.')
    p.add_argument('name'); p.add_argument('id'); p.add_argument('--by', required=True, choices=['doc', 'poc', 'owner'])
    p.add_argument('--evidence', required=True, help='A blob key, a URL, a file:line reference (the owner may state it in words).')
    poc = plan.add_parser('poc', help='Proofs of concept.').add_subparsers(dest='action', required=True)
    p = poc.add_parser('record', help='Record a PoC done by hand; its evidence file closes the unknown (unless confidence is low).')
    p.add_argument('name'); p.add_argument('unknown'); p.add_argument('--answer', required=True)
    p.add_argument('--evidence', required=True, type=Path, help='A file; stored as a blob.')
    p.add_argument('--confidence', required=True, choices=['high', 'medium', 'low'])
    p.add_argument('--by', choices=['poc', 'owner'], default='poc', help='poc: an AI may record it (the evidence file is the proof). owner: the owner own PoC; refused in an AI session.')
    p.add_argument('--poc-contract', type=Path, help='The PoC work contract, if it had one; refused when it can apply to the project.')
    brainstorm = plan.add_parser('brainstorm', help='Options of the plan.').add_subparsers(dest='action', required=True)
    p = brainstorm.add_parser('table', help='Print the options as a table of at most 30 lines.'); p.add_argument('name')
    p = plan.add_parser('enforce', help='Owner only: require an approved plan before any job of this state root can run.')
    p.add_argument('state', choices=['on', 'off']); p.add_argument('--by', required=True); p.add_argument('--reference', required=True)
    verdict = groups.add_parser('verdict').add_subparsers(dest='command', required=True)
    p = verdict.add_parser('record', help='Record a verifier result with its receipt blob.')
    p.add_argument('--plan', required=True); p.add_argument('--milestone', required=True)
    p.add_argument('--result', required=True, choices=['pass', 'fail', 'inconclusive'])
    p.add_argument('--by', required=True, help='The milestone\'s verifier (command, or owner for owner-manual).')
    p.add_argument('--artifact-sha', required=True)
    p.add_argument('--reference', help='Where the owner said so (kept in the verdict event).')
    receipt = p.add_mutually_exclusive_group(required=True)
    receipt.add_argument('--receipt', help='64-hex blob key in this state root.')
    receipt.add_argument('--receipt-file', type=Path, help='Store this file as the receipt blob. Owner-manual milestones only; command milestones use verdict run.')
    p = verdict.add_parser('run', help='Run the milestone\'s command verifier and record its verdict.')
    p.add_argument('--plan', required=True); p.add_argument('--milestone', required=True)
    p.add_argument('--cwd', type=Path, help='Workspace to verify (default: the verifier\'s cwd, else the project).')
    p = verdict.add_parser('diff', help='Print the diff a reviewer milestone would be sent now (tracked files only). No model call, nothing written.')
    p.add_argument('--plan', required=True); p.add_argument('--milestone', required=True)
    p = verdict.add_parser('artifact', help='Print the artifact sha of the project now, as JSON. Nothing written.')
    p.add_argument('--plan', required=True)
    return parser


def _dispatch(ledger, args):
    from . import gate, plan as plans, report, step0, verdict
    if args.group == 'plan':
        if args.command in ('report', 'digest'):         # read-only: a plan of any project in the state root, nothing written but --out
            text = report.render_report(ledger.state_root, args.name, args.revision) if args.command == 'report' else report.render_digest(ledger.state_root)
            return report.write_out(text, args.out, ledger.state_root) if args.out else text
        if args.command == 'propose': return plans.propose(ledger, args.name, read_json(args.file), args.author)
        if args.command == 'show': return plans.show(ledger, args.name, args.revision)
        if args.command == 'approve': return plans.approve(ledger, args.name, args.by, args.reference, args.revision, args.tick, args.choose)
        if args.command == 'precheck': return step0.precheck(ledger, args.name)
        if args.command == 'advise':
            from .verifiers import advisor
            return advisor.advise(ledger, args.name, args.model, args.provider)
        if args.command == 'rules':
            from .verifiers import advisor
            return advisor.init_rules(ledger) if args.action == 'init' else advisor.show_rules(ledger)
        if args.command == 'unknown': return step0.close_unknown(ledger, args.name, args.id, args.by, args.evidence)
        if args.command == 'poc':
            return step0.poc_record(ledger, args.name, args.unknown, args.answer, args.evidence, args.confidence,
                                    read_json(args.poc_contract) if args.poc_contract else None, args.by)
        if args.command == 'brainstorm':
            with ledger.transaction() as conn:
                state = plans.anchor_events(ledger, conn, args.name)
                chosen = (state['approved'] or {}).get('chosen') if state['approved'] and state['approved']['revision'] == state['latest'] else None
            return step0.brainstorm_table(plans.load(ledger, state)[0], chosen)
        if args.command == 'accept': return plans.accept(ledger, args.name, args.by, args.reference, args.artifact_sha)
        if args.command == 'amend': return plans.amend(ledger, args.name, read_json(args.file), args.reason, args.author)
        plans.require_owner(args.by, 'Changing enforcement')
        return gate.set_enforced(ledger, args.state == 'on', args.by, args.reference)
    if args.command == 'run': return verdict.run(ledger, args.plan, args.milestone, args.cwd)
    if args.command == 'diff': return verdict.diff(ledger, args.plan, args.milestone)
    if args.command == 'artifact': return verdict.artifact(ledger, args.plan)
    data = args.receipt_file.read_bytes() if args.receipt_file else None
    return verdict.record(ledger, args.plan, args.milestone, args.result, args.by, args.receipt, args.artifact_sha, data, args.reference)


def _lint(args):
    """plan lint: no sync_refusals (it writes the ledger), a ledger that cannot be written, exit 1 when there is a reason, 2 when the file cannot be read."""
    from . import lint
    try:
        reasons, warnings = lint.check(lint.ReadOnlyLedger(args.project, args.state_root), read_json(args.file), args.author, args.ack_criteria)
    except (ValueError, OSError, LedgerError) as error:
        print(json.dumps({'error': str(error), 'type': type(error).__name__}, ensure_ascii=False))
        return 2
    print(lint.render(reasons, warnings))
    return 1 if reasons else 0               # a warning never changes the exit code


def main(argv=None):
    args = _parser().parse_args(argv)
    from . import where
    args.state_root = where.state_root_for(args.project, args.state_root)      # G2: <project>/.onecrew/config.json when no --state-root is given
    if args.group == 'plan' and args.command == 'lint': return _lint(args)
    if args.group == 'verdict' and args.command in ('diff', 'artifact'):      # the ledger of a run that must write nothing: a write is an error, not a convention
        from . import lint
        ledger = lint.ReadOnlyLedger(args.project, args.state_root)
    else:
        ledger = Ledger(args.project, args.state_root)
    try:
        if not ((args.group == 'plan' and args.command in ('report', 'digest')) or (args.group == 'verdict' and args.command in ('diff', 'artifact'))):      # sync_refusals writes the ledger; these never do
            from .gate import sync_refusals
            sync_refusals(ledger)
        result = _dispatch(ledger, args)
        print(result if isinstance(result, str) else json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except Exception as error:
        import sqlite3
        if not isinstance(error, (ValueError, OSError, sqlite3.Error)): raise
        print(json.dumps({'error': str(error), 'type': type(error).__name__}, ensure_ascii=False))
        return 2


if __name__ == '__main__':
    sys.exit(main())
