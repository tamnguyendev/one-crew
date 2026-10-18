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
Only stdlib at import time: `check` runs before every tool call.
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

def find_plan_file(candidates, walk=True):
    """First <dir>/.onecrew/active-plan.json found (walking up from each candidate directory unless walk is False)."""
    for start in candidates:
        if not start: continue
        try:
            here = Path(start).resolve()
        except OSError:
            continue
        for directory in ((here, *here.parents) if walk else (here,)):
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
    guarded = [normalize(p, root) for p in plan.get('protected', [])] + [home / 'settings.json', home / 'settings.local.json']
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
    where = rel if rel is not None else f'{target} (outside the project)'
    return 'outside_owned', f'{where} is not in the owned scope. {rules_text(plan)}'


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


def judge_shell(plan, root, cwd, command):
    forms = variants(command)
    for entry in plan.get('bash_deny', []):
        for form in forms:
            hit = re.search(entry[3:], form, re.I) if entry.startswith('re:') else (entry.casefold() in form.casefold())
            if hit: return 'bash_deny', f'The command matches the deny rule "{entry[3:] if entry.startswith("re:") else entry}". Approval, acceptance, enforcement, push, tag and installs are the owner\'s. Ask the owner in chat.'
    first = (re.findall(r'[\w.-]+', command) or [''])[0].lower()
    flat = _fold(' '.join(forms)).replace('.onecrew/scratch', '')
    for item in [_fold(plan.get('state_root', '')) + '/plans', 'policy.json', '.sqlite', 'active-plan.json', 'violations.jsonl', 'hook-state.json', '.claude/settings',
                 '.onecrew', 'onecrew/plans']:
        if item in flat and first not in READ_ONLY:
            return 'protected', f'The command mentions {item}, which only the owner changes ({first or "?"} is not a read-only command).'
    for raw in all_targets(command):
        lowered = raw.casefold()
        if lowered in NULLS: continue
        if lowered.startswith(TEMP_VARS): continue
        if re.search(r'[$%`]', raw):
            return 'unresolvable_target', f'The command writes to "{raw}", a path the hook cannot resolve; write to a literal path inside the owned scope.'
        verdict = judge_path(plan, root, normalize(raw, cwd), 'The command writes there.')
        if verdict: return verdict
    return None


# ---- a stopped plan: reading stays possible --------------------------------------------------------------------------------

STOPPED_READ = {'cat', 'type', 'get-content', 'gc', 'ls', 'dir', 'get-childitem', 'gci', 'head', 'tail', 'grep', 'rg', 'select-string', 'findstr',
                'wc', 'pwd', 'cd', 'set-location'}
GIT_READ = {'status', 'log', 'diff', 'show', 'rev-parse', 'blame'}
GIT_EXEC = ('--output', '--ext-diff', '--textconv', '--open-files-in-pager', '--exec')
FIND_WRITE = {'-delete', '-exec', '-execdir', '-ok', '-okdir', '-fprint', '-fprint0', '-fprintf', '-fls'}
ONECREW_READ = {'plan': {'show', 'precheck'}, 'verdict': {'show'}}
SHELL_TOKEN = re.compile(r'"[^"]*"|\'[^\']*\'|&&|\|\||[;|&\n]|[^\s;|&"\']+')


def _program(token):
    name = re.split(r'[\\/]', token)[-1].lower()
    return name[:-4] if name.endswith('.exe') else name


def _read_only_segment(words):
    program, rest = _program(words[0]), words[1:]
    if program in STOPPED_READ: return not (program == 'rg' and any(w.startswith(('--pre', '--hostname-bin')) for w in rest))
    if program == 'find': return not any(w.lower() in FIND_WRITE for w in rest)
    if program == 'git':
        return bool(rest) and rest[0] in GIT_READ and not any(w.startswith(GIT_EXEC) for w in rest)
    tail = None
    if program in ('onecrew', 'onecrew.cmd'): tail = rest
    elif program.startswith('python') or program == 'py':
        i = 0
        while i < len(rest) and rest[i].startswith('-') and rest[i] != '-m': i += 2 if rest[i] == '-X' else 1
        if i < len(rest) and (_program(rest[i]) == 'onecrew_cli.py' or (rest[i] == '-m' and i + 1 < len(rest) and rest[i + 1] == 'onecrew')):
            tail = rest[i + 2:] if rest[i] == '-m' else rest[i + 1:]
    if tail is None: return False
    i = 0
    while i < len(tail) and tail[i].startswith('--'): i += 1 if '=' in tail[i] else 2        # global options (--project X, --state-root X) come before the verb
    return i + 1 < len(tail) and tail[i] in ONECREW_READ and tail[i + 1] in ONECREW_READ[tail[i]]


def read_only_command(command):
    """True only when every part of a shell command is a known read-only command (allowlist, fail closed). Redirects, command substitution and
    anything outside the list are not read-only: a stopped plan lets the AI look at the evidence, never change anything."""
    if re.search(r'`|\$\(|\$\{|<\(|\\["\']', command) or len(command) > 2000: return False      # an escaped quote makes the hook and the shell disagree on where a string ends
    if re.search('["\']', re.sub(r'"[^"]*"|\'[^\']*\'', '', command)): return False            # an unclosed quote: the rest of the line is a string to us and commands to the shell
    segments, current = [], []
    for token in SHELL_TOKEN.findall(command):
        if token in ('&&', '||', ';', '|', '&', '\n'):
            segments.append(current); current = []
        elif token.startswith(('"', "'")):
            if re.search(r'[;|&\n]', token): return False                                          # a separator inside a string is refused rather than guessed at
            current.append(token[1:-1])
        else:
            if re.search(r'[<>()]', token): return False                                           # redirects, and PowerShell (cmd) / @(cmd) that runs a command inside an argument
            current.append(token)
    segments.append(current)
    segments = [s for s in segments if s]
    return bool(segments) and all(_read_only_segment(s) for s in segments)


# ---- the verbs -------------------------------------------------------------------------------------------------------------

def read_stdin():
    try:
        data = json.loads(sys.stdin.buffer.read().decode('utf-8-sig') or 'null')
        if not isinstance(data, dict): return {}, 'stdin is not a JSON object'
        return data, None
    except (ValueError, OSError) as error:
        return {}, f'{type(error).__name__}: {error}'


def locate(args, event):
    """(plan_file, project root) of the plan that governs this call, or (None, None).

    B1: the project copy `<project>/.onecrew/active-plan.json` is the first source and the state-root copy `<state-root>/plans/<name>/active-plan.json`
    (written at the same time, outside the project) is the second. Deleting `.onecrew/` therefore does not end enforcement: a state-root copy that
    names this project brings the plan back, and a project copy that disagrees with it is treated as tampered with (see `tampered`)."""
    explicit = Path(args.project) if args.project else None
    project_copy = find_plan_file([explicit], walk=False) if explicit else find_plan_file([os.environ.get('CLAUDE_PROJECT_DIR'), event.get('cwd'), os.getcwd()])
    root = project_copy.parent.parent if project_copy else explicit
    if root is None: return None, None, None
    copy = state_copy(args.state_root, root)
    return project_copy, root, copy


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
    """(plan, root, error, source). error is a text when the files disagree or cannot be read; source tells where the plan came from."""
    project_copy, root, copy = locate(args, event)
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
    event, bad_input = read_stdin()
    plan, root, bad_plan, source = governing(args, event)
    if plan is None: return 0                           # no plan anywhere (project copy and state-root copy): nothing to enforce
    mode = 'enforce' if plan.get('mode') == 'enforce' else 'log'
    session, tool = event.get('session_id'), event.get('tool_name') or '?'
    if source == 'restored': record(root, plan, 'logged', tool, '.onecrew/active-plan.json was missing and was restored from the state root', 'plan_restored', session=session, mode=mode)
    try:
        if bad_input or bad_plan: raise ValueError(bad_input or bad_plan)
        if plan.get('status') not in ('approved', 'stopped_with_report'):
            return 0
        expires = plan.get('expires')
        if expires and dt.datetime.fromisoformat(expires) < dt.datetime.now(dt.timezone.utc):
            raise ValueError('the active plan expired; the owner re-approves it (plan approve) to refresh it')
        base = event.get('cwd') or root
        data = event.get('tool_input') if isinstance(event.get('tool_input'), dict) else {}
        verdict = None
        if plan.get('status') == 'stopped_with_report':
            # Edits, writes and anything not on the read-only allowlist stay refused; looking at the evidence (cat, git status, plan show) does not.
            if tool in SHELL_TOOLS and isinstance(data.get('command'), str) and read_only_command(data['command']):
                verdict = judge_shell(plan, root, base, data['command'])
            else:
                verdict = ('stopped', f"Plan {plan.get('plan')} is stopped_with_report: the owner decides the next step; nothing further is changed "
                                      f"(read-only commands such as cat, ls, git status|log|diff|show and `plan show` still work).")
        elif tool in EDIT_TOOLS:
            raw = next((data[k] for k in PATH_KEYS if isinstance(data.get(k), str) and data[k]), None)
            if raw is None: raise ValueError(f'{tool} call without a path field ({"/".join(PATH_KEYS)})')
            verdict = judge_path(plan, root, normalize(raw, base), 'Do not edit it.')
        elif tool in SHELL_TOOLS:
            if not isinstance(data.get('command'), str): raise ValueError(f'{tool} call without command')
            verdict = judge_shell(plan, root, base, data['command'])
        else:
            return 0                                     # a tool this hook does not govern
    except Exception as error:                          # noqa: BLE001 - fail closed in enforce, open in log
        record(root, plan, 'blocked' if mode == 'enforce' else 'logged', tool, f'hook error: {error}', 'hook_error', session=session, mode=mode)
        if mode == 'enforce':
            print(f'OneCrew hook failed ({error}); blocked because the plan is in enforce mode. Ask the owner.', file=sys.stderr)
            return 2
        return 0
    if verdict is None: return 0
    rule, reason = verdict
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
    if hit is None: return 0
    budget = plan.get('budget') or {}
    pending = next((m['id'] for m in plan.get('milestones', []) if m.get('state') != 'passed'), None)
    note = (f"Contract v{plan.get('revision')} says: {budget.get('max_calls')} calls, {budget.get('time')} minutes, next milestone {pending or 'none'}. "
            f"Spoken words are not in the ledger; change the contract with `onecrew plan amend` or file a CREQ.")
    record(root, plan, 'reminded', 'UserPromptSubmit', note, 'prompt_keyword:' + str(hit), session=event.get('session_id'))
    print(json.dumps({'hookSpecificOutput': {'hookEventName': 'UserPromptSubmit', 'additionalContext': note}}, ensure_ascii=False))
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
    ledger = Ledger(root, args.state_root or plan.get('state_root'))
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


def settings(project, state_root, repo):
    code = f"import sys; sys.path.insert(0, {str(repo)!r}); from onecrew.v2.hook_cli import main; sys.exit(main(sys.argv[1:]))"
    def entry(verb, timeout, matcher=None, fail='continue'):     # only the tool gate fails closed: a crashing prompt/stop hook must not lock the session
        handler = {'type': 'command', 'command': sys.executable, 'args': ['-c', code, '--project', str(project), '--state-root', str(state_root), 'hook', verb], 'timeout': timeout, 'onFailure': fail}
        return dict({'matcher': matcher} if matcher else {}, hooks=[handler])
    root = str(state_root).replace('\\', '/')
    deny = ['Edit(//' + root.lstrip('/') + '/**)',                       # Edit rules cover Write, MultiEdit and NotebookEdit too
            'Edit(**/plans/**)', 'Edit(**/*.sqlite*)', 'Edit(.onecrew/active-plan.json)', 'Edit(.onecrew/violations.jsonl)', 'Edit(.onecrew/hook-state.json)',
            'Edit(.claude/settings*.json)',
            'Bash(git push:*)', 'Bash(git * push*)', 'PowerShell(git push *)', 'PowerShell(git * push*)',
            'Bash(*git.exe*push*)', 'PowerShell(*git.exe*push*)', 'Bash(*send-pack*)', 'PowerShell(*send-pack*)', 'Bash(*http-push*)', 'PowerShell(*http-push*)',   # C9
            'Bash(*git.cmd*push*)', 'PowerShell(*git.cmd*push*)', 'Bash(*-c*alias.*push*)', 'PowerShell(*-c*alias.*push*)',   # C14: git.cmd and an alias given with -c
            'Bash(*-c*alias.*send-pack*)', 'PowerShell(*-c*alias.*send-pack*)', 'Bash(*--config-env*)', 'PowerShell(*--config-env*)',
            'Bash(git config * alias.*)', 'PowerShell(git config * alias.*)',
            'Edit(//' + str(Path.home()).replace('\\', '/').lstrip('/') + '/.claude/CLAUDE.md)', 'Edit(//' + str(Path.home()).replace('\\', '/').lstrip('/') + '/.claude/agents/**)']
    for verb in ('plan approve', 'plan accept', 'plan enforce', 'verdict record', 'hook mode', 'plan unknown close*owner', 'plan poc record*owner'):   # any way of calling onecrew (venv python, -X utf8, onecrew.cmd); C13: an AI may still close an unknown with --by doc|poc
        deny += ['Bash(*' + verb + '*)', 'PowerShell(*' + verb + '*)']                # git tag is left to the hook: a permission rule cannot tell `git tag -l` from `git tag v1`
    return {'hooks': {'PreToolUse': [entry('check', 15, 'Edit|Write|MultiEdit|NotebookEdit|Bash|PowerShell', fail='block')],
                      'UserPromptSubmit': [entry('prompt', 10)], 'Stop': [entry('stop', 30)],
                      'SessionStart': [entry('session', 30, 'startup|resume|clear|compact')]},
            'permissions': {'deny': deny}}


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
    args = parser().parse_args(argv)
    if args.group != 'hook': return 2
    if args.verb in ('check', 'prompt', 'stop', 'session'):
        return {'check': check, 'prompt': prompt, 'stop': stop, 'session': session}[args.verb](args)
    from ..ledger import Ledger, LedgerError
    try:
        project = Path(args.project or os.environ.get('CLAUDE_PROJECT_DIR') or Path.cwd())
        if args.verb == 'sync': out = sync(args)
        elif args.verb == 'install':
            repo = Path(__file__).resolve().parents[2]
            out = settings(project.resolve(), Path(Ledger(project, args.state_root).state_root), repo)
        else:
            from . import active_plan
            from .plan import require_owner
            ledger = Ledger(project, args.state_root)
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
