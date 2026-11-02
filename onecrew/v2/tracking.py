"""OBS-1: the read-only tracking view of a state root — the ONE state model the `track` CLI, the `track` web page and their JSON share.

Everything here is a projection of what the ledger already holds (plan.* events, engine node/generation/attempt events, Control attempts,
executor.observed liveness, requests, notices, estimates): no second progress ledger, no model call, no write. The ledger is opened read-only
(report._Reader: sqlite mode=ro + query_only), so a bug here can refuse to show something but can never change a task, a right or a result.

Words the owner sees are sourced: every status carries the events / attempts / requests it was derived from, and a value the ledger does not
hold is `unknown` ("chưa xác định"), never 0, never a guessed percentage. Four levels of "done" are kept apart (produced / verified / accepted,
plus "live activity"), an attempt is running until ITS OWN settlement (a child task's own completion does not settle it), events of an older
generation never move the current one (engine.state drops them; the timeline shows them as "thế hệ cũ"), and overlapping attempts are joined by
union (execution_mode.measure), never summed. Sessions of Claude/Codex that did not run through OneCrew have no source here and are reported as
NOT tracked; nothing turns a chat session into a monitored task.

Secrets: every string that leaves this module goes through `clean` (the S1 line redaction of diagnostics.redact_line, control characters
dropped, length capped). Environments, prompts and transcripts are never read.
"""
import datetime as dt
import json
import re
import sqlite3
from pathlib import Path

from ..ledger import LedgerError, utcnow
from . import namespaces, plan as plans, report

VERSION = 1
UNKNOWN = 'unknown'
KINDS = ('running', 'waiting', 'blocked', 'done', 'unknown')
WORDS = {'running': 'đang thực hiện', 'waiting': 'đang chờ', 'blocked': 'bị chặn', 'done': 'hoàn tất', 'unknown': 'chưa xác định'}
LEVELS = ('none', 'produced', 'verified', 'accepted')
LEVEL_WORDS = {'none': 'chưa có đầu ra', 'produced': 'đã tạo đầu ra', 'verified': 'đã kiểm', 'accepted': 'đã nghiệm thu'}
NOISE = ('learning.outcome', 'control.intervention', 'context.entry', 'learning.incident', 'learning.lesson')
NOT_TRACKED = 'chưa được theo dõi'
STATEMENT = ('Phiên Claude/Codex không chạy qua OneCrew không có nguồn trong sổ này: ' + NOT_TRACKED +
             '. Màn hình này không biến một phiên chat thành task được theo dõi; chỉ root/node/attempt có trong sổ mới xuất hiện.')
CONTROLS = 'không có: màn hình này không duyệt, không trả lời, không tạm dừng, không tiếp tục task; đọc hay mở bằng chứng không phải là duyệt.'
LIMIT = 300
HEX64 = re.compile(r'\b[0-9a-f]{64}\b')
EVIDENCE_CAP = 65536


# ---- text and time ------------------------------------------------------------------------------------------------------------------

def clean(value, limit=LIMIT):
    """One line of text safe to show: the secret parts withheld (diagnostics.redact_line), control characters dropped, at most `limit` chars."""
    if value is None: return None
    from .diagnostics import redact_line
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    text = ''.join(c if c.isprintable() or c == ' ' else ' ' for c in text.replace('\n', ' '))
    text, _ = redact_line(text)
    return text[:limit] + ('…' if len(text) > limit else '')


def _at(text):
    try:
        value = dt.datetime.fromisoformat(text)
        return value if value.tzinfo else value.replace(tzinfo=dt.timezone.utc)
    except (TypeError, ValueError):
        return None


def _iso(value):
    return value.isoformat() if isinstance(value, dt.datetime) else None


def _seconds(start, end):
    return round((end - start).total_seconds(), 3) if start and end and end >= start else UNKNOWN


def _now(now):
    return now if isinstance(now, dt.datetime) else (_at(now) if now else _at(utcnow()))


# ---- the ledger door ----------------------------------------------------------------------------------------------------------------

def _source(state_root):
    """(reader, source record): the read-only reader of the state root and what the overview says about its ledger."""
    reader = report._Reader(state_root)
    record = {'ledger': str(reader.path), 'status': 'ok', 'detail': None}
    if not reader.path.exists():
        record.update(status='missing', detail='không có sổ tại đường dẫn này (chưa có task nào, hoặc sai --state-root)')
    return reader, record


def _rows(conn, project_id):
    sql = 'SELECT id, project_id, project_path, request_key, revision, payload, created_at FROM tasks'
    args = []
    if project_id:
        sql += ' WHERE project_id=?'; args.append(project_id)
    return [dict(r) for r in conn.execute(sql + ' ORDER BY created_at, id', args)]


def _events(conn, task_id, kinds=None):
    sql = 'SELECT seq, kind, payload, created_at FROM events WHERE task_id=?'
    args = [task_id]
    if kinds:
        sql += f' AND kind IN ({",".join("?" for _ in kinds)})'; args += list(kinds)
    return [(r['seq'], r['kind'], json.loads(r['payload']), r['created_at']) for r in conn.execute(sql + ' ORDER BY seq', args)]


def _schema_version(conn):
    return conn.execute('PRAGMA user_version').fetchone()[0]


# ---- one root --------------------------------------------------------------------------------------------------------------------------

def _goal(contract, payload):
    understanding = (contract or {}).get('understanding') or {}
    return clean(understanding.get('restated_goal') or (contract or {}).get('title') or payload.get('title') or '')


def _attempts(conn, task_ids):
    if not task_ids or _schema_version(conn) < 2: return []
    marks = ','.join('?' for _ in task_ids)
    out = []
    for row in conn.execute(f'SELECT id, task_id, generation, status, created_at, updated_at, operation FROM attempts WHERE task_id IN ({marks}) ORDER BY created_at, id', list(task_ids)):
        op = json.loads(row['operation']) if row['operation'] else {}
        out.append({'id': row['id'], 'task': row['task_id'], 'generation': row['generation'], 'status': row['status'],
                    'created_at': row['created_at'], 'updated_at': row['updated_at'],
                    'unit': clean(op.get('unit', 'root'), 100), 'stage': clean(op.get('stage'), 100)})
    return out


def _progress_rows(events):
    """Latest executor.observed progress checkpoint per node (what progress_track.read returns), from the root's events."""
    latest = {}
    for seq, kind, p, at in events:
        if kind == 'executor.observed' and p.get('what') == 'progress' and p.get('node'):
            cp = p.get('checkpoint') or {}
            latest[p['node']] = {'seq': seq, 'attempt': p.get('attempt'), 'status': cp.get('status', UNKNOWN), 'reason': clean(cp.get('reason')),
                                 'observed_at': p.get('observed_at'), 'received_at': p.get('received_at') or at, 'time_source': p.get('time_source'),
                                 'kind': (p.get('observation') or {}).get('kind'),
                                 'elapsed_seconds': (p.get('observation') or {}).get('elapsed_seconds'),
                                 'command_cap_seconds': p.get('command_cap_seconds')}
    return latest


def _open_waits(events):
    """Executor waits (what=wait) that have no end, and recorded mode waits without a later record of the same node."""
    waits = []
    for seq, kind, p, at in events:
        if kind == 'executor.observed' and p.get('what') == 'wait':
            wait = p.get('wait') or {}
            if not wait.get('until'):
                waits.append({'seq': seq, 'reason': wait.get('reason'), 'since': p.get('observed_at') or at, 'attempt': p.get('attempt'), 'source': 'executor.observed'})
        elif kind == 'workflow.mode' and p.get('mode') == 'wait' and not p.get('corrects'):
            waits.append({'seq': seq, 'reason': clean(p.get('mode_reasons') or p.get('reasons')), 'since': at, 'node': p.get('node'), 'source': 'workflow.mode'})
    # a mode wait of a node ends at that node's next non-wait record
    ended = set()
    for w in waits:
        if w['source'] != 'workflow.mode': continue
        for seq, kind, p, at in events:
            if seq > w['seq'] and kind in ('workflow.mode', 'node.started') and p.get('node') == w.get('node') and not (kind == 'workflow.mode' and p.get('mode') == 'wait'):
                ended.add(w['seq']); break
    return [w for w in waits if w['seq'] not in ended]


def _needs_user(state, requests, views, level, engine_view):
    needs = []
    for r in requests:
        if r['state'] != 'pending': continue
        q = r['question'] or {}
        needs.append({'kind': 'request', 'id': r['id'], 'revision': r['revision'], 'question': clean(q.get('question')),
                      'options': [{'id': clean(o.get('id'), 60), 'label': clean(o.get('label'), 200)} for o in (q.get('options') or [])[:6]],
                      'reply_command': f"question answer {r['id']} --revision {r['revision']} --choice <option-id>",
                      'note': 'đọc, đóng cửa sổ hay bỏ qua không phải là trả lời; request vẫn chờ', 'source': ['request:' + r['id']]})
    if state['status'] == 'proposed':
        needs.append({'kind': 'approve', 'question': f"Duyệt bản {state['latest']} của plan {state['name']} (plan approve, lệnh của chủ sở hữu)",
                      'source': [f"plan.{'amended' if state['latest'] > 1 else 'proposed'}:rev{state['latest']}"]})
    elif state['status'] == 'stopped_with_report':
        stopped = state['stopped'].get(state['latest']) or {}
        needs.append({'kind': 'stopped', 'question': 'Đọc báo cáo dừng ở mốc ' + clean(stopped.get('milestone'), 50) + ' và quyết định (tiếp tục / amend / dừng)',
                      'source': [f"milestone.stopped:rev{state['latest']}"]})
    elif state['status'] == 'approved' and level == 'verified':
        if engine_view is not None or (views and all(v['state'] == 'passed' for v in views)):
            needs.append({'kind': 'accept', 'question': 'Mọi mốc đã có verdict đạt: nghiệm thu (plan accept, lệnh của chủ sở hữu) hoặc nêu điều chưa đạt',
                          'source': ['milestone.passed' if views else 'node.verification:pass']})
    return needs


def _level(state, engine_view, views):
    if state['status'] in ('accepted', 'closed'): return 'accepted'
    if engine_view is not None and engine_view.get('nodes'):
        ranks = [{'produced': 1, 'verified': 2, 'accepted': 3}.get(r.get('state'), 0) for r in engine_view['nodes'].values()]
        if ranks and all(r >= 3 for r in ranks): return 'accepted'
        if ranks and all(r >= 2 for r in ranks): return 'verified'
        if any(r >= 1 for r in ranks): return 'produced'
        return 'none'
    if views and all(v['state'] == 'passed' for v in views): return 'verified'
    return 'none'


def _status(state, engine_view, attempts, progress, waits, requests, views, verifier_runs, level, first_started):
    """(kind, reason, sources): the sourced status of a root. Order: done > blocked > activity (running / unknown attempt) > waiting > not started."""
    src = []
    if state['status'] in ('accepted', 'closed'):
        return 'done', 'đã nghiệm thu' if state['status'] == 'accepted' else 'chủ sở hữu đã đóng', [f"plan.{state['status']}"]
    if state['status'] == 'stopped_with_report':
        return 'blocked', 'dừng có báo cáo ở mốc ' + clean((state['stopped'].get(state['latest']) or {}).get('milestone'), 50), [f"milestone.stopped:rev{state['latest']}"]
    if state['status'] == 'proposed':
        return 'waiting', 'chờ chủ sở hữu duyệt bản ' + str(state['latest']), [f"plan.proposed:rev{state['latest']}"]
    active = [a for a in attempts if a['status'] in ('reserved', 'running', 'unknown')]
    unknown = [a['id'] for a in active if a['status'] == 'unknown']
    if engine_view is not None:
        held = [nid for nid, r in engine_view['nodes'].items() if r.get('phase') == 'held']
        blockers = {k: v for k in ('finding_blockers', 'unknown_blockers', 'failed_blockers', 'request_blockers') for v in [engine_view.get(k) or {}] if v}
        stalled = [nid for nid, p in progress.items() if p['status'] == 'blocked' and engine_view['nodes'].get(nid, {}).get('phase') == 'running']
        if held or blockers or stalled:
            parts = []
            if held: parts.append('node bị giữ: ' + ', '.join(f"{nid} ({clean(engine_view['nodes'][nid].get('reason'), 80)})" for nid in held)); src += ['node.held:' + n for n in held]
            for key, value in blockers.items():
                parts.append(key.replace('_blockers', '') + ' chặn ' + ', '.join(sorted(value))); src.append(key)
            if stalled: parts.append('quan sát tiến độ báo blocked ở ' + ', '.join(stalled)); src += [f"executor.observed:{progress[n]['seq']}" for n in stalled]
            if unknown: parts.append('attempt ở trạng thái unknown: ' + ', '.join(unknown)); src += ['attempt:' + a for a in unknown]
            others = [a for a in active if a['status'] != 'unknown' and not any(engine_view['nodes'].get(n, {}).get('attempt') == a['id'] for n in held + stalled)]
            if others: parts.append('node khác vẫn có attempt đang chạy: ' + ', '.join(a['id'] for a in others))
            return 'blocked', '; '.join(parts), src
    if unknown:
        return 'unknown', 'attempt ở trạng thái unknown (kết quả tiến trình chưa được xác định): ' + ', '.join(unknown), ['attempt:' + a for a in unknown]
    if active:
        words = []
        for a in active:
            node = next((nid for nid, r in (engine_view or {}).get('nodes', {}).items() if r.get('attempt') == a['id']), None)
            p = progress.get(node) if node else None
            live = f", quan sát gần nhất {p['status']} lúc {p['observed_at'] or p['received_at']}" if p else ', chưa có quan sát tiến độ (im lặng không phải là không tiến triển)'
            words.append(f"attempt {a['id']} [{a['status']}]" + (f" node {node}" if node else '') + live)
        return 'running', '; '.join(words), ['attempt:' + a['id'] for a in active]
    open_runs = [r for r in verifier_runs if r['receipt'] is None and r['abandoned'] is None]
    if open_runs:
        return 'running', 'verdict đang chạy ở mốc ' + ', '.join(clean(r.get('milestone'), 50) for r in open_runs), ['verdict.run_started:' + str(r.get('run_id')) for r in open_runs]
    pending = [r for r in requests if r['state'] == 'pending']
    if pending:
        return 'waiting', 'chờ chủ sở hữu trả lời ' + ', '.join(r['id'] for r in pending), ['request:' + r['id'] for r in pending]
    if waits:
        return 'waiting', 'đang chờ: ' + '; '.join(clean(w.get('reason'), 120) or 'không rõ lý do' for w in waits), [f"{w['source']}:{w['seq']}" for w in waits]
    if level == 'verified':
        return 'done', 'mọi mốc/node đã kiểm đạt; chờ nghiệm thu của chủ sở hữu', ['node.verification' if engine_view is not None else 'milestone.passed']
    if engine_view is not None:
        produced = [nid for nid, r in engine_view['nodes'].items() if r.get('state') == 'produced']
        pending_nodes = [nid for nid, r in engine_view['nodes'].items() if r.get('phase') == 'pending']
        if produced:
            return 'waiting', 'đầu ra đã tạo, chờ kiểm: ' + ', '.join(produced), ['node.produced:' + n for n in produced]
        if pending_nodes and not first_started:
            return 'waiting', 'đã duyệt, chưa có worker nào được bắt đầu (chờ engine step)', ['plan.approved']
        if pending_nodes:
            return 'waiting', 'chờ bước tiếp theo cho ' + ', '.join(pending_nodes), ['engine.state']
        return 'unknown', 'không có node đang chạy, bị giữ hay chờ; không suy được từ sổ', ['engine.state']
    if views:
        left = [v['id'] for v in views if v['state'] != 'passed']
        return 'waiting', 'chờ verdict của mốc ' + ', '.join(left) + ' (root không có engine: chỉ theo dõi mốc)', ['plan.approved']
    return 'unknown', 'hợp đồng không đọc được; không suy được trạng thái', ['plan.approved']


def _elapsed(state, events, now):
    approved = state.get('approved') or {}
    start = _at(approved.get('at') or approved.get('recorded_at'))
    if start is None:
        return {'since': None, 'seconds': UNKNOWN, 'basis': 'chưa duyệt: thời gian đã chạy đo từ lúc duyệt'}
    end = None
    for seq, kind, p, at in events:
        if kind in ('plan.accepted', 'plan.closed'): end = _at(p.get('at') or at)
    stop = end or now
    return {'since': _iso(start), 'until': _iso(end), 'seconds': _seconds(start, stop),
            'basis': 'plan.approved → ' + ('plan.accepted/closed' if end else 'bây giờ') + ' (thời gian lịch, gồm cả chờ)'}


def _last_evidence(events):
    best = None
    for seq, kind, p, at in events:
        ref, label = None, None
        if kind == 'node.produced': ref, label = p.get('receipt'), f"đầu ra node {p.get('node')}"
        elif kind == 'node.verification': ref, label = p.get('receipt'), f"kiểm node {p.get('node')}: {p.get('result')}"
        elif kind == 'verdict.recorded': ref, label = p.get('receipt'), f"verdict mốc {p.get('milestone')}: {p.get('result')}"
        elif kind == 'executor.observed': ref, label = (p.get('basis') or {}).get('ref'), f"quan sát {p.get('what')} ({(p.get('checkpoint') or {}).get('status', '')})".replace(' ()', '')
        elif kind == 'support.feedback': ref, label = None, 'báo lỗi S1'
        else: continue
        when = p.get('observed_at') or at
        item = {'seq': seq, 'kind': kind, 'at': when, 'received_at': at, 'label': clean(label, 120), 'ref': clean(ref, 200),
                'provenance': p.get('time_source') or 'ledger_event'}
        if best is None or (_at(when) or _at(at)) >= (_at(best['at']) or _at(best['received_at'])): best = item
    return best


def _summary(kind, p):
    n, g = p.get('node'), p.get('generation')
    if kind in ('plan.proposed', 'plan.amended'): return f"{'đề xuất' if kind.endswith('proposed') else 'sửa'} bản {p.get('revision')} bởi {p.get('author') or '?'}"
    if kind == 'plan.approved': return f"chủ sở hữu duyệt bản {p.get('revision')}"
    if kind == 'plan.accepted': return f"chủ sở hữu nghiệm thu bản {p.get('revision')}"
    if kind == 'plan.closed': return 'chủ sở hữu đóng plan'
    if kind == 'plan.revised': return f"kế hoạch nội bộ bản {p.get('internal_revision')}: {p.get('reason') or ''}"
    if kind == 'node.started': return f"node {n} (thế hệ {g}) bắt đầu — attempt {p.get('attempt')}, task con {p.get('child')}"
    if kind == 'node.produced': return f"node {n} (thế hệ {g}) đã tạo đầu ra"
    if kind == 'node.verification': return f"kiểm node {n} (thế hệ {g}): {p.get('result')}"
    if kind == 'node.accepted': return f"node {n} được nghiệm thu"
    if kind == 'node.held': return f"node {n} bị giữ: {p.get('reason') or ''} ({p.get('classification') or ''})"
    if kind == 'node.resumed': return f"node {n}: thế hệ mới sau thế hệ {g}" + (' (tiếp tục từ đầu ra dở)' if p.get('resume_artifact') else '')
    if kind == 'node.result_retained': return f"node {n}: kết quả được giữ lại ({p.get('reason') or ''})"
    if kind == 'workflow.mode': return f"cách chạy node {n}: {p.get('mode')} — {p.get('mode_reasons') or p.get('reasons') or ''}"
    if kind == 'executor.observed':
        cp = p.get('checkpoint') or {}
        return f"quan sát {p.get('what')}" + (f" node {n}: {cp.get('status')} ({cp.get('reason') or ''})" if p.get('what') == 'progress' else '') + (f" chờ {p.get('wait', {}).get('reason')}" if p.get('what') == 'wait' else '')
    if kind == 'executor.managed': return f"worker được quản lý: {p.get('phase')} (attempt {p.get('attempt')})"
    if kind in ('attempt.reserved', 'attempt.launched', 'attempt.settled'): return f"attempt {p.get('id')} {kind.split('.')[1]}"
    if kind in ('request.created', 'request.revised'): return f"câu hỏi {p.get('id')} bản {p.get('revision')}: {(p.get('question') or {}).get('question') if isinstance(p.get('question'), dict) else p.get('question') or ''}"
    if kind == 'request.consumed': return f"câu hỏi {p.get('id')} đã được trả lời và dùng"
    if kind == 'notice.exception': return f"thông báo {p.get('category')}: {p.get('reason') or ''}"
    if kind == 'verdict.recorded': return f"verdict mốc {p.get('milestone')}: {p.get('result')} bởi {p.get('by')}"
    if kind == 'verdict.run_started': return f"bắt đầu chạy verdict mốc {p.get('milestone')}"
    if kind == 'verdict.receipt_issued': return f"receipt verdict mốc {p.get('milestone')}"
    if kind == 'milestone.passed': return f"mốc {p.get('milestone')} đạt"
    if kind == 'milestone.stopped': return f"dừng ở mốc {p.get('milestone')}: {p.get('reason') or ''}"
    if kind == 'milestone.failed': return f"mốc {p.get('milestone')} không đạt"
    if kind == 'workflow.recovery_decided': return f"quyết định khôi phục node {n}: {p.get('disposition')} ({p.get('reason') or ''})"
    if kind == 'knowledge.delivered': return f"tri thức giao cho node {n}"
    if kind == 'workflow.checkpoint': return f"checkpoint v1: {p.get('phase')} — {p.get('message') or ''}"
    if kind.startswith('support.'): return f"hỗ trợ: {kind.split('.', 1)[1]} {p.get('id') or ''}"
    if kind == 'decision.recorded':
        subject = p.get('subject') if isinstance(p.get('subject'), dict) else {}
        return f"quyết định của {subject.get('component') or p.get('subject') or '?'}: {p.get('basis') or ''}"
    if kind == 'task.submitted': return 'task được ghi vào sổ'
    if kind == 'attempt.unknown': return f"attempt {p.get('id')}: kết quả tiến trình chưa xác định"
    if kind == 'execution.configured': return 'cấu hình thực thi của task con'
    if kind == 'budget.group': return 'ngân sách chung của root'
    if kind in ('estimate.baseline', 'estimate.eta', 'estimate.additional'): return f"ước lượng: {kind.split('.')[1]} — {p.get('reason') or ''}"
    if kind == 'precondition.recorded': return 'điều kiện tiên quyết đã kiểm'
    if kind == 'plan.step0_closed': return 'bước 0 khép'
    if kind == 'plan.advised': return f"cố vấn bản {p.get('revision')}"
    return kind


def _keys_of(payload):
    return set(HEX64.findall(json.dumps(payload, ensure_ascii=False, default=str)))


def _timeline(conn, root_id, children, current_generation, limit):
    rows = []
    task_ids = [root_id] + sorted(children)
    marks = ','.join('?' for _ in task_ids)
    noise = ','.join('?' for _ in NOISE)
    total = conn.execute(f'SELECT COUNT(*) FROM events WHERE task_id IN ({marks}) AND kind NOT IN ({noise})', task_ids + list(NOISE)).fetchone()[0]
    keys = set()
    for r in conn.execute(f'SELECT seq, task_id, kind, payload, created_at FROM events WHERE task_id IN ({marks}) AND kind NOT IN ({noise}) ORDER BY seq DESC LIMIT ?',
                          task_ids + list(NOISE) + [limit]):
        p = json.loads(r['payload'])
        keys |= _keys_of(p)
        node, gen = p.get('node'), p.get('generation')
        stale = node is not None and gen is not None and node in current_generation and gen != current_generation[node]
        rows.append({'seq': r['seq'], 'task': 'root' if r['task_id'] == root_id else r['task_id'], 'at': r['created_at'], 'kind': r['kind'],
                     'node': node, 'generation': gen, 'attempt': p.get('attempt') or (p.get('id') if r['kind'].startswith('attempt.') else None),
                     'summary': clean(_summary(r['kind'], p), 240),
                     'observed_at': p.get('observed_at'), 'received_at': p.get('received_at'),
                     'stale_generation': stale, 'note': 'thế hệ cũ: không đổi trạng thái hiện tại' if stale else None,
                     'evidence': sorted(_keys_of(p))[:6]})
    rows.reverse()
    return rows, total, keys


def _item(reader, conn, row, now, *, full=False, timeline_limit=200):
    rd = report._Reader(reader.state_root, row['project_id'], row['project_path'])
    state = plans.derive(rd, conn, row['request_key'])
    payload = json.loads(row['payload'])
    events = _events(conn, row['id'])
    events = [e for e in events if e[1] not in NOISE]
    try:
        contract, contract_error = plans.load(rd, state, state['latest'])[0], None
    except (LedgerError, OSError, ValueError) as error:
        contract, contract_error = None, clean(str(error), 200)
    engine_root = namespaces.has_capability(state, 'sequential-engine')
    engine_view, engine_error = None, None
    if engine_root:
        try:
            from . import engine
            engine_view = engine.state(rd, row['request_key'], conn)
        except (LedgerError, OSError, ValueError, KeyError) as error:
            engine_error = clean(str(error), 200)
    views = []
    if contract and not engine_root:
        try: views = plans.milestone_views(contract, state, state['latest'])
        except (LedgerError, OSError, ValueError, KeyError): views = []
    children = {p.get('child') for seq, kind, p, at in events if kind == 'node.started' and p.get('child')}
    attempts = _attempts(conn, [row['id']] + sorted(children))
    progress = _progress_rows(events)
    waits = _open_waits(events)
    requests = [{'id': r['id'], 'revision': r['revision'], 'state': r['state'], 'created_at': r['created_at'], 'updated_at': r['updated_at'],
                 'question': json.loads(r['payload'])} for r in conn.execute('SELECT * FROM requests WHERE task_id=? ORDER BY created_at, id', (row['id'],))]
    from . import verdict
    try: runs = verdict.run_records(conn, row['id'])
    except (LedgerError, ValueError, KeyError): runs = []
    level = _level(state, engine_view, views)
    first_started = next((at for seq, kind, p, at in events if kind == 'node.started'), None)
    kind, reason, sources = _status(state, engine_view, attempts, progress, waits, requests, views, runs, level, first_started)
    last = events[-1] if events else None
    nodes = {}
    if engine_view is not None:
        for nid, r in engine_view['nodes'].items():
            nodes[nid] = {'generation': r.get('generation'), 'phase': r.get('phase'), 'state': r.get('state') or 'none', 'attempt': r.get('attempt'), 'child': r.get('child'),
                          'reason': clean(r.get('reason'), 200), 'classification': r.get('classification'),
                          'receipt': r.get('receipt'), 'verification_receipt': r.get('verification_receipt'), 'verification_result': r.get('verification_result'),
                          'continues': r.get('continues'), 'resume_artifact': r.get('resume_artifact'), 'retained_candidate': r.get('retained_candidate'),
                          'progress': progress.get(nid)}
    counts = {'total': len(nodes), 'pending': 0, 'running': 0, 'held': 0, 'produced': 0, 'verified': 0, 'accepted': 0}
    for r in nodes.values():
        if r['phase'] in counts: counts[r['phase']] += 1
        if r['state'] in counts: counts[r['state']] += 1
    item = {'id': row['id'], 'plan': state['name'], 'selector': row['request_key'], 'project': row['project_path'], 'project_id': row['project_id'],
            'goal': _goal(contract, payload), 'title': clean(payload.get('title'), 200), 'contract_revision': state['latest'],
            'root_status': state['status'],
            'status': {'kind': kind, 'label': WORDS[kind], 'reason': clean(reason, 600), 'source': sources},
            'level': {'kind': level, 'label': LEVEL_WORDS[level]},
            'elapsed': _elapsed(state, events, now),
            'last_update': {'seq': last[0], 'kind': last[1], 'at': last[3], 'summary': clean(_summary(last[1], last[2]), 200)} if last else None,
            'last_evidence': _last_evidence(events),
            'needs_user': _needs_user(state, requests, views, level, engine_view),
            'active': [{'attempt': a['id'], 'status': a['status'], 'since': a['created_at'], 'unit': a['unit'], 'stage': a['stage'],
                        'node': next((nid for nid, r in nodes.items() if r['attempt'] == a['id']), None)} for a in attempts if a['status'] in ('reserved', 'running', 'unknown')],
            'nodes_summary': counts,
            'tracking': {'adapter': 'engine' if engine_root else 'milestones',
                         'coverage': ('root sequential-engine: node / thế hệ / attempt / quan sát tiến độ' if engine_root
                                      else 'root không có engine: chỉ mốc và verdict, không có attempt hay quan sát tiến độ'),
                         'errors': [e for e in (contract_error and 'hợp đồng: ' + contract_error, engine_error and 'engine: ' + engine_error) if e]},
            'milestones': [{'id': v['id'], 'title': clean(v['title'], 120), 'state': v['state'], 'stale': bool(v.get('stale'))} for v in views],
            'capabilities': list(state.get('capabilities') or ()),
            'read_only': True}
    if not full: return item
    item['nodes'] = nodes
    item['attempts'] = attempts
    item['requests'] = [{'id': r['id'], 'revision': r['revision'], 'state': r['state'], 'created_at': r['created_at'], 'updated_at': r['updated_at'],
                         'question': clean((r['question'] or {}).get('question'), 300)} for r in requests]
    item['waits'] = [dict(w, reason=clean(w.get('reason'), 200)) for w in waits]
    item['notices'] = [{'seq': seq, 'at': at, 'category': p.get('category'), 'reason': clean(p.get('reason'), 300), 'user_action': clean(p.get('user_action'), 200),
                        'evidence': [clean(e, 120) for e in (p.get('evidence') or [])[:6]]} for seq, kind, p, at in events if kind == 'notice.exception']
    item['progress'] = progress
    current = {nid: r['generation'] for nid, r in nodes.items()}
    item['timeline'], item['timeline_total'], keys = _timeline(conn, row['id'], children, current, timeline_limit)
    for r in nodes.values():
        for key in (r['receipt'], r['verification_receipt'], r['resume_artifact'], r['retained_candidate']):
            if isinstance(key, str) and HEX64.fullmatch(key): keys.add(key)
    item['evidence_keys'] = sorted(keys)
    item['measure'] = _measure(rd, row['request_key']) if engine_root else {'note': 'root không có engine: không có attempt để đo'}
    item['eta'] = _eta(rd, row['request_key'], now)
    item['holds'] = _holds(rd, row['request_key'], conn) if engine_root else []
    return item


def _measure(rd, selector):
    try:
        from . import execution_mode
        m = execution_mode.measure(rd, selector)
        return {'attempts_wall_seconds': m.get('attempts_wall_seconds', UNKNOWN), 'wait_seconds': m.get('wait_seconds', UNKNOWN),
                'time_to_first_useful_action_seconds': m.get('time_to_first_useful_action_seconds', UNKNOWN),
                'rework': m.get('rework'), 'method': m.get('method'),
                'attempts': [{k: a.get(k) for k in ('attempt', 'node', 'generation', 'mode', 'execution_seconds', 'span_seconds', 'reserved_at', 'settled_at')} for a in m.get('attempts', [])],
                'waits': [dict(w, reasons=clean(w.get('reasons'), 200)) for w in m.get('waits', [])],
                'verification': m.get('verification')}
    except (LedgerError, OSError, ValueError, KeyError, TypeError) as error:
        return {'error': clean(str(error), 200), 'attempts_wall_seconds': UNKNOWN, 'wait_seconds': UNKNOWN}


def _eta(rd, selector, now):
    try:
        from . import estimates
        out = estimates.read(rd, selector, now=_iso(now))
    except (LedgerError, OSError, ValueError, KeyError, TypeError) as error:
        return {'remaining_seconds': None, 'label': 'chưa xác định', 'reason': 'không đọc được ước lượng: ' + clean(str(error), 160)}
    remaining = out.get('remaining_seconds')
    eta = {'remaining_seconds': remaining, 'execution_seconds': out.get('execution_seconds'), 'waiting_seconds': out.get('waiting_seconds'),
           'deadline': out.get('deadline'), 'wall_clock_remaining_seconds': out.get('wall_clock_remaining_seconds'),
           'deadline_passed': out.get('deadline_passed'), 'calibrated': False, 'reason': clean(out.get('remaining_reason'), 200),
           'last_change': clean((out.get('history') or [{}])[-1].get('reason'), 200) if out.get('history') else None}
    if remaining is None:
        eta['label'] = 'chưa xác định' + ('' if out.get('baseline') else ' (không có ước lượng ban đầu)')
    else:
        eta['label'] = f'công còn lại {_hms(remaining[0])}–{_hms(remaining[1])} (công, không phải thời gian lịch; chưa hiệu chỉnh)'
    return eta


def _holds(rd, selector, conn):
    try:
        from . import managed_executor
        return [{'node': h['node'], 'attempt': h['attempt'], 'findings': h['findings'], 'text': clean(h.get('text'), 300), 'requested': h.get('requested'), 'confirmed': h.get('confirmed')}
                for h in managed_executor.hold_views(rd, selector, conn)]
    except (LedgerError, OSError, ValueError, KeyError) as error:
        return [{'error': clean(str(error), 200)}]


# ---- what is NOT tracked ----------------------------------------------------------------------------------------------------------------

def _untracked(conn, rows, state_root, projects_seen, children=frozenset()):
    v1 = []
    for row in rows:
        if row['request_key'].startswith((namespaces.LEGACY, namespaces.NAMESPACED)) or row['id'] in children: continue
        last = conn.execute("SELECT payload FROM events WHERE task_id=? AND kind='workflow.checkpoint' ORDER BY seq DESC LIMIT 1", (row['id'],)).fetchone()
        phase = json.loads(last['payload']).get('phase') if last else None
        payload = json.loads(row['payload'])
        v1.append({'id': row['id'], 'project': row['project_path'], 'key': clean(row['request_key'], 100), 'title': clean(payload.get('title') or payload.get('goal'), 120),
                   'phase': clean(phase, 40) or 'chưa xác định', 'note': 'task ngoài plan (v1 hoặc task con): chỉ phase checkpoint, không node/attempt ở đây'})
    registry = []
    try:
        from . import where
        path = where.registry_file()
        for project, root in where._read_registry(path).items():
            if project.casefold() not in projects_seen:
                registry.append({'project': project, 'state_root': root, 'same_state_root': Path(root).resolve() == Path(state_root).resolve() if root else False,
                                 'note': 'project đã init (registry hook) nhưng không có plan trong sổ này: ' + NOT_TRACKED})
        registry_note = str(path)
    except (OSError, ValueError, TypeError):
        registry_note = 'registry hook không đọc được'
    sessions = []
    for project in sorted(projects_seen):
        path = Path(project) / '.onecrew' / 'hook-state.json'
        try:
            state = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            continue
        for session, mine in list(state.items())[-5:]:
            sessions.append({'project': project, 'session': clean(session, 40), 'stop_blocks': (mine or {}).get('stop_blocks'),
                             'note': 'phiên hook Claude Code mà OneCrew thấy qua hook; không phải task, ' + NOT_TRACKED + ' về tiến độ'})
    return {'statement': STATEMENT, 'other_tasks': v1, 'registry_projects_without_plan': registry, 'registry': registry_note, 'hook_sessions': sessions}


# ---- public -------------------------------------------------------------------------------------------------------------------------

def overview(state_root, *, project_id=None, now=None):
    """The list: every plan root of the state root (or of one project), grouped by project, with its sourced status; plus what is not tracked."""
    now = _now(now)
    reader, source = _source(state_root)
    result = {'kind': 'onecrew-tracking-overview', 'version': VERSION, 'generated_at': _iso(now), 'state_root': str(Path(state_root).resolve()),
              'read_only': True, 'controls': CONTROLS, 'source': source, 'projects': [], 'tasks_total': 0,
              'coverage': {'engine': 'root sequential-engine: node / thế hệ / attempt / quan sát tiến độ / chờ',
                           'milestones': 'root không engine: mốc và verdict', 'other': 'task ngoài plan: phase checkpoint v1',
                           'external': STATEMENT},
              'untracked': {'statement': STATEMENT, 'other_tasks': [], 'registry_projects_without_plan': [], 'hook_sessions': []}}
    if source['status'] != 'ok': return result
    try:
        with reader.transaction() as conn:
            if conn is None:
                source.update(status='missing', detail='sổ không mở được'); return result
            rows = _rows(conn, project_id)
            source['last_seq'] = conn.execute('SELECT COALESCE(MAX(seq),0) FROM events').fetchone()[0]
            source['schema_version'] = _schema_version(conn)
            projects, children = {}, set()
            for row in rows:
                if not row['request_key'].startswith((namespaces.LEGACY, namespaces.NAMESPACED)): continue
                children |= {r[0] for r in conn.execute("SELECT json_extract(payload,'$.child') FROM events WHERE task_id=? AND kind='node.started'", (row['id'],)) if r[0]}
                try:
                    item = _item(reader, conn, row, now)
                except (LedgerError, OSError, ValueError, KeyError, TypeError) as error:
                    item = {'id': row['id'], 'plan': clean(row['request_key'], 100), 'selector': row['request_key'], 'project': row['project_path'], 'project_id': row['project_id'],
                            'goal': None, 'root_status': UNKNOWN, 'status': {'kind': 'unknown', 'label': WORDS['unknown'], 'reason': 'không đọc được: ' + clean(str(error), 200), 'source': []},
                            'level': {'kind': 'none', 'label': LEVEL_WORDS['none']}, 'elapsed': {'seconds': UNKNOWN}, 'needs_user': [], 'active': [], 'last_update': None,
                            'last_evidence': None, 'nodes_summary': {}, 'tracking': {'adapter': UNKNOWN, 'coverage': 'lỗi đọc', 'errors': [clean(str(error), 200)]}, 'read_only': True}
                projects.setdefault(row['project_path'], []).append(item)
            result['projects'] = [{'path': path, 'tasks': items} for path, items in projects.items()]
            result['tasks_total'] = sum(len(p['tasks']) for p in result['projects'])
            result['untracked'] = _untracked(conn, rows, reader.state_root, {p.casefold() for p in projects}, children)
            try:
                source['ledger_mtime'] = dt.datetime.fromtimestamp(reader.path.stat().st_mtime, dt.timezone.utc).isoformat()
            except OSError:
                pass
    except (LedgerError, sqlite3.Error, OSError) as error:
        source.update(status='unreadable', detail=clean(str(error), 300))
    return result


def _find(conn, reader, selector, project_id):
    name, explicit = namespaces.parse(selector)
    keys = (explicit,) if explicit else (namespaces.LEGACY + name, namespaces.NAMESPACED + name)
    marks = ','.join('?' for _ in keys)
    sql = f'SELECT id, project_id, project_path, request_key, revision, payload, created_at FROM tasks WHERE request_key IN ({marks})'
    args = list(keys)
    if project_id: sql += ' AND project_id=?'; args.append(project_id)
    rows = [dict(r) for r in conn.execute(sql, args)]
    if not rows: raise LedgerError(f'Không có plan {selector} trong sổ này' + (' cho project này' if project_id else '') + '.')
    if len(rows) > 1: raise LedgerError(f'Plan {selector} có ở {len(rows)} project: chọn --project-id ' + ', '.join(r['project_id'][:12] for r in rows))
    return rows[0]


def detail(state_root, selector, *, project_id=None, now=None, timeline_limit=200):
    """One root in full: nodes, attempts, requests, waits, notices, measured spans (union), ETA or unknown, holds, timeline, evidence keys."""
    now = _now(now)
    reader, source = _source(state_root)
    if source['status'] != 'ok': raise LedgerError(source['detail'])
    with reader.transaction() as conn:
        if conn is None: raise LedgerError('Sổ không mở được.')
        row = _find(conn, reader, selector, project_id)
        item = _item(reader, conn, row, now, full=True, timeline_limit=timeline_limit)
        item.update(kind='onecrew-tracking-detail', version=VERSION, generated_at=_iso(now), state_root=str(reader.state_root), controls=CONTROLS,
                    source=dict(source, last_seq=conn.execute('SELECT COALESCE(MAX(seq),0) FROM events').fetchone()[0]))
        return item


def evidence(state_root, selector, key, *, project_id=None):
    """The text of one blob the root's events name (receipt, candidate, evidence), redacted line by line and capped; any other key is refused."""
    if not isinstance(key, str) or not HEX64.fullmatch(key): raise LedgerError('Mã bằng chứng không hợp lệ.')
    item = detail(state_root, selector, project_id=project_id, timeline_limit=5000)
    if key not in item['evidence_keys']: raise PermissionError('Bằng chứng này không thuộc root đã chọn; không mở.')
    from ..snapshots import Snapshots
    from .diagnostics import redact
    data = Snapshots(state_root).read_blob(key)
    truncated = len(data) > EVIDENCE_CAP
    text = data[:EVIDENCE_CAP].decode('utf-8', 'replace')
    try:
        text = json.dumps(json.loads(data.decode('utf-8')), ensure_ascii=False, indent=1, sort_keys=True)
        truncated = len(text) > EVIDENCE_CAP; text = text[:EVIDENCE_CAP]
    except (ValueError, UnicodeDecodeError):
        pass
    clean_text, redaction = redact(text)
    return {'key': key, 'bytes': len(data), 'truncated': truncated, 'text': clean_text, 'redaction': redaction, 'read_only': True}


# ---- plain text (the `track list` / `track show` lines) -----------------------------------------------------------------------------

def _hms(seconds):
    if not isinstance(seconds, (int, float)): return 'chưa xác định'
    s = int(round(seconds))
    return f'{s // 3600}h{(s % 3600) // 60:02d}m' if s >= 3600 else (f'{s // 60}m{s % 60:02d}s' if s >= 60 else f'{s}s')


def render_overview(value):
    src = value['source']
    lines = [f"THEO DÕI (chỉ đọc) — sổ {value['state_root']} — lúc {value['generated_at']} — nguồn: {src['status']}" + (f" ({src['detail']})" if src.get('detail') else '')]
    if not value['projects']: lines.append('Không có plan nào trong phạm vi này.')
    for project in value['projects']:
        lines += ['', project['path']]
        for t in project['tasks']:
            lines.append(f"  [{t['status']['label']}] {t['plan']} ({t['id'][:12]}) · {t['level']['label']} · đã chạy {_hms(t['elapsed'].get('seconds'))} · {t['tracking']['adapter']}")
            if t.get('goal'): lines.append('    mục tiêu: ' + t['goal'][:160])
            lines.append('    vì: ' + (t['status']['reason'] or '') + ' [' + ', '.join(t['status']['source']) + ']')
            if t.get('last_update'): lines.append(f"    cập nhật cuối: {t['last_update']['at']} #{t['last_update']['seq']} {t['last_update']['summary']}")
            if t.get('last_evidence'): lines.append(f"    bằng chứng cuối: {t['last_evidence']['at']} {t['last_evidence']['label']} ({t['last_evidence']['provenance']})")
            for n in t['needs_user']: lines.append('    CẦN BẠN: ' + (n.get('question') or n['kind']) + (f"  → {n['reply_command']}" if n.get('reply_command') else ''))
    u = value['untracked']
    lines += ['', 'Chưa được theo dõi: ' + u['statement']]
    for o in u['other_tasks'][:10]: lines.append(f"  - task {o['id'][:12]} ({o['key']}) phase {o['phase']}: {o['note']}")
    for r in u['registry_projects_without_plan'][:10]: lines.append(f"  - {r['project']}: {r['note']}")
    for s in u['hook_sessions'][:10]: lines.append(f"  - phiên hook {s['session']} @ {s['project']}: {s['note']}")
    lines.append('Điều khiển: ' + value['controls'])
    return '\n'.join(lines) + '\n'


def render_detail(value):
    t = value
    lines = [f"PLAN {t['plan']} ({t['id']}) — {t['project']} — lúc {t['generated_at']} (chỉ đọc)",
             f"Trạng thái: {t['status']['label']} — {t['status']['reason']} [{', '.join(t['status']['source'])}]",
             f"Mức đầu ra: {t['level']['label']} · root: {t['root_status']} · đã chạy: {_hms(t['elapsed'].get('seconds'))} ({t['elapsed'].get('basis')})",
             f"ETA: {t['eta'].get('label')}" + (f" — {t['eta']['reason']}" if t['eta'].get('reason') else ''),
             f"Thời gian attempt (union): {_hms(t['measure'].get('attempts_wall_seconds'))} · chờ (union): {_hms(t['measure'].get('wait_seconds'))}"]
    if t.get('goal'): lines.append('Mục tiêu: ' + t['goal'])
    for n in t['needs_user']: lines.append('CẦN BẠN: ' + (n.get('question') or n['kind']) + (f"  → {n['reply_command']}" if n.get('reply_command') else ''))
    if t['nodes']:
        lines.append('Node:')
        for nid, r in t['nodes'].items():
            p = r.get('progress')
            lines.append(f"  - {nid} thế hệ {r['generation']} · {r['phase']} · {LEVEL_WORDS.get(r['state'], r['state'])}" + (f" · attempt {r['attempt']}" if r['attempt'] else '')
                         + (f" · giữ: {r['reason']}" if r['phase'] == 'held' else '') + (f" · quan sát: {p['status']} {p['observed_at'] or p['received_at']}" if p else ''))
    if t['attempts']:
        lines.append('Attempt:')
        for a in t['attempts']: lines.append(f"  - {a['id']} [{a['status']}] thế hệ {a['generation']} · {a['unit']} · {a['created_at']} → {a['updated_at']}")
    if t['waits']:
        lines.append('Đang chờ:')
        for w in t['waits']: lines.append(f"  - từ {w['since']}: {w.get('reason')} ({w['source']})")
    if t['holds']:
        lines.append('Giữ (finding):')
        for h in t['holds']: lines.append('  - ' + (h.get('text') or h.get('error') or ''))
    lines.append(f"Timeline ({len(t['timeline'])}/{t['timeline_total']} sự kiện, cũ → mới):")
    for e in t['timeline']:
        when = e['at'] + (f" (quan sát {e['observed_at']})" if e.get('observed_at') and e['observed_at'] != e['at'] else '')
        lines.append(f"  #{e['seq']} {when} {e['kind']}: {e['summary']}" + ('  [thế hệ cũ]' if e['stale_generation'] else ''))
    lines.append(f"Bằng chứng mở được: {len(t['evidence_keys'])} blob · Điều khiển: {t['controls']}")
    return '\n'.join(lines) + '\n'
