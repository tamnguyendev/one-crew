"""R06 incident adapter: authentic attempt observations, one incident per finding.

Observations use the existing context/receipt mechanism. A verified repair
finalizes one neutral learning.incident, without completing a task or root.
"""
import json

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
