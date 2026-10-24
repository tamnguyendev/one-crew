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
