"""C3, the process side: the owner's verbs (plan approve|accept|enforce, verdict record --by owner, hook mode) are refused when the process runs
inside an AI tool session.

Claude Code documents (code.claude.com/docs/en/env-vars, read 2026-10-18) CLAUDECODE=1 for every subprocess it spawns, IDE terminals included, and
CLAUDE_CODE_CHILD_SESSION as the one that is "only set by Claude Code itself when it launches a subprocess" (a tool call or a hook), so it is the one
tested here: the owner's own VS Code terminal has CLAUDECODE but not CLAUDE_CODE_CHILD_SESSION. Seen set in the shell of a `claude -p` tool call (2.1.286). Limits, said plainly: an environment variable is a claim about the process
and an AI that can run `env -u CLAUDE_CODE_CHILD_SESSION` defeats it, so the hook also denies every command that names CLAUDE_CODE_* / CLAUDECODE / ONECREW_ACTOR / plan_cli, and
the generated `permissions.deny` covers the verbs. The check sits at the CLI router (cli.py), gate.set_enforced, verdict.record and `hook mode`;
a direct `python -m onecrew.v2.plan_cli plan approve` is covered by the hook rule only (plan.py and plan_cli.py are not changed in this slice).
"""
import json
import os

from ..ledger import LedgerError

AI_MARKERS = ('CLAUDE_CODE_CHILD_SESSION',)
OWNER_VERBS = {('plan', 'approve'), ('plan', 'accept'), ('plan', 'enforce'), ('hook', 'mode')}


def in_ai_session():
    return any(os.environ.get(name) for name in AI_MARKERS)


def refuse_in_ai_session(what):
    if in_ai_session():
        raise LedgerError(f'{what} refused: this process runs inside an AI tool session (CLAUDE_CODE_CHILD_SESSION is set). The owner runs it in a terminal of their own.')


def refuse_argv(argv):
    """Exit code 2 (after printing the reason) when `argv` (starting at the group: plan|verdict|hook) is an owner verb inside an AI session; else None."""
    words = [w for w in argv if not w.startswith('-')][:2]
    owner_record = len(words) == 2 and words[0] == 'verdict' and words[1] == 'record' and any(
        w == 'owner' or w == '--by=owner' for w in argv)
    if not (tuple(words) in OWNER_VERBS or owner_record) or not in_ai_session(): return None
    print(json.dumps({'error': f'{" ".join(words)} refused: this process runs inside an AI tool session (CLAUDE_CODE_CHILD_SESSION is set). The owner runs it in a terminal of their own.',
                      'type': 'LedgerError'}))
    return 2
