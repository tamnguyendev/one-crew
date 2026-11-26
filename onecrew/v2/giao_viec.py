"""GSDP-A (#63, decision D7/D10): the delegation reminder. When the session's plan is a standing plan, a delegation (Agent, Task, SendMessage,
start_session, send_message) whose text lacks an item of the owner's template gets one `reminded` line and the list of missing items as
additionalContext. It only reminds: it never blocks, never asks, and any error in it is silence (hook_cli.remind always exits 0).

The template is `<state-root>/plans/mau-giao-viec.md`, written by `onecrew init --remind on` when it is missing (like owner-rules.md); the owner edits it.
One item per line: `- <name>: <keyword>, <keyword>, ...`. A delegation that holds one keyword of an item (case-insensitive, anywhere in ANY string of
tool_input: the field names of SendMessage and start_session are not documented, so no field name is relied on) has that item. Lines that start with
`#` and blank lines are skipped. A missing file means the built-in template below; a file with no item means no reminder; an unreadable file means
silence. The match is by keyword only: it knows a heading is there, not that what follows it is right (D10).

QLMAU: every prompt template (the delegation template, the owner-words reminder, the role templates under docs/vai3/) opens with one header line
`onecrew-mau: ten=<name> phien-ban=<integer>` (a `#` or `<!-- -->` comment). The person who edits a template raises its number; the short hash is
computed. `onecrew mau list` / `mau lint` are here too: they only read template files (no ledger, no skill, no write). The module is the one that
owns the templates; a template without a header still works and shows its version as unknown.
"""
import argparse
import hashlib
import re
import unicodedata
from pathlib import Path

TEMPLATE_NAME = 'mau-giao-viec.md'
TOOLS = ('Agent', 'Task', 'SendMessage', 'mcp__ccd_session__start_session', 'mcp__ccd_session_mgmt__send_message')
MATCHER = '|'.join(TOOLS)
MAX_CHARS = 400_000          # the text read from one tool_input; a longer delegation is cut, never refused
DEFAULT_TEMPLATE = '''# onecrew-mau: ten=mau-giao-viec phien-ban=1
# Mẫu giao việc: OneCrew nhắc khi lời giao việc của plan thường trực thiếu mục (chỉ nhắc, không chặn).
# Mỗi dòng "- <tên mục>: <từ khóa>, <từ khóa>, ..." là một mục; lời giao có một từ khóa (không phân biệt hoa thường) là đủ mục đó.
# Dòng bắt đầu bằng # và dòng trống được bỏ qua. Chủ sở hữu sửa tệp này bất cứ lúc nào; tệp không còn mục nào thì không nhắc.
- Mục tiêu: mục tiêu, mục đích, goal, objective
- Tệp được sửa: tệp được sửa, phạm vi, chỉ sửa, files, scope
- Xong khi: xong khi, hoàn thành khi, done when, definition of done
- Không làm: không làm, không được, not doing, non-goal, do not
- Cách kiểm: cách kiểm, kiểm bằng, kiểm tra, verify, how to check
- Skill: skill
'''


# The words GSDP-A shows (install.py and owner_cli.py keep no Vietnamese text of their own; messages.py is outside this change)
INIT_TEXT = {
    'step': {'en': 'Delegation reminder (--remind on): a separate PreToolUse entry `hook remind` for Agent, Task, SendMessage, start_session, send_message; it only reminds a standing plan, never blocks. Template: {path}',
             'vi': 'Nhắc lời giao việc (--remind on): một mục PreToolUse riêng `hook remind` cho Agent, Task, SendMessage, start_session, send_message; chỉ nhắc khi plan là thường trực, không bao giờ chặn. Tệp mẫu: {path}'},
    'off': {'en': 'Delegation reminder (--remind off): the `hook remind` entry is removed; every other entry stays.',
            'vi': 'Nhắc lời giao việc (--remind off): gỡ mục `hook remind`; các mục khác giữ nguyên.'},
    'template': {'en': 'Delegation template written (the owner edits it): {path}', 'vi': 'Đã ghi tệp mẫu giao việc (chủ sở hữu sửa được): {path}'},
}
# what `owner approve --human` adds for a standing plan (D6), so the owner sees at once what was approved
STANDING_HUMAN = ('Plan {plan} là plan THƯỜNG TRỰC (standing): hết hạn {expires} (lúc duyệt + {minutes} phút; xuất lại không kéo dài hạn, chỉ lần duyệt mới '
                  'đặt hạn mới). Dừng lượt (Stop) không chặn và không ghi dòng nhật ký vi phạm mỗi lượt. Sửa và lệnh vẫn bị xét như plan thường; hết hạn ở chế độ chặn '
                  'thì mọi sửa và lệnh bị chặn tới khi bạn duyệt lại. Cách thoát: owner enforce {plan} --mode log.')
LOCAL_TIME = ' (giờ máy)'
EXPIRY_RULE = 'lúc duyệt + {minutes} phút'


# VAI3: the reminder when the OWNER types straight into a session under a standing plan. The app wraps what it sends on its own (another session's
# message, its events) or heads it "[Cross-session ...]" (its notices about delivery and idle sessions); text that does not start with one of
# these is taken as the owner's (D3: an unknown wrapper counts as the owner).
APP_WRAPPERS = ('cross-session-message', 'system-reminder', 'task-notification', 'side-sessions-event', 'ci-monitor-event')
_APP_WRAPPED = re.compile(r'<(?:' + '|'.join(APP_WRAPPERS) + r')(?=[\s/>]|$)|\[Cross-session ')
OWNER_TEMPLATE_NAME = 'mau-loi-chu.md'      # <state-root>/plans/: the owner's own reminder text; an empty file turns the reminder off (D6)
OWNER_MAX_CHARS = 4_000
_LEADING = chr(0xFEFF) + ' \t\r\n'          # blank space and a byte-order mark before the wrapper
_OWNER_HEADER = '# onecrew-mau: ten=mau-loi-chu phien-ban=1\n'     # removed before the text is sent (see owner_reminder)
OWNER_TEXT = {
    'vi': (_OWNER_HEADER + 'Chủ sở hữu vừa gõ thẳng vào phiên này (plan thường trực {plan}). Trước khi làm: (1) ghi lời đó, nguyên văn kèm giờ, vào sổ yêu cầu '
           '(mặc định YEU-CAU-CHU.vi.md ở thư mục của phiên); (2) báo phiên trao đổi một dòng; rồi làm. Nếu lời đó là một quyết định thì ghi thêm vào '
           'sổ quyết định của repo bằng `onecrew decision add` (phạm vi, tiêu đề, lời nguyên văn). Lời nhắc này không chặn gì.'),
    'en': (_OWNER_HEADER + 'The owner just typed straight into this session (standing plan {plan}). Before acting: (1) write those words, verbatim with the time, '
           'into the owner request log (default YEU-CAU-CHU.vi.md in the session folder); (2) tell the exchange session in one line; then carry on. '
           "If those words are a decision, also record it in the repository's decision book with `onecrew decision add` (scope, title, the words verbatim). "
           'This reminder blocks nothing.'),
}
OWNER_NOTE = 'owner typed straight into a standing plan session; reminded to log the words and tell the exchange session'   # the ledger line: never the words
# `plan present` of a standing plan: the owner sees the flag BEFORE approving (STANDING_HUMAN below is what `owner approve` says after)
STANDING_PRESENT = ('THƯỜNG TRỰC (standing): hợp đồng này hết hạn lúc duyệt + {minutes} phút (xuất lại không kéo dài hạn); dừng lượt (Stop) không '
                    'chặn; sửa và lệnh vẫn bị xét như plan thường.')


def owner_typed(prompt):
    """True when the text of a new turn counts as the owner's: any text that does not start with one of the app's own wrappers or notices."""
    if not isinstance(prompt, str) or not prompt.strip(): return False
    return not _APP_WRAPPED.match(prompt.lstrip(_LEADING))


def owner_reminder(plan, state_root, language):
    """The reminder text: <state-root>/plans/mau-loi-chu.md when it is there ('' when it is empty or holds only its header line: no reminder), else the
    built-in text. The `onecrew-mau:` header line is never sent. Raises OSError/ValueError when the file cannot be read."""
    path = Path(state_root) / 'plans' / OWNER_TEMPLATE_NAME if state_root else None
    if path is not None and path.exists(): return without_header(path.read_text(encoding='utf-8-sig')).strip()[:OWNER_MAX_CHARS]
    return without_header(OWNER_TEXT['vi' if language == 'vi' else 'en']).format(plan=plan)


# ---- QLMAU: the version header -------------------------------------------------------------------------------------------------

_HEADER = re.compile(r'[ \t]*(?:#+[ \t]*|<!--[ \t]*)?onecrew-mau:[ \t]*ten=([a-z0-9][a-z0-9-]*)[ \t]+phien-ban=([0-9]{1,9})[ \t]*(?:-->)?[ \t]*\Z')
UNKNOWN_VERSION = 'chua-ghi'


def header(text):
    """(name, version) of the header on the FIRST line of a template text, or None."""
    lines = text.lstrip(chr(0xFEFF)).splitlines()
    found = _HEADER.match(lines[0]) if lines else None
    return (found.group(1), int(found.group(2))) if found else None


def without_header(text):
    """The text with its header line removed; the text itself when it has none."""
    text = text.lstrip(chr(0xFEFF))
    return ''.join(text.splitlines(keepends=True)[1:]) if header(text) else text


def delegation_version(state_root):
    """The version of the delegation template in force (the owner's file, else the built-in one); None when its header says none or it cannot be read."""
    try:
        path = template_path(state_root) if state_root else None
        text = path.read_text(encoding='utf-8-sig') if path is not None and path.exists() else DEFAULT_TEMPLATE
    except (OSError, ValueError):
        return None
    found = header(text)
    return found[1] if found else None


def init_text(key, language, **values):
    return INIT_TEXT[key]['vi' if language == 'vi' else 'en'].format(**values)


def template_path(state_root):
    return Path(state_root) / 'plans' / TEMPLATE_NAME


def parse(text):
    """[(name, [keyword, ...])] of a template text, in file order. A line without ':' or without a keyword is not an item."""
    items = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith('#') or _HEADER.match(line): continue
        if line[:1] in '-*': line = line[1:].strip()
        name, colon, rest = line.partition(':')
        words = [w.strip() for w in rest.split(',') if w.strip()]
        if colon and name.strip() and words: items.append((name.strip(), words))
    return items


def items_for(state_root):
    """The items of the owner's template; the built-in template when the file is missing. Raises OSError/ValueError when it cannot be read."""
    path = template_path(state_root) if state_root else None
    if path is None or not path.exists(): return parse(DEFAULT_TEMPLATE)
    return parse(path.read_text(encoding='utf-8-sig'))


def write_default(state_root):
    """Write the built-in template when the state root has none. True when written; an existing file (the owner's) is never touched."""
    path = template_path(state_root)
    if path.exists(): return False
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'x', encoding='utf-8', newline='\n') as stream: stream.write(DEFAULT_TEMPLATE)
    return True


def strings(value, out=None, depth=0):
    """Every string value inside `value` (dict values, list items), depth first. Field NAMES are left out (a field called "scope" is not the item
    "scope"), and so are numbers and the like."""
    out = [] if out is None else out
    if depth > 20: return out
    if isinstance(value, str): out.append(value)
    elif isinstance(value, dict):
        for item in value.values(): strings(item, out, depth + 1)
    elif isinstance(value, (list, tuple)):
        for item in value: strings(item, out, depth + 1)
    return out


def missing(items, tool_input):
    """The names of the items none of whose keywords appear in any string of tool_input."""
    text = '\n'.join(strings(tool_input))[:MAX_CHARS].casefold()
    return [name for name, words in items if not any(word.casefold() in text for word in words)]


# SQD (I5): a delegation of a repository that has decisions in force says which one applies: an id "SQD-n", or the sentence below. Like the
# template items, it is a match on form: it knows a decision is named, not that it is the right one (D4).
DECISION_ID = re.compile(r'(?<![\w-])sqd-\d+(?!\w)')
NO_DECISION = unicodedata.normalize('NFC', 'không có quyết định liên quan')
DECISIONS_NAMED = 10         # at most this many (the newest) in the reminder


def names_decision(tool_input):
    """True when any string of tool_input holds "SQD-n" or "không có quyết định liên quan" (any case, any Unicode form, any spacing)."""
    text = unicodedata.normalize('NFC', '\n'.join(strings(tool_input))[:MAX_CHARS]).casefold()
    return bool(DECISION_ID.search(text)) or NO_DECISION in ' '.join(text.split())


def decision_reminder(plan, tool, records):
    """One line: the decisions in force (id and title, never the owner's words)."""
    shown = records[-DECISIONS_NAMED:]
    listed = '; '.join(f"{r['id']} {' '.join(r['title'].split())}" for r in shown)
    more = f'; và {len(records) - len(shown)} quyết định cũ hơn (onecrew decision list)' if len(records) > len(shown) else ''
    return (f'OneCrew (plan thường trực {plan}): lời giao việc vừa gửi qua {tool} chưa nói quyết định nào của chủ áp cho việc này. '
            f'Còn hiệu lực: {listed}{more}. Nêu mã SQD-n áp dụng hoặc ghi "{NO_DECISION}". Việc giao KHÔNG bị chặn.')


def reminder(plan, tool, names, state_root):
    path = template_path(state_root) if state_root else TEMPLATE_NAME
    version = delegation_version(state_root)
    mark = f'mau-giao-viec@{UNKNOWN_VERSION if version is None else version}'
    return (f"OneCrew (plan thường trực {plan}): lời giao việc vừa gửi qua {tool} thiếu mục: {', '.join(names)}. "
            f"Việc giao KHÔNG bị chặn. Bổ sung các mục này cho người nhận (hoặc ở lần giao sau). Mẫu của chủ sở hữu: {path} (mẫu {mark}).")


# ---- QLMAU: `onecrew mau list` and `onecrew mau lint` (read only) ---------------------------------------------------------------

ROLE_FOLDER = ('docs', 'vai3')                      # not in the wheel: read from the project, else beside the code (a checkout)
ROLE_SECTIONS = {'vi': ('Việc của vai', 'Không làm', 'Nhận việc từ', 'Báo cho'), 'en': ('Role', 'Not doing', 'Takes work from', 'Reports to')}
BUILT_IN = {'en': '(built into the program)', 'vi': '(có sẵn trong chương trình)'}
MAU_TEXT = {
    'no_header': {'en': 'no valid header line `onecrew-mau: ten=<name> phien-ban=<integer>` on the first line',
                  'vi': 'dòng đầu không có `onecrew-mau: ten=<tên> phien-ban=<số>` hợp lệ'},
    'same_name': {'en': 'the name "{value}" is already used by {other}', 'vi': 'tên "{value}" đã dùng ở {other}'},
    'unreadable': {'en': 'cannot be read: {value}', 'vi': 'không đọc được: {value}'},
    'not_item': {'en': 'not an item `- <name>: <keyword>, ...`', 'vi': 'dòng không phải mục `- <tên mục>: <từ khóa>, ...`'},
    'empty_item': {'en': 'item "{value}" has no keyword', 'vi': 'mục "{value}" bỏ trống, không có từ khóa'},
    'same_item': {'en': 'item "{value}" is written twice (line {other})', 'vi': 'mục "{value}" viết hai lần (dòng {other})'},
    'overlap': {'en': 'keyword "{value}" is already in item "{other}"', 'vi': 'từ khóa "{value}" đã có ở mục "{other}" (chồng chéo)'},
    'missing_item': {'en': 'required item missing: {value}', 'vi': 'thiếu mục bắt buộc: {value}'},
    'missing_part': {'en': 'required part missing: ## {value}', 'vi': 'thiếu phần của vai: ## {value}'},
    'empty_part': {'en': 'part "## {value}" is empty', 'vi': 'phần "## {value}" bỏ trống'},
    'same_part': {'en': 'part "## {value}" is written twice', 'vi': 'phần "## {value}" viết hai lần'},
    'off': {'en': 'NOTE {name} {path}: no text, so this reminder is turned off', 'vi': 'GHI CHÚ {name} {path}: không có chữ, nên lời nhắc này đang tắt'},
    'no_roles': {'en': 'NOTE role templates not found (no docs/vai3 under {value}); point --project at a checkout that has it',
                 'vi': 'GHI CHÚ không thấy mẫu vai (không có docs/vai3 ở {value}); trỏ --project vào bản mã có thư mục đó'},
    'passed': {'en': 'PASS: {value} templates meet the norm', 'vi': 'ĐẠT: {value} mẫu đúng quy chuẩn'},
    'failed': {'en': 'FAIL: {value} problem(s)', 'vi': 'KHÔNG ĐẠT: {value} lỗi'},
}


def mau_text(key, language, **values):
    return MAU_TEXT[key]['vi' if language == 'vi' else 'en'].format(**values)


def _entry(kind, name, path, built_in=None):
    """One template: {kind, name, path, text, version, sha, problem}. `built_in` is the program's own text (no file)."""
    entry = {'kind': kind, 'name': name, 'path': str(path), 'text': None, 'version': None, 'sha': '-', 'problem': None}
    try:
        data = built_in.encode('utf-8') if built_in is not None else Path(path).read_bytes()
        entry['text'] = data.decode('utf-8-sig')
    except (OSError, ValueError) as error:
        entry['problem'] = type(error).__name__
        return entry
    entry['sha'] = hashlib.sha256(data).hexdigest()[:12]
    found = header(entry['text'])
    if found: entry['name'], entry['version'] = found
    return entry


def role_folders(project):
    return [Path(project).joinpath(*ROLE_FOLDER), Path(__file__).resolve().parents[2].joinpath(*ROLE_FOLDER)]


def entries(project, state_root, language):
    """The templates in force: the delegation template and the owner-words reminder (the owner's file under <state-root>/plans/ when there is one, else
    the built-in text), then every *.md of docs/vai3. Only these files are read: no ledger, no skill."""
    result = []
    for kind, name, file, built_in in (('delegation', 'mau-giao-viec', TEMPLATE_NAME, DEFAULT_TEMPLATE),
                                       ('owner', 'mau-loi-chu', OWNER_TEMPLATE_NAME, OWNER_TEXT['vi' if language == 'vi' else 'en'])):
        path = Path(state_root) / 'plans' / file if state_root else None
        if path is not None and path.exists(): result.append(_entry(kind, name, path))
        else: result.append(_entry(kind, name, BUILT_IN['vi' if language == 'vi' else 'en'], built_in))
    folder = next((f for f in role_folders(project) if f.is_dir()), None)
    for path in sorted(folder.glob('*.md')) if folder else ():
        result.append(_entry('role', 'vai-' + path.stem.replace('.', '-'), path))
    return result


def _lint_items(text):
    """[(line, key, values)] of the delegation template: not an item, empty item, overlap, required item of the built-in template missing."""
    found, names, words_of, items = [], {}, {}, []
    for number, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith('#') or _HEADER.match(line): continue
        if line[:1] in '-*': line = line[1:].strip()
        name, colon, rest = line.partition(':')
        name, words = name.strip(), [w.strip() for w in rest.split(',') if w.strip()]
        if not colon or not name:
            found.append((number, 'not_item', {}))
            continue
        if not words:
            found.append((number, 'empty_item', {'value': name}))
            continue
        items.append((name, words))
        if name.casefold() in names: found.append((number, 'same_item', {'value': name, 'other': names[name.casefold()]}))
        else: names[name.casefold()] = number
        for word in words:
            first = words_of.setdefault(word.casefold(), (number, name))
            if first[0] != number: found.append((number, 'overlap', {'value': word, 'other': first[1]}))
    # a required item is there when an item has its name or one of its keywords, so an owner may rename it or keep one language only
    have = {n.casefold() for n, _ in items} | {w.casefold() for _, words in items for w in words}
    lacking = [name for name, words in parse(DEFAULT_TEMPLATE) if not ({name.casefold(), *(w.casefold() for w in words)} & have)]
    if lacking: found.append((1, 'missing_item', {'value': ', '.join(lacking)}))
    return found


def _lint_role(text, path):
    """[(line, key, values)] of a role template: each part of the role is there once and holds some text."""
    sections = ROLE_SECTIONS['en' if path.endswith('.en.md') else 'vi']
    found, parts, current = [], {}, None
    for number, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if line.startswith('## '):
            current = line[3:].strip()
            if current in parts: found.append((number, 'same_part', {'value': current}))
            else: parts[current] = [number, False]
        elif line and current in parts: parts[current][1] = True
    for name in sections:
        if name not in parts: found.append((1, 'missing_part', {'value': name}))
        elif not parts[name][1]: found.append((parts[name][0], 'empty_part', {'value': name}))
    return found


def lint(templates, language):
    """(problems, notes): the one norm of every template: a valid header, no overlap (names, items, keywords, parts), nothing left empty or missing."""
    problems, notes, seen = [], [], {}
    for entry in templates:
        def problem(line, key, **values):
            problems.append(f"{entry['name']} {entry['path']}:{line}: {mau_text(key, language, **values)}")
        if entry['text'] is None:
            problem(0, 'unreadable', value=entry['problem'])
            continue
        if entry['kind'] == 'owner' and not without_header(entry['text']).strip():
            notes.append(mau_text('off', language, name=entry['name'], path=entry['path']))
            if not entry['text'].strip(): continue
        if entry['version'] is None: problem(1, 'no_header')
        if entry['name'] in seen: problem(1, 'same_name', value=entry['name'], other=seen[entry['name']])
        else: seen[entry['name']] = entry['path']
        if entry['kind'] == 'delegation': found = _lint_items(entry['text'])
        elif entry['kind'] == 'role': found = _lint_role(entry['text'], entry['path'])
        else: found = []
        for line, key, values in found: problem(line, key, **values)
    return problems, notes


def mau_main(args):
    """`onecrew [--project <p>] [--state-root <s>] mau list|lint`. Reads template files only and writes nothing. lint: exit 1 when a rule is broken."""
    from . import messages, where
    parser = argparse.ArgumentParser(prog='onecrew')
    parser.add_argument('--project')
    parser.add_argument('--state-root')
    parser.add_argument('group', choices=['mau'])
    parser.add_argument('command', choices=['list', 'lint'], help='list: name, version, short hash, path; lint: one norm for every template')
    options = parser.parse_args(args)
    project = Path(options.project) if options.project else Path.cwd()
    state_root = options.state_root or where.configured_state_root(project) or where.registered_state_root(project) or where.default_state_root()
    language = messages.lang()
    templates = entries(project, state_root, language)
    roles = any(e['kind'] == 'role' for e in templates)
    note = None if roles else mau_text('no_roles', language, value=project)
    if options.command == 'list':
        for e in templates:
            version = UNKNOWN_VERSION if e['version'] is None else e['version']
            print(f"{e['name']}  phien-ban={version}  {e['sha']}  {e['path']}")
        if note: print(note)
        return 0
    problems, notes = lint(templates, language)
    for line in [*notes, *([note] if note else []), *problems]: print(line)
    print(mau_text('failed', language, value=len(problems)) if problems else mau_text('passed', language, value=len(templates)))
    return 1 if problems else 0
