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
    if type(limit) is not int or not 1<=limit<=200: raise LedgerError('limit must be 1-200.')
    with ledger.transaction() as conn:
        if conn is None: return []
        rows=conn.execute("SELECT e.seq,e.payload FROM events e JOIN tasks t ON t.id=e.task_id WHERE t.project_id=? AND e.kind='learning.outcome' ORDER BY e.seq DESC LIMIT ?",(ledger.project_id,limit)).fetchall()
    return [{'event':r['seq'],**json.loads(r['payload'])} for r in rows]


def recommend(ledger, goal, mode, provider, model, history=None):
    """Evidence-only budget advice. `history` is the outcomes reader (v1 passes learning.outcomes, so patching it there still works)."""
    # Exact goal, same project/mode/provider/model. Similar wording alone is not
    # sufficient evidence to reduce a grant. Latest outcome wins per task.
    latest = {}
    for row in (history or outcomes)(ledger, 200): latest.setdefault(row['task'], row)
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
           _delivery_parent=None, _delivery_node=None, _delivery_generation=0, _delivery_scope=None, extension=None):
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
    # Idempotent replay retains the original choice after operator preferences change.
    with ledger.transaction() as conn:
        prior=conn.execute('SELECT payload FROM tasks WHERE project_id=? AND request_key=?',
                          (ledger.project_id,request_key)).fetchone() if conn else None
    from .model_preferences import resolve, read
    previous=json.loads(prior['payload']).get('owned_execution') if prior else None
    prior_limits=json.loads(prior['payload'])['grant']['limits'] if prior else {}
    if max_calls is None: max_calls=prior_limits.get('max_calls',DEFAULT_CALLS)
    if max_seconds is None: max_seconds=prior_limits.get('max_seconds',DEFAULT_SECONDS)
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
            return ledger._task_view(conn,old)
        binding = ext.solution_binding(ledger,conn,mode,solution_id,solution_revision,_delivery_parent)
        task_id = 'TASK-'+uuid.uuid4().hex
        created = utcnow()
        deadline = (dt.datetime.fromisoformat(created)+dt.timedelta(seconds=max_seconds)).isoformat()
        if _delivery_parent: deadline=min(deadline,root_budget['deadline'])
        conn.execute('INSERT INTO tasks VALUES(?,?,?,?,?,?,?,?)',
                     (task_id,ledger.project_id,ledger.project_path,request_key,revision,canonical(payload),created,deadline))
        if binding:
            ext.bind(conn,task_id,binding,solution_id,solution_revision)
        if _delivery_parent:
            ext.link_child(conn,task_id,_delivery_parent,_delivery_node,_delivery_generation)
        ledger._event(conn,task_id,'task.submitted',{'revision':revision,'request_key':request_key,'mode':'owned_execution'})
        return ledger._task_view(conn,ledger._task(conn,task_id))
