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
    issue = groups.add_parser('issue', help='Read-only, pinned issue lookup; suspects remain hypotheses.').add_subparsers(dest='command', required=True)
    p = issue.add_parser('localize'); p.add_argument('description'); p.add_argument('--name'); p.add_argument('--revision', default='HEAD')
    p.add_argument('--image', type=Path, help='Without a declared vision adapter the image is not opened.')
    p.add_argument('--provider', choices=['claude', 'codex', 'kiro'], help='Whose capability declaration decides whether --image is read (W50b).')
    p = issue.add_parser('evaluate', help='Held-out evaluation: top-1/3/5 and time to a candidate; the oracle file is read only after each lookup.')
    p.add_argument('--cases', type=Path, required=True, help='JSON list of {id, description, revision} (no fixes, labels or lessons).')
    p.add_argument('--oracle', type=Path, required=True, help='JSON object id -> {file, method}; kept apart from the cases.')
    p = issue.add_parser('map', help='Explicitly record a bounded incremental map using context.entry.')
    p.add_argument('name'); p.add_argument('--revision', default='HEAD')
    return parser


def _run(args):
    from . import incidents, lessons
    ledger = _ledger(args, args.command in ('list', 'localize'))
    if args.group == 'issue':
        from . import localization
        if args.command == 'map': return localization.index_project(ledger, args.name, args.revision)
        if args.command == 'evaluate':
            cases = json.loads(args.cases.read_text(encoding='utf-8'))
            oracle_path = args.oracle
            def oracle(case_id):
                return json.loads(oracle_path.read_text(encoding='utf-8'))[case_id]
            return localization.evaluate(ledger, cases, oracle)
        provider = None
        if args.provider:
            from . import providers
            provider = providers.vision(args.provider)
        result = localization.localize(ledger, args.description, name=args.name, revision=args.revision, image=args.image, provider=provider)
        if provider and not result['image']['read'] and provider.get('reason') and args.image is not None:
            result['image']['reason'] = f"{result['image']['reason']} ({provider['reason']})"
        return result
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
