"""Shared dependency/owned-path closure extracted unchanged from amendment."""
from .ledger import LedgerError


def ready_batch(state):
    ready = [r for r in state['plan']['tasks'] if r['id'] not in state['done'] and r['id'] not in state.get('branch_errors', {}) and set(r['depends_on']) <= set(state['done'])]
    if len(ready) < 2:
        return ready[:1]
    first = ready[0]
    second = next((r for r in ready[1:] if not set(r['owned']) & set(first['owned'])), None)
    return [first, second] if second else [first]


def initial_node_states(nodes):
    """The delivery node/generation constructor, shared without pack policy."""
    return {n['id']: {'phase': 'pending', 'generation': 0, 'receipt': None, 'child': None} for n in nodes}


def affected_tasks(plan, selected):
    tasks = {r['id']: r for r in plan['tasks']}
    if not isinstance(selected, list) or not selected or not all(isinstance(x, str) for x in selected) or not set(selected) <= set(tasks):
        raise LedgerError('Affected task IDs must be a non-empty subset of the current plan.')
    affected = set(selected)
    while True:
        owned = {p for key in affected for p in tasks[key]['owned']}
        expanded = affected | {key for key, row in tasks.items()
                               if set(row['depends_on']) & affected or set(row['owned']) & owned}
        if expanded == affected:
            return affected
        affected = expanded
