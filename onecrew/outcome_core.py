"""The v1 learning.outcome identity and merge rule, shared with plan roots."""
from .ledger import LedgerError, content_hash


def outcome_id(data):
    return content_hash({key: value for key, value in data.items() if key != 'id'})


def append_outcome(conn, ledger, task_id, data):
    return append_learning(conn, ledger, task_id, 'learning.outcome', data)


def append_learning(conn, ledger, task_id, kind, data):
    """One content merge law for v1 outcomes/lessons and neutral plan adapters."""
    if kind not in ('learning.outcome', 'learning.lesson', 'learning.incident'):
        raise LedgerError('Unknown learning event kind.')
    if conn.execute("SELECT 1 FROM events WHERE task_id=? AND kind=? AND json_extract(payload,'$.id')=?",
                    (task_id, kind, data['id'])).fetchone():
        return None
    ledger._event(conn, task_id, kind, data)
    return conn.execute('SELECT last_insert_rowid()').fetchone()[0]
