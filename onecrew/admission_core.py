"""Shared existing pending-question and consultation admission reads."""
import json

SCOPED_TYPES = ('workflow.branch',)          # v1: the branch question names the units it holds (parameters.affected_tasks)


def blocking(rows, unit='root', *, scoped_types=SCOPED_TYPES, unscoped_blocks=True):
    """The shared admission rule (v1 branch inbox; v2 engine through finding_scope): which pending requests hold `unit`.

    rows: (request_id, action) pairs. A request is SCOPED when its type is one of `scoped_types` and its parameters name the units it
    holds (`affected_tasks`, or `nodes` for the v2 U2 question); a scoped request holds exactly those units and the root. An UNSCOPED
    pending request holds everything when `unscoped_blocks` (v1: a global question stops dispatch) and nothing when not (v2: a decision
    card or a U2 without nodes is a question for the owner, not a hold on independent work — HD-25/T16). Returns the request ids."""
    held = []
    for request_id, action in rows:
        parameters = action.get('parameters') or {}
        affected = parameters.get('affected_tasks')
        if affected is None: affected = parameters.get('nodes')
        scoped = action.get('type') in scoped_types and isinstance(affected, list) and affected and all(isinstance(x, str) for x in affected)
        if not scoped:
            if unscoped_blocks: held.append(request_id)
            continue
        if unit == 'root' or (unit != 'scheduler' and (not unit.startswith('task:') or unit[5:] in affected)):
            held.append(request_id)
    return held


def pending(conn, task_id):
    return [(row['id'], json.loads(row['payload'])['action']) for row in
            conn.execute("SELECT id,payload FROM requests WHERE task_id=? AND state='pending'", (task_id,)).fetchall()]


def blocks(conn, task_id, unit='root', **policy):
    """v1 entry point, unchanged behaviour with the default policy."""
    return bool(blocking(pending(conn, task_id), unit, **policy))

def consultations_installed(conn):
    return bool(conn and conn.execute("SELECT 1 FROM sqlite_master WHERE name='consultations'").fetchone())

def active_consultations(conn):
    return conn.execute("SELECT COUNT(*) FROM consultations WHERE json_extract(state,'$.attempt.status') IN ('reserved','running','unknown')").fetchone()[0] if consultations_installed(conn) else 0
