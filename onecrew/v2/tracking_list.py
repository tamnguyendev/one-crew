"""OBS-2C: the work list and its history — every plan root of the scope in ONE stable order, searched and filtered on the ledger, a page at
a time, with where each piece of work came from (owner / AI / unknown) and the relations a producer recorded (repairs, child tasks,
revisions, approvals, the end). A projection of tracking.py's model: no second ledger, store or collector, no model call, no write; the
ledger is opened read-only (report._Reader) and everything returned passes tracking.outward.

Order and paging (R6). A root's place is its CREATION SEQ, the seq of its first event in the ledger: it never changes when events arrive,
so the order is newest work first and stable. A page answer covers the rows of the scan region [floor, top]: `floor` is the creation seq of
the last row the reader has loaded (inclusive), `more` asks for that many further matching rows below it. A poll sends the same floor with
more=0 and gets the same region again, read anew: a root created meanwhile appears on top (it is newer than every loaded row), and no row of
the region is lost or doubled, whatever events arrived in between. `total` (roots in scope), `matched` (after the ledger-side filters),
`shown`, `scanned` and `remaining` (matching rows below the region, not read yet) are the coverage; `complete` says nothing is left.

Filters. Text (`q`), project, source, time (created / updated / ended, an instant range) and the end state are judged on the cheap index
of every root, so a search finds a root that is not on the first page. A stage filter (the situation stage the page shows, `need`, `running`)
needs the full item; it is judged row by row while scanning, and `matched` is then only known once nothing remains (`matched_exact`).

Source (R3), from ledger records only, never guessed:
  owner    the first revision's author is owner/user (plan.proposed; an AI session cannot write that name: plan.refuse_owner_author), or the
           contract's origin names the owner with the owner's words (origin.by owner/user + quote);
  ai       the contract's origin names someone else as the one who asked (an AI or an agent);
  unknown  no origin in the contract and no owner author: who asked is not recorded ("chưa theo dõi"), even when an AI wrote the contract
           and the owner approved it (approved is not assigned).
Work an AI or the engine spawned inside a root (repair tasks prepared after a failed check, child tasks of the engine's nodes) is listed
under that root with its source and reason, counted once per id however many events name it; `spawned` filters the roots that have some.
The approval keeps its recorded session: ai_session False = a process that declared itself the owner, True = an AI session, anything else
(missing, 'unknown') = unknown — never read as AI. Split, merge, rename and work asked for in a chat have no producer record: "chưa theo dõi".
Ended is accepted (the owner's acceptance) or closed (an end, NOT a success); verified is not accepted; assigned is not executed.
"""
import datetime as dt
import json
import sqlite3

from ..ledger import LedgerError
from . import namespaces, plan as plans

PAGE, MAX_PAGE, SCAN_CAP = 50, 200, 300
OWNER = tuple(plans.OWNER_ACTORS)
SOURCES = ('owner', 'ai', 'unknown')
SOURCE_WORDS = {'owner': 'Chủ giao', 'ai': 'AI giao', 'unknown': 'Chưa rõ nguồn'}
SPAWNED = 'spawned'
SPAWNED_WORD = 'Có việc AI phát sinh (việc sửa, việc con)'
STAGES = ('need', 'running', 'recheck', 'inconclusive', 'idle', 'todo', 'doing', 'fix', 'check', 'accept', 'done', 'stopped', 'unknown', 'closed')
# UIMOCK D5: the six chips of the work list split every root once: waits for the owner, else the group of its situation stage
GROUPS = ('g_doing', 'g_check', 'g_todo', 'g_done')
STAGES = STAGES + GROUPS


def group(item):
    """'need' when the root waits for the owner, else 'doing', 'check', 'todo' or 'done' (the chips Đang làm, Chờ kiểm, Chưa bắt đầu, Xong)."""
    if item.get('needs_user'): return 'need'
    stage = (item.get('situation') or {}).get('stage') or 'unknown'
    if stage in ('done', 'closed'): return 'done'
    if stage in ('check', 'accept'): return 'check'
    if stage == 'todo': return 'todo'
    return 'doing'
NOT_COMPARED = ('Danh sách không băm từng dự án: việc chưa mở trang riêng thì kết quả kiểm chưa được so với bản hiện tại; '
                'việc đã mở dùng lần so gần nhất của trang việc, kèm thời điểm. Mở việc để so.')
ENDED = ('accepted', 'closed')
STATES = ('ended', 'open')
TIME_FIELDS = ('created', 'updated', 'ended')
NOT_TRACKED = 'chưa theo dõi'
ORDER_BASIS = ('Mới tạo trước. Thứ tự theo seq của sự kiện đầu tiên của việc trong sổ: không đổi khi có sự kiện mới, nên đọc thêm không làm '
               'trùng hay mất dòng; việc mới tạo hiện ở đầu danh sách.')
UNTRACKED_LINKS = ('Tách, gộp, đổi tên việc và việc được yêu cầu trong chat: sổ không có bản ghi nào của bên tạo ra chúng — ' + NOT_TRACKED +
                   '; trang không dựng lại lịch sử đó.')
COVERAGE_NOTE = ('Danh sách dựng từ mọi gốc plan trong sổ của phạm vi này (sổ giữ toàn bộ sự kiện, không cắt theo cửa sổ). Một việc không đọc '
                 'được vẫn được đếm và hiện là chưa xác định; bằng chứng đã mất khỏi kho hiện là không mở được trong chi tiết, và một lần kiểm '
                 'đạt mà receipt không còn trong kho không được tính là đã kiểm.')
LIST_KEYS = ('list', 'q', 'project', 'stage', 'source', 'time', 'since', 'until', 'floor', 'more', 'limit')
# what a spawned item is, in plain words (repair 1 of 14/11: a relation is never shown as its raw id alone)
KIND_WORDS = {'repair': 'Việc sửa', 'child': 'Phần việc con'}
REPAIR_STATES = {'verified': 'đã kiểm lại đủ phần ảnh hưởng', 'partial': 'mới kiểm lại một phần', 'unverified': 'chưa kiểm lại'}
ATTEMPT_STATES = {'reserved': 'đã giữ chỗ, chưa chạy', 'running': 'đang chạy', 'settled': 'lượt chạy đã kết thúc', 'unknown': 'kết quả lượt chạy chưa xác định',
                  'failed': 'lượt chạy lỗi', 'cancelled': 'lượt chạy đã dừng', 'abandoned': 'lượt chạy bị bỏ dở'}
NO_STATE = 'trạng thái chưa xác định'
NO_NAME = 'chưa có tên trong sổ'


def _short(value):
    return (value[:12] + '…') if isinstance(value, str) and len(value) > 12 else value


def _clean(value, limit=300):
    from .tracking import clean
    return clean(value, limit)


# ---- where a root came from ------------------------------------------------------------------------------------------------------------

def approval(record):
    """The recorded approval with its session as written: ai_session False / True / anything else = unknown (never read as AI)."""
    if not record: return {'state': 'none', 'label': 'chưa duyệt', 'session': None, 'session_label': None, 'by': None, 'revision': None}
    raw = record.get('ai_session', 'unknown')
    session = raw if raw is True or raw is False else 'unknown'
    words = {False: 'phiên tự khai là của chủ sở hữu', True: 'phiên AI', 'unknown': 'chưa rõ phiên (không khai báo; không suy là phiên AI)'}
    return {'state': 'approved', 'by': _clean(record.get('by'), 100), 'revision': record.get('revision'), 'session': session,
            'session_label': words[session], 'at': record.get('at') or record.get('recorded_at'),
            'label': f"{'chủ sở hữu' if record.get('by') in OWNER else _clean(record.get('by'), 100) or 'chưa rõ người'} duyệt bản {record.get('revision')} · {words[session]}",
            'source': f"plan.approved:rev{record.get('revision')}"}


def origin(state, contract, error=None):
    """Who asked for this root and in which words, from the first revision's author and the contract's origin (see the module doc)."""
    revisions = (state or {}).get('revisions') or {}
    first = revisions.get(min(revisions)) if revisions else {}
    author, content_author = first.get('author'), first.get('content_author')
    record = (contract or {}).get('origin') if isinstance((contract or {}).get('origin'), dict) else None
    by = record['by'].strip() if record and isinstance(record.get('by'), str) and record['by'].strip() else None
    quote = record.get('quote') if record and isinstance(record.get('quote'), str) and record['quote'].strip() else None
    if author in OWNER:
        source, why, basis = 'owner', 'chủ sở hữu là tác giả bản 1 của hợp đồng (một phiên AI không ghi được tên này)', ['plan.proposed:rev1.author']
    elif by and by.casefold() in OWNER and quote:
        source, why, basis = 'owner', 'hợp đồng ghi chủ sở hữu giao việc, kèm lời của chủ (origin)', ['contract.origin']
    elif by and by.casefold() not in OWNER:
        source, why, basis = 'ai', f'hợp đồng ghi người giao việc là {by}, không phải chủ sở hữu (origin)', ['contract.origin']
    else:
        source, basis = 'unknown', ['plan.proposed:rev1.author'] + (['contract.origin'] if contract else [])
        why = ('hợp đồng không ghi người giao việc (origin): ' + NOT_TRACKED + '; người viết hợp đồng ' + (str(author) if author else 'không được ghi')
               + ' — viết hay duyệt hợp đồng không phải là giao việc') if contract else ('không đọc được hợp đồng' + (f' ({error})' if error else '')
               + '; tác giả bản 1: ' + (str(author) if author else 'không được ghi') + ' — nguồn giao việc ' + NOT_TRACKED)
    shown = (contract or {}).get('presentation') or {}
    if quote: request, request_source = quote, 'contract.origin.quote'
    elif isinstance(shown.get('request'), str) and shown['request'].strip(): request, request_source = shown['request'], 'contract.presentation.request'
    elif isinstance((contract or {}).get('title'), str): request, request_source = contract['title'], 'contract.title'
    else: request, request_source = None, None
    return {'source': source, 'label': SOURCE_WORDS[source], 'why': _clean(why, 400), 'basis': basis,
            'request': _clean(request, 500), 'request_source': request_source,
            'request_note': {'contract.origin.quote': 'lời chủ được ghi trong hợp đồng (origin' + (', ' + _clean(record.get('at'), 40) if record and record.get('at') else '') + ')',
                             'contract.presentation.request': 'mô tả cho chủ do người viết hợp đồng soạn (không phải lời chủ)',
                             'contract.title': 'tên hợp đồng (không phải lời chủ)'}.get(request_source, 'yêu cầu ban đầu ' + NOT_TRACKED),
            'by': _clean(by, 100), 'author': _clean(author, 100), 'content_author': _clean(content_author, 100),
            'author_is_owner': author in OWNER, 'approval': approval((state or {}).get('approved'))}


# ---- what a root spawned ---------------------------------------------------------------------------------------------------------------

def children(events):
    """{child task id: first node.started that names it (node, generation, attempt, seq, at) + the seqs of later ones}: one entry per child."""
    out = {}
    for seq, kind, p, at in events:
        if kind != 'node.started' or not isinstance(p.get('child'), str) or not p['child']: continue
        if p['child'] in out: out[p['child']]['also'].append(seq); continue
        out[p['child']] = {'id': p['child'], 'node': p.get('node'), 'generation': p.get('generation'), 'attempt': p.get('attempt'),
                           'seq': seq, 'at': at, 'also': []}
    return out


def repairs(reader, events, root_id, limitations=None):
    """The repair rounds of a root as tracking_work._repairs reads them (one per repair key, an order-only rebinding inside its round),
    without the check receipts: the list counts them, the detail shows tracking_work's own rows with their rechecks."""
    from . import tracking_work
    blobs = tracking_work._Blobs(reader, limitations if limitations is not None else [])
    return tracking_work._repairs([e for e in events if e[1] == 'plan.revised'], root_id, blobs, {'runs': []}, None)


def relations(reader, conn, row, state, events, item, work):
    """The detail's "Nguồn và quan hệ": origin, revisions (author, reason, impact), approvals (session as recorded), what the root spawned
    (repairs with reason / failed check / affected parts / recheck, child tasks with their attempts), advice, the end — each with its event."""
    root = {'id': row['id'], 'plan': state['name'], 'project_id': row['project_id']}
    revisions, approvals, advice, end = [], [], [], None
    for seq, kind, p, at in events:
        if kind in ('plan.proposed', 'plan.amended'):
            diff = p.get('acceptance_diff') or {}
            revisions.append({'revision': p.get('revision'), 'kind': 'proposed' if kind == 'plan.proposed' else 'amended', 'at': at,
                              'author': _clean(p.get('author'), 100), 'content_author': _clean(p.get('content_author'), 100),
                              'author_is_owner': p.get('author') in OWNER,
                              'reason': _clean(p.get('reason'), 300) if kind == 'plan.amended' else None,
                              'impact': _clean(diff.get('summary'), 300), 'impact_kind': _clean(diff.get('classification'), 60),
                              'source': {'kind': kind, 'seq': seq, 'at': at}})
        elif kind == 'plan.approved':
            a = approval(dict(p, recorded_at=at))
            approvals.append(dict(a, reference=_clean(p.get('reference'), 200), source={'kind': kind, 'seq': seq, 'at': at}))
        elif kind == 'plan.advised':
            advice.append({'revision': p.get('revision'), 'at': at, 'by': _clean(p.get('by') or p.get('model') or p.get('provider'), 100),
                           'note': 'gợi ý của cố vấn: chỉ để tham khảo, không quyết định', 'source': {'kind': kind, 'seq': seq, 'at': at}})
        elif kind in ('plan.accepted', 'plan.closed'):
            end = {'kind': 'accepted' if kind == 'plan.accepted' else 'closed', 'at': p.get('at') or at, 'by': _clean(p.get('by'), 100),
                   'reason': _clean(p.get('reason') or p.get('reference'), 300), 'accepted': kind == 'plan.accepted',
                   'label': 'chủ sở hữu nghiệm thu' if kind == 'plan.accepted' else 'đã đóng — đóng không phải nghiệm thu, không phải thành công',
                   'source': {'kind': kind, 'seq': seq, 'at': at}}
    if end and end['kind'] == 'closed' and state.get('status') != 'closed': end = None     # a plan.closed the plan model does not count (no engine)
    spawned = []
    titles = {nid: (n or {}).get('title') for nid, n in ((work or {}).get('nodes') or {}).items()
              if (n or {}).get('title') and (n or {}).get('title') != nid}                         # the node goals of the definition (tracking_work); an id is no name
    for r in (work or {}).get('repairs') or []:
        node = r.get('node')
        spawned.append({'kind': 'repair', 'id': r.get('id'), 'label': KIND_WORDS['repair'], 'source_label': 'AI/engine phát sinh sau một lần kiểm không đạt',
                        'name': _clean(titles.get(node), 200) if titles.get(node) else None, 'name_source': 'plan.revised: tên phần việc được sửa' if titles.get(node) else None,
                        'node': node, 'reason': _clean(r.get('reason'), 400), 'failed_checks': [_clean(c, 100) for c in (r.get('failed_checks') or [])[:10]],
                        'from_check': {'seq': r.get('source_event'), 'receipt': r.get('source_receipt'), 'authentic': r.get('authentic_source')},
                        'affected_nodes': list(r.get('affected_nodes') or [])[:20], 'status': r.get('status'), 'applicable': r.get('applicable'),
                        'state': r.get('status'), 'state_label': REPAIR_STATES.get(r.get('status'), NO_STATE) + (' · lịch sử, không chứng nhận bản hiện hành' if r.get('applicable') is False else ''),
                        'rechecks': list(r.get('verification') or [])[:20], 'rebindings': len(r.get('rebindings') or []),
                        'short_id': _short(r.get('id')), 'opens': 'results', 'root': root, 'source': r.get('source')})
    kids = children(events)
    if kids:
        marks = ','.join('?' for _ in kids)
        payloads = {r['id']: json.loads(r['payload']) for r in conn.execute(f'SELECT id, payload FROM tasks WHERE id IN ({marks})', list(kids))}
        attempts = {}
        for a in (item or {}).get('attempts') or []:
            attempts.setdefault(a['task'], []).append({'id': a['id'], 'status': a['status'], 'generation': a['generation']})
        for cid, c in kids.items():
            body = payloads.get(cid) or {}
            name = body.get('title') or body.get('goal')
            runs = attempts.get(cid, [])
            latest = runs[-1]['status'] if runs else None              # the attempts table, in the order the ledger created them
            spawned.append({'kind': 'child', 'id': cid, 'label': KIND_WORDS['child'], 'source_label': 'engine tạo cho một phần việc (node.started)',
                            'name': _clean(name, 200) if isinstance(name, str) and name.strip() else None,
                            'name_source': 'tasks: tên của việc con' if isinstance(name, str) and name.strip() else None,
                            'node': c['node'], 'generation': c['generation'], 'attempt': c['attempt'],
                            'title': _clean(name, 200) if isinstance(name, str) and name.strip() else None, 'attempts': runs[:10],
                            'state': latest, 'state_label': ATTEMPT_STATES.get(latest, 'lượt chạy: ' + str(latest)) if latest else 'chưa có lượt chạy ghi nhận',
                            'known_task': cid in payloads, 'short_id': _short(cid), 'opens': 'progress',
                            'root': root, 'source': {'kind': 'node.started', 'seq': c['seq'], 'at': c['at']}, 'also': c['also'][:10]})
    return {'origin': (item or {}).get('origin'), 'root': root, 'revisions': revisions, 'approvals': approvals, 'spawned': spawned,
            'advice': advice, 'end': end,
            'counts': {'repairs': sum(1 for s in spawned if s['kind'] == 'repair'), 'children': sum(1 for s in spawned if s['kind'] == 'child'),
                       'revisions': len(revisions)},
            'parent': {'link': NOT_TRACKED, 'note': 'sổ không ghi việc này được tách hay sinh ra từ một việc gốc khác'},
            'not_tracked': UNTRACKED_LINKS,
            'basis': 'mỗi quan hệ lấy từ một sự kiện của chính việc này (seq ghi kèm); một việc con hay việc sửa được nhiều sự kiện nêu vẫn chỉ đếm một lần'}


# ---- the index of every root (cheap: no full item) ---------------------------------------------------------------------------------------

def _text(*parts):
    out = []
    for x in parts:
        if isinstance(x, str): out.append(x)
        elif isinstance(x, (list, tuple)): out += [y for y in x if isinstance(y, str)]
    return ' '.join(out).casefold()


def _index(reader, conn, roots):
    """One entry per root: creation seq, times, end, plan status, origin, spawned counts, pending questions and the search text."""
    from . import report, tracking
    ids = {r['id'] for r in roots}
    first, last_at, ends, started, revised, pending = {}, {}, {}, {}, {}, {}
    for r in conn.execute('SELECT task_id, MIN(seq) AS s FROM events GROUP BY task_id'):
        if r['task_id'] in ids: first[r['task_id']] = r['s']
    noise = ','.join('?' for _ in tracking.NOISE)
    for r in conn.execute(f'SELECT task_id, MAX(created_at) AS at FROM events WHERE kind NOT IN ({noise}) GROUP BY task_id', list(tracking.NOISE)):
        if r['task_id'] in ids: last_at[r['task_id']] = r['at']
    for r in conn.execute("SELECT task_id, kind, created_at FROM events WHERE kind IN ('plan.accepted','plan.closed') ORDER BY seq"):
        if r['task_id'] in ids: ends.setdefault(r['task_id'], {})[r['kind']] = r['created_at']
    for kind, into in (('node.started', started), ('plan.revised', revised)):
        for r in conn.execute('SELECT task_id, seq, payload, created_at FROM events WHERE kind=? ORDER BY seq', (kind,)):
            if r['task_id'] in ids: into.setdefault(r['task_id'], []).append((r['seq'], kind, json.loads(r['payload']), r['created_at']))
    for r in conn.execute("SELECT task_id, COUNT(*) AS n FROM requests WHERE state='pending' GROUP BY task_id"):
        if r['task_id'] in ids: pending[r['task_id']] = r['n']
    entries, readers = [], {}
    for row in roots:
        entry = {'row': row, 'id': row['id'], 'seq': first.get(row['id'], 0), 'created_at': row['created_at'], 'updated_at': last_at.get(row['id']),
                 'project': row['project_path'], 'project_id': row['project_id'], 'pending': pending.get(row['id'], 0), 'error': None}
        try:
            key = (row['project_id'], row['project_path'])
            rd = readers.get(key) or readers.setdefault(key, tracking._Joined(reader.state_root, row['project_id'], row['project_path'], conn))   # UI3: never a second connection
            state = plans.derive(rd, conn, row['request_key'])
            try: contract, error = plans.load(rd, state, state['latest'])[0], None
            except (LedgerError, OSError, ValueError) as e: contract, error = None, tracking.clean(str(e), 160)
            kids = children(started.get(row['id'], []))
            rounds = repairs(rd, revised.get(row['id'], []), row['id']) if revised.get(row['id']) else []
            status = state['status']
            end_kind = status if status in ENDED else None
            shown = (contract or {}).get('presentation') or {}
            o = origin(state, contract, error)
            payload = json.loads(row['payload']) if row.get('payload') else {}
            mine = None             # UI58 MC: a root whose next step is the owner's own check of an owner-manual milestone also waits for the owner
            if contract and status == 'approved' and not namespaces.has_capability(state, 'sequential-engine'):
                from .tracking_situation import owner_try
                try: mine = owner_try(plans.milestone_views(contract, state, state['latest']))
                except (LedgerError, OSError, ValueError, KeyError, TypeError): mine = None     # the row itself is still read in full when shown
            entry.update(plan=state['name'], status=status, contract_error=error, origin=o, owner_try=mine['id'] if mine else None,
                         ended=({'kind': end_kind, 'accepted': end_kind == 'accepted', 'at': (ends.get(row['id']) or {}).get('plan.' + end_kind)} if end_kind else None),
                         links={'repairs': len(rounds), 'children': len(kids), 'spawned': len(rounds) + len(kids)},
                         text=_text(state['name'], row['id'], (contract or {}).get('title'), ((contract or {}).get('understanding') or {}).get('restated_goal'),
                                    payload.get('title'), shown.get('request'), shown.get('user_sees'), shown.get('acceptance_steps'), shown.get('not_doing'),
                                    ((contract or {}).get('origin') or {}).get('quote') if isinstance((contract or {}).get('origin'), dict) else None,
                                    o.get('by'), o.get('author')))
        except (LedgerError, OSError, ValueError, KeyError, TypeError) as e:
            entry.update(plan=tracking.clean(row['request_key'], 100), status='unknown', contract_error=None, ended=None,
                         origin={'source': 'unknown', 'label': SOURCE_WORDS['unknown'], 'why': 'không đọc được việc này: ' + tracking.clean(str(e), 200),
                                 'basis': [], 'request': None, 'request_source': None, 'approval': approval(None)},
                         links={'repairs': 0, 'children': 0, 'spawned': 0}, text=_text(row['request_key'], row['id']), error=tracking.clean(str(e), 200))
        entries.append(entry)
    entries.sort(key=lambda e: (e['seq'], e['created_at'] or '', e['id']), reverse=True)
    return entries, {c for kids in started.values() for _, _, p, _ in kids for c in [p.get('child')] if c}


# ---- the filters ---------------------------------------------------------------------------------------------------------------------------

def _instant(value, name):
    from .tracking import _at
    if value in (None, ''): return None
    text = str(value).strip()
    if len(text) == 10: text += 'T00:00:00+00:00'                 # a bare date is that day at 00:00 UTC; the page sends local midnights as instants
    at = _at(text)
    if at is None: raise ValueError(f'{name}: thời điểm ISO 8601 hoặc ngày YYYY-MM-DD')
    return at


def _int(value, name, low, high, default):
    if value in (None, ''): return default
    try: number = int(value)
    except (TypeError, ValueError): raise ValueError(f'{name}: số nguyên {low}-{high}') from None
    if not low <= number <= high: raise ValueError(f'{name}: số nguyên {low}-{high}')
    return number


def params(query):
    """The list parameters of a request (query string dict); ValueError on a value outside the allowed set."""
    q = query or {}
    stage = q.get('stage') or None
    if stage is not None and stage not in STAGES + STATES: raise ValueError('stage: ' + ', '.join(STAGES + STATES))
    source = q.get('source') or None
    if source is not None and source not in SOURCES + (SPAWNED,): raise ValueError('source: owner, ai, unknown, spawned')
    time = q.get('time') or 'created'
    if time not in TIME_FIELDS: raise ValueError('time: ' + ', '.join(TIME_FIELDS))
    floor = q.get('floor')
    return {'q': str(q.get('q') or '').strip()[:200], 'project': q.get('project') or None, 'stage': stage, 'source': source, 'time': time,
            'since': _instant(q.get('since'), 'since'), 'until': _instant(q.get('until'), 'until'),
            'floor': None if floor in (None, '') else _int(floor, 'floor', 0, 1 << 62, 0),
            'more': _int(q.get('more'), 'more', 0, MAX_PAGE, 0), 'limit': _int(q.get('limit'), 'limit', 1, MAX_PAGE, PAGE)}


def _cheap(entry, f):
    from .tracking import _at
    project = f['project']
    if project and project.startswith('repo:'):
        if entry['project_id'] not in project[5:].split(','): return False
    elif project and entry['project'] != project: return False
    if f['q'] and f['q'].casefold() not in entry['text']: return False
    if f['source'] == SPAWNED:
        if not entry['links']['spawned']: return False
    elif f['source'] and entry['origin']['source'] != f['source']: return False
    if f['stage'] == 'ended' and not entry['ended']: return False
    if f['stage'] == 'open' and entry['ended']: return False
    if f['since'] or f['until']:
        when = _at({'created': entry['created_at'], 'updated': entry['updated_at'], 'ended': (entry['ended'] or {}).get('at')}[f['time']])
        if when is None or (f['since'] and when < f['since']) or (f['until'] and when >= f['until']): return False
    return True


def _stage_ok(item, stage, now=None):
    if stage in (None,) + STATES: return True
    if stage == 'need': return bool(item.get('needs_user'))
    if stage in GROUPS: return group(item) == stage[2:]
    situation = item.get('situation') or {}
    if stage == 'inconclusive': return situation.get('label') == 'Chưa kết luận'
    if stage == 'idle':
        from .tracking import _at
        updated = _at((item.get('last_update') or {}).get('at') or item.get('created_at'))
        return bool(updated and now and situation.get('stage') not in ('done', 'closed') and now - updated > dt.timedelta(days=3))
    if stage == 'running': return bool((situation.get('activity') or {}).get('running'))
    if stage == 'recheck': return (item.get('validity') or {}).get('kind') == 'recheck' or situation.get('label') == 'Cần kiểm lại'   # UI58 MC: the card's word
    return (situation.get('stage') or 'unknown') == stage


def _public(entry):
    return {'seq': entry['seq'], 'updated_at': entry['updated_at'], 'ended': entry['ended'], 'links': entry['links'], 'origin_source': entry['origin']['source']}


# ---- public ----------------------------------------------------------------------------------------------------------------------------------

def page(state_root, query=None, *, project_id=None, now=None, reuse_seconds=0, comparison=True):
    """The overview model of one list request (tracking.overview's shape: `projects` hold the rows of the scan region only) plus `list`: order,
    coverage, filters, counts, the next cursor and the roots outside the region that wait for the owner. Passed through the outbound guard.
    `reuse_seconds` (the server's polls): a project observation of a root whose ledger is unchanged is reused for that long (UI3)."""
    from .tracking import outward
    return outward(_page(state_root, params(query), project_id=project_id, now=now, reuse_seconds=reuse_seconds, comparison=comparison))


def _page(state_root, f, *, project_id=None, now=None, reuse_seconds=0, comparison=True):
    """UI3: each round is one short read transaction; the project observations a round needs are made after it closes (tracking._observed)."""
    from . import tracking
    now = tracking._now(now)
    reader, source = tracking._source(state_root)
    return tracking._observed(lambda observe: _page_read(state_root, f, reader, dict(source), project_id, now, observe),
                              now, reuse_seconds, comparison=comparison)


def _page_read(state_root, f, reader, source, project_id, now, observe):
    from . import tracking
    listed = {'order': 'created_seq_desc', 'order_basis': ORDER_BASIS, 'total': 0, 'matched': 0, 'matched_exact': True, 'scanned': 0, 'shown': 0,
              'remaining': 0, 'floor': 0, 'next_cursor': None, 'complete': True, 'limit': f['limit'], 'as_of_seq': None,
              'filters': {k: (tracking._iso(v) if isinstance(v, dt.datetime) else v) for k, v in f.items()},
              'counts': {}, 'projects': [], 'unreadable': 0, 'attention_outside': {'count': 0, 'items': []},
              'coverage': COVERAGE_NOTE, 'not_tracked': UNTRACKED_LINKS, 'read_only': True}
    result = tracking._overview_shell(state_root, now, source)
    result['list'] = listed
    if source['status'] != 'ok': return result
    try:
        with reader.transaction() as conn:
            if conn is None:
                source.update(status='missing', detail='sổ không mở được'); return result
            rows = tracking._rows(conn, project_id)
            source['last_seq'] = listed['as_of_seq'] = conn.execute('SELECT COALESCE(MAX(seq),0) FROM events').fetchone()[0]
            source['schema_version'] = tracking._schema_version(conn)
            roots = [r for r in rows if r['request_key'].startswith((namespaces.LEGACY, namespaces.NAMESPACED))]
            entries, kids = _index(reader, conn, roots)
            listed['total'] = len(entries)
            listed['unreadable'] = sum(1 for e in entries if e['error'])
            listed['counts'] = {'source': {s: sum(1 for e in entries if e['origin']['source'] == s) for s in SOURCES},
                                'spawned': sum(1 for e in entries if e['links']['spawned']),
                                'ended': sum(1 for e in entries if e['ended']), 'accepted': sum(1 for e in entries if (e['ended'] or {}).get('kind') == 'accepted'),
                                'closed': sum(1 for e in entries if (e['ended'] or {}).get('kind') == 'closed')}
            paths = {}
            for e in entries: paths.setdefault(e['project'], {'path': e['project'], 'project_id': e['project_id'], 'tasks': 0})['tasks'] += 1
            listed['projects'] = list(paths.values())
            stage = f['stage'] if f['stage'] in STAGES else None
            candidates = [e for e in entries if _cheap(e, f)]
            listed['matched'] = len(candidates)
            floor = f['floor']
            region = [e for e in candidates if floor is not None and e['seq'] >= floor]
            below = [e for e in candidates if floor is None or e['seq'] < floor]
            wanted = f['limit'] if floor is None else f['more']
            items, scanned, found, bottom = [], 0, 0, floor
            groups = dict.fromkeys(('need', 'doing', 'check', 'todo', 'done'), 0)
            def read(entry):
                try: item = tracking._item(reader, conn, entry['row'], now, observe=observe)
                except (LedgerError, OSError, ValueError, KeyError, TypeError) as error: item = tracking._unreadable(entry['row'], error)
                item['list'] = _public(entry)
                groups[group(item)] += 1
                return item
            for e in region:
                item = read(e); scanned += 1
                if _stage_ok(item, stage, now): items.append(item)
            extra = 0
            for e in below:
                if found >= wanted or extra >= SCAN_CAP: break
                item = read(e); scanned += 1; extra += 1; bottom = e['seq']
                if _stage_ok(item, stage, now): items.append(item); found += 1
            left = [e for e in candidates if e['seq'] < bottom] if bottom is not None else []     # matching rows below the region, not read
            validity = [(i.get('validity') or {}) for i in items]       # UI58 MC: how many shown results were compared with the project, and when
            listed['validity'] = {'not_compared': sum(1 for v in validity if v.get('kind') == 'not_compared'),
                                  'reused': sum(1 for v in validity if v.get('compared')), 'recheck': sum(1 for v in validity if v.get('kind') == 'recheck'),
                                  'note': NOT_COMPARED}
            listed.update(scanned=scanned, shown=len(items), remaining=len(left), complete=not left,
                          floor=bottom if left else 0, next_cursor=bottom if left else None,
                          matched_exact=stage is None or not left, stage_matched=len(items) if stage else None)
            if stage and not left: listed['matched'] = len(items)
            # UIMOCK D5: the chips' counts over every root read for this answer; exact when nothing matching was left unread
            listed["groups"] = dict(groups, all=sum(groups.values()), exact=not left, scanned=scanned)
            outside = [e for e in entries if left and e['seq'] < bottom and (e['status'] in ('proposed', 'stopped_with_report') or e['pending'] or e.get('owner_try'))]
            listed['attention_outside'] = {'count': len(outside), 'items': [
                {'plan': e['plan'], 'id': e['id'], 'project': e['project'], 'project_id': e['project_id'],
                 'why': 'chờ bạn trả lời ' + str(e['pending']) + ' câu hỏi' if e['pending'] else 'chờ bạn duyệt' if e['status'] == 'proposed'
                        else 'dừng có báo cáo, chờ bạn quyết định' if e['status'] == 'stopped_with_report' else 'chờ bạn thử và ghi kết quả mốc ' + str(e['owner_try'])}
                for e in outside[:10]],
                'note': 'việc cũ hơn phần đã tải đang chờ bạn (theo sổ: chờ duyệt, câu hỏi chưa trả lời, dừng có báo cáo, mốc chờ bạn tự thử); chọn lọc "Cần bạn quyết định" để đọc đủ'}
            projects = {}
            for item in items: projects.setdefault(item['project'], []).append(item)
            result['projects'] = [{'path': path, 'tasks': group} for path, group in projects.items()]
            result['tasks_total'] = len(entries)
            seen = {e['project'].casefold() for e in entries}
            result['untracked'] = tracking._untracked(conn, rows, reader.state_root, seen, kids, project_id=project_id,
                                                      seen_ids={e['project_id'] for e in entries}, comparison=observe.comparison)
    except (LedgerError, sqlite3.Error, OSError) as error:
        source.update(status='unreadable', detail=tracking.clean(str(error), 300))
    return result
