"""Explicit, revision-bound in-scope requirement changes with DAG invalidation."""
from .ledger import LedgerError, content_hash, text_field
from .specs import Project


def profile_for(state, control):
    return (state.get('amendment') or {}).get('profile', control['configuration']['profile'])


def spec_for(state, task):
    return (state.get('amendment') or {}).get('spec_text', task['handoff']['spec_text'])


def plan_revision(state):
    if not state or not state.get('plan'):
        return None
    if state.get('amendment'):
        return content_hash({'plan': state['plan'], 'spec_revision': state['amendment']['spec_revision'],
                             'profile': state['amendment']['profile']})
    return content_hash(state['plan'])


def affected_tasks(plan, selected):
    tasks = {r['id']: r for r in plan['tasks']}
    if not isinstance(selected, list) or not selected or not all(isinstance(x, str) for x in selected) or not set(selected) <= set(tasks):
        raise LedgerError('Affected task IDs must be a non-empty subset of the current plan.')
    affected = set(selected)
    while True:
        owned = {p for key in affected for p in tasks[key]['owned']}
        expanded = affected | {key for key, row in tasks.items()
                               if set(row['depends_on']) & affected or set(row['owned']) & owned}
        if expanded == affected:
            return affected
        affected = expanded


def apply(workflow, task_id, revision, spec_revision, profile, selected, reason):
    from .workflow import task_lock, validate_profile, validate_plan
    text_field(reason, 'Requirement change reason', 1000)
    profile = validate_profile(profile)
    with task_lock(workflow.ledger, task_id):
        sequence, state = workflow.state(task_id)
        control = workflow.control.status(task_id)
        if not state or content_hash(state) != revision:
            raise LedgerError('Stale workflow revision; review the current plan/output before amendment.')
        if state.get('feedback_repair') or state.get('tool_pending'):
            raise LedgerError('Finish the scheduled review correction before changing its requirements.')
        if not state['plan'] or control['cancel_requested']:
            raise LedgerError('A non-cancelled planned task is required.')
        if any(a['status'] != 'settled' for a in control['attempts']):
            raise LedgerError('Stop and reconcile all writers before changing requirements.')
        task = workflow.ledger.task(task_id, full=True)
        if task['pending_requests']:
            raise LedgerError('Resolve pending questions before changing their requirement revision.')
        original = control['configuration']['profile']
        old_profile = profile_for(state, control)
        # This operation is explicitly authorized by the local operator, but cannot turn
        # a revision into permission to read/write new paths, tools, models or larger caps.
        for field in ('context', 'owned'):
            if set(profile[field]) != set(original[field]):
                raise LedgerError('Requirement amendment cannot expand or replace the sealed file scope.')
        for field in ('provider', 'model', 'parallel', 'max_repairs', 'step_seconds', 'tools'):
            if profile.get(field) != old_profile.get(field):
                raise LedgerError('Use the dedicated controls for worker/budget changes; amendment only changes acceptance/checks.')
        if {a['id'] for a in profile['acceptance']} != {a['id'] for a in old_profile['acceptance']}:
            raise LedgerError('Keep acceptance IDs stable so their dependent tasks can be invalidated.')
        spec = Project(workflow.ledger.project).find(task['spec_id'])
        if spec.revision != spec_revision:
            raise LedgerError('Stale spec revision; review the edited spec first.')
        previous_spec = (state.get('amendment') or {}).get('spec_revision', task['spec_revision'])
        if spec_revision == previous_spec and profile == old_profile:
            raise LedgerError('No requirement change to apply.')
        validate_plan(state['plan'], profile)
        container_checks = [c for c in profile['checks'] if c['kind'] == 'container_test']
        if container_checks:
            from .sandbox_gate import ContainerGate
            ContainerGate(workflow.store).preflight(container_checks)
        # Every task tied to a changed AC/check is invalidated even if an operator omits it.
        old_ac = {a['id']: a for a in old_profile['acceptance']}
        changed_ac = {a['id'] for a in profile['acceptance'] if a != old_ac[a['id']]}
        old_checks, new_checks = ({c['id']: c for c in p['checks']} for p in (old_profile, profile))
        for key in set(old_checks) | set(new_checks):
            if old_checks.get(key) != new_checks.get(key):
                changed_ac.update(old_checks.get(key, {}).get('acceptance', []))
                changed_ac.update(new_checks.get(key, {}).get('acceptance', []))
        base = workflow.store.load(state['base'])
        new_base_id = workflow.store.capture(workflow.ledger.project, profile['context'])
        new_base = workflow.store.load(new_base_id)
        if any(base['files'][p] != new_base['files'][p] for p in profile['owned']):
            raise LedgerError('User-owned source/index changed; reconcile it explicitly before amending this candidate.')
        for check in profile['checks']:
            if base['files'][check['path']]['working'] != new_base['files'][check['path']]['working']:
                changed_ac.update(check['acceptance'])
        mandatory = [r['id'] for r in state['plan']['tasks'] if set(r['acceptance']) & changed_ac]
        affected = affected_tasks(state['plan'], selected)
        if mandatory:
            affected = affected_tasks(state['plan'], sorted(affected | set(mandatory)))
        paths = sorted({p for r in state['plan']['tasks'] if r['id'] in affected for p in r['owned']})
        before = state['snapshot']
        previous = workflow.store.load(before)
        changes = {}
        for path in profile['owned']:
            source = new_base if path in paths else previous
            blob = source['files'][path]['working']
            changes[path] = workflow.store.read_blob(blob) if blob else None
        candidate = workflow.store.overlay(new_base_id, changes, profile['owned'])
        state['amendment'] = {'spec_revision': spec_revision, 'spec_text': spec.text, 'profile': profile,
                              'previous_workflow_revision': revision, 'reason': reason, 'authority': 'local_operator',
                              'affected_tasks': sorted(affected), 'old_snapshot': before, 'previous_base': state['base'], 'scope_expanded': False}
        state['base'] = new_base_id
        state['snapshot'] = candidate
        state['done'] = [key for key in state['done'] if key not in affected]
        state['branch_errors'] = {key: value for key, value in state.get('branch_errors', {}).items() if key not in affected}
        state.update(phase='working', verification='pending', acceptance='not_requested', message=None,
                     checks=None, pending=None, parallel_pending=[], failures=[], last_failure=None)
        state.pop('verification_only', None)
        state.pop('resume_phase', None)
        # Preserve counters, completed independent branches, original bytes and all old evidence.
        for output in state['outputs']:
            if output['stage'] in affected or output['stage'] == 'repair':
                output['invalidated_by'] = spec_revision
                output['verification'] = 'stale'
        workflow.persist(task_id, sequence, state, unpause=True)
        return {'workflow_revision': content_hash(state), 'spec_revision': spec_revision,
                'invalidated_tasks': sorted(affected), 'preserved_tasks': state['done'],
                'snapshot': candidate, 'used_calls': control['used_calls'], 'deadline': control['deadline']}
