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
                row = conn.execute('SELECT state,revision FROM requests WHERE id=?',(item['request'],)).fetchone()
            if not row or row['state'] != 'pending' or row['revision'] != item['revision']: continue
        notices.append(item)
    if notices:
        durable_write(target, canonical(dict(batch, notifications=notices,
            transport='local-file', chat_callback=False)).encode())
    receipt = ack(ledger, consumer, batch['id'])
    return dict(receipt, delivered=len(notices), path=str(target) if notices else None,
                has_more=batch['has_more'], transport='local-file', chat_callback=False)


def best_effort(ledger):
    """Outbox survives sink failure; never change execution success to delivery success."""
    try: return deliver(ledger)
    except (ValueError,OSError) as error:
        return {'status':'delivery_pending','error':str(error)[:500],'chat_callback':False}


def feed(ledger, consumer='local-feed', limit=20):
    path = location(ledger,consumer,False)
    root = path.parent/'delivered'/path.stem
    files = sorted(root.glob('*.json'),key=lambda p:p.stat().st_mtime,reverse=True)[:limit]
    return {'transport':'local-file','chat_callback':False,
            'batches':[json.loads(p.read_text(encoding='utf-8')) for p in files]}
