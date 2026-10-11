"""Natural goal intake; no source spec/profile or preselected evidence required."""
import datetime as dt
import json
import re
import uuid

from .ledger import LedgerError, canonical, content_hash, key_field, text_field, utcnow, validate_grant


def submit(ledger, goal, request_key, *, mode='audit', provider=None, model=None,
           max_calls=None, max_seconds=None, image=None, branch=None, remote=None, android_build=None, native_change=None,
           solution_id=None, solution_revision=None,
           _delivery_parent=None, _delivery_node=None, _delivery_generation=0):
    goal = text_field(goal, 'goal', 12000)
    key_field(request_key)
    # Idempotent replay retains the original choice after operator preferences change.
    with ledger.transaction() as conn:
        prior=conn.execute('SELECT payload FROM tasks WHERE project_id=? AND request_key=?',
                          (ledger.project_id,request_key)).fetchone() if conn else None
    from .model_preferences import resolve, read
    previous=json.loads(prior['payload']).get('owned_execution') if prior else None
    from .budget_policy import DEFAULT_CALLS, DEFAULT_SECONDS, POLICY
    prior_limits=json.loads(prior['payload'])['grant']['limits'] if prior else {}
    if max_calls is None: max_calls=prior_limits.get('max_calls',DEFAULT_CALLS)
    if max_seconds is None: max_seconds=prior_limits.get('max_seconds',DEFAULT_SECONDS)
    # An explicit provider/model pins this job; only default intake inherits the chain.
    inherit_fallbacks = provider is None and model is None
    preference = previous or read(ledger)
    provider,model=resolve(ledger,provider,model,preference)
    if mode not in ('audit','change','delivery','branch') or provider not in ('codex','claude','kiro'):
        raise LedgerError('Unsupported job mode or provider.')
    text_field(model, 'model', 120)
    if image is not None and not re.fullmatch(r'sha256:[a-f0-9]{64}',image):
        raise LedgerError('Image must be a locally installed immutable sha256 image ID.')
    if native_change is not None:
        from .native_change import validate
        native_change=validate(native_change)
        if mode!='change' or provider!='claude' or branch or remote or image:
            raise LedgerError('Native change requires Claude change mode without publication/container options.')
    if mode == 'change' and not image and not native_change:
        raise LedgerError('Change jobs require an authorized sandbox image.')
    if mode in ('delivery','branch') or branch or remote:
        if mode=='audit': raise LedgerError('Audit jobs cannot publish Git changes.')
        if not branch or not re.fullmatch(r'onecrew/[A-Za-z0-9][A-Za-z0-9._/-]{0,100}', branch) or '..' in branch:
            raise LedgerError('Delivery needs an explicit new onecrew/... branch.')
        if mode=='branch' and remote: raise LedgerError('Historical branch mode is local only.')
        if mode!='branch' and (not remote or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,60}',remote)):
            raise LedgerError('Delivery needs an explicit existing Git remote name.')
    from .owned_recipes import validate
    android_build = validate(android_build)
    if android_build and mode != 'branch': raise LedgerError('Historical Android recipe requires branch mode.')
    permissions = ['discover','report'] + (['candidate.write','sandbox.test'] if mode == 'change' else [])
    if android_build: permissions += ['android.build']
    if native_change: permissions += ['native.test','workspace.apply']
    if native_change and native_change.get('apk_build'): permissions += ['android.build']
    if branch and remote:
        permissions += ['git.branch','git.commit','git.push']
    elif mode=='branch': permissions += ['git.branch']
    grant = validate_grant({'schema_version':1,'permissions':permissions,
                           'limits':{'max_calls':max_calls,'max_seconds':max_seconds},'source':'local operator: job submit'})
    options = dict(mode=mode,provider=provider,model=model,image=image,branch=branch,remote=remote)
    if previous and 'budget_policy' in previous:
        options['budget_policy']=previous['budget_policy']
        options['budget_advice']=previous['budget_advice']
    elif not prior:
        from .budget_policy import recommend
        options['budget_policy']=dict(POLICY)
        options['budget_advice']=recommend(ledger,goal,mode,provider,model)
    if previous and 'fallbacks' in previous:
        options['fallbacks'] = previous['fallbacks']
    elif not previous and inherit_fallbacks and preference.get('fallbacks'):
        options['fallbacks'] = preference['fallbacks']
    if android_build: options['android_build'] = android_build
    if native_change: options['native_change'] = native_change
    payload = dict(schema_version=1,project_id=ledger.project_id,project_path=ledger.project_path,
                   spec_id='GOAL',spec_revision=content_hash(goal),spec_text=goal,title=goal[:200],
                   goal=goal,owned_execution=options,grant=grant)
    if not prior or 'solution_required' in json.loads(prior['payload']):
        payload['solution_required']=mode!='audit'
        payload['solution_id']=solution_id;payload['solution_revision']=solution_revision
    revision = content_hash(payload)
    with ledger.transaction(write=True) as conn:
        if _delivery_parent:
            from .delivery_store import child_authority
            root_budget=child_authority(ledger,conn,_delivery_parent,_delivery_node,_delivery_generation,
                                       goal,native_change,solution_id,solution_revision)
            if max_calls>root_budget['limits']['max_calls']:
                raise LedgerError('Child call cap exceeds root grant.')
        old = conn.execute('SELECT * FROM tasks WHERE project_id=? AND request_key=?',
                           (ledger.project_id,request_key)).fetchone()
        if old:
            if old['revision'] != revision:
                raise LedgerError('Submission key already has a different goal, authority or budget.')
            return ledger._task_view(conn,old)
        binding=None
        if mode!='audit' or solution_id:
            from .conversations import ensure, approved
            ensure(conn)
            if not solution_id or not solution_revision:raise LedgerError('Review/approve a solution first; pass solution_id and solution_revision for implementation.')
            sol,decision=approved(ledger,conn,solution_id,solution_revision)
            # One feature contract has one live writer. Parallel implementation uses
            # the existing sealed DAG with explicit ownership/integration checks.
            if mode!='audit':
                peers=conn.execute('SELECT b.task_id FROM solution_bindings b JOIN tasks t ON t.id=b.task_id WHERE b.solution=? AND json_extract(t.payload,\'$.owned_execution.mode\')!=\'audit\'',(solution_id,)).fetchall()
                for peer in peers:
                    if peer['task_id']==_delivery_parent: continue
                    if conn.execute("SELECT 1 FROM events WHERE task_id=? AND kind='solution.stopped'",(peer['task_id'],)).fetchone():continue
                    checkpoint=conn.execute("SELECT json_extract(payload,'$.phase') FROM events WHERE task_id=? AND kind='workflow.checkpoint' ORDER BY seq DESC LIMIT 1",(peer['task_id'],)).fetchone()
                    if not checkpoint or checkpoint[0] not in ('completed','failed','cancelled'):
                        raise LedgerError('This solution already has a live task; continue it instead of creating parallel writers.')
            binding=(sol,decision)
        task_id = 'TASK-'+uuid.uuid4().hex
        created = utcnow()
        deadline = (dt.datetime.fromisoformat(created)+dt.timedelta(seconds=max_seconds)).isoformat()
        if _delivery_parent: deadline=min(deadline,root_budget['deadline'])
        conn.execute('INSERT INTO tasks VALUES(?,?,?,?,?,?,?,?)',
                     (task_id,ledger.project_id,ledger.project_path,request_key,revision,canonical(payload),created,deadline))
        if binding:
            sol,decision=binding
            conn.execute('INSERT INTO solution_bindings VALUES(?,?,?,?,?)',(task_id,sol['conversation'],solution_id,solution_revision,decision['id']))
        if _delivery_parent:
            conn.execute('INSERT INTO delivery_children VALUES(?,?,?,?)',
                         (task_id,_delivery_parent,_delivery_node,_delivery_generation))
        ledger._event(conn,task_id,'task.submitted',{'revision':revision,'request_key':request_key,'mode':'owned_execution'})
        return ledger._task_view(conn,ledger._task(conn,task_id))
