"""Verify an explicit multi-repository commit vector; never update refs atomically."""
from contextlib import ExitStack
import json
import re

from .amendment import profile_for
from .goal_budget import group
from .integration import Integration
from .ledger import Ledger, LedgerError, content_hash, exact_fields, text_field, utcnow
from .workflow import Workflow, task_lock, validate_profile, verify


def check_refs(items):
    for item in items:
        actual = item['integration'].git('show-ref','--verify','--hash',item['ref'],allow_failure=True)
        if actual is None or actual.decode().strip() != item['commit']:
            raise LedgerError('Commit vector is stale: '+item['alias']+' ref moved.')


def verify_vector(workflow, owner_id, group_revision, recipe):
    exact_fields(recipe,('members','check'),'Commit vector recipe')
    members = recipe['members']
    if not isinstance(members,list) or not 2 <= len(members) <= 20:
        raise LedgerError('Commit vector requires 2-20 explicit members.')
    ids, aliases, items = set(), set(), []
    for row in members:
        exact_fields(row,('task_id','project','alias','snapshot','ref','commit'),'Vector member')
        for field in ('task_id','project','snapshot','ref','commit'):
            text_field(row[field],field,1000)
        if not isinstance(row['alias'],str) or not re.fullmatch('[A-Za-z][A-Za-z0-9_-]{0,23}',row['alias']):
            raise LedgerError('Vector alias must be a short path-safe label.')
        if row['task_id'] in ids or row['alias'].lower() in aliases:
            raise LedgerError('Duplicate vector task or alias.')
        ids.add(row['task_id'])
        aliases.add(row['alias'].lower())
        member = Workflow(Ledger(row['project'],workflow.ledger.state_root))
        items.append(dict(row,workflow=member,integration=Integration(member)))
    if owner_id not in ids:
        raise LedgerError('Owner must belong to the commit vector.')
    digest = content_hash({'group_revision':group_revision,'recipe':recipe})
    with ExitStack() as stack:
        for item in sorted(items,key=lambda r:r['task_id']):
            stack.enter_context(task_lock(item['workflow'].ledger,item['task_id']))
        with workflow.ledger.transaction() as conn:
            workflow.ledger._task(conn,owner_id)
            shared = group(conn,owner_id)
            if not shared or shared['owner_task_id'] != owner_id or shared['revision'] != group_revision:
                raise LedgerError('Stale or missing owner goal budget revision.')
            if ids != {r['task_id'] for r in shared['members']}:
                raise LedgerError('Commit vector must cover exactly the approved goal members.')
            old = conn.execute("SELECT payload FROM events WHERE task_id=? AND kind='integration.vector' AND json_extract(payload,'$.revision')=? ORDER BY seq DESC LIMIT 1",(owner_id,digest)).fetchone()
            previous = json.loads(old['payload']) if old else None
        files, owned, commits = {}, [], []
        owner_entry = None
        for item in items:
            member, task_id = item['workflow'],item['task_id']
            _, state = member.state(task_id)
            control = member.control.status(task_id)
            if (not state or state['snapshot'] != item['snapshot'] or state['phase'] != 'completed'
                    or state['verification'] != 'passed' or control['cancel_requested']
                    or any(a['status'] != 'settled' for a in control['attempts'])):
                raise LedgerError('Every vector member must be current, verified, settled and non-cancelled.')
            with member.ledger.transaction() as conn:
                rows = conn.execute("SELECT payload FROM actions WHERE task_id=? AND status='verified'",(task_id,)).fetchall()
            action = next((p for p in (json.loads(r['payload']) for r in rows)
                           if p.get('commit') == item['commit'] and p.get('ref') == item['ref']
                           and p.get('snapshot') == item['snapshot'] and p.get('gate_snapshot')),None)
            if not action:
                raise LedgerError('Vector members need a verified OneCrew Git delivery receipt matching snapshot/ref/commit.')
            check_refs([item])
            tree = item['integration'].git('rev-parse','--verify',item['commit']+'^{tree}').decode().strip()
            actual_snapshot = item['integration'].inspect_tree(tree,action['gate_snapshot'])
            manifest = member.store.load(actual_snapshot)
            profile = profile_for(state,control)
            for path,value in manifest['files'].items():
                files[item['alias']+'/'+path] = value
            owned += [item['alias']+'/'+path for path in profile['owned']]
            commits.append({key:item[key] for key in ('task_id','project','alias','snapshot','ref','commit')} | {'tree':tree,'gate_snapshot':actual_snapshot})
            if task_id == owner_id:
                owner_entry = (item,profile,member.store.load(state['base']))
        # Compatibility test code must already belong to the owner's sealed,
        # read-only context. The new recipe selects only its immutable image/argv.
        check = recipe['check']
        if not isinstance(check,dict) or check.get('kind') != 'container_test':
            raise LedgerError('Cross-repository compatibility requires a container_test gate.')
        owner,owner_profile,owner_base = owner_entry
        prefix = owner['alias']+'/'
        path = check.get('path','')
        original_path = path[len(prefix):] if isinstance(path,str) and path.startswith(prefix) else None
        if original_path not in owner_profile['context'] or original_path in owner_profile['owned']:
            raise LedgerError('Compatibility test must be sealed read-only context of the goal owner.')
        if files[path]['working'] is None or files[path]['working'] != owner_base['files'][original_path]['working']:
            raise LedgerError('Compatibility test bytes changed since owner approval.')
        profile = validate_profile({'version':1,'context':sorted(files),'owned':sorted(owned),
            'acceptance':[{'id':'AC-VECTOR','description':'The declared repository commits are compatible.'}],
            'checks':[check],'max_repairs':0,'provider':'codex','model':'verification-only','step_seconds':300})
        check_refs(items)
        if previous and previous['status'] == 'passed':
            return previous
        snapshot = workflow.store.save({'version':1,'parent':None,'head':None,'source':'OneCrew commit vector',
                                        'files':files,'commit_vector':commits})
        from .sandbox_gate import task_guard
        def guard():
            for item in items:
                task_guard(item['workflow'].control,item['task_id'])()
        checks = verify(workflow.store,snapshot,profile,guard=guard)
        check_refs(items)  # No receipt can certify a ref set that moved during the gate.
        guard()
        receipt = {'revision':digest,'goal_revision':group_revision,'commit_vector':commits,
                   'snapshot':snapshot,'status':'passed' if checks['passed'] else 'failed',
                   'checks':checks,'observed_at':utcnow(),'model_calls':0,'refs_updated':False,
                   'acceptance':'pending','atomic_cross_repo_commit':False}
        with workflow.ledger.transaction(write=True) as conn:
            workflow.ledger._event(conn,owner_id,'integration.vector',receipt)
        return receipt
