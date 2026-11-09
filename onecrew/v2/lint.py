"""`onecrew plan lint --file <json> [--author <id>]`: every refusal that propose + approve would raise for the *form* of a contract, listed
at once, before anything is written (v2.1 job 11a).

Nothing here is a copy of a rule: `contract.validate` (schema, text limits), `step0.check_target` / `step0._bad_evidence` /
`step0.check_provenance` (target paths, evidence, origin and item sources) and the reviewer's `MODEL_LIKE` are the functions the
real path calls. What lint adds is only the list, the typed codes, and the argv control-character check.

It is read-only on purpose: the ledger is opened through `ReadOnlyLedger`, whose `transaction(write=True)` raises, and
`step0.evaluate(run=False)` neither runs a precondition nor stores a receipt. No ledger event and no file is written.
"""
import os
import re
import subprocess
from contextlib import contextmanager

from ..ledger import Ledger, LedgerError, content_hash, text_field
from . import contract as contracts, step0
from .plan import refuse_owner_author
from .ownership import OWNER_ACTORS
from .verifiers import command
from .verifiers.reviewer import MODEL_LIKE

# The reasons of evaluate() that are about the form of the contract. The rest (unknowns open, options not chosen, advice, preconditions)
# belong to the approval itself and say nothing about a typo, so lint leaves them to approve.
FORM_CODES = ('target_repo', 'target_ref', 'target_path', 'assumption_no_evidence', 'assumption_evidence_invalid', 'option_evidence_invalid',
              'origin_missing', 'item_without_source', 'unknown_decision', 'unknowns_missing')


class ReadOnlyLedger(Ledger):
    """The ledger of a lint run: reads work, a write is an error (not a convention)."""

    @contextmanager
    def transaction(self, write=False):
        if write: raise LedgerError('plan lint is read-only: it never writes the ledger.')
        with super().transaction() as conn:
            yield conn


def _argv_lists(raw):
    """(where, argv) for every command verifier and every command precondition of the raw JSON, as far as it is shaped like a contract."""
    found = []
    if not isinstance(raw, dict): return found
    for m in raw.get('milestones') if isinstance(raw.get('milestones'), list) else ():
        verifier = m.get('verifier') if isinstance(m, dict) else None
        config = verifier.get('config') if isinstance(verifier, dict) and verifier.get('type') == 'command' else None
        if isinstance(config, dict) and isinstance(config.get('argv'), list): found.append((f'milestone {m.get("id")}', config['argv']))
    for p in raw.get('preconditions') if isinstance(raw.get('preconditions'), list) else ():
        args = p.get('args') if isinstance(p, dict) else None
        if isinstance(args, dict) and isinstance(args.get('argv'), list): found.append((f'precondition {p.get("id")}', args['argv']))
    return found


def _control_chars(raw):
    reasons = []
    for where, argv in _argv_lists(raw):
        for number, element in enumerate(argv):
            if isinstance(element, str) and command.CONTROL.search(element):
                reasons.append(('argv_control_char', f'{where}: argv[{number}] contains a control character ({element[:40]!r}); '
                                                     'the command would not run as written.'))
    return reasons


def _author(author):
    if author is None: return []
    try:
        text_field(author, 'author', 100)
        refuse_owner_author(author)
    except LedgerError as error:
        return [('author_invalid', str(error))]
    if author not in OWNER_ACTORS and not MODEL_LIKE.fullmatch(author):
        return [('author_not_model_id', f'author "{author}" is not a model id (like claude-sonnet-5-5), so a reviewer cannot tell whether it is independent.')]
    return []


def lint(ledger, raw, author=None):
    """[(code, text)] in the order a reader fixes them; empty when the contract would pass the form checks of propose and approve."""
    reasons = _author(author) + _control_chars(raw)
    try:
        contract = contracts.validate(raw)
    except LedgerError as error:
        code = ('text_over_limit' if 'at most' in str(error) and 'characters' in str(error)
                else 'authority' if str(error).startswith('authority') else 'schema')
        return reasons + [(code, str(error))]
    verdict = step0.evaluate(ledger, 'lint', 0, content_hash(contract), contract, {}, choose=contract['options']['recommended'] if contract['options'] else None,
                             run=False, author=author)
    return reasons + [r for r in verdict['reasons'] if r[0] in FORM_CODES] + owner_view(ledger, contract) + no_fail_clause(raw)


# ---- dev11: the owner part of a contract ---------------------------------------------------------------------------------------------
# presentation.request / user_sees / acceptance_steps / not_doing: the four sentences the tracking page shows whoever follows the work.
# Required once the owner-rules file exists in the state root (the owner's own setup, as for the provenance rules); plain words whenever given.
OWNER_PARTS = (('request', 'Việc này làm gì'), ('user_sees', 'Xong bạn thấy gì'), ('acceptance_steps', 'Làm sao biết đạt'), ('not_doing', 'Không làm gì'))
OWNER_CODES = ('owner_view_missing', 'owner_view_technical')
# dev14 (owner 09/11 "Đồng ý": refuse only what is certainly technical, warn on what may be). Two levels, because the same shapes are everyday
# Vietnamese, medical above all: ICD codes (F32.1, I10, J18.9), doses (5 mg/kg/ngày, 1 mg/kg/24 giờ), vitamins and rooms (D3, phòng B12), choices
# (A/B/C, Q1/Q2). A pattern list that refuses every ambiguous shape never stops growing; a warning lets the author look and the owner decide.
# CERTAIN (owner_view_technical, refused): a Windows/UNC path; a path starting with / ./ ../ ~/; a URL with a scheme; a file name with a known
# extension; a --flag; text in backticks; a hash; a system error name; a OneCrew code in its own context (mốc M1, rev 2, v2.5, dev12, Sol6, OBS-1).
_EXT = (r'py|pyc|json|md|ps1|psm1|txt|js|mjs|cjs|jsx|ts|tsx|vue|html?|css|scss|less|ya?ml|toml|ini|cfg|conf|env|sqlite3?|db|sql|whl|exe|dll|so|'
        r'dylib|msi|msix|sh|bat|cmd|cs|csproj|sln|java|kt|kts|gradle|go|rs|c|h|cpp|hpp|rb|php|swift|xml|plist|proto|csv|log|apk|aab|ipa|jar|'
        r'zip|tar|gz|tgz|7z|lock|ipynb|pem|crt|pfx|p12')
CERTAIN = (
    ('đường dẫn', re.compile(r'(?<![\w])[A-Za-z]:\\[^\s,;]*|\\\\[^\s,;]+|(?<![\w\\])[\w.-]+(?:\\[\w.-]+)+')),
    ('đường dẫn', re.compile(r'(?<![\w/.~])(?:~|\.\.?)/[A-Za-z0-9_.][A-Za-z0-9_.-]*(?:/[A-Za-z0-9_.-]+)*'
                             r'|(?<![\w/.~])/[A-Za-z_.][A-Za-z0-9_.-]*(?:/[A-Za-z0-9_.-]+)+')),
    ('địa chỉ web', re.compile(r'\b[A-Za-z][A-Za-z0-9+.-]*://\S+')),
    ('tên file', re.compile(rf'(?<![\w.])[\w/-]*[\w-]\.(?:{_EXT})\b|(?<![\w.])\.(?:env|git|gitignore|venv|vscode|claude|onecrew)\b', re.I)),
    ('cờ lệnh', re.compile(r'(?<![\w-])--[A-Za-z][\w-]*')),
    ('mã lệnh', re.compile(r'`[^`]+`')),
    ('mã băm', re.compile(r'\b(?=[0-9A-Fa-f]*\d)(?=[0-9A-Fa-f]*[A-Fa-f])[0-9A-Fa-f]{7,64}\b')),
    ('mã lỗi', re.compile(r'\b(?:Errno|errno|WinError)\b(?:\s*\d+)?|\bTraceback\b|\bexit (?:code|status)\s*-?\d+|\b0x[0-9A-Fa-f]{2,}\b'
                          r'|\bE(?:ACCES|NOENT|PERM|EXIST|INVAL|BUSY|ISDIR|NOTDIR|NOSPC|AGAIN|TIMEDOUT|CONNREFUSED|CONNRESET|PIPE|MFILE|NOTEMPTY|ROFS|XDEV)\b'
                          r'|\bSIG(?:KILL|TERM|INT|SEGV|ABRT|HUP)\b')),
    ('mã nội bộ', re.compile(r'(?i:\b(?:mốc|milestone)\s+)M\d+\b|\brev(?:ision)?\s*\d+\b|\bv\d+\.\d+(?:\.\d+)*\b|\bdev\d+\b|\bSol\d+(?:\.\d+)?\b'
                             r'|\b(?:OBS|MR|RD|CP)-[A-Z0-9]+\b')),
)
# MAYBE (owner_view_maybe_technical, a warning): a slash between words that are not numbers, units, letters with a number, everyday words or a
# date format; a web address without scheme; a CONSTANT_NAME; a ticket-like code (REQ-123); a build file name; a bare OneCrew-like code with
# one digit (U1, F7, R3) not after a word that names a place, group or substance.
_SLASHED = re.compile(r'(?<![\w/.~])[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)+(?![\w/])')
_UNITS = frozenset('mg kg g mcg ug ml l dl cl km m cm mm h s min mmol mol iu ui mmhg bpm kcal cal mg% mmhg l/ph'.split())
_EVERYDAY = frozenset('online offline input output email sms web mobile desktop tablet android ios windows mac linux video audio text yes no on '
                      'off in out am pm male female nam nu'.split())
_DATE = re.compile(r'(?:dd|mm|yy|yyyy|hh)(?:/(?:dd|mm|yy|yyyy|hh))+', re.I)
_PLACE = frozenset('phòng giường buồng tầng lầu khu dãy lớp nhóm tổ khoa vitamin khổ mẫu đơn số quý hạng loại cỡ size bàn ghế ô hộp kệ tủ '
                   'xe tuyến đường lô block căn nhà máu type typ tuýp'.split())
_BUILD = re.compile(r'\b(?:Dockerfile|Makefile|Jenkinsfile|Procfile|Gemfile|Rakefile|Vagrantfile|CMakeLists|README|LICENSE|CHANGELOG)\b')
MAYBE = (
    ('địa chỉ web', re.compile(r'\bwww\.[\w.-]+\w|\b[a-z0-9-]+(?:\.[a-z0-9-]+)*\.(?:com|net|org|io|vn|dev|app|ai|info)\b')),
    ('tên hằng', re.compile(r'\b[A-Z][A-Z0-9]*_[A-Z0-9_]+\b')),
    ('mã phiếu', re.compile(r'\b[A-Z]{2,}-\d{3,}\b')),
    ('tên file', _BUILD),
    ('mã nội bộ', re.compile(r'\b(?:M|R|U|F|P|T|W|G|D|I|O|S|L)\d[a-z]?\b')),
)


def _plain_segment(part):
    p = part.strip('.,;:').lower()
    return (not p or p.isdigit() or re.fullmatch(r'\d+(?:[.,]\d+)?', p) is not None or re.fullmatch(r'[a-z]\d{0,2}', p) is not None
            or p in _UNITS or p in _EVERYDAY)


def _slash_may_be_path(token):
    token = token.strip('.,;:')
    if _DATE.fullmatch(token): return False
    return not all(_plain_segment(p) for p in token.split('/'))


def _previous_word(text, at):
    words = re.findall(r'[^\W\d_]+', text[:at])
    return words[-1].lower() if words else ''


def technical_word(text):
    """(kind, word) of the first CERTAIN technical token in an owner sentence, else None (a refusal: owner_view_technical)."""
    for kind, pattern in CERTAIN:
        found = pattern.search(text)
        if found: return kind, found.group(0).strip().rstrip('.,;:')
    return None


def maybe_technical_word(text):
    """(kind, word) of the first token that MAY be technical, else None (a warning only: owner_view_maybe_technical)."""
    for match in _SLASHED.finditer(text):
        if _slash_may_be_path(match.group(0)): return 'đường dẫn', match.group(0).strip('.,;:')
    for kind, pattern in MAYBE:
        for match in pattern.finditer(text):
            if kind == 'mã nội bộ' and _previous_word(text, match.start()) in _PLACE: continue
            return kind, match.group(0).strip('.,;:')
    return None


def _owner_texts(shown, key):
    value = shown.get(key)
    if isinstance(value, str): return [value] if value.strip() else []
    if isinstance(value, list): return [v for v in value if isinstance(v, str) and v.strip()]
    return []


def owner_view(ledger, contract):
    """[(code, text)] for the owner part: missing parts (only once the owner-rules file exists), and technical words (whenever present)."""
    shown = contract.get('presentation') or {}
    reasons = []
    missing = [label for key, label in OWNER_PARTS if not _owner_texts(shown, key)]
    if missing and step0.rules_path(ledger).exists():
        reasons.append(('owner_view_missing', 'Hợp đồng thiếu phần viết cho người theo dõi: ' + ', '.join(f'"{m}"' for m in missing)
                        + '. Mỗi phần là một hai câu lời thường, tiếng Việt, không tên file hay mã lệnh (presentation.request, user_sees, '
                          'acceptance_steps, not_doing). Trang theo dõi dùng đúng các câu này làm tiêu đề và mô tả của thẻ.'))
    for key, label in OWNER_PARTS:
        for text in _owner_texts(shown, key):
            hit = technical_word(text)
            if hit:
                reasons.append(('owner_view_technical', f'Phần "{label}" có {hit[0]} «{hit[1][:60]}»: người theo dõi không đọc được chữ này. '
                                                        'Viết lại bằng lời thường (nói việc và kết quả, không nêu tên file, đường dẫn, cờ lệnh, mã lỗi hay mã nội bộ).'))
                break
    return reasons


def owner_view_warnings(contract):
    """dev14: [(code, text)] warnings (never refusals) for words of the owner part that MAY be technical; plan lint prints them and exits 0,
    propose and approve go on and return them as `warnings`. A sentence already refused for a certain technical word is not warned twice."""
    shown = contract.get('presentation') or {}
    out = []
    for key, label in OWNER_PARTS:
        for text in _owner_texts(shown, key):
            hit = None if technical_word(text) else maybe_technical_word(text)
            if hit:
                out.append(('owner_view_maybe_technical', f'Phần "{label}" có chữ có thể là {hit[0]} «{hit[1][:60]}». Chỉ là cảnh báo, không chặn: '
                                                          'nếu người theo dõi không hiểu chữ này thì viết lại bằng lời thường.'))
                break
    return out


QUOTED =(re.compile(r"'([^'\n]{4,}?)'"), re.compile(r'"([^"\n]{4,}?)"'), re.compile(r'`([^`\n]{4,}?)`'))
WORD = re.compile(r'[^\W\d_]{6,}')
SHARED = 6                      # letters two words must share at the start to count as the same word (message / messages, translated / translating)


def _criteria(raw):
    """(milestone id, criterion id, question) of every reviewer criterion of the raw JSON, as far as it is shaped like a contract."""
    found = []
    for m in raw.get('milestones') if isinstance(raw, dict) and isinstance(raw.get('milestones'), list) else ():
        verifier = m.get('verifier') if isinstance(m, dict) else None
        config = verifier.get('config') if isinstance(verifier, dict) and verifier.get('type') == 'reviewer' else None
        for c in config.get('criteria') if isinstance(config, dict) and isinstance(config.get('criteria'), list) else ():
            if isinstance(c, dict) and isinstance(c.get('question'), str): found.append((m.get('id'), c.get('id'), c['question']))
    return found


def _in_base_tree(project, literal):
    """Does `git grep -F` find `literal` in HEAD of the project? False when it cannot be asked (no repository, no commit)."""
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith('GIT_')}
    try:
        done = subprocess.run(['git', '-C', str(project), 'grep', '-F', '-q', '-e', literal, 'HEAD'], capture_output=True, env=env, timeout=60,
                              creationflags=0x08000000 if os.name == 'nt' else 0)
    except (OSError, subprocess.SubprocessError):
        return False
    return done.returncode == 0


def no_fail_clause(raw):
    """dev12 (review K1): one rule for lint, the propose command and approve (step0.evaluate); `raw` may be the validated contract."""
    return [('criterion_no_fail_clause', f'milestone {m} criterion {c}: the question has no "fail if ..." clause, so nobody can tell what would make it fail; '
                                         'say what a fail looks like (the reviewer answers pass or fail, never "pass with remarks").')
            for m, c, question in _criteria(raw) if 'fail if' not in question.lower()]


def _warnings(ledger, raw, contract):
    """Two checks that can be wrong in both directions, so they only warn: a quoted literal the base tree already contains (the reviewer would
    fail a criterion the work cannot change), and a word a criterion shares with a non_goal (the criterion may ask for what the contract excludes)."""
    out = []
    for m, c, question in _criteria(raw):
        seen = set()
        for pattern in QUOTED:
            for literal in pattern.findall(question):
                if literal in seen: continue
                seen.add(literal)
                if _in_base_tree(ledger.project, literal):
                    out.append(('criterion_literal_present', f'milestone {m} criterion {c}: "{literal[:60]}" already appears in the base tree (HEAD); '
                                                              'a criterion that fails on it fails before any work. Ask about what the diff adds or removes.'))
        stems = {w.lower()[:SHARED] for w in WORD.findall(question)}
        for goal in contract['non_goals']:
            shared = sorted(stems & {w.lower()[:SHARED] for w in WORD.findall(goal)})
            if shared:
                out.append(('criterion_vs_non_goal', f'milestone {m} criterion {c} shares "{shared[0]}..." with the non_goal "{goal[:80]}"; '
                                                      'check the criterion does not ask for what the contract excludes.'))
    return out


def check(ledger, raw, author=None, ack_criteria=False):
    """(reasons, warnings): reasons make `plan lint` exit 1, warnings are printed and change nothing. `ack_criteria` silences the two criteria
    warnings (the author has read them); the missing "fail if" is a reason either way."""
    reasons = lint(ledger, raw, author)
    try:
        contract = contracts.validate(raw)
    except LedgerError:
        return reasons, []
    return reasons, ([] if ack_criteria else _warnings(ledger, raw, contract)) + owner_view_warnings(contract)


def notes(raw):
    """Facts about the host, not about the contract (beta report B4, 29/10): `plan lint` prints them on stderr, so they never change the exit code
    or the `lint: clean` line. Today one: an AI session that works under the hooks has no call counter, so budget.max_calls limits nothing there."""
    budget = raw.get('budget') if isinstance(raw, dict) else None
    calls = budget.get('max_calls') if isinstance(budget, dict) else None
    if type(calls) is not int: return []
    return [('budget_calls_untracked', f'budget.max_calls ({calls}) is not counted for an AI session that works under the hooks: nothing deducts its '
                                       'tool calls and plan report shows the calls as not counted; only runs that OneCrew executes itself are metered. '
                                       'Read it as a note for the reviewer, not as a limit.')]


def render(reasons, warnings=()):
    lines = [f'[{code}] {text}' for code, text in list(reasons) + list(warnings)]
    return '\n'.join(lines) if lines else 'lint: clean'
