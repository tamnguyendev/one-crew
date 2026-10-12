"""Who decided each recorded decision (request replies, SOL decisions, CREQ replies). Read-only; never exports text."""
import json

from .delegations import ENTRY_ACTORS, RUNTIME_ACTORS, problem, valid_reference

SOURCES = ('user', 'relayed', 'delegated', 'undelegated', 'observed', 'unknown')
# Readable legacy keys: an 'entry' count without delegation evidence is an undelegated entry decision.
LEGACY = {'entry': 'undelegated'}


def source(provenance, sender=None, delegations=None, at=None):
    """user: the user sent it. relayed: an entry carried the user's decision with a reference to their words.
    delegated: an entry decided under a delegation that covers the class and time. undelegated: any other entry
    decision (legacy 'entry' included). observed: the runtime saw the condition resolve; not a decision.
    Anything not positively attributable, including a relay without a user reference, is unknown."""
    p = provenance if isinstance(provenance, dict) else {}
    by, decided, channel = p.get('by') or sender, p.get('decided_by'), p.get('channel')
    if channel == 'runtime_observed' or p.get('basis') == 'observed':
        return 'observed' if by in RUNTIME_ACTORS else 'unknown'
    if decided == 'entry' or channel in ('entry_delegated', 'entry_undelegated'):
        if channel == 'entry_delegated' and by in ENTRY_ACTORS and \
                problem((delegations or {}).get(p.get('delegation')), p.get('decision_class'), at) is None:
            return 'delegated'
        return 'undelegated'
    if by == 'user':
        return 'user'
    if decided == 'user' and by in ENTRY_ACTORS:
        return 'relayed' if valid_reference(p.get('user_reference')) else 'unknown'
    return 'unknown'


def receipt_source(receipt, sender=None, delegations=None):
    """A request.answered receipt, or a request.resolved event that carries its basis at top level."""
    if not isinstance(receipt, dict):
        return 'unknown'
    provenance = receipt['provenance'] if isinstance(receipt.get('provenance'), dict) else receipt if 'basis' in receipt else {}
    return source(provenance, sender, delegations, receipt.get('recorded_at') or receipt.get('at'))


def counts(values):
    result = dict.fromkeys(SOURCES, 0)
    for value in values:
        result[value if value in result else 'unknown'] += 1
    return result


def normalized(by_source):
    """A decisions_by_source mapping in the current keys; legacy keys stay readable."""
    if not isinstance(by_source, dict):
        return None
    result = dict.fromkeys(SOURCES, 0)
    for key, value in by_source.items():
        name = LEGACY.get(key, key)
        if name not in result or type(value) is not int:
            return None
        result[name] += value
    return result


def _table(conn, name):
    return bool(conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone())


def _marks(values):
    return ','.join('?' for _ in values)


def contract_decisions(conn, members, delegations=None):
    """SOL decisions on every solution these tasks were bound to (oldest first) and CREQ replies affecting them.
    The first approval is the handoff; earlier decisions belong to the discussion before it."""
    members = list(members)
    if not members or not _table(conn, 'solution_bindings') or not _table(conn, 'solution_decisions'):
        return None
    bound = conn.execute(f'SELECT conversation,solution FROM solution_bindings WHERE task_id IN ({_marks(members)})', members).fetchall()
    solutions = {r['solution'] for r in bound}
    for row in conn.execute(f"SELECT payload FROM events WHERE task_id IN ({_marks(members)}) AND kind='solution.amended'", members):
        solution = json.loads(row['payload']).get('solution')
        if isinstance(solution, str): solutions.add(solution)
    if not solutions:
        return None
    decisions = []
    for row in conn.execute(f'SELECT rowid AS n,* FROM solution_decisions WHERE solution IN ({_marks(solutions)}) ORDER BY rowid', sorted(solutions)):
        event = conn.execute("SELECT payload FROM conversation_events WHERE request_key=? AND kind='solution.decision'", (row['id'],)).fetchone() \
            if _table(conn, 'conversation_events') else None
        provenance = json.loads(event['payload']).get('decision') if event else None
        decisions.append({'choice': row['choice'], 'source': source(provenance, None, delegations, row['created_at'])})
    first = next((n for n, d in enumerate(decisions) if d['choice'] == 'approve'), None)
    replies = []
    conversations = sorted({r['conversation'] for r in bound})
    if conversations and _table(conn, 'conversation_questions'):
        for row in conn.execute(f"SELECT payload,answer FROM conversation_questions WHERE state='answered' AND conversation IN ({_marks(conversations)}) ORDER BY rowid", conversations):
            if set(json.loads(row['payload']).get('affected_tasks') or []) & set(members):
                answer = json.loads(row['answer']) if row['answer'] else {}
                replies.append(source(answer.get('decision') if isinstance(answer, dict) else None, None, delegations))
    later = decisions[first + 1:] if first is not None else []
    return {'handoff_approval': decisions[first]['source'] if first is not None else None,
            'later_solution_decisions': [d['source'] for d in later],
            'repeat_approvals': [d['source'] for d in later if d['choice'] == 'approve'],
            'creq_replies': replies}


def merge(metrics, contract):
    """Fold contract decisions into the observation: later SOL decisions and CREQ replies are decisions like any
    reply; the first approval is reported as the handoff it is."""
    metrics['handoff_approval'] = contract['handoff_approval'] if contract else None
    metrics['repeat_approvals'] = counts(contract['repeat_approvals']) if contract else None
    if not contract:
        return metrics
    extra = contract['later_solution_decisions'] + contract['creq_replies']
    by = normalized(metrics.get('decisions_by_source')) or dict.fromkeys(SOURCES, 0)
    for key, value in counts(extra).items():
        by[key] += value
    metrics['decisions_by_source'] = by
    metrics['decisions_answered'] = (metrics.get('decisions_answered') or 0) + len(extra)
    return metrics
