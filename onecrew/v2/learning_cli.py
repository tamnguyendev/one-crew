"""Incident and lesson adapters. Read commands never publish learning."""
import argparse
import json
import sys
from pathlib import Path

from .evidence_cli import _ledger


def _parser():
    parser = argparse.ArgumentParser(prog='onecrew')
    parser.add_argument('--project', type=Path, default=Path.cwd())
    parser.add_argument('--state-root', type=Path)
    groups = parser.add_subparsers(dest='group', required=True)
    incident = groups.add_parser('incident', help='Authentic attempts and verified-repair incidents.').add_subparsers(dest='command', required=True)
    p = incident.add_parser('list'); p.add_argument('name')
    p = incident.add_parser('observe'); p.add_argument('name'); p.add_argument('finding'); p.add_argument('--receipt', required=True)
    p.add_argument('--intentional-red', action='store_true'); p.add_argument('--intent-event', type=int)
    p.add_argument('--refuted', default='[]', help='JSON list of {id,text,event} refuted hypotheses.')
    p = incident.add_parser('finalize', help='Requires an explicit finding resolution on the verified receipt.')
    p.add_argument('name'); p.add_argument('finding')
    lesson = groups.add_parser('lesson', help='Project repair lessons and explicit general candidates; data, never policy.').add_subparsers(dest='command', required=True)
    p = lesson.add_parser('list'); p.add_argument('--name'); p.add_argument('--revision'); p.add_argument('--scope', choices=['project', 'general', 'both'], default='both')
    p = lesson.add_parser('record'); p.add_argument('name'); p.add_argument('--incident', type=int, required=True)
    for flag in ('text', 'path', 'revision', 'test'): p.add_argument('--' + flag, required=True)
    p.add_argument('--line', type=int, required=True); p.add_argument('--symbol')
    p = lesson.add_parser('general', help='Propose a separate, conditional general candidate.')
    p.add_argument('name'); p.add_argument('lesson'); p.add_argument('--text', required=True); p.add_argument('--condition', required=True, action='append')
    p = lesson.add_parser('withdraw'); p.add_argument('name'); p.add_argument('lesson'); p.add_argument('--reason', required=True)
    return parser


def _run(args):
    from . import incidents, lessons
    ledger = _ledger(args, args.command == 'list')
    if args.group == 'incident':
        if args.command == 'list':
            return {'incidents': incidents.list_incidents(ledger, args.name), 'observations': incidents.observations(ledger, args.name)}
        if args.command == 'observe':
            refuted = json.loads(args.refuted)
            if not isinstance(refuted, list) or not all(isinstance(h, dict) for h in refuted):
                raise ValueError('--refuted must be a JSON list of hypothesis objects.')
            return incidents.observe(ledger, args.name, args.finding, args.receipt, intentional_red=args.intentional_red,
                                     intent_event=args.intent_event, refuted_hypotheses=refuted)
        return incidents.finalize(ledger, args.name, args.finding)
    if args.command == 'list': return lessons.retrieve(ledger, name=args.name, revision=args.revision, scope=args.scope)
    if args.command == 'record':
        return lessons.record(ledger, args.name, args.incident, text=args.text, path=args.path, line=args.line,
                              revision=args.revision, test=args.test, symbol=args.symbol)
    if args.command == 'general':
        return lessons.propose_general(ledger, args.name, args.lesson, text=args.text, conditions=args.condition)
    return lessons.withdraw(ledger, args.name, args.lesson, reason=args.reason)


def main(argv=None):
    args = _parser().parse_args(argv)
    try:
        result = _run(args)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except Exception as error:
        import sqlite3
        if not isinstance(error, (ValueError, OSError, sqlite3.Error)): raise
        print(json.dumps({'error': str(error), 'type': type(error).__name__}, ensure_ascii=False))
        return 2


if __name__ == '__main__':
    sys.exit(main())
