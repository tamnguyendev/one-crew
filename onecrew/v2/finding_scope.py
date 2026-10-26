"""W18: read-only engine holds projected from the existing finding register.

No node state or register is copied to another store. Dependency/read/write
influence uses the same v1 affected_tasks closure as internal revisions.
"""
from .. import dependency_core
from . import findings, namespaces, plan


def blockers(ledger, selector, nodes, conn=None):
    if conn is None:
        with ledger.transaction() as connection:
            return blockers(ledger, selector, nodes, connection)
    root = plan.anchor_events(ledger, conn, selector)
    if not namespaces.has_capability(root, 'finding-register'): return {}
    register_root, _, _, contract = findings._context(ledger, conn, root['selector'])
    value = findings._read(ledger, conn, register_root['id'])
    findings._refresh(value, contract, nodes or None)
    from . import internal_plan
    projection=internal_plan.influence_projection(nodes)
    result = {}
    for finding in value['findings']:
        if finding['status'] != 'open': continue
        scope = finding.get('scope') or {}
        paths = set(scope.get('read', []) + scope.get('write', []))
        seeds = [node['id'] for node in nodes if node['id'] == finding.get('node')
                 or paths & set(node['read'] + node['write']) or node['integration']]
        # Integration is the aggregate mandatory gate. A valid open finding
        # without a mapped path still blocks that gate, preserving independent
        # work until its scope is clarified through the original register.
        if not seeds: continue
        for nid in dependency_core.affected_tasks(projection, seeds):
            result.setdefault(nid, []).append(finding['id'])
    _release_repairs(ledger, result, value['findings'], nodes)
    return result


def _release_repairs(ledger, held, open_findings, nodes):
    """W21/W19 (T11 [E3]): the nodes a prepared repair re-issues for an internal-node finding (they carry the repair-evidence marker whose
    source receipt is that finding's receipt) are not held by that finding — otherwise nothing could ever repair it. Every other node in the
    scope stays held, and so does the finding until the register closes it on a passing receipt."""
    import json
    from ..snapshots import Snapshots
    from .repair_tasks import PREFIX, KIND as REPAIR_KIND
    by_receipt = {f['source']['receipt']: f['id'] for f in open_findings if f.get('internal') and f.get('status') == 'open'}
    # R10 D6: a second repair binds the finding's latest failed observation (merged on the repaired generation), not its first report;
    # without this the re-issued node stays held by the same finding and the repair can never run (deadlock).
    by_receipt.update({f['last_observed']['receipt']: f['id'] for f in open_findings
                       if f.get('internal') and f.get('status') == 'open' and (f.get('last_observed') or {}).get('receipt')})
    if not by_receipt: return
    store = Snapshots(ledger.state_root)
    for node in nodes:
        if node['id'] not in held: continue
        for marker in [i[len(PREFIX):] for i in node.get('input', []) if isinstance(i, str) and i.startswith(PREFIX)]:
            try:
                plan_ = json.loads(store.read_blob(marker))
            except Exception:                                   # noqa: BLE001 — an unreadable marker releases nothing
                continue
            if plan_.get('kind') != REPAIR_KIND: continue
            released = by_receipt.get(plan_.get('source_receipt'))
            if released and node['id'] in set(plan_.get('affected_nodes') or []):
                held[node['id']] = [f for f in held[node['id']] if f != released]
        if not held[node['id']]: del held[node['id']]


V2_SCOPED_TYPES = ('workflow.branch', 'authorize')      # the v1 branch question and the v2 U2 question (W32a) both name the nodes they hold


def request_blockers(ledger, selector, nodes, conn=None):
    """W18 (T07a [E14]): the branch hold that comes from PENDING REQUESTS, through v1's admission rule (`admission_core.blocking`, the
    same function the v1 controller uses) with the v2 policy: only a request that names its nodes holds them (plus their dependents
    through `dependency_core.affected_tasks`); a question without a scope holds nothing — independent work goes on (HD-25, T16).
    {node: [request ids]}; {} without the finding-register capability."""
    if conn is None:
        with ledger.transaction() as connection:
            return request_blockers(ledger, selector, nodes, connection)
    root = plan.anchor_events(ledger, conn, selector)
    if not namespaces.has_capability(root, 'finding-register') or not nodes: return {}
    from .. import admission_core
    from . import internal_plan
    rows = admission_core.pending(conn, root['task_id'])
    if not rows: return {}
    projection = internal_plan.influence_projection(nodes)
    result = {}
    for node in nodes:
        held = admission_core.blocking(rows, 'task:' + node['id'], scoped_types=V2_SCOPED_TYPES, unscoped_blocks=False)
        if not held: continue
        for nid in dependency_core.affected_tasks(projection, [node['id']]):
            for request_id in held:
                if request_id not in result.setdefault(nid, []): result[nid].append(request_id)
    return result


def write_scope(ledger, selector, conn=None):
    """The existing active-plan cache's precise write withdrawal projection."""
    if conn is None:
        with ledger.transaction() as connection: return write_scope(ledger, selector, connection)
    root=plan.anchor_events(ledger,conn,selector)
    if not namespaces.has_capability(root,'finding-register'): return {'paths':[],'findings':[],'nodes':[]}
    from . import internal_plan
    current=internal_plan.current(ledger,selector,conn)
    nodes=current['definition']['nodes'] if current['definition'] else []
    held=blockers(ledger,selector,nodes,conn)
    register_root,_,_,contract=findings._context(ledger,conn,selector)
    value=findings._read(ledger,conn,register_root['id']); findings._refresh(value,contract)
    opened=[finding for finding in value['findings'] if finding['status']=='open']
    paths={path for node in nodes if node['id'] in held for path in node['write']}
    for finding in opened:
        scope=finding.get('scope') or {}
        paths.update(scope.get('read',[])+scope.get('write',[]))
    return {'paths':sorted(paths),'findings':[finding['id'] for finding in opened],'nodes':sorted(held)}
