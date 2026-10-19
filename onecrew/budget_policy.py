"""Versioned intake defaults and evidence-only budget advice; no grant mutations."""
import datetime as dt
import math

from .ledger import canonical
from .task_intake import DEFAULT_CALLS, DEFAULT_SECONDS, POLICY, recommend as core_recommend  # noqa: F401  (the intake defaults and advice are core)


def watch_policy(policy, calls, seconds):
    if not policy or policy.get('version') != 2:
        return {'calls': 20, 'seconds': 600}
    return {'version': 2, 'fraction': policy['warning_fraction'],
            'calls': max(1, math.ceil(calls * policy['warning_fraction'])),
            'seconds': max(1, math.ceil(seconds * policy['warning_fraction']))}


def recommend(ledger, goal, mode, provider, model):
    from .learning import outcomes
    return core_recommend(ledger, goal, mode, provider, model, outcomes)


def timing(conn, task, state, attempts):
    checkpoint = conn.execute("SELECT created_at FROM events WHERE task_id=? AND kind='workflow.checkpoint' AND payload=? ORDER BY seq LIMIT 1",
                              (task['id'], canonical(state))).fetchone()
    end = checkpoint['created_at'] if checkpoint else None
    wall = max(0, (dt.datetime.fromisoformat(end)-dt.datetime.fromisoformat(task['created_at'])).total_seconds()) if end else None
    settled = [a for a in attempts if a['status'] == 'settled']
    attempt_seconds = sum(max(0, (dt.datetime.fromisoformat(a['updated_at'])-dt.datetime.fromisoformat(a['created_at'])).total_seconds()) for a in settled)
    return {'wall_seconds': wall, 'settled_attempt_seconds': attempt_seconds,
            'wait_seconds': None, 'includes_waits': True, 'active_compute_seconds': None}
