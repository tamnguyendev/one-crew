"""Natural goal intake; no source spec/profile or preselected evidence required."""
import datetime as dt
import json
import re
import uuid

from .ledger import LedgerError, canonical, content_hash, key_field, text_field, utcnow, validate_grant


def submit(ledger, goal, request_key, *, mode='audit', provider='codex', model='gpt-6-luna',
           max_calls=20, max_seconds=1200, image=None, branch=None, remote=None):
    goal = text_field(goal, 'goal', 12000)
    key_field(request_key)
    if mode not in ('audit','change','delivery','branch') or provider not in ('codex','claude','kiro'):
        raise LedgerError('Unsupported job mode or provider.')
    text_field(model, 'model', 120)
    if image is not None and not re.fullmatch(r'sha256:[a-f0-9]{64}',image):
        raise LedgerError('Image must be a locally installed immutable sha256 image ID.')
    if mode == 'change' and not image:
        raise LedgerError('Change jobs require an authorized sandbox image.')
    if mode in ('delivery','branch') or branch or remote:
        if mode=='audit': raise LedgerError('Audit jobs cannot publish Git changes.')
        if not branch or not re.fullmatch(r'onecrew/[A-Za-z0-9][A-Za-z0-9._/-]{0,100}', branch) or '..' in branch:
            raise LedgerError('Delivery needs an explicit new onecrew/... branch.')
        if mode=='branch' and remote: raise LedgerError('Historical branch mode is local only.')
        if mode!='branch' and (not remote or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,60}',remote)):
            raise LedgerError('Delivery needs an explicit existing Git remote name.')
    permissions = ['discover','report'] + (['candidate.write','sandbox.test'] if mode == 'change' else [])
    if branch and remote:
        permissions += ['git.branch','git.commit','git.push']
    elif mode=='branch': permissions += ['git.branch']
    grant = validate_grant({'schema_version':1,'permissions':permissions,
                           'limits':{'max_calls':max_calls,'max_seconds':max_seconds},'source':'local operator: job submit'})
    options = dict(mode=mode,provider=provider,model=model,image=image,branch=branch,remote=remote)
    payload = dict(schema_version=1,project_id=ledger.project_id,project_path=ledger.project_path,
                   spec_id='GOAL',spec_revision=content_hash(goal),spec_text=goal,title=goal[:200],
                   goal=goal,owned_execution=options,grant=grant)
    revision = content_hash(payload)
    with ledger.transaction(write=True) as conn:
        old = conn.execute('SELECT * FROM tasks WHERE project_id=? AND request_key=?',
                           (ledger.project_id,request_key)).fetchone()
        if old:
            if old['revision'] != revision:
                raise LedgerError('Submission key already has a different goal, authority or budget.')
            return ledger._task_view(conn,old)
        task_id = 'TASK-'+uuid.uuid4().hex
        created = utcnow()
        deadline = (dt.datetime.fromisoformat(created)+dt.timedelta(seconds=max_seconds)).isoformat()
        conn.execute('INSERT INTO tasks VALUES(?,?,?,?,?,?,?,?)',
                     (task_id,ledger.project_id,ledger.project_path,request_key,revision,canonical(payload),created,deadline))
        ledger._event(conn,task_id,'task.submitted',{'revision':revision,'request_key':request_key,'mode':'owned_execution'})
        return ledger._task_view(conn,ledger._task(conn,task_id))
