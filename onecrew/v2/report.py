"""`onecrew plan report <name>` and `onecrew plan digest`: one page of plain text, written from what the ledger already holds
(v2 item 4). Both are read-only on purpose:

* the ledger is opened with sqlite `mode=ro` (a `_Reader` that refuses `transaction(write=True)`), so no event, request or file
  of the state root can be written; the only write is the optional `--out` file, which is refused inside the state root;
* no model, no network: the one outside look is `git log` on the repository the receipts name, which changes nothing there;
* the plan is found by name in the whole state root, and the directory of the receipts (not `--project`) says where the hook
  log and the repository are, so a plan of another project reads the same from any folder;
* a source that is missing prints "không có dữ liệu" / "không có nhật ký hook", never a guess.

Labels are Vietnamese; text that came from the ledger or the contract (titles, outputs, questions, reasons) is quoted as it is
(only whitespace is folded and a long text is cut with "…" so the page stays one page).
"""
import datetime as dt
import json
import os
import subprocess
from contextlib import contextmanager
from pathlib import Path

from ..ledger import Ledger, LedgerError
from . import contract as contracts, plan as plans, step0

NO_DATA = 'không có dữ liệu'
NO_HOOK_LOG = 'không có nhật ký hook'
TITLES = ('Output đạt tới đâu', 'Mốc và verdict', 'Phút so ngân sách', 'Lần chặn', 'Câu hỏi', 'Chạy ngoài kiểm soát', 'Bãi đỗ')
OPEN_CAP = 10                                  # lines for open plans in the digest
SCOPE_WORDS = ('scope', 'owned', 'outside', 'refused')
QUESTION_TYPES = ('v2.plan_stopped', 'v2.item_budget')
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
        if write: raise LedgerError('plan report/digest are read-only: they never write the ledger.')
        with Ledger.transaction(self) as conn:
            yield conn


def _cut(text, width=140):
    text = ' '.join(str(text).split())
    return text if len(text) <= width else text[:width - 1] + '…'


def _short(sha):
    return sha[:7] if isinstance(sha, str) and sha else '—'


def _when(text):
    return dt.datetime.fromisoformat(text)


def _stamp(text):
    return _when(text).astimezone(dt.timezone.utc).strftime('%Y-%m-%d %H:%M')


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
            'error': error, 'views': views, 'requests': reader.requests(row['id'])}


def _lookup(state_root, name, revision=None):
    found = [row for row, _ in _anchors(state_root) if row['request_key'] == plans.ANCHOR + name]
    if not found: raise LedgerError(f'No plan named {name} in {Path(state_root).resolve()}.')
    return _gather(state_root, found[-1], revision)


# ---- the seven sections -----------------------------------------------------------------------------------------------

def _outputs(f):
    c = f['contract']
    if c is None: return [f'{NO_DATA} (hợp đồng bản {f["revision"]} không đọc được: {_cut(f["error"], 90)})']
    by_id = {v['id']: v for v in f['views']}
    lines = []
    for oid, text in zip(contracts.output_ids(c['output']), c['output']):
        covering = [m['id'] for m in c['milestones'] if oid in m['covers']]
        shown = ' '.join(f'{m}={by_id[m]["last_verdict"]["result"] if by_id[m]["last_verdict"] else "chưa có verdict"}' for m in covering)
        done = bool(covering) and all(by_id[m]['state'] == 'passed' for m in covering)
        lines.append(f'  {oid} {"ĐẠT" if done else "CHƯA"} [{shown}] «{_cut(text, 110)}»')
    return lines


def _milestones(f):
    if f['contract'] is None: return [NO_DATA]
    lines = []
    for v in f['views']:
        last, mark = v['last_verdict'], ' · DỪNG' if v['state'] == 'stopped' else ''
        used = f'sửa {v["failures"]}/{v["max_repairs"]}'
        if last: lines.append(f'  {v["id"]} {last["result"]} · by {last["by"]} · {_short(last["artifact_sha"])} · {used}{mark} · «{_cut(v["title"], 60)}»')
        else: lines.append(f'  {v["id"]} chưa có verdict · {used} · «{_cut(v["title"], 60)}»')
    return lines


def _minutes(f):
    first, last = f['events'][0][1], f['events'][-1][1]
    spent = (_when(last) - _when(first)).total_seconds() / 60
    budget = f['contract']['budget']['time'] if f['contract'] else None
    line = f'  đã chạy {spent:.0f} phút (từ {_stamp(first)} đến {_stamp(last)} UTC)'
    if budget: line += f' / ngân sách {budget} phút' + (' — VƯỢT' if spent > budget else '')
    else: line += f' / ngân sách: {NO_DATA}'
    return [line, '  Lệnh: chưa đếm được']


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
    if found is None: return [f'  {NO_HOOK_LOG}' + (f' (tìm ở {places[0]})' if places else '')]
    try:
        raw = found.read_text(encoding='utf-8', errors='replace').splitlines()
    except OSError as error:
        return [f'  {NO_HOOK_LOG} (không đọc được {found}: {_cut(error, 60)})']
    mine = []
    for line in raw:
        try:
            item = json.loads(line)
        except ValueError:
            continue
        if isinstance(item, dict) and item.get('plan') == f['name'] and isinstance(item.get('reason'), str): mine.append(item['reason'])
    kinds = [_block_kind(r) for r in mine]
    lines = [f'  chờ kiểm: {kinds.count("wait")} · ngoài phạm vi: {kinds.count("scope")} · khác: {kinds.count("other")}']
    for reason in [r for r, k in zip(mine, kinds) if k == 'scope'][-3:]: lines.append(f'  ngoài phạm vi: «{_cut(reason, 150)}»')
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
    since = _when(start).astimezone(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%S+00:00')
    until = _when(f['events'][-1][1]).astimezone(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%S+00:00')
    known = {v['artifact_sha'] for v in f['state']['verdicts']}
    commits, problems = {}, []
    for directory in cwds:
        try:
            for sha, tree, short, subject in _git_log(directory, since, until): commits[sha] = (tree, short, subject)
        except (OSError, subprocess.SubprocessError) as error:
            problems.append(f'{directory}: {_cut(error, 70)}')
    if problems and not commits: return [f'  {NO_DATA} (không đọc được git: {problems[0]})']
    suspects = [(short, subject) for tree, short, subject in commits.values() if tree not in known]
    lines = [f'  {len(commits)} commit trong khoảng {_stamp(start)} → {_stamp(f["events"][-1][1])} UTC; {len(commits) - len(suspects)} khớp một biên nhận']
    lines += [f'  nghi ngờ {short} «{_cut(subject, 90)}»' for short, subject in suspects[:5]]
    if len(suspects) > 5: lines.append(f'  … và {len(suspects) - 5} commit nghi ngờ nữa')
    if not suspects and commits: lines.append('  không có commit nghi ngờ')
    return lines


def _questions(f):
    lines = []
    if f['contract']:
        used = len([r for r in f['requests'] if r['question'].get('action', {}).get('type') == 'v2.plan_stopped'])
        lines.append(f'  hạn mức hỏi chủ sở hữu: đã dùng {used}/{f["contract"]["attention"]["questions"]}')
    for r in f['requests']:
        lines.append(f'  [{"mở" if r["state"] == "pending" else "đã trả lời"}] {r["id"]}: «{_cut(r["question"].get("question", ""), 150)}»')
        if r['answer'] is not None: lines.append(f'    trả lời: {_cut(json.dumps(r["answer"], ensure_ascii=False), 150)}')
    if not f['requests']: lines.append('  không có câu hỏi nào')
    return lines


def _parked(f):
    c = f['contract']
    if c is None: return [NO_DATA]
    passed = {v['id'] for v in f['views'] if v['state'] == 'passed'}
    waiting = [i for i in c['items'] if i['tier'] == 'should' and i['milestone'] not in passed]
    unknown = [u for u in c['understanding']['unknowns'] if u['status'] == 'open' or u['id'] not in f['closed']]
    return [('  should chưa có mốc đạt: ' + '; '.join(f'{i["id"]} «{_cut(i["title"], 60)}»' for i in waiting[:5])
             + (f'; … +{len(waiting) - 5}' if len(waiting) > 5 else '')) if waiting else '  should chưa có mốc đạt: không có',
            f'  vượt hạn mức chú ý: {f["state"]["exceeded"]} lần',
            ('  unknown còn mở: ' + '; '.join(f'{u["id"]} «{_cut(u["question"], 70)}»' for u in unknown[:4])) if unknown else '  unknown còn mở: không có']


def _report(f):
    state, c = f['state'], f['contract']
    header = [f'BÁO CÁO: {f["name"]} — bản {f["revision"]}/{state["latest"]}, trạng thái {state["status"]}' + (f', cỡ {c["size"]}' if c else ''),
              f'Tiêu đề: «{_cut(c["title"], 150)}»' if c else f'Tiêu đề: {NO_DATA}',
              f'Dự án: {f["row"]["project_path"]}']
    sections = (_outputs, _milestones, _minutes, _blocks, _questions, _outside, _parked)
    lines = list(header)
    for number, (title, build) in enumerate(zip(TITLES, sections), 1):
        lines += ['', f'{number}. {title}'] + build(f)
    return '\n'.join(lines) + '\n'


def render_report(state_root, name, revision=None):
    return _report(_lookup(state_root, name, revision))


# ---- digest -----------------------------------------------------------------------------------------------------------

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


def render_digest(state_root):
    anchors = _anchors(state_root)
    opened, counts = [], {'accepted': 0, 'stopped': 0, 'failed': 0}
    for row, last in anchors:
        f = _gather(state_root, row)
        kind, who = _standing(f)
        if kind != 'open': counts[kind] += 1; continue
        passed = len([v for v in f['views'] if v['state'] == 'passed'])
        total = f'{passed}/{len(f["views"])}' if f['contract'] else '?/?'
        opened.append((last, f'{f["name"]:<38} {f["state"]["status"]:<12} mốc {total:<5} chờ: {who}'))
    opened.sort(key=lambda item: item[0], reverse=True)
    lines = [f'TÓM TẮT CÁC VIỆC ({len(anchors)} kế hoạch) — sổ: {Path(state_root).resolve()}']
    lines += [text for _, text in opened[:OPEN_CAP]]
    if len(opened) > OPEN_CAP: lines.append(f'… còn {len(opened) - OPEN_CAP} việc mở nữa, không hiển thị')
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
