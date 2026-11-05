"""`onecrew plan report <name>` and `onecrew plan digest`: one page of plain text, written from what the ledger already holds
(v2 item 4). Both are read-only on purpose:

* the ledger is opened with sqlite `mode=ro` (a `_Reader` that refuses `transaction(write=True)`), so no event, request or file
  of the state root can be written; the only write is the optional `--out` file, which is refused inside the state root;
* no model, no network: the outside looks are `git log` on the repository the receipts name, reading receipt blobs, and (for a plan that is not
  accepted) the artifact of the plan's project, hashed through a throw-away index exactly as `plan show` does it so that both name the same milestone
  states; none of them changes the state root or the working tree;
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
from . import contract as contracts, plan as plans, namespaces, step0

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
        rows = conn.execute("SELECT id, project_id, project_path, request_key, created_at FROM tasks WHERE request_key LIKE 'plan:%' OR request_key LIKE 'plan-ns:%' "
                            'ORDER BY created_at, id').fetchall()
        last = {r[0]: r[1] for r in conn.execute("SELECT task_id, MAX(created_at) FROM events WHERE kind NOT IN ('learning.outcome','control.intervention','context.entry','learning.incident','learning.lesson') GROUP BY task_id")}
    return [(dict(row), last.get(row['id'], row['created_at'])) for row in rows]


def _gather(state_root, row, revision=None):
    """Everything both commands read about one plan, in one pass over the ledger.

    The milestone views here are what the plan recorded on its own revision. The digest keeps them: it opens every plan of the state root, so it never
    hashes a project, and its lines stay as 2.1 printed them. `_lookup` (the report) replaces them with the views `plan show` and `accept` use."""
    reader = _Reader(state_root, row['project_id'], row['project_path'])
    name = namespaces.parse(row['request_key'])[0]
    with reader.transaction() as conn:
        state = plans.derive(reader, conn, row['request_key'])
        events = [(e['kind'], e['created_at'], json.loads(e['payload']))
                  for e in conn.execute("SELECT kind, created_at, payload FROM events WHERE task_id=? AND kind NOT IN ('learning.outcome','control.intervention','context.entry','learning.incident','learning.lesson') ORDER BY seq", (row['id'],))]
        closed = set(step0.closed_events(conn, row['id']))
        unknowns, holds = [], []
        if namespaces.has_capability(state, 'sequential-engine'):
            from . import runtime_unknowns, managed_executor
            unknowns = [u for u in runtime_unknowns.read(reader, row['request_key'], conn) if u['state'] == 'open']
            try:
                holds = managed_executor.hold_views(reader, row['request_key'], conn)          # W33a: how each held running node is held
            except LedgerError as problem:
                holds = [{'error': str(problem)}]
            # W20 (T18a [E2]): the latest recovery decision per node that is not a plain repair is a blocker/diagnosis the owner must see
            latest = {}
            for event in conn.execute("SELECT seq,payload FROM events WHERE task_id=? AND kind='workflow.recovery_decided' ORDER BY seq", (row['id'],)):
                p = json.loads(event['payload']); latest[p.get('node')] = dict(p, seq=event['seq'])
            blockers = [p for p in latest.values() if p.get('disposition') in ('blocked', 'diagnose')]
    if revision is not None and revision not in state['revisions']:
        raise LedgerError(f'Plan {name} has no revision {revision}.')
    revision = revision or state['latest']
    try:
        contract, error = plans.load(reader, state, revision)[0], None
    except LedgerError as problem:
        contract, error = None, str(problem)
    views = plans.milestone_views(contract, state, revision) if contract else []
    return {'name': name, 'row': row, 'state': state, 'events': events, 'closed': closed, 'revision': revision, 'contract': contract,
            'error': error, 'views': views, 'requests': reader.requests(row['id']), 'state_root': Path(state_root).resolve(), 'runtime_unknowns': unknowns,
            'holds': holds, 'recovery_blockers': blockers if namespaces.has_capability(state, 'sequential-engine') else [],
            'owner_choices': _owner_choices(reader.requests(row['id']))}


CHOICE_WORDS = {'stop': 'đã chọn dừng', 'amend_plan': 'đã chọn amend (chờ bản mới được duyệt; hợp đồng chưa đổi)', 'continue': 'đã chọn tiếp tục trong quyền đã cấp'}


def _owner_choices(requests):
    """W30b (T47a [E11]): what the owner chose on the plan's own questions (stop / amend / continue), from `request.answered`
    (the answer's choice and reference), never from an applied effect."""
    rows = []
    for request in requests:
        if request.get('state') != 'answered' or not isinstance(request.get('answer'), dict): continue
        action = (request.get('question') or {}).get('action') or {}
        if action.get('type') not in ('v2.plan_stopped', 'v2.workflow_hold'): continue
        answer = request['answer']
        choice = answer.get('choice')
        if choice not in CHOICE_WORDS: continue
        provenance = answer.get('provenance') or {}
        rows.append({'request': request['id'], 'choice': choice, 'reference': provenance.get('reference') or answer.get('reference'),
                     'by': provenance.get('by') or answer.get('by'), 'at': answer.get('at') or request.get('updated_at')})
    return rows


def _choice_lines(f):
    lines = []
    for row in f.get('owner_choices', []):
        who = 'Chủ sở hữu' if row.get('by') in ('user', 'owner') else f'Trả lời ({row.get("by") or "không rõ chủ thể"})'
        lines.append(f'{who} {CHOICE_WORDS[row["choice"]]}' + (f' («{row["reference"]}»)' if row.get('reference') else '') + f' — câu hỏi {row["request"]}')
    return lines


def _blocker_lines(f):
    """W20 (T18a [E2]): one line per node whose last recovery decision is a blocker or a diagnosis: the red checks, how many attempts
    (their receipts), what was spent against the ceilings, and what the policy asks next. No request is created by reading this."""
    lines = []
    for p in f.get('recovery_blockers', []):
        d = p.get('diagnosis') or {}
        spent = d.get('spent') or {}
        attempts = d.get('attempts') or []
        receipts = ', '.join(_short(a.get('receipt') or '') for a in attempts[-3:]) or NO_DATA
        cost = (f'{spent.get("used_calls")}/{spent.get("max_calls")} lời gọi' if spent.get('max_calls') is not None else 'chi phí: ' + NO_DATA)
        word = 'Blocker' if p.get('disposition') == 'blocked' else 'Cần chẩn đoán'
        lines.append(f'{word} node {p.get("node")}: ca đỏ {", ".join(d.get("failed_checks") or []) or NO_DATA} · {len(attempts)} lần thử ({receipts}) · '
                     f'đã tiêu {cost}, hạn {spent.get("deadline") or NO_DATA} · tiếp: {d.get("next") or NO_DATA}')
    return lines


def _hold_lines(f):
    """W33a (T15b [E3]): one line per running node an open finding holds, worded from the executor's declaration (hold_text), never "đã dừng"."""
    lines = []
    for hold in f.get('holds', []):
        if 'error' in hold:
            lines.append(f'Giữ node: không đọc được trạng thái giữ: {hold["error"]}'); continue
        state = ' — đã xác nhận tại điểm an toàn' if hold.get('confirmed') else (' — đã gửi yêu cầu' if hold.get('requested') and hold['plan']['command'] else '')
        lines.append(f'Giữ node {hold["node"]} (finding {", ".join(hold["findings"])}): {hold["text"]}{state}')
    return lines


def _lookup(state_root, name, revision=None, project_id=None):
    bare, explicit = namespaces.parse(name)
    keys = (explicit,) if explicit else (namespaces.LEGACY + bare, namespaces.NAMESPACED + bare)
    found = [row for row, _ in _anchors(state_root) if row['request_key'] in keys]
    local = [row for row in found if row['project_id'] == project_id]
    if local:
        found = local
    if not found: raise LedgerError(f'No plan named {name} in {Path(state_root).resolve()}.')
    if len(found) > 1:
        choices = ', '.join(row['request_key'] + ' (project ' + row['project_id'][:12] + ')' for row in found)
        raise LedgerError(f'Plan {bare} is ambiguous: choose an explicit anchor and project: {choices}.')
    f = _gather(state_root, found[0], revision)
    if f['contract']:       # the report reads the same milestone views as `plan show` and `accept` (plans.views_for): a carried verdict counts, a pass the artifact has left is stale,
        row = f['row']      # an accepted revision is read at the artifact accepted
        f['views'] = plans.views_for(_Reader(state_root, row['project_id'], row['project_path']), f['contract'], f['state'], f['revision'])
    return f


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
    if status == 'closed': return 'closed', '—'
    if status == 'stopped_with_report': return 'stopped', '—'
    if f['contract'] is None: return 'open', NO_DATA
    if status == 'proposed': return 'open', 'chủ sở hữu'
    pending = next((v for v in views if v['state'] != 'passed'), None)
    # An engine root that used its last repair round is still open: the engine names its next step (replan, or a stop with a reason); nothing closed it.
    if pending and pending['state'] == 'failed' and pending['repairs_left'] == 0 and not namespaces.has_capability(state, 'sequential-engine'): return 'failed', '—'
    if any(r['state'] == 'pending' for r in f['requests']): return 'open', 'chủ sở hữu'
    if f.get('runtime_unknowns'):
        return 'open', 'chủ sở hữu' if any(u['resolver']=='owner' for u in f['runtime_unknowns']) else 'AI'
    if pending is None: return 'open', 'chủ sở hữu'                              # every milestone passed: acceptance is the owner's
    if pending['state'] == 'failed': return 'open', 'AI'                          # a repair round remains
    if pending['verifier'] == 'owner-manual': return 'open', 'chủ sở hữu'
    return 'open', 'kiểm' if any(v['revision'] == f['revision'] for v in state['verdicts']) else 'AI'


def _needs(f):
    """What the owner has to do now: nghiệm thu | duyệt bản N | trả lời câu hỏi | không gì (and, for a stopped plan with no open question,
    the decision that stays with the owner)."""
    status, state = f['state']['status'], f['state']
    if status in ('accepted', 'closed'): return NOTHING
    if any(r['state'] == 'pending' for r in f['requests']): return 'trả lời câu hỏi'
    if status == 'proposed': return f'duyệt bản {state["latest"]}'
    if status == 'stopped_with_report': return 'quyết định việc đã dừng'
    if f['contract'] is None: return NO_DATA
    if f.get('runtime_unknowns'):
        return 'giải điều chưa biết thuộc chủ sở hữu' if any(u['resolver']=='owner' for u in f['runtime_unknowns']) else 'chưa cần quyết; AI cần giải unknown đúng phần bị giữ'
    if _open_findings(f): return 'chưa cần quyết; AI cần xử lý finding còn mở trước khi bàn giao'
    if f.get('finding_error'): return 'chưa thể nghiệm thu: không đọc được sổ finding'
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
    word = {'accepted': 'XONG', 'stopped': 'DỪNG', 'failed': 'HỎNG', 'closed': 'ĐÃ ĐÓNG'}.get(kind, 'ĐANG CHỜ')
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
    else:
        waiting = next(v for v in f['views'] if v['state'] != 'passed')
        why = f'mốc {waiting["id"]} ' + ('cũ: ' + '; '.join(waiting['stale_reasons']) if waiting.get('stale_reasons') else
                                            'cũ: đạt trên artifact khác, cần chạy lại' if waiting.get('stale') else 'chưa có verdict')
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

def _verdict_word(view, short=False):
    """What the milestone's verdict is worth in the state `plan show` gives it: the result as it was recorded, plus `cũ` (a pass on another artifact, which no
    longer covers the artifact now: state pending, `stale`), `kế thừa` (carried over from an earlier revision) or `trung lập` (only a path the contract
    declares neutral differs). A passed milestone with none of these reads exactly as it always did."""
    last = view['last_verdict']
    if not last: return 'chưa có verdict'
    if view.get('stale'): return 'cũ' if short else ('cũ (' + '; '.join(view['stale_reasons']) + ')' if view.get('stale_reasons') else
                                                   f'cũ ({last["result"]} trên artifact khác, cần chạy lại)')
    if view.get('neutral_diff'): return f'{last["result"]} (chỉ khác đường dẫn trung lập)' if not short else f'{last["result"]} trung lập'
    if view.get('carried_from'): return f'{last["result"]} (kế thừa từ bản {view["carried_from"]})' if not short else f'{last["result"]} kế thừa'
    return last['result']


def _outputs(f):
    rows = _output_rows(f)
    if rows is None: return _wrap(f'{NO_DATA} (hợp đồng bản {f["revision"]} không đọc được: {f["error"]})', '')
    by_id = {v['id']: v for v in f['views']}

    def shown(covering):
        return ' '.join(f'{m}={_verdict_word(by_id[m], short=True)}' for m in covering)
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
        if last: lines += _wrap(f'{v["id"]} {_verdict_word(v)} · by {last["by"]} · {_short(last["artifact_sha"])} · {used}{mark} · «{v["title"]}»', '  ', '      ')
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
    lines += _forecast_lines(f)
    for unknown in f.get('runtime_unknowns', []):
        lines += _wrap(f'Chưa rõ {unknown["unknown"]}: {unknown["question"]}; giữ {", ".join(unknown["required_by"])}; chủ thể giải: {unknown["resolver"]}.', '', '  ')
    for line in _hold_lines(f) + _blocker_lines(f) + _choice_lines(f): lines += _wrap(line, '', '  ')
    if state.get('workflow_version') is not None:
        lines += _wrap(f'Workflow: {state["workflow_version"]}; capabilities: {", ".join(state["capabilities"])}', '', '  ')
    sections = (_outputs, _milestones, _minutes, _blocks, _questions, _outside, _parked)
    for number, (title, build) in enumerate(zip(TITLES, sections), 1):
        lines += ['', f'{number}. {title}'] + build(f)
    lines += _reviewer_notes(f)
    return '\n'.join(lines) + '\n'


def render_report(state_root, name, revision=None, project_id=None):
    return _report(_lookup(state_root, name, revision, project_id))


# ---- digest -----------------------------------------------------------------------------------------------------------

def render_digest(state_root):
    anchors = _anchors(state_root)
    names = [namespaces.parse(row['request_key'])[0] for row, _ in anchors]
    opened, counts = [], {'accepted': 0, 'stopped': 0, 'failed': 0, 'closed': 0}
    for row, last in anchors:
        f = _gather(state_root, row)
        kind, _ = _standing(f)
        if kind != 'open': counts[kind] += 1; continue
        passed = len([v for v in f['views'] if v['state'] == 'passed'])
        total = f'{passed}/{len(f["views"])}' if f['contract'] else '?/?'
        label = f['name'] if names.count(f['name']) == 1 else f'{row["request_key"]} [{row["project_id"][:12]}]'
        need, next_step = _needs(f), ''
        if namespaces.has_capability(f['state'], 'sequential-engine'):
            try:
                from . import engine
                guidance = engine.next_action(_Reader(state_root, row['project_id'], row['project_path']), row['request_key'], observe_project=False)
                role = 'chủ sở hữu' if guidance['owner_only'] else 'bộ thực thi'
                next_step = '; bước tiếp theo (' + role + '): ' + guidance['reason']
                if guidance['kind'] == 'owner_accept': need = 'nghiệm thu'
                elif guidance['state'] == 'stopped': need = 'đã dừng: đọc lý do, bằng chứng được giữ'
                elif guidance['owner_only'] and need.startswith('chưa cần quyết'):
                    need = 'quyết định quyền hoặc ngân sách còn thiếu'
                elif need in (NOTHING, 'nghiệm thu'): need = 'quyết định quyền còn thiếu' if guidance['owner_only'] else 'chưa cần quyết'
            except (LedgerError, OSError, ValueError, KeyError, TypeError) as error:
                next_step = '; chưa xác minh được bước engine tiếp theo: ' + str(error)[:160]
        opened.append((last, f'{label:<38} {f["state"]["status"]:<12} mốc {total:<5} cần bạn làm gì: {need}' + next_step))
    opened.sort(key=lambda item: item[0], reverse=True)
    lines = [f'TÓM TẮT CÁC VIỆC ({len(anchors)} kế hoạch) — sổ: {Path(state_root).resolve()}']
    lines += [text for _, text in opened[:OPEN_CAP]]
    if len(opened) > OPEN_CAP: lines.append(f'(còn {len(opened) - OPEN_CAP} việc mở nữa, không hiển thị)')
    if not anchors: lines.append(NO_DATA)
    else: lines.append(f'{sum(counts.values())} việc đã đóng: {counts["accepted"]} nghiệm thu, {counts["stopped"]} dừng, {counts["failed"]} hỏng' +
                       (f', {counts["closed"]} chủ sở hữu đóng' if counts['closed'] else ''))
    return '\n'.join(lines) + '\n'


# ---- handover by acceptance (W23a, HD-31) and `plan present` ------------------------------------------------------------
#
# Both read what `_lookup` reads (the views of `plan show`), write nothing and call no model. An acceptance is an output criterion (O1, O2, ...); its
# evidence is the verdict of the milestones that cover it. It is "đạt" only when EVERY covering milestone is passed in the state `plan show` gives it (so a
# pass on another artifact is not) AND the receipt it names can be read from the blob store. It is "cần kiểm lại" when some covering milestone has a verdict
# that no longer counts (older artifact, failed, receipt gone), and "chưa có" when the rest has no verdict at all. A line of an acceptance that is not "đạt"
# never contains that word.

OK, RECHECK, NONE_YET = 'đạt', 'cần kiểm lại', 'chưa có'
# W23a / T38b [E4]: the state of one TASK (milestone), by what the ledger holds for it — never inferred from a missing receipt alone
CHECKED, RECHECK_TASK, SPECIFIED = 'đã-kiểm', 'phải kiểm lại', 'testcase-đã-đặc-tả'
PRESENT_TITLES = ('Yêu cầu', 'Kết quả bàn giao', 'Rủi ro', 'Cách nghiệm thu', 'Bằng chứng còn thiếu')
LIMITS_HEADING = 'Hạn chế còn lại:'
FINDINGS_NOTE = 'Finding còn mở: root này chưa bật sổ finding; không kết luận rằng không có lỗi.'


def _open_findings(f):
    if 'open_findings' not in f:
        if not namespaces.has_capability(f['state'], 'finding-register'):
            f['open_findings'] = []
        else:
            from .findings import list_findings
            reader = _Reader(f['state_root'], f['row']['project_id'], f['row']['project_path'])
            try:
                f['open_findings'] = list_findings(reader, f['row']['request_key'], task_id=f['row']['id'], open_only=True)
            except LedgerError as error:
                f['finding_error'] = str(error)
                f['open_findings'] = []
    return f['open_findings']


def _finding_limits(f):
    rows = _open_findings(f)
    if f.get('finding_error'):
        return ['Finding còn mở: không đọc được sổ finding: ' + f['finding_error']]
    if not namespaces.has_capability(f['state'], 'finding-register'):
        return [FINDINGS_NOTE] + _hold_lines(f) + _blocker_lines(f)
    return ([f'Finding còn mở: {r["id"]} · {r["severity"]} · mốc {r["node"]} · tiêu chí {r.get("criterion") or NO_DATA} · artifact {_short(r.get("artifact_sha") or "")} · '
             f'{r["head"]} · biên nhận {r["source"]["receipt"]}' for r in rows]
            or ['Finding còn mở: 0 theo sổ finding của root.']) + _hold_lines(f) + _blocker_lines(f)
CHECKER = {'command': 'lệnh tự chạy trên artifact, bạn không phải làm gì', 'reviewer': 'một reviewer (model khác) đọc diff và trả lời tiêu chí',
           'owner-manual': 'bạn tự thử rồi ghi kết quả (verdict của chủ sở hữu)'}


def _artifact_now(f):
    """The artifact the evidence is judged against: the one accepted, else the project's tree now (None when it cannot be made)."""
    accepted = f['state']['accepted']
    if accepted and accepted['revision'] == f['revision']: return accepted.get('artifact_sha')
    if 'artifact_now' not in f:
        from .verifiers import artifact as identities
        try:
            with identities.command.snapshot_limits():
                f['artifact_now'] = identities.identity(Path(f['row']['project_path'])) if f['row']['project_path'] else None
        except (LedgerError, OSError, subprocess.SubprocessError):
            f['artifact_now'] = None
    return f['artifact_now']


def _evidence(f, view):
    """(kind, text, receipt line or None) of one milestone as evidence: ok | stale | failed | lost | none. The receipt line is never wrapped (a path is one word)."""
    last, mid = view['last_verdict'], view['id']
    if not last: return 'none', f'mốc {mid} {SPECIFIED}: testcase có trong hợp đồng (bản {f["revision"]}), chưa chạy kiểm lần nào', None
    key = last.get('receipt')
    path = str(f['state_root'] / 'snapshots' / 'blobs' / key) if key else None
    readable = bool(key) and _blob_text(f['state_root'], key) is not None
    link = f'biên nhận {path}' if readable else None
    if view['state'] == 'passed':
        if readable: return 'ok', f'mốc {mid} {_verdict_word(view)} · by {last["by"]} · artifact {last["artifact_sha"]}', link
        return 'lost', f'mốc {mid}: verdict {last["result"]} nhưng biên nhận {key or "(không ghi)"} không đọc được trong sổ', None
    if view.get('stale'):
        if view.get('stale_reasons'):
            return 'stale', f'mốc {mid}: ' + '; '.join(view['stale_reasons']), link
        return 'stale', (f'mốc {mid}: bằng chứng cũ, {last["result"]} trên artifact {last["artifact_sha"]}, artifact hiện tại {_artifact_now(f) or "không xác định"}'), link
    reason = _receipt_reason(f, view)
    full = next((v for v in reversed((f.get('state') or {}).get('verdicts') or []) if v.get('receipt') == key), {})   # the ledger event carries the integrity record
    integrity = full.get('test_integrity') or last.get('test_integrity') or {}
    if last.get('result') == 'inconclusive' and 'no approved baseline' in str(integrity.get('error') or ''):
        return 'failed', (f'mốc {mid}: verdict gần nhất inconclusive — root cũ chưa có baseline đã duyệt (bản cũ không ghi artifact gốc, không có commit trước lúc duyệt); '
                          f'chủ sở hữu ghi baseline có chứng cứ: `onecrew verdict baseline --plan {f["name"]} --from-commit <commit đã duyệt> --by owner --reference <nơi quyết định>` rồi chạy lại mốc'), link
    return 'failed', f'mốc {mid}: verdict gần nhất {last["result"]} trên artifact {last["artifact_sha"]}' + (f' ({reason})' if reason else ''), link


def _acceptance(f):
    """[{id, text, status, evidence: [(kind, text, receipt line)]}] per output criterion, or None when the contract cannot be read."""
    rows = _output_rows(f)
    if rows is None: return None
    by_id = {v['id']: v for v in f['views']}
    out = []
    for oid, text, covering, _ in rows:
        evidence = [_evidence(f, by_id[m]) for m in covering]
        for finding in _open_findings(f):
            if finding['node'] in covering:
                evidence.append(('finding', f'finding {finding["id"]} ({finding["severity"]}) chưa được đóng bằng biên nhận hợp lệ', None))
        kinds = {e[0] for e in evidence}
        status = (OK if evidence and kinds == {'ok'} else RECHECK if kinds & {'stale', 'failed', 'lost', 'finding'} else NONE_YET)
        if f.get('finding_error'): status = RECHECK
        if not evidence: evidence = [('none', 'không có mốc nào kiểm output này', None)]
        out.append({'id': oid, 'text': text, 'status': status, 'evidence': evidence})
    return out


def _acceptance_lines(f):
    rows = _acceptance(f)
    if rows is None: return _wrap(f'{NO_DATA} (hợp đồng bản {f["revision"]} không đọc được: {f["error"]})')
    lines = []
    by_id = {v['id']: v for v in f['views']}
    covering = {oid: cov for oid, _, cov, _ in (_output_rows(f) or [])}
    for row in rows:
        states = ', '.join(f'{m} {task_state(f, by_id[m])[0]}' for m in covering.get(row['id'], []) if m in by_id)
        lines += _wrap(f'{row["id"]} {row["status"]} «{row["text"]}»' + (f' — task: {states}' if states else ''), '  ', '      ')
        for _, text, link in row['evidence']: lines += _wrap(text, '      ', '        ') + ([f'        {link}'] if link else [])
    return lines


def _limits(f):
    rows = _acceptance(f)
    if rows is None: return [NO_DATA]
    limits = [f'{r["id"]} {r["status"]}: ' + '; '.join(e[1] for e in r['evidence'] if e[0] != 'ok') for r in rows if r['status'] != OK]
    waiting, unknown = _parked_data(f)
    if waiting: limits.append('should chưa có mốc pass: ' + '; '.join(f'{i["id"]} «{i["title"]}»' for i in waiting))
    if unknown: limits.append('unknown còn mở: ' + '; '.join(f'{u["id"]} «{u["question"]}»' for u in unknown))
    if f['state']['status'] != 'accepted' and any(v['last_verdict'] for v in f['views']) and _artifact_now(f) is None:
        limits.append('không xác định được artifact hiện tại của dự án, nên chưa kiểm được bằng chứng còn khớp')
    return limits + _finding_limits(f)


def _heading(f, word):
    state, c = f['state'], f['contract']
    lines = [f'{word}: {f["name"]} — bản {f["revision"]}/{state["latest"]}, trạng thái {state["status"]}']
    lines += _wrap(f'Tiêu đề: «{c["title"]}»' if c else f'Tiêu đề: {NO_DATA}', '', '  ')
    return lines + _wrap(f'Dự án: {f["row"]["project_path"]}', '', '  ')


def render_handover(state_root, name, revision=None, project_id=None):
    """The handover report by acceptance: each output criterion as đạt / cần kiểm lại / chưa có with the evidence behind it, then what is left."""
    f = _lookup(state_root, name, revision, project_id)
    lines = _heading(f, 'BÀN GIAO') + ['Theo acceptance:'] + _acceptance_lines(f) + [LIMITS_HEADING]
    for limit in _limits(f): lines += _wrap('- ' + limit, '  ', '    ')
    return '\n'.join(lines) + '\n'


# ---- plan present -----------------------------------------------------------------------------------------------------

_GONE = object()


def _diff(old, new, path=''):
    """The shared, lossless contract diff, retaining the existing display API."""
    from .. import contract_diff
    return contract_diff.diff(old, new, path, missing=_GONE)


def _value(value):
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, sort_keys=True)


def _pending(f):
    """(baseline revision, was it approved) when the revision shown waits for the owner after an amendment; else None."""
    state = f['state']
    if f['revision'] != state['latest'] or state['latest'] < 2 or state['status'] != 'proposed': return None
    approved = state['approved']
    if approved and approved['revision'] < state['latest']: return approved['revision'], True
    return state['revisions'][state['latest']].get('from_revision') or state['latest'] - 1, False


def _amend_block(f):
    pending = _pending(f)
    if pending is None: return []
    base, was_approved = pending
    state, reader = f['state'], _Reader(f['state_root'], f['row']['project_id'], f['row']['project_path'])
    event = state['revisions'][f['revision']]
    lines = ['', f'ĐỔI SO VỚI BẢN {"ĐÃ DUYỆT" if was_approved else "TRƯỚC (chưa có bản nào được duyệt)"} (bản {base} → bản {f["revision"]})']
    if event.get('reason') is not None: lines += _wrap(f'Lý do amend: «{event["reason"]}»', '', '    ')
    if event.get('author'): lines += _wrap(f'Người sửa: {event["author"]}', '', '    ')
    try:
        old = plans.load(reader, state, base)[0]
    except LedgerError as error:
        return lines + _wrap(f'{NO_DATA} (bản {base} không đọc được: {error})', '', '    ')
    if f['contract'] is None: return lines + _wrap(f'{NO_DATA} (bản {f["revision"]} không đọc được)', '', '    ')
    changes = _diff(old, f['contract'])
    for where, how, before, after in changes:
        text = (f'{where}: ' + (f'thêm «{_value(after)}»' if how == 'thêm' else f'bỏ «{_value(before)}»' if how == 'bỏ'
                                else f'đổi «{_value(before)}» → «{_value(after)}»' if how == 'đổi' else 'đổi thứ tự'))
        lines += _wrap('- ' + text, '  ', '      ')
    if not changes: lines.append('  không có khác biệt nào trong hợp đồng')
    try:
        target = plans.resolve(reader, state)
    except LedgerError:
        target = None
    frozen = target['frozen'] if target else None
    if frozen:
        lines += _wrap('Ảnh hưởng: mốc chạy tiếp được trên bản đã duyệt: ' + (', '.join(frozen['runnable']) or 'không có') +
                       '; mốc chờ bản mới được duyệt: ' + (', '.join(frozen['frozen']) or 'không có'), '', '    ')
    else:
        lines += _wrap('Ảnh hưởng: chưa mốc nào chạy được cho tới khi bản mới được duyệt', '', '    ')
    return lines


def _present_request(f):
    c = f['contract']
    if c is None: return _wrap(NO_DATA)
    shown = c.get('presentation') or {}
    lines = _wrap(shown['request'] if shown.get('request') else 'Mục tiêu (AI diễn đạt lại): ' + c['understanding']['restated_goal'])
    if c.get('origin'): lines += _wrap(f'Lời gốc ({c["origin"]["by"]}, {c["origin"]["at"]}): «{c["origin"]["quote"]}»')
    lines += _wrap('Không làm: ' + (shown['not_doing'] if shown.get('not_doing') else '; '.join(c['non_goals']) or 'không ghi'))
    if shown.get('guard'): lines += _wrap('Giữ nguyên: ' + shown['guard'])
    return lines


def task_state(f, view):
    """W23a / T38b [E4]: (state, source) of one milestone as a task: `đã-kiểm` only for a valid pass on the current artifact with a
    readable receipt; `phải kiểm lại` when a verdict exists but no longer counts (older artifact, failed, receipt gone, open finding);
    `testcase-đã-đặc-tả` when the testcase is in the approved contract and no verdict was ever recorded. The source names the receipt,
    the reason or the contract revision — a missing receipt is never read as a missing testcase."""
    kind, text, link = _evidence(f, view)
    if kind == 'ok' and not any(finding['node'] == view['id'] for finding in _open_findings(f)):
        return CHECKED, link or text
    if kind == 'none':
        return SPECIFIED, text
    return RECHECK_TASK, text


def _milestone_facts(f):
    lines = []
    for v in f['views']:
        last = v['last_verdict']
        state, source = task_state(f, v)
        head = (f'{v["id"]} {v["state"]} · {_verdict_word(v, short=True)} · by {last["by"]} · artifact {last["artifact_sha"]}' if last
                else f'{v["id"]} {v["state"]} · chưa có verdict')
        lines += _wrap(f'{head} · trạng thái task: {state} · nguồn: {source}', '  ', '      ')
    return lines


def _present_result(f):
    c = f['contract']
    if c is None: return _wrap(NO_DATA)
    lines, sees = [], (c.get('presentation') or {}).get('user_sees') or []
    if f['state'].get('closed'):
        lines += _wrap('ĐÃ ĐÓNG — ' + f['state']['closed']['reason'])
    if sees: lines.append('  Bạn sẽ thấy:')
    for number, item in enumerate(sees, 1): lines += _wrap(f'{number}. {item}', '    ', '       ')
    accepted = f['state']['accepted']
    if accepted and accepted['revision'] == f['revision']:
        lines += _wrap(f'Đã nghiệm thu bởi {accepted.get("by")} («{accepted.get("reference")}») trên artifact {accepted.get("artifact_sha")}')
    for line in _choice_lines(f): lines += _wrap(line)
    return lines + ['  Theo acceptance:'] + _acceptance_lines(f) + ['  Mốc:'] + _milestone_facts(f)


def _present_risk(f):
    c = f['contract']
    if c is None: return _wrap(NO_DATA)
    items = [f'(tác giả ghi) {r}' for r in (c.get('presentation') or {}).get('risk') or []]
    view, reason = _failing(f)
    if view: items.append(f'mốc {view["id"]} ' + ('dừng' if view['state'] == 'stopped' else 'hỏng') + ': ' + (_receipt_reason(f, view) or 'không đọc được biên nhận')
                          + (f' ({reason})' if reason else ''))
    data = _parked_data(f)
    items += [f'unknown còn mở {u["id"]}: «{u["question"]}»' for u in data[1]]
    understanding = c['understanding']
    if understanding['confidence'] != 'high': items.append(f'độ tin cậy của hiểu yêu cầu: {understanding["confidence"]}')
    items += [f'giả định chưa có bằng chứng: «{a["text"]}»' for a in understanding['assumptions'] if not a.get('evidence')]
    if f['state']['exceeded']: items.append(f'đã vượt hạn mức chú ý {f["state"]["exceeded"]} lần')
    lines = []
    for item in items: lines += _wrap('- ' + item, '  ', '    ')
    return (lines or ['  không có rủi ro nào được ghi']) + _wrap(f'Ngân sách: {c["budget"]["max_calls"]} lần gọi, {c["budget"]["time"]} phút')


def _present_acceptance(f):
    c = f['contract']
    if c is None: return _wrap(NO_DATA)
    steps = (c.get('presentation') or {}).get('acceptance_steps')
    lines = []
    if steps:
        for number, step in enumerate(steps, 1): lines += _wrap(f'{number}. {step}', '  ', '     ')
    else:
        for m in c['milestones']:
            checker = CHECKER.get(m['verifier']['type'], 'bộ kiểm ' + m['verifier']['type'] + ' trên artifact cố định')
            lines += _wrap(f'mốc {m["id"]} «{m["title"]}»: {checker}', '  ', '      ')
    return lines + _wrap(f'Việc của bạn bây giờ: {_needs(f)}')


def _present_missing(f):
    rows = _acceptance(f)
    if rows is None: return _wrap(NO_DATA)
    lines = []
    for row in [r for r in rows if r['status'] != OK]:
        lines += _wrap(f'{row["id"]} {row["status"]}: ' + '; '.join(e[1] for e in row['evidence'] if e[0] != 'ok'), '  ', '      ')
    for u in _parked_data(f)[1]: lines += _wrap(f'unknown còn mở {u["id"]}: «{u["question"]}»', '  ', '      ')
    if _open_findings(f) or f.get('finding_error'):
        for limit in _finding_limits(f): lines += _wrap(limit, '  ', '      ')
    if f['state']['status'] != 'accepted' and any(v['last_verdict'] for v in f['views']) and _artifact_now(f) is None:
        lines += _wrap('không xác định được artifact hiện tại, nên chưa kiểm được bằng chứng còn khớp', '  ', '      ')
    return lines or ['  không thiếu bằng chứng nào cho các acceptance']


def render_present(state_root, name, revision=None, project_id=None):
    """`plan present`: one page of plain text, from the ledger, no model - what the owner reads before approving or accepting."""
    f = _lookup(state_root, name, revision, project_id)
    state = f['state']
    approved = state['approved']['revision'] if state['approved'] else 'chưa có'
    lines = _heading(f, 'TRÌNH') + [f'Bản đã duyệt: {approved}', f'Sha bản: {state["revisions"][f["revision"]]["sha"]}', f'Mã việc: {state["task_id"]}']
    lines += _wrap(f'Cần bạn làm: {_needs(f)}', '', '  ') + _amend_block(f)
    lines += _forecast_lines(f)
    for unknown in f.get('runtime_unknowns', []):
        lines += _wrap(f'Chưa rõ {unknown["unknown"]}: {unknown["question"]}; giữ {", ".join(unknown["required_by"])}; chủ thể giải: {unknown["resolver"]}.', '', '  ')
    for number, (title, build) in enumerate(zip(PRESENT_TITLES, (_present_request, _present_result, _present_risk, _present_acceptance, _present_missing)), 1):
        lines += ['', f'{number}. {title}'] + build(f)
    return '\n'.join(lines) + '\n'


def forecast_lines(state_root, name, revision=None, project_id=None):
    """The estimate/forecast block exactly as render_present and render_report embed it (they call the same _forecast_lines): the lines
    that carry estimate semantics, apart from identifiers and metadata, for checks that must judge the estimate wording only."""
    return _forecast_lines(_lookup(state_root, name, revision, project_id))


def _forecast_lines(f):
    from . import estimates
    try:
        row = f['row']
        out = estimates.read(_Reader(f['state_root'], row['project_id'], row['project_path']), row['request_key'])
    except (LedgerError, OSError, ValueError) as error:
        return ['Ước lượng: không đọc được dữ liệu (' + str(error) + ').']
    warnings = [w for item in out.get('budget_warnings', [])
                for w in _wrap('Cảnh báo 70% ngân sách (trong quyền, không cần bạn làm gì): ' + item['reason'] +
                               ' Bằng chứng: ' + ', '.join(item['evidence']), '', '  ')]
    if not out['baseline']: return warnings
    def span(value):
        return 'chưa có dữ liệu' if value is None else f'{value[0] / 3600:g}–{value[1] / 3600:g} giờ'
    def elapsed(value):
        return 'chưa đo được' if value == 'unknown' else f'{value / 3600:g} giờ'
    lines = [f'Ước lượng công thực thi ban đầu: {span(out["baseline"]["execution_seconds"])}; công còn lại: {span(out["remaining_seconds"])} (chưa hiệu chỉnh).',
             f'Thực thi: {elapsed(out["execution_seconds"])}; chờ: {elapsed(out["waiting_seconds"])}; deadline: {out["deadline"] or "chưa đặt"}.']
    left = out.get('wall_clock_remaining_seconds')
    if left is not None:
        lines.append((f'Đã quá deadline {-left / 3600:.1f} giờ' if out.get('deadline_passed') else f'Còn {left / 3600:.1f} giờ lịch tới deadline') +
                     ' (thời gian lịch, đã gồm thời gian chờ; không phải công còn lại, không phải ETA).')
    lines.append('Thời điểm hoàn thành dự kiến: chưa xác định; tổng công không phải thời gian lịch khi chạy song song hoặc chờ.')
    if out.get('remaining_reason'): lines.append(out['remaining_reason'])
    if out['history']:
        last = out['history'][-1]
        lines += _wrap('Lý do đổi ước lượng: ' + last['reason'], '', '  ')
    for item in out['additional']:
        lines += _wrap(f'Phát sinh {item["key"]} ({item["category"]}, {item["disposition"]}): {item["reason"]}', '', '  ')
    return lines + warnings


# ---- the only write: --out --------------------------------------------------------------------------------------------

def write_out(text, out, state_root):
    target = Path(out).resolve()
    if target.is_relative_to(Path(state_root).resolve()):
        raise LedgerError(f'--out {target} is inside the state root; a report never writes there.')
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding='utf-8', newline='\n')
    return f'Đã ghi {target} ({len(text.splitlines())} dòng)'
