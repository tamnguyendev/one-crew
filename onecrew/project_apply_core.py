"""Shared v1 project apply: durable Control intent, Git-blob CAS and rollback.

Callers establish authority and deliverable scope before calling. The optional
guard adds the common workflow's current-root fence; the legacy caller has none.
"""
import json

from .ledger import LedgerError, canonical, content_hash
from .snapshots import durable_write, safe_file
from .work_contract import git
from .effects_core import EffectUnknown


def clean_blob(repo, path, name):
    return git(repo, 'hash-object', '--path=' + name, str(path)).decode().strip()


def apply(ledger, control, task_id, repo, root, base, candidate, files, earlier, backup, *, guard=None):
    payload = {'kind': 'apply', 'repository': str(repo), 'base': base, 'candidate': candidate, 'files': files}

    def observe(value):
        ok = all(((repo / f['path']).is_file() and clean_blob(repo, repo / f['path'], f['path']) == f['blob'])
                 if f['blob'] else not (repo / f['path']).exists() for f in value['files'])
        return dict(value, verified=ok, rollback=str(backup))

    def untouched(value):
        if guard: guard()
        for f in value['files']:
            target = safe_file(repo, f['path'])
            original = git(repo, 'rev-parse', '--verify', '--quiet', base + ':' + f['path'], allow_failure=True)
            current = clean_blob(repo, target, f['path']) if target.is_file() else None
            allowed = {original.decode().strip() if original else None}
            if f['path'] in earlier: allowed.add(earlier[f['path']])
            if current not in allowed:
                raise LedgerError('Project file changed since the pin; refusing to overwrite: ' + f['path'])
    key = 'work:apply:' + content_hash(payload)[:16]
    with ledger.transaction() as conn:
        prior = conn.execute('SELECT 1 FROM actions WHERE task_id=? AND request_key=?', (task_id, key)).fetchone()
    if not prior: untouched(payload)
    action = control.propose_action(task_id, key, payload)
    if action['status'] == 'proposed':
        control.authorize_action(action['id'], action['revision']); action['status'] = 'authorized'
    if action['status'] in ('unknown', 'executing'):
        receipt = control.reconcile_action(action['id'], action['revision'], observe)
    elif action['status'] == 'verified': receipt = json.loads(action['receipt'])
    else: receipt = None
    if receipt is None:
        def effect(value):
            untouched(value)
            backup.mkdir(parents=True, exist_ok=True)
            manifest_path = backup / 'manifest.json'
            manifest = json.loads(manifest_path.read_text()) if manifest_path.is_file() else {'base': base, 'files': {}}
            for f in value['files']:
                if guard: guard()
                target = safe_file(repo, f['path'])
                if f['path'] not in manifest['files']:
                    copy = content_hash(f['path'])[:16] + '.orig'
                    if target.is_file(): durable_write(backup / copy, target.read_bytes())
                    manifest['files'][f['path']] = {'original': copy if target.is_file() else None}
                if f['blob'] is None: target.unlink(missing_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True); durable_write(target, safe_file(root, f['path']).read_bytes())
            durable_write(manifest_path, canonical(manifest).encode())
            return observe(value)
        receipt = control.execute_action(action['id'], effect)
    if receipt.get('status') != 'verified':
        raise EffectUnknown('Apply effect unconfirmed; resume reconciles it without writing again.')
    return receipt
