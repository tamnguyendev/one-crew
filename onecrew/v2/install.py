"""`onecrew init` and `onecrew doctor` (G2): put a repo under OneCrew from an installed copy, and say what a machine is missing.

init (once per repo, again whenever the install moves): the state root (ledger, `plans/owner-rules.md`), `<project>/.onecrew/config.json`
{"state_root"}, and the Claude Code hooks in `.claude/settings.local.json` (`settings.json` with --shared). The hooks are merged by key into what is
already there: other tools' hooks, `permissions.allow` and `permissions.deny` entries and every other key stay; OneCrew's own entries are replaced, never
doubled; a `.bak` copy is kept before the first change; a second run writes nothing. The hook command is the installed `onecrew` executable itself
(`onecrew hook <verb>`): the project comes from CLAUDE_PROJECT_DIR and the state root from config.json at run time (hook_cli.portable_settings).
init also records project -> state root in a registry outside the project (where.register_project), the pointer the hook falls back to when `.onecrew/` is gone.
init also gives the project a wiki (2.3-A1 WI-01..05, docs/v23/HOP-DONG-2.3.vi.md §10.3): the folder `.onecrew/config.json` names under
"wiki": {"paths": [...]}, else `docs/wiki/`. A wiki that is there is used as it is; a missing or empty one gets a minimal skeleton (an entry
page, the project context, the lessons) that yields no knowledge entry; init never overwrites a file, never writes outside the repository
or through a link, and stops with nothing written when the configuration cannot be read or names a folder it cannot use.
The Claude CLI is looked for and asked whether it is logged in; init never logs in for the user.

doctor: one line `PASS|WARN|FAIL <name>: <detail>` per check; exit 1 when any line is FAIL.
All wording comes from messages.py (English by default, ONECREW_LANG=vi for Vietnamese).
"""
import argparse
import copy
import datetime as dt
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

from ..ledger import Ledger, LedgerError
from ..snapshots import control_part, is_link
from . import claude_cli, hook_cli, where
from .messages import TEXT, lang, t
from .session_observe import OBSERVE_EVENTS

EXE_NAMES = ('onecrew', 'onecrew.exe', 'onecrew.cmd')
HOOK_VERBS = tuple(verb for _, verb, _, _, _ in hook_cli.HOOK_EVENTS) + ('background',)      # BG-A: `hook background` is ours too (opt-in events)
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
    """The words of a command line, quotes grouping and removed (a path with spaces in double quotes is one word). A backslash is a plain character, as in a
    Windows path, except that `\\"` inside double quotes is a quote. None when a quote is never closed."""
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


SHELL_ACTIVE = re.compile(r'[;&|<>$`]')          # in a command line, a word with one of these could end the command or run another (`;`, `&`, `|`, `$(...)`, backticks)


def handler_words(handler):
    """(words, line) of a command handler: [command, *args] when `args` is a list of strings (nothing reads it as a shell line), else the `command` line cut by
    command_words (line=True: a shell reads it). (None, False) when the handler is not a command we can read."""
    if not isinstance(handler, dict) or handler.get('type', 'command') != 'command': return None, False
    command, args = handler.get('command'), handler.get('args')
    if not isinstance(command, str) or not command.strip(): return None, False
    if args is None: return command_words(command), True
    if isinstance(args, list) and all(isinstance(a, str) for a in args): return [command, *args], False
    return None, False


def checkout_code_index(rest):
    """The index in `rest` (the words after the interpreter) of the checkout code, when `rest` is exactly the arguments of the checkout form: interpreter flags
    (`-u -B -E -I -s -S`, `-X <option>` or `-X<option>`) each at most once, `-c <the code>`, `--project <p>` and `--state-root <s>` each at most once, then
    `hook <verb>`. None otherwise."""
    index, seen = 0, set()
    while index < len(rest):
        word = rest[index]
        if word in PYTHON_FLAGS: option, step = word, 1
        elif word == '-X' and index + 1 < len(rest): option, step = ('-X', rest[index + 1]), 2
        elif word.startswith('-X') and len(word) > 2: option, step = ('-X', word[2:]), 1
        else: break
        if option in seen: return None
        seen.add(option)
        index += step
    if index + 1 >= len(rest) or rest[index] != '-c' or not CHECKOUT_CODE.fullmatch(rest[index + 1]): return None
    code, index, given = index + 1, index + 2, set()
    while index + 1 < len(rest) and rest[index] in ('--project', '--state-root') and rest[index] not in given:
        given.add(rest[index])
        index += 2
    return code if len(rest) - index == 2 and rest[index] == 'hook' and rest[index + 1] in HOOK_VERBS else None


def is_ours(handler):
    """A hook handler written by OneCrew, judged by its structure: the program that runs, then its arguments, are exactly one of the forms OneCrew
    generates (the words come from `args`, or from the `command` line cut by command_words, a quoted path with spaces being one word):
      * the installed executable: `<path>/onecrew[.exe|.cmd] hook <verb>`  (hook_cli.portable_settings, from 2.2.0.dev1);
      * the checkout form: a Python interpreter, interpreter flags and `-X <option>` / `-X<option>`, `-c <the code hook_cli.settings generates>`, then `--project <p>`
        and/or `--state-root <s>` (2.1, 2.2 and the `-X utf8` one the verify kit uses), then `hook <verb>`; every option at most once.
    <verb> is one of the four hook verbs. In a command LINE (no `args`) a shell reads the words, so a word with `;` `&` `|` `<` `>` `$` or a backtick, or a
    line break in the line, is not ours (`--project D:/p;audit-tool hook check`, `--project "$(audit-tool --log)"`): the checkout code, which has `;` and `(` of
    its own, is the one word that is only refused if it holds `$` or a backtick. Anything else is not ours and is never replaced:
    `echo from onecrew.v2.hook_cli import main hook check`, a wrapper or audit tool in front of the interpreter (`audit-tool python -c "<our code>" hook check`),
    a handler that only mentions the module."""
    words, line = handler_words(handler)
    if not words or (line and re.search(r'[\r\n]', handler['command'])): return False
    program, rest = re.split(r'[\\/]', words[0].strip())[-1], words[1:]
    if program.casefold() in EXE_NAMES:
        code = None
        if not (len(rest) == 2 and rest[0] == 'hook' and rest[1] in HOOK_VERBS): return False
    elif PYTHON_NAME.fullmatch(program):
        code = checkout_code_index(rest)
        if code is None: return False
        code += 1                                                      # an index in `words`
    else: return False
    if line:
        for position, word in enumerate(words):
            risky = re.search(r'[$`]', word) if position == code else SHELL_ACTIVE.search(word)
            if risky: return False
    return True


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


# ---- the project wiki (2.3-A1 WI-01..05) ------------------------------------------------------------------------------------

SKELETON_MARK = '<!-- onecrew:wiki-skeleton 1 -->'       # first line of every page init writes: how a later init tells its own pages apart
SKELETON_NAMES = ('README.md', 'project.md', 'lessons.md')
DEFAULT_WIKI = 'docs/wiki'                                 # = wiki.DEFAULT_PATHS
SKELETON = {'README.md': 'wiki.page_readme', 'project.md': 'wiki.page_project', 'lessons.md': 'wiki.page_lessons'}      # the words are in messages.py


def skeleton_text(name, language):
    """The page `name` of a new wiki. No line starts with a `##`/`###` heading or a fence: the reader cuts entries there, so the skeleton
    yields no entry and no mandatory section (KW-11); the example is indented."""
    return SKELETON_MARK + '\n' + TEXT[SKELETON[name]]['vi' if language == 'vi' else 'en'].format()


def _is_skeleton(path):
    """Is this page init's own: the skeleton text of its name (either language, LF or CRLF), or a prefix of it, empty included (an
    interrupted write, review dev7 R7-15)? An edited page is the user's (R7-10). Such a page is never rewritten; only missing pages are added.
    The texts of a released version must stay recognised here if the wording ever changes (2.3.0.dev7 is the first that writes a skeleton)."""
    try:
        data = Path(path).read_bytes().replace(b'\r\n', b'\n')
    except OSError:
        return False
    return any(skeleton_text(Path(path).name, language).encode('utf-8').startswith(data) for language in ('en', 'vi'))


DEVICE = re.compile(r'(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?', re.I)      # = snapshots.scoped_path


def _spelling(part):
    """A component Windows reads as another name whatever is on disk: a trailing dot or space, a stream (`name:stream`) (review dev7 R7-02).
    A short (8.3) name is judged by what it resolves to (_path_problem), so a real folder named like one is accepted (R7-19)."""
    return part.endswith(('.', ' ')) or ':' in part


def _guarded(part):
    return control_part(part) or part.casefold() == '.claude'


def _path_problem(root, parts):
    """None, or (message key, linked) for the folder root/parts: a link or junction on the way (also one is_link cannot see before Python 3.12:
    the deepest existing folder must resolve inside the repository), a file on the way, a control folder however it is spelled (the names the
    file system resolves are judged, R7-02). Asked when init plans and again right before it writes (R7-08)."""
    current = root
    for part in parts:
        current = current / part
        if is_link(current): return 'link'
        if not current.exists(): break
        if not current.is_dir(): return 'not_folder'
    probe, rest = root.joinpath(*parts), []
    while not probe.exists() and probe != root: rest.insert(0, probe.name); probe = probe.parent
    try:
        resolved, top = probe.resolve(), root.resolve()
    except OSError:
        return 'unlistable'
    if not resolved.is_relative_to(top): return 'link'
    names = list(resolved.relative_to(top).parts)
    if [n.casefold() for n in names] != [p.casefold() for p in parts[:len(parts) - len(rest)]]: return 'spelling'   # an 8.3 alias, R7-19
    if any(_guarded(p) for p in names + rest): return 'protected'
    return None


def wiki_plan(root):
    """What init does about the wiki of the repository `root`, decided before anything is written:
    {'action': 'create', 'target', 'shown', 'parts', 'names'}: the folder and the skeleton pages that do not exist yet (a missing folder, an
    empty one, or one that holds only pages init wrote and the user did not edit: an interrupted init); {'action': 'reuse', 'folders',
    'pages'}: a wiki is there (also a linked one that has pages, R7-09), or several folders or a folder outside the repository are
    configured: nothing is written there (init never picks a folder to write into); {'action': 'refuse', 'reason'}: the configuration or the
    folder cannot be used, init stops with nothing written. A config.json that cannot be read is refused, never overwritten (where.read_config
    reads it as {}). A rooted path without a drive ('/docs/wiki') is a folder at the drive's root, outside the repository, as the reader reads
    it: only reused (R7-03, R7-18)."""
    refuse = lambda key, **values: {'action': 'refuse', 'reason': t('wiki.' + key, **values)}
    config = where.config_file(root)
    paths = [DEFAULT_WIKI]
    if config.exists():
        try:
            value = json.loads(config.read_text(encoding='utf-8-sig'))
        except (OSError, ValueError) as error:
            return refuse('config_unreadable', path=config, why=type(error).__name__)
        if not isinstance(value, dict): return refuse('config_unreadable', path=config, why='not a JSON object')
        if 'wiki' in value:
            raw = value['wiki'].get('paths') if isinstance(value['wiki'], dict) else None
            if not (isinstance(raw, list) and raw and all(isinstance(p, str) and p.strip() for p in raw)): return refuse('config_shape', path=config)
            paths = raw
    inside, outside = [], []
    for raw in paths:
        candidate = Path(raw)
        if candidate.is_absolute(): outside.append(candidate); continue
        if candidate.root and not candidate.drive: outside.append(root / candidate); continue    # '/x': the drive's root, read as the reader reads it (R7-18)
        parts = [p for p in raw.replace(chr(92), '/').split('/') if p not in ('', '.')]
        if candidate.drive or '..' in parts: return refuse('outside', path=raw)             # 'D:x': a folder of another drive's current directory
        if any(_spelling(p) for p in parts): return refuse('spelling', path=raw)
        if any(DEVICE.fullmatch(p) for p in parts): return refuse('device', path=raw)      # review dev7 delta N2
        if any(_guarded(p) for p in parts): return refuse('protected', path=raw)
        inside.append((raw, parts))
    if len(paths) > 1 or outside:                      # only reused: every folder must be there
        folders = [root.joinpath(*parts) for _, parts in inside] + outside
        missing = [str(f) for f in folders if not f.is_dir()]
        if missing: return refuse('missing', paths=', '.join(missing))
        return {'action': 'reuse', 'folders': [str(f) for f in folders], 'pages': sum(_count_pages(f) for f in folders)}
    raw, parts = inside[0]
    if not parts: return {'action': 'reuse', 'folders': [raw], 'pages': _count_pages(root)}     # the repository root itself: never a skeleton there
    target = root.joinpath(*parts)
    problem = _path_problem(root, parts)
    if problem == 'link' and target.is_dir() and _count_pages(target):
        return {'action': 'reuse', 'folders': [raw], 'pages': _count_pages(target), 'linked': True}   # R7-09: read as it is, never written through
    if problem: return refuse(problem, path=raw, why='OSError')
    if not target.exists(): return {'action': 'create', 'target': target, 'shown': raw, 'parts': parts, 'names': list(SKELETON_NAMES)}
    try:
        pages = sorted(p for p in target.rglob('*.md') if p.is_file())
    except OSError as error:
        return refuse('unlistable', path=raw, why=type(error).__name__)
    if any(p.parent != target or p.name not in SKELETON_NAMES or not _is_skeleton(p) for p in pages):
        return {'action': 'reuse', 'folders': [raw], 'pages': len(pages)}         # a page of the user: the wiki is theirs, nothing is added
    names = [n for n in SKELETON_NAMES if not os.path.lexists(target / n)]       # a name taken by a folder is left alone
    if not names: return {'action': 'reuse', 'folders': [raw], 'pages': len(pages)}
    return {'action': 'create', 'target': target, 'shown': raw, 'parts': parts, 'names': names}


def _count_pages(folder):
    try:
        return sum(1 for p in Path(folder).rglob('*.md') if p.is_file())
    except OSError:
        return 0


def _create_new_file(path, text):
    """Write a file that does not exist yet; an existing one is never overwritten (FileExistsError)."""
    with open(path, 'x', encoding='utf-8', newline='\n') as stream: stream.write(text)


def write_wiki(plan, language, root):
    """Create the skeleton pages `plan` names: (written names, None) or, at the first error, (written so far, (name, why)). The path is judged
    again right before the folder is made and before the pages are written: what changed while init waited for its answer is not written
    through (review dev7 R7-08)."""
    written = []
    why = lambda error: type(error).__name__ + (': ' + error.strerror if getattr(error, 'strerror', None) else '')
    for moment in ('before', 'after'):
        problem = _path_problem(root, plan['parts'])
        if problem: return written, (plan['shown'], t('wiki.' + problem, path=plan['shown'], why='OSError'))
        if moment == 'after': break
        try:
            plan['target'].mkdir(parents=True, exist_ok=True)
        except OSError as error:
            return written, (plan['shown'], why(error))
    for name in plan['names']:
        try:
            _create_new_file(plan['target'] / name, skeleton_text(name, language))
        except FileExistsError:
            continue                                   # appeared meanwhile: never overwritten
        except OSError as error:
            return written, (name, why(error))
        written.append(name)
    return written, None


# ---- init -------------------------------------------------------------------------------------------------------------------

def say(line):
    print(line, flush=True)


def init(project=None, state_root=None, shared=False, yes=False, exe=None, ask=input, claude=claude_status):
    """Exit code: 0 done; 1 done but the Claude CLI is missing or logged out; 2 nothing written (not a git repo, bad settings file, a config.json
    or wiki folder init cannot use, no installed command, declined); 3 done except the wiki skeleton (what was written and the error are told)."""
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
    wiki_step = wiki_plan(root)
    if wiki_step['action'] == 'refuse':
        say(t('init.wiki_refused', reason=wiki_step['reason']))
        return 2
    config = where.read_config(root)
    wanted_config = dict(config, state_root=str(state))
    ignore_path = config_path.parent / '.gitignore'
    todo = {'state': not ledger.path.is_file(), 'rules': not rules_path.exists(), 'config': config != wanted_config,
            'ignore': not ignore_path.exists(),
            'settings': merged != existing or not settings_path.exists(), 'wiki': wiki_step['action'] == 'create'}
    wiki_written, wiki_failed = [], None
    if any(todo.values()):
        say(t('init.plan_title', project=root))
        if todo['state']: say(t('init.step_state', path=state, note=t('init.note_exists') if state.exists() else t('init.note_new')))
        if todo['rules']: say(t('init.step_rules', path=rules_path))
        if todo['config']: say(t('init.step_config', path=config_path))
        if todo['ignore']: say(t('init.step_ignore', path=ignore_path))
        if todo['settings']:
            say(t('init.step_settings', verb=t('init.verb_merge') if settings_path.exists() else t('init.verb_create'), path=settings_path,
                  bak=t('init.bak_note') if settings_path.exists() and not settings_path.with_name(settings_path.name + '.bak').exists() else ''))
        if todo['wiki']: say(t('init.step_wiki', path=wiki_step['shown'], files=', '.join(wiki_step['names'])))
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
        if todo['ignore']: write_text(ignore_path, '*\n')
        if todo['settings']:
            backup = settings_path.with_name(settings_path.name + '.bak')
            if settings_path.exists() and not backup.exists(): shutil.copyfile(settings_path, backup)
            write_text(settings_path, dump(merged))
        if todo['wiki']: wiki_written, wiki_failed = write_wiki(wiki_step, 'vi' if lang() == 'vi' else 'en', root)     # last: a wiki error never undoes the rest
    else:
        say(t('init.nothing'))
    where.register_project(root, state)       # a second pointer to the state root, outside .onecrew/, for the hook when that folder is gone
    say(t('init.done', state=state, settings=settings_path, command=exe, rules=rules_path))
    if wiki_failed: say(t('init.wiki_failed', name=wiki_failed[0], path=wiki_step['shown'], why=wiki_failed[1], done=', '.join(wiki_written) or '-'))
    elif wiki_written: say(t('init.wiki_created', path=wiki_step['shown'], files=', '.join(wiki_written)))
    else: say(t('init.wiki_reuse', paths=', '.join(wiki_step.get('folders') or [wiki_step.get('shown', DEFAULT_WIKI)]), pages=wiki_step.get('pages', 0)))
    say(t('init.config_note'))
    state_name, path, why = claude()
    if state_name == 'ok': say(t('init.claude_ok', path=path))
    elif state_name == 'missing': say(t('init.claude_missing'))
    elif state_name == 'logged_out': say(t('init.claude_logged_out', path=path))
    else: say(t('init.claude_unknown', path=path, why=why))
    say(t('init.next'))
    if wiki_failed: return 3
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
        commands = {handler_words(h)[0][0] for entries in our_entries(data).values() for e in entries for h in e.get('hooks', []) if is_ours(h)}       # the program each runs, not the whole line
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


# ---- #25: the user-scope hook ------------------------------------------------------------------------------------------------
# One PreToolUse entry in the user's own Claude Code settings: a session opened outside an enforced project, and its subagents, then ask that project's
# plan (hook_cli.check --scope user). Only this entry is ours there: no other event, no permissions; every other key and hook stays as it was.

USER_MATCHER = 'Edit|Write|MultiEdit|NotebookEdit|Bash|PowerShell'
USER_ARGS = ['hook', 'check', '--scope', 'user']
OBSERVE_ARGS = ['hook', 'observe']


def _observer(handler):
    return (isinstance(handler, dict) and handler.get('type') == 'command' and handler.get('args') == OBSERVE_ARGS
            and re.split(r'[\\/]', str(handler.get('command', '')).strip())[-1].casefold() in EXE_NAMES)


def observed_events(settings):
    hooks = settings.get('hooks')
    if not isinstance(hooks, dict): return []
    return [name for name in OBSERVE_EVENTS if isinstance(hooks.get(name), list)
            and any(isinstance(entry, dict) and isinstance(entry.get('hooks'), list) and any(_observer(h) for h in entry['hooks'])
                    for entry in hooks[name])]


def merge_observers(hooks, exe):
    for name in OBSERVE_EVENTS:
        entries = hooks.get(name, [])
        if not isinstance(entries, list): raise SettingsShape('hooks.' + name, 'list')
        kept = []
        for entry in entries:
            handlers = entry.get('hooks') if isinstance(entry, dict) else None
            if not isinstance(handlers, list) or not any(_observer(h) for h in handlers):
                kept.append(entry)
            else:
                rest = [h for h in handlers if not _observer(h)]
                if rest: kept.append(dict(entry, hooks=rest))
        if exe:
            kept.append({'hooks': [{'type': 'command', 'command': str(exe), 'args': list(OBSERVE_ARGS),
                                    'timeout': 10, 'onFailure': 'continue'}]})
        if kept: hooks[name] = kept
        elif entries: hooks.pop(name)


def user_settings_file(env=None):
    """$CLAUDE_CONFIG_DIR/settings.json when that is set (and not empty), else ~/.claude/settings.json."""
    folder = (os.environ if env is None else env).get('CLAUDE_CONFIG_DIR')
    return Path(folder) / 'settings.json' if folder else Path.home() / '.claude' / 'settings.json'


def is_user_hook(handler):
    """The handler `hook user install` writes: an onecrew executable with exactly the arguments `hook check --scope user`."""
    if not isinstance(handler, dict) or handler.get('type', 'command') != 'command': return False
    command = handler.get('command')
    return isinstance(command, str) and handler.get('args') == USER_ARGS and re.split(r'[\\/]', command.strip())[-1].casefold() in EXE_NAMES


def user_handlers(settings):
    """[handler, ...] of the user-scope hook in a settings dict (PreToolUse entries only)."""
    entries = (settings.get('hooks') or {}).get('PreToolUse') if isinstance(settings.get('hooks'), dict) else None
    return [h for e in (entries if isinstance(entries, list) else []) if isinstance(e, dict) and isinstance(e.get('hooks'), list) for h in e['hooks'] if is_user_hook(h)]


def program_found(program):
    return bool(program) and (Path(program).is_file() or shutil.which(program) is not None)


def program_why_not(exe):
    """#25 (review P2-1): None when `exe` can be the program of the user hook, else the key of the reason (messages.py): it exists, it is named like onecrew
    (else `status` and `uninstall` would not know the entry), and it answers `--version`."""
    if not Path(exe).is_file(): return 'user.why_missing'
    if Path(exe).name.casefold() not in EXE_NAMES: return 'user.why_name'
    try:
        done = subprocess.run([str(exe), '--version'], capture_output=True, timeout=30, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return 'user.why_version'
    if done.returncode != 0: return 'user.why_version'
    return None if program_runs_scope(exe)[0] else 'user.why_scope'        # #25 (review 2, P3-2): the doctor's check, before anything is written


def program_runs_scope(program, hook_args=USER_ARGS):
    """#25 (review P2-7): (ok, why) of the hook's own program asked what Claude Code asks it: `hook check --scope user` with an empty event, started in a folder
    no plan governs. A OneCrew from before #25 refuses `--scope` (exit 2), which Claude Code reads as 'blocked' for every call."""
    env = {k: v for k, v in os.environ.items() if k not in ('CLAUDE_PROJECT_DIR', 'CLAUDECODE', 'CLAUDE_CODE_CHILD_SESSION')}
    try:
        with tempfile.TemporaryDirectory() as folder:
            done = subprocess.run([str(program), *hook_args], input=b'{}', capture_output=True, timeout=30, cwd=folder, env=env)
    except (OSError, subprocess.SubprocessError) as error:
        return False, f'{type(error).__name__}'
    if done.returncode == 0: return True, ''
    return False, f'exit {done.returncode}: ' + ((done.stderr or done.stdout).decode('utf-8', errors='replace').strip().splitlines() or [''])[-1][:160]


def _profile_form(path):
    """FIX25B (Codex F4): one normal form for a settings file, so every spelling of the same file gets the same answer: without a `\\\\?\\` / `\\\\.\\` prefix
    (`\\\\?\\UNC\\host\\share` is `\\\\host\\share`), resolved, and case-folded on Windows."""
    text = str(path)
    if text[:8].upper() == '\\\\?\\UNC\\': text = '\\\\' + text[8:]
    elif text.startswith(('\\\\?\\', '\\\\.\\')): text = text[4:]
    return os.path.normcase(os.path.realpath(text))


def user_hook(verb, settings_file=None, program=None, *, observe=False):
    """`onecrew hook user install|status|uninstall`. Exit code: 0 done (or nothing to do); 2 refused or nothing written (AI session on the user's own
    profile, bad settings file, no installed command)."""
    shown_path = Path(settings_file) if settings_file else user_settings_file()
    path = Path(os.path.realpath(shown_path))              # #25 (review P2-2): a settings file that is a symlink is read and written through the link; the link stays
    if verb != 'status' and os.path.islink(shown_path):    # #25 (review 2, P3-3): a link that loops or points nowhere is refused, never replaced by a file
        try:
            path = Path(os.path.realpath(shown_path, strict=True))
        except (OSError, RuntimeError):
            say(t('user.link_broken', path=shown_path))
            return 2
    data, bad = read_settings(path)
    if verb == 'status':
        handlers = user_handlers(data or {})
        shown = handlers[0]['command'] if handlers else (str(installed_exe()) if installed_exe() else None)
        print(json.dumps({'configured': bool(handlers), 'settings_file': str(shown_path), 'program': shown, 'program_found': program_found(shown),
                          'observation_events': observed_events(data or {}), 'error': bad}, ensure_ascii=False, indent=2))
        return 0
    from .ownership import claude_session
    try:       # #25 (review P2-3): the owner's profile is ~/.claude/settings.json and, when CLAUDE_CONFIG_DIR is set, the settings.json of that folder
        profiles = {_profile_form(p) for p in (Path.home() / '.claude' / 'settings.json', user_settings_file())}
        own = _profile_form(path) in profiles
    except OSError:
        own = False
    if own and claude_session():
        say(t('user.refused', path=shown_path, verb=verb))
        return 2
    if bad:
        say(t('init.bad_settings', reason=bad))
        return 2
    exe = None
    if verb == 'install':
        exe = Path(program).resolve() if program else installed_exe()
        if exe is None:
            say(t('user.no_exe'))
            return 2
        why = program_why_not(exe)
        if why:
            say(t('user.bad_program', program=exe, why=t(why)))
            return 2
        if (observe or observed_events(data)) and not program_runs_scope(exe, OBSERVE_ARGS)[0]:
            say(t('user.bad_program', program=exe, why='hook observe'))
            return 2
    merged = copy.deepcopy(data)
    backup = path.with_name(path.name + '.bak')
    # The permanent .bak can predate this installation. Track exactly which denies we add.
    ownership_file = path.with_name(path.name + '.onecrew-observation-rules.json')
    ownership, error = read_settings(ownership_file)
    if not error and ownership and (
        not isinstance(ownership.get('added'), list)
        or any(r not in hook_cli.OBSERVATION_DENY_RULES for r in ownership['added'])
        or not all(isinstance(ownership.get(k), bool) for k in ('had_permissions', 'had_deny'))
    ):
        error = f'Invalid OneCrew permission record: {ownership_file}'
    if error:
        say(t('init.bad_settings', reason=error))
        return 2
    record = None
    try:
        if verb == 'install':
            merged = merge_settings(merged, {'hooks': {}, 'permissions': {'deny': hook_cli.OBSERVATION_DENY_RULES}})
            previous = data.get('permissions', {})
            added = [r for r in hook_cli.OBSERVATION_DENY_RULES if r not in previous.get('deny', [])]
            record = dict(ownership) if ownership else {'added': [], 'had_permissions': 'permissions' in data, 'had_deny': 'deny' in previous}
            record['added'] = [r for r in hook_cli.OBSERVATION_DENY_RULES if r in record['added'] or r in added]
        elif ownership and user_handlers(data):
            perms = merged.get('permissions')
            if isinstance(perms, dict) and isinstance(perms.get('deny'), list):
                for rule in hook_cli.OBSERVATION_DENY_RULES:
                    if rule in ownership.get('added', []) and rule in perms['deny']:
                        perms['deny'].remove(rule)
                if not perms['deny'] and not ownership.get('had_deny'):
                    del perms['deny']
                if not perms and not ownership.get('had_permissions'):
                    del merged['permissions']
        hooks = merged.setdefault('hooks', {}) if verb == 'install' else merged.get('hooks', {})
        if not isinstance(hooks, dict): raise SettingsShape('hooks', 'object')
        entries = hooks.get('PreToolUse', [])
        if not isinstance(entries, list): raise SettingsShape('hooks.PreToolUse', 'list')
    except SettingsShape as error:
        say(t('init.bad_settings', reason=t('settings.shape', path=path, field=error.key, expected=t('shape.' + error.expected))))
        return 2
    kept = []
    for entry in entries:                                           # drop every user-scope handler; the entry goes with it when it held nothing else
        handlers = entry.get('hooks') if isinstance(entry, dict) and isinstance(entry.get('hooks'), list) else None
        if handlers is None or not any(is_user_hook(h) for h in handlers):
            kept.append(entry)
            continue
        rest = [h for h in handlers if not is_user_hook(h)]
        if rest: kept.append(dict(entry, hooks=rest))
    if verb == 'install':
        entry = {'matcher': USER_MATCHER, 'hooks': [{'type': 'command', 'command': str(exe), 'args': list(USER_ARGS), 'timeout': 15, 'onFailure': 'block'}]}
        place = next((i for i, e in enumerate(entries) if isinstance(e, dict) and any(is_user_hook(h) for h in e.get('hooks') or [] if isinstance(h, dict))), len(kept))
        hooks['PreToolUse'] = kept[:place] + [entry] + kept[place:]
    else:
        if hooks.get('PreToolUse') is not None: hooks['PreToolUse'] = kept
        if not kept: hooks.pop('PreToolUse', None)
        if not hooks: merged.pop('hooks', None)
    if observe or observed_events(data):
        try:
            merge_observers(hooks, exe)
        except SettingsShape as error:
            say(t('init.bad_settings', reason=t('settings.shape', path=path, field=error.key, expected=t('shape.' + error.expected))))
            return 2
        if not hooks: merged.pop('hooks', None)
    if merged == data:
        say(t('user.unchanged' if verb == 'install' else 'user.absent', path=shown_path))
        return 0
    try:
        if path.exists() and not backup.exists(): shutil.copyfile(path, backup)
        if record is not None and record != ownership:
            write_text(ownership_file, dump(record))
        write_text(path, dump(merged))
        if verb == 'uninstall' and ownership:
            ownership_file.unlink(missing_ok=True)
    except OSError as error:
        say(t('user.write_failed', path=shown_path, code=type(error).__name__))
        return 2
    say(t('user.installed', path=shown_path, program=exe, bak=backup if backup.exists() else '-') if verb == 'install' else t('user.removed', path=shown_path))
    return 0


def check_user_hook():
    """(level, detail) of the user-scope hook in the user's settings (CLAUDE_CONFIG_DIR, else the home folder), read the way `hook user status` reads it."""
    path = user_settings_file()
    data, bad = read_settings(path)
    if bad: return 'WARN', t('doctor.user_bad', reason=bad)
    handlers = user_handlers(data or {})
    if not handlers: return 'WARN', t('doctor.user_none')
    gone = next((h['command'] for h in handlers if not program_found(h['command'])), None)
    if gone: return 'FAIL', t('doctor.user_stale', path=path, command=gone)
    for handler in handlers:                           # #25 (review P2-7): the program is there; does it answer what Claude Code asks it?
        ok, why = program_runs_scope(handler['command'])
        if not ok: return 'FAIL', t('doctor.user_old', path=path, command=handler['command'], why=why)
    return 'PASS', t('doctor.user_ok', path=path)


def last_user_call(root):
    """The newest record of <root>/.onecrew/violations.jsonl with scope user (as a dict), or None."""
    try:
        lines = (Path(root) / '.onecrew' / 'violations.jsonl').read_text(encoding='utf-8', errors='replace').splitlines()
    except OSError:
        return None
    for line in reversed(lines):
        try:
            item = json.loads(line)
        except ValueError:
            continue
        if isinstance(item, dict) and item.get('scope') == 'user': return item
    return None


def _plan_readiness(document, root, state_root):
    from ..specs import digest
    from . import plan as plans
    from .report import _Reader

    name, revision, mode = (document.get(key) for key in ('plan', 'revision', 'mode'))
    status, pending = document.get('status'), document.get('pending_revision')
    project = os.path.normcase(str(root.resolve()))
    reader = _Reader(state_root, digest(project), project)
    with reader.transaction() as conn:
        state = plans.derive(reader, conn, document.get('anchor') or name) if name else None
    if state:
        approved = state['approved']
        pending = state['latest'] if not approved or state['latest'] > approved['revision'] else None
        status = state['status']
        if status == 'proposed' and approved:
            status = 'stopped_with_report' if approved['revision'] in state['stopped'] else 'approved'
    detail = t('doctor.plan_ok', name=name, revision=revision, mode=mode)
    if pending:
        detail += t('doctor.plan_pending', revision=pending)
    if status == 'accepted':
        return 'PASS', t('doctor.plan_accepted', name=name)
    if status in ('stopped_with_report', 'closed'):
        return 'WARN', detail + t('doctor.plan_stopped', status=status) + (t('doctor.plan_blocks') if mode == 'enforce' else '')
    expires = document.get('expires')
    if expires and dt.datetime.fromisoformat(expires) < dt.datetime.now(dt.timezone.utc):
        return ('FAIL' if mode == 'enforce' else 'WARN', detail + t('doctor.plan_expired', expires=expires, name=name)
                + (t('doctor.plan_blocks') if mode == 'enforce' else ''))
    if state and approved and revision != approved['revision']:
        return 'WARN', detail + t('doctor.plan_outdated', revision=approved['revision'], name=name)
    return ('PASS' if status == 'approved' else 'WARN'), detail


def doctor_facts(project=None, state_root=None, exe=None, claude=claude_status):
    """The doctor checks as [(level, name, detail)], printing nothing. claude=None skips the two Claude CLI checks (they start a program);
    the support bundle (diagnostics.py) uses that form."""
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
    state_name, path, why = claude() if claude is not None else ('not_probed', None, '')
    if state_name == 'not_probed':
        pass
    elif state_name == 'missing':
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
        copy = hook_cli.state_copy(chosen, root)
        if not plan_file.is_file() and copy is None: add('PASS', 'doctor.plan', t('doctor.plan_none'))
        else:
            if plan_file.is_file() and copy:
                plan, _, bad, _ = hook_cli.govern(plan_file, root, copy)
            else:
                # The hook may restore a missing project file. Doctor only reads its governing copy.
                plan, bad = hook_cli.load_plan(copy or plan_file)
            if bad: add('FAIL', 'doctor.plan', t('doctor.plan_bad', why=bad.split(':')[0]))
            else:
                try:
                    level, detail = _plan_readiness(plan, root, chosen)
                except (OSError, ValueError, sqlite3.Error, TypeError) as error:
                    level, detail = 'FAIL', t('doctor.plan_bad', why=str(error))
                add(level, 'doctor.plan', detail)
    level, detail = check_user_hook()                                  # #25
    add(level, 'doctor.user', detail)
    present = observed_events(read_settings(user_settings_file())[0] or {})
    complete = len(present) == len(OBSERVE_EVENTS)
    coverage = f'{len(present)}/{len(OBSERVE_EVENTS)}'
    if not complete:
        coverage += ' · hook user install --observe'
    add('PASS' if complete else 'WARN', 'doctor.observation', coverage)
    if root is not None:
        seen = last_user_call(root)
        add('PASS', 'doctor.user_calls', t('doctor.user_seen', at=seen.get('at'), session=seen.get('session')) if seen else t('doctor.user_unseen'))
    return lines


def doctor(project=None, state_root=None, exe=None, claude=claude_status):
    lines = doctor_facts(project, state_root, exe, claude)
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
