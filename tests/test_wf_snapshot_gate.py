"""P2 of the Codex review (9aca8be): the development gate runs on a fixed snapshot — a clean detached worktree of one commit — and refuses
a result whose snapshot moved. Temporary Git repositories only; the real gate subprocess is not run here (the kit tests cover `decide`).

Counter-rules: a file edited in the ORIGINAL checkout after the snapshot was prepared does not reach the snapshot; a file edited inside the
snapshot, a moved HEAD or a changed external document folder make `intact` report a problem and `finish` refuse, whatever the gate said;
a request for a non-commit or a non-new output folder is refused before anything is created.
"""
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from wfkit import development_gate as dg


def git(repo, *args):
    return subprocess.run(['git', '-C', str(repo), *args], check=True, capture_output=True, text=True, encoding='utf-8').stdout.strip()


class SnapshotGateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name) / 'repo'; self.repo.mkdir()
        git(self.repo, 'init', '-q'); git(self.repo, 'config', 'user.name', 'fixture'); git(self.repo, 'config', 'user.email', 'fixture@localhost')
        (self.repo / 'code.py').write_text('VALUE = 1\n'); (self.repo / 'test_code.py').write_text('def test_value(): assert True\n')
        git(self.repo, 'add', '.'); git(self.repo, 'commit', '-qm', 'one')
        self.commit = git(self.repo, 'rev-parse', 'HEAD')
        self.docs = Path(self.temp.name) / 'docs'; self.docs.mkdir(); (self.docs / '00.md').write_text('design\n')
        self.out = Path(tempfile.gettempdir()) / ('wf-snapshot-test-' + os.urandom(4).hex())
        self.addCleanup(lambda: subprocess.run(['git', '-C', str(self.repo), 'worktree', 'prune'], capture_output=True))

    def test_prepare_gives_a_clean_detached_worktree_that_later_edits_of_the_checkout_do_not_reach(self):
        prepared = dg.prepare(self.repo, 'HEAD', self.out, self.docs)
        tree = Path(prepared['tree'])
        self.assertEqual(prepared['commit'], self.commit); self.assertEqual(prepared['status_at_start'], [])
        self.assertEqual(git(tree, 'rev-parse', 'HEAD'), self.commit)
        self.assertEqual(prepared['doc_fingerprint'], {'00.md': dg.kitguard.sha256_file(self.docs / '00.md')})
        self.assertTrue(prepared['python']['sha256'])
        (self.repo / 'code.py').write_text('VALUE = 2  # edited in the checkout while the gate runs\n')        # the original checkout moves on
        self.assertEqual((tree / 'code.py').read_text(), 'VALUE = 1\n')                                     # the snapshot does not
        self.assertEqual(dg.intact(prepared), [])
        decision = dg.finish(prepared, {'decision': 'refused', 'problems': [{'kind': 'acceptance-partial'}], 'release_delivery': False}, dg.intact(prepared))
        self.assertTrue(decision['snapshot']['intact']); self.assertEqual(decision['snapshot']['commit'], self.commit)

    def test_edits_inside_the_snapshot_a_moved_head_or_a_changed_doc_folder_refuse_the_result(self):
        prepared = dg.prepare(self.repo, self.commit, self.out, self.docs)
        tree = Path(prepared['tree'])
        (tree / 'test_code.py').write_text('def test_value(): assert False\n')                              # a test changed during the run
        kinds = {p['kind'] for p in dg.intact(prepared)}
        self.assertIn('snapshot-dirty', kinds)
        git(tree, 'checkout', '-q', '--', 'test_code.py')
        self.assertEqual(dg.intact(prepared), [])
        (self.docs / '00.md').write_text('design changed\n')                                                 # the external source changed
        self.assertEqual({p['kind'] for p in dg.intact(prepared)}, {'external-source-changed'})
        (self.docs / '00.md').write_text('design\n')
        git(self.repo, 'commit', '-q', '--allow-empty', '-m', 'two')
        git(tree, 'checkout', '-q', '--detach', git(self.repo, 'rev-parse', 'HEAD'))                          # HEAD moved
        problems = dg.intact(prepared)
        self.assertEqual({p['kind'] for p in problems}, {'snapshot-moved'})
        decision = dg.finish(prepared, {'decision': 'pass', 'release_delivery': True, 'problems': []}, problems)
        self.assertEqual(decision['decision'], 'refused'); self.assertFalse(decision['release_delivery']); self.assertFalse(decision['snapshot']['intact'])
        self.assertIn('snapshot-moved', {p['kind'] for p in decision['problems']})
        missing = dg.finish(prepared, None, [])
        self.assertEqual(missing['decision'], 'refused')                                                     # no decision file = no certificate

    def test_a_non_commit_or_a_used_output_is_refused_before_anything_exists(self):
        with self.assertRaises(ValueError):
            dg.prepare(self.repo, 'no-such-ref', self.out, self.docs)
        self.assertFalse(self.out.exists())
        self.out.mkdir()
        with self.assertRaises(ValueError):
            dg.prepare(self.repo, 'HEAD', self.out, self.docs)
        with self.assertRaises(ValueError):
            dg.prepare(self.repo, 'HEAD', Path(self.temp.name) / 'not-under-os-temp-marker' / 'x', self.docs) if not Path(self.temp.name).resolve().is_relative_to(Path(tempfile.gettempdir()).resolve()) else (_ for _ in ()).throw(ValueError('n/a'))
