"""`onecrew hook check|prompt|stop|session|sync|export|mode|install` — Claude Code hooks for an active v2 plan (slice L2).

The hooks read `<project>/.onecrew/active-plan.json` (see active_plan.py) and never open the ledger on the hot path; `stop`,
`session`, `sync` and `export` may read it. Field names of the hook JSON (Claude Code docs, checked 2026-10-18):
  stdin, all events: session_id, transcript_path, cwd, permission_mode, hook_event_name
  PreToolUse: tool_name, tool_input {Edit/Write/MultiEdit: file_path; NotebookEdit: notebook_path; Bash/PowerShell: command}
  UserPromptSubmit: prompt        Stop: stop_hook_active        SessionStart: source (startup|resume|clear|compact)
  exit 2 blocks (stderr is the reason) on PreToolUse and Stop; output JSON {"hookSpecificOutput": {"hookEventName", "additionalContext"}}.

Modes: `log` never blocks, it only records what it would have blocked; `enforce` blocks. In `enforce` an internal error blocks too
(fail-closed). A missing plan passes. Bash is not a security boundary: this reads the command text, it cannot see what a
script does. The hard layer is `permissions.deny` (`hook install --print`); the hook is the layer that explains and records.
A plan in `stopped_with_report` blocks everything `check` governs: Edit/Write/MultiEdit/NotebookEdit and every Bash/PowerShell command, with no allowlist
(the evidence is read with Read, Grep and Glob, which this hook does not see). Only stdlib at import time: `check` runs before every tool call.
"""
import argparse
import bisect
import contextlib
import datetime as dt
import fnmatch
import glob
import json
import os
import posixpath
import re
import sys
import tempfile
import time
import uuid
from pathlib import Path

from . import where

FILE = 'active-plan.json'
EDIT_TOOLS = ('Edit', 'Write', 'MultiEdit', 'NotebookEdit')
SHELL_TOOLS = ('Bash', 'PowerShell')
PATH_KEYS = ('file_path', 'notebook_path', 'path')
STOP_BLOCK_CAP = 2
READ_ONLY = {'cat', 'type', 'head', 'tail', 'less', 'more', 'ls', 'dir', 'get-content', 'gc', 'get-childitem', 'gci', 'select-string',
             'grep', 'rg', 'findstr', 'test-path', 'stat', 'wc', 'pwd', 'where', 'which'}
HOOK_KINDS = {'blocked': 'hook.blocked', 'logged': 'hook.logged', 'reminded': 'hook.reminded', 'stop_blocked': 'hook.stop_blocked'}
NULLS = {'/dev/null', 'nul', '$null', 'null'}
TEMP_VARS = ('$env:temp', '$env:tmp', '$tmpdir', '${tmpdir}', '$temp', '%temp%', '%tmp%')


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')


# ---- locating and reading the plan -----------------------------------------------------------------------------------------

def utf8_streams():
    """stdout and stderr write UTF-8 whatever code page the pipe was given (Windows hands a hook cp1252): the hook prints Vietnamese titles, and an
    encoding error there would end in a crash instead of the block it was about to give."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding='utf-8', errors='replace')
        except (AttributeError, ValueError, OSError):
            pass


def find_plan_file(candidates, walk=True):
    """First <dir>/.onecrew/active-plan.json found in a candidate directory and, unless walk is False, in its parents up to the repository root (never
    above it: the plan of a parent repository does not govern a repository inside it)."""
    for start in candidates:
        if not start: continue
        try:
            directories = where.repository_dirs(start) if walk else [Path(start).resolve()]
        except OSError:
            continue
        for directory in directories:
            if (directory / '.onecrew' / FILE).is_file(): return directory / '.onecrew' / FILE
    return None


def load_plan(path):
    """(plan, error). A file that exists but cannot be read counts as a plan whose mode is enforce (fail closed)."""
    try:
        plan = json.loads(path.read_text(encoding='utf-8-sig'))
        if not isinstance(plan, dict) or not isinstance(plan.get('owned'), list): raise ValueError('active-plan.json has no owned list')
        return plan, None
    except (OSError, ValueError) as error:
        return {'mode': 'enforce', 'owned': [], 'non_goals': [], 'bash_deny': [], 'protected': [], 'scratch': [], 'plan': '?', 'revision': 0,
                'status': 'approved'}, f'{type(error).__name__}: {error}'


# #25: who made the call that is being judged, and through which hook. Set once per process by note_call; record() writes it on every line.
CALL = {'agent_id': None, 'agent_type': None, 'tool_use_id': None, 'scope': 'project', 'quiet': False}


def note_call(event, scope='project', quiet=False):
    """#25: remember the identity fields of the payload (null when it has none: never guessed). `quiet`: a user-scope call in a project that has its own
    OneCrew hook, which records the call; this one only answers."""
    CALL.update(scope=scope, quiet=quiet)
    for key in ('agent_id', 'agent_type', 'tool_use_id'):
        value = event.get(key) if isinstance(event, dict) else None
        CALL[key] = value if isinstance(value, str) and value else None


def already_recorded(project, plan, tool_use_id):
    """#25 (review P2-4): is there a line for this tool_use_id and plan in the tail of violations.jsonl? (The project hook and the user hook of one call both reach
    record(); the one that comes second adds nothing. A payload with no tool_use_id is never matched.)"""
    if not tool_use_id: return False
    path = Path(project) / '.onecrew' / 'violations.jsonl'
    try:
        with path.open('rb') as stream:
            stream.seek(0, os.SEEK_END)
            stream.seek(max(0, stream.tell() - 65536))
            tail = stream.read().decode('utf-8', errors='replace').splitlines()
    except OSError:
        return False
    name = (plan or {}).get('plan')
    for line in tail[-200:]:
        try:
            item = json.loads(line)
        except ValueError:
            continue
        if isinstance(item, dict) and item.get('tool_use_id') == tool_use_id and item.get('plan') == name and item.get('rule') != 'plan_restored': return True
    return False


def claim_call(folder, plan, tool_use_id):
    """#25 (review 2, P2-A): True when this process may write the line of the call. The project hook and the user hook of one call run at the same time, so
    reading the tail is not enough: whoever creates `.onecrew/calls/<tool_use_id>.<plan>` first (O_CREAT | O_EXCL) writes, the other gets FileExistsError and
    does not. A call without a tool_use_id always records. Claims older than a day are removed (best effort) so the folder stays small."""
    if not tool_use_id: return True
    calls = Path(folder) / 'calls'
    name = re.sub(r'[^\w.-]', '_', f'{tool_use_id}.{(plan or {}).get("plan")}')[:150]
    try:
        calls.mkdir(exist_ok=True)
        os.close(os.open(str(calls / name), os.O_CREAT | os.O_EXCL | os.O_WRONLY))
    except FileExistsError:
        return False
    except OSError:
        return True                  # no marker possible: record (a double line is better than none)
    try:
        limit = time.time() - 86400
        for old in calls.iterdir():
            if old.stat().st_mtime < limit: old.unlink()
    except OSError:
        pass
    return True


@contextlib.contextmanager
def appending(lock_path, wait=10.0):
    """FIX25B (Codex F5, decision D4): an OS lock (msvcrt.locking on Windows, fcntl.flock elsewhere) on a small lock file, held while a line is appended. The lock is
    taken by polling for up to `wait` seconds; a lock that cannot be had in that time (or at all) is skipped, so a record is never lost to a stuck lock: a rare torn line is
    better than none. The lock dies with the process, so a crashed hook leaves nothing behind."""
    handle, locked = None, False
    try:
        handle = open(lock_path, 'a+b')
        deadline = time.monotonic() + wait
        while True:
            try:
                if os.name == 'nt':
                    import msvcrt
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                locked = True
                break
            except OSError:
                if time.monotonic() >= deadline: break
                time.sleep(0.003)
    except OSError:
        pass
    try:
        yield
    finally:
        if handle is not None:
            try:
                if locked:
                    if os.name == 'nt':
                        import msvcrt
                        handle.seek(0)
                        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass
            handle.close()


def record(project, plan, event, tool, reason, rule, subject='', session=None, mode=None):
    """Append to <project>/.onecrew/violations.jsonl (no ledger lock). Only when .onecrew/ exists: a repo without a plan stays untouched."""
    if CALL['quiet']: return
    if rule != 'plan_restored' and already_recorded(project, plan, CALL['tool_use_id']): return        # #25 (review P2-4): one call, one record
    folder = Path(project) / '.onecrew'
    try:
        folder.mkdir(exist_ok=True)                      # a plan governs this project, so the record goes in even if .onecrew/ was deleted
    except OSError:
        return
    if rule != 'plan_restored' and not claim_call(folder, plan, CALL['tool_use_id']): return        # #25 (review 2, P2-A): the other hook of this call got there first
    line = {'id': uuid.uuid4().hex, 'at': now(), 'event': event, 'tool': tool, 'rule': rule, 'reason': reason[:400], 'subject': subject[:300],
            'plan': (plan or {}).get('plan'), 'revision': (plan or {}).get('revision'), 'mode': mode or (plan or {}).get('mode'), 'session': session,
            'agent_id': CALL['agent_id'], 'agent_type': CALL['agent_type'], 'tool_use_id': CALL['tool_use_id'], 'scope': CALL['scope']}
    data = (json.dumps(line, ensure_ascii=False) + '\n').encode('utf-8')
    try:
        with appending(folder / 'violations.lock'):       # FIX25B (Codex F5): one writer at a time; without it concurrent appends overwrote each other (344 of 360 lines)
            with (folder / 'violations.jsonl').open('ab') as stream: stream.write(data)
    except OSError:
        pass


def session_state(project, session, update=None):
    path = Path(project) / '.onecrew' / 'hook-state.json'
    try:
        state = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        state = {}
    mine = state.get(session or '?', {})
    if update is not None:
        mine.update(update)
        state[session or '?'] = mine
        for stale in list(state)[:-20]: state.pop(stale, None)
        try:
            path.write_text(json.dumps(state), encoding='utf-8')
        except OSError:
            pass
    return mine


# ---- paths -----------------------------------------------------------------------------------------------------------------

def normalize(raw, base):
    """Absolute, resolved Path of a tool path (Git Bash /d/x style included)."""
    text = str(raw).strip().strip('"\'')
    if os.name == 'nt' and re.match(r'^/[A-Za-z]/', text): text = text[1] + ':' + text[2:]
    path = Path(os.path.expandvars(text)).expanduser()
    return (path if path.is_absolute() else Path(base) / path).resolve()


def relative(path, root):
    try:
        return Path(path).relative_to(root).as_posix()
    except ValueError:
        return None


def _fold(text):
    return str(text).replace('\\', '/').casefold()


def under(rel, pattern):
    """rel (posix, project relative) matches an owned/non-goal pattern: exact, directory prefix, or glob."""
    pattern = _fold(pattern).lstrip('./') if _fold(pattern).startswith('./') else _fold(pattern)
    rel = _fold(rel)
    if any(c in pattern for c in '*?['): return fnmatch.fnmatchcase(rel, pattern) or fnmatch.fnmatchcase(rel + '/', pattern)
    pattern = pattern.rstrip('/')
    return rel == pattern or rel.startswith(pattern + '/')


def path_like(text):
    return bool(text) and not re.search(r'\s', text)       # a non_goal sentence is text for people; only path-shaped ones are rules


def rules_text(plan):
    return (f"Plan {plan.get('plan')} revision {plan.get('revision')}: you may change {', '.join(plan.get('owned', [])[:8])}"
            f"{' ...' if len(plan.get('owned', [])) > 8 else ''}. To change this list, ask the owner: write the new revision and run "
            f"`onecrew plan amend {plan.get('plan')} --file <revised plan.json> --reason \"<why>\" --author claude`; the owner approves it.")


def holds_current(root, plan):
    """The hot path reads only two small files. The register writer leaves `.onecrew/workflow-holds.json` {anchor, register_seq} before it
    re-exports the plan; a marker newer than the plan's workflow_holds.register_seq means the exported holds are stale (the export failed or
    has not happened yet), so the plan cannot say which paths are held: raise, and enforce mode blocks the call."""
    holds = plan.get('workflow_holds')
    if not isinstance(holds, dict): return
    try:
        marker = json.loads((Path(root) / '.onecrew' / 'workflow-holds.json').read_text(encoding='utf-8-sig'))
    except (OSError, ValueError):
        return
    if not isinstance(marker, dict) or marker.get('anchor') != plan.get('anchor'): return
    newer, known = marker.get('register_seq'), holds.get('register_seq')
    if isinstance(newer, int) and (not isinstance(known, int) or newer > known):
        raise ValueError(f'the finding register changed (seq {newer}) after the active plan was exported (seq {known}); the held scope is unknown. '
                         f'Run `onecrew hook export {plan.get("plan")}` to refresh it.')


def plain_form(path):
    """#25: the path without a `\\\\?\\` or `\\\\.\\` prefix (`\\\\?\\UNC\\host\\share` is `\\\\host\\share`)."""
    text = str(path)
    if text[:8].upper() == '\\\\?\\UNC\\': return Path('\\\\' + text[8:])
    return Path(text[4:]) if text.startswith(('\\\\?\\', '\\\\.\\')) else Path(path)


def judge_path(plan, root, target, action):
    """(rule, reason) when this plan forbids writing to `target`, else None."""
    verbatim = str(target).startswith(('\\\\?\\', '\\\\.\\'))        # #25 (review P2-6): Win32 trims trailing dots and spaces of a component, a `\\?\` path is not trimmed
    root, target = plain_form(root), plain_form(target)            # the same form on both sides, so a prefix on one never hides a path from `relative`
    rel = relative(target, root)
    scratch = [normalize(s, root) if not os.path.isabs(s) else Path(s).resolve() for s in plan.get('scratch', [])]
    # #25: interpreter code now reaches judge_path with literal paths; a path Windows reads as inside scratch (`.onecrew/scratch ./x`) stays excused
    if rel is not None and (under(rel, '.onecrew/scratch') or (not verbatim and _fold(rel).startswith('.onecrew') and stays_in_scratch(_fold(rel)))): return None
    home =Path.home().resolve() / '.claude'
    guarded = [normalize(p, root) for p in plan.get('protected', [])] + [home / 'settings.json', home / 'settings.local.json', where.registry_file().resolve()]      # the registry: the owner's pointer to the state root
    for item in guarded:
        if target == item or item in target.parents:
            return 'protected', f'{target} is protected: the ledger, plans/ and hook files are the owner\'s, not the AI\'s. {action}'
    if rel is not None:
        holds=plan.get('workflow_holds') or {}
        if any(under(rel,path) for path in holds.get('paths',[])):
            return 'finding_scope', f'{rel} is held by unresolved findings {", ".join(holds.get("findings",[]))}; write permission is withdrawn for this scope. The session is not stopped.'
        for goal in plan.get('non_goals', []):
            if path_like(goal) and under(rel, goal):
                return 'non_goal', f'{rel} matches non_goal "{goal}". {rules_text(plan)}'
        if any(under(rel, o) for o in plan.get('owned', [])): return None
    for item in scratch:                                  # a scratch place outside the project never excuses a file inside it
        if item in Path(root).parents: continue           # nor does one that contains the whole project (a project under %TEMP%)
        if (target == item or item in target.parents) and (rel is None or item == Path(root) or Path(root) in item.parents): return None
    place = rel if rel is not None else f'{target} (outside the project)'
    return 'outside_owned', f'{place} is not in the owned scope. {rules_text(plan)}'


# ---- shell commands --------------------------------------------------------------------------------------------------------

# #12: a target is a whole shell word: quoted and unquoted parts joined (`"$TMPDIR"/../x` is one word, not `"$TMPDIR"`)
REDIRECT_PS = re.compile(r'(?<![<>&-])(?:\d|\*)?>>?(?![&>])[ \t]*((?:"[^"]*"|\'[^\']*\'|[^\s;|&<>()])+)')
# FIX25B (Codex F3): the `*` stream prefix (`*>`, `*>>`, `*>&1`) is PowerShell's all-streams operator; in Bash `rm -f *>/dev/null` is the glob `*` and a redirect,
# so the Bash forms have no `*` and the glob stays a word of its command.
REDIRECT = re.compile(REDIRECT_PS.pattern.replace(r'(?:\d|\*)?', r'\d?'))
# #12: the write redirects REDIRECT leaves out: `>|` (its target class stops at `|`), `&>`, `&>>` (its lookbehind), and `>&file` (but `>&1`, `>&2`, `>&-` copy a descriptor,
# also when `;` `|` `&` `)` `<` `>` follows: `2>&1)`)
REDIRECT_MORE_PS = re.compile(r'(?:>\||&>>?|(?<![<>&])(?:\d|\*)?>&(?![ \t]*(?:\d+|-)(?![\w.])))[ \t]*((?:"[^"]*"|\'[^\']*\'|[^\s;|&<>()])+)')
REDIRECT_MORE = re.compile(REDIRECT_MORE_PS.pattern.replace(r'(?:\d|\*)?', r'\d?'))
EVERY = ('rm', 'del', 'erase', 'rd', 'rmdir', 'ri', 'remove-item', 'mkdir', 'md', 'touch', 'tee', 'clear-content', 'clc')        # every plain word is a target
FIRST = ('set-content', 'sc', 'add-content', 'ac', 'out-file', 'tee-object', 'new-item', 'ni', 'export-csv', 'export-clixml')   # the first one is
COPY = ('cp', 'mv', 'copy', 'move', 'copy-item', 'cpi', 'move-item', 'mi', 'ren', 'rename', 'rename-item', 'rni')              # the last one is
MOVE = ('mv', 'move', 'move-item', 'mi', 'ren', 'rename', 'rename-item', 'rni')               # FIX25B (Codex F1): the ones of COPY that also change their source
RENAME = ('ren', 'rename', 'rename-item', 'rni')               # FIX25C (Codex R2): the ones of MOVE whose second word is a new name in the source's own folder
NAMED = ('-path', '-filepath', '-literalpath', '-destination', '-name')
WORD = r'(?:"[^"]*"|\'[^\']*\'|[^\s;|&<>])+'            # #12: one shell word, its quoted and unquoted parts joined
WORDS = re.compile(r'(?:"[^"]*"|\'[^\']*\'|\S)+')
SEP = r'(?:[ \t]|\\\r?\n)+'          # #12: blanks between the words of a writer; a bare line end ends the command, a backslash-newline does not
WRITERS = re.compile(r'(?:^|[\s;|&(])(' + '|'.join(re.escape(n) for n in sorted(EVERY + FIRST + COPY, key=len, reverse=True)) + r')(?=\s)'
                     r'((?:' + SEP + r'(?:--?[\w-]+(?:=' + WORD + r')?' + SEP + WORD + r'|--?[\w-]+(?:=' + WORD + r')?|(?!-)' + WORD + r'))+)', re.I)      # FIX25B (Codex F1): a long option (`--target-directory=src`) is one option, not the end of the arguments   # a flag's value stops at ; | & < > (B1)
DOTNET = re.compile(r'\[(?:System\.)?IO\.(?:File|Directory)\]::(\w+)\(\s*("[^"]*"|\'[^\']*\'|[^,)\s]+)(?:\s*,\s*("[^"]*"|\'[^\']*\'|[^,)\s]+))?', re.I)
# PowerShell only (beta report B1): the common parameters whose value is never a path, and the built-in drives that are not files. A drive the
# session makes with New-PSDrive is still read as a file; registry writes are left to the other rules.
COMMON_VALUE = ('-erroraction', '-ea', '-warningaction', '-wa', '-informationaction', '-infa', '-errorvariable', '-ev', '-warningvariable', '-wv',
                '-informationvariable', '-iv', '-outvariable', '-ov', '-outbuffer', '-ob', '-pipelinevariable', '-pv')
# #12: a switch takes no value, so the word after it is still a target (`New-Item -ItemType File -Force x`)
SWITCHES = ('-force', '-recurse', '-append', '-noclobber', '-nonewline', '-passthru', '-whatif', '-confirm', '-usetransaction', '-asbytestream',
            '-notypeinformation', '-nonewline')
# #12: sed with -i / --in-place anywhere among its options writes its file operands (`sed -E -i`, `sed -e ... -i f`); the options are read from the text as written
SED_WORDS = re.compile(r'(?<![\w.-])sed(?=\s)([^;|&<>\n]*)', re.I)
FEEDERS = re.compile(r'(?<![\w.-])(?:xargs|parallel)(?![\w.-])', re.I)


DESCRIPTOR_DUP_PS = re.compile(r'(?<![<>&\w])(?:\d*|\*)[<>]&(?:\d+|-)(?![\w.])')      # #25 (final review P1-2): `*>&1` is PowerShell's all-streams duplication
DESCRIPTOR_DUP = re.compile(r'(?<![<>&\w])\d*[<>]&(?:\d+|-)(?![\w.])')               # FIX25B (Codex F3): no `*` in Bash


def unquote(word):
    """The shell word without its quote marks (`"$TMPDIR"/x` is `$TMPDIR/x`)."""
    return re.sub(r'["\']', '', word)


# #25 (review P1-2): in Bash a backslash before a space keeps the word whole (`du\ an\ A`). The escape is hidden as two control characters of the same length
# before the text is read and put back as a plain space after, so no quote or comment reader has to change; PowerShell has no such escape.
ESCAPED = re.compile(r'(?<!\\)((?:\\\\)*)\\([ \t])')
HIDDEN = '\x01'


def hide_escapes(text, powershell=False):
    return text if powershell or '\\' not in text else ESCAPED.sub(lambda m: m.group(1) + HIDDEN + ('\x02' if m.group(2) == ' ' else '\x03'), text)


def show_escapes(text):
    return text.replace(HIDDEN + '\x02', ' ').replace(HIDDEN + '\x03', '\t') if HIDDEN in text else text


PSDRIVE = re.compile(r'^(?:(?:env|variable|function|alias|hkcu|hklm|cert|wsman):|(?:microsoft\.powershell\.(?:core|security)\\)?'
                     r'(?:environment|variable|function|alias|registry|certificate|wsman)::)', re.I)


BACKSLASHES = re.compile(r'\\+')
NEWLINE = re.compile(r'\r?\n')


def COMMENT_START(command, i, powershell=False):
    """#12: does the `#` at `i` start a word (so it starts a comment)? `$#`, `${x#y}`, `a#b` do not. `)` ends a word in both shells, `{` and `}` in PowerShell
    (in bash `${#x}` is a length); in bash a space or tab with an odd run of backslashes before it is an escaped space, so the `#` after it is in the middle of a word."""
    if i == 0: return True
    before = command[i - 1]
    if before in ' \t' and not powershell:
        j = i - 2
        while j >= 0 and command[j] == '\\': j -= 1
        return (i - 2 - j) % 2 == 0
    return before in ' \t\r\n;|&()' or (powershell and before in '{}')


def block_comment_end(command, i):
    """The end of a PowerShell `<# ... #>` comment that starts at `i` (it may span lines; a missing `#>` runs to the end)."""
    close = command.find('#>', i + 2)
    return len(command) if close < 0 else close + 2


def masked_quotes(command, powershell=False):
    """The command with the inside of every quoted string blanked (same length, the quotes kept), so `<`, `>`, `|`, `;` and a writer's name
    inside a string are text, not a redirect, a pipe or a command (beta report B2). A double-quoted string that holds `$(` or a backtick is left as
    written, because it can run a command; quotes that do not pair leave the whole text as written (such a command does not parse)."""
    spans, comments, i, n = [], [], 0, len(command)
    while i < n:
        quote = command[i]
        if quote == '\\' and not powershell:               # #12: in bash `\'` and `\"` outside quotes are plain characters; the run is counted without slicing
            run = BACKSLASHES.match(command, i).end() - i
            i += run
            if run % 2 and i < n and command[i] in '"\'': i += 1
            continue
        if powershell and quote == '<' and command.startswith('<#', i):      # #12: a PowerShell block comment `<# ... #>`, masked before line comments
            end = block_comment_end(command, i)
            comments.append((i, end))
            i = end
            continue
        if quote == '#' and COMMENT_START(command, i, powershell):      # #12: a comment runs to the line end; its text is neither a command nor a write target
            end = command.find('\n', i)
            end = n if end < 0 else end
            comments.append((i, end))
            i = end
            continue
        if powershell and quote == '`':                      # #12: in PowerShell a backtick escapes the next character (`'` is no quote)
            i += 2
            continue
        if quote not in '"\'':
            i += 1
            continue
        end = i + 1
        while end < len(command) and command[end] != quote:
            end += 2 if quote == '"' and (command[end] == '\\' or (powershell and command[end] == '`')) else 1
        if end >= len(command): return command
        spans.append((i, end))
        i = end + 1
    out = list(command)
    for start, end in comments: out[start:end] = ' ' * (end - start)      # #12: blanks, not `_`: a word never runs on into the comment text
    for start, end in spans:
        inner = command[start + 1:end]
        if command[start] == '"' and ('$(' in inner or '`' in inner): continue
        out[start + 1:end] = '_' * len(inner)
    return ''.join(out)


def shell_targets(command, powershell=False):
    """Paths a shell command text appears to write. Heuristic: redirects, tee/Set-Content/sc/ac/Out-File/Tee-Object/cp/mv/rm/ri..., [IO.File]::, sed -i.
    Redirects and writers are found outside quoted strings (masked_quotes); their targets are read from the command as written. In PowerShell
    the value of a common parameter (-ErrorAction ...) is not a target."""
    command = hide_escapes(command, powershell)
    masked = masked_quotes(command, powershell)
    # #25 (review 3, P1-C): `2>&1`, `1>&2`, `>&-`, `0<&3` copy a descriptor; blanked before the writers read their words, so the `2` is no copy target
    blank = lambda m: ' ' * len(m.group(0))
    dup, redirect, more = (DESCRIPTOR_DUP_PS, REDIRECT_PS, REDIRECT_MORE_PS) if powershell else (DESCRIPTOR_DUP, REDIRECT, REDIRECT_MORE)
    command, masked = dup.sub(blank, command), dup.sub(blank, masked)
    found = [unquote(command[m.start(1):m.end(1)]) for m in redirect.finditer(masked)]
    found += [unquote(command[m.start(1):m.end(1)]) for m in more.finditer(masked)]
    for m in SED_WORDS.finditer(masked):
        text = command[m.start(1):m.start(1) + len(masked[m.start(1):m.end(1)].rstrip())]      # #12: a comment after the options is masked blank, its words are no files
        if command[m.end(1):m.end(1) + 1] == '>' and re.search(r'(?:^|\s)\d+$', command[m.start(1):m.end(1)]): text = re.sub(r'(?:^|\s)\d+$', '', text)      # #12: `2>/dev/null` is a redirect, its `2` no file
        words = [unquote(w) for w in WORDS.findall(text)]
        in_place, script_given, files, i = False, False, [], 0
        while i < len(words):
            w = words[i]
            if w == '--':
                files += words[i + 1:]; break
            if w.startswith('--'):
                name = w.split('=')[0]
                in_place = in_place or (len(name) >= 4 and '--in-place'.startswith(name))
                if name in ('--expression', '--file') and '=' not in w: i += 1
                script_given = script_given or name in ('--expression', '--file')
            elif w.startswith('-') and len(w) > 1:
                for n, letter in enumerate(w[1:]):         # a cluster ends at -i (the rest is its suffix) or at -e/-f (the rest, or the next word, is the script)
                    if letter == 'i':
                        in_place = True; break
                    if letter in 'ef':
                        script_given = True
                        if n == len(w) - 2: i += 1
                        break
            else: files.append(w)
            i += 1
        if in_place: found += files if script_given else files[1:]
        # #12: behind xargs / parallel the files come from stdin and the line does not show them: a target the hook cannot resolve
        if in_place and FEEDERS.search(masked[max(masked.rfind(c, 0, m.start()) for c in ';|&\n') + 1:m.start()]): found.append('$xargs')
    for m in WRITERS.finditer(masked):
        cmd, words = m.group(1).lower(), WORDS.findall(command[m.start(2):m.end(2)])
        if powershell:
            words = [w for i, w in enumerate(words) if not (i and words[i - 1].lower() in COMMON_VALUE)]
        if cmd == 'rm' and '--cached' in words: continue            # FIX25B: `git rm --cached` only changes the index; the long-option reader below now sees past `--cached`
        named = [words[i + 1] for i, w in enumerate(words[:-1]) if w.lower() in NAMED]
        plain = [w for w in words if not w.startswith('-')]
        if cmd in EVERY: values = plain + named
        elif cmd in RENAME: values = rename_targets(words)
        elif cmd in MOVE:
            # FIX25B (Codex F1): a move or rename takes its SOURCE away too, so every source and the destination are targets (`--target-directory=DIR` is one)
            values = plain + named + [w.split('=', 1)[1] for w in words if w.lower().startswith('--target-directory=')]
        elif cmd in COPY: values = named[-1:] or plain[-1:]
        else:                                           # FIRST: -Value / -Encoding take a value, so only the first plain word counts
            values = named[:1] or [w for i, w in enumerate(words) if not w.startswith('-') and not (i and words[i - 1].startswith('-') and words[i - 1].lower() not in SWITCHES)][:1]
        found += [unquote(v) for v in values]
    for m in DOTNET.finditer(command):                  # the second argument is a path only for Copy / Move / Replace (WriteAllText takes the content)
        found += [g.strip('"\'') for g in ((m.group(2), m.group(3)) if m.group(1).lower() in ('copy', 'move', 'replace') else (m.group(2),)) if g]
    return [show_escapes(f) for f in found if f]



def rename_targets(words):
    """FIX25C (Codex R2): the targets of `Rename-Item` / `ren` (their aliases too): the item renamed (-Path / -LiteralPath / the first plain word) and the new
    name (-NewName / the next plain word) in the item's OWN folder: `Rename-Item src/a.txt b.txt` makes src/b.txt, not b.txt where the shell is. A new name
    that holds a folder is also kept as written, and any other plain word is a target as before: the hook does not guess, it may only refuse more."""
    sources, names, rest, i = [], [], [], 0
    while i < len(words):
        word = words[i]
        low = word.lower()
        if low.startswith('-') and len(low) > 1:
            option, colon, value = low.partition(':')
            kind = 'name' if '-newname'.startswith(option) and len(option) > 1 else \
                'path' if option in ('-lp', '-pspath') or ('-literalpath'.startswith(option) and len(option) > 1) or ('-path'.startswith(option) and len(option) > 3) else None
            if kind and colon: (names if kind == 'name' else sources).append(word.partition(':')[2])
            elif kind and i + 1 < len(words):
                (names if kind == 'name' else sources).append(words[i + 1])
                i += 1
            i += 1
            continue
        rest.append(word)
        i += 1
    if not sources and rest: sources.append(rest.pop(0))
    if not names and rest: names.append(rest.pop(0))
    values = sources + rest
    for name in names:
        bare = unquote(name)
        if re.search(r'[/\\]', bare): values.append(name)
        for source in sources:
            folder = unquote(source).rstrip('/\\')
            values.append(folder[:max(folder.rfind('/'), folder.rfind('\\')) + 1] + bare)
    return values


QUOTED = re.compile(r"\"([^\"]{3,})\"|'([^']{3,})'")
BASH_WORDS = re.compile(r'(?:"(?:[^"\\]|\\.)*"|\'[^\']*\'|\\.|\S)+', re.S)      # #25: WORDS for Bash, where a double-quoted string may hold `\"` and a `\"` outside quotes is no quote
BASH_QUOTED = re.compile(r"\"((?:[^\"\\]|\\.){3,})\"|'([^']{3,})'", re.S)


def nested_strings(text, powershell=False):
    """#25 (review P2-5): [(start, string)] of the quoted parts of `text`. In Bash a double-quoted string may hold `\\"` and `\\\\`: it is read to its real end and
    unescaped (`sh -c "cd \\"A\\" && echo hi > x"` is `cd "A" && echo hi > x`); PowerShell keeps the plain reader."""
    if powershell: return [(m.start(), m.group(1) or m.group(2)) for m in QUOTED.finditer(text)]
    return [(m.start(), re.sub(r'\\(["\\$`])', r'\1', m.group(1)) if m.group(1) is not None else m.group(2)) for m in BASH_QUOTED.finditer(text)]


CUE = re.compile(r'\b(?:iex|invoke-expression|powershell(?:\.exe)?|pwsh|cmd(?:\.exe)?|bash|sh|zsh|dash|eval|invoke-command|start-process|wsl)\b', re.I)


def all_targets(command, depth=0, powershell=False):
    """C10: shell_targets of the command as written, without backticks/carets, and (recursively, up to 3 levels) of each quoted part that follows an
    interpreter (`iex 'sc README.md x'`, `powershell -c "sc ..."`, `cmd /c "..."`, `bash -c '...'`), so a write nested in a string is judged like one
    typed plainly. Only text after such a cue is read as a command: a commit message "Move a to b" is not a move. A quoted path with a space
    may show up cut at the space, which errs on the side of blocking. `powershell`: the text is PowerShell; a nested string is PowerShell after
    powershell/pwsh, not after bash/sh/zsh/dash/wsl/cmd, and otherwise what its parent is."""
    cleaned = re.sub(r'[`^]', '', command)
    found = shell_targets(command, powershell)
    if cleaned != command: found += shell_targets(cleaned, powershell)
    if depth < 3:
        for text in dict.fromkeys((command, cleaned)):
            for start, inner_text in nested_strings(text, powershell):
                cue = CUE.findall(re.split(r'[;&|\n]', text[:start])[-1])
                if cue:
                    word = cue[-1].lower()
                    inner = True if word.startswith(('powershell', 'pwsh')) else False if word.startswith(('bash', 'sh', 'zsh', 'dash', 'wsl', 'cmd')) else powershell
                    found += all_targets(inner_text, depth + 1, inner)
    return list(dict.fromkeys(found))


def not_a_file(raw, powershell):
    """A write target that is no file of any project: a null device, the temp folder, or (PowerShell) a built-in drive that is not a file system."""
    lowered = raw.casefold()
    # #12: a temp variable excuses only what stays inside it: a `..` component (as Windows reads it) makes the target an ordinary one
    # and only a variable whose name ends right there (`$TEMPDIR_X` is not `$TEMP`)
    in_temp = any(lowered.startswith(v) and lowered[len(v):len(v) + 1] in ('', '/', '\\') for v in TEMP_VARS) and not any(scratch_component(part) == '..' for part in re.split(r'[\\/]+', raw))
    return lowered in NULLS or in_temp or (powershell and PSDRIVE.match(raw) is not None)


def variants(command):
    """The command as written, without quotes/backticks/carets, and without backslashes too: `plan "approve"` and `plan app\rove` still name approve."""
    unquoted = re.sub(r'["\'`^]', '', command)
    return [command, unquoted, unquoted.replace('\\', '')]


def shell_segments(command, powershell=False, detail=False):
    """The command cut at `;`, `&&`, `||`, `|`, a lone `&` and line ends, outside quotes: a quoted string stays in the segment that holds it.
    `detail`: every piece, the empty ones too, as (text, the operator that ends it, the index in `command` where the operator ends).
    #12: in bash (not PowerShell) an odd run of backslashes before the line end joins the lines (backslash, newline, then `git stash`), except inside single quotes; in
    PowerShell a backslash is a path character: it joins nothing and does not escape a quote (a quoted path may end in one)."""
    parts, current, quote, i, n = [], [], None, 0, len(command)
    ops, cuts = [], []
    while i < n:
        char = command[i]
        if char == '\\' and not powershell and quote != "'":
            run = BACKSLASHES.match(command, i).end() - i        # #12: counted in place, not by slicing the rest of the text per backslash (linear time)
            end = NEWLINE.match(command, i + run)
            if end:
                current.append('\\' * (run - run % 2))                  # an even run is escaped backslashes: the line end stays a line end
                i += run + (end.end() - end.start() if run % 2 else 0)
                continue
            current.append('\\' * run)
            i += run
            if run % 2 and i < n and command[i] in '"\'' and (quote is None or command[i] == '"'):
                current.append(command[i]); i += 1                      # #12: `\'` and `\"` are plain characters, not quote marks
            continue
        if powershell and quote is None and command.startswith('<#', i):      # #12: a block comment is no command
            i = block_comment_end(command, i)
            current.append(' ')
            continue
        if quote is None and char == '#' and COMMENT_START(command, i, powershell):      # #12: a comment is no command
            end = command.find('\n', i)
            i = n if end < 0 else end
            continue
        if powershell and char == '`' and quote != "'" and i + 1 < n:      # #12: a PowerShell backtick escapes the next character: `'` and `"` are no quote marks
            current.append(command[i:i + 2]); i += 2
            continue
        if quote:
            current.append(char)
            if char == '\\' and quote == '"' and not powershell and i + 1 < len(command) and command[i + 1] in '"\\':
                current.append(command[i + 1]); i += 1
            elif char == quote: quote = None
        elif char in '"\'': quote = char; current.append(char)
        elif char in ';|&\n':
            parts.append(''.join(current)); current = []
            first = i
            while i + 1 < len(command) and command[i + 1] in '|&' and char in '|&': i += 1       # `&&` and `||` are one cut
            ops.append(command[first:i + 1]); cuts.append(i + 1)
        else: current.append(char)
        i += 1
    parts.append(''.join(current)); ops.append(''); cuts.append(n)
    if detail: return list(zip(parts, ops, cuts))
    return [p for p in parts if p.strip()]


# ---- #25: where each part of a command runs (cd), heredoc bodies, code given to an interpreter ----------------------------------------------
# Kept apart from shell_targets/all_targets (which read one piece of text) so the shell rules above stay as they were: shell_effects cuts the command
# into the pieces a shell runs one after the other, keeps the directory in force for each piece, and asks all_targets about the piece alone.

CODE_PATH = '$(interpreter code)'       # a write the code does to a path or with a mode that is not a literal: the hook cannot read where it goes
CD_NAMES = ('cd', 'chdir', 'pushd', 'set-location', 'sl', 'push-location')
POP_NAMES = ('popd', 'pop-location')
INTERPRETER = re.compile(r'(python[\d.]*|pythonw[\d.]*|py|node|nodejs|perl|ruby)(?:\.exe)?$', re.I)
KWARG = re.compile(r'^(\w+)\s*=(?!=)\s*(.*)$', re.S)
LITERAL = re.compile(r'''^[rRuUbB]{0,2}(?:'([^']*)'|"([^"]*)"|`([^`$]*)`)$''', re.S)    # a string with no f/format prefix and nothing computed


def cut_pieces(command):
    """[(piece, separator before, separator after)] of the command cut as shell_segments cuts it (outside quotes at `;` `&&` `||` `|` `&` and line ends); the
    separators tell a pipeline stage (a `cd` there does not carry over) from a step in sequence."""
    command = re.sub(r'\\\r?\n', '', command)
    raw, current, quote, i = [], [], None, 0
    while i < len(command):
        char = command[i]
        if quote:
            current.append(char)
            if char == '\\' and quote == '"' and i + 1 < len(command) and command[i + 1] in '"\\':
                current.append(command[i + 1]); i += 1
            elif char == quote: quote = None
        elif char in '"\'': quote = char; current.append(char)
        elif char in '|&' and ((current and current[-1] in '<>') or (char == '&' and command[i + 1:i + 2] == '>')):
            current.append(char)                      # part of a redirect (`>&`, `>|`, `&>`, `&>>`), not a cut
        elif char in ';|&\n':
            sep = char
            while i + 1 < len(command) and command[i + 1] in '|&' and char in '|&': i += 1; sep += command[i]
            raw.append((''.join(current), sep)); current = []
        else: current.append(char)
        i += 1
    raw.append((''.join(current), ''))
    pieces, before = [], ''
    for text, after in raw:
        if text.strip(): pieces.append((text, before, after)); before = after
        else: before += after
    return pieces


def heredoc_units(command, marked=False):
    """[(text, bodies)]: the command in chunks that end at a line holding here-documents, with their bodies (`<<WORD` to the line `WORD`) taken out of the text;
    `bodies` go to the interpreter scan. #25 merge with HOOK30 round 6: the same reading as without_heredocs (joined lines, strings, skips_body): a body its
    receiver may run is also a chunk of its own, judged as shell commands, and the `$(...)`/backticks of an unquoted text body too. A `<<` with no closing
    line is left as written. FIX25B (Codex F2): `marked` adds a third value, True for a body that runs as a script (a child shell: its `cd` does not reach the text after it)."""
    if '<<' not in command: return [(command, [], False)] if marked else [(command, [])]
    lines, units, chunk, i = command.split('\n'), [], [], 0
    while i < len(lines):
        start, logical, joined = i, lines[i], 0
        while i + 1 < len(lines):
            plain = logical.rstrip('\r')
            if (len(plain) - len(plain.rstrip('\\'))) % 2:
                logical = plain[:-1] + lines[i + 1]
            elif '<<' in logical and joined < 50 and scan_heredocs(logical, [])[1] is not None:
                logical += '\n' + lines[i + 1]; joined += 1
            else: break
            i += 1
        chunk += lines[start:i + 1]
        i += 1
        matches = list(HEREDOC.finditer(logical))
        if not matches: continue
        seen, _ = scan_heredocs(logical, [m.start() for m in matches])
        commands = ends = readers = None
        bodies, scripts = [], []
        for m in matches:
            word = m.group(2) or m.group(3) or m.group(4)
            end = next((n for n in range(i, len(lines)) if (lines[n].strip('\t\r') if m.group(1) else lines[n].rstrip('\r')) == word), None)
            if end is None: break
            if seen[m.start()][2] is not None: continue                        # inside a string: not a here-document
            if commands is None: commands = pipeline(logical); ends = [c[2] for c in commands]; readers = text_readers(commands)
            body = '\n'.join(lines[i:end])
            bodies.append(body)
            if not skips_body(logical, m, seen[m.start()], commands, ends, readers, lines, end): scripts.append(body)
            elif m.group(4) and '\\' not in m.group(0): scripts += substitutions(body)
            i = end + 1
        if bodies:
            units.append(('\n'.join(chunk), bodies, False))
            units += [(script, [], True) for script in scripts]
            chunk = []
    if chunk: units.append(('\n'.join(chunk), [], False))
    return units if marked else [unit[:2] for unit in units]


def is_absolute_text(path):
    return re.match(r'^(?:[A-Za-z]:|/|\\\\|~)', path.strip().strip('"\'')) is not None


def cd_target(words):
    """The folder a `cd`-like command (its words, the command first) names: '' for none (the home folder), '-' for the previous one, else the word."""
    rest, i = words[1:], 0
    while i < len(rest):
        word, low = rest[i], rest[i].lower()
        if low in ('-path', '-literalpath') and i + 1 < len(rest): return rest[i + 1]
        if re.match(r'-(?:path|literalpath):', low): return word.split(':', 1)[1]
        if low == '--': return rest[i + 1] if i + 1 < len(rest) else ''
        if low == '-stackname': i += 2; continue
        if low == '/d' or (word.startswith('-') and word != '-'): i += 1; continue
        return word
    return ''


def piped(separator):
    return separator in ('|', '|&')


def redirect_split(core, powershell=False):
    """#25 (review 2, P1-A/P2-B): (targets of the redirects in `core`, `core` with those targets blanked). The shell opens a redirect in its own folder, before the
    program runs, so a redirect target is judged against the directory in force; the other targets (the program's own arguments) against the program's folder."""
    text = hide_escapes(core, powershell)
    masked = masked_quotes(text, powershell)
    matches = [m for pattern in ((REDIRECT_PS, REDIRECT_MORE_PS) if powershell else (REDIRECT, REDIRECT_MORE)) for m in pattern.finditer(masked)]
    found, rest = [show_escapes(unquote(text[m.start(1):m.end(1)])) for m in matches], list(text)
    for m in matches: rest[m.start():m.end()] = ' ' * (m.end() - m.start())      # the operator goes too, or the next word would read as its target
    return [f for f in found if f], ''.join(rest)            # the escapes stay hidden: the caller reads the text again as one Bash text


GIT_ENV = ('GIT_WORK_TREE', 'GIT_DIR')
PS_ENV = re.compile(r'^\$env:(GIT_WORK_TREE|GIT_DIR)\s*=\s*(.+?)\s*$', re.I | re.S)


def git_exports(words, core, powershell):
    """#25 (review 2, P1-B): {name: raw value} of the GIT_WORK_TREE / GIT_DIR a piece sets for the pieces after it: `export NAME=value ...` (Bash) or
    `$env:NAME = 'value'` (PowerShell)."""
    if powershell:
        m = PS_ENV.match(core.strip())
        return {m.group(1).upper(): unquote(m.group(2))} if m else {}
    head, _ = command_head(list(words)) if words else ([], False)
    if not head or head[0] != 'export': return {}
    return {w.split('=', 1)[0]: w.split('=', 1)[1] for w in head[1:] if w.split('=', 1)[0] in GIT_ENV and '=' in w}


UNREADABLE = False       # a folder the hook cannot resolve (`git -C "$X"`): the program's own targets are unresolvable


def reach_places(words, here, exports=None, flags_own=True):
    """#25 (review P1-1): ([folders], folder or None) a command runs in besides the directory in force: `git -C DIR` (repeatable, each relative to the one before),
    `git --work-tree[=]DIR`, `git --git-dir[=]DIR` (the folder that holds that `.git`), and `env -C DIR` / `--chdir[=]DIR`. Only the command itself is read (after
    wrappers and assignments), so a word `git` in an argument is nothing. The second value is the folder of `env -C` (the command's own piece runs there)."""
    head, _ = command_head(list(words)) if words else ([], False)
    start, found, env_dir, current = len(words) - len(head), [], None, here

    def resolve(raw, base):
        if re.search(r'[$%`]', raw) or (base is None and not is_absolute_text(raw)): return None
        try:
            return normalize(raw, base or Path.cwd())
        except (OSError, ValueError):
            return None

    def program(word):
        name = os.path.basename(word.replace('\\', '/')).lower()
        return name[:-4] if name.endswith('.exe') else name

    for i in range(start + 1):
        if i >= len(words): break
        name = program(words[i])
        if name == 'env':
            j = i + 1
            while j < len(words) and words[j].startswith('-') and len(words[j]) > 1:
                word = words[j]
                value = word.split('=', 1)[1] if word.startswith('--chdir=') else words[j + 1] if word in ('-C', '--chdir') and j + 1 < len(words) else None
                if value is not None:
                    folder = resolve(value, current)
                    if folder is not None: found.append(folder); env_dir = current = folder
                j += 2 if word in ('-C', '--chdir', '-u', '-S') else 1
        elif name == 'git' and i == start:
            j, folder, tree, git_dir, moved = i + 1, current, None, None, False
            while j < len(words) and words[j].startswith('-'):
                word = words[j]
                if word == '-C' and j + 1 < len(words):
                    folder, moved = resolve(words[j + 1], folder), True
                    if folder is not None: found.append(folder)
                    j += 1
                elif word.split('=')[0] in ('--work-tree', '--git-dir'):
                    value = word.split('=', 1)[1] if '=' in word else words[j + 1] if j + 1 < len(words) else ''
                    where_ = resolve(value, folder) if value else None
                    if word.startswith('--git-dir'):
                        git_dir = value
                        if where_ is not None and where_.name.casefold() == '.git': where_ = where_.parent
                    else: tree = where_ if where_ is not None else UNREADABLE       # #25 (review 2): the program's own paths are relative to the work tree
                    if where_ is not None: found.append(where_)
                    j += 0 if '=' in word else 1
                elif word in GIT_VALUE: j += 1
                j += 1
            if not flags_own: tree, moved = None, False          # discard_verdict: git_verdict reads -C / --work-tree itself; only the variables are new
            assigned = dict(exports or {})                    # #25 (review 2, P1-B): GIT_WORK_TREE=DIR / GIT_DIR=X before git (or exported earlier) act as the flags
            for word in words[:start]:
                if '=' in word and word.split('=', 1)[0] in GIT_ENV: assigned[word.split('=', 1)[0]] = word.split('=', 1)[1]
            if tree is None and assigned.get('GIT_WORK_TREE'):
                where_ = resolve(assigned['GIT_WORK_TREE'], folder)
                tree = where_ if where_ is not None else UNREADABLE
                if where_ is not None: found.append(where_)
            if git_dir is None and assigned.get('GIT_DIR'):
                where_ = resolve(assigned['GIT_DIR'], folder)
                if where_ is not None and where_.name.casefold() == '.git': where_ = where_.parent
                if where_ is not None: found.append(where_)
            if tree is not None: env_dir = tree
            elif moved: env_dir = folder if folder is not None else UNREADABLE
    return found, env_dir


def shell_effects(command, base, powershell=False, depth=0):
    """(targets, places) of a shell command run in `base`. targets: [(raw path, directory in force or None when a `cd` could not be read)], every path the command
    appears to write with the directory its own piece runs in: `cd DIR` / `pushd` / `Set-Location` (quoted or not, absolute or relative to the directory in force)
    changes it for the pieces after it; a `cd` inside `( ... )` ends at the `)`, one in a pipeline stage or before `&` does not carry over. places: the folders a
    `cd` goes to (the command runs there, like the cwd). A heredoc body is not shell text; the code an interpreter is given is read for file writes (code_writes)."""
    targets, places = [], []
    here, scopes, stack, previous, exports = (Path(base) if base is not None else None), [], [], '', {}
    launch = [here]                                     # FIX25B (Codex F2): the folders in force in the chunk a heredoc body was launched from
    for text, bodies, script in heredoc_units(command, True):
        if script:
            # a body that runs as a script is a child shell: it starts in the folders in force when the segment holding its `<<` starts (FIX25C, Codex R1:
            # `pushd A && bash <<EOF && popd` in A, `bash <<EOF && cd src` where the command was) and its `cd` does not reach the text after it
            for folder in launch:
                more, there = shell_effects(text, folder, powershell, depth + 1)
                targets += more
                places += there
            continue
        spans, steps, launch = chunk_folders(text, here, powershell)      # FIX25C (Codex R1): where each `$( )` and each here-document body of the chunk starts
        bodies = list(bodies)
        for piece, before, after in cut_pieces(text):
            stripped = piece.strip()
            opens = len(stripped) - len(stripped.lstrip('('))
            core = stripped[opens:].strip()
            masked = masked_quotes(core)
            run = len(core) - len(core.rstrip(')'))
            closes = max(0, min(masked.count(')') - masked.count('('), run))
            core = core[:len(core) - closes]
            scopes += [here] * opens
            words = [show_escapes(unquote(w)) for w in (WORDS if powershell else BASH_WORDS).findall(hide_escapes(core, powershell))]
            head, _ = command_head(list(words)) if words else ([], False)
            reached = reach_places(words, here, exports)        # #25 (review P1-1): `git -C DIR`, `--work-tree`, `--git-dir`, `env -C DIR` run in DIR
            places += reached[0]
            piece_here = here if reached[1] is None else None if reached[1] is UNREADABLE else reached[1]
            exports.update(git_exports(words, core, powershell))
            name = os.path.basename(head[0].replace('\\', '/')).lower() if head else ''
            name = name[:-4] if name.endswith('.exe') else name
            mine = [bodies.pop(0) for _ in range(min(len(HEREDOC.findall(core)), len(bodies)))]
            carries = after != '&' if powershell else not piped(before) and not piped(after) and after != '&'      # FIX25D: a PowerShell pipeline runs in the session
            if name in CD_NAMES:
                target = cd_target(head)
                new = None
                try:
                    if target == '': new = Path.home()
                    elif target != '-' and not re.search(r'[$%`]', target) and (here is not None or is_absolute_text(target)): new = normalize(target, here or Path.cwd())
                except (OSError, ValueError):
                    new = None
                if new is not None: places.append(new)
                if name in ('pushd', 'push-location') and carries: stack.append(here)
                if carries: here = new
            elif name in POP_NAMES:
                if carries: here = stack.pop() if stack else None
            else:
                redirects, arguments = redirect_split(core, powershell)       # #25 (review 2): a redirect is opened by the shell (here), the program's arguments live in its own folder
                targets += [(raw, here) for raw in redirects]
                targets += [(raw, piece_here) for raw in all_targets(arguments, 3, powershell)]      # depth 3: the strings after an interpreter are read below, with the directory in force
                kind = interpreter_kind(name)
                if kind: targets += [(raw, piece_here) for raw in code_writes(kind, '\n'.join([core, *mine] + ([previous] if piped(before) else [])))]
                if depth < 3:
                    for form in dict.fromkeys((core, re.sub(r'[`^]', '', core))):
                        for start, inner_text in nested_strings(form, powershell):
                            cue = CUE.findall(re.split(r'[;&|\n]', form[:start])[-1])
                            if not cue: continue
                            word = cue[-1].lower()
                            inner = True if word.startswith(('powershell', 'pwsh')) else False if word.startswith(('bash', 'sh', 'zsh', 'dash', 'wsl', 'cmd')) else powershell
                            more, there = shell_effects(inner_text, piece_here, inner, depth + 1)
                            targets += more
                            places += there
            if powershell and name not in CD_NAMES and name not in POP_NAMES and carries: here = ps_after(core, here)      # FIX25D (Codex C1): `$x = $(Set-Location ..)`
            previous = '\n'.join([core, *mine])
            for _ in range(closes): here = scopes.pop() if scopes else here
        # FIX25B/FIX25C (Codex F2, R1): the commands inside `$( )` and backticks are read as shell too, each in the folders in force when its segment starts
        # (`x=$(cd A && git checkout -- f)` in A, `x=$(echo > f); cd src` where the command was)
        if depth < 3 and not powershell:
            every = launch + [f for _, _, many in steps for f in many if f not in launch]
            for start, _, inner in spans:
                for folder in next((many for begin, end, many in steps if begin <= start < end), every):
                    more, there = shell_effects(inner, folder, powershell, depth + 1)
                    targets += more
                    places += there
    return list(dict.fromkeys(targets)), places


def interpreter_kind(name):
    m = INTERPRETER.match(name)
    if not m: return None
    word = m.group(1).lower()
    return 'python' if word.startswith(('py', 'python')) else 'node' if word.startswith('node') else word


def call_args(text, start):
    """The arguments (as text) of the call whose `(` is just before text[start]: cut at the commas outside brackets and strings, up to the closing `)`."""
    args, depth, quote, current, i = [], 0, None, [], start
    while i < len(text):
        char = text[i]
        if quote:
            current.append(char)
            if char == '\\' and i + 1 < len(text): current.append(text[i + 1]); i += 1
            elif char == quote: quote = None
        elif char in '"\'`': quote = char; current.append(char)
        elif char in '([{': depth += 1; current.append(char)
        elif char in ')]}':
            if depth == 0: break
            depth -= 1; current.append(char)
        elif char == ',' and depth == 0: args.append(''.join(current).strip()); current = []
        else: current.append(char)
        i += 1
    args.append(''.join(current).strip())
    return [a for a in args if a], i + 1


def args_at(text, end):
    """The arguments of a call whose name ends at text[end], with or without brackets (Perl, Ruby): `unlink 'a', 'b';` reads up to the `;` or the line end."""
    rest = text[end:]
    if rest.lstrip().startswith('('): return call_args(text, end + len(rest) - len(rest.lstrip()) + 1)[0]
    return call_args(re.split(r'[;\n]', rest, 1)[0] + ')', 0)[0]


def literal(arg):
    """The text of a string literal, else None (an f-string, a name, a sum of strings, a call)."""
    m = LITERAL.match((arg or '').strip())
    return next((g for g in m.groups() if g is not None), None) if m else None


def path_of(arg):
    value = literal(arg)
    return value if value else CODE_PATH


def writes_mode(mode):
    """True for a mode that writes, False for one that only reads, None for a mode that is not a literal."""
    value = literal(mode)
    return None if value is None else bool(set('wax+') & set(value))


def split_kwargs(args):
    positional = [a for a in args if not KWARG.match(a)]
    return positional, {m.group(1): m.group(2) for m in map(KWARG.match, args) if m}


def code_writes(kind, text):
    """The paths the code (python, node, perl or ruby) in `text` writes: the literal ones as written, CODE_PATH for a write whose path or mode is not a literal.
    Reads are not writes. Code that is not a literal is not run, only read: a heuristic, as every other rule of this hook."""
    text = text.replace('\\"', '"').replace("\\'", "'")        # the code sat in a shell string: its own quotes were escaped
    found = []
    if kind == 'python':
        for m in re.finditer(r'(?<![\w.])(?:(?:io|codecs|builtins)\.)?open\s*\(', text):
            positional, named = split_kwargs(call_args(text, m.end())[0])
            path, mode = named.get('file', positional[0] if positional else None), named.get('mode', positional[1] if len(positional) > 1 else None)
            if mode is None: continue                                  # open(path): a read
            wrote = writes_mode(mode)
            if wrote is None: found.append(CODE_PATH)
            elif wrote: found.append(path_of(path))
        covered = set()
        for m in re.finditer(r'(?<![\w.])(?:pathlib\.)?Path\s*\(', text):
            args, end = call_args(text, m.end())
            rest = text[end:]
            method = re.match(r'\s*\.\s*(write_text|write_bytes|touch|unlink|rmdir|mkdir|rename|replace|symlink_to|hardlink_to|open)\s*\(', rest)
            line = rest.split('\n', 1)[0]
            if method:
                covered.add(end + method.start(1))
                margs = call_args(rest, method.end())[0]
                if method.group(1) == 'open':
                    positional, named = split_kwargs(margs)
                    wrote = writes_mode(named.get('mode', positional[0] if positional else "'r'"))
                    if wrote is not False: found.append(path_of(args[0]) if len(args) == 1 and wrote else CODE_PATH)
                    continue
                found.append(path_of(args[0]) if len(args) == 1 else CODE_PATH)
                if method.group(1) in ('rename', 'replace', 'symlink_to', 'hardlink_to') and margs: found.append(path_of(margs[0]))
            elif re.match(r'\s*(?:/|\.\s*(?:parent|parents|joinpath|with_name|with_suffix|with_stem|resolve|expanduser|absolute|home)\b)', rest) \
                    and re.search(r'\.\s*(?:write_text|write_bytes|touch|unlink|rmdir|mkdir|rename|replace)\s*\(', line):
                found.append(CODE_PATH)
        for m in re.finditer(r'\.\s*(write_text|write_bytes)\s*\(', text):
            if m.start(1) not in covered: found.append(CODE_PATH)       # a variable that holds a Path: where it points is not in the text
        for m in re.finditer(r'(?<![\w.])(shutil|os)\.(\w+)\s*\(', text):
            module, name = m.group(1), m.group(2)
            args = call_args(text, m.end())[0]
            if module == 'shutil' and name in ('copy', 'copy2', 'copyfile', 'copytree'): wanted = args[1:2] or ['?']
            elif (module, name) in (('shutil', 'move'), ('os', 'rename'), ('os', 'renames'), ('os', 'replace')): wanted = args[:2] or ['?']
            elif module == 'os' and name in ('symlink', 'link'): wanted = args[1:2] or ['?']
            elif (module, name) == ('shutil', 'rmtree') or (module == 'os' and name in ('remove', 'unlink', 'rmdir', 'removedirs', 'makedirs', 'mkdir', 'truncate')): wanted = args[:1] or ['?']
            else: continue
            found += [path_of(a) for a in wanted]
    elif kind == 'node':
        for m in re.finditer(r'\.\s*(writeFile\w*|appendFile\w*|rm\w*|unlink\w*|rename\w*|copyFile\w*|mkdir\w*|cp(?:Sync)?|createWriteStream)\s*\(', text):
            args = call_args(text, m.end())[0]
            both = m.group(1).startswith(('rename', 'copyFile', 'cp'))
            found += [path_of(a) for a in (args[:2] if both else args[:1]) or ['?']]
    elif kind == 'perl':
        for m in re.finditer(r'(?<![\w$@%>])open\s*\(?\s*(?:my\s+)?[$\w]+\s*,\s*', text):
            rest = text[m.end():]
            spec = re.match(r'''(['"])([^'"]*)\1''', rest)
            if not spec: found.append(CODE_PATH); continue
            mode = re.match(r'\s*(\+?>>?|\+<)', spec.group(2))
            if not mode: continue                                      # '<' and the pipe forms: a read
            more = rest[spec.end():]
            if re.match(r'\s*,', more):                                # three arguments: the file is the third
                third = re.match(r'''\s*,\s*(['"])([^'"$@]*)\1''', more)
                found.append(third.group(2) if third and third.group(2) else CODE_PATH)
            else:
                tail = spec.group(2)[mode.end():].strip()
                found.append(tail or CODE_PATH)                        # two arguments: ">file"
        for m in re.finditer(r'(?<![\w$@%>])(unlink|rename)\b', text):
            found += [path_of(a) for a in args_at(text, m.end()) or ['?']]
    elif kind == 'ruby':
        for m in re.finditer(r'\b(File|IO|FileUtils)\.(\w+)', text):
            owner, name = m.groups()
            args = args_at(text, m.end())
            if owner == 'FileUtils':
                if name in ('pwd', 'cd', 'chdir', 'compare_file', 'identical?', 'uptodate?', 'cmp', 'compare_stream'): continue
                wanted = args[-1:] if name in ('cp', 'copy', 'cp_r', 'copy_file', 'install', 'ln', 'ln_s', 'link', 'symlink') else args if name in ('mv', 'move') else args[:1]
                found += [path_of(a) for a in wanted or ['?']]
            elif name in ('write', 'binwrite', 'truncate') or (owner == 'File' and name in ('delete', 'unlink')):
                found += [path_of(a) for a in (args if name in ('delete', 'unlink') else args[:1]) or ['?']]
            elif owner == 'File' and name == 'rename': found += [path_of(a) for a in args[:2] or ['?']]
            elif owner == 'File' and name == 'open' and len(args) > 1:
                wrote = writes_mode(args[1])
                if wrote is None or wrote: found.append(path_of(args[0]) if wrote else CODE_PATH)
    return list(dict.fromkeys(found))


def repo_of(path):
    """The repository root that holds `path` (the nearest folder with a .git at or above its existing folder), or None."""
    folder = _nearest_dir(Path(path).parent)
    try:
        return where.git_root(folder) if folder is not None else None
    except OSError:
        return None


def inside_repo(plan_root, target):
    """Is `target` in the repository the plan's root belongs to? A nested repository (a worktree, a clone) inside the root is another repository."""
    try:
        mine = where.git_root(plan_root)
    except OSError:
        mine = None
    theirs = repo_of(target)
    if mine is None or theirs is None: return relative(target, plan_root) is not None
    return os.path.normcase(str(mine)) == os.path.normcase(str(theirs))


NAME_CHAR = r'[\w.-]'             # a character that can be part of a file name: a protected name next to one is another name
SCRATCH_START = re.compile(r'(?<![\w.-])\.onecrew/')                           # where a path goes into .onecrew/ (folded: separators are /)
SCRATCH_WORD_END = re.compile(r'[\s"\'`;|&<>()]')                              # where a shell word ends
SCRATCH_TEXT_END = re.compile(r'["\'`]')                                       # where a string literal (or a command substitution) ends


def mentions(flat, item, how):
    """Does the (folded) command text mention the protected `item`? how '' : anywhere in the text. 'whole': as a whole path component (`.onecrew`, not the
    end of `11.OneCrew`): not preceded by a character of a file name, and NOT followed, after any dots, by one (a letter, digit, `_` or `-`): whatever else
    follows (a separator, a quote, a space, the end, but also `{,.bak}`, `*`, `,`, `(`, `:` as in `.onecrew::$INDEX_ALLOCATION`) leaves the name `.onecrew`,
    because a glob or a brace or a stream suffix still reaches the folder, and Windows drops trailing dots (`.onecrew.` and `.onecrew..` are `.onecrew`),
    while `.onecrew.bak` and `.onecrew-old` are other names. 'start': as the start of a path component (`onecrew/plans`, not `11.OneCrew/plans`)."""
    if not how: return item in flat
    pattern = f'(?<!{NAME_CHAR})' + re.escape(item) + (r'(?!\.*[\w-])' if how == 'whole' else '')
    return re.search(pattern, flat) is not None


def scratch_component(part):
    """One component of a path as Windows reads it: trailing spaces and dots are dropped, a component of only dots is `.` or `..`, one of only spaces is
    nothing (so `scratch /..` and `scratch./..` leave `scratch`). Kept on every system: it can only make a path look less like scratch, never more."""
    bare = part.rstrip()
    if bare and not bare.strip('.'): return '.' if len(bare) == 1 else '..'
    return part.rstrip(' .\t\r\n\x0b\x0c')


def stays_in_scratch(text):
    """Does a path that starts with `.onecrew/` stay under `.onecrew/scratch/`, component by component, once Windows' reading of each component is applied and
    `..` is folded away as posixpath.normpath does it (`.onecrew/scratch/../config.json`, `.onecrew/scratch/a/../../x`, `.onecrew/scratchy/..` do not)?"""
    normal = posixpath.normpath('/'.join(scratch_component(part) for part in text.split('/')))
    return normal == '.onecrew/scratch' or normal.startswith('.onecrew/scratch/')


def without_scratch(flat):
    """One (folded) text without the paths that stay under `.onecrew/scratch/`, the one place of `.onecrew/` the AI may write. A path is cut out only when it
    stays in scratch read BOTH as the shell word (up to a space, a paren, `;`, `&`, `|`, `<`, `>`, a quote) and as the longest string it could be, to the next quote or
    backtick or the end of the text, up to the next word that starts with `.onecrew/` (a path in a string may hold spaces, parens and `;`, so
    `'.onecrew/scratch /..'` and `'.onecrew/scratch/a(/../../config.json'` leave scratch); only the word is cut, so another protected name after it
    stays in the text."""
    kept, position = [], 0
    for match in SCRATCH_START.finditer(flat):
        if match.start() < position: continue                     # inside a word that was already cut
        start = match.start()
        word = SCRATCH_WORD_END.search(flat, start)
        word_end = word.start() if word else len(flat)
        text = SCRATCH_TEXT_END.search(flat, start)
        text_end = text.start() if text else len(flat)
        for later in SCRATCH_START.finditer(flat, word_end):      # another path that starts after a space is its own
            if later.start() >= text_end: break
            if flat[later.start() - 1:later.start()].isspace(): text_end = later.start(); break
        if stays_in_scratch(flat[start:word_end]) and stays_in_scratch(flat[start:text_end]):
            kept.append(flat[position:start]); position = word_end
    kept.append(flat[position:])
    return ''.join(kept)


# ---- #12: commands that throw away work nobody committed --------------------------------------------------------------------------------
# These are read from the text, in the hook, and not as DEFAULT_BASH_DENY entries: an active plan exported by an older version carries the old list.
SAFE_WAY = ' Safe ways: work in a separate `git worktree add <folder> <branch>`, or copy the file into `.onecrew/scratch/` and change the copy there.'
TOKEN = WORDS
SUBSTITUTION = re.compile(r'\$\(|`|<\(|>\(')            # #12: a command inside a command: the segment is not read-only whatever its first word is
INNER = re.compile(r'[$<>]\(([^()]*)\)|`([^`]*)`')
# #12: words that run the next command: shell keywords, and wrappers with the flags (and the flag values) they take before it
KEYWORDS = ('if', 'then', 'else', 'elif', 'do', 'while', 'until', '!', 'time')
WRAPPERS = {'sudo': ('-u', '-g', '-h', '-p', '-C', '-D', '-R', '-T', '-U'), 'env': ('-u', '-C', '-S'), 'command': (), 'time': (), 'nohup': (), 'exec': (),
            'nice': ('-n',), 'ionice': ('-c', '-n', '-p'), 'timeout': ('-s', '-k'), 'setsid': (), 'stdbuf': ('-i', '-o', '-e'),
            'xargs': ('-n', '-I', '-L', '-P', '-d', '-E', '-s', '-a')}
SHELL_WORDS = {'bash': (), 'sh': (), 'zsh': (), 'dash': (), 'ksh': (), 'cmd': (), 'powershell': ('-executionpolicy', '-ep', '-workingdirectory', '-wd'),
               'pwsh': ('-executionpolicy', '-ep', '-workingdirectory', '-wd'), 'wsl': ('-d', '-u', '--distribution', '--user', '--cd')}
HEREDOC = re.compile(r'(?<!<)<<(?!<)(-?)[ \t]*(?:"([^"\n]+)"|\'([^\'\n]+)\'|\\?([\w.-]+))')
# #12: the commands known to read a here-document as text; any other receiver keeps the body judged
TEXT_READERS = {'cat', 'tee', 'sed', 'grep', 'egrep', 'fgrep', 'awk', 'gawk', 'wc', 'sort', 'uniq', 'head', 'tail', 'cut', 'tr', 'diff', 'patch', 'jq', 'echo', 'printf',
                'base64', 'less', 'more', 'fold', 'nl', 'xxd', 'od', 'iconv', 'python', 'python3', 'py', 'node', 'ruby', 'perl', 'php'}
GIT_TEXT = {'commit', 'apply', 'am', 'tag', 'notes', 'hash-object', 'fast-import'}
GIT_VALUE = ('-c', '--git-dir', '--work-tree', '--namespace', '--super-prefix', '--config-env', '--exec-path')


HERE_STRING = re.compile(r'@(["\'])[ \t]*\r?\n(.*?)\r?\n[ \t]*\1@', re.S)


def command_texts(command, depth=0, powershell=False):
    """The command and, up to 3 levels, the commands inside it: `$(...)`, backticks, `<(...)`, and a string that follows an interpreter (as all_targets).
    #12: a PowerShell here-string `@'...'@` whose line (or the line it ends on) holds `Invoke-Expression`, `iex` or another interpreter is a command text too."""
    texts = [command]
    if depth >= 3: return texts
    for m in INNER.finditer(command): texts += command_texts(m.group(1) or m.group(2) or '', depth + 1, powershell)
    for m in QUOTED.finditer(command):
        if CUE.findall(re.split(r'[;&|\n]', command[:m.start()])[-1]): texts += command_texts(m.group(1) or m.group(2), depth + 1, powershell)
    if '\\"' in command:                                 # #25 (review P2-5): a Bash string with `\"` inside is read to its real end and unescaped
        for start, inner in nested_strings(command):
            if inner not in texts and CUE.findall(re.split(r'[;&|\n]', command[:start])[-1]): texts += command_texts(inner, depth + 1)
    if powershell:
        for m in HERE_STRING.finditer(command):
            first = command[:m.start()].rsplit('\n', 1)[-1]
            last = command[m.end():].split('\n', 1)[0]
            if CUE.search(first) or CUE.search(last): texts += command_texts(m.group(2), depth + 1, True)
    return texts


def segment_reads_text(words):
    """True when the command of these words is a known text reader, False when it is not, None when there is no command (only assignments)."""
    while words and re.match(r'^\w+=', words[0]): words = words[1:]
    if not words: return None
    head = os.path.basename(unquote(words[0]).replace('\\', '/')).lower()
    head = head[:-4] if head.endswith('.exe') else head
    if head == 'git':
        rest, skip = [], False                                               # #12: the values of `-C <dir>` and `-c k=v` are not the sub-command
        for w in words[1:]:
            if skip: skip = False
            elif w in GIT_VALUE or w == '-C': skip = True
            elif not w.startswith('-'): rest.append(w)
        return bool(rest) and rest[0].lower() in GIT_TEXT
    if head == 'gh':                                                         # #12: `gh pr create --body "$(cat <<'EOF'...)"`: the body is text
        sub = []
        for w in words[1:]:
            if w.startswith('-'): break
            sub.append(w.lower())
        return sub[:2] in (['pr', 'create'], ['pr', 'edit'], ['pr', 'comment'], ['issue', 'create'], ['issue', 'comment'])
    if head == 'printf' and any(w == '-v' or (w.startswith('-v') and not w.startswith('--')) for w in words[1:]): return False      # #12: `printf -v x` keeps the output in a variable
    return head in TEXT_READERS


def scan_heredocs(line, starts):
    """One left-to-right pass over a (logical) line: for each index in `starts` (where a `<<` begins) the state there, as (open groups, the innermost group, the
    quote open there): a group is (kind `$(` `<(` `>(` `(` or a backtick, where it opens, the quote that was open outside it); a quote inside a group starts anew, a `)`
    inside a quote closes nothing, and a comment hides its text. Also returns the quote still open at the end of the line. #12"""
    stack, quote, k, n, si, seen = [], None, 0, len(line), 0, {}
    while k < n:
        while si < len(starts) and starts[si] <= k:
            seen[starts[si]] = (len(stack), stack[-1] if stack else None, quote); si += 1
        c = line[k]
        if c == '\\' and quote != "'":
            k += 2
            continue
        if quote == "'":
            if c == "'": quote = None
        elif c == '#' and quote is None and COMMENT_START(line, k):
            end = line.find('\n', k)
            k = n if end < 0 else end
            continue
        elif c == "'" and quote is None: quote = "'"
        elif c == '"': quote = None if quote == '"' else '"'
        elif c == '`':
            if stack and stack[-1][0] == '`': quote = stack.pop()[2]
            else: stack.append(('`', k, quote)); quote = None
        elif c in '$<>' and line[k + 1:k + 2] == '(' and (c == '$' or quote is None):
            stack.append((c + '(', k, quote)); quote = None
            k += 2
            continue
        elif c == '(' and quote is None:
            stack.append(('(', k, quote))
        elif c == ')' and quote is None and stack and stack[-1][0] != '`': quote = stack.pop()[2]
        k += 1
    while si < len(starts):
        seen[starts[si]] = (len(stack), stack[-1] if stack else None, quote); si += 1
    return seen, quote


def pipeline(logical):
    """The (logical) line cut into commands: [(text, operator that ends it, index where that operator ends)]; `2>&1`, `>&2` and `&>` stay in their command."""
    merged = []
    for text, op, end in shell_segments(logical, False, True):
        if merged and merged[-1][1] == '&' and (merged[-1][0].rstrip().endswith(('>', '<')) or text.lstrip().startswith('>')):
            merged[-1] = (merged[-1][0] + '&' + text, op, end)
        else: merged.append((text, op, end))
    return merged


def text_readers(commands):
    """For each command of a pipeline: does it, and every command after it joined by a pipe, read its input as text? (A command after `;`, `&&`, `||` or `&`
    gets no input from the here-document.) An empty command after a pipe (`cat <<EOF |` and the next line) is not known. #12"""
    ok = [False] * len(commands)
    for k in range(len(commands) - 1, -1, -1):
        text, op, _ = commands[k]
        mine = segment_reads_text(without_redirects(TOKEN.findall(HEREDOC.sub(' ', text)))) is True
        if op in ('|', '|&'):
            ok[k] = mine and k + 1 < len(commands) and bool(commands[k + 1][0].strip()) and ok[k + 1]
        else: ok[k] = mine
    return ok


def closes_safely(lines, end):
    """The line after the delimiter closes a `$(` group: `)` and an optional quote, then (the line joined with its backslash-newline continuations) nothing, redirects to
    plain files, `;`, `&&` or `||` and a command; a pipe hands the output on, so it is safe only into commands that all read text; `>(`, `<(` or anything else is not. #12"""
    if end + 1 >= len(lines): return False
    k = end + 1
    line = lines[k].rstrip('\r')
    while (len(line) - len(line.rstrip('\\'))) % 2 and k + 1 < len(lines):
        k += 1
        line = line[:-1] + lines[k].rstrip('\r')
    close = re.match(r'^[ \t]*\)"?(.*)$', line, re.S)
    if close is None: return False
    rest = close.group(1)
    while True:                                                            # redirects to plain file names (or a descriptor copy)
        redirect = re.match(r'[ \t]*(?:\d?>&\d+|(?:\d?>>?|&>>?|>\|)[ \t]*[^\s;|&<>()$`\'"\\]+)', rest)
        if redirect is None: break
        rest = rest[redirect.end():]
    rest = rest.strip()
    if not rest or rest.startswith((';', '&&', '||')): return True
    if rest[0] == '|' and '<(' not in rest and '>(' not in rest:
        commands = pipeline(' ' + rest.lstrip('|&'))
        return bool(commands) and text_readers(commands)[0]
    return False


def skips_body(logical, m, info, commands, ends, readers, lines, end):
    """Is the body of this here-document text (so it is not judged as commands)? Only two shapes are known to be safe; in every other shape the body stays judged. #12
    (a) at the outermost level, no quote open: its command and every command that the output is piped to read text.
    (b) the only group on the line is one `$(` (no backtick, `(`, `{`, `<(`, `>(`, `)` elsewhere): the receiver in it reads text and nothing follows the mark; the `$(`
        is an argument of a text reader (or of `git commit`), not an assignment or the first word; the line that closes it is `)`, with no pipe after it."""
    depth, top, quote = info
    if '<(' in logical or '>(' in logical: return False
    where = bisect.bisect_right(ends, m.start())
    if depth == 0:
        return quote is None and where < len(commands) and readers[where]
    if depth != 1 or top[0] != '$(' or quote is not None or top[2] not in (None, '"'): return False
    if logical.count('(') != 1 or logical.count(')') or '`' in logical or '{' in logical or logical[m.end():].strip(): return False
    inside = logical[top[1] + 2:m.start()]
    if re.search(r'[\'"`();|&{}\\<>]', inside) or segment_reads_text(TOKEN.findall(inside)) is not True: return False
    owner = bisect.bisect_right(ends, top[1])
    before = logical[(commands[owner - 1][2] if owner else 0):top[1]]
    words = TOKEN.findall(before)
    if before and not before[-1].isspace() and words:
        if re.match(r'^\w+=', words.pop()): return False                       # `x=$(...)`: the output is kept for a later eval
    if not words or segment_reads_text(without_redirects(words)) is not True: return False      # the first word of a command runs its output
    return closes_safely(lines, end)


def substitutions(text):
    """The commands inside the `$(...)` (parentheses balanced, quotes ignored) and backticks of a text, nested ones too; `\\$(` is text. #12"""
    found, k, n = [], 0, len(text)
    while k < n and len(found) < 200:
        if text[k] == '\\':
            k += 2
            continue
        if text.startswith('$(', k):
            depth, j = 1, k + 2
            while j < n and depth:
                depth += (text[j] == '(') - (text[j] == ')')
                j += 1
            found.append(text[k + 2:j - 1 if depth == 0 else n])
            k += 2
            continue
        if text[k] == '`':
            j = text.find('`', k + 1)
            found.append(text[k + 1:n if j < 0 else j])
            k = n if j < 0 else j + 1
            continue
        k += 1
    return found


def substitution_spans(text, powershell=False):
    r"""FIX25C (Codex R1): [(start, end, command)] of the top-level `$(...)` (parentheses balanced, quotes ignored) and, in bash, backtick commands of a text;
    `\$(` in bash and `` `$( `` in PowerShell are text. Nested ones are inside `command`, read when it is read."""
    spans, k, n = [], 0, len(text)
    while k < n and len(spans) < 200:
        if text[k] == ('`' if powershell else '\\'):
            k += 2
        elif text.startswith('$(', k):
            depth, j = 1, k + 2
            while j < n and depth:
                depth += (text[j] == '(') - (text[j] == ')')
                j += 1
            spans.append((k, j, text[k + 2:j - 1 if depth == 0 else n]))
            k = j
        elif text[k] == '`' and not powershell:
            j = text.find('`', k + 1)
            end = n if j < 0 else j + 1
            spans.append((k, end, text[k + 1:n if j < 0 else j]))
            k = end
        else:
            k += 1
    return spans


def hollow(text, spans):
    """FIX25B/FIX25C (Codex F2, R1): the text with each span blanked to a variable of the same length (`$____`): the commands inside `$( )` run in a child shell and
    are read on their own, with their own `cd`; the offsets stay, so each one is matched to the segment that runs it."""
    out, last = [], 0
    for start, end, _ in spans:
        out += [text[last:start], '$' + '_' * (end - start - 1)]
        last = end
    return ''.join(out) + text[last:]


def without_heredocs(command, powershell=False):
    """(the command without the bodies of its here-documents (`<<WORD` to the line `WORD`), the bodies that must still be judged). A body is text, not commands, only in
    the shapes skips_body knows; in any other shape it is a script, judged on its own (it is also kept out of the text, so a quote in it cannot hide the next command). A
    line is joined with its backslash-newline continuations and with the next lines while a quote is open at its end (the body starts after the whole command). The body
    of an unquoted `<<WORD` still runs `$(...)` and backticks: those commands are judged. A `<<` without a closing line is left as written. PowerShell has no
    here-document with `<<`."""
    if powershell or '<<' not in command: return command, []
    lines, out, extras, i = command.split('\n'), [], [], 0
    while i < len(lines):
        start, logical, joined = i, lines[i], 0
        while i + 1 < len(lines):
            plain = logical.rstrip('\r')
            if (len(plain) - len(plain.rstrip('\\'))) % 2:
                logical = plain[:-1] + lines[i + 1]
            elif '<<' in logical and joined < 50 and scan_heredocs(logical, [])[1] is not None:
                logical += '\n' + lines[i + 1]; joined += 1
            else: break
            i += 1
        out += lines[start:i + 1]
        i += 1
        matches = list(HEREDOC.finditer(logical))
        if not matches: continue
        seen, _ = scan_heredocs(logical, [m.start() for m in matches])
        commands = ends = readers = None
        for m in matches:
            word = m.group(2) or m.group(3) or m.group(4)
            end = next((n for n in range(i, len(lines)) if (lines[n].strip('\t\r') if m.group(1) else lines[n].rstrip('\r')) == word), None)
            if end is None: break
            if seen[m.start()][2] is not None: continue                        # inside a string: not a here-document
            if commands is None: commands = pipeline(logical); ends = [c[2] for c in commands]; readers = text_readers(commands)
            body = '\n'.join(lines[i:end])
            if not skips_body(logical, m, seen[m.start()], commands, ends, readers, lines, end): extras.append(body)
            elif m.group(4) and '\\' not in m.group(0): extras += substitutions(body)
            i = end + 1
    return '\n'.join(out), extras


REDIRECT_WORD = re.compile(r'^(?:\d+|\*)?(?:>>?|>&|<>?|&>>?|>\|)(.*)$', re.S)


def without_redirects(words):
    """The words without the redirects (`2>&1`, `>/dev/null`, `> file`, `*> $null`, `2>$null`): they are not git paths. The target is judged as a write elsewhere. #12"""
    out, skip = [], False
    for word in words:
        if skip: skip = False; continue
        m = REDIRECT_WORD.match(word) if word[:1] not in '"\'' else None
        if m is None: out.append(word)
        elif not m.group(1): skip = True
    return out


def valid_ref_name(name):
    """git's rules for a branch name, enough to tell it from a path: no `:`, backslash, `..`, space or control or `~^?*[` character, no component that is empty or
    starts with `.`, none ending in `.lock`, and no end in `/` or `.`."""
    if not name or name.endswith(('/', '.')) or re.search(r'[:\\\s~^?*\[\x00-\x1f\x7f]|\.\.|@\{', name) or name == '@': return False
    return all(part and not part.startswith('.') and not part.endswith('.lock') for part in name.split('/'))


def local_branch(folder, name):
    """Is `name` a local branch of the repository that holds `folder`? Read from `.git/refs/heads` and `packed-refs` as files (a worktree's `.git` file points at its
    gitdir, whose `commondir` holds the refs); no subprocess. #12: the name is compared as written (`./x`, `x/`, `x/.` and an absolute path are no branch names)."""
    if name.startswith('-') or not valid_ref_name(name): return False
    try:
        gitdir = None
        for directory in (folder, *folder.parents):
            dot = directory / '.git'
            if dot.is_dir(): gitdir = dot; break
            if dot.is_file():
                m = re.match(r'gitdir:\s*(.+)', dot.read_text(encoding='utf-8', errors='replace').strip())
                if m: gitdir = Path(os.path.join(directory, m.group(1).strip()))
                break
        if gitdir is None: return False
        common = gitdir
        if (gitdir / 'commondir').is_file(): common = Path(os.path.join(gitdir, (gitdir / 'commondir').read_text(encoding='utf-8', errors='replace').strip()))
        heads = os.path.join(common, 'refs', 'heads')
        ref = os.path.join(heads, *name.split('/'))
        if os.path.commonpath([os.path.abspath(heads), os.path.abspath(ref)]) == os.path.abspath(heads) and os.path.isfile(ref): return True
        packed = common / 'packed-refs'
        return packed.is_file() and any(line.strip().endswith(' refs/heads/' + name) for line in packed.read_text(encoding='utf-8', errors='replace').splitlines())
    except (OSError, ValueError):
        return False


def path_word(word, here):
    """#12: is the one word after `git checkout` a path (a pathspec), not a revision? A glob (`*.txt`, `o*`, `[o]ther.txt`), pathspec magic (`:/x`, `:(top)x`, `:!x`), `./x`,
    `../x`, `~/x`, `~+/x`, `~-/x`, or something that exists. A revision such as `HEAD~1`, `main^` or `@{-1}` is none of these."""
    return bool(re.search(r'[*?\[]', word)) or word.startswith((':', './', '../', '~+', '~-', '~/')) or normalize(word, here).exists()


def glob_names(word, here):
    """The paths a git path word stands for. Only an unquoted Bash word (`expand`) is expanded against the files on disk, as bash does before git runs (`src/*.txt` is
    `src/a.txt`). Any other glob (quoted, PowerShell, or matching no file) is a git pathspec, in which `*` matches `/` and dot files too: it covers the whole fixed folder
    before the first glob character (`src/` for `src/*.txt`, the repository root for `*.txt`). #12"""
    if here is None or word.startswith(':') or not re.search(r'[*?\[]', word) or re.search(r'[$%`]', word): return [word]
    if getattr(word, 'expand', False):
        try:
            found = glob.glob(word, root_dir=str(here))
        except (OSError, ValueError, TypeError):
            found = []
        if 0 < len(found) <= 500: return found
    prefix = re.split(r'[*?\[]', word, 1)[0].replace('\\', '/')
    return [prefix.rsplit('/', 1)[0] or '.' if '/' in prefix else '.']


class Word(str):
    """A shell word read from the text; `expand` is true for an unquoted Bash word (the shell expands its glob, not git). #12"""
    expand = False


def read_word(raw, powershell):
    word = Word(unquote(raw))
    word.expand = not powershell and not re.search(r'["\'\\]', raw)
    return word


def command_head(words):
    """(words from the command itself, fed): the shell keywords, `(` `{` `!`, assignments, wrappers with their flags and values (`env -i`, `sudo -E`, `timeout 60`,
    `nice -n 5`), and `eval`, `cmd /c`, `powershell -Command`, `bash -c`, `wsl` in front of it are dropped. `fed`: it runs behind xargs, which adds paths the line does not show."""
    fed = False
    while words:
        first = words[0]
        bare = first.lstrip('({')
        if bare != first:
            words = ([bare] if bare else []) + words[1:]
            continue
        name = os.path.basename(first.replace('\\', '/')).lower()
        name = name[:-4] if name.endswith('.exe') else name
        if name in KEYWORDS or re.match(r'^\w+=', first) or name == 'eval' or first in ('}', ')'): words = words[1:]
        elif name in WRAPPERS:
            fed = fed or name == 'xargs'
            words = words[1:]
            while words and words[0].startswith('-') and len(words[0]) > 1:
                flag, words = words[0], words[1:]
                if flag in WRAPPERS[name] and words: words = words[1:]            # `nice -n 5`, `sudo -u root`
            if name == 'timeout' and words: words = words[1:]                      # its duration
        elif name in SHELL_WORDS:
            words = words[1:]
            while words and (words[0].startswith('-') or (name == 'cmd' and words[0].startswith('/'))):
                flag, words = words[0], words[1:]
                if flag.lower() in SHELL_WORDS[name] and words: words = words[1:]
        else: break
    if words and words[-1].count(')') > words[-1].count('('):                                  # `(git stash)`
        trimmed = Word(words[-1].rstrip(')'))
        trimmed.expand = getattr(words[-1], 'expand', False)                                      # #12: the glob rule follows the word
        words[-1] = trimmed
    return [w for w in words if w], fed


def parse_options(args, short_value='', long_value=()):
    """(short letters, long names, plain words, words after `--`) of a git command's arguments. `-s X` / `--source X` take the next word."""
    shorts, longs, plain, after, i = set(), [], [], [], 0
    while i < len(args):
        word = args[i]
        if word == '--':
            after = args[i + 1:]; break
        if word.startswith('--'):
            name = word.split('=')[0]
            longs.append(name)
            if '=' not in word and name in long_value: i += 1
        elif word.startswith('-') and len(word) > 1:
            for n, letter in enumerate(word[1:]):
                shorts.add(letter)
                if letter in short_value:
                    if n == len(word) - 2: i += 1
                    break
        else: plain.append(word)
        i += 1
    return shorts, longs, plain, after


def has_long(longs, full, shortest=4):
    """git takes a unique prefix of a long option: `--fo` is `--force`."""
    return any(len(name) >= shortest and full.startswith(name) for name in longs)


def git_verdict(plan, root, here, words, limited, fed=False):
    """(rule, reason) for one git command (`words` start at the word after `git`), or None. `fed`: xargs / find -exec add the paths, the line does not show them."""
    i = 0
    while i < len(words) and words[i].startswith('-'):
        word = words[i]
        if word == '-C' and i + 1 < len(words):
            here = None if re.search(r'[$%`]', words[i + 1]) or here is None else normalize(words[i + 1], here); i += 1
        elif word == '--work-tree' or word.startswith('--work-tree='): here = None; i += 1 if '=' not in word else 0
        elif word in GIT_VALUE: i += 1
        i += 1
    if i >= len(words): return None
    if re.search(r'[$%`]', words[i]):                                      # #12: `git $c` runs a sub-command the line does not show
        return 'unresolvable_target', f'`git {words[i]}` has a sub-command the hook cannot resolve; write the git command out.' + SAFE_WAY
    sub, args = words[i].lower(), words[i + 1:]
    refuse =lambda why: ('git_discard', f'`git {sub}` {why} can throw away uncommitted work, and only the owned scope is yours to change.' + SAFE_WAY)

    def paths_verdict(paths):
        if fed and paths: return 'unresolvable_target', f'`git {sub}` gets its paths from xargs or find -exec, which the hook cannot read; name literal paths inside the owned scope.' + SAFE_WAY      # #12
        for raw in [name for path in paths for name in glob_names(path, here)]:
            if here is None or raw.startswith(':') or re.search(r'[$%`]', raw):      # #12: `:(top)x`, `:!x` and `:/x` are pathspec magic, not a file name
                return 'unresolvable_target', f'`git {sub}` names "{raw}", a path the hook cannot resolve; name a literal path inside the owned scope.' + SAFE_WAY
            target = normalize(raw, here)
            if limited and not inside_repo(root, target): continue
            verdict = judge_path(plan, root, target, f'`git {sub}` would overwrite it with the committed version.')
            if verdict: return verdict[0], verdict[1] + SAFE_WAY
        return None

    if sub == 'checkout':
        shorts, longs, plain, after = parse_options(args, 'bB', ('--orphan', '--conflict', '--pathspec-from-file'))
        if 'f' in shorts or has_long(longs, '--force'): return refuse('with force')
        if has_long(longs, '--pathspec-from-file', 8): return refuse('with --pathspec-from-file')
        paths = list(after)
        if not after and not ({'b', 'B'} & shorts or has_long(longs, '--orphan')) and plain:
            if '--' in args: paths = []                                           # #12: `checkout <name> --` says <name> is a tree-ish, not a path
            elif re.search(r'[$%`]', plain[0]): paths = plain
            elif local_branch(here if here is not None else Path(root), plain[0]): paths = plain[1:]       # #12: a local branch is a branch even when a folder has its name
            elif here is None or path_word(plain[0], here): paths = plain       # #12: `normalize` reads `/d/...` (Git Bash) as a path too; `*.txt` is a pathspec
            elif len(plain) > 1: paths = plain[1:]                                # `checkout <tree-ish> <paths>`
        if not paths and ('p' in shorts or has_long(longs, '--patch')): return refuse('--patch')
        if fed and not paths and not ({'b', 'B'} & shorts or has_long(longs, '--orphan')): paths = ['{}']      # #12: xargs adds the paths
        return paths_verdict(paths)
    if sub == 'switch':
        shorts, longs, plain, after = parse_options(args, 'cC', ('--create', '--force-create', '--orphan', '--conflict'))
        if 'f' in shorts or has_long(longs, '--force') or has_long(longs, '--discard-changes'): return refuse('with force or --discard-changes')
        return None
    if sub == 'restore':
        shorts, longs, plain, after = parse_options(args, 's', ('--source', '--conflict', '--pathspec-from-file'))
        if ('S' in shorts or has_long(longs, '--staged')) and not ('W' in shorts or has_long(longs, '--worktree')): return None       # only unstages
        if has_long(longs, '--pathspec-from-file', 8): return refuse('with --pathspec-from-file')
        paths = after + plain or (['{}'] if fed else [])                                       # #12: xargs adds the paths
        if not paths: return refuse('--patch') if 'p' in shorts or has_long(longs, '--patch') else None
        return paths_verdict(paths)
    if sub == 'stash':
        action = args[0].lower() if args and not args[0].startswith('-') else 'push'       # a bare `git stash` or `git stash -u` is push
        if action in ('list', 'show'): return None
        if action != 'push': return refuse(action)      # #12: `save` takes a message, not paths: it stashes everything
        shorts, longs, plain, after = parse_options(args[1:] if args and not args[0].startswith('-') else args, 'm', ('--message', '--pathspec-from-file'))
        paths = after + plain
        if not paths or has_long(longs, '--pathspec-from-file', 8): return refuse('without explicit paths')
        return paths_verdict(paths)
    if sub == 'reset':
        for word in args:
            if word.startswith('--') and any(has_long([word.split('=')[0]], full) for full in ('--hard', '--merge', '--keep')): return refuse('with --hard, --merge or --keep')
        return None
    if sub == 'clean':
        shorts, longs, plain, after = parse_options(args, 'e', ('--exclude',))
        if ('f' in shorts or has_long(longs, '--force')) and not ('n' in shorts or has_long(longs, '--dry-run')): return refuse('with force')
        return None
    if sub == 'checkout-index':
        shorts, longs, plain, after = parse_options(args)
        return refuse('with force') if 'f' in shorts or has_long(longs, '--force') else None
    if sub == 'read-tree':
        shorts, longs, plain, after = parse_options(args)
        return refuse('with -u') if 'u' in shorts else None
    return None


CD_WORDS = ('cd', 'pushd', 'popd', 'chdir', 'set-location', 'sl')


def folder_steps(text, state, powershell=False):
    """FIX25C (Codex R1): the segments of a shell text (cut as shell_segments cuts it) with the folders the shell may be in when each one STARTS. Yields
    (begin, end, segment, words, head words, is a cd, folders), then applies the segment's `cd`/`pushd`/`popd`/`( )` to `state` = [here, previous, pushed,
    groups, seen, unsure] (read again after the yield). What runs while a segment runs (its `$( )`, a here-document body it launches, a `bash -c` string) runs
    in these folders: a `cd` later in the command does not move it. #12: `( ... )` gives the folder back when it closes, `pushd`/`popd` push and pop, `cd -` goes
    to the previous folder; when the hook cannot tell for sure, every folder the command may be in (the start and each one entered) is a candidate."""
    begin, after_pipe = 0, False
    for segment, op, cut in shell_segments(text, powershell, detail=True):
        start, begin = begin, cut
        # FIX25E (Codex P1 on 6acc82a): in bash every stage of a pipeline is a child shell and so is a command sent to the background (`&`, not the `&` of
        # `2>&1` or `&>`): its `cd` does not move the commands after it (`cd src | cat; git checkout -- f` runs the checkout where the command was). PowerShell
        # runs a pipeline in the session (FIX25D), so there it does.
        background = op == '&' and text[cut - 2:cut - 1] not in ('>', '<') and text[cut:cut + 1] != '>'
        stage = not powershell and (after_pipe or op in ('|', '|&') or background)
        after_pipe = op in ('|', '|&')
        if not segment.strip(): continue
        here, previous, pushed, groups, seen, unsure = state
        words = []
        for raw in without_redirects(TOKEN.findall(hide_escapes(segment, powershell))):      # #25: `cd du\ an\ A` is one word
            word = read_word(raw, powershell)
            shown = Word(show_escapes(word)); shown.expand = word.expand and HIDDEN not in raw
            words.append(shown)
        head_words, _ = command_head(list(words))
        stripped = segment.strip()
        if not powershell: groups += [(here, previous)] * (len(stripped) - len(stripped.lstrip('(')))
        name = os.path.basename(head_words[0].replace('\\', '/')).lower() if head_words else ''
        moves = name in CD_WORDS
        folders = ([here] + [f for f in seen if f != here]) if unsure else [here]
        state[:] = [here, previous, pushed, groups, seen, unsure]
        yield start, cut, segment, words, head_words, moves, folders
        here, previous, pushed, groups, seen, unsure = state
        if moves and not stage:
            target = next((w for w in head_words[1:] if not w.startswith('-') or w == '-'), None)
            before = here
            if name == 'popd':
                if pushed: here = pushed.pop()
                else: unsure = True
            elif here is None or target is None or target.startswith('~'): here, unsure = None, True
            elif target == '-': here = previous
            elif re.search(r'[$%`]', target): here = None
            else: here = normalize(target, here)
            if name == 'pushd': pushed.append(before)
            if here != before: previous = before
            if here is not None and here not in seen: seen.append(here)
        if not powershell:
            for _ in range(min(max(0, stripped.count(')') - stripped.count('(')), len(groups))): here, previous = groups.pop()
        state[:] = [here, previous, pushed, groups, seen, unsure]



# FIX25D (Codex C1 on 7781c08): a PowerShell location change the hook cannot follow step by step: in a script block `{ }`, a group `( )`, after `&`, `.`,
# or `=` (`& { Set-Location .. }`, `(cd ..)`, `$x = Set-Location ..`). LOCATION_WORD only decides whether ps_after has anything to read.
LOCATION = re.compile(r'(?:[{(=&]|(?:^|\s)\.\s)\s*(?:cd|chdir|sl|set-location|pushd|push-location|popd|pop-location)(?=[\s;})]|$)', re.I)
LOCATION_WORD = re.compile(r'(?<![\w-])(?:cd|chdir|sl|set-location|pushd|push-location|popd|pop-location)(?![\w-])', re.I)


def ps_after(text, here, depth=0):
    """FIX25D (Codex C1): the PowerShell location after `text` runs from `here`; None when the hook cannot tell. In PowerShell the location belongs to the
    session: a `Set-Location`/`cd` inside `$( )` moves every command after it (`$x = $(Set-Location ..); git checkout -- f` runs the checkout one folder
    up), unlike a bash `$( )`, a child shell. A `$( )` inside '...' is text. A change the hook cannot follow (LOCATION, a `$( )` more than 3 levels
    deep, a folder that is not a literal) gives None, and what comes after is judged as after an unreadable cd (a relative path is refused)."""
    if here is None: return None
    spans = substitution_spans(text, True)
    if not spans and not LOCATION_WORD.search(text): return here
    lit = masked_quotes(text, True)
    state = [here, here, [], [], [here], False]
    for begin, end, segment, _, _, _, _ in folder_steps(hollow(text, spans), state, True):
        cur = state[0]
        for start, _, inner in spans:
            if begin <= start < end and lit[start:start + 1] == '$':
                cur = ps_after(inner, cur, depth + 1) if depth < 3 else None
        if LOCATION.search(masked_quotes(segment, True)): cur = None
        if cur != state[0]:
            state[1], state[0] = state[0], cur
            if cur is None: state[5] = True
            elif cur not in state[4]: state[4].append(cur)
    return None if state[5] else state[0]


def chunk_folders(text, start, powershell=False):
    """FIX25C (Codex R1), for shell_effects: (the `$( )`/backtick spans of a chunk, [(begin, end, folders)] of its segments, the folders its here-document bodies
    are launched in: those in force when a segment holding a `<<` starts, or every folder the chunk may be in when none is found)."""
    spans = substitution_spans(text, powershell)
    state = [start, start, [], [], [start], False]
    steps, launch = [], []
    for begin, end, segment, _, _, _, folders in folder_steps(text if powershell else hollow(text, spans), state, powershell):
        steps.append((begin, end, folders))
        if HEREDOC.search(segment): launch += [f for f in folders if f not in launch]
    if not launch: launch = list(dict.fromkeys([start, *(f for _, _, many in steps for f in many), state[0]]))
    return spans, steps, launch


def discard_verdict(plan, root, cwd, command, limited=False, powershell=False, split=None):
    """(rule, reason) when a command of the text (`cd` followed, `git -C` followed, `$(...)` and `bash -c '...'` read too) is a git form that throws away
    uncommitted work outside the owned scope, or `rm` with recursive and force in any spelling; else None."""
    exports = {}

    def one(words, here, fed):
        env_dir = reach_places(words, here, exports, False)[1] if words else None        # #25: `env -C DIR git ...` and GIT_WORK_TREE=DIR run git in DIR
        if env_dir is UNREADABLE: here = None
        elif env_dir is not None: here = env_dir
        words, wrapped = command_head(words)
        fed = fed or wrapped
        if not words: return None
        head = os.path.basename(words[0].replace('\\', '/')).lower()
        if head in ('git', 'git.exe', 'git.cmd'): return git_verdict(plan, root, here, words[1:], limited, fed)
        if head == 'find':                                           # #12: `find ... -exec git checkout -- {} +` gets its paths from find
            for n, word in enumerate(words):
                if word in ('-exec', '-execdir', '-ok', '-okdir'):
                    verdict = one([w for w in words[n + 1:] if w not in ('+', '\\;')], here, True)
                    if verdict: return verdict
        if head == 'rm':
            options = [w for w in words[1:words.index('--')] if w.startswith('-')] if '--' in words[1:] else [w for w in words[1:] if w.startswith('-')]
            letters = ''.join(w[1:] for w in options if not w.startswith('--'))
            recursive = bool(set('rR') & set(letters)) or any(has_long([w], '--recursive') for w in options)
            force = 'f' in letters or any(has_long([w], '--force') for w in options)
            if recursive and force:
                return 'bash_deny', 'rm with recursive and force (-rf in any spelling) is refused: remove a file with plain `rm <file>`, or work in a separate `git worktree add`, or in `.onecrew/scratch/`.'
        return None

    def walk(text, state, depth=0, launches=None):
        # FIX25C (Codex R1): each segment is judged in the folders in force when it starts, and so is every text that runs while it runs (`$( )`, backticks,
        # `<( )`, a string given to `bash -c`): `x=$(git checkout -- f); cd src` runs the checkout where the command started, `x=$(cd A && git checkout -- f)`
        # runs it in A. `launches` collects the folders of the segments holding a `<<`: their here-document bodies start there.
        # FIX25D (Codex C1): PowerShell is hollowed too; a PowerShell `$( )` runs in the session, so the location it leaves is carried on by ps_after below
        spans = substitution_spans(text, powershell)
        body = hollow(text, spans)       # bash: `$( )` is a child shell, its `cd` does not reach the segments after it
        literal = masked_quotes(text, True) if powershell else ''
        # the other texts a shell runs (`bash -c '...'`, `@'...'@ | iex`, `<( )`) are found in the WHOLE text, since their cue may sit in another segment
        # (`| Invoke-Expression`), and each is read in the folders of the segment it starts in; one the hook cannot place is read in every segment's folders
        others = []
        if depth < 3:
            for t in dict.fromkeys(command_texts(body, 2, powershell)[1:]):
                places = [m.start() for m in re.finditer(re.escape(t), body)] if t.strip() else []
                others += [(at, t) for at in places] or [(-1, t)]
        for begin, end, segment, words, head_words, moves, folders in folder_steps(body, state, powershell):
            judge = folders
            if depth < 3:
                cur = list(folders)
                for s, _, t in [span for span in spans if begin <= span[0] < end]:
                    for folder in cur:
                        verdict = walk(t, [folder, folder, [], [], [folder], False], depth + 1)
                        if verdict: return verdict
                    if powershell and literal[s:s + 1] == '$': cur = list(dict.fromkeys(ps_after(t, f) for f in cur))      # FIX25D: the next one starts there
                for t in dict.fromkeys(t for at, t in others if begin <= at < end or at < 0):
                    for folder in cur:
                        verdict = walk(t, [folder, folder, [], [], [folder], False], depth + 1)
                        if verdict: return verdict
                        if powershell and ps_after(t, folder) != folder: cur = [None]      # FIX25D: an `iex` string (or a child) that moves: not followed
            if powershell and not moves and depth < 3:
                # FIX25D (Codex C1): the command of the segment runs after its `$( )`, and the commands after it run where the segment left the session
                judge = [None] if cur == [None] else list(dict.fromkeys(ps_after(text[begin:end], f) for f in folders))      # from the start of the segment: its `$( )` in order
                if judge != folders:
                    here = state[0]
                    if len(judge) == 1 and not state[5]:
                        state[1], state[0] = here, judge[0]
                        if judge[0] is None: state[5] = True
                    else:
                        state[5] = True
                        state[0] = None if None in judge else judge[0]
                    state[4].extend(f for f in judge if f is not None and f not in state[4])
            if launches is not None and HEREDOC.search(segment): launches.extend(f for f in folders if f not in launches)
            if head_words and not moves:
                for folder in judge:
                    verdict = one(words, folder, False)
                    if verdict: return verdict
            if head_words: exports.update(git_exports(words, segment, powershell))      # #25: `export GIT_WORK_TREE=...` holds for the commands after it
        return None

    # #25 (final review P1-1): the command is walked in the chunks of heredoc_units (as shell_effects does) with ONE folder state.
    start = Path(cwd)
    state = [start, start, [], [], [start], False]
    launches = [start]
    for unit, _, script in heredoc_units(command, True):
        if script:
            # FIX25B/FIX25C (Codex F2, R1): a body that runs as a script is a child shell started by the segment holding its `<<`, in the folders in force when that
            # segment starts (`pushd A && bash <<EOF && popd` runs it in A, `bash <<EOF && cd src` where the command was); its `cd` does not reach the text after it
            for folder in launches:
                verdict = walk(unit, [folder, folder, [], [], [folder], False])
                if verdict: return verdict
            continue
        before = [state[0], *state[4]]
        launches = []
        verdict = walk(unit, state, 0, launches)
        if verdict: return verdict
        if not launches: launches = list(dict.fromkeys([*before, state[0], *state[4]]))      # no `<<` segment found: every folder the chunk may be in
    return None


def judge_shell(plan, root, cwd, command, limited=False, refuse_unresolvable=False, powershell=False):
    """The plan's verdict on a shell command. `limited` is a plan that is not the session's (it was reached through the cwd or through a path the command
    writes): the deny and mention rules apply, since the command runs there, but only the paths the command writes INSIDE that plan's repository are
    judged, and a path the hook cannot resolve is left to the session's plan, unless `refuse_unresolvable` (the plan of the cwd when the session has no
    enforce plan of its own: nothing else would look at it). `powershell`: the command comes from the PowerShell tool."""
    split = without_heredocs(command, powershell)
    verdict = discard_verdict(plan, root, cwd, command, limited, powershell, split)      # first: an older plan's deny list says `reset --hard` without the way out
    if verdict: return verdict
    forms = variants('\n'.join([split[0]] + split[1]))      # #12: the deny list reads commands, not the text of a here-document that a text reader takes (`git reset --hard` in a commit message)
    for entry in plan.get('bash_deny', []):
        for form in forms:
            hit = re.search(entry[3:], form, re.I) if entry.startswith('re:') else (entry.casefold() in form.casefold())
            if hit:
                note = ' Local evidence refs/onecrew must not be published.' if 'refs/onecrew' in form.casefold() else ''
                return 'bash_deny', f'The command matches the deny rule "{entry[3:] if entry.startswith("re:") else entry}". Approval, acceptance, enforcement, push, tag and installs are the owner\'s. Ask the owner in chat.' + note
    items = [(_fold(plan.get('state_root', '')) + '/plans', ''), ('policy.json', ''), ('.sqlite', ''), ('active-plan.json', ''), ('violations.jsonl', ''), ('hook-state.json', ''),
             (where.REGISTRY, ''), ('.claude/settings', ''), ('.onecrew', 'whole'), ('onecrew/plans', 'start')]
    for segment in shell_segments(command, powershell):         # each segment on its own: `ls; python -c "...remove(registry)"` is not read-only because its first word is
        first = (re.findall(r'[\w.-]+', segment) or [''])[0].lower()
        if first in READ_ONLY and not SUBSTITUTION.search(segment): continue      # #12: `cat $(...)` runs the command inside
        flat = ' '.join(without_scratch(_fold(form)) for form in variants(segment))       # each form on its own: a path never runs from one into the next
        for item, how in items:
            if mentions(flat, item, how):
                return 'protected', f'The command mentions {item}, which only the owner changes ({first or "?"} is not a read-only command).'
    for raw, here in shell_effects(command, cwd, powershell)[0]:        # #25: each target with the directory its piece runs in (cd), interpreter code read; #12: a body a text reader takes (skips_body) is no write target
        if not_a_file(raw, powershell): continue
        if re.search(r'[$%`]', raw) or (here is None and not is_absolute_text(raw)):
            if limited and not refuse_unresolvable: continue
            if raw == CODE_PATH:
                return 'unresolvable_target', 'The code given to an interpreter in this command writes a path the hook cannot read (it is not a literal); write to a literal path inside the owned scope.'
            if here is None and not re.search(r'[$%`]', raw):
                return 'unresolvable_target', f'The command writes to "{raw}" after a `cd` the hook cannot resolve; cd to a literal folder, or write to an absolute path inside the owned scope.'
            return 'unresolvable_target', f'The command writes to "{raw}", a path the hook cannot resolve; write to a literal path inside the owned scope.'
        target = normalize(raw, here or cwd)
        if limited and not inside_repo(root, target): continue
        verdict = judge_path(plan, root, target, 'The command writes there.')
        if verdict: return verdict
    return None


def touches_repo(plan, root, event, base):
    """Does this call write somewhere in the repository of the plan's root? (An Edit: its path; a shell command: any path it appears to write.)"""
    data = event.get('tool_input') if isinstance(event.get('tool_input'), dict) else {}
    try:
        if event.get('tool_name') in EDIT_TOOLS:
            raw = next((data[k] for k in PATH_KEYS if isinstance(data.get(k), str) and data[k]), None)
            return raw is not None and inside_repo(root, normalize(raw, base))
        if event.get('tool_name') in SHELL_TOOLS and isinstance(data.get('command'), str):
            powershell = event.get('tool_name') == 'PowerShell'
            for raw, here in shell_effects(data['command'], base, powershell)[0]:
                if re.search(r'[$%`]', raw) or not_a_file(raw, powershell) or (here is None and not is_absolute_text(raw)): continue
                if inside_repo(root, normalize(raw, here or base)): return True
    except (OSError, ValueError):
        return True
    return False


# ---- the verbs -------------------------------------------------------------------------------------------------------------

def read_stdin():
    try:
        data = json.loads(sys.stdin.buffer.read().decode('utf-8-sig') or 'null')
        if not isinstance(data, dict): return {}, 'stdin is not a JSON object'
        return data, None
    except (ValueError, OSError) as error:
        return {}, f'{type(error).__name__}: {error}'


def _nearest_dir(path):
    """The nearest existing directory at or above `path` (a file that does not exist yet has its folder, or one above it)."""
    here = Path(path)
    for directory in (here, *here.parents):
        if directory.is_dir(): return directory
    return None


def _shell_target_dirs(command, base, powershell=False):
    """The folders that hold the paths a shell command appears to write (all_targets, resolved against `base`; a target the hook cannot resolve is skipped
    here, judge_shell refuses it on its own)."""
    found, goes = [], []
    targets, places = shell_effects(command, base, powershell)       # #25 (review 2): PowerShell text is read as PowerShell here too ($env: assignments, no `\ ` escape)
    for raw, here in targets:
        if re.search(r'[$%`]', raw) or raw.casefold() in NULLS or raw.casefold().startswith(TEMP_VARS) or (here is None and not is_absolute_text(raw)): continue
        try:
            folder = _nearest_dir(normalize(raw, here or base).parent)
        except (OSError, ValueError):
            continue
        if folder is not None and folder not in found: found.append(folder)
    for place in places:                       # #25: a folder a `cd` goes to is a place the command runs in, like the cwd
        folder = _nearest_dir(place)
        if folder is not None and folder not in goes: goes.append(folder)
    return found, goes


SESSION, CWD, LIMITED = 'session', 'cwd', 'limited'          # roles of a plan, strongest first: the session's, the plan of the repository of the cwd, another repository the call writes in
RANK = {SESSION: 2, CWD: 1, LIMITED: 0}


def candidate_dirs(args, event):
    """[(place, role)]: every place a plan applies to this call from, and in what role.

    The SESSION's project is where.project_from_environment (CLAUDE_PROJECT_DIR, else the event's cwd, else ours): its plan judges the whole call. A
    LIMITED place is another repository the call reaches: for an Edit/Write the one that holds the PATH being written (the cwd is not a place); for a shell
    command the one that holds its cwd and the ones that hold the paths it appears to write. A limited plan judges only what the call does inside its own
    repository (see judge_call). Every other hook event (prompt, stop, session) has the session's project alone."""
    cwd = event.get('cwd') if isinstance(event.get('cwd'), str) and event.get('cwd') else None
    session = where.project_from_environment(cwd)
    tool = event.get('tool_name')
    data = event.get('tool_input') if isinstance(event.get('tool_input'), dict) else {}
    places = [(session, SESSION)]
    if tool in EDIT_TOOLS:
        raw = next((data[k] for k in PATH_KEYS if isinstance(data.get(k), str) and data[k]), None)
        try:
            target = normalize(raw, cwd or os.environ.get('CLAUDE_PROJECT_DIR') or os.getcwd()) if raw else None
        except (OSError, ValueError):
            target = None
        if target is not None and _nearest_dir(target.parent) is not None: places.append((_nearest_dir(target.parent), LIMITED))
    elif tool in SHELL_TOOLS:
        command = data.get('command')
        if cwd: places.append((cwd, CWD))
        if isinstance(command, str):
            written, goes = _shell_target_dirs(command, cwd or os.environ.get('CLAUDE_PROJECT_DIR') or os.getcwd(), tool == 'PowerShell')
            places += [(folder, CWD) for folder in goes] + [(folder, LIMITED) for folder in written]
    return places


def locate_all(args, event):
    """[(project copy, project root, state-root copy, role)] of EVERY plan that applies to this call, one per project, in the order of candidate_dirs; [] when none.

    B1: the project copy `<project>/.onecrew/active-plan.json` is the first source and the state-root copy `<state-root>/plans/<name>/active-plan.json`
    (written at the same time, outside the project) is the second. Deleting the project copy, or the whole `.onecrew/`, therefore does not end
    enforcement: a state-root copy that names this project brings the plan back, and a project copy that disagrees with it is treated as tampered with
    (see `tampered`). The state root is `--state-root`, else `<project>/.onecrew/config.json` (which the hook also records in the registry outside the
    project, where.register_project), else that registry, else the default: a custom state root survives the deletion of `.onecrew/`.
    Each place is searched up to the root of its repository and no further, so the plan of a parent repository never governs a repository inside it. The
    plans are all kept: a call is judged by every one of them (check), and none can be replaced by a nearer one, however it got there."""
    explicit = Path(args.project) if args.project else None

    def state_of(directory):       # G2: an installed hook has no --state-root
        if args.state_root: return args.state_root
        folder, configured = where.configured(directory)
        if configured:
            where.register_project(folder, configured)
            return configured
        return where.registered_state_root(directory) or where.default_state_root()

    found, seen = [], {}
    for start, role in ([(explicit, SESSION)] if explicit else candidate_dirs(args, event)):
        hit = None
        project_copy = find_plan_file([start], walk=not explicit)
        if project_copy:
            root = project_copy.parent.parent
            hit = [project_copy, root, state_copy(state_of(root), root), role]
        else:
            try:
                directories = [explicit] if explicit else where.repository_dirs(start)
            except OSError:
                continue
            for directory in directories:       # no project copy: the state-root copy that names this very directory as its project still governs it
                copy = state_copy(state_of(directory), directory)
                if copy:
                    hit = [None, directory, copy, role]
                    break
        if hit is None: continue
        key = os.path.normcase(str(Path(hit[1]).resolve()))
        if key not in seen:
            seen[key] = hit
            found.append(hit)
        elif RANK[role] > RANK[seen[key][3]]: seen[key][3] = role          # a repository reached more than one way keeps the strongest role
    return [tuple(hit) for hit in found]


def locate(args, event):
    """The first of locate_all, or (None, explicit project, None): the one plan of the verbs that have no tool call (prompt, stop, session, sync)."""
    found = locate_all(args, event)
    return found[0][:3] if found else (None, Path(args.project) if args.project else None, None)


def state_copy(state_root, root):
    """The newest state-root copy of an active plan that belongs to project `root`, as a path; None when there is none (or no --state-root)."""
    if not state_root: return None
    best, stamp = None, ''
    try:
        here = os.path.normcase(str(Path(root).resolve()))
        for candidate in Path(state_root).glob('plans/*/' + FILE):
            try:
                value = json.loads(candidate.read_text(encoding='utf-8-sig'))
                if os.path.normcase(str(Path(value['project']).resolve())) == here and str(value.get('exported_at', '')) >= stamp: best, stamp = candidate, str(value.get('exported_at', ''))
            except (OSError, ValueError, KeyError, TypeError):
                continue
    except OSError:
        return None
    return best


def tampered(project_plan, copy_plan):
    """True when the project copy says something other than the state-root copy about what is allowed."""
    return any(project_plan.get(k) != copy_plan.get(k) for k in ('plan', 'revision', 'plan_sha', 'mode', 'owned', 'non_goals', 'bash_deny', 'protected', 'scratch','workflow_holds'))


def governing(args, event):
    """(plan, root, error, source) of the first plan that applies (see `locate`)."""
    return govern(*locate(args, event))


def govern(project_copy, root, copy):
    """(plan, root, error, source) of one located plan. error is a text when the files disagree or cannot be read; source tells where the plan came from."""
    if project_copy is None and copy is None: return None, root, None, None
    if copy is None:
        plan, bad = load_plan(project_copy)
        return plan, root, (('active plan unreadable: ' + bad) if bad else None), project_copy
    cplan, cbad = load_plan(copy)
    if project_copy is None:                            # B1: .onecrew/ was deleted; the plan is still the state root's, and the project copy is put back
        if cbad: return cplan, root, 'active plan unreadable: ' + cbad, copy
        try:
            (Path(root) / '.onecrew').mkdir(exist_ok=True)
            (Path(root) / '.onecrew' / FILE).write_text(copy.read_text(encoding='utf-8-sig'), encoding='utf-8')
        except OSError:
            pass
        return cplan, root, None, 'restored'
    pplan, pbad = load_plan(project_copy)
    if pbad: return cplan, root, 'active plan unreadable: ' + pbad, copy
    if not cbad and tampered(pplan, cplan): return cplan, root, 'the project copy of the active plan differs from the state-root copy', copy
    return cplan if not cbad else pplan, root, None, project_copy


def has_project_hook(project, same=None):
    """#25: does <project>/.claude/settings.local.json or settings.json hold a OneCrew PreToolUse hook (`onecrew hook check`, or the checkout form), not the user-scope one?
    `same` (a program path): only a hook that runs that very program counts."""
    for name in ('settings.local.json', 'settings.json'):
        try:
            data = json.loads((Path(project) / '.claude' / name).read_text(encoding='utf-8-sig'))
            entries = data['hooks']['PreToolUse']
        except (OSError, ValueError, KeyError, TypeError):
            continue
        for entry in entries if isinstance(entries, list) else []:
            for handler in (entry.get('hooks') if isinstance(entry, dict) and isinstance(entry.get('hooks'), list) else []):
                if not isinstance(handler, dict) or not isinstance(handler.get('command'), str): continue
                args = handler.get('args')
                words = [handler['command'], *args] if isinstance(args, list) else handler['command'].replace('"', ' ').split()
                program = re.split(r'[\\/]', words[0].strip())[-1].casefold() if words else ''
                if same is not None and os.path.normcase(os.path.realpath(str(words[0]).strip('"'))) != same: continue
                if [str(w) for w in words[-2:]] == ['hook', 'check'] and (program in ('onecrew', 'onecrew.exe', 'onecrew.cmd') or any('onecrew.v2.hook_cli' in str(w) for w in words)):
                    return True
    return False


def check(args):
    """Exit 2 when ANY plan that applies to the call blocks it. The plans are the session's (its project: judges the whole call) and the plans of the other
    repositories the call reaches (the repository that holds a path it writes; for a shell command also the one that holds its cwd), which judge only what
    the call does inside their own repository. A plan that is accepted, in log mode, only proposed or not there at all never lets through what another plan
    blocks. No plan anywhere: nothing to enforce."""
    event, bad_input = read_stdin()
    user = getattr(args, 'scope', 'project') == 'user'
    # #25: the user-scope hook decides exactly as the project hook; it writes the record only when the session's project has no OneCrew hook of its own
    # (then that hook writes it), so one call gives one record
    # #25 (review P2-4): the record() of a call with a tool_use_id is written once whoever comes first; the guess from the settings files stays only for a payload
    # that has no tool_use_id (nothing else can tell the two hooks' lines apart then)
    no_id = not (isinstance(event.get('tool_use_id'), str) and event.get('tool_use_id'))
    # #25 (review 2, P2-A): also quiet, with an id, when the project hook runs this very program (the two run at once; claim_call settles the rest)
    session_project = where.project_from_environment(event.get('cwd') if isinstance(event.get('cwd'), str) else None) if user else None
    same = os.path.normcase(os.path.realpath(sys.argv[0])) if user and sys.argv and sys.argv[0] else None
    note_call(event, 'user' if user else 'project', quiet=user and (has_project_hook(session_project, same) if not no_id else has_project_hook(session_project)))
    governed = [(govern(project_copy, project_root, copy), role) for project_copy, project_root, copy, role in locate_all(args, event)]
    # a path the hook cannot resolve (`$PWD/x`) is judged by the session's plan; when the session has no enforce plan of its own, the plan of the cwd judges it
    watched = any(plan is not None and role == SESSION and plan.get('mode') == 'enforce' and plan.get('status') in ('approved', 'stopped_with_report','closed')
                  for (plan, _, _, _), role in governed)
    code = 0
    for (plan, root, bad_plan, source), role in governed:
        if plan is not None and judge_call(plan, root, bad_plan, source, event, bad_input, limited=role != SESSION, refuse_unresolvable=role == CWD and not watched) == 2: code = 2
    return code


def judge_call(plan, root, bad_plan, source, event, bad_input, limited=False, refuse_unresolvable=False):
    """One plan's verdict on one call: 2 when it blocks the call (enforce mode), else 0.

    `limited` is a plan that is not the session's: it was reached through the cwd of a shell command or through a path the call writes. It judges what
    the call writes inside ITS repository (a path of another repository, a nested worktree included, is not its business), and for a shell command
    also the deny and mention rules, because the command runs there. A plan that is stopped_with_report refuses a call only when the call writes in
    its repository, so a cwd that drifted into it does not lock the session, and `cd` back to the session's project is always possible."""
    mode = 'enforce' if plan.get('mode') == 'enforce' else 'log'
    session, tool = event.get('session_id'), event.get('tool_name') or '?'
    if source == 'restored': record(root, plan, 'logged', tool, '.onecrew/active-plan.json was missing and was restored from the state root', 'plan_restored', session=session, mode=mode)
    try:
        base = event.get('cwd') or root
        touched = not limited or touches_repo(plan, root, event, base)
        if bad_input or (bad_plan and touched): raise ValueError(bad_input or bad_plan)
        if plan.get('status') not in ('approved', 'stopped_with_report','closed'):
            return 0
        expires = plan.get('expires')
        if touched and expires and dt.datetime.fromisoformat(expires) < dt.datetime.now(dt.timezone.utc):
            raise ValueError('the active plan expired; the owner re-approves it (plan approve) to refresh it')
        if touched: holds_current(root, plan)        # W18: a register newer than the exported holds fails closed, never open
        data = event.get('tool_input') if isinstance(event.get('tool_input'), dict) else {}
        verdict = None
        if plan.get('status') in ('stopped_with_report','closed') and touched:      # first in the chain and not tool-specific: edits and shell commands alike get this verdict
            verdict = ('stopped', f"Plan {plan.get('plan')} is {plan['status']}: the owner decides the next step; nothing further is changed. "
                                  f"Every shell command and every edit is refused; read the evidence with Read, Grep and Glob.")
        elif tool in EDIT_TOOLS:
            raw = next((data[k] for k in PATH_KEYS if isinstance(data.get(k), str) and data[k]), None)
            if raw is None: raise ValueError(f'{tool} call without a path field ({"/".join(PATH_KEYS)})')
            verdict = judge_path(plan, root, normalize(raw, base), 'Do not edit it.') if touched else None
        elif tool in SHELL_TOOLS:
            if not isinstance(data.get('command'), str): raise ValueError(f'{tool} call without command')
            verdict = judge_shell(plan, root, base, data['command'], limited=limited, refuse_unresolvable=refuse_unresolvable, powershell=tool == 'PowerShell')
        else:
            return 0                                     # a tool this hook does not govern
    except Exception as error:                          # noqa: BLE001 - fail closed in enforce, open in log
        record(root, plan, 'blocked' if mode == 'enforce' else 'logged', tool, f'hook error: {error}', 'hook_error', session=session, mode=mode)
        if mode == 'enforce':
            print(f'OneCrew hook failed ({error}); blocked because the plan is in enforce mode. Ask the owner.', file=sys.stderr)
            return 2
        return 0
    if verdict is None: return 0
    rule, reason = verdict                                  # any verdict, the stopped one included, is exit 2 below in enforce mode
    subject = next((str(v) for k, v in (event.get('tool_input') or {}).items() if k in PATH_KEYS + ('command',)), '')
    record(root, plan, 'blocked' if mode == 'enforce' else 'logged', tool, reason, rule, subject, session, mode)
    if mode == 'enforce':
        print(f'Blocked by the OneCrew plan ({rule}): {reason}', file=sys.stderr)
        return 2
    return 0


def prompt(args):
    event, _ = read_stdin()
    note_call(event)                 # #25: the identity of an earlier call in this process must not leak into this record
    plan, root, bad, _ = governing(args, event)
    if plan is None or plan.get('status') not in ('approved', 'stopped_with_report'): return 0
    text = str(event.get('prompt') or '').casefold()
    hit = next((k for k in plan.get('prompt_keywords', []) if str(k).casefold() in text), None)
    rules = Path(plan.get('state_root') or '.') / 'plans' / 'owner-rules.md'
    line = f"The owner's rules are in {rules}; read them before proposing or presenting anything." if rules.is_file() else None
    if hit is None:
        if line: print(json.dumps({'hookSpecificOutput': {'hookEventName': 'UserPromptSubmit', 'additionalContext': line}}, ensure_ascii=False))
        return 0
    budget = plan.get('budget') or {}
    pending = next((m['id'] for m in plan.get('milestones', []) if m.get('state') != 'passed'), None)
    note = (f"Contract v{plan.get('revision')} says: {budget.get('max_calls')} calls, {budget.get('time')} minutes, next milestone {pending or 'none'}. "
            f"Spoken words are not in the ledger; change the contract with `onecrew plan amend` or file a CREQ.")
    record(root, plan, 'reminded', 'UserPromptSubmit', note, 'prompt_keyword:' + str(hit), session=event.get('session_id'))
    print(json.dumps({'hookSpecificOutput': {'hookEventName': 'UserPromptSubmit', 'additionalContext': note + (' ' + line if line else '')}}, ensure_ascii=False))
    return 0


def refreshed(root, plan):
    """The plan as the ledger knows it now (so Stop sees verdicts and acceptance); the file when the ledger cannot be read."""
    try:
        from ..ledger import Ledger
        from . import active_plan, namespaces
        ledger = Ledger(Path(plan['project']), Path(plan['state_root']))
        try:
            from . import verdict
            verdict.reap(ledger, plan.get('anchor', plan['plan']))
        except Exception:
            pass  # build ignores lost runs even if the cleanup record cannot be written
        fresh = active_plan.build(ledger, plan.get('anchor', plan['plan']))
        if fresh:
            fresh['expires'] = plan.get('expires', fresh['expires'])   # a session start must not renew the owner's approval window
            active_plan._write(active_plan.project_file(root), fresh)                               # both copies, so they keep agreeing
            active_plan._write(namespaces.active_file(ledger, fresh['anchor']), fresh)
            return fresh
    except Exception:                                    # noqa: BLE001 - a stale file is better than no answer
        pass
    return plan


def running_checks(plan):
    """The checks running now in the shared lifecycle (review_dispatch.active_checks), read-only; none when the ledger cannot be read."""
    try:
        from ..ledger import Ledger
        from . import review_dispatch
        return review_dispatch.active_checks(Ledger(Path(plan['project']), Path(plan['state_root'])), plan.get('anchor', plan['plan']))
    except Exception:                                    # noqa: BLE001 - a hook must not lock the session
        return []


def engine_next(plan):
    """What moves a workflow root (the engine owns its execution and the owner accepts its handoff; a milestone verdict does not count there):
    {'delivered': True} or {'delivered': False, 'command': the next engine verb}. None for any other root or when the ledger cannot be read."""
    if 'sequential-engine' not in (plan.get('capabilities') or []): return None
    try:
        from ..ledger import Ledger
        from . import engine
        anchor = plan.get('anchor', plan['plan'])
        ledger = Ledger(Path(plan['project']), Path(plan['state_root']))
        if engine.root_ready(ledger, anchor): return {'delivered': True}
        records = engine.state(ledger, anchor)['nodes']
        produced = [nid for nid, record in records.items() if record.get('state') == 'produced' and record.get('phase') != 'held']
        return {'delivered': False, 'command': f"onecrew engine verify {plan['plan']} {produced[0]}" if produced else f"onecrew engine step {plan['plan']}"}
    except Exception:                                    # noqa: BLE001 - a hook must not lock the session
        return None


def owner_wait(milestone):
    """Why a milestone without a passing verdict waits for the owner and not for the session, or None (beta report B6, 29/10): the owner checks it
    (owner-manual), its last verdict was inconclusive (another run on the same work gives the same answer and uses a repair), or no repair is
    left. Read from the exported milestone; an export written before these fields existed says None, and the Stop hook behaves as before."""
    if milestone.get('verifier') == 'owner-manual': return 'the owner checks it (owner-manual) and only the owner records its verdict'
    if milestone.get('last_result') == 'inconclusive':
        return (f"its last verdict was inconclusive: the verifier could not judge the work, and another run on the same work gives the same answer "
                f"and uses a repair ({milestone.get('repairs_left')} left). If the receipt names a cause in your own work, fix that first; otherwise "
                f"tell the owner what blocks it (the owner amends the plan)")
    if milestone.get('repairs_left') == 0 and milestone.get('runs'): return 'no repair is left; only an amendment the owner approves can change it'
    return None


def stop(args):
    event, _ = read_stdin()
    note_call(event)
    plan, root, bad, _ = governing(args, event)
    if plan is None: return 0
    plan = refreshed(root, plan)
    session = event.get('session_id')
    pending = next((m for m in plan.get('milestones', []) if m.get('state') != 'passed'), None)
    if plan.get('status') != 'approved' or pending is None:
        session_state(root, session, {'stop_blocks': 0})
        return 0
    waiting = plan.get('waiting') or {}
    checks = running_checks(plan)                       # 2.5-B: the same requests the engine and candidate doors run; the hook never runs a check itself
    if waiting.get('receipt_without_verdict') or waiting.get('open_questions') or waiting.get('run_in_progress') or checks:
        # The turn can end: what is missing is not the session's to do. A receipt waits for its verdict (verdict run records it), or the owner
        # has an open question. Nothing else lets go of an unfinished plan; the cap below still applies to it.
        what = ('a receipt without a verdict for ' + ', '.join(waiting['receipt_without_verdict'])) if waiting.get('receipt_without_verdict') else ''
        if waiting.get('run_in_progress'):
            what += ('; ' if what else '') + 'a verdict run in progress for ' + ', '.join(waiting['run_in_progress'])
        if checks:
            what += ('; ' if what else '') + 'a check running: ' + ', '.join(f"{c['door']} run {c['run_id']}" for c in checks[:5])
        what += ('; ' if what else '') + ('an open owner question (' + ', '.join(waiting['open_questions']) + ')') if waiting.get('open_questions') else ''
        record(root, plan, 'logged', 'Stop', f"waiting, the session is let go: {what}; milestone {pending['id']} ({pending['title']}) has no verdict yet", 'stop_waiting', session=session)
        return 0
    state = session_state(root, session)
    moves = engine_next(plan)
    why = 'the verified candidate was delivered and only the owner accepts it' if moves and moves['delivered'] else None if moves else owner_wait(pending)
    if why:
        # B6: the session cannot move this milestone. Say so once for each (plan, revision, milestone, number of runs), then let the session
        # stop: a new verdict or a new revision is a new reminder. The milestone stays unpassed, so "done" is still not true.
        key = f"{plan.get('anchor', plan['plan'])}:{plan.get('revision')}:{pending['id']}:{pending.get('runs')}"
        reason = ((f"Plan {plan['plan']} waits for the owner: {why}. " if moves else f"Milestone {pending['id']} ({pending['title']}) has no passing verdict and waits for the owner: {why}. ")
                  + "Stop here and say what the owner has to decide. Do not say it is done.")
        if plan.get('mode') != 'enforce':
            record(root, plan, 'logged', 'Stop', 'would block once: ' + reason, 'stop_owner_wait', session=session)
            return 0
        if state.get('owner_wait') == key:
            record(root, plan, 'logged', 'Stop', 'waiting for the owner, the session is let go: ' + reason, 'stop_waiting_owner', session=session)
            return 0
        session_state(root, session, {'owner_wait': key, 'stop_blocks': 0})
        record(root, plan, 'stop_blocked', 'Stop', reason, 'stop_owner_wait', session=session)
        print(json.dumps({'decision': 'block', 'reason': reason}, ensure_ascii=False))
        return 0
    reason = (f"Plan {plan['plan']} is not delivered yet; run `{moves['command']}` (or `onecrew plan amend {plan['plan']}` to change the contract). Do not say it is done." if moves else
              f"Milestone {pending['id']} ({pending['title']}) has no passing verdict; run `onecrew verdict run --plan {plan['plan']} --milestone {pending['id']}` "
              f"(or `onecrew plan amend {plan['plan']}` to change the contract). Do not say it is done.")
    if plan.get('mode') != 'enforce':
        record(root, plan, 'logged', 'Stop', 'would block: ' + reason, 'stop_pending_milestone', session=session)
        return 0
    if state.get('stop_blocks', 0) >= STOP_BLOCK_CAP:
        record(root, plan, 'logged', 'Stop', f'stop block cap ({STOP_BLOCK_CAP}) reached; the session is let go: ' + reason, 'stop_cap', session=session)
        session_state(root, session, {'stop_blocks': 0})
        return 0
    session_state(root, session, {'stop_blocks': state.get('stop_blocks', 0) + 1})
    record(root, plan, 'stop_blocked', 'Stop', reason, 'stop_pending_milestone', session=session)
    print(json.dumps({'decision': 'block', 'reason': reason}, ensure_ascii=False))
    return 0


def session(args):
    event, _ = read_stdin()
    note_call(event)
    plan, root, bad, _ = governing(args, event)
    if plan is None: return 0
    plan = refreshed(root, plan)
    budget = plan.get('budget') or {}
    pending = next((m for m in plan.get('milestones', []) if m.get('state') != 'passed'), None)
    lines = [f"OneCrew contract {plan.get('plan')} v{plan.get('revision')} [{plan.get('status')}, hook mode {plan.get('mode')}]: {plan.get('title')}",
             'Output: ' + '; '.join(plan.get('output', []))[:400],
             'You may change only: ' + ', '.join(plan.get('owned', [])[:12]) + (' ...' if len(plan.get('owned', [])) > 12 else '')]
    lines += ['Not goals: ' + '; '.join(plan.get('non_goals', []))[:300]] if plan.get('non_goals') else []
    lines.append(f"Budget: {budget.get('max_calls')} calls, {budget.get('time')} minutes (the ledger holds the remaining amount).")
    lines += [f"Milestones: {', '.join(m['id'] + '=' + m['state'] for m in plan.get('milestones', []))}",
              f"Next: {pending['id'] + ' ' + pending['title'] if pending else 'all milestones passed; the owner accepts'}",
              'Not yours: plan approve/accept/enforce, verdict record --by owner, push, tag. Do not say "done" before the verdict.',
              'Change the contract with `onecrew plan amend` (owner approves).']
    text = '\n'.join(lines[:25])
    name = event.get('hook_event_name') or 'SessionStart'
    if name != 'SessionStart': return 0                 # PreCompact has no documented way to add context; SessionStart(source=compact) follows it
    print(json.dumps({'hookSpecificOutput': {'hookEventName': 'SessionStart', 'additionalContext': text}}, ensure_ascii=False))
    return 0


def sync(args):
    """Import violations.jsonl into the ledger as hook.* events on the plan's anchor task. Idempotent (by line id)."""
    from ..ledger import Ledger
    from . import plan as plans
    plan, root, _, _ = governing(args, {})
    if plan is None: raise ValueError('No active plan found for this project; pass --project (and --state-root).')
    ledger = Ledger(root, where.state_root_for(root, args.state_root) or plan.get('state_root'))
    spool = root / '.onecrew' / 'violations.jsonl'
    lines = spool.read_text(encoding='utf-8', errors='replace').splitlines() if spool.exists() else []
    added = skipped = 0
    with ledger.transaction(write=True) as conn:
        for line in lines:
            try:
                item = json.loads(line)
                kind = HOOK_KINDS[item['event']]
                state = plans.derive(ledger, conn, item['plan'])
                if state is None: raise KeyError('plan')
            except (ValueError, KeyError, TypeError):
                skipped += 1
                continue
            if conn.execute("SELECT 1 FROM events WHERE task_id=? AND kind=? AND json_extract(payload,'$.spool_id')=?", (state['task_id'], kind, item['id'])).fetchone(): continue
            plans.emit(ledger, conn, state['task_id'], kind, dict({k: item.get(k) for k in ('plan', 'revision', 'tool', 'rule', 'reason', 'subject', 'mode', 'session', 'agent_id', 'agent_type', 'tool_use_id', 'scope')},
                                                                   spool_id=item['id'], recorded_at=item.get('at')))
            added += 1
    return {'imported': added, 'skipped': skipped, 'lines': len(lines)}


HOOK_EVENTS = (('PreToolUse', 'check', 15, 'Edit|Write|MultiEdit|NotebookEdit|Bash|PowerShell', 'block'),     # only the tool gate fails closed: a crashing
               ('UserPromptSubmit', 'prompt', 10, None, 'continue'),                                         # prompt/stop hook must not lock the session
               ('Stop', 'stop', 30, None, 'continue'),
               ('SessionStart', 'session', 30, 'startup|resume|clear|compact', 'continue'))
OWNER_DENY = ('plan approve', 'plan accept', 'plan enforce', 'verdict record', 'hook mode', 'plan unknown close*owner', 'plan poc record*owner',
              'owner approve', 'owner accept', 'owner enforce', 'owner record', 'owner answer', 'question answer',
              'support confirm', 'support target add', 'support rollback', 'support cleanup*--v')    # owner-only entry points


def build_settings(handler, state_root):
    """{'hooks', 'permissions'}; handler(verb, timeout, fail) is the handler dict of one hook event."""
    def entry(verb, timeout, matcher, fail):
        return dict({'matcher': matcher} if matcher else {}, hooks=[handler(verb, timeout, fail)])
    return {'hooks': {event: [entry(verb, timeout, matcher, fail)] for event, verb, timeout, matcher, fail in HOOK_EVENTS},
            'permissions': {'deny': deny_rules(state_root)}}


def portable_settings(exe, state_root):
    """What `onecrew init` writes: the installed `onecrew` executable runs `hook <verb>`; the project comes from CLAUDE_PROJECT_DIR and the state
    root from <project>/.onecrew/config.json, so no handler names a repo, an interpreter or a state root."""
    return build_settings(lambda verb, timeout, fail: {'type': 'command', 'command': str(exe), 'args': ['hook', verb], 'timeout': timeout, 'onFailure': fail},
                          state_root)


def settings(project, state_root, repo):
    """The checkout form (`hook install --print` from onecrew_cli.py): this interpreter runs the checkout's hook_cli with explicit --project/--state-root."""
    code = f"import sys; sys.path.insert(0, {str(repo)!r}); from onecrew.v2.hook_cli import main; sys.exit(main(sys.argv[1:]))"
    return build_settings(lambda verb, timeout, fail: {'type': 'command', 'command': sys.executable,
                                                       'args': ['-c', code, '--project', str(project), '--state-root', str(state_root), 'hook', verb],
                                                       'timeout': timeout, 'onFailure': fail}, state_root)


def deny_rules(state_root):
    """permissions.deny: the one list the checkout print and `onecrew init` both write."""
    root = str(state_root).replace('\\', '/')
    deny = ['Edit(//' + root.lstrip('/') + '/**)',                       # Edit rules cover Write, MultiEdit and NotebookEdit too
            'Edit(//' + str(where.registry_file()).replace('\\', '/').lstrip('/') + ')',      # the registry of project -> state root, outside the project
            'Edit(**/plans/**)', 'Edit(**/*.sqlite*)', 'Edit(.onecrew/active-plan.json)', 'Edit(.onecrew/violations.jsonl)', 'Edit(.onecrew/hook-state.json)', 'Edit(.onecrew/config.json)',
            'Edit(.claude/settings*.json)',
            'Bash(git push:*)', 'Bash(git * push*)', 'PowerShell(git push *)', 'PowerShell(git * push*)',
            'Bash(*git.exe*push*)', 'PowerShell(*git.exe*push*)', 'Bash(*send-pack*)', 'PowerShell(*send-pack*)', 'Bash(*http-push*)', 'PowerShell(*http-push*)',   # C9
            'Bash(*git.cmd*push*)', 'PowerShell(*git.cmd*push*)', 'Bash(*-c*alias.*push*)', 'PowerShell(*-c*alias.*push*)',   # C14: git.cmd and an alias given with -c
            'Bash(*-c*alias.*send-pack*)', 'PowerShell(*-c*alias.*send-pack*)', 'Bash(*--config-env*)', 'PowerShell(*--config-env*)',
            'Bash(git config * alias.*)', 'PowerShell(git config * alias.*)',
            'Edit(//' + str(Path.home()).replace('\\', '/').lstrip('/') + '/.claude/CLAUDE.md)', 'Edit(//' + str(Path.home()).replace('\\', '/').lstrip('/') + '/.claude/agents/**)']
    for verb in OWNER_DENY:
        deny += ['Bash(*' + verb + '*)', 'PowerShell(*' + verb + '*)']                # git tag is left to the hook: a permission rule cannot tell `git tag -l` from `git tag v1`
    return deny


def parser():
    root = argparse.ArgumentParser(prog='onecrew')
    root.add_argument('--project', type=Path); root.add_argument('--state-root', type=Path)
    verbs = root.add_subparsers(dest='group', required=True).add_parser('hook', help='Claude Code hooks for the active plan.').add_subparsers(dest='verb', required=True)
    for name, text in (('check', 'PreToolUse: block edits/commands outside the plan (stdin JSON).'), ('prompt', 'UserPromptSubmit: remind, never block.'),
                       ('stop', 'Stop: no "done" without a passing verdict (at most 2 blocks per session).'),
                       ('session', 'SessionStart: contract summary as additionalContext.'),
                       ('sync', 'Import violations.jsonl into the ledger.'), ('export', 'Re-export active-plan.json.')):
        p = verbs.add_parser(name, help=text)
        if name == 'export': p.add_argument('plan')
        if name == 'check': p.add_argument('--scope', choices=['project', 'user'], default='project', help='user: the hook installed by `hook user install` (#25).')
    p = verbs.add_parser('mode', help='Owner only: log or enforce.'); p.add_argument('mode', choices=['log', 'enforce']); p.add_argument('--by', required=True)
    p.add_argument('--plan'); p.add_argument('--reference', required=True)
    p = verbs.add_parser('install', help='Print the hooks and permissions.deny settings (never edits a settings file).')
    p.add_argument('--print', dest='show', action='store_true', required=True)
    p = verbs.add_parser('user', help='Owner only: install|status|uninstall the user-scope hook (#25).')
    p.add_argument('action', choices=['install', 'status', 'uninstall'])
    p.add_argument('--settings-file', type=Path); p.add_argument('--program', type=Path)
    return root


def main(argv=None):
    utf8_streams()          # before anything is printed, whichever way the hook was started (this module through `python -c`, or the installed `onecrew hook <verb>`)
    args = parser().parse_args(argv)
    if args.group != 'hook': return 2
    if args.verb in ('check', 'prompt', 'stop', 'session'):
        return {'check': check, 'prompt': prompt, 'stop': stop, 'session': session}[args.verb](args)
    if args.verb == 'user':                  # #25: no ledger, no project: a file of the user's own
        from . import install
        return install.user_hook(args.action, args.settings_file, args.program)
    from ..ledger import Ledger, LedgerError
    try:
        project = Path(args.project or os.environ.get('CLAUDE_PROJECT_DIR') or Path.cwd())
        state_root = where.state_root_for(project, args.state_root)       # G2: config.json of the project when no --state-root
        if args.verb == 'sync': out = sync(args)
        elif args.verb == 'install':
            repo = Path(__file__).resolve().parents[2]
            out = settings(project.resolve(), Path(Ledger(project, state_root).state_root), repo)
        else:
            from . import active_plan
            from .plan import require_owner
            ledger = Ledger(project, state_root)
            if args.verb == 'mode':
                require_owner(args.by, 'Changing the hook mode')
                from .ownership import refuse_in_ai_session
                refuse_in_ai_session('Changing the hook mode')
                found = find_plan_file([project])
                name = args.plan or (load_plan(found)[0].get('plan') if found else None)
                if not name:
                    raise LedgerError('Select an approved plan before changing hook mode; no mode was changed.')
                try:
                    document = active_plan.build(ledger, name)
                except (LedgerError, ValueError, OSError) as error:
                    raise LedgerError(str(error) + '; no mode was changed.') from error
                if document is None:
                    raise LedgerError('Plan ' + name + ' has never been approved; no mode was changed.')
                # Validate the named grant before the first mode write. A later
                # export failure still reports the policy effect truthfully.
                out = {'mode': active_plan.set_mode(ledger, args.mode), 'mode_committed': True,
                       'plan': document['plan'], 'revision': document['revision'], 'exported': False}
                try:
                    out['exported'] = bool(active_plan.export(ledger, name, take_over=True))      # dev25: the owner chooses the governing plan
                    if not out['exported']: raise LedgerError('Active-plan export did not complete; see the retained export warning for its cause. The mode was already written.')
                except (LedgerError, ValueError, OSError) as error:
                    print(json.dumps(dict(out, error=str(error), type=type(error).__name__), ensure_ascii=False))
                    return 2
            else:
                out = active_plan.export(ledger, args.plan, strict=True)      # dev25: refreshes the governing plan; switching it is the owner's
                if out is None: raise LedgerError('Plan ' + args.plan + ' has never been approved; nothing to export.')
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0
    except (LedgerError, ValueError, OSError) as error:
        print(json.dumps({'error': str(error), 'type': type(error).__name__}, ensure_ascii=False))
        return 2


if __name__ == '__main__':
    sys.exit(main())
