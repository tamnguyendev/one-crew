"""Local CLI transport shared by Codex, Claude, Kiro and terminal callers."""
import argparse
import json
from pathlib import Path
import sqlite3

from . import entry
from .ledger import Ledger
from .specs import SpecError


def main(argv=None):
    parser = argparse.ArgumentParser(prog='onecrew', description='Portable context; no model calls or approval side effects.')
    parser.add_argument('--project', type=Path, default=Path.cwd())
    parser.add_argument('--state-root', type=Path)
    group = parser.add_subparsers(dest='group', required=True).add_parser('entry')
    commands = group.add_subparsers(dest='command', required=True)
    for name in ('connect', 'note'):
        command = commands.add_parser(name)
        command.add_argument('id')
        command.add_argument('--json', action='store_true')
        if name == 'note':
            command.add_argument('--revision', required=True)
            command.add_argument('--request-id', required=True)
            command.add_argument('--kind', choices=['proposal', 'decision'], required=True)
            command.add_argument('--file', type=Path, required=True, help='UTF-8 summary, at most 2000 characters.')
            command.add_argument('--source', required=True, help='Attribution only, not authentication.')
            command.add_argument('--reference', required=True)
    args = parser.parse_args(argv)
    try:
        ledger = Ledger(args.project, args.state_root)
        if args.command == 'connect':
            result = entry.connect(ledger, args.id)
        else:
            with args.file.open('rb') as stream:
                data = stream.read(8004)
            if len(data) > 8003:
                raise ValueError('Note file exceeds 8003 bytes.')
            result = entry.note(ledger, args.id, args.revision, args.request_id, args.kind,
                                data.decode('utf-8-sig'), args.source, args.reference)
        if args.json or args.command == 'note':
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(human(result))
        return 0
    except (ValueError, OSError, sqlite3.Error, SpecError) as error:
        print(json.dumps({'error': str(error)}, ensure_ascii=False))
        return 1


def human(packet):
    task = packet['task']
    lines = [f"{task['id']} — {task['title']}",
             f"Execution: {task['execution']} | verification: {task['verification']} | acceptance: {task['acceptance']}",
             f"Worker: {packet['worker']} | budget: {task['budget']}",
             f"Context revision: {packet['revision']}", packet['spec']['brief']['text']]
    lines += [f"{'Done' if p['done'] else 'Queued'}: {p['id']} — {p['title']['text']}" for p in packet['plan']['items']]
    lines += [f"Question {q['id']}: {q['question']['text']} (revision {q['revision']}; {q['details_command']})" for q in packet['pending_questions']['items']]
    lines += [f"Answer {a['id']}: {a['choice']} | controller effect: {a['controller_effect']}" for a in packet['recent_answers']]
    lines += [f"Output {o.get('revision')}: {o['summary']['text']} | verification: {o.get('verification')}" for o in packet['outputs']['items']]
    lines += [f"{n['kind']}: {n['summary']} [{n['provenance']['source']}]" for n in packet['notes']['items']]
    lines += [f"Showing plan {len(packet['plan']['items'])}/{packet['plan']['total']}, questions {len(packet['pending_questions']['items'])}/{packet['pending_questions']['total']}, notes {len(packet['notes']['items'])}/{packet['notes']['total']}.",
              'Local context only; private chat is not imported. Notes do not approve or resume work.',
              *packet['detail_commands']]
    if packet['spec']['brief']['truncated']:
        lines.append('Spec brief truncated; task connect contains the pinned full spec.')
    return '\n'.join(lines)
