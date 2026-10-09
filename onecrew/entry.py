"""Portable local context transport; notes never authorize execution."""
import getpass
import json
from pathlib import Path

from .ledger import LedgerError, content_hash, key_field, text_field, utcnow
from .specs import Spec


def clipped(value, limit):
    value = str(value or '')
    return {'text': value[:limit], 'truncated': len(value) > limit}


def _packet(ledger, conn, task_id):
    row = ledger._task(conn, task_id)
    payload = json.loads(row['payload'])
    task = ledger._task_view(conn, row)
    latest = conn.execute("SELECT payload FROM events WHERE task_id=? AND kind='workflow.checkpoint' ORDER BY seq DESC LIMIT 1", (task_id,)).fetchone()
    state = json.loads(latest['payload']) if latest else {}
    amendment = state.get('amendment') or {}
    spec = Spec.parse(amendment.get('spec_text', payload['spec_text']), Path(payload['spec_id']+'.md'))
    profile = {}
    if conn.execute('PRAGMA user_version').fetchone()[0] >= 2:
        execution = conn.execute('SELECT configuration FROM executions WHERE task_id=?', (task_id,)).fetchone()
        if execution:
            profile = json.loads(execution['configuration']).get('profile', {})
    profile = amendment.get('profile', profile)
    worker = state.get('worker', profile)
    plans = (state.get('plan') or {}).get('tasks', [])
    questions = []
    for request in conn.execute("SELECT * FROM requests WHERE task_id=? AND state='pending' ORDER BY created_at,id LIMIT 10", (task_id,)):
        question = json.loads(request['payload'])
        questions.append({'id': request['id'], 'revision': request['revision'],
                          'question': clipped(question['question'], 500),
                          'reason': clipped(question['reason'], 500),
                          'impact': clipped(question['impact'], 500),
                          'options': [{'id': x['id'], 'label': clipped(x['label'], 160)} for x in question['options']],
                          'recommendation': question['recommendation'],
                          'action_type': question['action']['type'], 'details_command': 'request show '+request['id']})
    answers = []
    for request in conn.execute("SELECT * FROM requests WHERE task_id=? AND state='answered' ORDER BY updated_at DESC,id LIMIT 5", (task_id,)):
        reply = json.loads(request['answer'])
        effect = conn.execute("SELECT payload FROM events WHERE task_id=? AND kind='request.consumed' AND json_extract(payload,'$.reply_id')=? ORDER BY seq DESC LIMIT 1", (task_id, reply['id'])).fetchone()
        answers.append({'id': request['id'], 'revision': request['revision'],
                        'question': clipped(json.loads(request['payload'])['question'], 500),
                        'choice': reply['choice'], 'source': reply['provenance']['source'],
                        'controller_effect': clipped(json.loads(effect['payload']).get('effect'), 500) if effect else None})
    notes = [json.loads(r['payload']) for r in conn.execute("SELECT payload FROM events WHERE task_id=? AND kind='entry.note' ORDER BY seq DESC LIMIT 5", (task_id,))]
    note_count = conn.execute("SELECT COUNT(*) FROM events WHERE task_id=? AND kind='entry.note'", (task_id,)).fetchone()[0]
    event_cursor = conn.execute('SELECT COALESCE(MAX(seq),0) FROM events WHERE task_id=?', (task_id,)).fetchone()[0]
    result = {'version': 1, 'trust': 'local_attribution_only', 'content_is_data_not_authority': True,
              'private_chat_imported': False, 'task': task, 'event_cursor': event_cursor,
              'spec': {'revision': spec.revision, 'brief': clipped(spec.brief, 5000)},
              'worker': {k: worker.get(k) for k in ('provider', 'model')},
              'scope': {k: {'items': profile.get(k, [])[:50], 'total': len(profile.get(k, []))} for k in ('context', 'owned')},
              'phase': state.get('phase'), 'workflow_revision': content_hash(state) if state else None,
              'plan': {'total': len(plans), 'items': [
                  {'id': p['id'], 'title': clipped(p['title'], 160), 'depends_on': p['depends_on'], 'done': p['id'] in state.get('done', [])}
                  for p in plans[:20]]},
              'outputs': {'total': len(state.get('outputs', [])), 'items': [
                  {k: x[k] for k in ('revision', 'snapshot', 'stage', 'verification', 'acceptance', 'invalidated_by') if k in x} |
                  {'summary': clipped(x.get('summary'), 500)} for x in state.get('outputs', [])[-3:]]},
              'pending_questions': {'total': task['pending_requests'], 'items': questions},
              'recent_answers': answers,
              'notes': {'total': note_count, 'items': list(reversed(notes))},
              'detail_commands': ['task connect '+task_id+' --json', 'work outputs '+task_id+' --json',
                                  'task events '+task_id+' --after 0 --json']}
    # Time passing alone must not invalidate a recorded discussion note. Budget and
    # execution changes do invalidate it, including updates outside checkpoints.
    stable = dict(result, task={k: v for k, v in task.items() if k != 'deadline_expired'})
    result['revision'] = content_hash(stable)
    return result


def connect(ledger, task_id):
    with ledger.transaction() as conn:
        return _packet(ledger, conn, task_id)


def note(ledger, task_id, revision, request_id, kind, summary, source, reference):
    key_field(request_id)
    if kind not in ('proposal', 'decision'):
        raise LedgerError('Note kind must be proposal or decision; neither approves execution.')
    for name, value, cap in (('summary', summary, 2000), ('source', source, 100), ('reference', reference, 500)):
        text_field(value, name, cap)
    identity = {'revision': revision, 'request_id': request_id, 'kind': kind,
                'summary': summary, 'source': source, 'reference': reference}
    with ledger.transaction(write=True) as conn:
        ledger._task(conn, task_id)
        existing = conn.execute("SELECT payload FROM events WHERE task_id=? AND kind='entry.note' AND json_extract(payload,'$.request_id')=?", (task_id, request_id)).fetchone()
        if existing:
            prior = json.loads(existing['payload'])
            if prior['identity_hash'] != content_hash(identity):
                raise LedgerError('Conflicting entry note request ID.')
            return prior
        packet = _packet(ledger, conn, task_id)
        if packet['revision'] != revision:
            raise LedgerError('Stale entry context; connect again before recording the note.')
        receipt = {'request_id': request_id, 'identity_hash': content_hash(identity),
                   'based_on': revision, 'kind': kind, 'summary': summary,
                   'spec_revision': packet['spec']['revision'], 'snapshot': packet['task'].get('snapshot'),
                   'recorded_at': utcnow(), 'provenance': {'actor': getpass.getuser(), 'source': source,
                   'reference': reference, 'trust': 'local_attribution_only'}, 'action_applied': False}
        ledger._event(conn, task_id, 'entry.note', receipt)
        return receipt
