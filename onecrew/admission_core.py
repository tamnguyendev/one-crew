"""Shared existing pending-question and consultation admission reads."""
import json

def blocks(conn, task_id, unit='root'):
    rows = conn.execute("SELECT payload FROM requests WHERE task_id=? AND state='pending'", (task_id,)).fetchall()
    for row in rows:
        action = json.loads(row['payload'])['action']
        affected = action['parameters'].get('affected_tasks')
        scoped = action['type'] == 'workflow.branch' and isinstance(affected, list) and affected and all(isinstance(x, str) for x in affected)
        if not scoped or unit == 'root':
            return True
        if unit != 'scheduler' and (not unit.startswith('task:') or unit[5:] in affected):
            return True
    return False

def consultations_installed(conn):
    return bool(conn and conn.execute("SELECT 1 FROM sqlite_master WHERE name='consultations'").fetchone())

def active_consultations(conn):
    return conn.execute("SELECT COUNT(*) FROM consultations WHERE json_extract(state,'$.attempt.status') IN ('reserved','running','unknown')").fetchone()[0] if consultations_installed(conn) else 0
