"""R06 incident adapter: authentic attempt observations, one incident per finding.

Observations use the existing context/receipt mechanism. A verified repair
finalizes one neutral learning.incident, without completing a task or root.
"""
import json
import ast

from .. import outcome_core
from ..ledger import LedgerError, canonical, content_hash, key_field, text_field
from ..snapshots import Snapshots
from . import compat, context, findings, namespaces, plan as plans, verdict

OBSERVATION = 'incident-observation'
KIND = 'learning.incident'


def _root(ledger, conn, name):
    state = plans.anchor_events(ledger, conn, name)
    return state, conn.execute('SELECT request_key FROM tasks WHERE id=?', (state['task_id'],)).fetchone()[0]


def _event(ledger, conn, task, seq, kind=None):
    if type(seq) is not int or seq < 1:
        raise LedgerError('A source event id is required.')
    row = conn.execute('SELECT seq,kind,payload FROM events WHERE seq=? AND task_id=?', (seq, task)).fetchone()
    if row is None or kind is not None and row['kind'] != kind:
        raise LedgerError('The evidence event does not belong to this root or source kind.')
    return dict(row, payload=json.loads(row['payload']))


def _receipt(ledger, conn, state, selector, receipt, latest=False):
    try:
        body = json.loads(Snapshots(ledger.state_root).read_blob(receipt))
    except (OSError, ValueError) as error:
        raise LedgerError('Attempt evidence is not a receipt blob.') from error
    if not isinstance(body, dict):
        raise LedgerError('Attempt evidence is not a receipt object.')
    if body.get('kind') == 'node-verifier-receipt':
        return _node_receipt(ledger, conn, state, receipt, body, latest=latest)
    revision, node = body.get('revision'), body.get('milestone')
    contract, sha = plans.load(ledger, state, revision)
    root = {'id': state['task_id'], 'request_key': selector}
    if latest:
        proof, result, seq = findings._proof(ledger, conn, root, state['name'], revision, sha, contract, node, receipt,
                                            body.get('generation', 1), body.get('artifact_sha'), latest=True)
    else:
        matched = [v for v in state['verdicts'] if v['revision'] == revision and v['milestone'] == node
                   and v['receipt'] == receipt and v['artifact_sha'] == body.get('artifact_sha')]
        if not matched:
            raise LedgerError('The receipt has no recorded verdict on this root.')
        result, seq = matched[-1]['result'], matched[-1]['seq']
        milestone = next((m for m in contract['milestones'] if m['id'] == node), None)
        if milestone is None:
            raise LedgerError('The attempt names no milestone of its recorded revision.')
        proof = verdict._check_receipt(ledger, state['name'], revision, sha, milestone, result,
                                       milestone['verifier']['type'], body['artifact_sha'], receipt, state['issued'])
    run = next((r for r in verdict.run_records(conn, state['task_id']) if r['receipt'] and r['receipt'].get('receipt') == receipt), None)
    if run is None:
        raise LedgerError('Attempt evidence needs an authentic verifier run id.')
    return proof, result, seq, run['run_id']


def _node_receipt(ledger, conn, state, receipt, body, *, latest=False):
    """Adapt the engine's issued event and real candidate checker receipts."""
    from . import engine
    from .. import common_verification as cv
    store = Snapshots(ledger.state_root)
    rows = conn.execute("SELECT seq,payload FROM events WHERE task_id=? AND kind='node.verification' AND json_extract(payload,'$.receipt')=? ORDER BY seq",
                        (state['task_id'], receipt)).fetchall()
    if not rows or body.get('root') != state['task_id']:
        raise LedgerError('The node receipt has no authentic verification event on this root.')
    event, seq = json.loads(rows[-1]['payload']), rows[-1]['seq']
    if any(event.get(k) != body.get(k) for k in ('node', 'generation', 'result')):
        raise LedgerError('The node receipt differs from its recorded verification.')
    proposal = conn.execute("SELECT payload FROM events WHERE task_id=? AND kind='plan.revised' AND seq<? AND json_extract(payload,'$.internal_revision')=? ORDER BY seq DESC LIMIT 1",
                            (state['task_id'], seq, body.get('internal_revision'))).fetchone()
    if proposal is None:
        raise LedgerError('No immutable internal definition supports this receipt.')
    definition_event = json.loads(proposal['payload'])
    definition = json.loads(store.read_blob(definition_event['definition']))
    item = next((n for n in definition['nodes'] if n['id'] == body.get('node')), None)
    if item is None or content_hash(item['checks']) != body.get('checks_sha'):
        raise LedgerError('The receipt check configuration is not the immutable node definition.')
    started = conn.execute("SELECT payload FROM events WHERE task_id=? AND kind='node.started' AND seq<? AND json_extract(payload,'$.node')=? AND json_extract(payload,'$.generation')=? AND json_extract(payload,'$.internal_revision')=? ORDER BY seq DESC LIMIT 1",
                           (state['task_id'], seq, item['id'], body['generation'], body['internal_revision'])).fetchone()
    if started is None:
        raise LedgerError('Node evidence needs its actual engine attempt.')
    attempt = json.loads(started['payload'])['attempt']
    execution = conn.execute('SELECT status FROM attempts WHERE id=?', (attempt,)).fetchone()
    if execution is None or execution['status'] != 'settled':
        raise LedgerError('The node producer attempt has not settled.')
    if latest:
        view = engine.state(ledger, state['selector'], conn)
        record = view['nodes'].get(item['id'], {})
        valid_revisions = record.get('valid_internal_revisions', [view['internal_revision']])
        if (body['internal_revision'] not in valid_revisions or record.get('generation') != body['generation']
                or record.get('artifact') != body['artifact'] or record.get('verification_receipt') != receipt):
            raise LedgerError('The node evidence is superseded by a later generation or verification.')
    contract, sha = plans.load(ledger, state, definition_event['revision'])
    observed = body.get('observed') or {}
    supported, environment = [], bool(body.get('evidence_errors'))
    for row in observed.get('checks', []):
        if row.get('result') == 'blocked':
            continue
        try:
            wrapper = json.loads(store.read_blob(row['evidence']))
            kind = wrapper.get('kind')
            if kind not in cv.PROOF_FIELD:
                continue        # typed support covers command, adapter and reviewer proofs; anything else stays unknown
            ref = wrapper[cv.PROOF_FIELD[kind]]
            proof = json.loads(store.read_blob(ref))
            milestone = next((m for m in contract['milestones'] if m['id'] == row['id']), None)
            if (milestone is None or wrapper.get('node') != item['id'] or wrapper.get('snapshot') != body['artifact']
                    or wrapper.get('tree') != observed.get('candidate_tree')
                    or cv.proof_mismatch(wrapper, proof, milestone, sha, definition_event['revision'], wrapper['tree']) is not None):
                raise LedgerError('Candidate check evidence does not bind the recorded node artifact and contract.')
            if cv.expected_of(kind, proof) != row['result']:
                raise LedgerError('Candidate result differs from its actual configured verification.')
            environment |= bool(proof.get('error') or proof.get('timed_out') or proof.get('provider_error'))
            supported.append({'id': row['id'], 'result': row['result'], 'kind': kind, 'receipt': ref, 'body': proof,
                              'config': milestone['verifier']['config']})
        except (OSError, ValueError, KeyError, TypeError):
            continue  # Unsupported injected checker evidence cannot become verified learning.
    return dict(body, revision=definition_event['revision'], artifact_sha=body['artifact'], milestone=item['id'],
                verified_tree=observed.get('candidate_tree'), supported_checks=supported, environment_error=environment), body['result'], seq, attempt


def observe(ledger, name, finding, receipt, *, intentional_red=False, intent_event=None, refuted_hypotheses=()):
    """Record one real run; typed receipt failures are never called product defects.

    An intentional red needs a recorded acceptance-test-preparation decision.
    Its observation remains evidence but is not promoted to a product incident.
    """
    key_field(finding)
    with ledger.transaction() as conn:
        state, selector = _root(ledger, conn, name)
        registered = next((f for f in findings.list_findings(ledger, selector) if f['id'] == finding), None)
        if registered is None:
            raise LedgerError('The finding is not registered on this root.')
        body, result, seq, attempt = _receipt(ledger, conn, state, selector, receipt)
        if body['milestone'] != registered['node']:
            raise LedgerError('The attempt does not verify the finding node.')
        refuted = []
        for hypothesis in refuted_hypotheses:
            ident = key_field(hypothesis.get('id'))
            text = text_field(hypothesis.get('text'), 'refuted hypothesis', 600)
            evidence = _event(ledger, conn, state['task_id'], hypothesis.get('event'), 'context.entry')
            if evidence['payload'].get('label') != 'refuted':
                raise LedgerError('A refuted hypothesis needs its refuted context event.')
            refuted.append({'id': ident, 'text': text, 'event': evidence['seq'], 'label': 'refuted'})
        if intentional_red:
            intent = _event(ledger, conn, state['task_id'], intent_event, 'decision.recorded')
            if intent['payload'].get('scope') != 'acceptance-test-preparation':
                raise LedgerError('Intentional red requires an acceptance-test-preparation decision.')
            if intent['seq'] >= seq:
                raise LedgerError('The intentional-red decision must precede the failed attempt.')
            if result == 'pass':
                raise LedgerError('A passing attempt is not an intentional red.')
    classification = ('intentional_red' if intentional_red else 'verified' if result == 'pass' else
                      'environment' if body.get('error') or body.get('timed_out') or body.get('provider_error') else
                      'product' if result == 'fail' else 'unknown')
    value = {'kind': OBSERVATION, 'version': 1, 'root': state['task_id'], 'finding': finding, 'attempt': attempt,
             'receipt': receipt, 'verdict_event': seq, 'revision': body['revision'], 'artifact': body['artifact_sha'],
             'classification': classification, 'refuted_hypotheses': refuted, 'intent_event': intent_event}
    blob = Snapshots(ledger.state_root).blob(canonical(value).encode('utf-8'))
    entry = context.add(ledger, selector, kind='note', label='observed', text=f'Attempt {attempt}: {classification} for finding {finding}.',
                        source={'type': 'receipt', 'key': blob}, key='incident-' + content_hash([finding, attempt])[:32])
    return dict(value, recorded=entry['recorded'], context_event=entry['event'])


def observations(ledger, name, finding=None):
    rows = context.retrieve(ledger, plan=name, scope='project', limit=1000)['entries']
    out = []
    for entry in rows:
        if not entry['key'].startswith('incident-') or entry['source']['type'] != 'receipt':
            continue
        body = json.loads(Snapshots(ledger.state_root).read_blob(entry['source']['key']))
        if body.get('kind') == OBSERVATION and (finding is None or body['finding'] == finding):
            out.append(dict(body, context_event=entry['event']))
    return sorted(out, key=lambda item: item['verdict_event'])


def list_incidents(ledger, name):
    with ledger.transaction() as conn:
        state, _ = _root(ledger, conn, name)
        return [dict(json.loads(r['payload']), event=r['seq']) for r in conn.execute(
            'SELECT seq,payload FROM events WHERE task_id=? AND kind=? ORDER BY seq', (state['task_id'], KIND))]


def finalize(ledger, name, finding, *, cause=None, require_resolved=True):
    """Finalize exactly one incident after an authentic, explicitly resolved repair."""
    if cause is not None:
        raise LedgerError('A cause is not inferred from a green test; keep hypotheses and evidence separate.')
    existing = next((i for i in list_incidents(ledger, name) if i['finding'] == finding), None)
    if existing:
        return dict(existing, recorded=False)
    attempts = [o for o in observations(ledger, name, finding) if o['classification'] != 'intentional_red']
    if not attempts or attempts[-1]['classification'] != 'verified':
        raise LedgerError('An incident finalizes only after a verified repair.')
    registered = next((f for f in findings.list_findings(ledger, name) if f['id'] == finding), None)
    if registered is None or (require_resolved and (registered['status'] != 'resolved' or registered['resolution']['receipt'] != attempts[-1]['receipt'])):
        raise LedgerError('The finding needs an explicit resolution on the verified repair receipt.')
    refuted = {h['id']: h for attempt in attempts for h in attempt['refuted_hypotheses']}
    with ledger.transaction(write=True) as conn:
        state, selector = _root(ledger, conn, name)
        # Revalidate the proof against the latest generation/receipt before publishing.
        last = attempts[-1]
        _receipt(ledger, conn, state, selector, last['receipt'], latest=True)
        value = {'version': 1, 'task': state['task_id'], 'plan': state['name'], 'finding': finding,
                 'incident': 'INC-' + content_hash([state['task_id'], finding])[:24], 'attempts': attempts,
                 'refuted_hypotheses': list(refuted.values()), 'cause': None, 'verified_receipt': last['receipt'],
                 'artifact': last['artifact'], 'revision': last['revision'], 'automatic_injection': False}
        value['id'] = outcome_core.outcome_id(value)
        compat.check_write(KIND, value, selector)
        event = outcome_core.append_learning(conn, ledger, state['task_id'], KIND, value)
    return dict(value, event=event, recorded=event is not None)


def after_verdict(ledger, name, node, receipt):
    """Best-effort observer hook after authentic verdict publication.

    It records facts only. A passing check never resolves a finding or changes
    a gate. A project candidate quotes the actual verified check and location;
    a cause or general rule is never invented.
    """
    from . import lessons
    with ledger.transaction() as conn:
        state, selector = _root(ledger, conn, name)
    if not namespaces.has_capability(state, 'finding-register'):
        return []
    results = []
    for finding in findings.list_findings(ledger, selector, open_only=True):
        if finding['node'] != node:
            continue
        observation = observe(ledger, selector, finding['id'], receipt)
        result = {'observation': observation}
        if observation['classification'] == 'verified':
            incident = finalize(ledger, selector, finding['id'], require_resolved=False)
            result['incident'] = incident
            with ledger.transaction() as conn:
                current, _ = _root(ledger, conn, selector)
                proof, _, _, _ = _receipt(ledger, conn, current, selector, receipt, latest=True)
            row = next((c for c in proof.get('criteria', []) if c.get('id') == finding['criterion'] and c.get('verdict') == 'pass'), None)
            location = next((e for e in (row or {}).get('evidence', []) if e.get('file') and e.get('line')), None)
            if location:
                check = 'reviewer:' + finding['criterion']
                text = f'Check {check} passed at {location["file"]}:{location["line"]} for finding {finding["id"]}. Finding closure is a separate explicit transition. Receipt {receipt}.'
                revision = proof['artifact_sha']
                try:
                    head = context.resolve_revision(ledger.project, 'HEAD')
                    from .verifiers import command
                    if command._git(ledger.project, 'rev-parse', head + '^{tree}') == proof['artifact_sha']:
                        revision = head
                except LedgerError:
                    pass
                result['lesson'] = lessons.record(ledger, selector, incident['event'], text=text, path=location['file'], line=location['line'],
                                                  revision=revision, test=check, candidate=True)
        results.append(result)
    return results


def observe_node(ledger, name, node, receipt):
    """A native failure episode is distinct from a registered review finding."""
    with ledger.transaction() as conn:
        state, selector = _root(ledger, conn, name)
        proof, result, seq, attempt = _receipt(ledger, conn, state, selector, receipt, latest=True)
        if proof.get('kind') != 'node-verifier-receipt' or proof['node'] != node:
            raise LedgerError('The node observation needs its authentic node receipt.')
        if not namespaces.has_capability(state, 'sequential-engine'):
            return None
        intent = None
        for row in conn.execute("SELECT seq,payload FROM events WHERE task_id=? AND kind='decision.recorded' AND seq<? ORDER BY seq DESC", (state['task_id'], seq)):
            decision = json.loads(row['payload'])
            validity = decision.get('validity') or {}
            if (decision.get('scope') == 'acceptance-test-preparation' and isinstance(validity, dict)
                    and validity.get('node') == node and validity.get('internal_revision') == proof['internal_revision']):
                intent = row['seq']; break
    actual = proof['supported_checks']
    classification = ('intentional_red' if intent and result != 'pass' else
                      'environment' if proof['environment_error'] else
                      'verified' if result == 'pass' and actual and all(c['result'] == 'pass' for c in actual) else
                      'product' if any(c['result'] == 'fail' for c in actual) else 'unknown')
    prior = [o for o in observations(ledger, selector) if o.get('node') == node and o.get('checks_sha') == proof['checks_sha'] and o.get('episode')]
    prior = sorted(prior, key=lambda o: o['verdict_event'])
    if prior and prior[-1]['receipt'] == receipt:
        return dict(prior[-1], recorded=False)
    if classification == 'verified' and (not prior or prior[-1]['classification'] in ('verified', 'intentional_red')):
        return None
    if not prior or prior[-1]['classification'] in ('verified', 'intentional_red'):
        episode = 'NEP-' + content_hash([state['task_id'], node, proof['checks_sha'], seq])[:28]
    else:
        episode = prior[-1]['episode']
    value = {'kind': OBSERVATION, 'version': 1, 'root': state['task_id'], 'finding': None, 'episode': episode,
             'node': node, 'checks_sha': proof['checks_sha'], 'attempt': attempt, 'receipt': receipt, 'verdict_event': seq,
             'revision': proof['revision'], 'generation': proof['generation'], 'internal_revision': proof['internal_revision'],
             'artifact': proof['artifact'], 'verified_tree': proof['verified_tree'], 'classification': classification,
             'refuted_hypotheses': [], 'intent_event': intent}
    blob = Snapshots(ledger.state_root).blob(canonical(value).encode())
    entry = context.add(ledger, selector, kind='note', label='observed',
                        text=f'Node {node} attempt {attempt}: {classification}; failure episode {episode}.',
                        source={'type': 'receipt', 'key': blob}, key='incident-' + content_hash([episode, receipt])[:32])
    return dict(value, recorded=entry['recorded'], context_event=entry['event'])


def _node_location(ledger, proof):
    """Only locate actual configured file inputs; do not infer a root cause."""
    tree = proof.get('verified_tree')
    if not tree:
        return None
    for check in proof['supported_checks']:
        if check['result'] != 'pass':
            continue
        paths = []
        if check['kind'] == 'candidate-reviewer-check':
            continue        # a review reads a diff, not a configured file input; nothing to locate from it
        if check['kind'] == 'candidate-adapter-check':
            paths.append(check['config'].get('path'))
        else:
            argv = check['body'].get('argv', [])
            paths += [p for p in argv[1:] if isinstance(p, str) and not p.startswith('-') and '\n' not in p]
            if '-c' in argv:
                try:
                    parsed = ast.parse(argv[argv.index('-c') + 1])
                    paths += [n.args[0].value for n in ast.walk(parsed) if isinstance(n, ast.Call) and n.args
                              and isinstance(n.args[0], ast.Constant) and isinstance(n.args[0].value, str)
                              and ((isinstance(n.func, ast.Name) and n.func.id in ('Path', 'open'))
                                   or isinstance(n.func, ast.Attribute) and n.func.attr == 'Path')]
                except (SyntaxError, IndexError):
                    pass
        for path in paths:
            try:
                path = context._path(path)
                if context.file_at(ledger.project, tree, path).splitlines():
                    return {'path': path, 'line': 1, 'revision': tree, 'test': 'check:' + check['id']}
            except (LedgerError, OSError, TypeError):
                continue
    return None


def after_node(ledger, name, node, receipt):
    """Observe authentic native fail→repair→pass without inventing a finding."""
    from . import lessons
    observation = observe_node(ledger, name, node, receipt)
    if observation is None or observation['classification'] != 'verified':
        return {'observation': observation}
    episode = observation['episode']
    previous = next((i for i in list_incidents(ledger, name) if i.get('episode') == episode), None)
    if previous:
        incident = dict(previous, recorded=False)
    else:
        attempts = [o for o in observations(ledger, name) if o.get('episode') == episode]
        if not any(o['classification'] == 'product' for o in attempts):
            return {'observation': observation}  # An environment failure alone is not a product lesson.
        with ledger.transaction(write=True) as conn:
            state, selector = _root(ledger, conn, name)
            proof, _, _, _ = _receipt(ledger, conn, state, selector, receipt, latest=True)
            value = {'version': 1, 'task': state['task_id'], 'plan': state['name'], 'finding': None, 'episode': episode,
                     'node': node, 'incident': 'INC-' + content_hash([state['task_id'], episode])[:24], 'attempts': attempts,
                     'refuted_hypotheses': [], 'cause': None, 'verified_receipt': receipt, 'artifact': proof['artifact'],
                     'verified_tree': proof['verified_tree'], 'revision': proof['revision'], 'automatic_injection': False}
            value['id'] = outcome_core.outcome_id(value)
            compat.check_write(KIND, value, selector)
            event = outcome_core.append_learning(conn, ledger, state['task_id'], KIND, value)
            if event is None:
                event = conn.execute("SELECT seq FROM events WHERE task_id=? AND kind=? AND json_extract(payload,'$.id')=?",
                                     (state['task_id'], KIND, value['id'])).fetchone()[0]
        incident = dict(value, event=event, recorded=True)
    with ledger.transaction() as conn:
        state, selector = _root(ledger, conn, name)
        proof, _, _, _ = _receipt(ledger, conn, state, selector, receipt, latest=True)
    location = _node_location(ledger, proof)
    result = {'observation': observation, 'incident': incident}
    if location:
        result['lesson'] = lessons.record(ledger, name, incident['event'],
            text=f'Configured {location["test"]} passed on the repaired candidate input {location["path"]}. Failure episode {episode}; cause is not established.',
            candidate=True, **location)
    return result
