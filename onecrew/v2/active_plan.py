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
import re
import sys
import tempfile
import uuid
from pathlib import Path

from ..ledger import LedgerError, utcnow

FILE = 'active-plan.json'
EXPIRY_HOURS = 24
# Commands an AI session may not run while a plan is active. Plain entries are case-insensitive substrings; `re:` entries are regexes.
GITNAME = r'(?<![\w-])git(?:\.exe|\.cmd)?'                                    # C14: git.cmd is the Git for Windows shim
ALIAS_PUSH = r'\s[^|;&]*?-c\s*alias\.[^\s=]+=\S*(?:push|send-pack|http-push)'  # C14: an alias given on the command line (git -c alias.p=push p origin main)
GIT = GITNAME + r'(?:\s+-\S+(?:\s+\S+)?)*'                    # C9: git, git.exe (the hook also tests the form without quotes, so a full path counts), git -c k=v, --no-pager, git -C dir
PUSH = r'(?:push|send-pack|http-push)\b'                                      # C9: send-pack and http-push publish like push
OWNER = r'--b(?:y)?[ =]+owner\b'                                              # C13: argparse accepts the prefix --b for --by
DEFAULT_BASH_DENY = ['re:' + GIT + r'\s+' + PUSH, 're:' + GITNAME + ALIAS_PUSH, r're:\s--config-env[ =]+\S*alias\.', r're:GIT_CONFIG_(?:COUNT|KEY_\d|PARAMETERS)', 're:' + GIT + r'\s+tag\s+(?!-l\b|--list\b|-n\b)\S', 're:' + GIT + r'\s+config\b.*\balias\.',
                     'rm -rf', 'Remove-Item -Recurse', 'pip install',
                     r're:\bplan\s+(approve|accept|enforce)\b',                    # C3: the owner's verbs are not the AI's
                     r're:(?s)\bverdict\s+record\b.*' + OWNER, r're:\bhook\s+mode\b', r're:\bplan_cli\b',
                     r're:(?s)\bplan\s+unknown\s+close\b.*' + OWNER,               # C13: L3's owner verbs (an AI may still close an unknown with --by doc|poc)
                     r're:(?s)\bplan\s+poc\s+record\b.*' + OWNER,
                     r're:(?s)\bonecrew\.v2\b.*\b(?:approve|accept|set_enforced|set_mode|require_owner|close_unknown|poc_record)\s*\(',   # C11: the same verbs called as functions
                     're:ONECREW_ACTOR|CLAUDECODE|CLAUDE_CODE_', r're:\b(git\s+)?(reset\s+--hard|clean\s+-[a-z]*f)',
                     r're:(?:\bri\b|\brd\b|\brmdir\b|\bdel\b|remove-item|rmtree|os\.(?:remove|unlink|rmdir)|shutil\.move)[^|;&]*\.?onecrew']  # B1: deleting .onecrew
# Paths an AI may not write (Edit/Write tools) or mention in a shell command except to read them. Relative entries are project-relative.
DEFAULT_PROTECTED = ['.onecrew/', '.claude/settings.json', '.claude/settings.local.json']
DEFAULT_SCRATCH = ['.onecrew/scratch/']
DEFAULT_GUARDED_HOME = ['CLAUDE.md', 'agents', 'commands', 'skills', 'hooks', 'settings.json', 'settings.local.json']   # F4: instructions for every later session
DEFAULT_KEYWORDS = ['giờ', 'bỏ test', 'skip', 'không cần', 'nhanh lên', 'hours', 'skip test']


def memory_dir(project):
    """The Claude Code memory folder of this project (~/.claude/projects/<path with non-alphanumerics as '-'>/memory): the only part of ~/.claude an AI may write."""
    return str(Path.home() / '.claude' / 'projects' / re.sub(r'[^A-Za-z0-9]', '-', str(Path(project).resolve())) / 'memory')


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
        views = plans.views_for(ledger, contract, state, revision)         # the hooks see what plan show sees: a carried-over milestone as passed, a stale one as not
        status = state['status'] if revision == state['latest'] else 'approved'
        if state['accepted'] and state['accepted']['revision'] == revision: status = 'accepted'
        elif revision in state['stopped']: status = 'stopped_with_report'
        task_id, latest = state['task_id'], state['latest']
        later = {}                                                   # milestone -> seq of its latest verdict.recorded on this revision
        for v in state['verdicts']:
            if v['revision'] == revision: later[v['milestone']] = v['seq']
        unanswered = sorted(m for (r, m), seq in state['issued_seq'].items() if r == revision and seq > later.get(m, 0))
    questions = [r['id'] for r in ledger.requests(task_id, pending=True)]
    chosen = policy(ledger)
    root = Path(ledger.state_root).resolve()
    now = dt.datetime.now(dt.timezone.utc)
    return {'schema_version': 1, 'plan': name, 'revision': revision, 'plan_sha': sha, 'status': status,
            'pending_revision': latest if latest != revision else None, 'anchor_task': task_id,
            # what the plan waits for outside the session: a receipt that has no verdict yet, an owner question nobody answered (the Stop hook lets go)
            'waiting': {'receipt_without_verdict': unanswered, 'open_questions': questions},
            'mode': chosen.get('mode', 'log'), 'title': contract['title'], 'output': contract['output'],
            'owned': contract['scope']['owned'], 'non_goals': contract['non_goals'],
            'bash_deny': list(DEFAULT_BASH_DENY) + list(chosen.get('bash_deny', [])),
            'protected': list(DEFAULT_PROTECTED) + [str(root / 'plans'), str(root)] + [str(Path.home() / '.claude' / n) for n in DEFAULT_GUARDED_HOME],
            'scratch': list(DEFAULT_SCRATCH) + [tempfile.gettempdir(), memory_dir(ledger.project)],
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
