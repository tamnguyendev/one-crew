"""Pinned live trials and the eval environment's node (A2, 12/10/2026).

A trial records the runtime (git, tree, dirty), state root and target head before its root task runs. A runner
started from another runtime tree, a dirty runtime, or a commit outside OneCrew on the target branch inside the
window make the run assisted; a claimed trial without these records is unknown."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from onecrew import eval_scorecard as sc
from onecrew import eval_trials as et
from onecrew import evaluation as ev
from onecrew.eval_observe import observe
from onecrew.ledger import LedgerError
from tests.test_interventions import LedgerFixture

PIN = {'tree': 'a' * 64, 'git': 'b' * 40, 'dirty': False}


def git(repo, *args):
    return subprocess.run(['git', '-C', str(repo), '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
                           '-c', 'commit.gpgsign=false', *args], capture_output=True, text=True, check=True).stdout.strip()


class TrialFixture(unittest.TestCase):
    def setUp(self):
        self.f = LedgerFixture(self); self.ledger = self.f.ledger
        self.repo = self.f.project
        git(self.repo, 'init', '-q', '-b', 'claude/trial'); git(self.repo, 'add', '-A'); git(self.repo, 'commit', '-q', '-m', 'base')
        self.base = git(self.repo, 'rev-parse', 'HEAD')

    def open(self, key, runtime=PIN, **kwargs):
        with patch('onecrew.interventions.revision', return_value=dict(runtime)):
            return et.open_trial(self.ledger, key, **kwargs)

    def started(self, task, runtime):
        with self.ledger.transaction(write=True) as conn:
            self.ledger._event(conn, task, 'runner.started', {'identity': {}, 'runtime': runtime, 'initiator': 'claude'})

    def commit(self, name):
        (self.repo/name).write_text(name, encoding='utf-8'); git(self.repo, 'add', name); git(self.repo, 'commit', '-q', '-m', name)
        return git(self.repo, 'rev-parse', 'HEAD')

    def evidence(self, task):
        return observe(self.f.state_root, [task])['tasks'][0]['trial']


class TrialTests(TrialFixture):
    def test_trial_records_the_pins(self):
        trial = self.open('root-1')
        self.assertRegex(trial['id'], r'^TRIAL-[0-9a-f]{32}$')
        self.assertEqual((trial['root_key'], trial['runtime'], trial['state_root'], trial['predecessor']),
                         ('root-1', PIN, str(self.f.state_root), None))
        self.assertEqual((trial['target']['head'], trial['target']['branch']), (self.base, 'claude/trial'))
        self.assertTrue(trial['opened_at'])
        self.assertEqual(self.open('root-1')['id'], trial['id'])  # a replayed open
        with self.assertRaisesRegex(LedgerError, 'already open'):
            self.open('root-1', dict(PIN, tree='c' * 64))
        self.f.task('existing-root')
        with self.assertRaisesRegex(LedgerError, 'before submitting'):
            self.open('existing-root')

    def test_runtime_change_mid_trial_assisted(self):
        self.open('root-2'); task = self.f.task('root-2')
        self.started(task, dict(PIN))
        self.assertEqual(self.evidence(task)['assisted'], [])
        self.assertEqual((self.evidence(task)['pinned'], self.evidence(task)['unknown']), (True, []))
        self.started(task, dict(PIN, tree='c' * 64))  # the runtime was edited and the runner restarted
        self.assertEqual(self.evidence(task)['assisted'], ['runtime_changed_in_trial'])
        level, reasons = sc.assistance_level(observe(self.f.state_root, [task])['tasks'][0])
        self.assertEqual(level, 'assisted'); self.assertIn('runtime_changed_in_trial', reasons)

    def test_dirty_runtime_flagged(self):
        self.open('root-3', dict(PIN, dirty=True)); task = self.f.task('root-3')
        self.assertEqual(self.evidence(task)['assisted'], ['runtime_changed_in_trial'])
        self.open('root-4'); clean = self.f.task('root-4')
        self.started(clean, dict(PIN, dirty=True))  # same tree hash but uncommitted runtime edits
        self.assertEqual(self.evidence(clean)['assisted'], ['runtime_changed_in_trial'])

    def test_external_commit_assisted(self):
        self.open('root-5'); task = self.f.task('root-5')
        self.assertEqual(self.evidence(task)['assisted'], [])
        ours = self.commit('onecrew.txt')
        with self.ledger.transaction(write=True) as conn:  # the commit receipt OneCrew wrote for its own commit
            self.ledger._event(conn, task, 'workflow.checkpoint', {'phase': 'completed', 'delivery': {'nodes': {
                'commit': {'phase': 'passed', 'receipt': {'passed': True, 'commit': ours, 'verified': True, 'pushed': False}}}}})
        self.assertEqual(self.evidence(task)['assisted'], [])
        external = self.commit('someone-else.txt')
        self.assertEqual(self.evidence(task)['assisted'], ['external_commit'])
        trial = et.close_trial(self.ledger, et.show(self.ledger, self.open_id('root-5'))['id'])
        self.assertEqual((trial['closed']['onecrew_commits'], trial['closed']['external_commits']), ([ours], [external]))
        self.assertEqual(trial['closed']['task'], task)
        self.assertIn('external_commit', trial['closed']['scorecard']['assistance_reasons'])
        git(self.repo, 'reset', '-q', '--hard', ours)  # after close the recorded window is what counts
        self.assertEqual(self.evidence(task)['assisted'], ['external_commit'])

    def open_id(self, key):
        with self.ledger.transaction() as conn:
            return conn.execute('SELECT id FROM eval_trials WHERE root_key=?', (key,)).fetchone()[0]

    def test_claimed_trial_without_record_unknown(self):
        task = self.f.task('no-trial')
        self.assertIsNone(self.evidence(task))
        rows = {t['task']: t for t in sc.scorecard(self.f.state_root, [task], claim_trials=True)['axes']['task_completion']['tasks']}
        self.assertIn('trial_unpinned', rows[task]['assistance_reasons'])
        unclaimed = sc.scorecard(self.f.state_root, [task])['axes']['task_completion']['tasks'][0]
        self.assertNotIn('trial_unpinned', unclaimed['assistance_reasons'])
        self.open('root-6', dict(PIN, git=None)); unpinned = self.f.task('root-6')  # runtime not a commit
        self.assertEqual((self.evidence(unpinned)['pinned'], self.evidence(unpinned)['unknown']), (False, ['trial_unpinned']))
        self.open('root-7'); legacy = self.f.task('root-7')
        self.started(legacy, None)  # a runner that recorded no runtime
        self.assertEqual(self.evidence(legacy)['unknown'], ['trial_unpinned'])
        with patch('onecrew.eval_trials.git', return_value=None):  # the target window cannot be shown
            self.assertIn('trial_unpinned', self.evidence(legacy)['unknown'])

    def test_superseded_trial_linked(self):
        first = self.open('root-a')
        with self.assertRaisesRegex(LedgerError, 'Close the predecessor'):
            self.open('root-b', predecessor=first['id'])
        closed = et.close_trial(self.ledger, first['id'])
        self.assertEqual(et.close_trial(self.ledger, first['id'])['closed'], closed['closed'])  # closing twice keeps the first result
        self.assertIsNone(closed['closed']['task'])
        second = self.open('root-b', predecessor=first['id'])
        self.assertEqual(second['predecessor'], first['id'])
        self.assertEqual(et.show(self.ledger, first['id'])['successors'], [second['id']])
        with self.assertRaisesRegex(LedgerError, 'Unknown predecessor'):
            self.open('root-c', predecessor='TRIAL-' + '0' * 32)
        with self.assertRaisesRegex(LedgerError, 'new root key'):
            self.open('root-a')


class EnvironmentTests(unittest.TestCase):
    def test_environment_records_node_and_clean_env_resolves_it(self):
        node = ev.node_binary()
        if node is None: self.skipTest('no node.exe on this machine')
        e = ev.environment()['node']
        self.assertEqual(e['path'], str(node)); self.assertRegex(e['sha256'], '^[0-9a-f]{64}$'); self.assertTrue(e['version'].startswith('v'))
        with tempfile.TemporaryDirectory() as home:
            # Even when the caller's PATH has no node, the clean probe environment resolves the pinned one.
            bare = os.pathsep.join(p for p in os.environ.get('PATH', '').split(os.pathsep) if not (Path(p)/'node.exe').is_file() and not (Path(p)/'node').is_file())
            with patch.dict(os.environ, {'PATH': bare}), patch.object(ev, 'NODE_CANDIDATES', (node,)):
                env = ev.clean_environment(Path(home))
            self.assertEqual(env['ONECREW_EVAL_NODE'], str(node))
            found = subprocess.run([sys.executable, '-c', 'import shutil; print(shutil.which("node"))'], env=env,
                                   capture_output=True, text=True, timeout=60).stdout.strip()
            self.assertEqual(Path(found).resolve(), node)

    def test_node_choice_and_absence_are_recorded(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake = Path(tmp)/'node.exe'; fake.write_bytes(b'not really node')
            with patch.dict(os.environ, {'ONECREW_EVAL_NODE': str(fake)}):
                self.assertEqual(ev.node_binary(), fake.resolve())
            with patch.dict(os.environ, {'ONECREW_EVAL_NODE': ''}), patch.object(shutil, 'which', return_value=None), \
                 patch.object(ev, 'NODE_CANDIDATES', ()):
                self.assertIsNone(ev.node_binary()); self.assertIsNone(ev.node_identity())
                env = ev.clean_environment(Path(tmp)/'home')
                self.assertNotIn('ONECREW_EVAL_NODE', env)


if __name__ == '__main__':
    unittest.main()
