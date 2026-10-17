"""`onecrew qc submit|status`: hand a candidate built outside OneCrew to the QC gate, and read the verdict.

The verdict is set only by the runtime (qc_gate); no flag here can name it. Submitting creates a task; `--start` dispatches it the
way `job start` does. Nothing is written to the project.
"""
import argparse
import json
import os
from pathlib import Path

from .ledger import Ledger, LedgerError
from .owned_intake import submit


def _submit(ledger, args):
    from . import interventions, qc_gate
    from .model_preferences import resolve
    from .native_change import validate
    recipe = validate(json.loads(args.recipe.read_text(encoding='utf-8-sig')))
    provider, model = resolve(ledger, args.provider, args.model)
    qc = qc_gate.make(ledger.project, args.branch, recipe, report=args.report, author=args.author, author_provider=args.author_provider,
                      author_model=args.author_model, reviewer_provider=provider, reviewer_model=model, supersedes=args.supersedes)
    goal = 'QC of candidate ' + args.branch + (' (' + qc['head'][:12] + ')' if qc['head'] else '') + ' by ' + args.author
    result = submit(ledger, goal, args.key, mode='change', provider=provider, model=model, max_calls=args.max_calls,
                    max_seconds=args.max_seconds, solution_id=args.solution_id, solution_revision=args.solution_revision,
                    native_change=recipe, qc=qc)
    interventions.note(ledger, result['id'], 'qc.submit', channel='cli', key='qc-submit-' + args.key,
                       details={'branch': args.branch, 'head': qc['head'], 'author': args.author, 'reviewer': qc['reviewer'],
                                'independence': qc['independence']['level'], 'scope_reasons': len(qc['reasons'])})
    result['qc'] = {k: qc[k] for k in ('branch', 'head', 'base', 'author', 'reviewer', 'independence', 'report_sha', 'supersedes', 'plan')}
    result['qc']['scope_reasons'] = qc['reasons']
    if args.start:
        from .owned import Owned
        from .owned_cli import _retrying
        from .runner import start
        _retrying(lambda: Owned(ledger).enable(result['id']))
        result['runner'] = _retrying(lambda: start(ledger, result['id']))
    else:
        result['next'] = 'Start the check with: job start ' + result['id'] + ' (or resubmit with --start). A scope rejection costs no model call.'
    return result


def _status(ledger, task):
    from .owned import Owned
    view = ledger.task(task, full=True)
    options = (view['handoff'].get('owned_execution') or {}) if view.get('handoff') else {}
    qc = options.get('qc')
    if not qc: raise LedgerError(task + ' is not a QC task.')
    runtime = Owned(ledger)
    state = runtime.state(task)[1]
    result = {'task': task, 'verdict': 'pending', 'phase': 'queued', 'stage': None, 'reasons': [], 'author': qc['author'],
              'branch': qc['branch'], 'head': qc['head'], 'base': qc['base'], 'independence': qc['independence'],
              'reviewer': qc['reviewer'], 'plan': qc['plan'], 'supersedes': qc['supersedes'], 'scope_reasons_at_submit': len(qc['reasons']),
              'evidence': {'state_root': str(ledger.state_root)}, 'calls': 0}
    if state is None: return result
    result['phase'] = state['phase']
    finished = state.get('qc')
    if finished:
        result.update(verdict=finished['verdict'], stage=finished['stage'], reasons=finished['reasons'], gate_receipt=finished['gate_receipt'])
        index = finished.get('review_index')
        if index is not None and index < len(state.get('reviews') or []): result['review'] = state['reviews'][index]
    elif state['phase'] == 'blocked':
        result['message'] = state.get('message')
    native = state.get('native_change') or {}
    if native.get('workspace'): result['evidence']['workspace'] = native['workspace']
    try: result['calls'] = runtime.control.status(task)['used_calls']
    except (LedgerError, KeyError): pass
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(prog='onecrew')
    parser.add_argument('--project', type=Path, default=Path.cwd())
    parser.add_argument('--state-root', type=Path)
    group = parser.add_subparsers(dest='group', required=True).add_parser('qc')
    commands = group.add_subparsers(dest='command', required=True)
    p = commands.add_parser('submit', help='Judge a candidate branch built outside OneCrew.')
    p.add_argument('--key', required=True)
    p.add_argument('--branch', required=True, help='Ref in this project\'s repository, built on its current HEAD.')
    p.add_argument('--report', required=True, type=Path, help='The author\'s report (UTF-8). It is recorded and hashed, never trusted.')
    p.add_argument('--recipe', required=True, type=Path, help='Native change recipe JSON: owned files, tests, package, flutter_root.')
    p.add_argument('--solution-id', required=True)
    p.add_argument('--solution-revision', required=True)
    p.add_argument('--author', required=True, help='Who wrote the candidate, e.g. claude-code.')
    p.add_argument('--author-provider', choices=['claude', 'codex', 'kiro'], help='Author vendor when the name does not show it.')
    p.add_argument('--author-model', help='Author model; required when the author is Claude (the only native reviewer), so a different reviewer model is shown.')
    p.add_argument('--provider', default='claude', help='Reviewer provider (MVP-1: claude, the only native reviewer).')
    p.add_argument('--model', help='Reviewer model; give one that differs from the author\'s.')
    p.add_argument('--supersedes', help='Task id of an earlier submission of this candidate.')
    p.add_argument('--max-calls', type=int, default=6)
    p.add_argument('--max-seconds', type=int)
    p.add_argument('--start', action='store_true')
    p = commands.add_parser('status')
    p.add_argument('task')
    args = parser.parse_args(argv)
    ledger = Ledger(args.project, args.state_root)
    try:
        result = _submit(ledger, args) if args.command == 'submit' else _status(ledger, args.task)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except Exception as error:
        import sqlite3
        if not isinstance(error, (ValueError, OSError, sqlite3.Error)): raise
        print(json.dumps({'error': str(error), 'type': type(error).__name__}, ensure_ascii=False))
        return 2
