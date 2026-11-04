"""OBS-2 work history, projected from existing contracts, events and sealed receipts.

No constructor opens a writable ledger, no producer/helper that reconciles state is
called. A check is evidence only with its issuing event and exact historical
root/node/generation/artifact/definition binding. An output never inherits another
output's green colour merely because its node or content key happens to match.
"""
import json

from .. import contract_diff
from ..ledger import LedgerError, content_hash
from ..snapshots import Snapshots
from . import plan as plans, solution_link, step0, survey

VERSION = 1
STATUSES = ('pass', 'fail', 'skip', 'error', 'unknown')
DISPLAY_LIMIT = 1800
DIFF_LIMIT = 80


def _display(value):
    """Bound human-readable fields, never event ids / evidence identities."""
    if isinstance(value, str): return value[:DISPLAY_LIMIT] + ('…' if len(value) > DISPLAY_LIMIT else '')
    if isinstance(value, list): return [_display(v) for v in value[:40]]
    if isinstance(value, dict): return {k: _display(v) for k, v in list(value.items())[:60]}
    return value


def _source(seq, kind, at, root):
    return {'seq': seq, 'kind': kind, 'at': at, 'task': root}


def _status(value):
    return value if value in STATUSES else 'unknown'


def _counts(rows):
    return {s: sum(r.get('status') == s for r in rows) for s in STATUSES}


class _Blobs:
    def __init__(self, reader, limitations):
        self.store, self.cache, self.limitations = Snapshots(reader.state_root), {}, limitations

    def get(self, key):
        if not isinstance(key, str):
            return None
        if key not in self.cache:
            try:
                value = json.loads(self.store.read_blob(key))
                if not isinstance(value, dict): raise ValueError('not an object')
                self.cache[key] = value
            except (LedgerError, OSError, ValueError, TypeError):
                self.cache[key] = None
                self.limitations.append('Không đọc được receipt/definition/register: ' + str(key))
        return self.cache[key]

    def exists(self, key):
        try: self.store.read_blob(key); return True
        except (LedgerError, OSError, ValueError, TypeError): return False


def _solution(reader, conn, state, engine, limitations):
    approved = state.get('approved') or {}
    effective = (engine or {}).get('definition_contract_revision') or approved.get('revision')
    display_revision = effective or state['latest']
    contract, sha = plans.load(reader, state, display_revision)
    try: runnable = plans.resolve(reader, state)
    except (LedgerError, OSError, ValueError, KeyError): runnable = None
    view = {'latest_revision': state['latest'], 'approved_revision': approved.get('revision'),
            'effective_revision': effective, 'display_revision': display_revision,
            'runnable_revision': runnable.get('revision') if runnable else None,
            'frozen': runnable.get('frozen') if runnable else None, 'approval': _display(approved) or None,
            'contract': {'revision': display_revision, 'sha': sha, 'title': _display(contract.get('title')),
                         'goal': _display(contract['understanding']['restated_goal']), 'outputs': _display(contract['output']),
                         'acceptance': _display(contract.get('items')), 'scope': _display(contract.get('scope')),
                         'preserve': _display(contract.get('non_goals', []))},
            'source_solution': None, 'card': None, 'authority_source': 'root contract; SOL grants no execution authority'}
    ref = contract.get('solution_ref')
    if ref:
        try:
            source = solution_link.source(reader, conn, ref['id'], ref['revision'])
            payload = source['payload']
            view['source_solution'] = dict(ref, status='available',
                payload=_display({k: payload[k] for k in ('brief', 'detail', 'acceptance', 'non_goals', 'assumptions', 'questions',
                                                          'before', 'after', 'preferred', 'why', 'preserve') if k in payload}))
        except (LedgerError, OSError, ValueError, KeyError, TypeError):
            # Never echo a foreign SOL's payload or other-project metadata.
            view['source_solution'] = dict(ref, status='unavailable', payload=None)
            limitations.append('SOL ghim không có, sai revision hoặc không thuộc project; chỉ hiện hợp đồng root.')
    try:
        check = step0.latest_proposal_check(conn, state['task_id'], display_revision)
        history = step0.proposal_history(reader, state['selector'], check.get('requirement_sha') if check else None, conn)
        view['card'] = _display(step0.card(contract, check, survey.states(conn, state['task_id']),
                                         step0._baseline(conn, state['task_id']), history=history))
    except (LedgerError, OSError, ValueError, KeyError, TypeError):
        limitations.append('Không có card bước 0 đọc được; mục tiêu và đầu ra lấy từ hợp đồng.')
    return view, contract


def _changes(reader, state, events, blobs, root):
    rows, previous_definition = [], None
    for seq, kind, p, at in events:
        if kind not in ('plan.amended', 'plan.revised', 'node.resumed'): continue
        row = {'id': 'event:' + str(seq), 'kind': {'plan.amended': 'contract', 'plan.revised': 'internal', 'node.resumed': 'retry'}[kind],
               'source': _source(seq, kind, at, root), 'at': at, 'revision': p.get('revision'),
               'internal_revision': p.get('internal_revision'), 'node': p.get('node'), 'generation': p.get('generation'),
               'reason': _display(p.get('reason')), 'author': p.get('author'), 'evidence': _display(p.get('evidence') or []),
               'decision': _display(p.get('decision')), 'cost': _display(p.get('cost')), 'diff': [], 'diff_total': 0,
               'affected_nodes': (p.get('cost') or {}).get('counted', []), 'reused_nodes': (p.get('cost') or {}).get('reused', [])}
        try:
            if kind == 'plan.amended':
                old = plans.load(reader, state, p.get('from_revision', p['revision'] - 1))[0]
                new = plans.load(reader, state, p['revision'])[0]
                differences = contract_diff.changes(old, new)
                row['approved'] = any(k == 'plan.approved' and b.get('revision') == p['revision'] and b.get('sha') == p.get('sha')
                                      for _, k, b, _ in events)
                row['sha'], row['from_revision'] = p.get('sha'), p.get('from_revision')
            elif kind == 'plan.revised':
                new = blobs.get(p.get('definition'))
                differences = contract_diff.changes(previous_definition or {}, new or {})
                previous_definition = new
            else: differences = []
            row['diff'], row['diff_total'] = [_display(d) for d in differences[:DIFF_LIMIT]], len(differences)
        except (LedgerError, OSError, ValueError, KeyError, TypeError): row['diff_error'] = 'Không đọc được nguồn diff.'
        rows.append(row)
    return rows


def _actor(role, node, attempt, source, data=None):
    data = data if isinstance(data, dict) else {}
    return {'role': role, 'node': node, 'attempt': attempt, 'provider': data.get('provider'), 'model': data.get('model'),
            'actor': data.get('actor') or data.get('by'), 'source': source,
            'status': 'recorded' if any(data.get(k) for k in ('actor', 'by', 'provider', 'model')) else 'unknown'}


def _checks(reader, state, events, root, blobs, engine, limitations):
    """Published node checks and recorded milestone verdicts, never prose parsing."""
    definitions, produced, starts, runs, by_identity = {}, {}, {}, [], {}
    current = (engine or {}).get('nodes', {})
    issued = {(p.get('revision'), p.get('milestone'), p.get('receipt')) for _, k, p, _ in events if k == 'verdict.receipt_issued'}
    for seq, kind, p, at in events:
        nid, gen = p.get('node'), p.get('generation')
        if kind == 'plan.revised':
            body = blobs.get(p.get('definition'))
            if body and content_hash(body) == p.get('definition_sha'): definitions[p['internal_revision']] = body
        if kind == 'node.started': starts[nid, gen] = p.get('attempt')
        if kind == 'node.produced': produced[nid, gen] = p.get('artifact')
        if kind not in ('node.verification', 'verdict.recorded'): continue
        source = _source(seq, kind, at, root)
        identity = (kind, nid or p.get('milestone'), gen, p.get('revision'), p.get('receipt'))
        if identity in by_identity:
            by_identity[identity]['sources'].append(source)
            continue
        body = blobs.get(p.get('receipt'))
        observed = (body or {}).get('observed') or {}
        if not isinstance(observed, dict): observed = {}
        artifact = (body or {}).get('artifact') if kind == 'node.verification' else p.get('artifact_sha')
        definition = definitions.get(p.get('internal_revision')) or {}
        item = next((n for n in definition.get('nodes', []) if n.get('id') == nid), {})
        if kind == 'node.verification':
            authentic = bool(body and item and all(body.get(k) == v for k, v in
                {'kind': 'node-verifier-receipt', 'root': root, 'node': nid, 'generation': gen,
                 'internal_revision': p.get('internal_revision'), 'result': p.get('result'),
                 'artifact': produced.get((nid, gen)), 'checks_sha': content_hash(item.get('checks', []))}.items())
                and artifact is not None and observed.get('artifact') == artifact and not body.get('evidence_errors'))
            raw_checks = observed.get('checks') or []
            if not isinstance(raw_checks, list): raw_checks = []
            expected = {c['id'] for c in item.get('checks', [])}
            actual_ids = [c.get('id') for c in raw_checks if isinstance(c, dict) and isinstance(c.get('id'), str)]
            authentic = authentic and len(raw_checks) == len(expected) and set(actual_ids) == expected and len(actual_ids) == len(raw_checks)
        else:
            # verdict.record validates this binding when it writes. Legacy owner
            # receipts can be opaque; expose the event verdict without inventing cases.
            authentic = bool(body and (p.get('revision'), p.get('milestone'), p.get('receipt')) in issued
                and body.get('plan') == p.get('plan') and body.get('revision') == p.get('revision')
                and body.get('milestone') == p.get('milestone') and body.get('artifact_sha') == artifact
                and body.get('plan_sha') == state['revisions'].get(p.get('revision'), {}).get('sha'))
            raw_checks = ((body or {}).get('criteria') or (body or {}).get('checks') or [])
            if not isinstance(raw_checks, list): raw_checks = []
            if not raw_checks: raw_checks = [{'id': p.get('milestone'), 'result': p.get('result')}]
        check_rows, cases = [], []
        for number, check in enumerate(raw_checks):
            if not isinstance(check, dict): continue
            evidence = check.get('evidence')
            proven = authentic and (kind != 'node.verification' or blobs.exists(evidence))
            status = _status(check.get('result') or check.get('status') or check.get('verdict')) if proven else 'unknown'
            cid = check.get('id') or check.get('criterion') or 'unknown:' + str(number)
            if not isinstance(cid, str):
                cid = 'unknown:' + str(number)
                status, proven = 'unknown', False
            check_rows.append({'id': cid, 'status': status, 'evidence': evidence, 'authentic': proven,
                               'label': _display(check.get('spec') or check.get('claim') or cid)})
            # Only explicit identities in a structured receipt count as cases.
            for case in check.get('testcases', []) if isinstance(check.get('testcases'), list) else []:
                if (isinstance(case, dict) and isinstance(case.get('id'), str) and case['id']
                        and (case.get('suite') is None or isinstance(case['suite'], str))):
                    cases.append({'id': case['id'], 'suite': case.get('suite') or cid,
                                  'status': _status(case.get('status') or case.get('result')) if proven else 'unknown',
                                  'check': cid})
                else: limitations.append('Bỏ testcase metadata sai kiểu identity/suite; không suy tổng từ metadata lỗi.')
        for case in observed.get('testcases', []) if isinstance(observed.get('testcases'), list) else []:
            if (isinstance(case, dict) and isinstance(case.get('id'), str) and case['id']
                    and (case.get('suite') is None or isinstance(case['suite'], str))):
                cases.append({'id': case['id'], 'suite': case.get('suite'),
                              'status': _status(case.get('status') or case.get('result')) if authentic else 'unknown', 'check': None})
            else: limitations.append('Bỏ testcase metadata sai kiểu identity/suite; không suy tổng từ metadata lỗi.')
        all_proven = authentic and bool(check_rows) and all(c['authentic'] for c in check_rows)
        if p.get('result') == 'pass' and any(c['status'] != 'pass' for c in check_rows): all_proven = False
        if p.get('result') == 'fail' and not any(c['status'] == 'fail' for c in check_rows): all_proven = False
        record = current.get(nid) or {}
        stale = (gen != record.get('generation') or artifact != record.get('artifact') or
                 p.get('internal_revision') not in record.get('valid_internal_revisions', [])) if nid else (
                     p.get('revision') != (state.get('approved') or {}).get('revision') or
                     p.get('revision') != state['latest'])
        run = {'id': 'check:' + str(seq), 'receipt': p.get('receipt'), 'node': nid or p.get('milestone'), 'generation': gen,
               'revision': p.get('revision'), 'internal_revision': p.get('internal_revision'),
               'attempt': p.get('attempt'), 'producer_attempt': starts.get((nid, gen)), 'artifact': artifact, 'stale': stale,
               'authentic': bool(all_proven), 'status': _status(p.get('result')) if all_proven else 'unknown',
               'checks': check_rows, 'testcases': cases, 'checks_sha': (body or {}).get('checks_sha'), 'source': source, 'sources': [source],
               'actor': _actor('reviewer', nid or p.get('milestone'), p.get('attempt'), source,
                               observed.get('reviewer') or (body if kind == 'verdict.recorded' else None))}
        run['actors'] = []
        for check in check_rows:
            proof = blobs.get(check.get('evidence')) if isinstance(check.get('evidence'), str) and check['authentic'] else None
            if (proof and proof.get('kind') == 'candidate-reviewer-check' and proof.get('node') == nid
                    and proof.get('snapshot') == artifact and proof.get('milestone') == check['id']):
                reviewer = blobs.get(proof.get('reviewer_receipt'))
                if (reviewer and reviewer.get('kind') == 'reviewer-receipt' and isinstance(reviewer.get('calls'), (int, float)) and reviewer['calls'] > 0
                        and reviewer.get('artifact_sha') == proof.get('tree') and reviewer.get('milestone') == check['id']
                        and reviewer.get('revision') == p.get('revision')):
                    run['actors'].append(_actor('reviewer', nid, run['attempt'],
                        dict(source, receipt=proof.get('reviewer_receipt'), check=check['id']), reviewer))
        if not all_proven: limitations.append('Kiểm chưa đủ binding/evidence hợp lệ: ' + str(p.get('receipt')))
        runs.append(run); by_identity[identity] = run
    checks = [c for r in runs for c in r['checks']]
    cases = [c for r in runs for c in r['testcases']]
    unique_cases = {(r['node'], c.get('suite'), c['id']) for r in runs for c in r['testcases']}
    return {'runs': runs, 'summary': {'runs': len(runs), 'checks': _counts(checks), 'check_executions': len(checks),
            'unique_checks': len({(r['node'], c['id']) for r in runs for c in r['checks']}),
            'testcases': dict(_counts(cases), executions=len(cases), unique=len(unique_cases)) if cases else None},
            'coverage': 'Chỉ receipt có sự kiện phát hành và binding; số check không phải số testcase.'}


def _outputs(state, events, root, engine, evidence_keys, checks, blobs):
    rows, starts, seen = [], {}, {}
    current = (engine or {}).get('nodes', {})
    definitions = ((engine or {}).get('definition') or {}).get('nodes', [])
    titles = {n['id']: '; '.join(n.get('output') or [n.get('goal') or n['id']]) for n in definitions}
    for seq, kind, p, at in events:
        nid, gen = p.get('node'), p.get('generation')
        if kind == 'node.started': starts[nid, gen] = p.get('attempt')
        if kind not in ('node.produced', 'node.resumed', 'verdict.recorded'): continue
        inherited = kind == 'node.resumed'
        if inherited and type(gen) is int: gen += 1    # node.resumed names the generation it replaces
        artifact = p.get('resume_artifact') if inherited else p.get('artifact') or p.get('artifact_sha')
        if not artifact: continue
        node_id = nid or p.get('milestone')
        attempt = p.get('attempt') or starts.get((nid, gen))
        source = _source(seq, kind, at, root)
        identity = (node_id, gen, attempt, artifact, inherited, p.get('revision'))
        if identity in seen:
            seen[identity]['sources'].append(source); continue
        record = current.get(nid) or {}
        current_artifact = record.get('resume_artifact') if inherited else record.get('artifact')
        stale = bool(nid and (gen != record.get('generation') or artifact != current_artifact or
                     p.get('internal_revision') not in record.get('valid_internal_revisions', []))) if nid else (
                     p.get('revision') != (state.get('approved') or {}).get('revision') or p.get('revision') != state['latest'])
        matching = [r for r in checks['runs'] if r['authentic'] and r['node'] == node_id and r['generation'] == gen
                 and r['artifact'] == artifact and r['revision'] == p.get('revision') and r['source']['seq'] >= seq
                 ]
        proof = matching[-1:] if matching and matching[-1]['status'] == 'pass' else []
        accepted = any(k == 'node.accepted' and b.get('node') == nid and b.get('generation') == gen
                       and b.get('internal_revision') == p.get('internal_revision') and s >= seq for s, k, b, _ in events) if nid else False
        row = {'id': 'output:' + str(seq), 'node': node_id, 'title': _display(titles.get(nid) or node_id or 'Đầu ra'),
               'generation': gen, 'attempt': attempt, 'revision': p.get('revision'), 'internal_revision': p.get('internal_revision'),
               'artifact': artifact, 'receipt': p.get('receipt'), 'stored': artifact in evidence_keys,
               'openable': artifact in evidence_keys, 'inherited': inherited or bool(nid and not stale and
                    p.get('internal_revision') != (engine or {}).get('internal_revision')),
               'stale': stale, 'level': 'accepted' if accepted and proof else 'verified' if proof else 'produced',
               'verification': [r['id'] for r in proof], 'source': source, 'sources': [source]}
        if inherited:
            row['from_generation'], row['from_attempt'] = p.get('generation'), p.get('continues_attempt')
        rows.append(row); seen[identity] = row
    return rows


def _findings(reader, conn, state, contract, engine, limitations):
    from . import findings
    try:
        value = findings._read(reader, conn, state['task_id'])
        recorded = {f['id']: f.get('status') for f in value.get('findings', [])}
        findings._refresh(value, contract, ((engine or {}).get('definition') or {}).get('nodes'))
        return [_display(dict(f, recorded_status=recorded[f['id']], state=f.get('status'), text=f.get('head'),
                         state_basis='register' if recorded[f['id']] == f.get('status') else 'current definition',
                         category=f.get('category'), duplicate_of=f.get('duplicate_of'), recurrence_of=f.get('recurrence_of')))
                for f in value.get('findings', [])]
    except (LedgerError, OSError, ValueError, KeyError, TypeError):
        limitations.append('Không đọc được finding register; không suy số bug từ check fail.')
        return []


def _repairs(events, root, blobs, checks, engine):
    from . import repair_tasks
    rows, seen, lineage = [], set(), {}
    for seq, kind, p, at in events:
        if kind != 'plan.revised': continue
        definition = blobs.get(p.get('definition')) or {}
        for node in definition.get('nodes', []):
            for ref in node.get('input', []):
                if not isinstance(ref, str) or not ref.startswith(repair_tasks.PREFIX): continue
                key = ref[len(repair_tasks.PREFIX):]
                if key in seen: continue
                seen.add(key); body = blobs.get(key)
                if not body or body.get('kind') != repair_tasks.KIND or body.get('root') != root: continue
                source_runs = [r for r in checks['runs'] if r['receipt'] == body.get('source_receipt') and r['authentic']
                               and r['status'] == 'fail' and r['source']['seq'] == body.get('source_event')
                               and set(body.get('failed_checks') or []) <= {c['id'] for c in r['checks'] if c['status'] == 'fail'}]
                generations = body.get('generations') or {}
                later = [r for r in checks['runs'] if source_runs and r['source']['seq'] > seq and r['authentic']
                         and r['generation'] == generations.get(r['node'])
                         and r['checks_sha'] == (body.get('checks_sha') or {}).get(r['node'])
                         and r['node'] in body.get('affected_nodes', [])]
                latest = {}
                for r in later: latest[r['node']] = r
                verified_nodes = [nid for nid, r in latest.items() if r['status'] == 'pass']
                affected = body.get('affected_nodes') or []
                status = ('verified' if affected and set(verified_nodes) == set(affected) else 'partial' if verified_nodes else 'unverified')
                repair = {'id': key, 'node': body.get('target'), 'source_receipt': body.get('source_receipt'),
                    'source_event': body.get('source_event'), 'failed_checks': body.get('failed_checks') or [],
                    'affected_nodes': affected, 'generations': generations, 'reason': _display(body.get('reason')),
                    'evidence': _display(body.get('evidence')), 'authentic_source': bool(source_runs),
                    'status': status, 'verified_nodes': verified_nodes, 'verification': [r['id'] for r in later],
                    'applicable': all(((engine or {}).get('nodes', {}).get(nid) or {}).get('generation') == generations.get(nid) for nid in affected),
                    'rebinds_order_only': body.get('rebinds_order_only', False), 'rebound_from': body.get('rebound_from'),
                    'carried_from': body.get('carried_from') or [], 'source_receipts': body.get('source_receipts') or [],
                    'source': _source(seq, kind, at, root), 'rebindings': []}
                parents = ([body['rebound_from']] if body.get('rebound_from') else []) + (body.get('carried_from') or [])
                parent = next((lineage[ref] for ref in parents if ref in lineage), None)
                if body.get('rebinds_order_only') and parent:
                    parent['rebindings'].append(repair); lineage[key] = parent
                else:
                    rows.append(repair); lineage[key] = repair
    return rows


def project(reader, conn, row, state, events, engine, evidence_keys):
    """Detail-only addition; caller already holds report._Reader's RO transaction.

    Events are the complete root history, independent of the visible timeline.
    Evidence links are limited to the pre-existing tracking evidence door.
    """
    limitations = ['Nội dung hiển thị tối đa 1800 ký tự/trường, 40 mục/danh sách, 80 dòng diff; lịch sử sự kiện không cắt.',
                   'Không có testcase có định danh trong receipt thì tổng testcase chưa xác định; finding không đồng nghĩa bug.',
                   'Actor thiếu trong receipt là chưa xác định; pin được giao không chứng minh đã thực hiện.']
    blobs = _Blobs(reader, limitations)
    try: solution, contract = _solution(reader, conn, state, engine, limitations)
    except (LedgerError, OSError, ValueError, KeyError, TypeError):
        solution, contract = {'latest_revision': state['latest'], 'approved_revision': (state.get('approved') or {}).get('revision'),
            'effective_revision': None, 'contract': None, 'source_solution': None, 'card': None}, None
        limitations.append('Không đọc được hợp đồng có hash hợp lệ; không suy quyền hay nội dung solution.')
    checks = _checks(reader, state, events, row['id'], blobs, engine, limitations)
    outputs = _outputs(state, events, row['id'], engine, set(evidence_keys), checks, blobs)
    definitions = ((engine or {}).get('definition') or {}).get('nodes', [])
    actors = [_actor('assigned', n['id'], None, {'kind': 'plan.revised', 'internal_revision': (engine or {}).get('internal_revision')},
                     n.get('executor')) for n in definitions]
    for output in outputs:
        body = blobs.get(output.get('receipt')) if output.get('receipt') else None
        # Opaque executor receipts intentionally leave identity unknown.
        bound = bool(body and body.get('node') == output['node'] and body.get('artifact') == output['artifact']
                     and body.get('attempt') == output['attempt'])
        actors.append(_actor('executed', output['node'], output['attempt'], output['source'],
                              (body.get('producer') or body) if bound else None))
    actors += [a for r in checks['runs'] for a in (r['actors'] or [r['actor']])]
    return {'schema_version': VERSION, 'solution': solution,
            'nodes': {n['id']: {'title': _display(n.get('goal') or n['id']), 'outputs': _display(n.get('output') or []),
                               'integration': n.get('integration', False)} for n in definitions},
            'changes': _changes(reader, state, events, blobs, row['id']), 'outputs': outputs, 'checks': checks,
            'findings': _findings(reader, conn, state, contract, engine, limitations) if contract else [],
            'repairs': _repairs(events, row['id'], blobs, checks, engine), 'actors': actors,
            'limitations': list(dict.fromkeys(limitations)), 'history_complete': True, 'read_only': True}
