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


def _is_glob(path):
    return any(c in path for c in '*?[')


def _overlaps(a, b):
    """Do two write scopes (concrete paths or scope.owned patterns) share a path? The same rule as authority.owned_match: exact,
    directory prefix or glob, case-folded. A glob is compared by its literal prefix with a directory or another glob; a scope that
    cannot be validated overlaps everything (an unknown scope never runs beside a writer)."""
    try:
        a, b = authority._scope_path(a, pattern=True), authority._scope_path(b, pattern=True)
        if '.' in (a, b): return True
        for one, two in ((a, b), (b, a)):
            if not _is_glob(one) and authority.owned_match(one, [two]): return True
            if _is_glob(two) and not _is_glob(one) and two.split('*')[0].split('?')[0].split('[')[0].startswith(one + '/'): return True
        if _is_glob(a) and _is_glob(b):
            pa, pb = (x.split('*')[0].split('?')[0].split('[')[0] for x in (a, b))
            return pa.startswith(pb) or pb.startswith(pa)
        return False
    except LedgerError:
        return True


def _scope(ledger, conn, task, binding):
    """The write scope of a bound task: its sealed child paths, else the owned scope of its root revision; None when unknown."""
    try:
        paths = authority.child_wanted(task)[0].get('paths')
        if paths: return list(paths)
        from . import plan as plans
        state = plans.derive(ledger, conn, binding['selector'])
        if state is None or state['task_id'] != binding['root_task_id']: return None
        return list(plans.load(ledger, state, binding['revision'])[0]['scope']['owned']) or None
    except (LedgerError, ValueError, TypeError, KeyError, AttributeError):
        return None


def _shared(mine, theirs):
    return mine is None or theirs is None or any(_overlaps(a, b) for a in mine for b in theirs)


def _live(ledger, conn, task_id=None, action_id=None):
    """(peer task row, live identity) for every live write attempt (reserved/running/unknown, of a writing task) and every
    executing/unknown Control effect in the project, skipping `task_id`'s attempts and the effect `action_id`."""
    if conn.execute("SELECT 1 FROM sqlite_master WHERE name='attempts'").fetchone():
        for row in conn.execute("SELECT t.*, a.id AS active_id FROM attempts a JOIN tasks t ON t.id=a.task_id "
                                "WHERE t.project_id=? AND a.status IN ('reserved','running','unknown')", (ledger.project_id,)):
            if row['id'] != task_id and writes(row): yield row, row['active_id']
    if conn.execute("SELECT 1 FROM sqlite_master WHERE name='actions'").fetchone():
        for row in conn.execute("SELECT t.*, a.id AS active_id FROM actions a JOIN tasks t ON t.id=a.task_id "
                                "WHERE t.project_id=? AND a.status IN ('executing','unknown')", (ledger.project_id,)):
            if row['active_id'] != action_id: yield row, row['active_id']


def guard(ledger, conn, task, *, effect=False, action_id=None):
    """Call inside Control's write transaction before reservation/effect start.

    `effect` is supplied by trusted Control.execute_action, never task/model data.
    Durable Control actions are effects even when their task is a read-only
    managed candidate producer. Merely proposing/authorizing one acquires nothing.
    A live writer of ANOTHER root whose write scope overlaps this one also holds
    the scope (W12b, T32 E4 / T26 E4): one write has one live approval source.
    """
    binding = _binding(conn, task)
    if binding is None or (not effect and not writes(task)):
        return
    root = binding['root_task_id']
    mine = []
    for peer, identity in _live(ledger, conn, task['id'], action_id):
        other = _binding(conn, peer)
        if other is None: continue
        if other.get('root_task_id') == root:
            raise LedgerError(f"Root {binding['selector']} ({root}) already has live writer {peer['id']} ({identity}); "
                              'settle or reconcile it before another writer starts.')
        if not mine: mine.append(_scope(ledger, conn, task, binding))
        if _shared(mine[0], _scope(ledger, conn, peer, other)):
            raise LedgerError(f"Root {other.get('selector')} ({other.get('root_task_id')}) already has live writer {peer['id']} ({identity}) "
                              f"on a write scope that overlaps this task of root {binding['selector']} ({root}); one write has one approval "
                              'source: settle or reconcile it before another writer starts.')


def check_approval(ledger, conn, state, contract):
    """T26 E4 at approval: a plan-ns root whose scope.owned overlaps the write scope of a live writer of ANOTHER approved root is not
    approved (a second approval source for that work); the refusal names the existing root. Legacy plan: roots keep their behaviour;
    with no live writer the approval stands (the writer guard above still serialises later writers).

    Decided 25/10 round 6 under delegated authority (T26 [E4] reading): "cùng việc" is the SOL-linked work — 05 T26 Tiền điều kiện "cùng một việc
    có SOL v1 đã duyệt", Fixture "một SOL v1 đã duyệt, và một root v2 cho cùng việc"; 00 HD-07 "v1 và v2 không là hai nguồn duyệt độc lập cho cùng
    việc". The second approval for that work is refused by solution_link.validate_revision at propose, amend and approve (naming the existing
    root); tests/test_wf_t26_e4_one_source. Scope overlap alone is not the same work (T32 [E3]: several roots are legitimate), so this
    live-writer check stays as defence (T32 [E4]) and is not widened to every overlapping scope."""
    from . import namespaces
    if not state['selector'].startswith(namespaces.NAMESPACED): return
    owned = list(contract['scope']['owned'])
    for peer, identity in _live(ledger, conn):
        other = _binding(conn, peer)
        if other is None or other.get('root_task_id') == state['task_id']: continue
        if _shared(owned, _scope(ledger, conn, peer, other)):
            raise LedgerError(f"Approval refused: root {other.get('selector')} ({other.get('root_task_id')}) is the approval source of live "
                              f"writer {peer['id']} ({identity}) on a scope that overlaps scope.owned of {state['selector']}; a second approval "
                              'for the same work is refused (settle or reconcile that writer first). Nothing was recorded.')
