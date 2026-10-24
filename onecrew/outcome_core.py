"""The v1 learning.outcome identity and merge rule, shared with plan roots."""
from .ledger import content_hash


def outcome_id(data):
    return content_hash({key: value for key, value in data.items() if key != 'id'})


def append_outcome(conn, ledger, task_id, data):
    if conn.execute("SELECT 1 FROM events WHERE task_id=? AND kind='learning.outcome' AND json_extract(payload,'$.id')=?",
                    (task_id, data['id'])).fetchone():
        return None
    ledger._event(conn, task_id, 'learning.outcome', data)
    return conn.execute('SELECT last_insert_rowid()').fetchone()[0]
