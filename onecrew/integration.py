"""Prepare a verified local review branch without touching the user's checkout/index."""
import json
import os
import re
import subprocess
import uuid

from .ledger import LedgerError
from .workflow import task_lock, verify


class Integration:
    def __init__(self, workflow):
        self.workflow = workflow
        self.ledger = workflow.ledger
        self.store = workflow.store

    def git(self, *args, stdin=None, index=None, allow_failure=False):
        environment = {k: v for k, v in os.environ.items() if not k.upper().startswith('GIT_')}
        if index:
            environment['GIT_INDEX_FILE'] = str(index)
        hooks = self.ledger.state_root/'empty-hooks'
        hooks.mkdir(parents=True, exist_ok=True)
        command = ['git', '--literal-pathspecs', '-C', str(self.ledger.project),
                   '-c', 'user.name=OneCrew', '-c', 'user.email=onecrew@localhost',
                   '-c', 'core.hooksPath=' + str(hooks), '-c', 'commit.gpgSign=false',
                   '-c', 'core.fsmonitor=false', *args]
        result = subprocess.run(command, input=stdin, env=environment, capture_output=True, timeout=20)
        if result.returncode and not allow_failure:
            raise LedgerError('Git review-branch operation failed: ' + result.stderr.decode('utf-8', errors='replace')[:400])
        return result.stdout if result.returncode == 0 else None

    def tree(self, manifest, parent, index):
        self.git('read-tree', parent, index=index)
        for path, item in manifest['files'].items():
            if item['working'] is None:
                self.git('update-index', '--force-remove', '--', path, index=index)
            else:
                blob = self.git('hash-object', '--no-filters', '-w', '--stdin', stdin=self.store.read_blob(item['working'])).decode().strip()
                mode = next((r['mode'] for r in item['index'] if r['stage'] == 0), '100644')
                self.git('update-index', '--add', '--cacheinfo', mode, blob, path, index=index)
        return self.git('write-tree', index=index).decode().strip()

    def inspect_tree(self, tree, candidate):
        # Reconstruct gate inputs from the actual Git candidate, not an earlier workspace.
        manifest = self.store.load(candidate)
        for path, item in manifest['files'].items():
            entry = self.git('ls-tree', '-z', tree, '--', path)
            data = self.git('cat-file', 'blob', tree + ':' + path) if entry else None
            actual = self.store.blob(data) if data is not None else None
            if actual != item['working']:
                raise LedgerError('Git candidate differs from the published output snapshot.')
        manifest['git_candidate_tree'] = tree
        return self.store.save(manifest)

    def branch(self, task_id, revision, name):
        if not isinstance(name, str) or not re.fullmatch('[A-Za-z0-9][A-Za-z0-9_-]{0,63}', name):
            raise LedgerError('Review branch name must be a short alphanumeric/hyphen/underscore label.')
        ref = 'refs/heads/onecrew/' + name
        key = 'branch:' + name
        with task_lock(self.ledger, task_id):
            _, state = self.workflow.state(task_id)
            if not state or state['snapshot'] != revision or state['verification'] != 'passed':
                raise LedgerError('Only the current verified snapshot can produce a review branch.')
            if any(a['status'] != 'settled' for a in self.workflow.control.status(task_id)['attempts']):
                raise LedgerError('Reconcile every writer before integration.')
            with self.ledger.transaction() as conn:
                existing = conn.execute('SELECT * FROM actions WHERE task_id=? AND request_key=?', (task_id, key)).fetchone()
                existing = dict(existing) if existing else None
            if existing:
                payload = json.loads(existing['payload'])
                if payload['snapshot'] != revision:
                    raise LedgerError('Branch action is already bound to another snapshot.')
                if existing['status'] == 'proposed':
                    self.workflow.control.authorize_action(existing['id'], existing['revision'])
                    existing['status'] = 'authorized'
                return self._apply(existing)
            from .amendment import profile_for
            profile = profile_for(state, self.workflow.control.status(task_id))
            base = self.store.load(state['base'])
            candidate = self.store.load(revision)
            if not base['head']:
                raise LedgerError('Review branch needs an existing Git HEAD; use work export for a non-Git project.')
            self._check_source(base, state['base'], profile)
            if self.git('show-ref', '--verify', '--hash', ref, allow_failure=True):
                raise LedgerError('Review branch already exists; choose a fresh name. It will not be overwritten.')
            directory = self.ledger.state_root/'integration'/uuid.uuid4().hex
            directory.mkdir(parents=True)
            index = directory/'index'
            baseline_tree = self.tree(base, base['head'], index)
            baseline_commit = self.git('commit-tree', baseline_tree, '-p', base['head'],
                                       '-m', f'OneCrew captured source bytes for {task_id} (includes user changes)').decode().strip()
            candidate_tree = self.tree(candidate, baseline_commit, index)
            gate_snapshot = self.inspect_tree(candidate_tree, revision)
            from .sandbox_gate import task_guard
            checks = verify(self.store, gate_snapshot, profile, guard=task_guard(self.workflow.control, task_id))
            if not checks['passed']:
                raise LedgerError('Actual Git candidate failed configured checks; branch not published.')
            commit = self.git('commit-tree', candidate_tree, '-p', baseline_commit,
                              '-m', f'OneCrew artifacts for {task_id}\n\nOutput: {revision}').decode().strip()
            self._check_source(base, state['base'], profile)
            payload = {'snapshot': revision, 'ref': ref, 'commit': commit, 'tree': candidate_tree,
                       'base_head': base['head'], 'baseline_commit': baseline_commit,
                       'gate_snapshot': gate_snapshot, 'checks': checks, 'source_snapshot': state['base']}
            action = self.workflow.control.propose_action(task_id, key, payload)
            self.workflow.control.authorize_action(action['id'], action['revision'])
            return self._apply(action)

    def _check_source(self, base, revision, profile):
        head = self.git('rev-parse', '--verify', 'HEAD').decode().strip()
        if head != base['head'] or self.store.capture(self.ledger.project, profile['context']) != revision:
            raise LedgerError('Source HEAD/index/working bytes changed since capture; rebase and verify a new task before integration.')

    def _apply(self, action):
        def observe(payload):
            target = self.git('show-ref', '--verify', '--hash', payload['ref'], allow_failure=True)
            return {'verified': target is not None and target.decode().strip() == payload['commit'],
                    'ref': payload['ref'], 'commit': payload['commit'], 'tree': payload['tree'],
                    'source_modified': False, 'gate_snapshot': payload['gate_snapshot']}

        if action['status'] in ('unknown', 'executing'):
            receipt = self.workflow.control.reconcile_action(action['id'], action['revision'], observe)
        elif action['status'] == 'verified':
            receipt = json.loads(action['receipt'])
            if not observe(json.loads(action['payload']))['verified']:
                raise LedgerError('Previously delivered branch has moved; stored receipt is stale.')
        else:
            def apply(payload):
                # No hooks, checkout, filters, source/index changes or remote push.
                self.git('update-ref', payload['ref'], payload['commit'], '0' * len(payload['commit']))
                return observe(payload)
            receipt = self.workflow.control.execute_action(action['id'], apply)
        return {'action': action['id'], 'revision': action['revision'], 'receipt': receipt}
