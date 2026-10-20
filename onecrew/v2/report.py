"""`onecrew plan report <name>` and `onecrew plan digest`: one page of plain text, written from what the ledger already holds
(v2 item 4). Both are read-only on purpose:

* the ledger is opened with sqlite `mode=ro` (a `_Reader` that refuses `transaction(write=True)`), so no event, request or file
  of the state root can be written; the only write is the optional `--out` file, which is refused inside the state root;
* no model, no network: the outside looks are `git log` on the repository the receipts name and reading receipt blobs, which change nothing;
* the plan is found by name in the whole state root, and the directory of the receipts (not `--project`) says where the hook
  log and the repository are, so a plan of another project reads the same from any folder;
* a source that is missing prints "không có dữ liệu" / "không có nhật ký hook", never a guess.

Labels are Vietnamese. The page opens with a four-line conclusion (Kết luận, Vì sao, Còn gì, Bạn cần làm) derived only from ledger
data, then seven numbered sections. Text that came from the ledger or the contract (titles, outputs, questions, reasons) is quoted
as it is: nothing is cut; long lines wrap at WIDTH and only whitespace is folded. Times are the machine's local time.
"""
import datetime as dt
import json
import os
import sqlite3
import subprocess
import textwrap
from contextlib import contextmanager
from pathlib import Path

from ..ledger import APP_ID, VERSION, Ledger, LedgerError
from ..snapshots import Snapshots
from . import contract as contracts, plan as plans, step0

NO_DATA = 'không có dữ liệu'
NO_HOOK_LOG = 'không có nhật ký hook'
TITLES = ('Output đạt tới đâu', 'Mốc và verdict', 'Phút so ngân sách', 'Lần chặn', 'Câu hỏi', 'Chạy ngoài kiểm soát', 'Bãi đỗ')
OPEN_CAP = 10                                  # lines for open plans in the digest
WIDTH = 110
SCOPE_WORDS = ('scope', 'owned', 'outside', 'refused')
NOTHING = 'không gì'
GIT_TIMEOUT = 30


class _Reader(Ledger):
    """The ledger of one plan's project, read-only. It never calls Ledger.__init__ (that needs the project folder to exist)."""

    def __init__(self, state_root, project_id=None, project_path=''):
        self.state_root = Path(state_root).resolve()
        self.path = self.state_root / 'ledger.sqlite3'
        self.project_id, self.project_path = project_id, project_path
        self.project = Path(project_path) if project_path else None

    @contextmanager
    def transaction(self, write=False):
        """The one door to the ledger in this module: sqlite is opened `mode=ro` (and `query_only`), here, so a write is an sqlite error."""
        if write: raise LedgerError('plan report/digest are read-only: they never write the ledger.')
        if not self.path.exists():
            yield None
            return
        conn = sqlite3.connect(self.path.as_uri() + '?mode=ro', uri=True, timeout=10, isolation_level=None)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute('PRAGMA query_only=ON')
            conn.execute('BEGIN')
            if conn.execute('PRAGMA application_id').fetchone()[0] != APP_ID or conn.execute('PRAGMA user_version').fetchone()[0] not in (VERSION, 2, 3):
                raise LedgerError('Unrecognized or unsupported ledger schema; nothing was read.')
            yield conn
            conn.commit()
        finally:
            conn.close()


def _wrap(text, indent='  ', hang=None):
    """The whole text on lines of at most WIDTH (a longer word stays whole); whitespace is folded, nothing is dropped."""
    hang = indent + '    ' if hang is None else hang
    return textwrap.wrap(' '.join(str(text).split()), WIDTH, initial_indent=indent, subsequent_indent=hang,
                         break_long_words=False, break_on_hyphens=False) or [indent.rstrip()]


def _short(sha):
    return sha[:7] if isinstance(sha, str) and sha else '—'


def _when(text):
    return dt.datetime.fromisoformat(text)


def _stamp(text):
    """Local machine time, e.g. 2026-10-18 22:54."""
    return _when(text).astimezone().strftime('%Y-%m-%d %H:%M')


def _anchors(state_root):
    """[(task row, last event time)] of every plan in the state root, oldest first."""
    reader = _Reader(state_root)
    with reader.transaction() as conn:
        if conn is None: raise LedgerError(f'Không có sổ ở {reader.path}.')
        rows = conn.execute("SELECT id, project_id, project_path, request_key, created_at FROM tasks WHERE request_key LIKE 'plan:%' "
                            'ORDER BY created_at, id').fetchall()
        last = {r[0]: r[1] for r in conn.execute('SELECT task_id, MAX(created_at) FROM events GROUP BY task_id')}
    return [(dict(row), last.get(row['id'], row['created_at'])) for row in rows]


def _gather(state_root, row, revision=None):
    """Everything both commands read about one plan, in one pass over the ledger."""
    reader = _Reader(state_root, row['project_id'], row['project_path'])
    name = row['request_key'][len(plans.ANCHOR):]
    with reader.transaction() as conn:
        state = plans.derive(reader, conn, name)
        events = [(e['kind'], e['created_at'], json.loads(e['payload']))
                  for e in conn.execute('SELECT kind, created_at, payload FROM events WHERE task_id=? ORDER BY seq', (row['id'],))]
        closed = set(step0.closed_events(conn, row['id']))
    if revision is not None and revision not in state['revisions']:
        raise LedgerError(f'Plan {name} has no revision {revision}.')
    revision = revision or state['latest']
    try:
        contract, error = plans.load(reader, state, revision)[0], None
    except LedgerError as problem:
        contract, error = None, str(problem)
    views = plans.milestone_views(contract, state, revision) if contract else []
    return {'name': name, 'row': row, 'state': state, 'events': events, 'closed': closed, 'revision': revision, 'contract': contract,
            'error': error, 'views': views, 'requests': reader.requests(row['id']), 'state_root': Path(state_root).resolve()}


def _lookup(state_root, name, revision=None):
    found = [row for row, _ in _anchors(state_root) if row['request_key'] == plans.ANCHOR + name]
    if not found: raise LedgerError(f'No plan named {name} in {Path(state_root).resolve()}.')
    return _gather(state_root, found[-1], revision)


# ---- what is reached, what is parked ----------------------------------------------------------------------------------

def _output_rows(f):
    """[(output id, text, covering milestone ids, reached)] or None when the contract cannot be read."""
    c = f['contract']
    if c is None: return None
    by_id = {v['id']: v for v in f['views']}
    rows = []
    for oid, text in zip(contracts.output_ids(c['output']), c['output']):
        covering = [m['id'] for m in c['milestones'] if oid in m['covers']]
        rows.append((oid, text, covering, bool(covering) and all(by_id[m]['state'] == 'passed' for m in covering)))
    return rows


def _parked_data(f):
    """(should items with no passed covering milestone, unknowns still open); None when the contract cannot be read."""
    c = f['contract']
    if c is None: return None
    passed = {v['id'] for v in f['views'] if v['state'] == 'passed'}
    waiting = [i for i in c['items'] if i['tier'] == 'should' and i['milestone'] not in passed]
    unknown = [u for u in c['understanding']['unknowns'] if u['status'] == 'open' or u['id'] not in f['closed']]
    return waiting, unknown


def _standing(f):
    """(kind, who): kind is open|accepted|stopped|failed; who is whose move it is (open plans only).
    A heuristic from the ledger, not a promise: the ledger does not say whether the AI is still working."""
    status, views, state = f['state']['status'], f['views'], f['state']
    if status == 'accepted': return 'accepted', '—'
    if status == 'stopped_with_report': return 'stopped', '—'
    if f['contract'] is None: return 'open', NO_DATA
    if status == 'proposed': return 'open', 'chủ sở hữu'
    pending = next((v for v in views if v['state'] != 'passed'), None)
    if pending and pending['state'] == 'failed' and pending['repairs_left'] == 0: return 'failed', '—'
    if any(r['state'] == 'pending' for r in f['requests']): return 'open', 'chủ sở hữu'
    if pending is None: return 'open', 'chủ sở hữu'                              # every milestone passed: acceptance is the owner's
    if pending['state'] == 'failed': return 'open', 'AI'                          # a repair round remains
    if pending['verifier'] == 'owner-manual': return 'open', 'chủ sở hữu'
    return 'open', 'kiểm' if any(v['revision'] == f['revision'] for v in state['verdicts']) else 'AI'


def _needs(f):
    """What the owner has to do now: nghiệm thu | duyệt bản N | trả lời câu hỏi | không gì (and, for a stopped plan with no open question,
    the decision that stays with the owner)."""
    status, state = f['state']['status'], f['state']
    if status == 'accepted': return NOTHING
    if any(r['state'] == 'pending' for r in f['requests']): return 'trả lời câu hỏi'
    if status == 'proposed': return f'duyệt bản {state["latest"]}'
    if status == 'stopped_with_report': return 'quyết định việc đã dừng'
    if f['contract'] is None: return NO_DATA
    first = next((v for v in f['views'] if v['state'] != 'passed'), None)
    if first is None or (first['state'] == 'pending' and first['verifier'] == 'owner-manual'): return 'nghiệm thu'
    return NOTHING                                                                # the AI repairs, or a check is still to run


# ---- why a milestone is not passed ------------------------------------------------------------------------------------

def _blob_text(state_root, key):
    try:
        return Snapshots(state_root).read_blob(key).decode('utf-8', errors='replace')
    except (OSError, LedgerError):
        return None


def _tail(state_root, key):
    """The last non-empty line of a stdout/stderr blob, as it is."""
    lines = [l.strip() for l in (_blob_text(state_root, key) or '').splitlines() if l.strip()] if key else []
    return lines[-1] if lines else None


def _receipt_reason(f, view):
    """The exit/reason line of the receipt of the milestone's last verdict (None when the blob cannot be read)."""
    last = view['last_verdict']
    text = _blob_text(f['state_root'], last['receipt']) if last and last.get('receipt') else None
    try:
        body = json.loads(text) if text else None
    except ValueError:
        body = None
    if not isinstance(body, dict): return None
    if body.get('kind') == 'command-receipt':
        head = 'lệnh hết giờ' if body.get('timed_out') else f'lệnh lỗi: {body["error"]}' if body.get('error') else f'lệnh thoát mã {body.get("exit_code")}'
        tail = _tail(f['state_root'], body.get('stderr')) or _tail(f['state_root'], body.get('stdout'))
        return head + (f'; dòng cuối: {tail}' if tail else '')
    if body.get('kind') == 'reviewer-receipt':
        problems = [p if isinstance(p, str) else json.dumps(p, ensure_ascii=False) for p in (body.get('problems') or [])]
        head = f'reviewer {body.get("result")}' + (f' ({body["error"]})' if body.get('error') else '')
        return head + ('; ' + '; '.join(problems) if problems else '')
    return None


def _failing(f):
    """(milestone view, stop reason) of the milestone that failed or stopped the plan, or (None, None)."""
    stopped = f['state']['stopped'].get(f['revision'])
    if stopped:
        view = next((v for v in f['views'] if v['id'] == stopped['milestone']), None)
        if view: return view, stopped.get('reason')
    return next((v for v in f['views'] if v['state'] == 'failed'), None), None


def _conclusion(f):
    """Four lines for the owner, from ledger data only. Wrapped, never cut."""
    kind, _ = _standing(f)
    word = {'accepted': 'XONG', 'stopped': 'DỪNG', 'failed': 'HỎNG'}.get(kind, 'ĐANG CHỜ')
    state, rows = f['state'], _output_rows(f)
    view, reason = _failing(f)
    if kind in ('stopped', 'failed') or (kind == 'open' and view):
        if view is None: why = f'{NO_DATA} (hợp đồng không đọc được)'
        else:
            why = f'mốc {view["id"]}: ' + (_receipt_reason(f, view) or 'không đọc được biên nhận')
            if reason: why += f' ({reason})'
    elif kind == 'accepted' or (rows is not None and f['views'] and all(v['state'] == 'passed' for v in f['views'])): why = 'mọi mốc đạt'
    elif state['status'] == 'proposed': why = f'bản {state["latest"]} chưa được duyệt'
    elif f['contract'] is None: why = NO_DATA
    else: why = 'mốc ' + next(v['id'] for v in f['views'] if v['state'] != 'passed') + ' chưa có verdict'
    parked = _parked_data(f)
    if rows is None or parked is None: left = NO_DATA
    else:
        parts = []
        if [r[0] for r in rows if not r[3]]: parts.append('output chưa đạt: ' + ', '.join(r[0] for r in rows if not r[3]))
        if parked[0]: parts.append('should chưa có mốc đạt: ' + ', '.join(i['id'] for i in parked[0]))
        if parked[1]: parts.append('unknown còn mở: ' + ', '.join(u['id'] for u in parked[1]))
        left = '; '.join(parts) or 'không còn gì'
    lines = [f'Kết luận: {word}']
    for label, text in (('Vì sao', why), ('Còn gì', left), ('Bạn cần làm', _needs(f))): lines += _wrap(f'{label}: {text}', '', '    ')
    return lines


# ---- the seven sections -----------------------------------------------------------------------------------------------

def _outputs(f):
    rows = _output_rows(f)
    if rows is None: return _wrap(f'{NO_DATA} (hợp đồng bản {f["revision"]} không đọc được: {f["error"]})', '')
    by_id = {v['id']: v for v in f['views']}

    def shown(covering):
        return ' '.join(f'{m}={by_id[m]["last_verdict"]["result"] if by_id[m]["last_verdict"] else "chưa có verdict"}' for m in covering)
    shown_to_owner = f['contract'].get('presentation') or {}
    if any(shown_to_owner.get(k) for k in ('request', 'user_sees', 'acceptance_steps')):
        lines = _wrap(f'Yêu cầu: {shown_to_owner["request"]}') if shown_to_owner.get('request') else []
        for label, key in (('Bạn sẽ thấy', 'user_sees'), ('Cách nghiệm thu', 'acceptance_steps')):
            if shown_to_owner.get(key):
                lines.append(f'  {label}:')
                for number, item in enumerate(shown_to_owner[key], 1): lines += _wrap(f'{number}. {item}', '    ', '       ')
        return lines + _wrap('Tiến độ: ' + ' · '.join(f'{oid} {"ĐẠT" if done else "CHƯA"} [{shown(c)}]' for oid, _, c, done in rows))
    lines = []
    for oid, text, covering, done in rows: lines += _wrap(f'{oid} {"ĐẠT" if done else "CHƯA"} [{shown(covering)}] «{text}»', '  ', '      ')
    return lines


def _milestones(f):
    if f['contract'] is None: return [NO_DATA]
    lines = []
    for v in f['views']:
        last, mark = v['last_verdict'], ' · DỪNG' if v['state'] == 'stopped' else ''
        used = f'sửa {v["failures"]}/{v["max_repairs"]}'
        if last: lines += _wrap(f'{v["id"]} {last["result"]} · by {last["by"]} · {_short(last["artifact_sha"])} · {used}{mark} · «{v["title"]}»', '  ', '      ')
        else: lines += _wrap(f'{v["id"]} chưa có verdict · {used} · «{v["title"]}»', '  ', '      ')
    return lines


def _minutes(f):
    if not f['events']: return [f'  {NO_DATA}', '  Lệnh: chưa đếm được']
    first, last = f['events'][0][1], f['events'][-1][1]
    spent = (_when(last) - _when(first)).total_seconds() / 60
    budget = f['contract']['budget']['time'] if f['contract'] else None
    line = f'đã chạy {spent:.0f} phút (từ {_stamp(first)} đến {_stamp(last)}, giờ máy này)'
    if budget: line += f' / ngân sách {budget} phút' + (' — VƯỢT' if spent > budget else '')
    else: line += f' / ngân sách: {NO_DATA}'
    return _wrap(line) + ['  Lệnh: chưa đếm được']


def _cwds(f):
    """Directories the receipts name, the latest first (verdict.receipt_issued and verdict.recorded both carry the cwd)."""
    seen = []
    for kind, _, p in reversed(f['events']):
        directory = p.get('cwd') if kind in ('verdict.receipt_issued', 'verdict.recorded') else None
        if directory and os.path.normcase(directory) not in [os.path.normcase(s) for s in seen]: seen.append(directory)
    return seen


def _block_kind(reason):
    low = reason.lower()
    if reason.startswith('Milestone ') or 'stop block cap' in low: return 'wait'
    return 'scope' if any(word in low for word in SCOPE_WORDS) else 'other'


def _blocks(f):
    places = []
    for directory in _cwds(f) + ([f['row']['project_path']] if f['row']['project_path'] else []):
        path = Path(directory) / '.onecrew' / 'violations.jsonl'
        if os.path.normcase(str(path)) not in [os.path.normcase(str(p)) for p in places]: places.append(path)
    found = next((p for p in places if p.is_file()), None)
    if found is None: return _wrap(NO_HOOK_LOG + (f' (tìm ở {places[0]})' if places else ''))
    try:
        raw = found.read_text(encoding='utf-8', errors='replace').splitlines()
    except OSError as error:
        return _wrap(f'{NO_HOOK_LOG} (không đọc được {found}: {error})')
    mine = []
    for line in raw:
        try:
            item = json.loads(line)
        except ValueError:
            continue
        if isinstance(item, dict) and item.get('plan') == f['name'] and isinstance(item.get('reason'), str): mine.append(item['reason'])
    kinds = [_block_kind(r) for r in mine]
    lines = [f'  chờ kiểm: {kinds.count("wait")} · ngoài phạm vi: {kinds.count("scope")} · khác: {kinds.count("other")}']
    for reason in [r for r, k in zip(mine, kinds) if k == 'scope'][-3:]: lines += _wrap(f'ngoài phạm vi: «{reason}»', '  ', '      ')
    return lines


def _git_log(directory, since, until):
    env = dict(os.environ, GIT_OPTIONAL_LOCKS='0')
    done = subprocess.run(['git', '-C', directory, 'log', 'HEAD', f'--since={since}', f'--until={until}', '--format=%H%x09%T%x09%h%x09%s'],
                          capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=GIT_TIMEOUT, env=env)
    if done.returncode: raise OSError(done.stderr.strip() or f'git exit {done.returncode}')
    return [line.split('\t', 3) for line in done.stdout.splitlines() if line.count('\t') >= 3]


def _outside(f):
    cwds = _cwds(f)
    if not cwds: return [f'  {NO_DATA} (sổ không ghi thư mục của biên nhận)']
    start = next((at for kind, at, _ in f['events'] if kind == 'plan.approved'), f['events'][0][1])
    utc = lambda text: _when(text).astimezone(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%S+00:00')       # what git is asked, not what is shown
    known = {v['artifact_sha'] for v in f['state']['verdicts']}
    commits, problems = {}, []
    for directory in cwds:
        try:
            for sha, tree, short, subject in _git_log(directory, utc(start), utc(f['events'][-1][1])): commits[sha] = (tree, short, subject)
        except (OSError, subprocess.SubprocessError) as error:
            problems.append(f'{directory}: {error}')
    if problems and not commits: return _wrap(f'{NO_DATA} (không đọc được git: {problems[0]})')
    suspects = [(short, subject) for tree, short, subject in commits.values() if tree not in known]
    lines = _wrap(f'{len(commits)} commit trong khoảng {_stamp(start)} → {_stamp(f["events"][-1][1])}; {len(commits) - len(suspects)} khớp một biên nhận')
    for short, subject in suspects: lines += _wrap(f'nghi ngờ {short} «{subject}»', '  ', '      ')
    if not suspects and commits: lines.append('  không có commit nghi ngờ')
    return lines


def _questions(f):
    lines = []
    if f['contract']:
        used = len([r for r in f['requests'] if r['question'].get('action', {}).get('type') == 'v2.plan_stopped'])
        lines.append(f'  hạn mức hỏi chủ sở hữu: đã dùng {used}/{f["contract"]["attention"]["questions"]}')
    for r in f['requests']:
        lines += _wrap(f'[{"mở" if r["state"] == "pending" else "đã trả lời"}] {r["id"]}: «{r["question"].get("question", "")}»', '  ', '      ')
        if r['answer'] is not None: lines += _wrap('trả lời: ' + json.dumps(r['answer'], ensure_ascii=False), '    ', '        ')
    if not f['requests']: lines.append('  không có câu hỏi nào')
    return lines


def _parked(f):
    data = _parked_data(f)
    if data is None: return [NO_DATA]
    waiting, unknown = data
    lines = _wrap('should chưa có mốc đạt: ' + ('; '.join(f'{i["id"]} «{i["title"]}»' for i in waiting) or 'không có'))
    lines.append(f'  vượt hạn mức chú ý: {f["state"]["exceeded"]} lần')
    return lines + _wrap('unknown còn mở: ' + ('; '.join(f'{u["id"]} «{u["question"]}»' for u in unknown) or 'không có'))


NOTES_HEADING = 'Reviewer ghi chú ngoài tiêu chí'
NOTE_CAP = 300


def _reviewer_notes(f):
    """The section after the seven: for every reviewer milestone that passed, what the reviewer noticed outside its criteria (its receipt's
    outside_criteria), one bullet per remark, cut at NOTE_CAP characters. [] when no passed reviewer milestone has any: the page is then as before."""
    lines = []
    for view in f['views']:
        last = view['last_verdict']
        if view['state'] != 'passed' or view['verifier'] != 'reviewer' or not last or not last.get('receipt'): continue
        try:
            body = json.loads(_blob_text(f['state_root'], last['receipt']) or '')
        except ValueError:
            continue
        notes = [' '.join(n.split()) for n in body.get('outside_criteria') or [] if isinstance(n, str) and n.strip()] if isinstance(body, dict) else []
        if notes:
            lines.append(f'  {view["id"]} «{view["title"]}»')
            lines += [f'    - {n if len(n) <= NOTE_CAP else n[:NOTE_CAP - 1] + "…"}' for n in notes]
    return ['', NOTES_HEADING] + lines if lines else []


def _report(f):
    state, c = f['state'], f['contract']
    lines = _conclusion(f) + ['', f'BÁO CÁO: {f["name"]} — bản {f["revision"]}/{state["latest"]}, trạng thái {state["status"]}' + (f', cỡ {c["size"]}' if c else '')]
    lines += _wrap(f'Tiêu đề: «{c["title"]}»' if c else f'Tiêu đề: {NO_DATA}', '', '  ')
    lines += _wrap(f'Dự án: {f["row"]["project_path"]}', '', '  ')
    sections = (_outputs, _milestones, _minutes, _blocks, _questions, _outside, _parked)
    for number, (title, build) in enumerate(zip(TITLES, sections), 1):
        lines += ['', f'{number}. {title}'] + build(f)
    lines += _reviewer_notes(f)
    return '\n'.join(lines) + '\n'


def render_report(state_root, name, revision=None):
    return _report(_lookup(state_root, name, revision))


# ---- digest -----------------------------------------------------------------------------------------------------------

def render_digest(state_root):
    anchors = _anchors(state_root)
    opened, counts = [], {'accepted': 0, 'stopped': 0, 'failed': 0}
    for row, last in anchors:
        f = _gather(state_root, row)
        kind, _ = _standing(f)
        if kind != 'open': counts[kind] += 1; continue
        passed = len([v for v in f['views'] if v['state'] == 'passed'])
        total = f'{passed}/{len(f["views"])}' if f['contract'] else '?/?'
        opened.append((last, f'{f["name"]:<38} {f["state"]["status"]:<12} mốc {total:<5} cần bạn làm gì: {_needs(f)}'))
    opened.sort(key=lambda item: item[0], reverse=True)
    lines = [f'TÓM TẮT CÁC VIỆC ({len(anchors)} kế hoạch) — sổ: {Path(state_root).resolve()}']
    lines += [text for _, text in opened[:OPEN_CAP]]
    if len(opened) > OPEN_CAP: lines.append(f'(còn {len(opened) - OPEN_CAP} việc mở nữa, không hiển thị)')
    if not anchors: lines.append(NO_DATA)
    else: lines.append(f'{sum(counts.values())} việc đã đóng: {counts["accepted"]} nghiệm thu, {counts["stopped"]} dừng, {counts["failed"]} hỏng')
    return '\n'.join(lines) + '\n'


# ---- the only write: --out --------------------------------------------------------------------------------------------

def write_out(text, out, state_root):
    target = Path(out).resolve()
    if target.is_relative_to(Path(state_root).resolve()):
        raise LedgerError(f'--out {target} is inside the state root; a report never writes there.')
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding='utf-8', newline='\n')
    return f'Đã ghi {target} ({len(text.splitlines())} dòng)'
