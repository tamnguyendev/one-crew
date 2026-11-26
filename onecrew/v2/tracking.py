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
import copy
import datetime as dt
import functools
import json
import os
import re
import sqlite3
import subprocess
import threading
from contextlib import contextmanager
from pathlib import Path

from ..ledger import LedgerError, utcnow
from ..specs import digest
from . import namespaces, plan as plans, report, tracking_list

VERSION = 1
UNKNOWN = 'unknown'
KINDS = ('running', 'waiting', 'blocked', 'done', 'unknown')
WORDS = {'running': 'đang thực hiện', 'waiting': 'đang chờ', 'blocked': 'bị chặn', 'done': 'hoàn tất', 'unknown': 'chưa xác định'}
LEVELS = ('none', 'produced', 'verified', 'accepted')
LEVEL_WORDS = {'none': 'chưa có đầu ra', 'produced': 'đã tạo đầu ra', 'verified': 'đã kiểm', 'accepted': 'đã nghiệm thu'}
# UX-05: a "done" root is one of three different things, and the word (and the colour the page gives it) says which
OUTCOME_WORDS = {'accepted': 'đã nghiệm thu', 'verified': 'đã kiểm, chờ nghiệm thu', 'closed': 'đã đóng'}
STOPPED_WORD = 'đã dừng'
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


class _Joined(report._Reader):
    """UI3 (P1 of 19/11): the read-only reader of one root that JOINS the read transaction already open (`conn`) instead of opening a second ledger
    connection. In rollback-journal mode a second reader opened while the first holds its SHARED lock waits behind a writer's PENDING lock, while that
    writer waits for the first one to finish: both give up and the writer (`plan advise`, `plan approve`, `verdict run`) says "database is locked".
    Every helper a tracking read hands a reader to (estimates, measure, engine, findings, holds, evidence reuse) reads through this one connection."""

    def __init__(self, state_root, project_id, project_path, conn):
        super().__init__(state_root, project_id, project_path)
        self._conn = conn

    @contextmanager
    def transaction(self, write=False):
        if write: raise LedgerError('plan report/digest are read-only: they never write the ledger.')
        yield self._conn


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

def _owner_view(contract):
    """dev11: the contract's owner part (presentation): the card's title, description and acceptance words. `present` False: the contract
    has no owner sentence, and the page shows the technical goal as before with the label "chưa có mô tả cho chủ"."""
    shown = (contract or {}).get('presentation') or {}
    texts = lambda key: [clean(x, 300) for x in (shown.get(key) or []) if isinstance(x, str) and x.strip()][:6] if isinstance(shown.get(key), list) else []
    request = clean(shown.get('request'), 500) if isinstance(shown.get('request'), str) and shown.get('request').strip() else None
    not_doing = clean(shown.get('not_doing'), 500) if isinstance(shown.get('not_doing'), str) and shown.get('not_doing').strip() else None
    return {'present': bool(request), 'request': request, 'user_sees': texts('user_sees'), 'acceptance_steps': texts('acceptance_steps'),
            'not_doing': not_doing}


def short_title(title, limit=64):
    """#58: the card's line from the contract title: whole when short; else cut at a clause boundary (', ' ' (' '; ' ' — ') when that keeps most of
    the room, otherwise at the last word, with '…'. The full title stays in `headline`."""
    text = ' '.join(str(title or '').split())
    if len(text) <= limit: return text or None
    head = text[:limit - 1]
    cut = max(head.rfind(mark) for mark in (', ', ' (', '; ', ' — ', ' - '))
    if cut < limit * 0.6: cut = head.rfind(' ')
    return (head[:cut] if cut > 0 else head).rstrip(' ,;:—-(') + '…'


ROW_TITLE = 80


def row_title(request, title, limit=ROW_TITLE):
    """UI58 MC (regression of 19/11): the list row's short name. The first sentence of the owner's request (presentation.request), cut on a word
    boundary with '…' when longer than `limit`; without a request, short_title of the contract title. The full request stays on the task page
    ("Việc này làm gì"), in the row's title attribute and accessible name, and in the search text."""
    text = ' '.join(str(request or '').split())
    if not text: return short_title(title)
    end = re.search(r'[.!?…](?=\s|$)', text)
    first = text[:end.start() + 1] if end else text
    if first.endswith('.') and not first.endswith('..'): first = first[:-1]
    if len(first) <= limit: return first
    head = first[:limit - 1]
    cut = head.rfind(' ')
    return (head[:cut] if cut > limit * 0.5 else head).rstrip(' ,;:—-(') + '…'


def _live_views(reader, contract, state):
    """#58: the task page reads the milestones as `plan report` does (plans.views_for): each pass judged against the project as it is now, so a pass
    the code has left reads 'cần kiểm lại' and is not counted. One observation of the project for the whole read (observed_view, opened by
    _observed around every round of the read). When the project's current artifact cannot be read, a pass of a non-manual verifier is not counted
    and says so (current_unknown). -> (views, current). UI3: it observes the project, so it is called only with no ledger transaction open (from
    _Observations.make, with a reader that opens its own short transactions), never from inside a read."""
    from .verifiers import artifact as identities
    here = None
    if state['status'] not in ('accepted', 'closed') and getattr(reader, 'project', None):
        try: here = identities.identity(reader.project)
        except (LedgerError, OSError, subprocess.SubprocessError, ValueError): here = None
    elif state['status'] in ('accepted', 'closed'):
        return plans.views_for(reader, contract, state, state['latest']), 'compared'
    if here is None:
        return _unknown_views(contract, state), 'unknown'
    return plans.views_for(reader, contract, state, state['latest']), 'compared'


def _ledger_views(observe, free, contract, state, root_key, sig):
    """UIMOCK rev 9 (UI58 on the development ledger, 23/11): the views of a read that does not compare with the project (the list, the task
    page's tiles before "Xem sâu"). Before such a view asks the OWNER to try a milestone (tracking_situation.owner_try) on passes it has not
    compared, it checks the one part of the comparison that needs no hash of the project and no read of a Python environment: a command pass
    whose program file changed since it ran is stale (plan.program_stale, quick), so it is not counted and the owner's step is not offered on it.
    Only that case is checked (a stat and a digest per receipt), so the first paint stays as fast as before. A check that fails leaves the
    ledger's own views (their validity still says "chưa so")."""
    views = plans.milestone_views(contract, state, state['latest'])
    if state['status'] in ('accepted', 'closed') or not observe.comparison: return views
    from .tracking_situation import owner_try
    if owner_try(views) is None: return views
    try: found = plans.program_stale(free, contract, state, state['latest'])
    except Exception: found = None
    if found: plans.mark_program_stale(contract, views, found)
    return views


def _unknown_views(contract, state):
    """The views from the ledger alone, a pass of a non-manual verifier not counted (current_unknown): the project's artifact was not compared."""
    views = plans.milestone_views(contract, state, state['latest'])
    for v in views:
        if v['state'] == 'passed' and v['verifier'] != 'owner-manual': v.update(state='pending', current_unknown=True)
    return views


# ---- project observations, never inside a ledger transaction (UI3, P1 of 19/11) ----------------------------------------------------------
# A tracking read used to hash the project (artifact identity, the scoped tree of declared inputs, the evidence binding: git subprocesses) inside
# its read transaction, so every 2 s poll of an open task page held the ledger's SHARED lock for the whole hash, and the owner's own writers
# (plan advise / approve, verdict run) failed with "database is locked". Now a read asks _Observations for what it needs; what is not at hand is
# noted, the read closes its transaction, the noted observations are made with no transaction open, and the read is made again (a new short
# transaction) with them. The ledger signature of the root (_compared_sig) is part of every key: an observation is never used for another state.
# With a reuse window (the server's polls, REUSE_SECONDS) an observation of the same root and signature younger than the window is reused and
# shown with the time it was made; a new ledger event for the root or the end of the window makes a new one. Without one (CLI, tests) every
# read observes the project again, as before.
REUSE_SECONDS = 20
OBSERVE_ROUNDS = 4
REUSE_CAP = 512
_reused = {}
_reused_lock = threading.Lock()
_ARTIFACT = re.compile(r'[0-9a-f]{40}|[0-9a-f]{64}')


class _Need(Exception):
    """A read that stops at the first observation it does not have (the task page): its transaction closes before the observation is made."""


class _Observations:
    """The project observations of ONE read (task page, overview or list page). `get` never observes: it answers from this read's observations or
    the reuse window, else notes the need and answers None (the caller goes on with what it shows without it; a read with needs is made again)
    or, with `stop`, raises _Need. `make` runs the noted observations; the caller calls it only after the read's transaction is closed."""

    def __init__(self, now, reuse_seconds=0, *, stop=False, final=False, comparison=True):
        self.now, self.reuse, self.stop, self.final = now, reuse_seconds or 0, stop, final
        self.comparison = comparison
        self.values, self.needs = {}, {}

    def get(self, key, sig, make):
        """('ok', value, at) | ('raise', error, at) | None; `make` is called later, outside the transaction, never here."""
        full = (key, sig)
        if full in self.values: return self.values[full]
        if self.reuse > 0:
            with _reused_lock: hit = _reused.get(key)
            made = _at(hit['at']) if hit else None
            if hit and hit['sig'] == sig and made and 0 <= (self.now - made).total_seconds() < self.reuse:
                self.values[full] = ('ok', hit['value'], hit['at'])
                return self.values[full]
        if self.final: return None
        self.needs[full] = make
        if self.stop: raise _Need()
        return None

    def make(self):
        at = _iso(self.now)
        for full, make in list(self.needs.items()):
            try: got = ('ok', make(), at)
            except Exception as error: got = ('raise', error, at)        # raised again where the read uses it, as when it was made in place
            self.values[full] = got
            if got[0] == 'ok':
                with _reused_lock:
                    if full[0] not in _reused and len(_reused) >= REUSE_CAP: _reused.pop(next(iter(_reused)))
                    _reused[full[0]] = {'sig': full[1], 'value': copy.deepcopy(got[1]), 'at': at}
        self.needs = {}


def _taken(got):
    """(value, at) of an observation, a copy the read may change; an observation that failed raises its error here."""
    status, value, at = got
    if status == 'raise': raise value
    return copy.deepcopy(value), at


def _observed(read, now, reuse_seconds=0, *, stop=False, comparison=True):
    """Run `read(observe)` — which opens and closes its own short ledger transaction — until it needs no observation it does not have; the needed
    observations are made between rounds, with no ledger transaction open, under ONE observed_view (one identity of the project for the whole read).
    A ledger that moves on between rounds makes another round; the last round observes nothing and shows what it has (current unknown)."""
    if not comparison:
        return read(_Observations(now, final=True, comparison=False))
    from .verifiers import artifact as identities
    observe = _Observations(now, reuse_seconds, stop=stop)

    @identities.observed_view
    def rounds():
        result = None
        for number in range(OBSERVE_ROUNDS):
            observe.final = number == OBSERVE_ROUNDS - 1
            try: result = read(observe)
            except _Need: result = None
            if not observe.needs: return result
            observe.make()
        return result
    return rounds()


# UI58 MC (D4): the list does not hash every project. The task page's comparison (_live_views) is kept here, per process, keyed by the ledger's
# identity of the root (resolved state root, project id, task id); it is reused by the list while the root's ledger is the same (latest revision,
# plan status and last event seq: any new event, a new verdict included, drops it), and always shown with the time it was made. Files that change
# after that time are not seen until the task page compares again; the list says so with the time instead of claiming the result is current.
COMPARED_CAP = 512
_compared = {}


def _compared_key(state_root, row):
    try: root = os.path.normcase(str(Path(state_root).resolve()))
    except (OSError, ValueError, RuntimeError): root = str(state_root)
    return (root, row['project_id'], row['id'])


def _compared_sig(state, events):
    return (state.get('latest'), state.get('status'), events[-1][0] if events else 0)


def _remember_compared(state_root, row, state, events, views, current, at):
    """`at`: when the comparison was made (ISO text, or a datetime)."""
    if current not in ('compared', 'unknown'): return
    key = _compared_key(state_root, row)
    with _reused_lock:
        if key not in _compared and len(_compared) >= COMPARED_CAP: _compared.pop(next(iter(_compared)))
        _compared[key] = {'sig': _compared_sig(state, events), 'views': copy.deepcopy(views), 'current': current,
                          'at': at if isinstance(at, str) else _iso(at)}


def _recall_compared(state_root, row, state, events):
    with _reused_lock: hit = _compared.get(_compared_key(state_root, row))
    if not hit or hit['sig'] != _compared_sig(state, events): return None
    return copy.deepcopy(hit['views']), hit['current'], hit['at']


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
# UI58 MC: the tracking page builds no template for the owner's own result of a milestone; the command is in the plan's handover
OWNER_TRY_NOTE = ('Trang chưa có mẫu lệnh cho bước này. Lệnh ghi kết quả của bạn nằm trong phần bàn giao của kế hoạch (tin "Xin nghiệm thu"); '
                  'lệnh chỉ xem bên dưới in lại các mốc và cách nghiệm thu. Ghi kết quả đạt cho mốc này rồi mới đến bước nghiệm thu.')


def _quote(value):
    """One PowerShell argument (the supported shell for the templates: the owner's scripts are .ps1): single-quoted, so `$`, backticks, `&`,
    `(`, spaces and `'` (doubled) inside a path are passed through unchanged; double quotes would let `$SDK` be interpolated (P2-B)."""
    return "'" + str(value).replace("'", "''") + "'"


def _runtime_exe():
    import sys
    exe = Path(sys.executable).parent / ('onecrew.exe' if sys.platform == 'win32' else 'onecrew')
    return exe if exe.is_file() else None


def _runtime():
    """How the command names THIS runtime: the venv's onecrew.exe next to the interpreter when it exists (`& '<exe>'`), else plain `onecrew`."""
    import sys
    exe = _runtime_exe()
    return '& ' + _quote(exe) if exe else '& ' + _quote(sys.executable) + ' -I -X utf8 -m onecrew.console'


def _runtime_binding(project, state_root):
    """Read the existing init/doctor binding; never run a binary supplied by the project."""
    from . import install
    exe = _runtime_exe()
    try:
        if exe and project and state_root and install.check_hooks(Path(project), Path(state_root), exe)[0] == 'PASS':
            return {'verified': True, 'runtime': str(exe), 'reason': None}
    except (OSError, ValueError, TypeError, KeyError, IndexError, AttributeError):
        pass
    return {'verified': False, 'runtime': str(exe) if exe else None,
            'reason': 'Chưa xác minh hook project dùng đúng runtime của trang và đúng sổ. Không cung cấp lệnh ghi quyết định. Mở trang bằng runtime đã gắn với project; không đổi hook chỉ để sao chép lệnh.'}


def _bind_actions(needs, binding):
    for need in needs:
        need['runtime_binding'] = binding
        if binding['verified'] or need.get('kind') == 'owner_try': continue     # owner_try carries no template: its note stays the handover one
        for entry in [need, *need.get('options', [])]:
            entry['human_command'] = entry['reply_command'] = None
            entry['binding_reason'] = binding['reason']
            entry['reply_note'] = binding['reason']
            if entry.get('action'):
                entry['action'] = dict(entry['action'], enabled=False, template=None, note=binding['reason'])
    return needs


def _acceptance(reader, conn, state, contract, engine_view, level, *, free=None, observe=None, key=(), sig=None):
    """Eligibility from recorded evidence only; the owner command rechecks the live artifact. UI3: the project is observed (the
    delivery tree and the milestone views at that artifact) by `observe` with no transaction open, through `free` (a reader that opens its own
    short transactions); `reader` and `conn` are the read's own transaction. Without an observation at hand the root is not shown as ready."""
    result = {'ready': False, 'artifact': None, 'basis': 'recorded evidence; CLI rechecks current project', 'reason': None}
    if state['status'] != 'approved' or not contract: return result
    try:
        if namespaces.has_capability(state, 'finding-register'):
            from .findings import list_findings
            opened = list_findings(reader, state['selector'], task_id=state['task_id'], open_only=True)
            if opened:
                ids = [item['id'] for item in opened]
                result.update(open_findings=ids, reason=report.finding_blocker(ids))
                return result
        if level != 'verified': return result
        if engine_view is not None:
            from . import engine
            guidance = engine.next_action(reader, state['selector'], conn=conn, view=engine_view, observe_project=False)
            result['next_action'] = guidance
            if guidance['kind'] != 'owner_accept':
                result['reason'] = guidance['reason']
                return result
        views = plans.milestone_views(contract, state, state['latest'])
        missing = [v['id'] for v in views if v['state'] != 'passed' or v.get('stale')]
        if not views or missing:
            result['reason'] = 'Chờ bộ thực thi kiểm mốc ' + ', '.join(missing) + '; chưa đến bước nghiệm thu.'
            return result
        from .contract import delivery_milestone
        final = delivery_milestone(contract)
        # The final check's whole tree anchors the scoped intermediate receipts.
        delivery = next((v for v in views if v['id'] == final), views[-1])
        recorded = delivery['last_verdict']['artifact_sha']
        if any(v['verifier'] == 'owner-manual' and v['last_verdict']['artifact_sha'] != recorded for v in views):
            result['reason'] = 'Chờ bộ thực thi kiểm các mốc trên cùng bản bàn giao.'
            return result
        if not isinstance(recorded, str) or not _ARTIFACT.fullmatch(recorded):
            result['reason'] = 'Chưa xác minh định danh bản bàn giao để nghiệm thu.'
            return result
        free = free or report._Reader(reader.state_root, reader.project_id, reader.project_path)

        def seen():
            from .verifiers import artifact as identities
            with identities.command.leaves_no_objects():
                current = identities.identity(free.project) if final or identities.is_git(free.project) else recorded
                checked = plans.milestone_views(contract, state, state['latest'], free, artifact=current, recorded_environment=True)
            return {'artifact': current, 'views': checked}
        got = observe.get(('acceptance',) + tuple(key) + (recorded,), sig, seen) if observe is not None else None
        if got is None:
            result['reason'] = 'Chưa xác minh đủ bằng chứng nghiệm thu; cần kiểm lại mốc và bàn giao.'
            return result
        observed, _ = _taken(got)
        artifact = observed['artifact']
        if not isinstance(artifact, str) or not _ARTIFACT.fullmatch(artifact):
            result['reason'] = 'Chưa xác minh định danh bản bàn giao để nghiệm thu.'
            return result
        if engine_view is not None:
            from . import engine
            proof = engine.handoff_evidence(reader, state['selector'])
            if not proof or proof.get('delivered_artifact') != artifact:
                result['reason'] = 'Chờ bộ thực thi hoàn tất kiểm tích hợp và bằng chứng bàn giao; chưa đến bước nghiệm thu.'
                return result
        views = observed['views']
        result['views'] = views                     # review of dev24d (P3): the milestone rows show this live view, not the ledger-only one
        if any(v['state'] != 'passed' or v.get('stale') for v in views):
            result['reason'] = 'Chờ bộ thực thi kiểm lại bằng chứng các mốc của bản bàn giao.'
            return result
        result.update(ready=True, artifact=artifact, reason='Đủ bằng chứng trong sổ để trình nghiệm thu; lệnh sẽ kiểm lại hiện trạng project.')
    except (LedgerError, OSError, ValueError, KeyError, TypeError):
        result['reason'] = 'Chưa xác minh đủ bằng chứng nghiệm thu; cần kiểm lại mốc và bàn giao.'
    return result


def _action(template, expected, placeholders=(), note=None):
    return {'schema_version': 1, 'enabled': bool(template), 'template': template, 'shell': REPLY_SHELL,
            'placeholders': list(placeholders), 'expected': expected, 'note': note}


def _needs_user(state, requests, views, level, engine_view, project=None, state_root=None, contract=None, acceptance=None, *, comparison=True, advice_pending=False):
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
        for option in (q.get('options') or [])[:8]:            # UI58 MC: every option the ledger holds (2-8), each with its own consequence when recorded
            template = human + _quote(option.get('id')) + suffix + ' --human' if complete else None
            said = option.get('consequence') or option.get('impact')
            options.append({'id': clean(option.get('id'), 60), 'label': clean(option.get('label'), 500),
                            'consequence': clean(said, 500) if isinstance(said, str) and said.strip() else None,
                            'recommended': option.get('id') == q.get('recommendation'),
                            'reply_command': command + clean(option.get('id'), 60) + suffix,
                            'human_command': template, 'action': _action(template, dict(expected, choice=option.get('id')), ['reference'])})
        needs.append({'kind': 'request', 'id': r['id'], 'revision': r['revision'], 'question': clean(q.get('question'), 2000),
                      'source_kind': 'ledger_request', 'source_label': 'Yêu cầu trong sổ (chờ bạn trả lời)', 'asked_at': r.get('created_at'),
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
        owner = _owner_view(contract)
        reason = clean(written.get('reason'))
        if advice_pending:
            template = None
            reason = (reason + '. ' if reason else '') + f'Chờ kết quả cố vấn. AI chạy onecrew plan advise {selector} trước khi chủ duyệt.'
        needs.append({**({'owner_ask': 'Duyệt việc: ' + owner['request']} if owner['present'] else {}),
                      'source_kind': 'scope_change' if revision > 1 else 'plan_approval',
                      'source_label': (f'Đề xuất đổi phạm vi: bản {revision} chờ bạn duyệt' if revision > 1 else 'Kế hoạch chờ bạn duyệt'),
                      'kind': 'approve','question': f"Duyệt bản {state['latest']} của plan {state['name']} (plan approve, lệnh của chủ sở hữu)",
                      'id': state.get('task_id'), 'revision': revision, 'title': clean((contract or {}).get('title')),
                      'reason': reason, 'impact': clean((written.get('acceptance_diff') or {}).get('summary')),
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
        needs.append({'kind': 'stopped', 'question': 'Đọc báo cáo dừng ở mốc ' + clean(stopped.get('milestone'), 50) + ' và quyết định (amend để đi tiếp / kết thúc)',
                      'source': [f"milestone.stopped:rev{state['latest']}"]})
    elif state['status'] == 'approved' and level == 'verified':
        if acceptance and acceptance['ready']:
            revision = (state.get('approved') or {}).get('revision')
            artifact = acceptance['artifact']
            template = (f'{prefix} owner accept {_quote(selector)} --revision {revision} --artifact-sha {_quote(artifact)}'
                        + f' --reference {_quote(REFERENCE_PLACEHOLDER)} --human') if complete and selector and revision and artifact else None
            why = None if template else 'Chưa tạo lệnh nghiệm thu: nguồn hiện có chưa có một artifact bàn giao chung đã kiểm hợp lệ; không lấy snapshot node thay artifact được bàn giao. Đọc báo cáo ghim revision và đối chiếu bằng chứng trước.'
            owner = _owner_view(contract)
            needs.append({**({'owner_ask': 'Nghiệm thu: ' + ('; '.join(owner['acceptance_steps']) or owner['request'])} if owner['present'] else {}),
                          'kind': 'accept', 'question': 'Mọi mốc đã có verdict đạt: nghiệm thu (plan accept, lệnh của chủ sở hữu) hoặc nêu điều chưa đạt',
                          'id': state.get('task_id'), 'revision': revision, 'artifact_sha': artifact,
                          'reply_command': template, 'human_command': template, 'reply_shell': REPLY_SHELL,
                          'reference_placeholder': REFERENCE_PLACEHOLDER, 'placeholders': ['reference'] if template else [],
                          'reply_note': 'Điền --reference của bạn; CLI kiểm lại revision và artifact trong giao dịch nghiệm thu, không duyệt từ thao tác sao chép.' if template else why,
                          'binding_reason': why,
                          'inspect_command': f'{prefix} plan report {_quote(selector)} --revision {state["approved"]["revision"]}' if complete and selector and state.get('approved') else None,
                          'action': _action(template, {'task': state.get('task_id'), 'selector': selector,
                                                       'revision': revision, 'artifact_sha': artifact}, ['reference'] if template else [], note=why),
                          'source': ['milestone.passed' if views else 'node.verification:pass']})
    elif state['status'] == 'approved' and engine_view is None and not namespaces.has_capability(state, 'sequential-engine'):
        from .tracking_situation import owner_try, owner_try_step
        mine = owner_try(views)
        if mine is not None:     # UI58 MC: the owner-manual milestone waits for the owner (plan report: "Cần bạn làm: nghiệm thu"); no command is invented
            owner = _owner_view(contract)
            ask = owner_try_step(mine)
            needs.append({'kind': 'owner_try', 'owner_ask': ask, 'id': state.get('task_id'), 'revision': state['latest'], 'milestone': mine['id'],
                          'milestone_title': clean(mine.get('title'), 200),
                          'question': ask + '; khi đạt, bạn nghiệm thu việc (mốc này do bạn tự kiểm, bộ kiểm OneCrew không chạy nó)',
                          'source_kind': 'owner_manual', 'source_label': 'Mốc chờ bạn tự thử và ghi kết quả',
                          'steps': owner['acceptance_steps'] if owner['present'] else [],
                          'reply_command': None, 'human_command': None, 'placeholders': [], 'reply_shell': REPLY_SHELL,
                          'binding_reason': OWNER_TRY_NOTE, 'note': OWNER_TRY_NOTE,
                          'inspect_command': f'{prefix} plan report {_quote(selector)}' if complete and selector else None,
                          'action': _action(None, {'task': state.get('task_id'), 'selector': selector, 'revision': state['latest'], 'milestone': mine['id']},
                                            note=OWNER_TRY_NOTE),
                          'source': ['milestone.pending:' + str(mine['id']), 'verifier:owner-manual']})
    binding = (_runtime_binding(project, state_root) if comparison else
               {'verified': False, 'runtime': None, 'reason': 'Bản sao sổ dùng để xem. Quyết định được ghi trên sổ nguồn.'})
    return _bind_actions(needs, binding)


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


def _status(state, engine_view, attempts, progress, waits, requests, views, verifier_runs, level, first_started, acceptance=None, guidance=None):
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
    if (guidance or {}).get('state') == 'stopped' and not active:
        return 'blocked', guidance['reason'], ['engine.next_action']
    if engine_view is not None:
        from . import engine
        held = [nid for nid, r in engine_view['nodes'].items() if r.get('phase') == 'held']
        gate = {'finding_blockers': engine.finding_gate(engine_view), 'unknown_blockers': engine_view.get('unknown_blockers') or {},
                'failed_blockers': engine_view.get('failed_blockers') or {}, 'request_blockers': engine_view.get('request_blockers') or {}}
        blockers = {k: v for k, v in gate.items() if v}
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
        if acceptance and acceptance['ready']:
            return 'done', acceptance['reason'], ['milestone.passed', 'acceptance.recorded_evidence']
        if (acceptance or {}).get('next_action', {}).get('state') in ('blocked', 'handoff_blocked', 'held', 'stopped'):
            return 'blocked', acceptance['reason'], ['engine.next_action']
        return 'waiting', (acceptance or {}).get('reason') or 'Chờ kiểm đủ điều kiện bàn giao, chưa đến bước nghiệm thu.', ['acceptance.recorded_evidence']
    if engine_view is not None:
        if not engine_view['nodes']:
            return 'waiting', 'đã duyệt, chưa có kế hoạch nội bộ; bước tiếp theo engine revise', ['engine.state']
        produced = [nid for nid, r in engine_view['nodes'].items() if r.get('state') == 'produced']
        pending_nodes = [nid for nid, r in engine_view['nodes'].items() if r.get('phase') == 'pending']
        if produced:
            return 'waiting', 'đầu ra đã tạo, chờ kiểm; bước tiếp theo engine verify cho node: ' + ', '.join(produced), ['node.produced:' + n for n in produced]
        if pending_nodes and not first_started:
            return 'waiting', 'đã duyệt, chưa có worker nào được bắt đầu (chờ engine step)', ['plan.approved']
        if pending_nodes:
            return 'waiting', 'chờ bước tiếp theo cho ' + ', '.join(pending_nodes), ['engine.state']
        return 'unknown', 'không có node đang chạy, bị giữ hay chờ; không suy được từ sổ', ['engine.state']
    if views:
        from .tracking_situation import owner_try
        mine = owner_try(views)
        if mine is not None:        # UI58 MC: the owner's own check of an owner-manual milestone, then acceptance (plan report: "nghiệm thu")
            return 'waiting', f"chờ chủ sở hữu tự thử và ghi kết quả mốc {mine['id']}, rồi nghiệm thu (root không có engine: chỉ theo dõi mốc)", \
                ['plan.approved', 'milestone.pending:' + str(mine['id'])]
        # R7-2: a milestone whose latest verdict on this revision failed is checked-and-not-passed, not "waiting for a verdict".
        failed = [v['id'] for v in views if v['state'] == 'failed']
        left = [v['id'] for v in views if v['state'] not in ('passed', 'failed')]
        parts = (['mốc ' + ', '.join(failed) + ' kiểm chưa đạt (verdict gần nhất không đạt), chờ sửa và kiểm lại'] if failed else []) \
            + (['chờ verdict của mốc ' + ', '.join(left)] if left else [])
        return 'waiting', '; '.join(parts or ['chờ verdict của mốc']) + ' (root không có engine: chỉ theo dõi mốc)', \
            ['plan.approved'] + ['milestone.failed:' + m for m in failed]
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


def _item(reader, conn, row, now, *, full=False, timeline_limit=200, observe=None):
    """One root, read inside the caller's transaction `conn`. UI3: nothing here observes the project or opens a second ledger connection: `rd`
    joins `conn`, and the comparisons with the project come from `observe` (made by _observed between rounds, with no transaction open, through
    `free`). Without `observe` nothing is compared (current unknown)."""
    rd = _Joined(reader.state_root, row['project_id'], row['project_path'], conn)
    free = report._Reader(reader.state_root, row['project_id'], row['project_path'])
    if observe is None: observe = _Observations(now, final=True)
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
    views, current, compared_at = [], None, None
    root_key, sig = _compared_key(reader.state_root, row), _compared_sig(state, events)
    if contract and not engine_root:
        try:
            if not observe.comparison:
                views, current = plans.milestone_views(contract, state, state['latest']), 'copy'
            elif full:
                got = observe.get(('live',) + root_key, sig, lambda: _live_views(free, contract, state))
                if got is None:                     # not at hand in this read: what the page shows when the project could not be compared
                    views, current = _unknown_views(contract, state), 'unknown'
                else:
                    (views, current), compared_at = _taken(got)
                    _remember_compared(reader.state_root, row, state, events, views, current, compared_at)
            else:
                recalled = _recall_compared(reader.state_root, row, state, events)     # D4: the task page's last comparison, never a new hash
                if recalled: views, current, compared_at = recalled
                else: views = _ledger_views(observe, free, contract, state, root_key, sig)
        except (LedgerError, OSError, ValueError, KeyError): views = []
    gaps = _receipt_gaps(reader.state_root, state, views, engine_view)
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
    # R7-2: work has begun once a node started, an attempt exists or a milestone check ran or was recorded (a failed one included, any
    # revision). A milestone-only root never writes node.started. Started is not progress toward acceptance: acceptance keeps its own rule.
    has_started = first_started is not None or bool(attempts) or bool(state.get('verdicts')) or bool(runs)
    acceptance = _acceptance(rd, conn, state, contract, engine_view, level, free=free, observe=observe, key=root_key, sig=sig)
    live = acceptance.pop('views', None)
    if live is not None and not engine_root:
        views = live
        _receipt_gaps(reader.state_root, state, views, None)        # OBS-2C: the live views too (the gaps were reported above)
        level = _level(state, engine_view, views)       # UX 13/11 (B1): the overview said "đã kiểm" while the milestones it shows need a recheck
    for v in views:         # #58: why the last check did not pass, from its receipt (the line `plan report` prints under "Vì sao")
        if (v.get('last_verdict') or {}).get('result') not in (None, 'pass'):
            try: v['last_reason'] = clean(report._receipt_reason({'state_root': reader.state_root}, v), 300)
            except (LedgerError, OSError, ValueError, KeyError, TypeError): v['last_reason'] = None
    guidance = acceptance.get('next_action')
    if engine_view is not None and guidance is None:
        from . import engine
        try: guidance = engine.next_action(rd, state['selector'], conn=conn, view=engine_view, observe_project=False)
        except (LedgerError, OSError, ValueError, KeyError, TypeError): pass
    kind, reason, sources = _status(state, engine_view, attempts, progress, open_waits, requests, views, runs, level, first_started, acceptance, guidance)
    if guidance and guidance.get('delivery_limit') and state['status'] == 'approved' and kind != 'done':
        reason += '; bàn giao: ' + guidance['delivery_limit']
    last = events[-1] if events else None
    nodes = {}
    if engine_view is not None:
        # NHANVAI: the role label, the sub-tasks still waited for (engine state, in declared order), and the roles-table report of the
        # node (option nhan-co-vung: {'kind': 'outside_area' | 'role_not_in_table', 'paths'}; None when nothing is reported)
        role_notes = {e['node']: {'kind': e['kind'], 'paths': [clean(p, 200) for p in e['paths'][:20]]} for e in engine_view.get('role_area_report') or []}
        for nid, r in engine_view['nodes'].items():
            nodes[nid] = {'generation': r.get('generation'), 'phase': r.get('phase'), 'state': r.get('state') or 'none', 'attempt': r.get('attempt'), 'child': r.get('child'),
                          'reason': clean(r.get('reason'), 200), 'classification': clean(r.get('classification'), 100),
                          'receipt': r.get('receipt'), 'verification_receipt': r.get('verification_receipt'), 'verification_result': r.get('verification_result'),
                          'continues': r.get('continues'), 'resume_artifact': r.get('resume_artifact'), 'retained_candidate': r.get('retained_candidate'),
                          'progress': progress.get(nid),
                          'role': clean(r.get('role'), 40), 'waits_for': list(r.get('waits_for') or []), 'role_area': role_notes.get(nid)}
    counts = {'total': len(nodes), 'pending': 0, 'running': 0, 'held': 0, 'produced': 0, 'verified': 0, 'accepted': 0}
    for r in nodes.values():
        if r['phase'] in counts: counts[r['phase']] += 1
        if r['state'] in counts: counts[r['state']] += 1
    outcome = _outcome(state, kind, level)
    stopped_now = kind == 'blocked' and (state['status'] == 'stopped_with_report' or (guidance or {}).get('state') == 'stopped')    # the fifth state: nothing runs until the owner decides; a block has a next step
    active_rows = [{'attempt': a['id'], 'status': a['status'], 'since': a['created_at'], 'unit': a['unit'], 'stage': a['stage'],
                    'node': next((nid for nid, r in nodes.items() if r['attempt'] == a['id']), None)} for a in attempts if a['status'] in ('reserved', 'running', 'unknown')]
    from . import step0
    advice_pending = contract and state['status'] == 'proposed' and step0.advice_pending(
        rd, contract, state['revisions'][state['latest']]['sha'], state['advice'].get(state['latest']))
    needs = _needs_user(state, requests, views, level, engine_view, project=row['project_path'], state_root=str(reader.state_root),
                        contract=contract, acceptance=acceptance, comparison=observe.comparison, advice_pending=advice_pending)
    from . import tracking_situation
    checks = None
    if engine_view is None and views:
        from . import verdict as verdicts
        checks = tracking_situation.milestone_checks(views, history, state['latest'], now, lambda run: verdicts.lost_reason(run, now, verdicts.process_alive))
    situation = tracking_situation.situation(state=state, views=views, checks=checks, engine_view=engine_view, attempts=attempts, active=active_rows,
                                             requests=requests, needs=needs, acceptance=acceptance, level=level, has_started=has_started,
                                             guidance=guidance, status_kind=kind, status_reason=reason, progress=progress)
    item = {'id': row['id'], 'plan': state['name'], 'selector': row['request_key'], 'project': row['project_path'], 'project_id': row['project_id'],
            'goal': _goal(contract, payload), 'title': clean(payload.get('title'), 200), 'owner_view': _owner_view(contract), 'contract_revision': state['latest'],
            'headline': clean((contract or {}).get('title'), 200),     # mep6: the owner's line for the card; the AI's restated goal stays in 'goal'
            'short_title': short_title((contract or {}).get('title') or payload.get('title')),     # #58: the card's line; the full title stays in 'headline'
            'row_title': row_title(_owner_view(contract)['request'], (contract or {}).get('title') or payload.get('title')),   # UI58 MC: the row's one-line name
            'validity': tracking_situation.validity(state, views, (checks or {}).get('rows'), engine_view, current, as_of=compared_at, reused=not full),
            'compared': current,
            'compared_at': compared_at,          # UI58 MC: when the views were compared with the project (the list: the task page's last comparison, or None)
            'compared_by': ('task_page' if compared_at else None) if not engine_root else None,
            'created_at': row['created_at'], 'started_at': first_started, 'has_started': has_started, 'deadline': None,
            'node_titles': {n['id']: clean(n.get('goal'), 200) for n in ((engine_view or {}).get('definition') or {}).get('nodes', [])},
            'root_status': state['status'],
            'status': {'kind': kind, 'label': OUTCOME_WORDS[outcome] if outcome else (STOPPED_WORD if stopped_now else WORDS[kind]), 'outcome': outcome, 'reason': clean(reason, 600), 'source': sources},
            'level': {'kind': level, 'label': LEVEL_WORDS[level]},
            'elapsed': _elapsed(state, events, now),
            'current_step': clean((STOPPED_WORD + ': ' + reason if stopped_now and state['status'] != 'stopped_with_report' else _current_step(kind, state, engine_view, active_rows, requests, progress)) or reason, 200),
            'acceptance': acceptance,
            'next_action': guidance,
            'last_update': {'seq': last[0], 'kind': last[1], 'at': last[3], 'summary': clean(_summary(last[1], last[2]), 200)} if last else None,
            'last_evidence': _last_evidence(events),
            'needs_user': needs,
            'situation': situation,
            'active': active_rows,
            'nodes_summary': counts,
            'tracking': {'adapter': 'engine' if engine_root else 'milestones',
                         'coverage': ('root sequential-engine: node / thế hệ / attempt / quan sát tiến độ' if engine_root
                                      else 'root không có engine: chỉ mốc và verdict, không có attempt hay quan sát tiến độ'),
                         'errors': [e for e in (contract_error and 'hợp đồng: ' + contract_error, engine_error and 'engine: ' + engine_error) if e]},
            'milestones': [{'id': v['id'], 'title': clean(v['title'], 120), 'state': v['state'], 'stale': bool(v.get('stale')),
                            'result': (v.get('last_verdict') or {}).get('result'), 'reason': v.get('last_reason'),
                            'evidence_status': v.get('evidence_status'), 'evidence_reason': v.get('evidence_reason'),
                            **({'needs_recheck': True, 'state_text': 'cần kiểm lại', 'note': v.get('recheck_note')} if v.get('needs_recheck') else {}),
                            **({'current_unknown': True, 'note': tracking_situation.CURRENT_UNKNOWN} if v.get('current_unknown') else {})}
                           for v in views],
            'capabilities': list(state.get('capabilities') or ()),
            'origin': tracking_list.origin(state, contract, contract_error),      # OBS-2C: who asked for it, from ledger records only
            'evidence_gaps': gaps,
            'read_only': True}
    if not full: return item
    if contract:
        from . import goal_history
        item['goal_history_lines'] = goal_history.lines(goal_history.view(rd, state, state['latest'], contract))
        for need in needs:
            if need['kind'] == 'approve':
                need['goal_history_lines'] = item['goal_history_lines']
    item['milestone_checks'] = checks
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
    recheck = {v['id'] for v in views if v.get('stale') or v.get('needs_recheck')} if engine_view is None else set()
    item['work'] = tracking_work.project(rd, conn, row, state, events, engine_view, item['evidence_keys'], recheck=recheck)
    # dev11: the stdout/stderr a command receipt of this root names open where the receipt does (track evidence opens them one hop through it)
    named_outputs = {k for r in ((item['work'] or {}).get('checks') or {}).get('runs', []) if r.get('outputs') and r.get('receipt') in present
                     for k in (r['outputs']['stdout'], r['outputs']['stderr'])}
    if named_outputs - present:
        item['evidence_keys'] = sorted(present | {k for k, v in _stored(reader.state_root, named_outputs).items() if v})
    item['relations'] = tracking_list.relations(rd, conn, row, state, events, item, item['work'])     # OBS-2C: sourced relations, display only
    return item


RECEIPT_GONE = 'receipt của lần kiểm đạt không còn trong kho bằng chứng: không tính là đã kiểm; cần kiểm lại'


def _receipt_gaps(state_root, state, views, engine_view):
    """OBS-2C: a pass whose receipt is not in the store is not counted as checked (a missing receipt is never green). A milestone view is
    marked needs_recheck (the situation model words it "cần kiểm lại") unless the plan has ended (accepted / closed keep their history);
    an engine node is reported only (its outputs are judged on their receipts in tracking_work). Returns the gaps [{milestone|node, receipt}]."""
    from ..snapshots import Snapshots
    root = Snapshots(state_root).root
    def gone(key): return not (isinstance(key, str) and HEX64.fullmatch(key) and (root / 'blobs' / key).is_file())
    gaps, ended = [], state.get('status') in ('accepted', 'closed')
    for v in views:
        receipt = (v.get('last_verdict') or {}).get('receipt')
        if v.get('state') == 'passed' and gone(receipt):
            gaps.append({'milestone': v['id'], 'receipt': receipt if isinstance(receipt, str) else None, 'note': RECEIPT_GONE})
            if not ended: v.update(state='pending', stale=True, needs_recheck=True, receipt_missing=True, recheck_note=RECEIPT_GONE)
    for nid, r in ((engine_view or {}).get('nodes') or {}).items():
        if r.get('state') in ('verified', 'accepted') and gone(r.get('verification_receipt')):
            key = r.get('verification_receipt')
            gaps.append({'node': nid, 'receipt': key if isinstance(key, str) else None, 'note': 'receipt kiểm của phần việc không còn trong kho'})
    return gaps


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

def _untracked(conn, rows, state_root, projects_seen, children=frozenset(), *, project_id=None, seen_ids=frozenset(), comparison=True):
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
    if not comparison:
        return {'statement': STATEMENT, 'other_tasks': v1, 'registry_projects_without_plan': [], 'registry': None, 'hook_sessions': []}
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

def overview(state_root, *, project_id=None, now=None, reuse_seconds=0, comparison=True):
    """The list: every plan root of the state root (or of one project), grouped by project, with its sourced status; plus what is not tracked.
    A project scope covers the whole model (untracked registry included); everything returned passed the outbound guard. `reuse_seconds` (the
    server's polls): a project observation of a root whose ledger is unchanged is reused for that long (UI3)."""
    return outward(_overview(state_root, project_id=project_id, now=now, reuse_seconds=reuse_seconds, comparison=comparison))


def _overview_shell(state_root, now, source):
    """The overview model before any root is read (also the shape of an OBS-2C list page, tracking_list.page)."""
    return {'kind': 'onecrew-tracking-overview', 'version': VERSION, 'generated_at': _iso(now), 'state_root': str(Path(state_root).resolve()),
            'read_only': True, 'controls': CONTROLS, 'source': source, 'projects': [], 'tasks_total': 0,
            'coverage': {'engine': 'root sequential-engine: node / thế hệ / attempt / quan sát tiến độ / chờ',
                         'milestones': 'root không engine: mốc và verdict', 'other': 'task ngoài plan: phase checkpoint v1',
                         'external': STATEMENT},
            'untracked': {'statement': STATEMENT, 'other_tasks': [], 'registry_projects_without_plan': [], 'hook_sessions': []}}


def _unreadable(row, error):
    """The list entry of a root whose item could not be read: counted and shown as unknown, never dropped."""
    return {'id': row['id'], 'plan': clean(row['request_key'], 100), 'selector': row['request_key'], 'project': row['project_path'], 'project_id': row['project_id'],
            'goal': None, 'root_status': UNKNOWN, 'status': {'kind': 'unknown', 'label': WORDS['unknown'], 'reason': 'không đọc được: ' + clean(str(error), 200), 'source': []},
            'level': {'kind': 'none', 'label': LEVEL_WORDS['none']}, 'elapsed': {'seconds': UNKNOWN}, 'needs_user': [], 'active': [], 'last_update': None,
            'last_evidence': None, 'nodes_summary': {}, 'tracking': {'adapter': UNKNOWN, 'coverage': 'lỗi đọc', 'errors': [clean(str(error), 200)]},
            'situation': {'stage': 'unknown', 'label': 'Chưa xác định', 'reason': 'Không đọc được việc này trong sổ', 'next': None, 'next_by': None,
                          'next_by_text': None, 'activity': {'running': False, 'text': 'Không đọc được hoạt động', 'since': None}, 'milestones': None,
                          'no_owner_decision': True, 'source': []},
            'origin': {'source': 'unknown', 'label': 'Chưa rõ nguồn', 'why': 'không đọc được việc này trong sổ', 'basis': [], 'request': None},
            'read_only': True}


def _overview(state_root, *, project_id=None, now=None, reuse_seconds=0, rhythm=False, comparison=True):
    now = _now(now)
    reader, source = _source(state_root)
    if source['status'] != 'ok': return _overview_shell(state_root, now, source)
    return _observed(lambda observe: _overview_read(state_root, reader, dict(source), project_id, now, observe, rhythm),
                     now, reuse_seconds, comparison=comparison)


def _overview_read(state_root, reader, source, project_id, now, observe, rhythm=False):
    """One round of the overview: one short read transaction; the project observations it needs are made by _observed after it closes (UI3)."""
    result = _overview_shell(state_root, now, source)
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
                    item = _item(reader, conn, row, now, observe=observe)
                except (LedgerError, OSError, ValueError, KeyError, TypeError) as error:
                    item = _unreadable(row, error)
                projects.setdefault(row['project_path'], []).append(item)
            result['projects'] = [{'path': path, 'tasks': items} for path, items in projects.items()]
            result['tasks_total'] = sum(len(p['tasks']) for p in result['projects'])
            if rhythm:
                from .tracking_dashboard import check_days, repair_rounds
                from .tracking_sessions import KINDS
                result['check_days'] = check_days(conn, projects, now)
                result['repair_rounds'] = repair_rounds(conn, projects, now)
                result['session_tasks'] = {r['task_id']: r['n'] for r in conn.execute(
                    "SELECT e.task_id, count(DISTINCT json_extract(e.payload,'$.session')) AS n "
                    "FROM events e JOIN tasks t ON t.id=e.task_id WHERE e.kind IN (?,?,?,?) "
                    "AND json_type(e.payload,'$.session')='text' AND json_extract(e.payload,'$.session')<>'' "
                    "AND (? IS NULL OR t.project_id=?) GROUP BY e.task_id", (*KINDS, project_id, project_id))}
            seen_ids = {item.get('project_id') for items in projects.values() for item in items}
            result['untracked'] = _untracked(conn, rows, reader.state_root, {p.casefold() for p in projects}, children,
                                             project_id=project_id, seen_ids=seen_ids, comparison=observe.comparison)
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


def detail(state_root, selector, *, project_id=None, now=None, timeline_limit=200, reuse_seconds=0, comparison=True):
    """One root in full: nodes, attempts, requests, waits, notices, measured spans (union), ETA or unknown, holds, timeline, evidence keys.
    Everything returned passed the outbound guard. `reuse_seconds` (the server's 2 s polls): the comparison with the project is reused while the
    root's ledger is unchanged and it is younger than that, shown with its own time (compared_at); 0 (CLI, tests): compared on every read (UI3)."""
    return outward(_detail(state_root, selector, project_id=project_id, now=now, timeline_limit=timeline_limit,
                           reuse_seconds=reuse_seconds, comparison=comparison))


def _detail(state_root, selector, *, project_id=None, now=None, timeline_limit=200, reuse_seconds=0, comparison=True):
    now = _now(now)
    reader, source = _source(state_root)
    if source['status'] != 'ok': raise LedgerError(source['detail'])

    def read(observe):          # UI3: a short read transaction per round; it stops at the first observation it lacks, made after it closes
        with reader.transaction() as conn:
            if conn is None: raise LedgerError('Sổ không mở được.')
            row = _find(conn, reader, selector, project_id)
            item = _item(reader, conn, row, now, full=True, timeline_limit=timeline_limit, observe=observe)
            item.update(kind='onecrew-tracking-detail', version=VERSION, generated_at=_iso(now), state_root=str(reader.state_root), controls=CONTROLS,
                        source=dict(source, last_seq=conn.execute('SELECT COALESCE(MAX(seq),0) FROM events').fetchone()[0]))
            return item
    return _observed(read, now, reuse_seconds, stop=True, comparison=comparison)


def head(state_root, selector, *, project_id=None, now=None, reuse_seconds=0, comparison=True):
    """UIMOCK D4: one root as the list reads it (situation, validity, milestones, needs; no timeline, evidence, work or live comparison with the
    project), for the task page's four tiles before the reader opens "Xem sâu". A comparison already made within the reuse window is shown
    with its own time; none is made here. Passed through the outbound guard."""
    now = _now(now)
    reader, source = _source(state_root)
    if source['status'] != 'ok': raise LedgerError(source['detail'])

    def read(observe):
        with reader.transaction() as conn:
            if conn is None: raise LedgerError('Sổ không mở được.')
            row = _find(conn, reader, selector, project_id)
            item = _item(reader, conn, row, now, observe=observe)
            item.update(kind='onecrew-tracking-head', version=VERSION, generated_at=_iso(now), state_root=str(reader.state_root), controls=CONTROLS,
                        source=dict(source, last_seq=conn.execute('SELECT COALESCE(MAX(seq),0) FROM events').fetchone()[0]))
            return item
    return outward(_observed(read, now, reuse_seconds, comparison=comparison))


def prewarm():
    """Import the modules a first read uses, before the server answers (a cold viewer otherwise compiles them inside the first request).
    Nothing is read or cached: no ledger, no project."""
    from . import engine, goal_history, install, tracking_situation, tracking_work, verdict  # noqa: F401
    from .verifiers import artifact, command  # noqa: F401


def _names(conn, root_id, key):
    """Does any non-noise event of the root or of its child tasks name `key` (the same membership as `detail`'s evidence_keys), over the
    FULL history whatever its length? The ledger stores payloads as JSON text, so only the events whose text contains the key are parsed."""
    children = sorted({r[0] for r in conn.execute("SELECT json_extract(payload,'$.child') FROM events WHERE task_id=? AND kind='node.started'", (root_id,)) if r[0]})
    tasks = [root_id] + children
    marks, noise = ','.join('?' for _ in tasks), ','.join('?' for _ in NOISE)
    for (payload,) in conn.execute(f'SELECT payload FROM events WHERE task_id IN ({marks}) AND kind NOT IN ({noise}) AND instr(payload, ?) > 0', tasks + list(NOISE) + [key]):
        if key in _keys_of(json.loads(payload)): return True
    return False


def _output_of(conn, state_root, root_id, key):
    """dev11: is `key` the stdout or stderr that a command receipt named by a check event of this root (or its child tasks) names? One hop only,
    through a sealed command receipt; the output of another root's receipt stays refused."""
    from ..snapshots import Snapshots
    from .tracking_work import command_outputs
    children = sorted({r[0] for r in conn.execute("SELECT json_extract(payload,'$.child') FROM events WHERE task_id=? AND kind='node.started'", (root_id,)) if r[0]})
    tasks = [root_id] + children
    marks, store, seen = ','.join('?' for _ in tasks), Snapshots(state_root), set()
    for (receipt,) in conn.execute(f"SELECT json_extract(payload,'$.receipt') FROM events WHERE task_id IN ({marks}) "
                                   "AND kind IN ('verdict.recorded','node.verification','verdict.receipt_issued')", tasks):
        if not isinstance(receipt, str) or not HEX64.fullmatch(receipt) or receipt in seen: continue
        seen.add(receipt)
        try: body = json.loads(store.read_blob(receipt))
        except (LedgerError, OSError, ValueError, TypeError): continue
        outputs = command_outputs(body)
        if outputs and key in (outputs['stdout'], outputs['stderr']): return True
    return False


def evidence(state_root, selector, key, *, project_id=None):
    """The text of one blob the root's events name (receipt, candidate, evidence), redacted line by line and capped; any other key is refused."""
    if not isinstance(key, str) or not HEX64.fullmatch(key): raise LedgerError('Mã bằng chứng không hợp lệ.')
    reader, source = _source(state_root)
    if source['status'] != 'ok': raise LedgerError(source['detail'])
    with reader.transaction() as conn:
        if conn is None: raise LedgerError('Sổ không mở được.')
        row = _find(conn, reader, selector, project_id)
        named = _names(conn, row['id'], key) or _output_of(conn, reader.state_root, row['id'], key)
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
            owner = t.get('owner_view') or {}
            if owner.get('present'): lines.append('    việc: ' + owner['request'][:160] + (' · xong bạn thấy: ' + ' '.join(owner['user_sees'])[:160] if owner.get('user_sees') else ''))
            else: lines.append('    (chưa có mô tả cho chủ)')
            if t.get('goal'): lines.append(('    mục tiêu kỹ thuật: ' if owner.get('present') else '    mục tiêu: ') + t['goal'][:160])
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
