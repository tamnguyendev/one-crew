"""Project-local, evidence-backed skill candidates. No model, shell, or grant authority."""
import argparse
import json
import re
from pathlib import Path

from .ledger import Ledger, LedgerError, canonical, content_hash, text_field
from .snapshots import durable_write

POLICY = {'version': 1, 'min_tasks': 3, 'min_successes': 2, 'similarity': .6, 'history_limit': 200}
PERMISSIONS = {'write': ['candidate.write'], 'test': ['sandbox.test'],
               'deliver': ['git.branch', 'git.commit', 'git.push'], 'branch_before': ['git.branch'],
               'android_build': ['android.build']}
STEPS = {'list': 'Locate the relevant project files within scope.',
         'search': 'Search for evidence tied to the requested behavior.',
         'read': 'Read the implementation and original tests; record evidence.',
         'write': 'Make the smallest authorized candidate change; preserve original tests.',
         'test': 'Run authorized tests on the current candidate; retain failure and success evidence.',
         'git_status': 'Inspect repository state before selecting changes.',
         'git_diff': 'Inspect relevant diffs and exclude unrelated changes.',
         'git_log': 'Inspect bounded history for the requested boundary.',
         'git_show': 'Verify historical changes from actual diffs.',
         'branch_before': 'Create only the authorized historical branch after evidence review.',
         'android_build': 'Request the fixed granted build recipe; core waits and verifies its artifact.',
         'deliver': 'Publish only the authorized changes to the granted destination.',
         'finish': 'Report evidence, limitations and unverified acceptance criteria.'}


def signature(goal, mode, files):
    words = sorted(set(re.findall(r'[^\W\d_]{3,}', goal.lower(), re.UNICODE)))[:80]
    extensions = sorted({Path(p).suffix.lower() for p in files if Path(p).suffix})[:20]
    return {'mode': mode, 'extensions': extensions, 'words': words}


def similar(a, b):
    if not a or not b or a['mode'] != b['mode'] or not a['extensions'] or a['extensions'] != b['extensions']:
        return False
    x, y = set(a['words']), set(b['words'])
    return bool(x and y) and len(x & y) / len(x | y) >= POLICY['similarity']


def latest(ledger, conn):
    rows = conn.execute("SELECT e.seq,e.task_id,e.payload FROM events e JOIN tasks t ON t.id=e.task_id "
        "WHERE t.project_id=? AND e.kind='learning.outcome' ORDER BY e.seq DESC LIMIT ?",
        (ledger.project_id, POLICY['history_limit'])).fetchall()
    result = {}
    for row in rows:
        result.setdefault(row['task_id'], dict(json.loads(row['payload']), event=row['seq']))
    return list(result.values())


def good(row):
    return row['phase'] == 'completed' and row.get('verification') in ('passed', 'evidence_collected')


def records(ledger, conn):
    rows = conn.execute("SELECT e.payload FROM events e JOIN tasks t ON t.id=e.task_id "
        "WHERE t.project_id=? AND e.kind='skill.state' ORDER BY e.seq", (ledger.project_id,)).fetchall()
    result = {}
    for row in rows:
        value = json.loads(row['payload']); result[value['id']] = value
    return result


def skill_path(ledger, value):
    return ledger.state_root / 'skills' / ledger.project_id / value['id'] / value['revision'] / 'SKILL.md'


def refresh(ledger):
    """Called only after a new terminal outcome, or an explicit operator scan."""
    with ledger.transaction(write=True) as conn:
        history = latest(ledger, conn); existing = records(ledger, conn)
        created = []
        for seed in history:
            sig = seed.get('signature')
            if not sig or not good(seed): continue
            if any(similar(sig, value['signature']) for value in existing.values()): continue
            group = [r for r in history if similar(sig, r.get('signature'))]
            successful = [r for r in group if good(r) and r.get('procedure') == seed.get('procedure')]
            if len(group) < POLICY['min_tasks'] or len(successful) < POLICY['min_successes']: continue
            procedure = seed.get('procedure', [])
            if not procedure or not set(procedure) <= set(STEPS): continue
            name = 'repeat-' + content_hash(sig)[:16]
            required = sorted({p for action in procedure for p in PERMISSIONS.get(action, [])})
            body = ('---\nname: '+name+'\ndescription: Reviewed recurring '+sig['mode']+' procedure\n---\n\n'
                '# Recurring task procedure\n\nUse only for matching goals, project and technology. '
                'Do not use for a different outcome, technology or ungranted operation. '
                'If unsuitable, explain the mismatch and follow the task criteria.\n\n' +
                '\n'.join(str(i+1)+'. '+STEPS[action] for i, action in enumerate(procedure)) +
                '\n\nTask acceptance, permissions and budget override this guide. '
                'These steps are a draft derived from observed action types, not proof of universal correctness.\n')
            value = {'id': name, 'project': ledger.project_id, 'signature': sig,
                'policy': dict(POLICY), 'status': 'proposed', 'body': body,
                'required_permissions': required, 'tasks': [r['task'] for r in group],
                'evidence': [{'task': r['task'], 'event': r['event'], 'snapshot': r['snapshot'], 'success': good(r)} for r in group],
                'successes': len(successful), 'failures': sum(not good(r) for r in group),
                'reason': 'Repeated goals, same mode/technology and successful action sequence; human suitability review required.',
                'limitations': ['Lexical similarity only', 'Outcome assistance may be unknown', 'Customer acceptance is independent']}
            value['revision'] = content_hash(value)
            durable_write(skill_path(ledger, value), body.encode('utf-8'))
            ledger._event(conn, seed['task'], 'skill.state', value)
            existing[name] = value; created.append(value)
    return created


def validate_evidence(ledger, conn, value):
    current = {r['task']: r for r in latest(ledger, conn)}
    for ref in value['evidence']:
        row = current.get(ref['task'])
        if not row or row['event'] != ref['event'] or row['snapshot'] != ref['snapshot']:
            raise LedgerError('Skill evidence is stale or outside the bounded history window.')
        execution = conn.execute('SELECT status FROM executions WHERE task_id=?', (ref['task'],)).fetchone()
        if ref['success'] and (not good(row) or not execution or execution['status'] != 'completed'):
            raise LedgerError('Skill success evidence is no longer completed.')
        cp = conn.execute("SELECT payload FROM events WHERE task_id=? AND kind='workflow.checkpoint' ORDER BY seq DESC LIMIT 1", (ref['task'],)).fetchone()
        if cp and json.loads(cp['payload']).get('snapshot') != ref['snapshot']:
            raise LedgerError('Skill source snapshot changed.')
    path = skill_path(ledger, value)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 8000 or path.read_bytes() != value['body'].encode('utf-8'):
        raise LedgerError('Skill file differs from its reviewed revision.')


def review(ledger, name=None):
    with ledger.transaction() as conn:
        values = records(ledger, conn) if conn else {}
        if name is None:
            return [{k: v[k] for k in ('id','revision','status','tasks','successes','failures','reason')} for v in values.values()]
        if name not in values: raise LedgerError('Unknown skill in this project.')
        value = values[name]
        try: validate_evidence(ledger, conn, value); value['usable_evidence'] = True
        except (ValueError, OSError) as error: value.update(usable_evidence=False, evidence_error=str(error))
        return dict(value, path=str(skill_path(ledger, value)))


def decide(ledger, name, revision, decision, reference):
    if decision not in ('approved', 'rejected'): raise LedgerError('Invalid skill decision.')
    reference = text_field(reference, 'operator reference', 500)
    with ledger.transaction(write=True) as conn:
        value = records(ledger, conn).get(name)
        if not value or value['revision'] != revision: raise LedgerError('Skill revision changed; review again.')
        if value['status'] == decision: return value
        if value['status'] != 'proposed': raise LedgerError('Skill already decided.')
        if decision == 'approved': validate_evidence(ledger, conn, value)
        value.update(status=decision, operator_reference=reference)
        ledger._event(conn, value['tasks'][0], 'skill.state', value)
        return value


def select(ledger, goal, profile, state, permissions):
    sig = signature(goal, profile['mode'], state['files'])
    with ledger.transaction() as conn:
        if not conn: return []
        for value in reversed(list(records(ledger, conn).values())):
            if value['status'] != 'approved' or not similar(sig, value['signature']): continue
            if not set(value['required_permissions']) <= set(permissions): continue
            try: validate_evidence(ledger, conn, value)
            except (ValueError, OSError): continue
            return [{'id': value['id'], 'revision': value['revision'], 'body': value['body'],
                     'reason': 'Approved project/mode/technology/goal match; required tools are granted.'}]
    return []


def main(argv=None):
    p = argparse.ArgumentParser(); p.add_argument('--project', type=Path, default=Path.cwd()); p.add_argument('--state-root', type=Path)
    sub = p.add_subparsers(dest='group', required=True).add_parser('skills').add_subparsers(dest='command', required=True)
    sub.add_parser('list'); sub.add_parser('scan')
    sub.add_parser('review').add_argument('id')
    for name in ('approve', 'reject'):
        q = sub.add_parser(name); q.add_argument('id'); q.add_argument('--revision', required=True); q.add_argument('--reference', required=True)
    a = p.parse_args(argv); ledger = Ledger(a.project, a.state_root)
    try:
        if a.command == 'scan': value = refresh(ledger)
        elif a.command == 'list': value = review(ledger)
        elif a.command == 'review': value = review(ledger, a.id)
        else: value = decide(ledger, a.id, a.revision, 'approved' if a.command == 'approve' else 'rejected', a.reference)
        print(json.dumps(value, ensure_ascii=False, indent=2)); return 0
    except (ValueError, OSError) as error:
        print(json.dumps({'error': str(error)})); return 2
