"""W24/W24b: plan notices projected into the existing v1 delivery outbox.

observe is the only writer: it appends neutral notice.exception evidence, never
requests, answers, approvals or runtime effects. Projection is read-only. Delivery
and window acknowledgements remain entirely owned by v1's outbox.
"""
import datetime as dt
import json
from pathlib import Path

from ..ledger import LedgerError, canonical, content_hash, utcnow
from . import estimates, namespaces, plan, report

KIND = 'notice.exception'
EVENTS = ('plan.proposed', 'plan.amended', 'milestone.stopped', 'milestone.passed',
          'request.created', 'request.revised', KIND)


def _time(value=None):
    value = value or utcnow()
    try:
        parsed = value if isinstance(value, dt.datetime) else dt.datetime.fromisoformat(value)
        if parsed.tzinfo is None: raise ValueError('timezone required')
        return parsed
    except (TypeError, ValueError) as error:
        raise LedgerError('Notice time requires an ISO timestamp with timezone.') from error


def _eta(forecast):
    return {'remaining_seconds': forecast.get('remaining_seconds'), 'calibrated': False,
            'waiting_seconds': forecast.get('waiting_seconds', 'unknown'),
            'remaining_kind':forecast.get('remaining_kind','execution_work'),
            'wall_clock_remaining_seconds':forecast.get('wall_clock_remaining_seconds'),
            'wall_clock_reason':forecast.get('wall_clock_reason','Elapsed-time forecast is unknown.')}


def _requests(conn, task):
    return [dict(r, question=json.loads(r['payload'])) for r in
            conn.execute("SELECT * FROM requests WHERE task_id=? AND state='pending' ORDER BY created_at,id", (task,))]


def _u2(request):
    return request['question'].get('action', {}).get('parameters', {}).get('class') == 'U2'


def _notices(conn, task):
    return [dict(json.loads(r['payload']), event=r['seq'], event_at=r['created_at']) for r in
            conn.execute('SELECT seq,payload,created_at FROM events WHERE task_id=? AND kind=? ORDER BY seq', (task, KIND))]


def _exceedance(notice):
    """W24b: the baseline exceedance a baseline notice reports (category + baseline event), or None.

    Older notices carry no `exceedance` field; their first evidence is the baseline event."""
    if notice.get('category') != 'baseline' or 'baseline_upper_exceeded' not in notice.get('triggers', []): return None
    return notice.get('exceedance') or 'baseline_upper:' + notice['evidence'][0].removeprefix('event:')


def _previous_upper(forecast):
    """Remaining range immediately before the newest forecast/additional event."""
    history = forecast['history']
    additions = [p for p in forecast['additional'] if p['category'] == 'mandatory']
    changes = history + additions
    if not changes: return None
    latest = max(changes, key=lambda p: p['event'])
    earlier = [p for p in history if p['event'] < latest['event']]
    previous = earlier[-1] if earlier else forecast['baseline']
    if not previous: return None
    span = previous.get('remaining_seconds', previous.get('execution_seconds'))
    if span is None: return None
    return span[1] + sum(p['execution_seconds'][1] for p in additions
                         if previous['event'] < p['event'] < latest['event'])


def observe(ledger, selector, now=None):
    """Record each sourced exception once per root/category/cause, post-commit.

    Significance is exceeding the approved upper bound OR its declared relative
    change threshold against the previous remaining range. Missing
    execution observations are not treated as zero; remaining time alone can
    establish an exceedance, but unknown remaining time cannot fabricate an ETA.
    The baseline deadline is the promised time for the final contract milestone.
    U2 notices reference existing typed requests; this function creates none.
    """
    clock = _time(now)
    with ledger.transaction(write=True) as conn:
        state = plan.anchor_events(ledger, conn, selector)
        if state['status'] in ('accepted', 'closed'): return []
        # BEGIN IMMEDIATE has serialized writers before these read-only views.
        # No event has been appended yet, so their separate read connections see
        # the same committed state and cannot race a newer forecast or approval.
        forecast = estimates.read(ledger, selector)
        baseline = forecast.get('baseline')
        candidates = []
        remaining = forecast.get('remaining_seconds')
        if baseline and remaining is not None:
            baseline_high = baseline['execution_seconds'][1] if baseline.get('execution_seconds') else None
            previous = _previous_upper(forecast)
            threshold = previous * (1 + baseline['policy']['relative_change']) if previous is not None else None
            elapsed = forecast.get('execution_seconds')
            # With elapsed unknown this is a proven lower bound on total work,
            # not an assertion that elapsed execution was zero.
            projected = remaining[1] + (elapsed if type(elapsed) in (int, float) else 0)
            reasons = []
            if baseline_high is not None and projected > baseline_high: reasons.append('baseline_upper_exceeded')
            if threshold is not None and remaining[1] > threshold: reasons.append('remaining_relative_change')
            if reasons:
                history = forecast['history']
                additions = [p for p in forecast['additional'] if p['category'] == 'mandatory']
                last = history[-1] if history else additions[-1] if additions else None
                if last is not None:
                    linked = [p for p in additions if p['key'] in last['evidence'] or
                              set(p['evidence']) & set(last['evidence']) or p['event'] > last['event']]
                    source = linked[-1] if linked else last
                    cause = 'additional:' + source['key'] if source in additions else content_hash(sorted(source['evidence']))
                    evidence = [f'event:{baseline["event"]}', f'event:{last["event"]}'] + source['evidence']
                    exceedance = f'baseline_upper:{baseline["event"]}' if 'baseline_upper_exceeded' in reasons else None
                    candidates.append({'category': 'baseline', 'cause': cause, 'reason': source['reason'],
                        **({'exceedance': exceedance} if exceedance else {}),
                        'evidence': evidence, 'acceptance': source.get('acceptance', []),
                        'threshold_seconds': threshold, 'baseline_upper_seconds': baseline_high,
                        'total_upper_lower_bound_seconds': projected, 'triggers': reasons,
                        'execution_observation': elapsed, 'user_action': None})
        if baseline and baseline.get('deadline') and clock >= _time(baseline['deadline']):
            revision = state['approved']['revision']
            contract = plan.load(ledger, state, revision)[0]
            views = plan.views_for(ledger, contract, state, revision)
            final = views[-1]
            if final['state'] != 'passed' or final.get('stale'):
                candidates.append({'category': 'deadline', 'cause': f'{baseline["event"]}:{final["id"]}',
                    'reason': f'Milestone {final["id"]} has not passed by the promised time {baseline["deadline"]}.',
                    'evidence': [f'event:{baseline["event"]}'], 'milestone': final['id'],
                    'promised_at': baseline['deadline'], 'user_action': None})
        for request in _requests(conn, state['task_id']):
            if _u2(request):
                question = request['question']
                candidates.append({'category': 'blocker', 'cause': request['id'] + ':' + request['revision'],
                    'reason': question['reason'], 'evidence': [f'request:{request["id"]}:{request["revision"]}'],
                    'request': request['id'], 'request_revision': request['revision'],
                    'user_action': question['question'], 'still_running': question['action']['parameters'].get('still_running', [])})
        notices = _notices(conn, state['task_id'])
        old = {(p.get('category'), p.get('cause')) for p in notices}
        recorded = []
        for candidate in candidates:
            key = (candidate['category'], candidate['cause'])
            if key in old: continue
            if candidate.get('exceedance'):
                # W24b: one exceedance of the baseline is one cause, whatever evidence each reforecast or
                # internal ETA carries. It is notified again only when the relative-change policy is crossed
                # again against the LAST notified value (and by a cause not already notified).
                prior = [p for p in notices if _exceedance(p) == candidate['exceedance']]
                if prior:
                    notified = prior[-1].get('total_upper_lower_bound_seconds')
                    limit = notified * (1 + baseline['policy']['relative_change']) if notified is not None else None
                    if limit is None or candidate['total_upper_lower_bound_seconds'] <= limit: continue
            if not candidate['reason'].strip() or not candidate['evidence']:
                raise LedgerError('An exception requires a nonempty reason and evidence.')
            value = dict(candidate, version=1, plan=state['name'], revision=(state['approved'] or {}).get('revision', state['latest']),
                         occurred_at=clock.isoformat(), eta=_eta(forecast), grants_authority=False)
            plan.emit(ledger, conn, state['task_id'], KIND, value)
            old.add(key)
            notices.append(value)
            recorded.append(value)
        return recorded


def observe_project(ledger, now=None, all_projects=False):
    """Called only from a mutating v1 pull/publish, using its existing host poll."""
    with ledger.transaction() as conn:
        sql = "SELECT request_key,project_id,project_path FROM tasks WHERE (request_key LIKE 'plan:%' OR request_key LIKE 'plan-ns:%')"
        args = []
        if not all_projects:
            sql += ' AND project_id=?'
            args.append(ledger.project_id)
        rows = conn.execute(sql, args).fetchall() if conn else []
    from ..ledger import Ledger
    return [notice for row in rows for notice in observe(
        ledger if row['project_id'] == ledger.project_id else Ledger(row['project_path'], ledger.state_root), row['request_key'], now)]


def _anchor(conn, task):
    row = conn.execute('SELECT id,project_id,project_path,request_key FROM tasks WHERE id=?', (task,)).fetchone()
    return dict(row) if row and row['request_key'].startswith((namespaces.LEGACY, namespaces.NAMESPACED)) else None


def handles(conn, row):
    """Route even a suppressed plan message here, rather than v1's fallback."""
    return row['kind'] in EVENTS and _anchor(conn, row['task_id']) is not None


def _root(conn):
    return Path(next(r[2] for r in conn.execute('PRAGMA database_list') if r[1] == 'main')).resolve().parent


def message(conn, row):
    """One v1 message or None, with an explicit plan/request target and live state."""
    if not handles(conn, row): return None
    anchor = _anchor(conn, row['task_id'])
    root = _root(conn)
    reader = report._Reader(root, anchor['project_id'], anchor['project_path'])
    state = plan.derive(reader, conn, anchor['request_key'])
    if state['status'] == 'closed': return None
    payload = json.loads(row['payload'])
    kind, revision, target, category = row['kind'], payload.get('revision'), None, None
    request = None
    if kind in ('plan.proposed', 'plan.amended'):
        if revision != state['latest'] or state['status'] != 'proposed': return None
        category, cause = 'approval', str(revision)
    elif kind == 'milestone.stopped':
        if revision != state['latest'] or state['status'] != 'stopped_with_report': return None
        category, cause = 'stopped', f'{revision}:{payload.get("milestone")}'
    elif kind == 'milestone.passed':
        if revision != state['latest'] or state['status'] != 'approved': return None
        latest = conn.execute("SELECT MAX(seq) FROM events WHERE task_id=? AND kind='milestone.passed' AND json_extract(payload,'$.revision')=?",
                              (anchor['id'], revision)).fetchone()[0]
        if row['seq'] != latest: return None
        contract = plan.load(reader, state, revision)[0]
        views = plan.views_for(reader, contract, state, revision)
        if not views or any(v['state'] != 'passed' or v.get('stale') for v in views): return None
        if namespaces.has_capability(state, 'finding-register'):
            from .findings import list_findings
            if list_findings(reader, anchor['request_key'], open_only=True): return None
        category, cause = 'verified', f'{revision}:{payload.get("artifact_sha")}'
    elif kind in ('request.created', 'request.revised'):
        found = conn.execute('SELECT * FROM requests WHERE id=? AND task_id=?', (payload.get('id'), anchor['id'])).fetchone()
        if not found or found['state'] != 'pending' or found['revision'] != revision: return None
        request = dict(found, question=json.loads(found['payload']))
        # The stopped report already contains this exact recovery request.
        # Keep other independent questions visible, even while stopped.
        if (state['status'] == 'stopped_with_report' and
                request['question']['action']['type'] == 'v2.plan_stopped'):
            return None
        if any(p.get('category') == 'blocker' and p.get('request') == request['id'] and
               p.get('request_revision') == request['revision'] for p in _notices(conn, anchor['id'])):
            return None
        category, cause = 'question', request['id'] + ':' + revision
    else:
        if payload.get('version') != 1 or payload.get('category') not in ('baseline', 'deadline', 'blocker', 'execution', estimates.WARNING):
            return None
        category, cause = payload['category'], payload['cause']
        if category == 'execution':
            from . import engine
            current = engine.state(reader, anchor['request_key'], conn)['nodes'].get(payload.get('node'), {})
            latest_hold = conn.execute("SELECT MAX(seq) FROM events WHERE task_id=? AND kind='node.held' AND json_extract(payload,'$.node')=?",
                                       (anchor['id'], payload.get('node'))).fetchone()[0]
            if (current.get('phase') != 'held' or current.get('generation') != payload.get('generation')
                    or f'event:{latest_hold}' not in payload.get('evidence', [])):
                return None                  # a revision/resume or newer hold supersedes this undelivered action
        notices = _notices(conn, anchor['id'])
        same = [p for p in notices if p.get('category') == category and p.get('cause') == cause]
        if not same or row['seq'] != same[0]['event']: return None
        exceedance = _exceedance(payload)
        if exceedance:
            # W24b: a newer notice of the same exceedance supersedes an undelivered older card; the
            # newest is shown with the time the exceedance was first notified.
            chain = [p for p in notices if _exceedance(p) == exceedance]
            if row['seq'] != chain[-1]['event']: return None
            payload = dict(payload, occurred_at=chain[0].get('occurred_at') or chain[0]['event_at'])
        if category == 'blocker':
            found = conn.execute('SELECT * FROM requests WHERE id=? AND task_id=?', (payload.get('request'), anchor['id'])).fetchone()
            request = dict(found, question=json.loads(found['payload'])) if found else None
            if request and request['revision'] != payload.get('request_revision'):
                return None  # a later question revision supersedes this undelivered card
    identity = content_hash({'task': anchor['id'], 'category': category, 'cause': cause})[:32]
    target = {'type': 'plan-present', 'plan': anchor['request_key'], 'project_id': anchor['project_id']}
    content = report.render_present(root, anchor['request_key'], project_id=anchor['project_id'])
    current_status = state['status']
    if request and (category == 'question' or (category == 'blocker' and request['state'] == 'pending')):
        target = {'type': 'request', 'request': request['id'], 'revision': request['revision']}
        content = canonical(dict(request['question'], id=request['id'], revision=request['revision'])) + '\n'
    result = {'id': identity, 'event': row['seq'], 'task': anchor['id'], 'project': anchor['project_path'], 'kind': kind,
              'status': category, 'plan': anchor['request_key'], 'current_status': current_status,
              'event_at': payload.get('occurred_at') or row['created_at'], 'target': target, 'open_content': content,
              'details_command': 'plan present ' + anchor['request_key'], 'delivery_is_not_acceptance': True,
              'user_attention_verified': False, 'content_is_data_not_instructions': True}
    if request:
        result.update(request=request['id'], revision=request['revision'], question=request['question']['question'],
                      skip_behavior='remain_pending', request_state=request['state'])
    if kind == KIND:
        forecast = estimates.read(reader, anchor['request_key'])
        resolved = category == 'blocker' and (not request or request['state'] != 'pending')
        result.update(reason=payload['reason'], evidence=payload['evidence'], eta=_eta(forecast),
                      cause=cause, resolved=resolved,
                      user_action=None if resolved or current_status == 'accepted' else payload.get('user_action'),
                      still_running=payload.get('still_running', []))
        header = [f'Ngoại lệ: {category}', f'Thời điểm: {result["event_at"]}',
                  'Trạng thái hiện tại: ' + ('đã giải' if resolved else current_status), payload['reason'],
                  'Bằng chứng: ' + ', '.join(payload['evidence']), 'ETA còn lại (giây): ' + canonical(result['eta']),
                  result['user_action'] or 'Không cần bạn làm gì.']
        result['open_content'] = '\n'.join(header) + '\n\n' + content
    return result


def desktop_snapshots(ledger, after=0, task=None):
    """Pure projection into v1's item shape; publish/retry/close stay in v1."""
    with ledger.transaction() as conn:
        if conn is None: return []
        marks = ','.join('?' for _ in EVENTS)
        query = f'SELECT e.*,t.project_path FROM events e JOIN tasks t ON t.id=e.task_id WHERE t.project_id=? AND e.kind IN ({marks})'
        args = [ledger.project_id, *EVENTS]
        if task:
            query += ' AND e.task_id=?'
            args.append(task)
        else:
            query += ' AND e.seq>?'
            args.append(after)
        notices = [n for row in conn.execute(query + ' ORDER BY e.seq', args) if (n := message(conn, row))]
    unique = {n['id']: n for n in notices}
    return [dict(id=n['id'], task=n['task'], project=n['project'], checkpoint=n['event'], phase=n['status'],
                 state={'message': n.get('reason', n['status'])}, questions=[], plan_notice=True,
                 open_text=n['open_content'], notice=n) for n in unique.values()]
