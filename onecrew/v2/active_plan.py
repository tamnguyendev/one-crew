"""The approved plan, exported as a small file that the Claude Code hooks read (they never open the ledger).

`export()` is called at the end of plan approve / plan amend / verdict record and by `onecrew hook export`. It writes the same
document to `<state-root>/plans/<name>/active-plan.json` and `<project>/.onecrew/active-plan.json`:

    {plan, revision, plan_sha, status, mode: log|enforce, owned[], non_goals[], bash_deny[], protected[], scratch[], budget,
     milestones[], prompt_keywords[], expires, ...}

The file is evidence for the hooks, not authority: the ledger still decides what is approved. What an amendment does to it: the
file keeps describing the last APPROVED revision (so asking for a change cannot widen what is allowed); `pending_revision`
says that a newer one waits for the owner.
"""
import datetime as dt
import json
import os
import sys
import tempfile
import uuid
from pathlib import Path

from ..ledger import LedgerError, utcnow

FILE = 'active-plan.json'
EXPIRY_HOURS = 24
# Commands an AI session may not run while a plan is active. Plain entries are case-insensitive substrings; `re:` entries are regexes.
DEFAULT_BASH_DENY = ['git push', 'git tag', 'rm -rf', 'Remove-Item -Recurse', 'pip install',
                     're:\\bplan\\s+(approve|accept|enforce)\\b',                    # C3: the owner's verbs are not the AI's
                     're:\\bverdict\\s+record\\b.*--by[ =]+owner', 're:\\bhook\\s+mode\\b',
                     're:ONECREW_ACTOR', 're:\\b(git\\s+)?(reset\\s+--hard|clean\\s+-[a-z]*f)']
# Paths an AI may not write (Edit/Write tools) or mention in a shell command except to read them. Relative entries are project-relative.
DEFAULT_PROTECTED = ['.onecrew/', '.claude/settings.json', '.claude/settings.local.json']
DEFAULT_SCRATCH = ['.onecrew/scratch/']
DEFAULT_KEYWORDS = ['giờ', 'bỏ test', 'skip', 'không cần', 'nhanh lên', 'hours', 'skip test']


def project_file(project):
    return Path(project) / '.onecrew' / FILE


def policy(ledger):
    """Owner-chosen hook settings, kept in the state root so that a re-export keeps them: {"mode": "log"|"enforce"}."""
    try:
        value = json.loads((Path(ledger.state_root) / 'plans' / 'hook-policy.json').read_text(encoding='utf-8'))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def set_mode(ledger, mode):
    if mode not in ('log', 'enforce'): raise LedgerError('Mode must be log or enforce.')
    path = Path(ledger.state_root) / 'plans' / 'hook-policy.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    _write(path, dict(policy(ledger), mode=mode))
    return mode


def _write(path, document):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    temporary.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(temporary, path)


def build(ledger, name):
    """The document for plan `name`, or None while the plan has never been approved."""
    from . import plan as plans
    with ledger.transaction() as conn:
        state = plans.derive(ledger, conn, name)
        if state is None or not state['approved']: return None
        revision = state['approved']['revision']
        if state['approved']['sha'] != state['revisions'].get(revision, {}).get('sha'): return None
        contract, sha = plans.load(ledger, state, revision)
        views = plans.milestone_views(contract, state, revision)
        status = state['status'] if revision == state['latest'] else 'approved'
        if state['accepted'] and state['accepted']['revision'] == revision: status = 'accepted'
        elif revision in state['stopped']: status = 'stopped_with_report'
        task_id, latest = state['task_id'], state['latest']
    chosen = policy(ledger)
    root = Path(ledger.state_root).resolve()
    now = dt.datetime.now(dt.timezone.utc)
    return {'schema_version': 1, 'plan': name, 'revision': revision, 'plan_sha': sha, 'status': status,
            'pending_revision': latest if latest != revision else None, 'anchor_task': task_id,
            'mode': chosen.get('mode', 'log'), 'title': contract['title'], 'output': contract['output'],
            'owned': contract['scope']['owned'], 'non_goals': contract['non_goals'],
            'bash_deny': list(DEFAULT_BASH_DENY) + list(chosen.get('bash_deny', [])),
            'protected': list(DEFAULT_PROTECTED) + [str(root / 'plans'), str(root)],
            'scratch': list(DEFAULT_SCRATCH) + [tempfile.gettempdir(), str(Path.home() / '.claude')],
            'budget': contract['budget'], 'attention': contract['attention'],
            'milestones': [{'id': v['id'], 'title': v['title'], 'state': v['state'], 'verifier': v['verifier']} for v in views],
            'prompt_keywords': chosen.get('prompt_keywords', DEFAULT_KEYWORDS), 'project': str(Path(ledger.project).resolve()),
            'state_root': str(root), 'exported_at': utcnow(), 'expires': (now + dt.timedelta(hours=EXPIRY_HOURS)).isoformat()}


def export(ledger, name):
    """Write the active plan for the hooks. Never raises: an approval or a verdict that is already in the ledger must not fail
    because a file could not be written (the hooks then see a missing or stale file and say so)."""
    try:
        document = build(ledger, name)
        if document is None: return None
        _write(Path(ledger.state_root) / 'plans' / name / FILE, document)
        _write(project_file(ledger.project), document)
        return document
    except (OSError, LedgerError, ValueError) as error:
        print(f'warning: active-plan.json not exported: {type(error).__name__}: {error}', file=sys.stderr)
        return None
