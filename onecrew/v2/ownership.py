"""C3, the process side: the owner's verbs (plan approve|accept|enforce, verdict record --by owner, hook mode) are refused when the process runs
inside an AI tool session.

Claude Code documents (code.claude.com/docs/en/env-vars, read 2026-10-18) CLAUDECODE=1 for every subprocess it spawns, IDE terminals included, and
CLAUDE_CODE_CHILD_SESSION as the one that is "only set by Claude Code itself when it launches a subprocess" (a tool call or a hook), so it is the one
tested here: the owner's own VS Code terminal has CLAUDECODE but not CLAUDE_CODE_CHILD_SESSION. Seen set in the shell of a `claude -p` tool call (2.1.286). Limits, said plainly: an environment variable is a claim about the process
and an AI that can run `env -u CLAUDE_CODE_CHILD_SESSION` defeats it, so the hook also denies every command that names CLAUDE_CODE_* / CLAUDECODE / ONECREW_ACTOR / plan_cli, and
the generated `permissions.deny` covers the verbs. The check sits at the CLI router (cli.py), gate.set_enforced, verdict.record and `hook mode`;
a direct `python -m onecrew.v2.plan_cli plan approve` or a Python call of plan.approve was covered by the hook rule only; since the fix slice (C11)
`plan.require_owner` itself calls `refuse_in_ai_session`, so every route to an owner verb (router, plan_cli, function call) ends in the same check.
Evidence for the marker, read 2026-10-18: `env` in the tool shell of this session (Claude desktop app, CLAUDE_CODE_ENTRYPOINT=claude-desktop) shows
CLAUDE_CODE_CHILD_SESSION=1 and CLAUDECODE=1; the Opus review of L2 saw the same in its tool shell; the documentation citation above is the L2 author's.
"""
import json
import os

from ..ledger import LedgerError

AI_MARKERS = ('CLAUDE_CODE_CHILD_SESSION',)
OWNER_VERBS = {('plan', 'approve'), ('plan', 'accept'), ('plan', 'enforce'), ('hook', 'mode'),
               ('question', 'answer'), ('owner', 'answer'),
               ('owner', 'approve'), ('owner', 'accept'), ('owner', 'enforce'), ('owner', 'record'),
               ('support', 'confirm')}                    # 2.4-S1: the user's own confirmation of a feedback     # G2: `onecrew owner ...` is the same verbs under one name
OWNER_FORMS = {('verdict', 'record'), ('plan', 'unknown', 'close'), ('unknown', 'resolve'), ('plan', 'poc', 'record'), ('plan', 'retention', 'cleanup')}   # owner verbs only with --by owner (C13); an AI may close an unknown with --by doc|poc
OWNER_ACTORS = ('user', 'owner')


def in_ai_session():
    return any(name in os.environ for name in AI_MARKERS)   # C11: present with any value, an empty one included, is an AI session


def refuse_in_ai_session(what):
    if in_ai_session():
        raise LedgerError(f'{what} refused: this process runs inside an AI tool session (CLAUDE_CODE_CHILD_SESSION is set). The owner runs it in a terminal of their own.')


def session_info():
    """What this process can say about who runs it, for the ledger: {'actor_env': ONECREW_ACTOR or None, 'ai_session': True | False | 'unknown'}.
    True = the AI-session marker is set. False = no marker and the process declares itself the owner (ONECREW_ACTOR=user|owner). 'unknown' = no marker
    and no declaration: an AI that unset the marker looks the same, so nothing is claimed."""
    actor = os.environ.get('ONECREW_ACTOR')
    return {'actor_env': actor, 'ai_session': True if in_ai_session() else (False if actor in OWNER_ACTORS else 'unknown')}


def by_value(argv):
    """The value given to --by in `argv` (also --b, the prefix argparse accepts, and the --by=value form), or None."""
    for index, word in enumerate(argv):
        name, equals, value = word.partition('=')
        if name in ('--b', '--by'):
            if equals: return value
            if index + 1 < len(argv): return argv[index + 1]
    return None


def refuse_argv(argv):
    """Exit code 2 (after printing the reason) when `argv` (starting at the group: plan|verdict|hook) is an owner verb inside an AI session; else None."""
    words = tuple(w for w in argv if not w.startswith('-'))
    owner_form = any(words[:len(form)] == form for form in OWNER_FORMS) and by_value(argv) == 'owner'
    verb = words[:2] if words[:2] in OWNER_VERBS else words[:3] if owner_form and words[:3] in OWNER_FORMS else words[:2]
    if not (words[:2] in OWNER_VERBS or owner_form) or not in_ai_session(): return None
    print(json.dumps({'error': f'{" ".join(verb)} refused: this process runs inside an AI tool session (CLAUDE_CODE_CHILD_SESSION is set). The owner runs it in a terminal of their own.',
                      'type': 'LedgerError'}))
    return 2
