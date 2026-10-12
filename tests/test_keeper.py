import datetime as dt
import json
import os
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

from onecrew import interventions, keeper
from onecrew.interventions import runtime_revision
from onecrew.ledger import Ledger, LedgerError
from onecrew.supervisor import identity
from onecrew.workflow import task_lock
from tests.test_interventions import BOOTED, DEAD, QUESTION, UNKNOWN, LedgerFixture


def at(seconds):
    return dt.datetime.now(dt.timezone.utc)+dt.timedelta(seconds=seconds)


class ScanTests(unittest.TestCase):
    def setUp(self):
        self.f = LedgerFixture(self)
        self.calls = []

    def start(self, ledger, task, initiator=None):
        """Fixture launcher: the restarted runner registers, then dies again."""
        self.calls.append((task, initiator))
        self.f.started(task, DEAD, initiator=initiator)
        return {'status': 'alive', 'identity': DEAD, 'logs': 'fixture'}

    def test_scan_restarts_only_eligible_dead_roots(self):
        f = self.f
        eligible = [f.root('running'), f.root('operation', 'waiting_operation'), f.root('answered', 'waiting')]
        asked = f.root('asked', 'waiting'); f.ledger.create_request(asked, 'q', QUESTION)
        child_asked = f.root('child-asked', 'waiting'); f.ledger.create_request(f.child(child_asked, 'child'), 'q', QUESTION)
        blocked = f.root('blocked', 'blocked'); done = f.root('done', 'completed')
        cancelled = f.root('cancelled'); f.workflow.control.cancel(cancelled)
        paused = f.root('paused'); f.workflow.control.pause(paused)
        alive = f.root('alive'); never = f.root('never')
        legacy = f.root('legacy'); f.started(legacy, tree=None)  # last started by a runtime without the keeper: not adopted
        rebooted = f.root('rebooted'); f.started(rebooted, BOOTED)  # died with a reboot: needs an explicit resume
        standalone = f.task('standalone', 'running')  # not a delivery root
        for task in eligible+[asked, child_asked, blocked, done, cancelled, paused, standalone]: f.started(task)
        f.started(alive, identity(os.getpid()))
        actions = keeper.scan(f.state_root, now=at(20), start=self.start)
        self.assertEqual(sorted(self.calls), sorted((t, 'keeper') for t in eligible))
        self.assertEqual(sorted(a['task'] for a in actions if a['action'] == 'restarted'), sorted(eligible))
        self.assertEqual([a['task'] for a in actions if a['action'] == 'reboot'], [rebooted])
        for task in eligible:
            payload = f.events(task, 'coordinator.restarted')[0]['payload']
            self.assertEqual({k: payload[k] for k in ('cause', 'restart_count')}, {'cause': 'runner_dead', 'restart_count': 1})
            self.assertEqual(payload['last_checkpoint_seq'], f.workflow.state(task)[0])
            self.assertEqual(payload['runner']['status'], 'alive')
        for task in (asked, child_asked, blocked, done, cancelled, paused, alive, never, legacy, rebooted, standalone):
            self.assertEqual(f.events(task, 'coordinator.restarted'), [])

    def test_live_count_is_alive_runners_and_restartable_roots_only(self):
        """Idle exit must not wait on roots the keeper cannot act on, nor leave a live decision wait unsupervised."""
        f, me = self.f, identity(os.getpid())
        asked = f.root('asked', 'waiting'); f.ledger.create_request(asked, 'q', QUESTION); f.started(asked, me)
        paused = f.root('paused'); f.workflow.control.pause(paused); f.started(paused, me)
        f.root('never'); remote = f.root('remote'); f.started(remote, UNKNOWN)
        legacy = f.root('legacy'); f.started(legacy, tree=None); rebooted = f.root('rebooted'); f.started(rebooted, BOOTED)
        actions, live = keeper._scan(f.state_root, now=at(20), start=self.start)
        self.assertEqual((live, self.calls), (2, []))
        self.assertEqual(sorted(a['action'] for a in actions), ['reboot', 'unknown'])
        dead = f.root('dead'); f.started(dead)
        with patch.object(keeper, 'Ledger', side_effect=LedgerError('Project directory does not exist.')):
            actions, live = keeper._scan(f.state_root, now=at(20), start=self.start)
        self.assertEqual((live, self.calls), (0, [])); self.assertEqual({a['action'] for a in actions}, {'skipped'})
        self.assertEqual(keeper._scan(f.state_root, now=at(20), start=self.start)[1], 3)
        self.assertEqual(self.calls, [(dead, 'keeper')])

    def test_unknown_probe_is_never_restarted(self):
        task = self.f.root('remote'); self.f.started(task, DEAD); self.f.started(task, UNKNOWN)
        actions = keeper.scan(self.f.state_root, now=at(20), start=self.start)
        self.assertEqual(self.calls, [])
        self.assertEqual([a['action'] for a in actions], ['unknown'])
        self.assertEqual(self.f.events(task, 'coordinator.restarted'), [])

    def test_missing_ledger_or_lineage_is_nothing_to_do(self):
        self.assertEqual(keeper.scan(self.f.base/'empty', start=self.start), [])
        self.f.task('plain', 'running')
        self.assertEqual(keeper.scan(self.f.state_root, start=self.start), [])

    def test_backoff_and_hourly_bound_persist_and_exhaust_once(self):
        from onecrew.solution_delivery import Delivery
        task = self.f.root('crashy'); self.f.started(task)
        lost = MagicMock()
        steps = [(5, 'backoff'), (15, 'restarted'), (30, 'backoff'), (80, 'restarted'), (300, 'backoff'),
                 (400, 'restarted'), (500, 'exhausted'), (600, None), (3000, None)]
        with patch.object(Delivery, 'coordinator_lost', lost, create=True):
            for offset, expected in steps:  # every scan starts from ledger evidence only, like a restarted keeper
                actions = keeper.scan(self.f.state_root, now=at(offset), start=self.start)
                self.assertEqual([a['action'] for a in actions], [expected] if expected else [], offset)
        self.assertEqual(len(self.calls), 3)
        self.assertEqual([e['payload']['restart_count'] for e in self.f.events(task, 'coordinator.restarted')], [1, 2, 3])
        exhausted = self.f.events(task, 'coordinator.restart_exhausted')
        self.assertEqual(len(exhausted), 1); self.assertEqual(exhausted[0]['payload']['cause'], 'runner_dead')
        self.assertEqual(exhausted[0]['payload']['coordinator_lost'], {'status': 'reported'})
        lost.assert_called_once(); self.assertEqual(lost.call_args.args[0], task)
        self.assertIn('exhausted', lost.call_args.args[1])
        # A non-keeper start (the user's 'retry' answer, an operator resume) opens a new episode, even inside the hour.
        self.f.started(task, DEAD, initiator='reply')
        actions = keeper.scan(self.f.state_root, now=at(3100), start=self.start)
        self.assertEqual([(a['action'], a['restart_count']) for a in actions], [('restarted', 1)])

    def test_failed_loss_report_is_retried_within_a_bound(self):
        from onecrew.solution_delivery import Delivery
        busy = LedgerError('A controller already owns this task.')
        for outcomes, steps in (([busy, None], [(500, 'exhausted'), (505, 'backoff'), (511, 'lost_report'), (900, None)]),
                                ([busy, KeyError('defect'), OSError('disk')],
                                 [(500, 'exhausted'), (511, 'lost_report'), (560, 'backoff'), (572, 'lost_report'), (5000, None)])):
            with self.subTest(outcomes=outcomes):
                task = self.f.root('lost-%d' % len(outcomes)); self.f.started(task); self.calls.clear()
                for offset in (15, 80, 400): keeper.scan(self.f.state_root, now=at(offset), start=self.start)
                lost = MagicMock(side_effect=outcomes)
                with patch.object(Delivery, 'coordinator_lost', lost, create=True):
                    for offset, expected in steps:
                        actions = [a['action'] for a in keeper.scan(self.f.state_root, now=at(offset), start=self.start) if a['task'] == task]
                        self.assertEqual(actions, [expected] if expected else [], offset)
                self.assertEqual(lost.call_count, len(outcomes)); self.assertEqual(len(self.calls), 3)
                self.assertEqual(len(self.f.events(task, 'coordinator.restart_exhausted')), 1)
                reports = [self.f.events(task, 'coordinator.restart_exhausted')[0]['payload']['coordinator_lost']['status']]
                reports += [(e['payload']['status'], e['payload']['attempt']) for e in self.f.events(task, 'coordinator.lost_report')]
                self.assertEqual(reports, ['failed', ('reported', 2)] if len(outcomes) == 2 else ['failed', ('failed', 2), ('failed', 3)])
                self.assertEqual(keeper._scan(self.f.state_root, now=at(9000), start=self.start)[1], 0)  # episode closed

    def test_recent_runner_launch_defers_restart(self):
        task = self.f.root('launching'); self.f.started(task)
        (self.f.state_root/'runners'/'fresh').mkdir(parents=True)
        actions = keeper.scan(self.f.state_root, now=at(20), start=self.start)
        self.assertEqual([a['action'] for a in actions], ['backoff']); self.assertEqual(self.calls, [])


class KeeperProcessTests(unittest.TestCase):
    def setUp(self):
        self.f = LedgerFixture(self)

    def test_ensure_singleton_with_mocked_spawn(self):
        root = self.f.state_root
        with patch('onecrew.keeper.subprocess.Popen', return_value=SimpleNamespace(pid=os.getpid())) as spawn:
            first = keeper.ensure(root)
            self.assertEqual(first['status'], 'starting'); spawn.assert_called_once()
            argv, options = spawn.call_args.args[0], spawn.call_args.kwargs
            self.assertEqual(argv[argv.index('-m')+1:], ['onecrew.keeper', '--state-root', str(root.resolve())])
            self.assertEqual(options['creationflags'], 0x8 | 0x200 | 0x01000000); self.assertEqual(options['env']['ONECREW_ACTOR'], 'keeper')
            keeper._write(root, {'pid': os.getpid(), 'identity': identity(os.getpid()), 'last_scan': None})
            self.assertEqual(keeper.ensure(root)['status'], 'alive'); spawn.assert_called_once()
            keeper._write(root, {'pid': os.getpid(), 'identity': identity(os.getpid()), 'stopped_at': 'now'})
            self.assertEqual(keeper.ensure(root)['status'], 'starting')
            keeper._write(root, {'pid': os.getpid(), 'identity': DEAD})
            self.assertEqual(keeper.ensure(root)['status'], 'starting')
            self.assertEqual(spawn.call_count, 3)
            with patch.dict(os.environ, {'ONECREW_KEEPER': 'off'}):
                self.assertEqual(keeper.ensure(root), {'status': 'disabled'})
            self.assertEqual(spawn.call_count, 3)

    def loop(self, idle_exit=.05, settle=None, then=None):
        """Run the keeper loop on a daemon thread so a regression fails instead of hanging the suite.

        The thread itself holds the no-launch guard, so even a loop that outlives its test never spawns a real runner."""
        result = []

        def run():
            with patch.object(keeper.runner, 'start', side_effect=AssertionError('fixture roots must not be launched')):
                result.append(keeper.loop(self.f.state_root, interval=.02, idle_exit=idle_exit))
        worker = threading.Thread(target=run, daemon=True)
        worker.start()
        if settle:
            time.sleep(settle)
            try:
                self.assertTrue(worker.is_alive(), 'keeper exited while a root needed supervision')
                self.assertEqual(keeper.read_status(self.f.state_root)['live_roots'], 1)
            finally:
                then()
        worker.join(10)
        self.assertFalse(worker.is_alive(), 'keeper did not exit when idle')
        return result[0]

    def test_loop_is_singleton_and_exits_when_idle(self):
        root = self.f.state_root
        # Roots it can never act on do not keep it running: never launched, unprovable liveness, legacy start.
        self.f.root('never'); remote = self.f.root('remote'); self.f.started(remote, UNKNOWN)
        legacy = self.f.root('legacy'); self.f.started(legacy, tree=None)
        self.assertEqual(self.loop(), 'idle')
        status = keeper.read_status(root)
        self.assertEqual(status['pid'], os.getpid()); self.assertTrue(status['stopped_at']); self.assertTrue(status['last_scan'])
        with task_lock(SimpleNamespace(state_root=root.resolve()), 'keeper'), patch.object(keeper, 'LOCK_WAIT', .1):
            self.assertEqual(keeper.loop(root, interval=.01, idle_exit=.05), 'duplicate')

    def test_loop_stays_while_root_is_supervised(self):
        for phase, asked in (('running', False), ('waiting', True)):  # a user decision wait can outlast idle_exit
            with self.subTest(phase=phase):
                task = self.f.root('live-'+phase, phase); self.f.started(task, identity(os.getpid()))
                if asked: self.f.ledger.create_request(task, 'q', QUESTION)
                self.assertEqual(self.loop(idle_exit=.2, settle=.6, then=lambda: self.f.phase(task, 'completed')), 'idle')


class RunnerRecordTests(unittest.TestCase):
    def setUp(self):
        self.f = LedgerFixture(self); self.task = self.f.task()

    def test_runner_started_includes_runtime_and_initiator(self):
        from onecrew.runner import loop
        self.f.workflow.control.cancel(self.task)  # loop exits at its first check
        with patch.dict(os.environ, {'ONECREW_RUNNER_INITIATOR': 'keeper'}), patch('onecrew.runner.Workflow', return_value=self.f.workflow):
            self.assertEqual(loop(self.f.ledger, self.task), 'cancelled')
        with patch.dict(os.environ, {'ONECREW_RUNNER_INITIATOR': 'Not Valid'}), patch('onecrew.runner.Workflow', return_value=self.f.workflow):
            loop(self.f.ledger, self.task)
        rows = [e['payload'] for e in self.f.events(self.task, 'runner.started')]
        self.assertEqual([r['initiator'] for r in rows], ['keeper', 'unknown'])
        self.assertEqual(rows[0]['runtime'], runtime_revision())

    def test_runtime_hash_failure_never_fails_the_runner_start(self):
        from onecrew.runner import loop
        self.f.workflow.control.cancel(self.task)
        with patch.object(interventions, '_REVISION', None), patch.object(interventions, 'tree', side_effect=FileNotFoundError('replaced')), \
             patch('onecrew.runner.Workflow', return_value=self.f.workflow):
            self.assertEqual(loop(self.f.ledger, self.task), 'cancelled')
        self.assertIsNone(self.f.events(self.task, 'runner.started')[-1]['payload']['runtime']['tree'])

    def handoff(self, root):
        """Only the handoff marks a solution delivery; the fixture's roots are plain workflow tasks."""
        return patch.object(self.f.ledger, 'task', side_effect=lambda task, full=False: {'handoff': {'solution_delivery': {'version': 1}} if task == root else {}})

    def test_alive_delivery_runner_is_paired_with_a_keeper(self):
        from onecrew.runner import start
        root = self.f.root('root'); me = identity(os.getpid())
        for task in (root, self.task): self.f.started(task, me)
        with patch('onecrew.keeper.ensure', return_value={'status': 'starting'}) as ensure, patch('onecrew.runner.subprocess.Popen') as popen, \
             self.handoff(root):
            self.assertEqual(start(self.f.ledger, root)['keeper'], {'status': 'starting'})  # already alive: no new runner
            self.assertNotIn('keeper', start(self.f.ledger, self.task))
        popen.assert_not_called(); ensure.assert_called_once_with(self.f.ledger.state_root)

    def test_detached_delivery_runner_re_ensures_its_keeper(self):
        from onecrew import runner
        root = self.f.root('root')
        with patch('onecrew.keeper.ensure', side_effect=[{'status': 'alive'}, OSError('spawn denied')]) as ensure, self.handoff(root):
            runner._watch(self.f.ledger, root, every=0)()  # foreground/fixture loop: no launcher recorded
            with patch.dict(os.environ, {'ONECREW_RUNNER_INITIATOR': 'keeper'}):
                runner._watch(self.f.ledger, self.task, every=0)()  # not a delivery root
                watch = runner._watch(self.f.ledger, root, every=0); watch(); watch()  # a failed ensure is swallowed
                runner._watch(self.f.ledger, root, every=3600)()  # not yet due
        self.assertEqual(ensure.call_count, 2)

    def spawn(self, ledger, task, *, delivery, initiator=None, ensure=None):
        ensure = ensure or MagicMock(return_value={'status': 'alive'})
        process = MagicMock(pid=os.getpid()); process.poll.return_value = None
        handoff = {'handoff': {'solution_delivery': {'version': 1}} if delivery else {}}
        with patch('onecrew.runner.subprocess.Popen', return_value=process) as popen, \
             patch('onecrew.runner.status', side_effect=[{'status': 'stopped'}, {'status': 'alive', 'identity': DEAD}]), \
             patch('onecrew.runner.workflow_for', return_value=self.f.workflow), \
             patch.object(ledger, 'task', return_value=handoff), patch('onecrew.keeper.ensure', ensure):
            from onecrew.runner import start
            result = start(ledger, task, initiator=initiator) if initiator else start(ledger, task)
        return result, popen.call_args.kwargs['env'], ensure

    def test_start_passes_initiator_and_ensures_keeper_only_for_delivery_roots(self):
        ledger = Ledger(self.f.project, self.f.state_root)
        result, env, ensure = self.spawn(ledger, self.task, delivery=True, initiator='keeper')
        self.assertEqual((env['ONECREW_RUNNER_INITIATOR'], env['ONECREW_ACTOR']), ('keeper', 'onecrew'))
        ensure.assert_called_once_with(ledger.state_root); self.assertEqual(result['keeper'], {'status': 'alive'})
        with patch.dict(os.environ, {'ONECREW_ACTOR': 'codex'}):
            result, env, ensure = self.spawn(ledger, self.task, delivery=False)
        self.assertEqual(env['ONECREW_RUNNER_INITIATOR'], 'codex'); ensure.assert_not_called(); self.assertNotIn('keeper', result)
        result, _, _ = self.spawn(ledger, self.task, delivery=True, ensure=MagicMock(side_effect=OSError('spawn denied')))
        self.assertEqual(result['status'], 'alive'); self.assertEqual(result['keeper']['status'], 'unavailable')


if __name__ == '__main__':
    unittest.main()
