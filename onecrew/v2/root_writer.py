"""Root writer admission using existing Control attempts and durable intents.

No lease or second queue is created. Reserved/running/unknown write attempts and
executing/unknown effects retain ownership until the existing Control lifecycle
settles them. Sealed read-only tasks may compute isolated candidates concurrently;
their project publication is fenced as a Control effect, separately from compute.
Unbound v1 tasks keep their existing solution/DAG admission rules.
"""
from ..ledger import LedgerError
from . import authority, plan_binding


def _binding(conn, task):
    # Original submission survives a removed/mutated current payload. An old
    # writer does not lose its exclusion merely because its grant became stale.
    return plan_binding.submitted(conn, task) or plan_binding.read(task)


def writes(task):
    try:
        wanted, permissions = authority.child_wanted(task)
        return (any(wanted.get(key) for key in ('edit', 'apply_to_project', 'unconfined_commands', 'local_branches'))
                or bool(permissions & {'git.commit', 'git.push'}))
    except (ValueError, TypeError, KeyError, AttributeError) as error:
        raise LedgerError('Cannot establish root writer authority: ' + str(error)) from error


def guard(ledger, conn, task, *, effect=False, action_id=None):
    """Call inside Control's write transaction before reservation/effect start.

    `effect` is supplied by trusted Control.execute_action, never task/model data.
    Durable Control actions are effects even when their task is a read-only
    managed candidate producer. Merely proposing/authorizing one acquires nothing.
    """
    binding = _binding(conn, task)
    if binding is None or (not effect and not writes(task)):
        return
    root = binding['root_task_id']
    def same_root(peer):
        other = _binding(conn, peer)
        return other is not None and other.get('root_task_id') == root
    def refuse(peer, identity):
        raise LedgerError(f"Root {binding['selector']} ({root}) already has live writer {peer['id']} ({identity}); "
                          'settle or reconcile it before another writer starts.')
    for row in conn.execute("SELECT t.*, a.id AS active_id FROM attempts a JOIN tasks t ON t.id=a.task_id "
                            "WHERE t.project_id=? AND a.status IN ('reserved','running','unknown')", (ledger.project_id,)):
        if row['id'] != task['id'] and same_root(row) and writes(row):
            refuse(row, row['active_id'])
    for row in conn.execute("SELECT t.*, a.id AS active_id FROM actions a JOIN tasks t ON t.id=a.task_id "
                            "WHERE t.project_id=? AND a.status IN ('executing','unknown')", (ledger.project_id,)):
        if row['active_id'] != action_id and same_root(row):
            refuse(row, row['active_id'])
