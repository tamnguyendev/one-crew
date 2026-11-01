"""Common workflow CLI; installed storage/inspection and explicit host ports."""
import argparse
import json
import sys
from pathlib import Path

from ..ledger import Ledger, LedgerError
from . import engine, internal_plan, node_actions_cli
from .lint import ReadOnlyLedger
from .where import state_root_for

_AUTO = object()


def main(argv=None, *, native_executor=_AUTO, checker=_AUTO, handoff=_AUTO):
    args = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(prog='onecrew engine', allow_abbrev=False)
    parser.add_argument('--project', type=Path, default=Path.cwd())
    parser.add_argument('--state-root', type=Path)
    parser.add_argument('group', choices=['engine'])
    sub = parser.add_subparsers(dest='command', required=True)
    for verb in ('state', 'ready', 'handoff'):
        sub.add_parser(verb).add_argument('plan')
    p = sub.add_parser('step'); p.add_argument('plan')
    p.add_argument('--checks', action='store_true', help='2.4-C (root capability execution-mode): first run the checks of a produced node that need '
                                                         'no model (command/adapter milestones) through the connected checker; no child task, no attempt.')
    p=sub.add_parser('batch');p.add_argument('plan');p.add_argument('--slots',type=int,choices=(1,2),default=2)
    p.add_argument('--checks',action='store_true',help='2.4-C: model-free checks of produced nodes run beside the worker slots.')
    p = sub.add_parser('measure', help='2.4-C: time to first useful action, admission/preparation/execution spans, waits, verification, rework '
                                       'from the ledger (read-only; unknown stays unknown, overlapping attempts are joined by union).')
    p.add_argument('plan')
    p=sub.add_parser('resume-paused');p.add_argument('plan');p.add_argument('node')
    p = sub.add_parser('revise'); p.add_argument('plan'); p.add_argument('--file', type=Path, required=True)
    for verb in ('verify', 'accept-node'):
        p = sub.add_parser(verb); p.add_argument('plan'); p.add_argument('node')
    p = sub.add_parser('review-optional', help='W26: run the rule-based decision (SKIP/DEFER/HOLD/REVIEW) for one sealed optional review of a produced node; '
                                               'REVIEW calls the connected checker, the result is an observation and never the mandatory gate.')
    p.add_argument('plan'); p.add_argument('node'); p.add_argument('review')
    node_actions_cli.register(sub)
    opts = parser.parse_args(args)
    try:
        if opts.command == 'step' and native_executor is _AUTO:
            from ..common_executor import NativeExecutor
            native_executor = NativeExecutor
        if (opts.command in ('verify', 'review-optional') or getattr(opts, 'checks', False)) and checker is _AUTO:
            from ..common_verification import CandidateChecker
            checker = CandidateChecker
        if opts.command == 'handoff' and handoff is _AUTO:
            from ..common_handoff import handoff as apply_candidate
            handoff = apply_candidate
        if ((opts.command == 'step' and native_executor is None)
                or ((opts.command in ('verify', 'review-optional') or getattr(opts, 'checks', False)) and checker is None)
                or (opts.command == 'handoff' and handoff is None)):
            raise LedgerError('This operation needs a connected native host adapter; the supplied host port is disabled.')
        project = opts.project.resolve()
        ledger_class = ReadOnlyLedger if opts.command in ('state', 'ready', 'measure') else Ledger
        ledger = ledger_class(project, state_root_for(project, opts.state_root))
        if getattr(opts, 'checks', False) and 'execution-mode' not in engine.state(ledger, opts.plan)['capabilities']:
            # review C-R11: --checks never falls back to a plain step or batch that starts a model worker
            raise LedgerError('--checks needs the root capability execution-mode; nothing was run (no check, no worker).')
        if opts.command in node_actions_cli.ACTIONS: result = node_actions_cli.execute(opts, ledger)
        elif opts.command == 'state': result = engine.state(ledger, opts.plan)
        elif opts.command == 'ready': result = engine.ready(ledger, opts.plan)
        elif opts.command == 'revise':
            body = json.loads(opts.file.read_text(encoding='utf-8-sig'))
            if not isinstance(body, dict) or set(body) - {'nodes', 'reason', 'evidence', 'expected_revision'}:
                raise LedgerError('Internal revision file takes nodes, reason, evidence and optional expected_revision.')
            result = internal_plan.revise(ledger, opts.plan, **body)
        elif opts.command == 'measure':
            from . import execution_mode
            result = execution_mode.measure(ledger, opts.plan)
        elif opts.command == 'step':
            result = engine.step(ledger, opts.plan, native_executor(ledger), **({'checker': checker(ledger, opts.plan)} if opts.checks else {}))
        elif opts.command == 'batch':
            from .managed_executor import ManagedExecutor
            result=engine.run_batch(ledger,opts.plan,ManagedExecutor(ledger),slots=opts.slots,**({'checker':checker(ledger,opts.plan)} if opts.checks else {}))
        elif opts.command == 'resume-paused':
            from .managed_executor import ManagedExecutor
            result=engine.release_paused(ledger,opts.plan,opts.node,ManagedExecutor(ledger,initialize=False))
        elif opts.command == 'verify': result = engine.verify(ledger, opts.plan, opts.node, checker(ledger, opts.plan))
        elif opts.command == 'accept-node': result = engine.accept_node(ledger, opts.plan, opts.node)
        elif opts.command == 'review-optional':
            record = engine.state(ledger, opts.plan)['nodes'].get(opts.node)
            if not record or not record.get('artifact'):
                raise LedgerError('Optional review needs a produced node (no current artifact).')
            result = engine.review_optional(ledger, opts.plan, opts.node, opts.review, checker(ledger, opts.plan), record['artifact'])
        else: result = handoff(ledger, opts.plan)
        print(json.dumps(result, ensure_ascii=False, indent=2)); return 0
    except (LedgerError, OSError, ValueError, KeyError, TypeError) as error:
        print(json.dumps({'error': str(error), 'type': type(error).__name__}, ensure_ascii=False)); return 2
