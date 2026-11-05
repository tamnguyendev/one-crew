"""W18: read-only engine holds projected from the existing finding register.

No node state or register is copied to another store. Dependency/read/write
influence uses the same v1 affected_tasks closure as internal revisions.
"""
from .. import dependency_core
from ..ledger import content_hash
from . import findings, namespaces, plan


def blockers(ledger, selector, nodes, conn=None):
    return holds(ledger, selector, nodes, conn)['blockers']


def holds(ledger, selector, nodes, conn=None):
    """{'blockers': {node: [finding ids]} after the prepared repairs, 'raw': the same before them, 'covered': the external findings a prepared,
    authenticated repair is answering}. Read-only. A covered finding stays open until a verdict closes it; `covered` only says its repair is under way."""
    if conn is None:
        with ledger.transaction() as connection:
            return holds(ledger, selector, nodes, connection)
    root = plan.anchor_events(ledger, conn, selector)
    if not namespaces.has_capability(root, 'finding-register'): return {'blockers': {}, 'raw': {}, 'covered': []}
    register_root, _, _, contract = findings._context(ledger, conn, root['selector'])
    value = findings._read(ledger, conn, register_root['id'])
    findings._refresh(value, contract, nodes or None)
    from . import internal_plan
    projection=internal_plan.influence_projection(nodes)
    result = {}
    for finding in value['findings']:
        if finding['status'] != 'open': continue
        scope = finding.get('scope') or {}
        paths = scope.get('read', []) + scope.get('write', [])
        # A scope may name a folder and a node a file inside it (or the reverse): the rule of owned_match, not string equality.
        seeds = [node['id'] for node in nodes if node['id'] == finding.get('node')
                 or (paths and dependency_core.owned_overlap(paths, node['read'] + node['write'])) or node['integration']]
        # Integration is the aggregate mandatory gate. A valid open finding
        # without a mapped path still blocks that gate, preserving independent
        # work until its scope is clarified through the original register.
        if not seeds: continue
        for nid in dependency_core.affected_tasks(projection, seeds):
            result.setdefault(nid, []).append(finding['id'])
    raw = {nid: list(ids) for nid, ids in result.items()}
    covered = _release_repairs(ledger, conn, result, value['findings'], nodes, root)
    return {'blockers': result, 'raw': raw, 'covered': sorted(covered)}


def receipts_of(finding):
    """The failed receipts a repair of this finding may name: an external finding answers to its latest observation only (an older one no longer describes
    the delivered tree); an internal one also to its first report (R10 D6)."""
    if finding.get('internal'):
        rows = (finding['source'], finding.get('last_observed') or {})
    else:
        rows = (finding.get('last_observed') or finding['source'],)
    return [row['receipt'] for row in rows if row.get('receipt')]


def _sources_of(body):
    return {r for r in [body.get('source_receipt'), *(body.get('source_receipts') or [])] if r}


def _issued(conn, root, store, body, ref, node):
    """Only a marker issued by the repair door (or its authenticated order-only rebinding) can unblock work under a final finding."""
    import json
    original, origin = body, ref
    for _ in range(20):
        if not original.get('rebound_from'): break
        origin = original['rebound_from']
        try: original = json.loads(store.read_blob(origin))
        except (ValueError, OSError): return False
    row = conn.execute("SELECT 1 FROM events WHERE task_id=? AND kind='workflow.repair_prepared' AND json_extract(payload,'$.receipt')=?", (root['task_id'], origin)).fetchone()
    return bool(row and body.get('root') == root['task_id'] and root.get('approved')
                and body.get('contract_sha') == root['approved']['sha']
                and original.get('affected_nodes') == body.get('affected_nodes')
                and _sources_of(original) == _sources_of(body)
                and original.get('checks_sha', {}).get(node['id']) == body.get('checks_sha', {}).get(node['id'])
                and original.get('node_scopes', {}).get(node['id']) == {'read': node['read'], 'write': node['write']}
                and body.get('checks_sha', {}).get(node['id']) == content_hash(node['checks']))


def _release_repairs(ledger, conn, held, open_findings, nodes, root):
    """W21/W19 (T11 [E3]): the nodes a prepared repair re-issues (they carry the repair-evidence marker) are not held by the findings that repair answers:
    every failed receipt it names, each still the current observation of an open finding. Otherwise nothing could ever repair them. Every other node in
    the scope stays held, and so does the finding until the register closes it on a passing receipt. Returns the external findings a valid marker answers."""
    import json
    from ..snapshots import Snapshots
    from .repair_tasks import PREFIX, KIND as REPAIR_KIND
    by_receipt = {}
    # R10 D6: a second repair binds the finding's latest failed observation (merged on the repaired generation), not its first report;
    # without this the re-issued node stays held by the same finding and the repair can never run (deadlock).
    for finding in open_findings:
        if finding.get('status') != 'open': continue
        for receipt in receipts_of(finding):
            by_receipt.setdefault(receipt, []).append(finding)
    covered = set()
    if not by_receipt: return covered
    store = Snapshots(ledger.state_root)
    for node in nodes:
        for marker in [i[len(PREFIX):] for i in node.get('input', []) if isinstance(i, str) and i.startswith(PREFIX)]:
            try:
                body = json.loads(store.read_blob(marker))
            except Exception:                                   # noqa: BLE001 — an unreadable marker releases nothing
                continue
            if body.get('kind') != REPAIR_KIND: continue
            answered = [f for receipt in _sources_of(body) for f in by_receipt.get(receipt, [])]
            external = [f for f in answered if not f.get('internal')]
            authentic = bool(external) and _issued(conn, root, store, body, marker, node)
            released = {f['id'] for f in answered if f.get('internal') or authentic}
            if authentic: covered.update(f['id'] for f in external)
            if released and node['id'] in held and node['id'] in set(body.get('affected_nodes') or []):
                held[node['id']] = [f for f in held[node['id']] if f not in released]
        if node['id'] in held and not held[node['id']]: del held[node['id']]
    return covered


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
