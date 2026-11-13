"""OBS-2 work history, projected from existing contracts, events and sealed receipts.

No constructor opens a writable ledger, no producer/helper that reconciles state is
called. A check is evidence only with its issuing event and exact historical
root/node/generation/artifact/definition binding. An output never inherits another
output's green colour merely because its node or content key happens to match.
"""
import json
import re

from .. import contract_diff
from ..ledger import LedgerError, content_hash
from ..snapshots import Snapshots
from . import namespaces, plan as plans, solution_link, step0, survey

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


def command_outputs(body):
    """dev11: the stdout/stderr blobs a sealed command receipt names, with its exit code; None for any other receipt. Read-only: the keys are
    only offered where the receipt itself belongs to the root (tracking.evidence opens them one hop through such a receipt)."""
    if not isinstance(body, dict) or body.get('kind') != 'command-receipt': return None
    keys = {s: body.get(s) for s in ('stdout', 'stderr')}
    if not all(isinstance(k, str) and re.fullmatch(r'[0-9a-f]{64}', k) for k in keys.values()): return None
    return dict(keys, exit_code=body.get('exit_code'), timed_out=body.get('timed_out'), stdout_bytes=body.get('stdout_bytes'),
                stderr_bytes=body.get('stderr_bytes'), truncated=body.get('output_truncated'))


class _Blobs:
    def __init__(self, reader, limitations):
        self.store, self.cache, self.limitations = Snapshots(reader.state_root), {}, limitations

    def get(self, key, optional_json=False):
        if not isinstance(key, str):
            return None
        if key not in self.cache:
            try:
                raw = self.store.read_blob(key)
                try:
                    value = json.loads(raw)
                except (ValueError, TypeError):
                    if optional_json: return None
                    raise
                if optional_json and not isinstance(value, dict): return None
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
                if previous_definition is None and p.get('internal_revision') == 1: row['kind'] = 'initial'
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


def _milestone_artifacts(events):
    """Latest recorded artifact per milestone/revision; absence is unknown, never inherited certification."""
    latest, seen = {}, set()
    for _, kind, p, _ in events:
        if kind != 'verdict.recorded': continue
        key = (p.get('revision'), p.get('milestone'))
        identity = (*key, p.get('generation'), p.get('artifact_sha'), p.get('receipt'))
        if identity in seen: continue  # Replayed old evidence does not supersede a later candidate.
        seen.add(identity); latest[key] = p.get('artifact_sha')
    return latest


def _checks(reader, state, events, root, blobs, engine, limitations):
    """Published node checks and recorded milestone verdicts, never prose parsing."""
    definitions, produced, starts, runs, by_identity = {}, {}, {}, [], {}
    current = (engine or {}).get('nodes', {})
    milestone_artifacts = _milestone_artifacts(events)
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
                     p.get('revision') != state['latest'] or
                     artifact is None or artifact != milestone_artifacts.get((p.get('revision'), p.get('milestone'))))
        reviewer_data = None
        if all_proven and kind == 'verdict.recorded':
            calls = (body or {}).get('calls')
            if (body or {}).get('kind') != 'reviewer-receipt' or (isinstance(calls, (int, float)) and calls > 0):
                reviewer_data = body
        elif all_proven and kind == 'node.verification':
            recorded = observed.get('reviewer')
            if isinstance(recorded, dict) and isinstance(recorded.get('calls'), (int, float)) and recorded['calls'] > 0:
                reviewer_data = recorded
        run = {'id': 'check:' + str(seq), 'receipt': p.get('receipt'), 'node': nid or p.get('milestone'), 'generation': gen,
               'revision': p.get('revision'), 'internal_revision': p.get('internal_revision'),
               'attempt': p.get('attempt'), 'producer_attempt': starts.get((nid, gen)), 'artifact': artifact, 'stale': stale,
               'authentic': bool(all_proven), 'status': _status(p.get('result')) if all_proven else 'unknown',
               'checks': check_rows, 'testcases': cases, 'checks_sha': (body or {}).get('checks_sha'), 'source': source, 'sources': [source],
               'outputs': command_outputs(body),
               'actor': _actor('reviewer', nid or p.get('milestone'), p.get('attempt'), source,
                               reviewer_data)}
        run['actors'] = []
        for check in check_rows:
            proof = blobs.get(check.get('evidence'), optional_json=True) if isinstance(check.get('evidence'), str) and check['authentic'] else None
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


def _outputs(state, events, root, engine, evidence_keys, checks, blobs, recheck=frozenset()):
    rows, starts, seen = [], {}, {}
    current = (engine or {}).get('nodes', {})
    definitions = ((engine or {}).get('definition') or {}).get('nodes', [])
    milestone_artifacts = _milestone_artifacts(events)
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
                     p.get('revision') != (state.get('approved') or {}).get('revision') or p.get('revision') != state['latest'] or
                     artifact != milestone_artifacts.get((p.get('revision'), p.get('milestone'))))
        matching = [r for r in checks['runs'] if r['node'] == node_id and r['generation'] == gen
                 and r['artifact'] == artifact and r['revision'] == p.get('revision') and r['source']['seq'] >= seq
                 ]
        proof = matching[-1:] if matching and matching[-1]['authentic'] and matching[-1]['status'] == 'pass' else []
        failed = bool(matching and matching[-1]['authentic'] and matching[-1]['status'] == 'fail')   # UX 13/11 (B2): checked and not passed, not "only produced"
        if not nid and node_id in recheck: stale = True                        # UX 13/11 (B2): the milestone view says this pass needs a recheck
        accepted = any(k == 'node.accepted' and b.get('node') == nid and b.get('generation') == gen
                       and b.get('internal_revision') == p.get('internal_revision') and s >= seq for s, k, b, _ in events) if nid else False
        row = {'id': 'output:' + str(seq), 'node': node_id, 'title': _display(titles.get(nid) or node_id or 'Đầu ra'),
               'generation': gen, 'attempt': attempt, 'revision': p.get('revision'), 'internal_revision': p.get('internal_revision'),
               'artifact': artifact, 'receipt': p.get('receipt'), 'stored': artifact in evidence_keys,
               'openable': artifact in evidence_keys, 'inherited': inherited or bool(nid and not stale and
                    p.get('internal_revision') != (engine or {}).get('internal_revision')),
               'stale': stale, 'level': 'accepted' if accepted and proof else 'verified' if proof else 'failed' if failed else 'produced',
               **({'stale_reason': 'cần kiểm lại'} if not nid and node_id in recheck else {}),
               'verification': [r['id'] for r in proof], 'source': source, 'sources': [source]}
        if inherited:
            row['from_generation'], row['from_attempt'] = p.get('generation'), p.get('continues_attempt')
        rows.append(row); seen[identity] = row
    return rows


def _finding_text(finding):
    head = finding.get('head') or ''
    try:
        structured = isinstance(json.loads(head), (dict, list))
    except (ValueError, TypeError):
        # The register stores only a 500-character preview. A truncated JSON
        # object/list is still structured evidence, not a readable diagnosis.
        structured = (finding.get('chars') or 0) > len(head) and head.lstrip().startswith(('{', '['))
    if head and not structured: return head
    criterion = (finding.get('check') or {}).get('spec') or finding.get('criterion') or finding.get('id')
    return 'Không đạt: ' + str(criterion or 'chưa có mô tả tiêu chí')


def _findings(reader, conn, state, contract, engine, limitations):
    from . import findings
    try:
        value = findings._read(reader, conn, state['task_id'])
        recorded = {f['id']: f.get('status') for f in value.get('findings', [])}
        findings._refresh(value, contract, ((engine or {}).get('definition') or {}).get('nodes'))
        return [_display(dict(f, recorded_status=recorded[f['id']], state=f.get('status'), text=_finding_text(f),
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


def project(reader, conn, row, state, events, engine, evidence_keys, recheck=frozenset()):
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
    outputs = _outputs(state, events, row['id'], engine, set(evidence_keys), checks, blobs, recheck=recheck)
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
            'finding_register': namespaces.has_capability(state, 'finding-register'),
            'repairs': _repairs(events, row['id'], blobs, checks, engine), 'actors': actors,
            'limitations': list(dict.fromkeys(limitations)), 'history_complete': True, 'read_only': True}


# ---- 2.5-A cycle 2: review trace (data only, for OBS-2B) ------------------------------------------------------------------------------

_RUN_EVENTS = ('review.run_started', 'review.run_result', 'review.run_finished', 'review.run_held',
               'verdict.run_started', 'verdict.receipt_issued', 'verdict.run_abandoned', 'verdict.run_reconciled', 'verdict.run_held', 'verdict.run_released')


def _unknown(reason):
    return {'link': 'unknown', 'reason': reason}


def review_trace(ledger, selector):
    """Read-only chain request -> run (door, actor, status) -> receipt -> finding -> repair assignment -> repair output -> recheck.

    Every value is copied from an event or a sealed receipt blob; a link no event or receipt establishes is {'link': 'unknown', 'reason'}
    and is never inferred (no decision logic here: no pass/fail verdict is computed, a request's applicability is not judged). A run's
    `status` is the latest recorded lifecycle event, not a liveness check. `door` is the recorded `door` field, or the writer of that
    event kind (`door_source` says which)."""
    from . import findings, namespaces, repair_tasks, review_request
    limitations = ['Chain links come only from events and sealed receipts; "unknown" means no record establishes the link.',
                   'A run status is its latest recorded lifecycle event; liveness and applicability are not judged here.']
    with ledger.transaction() as conn:
        state = plans.anchor_events(ledger, conn, selector)
        task = state['task_id']
        events = [(r['seq'], r['kind'], json.loads(r['payload']), r['created_at']) for r in
                  conn.execute('SELECT seq, kind, payload, created_at FROM events WHERE task_id=? ORDER BY seq', (task,))]
        register = (findings._read(ledger, conn, task) if namespaces.has_capability(state, 'finding-register') else {'findings': []})
    blobs = _Blobs(ledger, limitations)

    runs, requests, receipts = {}, {}, {}
    for seq, kind, p, at in events:
        if kind in _RUN_EVENTS and isinstance(p.get('run_id'), str):
            run = runs.setdefault(p['run_id'], {'run_id': p['run_id'], 'request_id': p.get('request_id') or (p.get('request') or {}).get('id'),
                                                'status': 'unknown', 'receipt': None, 'applicable': None, 'sources': []})
            run['sources'].append(_source(seq, kind, at, task))
            if kind in ('review.run_started', 'verdict.run_started'):
                request = p.get('request') if isinstance(p.get('request'), dict) else {}
                subject = p.get('subject') if isinstance(p.get('subject'), dict) else {}
                actor = p.get('actor') or p.get('by')
                node = p.get('node') or subject.get('node')
                milestone = p.get('milestone') or subject.get('milestone')
                candidate = p.get('artifact') or p.get('candidate') or subject.get('candidate') or subject.get('artifact')
                review_id = p.get('review_id') or p.get('check') or milestone
                door = p.get('door') or ('verdict.run' if kind == 'verdict.run_started' else 'review_dispatch.optional')
                # who ran it: the execution identity a door derived from what it runs; a declaration, not proof of independence
                execution = (request.get('identity') or {}).get('execution')
                executor = ({k: execution.get(k) for k in ('method', 'implementation', 'provider', 'model')}
                            if isinstance(execution, dict) else _unknown('the request names no execution identity'))
                run.update(node=node, milestone=milestone, review_id=review_id, artifact=candidate, check=p.get('check'), parent=p.get('parent'),
                           request_id=request.get('id') or run['request_id'],
                           door=door, door_source='recorded' if p.get('door') else 'event-kind', executor=executor,
                           actor=actor or None, actor_status='recorded' if actor else 'unknown',
                           process={'host': p.get('host'), 'pid': p.get('pid')}, status='started')
                if request:
                    requests.setdefault(request['id'], {'id': request['id'], 'kind': review_request.kind_of(request) or 'unknown',
                        'node': node, 'milestone': milestone, 'review_id': review_id, 'candidate': candidate,
                        'execution_complete': request.get('execution_complete'), 'missing': request.get('missing') or [], 'runs': [],
                        'source': _source(seq, kind, at, task)})
            elif kind == 'verdict.receipt_issued':
                run['status'] = 'result_issued'; run['receipt'] = p.get('receipt')
                receipts.setdefault(p.get('receipt'), {'origin': 'verdict.run', 'run_id': p['run_id'], 'request_id': run['request_id'],
                                                       'source': _source(seq, kind, at, task)})
            elif kind == 'review.run_result':
                run['status'] = 'result_issued'; run['receipt'] = p.get('receipt')
                receipts.setdefault(p.get('receipt'), {'origin': 'review.run', 'run_id': p['run_id'], 'request_id': p.get('request_id'),
                                                       'source': _source(seq, kind, at, task)})
            elif kind == 'review.run_finished':
                # `outcome` (2.5-B): published | stale | observed | not_dispatched | released; cycle-1 rows carry only `applicable`
                run['status'] = p.get('outcome') or ('observed' if p.get('applicable') else 'stale_observation')
                run['applicable'] = p.get('applicable'); run['receipt'] = p.get('receipt') or run['receipt']
            elif kind in ('review.run_held', 'verdict.run_held'):
                run['status'] = 'held'; run['hold_reason'] = _display(p.get('reason'))
            elif kind == 'verdict.run_abandoned':
                if run['status'] != 'held': run['status'] = 'abandoned'
            elif kind == 'verdict.run_reconciled':
                if p.get('determination') == 'unknown':          # the record itself is the hold (verdict._hold_of)
                    run['status'] = 'held'; run['hold_reason'] = _display(p.get('detail'))
                else:
                    run['status'] = p.get('determination')
            elif kind == 'verdict.run_released':
                run['status'] = 'released'
    for run in runs.values():
        run.setdefault('door', 'unknown'); run.setdefault('actor_status', 'unknown'); run.setdefault('node', None)
        if run['request_id'] in requests: requests[run['request_id']]['runs'].append(run['run_id'])
    for seq, kind, p, at in events:
        if kind in ('node.verification', 'verdict.recorded') and isinstance(p.get('receipt'), str):
            body = blobs.get(p['receipt'], optional_json=True) or {}
            issued = receipts.get(p['receipt']) or {}
            run_id = p.get('run_id') or issued.get('run_id')
            # A door's published receipt: the run names its request; the record event says what it was published as.
            receipts[p['receipt']] = {'origin': kind, 'run_id': run_id, 'node': p.get('node') or p.get('milestone'),
                'result': p.get('result'), 'generation': p.get('generation'), 'artifact': p.get('artifact_sha') or body.get('artifact'),
                'request_id': body.get('request_id') or issued.get('request_id') or (runs.get(run_id) or {}).get('request_id'),
                'source': _source(seq, kind, at, task)}
    for ref, row in receipts.items():
        row['receipt'] = ref
        row['request_link'] = (_unknown('the receipt names no request') if row.get('request_id') is None
                               else {'link': 'known', 'request_id': row['request_id']})

    # repair assignments (node-repair-plan receipts in plan.revised definitions) and node outputs
    repairs, produced = {}, []
    for seq, kind, p, at in events:
        if kind == 'node.produced': produced.append((seq, p))
        if kind != 'plan.revised': continue
        for item in (blobs.get(p.get('definition')) or {}).get('nodes', []):
            for ref in item.get('input', []):
                if not isinstance(ref, str) or not ref.startswith(repair_tasks.PREFIX): continue
                key = ref[len(repair_tasks.PREFIX):]
                if key in repairs: continue
                body = blobs.get(key)
                if body and body.get('kind') == repair_tasks.KIND and body.get('root') == task:
                    repairs[key] = dict(body, id=key, seq=seq)
    out = []
    for f in register.get('findings', []):
        sources = [r for r in (f.get('source', {}).get('receipt'), (f.get('last_observed') or {}).get('receipt')) if r]
        resolution = f.get('resolution') if isinstance(f.get('resolution'), dict) else {}
        from_run = next((r['run_id'] for r in runs.values() if r.get('receipt') in sources), None)
        row = {'id': f['id'], 'status': f.get('status'), 'node': f.get('node'), 'criterion': f.get('criterion'),
               'severity': f.get('severity'), 'internal': bool(f.get('internal')), 'candidate': f.get('artifact_sha'),
               'generation': f.get('generation'), 'source_receipt': f.get('source', {}).get('receipt'),
               'from_run': ({'link': 'known', 'run_id': from_run} if from_run
                            else _unknown('the opening receipt is not the result of a recorded run')),
               'recurrence_of': f.get('recurrence_of'), 'recurred_as': f.get('recurred_as') or []}
        repair = next((r for r in repairs.values() if {r.get('source_receipt'), *(r.get('source_receipts') or [])} & set(sources)), None)
        output = None
        if repair:
            gen = (repair.get('generations') or {}).get(repair.get('target'))
            found = next(((s, p) for s, p in produced if s > repair['seq'] and p.get('node') == repair.get('target')
                          and p.get('generation') == gen), None)
            if found:
                output = {'link': 'known', 'artifact': found[1].get('artifact'), 'generation': gen, 'node': repair.get('target'),
                          'source': {'seq': found[0], 'kind': 'node.produced', 'task': task}}
        row['repair'] = ({'link': 'known', 'id': repair['id'], 'target': repair.get('target'), 'failed_node': repair.get('failed_node'),
                          'failed_checks': repair.get('failed_checks') or [], 'source': {'seq': repair['seq'], 'kind': 'plan.revised', 'task': task}}
                         if repair else _unknown('no repair assignment names the failing receipt of this finding'))
        row['output'] = output or _unknown('no produced output of the repaired generation is recorded' if repair else 'no repair assignment')
        recheck = _unknown('no recheck receipt is recorded for this finding')
        if resolution.get('receipt'):
            known = receipts.get(resolution['receipt']) or {}
            request_id = (resolution.get('recheck') or {}).get('request')
            recheck = {'link': 'known', 'receipt': resolution['receipt'], 'result': known.get('result'),
                       'closed': f.get('status') in ('resolved', 'rejected'),
                       'request': ({'link': 'known', 'request_id': request_id} if request_id
                                   else known.get('request_link') or _unknown('closed without a recorded request')),
                       'source': known.get('source')}
        elif output:
            later = [r for r in receipts.values() if r.get('origin') == 'node.verification' and r.get('node') == f.get('node')
                     and r['source']['seq'] > output['source']['seq']]
            if later:
                last = later[-1]
                recheck = {'link': 'known', 'receipt': last['receipt'], 'result': last.get('result'), 'closed': False,
                           'request': last['request_link'], 'source': last['source']}
        row['recheck'] = recheck
        out.append(row)
    return {'schema_version': VERSION, 'read_only': True, 'task': task, 'plan': state.get('name'),
            'requests': sorted(requests.values(), key=lambda r: r['source']['seq']),
            'runs': sorted(runs.values(), key=lambda r: r['sources'][0]['seq']),
            'receipts': sorted(receipts.values(), key=lambda r: r['source']['seq']), 'findings': out, 'limitations': limitations}
