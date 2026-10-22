"""`onecrew init` and `onecrew doctor` (G2): put a repo under OneCrew from an installed copy, and say what a machine is missing.

init (once per repo, again whenever the install moves): the state root (ledger, `plans/owner-rules.md`), `<project>/.onecrew/config.json`
{"state_root"}, and the Claude Code hooks in `.claude/settings.local.json` (`settings.json` with --shared). The hooks are merged by key into what is
already there: other tools' hooks, `permissions.allow` and `permissions.deny` entries and every other key stay; OneCrew's own entries are replaced, never
doubled; a `.bak` copy is kept before the first change; a second run writes nothing. The hook command is the installed `onecrew` executable itself
(`onecrew hook <verb>`): the project comes from CLAUDE_PROJECT_DIR and the state root from config.json at run time (hook_cli.portable_settings).
init also records project -> state root in a registry outside the project (where.register_project), the pointer the hook falls back to when `.onecrew/` is gone.
The Claude CLI is looked for and asked whether it is logged in; init never logs in for the user.

doctor: one line `PASS|WARN|FAIL <name>: <detail>` per check; exit 1 when any line is FAIL.
All wording comes from messages.py (English by default, ONECREW_LANG=vi for Vietnamese).
"""
import argparse
import copy
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from ..ledger import Ledger, LedgerError
from . import claude_cli, hook_cli, where
from .messages import lang, t

EXE_NAMES = ('onecrew', 'onecrew.exe', 'onecrew.cmd')
HOOK_VERBS = tuple(verb for _, verb, _, _, _ in hook_cli.HOOK_EVENTS)
LOGIN_TIMEOUT = 30


# ---- the installed command and the Claude CLI -------------------------------------------------------------------------------

def installed_exe():
    """The installed `onecrew` executable (absolute): the one that is running, else the one next to this interpreter, else the first on PATH. None in a checkout."""
    candidates = []
    argv0 = Path(sys.argv[0]) if sys.argv and sys.argv[0] else None
    if argv0 is not None and argv0.stem.casefold() == 'onecrew' and argv0.suffix.casefold() in ('', '.exe', '.cmd'):
        candidates += [argv0, argv0.with_suffix('.exe')]
    bin_dir = Path(sys.executable).parent
    candidates += [bin_dir / name for name in ('onecrew.exe', 'onecrew')]
    found = shutil.which('onecrew')
    if found: candidates.append(Path(found))
    for candidate in candidates:
        if candidate.is_file(): return candidate.resolve()
    return None


def claude_status(env=None, run=subprocess.run):
    """(state, path, why): 'missing' | 'ok' | 'logged_out' | 'unknown'. Asks `claude auth status`; never logs in."""
    try:
        argv = claude_cli.cli_argv(dict(os.environ if env is None else env))
    except LedgerError:
        return 'missing', None, ''
    path = argv[0]
    try:
        done = run([*argv, 'auth', 'status'], capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=LOGIN_TIMEOUT, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError) as error:
        return 'unknown', path, type(error).__name__                  # a code (the exception class), not a sentence
    text = ((done.stdout or '') + (done.stderr or '')).strip()
    try:
        value = json.loads(done.stdout)
        if isinstance(value, dict) and isinstance(value.get('loggedIn'), bool):
            return ('ok' if value['loggedIn'] else 'logged_out'), path, ''
    except (TypeError, ValueError):
        pass
    if done.returncode == 0 and not re.search(r'not\s+logged|logged\s+out|no\s+account', text, re.I): return 'ok', path, ''
    if re.search(r'not\s+logged|logged\s+out|no\s+account|login', text, re.I): return 'logged_out', path, ''
    return 'unknown', path, t('why.exit', code=done.returncode)


# ---- merging the settings file ----------------------------------------------------------------------------------------------

class SettingsShape(ValueError):
    """A settings file whose JSON is fine but whose shape is not (a key that should hold an object holds something else). Carries the key and the shape wanted."""
    def __init__(self, key, expected):
        super().__init__(key)
        self.key, self.expected = key, expected


CHECKOUT_CODE = re.compile(r'import sys; sys\.path\.insert\(0, (?:\'(?:[^\'\\]|\\.)*\'|"(?:[^"\\]|\\.)*")\); from onecrew\.v2\.hook_cli import main; sys\.exit\(main\(sys\.argv\[1:\]\)\)')
PYTHON_NAME = re.compile(r'pythonw?[\d.]*[a-z]?(?:\.exe)?|py(?:\.exe)?', re.I)         # sys.executable: python, python3, python3.13.exe, pythonw.exe, py
PYTHON_FLAGS = ('-u', '-B', '-E', '-I', '-s', '-S')                                      # flags of the interpreter that may stand before -c (and -X <option>)


def command_words(text):
    """The words of a command line, quotes grouping and removed (a path with spaces in double quotes is one word); a backslash is a plain character, as in a
    Windows path. None when a quote is never closed."""
    words, current, quote, started = [], [], None, False
    index = 0
    while index < len(text):
        char = text[index]
        if quote:
            if char == quote: quote = None
            elif char == '\\' and quote == '"' and text[index + 1:index + 2] == '"': current.append('"'); index += 1
            else: current.append(char)
        elif char in '"\'': quote, started = char, True
        elif char.isspace():
            if started or current: words.append(''.join(current)); current, started = [], False
        else: current.append(char); started = True
        index += 1
    if quote: return None
    if started or current: words.append(''.join(current))
    return words


def is_ours(handler):
    """A hook handler written by OneCrew, judged by its structure: the program that runs, then its arguments, are exactly one of the forms OneCrew
    generates (the words come from `args`, or from the `command` line cut by command_words, a quoted path with spaces being one word):
      * the installed executable: `<path>/onecrew[.exe|.cmd] hook <verb>`  (hook_cli.portable_settings, from 2.2.0.dev1);
      * the checkout form: a Python interpreter, any `-X <option>` / `-u -B -E -I -s -S` flags, `-c <the code hook_cli.settings generates>`, then `--project <p>` and/or
        `--state-root <s>` (2.1, 2.2 and the `-X utf8` one the verify kit uses), then `hook <verb>`.
    <verb> is one of the four hook verbs. Anything else is not ours and is never replaced: `echo from onecrew.v2.hook_cli import main hook check`, a
    wrapper or audit tool in front of the interpreter (`audit-tool python -c "<our code>" hook check`), a handler that only mentions the module."""
    if not isinstance(handler, dict) or handler.get('type', 'command') != 'command': return False
    command, args = handler.get('command'), handler.get('args')
    if not isinstance(command, str) or not command.strip(): return False
    if args is None: words = command_words(command)
    elif isinstance(args, list) and all(isinstance(a, str) for a in args): words = [command, *args]
    else: return False
    if not words: return False
    program, rest = re.split(r'[\\/]', words[0].strip())[-1], words[1:]
    if program.casefold() in EXE_NAMES: return len(rest) == 2 and rest[0] == 'hook' and rest[1] in HOOK_VERBS
    if not PYTHON_NAME.fullmatch(program): return False
    index = 0
    while index < len(rest) and (rest[index] in PYTHON_FLAGS or (rest[index] == '-X' and index + 1 < len(rest))): index += 2 if rest[index] == '-X' else 1
    if index + 1 >= len(rest) or rest[index] != '-c' or not CHECKOUT_CODE.fullmatch(rest[index + 1]): return False
    index += 2
    seen = set()
    while index + 1 < len(rest) and rest[index] in ('--project', '--state-root') and rest[index] not in seen: seen.add(rest[index]); index += 2
    return len(rest) - index == 2 and rest[index] == 'hook' and rest[index + 1] in HOOK_VERBS


def merge_settings(existing, ours):
    """`existing` with OneCrew's hooks and deny rules put in. Other keys, other tools' hooks, allow/deny entries stay; OneCrew's own entries are replaced in place."""
    merged = copy.deepcopy(existing)
    hooks = merged.setdefault('hooks', {})
    if not isinstance(hooks, dict): raise SettingsShape('hooks', 'object')
    for event, entries in ours['hooks'].items():
        current = hooks.get(event, [])
        if not isinstance(current, list): raise SettingsShape('hooks.' + event, 'list')
        result, placed = [], False
        for entry in current:
            handlers = entry.get('hooks') if isinstance(entry, dict) else None
            if not isinstance(handlers, list) or not any(is_ours(h) for h in handlers):
                result.append(entry)
                continue
            if not placed: result += copy.deepcopy(entries); placed = True
            rest = [h for h in handlers if not is_ours(h)]
            if rest: result.append(dict(entry, hooks=rest))
        if not placed: result += copy.deepcopy(entries)
        hooks[event] = result
    permissions = merged.setdefault('permissions', {})
    if not isinstance(permissions, dict): raise SettingsShape('permissions', 'object')
    deny = permissions.setdefault('deny', [])
    if not isinstance(deny, list): raise SettingsShape('permissions.deny', 'list')
    deny += [rule for rule in ours['permissions']['deny'] if rule not in deny]
    return merged


def our_entries(settings):
    """{event: [entry, ...]} of the OneCrew entries (those holding a OneCrew handler) of a settings dict."""
    found = {}
    for event, entries in (settings.get('hooks') or {}).items():
        if not isinstance(entries, list): continue
        mine = [e for e in entries if isinstance(e, dict) and any(is_ours(h) for h in (e.get('hooks') or []))]
        if mine: found[event] = mine
    return found


def read_settings(path):
    """(dict, reason). A missing file is an empty dict; a file that is not a JSON object is an error (reason = a sentence in the user's language) and is never overwritten."""
    if not path.exists(): return {}, None
    try:
        value = json.loads(path.read_text(encoding='utf-8-sig'))
    except json.JSONDecodeError as error:
        return None, t('settings.json_error', path=path, line=error.lineno, col=error.colno)
    except (OSError, ValueError) as error:
        return None, t('settings.unreadable', path=path, code=type(error).__name__)
    if not isinstance(value, dict): return None, t('settings.not_object', path=path)
    return value, None


def dump(value):
    return json.dumps(value, indent=2, ensure_ascii=False) + '\n'


def write_text(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, name = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + '.', suffix='.tmp')
    try:
        with os.fdopen(handle, 'w', encoding='utf-8', newline='\n') as stream: stream.write(text)
        os.replace(name, path)
    except BaseException:
        try: os.unlink(name)
        except OSError: pass
        raise


# ---- init -------------------------------------------------------------------------------------------------------------------

def say(line):
    print(line, flush=True)


def init(project=None, state_root=None, shared=False, yes=False, exe=None, ask=input, claude=claude_status):
    """Exit code: 0 done; 1 done but the Claude CLI is missing or logged out; 2 nothing written (not a git repo, bad settings file, no installed command, declined)."""
    start = Path(project) if project else where.project_from_environment()
    root = where.git_root(start)
    if root is None:
        say(t('init.no_git', path=start))
        return 2
    exe = exe or installed_exe()
    if exe is None:
        say(t('init.no_exe'))
        return 2
    exe = Path(exe).resolve()
    chosen = state_root or where.configured_state_root(root) or where.default_state_root()
    try:
        ledger = Ledger(root, chosen)
    except LedgerError as error:
        say(t('init.error', error=error))
        return 2
    state = ledger.state_root
    settings_path = root / '.claude' / ('settings.json' if shared else 'settings.local.json')
    config_path = where.config_file(root)
    rules_path = state / 'plans' / 'owner-rules.md'
    ours = hook_cli.portable_settings(exe, state)
    existing, bad = read_settings(settings_path)
    if bad:
        say(t('init.bad_settings', reason=bad))
        return 2
    try:
        merged = merge_settings(existing, ours)
    except SettingsShape as error:
        say(t('init.bad_settings', reason=t('settings.shape', path=settings_path, field=error.key, expected=t('shape.' + error.expected))))
        return 2
    config = where.read_config(root)
    wanted_config = dict(config, state_root=str(state))
    todo = {'state': not ledger.path.is_file(), 'rules': not rules_path.exists(), 'config': config != wanted_config,
            'settings': merged != existing or not settings_path.exists()}
    if any(todo.values()):
        say(t('init.plan_title', project=root))
        if todo['state']: say(t('init.step_state', path=state, note=t('init.note_exists') if state.exists() else t('init.note_new')))
        if todo['rules']: say(t('init.step_rules', path=rules_path))
        if todo['config']: say(t('init.step_config', path=config_path))
        if todo['settings']:
            say(t('init.step_settings', verb=t('init.verb_merge') if settings_path.exists() else t('init.verb_create'), path=settings_path,
                  bak=t('init.bak_note') if settings_path.exists() and not settings_path.with_name(settings_path.name + '.bak').exists() else ''))
        if not yes:
            try:
                answer = ask(t('init.ask'))
            except EOFError:
                answer = ''
            if answer.strip().casefold() not in ('y', 'yes'):
                say(t('init.cancelled'))
                return 2
        if todo['state'] or todo['rules']:
            from .verifiers import advisor
            if todo['state']:
                with ledger.transaction(write=True): pass                  # creates ledger.sqlite3 with its schema; an existing ledger is left alone
            if todo['rules']: advisor.init_rules(ledger, 'vi' if lang() == 'vi' else 'en')
        if todo['config']: write_text(config_path, dump(wanted_config))
        if todo['settings']:
            backup = settings_path.with_name(settings_path.name + '.bak')
            if settings_path.exists() and not backup.exists(): shutil.copyfile(settings_path, backup)
            write_text(settings_path, dump(merged))
    else:
        say(t('init.nothing'))
    where.register_project(root, state)       # a second pointer to the state root, outside .onecrew/, for the hook when that folder is gone
    say(t('init.done', state=state, settings=settings_path, command=exe, rules=rules_path))
    say(t('init.config_note'))
    state_name, path, why = claude()
    if state_name == 'ok': say(t('init.claude_ok', path=path))
    elif state_name == 'missing': say(t('init.claude_missing'))
    elif state_name == 'logged_out': say(t('init.claude_logged_out', path=path))
    else: say(t('init.claude_unknown', path=path, why=why))
    say(t('init.next'))
    return 1 if state_name in ('missing', 'logged_out') else 0


# ---- doctor -----------------------------------------------------------------------------------------------------------------

def check_hooks(root, state, exe):
    """(level, detail) for the hook entries of the two settings files of a repo."""
    found = []
    for name in ('settings.local.json', 'settings.json'):
        path = root / '.claude' / name
        data, bad = read_settings(path)
        if bad: return 'FAIL', bad
        if data and our_entries(data): found.append((path, data))
    if not found:
        return 'FAIL', t('doctor.hook_missing', paths=' / '.join(str(root / '.claude' / n) for n in ('settings.local.json', 'settings.json')))
    results = []
    for path, data in found:                       # every file that holds OneCrew hooks: a stale copy in the other file is reported too
        commands = {str(h.get('command')) for entries in our_entries(data).values() for e in entries for h in e.get('hooks', []) if is_ours(h)}
        gone = sorted(c for c in commands if not Path(c).is_file() and shutil.which(c) is None)
        if gone:
            results.append(('FAIL', t('doctor.hook_stale', path=path, command=gone[0])))
            continue
        want = hook_cli.portable_settings(exe or sorted(commands)[0], state)
        same = our_entries(data) == our_entries(want) and all(rule in ((data.get('permissions') or {}).get('deny') or []) for rule in want['permissions']['deny'])
        results.append(('PASS', t('doctor.hook_ok', path=path)) if same else ('WARN', t('doctor.hook_differs', path=path)))
    for level in ('FAIL', 'WARN'):
        bad = next((r for r in results if r[0] == level), None)
        if bad: return bad
    return 'PASS', ' / '.join(detail for _, detail in results)


def doctor(project=None, state_root=None, exe=None, claude=claude_status):
    start = Path(project) if project else where.project_from_environment()
    root = where.git_root(start)
    lines = []
    add = lambda level, key, detail: lines.append((level, t(key), detail))
    version = '.'.join(str(n) for n in sys.version_info[:3])
    if sys.version_info >= (3, 10): add('PASS', 'doctor.python', t('doctor.python_ok', version=version))
    else: add('FAIL', 'doctor.python', t('doctor.python_old', version=version))
    git = shutil.which('git')
    if git: add('PASS', 'doctor.git', t('doctor.git_ok', path=git))
    else: add('FAIL', 'doctor.git', t('doctor.git_missing'))
    state_name, path, why = claude()
    if state_name == 'missing':
        add('WARN', 'doctor.claude', t('doctor.claude_missing'))
        add('WARN', 'doctor.login', t('doctor.login_skip'))
    else:
        add('PASS', 'doctor.claude', t('doctor.claude_ok', path=path))
        if state_name == 'ok': add('PASS', 'doctor.login', t('doctor.login_ok'))
        elif state_name == 'logged_out': add('WARN', 'doctor.login', t('doctor.login_no'))
        else: add('WARN', 'doctor.login', t('doctor.login_unknown', why=why))
    if root is None:
        add('FAIL', 'doctor.project', t('doctor.project_none', path=start))
        chosen = Path(state_root) if state_root else where.default_state_root()
    else:
        add('PASS', 'doctor.project', t('doctor.project_ok', path=root))
        chosen = Path(state_root) if state_root else where.configured_state_root(root) or where.default_state_root()
    ledger_file = chosen / 'ledger.sqlite3'
    if not chosen.is_dir():
        add('FAIL', 'doctor.state', t('doctor.state_missing', path=chosen))
    else:
        try:
            with tempfile.TemporaryFile(dir=str(chosen)): pass
            if ledger_file.is_file() and not os.access(ledger_file, os.R_OK | os.W_OK): raise PermissionError('ledger.sqlite3')
            add('PASS', 'doctor.state', t('doctor.state_ok', path=chosen, ledger=t('doctor.state_ledger') if ledger_file.is_file() else t('doctor.state_noledger')))
        except OSError as error:
            add('FAIL', 'doctor.state', t('doctor.state_bad', path=chosen, why=type(error).__name__))
    if root is None:
        add('WARN', 'doctor.config', t('doctor.config_missing', path='.onecrew/config.json'))
        add('WARN', 'doctor.hook', t('doctor.hook_missing', paths='.claude/settings.local.json'))
        add('WARN', 'doctor.plan', t('doctor.plan_none'))
    else:
        configured = where.configured_state_root(root)
        if configured: add('PASS', 'doctor.config', t('doctor.config_ok', path=where.config_file(root), state=configured))
        else: add('WARN', 'doctor.config', t('doctor.config_missing', path=where.config_file(root)))
        level, detail = check_hooks(root, chosen, exe or installed_exe())
        add(level, 'doctor.hook', detail)
        plan_file = root / '.onecrew' / hook_cli.FILE
        if not plan_file.is_file(): add('PASS', 'doctor.plan', t('doctor.plan_none'))
        else:
            plan, bad = hook_cli.load_plan(plan_file)
            if bad: add('FAIL', 'doctor.plan', t('doctor.plan_bad', why=bad.split(':')[0]))
            else: add('PASS', 'doctor.plan', t('doctor.plan_ok', name=plan.get('plan'), revision=plan.get('revision'), mode=plan.get('mode')))
    for level, name, detail in lines: say(f'{level} {name}: {detail}')
    counts = {level: sum(1 for l in lines if l[0] == level) for level in ('FAIL', 'WARN', 'PASS')}
    say(t('doctor.summary', fails=counts['FAIL'], warns=counts['WARN'], passes=counts['PASS']))
    return 1 if counts['FAIL'] else 0


# ---- the command line -------------------------------------------------------------------------------------------------------

def _parser():
    parser = argparse.ArgumentParser(prog='onecrew')
    parser.add_argument('--project', type=Path); parser.add_argument('--state-root', type=Path)
    groups = parser.add_subparsers(dest='group', required=True)
    p = groups.add_parser('init', help=t('cli.init'))
    p.add_argument('--project', type=Path, default=argparse.SUPPRESS); p.add_argument('--state-root', type=Path, default=argparse.SUPPRESS)
    p.add_argument('--shared', action='store_true', help=t('cli.shared'))
    p.add_argument('--yes', '-y', action='store_true', help=t('cli.yes'))
    p = groups.add_parser('doctor', help=t('cli.doctor'))
    p.add_argument('--project', type=Path, default=argparse.SUPPRESS); p.add_argument('--state-root', type=Path, default=argparse.SUPPRESS)
    return parser


def main(argv=None):
    try:
        sys.stdout.reconfigure(errors='replace')
    except (AttributeError, ValueError):
        pass
    args = _parser().parse_args(argv)
    if args.group == 'init': return init(args.project, args.state_root, args.shared, args.yes)
    return doctor(args.project, args.state_root)


if __name__ == '__main__':
    sys.exit(main())
