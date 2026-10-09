"""Conservative whole-file three-way integration; verify before local ref CAS."""
import json
import re
import uuid

from .amendment import profile_for
from .integration import Integration
from .ledger import LedgerError, content_hash
from .snapshots import MAX_FILE
from .workflow import task_lock, verify


def available_target(integration, ref, expected):
    records = integration.git('worktree', 'list', '--porcelain', '-z').split(b'\0')
    if ('branch '+ref).encode() in records:
        raise LedgerError('Target is checked out in a worktree; choose an un-checked-out local branch.')
    actual = integration.git('show-ref', '--verify', '--hash', ref, allow_failure=True)
    if actual is None or actual.decode().strip() != expected:
        raise LedgerError('Target base changed; review the new base and rebuild/retest before updating it.')


def entry(integration, tree, path):
    line = integration.git('ls-tree', '-z', tree, '--', path)
    if not line:
        return (None, None)
    meta, name = line.rstrip(b'\0').split(b'\t', 1)
    mode, kind, oid = meta.decode('ascii').split()
    if kind != 'blob' or mode not in ('100644', '100755') or name.decode() != path:
        raise LedgerError('Merge context contains a link, submodule or unsupported tree entry.')
    if int(integration.git('cat-file', '-s', oid)) > MAX_FILE:
        raise LedgerError('Merge input exceeds snapshot file limit.')
    data = integration.git('cat-file', 'blob', oid)
    return mode, integration.store.blob(data)


def merge(workflow, task_id, revision, target, expected):
    integration = Integration(workflow)
    if not isinstance(target, str) or not target.startswith('refs/heads/') or integration.git('check-ref-format', target, allow_failure=True) is None:
        raise LedgerError('Target must be a full local refs/heads/... name.')
    if not isinstance(expected, str) or not re.fullmatch(r'(?:[0-9a-f]{40}|[0-9a-f]{64})', expected):
        raise LedgerError('Expected target must be an exact commit hash.')
    key = 'merge:'+content_hash({'target':target,'base':expected,'snapshot':revision})
    with task_lock(workflow.ledger, task_id):
        _, state = workflow.state(task_id)
        control = workflow.control.status(task_id)
        if (not state or state['snapshot'] != revision or state['phase'] != 'completed'
                or state['verification'] != 'passed' or control['cancel_requested']):
            raise LedgerError('Merge requires the current completed, verified, non-cancelled candidate.')
        if any(a['status'] != 'settled' for a in control['attempts']):
            raise LedgerError('Stop/reconcile all writers before merging.')
        with workflow.ledger.transaction() as conn:
            row = conn.execute('SELECT * FROM actions WHERE task_id=? AND request_key=?', (task_id,key)).fetchone()
        if row:
            action = dict(row)
            if action['status'] == 'proposed':
                workflow.control.authorize_action(action['id'],action['revision'])
                action['status'] = 'authorized'
            return integration._apply(action)
        profile = profile_for(state,control)
        base = workflow.store.load(state['base'])
        if not base['head']:
            raise LedgerError('Integration requires a captured Git base.')
        integration._check_source(base,state['base'],profile)
        available_target(integration,target,expected)
        if integration.git('rev-parse','--verify',expected+'^{commit}').decode().strip() != expected:
            raise LedgerError('Expected target is not a commit.')
        if integration.git('merge-base','--is-ancestor',base['head'],expected,allow_failure=True) is None:
            raise LedgerError('Target does not descend from the captured Git base; explicit rebase is required.')
        available_target(integration,target,expected)
        manifest = workflow.store.load(revision)
        conflicts = []
        for path, item in manifest['files'].items():
            ancestor = entry(integration,base['head'],path)
            theirs = entry(integration,expected,path)
            mode = next((r['mode'] for r in item['index'] if r['stage'] == 0),'100644')
            ours = (mode,item['working']) if item['working'] else (None,None)
            merged = ours if theirs == ancestor or theirs == ours else theirs if ours == ancestor else None
            if merged is None:
                conflicts.append(path)
                continue
            item['working'] = merged[1]
            item['index'] = [{'stage':0,'mode':merged[0],'blob':merged[1]}] if merged[1] else []
        if conflicts:
            with workflow.ledger.transaction(write=True) as conn:
                workflow.ledger._event(conn,task_id,'integration.conflict',{
                    'snapshot':revision,'target':target,'expected':expected,'paths':conflicts,
                    'resolution':'Explicit new source/spec candidate required; no automatic overwrite.'})
            raise LedgerError('Both sides changed these files differently: '+', '.join(conflicts))
        for check in profile['checks']:
            if check['kind'] == 'container_test' and manifest['files'][check['path']]['working'] != base['files'][check['path']]['working']:
                raise LedgerError('Target changed the sealed test entry; approve a new gate/source revision first.')
        manifest.update(parent=revision, head=expected, integration_target=target)
        merged_snapshot = workflow.store.save(manifest)
        directory = workflow.ledger.state_root/'integration'/uuid.uuid4().hex
        directory.mkdir(parents=True)
        index = directory/'index'
        merged_tree = integration.tree(manifest,expected,index)
        gate_snapshot = integration.inspect_tree(merged_tree,merged_snapshot)
        from .sandbox_gate import task_guard
        checks = verify(workflow.store,gate_snapshot,profile,guard=task_guard(workflow.control,task_id))
        if not checks['passed']:
            with workflow.ledger.transaction(write=True) as conn:
                workflow.ledger._event(conn,task_id,'integration.failed',{
                    'snapshot':revision,'target':target,'expected':expected,'gate_snapshot':gate_snapshot,'checks':checks})
            raise LedgerError('Merged Git candidate failed configured checks; target unchanged.')
        # Make source history explicit without checking it out or invoking hooks/drivers.
        source_tree = integration.tree(workflow.store.load(revision),base['head'],index)
        source_commit = integration.git('commit-tree',source_tree,'-p',base['head'],
            '-m',f'OneCrew source candidate {task_id}\nOutput: {revision}').decode().strip()
        commit = integration.git('commit-tree',merged_tree,'-p',expected,'-p',source_commit,
            '-m',f'OneCrew verified integration {task_id}\nOutput: {revision}').decode().strip()
        integration._check_source(base,state['base'],profile)
        available_target(integration,target,expected)
        payload = {'snapshot':revision,'ref':target,'expected_ref':expected,'commit':commit,'tree':merged_tree,
                   'base_head':base['head'],'source_snapshot':state['base'],'source_commit':source_commit,
                   'gate_snapshot':gate_snapshot,'checks':checks,'integration_mode':'whole-file-three-way'}
        action = workflow.control.propose_action(task_id,key,payload)
        workflow.control.authorize_action(action['id'],action['revision'])
        return integration._apply(action)
