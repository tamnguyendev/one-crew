"""Task intake (core): the one place a task row is written, shared by v1 (`job submit`) and v2 (the plan's anchor task).

Moved from owned_intake.py / budget_policy.py / learning.py so that v2 imports no v1 module. `submit` is the former
`owned_intake.submit` with its v1-only steps (work contract, native-change / QC / Android recipes, delivery children, solution
binding) behind an `extension` object; owned_intake passes the v1 extension, a plain install passes none and can submit audit
tasks only, which is what the plan anchor is. The rows written (the `tasks` row, its payload, the `task.submitted` event) are the same.
"""
import datetime as dt
import json
import math
import uuid

from .ledger import LedgerError, canonical, content_hash, key_field, text_field, utcnow, validate_grant

DEFAULT_CALLS = 100
DEFAULT_SECONDS = 7200
POLICY = {'version': 2, 'warning_fraction': .7, 'automatic_extension': False}
NEEDS_V1 = 'This install submits audit tasks only; the other job modes need the full OneCrew checkout.'


def outcomes(ledger, limit=50):
    """The newest `limit` v1 outcomes of the project, newest first, plus (W23b) the newest `limit` outcomes of v2 plan anchors.

    Each partition has its own window, so v2 roots' outcomes stay readable here but can never push a v1 outcome out of the v1 window."""
    if type(limit) is not int or not 1<=limit<=200: raise LedgerError('limit must be 1-200.')
    window = ("SELECT * FROM (SELECT e.seq,e.payload FROM events e JOIN tasks t ON t.id=e.task_id WHERE t.project_id=? "
              "AND e.kind='learning.outcome' AND {} (t.request_key LIKE 'plan:%' OR t.request_key LIKE 'plan-ns:%') ORDER BY e.seq DESC LIMIT ?)")
    with ledger.transaction() as conn:
        if conn is None: return []
        rows=conn.execute(window.format('NOT')+' UNION ALL '+window.format('')+' ORDER BY seq DESC',
                          (ledger.project_id,limit,ledger.project_id,limit)).fetchall()
    return [{'event':r['seq'],**json.loads(r['payload'])} for r in rows]


def recommend(ledger, goal, mode, provider, model, history=None):
    """Evidence-only budget advice. `history` is the outcomes reader (v1 passes learning.outcomes, so patching it there still works)."""
    # Exact goal, same project/mode/provider/model. Similar wording alone is not
    # sufficient evidence to reduce a grant. Latest outcome wins per task.
    latest = {}
    # W23b: a v2 root's outcome (source 'v2-plan', mode 'plan') is never a v1 goal's history.
    for row in (history or outcomes)(ledger, 200):
        if row.get('source') != 'v2-plan': latest.setdefault(row['task'], row)
    matching = [r for r in latest.values() if r.get('spec_revision') == content_hash(goal)
                and (r.get('mode'), r.get('provider'), r.get('model')) == (mode, provider, model)]
    good = [r for r in matching if r['phase'] == 'completed'
            and r.get('verification') in ('passed', 'evidence_collected')
            and r.get('acceptance') not in ('changes_requested', 'rejected')
            and r.get('timing', {}).get('wall_seconds') is not None]
    enough = len(good) >= 3 and len(good) == len(matching)
    calls = min(10000, max(20, math.ceil(max(r['managed_calls'] for r in good) * 1.5))) if enough else DEFAULT_CALLS
    seconds = min(28800, max(600, math.ceil(max(r['timing']['wall_seconds'] for r in good) * 1.5))) if enough else DEFAULT_SECONDS
    return {'version': 1, 'classification': 'repeated_verified' if enough else 'insufficient_history',
            'recommended': {'max_calls': calls, 'max_seconds': seconds},
            'matching_tasks': len(matching), 'verified_tasks': len(good),
            'evidence': [{'task': r['task'], 'event': r['event']} for r in matching],
            'automatic_application': False, 'jev_used': False,
            'limitations': ['Exact goal match only; environment may differ.',
                           'Verification is not customer acceptance; wall time includes waits.',
                           'Observed history is not proof that the proposed budget is sufficient.']}


class Audit:
    """The hooks of a plain install: audit tasks only. owned_intake.V1 overrides every one with the v1 behaviour."""

    @staticmethod
    def work_contract(ledger, goal, contract, branch, remote, image, android_build, native_change):
        raise LedgerError(NEEDS_V1)

    @staticmethod
    def admit(mode, provider, model, image, branch, remote, android_build, native_change, qc, contract):
        """Validate the job options for `mode`; returns (native_change, qc, android_build, permissions)."""
        if mode != 'audit' or image or branch or remote or android_build or native_change or qc or contract: raise LedgerError(NEEDS_V1)
        return native_change, qc, android_build, ['discover', 'report']

    @staticmethod
    def recommend(ledger, goal, mode, provider, model):
        return recommend(ledger, goal, mode, provider, model)

    @staticmethod
    def child_budget(ledger, conn, parent, node, generation, goal, native_change, solution_id, solution_revision):
        raise LedgerError(NEEDS_V1)

    @staticmethod
    def solution_binding(ledger, conn, mode, solution_id, solution_revision, delivery_parent):
        if mode != 'audit' or solution_id: raise LedgerError(NEEDS_V1)
        return None

    @staticmethod
    def bind(conn, task_id, binding, solution_id, solution_revision):
        raise LedgerError(NEEDS_V1)

    @staticmethod
    def link_child(conn, task_id, parent, node, generation):
        raise LedgerError(NEEDS_V1)


def submit(ledger, goal, request_key, *, mode='audit', provider=None, model=None,
           max_calls=None, max_seconds=None, image=None, branch=None, remote=None, android_build=None, native_change=None,
           solution_id=None, solution_revision=None, contract=None, qc=None,
           plan_selector=None, plan_revision=None,
           _delivery_parent=None, _delivery_node=None, _delivery_generation=0, _delivery_scope=None, extension=None, _then=None):
    # `_then(conn, task_id)`: internal (plan.propose). Runs inside the same write transaction as the task row, also on an idempotent
    # replay, so a refusal there rolls the row back; it is not part of the sealed payload.
    calls_default, seconds_default = max_calls is None, max_seconds is None
    ext = extension or Audit
    if mode == 'work':
        # Generic job: the user's work contract (goal, scope, invariants, acceptance, authority) is the sealed agreement.
        goal, contract = ext.work_contract(ledger, goal, contract, branch, remote, image, android_build, native_change)
    elif contract is not None:
        raise LedgerError('A work contract needs --mode work.')
    goal = text_field(goal, 'goal', 12000)
    if _delivery_scope is not None and (_delivery_scope != 'tests' or not _delivery_parent):
        raise LedgerError('Only a delivery coordinator may narrow a child to a tests-only repair.')
    key_field(request_key)
    from .v2.plan import valid_plan_key
    valid_plan_key(request_key)          # audit W12a: a plan:/plan-ns: key is a plan name; refused before any write
    if plan_revision is not None and (type(plan_revision) is not int or plan_revision < 1):
        raise LedgerError('plan_revision must be a positive integer.')
    # Idempotent replay retains the original choice after operator preferences change.
    with ledger.transaction() as conn:
        prior=conn.execute('SELECT * FROM tasks WHERE project_id=? AND request_key=?',
                          (ledger.project_id,request_key)).fetchone() if conn else None
        from .v2 import plan_binding
        root_binding = json.loads(prior['payload']).get('plan_binding') if prior else None
        if root_binding is not None:
            if ((plan_selector is not None and plan_selector != root_binding['selector'])
                    or (plan_revision is not None and plan_revision != root_binding['revision'])):
                raise LedgerError('Submission key already has a different sealed plan binding.')
        elif plan_selector is not None:
            root_binding = plan_binding.capture(ledger, conn, plan_selector, plan_revision)
        elif plan_revision is not None:
            raise LedgerError('plan_revision requires an explicit plan_selector.')
        elif not prior:
            root_binding = plan_binding.implicit_workflow(ledger, conn, request_key)
        if _delivery_parent:
            inherited_root = plan_binding.inherited_workflow(ledger, conn, _delivery_parent)
            if inherited_root is not None:
                if root_binding is not None and root_binding != inherited_root:
                    raise LedgerError('A workflow child cannot leave its parent sealed plan root.')
                root_binding = inherited_root
        if solution_id is not None:
            from .v2 import solution_link
            linked = solution_link.intake_binding(ledger, conn, solution_id, solution_revision)
            if linked is not None:
                if root_binding is not None and root_binding != linked[0]:
                    raise LedgerError('The SOL work belongs to a different approved root than this handoff.')
                root_binding = linked[0]
        from .budget_core import group
        shared_defaults = group(conn, root_binding['root_task_id']) if root_binding else None
        shared_seconds = ((dt.datetime.fromisoformat(shared_defaults['deadline']) - dt.datetime.fromisoformat(plan_binding.first_approval_at(ledger, conn, root_binding))).total_seconds()
                          if shared_defaults else None)
    from .model_preferences import resolve, read
    previous=json.loads(prior['payload']).get('owned_execution') if prior else None
    prior_limits=json.loads(prior['payload'])['grant']['limits'] if prior else {}
    if max_calls is None: max_calls=prior_limits.get('max_calls',DEFAULT_CALLS)
    if max_seconds is None: max_seconds=prior_limits.get('max_seconds',DEFAULT_SECONDS)
    if shared_defaults and not prior:
        if calls_default:
            max_calls = min(max_calls, shared_defaults['max_calls'])
        if seconds_default:
            max_seconds = min(max_seconds, int(shared_seconds))
    # An explicit provider/model pins this job; only default intake inherits the chain.
    inherit_fallbacks = provider is None and model is None
    preference = previous or read(ledger)
    provider,model=resolve(ledger,provider,model,preference)
    if mode not in ('audit','change','delivery','branch','work') or provider not in ('codex','claude','kiro'):
        raise LedgerError('Unsupported job mode or provider.')
    text_field(model, 'model', 120)
    native_change, qc, android_build, permissions = ext.admit(mode, provider, model, image, branch, remote, android_build, native_change, qc, contract)
    grant = validate_grant({'schema_version':1,'permissions':permissions,
                           'limits':{'max_calls':max_calls,'max_seconds':max_seconds},'source':'local operator: job submit'})
    options = dict(mode=mode,provider=provider,model=model,image=image,branch=branch,remote=remote)
    if previous and 'budget_policy' in previous:
        options['budget_policy']=previous['budget_policy']
        options['budget_advice']=previous['budget_advice']
    elif not prior:
        options['budget_policy']=dict(POLICY)
        options['budget_advice']=ext.recommend(ledger,goal,mode,provider,model)
    if previous and 'fallbacks' in previous:
        options['fallbacks'] = previous['fallbacks']
    elif not previous and inherit_fallbacks and preference.get('fallbacks'):
        options['fallbacks'] = preference['fallbacks']
    if android_build: options['android_build'] = android_build
    if native_change: options['native_change'] = native_change
    if qc: options['qc'] = qc
    if contract: options['contract'] = contract
    if _delivery_scope: options['delivery_scope'] = _delivery_scope  # narrows authority; never widens it
    payload = dict(schema_version=1,project_id=ledger.project_id,project_path=ledger.project_path,
                   spec_id='GOAL',spec_revision=content_hash(goal),spec_text=goal,title=goal[:200],
                   goal=goal,owned_execution=options,grant=grant)
    if root_binding is not None:
        payload['plan_binding'] = root_binding
    if not prior or 'solution_required' in json.loads(prior['payload']):
        # A work contract carries the user's authorization itself; a bound SOL is still honoured when given.
        payload['solution_required']=mode not in ('audit','work')
        payload['solution_id']=solution_id;payload['solution_revision']=solution_revision
    revision = content_hash(payload)
    with ledger.transaction(write=True) as conn:
        if _delivery_parent:
            root_budget=ext.child_budget(ledger,conn,_delivery_parent,_delivery_node,_delivery_generation,
                                        goal,native_change,solution_id,solution_revision)
            if max_calls>root_budget['limits']['max_calls']:
                raise LedgerError('Child call cap exceeds root grant.')
        old = conn.execute('SELECT * FROM tasks WHERE project_id=? AND request_key=?',
                           (ledger.project_id,request_key)).fetchone()
        if old:
            if old['revision'] != revision:
                raise LedgerError('Submission key already has a different goal, authority or budget.')
            if _then is not None: _then(conn, old['id'])
            return ledger._task_view(conn,old)
        if root_binding is not None:
            bound_state = plan_binding.validate(ledger, conn, root_binding)
            from .budget_core import ensure_plan_group
            plan_budget = ensure_plan_group(ledger, conn, root_binding['selector'])
            if plan_budget and (max_calls > plan_budget['max_calls'] or max_seconds > (dt.datetime.fromisoformat(plan_budget['deadline']) - dt.datetime.fromisoformat(plan_binding.first_approval_at(ledger, conn, root_binding))).total_seconds()):
                raise LedgerError('Child grant exceeds the shared workflow root budget.')
            if plan_budget is None:
                # W10: a root without root-budget has no shared counter; its bound jobs together get at most its one approved budget.
                from .v2 import plan as plans
                approved_calls = plans.load(ledger, bound_state)[0]['budget']['max_calls']
                others = plan_binding.allocated(ledger, conn, bound_state)
                if max_calls + others > approved_calls:
                    raise LedgerError(f'Job grant refused: {max_calls} calls plus the {others} already granted to other jobs of root '
                                      f'{root_binding["selector"]} exceed its approved budget of {approved_calls} calls; a new job key is not '
                                      'a new budget (amend the plan and have the owner approve it).')
        else:
            plan_budget = None
        binding = ext.solution_binding(ledger,conn,mode,solution_id,solution_revision,_delivery_parent)
        task_id = 'TASK-'+uuid.uuid4().hex
        created = utcnow()
        deadline = (dt.datetime.fromisoformat(created)+dt.timedelta(seconds=max_seconds)).isoformat()
        if _delivery_parent: deadline=min(deadline,root_budget['deadline'])
        if plan_budget:
            deadline = min(deadline, plan_budget['deadline'], key=dt.datetime.fromisoformat)
            if dt.datetime.fromisoformat(deadline) <= dt.datetime.fromisoformat(created):
                raise LedgerError('The shared workflow root deadline is exhausted.')
        conn.execute('INSERT INTO tasks VALUES(?,?,?,?,?,?,?,?)',
                     (task_id,ledger.project_id,ledger.project_path,request_key,revision,canonical(payload),created,deadline))
        if binding:
            ext.bind(conn,task_id,binding,solution_id,solution_revision)
        if _delivery_parent:
            ext.link_child(conn,task_id,_delivery_parent,_delivery_node,_delivery_generation)
        ledger._event(conn,task_id,'task.submitted',{'revision':revision,'request_key':request_key,'mode':'owned_execution',
                                                  **({'plan_binding': root_binding} if root_binding is not None else {})})
        if _then is not None: _then(conn, task_id)
        return ledger._task_view(conn,ledger._task(conn,task_id))
