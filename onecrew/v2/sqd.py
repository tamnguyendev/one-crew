"""SQD: the owner's decision book, one per repository (`onecrew decision add|list|show`; docs/quyet-dinh-chu.vi.md).

The book is `<state-root>/plans/quyet-dinh/<repository>.jsonl`: one JSON object per line, only ever appended (D2, D3). Every worktree of a repository
reads and writes the same book (the name comes from the git directory they share). A decision is replaced by a NEW line that names it (`--replaces`);
the old line stays byte for byte. A line that cannot be parsed is skipped. Nothing here blocks anything: the hooks read the book through `current`,
which answers [] on any error (D4). Nothing is written inside the repository.
"""
import argparse
import datetime as dt
import hashlib
import json
import os
import re
import sys
from pathlib import Path

from . import where

FOLDER = 'quyet-dinh'
ID = re.compile(r'SQD-([1-9]\d*)')
WRITTEN_ID = re.compile(rb'"id": *"SQD-(\d+)"')      # also found in a torn line, so its number is never given twice
MAX_QUOTE, MAX_TITLE, MAX_SCOPE, MAX_SOURCE = 500, 120, 200, 200
SESSION_LINES = 10                                   # I4: at most this many decisions in the session start (the newest)


# ---- where the book is ------------------------------------------------------------------------------------------------------

def repository(project):
    """(top of the working tree, the git directory all worktrees of the repository share). Outside git: the folder itself, twice."""
    top = where.git_root(project) or Path(project).resolve()
    dot = top / '.git'
    if dot.is_file():                                # a worktree or a submodule: "gitdir: <path>", whose `commondir` names the shared one
        text = dot.read_text(encoding='utf-8', errors='replace').strip()
        if text.startswith('gitdir:'):
            shared = Path(os.path.join(top, text[len('gitdir:'):].strip()))
            link = shared / 'commondir'
            if link.is_file(): shared = Path(os.path.join(shared, link.read_text(encoding='utf-8', errors='replace').strip()))
            return top, Path(os.path.realpath(shared))
    return top, Path(os.path.realpath(dot if dot.is_dir() else top))


def book_path(state_root, project):
    shared = repository(project)[1]
    name = shared.parent.name if shared.name.casefold() == '.git' else shared.name
    slug = re.sub(r'[^A-Za-z0-9._-]+', '-', name).strip('-.')[:40] or 'repo'
    mark = hashlib.sha256(os.path.normcase(str(shared)).encode('utf-8', 'surrogatepass')).hexdigest()[:12]
    return Path(state_root) / 'plans' / FOLDER / f'{slug}-{mark}.jsonl'


# ---- reading ----------------------------------------------------------------------------------------------------------------

def _valid(value):
    return (isinstance(value, dict) and isinstance(value.get('id'), str) and ID.fullmatch(value['id']) is not None
            and all(isinstance(value.get(k), str) for k in ('scope', 'title', 'quote', 'at'))
            and (value.get('replaces') is None or isinstance(value['replaces'], str)))


def read(path):
    """(records in file order, number of broken lines skipped, the raw bytes). A missing book is empty; an unreadable one raises OSError."""
    try:
        data = Path(path).read_bytes()
    except FileNotFoundError:
        return [], 0, b''
    records, broken, seen = [], 0, set()
    for raw in data.split(b'\n'):
        if not raw.strip(): continue
        try:
            value = json.loads(raw.decode('utf-8-sig'))
        except (ValueError, RecursionError):
            value = None
        if not _valid(value) or value['id'] in seen:
            broken += 1
            continue
        seen.add(value['id'])
        records.append(value)
    return records, broken, data


def number(record):
    return int(ID.fullmatch(record['id']).group(1))


def replaced_by(records):
    """{id of a replaced decision: id of the decision that replaced it}."""
    return {r['replaces']: r['id'] for r in records if r.get('replaces') and r['replaces'] != r['id']}


def in_force(records):
    gone = replaced_by(records)
    return sorted((r for r in records if r['id'] not in gone), key=number)


def current(state_root, project):
    """The decisions in force, for a hook: [] when there is no book, no state root, or anything at all goes wrong (I6)."""
    try:
        if not state_root or project is None: return []
        return in_force(read(book_path(state_root, project))[0])
    except Exception:                                # noqa: BLE001 - a reminder never locks the session
        return []


def one_line(text):
    """A field as it is printed in a list: on one line, also when the file was edited by hand."""
    return ' '.join(str(text).split())


def session_lines(state_root, project):
    """I4: what SessionStart adds. [] when the repository has no decision in force; the owner's words are never in it."""
    records = current(state_root, project)
    if not records: return []
    shown = records[-SESSION_LINES:]
    count = f'{len(records)}' + (f', hiện {len(shown)} mới nhất' if len(records) > len(shown) else '')
    head = (f'Quyết định của chủ còn hiệu lực cho repo này ({count}). Lời nguyên văn: onecrew --project "{project}" --state-root "{state_root}" '
            'decision show SQD-n. Lời giao việc nêu SQD-n nào áp, hoặc "không có quyết định liên quan".')
    return [head, *(f"{r['id']}  {one_line(r['title'])}  [phạm vi: {one_line(r['scope'])}]" for r in shown)]


# ---- writing ----------------------------------------------------------------------------------------------------------------

def _single(value, label, limit):
    value = value.strip()
    if not value: raise ValueError(f'{label} rỗng; không ghi gì.')
    if len(value.splitlines()) > 1: raise ValueError(f'{label} phải nằm trên một dòng; không ghi gì.')
    if len(value) > limit: raise ValueError(f'{label} dài {len(value)} ký tự, tối đa {limit}; không ghi gì.')
    return value


def scope_pattern(value):
    """`*` (the whole repository) or a path pattern relative to the repository: exact file, folder, or glob."""
    value = _single(value, '--scope', MAX_SCOPE).replace('\\', '/')
    while value.startswith('./'): value = value[2:]
    if not value or value.startswith('/') or re.match(r'[A-Za-z]:', value) or '..' in value.split('/'):
        raise ValueError('--scope là mẫu đường dẫn tính từ gốc repo (tệp, thư mục, glob) hoặc "*"; không ghi gì.')
    return value


def add(state_root, project, scope, title, quote, source=None, replaces=None):
    """Append one decision and return (record, path of the book). A refusal raises ValueError or OSError and writes nothing."""
    from .hook_cli import appending
    from .ownership import session_info
    scope, title = scope_pattern(scope), _single(title, '--title', MAX_TITLE)
    if not quote.strip(): raise ValueError('--quote (lời chủ nguyên văn) rỗng; không ghi gì.')
    if len(quote) > MAX_QUOTE: raise ValueError(f'--quote dài {len(quote)} ký tự, tối đa {MAX_QUOTE}; không ghi gì.')
    source = _single(source, '--source', MAX_SOURCE) if source is not None else None
    replaces = replaces.strip().upper() if replaces is not None else None
    path = book_path(state_root, project)

    def replaceable(records):
        if replaces is None: return
        if replaces not in {r['id'] for r in records}: raise ValueError(f'--replaces {replaces}: sổ của repo này không có mã đó; không ghi gì.')
        later = replaced_by(records).get(replaces)
        if later: raise ValueError(f'--replaces {replaces}: mã đó đã bị thay bởi {later}; thay {later}. Không ghi gì.')

    replaceable(read(path)[0])                       # refused before the folder or the lock file is made
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with appending(path.with_suffix('.lock'), required=True):
            records, _, data = read(path)            # again under the lock: another session may have written
            replaceable(records)
            top = max([number(r) for r in records] + [int(n) for n in WRITTEN_ID.findall(data)], default=0)
            record = {'id': f'SQD-{top + 1}', 'scope': scope, 'title': title, 'quote': quote,
                      'at': dt.datetime.now().astimezone().isoformat(timespec='seconds'), 'source': source, 'replaces': replaces,
                      'recorded_by': session_info()}  # who wrote it (an AI session or not, the declared actor): not a session id
            line = (json.dumps(record, ensure_ascii=False) + '\n').encode('utf-8')
            if data and not data.endswith(b'\n'): line = b'\n' + line          # a torn last line stays a line of its own
            with path.open('ab') as stream: stream.write(line)
    except TimeoutError as error:
        raise OSError(f'Sổ đang được một tiến trình khác ghi: {path}. Chạy lại; không ghi gì.') from error
    return record, path


# ---- the command ------------------------------------------------------------------------------------------------------------

def relative_to_repository(project, raw):
    """The repository-relative posix form of --path (relative paths are taken from the top of the working tree)."""
    value = Path(raw)
    if value.is_absolute():
        top = repository(project)[0]
        try:
            value = value.resolve().relative_to(top)
        except ValueError:
            raise ValueError(f'--path {raw} nằm ngoài repo {top}.') from None
    return os.path.normpath(str(value)).replace('\\', '/')


def applies(record, rel):
    from .hook_cli import under
    return record['scope'] == '*' or under(rel, record['scope'])


def list_line(record, gone):
    line = f"{record['id']}  {one_line(record['title'])}  | phạm vi: {one_line(record['scope'])} | {record['at'][:10]}"
    if record.get('replaces'): line += f" | thay {record['replaces']}"
    if record['id'] in gone: line += f" | đã bị thay bởi {gone[record['id']]}"
    return line


def show_text(record, gone):
    by = record.get('recorded_by') if isinstance(record.get('recorded_by'), dict) else {}
    kind = {True: 'phiên AI', False: 'không phải phiên AI'}.get(by.get('ai_session'), 'không rõ có phải phiên AI')
    if by.get('actor_env'): kind += f", actor {by['actor_env']}"
    state = f"đã bị thay bởi {gone[record['id']]}" if record['id'] in gone else 'còn hiệu lực'
    lines = [f"{record['id']}: {one_line(record['title'])}", f"Phạm vi: {one_line(record['scope'])}", f"Ngày ghi: {record['at']}",
             f"Nguồn: {record.get('source') or 'không ghi'}", f"Thay: {record.get('replaces') or 'không'}", f'Trạng thái: {state}', f'Người ghi: {kind}',
             'Lời chủ (nguyên văn):', record['quote']]
    return '\n'.join(lines)


def parser():
    root = argparse.ArgumentParser(prog='onecrew')
    root.add_argument('--project', type=Path); root.add_argument('--state-root', type=Path)
    verbs = root.add_subparsers(dest='group', required=True).add_parser('decision', help="The owner's decision book of this repository.").add_subparsers(dest='verb', required=True)
    p = verbs.add_parser('add', help='Append one decision of the owner (never edits or deletes a line).')
    p.add_argument('--scope', required=True, help='"*" (whole repository) or a path pattern: file, folder or glob')
    p.add_argument('--title', required=True, help='short, one line')
    p.add_argument('--quote', required=True, help=f"the owner's words, verbatim, at most {MAX_QUOTE} characters")
    p.add_argument('--source', help='where the words were said')
    p.add_argument('--replaces', metavar='SQD-n', help='the decision in force this one replaces')
    p = verbs.add_parser('list', help='Decisions in force, one line each.')
    p.add_argument('--path', help='only the decisions whose scope covers this file')
    p.add_argument('--all', action='store_true', help='also the replaced ones')
    verbs.add_parser('show', help="One decision with the owner's words.").add_argument('id', metavar='SQD-n')
    return root


def run(args):
    project = Path(args.project or Path.cwd()).resolve()
    if not project.is_dir(): raise ValueError(f'Thư mục dự án không có: {project}')
    state_root = Path(where.state_root_for(project, args.state_root) or where.default_state_root()).resolve()
    top, shared = repository(project)
    inside = [top, *([shared.parent] if shared.name.casefold() == '.git' else [])]
    if any(state_root == place or place in state_root.parents for place in inside):
        raise ValueError('State root phải nằm ngoài repo của dự án.')
    if args.verb == 'add':
        record, path = add(state_root, project, args.scope, args.title, args.quote, args.source, args.replaces)
        extra = f", thay {record['replaces']}" if record['replaces'] else ''
        return [f"Đã ghi {record['id']}{extra}: {record['title']}", f'Sổ: {path}', f"Đối chiếu lời nguyên văn: decision show {record['id']}"], 0
    path = book_path(state_root, project)
    records, broken, _ = read(path)
    gone = replaced_by(records)
    if args.verb == 'show':
        wanted = args.id.strip().upper()
        found = next((r for r in records if r['id'] == wanted), None)
        if found is None: raise ValueError(f'Sổ của repo này không có {wanted}: {path}')
        return [show_text(found, gone)], broken
    chosen = sorted(records, key=number) if args.all else in_force(records)
    if args.path:
        rel = relative_to_repository(project, args.path)
        chosen = [r for r in chosen if applies(r, rel)]
    if chosen: return [list_line(r, gone) for r in chosen], broken
    return [f'Không có quyết định {"nào" if args.all else "còn hiệu lực"}{" cho " + args.path if args.path else ""}. Sổ: {path}'], broken


def main(argv=None):
    from .hook_cli import utf8_streams
    utf8_streams()
    args = parser().parse_args(argv)
    try:
        lines, broken = run(args)
    except (ValueError, OSError) as error:
        print(json.dumps({'error': str(error), 'type': type(error).__name__}, ensure_ascii=False))
        return 2
    print('\n'.join(lines))
    if broken: print(f'Cảnh báo: bỏ qua {broken} dòng hỏng trong sổ.', file=sys.stderr)
    return 0
