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
    findings._refresh(value, contract)
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
