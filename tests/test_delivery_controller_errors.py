"""Controller defects and reboots become one typed request and one notice, never an untyped block or silence
(synthesis §3.6). Provider, Flutter and Windows windows are fixtures; no real runner is launched."""
import datetime as dt
import os
from pathlib import Path
import unittest
from unittest.mock import MagicMock, patch

from onecrew import delivery_recovery as rc
from onecrew import desktop_notifications as desktop
from onecrew import keeper, runner
from onecrew.ledger import LedgerError, utcnow
from onecrew.solution_delivery import Delivery
from tests.test_interventions import BOOTED
from tests import test_solution_delivery as fixtures  # module import: its TestCase is not collected twice


def never_start(ledger, task, initiator=None):
    raise AssertionError('a runner that died with a reboot must not be restarted silently')


class Base(unittest.TestCase):
    def setUp(self):
        fixtures.DeliveryTests.setUp(self)
        env = patch.dict(os.environ, {'ONECREW_DELIVERY_ROOT': str(Path(self.tmp.name)/'ocd'), 'ONECREW_KEEPER': 'off'})
        env.start(); self.addCleanup(env.stop)
        for name in ('ONECREW_RUNNER_INITIATOR', 'ONECREW_ACTOR', 'ONECREW_DESKTOP_HOME'): os.environ.pop(name, None)
        quiet = patch('traceback.print_exc'); quiet.start(); self.addCleanup(quiet.stop)
        self.r, self.t = fixtures.DeliveryTests.create(self)

    def pending(self):
        return self.ledger.requests(self.t, pending=True)

    def events(self, kind):
        return [e for e in self.ledger.events(self.t) if e['kind'] == kind]

    def answered(self, choice):
        """A runtime_bug question the user answered that no coordinator has applied yet."""
        self.r.run(self.t)
        with patch('onecrew.delivery_steps.execute', side_effect=TypeError('bad receipt')):
            self.r.run(self.t)
        [request] = self.pending()
        self.ledger.reply(request['id'], request['revision'], choice, 'terminal', 'anh chọn '+choice, decided_by='user', by='user')
        return request

    def consumed(self):
        return [x['request_id'] for x in Delivery(self.ledger).state(self.t)[1].get('consumed_replies', [])]


class ControllerErrorTests(Base):
    def test_keyerror_in_run_runtime_bug_request(self):
        self.r.run(self.t)  # preflight
        with patch('onecrew.delivery_steps.execute', side_effect=KeyError('teleport')):
            s = self.r.run(self.t)
        self.assertEqual(s['phase'], 'waiting')
        self.assertEqual({k: s['delivery']['escalation'][k] for k in ('class', 'node')}, {'class': 'runtime_bug', 'node': 'tests'})
        self.assertEqual(s['delivery']['nodes']['tests']['phase'], 'blocked')
        [request] = self.pending()
        self.assertIn('KeyError', request['question']['reason'])
        self.assertEqual([o['id'] for o in request['question']['options']], ['retry', 'stop'])
        with patch('onecrew.delivery_steps.execute') as op:  # still waiting: no replay, no second question
            self.assertEqual(self.r.run(self.t)['phase'], 'waiting'); op.assert_not_called()
        self.assertEqual(len(self.pending()), 1)

    def test_unknown_node_kind_typed_not_keyerror(self):
        from onecrew.delivery_steps import execute
        self.r.run(self.t)
        with self.assertRaisesRegex(LedgerError, 'Unsupported delivery operation: teleport'):
            execute(self.r, self.t, self.r.state(self.t)[1], {'id': 'x', 'kind': 'teleport', 'config': {}}, {})
        seq, s = self.r.state(self.t); s['plan']['nodes'][0]['kind'] = 'teleport'; self.r.persist(self.t, seq, s)
        s = self.r.run(self.t)
        self.assertEqual((s['phase'], s['delivery']['escalation']['class']), ('waiting', 'runtime_bug'))

    def test_runner_catch_all_typed_for_delivery(self):
        with patch.object(Delivery, 'run', side_effect=KeyError('checkpoint')):
            self.assertEqual(runner.loop(self.ledger, self.t, interval=0), 'waiting')
        s = Delivery(self.ledger).state(self.t)[1]
        self.assertEqual((s['phase'], s['waiting_reason']), ('waiting', 'decision'))
        self.assertNotIn('recovery', s)  # not the untyped controller block
        self.assertEqual(s['delivery']['escalation']['class'], 'runtime_bug')
        [request] = self.pending()
        self.assertIn('Controller error: KeyError', request['question']['reason'])
        self.assertEqual(self.events('runner.stopped')[-1]['payload']['outcome'], 'waiting')

    def test_answered_question_then_controller_error_asks_again(self):
        old = self.answered('retry')
        with patch.object(Delivery, 'run', side_effect=KeyError('checkpoint')):
            self.assertEqual(runner.loop(self.ledger, self.t, interval=0), 'waiting')
        [request] = self.pending()  # a question exists again, so the root is not stuck on an applied-never answer
        self.assertNotEqual(request['id'], old['id'])
        self.assertIn('Controller error: KeyError', request['question']['reason'])
        s = Delivery(self.ledger).state(self.t)[1]
        self.assertEqual((s['phase'], s['waiting_reason']), ('waiting', 'decision'))
        self.assertEqual((s['delivery']['escalation']['class'], s['delivery']['escalation']['request']), ('runtime_bug', request['id']))
        self.assertEqual(self.consumed(), [old['id']])  # the user's retry was applied, not dropped
        self.assertNotIn('recovery', s)

    def test_answered_stop_then_controller_error_cancels(self):
        self.answered('stop')
        with patch.object(Delivery, 'run', side_effect=KeyError('checkpoint')):
            self.assertEqual(runner.loop(self.ledger, self.t, interval=0), 'cancelled')
        self.assertEqual((Delivery(self.ledger).state(self.t)[1]['phase'], self.pending()), ('cancelled', []))

    def test_controller_error_without_question_blocks_untyped(self):
        # Backstop: a non-terminal root without a pending question would sit with nothing to answer and no notice.
        with patch.object(Delivery, 'run', side_effect=KeyError('checkpoint')), \
             patch.object(Delivery, 'coordinator_lost', lambda self, task, detail, cls='runtime_bug': self.state(task)[1]):
            with self.assertRaisesRegex(LedgerError, 'no typed question'):
                Delivery(self.ledger).controller_error(self.t, KeyError('checkpoint'))
            self.assertEqual(runner.loop(self.ledger, self.t, interval=0), 'blocked')
        s = Delivery(self.ledger).state(self.t)[1]
        self.assertEqual((s['phase'], s['recovery']['kind'], s['recovery']['error_type']), ('blocked', 'controller', 'KeyError'))

    def test_runner_keeps_untyped_block_when_typed_path_fails(self):
        with patch.object(Delivery, 'run', side_effect=KeyError('checkpoint')), \
             patch.object(Delivery, 'controller_error', side_effect=RuntimeError('defect in the typed path')):
            self.assertEqual(runner.loop(self.ledger, self.t, interval=0), 'blocked')
        s = Delivery(self.ledger).state(self.t)[1]
        self.assertEqual((s['phase'], s['recovery']['kind'], s['recovery']['error_type']), ('blocked', 'controller', 'KeyError'))

    def test_reply_continues_without_resume(self):
        self.r.run(self.t)
        with patch('onecrew.delivery_steps.execute', side_effect=TypeError('bad receipt')):
            self.r.run(self.t)
        [request] = self.pending()
        self.ledger.reply(request['id'], request['revision'], 'retry', 'terminal', 'anh chọn thử lại', decided_by='user', by='user')
        with patch('onecrew.runner.start', return_value={'status': 'alive'}) as start:
            continuation = keeper.after_reply(self.ledger, self.t)
        start.assert_called_once_with(self.ledger, self.t, initiator='reply'); self.assertTrue(continuation['started'])
        source = self.r.state(self.t)[1]['delivery']['source']['hash']
        with patch.object(Delivery, 'resume', side_effect=AssertionError('no entry resume')), \
             patch('onecrew.delivery_steps.execute', return_value={'passed': True, 'source': source, 'counts': {'passed': 1, 'skipped': 0}}):
            self.assertEqual(self.r.run(self.t)['phase'], 'running')
            s = self.r.run(self.t)
        self.assertEqual(s['delivery']['nodes']['tests']['phase'], 'passed')
        self.assertIn(request['id'], [x['request_id'] for x in s['consumed_replies']])
        self.assertEqual(self.pending(), [])


@unittest.skipUnless(os.name == 'nt', 'the last boot time is read from Windows')
class RebootTests(Base):
    def died_with_reboot(self):
        with self.ledger.transaction(write=True) as conn:
            self.ledger._event(conn, self.t, 'runner.started', {'identity': BOOTED, 'started_at': utcnow(), 'initiator': 'claude',
                                                               'runtime': {'tree': 'f'*64, 'git': None, 'dirty': None}})

    def test_keeper_reboot_one_notice(self):
        desktop.configure(self.ledger, True)
        self.died_with_reboot()
        now = dt.datetime.now(dt.timezone.utc)
        with patch.object(desktop, 'launch') as launch:
            self.assertEqual([a['action'] for a in keeper._scan(self.ledger.state_root, now, never_start, act=False)[0]], ['reboot'])
            self.assertEqual(self.events('coordinator.lost_report'), [])  # an idle check never writes
            first = keeper.scan(self.ledger.state_root, now, never_start)
            for later in (60, 600, 6000):  # repeated scans: same single question, no second window
                self.assertEqual(keeper.scan(self.ledger.state_root, now+dt.timedelta(seconds=later), never_start), [])
        self.assertEqual([(a['action'], a['status'], a['cause']) for a in first], [('reboot', 'reported', 'reboot')])
        [report] = self.events('coordinator.lost_report')
        self.assertEqual((report['payload']['cause'], report['payload']['runner_created']), ('reboot', BOOTED['created']))
        [request] = self.pending()
        s = Delivery(self.ledger).state(self.t)[1]
        self.assertEqual((s['phase'], s['delivery']['escalation']['class']), ('waiting', 'coordinator_lost'))
        self.assertIn('reboot', request['question']['reason'])
        self.assertEqual(launch.call_count, 1)
        [record] = [r for r in desktop.status(self.ledger)['records'] if r['task'] == self.t]
        self.assertEqual(record['title'], 'Cần anh trả lời')
        text = Path(record['report']).read_text(encoding='utf-8')
        self.assertIn('request reply '+request['id']+' --revision '+request['revision']+' --choice retry --decided-by user', text)

    def test_keeper_reboot_after_answer_asks_once(self):
        desktop.configure(self.ledger, True)
        now = dt.datetime.now(dt.timezone.utc)
        with patch.object(desktop, 'launch') as launch:
            old = self.answered('retry')  # the machine rebooted before any runner applied the answer
            self.died_with_reboot()
            [action] = keeper.scan(self.ledger.state_root, now, never_start)
            for later in (60, 600, 6000):
                self.assertEqual(keeper.scan(self.ledger.state_root, now+dt.timedelta(seconds=later), never_start), [])
        self.assertEqual((action['action'], action['status'], action['cause']), ('reboot', 'reported', 'reboot'))
        [request] = self.pending()
        self.assertNotEqual(request['id'], old['id'])
        s = Delivery(self.ledger).state(self.t)[1]
        self.assertEqual((s['phase'], s['delivery']['escalation']['class'], s['delivery']['escalation']['request']),
                         ('waiting', 'coordinator_lost', request['id']))
        self.assertEqual(self.consumed(), [old['id']])
        self.assertEqual(launch.call_count, 2)  # the first question, then exactly one notice for the reboot
        self.assertEqual([r['title'] for r in desktop.status(self.ledger)['records']], ['Cần anh trả lời']*2)

    def test_keeper_reboot_after_stop_not_raised(self):
        self.answered('stop')
        self.died_with_reboot()
        now = dt.datetime.now(dt.timezone.utc)
        [action] = keeper.scan(self.ledger.state_root, now, never_start)
        self.assertEqual((action['action'], action['status'], action['phase']), ('reboot', 'not_raised', 'cancelled'))
        self.assertEqual((Delivery(self.ledger).state(self.t)[1]['phase'], self.pending()), ('cancelled', []))
        self.assertEqual(keeper.scan(self.ledger.state_root, now+dt.timedelta(seconds=600), never_start), [])  # terminal

    def test_keeper_reboot_report_retried_then_closed(self):
        self.died_with_reboot()
        now = dt.datetime.now(dt.timezone.utc)
        lost = MagicMock(side_effect=[LedgerError('A controller already owns this task.'), None])
        steps = [(0, 'failed'), (5, None), (11, 'reported'), (400, None)]
        with patch.object(Delivery, 'coordinator_lost', lost):
            for offset, status in steps:
                [action] = keeper.scan(self.ledger.state_root, now+dt.timedelta(seconds=offset), never_start)
                self.assertEqual((action['action'], action.get('status')), ('reboot', status), offset)
        self.assertEqual(lost.call_count, 2)
        self.assertEqual(lost.call_args.args, (self.t, keeper.REBOOT)); self.assertEqual(lost.call_args.kwargs, {'cls': 'coordinator_lost'})
        self.assertEqual([(e['payload']['status'], e['payload']['attempt']) for e in self.events('coordinator.lost_report')],
                         [('failed', 1), ('reported', 2)])
        self.assertEqual(rc.POLICY['coordinator_lost'], ('ask', 0)); self.assertIn('coordinator_lost', rc.GUIDANCE)


if __name__ == '__main__':
    unittest.main()
