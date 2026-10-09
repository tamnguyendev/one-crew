"""Shared local entry: sealed profile, bounded run, checkpoint review and resume."""
import argparse
import json
from pathlib import Path
import sqlite3
import sys

from .ledger import Ledger, read_json, content_hash
from .workflow import Workflow


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(prog='onecrew')
    parser.add_argument('--project', type=Path, default=Path.cwd())
    parser.add_argument('--state-root', type=Path)
    group = parser.add_subparsers(dest='group', required=True).add_parser('work')
    commands = group.add_subparsers(dest='command', required=True)
    for name in ('enable', 'plan', 'triage', 'extend', 'amend', 'request-changes', 'recheck', 'run', 'start', 'runner', 'status', 'outputs', 'pause', 'resume', 'reorder', 'review', 'export', 'switch', 'branch'):
        command = commands.add_parser(name)
        command.add_argument('id')
        command.add_argument('--json', action='store_true')
        if name == 'outputs':
            command.add_argument('--full', action='store_true', help='Include diffs and gate evidence in the human review card.')
        if name == 'enable':
            command.add_argument('--profile', type=Path, required=True)
            command.add_argument('--revision', required=True)
        if name == 'run':
            command.add_argument('--steps', type=int, default=100)
        if name == 'resume':
            command.add_argument('--reuse-output', action='store_true', help='Reprocess a settled receipt after a parser fix; no new worker call.')
        if name in ('plan', 'review', 'reorder', 'export', 'switch', 'branch', 'extend', 'recheck', 'amend', 'request-changes'):
            command.add_argument('--revision', required=True)
        if name == 'request-changes':
            command.add_argument('--output', required=True)
            command.add_argument('--affected', nargs='+', required=True)
            command.add_argument('--comment', required=True)
            command.add_argument('--request-id', required=True)
        if name == 'amend':
            command.add_argument('--spec-revision', required=True)
            command.add_argument('--profile', type=Path, required=True)
            command.add_argument('--affected', nargs='+', required=True)
            command.add_argument('--reason', required=True)
        if name == 'extend':
            command.add_argument('--request-id', required=True)
            command.add_argument('--max-calls', type=int, required=True)
            command.add_argument('--deadline', required=True)
            command.add_argument('--reason', required=True)
        if name == 'plan':
            command.add_argument('--file', type=Path, required=True)
        if name == 'branch':
            command.add_argument('--name', required=True)
        if name == 'switch':
            command.add_argument('--provider', choices=('codex', 'claude', 'kiro'), required=True)
            command.add_argument('--model', required=True)
        if name == 'reorder':
            command.add_argument('--order', nargs='+', required=True)
        if name == 'review':
            command.add_argument('--decision', choices=('accept', 'feedback'), required=True)
            command.add_argument('--comment', required=True)
        if name == 'export':
            command.add_argument('--to', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        workflow = Workflow(Ledger(args.project, args.state_root))
        if args.command == 'enable':
            result = workflow.enable(args.id, args.revision, read_json(args.profile))
        elif args.command == 'run':
            result = workflow.run(args.id, steps=args.steps)
        elif args.command == 'plan':
            result = workflow.set_plan(args.id, args.revision, read_json(args.file))
        elif args.command == 'triage':
            from .triage import handle
            result = handle(workflow, args.id)
        elif args.command == 'extend':
            from .budget import extend
            result = extend(workflow.control, args.id, args.revision, args.request_id, args.max_calls, args.deadline, args.reason)
        elif args.command == 'recheck':
            result = workflow.recheck(args.id, args.revision)
        elif args.command == 'amend':
            from .amendment import apply
            result = apply(workflow, args.id, args.revision, args.spec_revision, read_json(args.profile), args.affected, args.reason)
        elif args.command == 'request-changes':
            from .feedback import request_changes
            result = request_changes(workflow, args.id, args.revision, args.output, args.affected, args.comment, args.request_id)
        elif args.command in ('start', 'runner'):
            from .runner import start, status
            result = (start if args.command == 'start' else status)(workflow.ledger, args.id)
        elif args.command == 'status':
            from .amendment import plan_revision
            seq, state = workflow.state(args.id)
            result = {'sequence': seq, 'state': state, 'control': workflow.control.status(args.id),
                      'workflow_revision': content_hash(state) if state else None,
                      'plan_revision': plan_revision(state)}
        elif args.command == 'outputs':
            result = workflow.outputs(args.id)
        elif args.command == 'pause':
            workflow.control.pause(args.id)
            result = workflow.control.status(args.id)
        elif args.command == 'resume':
            result = workflow.resume(args.id, reuse_output=args.reuse_output)
        elif args.command == 'reorder':
            result = workflow.reorder(args.id, args.revision, args.order)
        elif args.command == 'review':
            result = workflow.review(args.id, args.revision, args.decision, args.comment)
        elif args.command == 'switch':
            result = workflow.switch(args.id, args.revision, args.provider, args.model)
        elif args.command == 'branch':
            from .integration import Integration
            result = Integration(workflow).branch(args.id, args.revision, args.name)
        else:
            _, state = workflow.state(args.id)
            if not state or args.revision not in {r['revision'] for r in state['outputs']}:
                raise ValueError('Only this task\'s published output revisions may be exported.')
            result = {'directory': str(workflow.store.materialize(args.revision, args.to)), 'revision': args.revision}
        if not args.json and args.command in ('status', 'outputs'):
            from . import work_view
            print(work_view.status(result) if args.command == 'status' else work_view.outputs(result, args.full))
        else:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError, sqlite3.Error) as error:
        print(json.dumps({'error': str(error)}, ensure_ascii=False))
        return 2
