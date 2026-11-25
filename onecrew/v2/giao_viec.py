"""GSDP-A (#63, decision D7/D10): the delegation reminder. When the session's plan is a standing plan, a delegation (Agent, Task, SendMessage,
start_session, send_message) whose text lacks an item of the owner's template gets one `reminded` line and the list of missing items as
additionalContext. It only reminds: it never blocks, never asks, and any error in it is silence (hook_cli.remind always exits 0).

The template is `<state-root>/plans/mau-giao-viec.md`, written by `onecrew init --remind on` when it is missing (like owner-rules.md); the owner edits it.
One item per line: `- <name>: <keyword>, <keyword>, ...`. A delegation that holds one keyword of an item (case-insensitive, anywhere in ANY string of
tool_input: the field names of SendMessage and start_session are not documented, so no field name is relied on) has that item. Lines that start with
`#` and blank lines are skipped. A missing file means the built-in template below; a file with no item means no reminder; an unreadable file means
silence. The match is by keyword only: it knows a heading is there, not that what follows it is right (D10).
"""
import re
from pathlib import Path

TEMPLATE_NAME = 'mau-giao-viec.md'
TOOLS = ('Agent', 'Task', 'SendMessage', 'mcp__ccd_session__start_session', 'mcp__ccd_session_mgmt__send_message')
MATCHER = '|'.join(TOOLS)
MAX_CHARS = 400_000          # the text read from one tool_input; a longer delegation is cut, never refused
DEFAULT_TEMPLATE = '''# Mẫu giao việc: OneCrew nhắc khi lời giao việc của plan thường trực thiếu mục (chỉ nhắc, không chặn).
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
# message, its events); text that does not start with one of these wrappers is taken as the owner's (D3: an unknown wrapper counts as the owner).
APP_WRAPPERS = ('cross-session-message', 'system-reminder', 'task-notification', 'side-sessions-event', 'ci-monitor-event')
_APP_WRAPPED = re.compile(r'<(?:' + '|'.join(APP_WRAPPERS) + r')(?=[\s/>]|$)')
OWNER_TEMPLATE_NAME = 'mau-loi-chu.md'      # <state-root>/plans/: the owner's own reminder text; an empty file turns the reminder off (D6)
OWNER_MAX_CHARS = 4_000
_LEADING = chr(0xFEFF) + ' \t\r\n'          # blank space and a byte-order mark before the wrapper
OWNER_TEXT = {
    'vi': ('Chủ sở hữu vừa gõ thẳng vào phiên này (plan thường trực {plan}). Trước khi làm: (1) ghi lời đó, nguyên văn kèm giờ, vào sổ yêu cầu '
           '(mặc định YEU-CAU-CHU.vi.md ở thư mục của phiên); (2) báo phiên trao đổi một dòng; rồi làm. Lời nhắc này không chặn gì.'),
    'en': ('The owner just typed straight into this session (standing plan {plan}). Before acting: (1) write those words, verbatim with the time, '
           'into the owner request log (default YEU-CAU-CHU.vi.md in the session folder); (2) tell the exchange session in one line; then carry on. '
           'This reminder blocks nothing.'),
}
OWNER_NOTE = 'owner typed straight into a standing plan session; reminded to log the words and tell the exchange session'   # the ledger line: never the words
# `plan present` of a standing plan: the owner sees the flag BEFORE approving (STANDING_HUMAN below is what `owner approve` says after)
STANDING_PRESENT = ('THƯỜNG TRỰC (standing): hợp đồng này hết hạn lúc duyệt + {minutes} phút (xuất lại không kéo dài hạn); dừng lượt (Stop) không '
                    'chặn; sửa và lệnh vẫn bị xét như plan thường.')


def owner_typed(prompt):
    """True when the text of a new turn counts as the owner's: any text that does not start with one of the app's own wrappers."""
    if not isinstance(prompt, str) or not prompt.strip(): return False
    return not _APP_WRAPPED.match(prompt.lstrip(_LEADING))


def owner_reminder(plan, state_root, language):
    """The reminder text: <state-root>/plans/mau-loi-chu.md when it is there ('' when it is empty: no reminder), else the built-in text.
    Raises OSError/ValueError when the file cannot be read."""
    path = Path(state_root) / 'plans' / OWNER_TEMPLATE_NAME if state_root else None
    if path is not None and path.exists(): return path.read_text(encoding='utf-8-sig').strip()[:OWNER_MAX_CHARS]
    return OWNER_TEXT['vi' if language == 'vi' else 'en'].format(plan=plan)


def init_text(key, language, **values):
    return INIT_TEXT[key]['vi' if language == 'vi' else 'en'].format(**values)


def template_path(state_root):
    return Path(state_root) / 'plans' / TEMPLATE_NAME


def parse(text):
    """[(name, [keyword, ...])] of a template text, in file order. A line without ':' or without a keyword is not an item."""
    items = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith('#'): continue
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


def reminder(plan, tool, names, state_root):
    path = template_path(state_root) if state_root else TEMPLATE_NAME
    return (f"OneCrew (plan thường trực {plan}): lời giao việc vừa gửi qua {tool} thiếu mục: {', '.join(names)}. "
            f"Việc giao KHÔNG bị chặn. Bổ sung các mục này cho người nhận (hoặc ở lần giao sau). Mẫu của chủ sở hữu: {path}.")
