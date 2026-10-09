"""Local event sink driven by runner checkpoints; no AI, scheduler or remote sends."""
import json
from .ledger import canonical
from .notifications import pull, ack, location
from .snapshots import durable_write


def deliver(ledger, consumer='local-feed'):
    """Durable batch sink, then ack. Retries overwrite the same batch, not duplicate it."""
    batch = pull(ledger, consumer)
    path = location(ledger, consumer, False)
    target = path.parent/'delivered'/path.stem/(batch['id']+'.json')
    notices = []
    for item in batch['notifications']:
        if item.get('request'):
            # The persisted batch may predate an answer/revision change.
            with ledger.transaction() as conn:
                table='conversation_questions' if item['request'].startswith('CREQ-') else 'requests'
                row = conn.execute('SELECT state,revision FROM '+table+' WHERE id=?',(item['request'],)).fetchone()
            if not row or row['state'] != 'pending' or row['revision'] != item['revision']: continue
        notices.append(item)
    if notices:
        durable_write(target, canonical(dict(batch, notifications=notices,
            transport='local-file', chat_callback=False)).encode())
    receipt = ack(ledger, consumer, batch['id'])
    try:path.with_suffix('.error.json').unlink(missing_ok=True)
    except OSError:pass  # Cleanup of historical diagnostics must not undo delivery.
    return dict(receipt, delivered=len(notices), path=str(target) if notices else None,
                has_more=batch['has_more'], transport='local-file', chat_callback=False)


def best_effort(ledger):
    """Outbox survives sink failure; never change execution success to delivery success."""
    try: return deliver(ledger)
    except (ValueError,OSError) as error:
        failure={'status':'delivery_pending','error':str(error)[:500],'chat_callback':False}
        try: durable_write(location(ledger,'local-feed',False).with_suffix('.error.json'),canonical(failure).encode())
        except OSError: pass  # The durable unacknowledged batch still survives.
        return failure


def feed(ledger, consumer='local-feed', limit=20):
    path = location(ledger,consumer,False)
    root = path.parent/'delivered'/path.stem
    files = sorted(root.glob('*.json'),key=lambda p:p.stat().st_mtime,reverse=True)[:limit]
    from .notifications import read_state
    pending=read_state(path).get('batch')
    error_path=path.with_suffix('.error.json')
    return {'transport':'local-file','chat_callback':False,
            'pending_batch':pending['id'] if pending else None,
            'last_error':json.loads(error_path.read_text(encoding='utf-8')) if error_path.exists() else None,
            'batches':[json.loads(p.read_text(encoding='utf-8')) for p in files]}
