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


def _refresh(value, contract):
    """Changed criteria/configs invalidate old findings; no semantic inheritance."""
    for item in value['findings']:
        if item['status'] != 'open':
            continue
        try:
            signature = _signature(_milestone(contract, item['node']), item['criterion'])
        except LedgerError:
            signature = None
        if signature != (item['criterion_sha'], item['config_sha']):
            item.update(status='stale', stale_reason='criterion or reviewer configuration changed')


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
    entry = core.append_finding(value, {'plan': namespaces.parse(name)[0], 'revision': revision, 'plan_sha': sha, 'node': milestone['id'],
        'criterion': criterion, 'criterion_sha': criterion_sha, 'config_sha': config_sha,
        'candidate': artifact, 'artifact_sha': artifact, 'generation': generation, 'severity': severity,
        'scope': _scope(read, write), 'norm': key, 'chars': len(claim), 'head': core.safe(claim[:500]),
        'blob': blob, 'source': {'receipt': receipt, 'verdict_seq': verdict_seq}, 'review': value['review']})
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
            body, result, verdict_seq = _proof(ledger, conn, root, name, revision, sha, contract, target['node'], receipt, generation, artifact_sha, latest=True)
            observed_seq = max(target['source']['verdict_seq'], target.get('last_observed', {}).get('verdict_seq', 0))
            if verdict_seq <= observed_seq:
                raise LedgerError('Resolution evidence predates the finding; verify it again.')
            if result != 'pass':
                raise LedgerError('A finding closes only with passing verification evidence.')
            if body.get('kind') == 'reviewer-receipt':
                criterion = next((c for c in body.get('criteria') or [] if c.get('id') == target['criterion']), None)
                if criterion is None or criterion.get('verdict') != 'pass':
                    raise LedgerError('The evidence does not pass this finding criterion.')
            else:
                criterion = next((c for c in body.get('checks') or [] if c.get('id') == target['criterion']), None)
                if criterion is None or criterion.get('ok') is not True or criterion.get('problems'):
                    raise LedgerError('The evidence does not pass this finding check.')
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
