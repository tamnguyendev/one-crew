"""Owner receipts for a host session waiting on a specific plan revision."""
import json
import os
import re
import secrets

from ..ledger import Ledger, LedgerError, canonical, content_hash, text_field, utcnow
from ..locking_core import task_lock
from ..notification_core import read_state
from ..snapshots import durable_write
from . import plan


LABELS = {'plan.approved': 'đã duyệt', 'plan.accepted': 'đã nghiệm thu', 'verdict.recorded': 'đã ghi verdict',
          'request.answered': 'đã trả lời', 'hook.mode_recorded': 'đã đặt chế độ hook'}
STAGES = {'recorded': 'Đã ghi · chờ phiên nhận', 'sending': 'Chưa xác định kết quả gửi', 'delivered': 'Đã gửi qua hook',
          'acknowledged': 'Phiên đã xác nhận', 'resumed': 'Đã quan sát phiên làm tiếp'}


def _scope(ledger, task, revision, host, session):
    return dict(ledger=os.path.normcase(str(ledger.state_root)), project=ledger.project_id,
                task=task, revision=revision, host=host, session=session)


def _folder(ledger, task):
    return ledger.state_root / 'notifications' / 'owner-results' / content_hash([ledger.project_id, task])


def _path(ledger, scope):
    return _folder(ledger, scope['task']) / (content_hash(scope) + '.json')


def _save(path, state):
    durable_write(path, canonical(state).encode('utf-8'))


def _recorded(conn, scope, after):
    """Only committed owner effects. A request's revision is a hash, distinct from the contract revision."""
    marks = ','.join('?' for _ in LABELS)
    rows = conn.execute(f'SELECT seq, kind, payload FROM events WHERE task_id=? AND seq>? AND kind IN ({marks}) ORDER BY seq',
                        (scope['task'], after, *LABELS))
    results = []
    for row in rows:
        kind, p = row['kind'], json.loads(row['payload'])
        revision, detail = p.get('revision'), ''
        if kind == 'request.answered':
            source = p.get('provenance') or {}
            if source.get('by') != 'user' or source.get('source') != 'owner-terminal':
                continue
            request = conn.execute("SELECT seq,payload FROM events WHERE task_id=? AND kind IN ('request.created','request.revised') "
                                   "AND seq<? AND json_extract(payload,'$.id')=? AND json_extract(payload,'$.revision')=? ORDER BY seq DESC LIMIT 1",
                                   (scope['task'], row['seq'], p.get('request_id'), revision)).fetchone()
            if request is None:
                continue
            params = json.loads(request['payload'])['question']['action']['parameters']
            revision = params.get('contract_revision', params.get('revision'))
            if revision is None:
                prior = conn.execute("SELECT json_extract(payload,'$.revision') FROM events WHERE task_id=? AND seq<? "
                                     "AND kind IN ('plan.amended','plan.proposed') ORDER BY seq DESC LIMIT 1",
                                     (scope['task'], request['seq'])).fetchone()
                revision = prior[0] if prior else None
            detail = p['request_id'] + ' · ' + p['choice']
        elif p.get('by') != 'owner':
            continue
        elif kind == 'verdict.recorded':
            detail = p['milestone'] + ' · ' + p['result']
        elif kind == 'hook.mode_recorded':
            detail = p['mode']
        if revision == scope['revision']:
            results.append(dict(event=row['seq'], kind=kind, detail=detail))
    return results


def latest_revision(conn, task):
    row = conn.execute("SELECT json_extract(payload,'$.revision') FROM events WHERE task_id=? "
                       "AND kind IN ('plan.amended','plan.proposed') ORDER BY seq DESC LIMIT 1", (task,)).fetchone()
    return row[0] if row else None


def follow(ledger, selector, revision, host, session, receipt=None):
    text_field(host, 'host', 64)
    text_field(session, 'session', 200)
    with ledger.transaction() as conn:
        state = plan.anchor_events(ledger, conn, selector)
        if revision != state['latest']:
            raise LedgerError('The waiting session must name the current plan revision.')
        scope = _scope(ledger, state['task_id'], revision, host, session)
    path = _path(ledger, scope)
    with task_lock(ledger, 'owner.' + path.stem, wait=1):
        current = read_state(path)
        if receipt is None:
            if not path.exists():
                current.update(scope=scope, batches=[])
                _save(path, current)
            return dict(scope=scope, supported=host == 'claude', waiting=True)
        for batch in current.get('batches', []):
            if batch['id'] == receipt and current.get('scope') == scope and batch['stage'] in ('delivered','acknowledged','resumed'):
                if batch['stage'] == 'delivered':
                    if not batch.get('ack_tool'):
                        raise LedgerError('ACK needs a tool call from the host session that received the result.')
                    batch.update(stage='acknowledged', acknowledged_at=utcnow())
                    _save(path, current)
                return dict(receipt=receipt, stage=batch['stage'])
        raise LedgerError('No matching delivered owner receipt for this session.')


def _opportunity(ledger, scope, event, output):
    path = _path(ledger, scope)
    if not path.is_file():
        return
    with task_lock(ledger, 'owner.' + path.stem, wait=0.25):
        state = read_state(path)
        if state.get('scope') != scope:
            return
        with ledger.transaction() as conn:
            if conn is None or latest_revision(conn, scope['task']) != scope['revision']:
                return
            selector = ledger._task(conn, scope['task'])['request_key']
            notices = _recorded(conn, scope, state['cursor']) if output else []
        name, tool = event.get('hook_event_name'), event.get('tool_use_id')
        command = (event.get('tool_input') or {}).get('command', '')
        ack_command = (name == 'PreToolUse' and tool and event.get('tool_name') in ('Bash','PowerShell') and
                       isinstance(command, str) and re.search(r'\bnotifications[\s,\x22\x27]+ack-owner\b', command))
        changed = False
        for batch in state['batches']:
            if ack_command and batch['stage'] == 'delivered' and batch['id'] in command:
                batch['ack_tool'] = tool
                changed = True
            if batch['stage'] != 'acknowledged' or not tool:
                continue
            # Only a successful, identified work tool whose start was observed AFTER the ACK.
            if tool in (batch.get('delivery_tool'), batch.get('ack_tool')):
                continue
            if name == 'PreToolUse' and event.get('tool_name') in ('Write','Edit','MultiEdit','NotebookEdit','Bash','PowerShell'):
                if not ack_command and tool not in batch.setdefault('started', []):
                    batch['started'].append(tool)
                    changed = True
            elif name == 'PostToolUse' and tool in batch.get('started', []):
                batch.update(stage='resumed', observed_tool=tool, resumed_at=utcnow())
                batch.pop('started')
                changed = True
        if changed:
            _save(path, state)
        if not notices:
            return
        receipt = secrets.token_hex(32)
        batch = dict(id=receipt, notifications=notices, stage='sending', claimed_at=utcnow(), delivery_tool=tool)
        state['batches'].append(batch)
        state['cursor'] = notices[-1]['event']
        _save(path, state)  # A crash across stdout leaves an ambiguous claim; never replay it automatically.
        summary = ', '.join(f"{LABELS[n['kind']]} {n['detail']}".strip() for n in notices)
        ack_args = ['onecrew', '--project', str(ledger.project), '--state-root', str(ledger.state_root),
                    'notifications', 'ack-owner', '--plan', selector, '--revision', str(scope['revision']),
                    '--host', scope['host'], '--session', scope['session'], '--receipt', receipt]
        output(f"OneCrew · {summary}. Receipt {receipt}. Xác nhận đã nhận bằng lệnh (argv): {json.dumps(ack_args, ensure_ascii=False)}")
        batch.update(stage='delivered', delivered_at=utcnow())
        _save(path, state)


def hook(document, project, event, output=None):
    if not document or not document.get('anchor_task') or not event.get('session_id') or event.get('agent_id') or event.get('host', 'claude') != 'claude':
        return
    try:
        from . import hook_cli
        ledger = Ledger(project, document['state_root'])
        scope = _scope(ledger, document['anchor_task'], document['revision'], 'claude', event['session_id'])
        if not _path(ledger, scope).is_file():
            return
        external = hook_cli.state_copy(ledger.state_root, project)
        if not external:
            return
        active, error = hook_cli.load_plan(external)
        keys = ('anchor_task', 'revision')
        if error or any(document.get(key) != active.get(key) for key in keys) or any(
                os.path.normcase(document[key]) != os.path.normcase(active[key]) for key in ('project','state_root')):
            return
        _opportunity(ledger, scope, event, output)
    except (LedgerError, OSError, ValueError, KeyError, TypeError) as exc:
        import sys
        print(f'OneCrew owner result unavailable ({type(exc).__name__})', file=sys.stderr)


def status(reader, task, revision):
    """Read-only page projection. The source receipt is visible before the first hook runs."""
    with reader.transaction() as conn:
        scope = _scope(reader, task, revision, '', '')
        records = _recorded(conn, scope, 0)
    rows = []
    for path in sorted(_folder(reader, task).glob('*.json')):
        state = read_state(path)
        bound = state.get('scope', {})
        if bound != dict(scope, host=bound.get('host'), session=bound.get('session')) or path != _path(reader, bound):
            continue
        stages = {item['event']: batch['stage'] for batch in state['batches'] for item in batch['notifications']}
        rows.extend(dict(item, host=bound['host'], session=bound['session'], stage=stages.get(item['event'], 'recorded')) for item in records)
    return rows or [dict(item, host=None, session=None, stage='recorded') for item in records]
