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

Evidence provenance (R1 of the dev11 release review): blobs are content-addressed, so one key can be the output of two generations with
identical bytes, an inheritance AND a new output of the same node, or an evidence item of several events. The model therefore never maps a
key to one entry: `evidence_index` holds one entry per OCCURRENCE (event seq, key) with that event's own kind, time, node, generation,
attempt and role (where the key sits in the payload), built from the FULL history of the root and its child tasks — the events the Gantt
already reads — and never from the timeline display window; the evidence door checks membership against that same full history.

Secrets: every display string is built with `clean` (the S1 line redaction of diagnostics.redact_line, control characters dropped, length
capped), and on top of that ONE outbound guard, `outward`, walks everything the public functions return (overview, detail, evidence, the text
renders; tracking_web and tracking_cli send nothing else) and applies diagnostics.redact_line to every string value and key, line by line, with
no length cap: a string in which nothing is withheld comes out byte-identical (ids, paths, 64-hex keys, reply templates stay usable), a string
that matches a known secret shape comes out with that part `[withheld]` (R3 of 03/11: a field projected raw, such as an observation's basis
ref, can never carry a secret past the boundary, whichever field a later change adds). It is idempotent and memoised per short string, so the
1-2 s poll stays cheap. The ledger itself is never changed. Environments, prompts and transcripts are never read.

Scope: a project scope (`project_id`, the ledger's own identity = digest of the normcase'd resolved project path) applies to the WHOLE
returned model — tasks, untracked v1 tasks, hook sessions AND the registry list — so a project-only view never names another project's
path, state root or id (R2 of 03/11). Registry paths are compared with the scope, and with the projects that have a plan, by that identity,
never by string or prefix. All-projects mode lists every registry project without a plan.
"""
import datetime as dt
import functools
import json
import os
import re
import sqlite3
from pathlib import Path

from ..ledger import LedgerError, utcnow
from ..specs import digest
from . import namespaces, plan as plans, report

VERSION = 1
UNKNOWN = 'unknown'
KINDS = ('running', 'waiting', 'blocked', 'done', 'unknown')
WORDS = {'running': 'đang thực hiện', 'waiting': 'đang chờ', 'blocked': 'bị chặn', 'done': 'hoàn tất', 'unknown': 'chưa xác định'}
LEVELS = ('none', 'produced', 'verified', 'accepted')
LEVEL_WORDS = {'none': 'chưa có đầu ra', 'produced': 'đã tạo đầu ra', 'verified': 'đã kiểm', 'accepted': 'đã nghiệm thu'}
# UX-05: a "done" root is one of three different things, and the word (and the colour the page gives it) says which
OUTCOME_WORDS = {'accepted': 'đã nghiệm thu', 'verified': 'đã kiểm, chờ nghiệm thu', 'closed': 'đã đóng'}
ELAPSED_LABEL = 'từ khi duyệt (thời gian lịch, gồm cả chờ)'
NOISE = ('learning.outcome', 'control.intervention', 'context.entry', 'learning.incident', 'learning.lesson')
NOT_TRACKED = 'chưa được theo dõi'
STATEMENT = ('Phiên Claude/Codex không chạy qua OneCrew không có nguồn trong sổ này: ' + NOT_TRACKED +
             '. Màn hình này không biến một phiên chat thành task được theo dõi; chỉ root/node/attempt có trong sổ mới xuất hiện.')
CONTROLS = 'không có: màn hình này không duyệt, không trả lời, không tạm dừng, không tiếp tục task; đọc hay mở bằng chứng không phải là duyệt.'
LIMIT = 300
HEX64 = re.compile(r'\b[0-9a-f]{64}\b')
EVIDENCE_CAP = 65536
OUTPUT_KINDS = ('node.produced', 'node.verification', 'attempt.settled')    # an occurrence in one of these events is an output of its attempt
RECORD_FIELDS = (('receipt', 'receipt đầu ra'), ('verification_receipt', 'receipt kiểm'), ('resume_artifact', 'đầu ra dở được tiếp tục'),
                 ('retained_candidate', 'ứng viên được giữ lại'))
EVIDENCE_BASIS = ('toàn bộ sự kiện của root và các task con, không phụ thuộc giới hạn timeline: mỗi lần một sự kiện nêu một blob là một mục '
                  '(seq, key) với loại, thời điểm, phần việc, thế hệ, attempt và vai trò của chính sự kiện đó; cùng nội dung (cùng key) không gộp các lần nêu. '
                  'Chỉ khóa có trong kho là bằng chứng: blob (snapshots/blobs) hoặc ảnh chụp (snapshots/manifests: đầu ra, đầu ra kế thừa, ứng viên giữ lại, '
                  'ảnh chụp đầu vào của engine); mã định danh 64-hex khác (project_id, revision, sha của plan…) không được đếm, liệt kê hay mở; '
                  'sự kiện estimate.* không phải lần dùng bằng chứng (nền của ước lượng); một khóa ở trường đầu ra của sự kiện engine mà không còn '
                  'trong kho vẫn được liệt kê, đánh dấu stored: null / blob: false, không mở được')
NOT_EVIDENCE = ('estimate.',)   # event kinds whose keys are bookkeeping (the basis an estimate was computed from), not evidence uses
BLOB_FIELDS = ('artifact', 'receipt', 'resume_artifact', 'verification_receipt', 'precondition_receipt')   # engine fields that hold a blob key


# ---- text and time ------------------------------------------------------------------------------------------------------------------

def clean(value, limit=LIMIT):
    """One line of text safe to show: the secret parts withheld (diagnostics.redact_line), control characters dropped, at most `limit` chars
    (None: no cap — for references and ids, which must never be cut)."""
    if value is None: return None
    from .diagnostics import redact_line
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    text = ''.join(c if c.isprintable() or c == ' ' else ' ' for c in text.replace('\n', ' '))
    text, _ = redact_line(text)
    if limit is None: return text
    return text[:limit] + ('…' if len(text) > limit else '')


GUARD_CACHED = 2048          # strings up to this length are memoised (ids, times, kinds, labels repeat on every poll); longer ones are not kept


def _guard_line(line):
    from .diagnostics import redact_line
    out, hidden = redact_line(line)
    return out if hidden else line


_guard_line_cached = functools.lru_cache(maxsize=65536)(_guard_line)


def _guard(text):
    """One outward string: each line through diagnostics.redact_line; unchanged (byte for byte) unless a known secret shape was withheld."""
    if '\n' in text: return '\n'.join(_guard(line) for line in text.split('\n'))
    return _guard_line_cached(text) if len(text) <= GUARD_CACHED else _guard_line(text)


def outward(value):
    """The outbound guard (R3): `value` (a model dict, list or string) with every string value and key passed through `_guard`, no length cap.
    Applied at the boundary of overview / detail / evidence / the renders; idempotent, so a second pass (tracking_web, tracking_cli) changes nothing."""
    if isinstance(value, str): return _guard(value)
    if isinstance(value, dict): return {(_guard(k) if isinstance(k, str) else k): outward(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)): return [outward(v) for v in value]
    return value


def project_identity(path):
    """The ledger's identity of a project path (Ledger.project_id = digest of the normcase'd resolved path), or None when it cannot be resolved."""
    try:
        return digest(os.path.normcase(str(Path(path).resolve())))
    except (OSError, ValueError, TypeError, RuntimeError):
        return None


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
    """Latest executor.observed progress checkpoint per (node, attempt), from the root's events: every attempt keeps its own last observation."""
    latest = {}
    for seq, kind, p, at in events:
        if kind == 'executor.observed' and p.get('what') == 'progress' and p.get('node'):
            cp = p.get('checkpoint') or {}
            latest.setdefault(p['node'], {})[p.get('attempt')] = {
                'seq': seq, 'attempt': p.get('attempt'), 'status': clean(cp.get('status', UNKNOWN), 40), 'reason': clean(cp.get('reason')),
                'observed_at': p.get('observed_at'), 'received_at': p.get('received_at') or at, 'time_source': clean(p.get('time_source'), 60),
                'kind': clean((p.get('observation') or {}).get('kind'), 60), 'elapsed_seconds': (p.get('observation') or {}).get('elapsed_seconds'),
                'command_cap_seconds': p.get('command_cap_seconds')}
    return latest


def _current_progress(rows, engine_view):
    """The progress row of each node's CURRENT attempt (the one engine.state binds to the node), and nothing else: an observation of an
    older attempt, however late it is written, never speaks for the attempt that runs now (P2-02). It stays readable in the timeline, marked
    `stale_attempt`. Without an engine view there is no current attempt, so nothing is current."""
    if engine_view is None: return {}
    out = {}
    for nid, r in engine_view['nodes'].items():
        row = (rows.get(nid) or {}).get(r.get('attempt')) if r.get('attempt') else None
        if row: out[nid] = row
    return out


def _waits(events, attempts):
    """Every wait of the root, reconciled the way executors.summary does, each with `open` (current) or not (history, P2-03):
    an executor wait is ONE row per (attempt, basis ref); any record of that wait carrying `until` closes it, whatever order the records
    were written in, so a duplicate or late start never reopens a closed wait; an open wait of an attempt that is no longer active has an
    unknown end and is not current either. A recorded mode wait ends at that node's next non-wait record."""
    active = {a['id'] for a in attempts if a['status'] in ('reserved', 'running', 'unknown')}
    rows, order = {}, []
    for seq, kind, p, at in events:
        if kind == 'executor.observed' and p.get('what') == 'wait':
            wait = p.get('wait') or {}
            key = ('executor', p.get('attempt'), (p.get('basis') or {}).get('ref'))
            if key not in rows:
                rows[key] = {'seq': seq, 'ref': clean(key[2], None), 'reason': clean(wait.get('reason'), 200), 'since': p.get('observed_at') or at, 'attempt': p.get('attempt'),
                             'node': None, 'source': 'executor.observed', 'until': None, 'end_seq': None, 'open': True}
                order.append(key)
            if wait.get('until') and rows[key]['until'] is None:
                rows[key].update(until=wait['until'], end_seq=seq, open=False)
        elif kind == 'workflow.mode' and p.get('mode') == 'wait' and not p.get('corrects'):
            key = ('mode', seq)
            rows[key] = {'seq': seq, 'ref': None, 'reason': clean(p.get('mode_reasons') or p.get('reasons')), 'since': at, 'attempt': None, 'node': p.get('node'),
                         'source': 'workflow.mode', 'until': None, 'end_seq': None, 'open': True}
            order.append(key)
    for key in order:
        w = rows[key]
        if w['source'] == 'workflow.mode':
            for seq, kind, p, at in events:
                if seq > w['seq'] and kind in ('workflow.mode', 'node.started') and p.get('node') == w.get('node') and not (kind == 'workflow.mode' and p.get('mode') == 'wait'):
                    w.update(until=at, end_seq=seq, open=False); break
        elif w['open'] and w['attempt'] not in active:
            w.update(until=UNKNOWN, open=False)
    return [rows[k] for k in order]


REFERENCE_PLACEHOLDER = '<lý do hoặc bằng chứng của bạn>'
REPLY_SHELL = 'PowerShell'


def _quote(value):
    """One PowerShell argument (the supported shell for the templates: the owner's scripts are .ps1): single-quoted, so `$`, backticks, `&`,
    `(`, spaces and `'` (doubled) inside a path are passed through unchanged; double quotes would let `$SDK` be interpolated (P2-B)."""
    return "'" + str(value).replace("'", "''") + "'"


def _runtime():
    """How the command names THIS runtime: the venv's onecrew.exe next to the interpreter when it exists (`& '<exe>'`), else plain `onecrew`."""
    import sys
    exe = Path(sys.executable).parent / ('onecrew.exe' if sys.platform == 'win32' else 'onecrew')
    return '& ' + _quote(exe) if exe.is_file() else '& ' + _quote(sys.executable) + ' -I -X utf8 -m onecrew.console'


def _action(template, expected, placeholders=(), note=None):
    return {'schema_version': 1, 'enabled': bool(template), 'template': template, 'shell': REPLY_SHELL,
            'placeholders': list(placeholders), 'expected': expected, 'note': note}


def _needs_user(state, requests, views, level, engine_view, project=None, state_root=None, contract=None):
    needs = []
    prefix = _runtime() + (f' --project {_quote(project)}' if project else '') + (f' --state-root {_quote(state_root)}' if state_root else '')
    complete = bool(project and state_root)
    selector = state.get('selector') or state.get('anchor')
    for r in requests:
        if r['state'] != 'pending': continue
        q = r['question'] or {}
        # P2-B (03/11): the command the owner runs must be complete for the wheel's parser: project, state root, request, revision, choice AND the
        # mandatory --reference. The reference is the owner's own words: a marked placeholder, so this is a TEMPLATE to complete, never "ready to run".
        command = f"{prefix} question answer {r['id']} --revision {r['revision']} --choice "
        suffix = f' --reference {_quote(REFERENCE_PLACEHOLDER)}'
        human = f"{prefix} owner answer {_quote(r['id'])} --revision {_quote(r['revision'])} --choice "
        expected = {'task': state.get('task_id'), 'request': r['id'], 'revision': r['revision']}
        options = []
        for option in (q.get('options') or [])[:6]:
            template = human + _quote(option.get('id')) + suffix + ' --human' if complete else None
            options.append({'id': clean(option.get('id'), 60), 'label': clean(option.get('label'), 200),
                            'reply_command': command + clean(option.get('id'), 60) + suffix,
                            'human_command': template, 'action': _action(template, dict(expected, choice=option.get('id')), ['reference'])})
        needs.append({'kind': 'request', 'id': r['id'], 'revision': r['revision'], 'question': clean(q.get('question')),
                      'reason': clean(q.get('reason'), 300), 'impact': clean(q.get('impact'), 300), 'recommendation': clean(q.get('recommendation'), 60),
                      'options': options,          # UX-03: one template per option; the page copies, never runs
                      'reply_command': command + '<option-id>' + suffix,
                      'human_command': human + _quote('<option-id>') + suffix + ' --human' if complete else None,
                      'placeholders': ['reference'], 'reference_placeholder': REFERENCE_PLACEHOLDER, 'reply_shell': REPLY_SHELL,
                      'reply_note': 'mẫu lệnh cho ' + REPLY_SHELL + ' (nháy đơn giữ nguyên $, khoảng trắng, dấu nháy trong đường dẫn): thay ' + REFERENCE_PLACEHOLDER
                                    + ' bằng lý do/bằng chứng của bạn (tối đa 500 ký tự) rồi chạy trong PowerShell của bạn; quyền chủ sở hữu, bản (revision) và các guard hiện có vẫn áp dụng; trang này không chạy lệnh',
                      'note': 'đọc, đóng cửa sổ hay bỏ qua không phải là trả lời; request vẫn chờ', 'source': ['request:' + r['id']]})
    if state['status'] == 'proposed':
        revision = state['latest']; written = state['revisions'].get(revision) or {}
        choices = ((contract or {}).get('options') or {}).get('items') or []
        optional = [i for i in (contract or {}).get('items', []) if i.get('tier') == 'should']
        placeholders = ['reference'] + (['option-id'] if choices else [])
        template = (f'{prefix} owner approve {_quote(selector)} --revision {revision}'
                    + (f' --choose {_quote("<option-id>")}' if choices else '')
                    + f' --reference {_quote(REFERENCE_PLACEHOLDER)} --human') if complete and selector and contract else None
        needs.append({'kind': 'approve', 'question': f"Duyệt bản {state['latest']} của plan {state['name']} (plan approve, lệnh của chủ sở hữu)",
                      'id': state.get('task_id'), 'revision': revision, 'title': clean((contract or {}).get('title')),
                      'reason': clean(written.get('reason')), 'impact': clean((written.get('acceptance_diff') or {}).get('summary')),
                      'reply_command': template, 'human_command': template, 'reply_shell': REPLY_SHELL,
                      'reference_placeholder': REFERENCE_PLACEHOLDER, 'placeholders': placeholders,
                      'plan_choices': [{'id': o.get('id'), 'title': clean(o.get('title')), 'summary': clean(o.get('summary'))} for o in choices],
                      'optional_items': [{'id': i['id'], 'title': clean(i.get('title')), 'selected': False} for i in optional],
                      'action': _action(template, {'task': state.get('task_id'), 'selector': selector, 'revision': revision}, placeholders),
                      'reply_note': 'Điền --reference của bạn' + (' và --choose từ danh sách phương án' if choices else '')
                                    + '; mục should chỉ chạy nếu bạn chủ động thêm --tick ID. Không tự chọn mục phụ; duyệt không có nghĩa worker đã chạy.',
                      'source': [f"plan.{'amended' if state['latest'] > 1 else 'proposed'}:rev{state['latest']}"]})
    elif state['status'] == 'stopped_with_report':
        stopped = state['stopped'].get(state['latest']) or {}
        needs.append({'kind': 'stopped', 'question': 'Đọc báo cáo dừng ở mốc ' + clean(stopped.get('milestone'), 50) + ' và quyết định (tiếp tục / amend / dừng)',
                      'source': [f"milestone.stopped:rev{state['latest']}"]})
    elif state['status'] == 'approved' and level == 'verified':
        if engine_view is not None or (views and all(v['state'] == 'passed' for v in views)):
            revision = (state.get('approved') or {}).get('revision')
            artifacts = [(v.get('last_verdict') or {}).get('artifact_sha') for v in views]
            artifact = artifacts[0] if artifacts and len(set(artifacts)) == 1 and isinstance(artifacts[0], str) and re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}', artifacts[0]) else None
            if engine_view is not None or any(v.get('stale') or v.get('state') != 'passed' for v in views): artifact = None
            template = (f'{prefix} owner accept {_quote(selector)} --revision {revision} --artifact-sha {_quote(artifact)}'
                        + f' --reference {_quote(REFERENCE_PLACEHOLDER)} --human') if complete and selector and revision and artifact else None
            why = None if template else 'Chưa tạo lệnh nghiệm thu: nguồn hiện có chưa có một artifact bàn giao chung đã kiểm hợp lệ; không lấy snapshot node thay artifact được bàn giao. Đọc báo cáo ghim revision và đối chiếu bằng chứng trước.'
            needs.append({'kind': 'accept', 'question': 'Mọi mốc đã có verdict đạt: nghiệm thu (plan accept, lệnh của chủ sở hữu) hoặc nêu điều chưa đạt',
                          'id': state.get('task_id'), 'revision': revision, 'artifact_sha': artifact,
                          'reply_command': template, 'human_command': template, 'reply_shell': REPLY_SHELL,
                          'reference_placeholder': REFERENCE_PLACEHOLDER, 'placeholders': ['reference'] if template else [],
                          'reply_note': 'Điền --reference của bạn; CLI kiểm lại revision và artifact trong giao dịch nghiệm thu, không duyệt từ thao tác sao chép.' if template else why,
                          'binding_reason': why,
                          'inspect_command': f'{prefix} plan report {_quote(selector)} --revision {state["approved"]["revision"]}' if complete and selector and state.get('approved') else None,
                          'action': _action(template, {'task': state.get('task_id'), 'selector': selector,
                                                       'revision': revision, 'artifact_sha': artifact}, ['reference'] if template else [], note=why),
                          'source': ['milestone.passed' if views else 'node.verification:pass']})
    return needs


def _level(state, engine_view, views):
    """The output level is evidence: plan.accepted is the owner's acceptance; plan.closed is NOT (P2-01), the nodes' states still say
    what was produced, verified or accepted before the plan was closed."""
    if state['status'] == 'accepted': return 'accepted'
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
    if state['status'] == 'accepted':
        return 'done', 'đã nghiệm thu', ['plan.accepted']
    if state['status'] == 'closed':
        return 'done', f"chủ sở hữu đã đóng plan (đóng không phải nghiệm thu; đầu ra: {LEVEL_WORDS[level]})", ['plan.closed']
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
        waiting = [w for w in waits if w['source'] == 'executor.observed' and w.get('attempt') in {a['id'] for a in active}]
        if waiting:         # the running attempt's own executor reported an open wait: it is waiting, with the reason the executor gave
            return 'waiting', 'attempt đang chạy nhưng đang chờ: ' + '; '.join(f"{clean(w.get('reason'), 120) or 'không rõ lý do'} (attempt {w['attempt']}, từ {w['since']})" for w in waiting), \
                [f"executor.observed:{w['seq']}" for w in waiting]
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
    if pending:                                      # the full ids are the sources; the sentence stays readable when many questions wait (UX round 2)
        named = ', '.join(r['id'] for r in pending) if len(pending) <= 2 else f"{len(pending)} câu hỏi ({', '.join(r['id'][:12] + '…' for r in pending[:3])}{', …' if len(pending) > 3 else ''})"
        return 'waiting', 'chờ chủ sở hữu trả lời ' + named, ['request:' + r['id'] for r in pending]
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
        return {'since': None, 'seconds': UNKNOWN, 'label': ELAPSED_LABEL, 'basis': 'chưa duyệt: thời gian đã chạy đo từ lúc duyệt'}
    end = None
    for seq, kind, p, at in events:
        if kind in ('plan.accepted', 'plan.closed'): end = _at(p.get('at') or at)
    stop = end or now
    return {'since': _iso(start), 'until': _iso(end), 'seconds': _seconds(start, stop), 'label': ELAPSED_LABEL,
            'basis': 'plan.approved → ' + ('plan.accepted/closed' if end else 'bây giờ') + ' (thời gian lịch, gồm cả chờ)'}


def _outcome(state, kind, level):
    """UX-05: which "done" this is — accepted by the owner, verified and waiting for acceptance, or closed (an end, not an acceptance)."""
    if state['status'] == 'accepted': return 'accepted'
    if state['status'] == 'closed': return 'closed'
    if kind == 'done' and level == 'verified': return 'verified'
    return None


def _current_step(kind, state, engine_view, active, requests, nodes_progress):
    """One short line for the list: what the task is at right now (never a guess: each branch names the source it rests on)."""
    if state['status'] == 'accepted': return 'kết thúc: đã nghiệm thu'
    if state['status'] == 'closed': return 'kết thúc: plan đã đóng'
    pending_count = sum(1 for r in requests if r['state'] == 'pending')
    if pending_count > 1: return f'chờ bạn trả lời {pending_count} câu hỏi'
    if state['status'] == 'proposed': return f"chờ bạn duyệt bản {state['latest']}"
    if state['status'] == 'stopped_with_report': return 'dừng có báo cáo: chờ bạn quyết định'
    pending = [r['id'] for r in requests if r['state'] == 'pending']
    if pending: return 'chờ bạn trả lời câu hỏi ' + ', '.join(pending)
    if active:
        parts = []
        for a in active:
            p = nodes_progress.get(a.get('node')) if a.get('node') else None
            parts.append(f"phần việc {a['node']}" if a.get('node') else f"attempt {a['attempt'][:12]}")
            if p: parts[-1] += f" ({p['status']})"
        return ('đang chạy ' if kind != 'blocked' else 'bị chặn ở ') + ', '.join(parts)
    if engine_view is not None:
        held = [n for n, r in engine_view['nodes'].items() if r.get('phase') == 'held']
        if held: return 'bị giữ: ' + ', '.join(held)
        produced = [n for n, r in engine_view['nodes'].items() if r.get('state') == 'produced']
        if produced: return 'chờ kiểm phần việc ' + ', '.join(produced)
        pending_nodes = [n for n, r in engine_view['nodes'].items() if r.get('phase') == 'pending']
        if kind == 'done': return 'mọi phần việc đã kiểm: chờ bạn nghiệm thu'
        if pending_nodes: return 'chưa bắt đầu phần việc ' + ', '.join(pending_nodes)
    return None


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
        item = {'seq': seq, 'kind': kind, 'at': when, 'received_at': at, 'label': label, 'ref': ref,
                'provenance': p.get('time_source') or 'ledger_event'}
        if best is None or (_at(when) or _at(at)) >= (_at(best['at']) or _at(best['received_at'])): best = item
    if best: best.update(label=clean(best['label'], 120), ref=clean(best['ref'], 200))       # only the chosen entry leaves this module
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
    if kind in ('request.created', 'request.revised'): return f"câu hỏi {p.get('id')} bản {str(p.get('revision') or '')[:12]}…: {(p.get('question') or {}).get('question') if isinstance(p.get('question'), dict) else p.get('question') or ''}"
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


def _walk(value, path=''):
    """(key, role) of every 64-hex blob key a payload names, in payload order. The role is where the key sits: `artifact`, `receipt`,
    `resume_artifact`, `candidate.artifact`, `evidence[2]`, `basis.ref` … (a key used as a dict key is `<path>.{key}`)."""
    if isinstance(value, dict):
        for k, v in value.items():
            for key in HEX64.findall(str(k)): yield key, (path + '.' if path else '') + '{key}'
            yield from _walk(v, (path + '.' if path else '') + str(k))
    elif isinstance(value, list):
        for i, v in enumerate(value): yield from _walk(v, f'{path}[{i}]')
    elif isinstance(value, str) or (isinstance(value, (int, float)) and not isinstance(value, bool)):
        for key in HEX64.findall(str(value)): yield key, path or 'payload'


def _keys_of(payload):
    return {key for key, _ in _walk(payload)}


def _history(conn, root_id, events=None):
    """(root events, child task ids, root + child events by seq): the full non-noise history of a root, the one source of the Gantt and of
    the evidence provenance (never the timeline display window)."""
    if events is None: events = [e for e in _events(conn, root_id) if e[1] not in NOISE]
    children = {p.get('child') for seq, kind, p, at in events if kind == 'node.started' and p.get('child')}
    child_events = [e for child in sorted(children) for e in _events(conn, child) if e[1] not in NOISE]     # attempt.* events live on the child task
    return events, children, sorted(events + child_events, key=lambda e: e[0])


def _provenance(events, attempts, nodes, current_generation, current_attempt):
    """(occurrences, keys): one entry per (event seq, key) over the full history `events`, each with ITS event's kind, time (observed_at, else
    the ledger time), node (the event's, else the node its attempt was started for), generation (the event's, else its attempt's), attempt
    (the event's; for a node event that names none, the attempt node.started bound to that node and generation before it, with that
    node.started as `attempt_basis`; else null: not determined) and role. Engine node-record keys (receipt, verification_receipt,
    resume_artifact, retained_candidate) are added as `engine.state` entries only when no event names that key for that node (and, for
    the receipts, that generation).

    Generation = NODE generation. A payload `generation` counts only next to its `node`: attempt.reserved/launched carry the attempt's
    CONTROL generation (the task's attempt counter, 1 on every child task) and the attempts table holds that same counter, so an event
    without a node takes the generation of the node.started that bound its attempt (`generation_basis` 'node.started:#seq'); only an
    attempt no node.started binds falls back to the attempts-table counter, the value its Gantt row shows (`generation_basis`
    'attempts.counter'); else null."""
    attempt_counter = {a['id']: a['generation'] for a in attempts}
    started, attempt_node, bound = {}, {}, {}
    for seq, kind, p, at in events:
        if kind == 'node.started' and p.get('attempt') and p.get('node') is not None:
            started.setdefault((p['node'], p.get('generation')), []).append((seq, p['attempt']))
            attempt_node[p['attempt']] = p['node']
            bound[p['attempt']] = (p['node'], p.get('generation'), seq)
    out, keys, cleaned = [], set(), {}
    def once(text, limit):                       # observations repeat their summary and every payload repeats its paths: clean each text once
        if (text, limit) not in cleaned: cleaned[(text, limit)] = clean(text, limit)
        return cleaned[(text, limit)]
    for seq, kind, p, at in events:
        found = {}
        for key, role in _walk(p): found.setdefault(key, []).append(role)
        if not found: continue
        keys |= set(found)
        node = p.get('node')
        gen = p.get('generation') if node is not None else None          # never the control generation of attempt.reserved/launched
        gbasis = 'event' if gen is not None else None
        attempt = p.get('attempt') or (p.get('id') if kind.startswith('attempt.') else None)
        basis = 'event' if attempt else None
        if attempt is None and node is not None:
            prior = [(s, a) for s, a in started.get((node, gen), []) if s <= seq]
            if prior: attempt, basis = prior[-1][1], f'node.started:#{prior[-1][0]}'
        owner = node if node is not None else attempt_node.get(attempt)
        if gen is None and attempt:
            gen, gbasis = _attempt_generation(attempt, node, bound, attempt_counter)
        stale = (p.get('node') is not None and p.get('generation') is not None and node in current_generation and p.get('generation') != current_generation[node]) \
            or (owner is not None and attempt is not None and owner in current_attempt and attempt != current_attempt[owner])
        label, when = once(_summary(kind, p), 160), p.get('observed_at') or at
        for key, roles in found.items():
            entry = {'key': key, 'seq': seq, 'kind': kind, 'role': once(roles[0], 80), 'at': when, 'node': owner, 'generation': gen, 'attempt': attempt,
                     'attempt_basis': basis, 'generation_basis': gbasis, 'label': label, 'output': kind in OUTPUT_KINDS, 'stale': bool(stale)}
            if len(roles) > 1: entry['other_roles'] = [once(r, 80) for r in roles[1:6]]
            out.append(entry)
    named = {(o['key'], o['node']) for o in out}
    named_gen = {(o['key'], o['node'], o['generation']) for o in out}
    for nid, r in nodes.items():
        for field, what in RECORD_FIELDS:
            key = r.get(field); key = key.get('artifact') if isinstance(key, dict) else key
            if not (isinstance(key, str) and HEX64.fullmatch(key)): continue
            keys.add(key)
            receipt = field in ('receipt', 'verification_receipt')
            if ((key, nid, r['generation']) if receipt else (key, nid)) in (named_gen if receipt else named): continue
            out.append({'key': key, 'seq': None, 'kind': 'engine.state', 'role': field, 'at': None, 'node': nid, 'generation': r['generation'], 'attempt': r['attempt'],
                        'attempt_basis': 'engine.state', 'generation_basis': 'engine.state', 'label': f'{what} của phần việc {nid} (trạng thái engine; không sự kiện nào nêu nó)', 'output': receipt, 'stale': False})
    return out, keys


def _stored(state_root, keys):
    """{key: 'blob' | 'manifest'} for the keys the snapshot store holds (at most two stats per distinct key). The real engine stores node
    artifacts, inherited artifacts, retained candidates and captures as snapshot MANIFESTS (R1 closure review round 3); receipts and small
    evidence as blobs. Both are content that opens. Any other 64-hex value is an identifier (project_id, revision, plan sha ...) or gone."""
    from ..snapshots import Snapshots
    root = Snapshots(state_root).root
    out = {}
    for k in keys:
        if (root / 'blobs' / k).is_file(): out[k] = 'blob'
        elif (root / 'manifests' / (k + '.json')).is_file(): out[k] = 'manifest'
    return out


def _evidence_like(occurrence):
    """An occurrence that stays listed although its key is not a blob in the store: an engine-record entry or a key in a field the engine
    fills with a blob key (`artifact`, `receipt`, `result.artifact`, `candidate.receipt`, `resume_artifact` ...: the LAST name of its role), so
    an output whose blob is missing never reads as "no output"; it is marked blob: false. A 64-hex value anywhere else (project_id,
    revision, sha, basis_sha, a free-form evidence[i] string ...) is an identifier, not evidence."""
    if occurrence['kind'] == 'engine.state': return True
    if not occurrence['kind'].startswith(('node.', 'attempt.')): return False     # round 3: only an engine event's output field keeps a missing key
    names = re.findall(r'[a-z_]+', occurrence.get('role') or '')
    return bool(names) and names[-1] in BLOB_FIELDS


def _attempt_generation(attempt, node, bound, attempt_counter):
    """(node generation, basis) of an event that names an attempt but no generation of its own: the generation of the node.started that bound
    the attempt (when the event names a node, only if it is that node); else, for an attempt no node.started binds, the attempts-table
    counter (what its Gantt row shows); else (None, None)."""
    b = bound.get(attempt)
    if b and b[1] is not None and (node is None or node == b[0]): return b[1], f'node.started:#{b[2]}'
    if b is None and attempt in attempt_counter: return attempt_counter[attempt], 'attempts.counter'
    return None, None


def _source_of(occurrences, key, node, generation, attempt, before):
    """Where an inherited key came from: its occurrence in the SOURCE generation (and attempt) of that node — the production first, then any
    other output, then any use — never "the last occurrence of the key". With no occurrence in the source generation, the nearest older
    generation that names it; else None."""
    mine = [o for o in occurrences if o['key'] == key and o['node'] == node and o['seq'] is not None]
    pool = [o for o in mine if generation is not None and o['generation'] == generation and (attempt is None or o['attempt'] in (attempt, None))]
    if not pool and isinstance(before, int):
        older = [o for o in mine if isinstance(o['generation'], int) and o['generation'] < before]
        top = max((o['generation'] for o in older), default=None)
        pool = [o for o in older if o['generation'] == top]
    if not pool: return None
    best = min(pool, key=lambda o: (0 if o['kind'] == 'node.produced' else 1 if o['output'] else 2, o['seq']))
    return {k: best[k] for k in ('seq', 'kind', 'role', 'at', 'generation', 'attempt')}


def _timeline(conn, root_id, children, current_generation, limit, current_attempt=None, shown=None):
    """(rows, total): the newest `limit` non-noise events of the root and its children (display window). `shown`: the (seq, key) occurrences of
    evidence_index; a row names exactly the keys that have an occurrence OF THAT EVENT (an identifier, or a key of a non-evidence event, is not listed)."""
    current_attempt = current_attempt or {}
    rows = []
    task_ids = [root_id] + sorted(children)
    marks = ','.join('?' for _ in task_ids)
    noise = ','.join('?' for _ in NOISE)
    total = conn.execute(f'SELECT COUNT(*) FROM events WHERE task_id IN ({marks}) AND kind NOT IN ({noise})', task_ids + list(NOISE)).fetchone()[0]
    attempt_counter = {a['id']: a['generation'] for a in _attempts(conn, task_ids)} if task_ids else {}
    bound = {}                                   # attempt -> (node, node generation, seq of its node.started): the generation an attempt.* row shows
    for r in conn.execute(f"SELECT seq, payload FROM events WHERE task_id IN ({marks}) AND kind='node.started'", task_ids):
        p = json.loads(r['payload'])
        if p.get('attempt') and p.get('node') is not None: bound[p['attempt']] = (p['node'], p.get('generation'), r['seq'])
    attempt_node = {a: b[0] for a, b in bound.items()}
    for r in conn.execute(f'SELECT seq, task_id, kind, payload, created_at FROM events WHERE task_id IN ({marks}) AND kind NOT IN ({noise}) ORDER BY seq DESC LIMIT ?',
                          task_ids + list(NOISE) + [limit]):
        p = json.loads(r['payload'])
        named = {k for k in _keys_of(p) if shown is None or (r['seq'], k) in shown}       # exactly the occurrences of THIS event
        node = p.get('node')
        gen = p.get('generation') if node is not None else None          # attempt.reserved/launched: control generation, not the node's
        stale = node is not None and gen is not None and node in current_generation and gen != current_generation[node]
        attempt = p.get('attempt') or (p.get('id') if r['kind'].startswith('attempt.') else None)
        node_of_attempt = attempt_node.get(attempt) if attempt and node is None else None     # the event names no node, but its attempt was started for one
        owner = node if node is not None else node_of_attempt
        stale_attempt = owner is not None and attempt is not None and owner in current_attempt and attempt != current_attempt[owner]
        rows.append({'seq': r['seq'], 'task': 'root' if r['task_id'] == root_id else r['task_id'], 'at': r['created_at'], 'kind': r['kind'],
                     'node': node, 'node_of_attempt': node_of_attempt, 'generation': gen if gen is not None else (_attempt_generation(attempt, node, bound, attempt_counter)[0] if attempt else None), 'attempt': attempt,
                     'summary': clean(_summary(r['kind'], p), 240),
                     'observed_at': p.get('observed_at'), 'received_at': p.get('received_at'),
                     'stale_generation': stale, 'stale_attempt': stale_attempt,
                     'note': ('thế hệ cũ: không đổi trạng thái hiện tại' if stale else 'attempt cũ: không đổi trạng thái hiện tại' if stale_attempt else None),
                     'evidence': sorted(named)[:6], 'evidence_count': len(named)})      # display only: evidence_index (full history) is the index
    rows.reverse()
    return rows, total


MARK_KINDS = {'node.started': 'bắt đầu', 'node.produced': 'đã tạo đầu ra', 'node.verification': 'kiểm', 'node.held': 'bị giữ', 'node.resumed': 'thế hệ mới',
              'node.result_retained': 'giữ kết quả', 'attempt.unknown': 'kết quả chưa xác định', 'plan.approved': 'duyệt', 'plan.accepted': 'nghiệm thu',
              'plan.closed': 'đóng', 'plan.revised': 'kế hoạch nội bộ', 'request.created': 'câu hỏi', 'request.consumed': 'đã trả lời', 'milestone.stopped': 'dừng'}


def _timeline_spans(events, attempts, nodes, current_attempt, waits, now, node_views=None):
    """The Gantt rows, from sourced timestamps only: one row per attempt under its node (attempts.created_at = reserved, attempt.launched =
    execution start, attempts.updated_at of a settled attempt = end), executor waits with an `until`, verification spans (node.produced ->
    node.verification of the same generation), instant marks per attempt/node and per plan. A running attempt has a confirmed segment up to
    its latest sourced mark and a separate `to_now` segment (not confirmed) up to `now`; an attempt without a launch has only a reserved
    segment; nothing is invented: a missing timestamp leaves the segment out. Every comparison, min/max and span is on aware datetimes (an ISO
    string with any offset is normalised to UTC: P2-C), never on the strings; strings are emitted as `_iso` of the parsed value. A current
    attempt carries what its node legitimately inherits from an older generation (resume_artifact / continues: P2-B), read from the HISTORY
    (the node.resumed that opened the attempt's generation), so a row keeps it once newer generations exist (R1 review round 2)."""
    T = _at
    def iso(value): return _iso(value) if isinstance(value, dt.datetime) else None
    def later(a, b): return b if a is None or (b is not None and b > a) else a
    by_attempt = {a['id']: a for a in attempts}
    attempt_node, launched, marks_by_attempt, last_mark = {}, {}, {}, {}
    plan_marks, node_marks, produced_at, verifs = [], {}, {}, {}
    started_seq, resumed = {}, {}
    for seq, kind, p, at in events:
        when = T(p.get('observed_at')) or T(at)
        aid = p.get('attempt') or (p.get('id') if kind.startswith('attempt.') else None)
        if kind == 'node.started' and p.get('attempt'): attempt_node[p['attempt']] = (p.get('node'), p.get('generation')); started_seq.setdefault(p['attempt'], seq)
        if kind == 'node.resumed' and p.get('node') is not None: resumed.setdefault((p['node'], p.get('generation')), []).append((seq, p))
        if kind == 'attempt.launched' and p.get('id'): launched[p['id']] = T(at)
        if aid and aid in by_attempt and when: last_mark[aid] = later(last_mark.get(aid), when)
        if kind in MARK_KINDS and when:
            label = MARK_KINDS[kind] + (f": {clean(p.get('result'), 40)}" if kind == 'node.verification' else '') + (f": {clean(p.get('reason'), 60)}" if kind == 'node.held' else '')
            mark = {'seq': seq, 'at': iso(when), 'kind': kind, 'label': label, 'generation': p.get('generation')}
            if p.get('node') is not None: node_marks.setdefault((p['node'], p.get('generation')), []).append(mark)
            elif aid and aid in by_attempt: marks_by_attempt.setdefault(aid, []).append(mark)
            else: plan_marks.append(mark)
        if kind == 'executor.observed' and p.get('what') == 'progress' and (p.get('checkpoint') or {}).get('status') == 'blocked' and aid and when:
            marks_by_attempt.setdefault(aid, []).append({'seq': seq, 'at': iso(when), 'kind': 'executor.observed', 'label': 'quan sát: blocked', 'generation': p.get('generation')})
        if kind == 'node.produced': produced_at[(p.get('node'), p.get('generation'))] = T(at)
        if kind == 'node.verification' and (p.get('node'), p.get('generation')) in produced_at and T(at):
            verifs.setdefault((p.get('node'), p.get('generation')), []).append({'from': iso(produced_at[(p.get('node'), p.get('generation'))]), 'to': iso(T(at)), 'result': clean(p.get('result'), 40)})
    waits_by_attempt = {}
    for w in waits:
        if w['source'] == 'executor.observed' and w.get('attempt') and T(w['since']):
            until = T(w['until']) if w.get('until') not in (None, UNKNOWN) else None
            waits_by_attempt.setdefault(w['attempt'], []).append({'from': iso(T(w['since'])), 'until': iso(until), 'reason': clean(w.get('reason'), 120), 'open': w['open']})
    rows, times = [], []
    now_dt = now if isinstance(now, dt.datetime) else T(now)
    node_views = node_views or {}
    for nid in list(nodes) + [None]:
        for a in attempts:
            node, gen = attempt_node.get(a['id'], (None, a['generation']))
            if node != nid: continue
            active = a['status'] in ('reserved', 'running', 'unknown')
            start, launch = T(a['created_at']), launched.get(a['id'])
            end = T(a['updated_at']) if not active else None
            latest = None
            for candidate in (last_mark.get(a['id']), launch, start): latest = later(latest, candidate)
            segments = []
            if start and (launch or end or latest): segments.append({'kind': 'reserved', 'from': iso(start), 'to': iso(launch or end or latest), 'confirmed': True})
            if launch:
                if end: segments.append({'kind': 'execution', 'from': iso(launch), 'to': iso(end), 'confirmed': True})
                else:
                    if latest and latest > launch: segments.append({'kind': 'execution', 'from': iso(launch), 'to': iso(latest), 'confirmed': True})
                    segments.append({'kind': 'to_now', 'from': iso(latest or launch), 'to': iso(now_dt), 'confirmed': False})
            elif active and start: segments.append({'kind': 'to_now', 'from': iso(latest or start), 'to': iso(now_dt), 'confirmed': False})
            key = (node, gen)
            current = current_attempt.get(node) == a['id'] if node else False
            inherits = _inherited(node, gen, a['id'], started_seq, resumed, attempt_node, node_views.get(node) if node and current else None)
            row = {'node': node, 'attempt': a['id'], 'generation': gen, 'status': a['status'], 'current': current,
                   'reserved_at': iso(start), 'launched_at': iso(launch), 'settled_at': iso(end), 'latest_mark_at': iso(latest), 'active': active,
                   'segments': segments, 'waits': waits_by_attempt.get(a['id'], []),
                   'verification': verifs.get(key, []) if current or not any(r['attempt'] != a['id'] and (r['node'], r['generation']) == key for r in rows) else [],
                   'marks': sorted(node_marks.get(key, []) + marks_by_attempt.get(a['id'], []), key=lambda m: T(m['at'])),
                   'inherits': inherits,
                   'execution_seconds': _seconds(launch, end) if launch and end else UNKNOWN,
                   'span_seconds': _seconds(start, end) if start and end else UNKNOWN}
            rows.append(row)
            for s_ in segments: times += [T(s_['from']), T(s_['to'])]
            for w in row['waits']: times += [T(w['from']), T(w['until'])]
            for v in row['verification']: times += [T(v['from']), T(v['to'])]
            for m in row['marks']: times.append(T(m['at']))
    for m in plan_marks: times.append(T(m['at']))
    times = [t for t in times if t]
    extends = any(r['active'] for r in rows)
    axis_start, axis_end = (min(times), max(times)) if times else (None, None)
    if axis_start and extends and now_dt and now_dt > axis_end: axis_end = now_dt
    axis = {'start': iso(axis_start), 'end': iso(axis_end), 'now': iso(now_dt), 'extends_to_now': extends,
            'basis': 'attempts.created_at/updated_at, attempt.launched, executor.observed (observed_at), node.*; mọi mốc so theo giá trị thời gian (UTC), đoạn to_now = chưa xác nhận',
            'seconds': _seconds(axis_start, axis_end) if axis_start else UNKNOWN}
    return {'axis': axis, 'plan_marks': sorted(plan_marks, key=lambda m: T(m['at'])), 'rows': rows}


def _inherited(node, gen, attempt, started_seq, resumed, attempt_node, view=None):
    """P2-B + R1 review round 2: what an attempt of (node, gen) legitimately starts from, from the HISTORY, for every row (current or old):
    the node.resumed of (node, gen - 1) that opened generation `gen` (the first one before the attempt's node.started: the one the engine
    projector applies) with its resume_artifact and continues_attempt. `view` (the engine record, current row only) names the source as
    `nodes[N].field` while the engine still holds that value, and is the fallback only when the history names no such event. A node.held
    candidate is the held generation's OWN candidate (listed with that attempt's evidence, role candidate.*), never an inheritance."""
    if node is None or not isinstance(gen, int): return []
    s0 = started_seq.get(attempt)
    opened = next(((s, p) for s, p in resumed.get((node, gen - 1), []) if s0 is None or s < s0), None)
    view = view or {}
    vkey = view.get('resume_artifact'); vkey = vkey.get('artifact') if isinstance(vkey, dict) else vkey
    vkey = vkey if isinstance(vkey, str) and HEX64.fullmatch(vkey) else None
    vsrc = view.get('continues') if isinstance(view.get('continues'), str) else None
    if opened:
        seq, p = opened
        art = p.get('resume_artifact'); art = art.get('artifact') if isinstance(art, dict) else art
        art = art if isinstance(art, str) and HEX64.fullmatch(art) else None
        src = p.get('continues_attempt') if isinstance(p.get('continues_attempt'), str) else None
    elif vkey or vsrc:
        seq, art, src = None, vkey, vsrc
    else:
        return []
    src_gen = attempt_node.get(src, (None, None))[1] if src else None
    if src_gen is None and gen > 0: src_gen = gen - 1
    if art:
        source = f'nodes[{node}].resume_artifact' if art == vkey else f'node.resumed #{seq} resume_artifact'
        return [{'kind': 'resume_artifact', 'key': art, 'label': 'đầu ra dở được tiếp tục', 'from_attempt': src, 'from_generation': src_gen, 'source': source, 'resumed_seq': seq}]
    if src:
        source = f'nodes[{node}].continues' if src == vsrc else f'node.resumed #{seq} continues_attempt'
        return [{'kind': 'continues', 'key': None, 'label': 'tiếp từ lượt trước', 'from_attempt': src, 'from_generation': src_gen, 'source': source, 'resumed_seq': seq}]
    return []


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
    events, children, history = _history(conn, row['id'], events)
    attempts = _attempts(conn, [row['id']] + sorted(children))
    progress = _current_progress(_progress_rows(events), engine_view)
    waits = _waits(events, attempts)
    open_waits = [w for w in waits if w['open']]
    requests = [{'id': r['id'], 'revision': r['revision'], 'state': r['state'], 'created_at': r['created_at'], 'updated_at': r['updated_at'],
                 'question': json.loads(r['payload'])} for r in conn.execute('SELECT * FROM requests WHERE task_id=? ORDER BY created_at, id', (row['id'],))]
    from . import verdict
    try: runs = verdict.run_records(conn, row['id'])
    except (LedgerError, ValueError, KeyError): runs = []
    level = _level(state, engine_view, views)
    first_started = next((at for seq, kind, p, at in events if kind == 'node.started'), None)
    kind, reason, sources = _status(state, engine_view, attempts, progress, open_waits, requests, views, runs, level, first_started)
    last = events[-1] if events else None
    nodes = {}
    if engine_view is not None:
        for nid, r in engine_view['nodes'].items():
            nodes[nid] = {'generation': r.get('generation'), 'phase': r.get('phase'), 'state': r.get('state') or 'none', 'attempt': r.get('attempt'), 'child': r.get('child'),
                          'reason': clean(r.get('reason'), 200), 'classification': clean(r.get('classification'), 100),
                          'receipt': r.get('receipt'), 'verification_receipt': r.get('verification_receipt'), 'verification_result': r.get('verification_result'),
                          'continues': r.get('continues'), 'resume_artifact': r.get('resume_artifact'), 'retained_candidate': r.get('retained_candidate'),
                          'progress': progress.get(nid)}
    counts = {'total': len(nodes), 'pending': 0, 'running': 0, 'held': 0, 'produced': 0, 'verified': 0, 'accepted': 0}
    for r in nodes.values():
        if r['phase'] in counts: counts[r['phase']] += 1
        if r['state'] in counts: counts[r['state']] += 1
    outcome = _outcome(state, kind, level)
    active_rows = [{'attempt': a['id'], 'status': a['status'], 'since': a['created_at'], 'unit': a['unit'], 'stage': a['stage'],
                    'node': next((nid for nid, r in nodes.items() if r['attempt'] == a['id']), None)} for a in attempts if a['status'] in ('reserved', 'running', 'unknown')]
    item = {'id': row['id'], 'plan': state['name'], 'selector': row['request_key'], 'project': row['project_path'], 'project_id': row['project_id'],
            'goal': _goal(contract, payload), 'title': clean(payload.get('title'), 200), 'contract_revision': state['latest'],
            'created_at': row['created_at'], 'started_at': first_started, 'has_started': first_started is not None, 'deadline': None,
            'node_titles': {n['id']: clean(n.get('goal'), 200) for n in ((engine_view or {}).get('definition') or {}).get('nodes', [])},
            'root_status': state['status'],
            'status': {'kind': kind, 'label': OUTCOME_WORDS[outcome] if outcome else WORDS[kind], 'outcome': outcome, 'reason': clean(reason, 600), 'source': sources},
            'level': {'kind': level, 'label': LEVEL_WORDS[level]},
            'elapsed': _elapsed(state, events, now),
            'current_step': clean(_current_step(kind, state, engine_view, active_rows, requests, progress), 200),
            'last_update': {'seq': last[0], 'kind': last[1], 'at': last[3], 'summary': clean(_summary(last[1], last[2]), 200)} if last else None,
            'last_evidence': _last_evidence(events),
            'needs_user': _needs_user(state, requests, views, level, engine_view, project=row['project_path'], state_root=str(reader.state_root), contract=contract),
            'active': active_rows,
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
    item['notices'] = [{'seq': seq, 'at': at, 'category': clean(p.get('category'), 100), 'reason': clean(p.get('reason'), 300), 'user_action': clean(p.get('user_action'), 200),
                        'evidence': [clean(e, 120) for e in (p.get('evidence') or [])[:6]]} for seq, kind, p, at in events if kind == 'notice.exception']
    item['progress'] = progress
    current = {nid: r['generation'] for nid, r in nodes.items()}
    current_attempt = {nid: r['attempt'] for nid, r in nodes.items() if r['attempt']}
    occurrences, keys = _provenance(history, attempts, nodes, current, current_attempt)    # UX-07 + R1: every use of every blob, from the FULL history
    stored = _stored(reader.state_root, keys)                                             # R1 rounds 2-3: identifiers are not evidence; blobs AND manifests are
    occurrences = [dict(o, stored=stored.get(o['key']), blob=o['key'] in stored) for o in occurrences
                   if not o['kind'].startswith(NOT_EVIDENCE) and (o['key'] in stored or _evidence_like(o))]
    present = {o['key'] for o in occurrences if o['key'] in stored}
    item['timeline'], item['timeline_total'] = _timeline(conn, row['id'], children, current, timeline_limit, current_attempt, shown={(o['seq'], o['key']) for o in occurrences})
    item['timeline_limit'] = timeline_limit
    item['timeline_complete'] = len(item['timeline']) >= item['timeline_total']   # False: older events are not in `timeline`; their evidence is still in evidence_index
    item['evidence_keys'] = sorted(present)                                        # the stored keys (blob or manifest) the page counts and the door opens
    item['evidence_index'] = occurrences
    item['evidence_basis'] = EVIDENCE_BASIS
    item['gantt'] = _timeline_spans(history, attempts, list(nodes), current_attempt, waits, now, node_views=nodes)
    for r in item['gantt']['rows']:
        for x in r['inherits']:
            if x.get('key'):
                x['blob'] = x['key'] in stored
                x['stored'] = stored.get(x['key'])
                x['source_occurrence'] = _source_of(occurrences, x['key'], r['node'], x.get('from_generation'), x.get('from_attempt'), r['generation'])
                if x['source_occurrence'] is None: x['source_note'] = 'sổ không có sự kiện nào nêu blob này ở thế hệ nguồn'
    item['measure'] = _measure(rd, row['request_key']) if engine_root else {'note': 'root không có engine: không có attempt để đo'}
    item['eta'] = _eta(rd, row['request_key'], now)
    item['holds'] = _holds(rd, row['request_key'], conn) if engine_root else []
    from . import tracking_work
    item['work'] = tracking_work.project(rd, conn, row, state, events, engine_view, item['evidence_keys'])
    return item


def _measure(rd, selector):
    # Admission is Q2 -> node.started; preparation is reserved -> launched.
    # These sourced elapsed spans are not a scheduler-queue measurement.
    try:
        from . import execution_mode
        m = execution_mode.measure(rd, selector)
        return {'attempts_wall_seconds': m.get('attempts_wall_seconds', UNKNOWN), 'wait_seconds': m.get('wait_seconds', UNKNOWN),
                'time_to_first_useful_action_seconds': m.get('time_to_first_useful_action_seconds', UNKNOWN),
                'rework': m.get('rework'), 'method': m.get('method'),
                'attempts': [{k: a.get(k) for k in ('attempt', 'node', 'generation', 'mode', 'admission_seconds', 'preparation_seconds',
                                                  'execution_seconds', 'span_seconds', 'reserved_at', 'settled_at')} for a in m.get('attempts', [])],
                'waits': [dict(w, reasons=clean(w.get('reasons'), 200)) for w in m.get('waits', [])],
                'executor_waits': [{'at': w.get('at'), 'until': w.get('until'), 'reason': clean(w.get('reason'), 200), 'ref': clean(w.get('ref'), None),
                                    'time_source': clean(w.get('time_source'), 60)} for w in m.get('executor_waits', [])],
                'verification': [dict(v, result=clean(v.get('result'), 40)) if isinstance(v, dict) else clean(v) for v in (m.get('verification') or [])]}
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
        return [{'node': h['node'], 'attempt': h['attempt'], 'findings': [clean(f, None) for f in h['findings'] or []], 'text': clean(h.get('text'), 300), 'requested': h.get('requested'), 'confirmed': h.get('confirmed')}
                for h in managed_executor.hold_views(rd, selector, conn)]
    except (LedgerError, OSError, ValueError, KeyError) as error:
        return [{'error': clean(str(error), 200)}]


# ---- what is NOT tracked ----------------------------------------------------------------------------------------------------------------

def _untracked(conn, rows, state_root, projects_seen, children=frozenset(), *, project_id=None, seen_ids=frozenset()):
    """What is not tracked, inside the scope: the other tasks of the scoped rows, the hook sessions of the projects seen, and the registry
    projects without a plan in this ledger. Under a project scope the registry contributes only the scoped project's own entry (R2); a
    registry path is matched by the ledger identity (project_identity), so another spelling of a project that has a plan is not listed."""
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
            identity = project_identity(project)
            if project_id and identity != project_id: continue             # R2: another project's path / state root never enters a scoped model
            if identity in seen_ids or project.casefold() in projects_seen: continue
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
    """The list: every plan root of the state root (or of one project), grouped by project, with its sourced status; plus what is not tracked.
    A project scope covers the whole model (untracked registry included); everything returned passed the outbound guard."""
    return outward(_overview(state_root, project_id=project_id, now=now))


def _overview(state_root, *, project_id=None, now=None):
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
            seen_ids = {item.get('project_id') for items in projects.values() for item in items}
            result['untracked'] = _untracked(conn, rows, reader.state_root, {p.casefold() for p in projects}, children, project_id=project_id, seen_ids=seen_ids)
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
    """One root in full: nodes, attempts, requests, waits, notices, measured spans (union), ETA or unknown, holds, timeline, evidence keys.
    Everything returned passed the outbound guard."""
    return outward(_detail(state_root, selector, project_id=project_id, now=now, timeline_limit=timeline_limit))


def _detail(state_root, selector, *, project_id=None, now=None, timeline_limit=200):
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


def _names(conn, root_id, key):
    """Does any non-noise event of the root or of its child tasks name `key` (the same membership as `detail`'s evidence_keys), over the
    FULL history whatever its length? The ledger stores payloads as JSON text, so only the events whose text contains the key are parsed."""
    children = sorted({r[0] for r in conn.execute("SELECT json_extract(payload,'$.child') FROM events WHERE task_id=? AND kind='node.started'", (root_id,)) if r[0]})
    tasks = [root_id] + children
    marks, noise = ','.join('?' for _ in tasks), ','.join('?' for _ in NOISE)
    for (payload,) in conn.execute(f'SELECT payload FROM events WHERE task_id IN ({marks}) AND kind NOT IN ({noise}) AND instr(payload, ?) > 0', tasks + list(NOISE) + [key]):
        if key in _keys_of(json.loads(payload)): return True
    return False


def evidence(state_root, selector, key, *, project_id=None):
    """The text of one blob the root's events name (receipt, candidate, evidence), redacted line by line and capped; any other key is refused."""
    if not isinstance(key, str) or not HEX64.fullmatch(key): raise LedgerError('Mã bằng chứng không hợp lệ.')
    reader, source = _source(state_root)
    if source['status'] != 'ok': raise LedgerError(source['detail'])
    with reader.transaction() as conn:
        if conn is None: raise LedgerError('Sổ không mở được.')
        row = _find(conn, reader, selector, project_id)
        named = _names(conn, row['id'], key)
    if not named: raise PermissionError('Bằng chứng này không thuộc root đã chọn; không mở.')
    from ..snapshots import Snapshots
    from .diagnostics import redact
    kind = _stored(state_root, {key}).get(key)
    if kind is None:
        raise LedgerError('Không có trong kho bằng chứng: sổ nêu khóa này nhưng nó không phải nội dung đã lưu (blob hay ảnh chụp) — mã định danh như '
                          'project_id, revision, sha của plan, hoặc nội dung đã bị xóa khỏi kho; không có gì để mở.')
    if kind == 'manifest':                                                        # a snapshot: its files and their blob keys
        store = Snapshots(state_root)
        raw = (store.root / 'manifests' / (key + '.json')).read_bytes()
        try:
            value, verified = store.load(key), True
        except (LedgerError, OSError, ValueError) as error:
            value, verified = {'unverified': clean(str(error), 200), 'manifest': json.loads(raw.decode('utf-8', 'replace'))}, False
        files = len((value.get('files') if verified else (value['manifest'] or {}).get('files')) or {})
        text = json.dumps(value, ensure_ascii=False, indent=1, sort_keys=True)
        truncated = len(text) > EVIDENCE_CAP
        clean_text, redaction = redact(text[:EVIDENCE_CAP])
        return outward({'key': key, 'kind': 'manifest', 'files': files, 'verified': verified, 'bytes': len(raw), 'truncated': truncated,
                        'text': clean_text, 'redaction': redaction, 'read_only': True})
    data = Snapshots(state_root).read_blob(key)
    truncated = len(data) > EVIDENCE_CAP
    text = data[:EVIDENCE_CAP].decode('utf-8', 'replace')
    try:
        text = json.dumps(json.loads(data.decode('utf-8')), ensure_ascii=False, indent=1, sort_keys=True)
        truncated = len(text) > EVIDENCE_CAP; text = text[:EVIDENCE_CAP]
    except (ValueError, UnicodeDecodeError):
        pass
    clean_text, redaction = redact(text)
    return outward({'key': key, 'kind': 'blob', 'bytes': len(data), 'truncated': truncated, 'text': clean_text, 'redaction': redaction, 'read_only': True})


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
            lines.append(f"  [{t['status']['label']}] {t['plan']} ({t['id'][:12]}) · {t['level']['label']} · từ khi duyệt {_hms(t['elapsed'].get('seconds'))} (lịch) · {t['tracking']['adapter']}")
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
    return _guard('\n'.join(lines) + '\n')


def render_detail(value):
    t = value
    lines = [f"PLAN {t['plan']} ({t['id']}) — {t['project']} — lúc {t['generated_at']} (chỉ đọc)",
             f"Trạng thái: {t['status']['label']} — {t['status']['reason']} [{', '.join(t['status']['source'])}]",
             f"Mức đầu ra: {t['level']['label']} · root: {t['root_status']} · từ khi duyệt: {_hms(t['elapsed'].get('seconds'))} ({t['elapsed'].get('basis')})",
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
    if any(w['open'] for w in t['waits']):
        lines.append('Đang chờ:')
        for w in t['waits']:
            if w['open']: lines.append(f"  - từ {w['since']}: {w.get('reason')} ({w['source']})")
    if any(not w['open'] for w in t['waits']):
        lines.append('Đã chờ (lịch sử):')
        for w in t['waits']:
            if not w['open']: lines.append(f"  - {w['since']} → {w.get('until')}: {w.get('reason')} ({w['source']})")
    if t['holds']:
        lines.append('Giữ (finding):')
        for h in t['holds']: lines.append('  - ' + (h.get('text') or h.get('error') or ''))
    lines.append(f"Timeline ({len(t['timeline'])}/{t['timeline_total']} sự kiện, cũ → mới)" + ('' if t.get('timeline_complete', True) else
                 f" — đang hiện {len(t['timeline'])} sự kiện mới nhất; bằng chứng của sự kiện cũ hơn vẫn có trong `--json` (evidence_index, toàn bộ lịch sử) và trên trang theo dõi") + ':')
    for e in t['timeline']:
        when = e['at'] + (f" (quan sát {e['observed_at']})" if e.get('observed_at') and e['observed_at'] != e['at'] else '')
        lines.append(f"  #{e['seq']} {when} {e['kind']}: {e['summary']}" + ('  [thế hệ cũ]' if e['stale_generation'] else '  [attempt cũ]' if e.get('stale_attempt') else ''))
    index = t.get('evidence_index') or []
    missing = sorted({x['key'] for x in index if x.get('blob') is False})
    lines.append(f"Bằng chứng mở được: {len(t['evidence_keys'])} mục trong kho (blob hoặc ảnh chụp; {sum(1 for x in index if x.get('blob') is not False)} lần được nêu, toàn bộ lịch sử)"
                 + (f" · {len(missing)} khóa đầu ra không còn trong kho (không mở được)" if missing else '') + f" · Điều khiển: {t['controls']}")
    return _guard('\n'.join(lines) + '\n')
