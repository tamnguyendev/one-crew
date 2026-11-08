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
    p.add_argument('--workflow', action='store_true', help='Declare the stable default workflow capabilities; schema 2 alone retains legacy semantics.')
    p.add_argument('--capability', action='append', help='Explicit implemented capability set (repeat; requires --workflow); dependencies must be included.')
    p.add_argument('--reuse-existing', action='store_true', help='Return an open identical plan with identical capabilities; never amend, approve or upgrade an existing grant.')
    p = plan.add_parser('lint', help='Every form refusal propose/approve would raise, one per line; exit 1 on any. Writes nothing (read-only ledger).')
    p.add_argument('--file', required=True, type=Path); p.add_argument('--author', help='Check it is a model id, as the reviewer needs.')
    p.add_argument('--ack-criteria', action='store_true', help='Silence the two criteria warnings (a quoted literal already in the base tree; a word shared with a non_goal). A missing "fail if" is still refused.')
    p = plan.add_parser('show'); p.add_argument('name'); p.add_argument('--revision', type=int)
    p = plan.add_parser('report', help='One page of text from the ledger (read-only, no model): seven sections, Vietnamese labels.')
    p.add_argument('name'); p.add_argument('--revision', type=int); p.add_argument('--out', type=Path, help='The only write: save the page here instead of printing it (refused inside the state root).')
    p.add_argument('--handover', action='store_true', help='Evidence and remaining work for each acceptance criterion.')
    p = plan.add_parser('present', help='Read-only decision page: request, result, risks, acceptance and missing evidence.')
    p.add_argument('name'); p.add_argument('--revision', type=int); p.add_argument('--out', type=Path)
    p = plan.add_parser('digest', help='One line per plan in the state root; open plans first (read-only, no model).')
    p.add_argument('--out', type=Path, help='Save the page here instead of printing it.')
    p = plan.add_parser('approve', help='Owner only.')
    p.add_argument('name'); p.add_argument('--by', required=True, help='Must be: owner'); p.add_argument('--reference', required=True, help='Where the owner said yes.')
    p.add_argument('--revision', type=int); p.add_argument('--tick', action='append', default=[], metavar='ITEM', help='Run this should item.')
    p.add_argument('--choose', metavar='OPTION', help='The owner choice among the plan options (recorded here, never in the contract).')
    p.add_argument('--estimate-file', type=Path, help='Sourced execution range/deadline; sealed once after first approval, separate from the contract budget.')
    p = plan.add_parser('accept', help='Owner only; refused while a milestone lacks a passing verdict.')
    p.add_argument('name'); p.add_argument('--by', required=True); p.add_argument('--reference', required=True)
    p.add_argument('--artifact-sha', required=True, help='The artifact accepted; must be what the final milestone verified.')
    p.add_argument('--revision', type=int, help='Expected current revision; checked inside the acceptance write transaction.')
    p = plan.add_parser('amend', help='A new revision (needs a new approval); the old one is kept.')
    p.add_argument('name'); p.add_argument('--file', required=True, type=Path)
    p.add_argument('--reason', required=True, help='At most 200 characters.'); p.add_argument('--author', required=True)
    p = plan.add_parser('precheck', help='Run the preconditions and the target check (0 AI calls) without approving.'); p.add_argument('name')
    p = plan.add_parser('review-decision', help='Evaluate approved review depth by rules; never completes a milestone or calls a model.')
    p.add_argument('name'); p.add_argument('--node', required=True); p.add_argument('--artifact-sha', required=True)
    p.add_argument('--not-ready', action='store_true'); p.add_argument('--unknown', action='append', default=[])
    p.add_argument('--evidence', action='append', default=[])
    p = plan.add_parser('advise', help='One independent model call: three fixed questions about the latest revision, judged against the owner rules. Advice only.')
    p.add_argument('name'); p.add_argument('--model', help='Must differ from the model that wrote the plan (default: the contract advisor, else ONECREW_DEFAULT_MODEL, or DEFAULT_MODEL in claude_cli).')
    p.add_argument('--provider', choices=['claude', 'codex', 'kiro'], help='The advisor CLI (default: the contract advisor, else claude). Read-only; never changed on a quota error.')
    p.add_argument('--auth', choices=['subscription', 'api'], help='The credential of the claude call: subscription (the CLI login, default) or api '
                   '(ANTHROPIC_API_KEY of this onecrew process, given to the claude process only; default: the contract advisor auth). Neither replaces the other on failure.')
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
    card = plan.add_parser('card', help='Decision cards (W30a).').add_subparsers(dest='action', required=True)
    p = card.add_parser('present', help='Step 0 shows the owner only the important choices, in ONE card; technical choices inside the authority are decided and recorded (HD-05), not asked.')
    p.add_argument('name'); p.add_argument('--file', required=True, type=Path, help='{"choices": [...]}: each choice has id, class, problem, options, recommendation, evidence, scope, decide_by.')
    p.add_argument('--model', required=True, help='The model that decided the technical choices (recorded as the subject).'); p.add_argument('--component', default='step0')
    proposal = plan.add_parser('proposal', help='The step-0 proposal check (W47).').add_subparsers(dest='action', required=True)
    p = proposal.add_parser('check', help='Hold a proposal to the request: not too little, not too much (no model). Recorded on the plan; a refused check holds approval.')
    p.add_argument('name'); p.add_argument('--file', required=True, type=Path, help='{"requirement": {...}, "proposal": {...}}')
    survey = plan.add_parser('survey', help='Bounded read-only discovery for a scoped unknown.').add_subparsers(dest='action', required=True)
    p = survey.add_parser('open'); p.add_argument('name'); p.add_argument('unknown'); p.add_argument('--file', required=True, type=Path)
    p = survey.add_parser('show'); p.add_argument('name')
    p = survey.add_parser('run'); p.add_argument('name'); p.add_argument('survey'); p.add_argument('--file', required=True, type=Path)
    step0_ = plan.add_parser('step0', help='2.4-C: the step-0 view of the latest revision (read-only, no model).').add_subparsers(dest='action', required=True)
    p = step0_.add_parser('show', help='Goal, before/after, preferred option and why, what stays unchanged, acceptance, open decision-changing unknowns, '
                                       'estimate or "chưa đủ dữ liệu", investigation cap/spent/stop. Writes nothing.')
    p.add_argument('name'); p.add_argument('--json', action='store_true')
    brainstorm = plan.add_parser('brainstorm', help='Options of the plan.').add_subparsers(dest='action', required=True)
    p = brainstorm.add_parser('table', help='Print the options as a table of at most 30 lines.'); p.add_argument('name')
    p = plan.add_parser('enforce', help='Owner only: require an approved plan before any job of this state root can run.')
    p.add_argument('state', choices=['on', 'off']); p.add_argument('--by', required=True); p.add_argument('--reference', required=True)
    p = plan.add_parser('evidence-reuse', help='Record a validated scope.neutral basis; never creates a passing verdict.')
    p.add_argument('name'); p.add_argument('--milestone', required=True); p.add_argument('--receipt', required=True)
    p.add_argument('--artifact-sha', required=True)
    retention = plan.add_parser('retention', help='Local evidence tree refs; no automatic cleanup.').add_subparsers(dest='action', required=True)
    p = retention.add_parser('list'); p.add_argument('name')
    p = retention.add_parser('cleanup', help='Owner only; remove this plan scope refs, never prune objects.')
    p.add_argument('name'); p.add_argument('--by', required=True)
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
    p = verdict.add_parser('status', help='Show verifier runs; records abandonment when a process was lost.')
    p.add_argument('--plan', required=True)
    p = verdict.add_parser('release-run', help='W37a: release a run held with an unknown outcome so the milestone may be run again (an explicit, recorded decision).')
    p.add_argument('--plan', required=True); p.add_argument('--run', required=True); p.add_argument('--reason', required=True)
    p = verdict.add_parser('baseline', help='Owner only: record the base tree of a root approved by an older build that kept none (P1-D); the commit the root was approved against, with a reference.')
    p.add_argument('--plan', required=True); p.add_argument('--from-commit', required=True); p.add_argument('--by', required=True); p.add_argument('--reference', required=True)
    return parser


def _dispatch(ledger, args):
    from . import gate, plan as plans, report, step0, verdict
    if args.group == 'plan':
        if args.command == 'evidence-reuse':
            from . import verification_evidence
            return verification_evidence.record_reuse(ledger, args.name, args.milestone, args.receipt, args.artifact_sha)
        if args.command == 'retention':
            from . import retention
            return (retention.list_refs(ledger, args.name) if args.action == 'list'
                    else retention.cleanup(ledger, args.name, args.by))
        if args.command in ('report', 'digest', 'present'):         # read-only: a plan of any project in the state root, nothing written but --out
            if args.command == 'present': text = report.render_present(ledger.state_root, args.name, args.revision, project_id=ledger.project_id)
            elif args.command == 'report' and args.handover: text = report.render_handover(ledger.state_root, args.name, args.revision, project_id=ledger.project_id)
            else: text = report.render_report(ledger.state_root, args.name, args.revision, project_id=ledger.project_id) if args.command == 'report' else report.render_digest(ledger.state_root)
            return report.write_out(text, args.out, ledger.state_root) if args.out else text
        if args.command == 'propose': return plans.propose(ledger, args.name, read_json(args.file), args.author, workflow=args.workflow, capabilities=args.capability, reuse_existing=args.reuse_existing, check_form=True)
        if args.command == 'show': return plans.show(ledger, args.name, args.revision)
        if args.command == 'approve': plans.refuse_owner_view(ledger, args.name, args.revision)      # dev11: approve agrees with lint
        if args.command == 'approve': return plans.approve(ledger, args.name, args.by, args.reference, args.revision, args.tick, args.choose,
                                                         estimate=read_json(args.estimate_file) if args.estimate_file else None)
        if args.command == 'precheck': return step0.precheck(ledger, args.name)
        if args.command == 'review-decision':
            from . import review_policy
            return review_policy.decide(ledger, args.name, args.node, artifact_sha=args.artifact_sha,
                                        ready=not args.not_ready, unknowns=args.unknown, evidence=args.evidence)
        if args.command == 'advise':
            from .verifiers import advisor
            return advisor.advise(ledger, args.name, args.model, args.provider, args.auth)
        if args.command == 'rules':
            from .verifiers import advisor
            return advisor.init_rules(ledger) if args.action == 'init' else advisor.show_rules(ledger)
        if args.command == 'unknown': return step0.close_unknown(ledger, args.name, args.id, args.by, args.evidence)
        if args.command == 'poc':
            return step0.poc_record(ledger, args.name, args.unknown, args.answer, args.evidence, args.confidence,
                                    read_json(args.poc_contract) if args.poc_contract else None, args.by)
        if args.command == 'proposal':
            body = read_json(args.file)
            out = step0.review_proposal(ledger, args.name, body.get('requirement'), body.get('proposal'))
            if not out['ok']:
                raise LedgerError(f'Proposal refused ({out["result"]}):' + ''.join(f' | [{c}] {t}' for c, t in out['reasons']))
            return out
        if args.command == 'survey':
            from . import survey
            if args.action == 'run':
                from . import survey_worker
                return survey_worker.run(ledger, args.name, args.survey, read_json(args.file))
            return survey.show(ledger, args.name) if args.action == 'show' else survey.open_survey(ledger, args.name, args.unknown, read_json(args.file))
        if args.command == 'step0':
            view = step0.show_card(ledger, args.name)
            return view if args.json else step0.render_card(view)
        if args.command == 'card':
            return step0.present_decisions(ledger, args.name, read_json(args.file).get('choices'), {'component': args.component, 'model': args.model})
        if args.command == 'brainstorm':
            with ledger.transaction() as conn:
                state = plans.anchor_events(ledger, conn, args.name)
                chosen = (state['approved'] or {}).get('chosen') if state['approved'] and state['approved']['revision'] == state['latest'] else None
            return step0.brainstorm_table(plans.load(ledger, state)[0], chosen)
        if args.command == 'accept': return plans.accept(ledger, args.name, args.by, args.reference, args.artifact_sha, expected_revision=args.revision)
        if args.command == 'amend': return plans.amend(ledger, args.name, read_json(args.file), args.reason, args.author, check_form=True)
        plans.require_owner(args.by, 'Changing enforcement')
        return gate.set_enforced(ledger, args.state == 'on', args.by, args.reference)
    if args.command == 'run': return verdict.run(ledger, args.plan, args.milestone, args.cwd)
    if args.command == 'diff': return verdict.diff(ledger, args.plan, args.milestone)
    if args.command == 'artifact': return verdict.artifact(ledger, args.plan)
    if args.command == 'status': return verdict.status(ledger, args.plan)
    if args.command == 'release-run': return verdict.release_run(ledger, args.plan, args.run, args.reason)
    if args.command == 'baseline': return verdict.record_baseline(ledger, args.plan, args.from_commit, args.by, args.reference)
    data = args.receipt_file.read_bytes() if args.receipt_file else None
    return verdict.record(ledger, args.plan, args.milestone, args.result, args.by, args.receipt, args.artifact_sha, data, args.reference)


def _lint(args):
    """plan lint: no sync_refusals (it writes the ledger), a ledger that cannot be written, exit 1 when there is a reason, 2 when the file cannot be read."""
    from . import lint
    try:
        raw = read_json(args.file)
        reasons, warnings = lint.check(lint.ReadOnlyLedger(args.project, args.state_root), raw, args.author, args.ack_criteria)
    except (ValueError, OSError, LedgerError) as error:
        print(json.dumps({'error': str(error), 'type': type(error).__name__, **(error.structured() if hasattr(error, 'structured') else {})}, ensure_ascii=False))
        return 2
    print(lint.render(reasons, warnings))
    for code, text in lint.notes(raw): print(f'[note {code}] {text}', file=sys.stderr)       # B4: about the host, on stderr, never the exit code
    return 1 if reasons else 0               # a warning never changes the exit code


def _print(text):
    """Preserve Vietnamese output on Windows pipes with a legacy code page."""
    try:
        print(text)
    except UnicodeEncodeError:
        sys.stdout.flush()
        sys.stdout.buffer.write((text + '\n').encode('utf-8'))
        sys.stdout.buffer.flush()


def main(argv=None):
    args = _parser().parse_args(argv)
    from . import where
    args.state_root = where.state_root_for(args.project, args.state_root)      # G2: <project>/.onecrew/config.json when no --state-root is given
    if args.group == 'plan' and args.command == 'lint': return _lint(args)
    read_retention = args.group == 'plan' and args.command == 'retention' and args.action == 'list'
    read_survey = args.group == 'plan' and ((args.command == 'survey' and args.action == 'show') or args.command == 'step0')
    if read_survey or read_retention or (args.group == 'verdict' and args.command in ('diff', 'artifact')):      # the ledger of a run that must write nothing: a write is an error, not a convention
        from . import lint
        ledger = lint.ReadOnlyLedger(args.project, args.state_root)
    else:
        ledger = Ledger(args.project, args.state_root)
    try:
        if not (read_survey or read_retention or (args.group == 'plan' and args.command in ('report', 'digest', 'present')) or (args.group == 'verdict' and args.command in ('diff', 'artifact'))):      # sync_refusals writes the ledger; these never do
            from .gate import sync_refusals
            sync_refusals(ledger)
        result = _dispatch(ledger, args)
        _print(result if isinstance(result, str) else json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except Exception as error:
        import sqlite3
        if not isinstance(error, (ValueError, OSError, sqlite3.Error)): raise
        print(json.dumps({'error': str(error), 'type': type(error).__name__, **(error.structured() if hasattr(error, 'structured') else {})}, ensure_ascii=False))
        return 2


if __name__ == '__main__':
    sys.exit(main())
