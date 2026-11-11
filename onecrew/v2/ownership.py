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

2.5.0.dev25 (review Fable 5.2 of dev24, P1-1): a process OneCrew starts to run the project's or a model's code (a check, a reviewer, a step-0
precondition) carries ONECREW_VERIFIER (`child_env`). Such a process is treated as an AI session, so a check script cannot take the owner's
decisions, whoever started the check. One exception keeps OneCrew's own test suite usable as a check: when every ledger the process opened lies
in the temporary folder (fixed once, when this module is first imported, from TMPDIR/TEMP/TMP; never re-read), the marker does not count. With no ledger opened yet it
counts (closed when unknown). A process that declares a non-owner actor (ONECREW_ACTOR=onecrew|claude|codex|...) cannot run an owner verb either
(P1.c, `owner_refused`); who is recorded as the author of an ordinary decision (in_ai_session) is unchanged for it.
Said plainly: this REDUCES, it does not close, the risk. A script that removes the marker on purpose (os.environ.pop), starts `onecrew` with
another TEMP, reaches a real ledger through a hardlink, or writes the sqlite file itself still gets through: an environment variable is a claim.
Only signing the owner's decisions with something an AI cannot use (roadmap D4) closes it.
"""
import json
import os
import tempfile

from ..ledger import LedgerError

AI_MARKERS = ('CLAUDE_CODE_CHILD_SESSION',)
OWNER_VERBS = {('plan', 'approve'), ('plan', 'accept'), ('plan', 'enforce'), ('hook', 'mode'),
               ('question', 'answer'), ('owner', 'answer'),
               ('owner', 'approve'), ('owner', 'accept'), ('owner', 'enforce'), ('owner', 'record'),
               ('support', 'confirm'), ('support', 'target'), ('support', 'rollback')}                    # 2.4-S1: the user's own confirmation of a feedback     # G2: `onecrew owner ...` is the same verbs under one name
OWNER_FORMS = {('verdict', 'record'), ('plan', 'unknown', 'close'), ('unknown', 'resolve'), ('plan', 'poc', 'record'), ('plan', 'retention', 'cleanup')}   # owner verbs only with --by owner (C13); an AI may close an unknown with --by doc|poc
OWNER_FLAG_FORMS = {('support', 'cleanup'): '--v'}        # 2.4-S2 R4-04/R5-01: an owner verb with any option starting --v (--venv and every
                                                          # abbreviation of it); plain cleanup stays open
OWNER_ACTORS = ('user', 'owner')
VERIFIER_MARKER = 'ONECREW_VERIFIER'


def _real(path):
    return os.path.normcase(os.path.realpath(str(path)))


def _temp_root():
    """The temporary folder of THIS process: the first of TMPDIR, TEMP, TMP that is a folder, else the platform default. Read once, when this module
    is first imported (the first Ledger at the latest); a later change of the environment or of tempfile.tempdir does not move it. A script that
    changes TEMP before it imports onecrew, or starts onecrew with another TEMP, chooses it (known limit, LOI-DA-BIET)."""
    for name in ('TMPDIR', 'TEMP', 'TMP'):
        value = os.environ.get(name)
        if value and os.path.isdir(value): return _real(value)
    saved = tempfile.tempdir
    try:
        tempfile.tempdir = None
        return _real(tempfile.gettempdir())
    except OSError:
        return None
    finally:
        tempfile.tempdir = saved


TEMP_ROOT = _temp_root()
_OPENED = set()                         # real paths of the state roots this process opened (Ledger.__init__, the CLI routers)


def note_state_root(path):
    """Record a state root this process opens. Ledger.__init__ calls it for every ledger; a CLI router calls it before refuse_argv."""
    try:
        _OPENED.add(_real(path))
    except (OSError, ValueError, TypeError):
        _OPENED.add('?')                # a root that cannot be resolved is never a temporary one


def _disposable(real):
    if not TEMP_ROOT or real == '?': return False
    return real == TEMP_ROOT or real.startswith(TEMP_ROOT.rstrip(os.sep) + os.sep)


def started_by_check():
    """True when this process carries the marker of a OneCrew check and the exception (every opened ledger temporary) does not apply."""
    if VERIFIER_MARKER not in os.environ: return False
    return not (_OPENED and all(_disposable(r) for r in _OPENED))


def declared_ai_actor():
    """dev25 (P1.c): a process that declares an actor other than the owner (a OneCrew worker sets ONECREW_ACTOR=onecrew) is not the owner."""
    actor = os.environ.get('ONECREW_ACTOR')
    return bool(actor) and actor not in OWNER_ACTORS


def child_env(base):
    """The environment of a process OneCrew starts to run the project's or a model's code: `base` plus the marker."""
    return dict(base, **{VERIFIER_MARKER: '1'})


def in_ai_session():
    # C11: the Claude Code marker present with any value, an empty one included, is an AI session; dev25: so is a OneCrew check (module docstring)
    return any(name in os.environ for name in AI_MARKERS) or started_by_check()


def owner_refused():
    """dev25: the one test of every refusal of an owner verb: an AI session (in_ai_session) or a process that declares a non-owner actor (P1.c).
    Kept apart from in_ai_session, which also decides how an ordinary decision is attributed (decisions.record), so a worker that records its own
    decision under its own name is not treated as a Claude session there."""
    return in_ai_session() or declared_ai_actor()


def why():
    """The reason in_ai_session() is True, for a refusal."""
    if any(name in os.environ for name in AI_MARKERS): return 'this process runs inside an AI tool session (CLAUDE_CODE_CHILD_SESSION is set)'
    if started_by_check(): return ('this process was started by a OneCrew check or precondition (ONECREW_VERIFIER is set) and opened a ledger outside '
                                   "the temporary folder; a check cannot take the owner's decisions")
    return f'this process declares ONECREW_ACTOR={os.environ.get("ONECREW_ACTOR")}, an actor that is not the owner'


def refuse_in_ai_session(what):
    if owner_refused():
        raise LedgerError(f'{what} refused: {why()}. The owner runs it in a terminal of their own.')


def session_info():
    """What this process can say about who runs it, for the ledger: {'actor_env': ONECREW_ACTOR or None, 'ai_session': True | False | 'unknown'}.
    True = an AI-session marker is set (or a OneCrew check started it, or it declares a non-owner actor: owner_refused). False = no marker and the process declares
    itself the owner (ONECREW_ACTOR=user|owner). 'unknown' = no marker and no declaration: an AI that unset the marker looks the same, so nothing is
    claimed. dev25: 'started_by': 'onecrew-check' when the check marker counts."""
    actor = os.environ.get('ONECREW_ACTOR')
    info = {'actor_env': actor, 'ai_session': True if owner_refused() else (False if actor in OWNER_ACTORS else 'unknown')}
    if started_by_check(): info['started_by'] = 'onecrew-check'
    return info


def note_argv_state_root(argv):
    """The CLI routers: resolve the state root the global options name (--project, --state-root; else <project>/.onecrew/config.json, else the
    default, as Ledger does) and record it, BEFORE refuse_argv. Never raises: when the choice cannot be read nothing is recorded, and the check
    marker then counts (closed when unknown)."""
    try:
        project, explicit = None, None
        for index, word in enumerate(argv):
            name, equals, value = word.partition('=')
            if name in ('--project', '--state-root'):
                value = value if equals else (argv[index + 1] if index + 1 < len(argv) else None)
                if name == '--project': project = value
                else: explicit = value
        from . import where
        root = where.state_root_for(project or os.getcwd(), explicit) or where.default_state_root()
        note_state_root(root)
    except Exception:                    # noqa: BLE001 - the guard fails closed (nothing recorded), never open
        pass


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
    flag = OWNER_FLAG_FORMS.get(words[:2])
    flag_form = bool(flag) and any(w.startswith(flag) for w in argv)
    verb = words[:2] if words[:2] in OWNER_VERBS else words[:3] if owner_form and words[:3] in OWNER_FORMS else words[:2]
    if flag_form: verb = (*words[:2], '--venv')
    if not (words[:2] in OWNER_VERBS or owner_form or flag_form) or not owner_refused(): return None
    print(json.dumps({'error': f'{" ".join(verb)} refused: {why()}. The owner runs it in a terminal of their own.',
                      'type': 'LedgerError'}))
    return 2
