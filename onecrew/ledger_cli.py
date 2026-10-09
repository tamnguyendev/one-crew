"""CLI transport for the durable ledger. Local replies never dispatch actions."""
import argparse
import json
from pathlib import Path
import sqlite3
import sys

from .ledger import Ledger, read_json
from .specs import SpecError


def parser():
    result = argparse.ArgumentParser(prog='onecrew', description='Durable local ledger; no worker dispatch.')
    result.add_argument('--project', type=Path, default=Path.cwd())
    result.add_argument('--state-root', type=Path, help='Local state directory outside source; default user data/OneCrew.')
    groups = result.add_subparsers(dest='group', required=True)
    task = groups.add_parser('task').add_subparsers(dest='command', required=True)
    submit = task.add_parser('submit')
    submit.add_argument('--spec', required=True)
    submit.add_argument('--revision', required=True)
    submit.add_argument('--request-id', required=True, help='Caller-generated idempotency key; reuse on retry.')
    submit.add_argument('--grant', type=Path, required=True, help='JSON intent, not authenticated execution permission.')
    commands = [submit, task.add_parser('queue')]
    for name in ('status', 'connect', 'events'):
        command = task.add_parser(name)
        command.add_argument('id')
        if name == 'events':
            command.add_argument('--after', type=int, default=0)
        commands.append(command)
    requests = groups.add_parser('request').add_subparsers(dest='command', required=True)
    listing = requests.add_parser('list')
    listing.add_argument('--task')
    listing.add_argument('--pending', action='store_true')
    create = requests.add_parser('create')
    create.add_argument('--task', required=True)
    create.add_argument('--request-id', required=True)
    create.add_argument('--file', type=Path, required=True)
    commands += [listing, create]
    for name in ('show', 'revise', 'reply', 'defer'):
        command = requests.add_parser(name)
        command.add_argument('id')
        if name != 'show':
            command.add_argument('--revision', required=True)
        if name == 'revise':
            command.add_argument('--file', type=Path, required=True)
        if name == 'reply':
            command.add_argument('--choice', required=True)
        if name in ('reply','defer'):
            command.add_argument('--source', default='terminal')
            command.add_argument('--reference', default='local user input')
        commands.append(command)
    for command in commands:
        command.add_argument('--json', action='store_true', help='Structured output for connectors.')
    return result


def execute(args):
    ledger = Ledger(args.project, args.state_root)
    if args.group == 'task':
        if args.command == 'submit':
            return ledger.submit(args.spec, args.revision, args.request_id, read_json(args.grant))
        if args.command == 'queue':
            return {'tasks': ledger.tasks()}
        if args.command == 'events':
            events = ledger.events(args.id, args.after)
            return {'events': events, 'next_cursor': events[-1]['seq'] if events else args.after}
        return ledger.task(args.id, full=args.command == 'connect')
    if args.command == 'create':
        return ledger.create_request(args.task, args.request_id, read_json(args.file))
    if args.command == 'revise':
        return ledger.revise_request(args.id, args.revision, read_json(args.file))
    if args.command == 'list':
        return {'requests': ledger.requests(args.task, args.pending)}
    if args.command == 'reply':
        return ledger.reply(args.id, args.revision, args.choice, args.source, args.reference)
    if args.command == 'defer':
        return ledger.defer(args.id, args.revision, args.source, args.reference)
    return ledger.request(args.id)


def human(result):
    if 'tasks' in result:
        return '\n'.join(f"{r['id']} | {r['execution']} | {r['title']} | pending={r['pending_requests']}"
                         for r in result['tasks']) or 'Chưa có task trong ledger.'
    if 'requests' in result and 'id' not in result:
        return '\n\n'.join(human(r) for r in result['requests']) or 'Không có câu hỏi phù hợp.'
    if 'question' in result:
        q = result['question']
        lines = [f"{result['id']} | {result['state']}", q['question'],
                 f"Lý do: {q['reason']}", f"Tác động: {q['impact']}"]
        lines += [f"  {o['id']}: {o['label']}" + (' (khuyến nghị)' if o['id'] == q['recommendation'] else '')
                  for o in q['options']]
        lines += [f"Action: {json.dumps(q['action'], ensure_ascii=False)}", f"Revision: {result['revision']}"]
        if result['answer']:
            effect = result.get('controller_effect')
            lines.append(f"Đã ghi nhận: {result['answer']['choice']} — " +
                         (f"controller: {effect['effect']}." if effect else 'chưa có biên nhận áp dụng.'))
        return '\n'.join(lines)
    if 'execution' in result:
        lines = [f"{result['id']} | {result['title']}",
                 f"Trạng thái: {result['execution']} | câu hỏi chờ: {result['pending_requests']}",
                 f"Spec: {result['spec_id']} @ {result['spec_revision']}",
                 f"Deadline: {result['deadline']} | đã hết hạn: {result['deadline_expired']}",
                 ('Đã enable local workflow; quyền theo local operator.' if result.get('dispatch_enabled') else
                  'Chỉ lưu công việc; chưa enable worker.')]
        if 'handoff' in result:
            lines.append(result['handoff']['spec_text'])
            lines += [human(r) for r in result['requests']]
        return '\n\n'.join(lines)
    if 'choice' in result:
        return f"Đã ghi nhận {result['choice']} cho {result['request_id']}. Receipt: {result['id']}. Chưa áp dụng hành động."
    return json.dumps(result, ensure_ascii=False, indent=2)


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')
    args = parser().parse_args(argv)
    try:
        result = execute(args)
        print(json.dumps(result, ensure_ascii=False, indent=2) if args.json else human(result))
        return 0
    except (ValueError, SpecError, OSError, sqlite3.Error, RecursionError) as error:
        if args.json:
            print(json.dumps({'error': str(error)}, ensure_ascii=False))
        else:
            print(f'Cannot execute: {error}', file=sys.stderr)
        return 2
