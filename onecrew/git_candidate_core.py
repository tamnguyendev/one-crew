"""Shared v1 Git object candidates; no checkout/index/ref or remote mutation."""
import os
import subprocess

from .ledger import LedgerError


class GitCandidate:
    def __init__(self, ledger, store):
        self.ledger, self.store = ledger, store

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
