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
import datetime as dt
import fnmatch
import json
import os
import re
import sys
import tempfile
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


def record(project, plan, event, tool, reason, rule, subject='', session=None, mode=None):
    """Append to <project>/.onecrew/violations.jsonl (no ledger lock). Only when .onecrew/ exists: a repo without a plan stays untouched."""
    folder = Path(project) / '.onecrew'
    try:
        folder.mkdir(exist_ok=True)                      # a plan governs this project, so the record goes in even if .onecrew/ was deleted
    except OSError:
        return
    line = {'id': uuid.uuid4().hex, 'at': now(), 'event': event, 'tool': tool, 'rule': rule, 'reason': reason[:400], 'subject': subject[:300],
            'plan': (plan or {}).get('plan'), 'revision': (plan or {}).get('revision'), 'mode': mode or (plan or {}).get('mode'), 'session': session}
    try:
        with (folder / 'violations.jsonl').open('a', encoding='utf-8') as stream: stream.write(json.dumps(line, ensure_ascii=False) + '\n')
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


def judge_path(plan, root, target, action):
    """(rule, reason) when this plan forbids writing to `target`, else None."""
    rel = relative(target, root)
    scratch = [normalize(s, root) if not os.path.isabs(s) else Path(s).resolve() for s in plan.get('scratch', [])]
    if rel is not None and under(rel, '.onecrew/scratch'): return None
    home = Path.home().resolve() / '.claude'
    guarded = [normalize(p, root) for p in plan.get('protected', [])] + [home / 'settings.json', home / 'settings.local.json', where.registry_file().resolve()]      # the registry: the owner's pointer to the state root
    for item in guarded:
        if target == item or item in target.parents:
            return 'protected', f'{target} is protected: the ledger, plans/ and hook files are the owner\'s, not the AI\'s. {action}'
    if rel is not None:
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

REDIRECT = re.compile(r'(?<![<>&-])\d?>>?(?![&>])\s*("[^"]*"|\'[^\']*\'|[^\s;|&<>()]+)')
EVERY = ('rm', 'del', 'erase', 'rd', 'rmdir', 'ri', 'remove-item', 'mkdir', 'md', 'touch', 'tee')        # every plain word is a target
FIRST = ('set-content', 'sc', 'add-content', 'ac', 'out-file', 'tee-object', 'new-item', 'ni', 'export-csv', 'export-clixml')   # the first one is
COPY = ('cp', 'mv', 'copy', 'move', 'copy-item', 'cpi', 'move-item', 'mi', 'ren', 'rename', 'rename-item', 'rni')              # the last one is
NAMED = ('-path', '-filepath', '-literalpath', '-destination', '-name')
WRITERS = re.compile(r'(?:^|[\s;|&(])(' + '|'.join(re.escape(n) for n in sorted(EVERY + FIRST + COPY, key=len, reverse=True)) + r')(?=\s)'
                     r'((?:\s+(?:-\w+\s+\S+|-\w+|"[^"]*"|\'[^\']*\'|[^\s;|&<>-][^\s;|&<>]*))+)', re.I)
DOTNET = re.compile(r'\[(?:System\.)?IO\.(?:File|Directory)\]::(\w+)\(\s*("[^"]*"|\'[^\']*\'|[^,)\s]+)(?:\s*,\s*("[^"]*"|\'[^\']*\'|[^,)\s]+))?', re.I)
SED_I = re.compile(r'\bsed\s+(?:-\w*i\w*|--in-place)\b[^|;&]*?\s("[^"]+"|\'[^\']+\'|[^\s;|&<>]+)\s*(?:[;|&]|$)', re.I)


def shell_targets(command):
    """Paths a shell command text appears to write. Heuristic: redirects, tee/Set-Content/sc/ac/Out-File/Tee-Object/cp/mv/rm/ri..., [IO.File]::, sed -i."""
    found = [m.group(1).strip('"\'') for m in REDIRECT.finditer(command)]
    for m in WRITERS.finditer(command):
        cmd, words = m.group(1).lower(), re.findall(r'"[^"]*"|\'[^\']*\'|\S+', m.group(2))
        named = [words[i + 1] for i, w in enumerate(words[:-1]) if w.lower() in NAMED]
        plain = [w for w in words if not w.startswith('-')]
        if cmd in EVERY: values = plain + named
        elif cmd in COPY: values = named[-1:] or plain[-1:]
        else:                                           # FIRST: -Value / -Encoding take a value, so only the first plain word counts
            values = named[:1] or [w for i, w in enumerate(words) if not w.startswith('-') and not (i and words[i - 1].startswith('-'))][:1]
        found += [v.strip('"\'') for v in values]
    for m in DOTNET.finditer(command):                  # the second argument is a path only for Copy / Move / Replace (WriteAllText takes the content)
        found += [g.strip('"\'') for g in ((m.group(2), m.group(3)) if m.group(1).lower() in ('copy', 'move', 'replace') else (m.group(2),)) if g]
    found += [m.group(1).strip('"\'') for m in SED_I.finditer(command)]
    return [f for f in found if f]


QUOTED = re.compile(r"\"([^\"]{3,})\"|'([^']{3,})'")


CUE = re.compile(r'\b(?:iex|invoke-expression|powershell(?:\.exe)?|pwsh|cmd(?:\.exe)?|bash|sh|zsh|dash|eval|invoke-command|start-process|wsl)\b', re.I)


def all_targets(command, depth=0):
    """C10: shell_targets of the command as written, without backticks/carets, and (recursively, up to 3 levels) of each quoted part that follows an
    interpreter (`iex 'sc README.md x'`, `powershell -c "sc ..."`, `cmd /c "..."`, `bash -c '...'`), so a write nested in a string is judged like one
    typed plainly. Only text after such a cue is read as a command: a commit message "Move a to b" is not a move. A quoted path with a space
    may show up cut at the space, which errs on the side of blocking."""
    cleaned = re.sub(r'[`^]', '', command)
    found = shell_targets(command)
    if cleaned != command: found += shell_targets(cleaned)
    if depth < 3:
        for text in dict.fromkeys((command, cleaned)):
            for m in QUOTED.finditer(text):
                if CUE.search(re.split(r'[;&|\n]', text[:m.start()])[-1]): found += all_targets(m.group(1) or m.group(2), depth + 1)
    return list(dict.fromkeys(found))


def variants(command):
    """The command as written, without quotes/backticks/carets, and without backslashes too: `plan "approve"` and `plan app\rove` still name approve."""
    unquoted = re.sub(r'["\'`^]', '', command)
    return [command, unquoted, unquoted.replace('\\', '')]


def shell_segments(command):
    """The command cut at `;`, `&&`, `||`, `|`, a lone `&` and line ends, outside quotes: a quoted string stays in the segment that holds it."""
    parts, current, quote, i = [], [], None, 0
    while i < len(command):
        char = command[i]
        if quote:
            current.append(char)
            if char == '\\' and quote == '"' and i + 1 < len(command) and command[i + 1] in '"\\':
                current.append(command[i + 1]); i += 1
            elif char == quote: quote = None
        elif char in '"\'': quote = char; current.append(char)
        elif char in ';|&\n':
            parts.append(''.join(current)); current = []
            while i + 1 < len(command) and command[i + 1] in '|&' and char in '|&': i += 1       # `&&` and `||` are one cut
        else: current.append(char)
        i += 1
    parts.append(''.join(current))
    return [p for p in parts if p.strip()]


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


def judge_shell(plan, root, cwd, command, limited=False):
    """The plan's verdict on a shell command. `limited` is a plan that is not the session's (it was reached through the cwd or through a path the command
    writes): the deny and mention rules apply, since the command runs there, but only the paths the command writes INSIDE that plan's repository are
    judged, and a path the hook cannot resolve is left to the session's plan."""
    forms = variants(command)
    for entry in plan.get('bash_deny', []):
        for form in forms:
            hit = re.search(entry[3:], form, re.I) if entry.startswith('re:') else (entry.casefold() in form.casefold())
            if hit: return 'bash_deny', f'The command matches the deny rule "{entry[3:] if entry.startswith("re:") else entry}". Approval, acceptance, enforcement, push, tag and installs are the owner\'s. Ask the owner in chat.'
    items = [_fold(plan.get('state_root', '')) + '/plans', 'policy.json', '.sqlite', 'active-plan.json', 'violations.jsonl', 'hook-state.json', where.REGISTRY, '.claude/settings',
             '.onecrew', 'onecrew/plans']
    for segment in shell_segments(command):         # each segment on its own: `ls; python -c "...remove(registry)"` is not read-only because its first word is
        first = (re.findall(r'[\w.-]+', segment) or [''])[0].lower()
        if first in READ_ONLY: continue
        flat = _fold(' '.join(variants(segment))).replace('.onecrew/scratch', '')
        for item in items:
            if item in flat:
                return 'protected', f'The command mentions {item}, which only the owner changes ({first or "?"} is not a read-only command).'
    for raw in all_targets(command):
        lowered = raw.casefold()
        if lowered in NULLS: continue
        if lowered.startswith(TEMP_VARS): continue
        if re.search(r'[$%`]', raw):
            if limited: continue
            return 'unresolvable_target', f'The command writes to "{raw}", a path the hook cannot resolve; write to a literal path inside the owned scope.'
        target = normalize(raw, cwd)
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
            for raw in all_targets(data['command']):
                if re.search(r'[$%`]', raw) or raw.casefold() in NULLS or raw.casefold().startswith(TEMP_VARS): continue
                if inside_repo(root, normalize(raw, base)): return True
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


def _shell_target_dirs(command, base):
    """The folders that hold the paths a shell command appears to write (all_targets, resolved against `base`; a target the hook cannot resolve is skipped
    here, judge_shell refuses it on its own)."""
    found = []
    for raw in all_targets(command):
        if re.search(r'[$%`]', raw) or raw.casefold() in NULLS or raw.casefold().startswith(TEMP_VARS): continue
        try:
            folder = _nearest_dir(normalize(raw, base).parent)
        except (OSError, ValueError):
            continue
        if folder is not None and folder not in found: found.append(folder)
    return found


SESSION, LIMITED = 'session', 'limited'


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
        if cwd: places.append((cwd, LIMITED))
        if isinstance(command, str): places += [(folder, LIMITED) for folder in _shell_target_dirs(command, cwd or os.environ.get('CLAUDE_PROJECT_DIR') or os.getcwd())]
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
        elif role == SESSION: seen[key][3] = SESSION          # a repository reached both ways is the session's
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
    return any(project_plan.get(k) != copy_plan.get(k) for k in ('plan', 'revision', 'plan_sha', 'mode', 'owned', 'non_goals', 'bash_deny', 'protected', 'scratch'))


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


def check(args):
    """Exit 2 when ANY plan that applies to the call blocks it. The plans are the session's (its project: judges the whole call) and the plans of the other
    repositories the call reaches (the repository that holds a path it writes; for a shell command also the one that holds its cwd), which judge only what
    the call does inside their own repository. A plan that is accepted, in log mode, only proposed or not there at all never lets through what another plan
    blocks. No plan anywhere: nothing to enforce."""
    event, bad_input = read_stdin()
    code = 0
    for project_copy, project_root, copy, role in locate_all(args, event):
        plan, root, bad_plan, source = govern(project_copy, project_root, copy)
        if plan is not None and judge_call(plan, root, bad_plan, source, event, bad_input, limited=role != SESSION) == 2: code = 2
    return code


def judge_call(plan, root, bad_plan, source, event, bad_input, limited=False):
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
        if plan.get('status') not in ('approved', 'stopped_with_report'):
            return 0
        expires = plan.get('expires')
        if touched and expires and dt.datetime.fromisoformat(expires) < dt.datetime.now(dt.timezone.utc):
            raise ValueError('the active plan expired; the owner re-approves it (plan approve) to refresh it')
        data = event.get('tool_input') if isinstance(event.get('tool_input'), dict) else {}
        verdict = None
        if plan.get('status') == 'stopped_with_report' and touched:      # first in the chain and not tool-specific: edits and shell commands alike get this verdict
            verdict = ('stopped', f"Plan {plan.get('plan')} is stopped_with_report: the owner decides the next step; nothing further is changed. "
                                  f"Every shell command and every edit is refused; read the evidence with Read, Grep and Glob.")
        elif tool in EDIT_TOOLS:
            raw = next((data[k] for k in PATH_KEYS if isinstance(data.get(k), str) and data[k]), None)
            if raw is None: raise ValueError(f'{tool} call without a path field ({"/".join(PATH_KEYS)})')
            verdict = judge_path(plan, root, normalize(raw, base), 'Do not edit it.') if touched else None
        elif tool in SHELL_TOOLS:
            if not isinstance(data.get('command'), str): raise ValueError(f'{tool} call without command')
            verdict = judge_shell(plan, root, base, data['command'], limited=limited)
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
        from . import active_plan
        ledger = Ledger(Path(plan['project']), Path(plan['state_root']))
        fresh = active_plan.build(ledger, plan['plan'])
        if fresh:
            fresh['expires'] = plan.get('expires', fresh['expires'])   # a session start must not renew the owner's approval window
            active_plan._write(active_plan.project_file(root), fresh)                               # both copies, so they keep agreeing
            active_plan._write(Path(plan['state_root']) / 'plans' / plan['plan'] / FILE, fresh)
            return fresh
    except Exception:                                    # noqa: BLE001 - a stale file is better than no answer
        pass
    return plan


def stop(args):
    event, _ = read_stdin()
    plan, root, bad, _ = governing(args, event)
    if plan is None: return 0
    plan = refreshed(root, plan)
    session = event.get('session_id')
    pending = next((m for m in plan.get('milestones', []) if m.get('state') != 'passed'), None)
    if plan.get('status') != 'approved' or pending is None:
        session_state(root, session, {'stop_blocks': 0})
        return 0
    waiting = plan.get('waiting') or {}
    if waiting.get('receipt_without_verdict') or waiting.get('open_questions'):
        # The turn can end: what is missing is not the session's to do. A receipt waits for its verdict (verdict run records it), or the owner
        # has an open question. Nothing else lets go of an unfinished plan; the cap below still applies to it.
        what = ('a receipt without a verdict for ' + ', '.join(waiting['receipt_without_verdict'])) if waiting.get('receipt_without_verdict') else ''
        what += ('; ' if what else '') + ('an open owner question (' + ', '.join(waiting['open_questions']) + ')') if waiting.get('open_questions') else ''
        record(root, plan, 'logged', 'Stop', f"waiting, the session is let go: {what}; milestone {pending['id']} ({pending['title']}) has no verdict yet", 'stop_waiting', session=session)
        return 0
    state = session_state(root, session)
    reason = (f"Milestone {pending['id']} ({pending['title']}) has no passing verdict; run `onecrew verdict run --plan {plan['plan']} --milestone {pending['id']}` "
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
            plans.emit(ledger, conn, state['task_id'], kind, dict({k: item.get(k) for k in ('plan', 'revision', 'tool', 'rule', 'reason', 'subject', 'mode', 'session')},
                                                                   spool_id=item['id'], recorded_at=item.get('at')))
            added += 1
    return {'imported': added, 'skipped': skipped, 'lines': len(lines)}


HOOK_EVENTS = (('PreToolUse', 'check', 15, 'Edit|Write|MultiEdit|NotebookEdit|Bash|PowerShell', 'block'),     # only the tool gate fails closed: a crashing
               ('UserPromptSubmit', 'prompt', 10, None, 'continue'),                                         # prompt/stop hook must not lock the session
               ('Stop', 'stop', 30, None, 'continue'),
               ('SessionStart', 'session', 30, 'startup|resume|clear|compact', 'continue'))
OWNER_DENY = ('plan approve', 'plan accept', 'plan enforce', 'verdict record', 'hook mode', 'plan unknown close*owner', 'plan poc record*owner',
              'owner approve', 'owner accept', 'owner enforce', 'owner record')    # any way of calling onecrew (venv python, -X utf8, onecrew.cmd); C13: an AI may still close an unknown with --by doc|poc


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
    p = verbs.add_parser('mode', help='Owner only: log or enforce.'); p.add_argument('mode', choices=['log', 'enforce']); p.add_argument('--by', required=True)
    p.add_argument('--plan'); p.add_argument('--reference', required=True)
    p = verbs.add_parser('install', help='Print the hooks and permissions.deny settings (never edits a settings file).')
    p.add_argument('--print', dest='show', action='store_true', required=True)
    return root


def main(argv=None):
    utf8_streams()          # before anything is printed, whichever way the hook was started (this module through `python -c`, or the installed `onecrew hook <verb>`)
    args = parser().parse_args(argv)
    if args.group != 'hook': return 2
    if args.verb in ('check', 'prompt', 'stop', 'session'):
        return {'check': check, 'prompt': prompt, 'stop': stop, 'session': session}[args.verb](args)
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
                out = {'mode': active_plan.set_mode(ledger, args.mode)}
                found = find_plan_file([project])
                name = args.plan or (load_plan(found)[0].get('plan') if found else None)
                out['exported'] = bool(name and active_plan.export(ledger, name))
            else:
                out = active_plan.export(ledger, args.plan)
                if out is None: raise LedgerError('Plan ' + args.plan + ' has never been approved; nothing to export.')
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0
    except (LedgerError, ValueError, OSError) as error:
        print(json.dumps({'error': str(error), 'type': type(error).__name__}, ensure_ascii=False))
        return 2


if __name__ == '__main__':
    sys.exit(main())
