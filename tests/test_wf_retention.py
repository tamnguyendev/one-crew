"""T31 E1-E5: real orphan trees, Git GC, process restart and scoped owner cleanup.

Temporary repositories only. The absent-pin counterexample actually loses an
orphan tree through GC; no missing-import failure is counted as a counterexample.
Push-hook assertions are covered by the hook suite at the integration boundary.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from onecrew.ledger import LedgerError
from onecrew.v2 import retention
from onecrew.v2.verifiers import command


class RetentionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='ocret-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.repo = self.root / 'project'
        self.repo.mkdir()
        command._git(self.repo, 'init', '-q')
        (self.repo / 'a.txt').write_text('baseline\n', encoding='utf-8')
        command._git(self.repo, 'add', 'a.txt')
        command._git(self.repo, '-c', 'user.name=test', '-c', 'user.email=test@example.invalid',
                     'commit', '-qm', 'baseline')
        self.ledger = SimpleNamespace(project=self.repo, state_root=self.root / 'state')
        self.owner = patch.dict(os.environ, {'ONECREW_ACTOR': 'owner'})
        self.owner.start()
        self.addCleanup(self.owner.stop)
        self.marker = os.environ.pop('CLAUDE_CODE_CHILD_SESSION', None)
        self.addCleanup(self._restore_marker)

    def _restore_marker(self):
        if self.marker is not None:
            os.environ['CLAUDE_CODE_CHILD_SESSION'] = self.marker

    def tree(self, text):
        (self.repo / 'a.txt').write_text(text, encoding='utf-8')
        tree = command.artifact_sha(self.repo)
        blob = command._git(self.repo, 'rev-parse', tree + ':a.txt')
        (self.repo / 'a.txt').write_text('baseline\n', encoding='utf-8')
        return tree, blob

    def gc(self):
        command._git(self.repo, 'reflog', 'expire', '--expire=now', '--all')
        command._git(self.repo, 'gc', '--prune=now')

    def test_e1_e2_orphan_trees_and_blobs_survive_gc_and_process_restart(self):
        first = self.tree('verdict evidence\n')
        second = self.tree('accepted evidence\n')
        refs = retention.pin_trees(self.ledger, 'alpha', first[0], second[0])
        self.assertEqual(len(refs), 2)
        self.gc()
        for oid in (*first, *second):
            command._git(self.repo, 'cat-file', '-e', oid)
        script = '''import json, sys
from types import SimpleNamespace
from onecrew.v2 import retention
from onecrew.v2.verifiers import command
ledger = SimpleNamespace(project=sys.argv[1], state_root=sys.argv[2])
refs = retention.list_refs(ledger, 'alpha')
for tree in refs.values():
    command._git(ledger.project, 'cat-file', '-e', tree + ':a.txt')
print(json.dumps(refs, sort_keys=True))
'''
        done = subprocess.run([sys.executable, '-c', script, str(self.repo), str(self.ledger.state_root)],
                              cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(json.loads(done.stdout), retention.list_refs(self.ledger, 'alpha'))

    def test_e3_counterexample_unpinned_orphan_is_really_pruned(self):
        tree, blob = self.tree('never pinned\n')
        self.gc()
        for oid in (tree, blob):
            with self.assertRaises(LedgerError):
                command._git(self.repo, 'cat-file', '-e', oid)

    def test_e4_pins_are_local_no_push_is_invoked_and_bare_remote_stays_empty(self):
        remote = self.root / 'remote.git'
        command._git(self.root, 'init', '--bare', '-q', str(remote))
        command._git(self.repo, 'remote', 'add', 'origin', str(remote))
        tree, _ = self.tree('local evidence\n')
        with patch.object(command, '_git', wraps=command._git) as observed:
            retention.pin_trees(self.ledger, 'alpha', tree)
            retention.list_refs(self.ledger, 'alpha')
        self.assertFalse(any('push' in call.args[1:] for call in observed.call_args_list))
        self.assertEqual(command._git(remote, 'for-each-ref', '--format=%(refname)'), '')

    def test_e5_repin_and_restarts_never_delete_refs(self):
        first, _ = self.tree('first\n')
        second, _ = self.tree('second\n')
        original = retention.pin_trees(self.ledger, 'alpha', first, first)
        self.assertEqual(len(original), 1)
        retention.pin_trees(self.ledger, 'alpha', second)
        before = retention.list_refs(self.ledger, 'alpha')
        retention.pin_trees(self.ledger, 'alpha', second, first)
        self.gc()
        restarted = SimpleNamespace(project=str(self.repo), state_root=str(self.ledger.state_root))
        self.assertEqual(retention.list_refs(restarted, 'alpha'), before)

    def test_e5_owner_cleanup_only_removes_exact_plan_and_state_root(self):
        tree, _ = self.tree('shared evidence\n')
        alpha = retention.pin_trees(self.ledger, 'alpha', tree)
        beta = retention.pin_trees(self.ledger, 'beta', tree)
        other = SimpleNamespace(project=self.repo, state_root=self.root / 'other-state')
        elsewhere = retention.pin_trees(other, 'alpha', tree)
        head = command._git(self.repo, 'rev-parse', 'HEAD')
        result = retention.cleanup(self.ledger, 'alpha', 'owner')
        self.assertEqual(result['removed'], alpha)
        self.assertEqual(retention.list_refs(self.ledger, 'alpha'), {})
        self.assertEqual(list(retention.list_refs(self.ledger, 'beta')), beta)
        self.assertEqual(list(retention.list_refs(other, 'alpha')), elsewhere)
        self.assertEqual(command._git(self.repo, 'rev-parse', 'HEAD'), head)
        self.assertEqual(retention.cleanup(self.ledger, 'alpha', 'owner')['removed'], [])

    def test_e5_cleanup_refuses_ai_actor_and_ai_session_without_mutation(self):
        tree, _ = self.tree('still required\n')
        retention.pin_trees(self.ledger, 'alpha', tree)
        before = retention.list_refs(self.ledger, 'alpha')
        with self.assertRaisesRegex(LedgerError, "owner's decision"):
            retention.cleanup(self.ledger, 'alpha', 'codex')
        with patch.dict(os.environ, {'ONECREW_ACTOR': 'codex'}):
            with self.assertRaisesRegex(LedgerError, 'AI cannot'):
                retention.cleanup(self.ledger, 'alpha', 'owner')
        with patch.dict(os.environ, {'CLAUDE_CODE_CHILD_SESSION': ''}):
            with self.assertRaisesRegex(LedgerError, 'AI tool session'):
                retention.cleanup(self.ledger, 'alpha', 'owner')
        self.assertEqual(retention.list_refs(self.ledger, 'alpha'), before)

    def test_e5_cleanup_does_not_remove_another_worktrees_pins_in_shared_git_store(self):
        linked = self.root / 'linked'
        command._git(self.repo, 'worktree', 'add', '--detach', '-q', str(linked), 'HEAD')
        tree, _ = self.tree('shared object database\n')
        other = SimpleNamespace(project=linked, state_root=self.ledger.state_root)
        retention.pin_trees(self.ledger, 'alpha', tree)
        linked_refs = retention.pin_trees(other, 'alpha', tree)
        retention.cleanup(self.ledger, 'alpha', 'owner')
        self.assertEqual(list(retention.list_refs(other, 'alpha')), linked_refs)
        self.gc()
        command._git(linked, 'cat-file', '-e', tree + ':a.txt')

    def test_invalid_id_blob_commit_and_missing_tree_are_rejected_before_any_pin(self):
        tree, blob = self.tree('typed evidence\n')
        commit = command._git(self.repo, 'rev-parse', 'HEAD')
        for invalid in ('HEAD', '--all', '../escape', 'f' * 40, blob, commit, None):
            with self.subTest(invalid=invalid):
                with self.assertRaises(LedgerError):
                    retention.pin_trees(self.ledger, 'alpha', tree, invalid)
                self.assertEqual(retention.list_refs(self.ledger, 'alpha'), {})

    def test_git_environment_cannot_redirect_pins_to_another_repository(self):
        tree, _ = self.tree('correct repository\n')
        other = self.root / 'other.git'
        command._git(self.root, 'init', '--bare', '-q', str(other))
        with patch.dict(os.environ, {'GIT_DIR': str(other), 'GIT_WORK_TREE': str(self.root)}):
            refs = retention.pin_trees(self.ledger, 'alpha', tree)
        self.assertEqual(list(retention.list_refs(self.ledger, 'alpha')), refs)
        self.assertEqual(command._git(other, 'for-each-ref', '--format=%(refname)'), '')

    def test_symbolic_ref_cannot_redirect_cleanup_into_another_plans_pin(self):
        tree, _ = self.tree('symbolic redirection\n')
        alpha = retention.pin_trees(self.ledger, 'alpha', tree)[0]
        beta = retention.pin_trees(self.ledger, 'beta', tree)[0]
        command._git(self.repo, 'update-ref', '-d', alpha)
        command._git(self.repo, 'symbolic-ref', alpha, beta)
        with self.assertRaisesRegex(LedgerError, 'Symbolic'):
            retention.cleanup(self.ledger, 'alpha', 'owner')
        self.assertEqual(retention.list_refs(self.ledger, 'beta'), {beta: tree})


if __name__ == '__main__':
    unittest.main()
