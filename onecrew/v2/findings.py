"""W17: the shared finding register persisted on a namespaced plan root.

No new table or store: an event points at an immutable snapshot blob. The
finding_core module also owns v1's transitions. Authenticity of plan receipts
is checked here, before the common register sees a closure. Generation fencing
of executor results remains the executor's responsibility (W36).
"""
import argparse
import copy
import json
from pathlib import Path

from .. import finding_core as core
from ..ledger import Ledger, LedgerError, canonical, content_hash, text_field
from ..snapshots import Snapshots, scope_list
from . import contract as contracts, namespaces, plan as plans

KIND = 'finding.registered'  # class B: an open finding changes the gate
SEVERITIES = ('critical', 'major', 'minor')
MAX_FINDINGS = 500


def resolve_root(ledger, name, task_id=None, conn=None):
    """Resolve within this project; callers may supply the root task id.

    W12b resolves storage identity; plan.proposed binds the bare display name.
    """
    if conn is None:
        with ledger.transaction() as connection:
            if connection is None:
                raise LedgerError(f'No plan root {name!r} in this project.')
            return resolve_root(ledger, name, task_id, connection)
    bare, explicit = namespaces.parse(name)
    row = (conn.execute('SELECT id,project_id,request_key FROM tasks WHERE id=?', (task_id,)).fetchone()
           if task_id else namespaces.resolve(ledger, conn, name))
    if row is None or row['project_id'] != ledger.project_id or (explicit and row['request_key'] != explicit):
        raise LedgerError(f'No unique plan root {name!r} in this project.')
    root = dict(row)
    proposed = conn.execute("SELECT payload FROM events WHERE task_id=? AND kind='plan.proposed' ORDER BY seq LIMIT 1", (root['id'],)).fetchone()
    if proposed is None or json.loads(proposed['payload']).get('plan') != bare:
        raise LedgerError(f'Root task does not belong to plan {name!r}.')
    declaration = json.loads(proposed['payload'])
    namespaces.check_workflow(declaration)
    root.update({key: value for key, value in declaration.items() if key in ('workflow_version', 'capabilities')})
    if not root['request_key'].startswith('plan-ns:'):
        raise LedgerError('Finding state requires a plan-ns: root (W12b); a legacy plan: root is read-only.')
    return root


def _require_capability(root):
    if not namespaces.has_capability(root, 'finding-register'):
        raise LedgerError('This root did not declare the finding-register capability; schema-2 behavior is unchanged.')


def _context(ledger, conn, name, task_id=None, revision=None):
    root = resolve_root(ledger, name, task_id, conn)
    rows = conn.execute("SELECT payload FROM events WHERE task_id=? AND kind IN ('plan.proposed','plan.amended') ORDER BY seq", (root['id'],)).fetchall()
    revisions = [json.loads(row['payload']) for row in rows]
    latest = next((p for p in revisions if p['revision'] == revision), None) if revision is not None else max(revisions, key=lambda p: p['revision'])
    if latest is None:
        raise LedgerError(f'Plan {name} has no revision {revision}.')
    contract, sha = contracts.read_revision(ledger, root['request_key'], latest['revision'], latest['sha'])
    return root, latest['revision'], sha, contract


def _read(ledger, conn, task_id):
    row = conn.execute('SELECT payload FROM events WHERE task_id=? AND kind=? ORDER BY seq DESC LIMIT 1', (task_id, KIND)).fetchone()
    if row is None:
        return core.register({})
    payload = json.loads(row['payload'])
    try:
        value = json.loads(Snapshots(ledger.state_root).read_blob(payload['register']))
    except (OSError, ValueError) as error:
        raise LedgerError('Finding register snapshot cannot be read.') from error
    if not isinstance(value, dict) or not isinstance(value.get('findings'), list):
        raise LedgerError('Finding register snapshot is invalid.')
    return value


def _save(ledger, conn, root, name, revision, value, action, **details):
    blob = Snapshots(ledger.state_root).blob(canonical(value).encode('utf-8'))
    plans.emit(ledger, conn, root['id'], KIND,
               dict(plan=namespaces.parse(name)[0], revision=revision, register=blob, action=action, **details))


def _milestone(contract, node):
    found = next((m for m in contract['milestones'] if m['id'] == node), None)
    if found is None:
        raise LedgerError(f'Unknown finding node/milestone {node}.')
    return found


def _signature(milestone, criterion):
    config = milestone['verifier']['config']
    criteria = {c['id']: c for c in config.get('criteria', [])}
    if milestone['verifier']['type'] == 'reviewer' and criterion not in criteria:
        raise LedgerError(f'Unknown reviewer criterion {criterion}.')
    return content_hash(criteria.get(criterion, {'id': criterion})), content_hash(config)


def _refresh(value, contract, definition=None):
    """Changed criteria/configs invalidate old findings; no semantic inheritance. An internal-node finding (W21) is signed by the node's
    checks in the internal definition: without the definition at hand it is left as it is, with it a changed/removed node makes it stale."""
    for item in value['findings']:
        if item['status'] != 'open':
            continue
        try:
            if item.get('internal'):
                if definition is None:
                    continue
                signature = _signature(_node_milestone(definition, item['node']), item['criterion'])
            else:
                signature = _signature(_milestone(contract, item['node']), item['criterion'])
        except LedgerError:
            signature = None
        if signature is not None and signature != (item['criterion_sha'], item['config_sha']) and item.get('internal'):
            current = _wording_only(item, definition)
            if current is not None:
                # R10 D6: a wording-only change of this finding's own check (acceptance_diff 'same'/'wording') keeps it OPEN, rebound to
                # the current signature; origin, fail receipt, generation and closing condition stay. A real check change (changed,
                # threshold, removed) - or a finding without its recorded check (opened before round 10) - is made stale, as before.
                item.setdefault('wording_rebound_from', {'criterion_sha': item['criterion_sha'], 'config_sha': item['config_sha'], 'check': item['check']})
                item.update(criterion_sha=signature[0], config_sha=signature[1], check=current)
                continue
        if signature != (item['criterion_sha'], item['config_sha']):
            item.update(status='stale', stale_reason='criterion or reviewer configuration changed' if not item.get('internal') else 'node checks or definition changed')


def _wording_only(item, definition):
    """The current check of an internal finding when its recorded check still exists with the same or a reworded spec
    (acceptance_diff.classify_text 'same'/'wording'); None otherwise."""
    from .acceptance_diff import classify_text
    before = item.get('check')
    node = next((n for n in definition if n['id'] == item['node']), None)
    if not isinstance(before, dict) or node is None: return None
    after = next((c for c in node.get('checks', []) if isinstance(c, dict) and c.get('id') == item['criterion']), None)
    if after is None or classify_text(before.get('spec', ''), after.get('spec', '')) not in ('same', 'wording'): return None
    return dict(after)


# ---- W21: findings from the engine's node verification (an integration node that fails) ------------------------------------------------

def _node_milestone(definition, nid):
    """The register speaks in milestones; an internal node is presented as one whose criteria are its checks (signed by their content)."""
    item = next((n for n in definition if n['id'] == nid), None)
    if item is None:
        raise LedgerError(f'Unknown internal node {nid}.')
    return {'id': nid, 'internal': True, 'verifier': {'type': 'node-check', 'config': {'criteria': [dict(c) for c in item['checks']]}}}


def _node_proof(ledger, conn, root, nid, receipt):
    """A node receipt is evidence only when the engine published it: a `node.verification` event of this root points at it and agrees with it."""
    try:
        body = json.loads(Snapshots(ledger.state_root).read_blob(receipt))
    except (OSError, ValueError) as error:
        raise LedgerError('Finding evidence is not a valid receipt blob.') from error
    if not isinstance(body, dict) or body.get('kind') != 'node-verifier-receipt' or body.get('root') != root['id'] or body.get('node') != nid:
        raise LedgerError('Finding evidence is not a node verifier receipt of this root and node.')
    row = conn.execute("SELECT seq,payload FROM events WHERE task_id=? AND kind='node.verification' AND json_extract(payload,'$.receipt')=? ORDER BY seq DESC LIMIT 1",
                       (root['id'], receipt)).fetchone()
    if row is None:
        raise LedgerError('The node receipt has no published verification event on this root.')
    event = json.loads(row['payload'])
    if event.get('node') != nid or event.get('result') != body.get('result'):
        raise LedgerError('The node receipt differs from its published verification.')
    return body, body.get('result'), row['seq']


def node_scope(definition, nid):
    """The dependency scope of a node's finding (T11 [E1]): the nodes it depends on, and the paths they write / it reads."""
    item = next((n for n in definition if n['id'] == nid), None)
    if item is None:
        raise LedgerError(f'Unknown internal node {nid}.')
    by_id = {n['id']: n for n in definition}
    deps = [edge['node'] for edge in item.get('depends', []) if edge.get('node') in by_id]
    reads = set(item.get('read', []))
    if reads:
        # the integration node depends on every node (internal_plan._validate); the ones it integrates are those whose writes it reads
        narrowed = [dep for dep in deps if reads & set(by_id[dep].get('write', []))]
        deps = narrowed or deps
    write = sorted({path for dep in deps for path in by_id[dep].get('write', [])})
    read = sorted({path for dep in deps for path in by_id[dep].get('read', [])} | set(item.get('read', [])))
    return {'nodes': sorted(deps), 'read': read, 'write': write}


def record_node_verification(ledger, selector, nid, receipt, *, definition, severity='major', task_id=None, conn=None):
    """W21 (T11 [E1]): a failed check of an engine node becomes a finding attached to that node, scoped by its dependency edges; a passing
    receipt of the same node closes the internal findings whose check now passes. Nothing is written when there is nothing to open, merge or
    close (a green node without findings leaves no event). Returns {'opened','merged','closed','scope'}."""
    if conn is None:
        with ledger.transaction(write=True) as connection:
            result = record_node_verification(ledger, selector, nid, receipt, definition=definition, severity=severity, task_id=task_id, conn=connection)
        if result['opened'] or result['merged'] or result['closed']:
            after_change(ledger, selector)
        if result['opened']:
            hold_decided(ledger, selector, result['opened'], receipt, definition)
        return result
    root, revision, sha, contract = _context(ledger, conn, selector, task_id)
    _require_capability(root)
    body, result, seq = _node_proof(ledger, conn, root, nid, receipt)
    scope = node_scope(definition, nid)
    processed = conn.execute("SELECT payload FROM events WHERE task_id=? AND kind=? AND json_extract(payload,'$.action')='node-verification' "
                             "AND json_extract(payload,'$.receipt')=? LIMIT 1", (root['id'], KIND, receipt)).fetchone()
    if processed:
        previous = json.loads(processed['payload'])
        return {'opened': [], 'merged': previous.get('opened', []) + previous.get('merged', []), 'closed': previous.get('closed', []), 'scope': scope}
    value = _read(ledger, conn, root['id'])
    _refresh(value, contract, definition)
    milestone = _node_milestone(definition, nid)
    rows = [r for r in (body.get('observed') or {}).get('checks', []) if isinstance(r, dict)]
    opened, merged, closed = [], [], []
    for row in rows:
        if row.get('result') == 'fail':
            claim = canonical({'criterion': row.get('id'), 'evidence': [row.get('evidence')] if row.get('evidence') else []})
            item, fresh = _new(ledger, value, selector, revision, sha, milestone, row['id'], claim, receipt, body['artifact'], body.get('generation', 1),
                               severity, scope['read'], scope['write'], seq)
            if fresh:
                item['internal'] = True
                item['scope_nodes'] = scope['nodes']
                # R10 D6: the check as it was when the finding opened (a later wording-only revise keeps the finding open)
                item['check'] = next((dict(c) for c in milestone['verifier']['config']['criteria'] if c['id'] == row['id']), None)
            (opened if fresh else merged).append(item['id'])
    if result == 'pass':
        for item in value['findings']:
            if item['status'] == 'open' and item.get('internal') and item['node'] == nid and any(r.get('id') == item['criterion'] and r.get('result') == 'pass' for r in rows):
                observed_seq = max(item['source']['verdict_seq'], item.get('last_observed', {}).get('verdict_seq', 0))
                if seq <= observed_seq:
                    continue
                core.close_finding(value, item['id'], receipt, shown=[receipt], listed=[item['id']],
                                   resolution={'receipt': receipt, 'artifact_sha': body['artifact'], 'candidate': body['artifact'], 'revision': revision,
                                               'generation': body.get('generation', 1), 'reason': f'check {item["criterion"]} of node {nid} passes on a later generation',
                                               'evidence': [receipt]}, status='resolved')
                closed.append(item['id'])
    if opened or merged or closed:
        _save(ledger, conn, root, selector, revision, value, 'node-verification', receipt=receipt, node=nid, opened=opened, merged=merged, closed=closed,
              scope_nodes=scope['nodes'])
    return {'opened': opened, 'merged': merged, 'closed': closed, 'scope': scope}


def _proof(ledger, conn, root, name, revision, sha, contract, node, receipt, generation, artifact_sha=None, latest=False):
    name = namespaces.parse(name)[0]
    if type(generation) is not int or generation < 1:
        raise LedgerError('generation must be a positive integer.')
    milestone = _milestone(contract, node)
    try:
        body = json.loads(Snapshots(ledger.state_root).read_blob(receipt))
    except (OSError, ValueError) as error:
        raise LedgerError('Finding evidence is not a valid receipt blob.') from error
    if not isinstance(body, dict):
        raise LedgerError('Finding evidence is not a receipt object.')
    if body.get('generation', 1) != generation:
        raise LedgerError('Finding evidence belongs to a different generation.')
    artifact = body.get('artifact_sha')
    if artifact_sha is not None and artifact != artifact_sha:
        raise LedgerError('Finding evidence belongs to a different artifact.')
    issued = set()
    issuances = []
    verdicts = []
    for row in conn.execute("SELECT seq,kind,payload FROM events WHERE task_id=? AND kind IN ('verdict.receipt_issued','verdict.recorded') ORDER BY seq", (root['id'],)):
        p = json.loads(row['payload'])
        if row['kind'] == 'verdict.receipt_issued':
            issued.add((p['revision'], p['milestone'], p['receipt']))
            issuances.append(dict(p, event_seq=row['seq']))
        else:
            verdicts.append(dict(p, event_seq=row['seq']))
    matching = [v for v in verdicts if v.get('revision') == revision and v.get('milestone') == node and v.get('receipt') == receipt
                and v.get('artifact_sha') == artifact and v.get('generation', 1) == generation]
    observed_generations = [v.get('generation', 1) for v in verdicts + issuances if v.get('revision') == revision and v.get('milestone') == node]
    if any(type(g) is not int or g < 1 for g in observed_generations) or generation != max(observed_generations, default=1):
        raise LedgerError('Finding evidence is not from the current recorded generation.')
    if not matching:
        raise LedgerError('Finding evidence needs a recorded verdict for the current revision/generation.')
    if latest:
        applicable = [v for v in verdicts if v.get('revision') == revision and v.get('milestone') == node and v.get('generation', 1) == generation]
        issued_here = [v for v in issuances if v.get('revision') == revision and v.get('milestone') == node and v.get('generation', 1) == generation]
        if (matching[-1]['event_seq'] != max(v['event_seq'] for v in applicable)
                or not issued_here or max(issued_here, key=lambda v: v['event_seq'])['receipt'] != receipt):
            raise LedgerError('Finding evidence was superseded by a later verification; use the latest applicable receipt.')
    result = matching[-1]['result']
    from .verdict import _check_receipt
    _check_receipt(ledger, name, revision, sha, milestone, result, milestone['verifier']['type'], artifact, receipt, issued)
    return body, result, matching[-1]['event_seq']


def _scope(read, write):
    return {'read': scope_list(list(read)) if read else [], 'write': scope_list(list(write)) if write else []}


def _new(ledger, value, name, revision, sha, milestone, criterion, claim, receipt, artifact, generation, severity, read, write, verdict_seq):
    text_field(claim, 'finding claim', 200000)
    if severity not in SEVERITIES:
        raise LedgerError('Finding severity must be critical, major or minor.')
    criterion_sha, config_sha = _signature(milestone, criterion)
    # V1's whole-claim key is retained; plan/node/criterion identify its context.
    key = content_hash([milestone['id'], criterion, criterion_sha, config_sha, core.claim_key(claim)])
    existing = next((f for f in value['findings'] if f['status'] == 'open' and f['norm'] == key), None)
    if existing:
        # Keep the first report's provenance; the most recent observation is a
        # separate fact, so a superseded green receipt cannot close this defect.
        existing['last_observed'] = {'receipt': receipt, 'verdict_seq': verdict_seq, 'artifact_sha': artifact,
                                     'revision': revision, 'generation': generation}
        return existing, False
    if len(value['findings']) >= MAX_FINDINGS:
        raise LedgerError('Finding register is full; nothing was accepted.')
    blob = Snapshots(ledger.state_root).blob(claim.encode('utf-8'))
    # 2.5-A: the same defect re-appearing after a RESOLVED closure is a recurrence of that finding (linked both ways), not a new bug.
    # A rejected finding was judged not to be a defect, so it is not linked.
    prior = next((f for f in reversed(value['findings']) if f['status'] == 'resolved' and f['norm'] == key), None)
    entry = core.append_finding(value, {'plan': namespaces.parse(name)[0], 'revision': revision, 'plan_sha': sha, 'node': milestone['id'],
        'criterion': criterion, 'criterion_sha': criterion_sha, 'config_sha': config_sha,
        'candidate': artifact, 'artifact_sha': artifact, 'generation': generation, 'severity': severity,
        'scope': _scope(read, write), 'norm': key, 'chars': len(claim), 'head': core.safe(claim[:500]),
        'blob': blob, 'source': {'receipt': receipt, 'verdict_seq': verdict_seq}, 'review': value['review']})
    if prior:
        entry['recurrence_of'] = prior['id']
        prior.setdefault('recurred_as', []).append(entry['id'])
    return entry, True


def after_change(ledger, name):
    """After the register changed and committed: re-export the active plan (external hooks withdraw writes) and ask running
    managed attempts of held nodes to pause at their next safe point. Neither may undo the committed register change."""
    from . import active_plan
    managed = False
    try:
        with ledger.transaction() as conn:
            root = plans.anchor_events(ledger, conn, name)
            managed = namespaces.has_capability(root, 'sequential-engine')
            seq = active_plan.register_seq(conn, root['task_id'])
        if managed:
            # the marker goes first: if the export below fails, the hot hook sees a register newer than the plan it has and refuses writes
            active_plan._write(active_plan.holds_marker(ledger.project), {'anchor': root['selector'], 'register_seq': seq})
    except (LedgerError, OSError, ValueError) as error:
        import sys
        print('OneCrew holds marker not written: ' + type(error).__name__ + ': ' + str(error)[:200], file=sys.stderr)
    active_plan.export(ledger, name)
    try:
        if managed:
            from . import managed_executor
            return managed_executor.hold_for_findings(ledger, name)
    except (LedgerError, OSError, ValueError) as error:
        import sys
        print('OneCrew managed hold pending: ' + type(error).__name__ + ': ' + str(error)[:200], file=sys.stderr)
    return []


REOPEN = 'the finding closes through the register only: resolve on a passing receipt or reject with evidence (HD-25)'


def hold_decided(ledger, name, opened, receipt, definition=None):
    """T16b [E6] / round 8 G: Q8 - the newly opened findings hold exactly their affected scope (finding_scope.blockers, the engine's own
    projection). The hold is the SAFE default (HD-25: the affected branch takes no new work) and it is in force before this runs: it is a
    projection of the committed register, never skipped for lack of delegation. What needs authority is the opposite move - continuing
    despite a finding - and OneCrew has no such move: the branch reopens only when the register closes the finding (REOPEN), and
    engine.resume_held refuses while it is open. So this only RECORDS, through internal_plan.self_decided (the one decide()):
    delegated -> the HD-05 record; a workflow grant that does not delegate Q8 -> the U3 out-of-authority record of the same safety hold
    (scope, reopen condition), no request card (a `continue` card could not reopen a finding-held branch); a root with no workflow
    grant -> nothing new, as before. Written after the register change has committed; like after_change, a failure here never undoes
    that change, it is reported on stderr. Returns the self_decided verdict, or None when nothing is held."""
    from . import finding_scope, internal_plan
    try:
        nodes = definition if definition is not None else ((internal_plan.current(ledger, name).get('definition') or {}).get('nodes') or [])
        held = sorted(nid for nid, ids in finding_scope.blockers(ledger, name, nodes).items() if set(ids) & set(opened))
        if not held: return None
        return internal_plan.self_decided(ledger, name, 'Q8', held, 'onecrew.findings', key='q8-hold-' + receipt[:48],
                                          findings=sorted(opened), evidence=[receipt], hold='safety', reopen=REOPEN)
    except (LedgerError, OSError, ValueError) as error:
        import sys
        print('OneCrew Q8 hold decision not recorded: ' + type(error).__name__ + ': ' + str(error)[:200], file=sys.stderr)
        return None


def record_review(ledger, name, node, receipt, *, generation=1, severity='major', read=(), write=(), task_id=None, conn=None, revision=None):
    """Register failed criteria only; outside_criteria remain in the receipt.

    Call after receipt issuance and verdict recording. Pass/generic acceptance
    never closes anything: explicit resolve/reject is the sole closure route.
    """
    return record_verification(ledger, name, node, receipt, generation=generation, severity=severity, read=read, write=write,
                               task_id=task_id, conn=conn, revision=revision, reviewer_only=True)


def record_verification(ledger, name, node, receipt, *, generation=1, severity='major', read=(), write=(), task_id=None,
                        conn=None, revision=None, reviewer_only=False):
    """The same register for failed reviewer criteria or authentic adapter checks.

    Adapter claims about status/closure are never transitions. Only failed checks
    in a core-issued, recorded receipt become findings; advisory text stays there.
    """
    if conn is None:
        with ledger.transaction(write=True) as connection:
            result=record_verification(ledger, name, node, receipt, generation=generation, severity=severity, read=read, write=write,
                                      task_id=task_id, conn=connection, revision=revision, reviewer_only=reviewer_only)
        after_change(ledger, name)
        if result['opened']:
            hold_decided(ledger, name, result['opened'], receipt)
        return result
    root, revision, sha, contract = _context(ledger, conn, name, task_id, revision)
    _require_capability(root)
    body, result, verdict_seq = _proof(ledger, conn, root, name, revision, sha, contract, node, receipt, generation)
    is_review = body.get('kind') == 'reviewer-receipt'
    if reviewer_only and not is_review:
        raise LedgerError('record_review needs a reviewer receipt.')
    if not is_review:
        from .verifiers import port
        kind = _milestone(contract, node)['verifier']['type']
        if not port.known(kind) or body.get('kind') != port.receipt_kind(kind):
            raise LedgerError('Finding verification needs a reviewer or registered adapter receipt.')
    action = 'review' if is_review else 'verification'
    processed = conn.execute("SELECT payload FROM events WHERE task_id=? AND kind=? "
                             "AND json_extract(payload,'$.action')=? AND json_extract(payload,'$.receipt')=? LIMIT 1",
                             (root['id'], KIND, action, receipt)).fetchone()
    if processed:
        previous = json.loads(processed['payload'])
        return {'opened': [], 'merged': previous.get('opened', []) + previous.get('merged', []), 'closed': []}
    value = _read(ledger, conn, root['id'])
    _refresh(value, contract)
    opened, merged = [], []
    for row in body.get('criteria' if is_review else 'checks') or []:
        failed = row.get('verdict') == 'fail' if is_review else row.get('ok') is False or bool(row.get('problems'))
        if not failed:
            continue
        criterion = row['id']
        claim = canonical({'criterion': criterion, 'evidence': row.get('evidence' if is_review else 'problems') or []})
        item, fresh = _new(ledger, value, name, revision, sha, _milestone(contract, node), criterion, claim, receipt,
                           body['artifact_sha'], generation, severity, read, write, verdict_seq)
        (opened if fresh else merged).append(item['id'])
    _save(ledger, conn, root, name, revision, value, action, receipt=receipt, opened=opened, merged=merged)
    return {'opened': opened, 'merged': merged, 'closed': []}


def list_findings(ledger, name, *, task_id=None, open_only=False):
    """Read-only materialized register; stale status is computed from current contract."""
    with ledger.transaction() as conn:
        root, revision, sha, contract = _context(ledger, conn, name, task_id)
        if not namespaces.has_capability(root, 'finding-register'):
            return []
        value = _read(ledger, conn, root['id'])
        _refresh(value, contract)
    return [copy.deepcopy(item) for item in value['findings'] if not open_only or item['status'] == 'open']


def reviewer_context(ledger, name, node=None, *, task_id=None):
    """Include these findings in the next review prompt, preserving full claims."""
    rows = list_findings(ledger, name, task_id=task_id, open_only=True)
    store = Snapshots(ledger.state_root)
    return [dict(row, claim=store.read_blob(row['blob']).decode('utf-8')) for row in rows if node is None or row['node'] == node]


def update(ledger, name, ident, *, reason, severity=None, read=None, write=None, task_id=None):
    text_field(reason, 'finding update reason', 2000)
    with ledger.transaction(write=True) as conn:
        root, revision, sha, contract = _context(ledger, conn, name, task_id)
        _require_capability(root)
        value = _read(ledger, conn, root['id'])
        _refresh(value, contract)
        target = next((f for f in value['findings'] if f['id'] == ident and f['status'] == 'open'), None)
        if target is None:
            raise LedgerError(f'{ident} is not an open finding.')
        if severity is not None:
            if severity not in SEVERITIES:
                raise LedgerError('Finding severity must be critical, major or minor.')
            target['severity'] = severity
        target['scope'] = _scope(target['scope']['read'] if read is None else read, target['scope']['write'] if write is None else write)
        _save(ledger, conn, root, name, revision, value, 'update', finding=ident, reason=reason)
    after_change(ledger, name)
    return copy.deepcopy(target)


def _criterion_passes(target, body):
    """The receipt shows this finding's own criterion passing (node check, reviewer criterion or adapter check); LedgerError otherwise."""
    if target.get('internal'):
        criterion = next((c for c in (body.get('observed') or {}).get('checks') or [] if c.get('id') == target['criterion']), None)
        if criterion is None or criterion.get('result') != 'pass':
            raise LedgerError('The evidence does not pass this finding check.')
    elif body.get('kind') == 'reviewer-receipt':
        criterion = next((c for c in body.get('criteria') or [] if c.get('id') == target['criterion']), None)
        if criterion is None or criterion.get('verdict') != 'pass':
            raise LedgerError('The evidence does not pass this finding criterion.')
    else:
        criterion = next((c for c in body.get('checks') or [] if c.get('id') == target['criterion']), None)
        if criterion is None or criterion.get('ok') is not True or criterion.get('problems'):
            raise LedgerError('The evidence does not pass this finding check.')


def resolve(ledger, name, ident, receipt, *, reason, artifact_sha, generation=1, reject=False, task_id=None):
    """Explicit evidenced resolution/rejection. Refusals are durable and leave it open."""
    text_field(reason, 'finding resolution reason', 2000)
    with ledger.transaction(write=True) as conn:
        root, revision, sha, contract = _context(ledger, conn, name, task_id)
        _require_capability(root)
        value = _read(ledger, conn, root['id'])
        _refresh(value, contract)
        target = next((f for f in value['findings'] if f['id'] == ident), None)
        try:
            if target is None or target['status'] != 'open':
                raise LedgerError(f'{ident} is not an open finding.')
            if target.get('internal'):
                body, result, verdict_seq = _node_proof(ledger, conn, root, target['node'], receipt)
            else:
                body, result, verdict_seq = _proof(ledger, conn, root, name, revision, sha, contract, target['node'], receipt, generation, artifact_sha, latest=True)
            observed_seq = max(target['source']['verdict_seq'], target.get('last_observed', {}).get('verdict_seq', 0))
            if verdict_seq <= observed_seq:
                raise LedgerError('Resolution evidence predates the finding; verify it again.')
            if result != 'pass':
                raise LedgerError('A finding closes only with passing verification evidence.')
            _criterion_passes(target, body)
            core.close_finding(value, ident, receipt, shown=[receipt], listed=[ident],
                resolution={'receipt': receipt, 'artifact_sha': artifact_sha, 'candidate': artifact_sha, 'revision': revision,
                            'generation': generation, 'reason': reason, 'evidence': [receipt]},
                status='rejected' if reject else 'resolved')
            result_view = {'closed': [ident], 'refused': []}
        except LedgerError as error:
            result_view = {'closed': [], 'refused': [str(error)]}
        _save(ledger, conn, root, name, revision, value, 'reject' if reject else 'resolve', finding=ident, **result_view)
    after_change(ledger, name)
    return result_view


# ---- 2.5-A cycle 2: closing a finding from an authentic recheck bound to a request ----------------------------------------------------

def _repair_link(ledger, conn, name, source_receipts):
    """The repair assignment (node-repair-plan receipt in a node's inputs) that answered the finding's failing receipt, or None. Read-only."""
    from . import engine, repair_tasks
    try:
        view = engine.state(ledger, name, conn)
        store = Snapshots(ledger.state_root)
        for item in (view['definition'] or {}).get('nodes', []):
            for ref in item['input']:
                if not isinstance(ref, str) or not ref.startswith(repair_tasks.PREFIX): continue
                issued = json.loads(store.read_blob(ref[len(repair_tasks.PREFIX):]))
                if {issued.get('source_receipt'), *(issued.get('source_receipts') or [])} & set(source_receipts):
                    return {'repair': ref[len(repair_tasks.PREFIX):], 'target': issued.get('target'), 'failed_node': issued.get('failed_node')}
    except (LedgerError, OSError, ValueError, KeyError, TypeError):
        pass
    return None


def _recheck_evidence(ledger, conn, root, name, revision, sha, contract, target, receipt, request):
    """Raise LedgerError unless `receipt` is an authentic recheck of `target`'s criterion, on a repaired output, for a current request
    bound to that output. Returns the resolution evidence. Nothing here trusts a claim: receipts are authenticated through the same
    core-issued events as resolve, and the request must agree with them on root, contract, node, criterion, candidate and generation."""
    from . import review_request as rr
    if rr.kind_of(request) is None or request['version'] != rr.CHECK_VERSION:
        raise LedgerError('The recheck request is missing, malformed or a legacy descriptor; build it with review_request.build_check.')
    ident = request['identity']
    if ident['root'] != {'project_id': ledger.project_id, 'task_id': root['id']}:
        raise LedgerError('The recheck request belongs to another root.')
    if (ident['contract_revision'], ident['contract_sha']) != (revision, sha):
        raise LedgerError('Stale recheck request: it binds another contract revision.')
    internal = bool(target.get('internal'))
    if rr.kind_of(request) != ('node' if internal else 'milestone'):
        raise LedgerError('The recheck request kind does not match the finding.')
    refs = ident['target']
    if target['criterion'] not in refs['criteria_ids']:
        raise LedgerError('The recheck request does not cover the failed criterion.')
    if internal:
        if refs['node'] != target['node']:
            raise LedgerError('The recheck request is for another node.')
        body, result, seq = _node_proof(ledger, conn, root, target['node'], receipt)
        artifact, generation = body.get('artifact'), body.get('generation', 1)
        if ident['criteria'] != body.get('checks_sha'):
            raise LedgerError('The recheck request criteria differ from the checks the receipt ran.')
        if refs['generation'] != generation:
            raise LedgerError('The recheck request names another generation than the receipt.')
        from . import engine
        record = engine.state(ledger, name, conn)['nodes'].get(target['node']) or {}
        if record.get('artifact') != artifact or record.get('generation') != generation:
            raise LedgerError('Stale recheck: the node has a newer generation/candidate than this receipt verified.')
        produced = conn.execute("SELECT seq FROM events WHERE task_id=? AND kind='node.produced' AND json_extract(payload,'$.node')=? "
                                "AND json_extract(payload,'$.generation')=? AND json_extract(payload,'$.artifact')=? ORDER BY seq LIMIT 1",
                                (root['id'], target['node'], generation, artifact)).fetchone()
        if produced is None:
            raise LedgerError('The receipt does not verify a produced output of this node generation.')
        output = {'generation': generation, 'artifact': artifact, 'produced_seq': produced['seq']}
    else:
        if refs['milestone'] != target['node'] or refs['plan'] != namespaces.parse(name)[0] or refs['plan_sha'] != sha:
            raise LedgerError('The recheck request is for another milestone or plan.')
        expected = _milestone(contract, target['node'])['verifier']['config'].get('criteria')
        if expected is not None and ident['criteria'] != content_hash(expected):
            raise LedgerError('The recheck request criteria differ from the milestone criteria.')
        try:
            raw = json.loads(Snapshots(ledger.state_root).read_blob(receipt))
        except (OSError, ValueError) as error:
            raise LedgerError('Finding evidence is not a valid receipt blob.') from error
        if not isinstance(raw, dict): raise LedgerError('Finding evidence is not a receipt object.')
        generation, artifact = raw.get('generation', 1), raw.get('artifact_sha')
        body, result, seq = _proof(ledger, conn, root, name, revision, sha, contract, target['node'], receipt, generation, artifact, latest=True)
        output = {'generation': generation, 'artifact': artifact}
    if body.get('request_id') not in (None, request['id']):
        raise LedgerError('The receipt belongs to another request.')
    if artifact is None or ident['evidence']['candidate'] != artifact:
        raise LedgerError('The recheck request is bound to another candidate than the receipt verified.')
    if artifact in (target.get('artifact_sha'), target.get('candidate')):
        raise LedgerError('The receipt verifies the same candidate that failed; a recheck needs the repaired output.')
    if seq <= max(target['source']['verdict_seq'], (target.get('last_observed') or {}).get('verdict_seq', 0)):
        raise LedgerError('Recheck evidence predates the finding; verify it again.')
    if result != 'pass':
        raise LedgerError('A finding closes only with passing verification evidence.')
    _criterion_passes(target, body)
    sources = [target['source']['receipt'], (target.get('last_observed') or {}).get('receipt')]
    return dict(output, recheck={'request': request['id'], 'kind': ident['kind'], 'candidate': artifact,
                                 'criteria_ids': refs['criteria_ids'], 'verdict_seq': seq},
                repair=_repair_link(ledger, conn, name, [s for s in sources if s]))


def close_from_recheck(ledger, selector, finding_id, *, run_receipt, request, task_id=None):
    """Close finding `finding_id` only when an authentic recheck receipt for a request bound to the repaired output shows its criterion
    passing. A worker's or reviewer's own claim, an unrelated or older-candidate receipt, a receipt that predates the finding, a request
    for another root/contract/node/criterion/candidate/generation, or a stale request is refused with its reason, durably, and the finding
    stays open. A defect that re-appears after this closure becomes a new finding linked by `recurrence_of`. Returns {'closed','refused'}."""
    with ledger.transaction(write=True) as conn:
        root, revision, sha, contract = _context(ledger, conn, selector, task_id)
        _require_capability(root)
        value = _read(ledger, conn, root['id'])
        _refresh(value, contract)
        target = next((f for f in value['findings'] if f['id'] == finding_id), None)
        rid = request.get('id') if isinstance(request, dict) else None
        try:
            if target is None or target['status'] != 'open':
                raise LedgerError(f'{finding_id} is not an open finding.')
            if not isinstance(run_receipt, str) or not run_receipt:
                raise LedgerError('A closure needs the receipt of a recheck, not a claim.')
            found = _recheck_evidence(ledger, conn, root, selector, revision, sha, contract, target, run_receipt, request)
            core.close_finding(value, finding_id, run_receipt, shown=[run_receipt], listed=[finding_id],
                               resolution=dict(found, receipt=run_receipt, artifact_sha=found['artifact'], candidate=found['artifact'],
                                               revision=revision, reason='recheck of the repaired output passes this criterion',
                                               evidence=[run_receipt]), status='resolved')
            view = {'closed': [finding_id], 'refused': []}
        except LedgerError as error:
            view = {'closed': [], 'refused': [str(error)]}
        _save(ledger, conn, root, selector, revision, value, 'recheck-close', finding=finding_id,
              receipt=run_receipt if isinstance(run_receipt, str) else None, request=rid, **view)
    after_change(ledger, selector)
    return view


# ---- E29 (T35c): "finding F was missed by SKIP decision S" ------------------------------------------------------------------------------
# No new store: the SKIP is the HD-20 decision record review_policy.decide wrote (decision.recorded, subject review_policy/rules,
# validity.action SKIP), the finding is this register's entry, and the link itself is one more decision.recorded on the same root
# (subject finding_skip_link/rules) written through decisions.record, so the W03 guards (no owner signature from an AI session, the
# root's approved grant) apply unchanged. A SKIP covers exactly (root, approved revision + contract sha, artifact, optional review id):
# a finding is attributable to it only when it is on the same root, the same revision and contract sha, the same artifact (the defect
# was in what was skipped), was opened after the SKIP, and the link names that review. Nothing is attributed automatically.

SKIP_LINK = 'finding_skip_link'


def _skip_records(conn, task_id):
    """HD-20 SKIP records of review_policy on this root: {key: {id, seq, review, revision, contract_sha, artifact_sha}}."""
    out = {}
    for row in conn.execute("SELECT seq,payload FROM events WHERE task_id=? AND kind='decision.recorded' ORDER BY seq", (task_id,)):
        p = json.loads(row['payload'])
        v = p.get('validity') if isinstance(p.get('validity'), dict) else {}
        if p.get('subject') == {'component': 'review_policy', 'model': 'rules'} and v.get('action') == 'SKIP' and p.get('key'):
            out.setdefault(p['key'], {'id': p['key'], 'seq': row['seq'], 'review': p.get('scope'), 'revision': v.get('revision'),
                                      'contract_sha': v.get('contract_sha'), 'artifact_sha': v.get('artifact_sha')})
    return out


def _opened_seq(conn, task_id, ident):
    for row in conn.execute('SELECT seq,payload FROM events WHERE task_id=? AND kind=? ORDER BY seq', (task_id, KIND)):
        if ident in (json.loads(row['payload']).get('opened') or []):
            return row['seq']
    return None


def _link_problem(skip, finding, opened_seq, review):
    """Why `finding` cannot be attributed to `skip` (None when it can)."""
    if skip is None:
        return 'no review_policy SKIP (HD-20) record with this id on this root'
    if finding is None:
        return 'no finding with this id in the register of this root'
    if review != skip['review']:
        return f'the SKIP covered optional review {skip["review"]}, not {review}'
    if (finding.get('revision'), finding.get('plan_sha')) != (skip['revision'], skip['contract_sha']):
        return f'the finding is on revision {finding.get("revision")}, the SKIP applied to revision {skip["revision"]} (another contract)'
    if finding.get('artifact_sha') != skip['artifact_sha']:
        return 'the finding is on another artifact than the one the SKIP applied to'
    if opened_seq is None or opened_seq <= skip['seq']:
        return 'the finding was not opened after the SKIP'
    return None


def link_skip(ledger, name, ident, skip_record, *, review, reason, by=None, task_id=None):
    """Record that finding `ident` is a defect the skipped optional review `review` (SKIP record `skip_record`) should have caught.
    Refuses (LedgerError, nothing written) when the finding is outside what the SKIP covered or is already attributed to another SKIP;
    the same link twice is recorded once. Returns {'link': {...}, 'duplicate': bool}."""
    from . import decisions
    text_field(reason, 'skip link reason', 2000)
    # ONE write transaction: the checks below (SKIP record, finding, 'already attributed') and the record commit together, so two
    # concurrent links of the same finding to different SKIPs cannot both pass validation on a stale read (round-5 atomicity rule).
    with ledger.transaction(write=True) as conn:
        root = resolve_root(ledger, name, task_id, conn)
        _require_capability(root)
        state = plans.anchor_events(ledger, conn, name)
        if state['task_id'] != root['id']:
            raise LedgerError(f'Plan {name} does not resolve to the root of this finding register.')
        approved = state['approved']
        if not approved:
            raise LedgerError('A skip link needs the root approved grant it rests on.')
        skip = _skip_records(conn, root['id']).get(skip_record)
        finding = next((f for f in _read(ledger, conn, root['id'])['findings'] if f['id'] == ident), None)
        problem = _link_problem(skip, finding, _opened_seq(conn, root['id'], ident), review)
        if problem:
            raise LedgerError(f'Finding {ident} is not linked to SKIP {skip_record}: {problem}.')
        for other in skip_view_links(conn, root['id']):
            if other['finding'] == ident and other['skip_record'] != skip_record:
                raise LedgerError(f'Finding {ident} is already attributed to SKIP {other["skip_record"]}; a defect is counted once.')
        link = {'link': 'missed_by_skip', 'finding': ident, 'skip_record': skip_record, 'review': review, 'root': root['id'],
                'revision': skip['revision'], 'contract_sha': skip['contract_sha'], 'artifact_sha': skip['artifact_sha']}
        key = 'skip-link-' + content_hash({'root': root['id'], 'finding': ident, 'skip': skip_record})
        before = conn.execute("SELECT 1 FROM events WHERE task_id=? AND kind='decision.recorded' AND json_extract(payload,'$.key')=?",
                              (root['id'], key)).fetchone()
        decisions.record(ledger, root['id'], subject={'component': SKIP_LINK, 'model': 'rules'},
                         authority={'grant_id': 'approved-contract:' + approved['sha'], 'revision': str(approved['revision'])},
                         evidence=[f'finding:{ident}', f'skip-record:{skip_record}', f'receipt:{finding["source"]["receipt"]}',
                                   f'artifact:{skip["artifact_sha"]}', f'contract:{skip["contract_sha"]}'],
                         basis=reason, scope=review, validity=link, by=by, key=key, conn=conn)
    return {'link': link, 'duplicate': before is not None}


def skip_view_links(conn, task_id):
    """The link decisions recorded on this root, as written (not yet re-validated)."""
    out = []
    for row in conn.execute("SELECT seq,payload FROM events WHERE task_id=? AND kind='decision.recorded' ORDER BY seq", (task_id,)):
        p = json.loads(row['payload'])
        v = p.get('validity')
        if (p.get('subject') or {}).get('component') == SKIP_LINK and isinstance(v, dict):
            out.append(dict(v, record=p.get('key'), seq=row['seq']))
    return out


def skip_view(ledger, name):
    """Read path of E29: the SKIP (HD-20) records of a root and the recorded skip links, each re-validated against the SKIP record and
    the finding register (a link whose SKIP record or finding does not hold is listed under 'invalid', never counted).
    Returns {'skip_records': {key: record}, 'links': [{finding, skip_record, review, root, revision, artifact_sha, record}], 'invalid': [...]}."""
    with ledger.transaction() as conn:
        state = plans.anchor_events(ledger, conn, name)
        task = state['task_id']
        skips = _skip_records(conn, task)
        recorded = skip_view_links(conn, task)
        register = _read(ledger, conn, task)['findings'] if namespaces.has_capability(state, 'finding-register') else None
        opened = {r['finding']: _opened_seq(conn, task, r['finding']) for r in recorded}
    links, invalid, seen = [], [], set()
    for r in recorded:
        if register is None:
            invalid.append({'record': r['record'], 'reason': 'this root has no finding register'})
            continue
        skip = skips.get(r.get('skip_record'))
        finding = next((f for f in register if f['id'] == r.get('finding')), None)
        problem = _link_problem(skip, finding, opened.get(r.get('finding')), r.get('review'))
        if problem is None and (r.get('root'), r.get('revision'), r.get('artifact_sha')) != (task, skip['revision'], skip['artifact_sha']):
            problem = 'the link names another root, revision or artifact than its SKIP record'
        if problem is None and r['finding'] in seen:
            problem = 'the finding is already counted under another link'
        if problem:
            invalid.append({'record': r['record'], 'reason': problem})
            continue
        seen.add(r['finding'])
        links.append({'finding': r['finding'], 'skip_record': r['skip_record'], 'review': r['review'], 'root': task,
                      'revision': skip['revision'], 'artifact_sha': skip['artifact_sha'], 'record': r['record']})
    return {'skip_records': skips, 'links': links, 'invalid': invalid}


def main(argv=None):
    parser = argparse.ArgumentParser(prog='onecrew findings')
    parser.add_argument('--project', type=Path, default=Path.cwd())
    parser.add_argument('--state-root', type=Path)
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('list'); p.add_argument('name'); p.add_argument('--open-only', action='store_true')
    p = sub.add_parser('review'); p.add_argument('name'); p.add_argument('node'); p.add_argument('--receipt', required=True)
    for action in ('resolve', 'reject'):
        p = sub.add_parser(action); p.add_argument('name'); p.add_argument('id'); p.add_argument('--receipt', required=True)
        p.add_argument('--reason', required=True); p.add_argument('--artifact-sha', required=True); p.add_argument('--generation', type=int, default=1)
    args = parser.parse_args(argv)
    try:
        ledger = Ledger(args.project, args.state_root)
        if args.command == 'list':
            out = list_findings(ledger, args.name, open_only=args.open_only)
        elif args.command == 'review':
            out = record_review(ledger, args.name, args.node, args.receipt)
        else:
            out = resolve(ledger, args.name, args.id, args.receipt, reason=args.reason, artifact_sha=args.artifact_sha,
                          generation=args.generation, reject=args.command == 'reject')
        print(json.dumps(out, ensure_ascii=False))
        return 2 if isinstance(out, dict) and out.get('refused') else 0
    except (LedgerError, OSError) as error:
        print(json.dumps({'error': str(error)}, ensure_ascii=False))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
