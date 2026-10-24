"""Shared dependency/owned-path closure extracted unchanged from amendment."""
from .ledger import LedgerError


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
