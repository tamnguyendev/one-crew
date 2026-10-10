"""Versioned intake defaults and evidence-only budget advice; no grant mutations."""
import datetime as dt
import math

from .ledger import content_hash, canonical

DEFAULT_CALLS = 100
DEFAULT_SECONDS = 7200
POLICY = {'version': 2, 'warning_fraction': .7, 'automatic_extension': False}


def watch_policy(policy, calls, seconds):
    if not policy or policy.get('version') != 2:
        return {'calls': 20, 'seconds': 600}
    return {'version': 2, 'fraction': policy['warning_fraction'],
            'calls': max(1, math.ceil(calls * policy['warning_fraction'])),
            'seconds': max(1, math.ceil(seconds * policy['warning_fraction']))}


def recommend(ledger, goal, mode, provider, model):
    from .learning import outcomes
    # Exact goal, same project/mode/provider/model. Similar wording alone is not
    # sufficient evidence to reduce a grant. Latest outcome wins per task.
    latest = {}
    for row in outcomes(ledger, 200): latest.setdefault(row['task'], row)
    matching = [r for r in latest.values() if r.get('spec_revision') == content_hash(goal)
                and (r.get('mode'), r.get('provider'), r.get('model')) == (mode, provider, model)]
    good = [r for r in matching if r['phase'] == 'completed'
            and r.get('verification') in ('passed', 'evidence_collected')
            and r.get('acceptance') not in ('changes_requested', 'rejected')
            and r.get('timing', {}).get('wall_seconds') is not None]
    enough = len(good) >= 3 and len(good) == len(matching)
    calls = min(10000, max(20, math.ceil(max(r['managed_calls'] for r in good) * 1.5))) if enough else DEFAULT_CALLS
    seconds = min(28800, max(600, math.ceil(max(r['timing']['wall_seconds'] for r in good) * 1.5))) if enough else DEFAULT_SECONDS
    return {'version': 1, 'classification': 'repeated_verified' if enough else 'insufficient_history',
            'recommended': {'max_calls': calls, 'max_seconds': seconds},
            'matching_tasks': len(matching), 'verified_tasks': len(good),
            'evidence': [{'task': r['task'], 'event': r['event']} for r in matching],
            'automatic_application': False, 'jev_used': False,
            'limitations': ['Exact goal match only; environment may differ.',
                           'Verification is not customer acceptance; wall time includes waits.',
                           'Observed history is not proof that the proposed budget is sufficient.']}


def timing(conn, task, state, attempts):
    checkpoint = conn.execute("SELECT created_at FROM events WHERE task_id=? AND kind='workflow.checkpoint' AND payload=? ORDER BY seq LIMIT 1",
                              (task['id'], canonical(state))).fetchone()
    end = checkpoint['created_at'] if checkpoint else None
    wall = max(0, (dt.datetime.fromisoformat(end)-dt.datetime.fromisoformat(task['created_at'])).total_seconds()) if end else None
    settled = [a for a in attempts if a['status'] == 'settled']
    attempt_seconds = sum(max(0, (dt.datetime.fromisoformat(a['updated_at'])-dt.datetime.fromisoformat(a['created_at'])).total_seconds()) for a in settled)
    return {'wall_seconds': wall, 'settled_attempt_seconds': attempt_seconds,
            'wait_seconds': None, 'includes_waits': True, 'active_compute_seconds': None}
