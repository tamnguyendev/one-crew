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
                     r're:\bplan\s+retention\s+cleanup\b',
                     r're:\b(?:question|owner)\s+answer\b',
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


HOLDS_FILE = 'workflow-holds.json'


def holds_marker(project):
    """A tiny marker the register writer leaves BEFORE re-exporting the active plan: {anchor, register_seq}. The hot hook compares
    it with workflow_holds.register_seq of the exported plan and refuses writes while the export is behind the register."""
    return Path(project) / '.onecrew' / HOLDS_FILE


def register_seq(conn, task_id):
    row = conn.execute("SELECT MAX(seq) FROM events WHERE task_id=? AND kind='finding.registered'", (task_id,)).fetchone()
    return int(row[0] or 0)


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
        from . import verdict
        running = sorted({r.get('milestone') for r in verdict.live_runs(conn, task_id, revision)})
        workflow_holds = None
        from . import namespaces
        if namespaces.has_capability(state, 'sequential-engine'):
            from . import finding_scope
            workflow_holds = finding_scope.write_scope(ledger, state['selector'], conn)
            workflow_holds['register_seq'] = register_seq(conn, task_id)      # the register generation this export reflects
    questions = [r['id'] for r in ledger.requests(task_id, pending=True)]
    chosen = policy(ledger)
    root = Path(ledger.state_root).resolve()
    now = dt.datetime.now(dt.timezone.utc)
    return {'schema_version': 1, 'plan': state['name'], 'anchor': state['selector'],
            **({'workflow_holds': workflow_holds} if workflow_holds is not None else {}),
            **{key: state[key] for key in ('workflow_version', 'capabilities') if key in state},
            'revision': revision, 'plan_sha': sha, 'status': status,
            'pending_revision': latest if latest != revision else None, 'anchor_task': task_id,
            # what the plan waits for outside the session: a receipt that has no verdict yet, an owner question nobody answered (the Stop hook lets go)
            'waiting': {'receipt_without_verdict': unanswered, 'open_questions': questions, 'run_in_progress': running},
            'mode': chosen.get('mode', 'log'), 'title': contract['title'], 'output': contract['output'],
            'owned': contract['scope']['owned'], 'non_goals': contract['non_goals'],
            'bash_deny': list(DEFAULT_BASH_DENY) + list(chosen.get('bash_deny', [])),
            'protected': list(DEFAULT_PROTECTED) + [str(root / 'plans'), str(root)] + [str(Path.home() / '.claude' / n) for n in DEFAULT_GUARDED_HOME],
            'scratch': list(DEFAULT_SCRATCH) + [tempfile.gettempdir(), memory_dir(ledger.project)],
            'budget': contract['budget'], 'attention': contract['attention'],
            # last_result / runs / repairs_left: the Stop hook tells a milestone that waits for the owner from one the session can move (B6)
            'milestones': [{'id': v['id'], 'title': v['title'], 'state': v['state'], 'verifier': v['verifier'], 'runs': v.get('runs'),
                            'repairs_left': v.get('repairs_left'), 'last_result': (v.get('last_verdict') or {}).get('result')} for v in views],
            'prompt_keywords': chosen.get('prompt_keywords', DEFAULT_KEYWORDS), 'project': str(Path(ledger.project).resolve()),
            'state_root': str(root), 'exported_at': utcnow(), 'expires': (now + dt.timedelta(hours=EXPIRY_HOURS)).isoformat()}


ENFORCING = ('approved', 'stopped_with_report', 'closed')       # the statuses hook_cli.judge_call enforces


def _same(document, copy):
    if document.get('anchor') and copy.get('anchor'): return document['anchor'] == copy['anchor']
    return bool(document.get('plan')) and copy.get('plan') == document.get('plan')    # a copy from an old build has no anchor (review of dev25, P3-4)


def governing_copy(ledger):
    """The active plan the hooks of this project follow now, as a dict, chosen as hook_cli.govern chooses it: the newest state-root copy that names
    this project (hook_cli.state_copy; the hooks follow it when the project copy is missing, unreadable or different), else the project copy. None
    when there is none; {'unreadable': reason} when the copy that governs cannot be read."""
    from .hook_cli import state_copy
    path = state_copy(ledger.state_root, ledger.project)
    if path is None:
        path = project_file(ledger.project)
        if not path.exists(): return None
    try:
        value = json.loads(Path(path).read_text(encoding='utf-8-sig'))
        if not isinstance(value, dict) or not (value.get('anchor') or value.get('plan')): raise ValueError('no plan named')
        return value
    except (OSError, ValueError) as error:
        return {'unreadable': f'{path}: {type(error).__name__}: {error}'}


def _still_enforcing(ledger, copy):
    """True when the ledger says the governing plan still holds the project (approved, stopped_with_report, closed); also when that cannot be read
    (closed when unknown). False when the ledger has it accepted, or does not know it (never approved)."""
    if copy.get('unreadable'): return True
    try:
        here = ledger
        if copy.get('state_root') and os.path.normcase(str(Path(copy['state_root']).resolve())) != os.path.normcase(str(Path(ledger.state_root).resolve())):
            from ..ledger import Ledger
            here = Ledger(ledger.project, copy['state_root'])
        now = build(here, copy.get('anchor') or copy.get('plan'))
    except Exception:                   # noqa: BLE001 - unknown is enforcing
        return True
    return now is not None and now.get('status') in ENFORCING


def switch_refusal(ledger, document, take_over=False):
    """dev25 (review Fable 5.2, P1-2): the one rule of every write of the hooks' file. None when `document` may become what the hooks follow, else
    the reason. Allowed: no plan governs the project yet; the same plan is refreshed (an accepted one included: the file then says what is true);
    the owner switches (`take_over`: plan approve and hook mode, both behind require_owner); or the governing plan no longer holds the project (the
    ledger has it accepted) and the new one does, so the switch only makes the hooks stricter. Anything else is the owner's, whoever runs it
    (owner 12/11, option B): `hook export`, `plan amend` or `verdict run` of another plan never puts it in place of the one that is enforced."""
    if take_over: return None
    copy = governing_copy(ledger)
    if copy is None or (not copy.get('unreadable') and _same(document, copy)): return None
    if not _still_enforcing(ledger, copy) and document.get('status') in ENFORCING: return None
    current = 'an unreadable active plan (' + copy['unreadable'] + ')' if copy.get('unreadable') else f"plan {copy.get('plan')} ({copy.get('status')})"
    return (f"Plan {document.get('plan')} is not the plan the hooks of this project follow: {current} governs it and still holds it. Only the owner "
            f"switches the governing plan: hook mode enforce --plan {document.get('plan')} --by owner (scripts/owner/enforce.ps1), or plan approve.")


def export(ledger, name, take_over=False, strict=False):
    """Write the active plan for the hooks. Never raises (unless `strict`): an approval or a verdict that is already in the ledger must not fail
    because a file could not be written (the hooks then see a missing or stale file and say so). dev25: a plan that may not become the governing
    one (switch_refusal) is not written at all; `strict` (the `hook export` verb) raises that reason instead of returning None."""
    try:
        document = build(ledger, name)
        if document is None: return None
        refusal = switch_refusal(ledger, document, take_over)
        if refusal:
            if strict: raise LedgerError(refusal)
            print('warning: active-plan.json not exported: ' + refusal, file=sys.stderr)
            return None
        from . import namespaces
        _write(namespaces.active_file(ledger, document['anchor']), document)
        _write(project_file(ledger.project), document)
        return document
    except (OSError, LedgerError, ValueError) as error:
        if strict: raise
        print(f'warning: active-plan.json not exported: {type(error).__name__}: {error}', file=sys.stderr)
        return None
