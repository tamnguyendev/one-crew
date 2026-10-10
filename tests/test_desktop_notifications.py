import os
from pathlib import Path
import unittest
from unittest.mock import patch

from tests import test_owned as fixtures
from onecrew import desktop_notifications as desktop
from onecrew import desktop_window
from onecrew.ledger import LedgerError


class DesktopTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.OwnedTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.home = Path(self.f.temp.name)/'desktop-on-other-disk'
        self.env = patch.dict(os.environ, ONECREW_DESKTOP_HOME=str(self.home))
        self.env.start(); self.addCleanup(self.env.stop)
        self.launcher = patch.object(desktop, 'launch')
        self.launch = self.launcher.start(); self.addCleanup(self.launcher.stop)
        self.run, self.task, self.worker = self.f.runtime([])
        self.ledger = self.f.ledger

    def change(self, phase, **fields):
        seq, state = self.run.state(self.task)
        state.update(phase=phase, message='Fixture '+phase, **fields)
        self.run.persist(self.task, seq, state)

    def records(self):
        return desktop.status(self.ledger)['records']

    def test_disabled_default_and_running_are_silent(self):
        self.change('blocked')
        self.assertFalse(self.home.exists())
        desktop.configure(self.ledger, True)
        self.change('running')
        self.assertEqual(self.launch.call_count, 0)
        self.assertEqual(self.records(), [])

    def test_terminal_once_even_after_repeated_checkpoint_and_reopen(self):
        desktop.configure(self.ledger, True)
        self.change('completed', report='Scope fixed', verification={'passed':True})
        self.change('completed')
        desktop.configure(self.ledger, True)
        desktop.publish(self.ledger, self.task)
        self.assertEqual(self.launch.call_count, 1)
        self.assertEqual(len(self.records()), 1)
        self.assertEqual(self.worker.calls, [])
        report = Path(self.records()[0]['report']).read_text(encoding='utf-8')
        self.assertIn('Scope fixed', report)
        self.assertIn('Kiểm chứng độc lập', report)
        self.assertNotIn('shown_at', self.records()[0])

    def test_block_resume_complete_has_two_outcomes(self):
        desktop.configure(self.ledger, True)
        self.change('blocked')
        self.change('running')
        self.change('completed')
        self.assertEqual(self.launch.call_count, 2)
        self.assertEqual({r['phase'] for r in self.records()}, {'blocked', 'completed'})

    def test_same_phase_in_later_episode_not_lost(self):
        desktop.configure(self.ledger, True)
        self.change('blocked'); self.change('running'); self.change('blocked')
        self.assertEqual(self.launch.call_count, 2)

    def test_event_hook_is_independent_of_old_sink_full_disk(self):
        desktop.configure(self.ledger, True)
        with patch('onecrew.delivery.deliver', side_effect=OSError('C disk full')):
            self.change('blocked')
        self.assertEqual(self.launch.call_count, 1)
        self.assertTrue(Path(self.records()[0]['report']).is_file())

    def test_launch_failure_retries_same_entry_on_next_event(self):
        desktop.configure(self.ledger, True)
        self.launch.side_effect = OSError('cannot launch')
        self.change('completed')
        first = self.records()[0]
        self.assertEqual(first['status'], 'pending')
        self.launch.side_effect = None
        desktop.publish(self.ledger)
        self.assertEqual(len(self.records()), 1)
        self.assertEqual(self.records()[0]['id'], first['id'])
        self.assertEqual(self.launch.call_count, 2)

    def test_outbox_failure_never_marks_task_failed_and_can_recover(self):
        desktop.configure(self.ledger, True)
        with patch.object(desktop, 'durable_write', side_effect=OSError('D disk full')):
            self.change('completed')
        self.assertEqual(self.run.state(self.task)[1]['phase'], 'completed')
        self.assertEqual(self.launch.call_count, 0)
        desktop.publish(self.ledger)
        self.assertEqual(self.launch.call_count, 1)

    def test_uncertain_launch_is_not_automatically_repeated(self):
        desktop.configure(self.ledger, True)
        self.change('blocked')
        root = desktop.directory(self.ledger)
        record = self.records()[0]
        record['status'] = 'claimed'
        desktop.write(root/(record['id']+'.json'), record)
        desktop.publish(self.ledger)
        self.assertEqual(self.launch.call_count, 1)
        desktop.retry(self.ledger, record['id'])
        self.assertEqual(self.launch.call_count, 2)

    def test_retry_refuses_already_shown(self):
        desktop.configure(self.ledger, True)
        self.change('completed')
        record = self.records()[0]; record['status'] = 'shown'
        desktop.write(desktop.directory(self.ledger)/(record['id']+'.json'), record)
        with self.assertRaisesRegex(LedgerError, 'Already shown'):
            desktop.retry(self.ledger, record['id'])

    def test_explicit_current_result_and_disable(self):
        self.change('blocked')
        desktop.configure(self.ledger, True)
        desktop.publish(self.ledger)
        self.assertEqual(self.launch.call_count, 0)
        desktop.publish(self.ledger, self.task)
        self.assertEqual(self.launch.call_count, 1)
        desktop.configure(self.ledger, False)
        self.change('completed')
        self.assertEqual(self.launch.call_count, 1)

    def test_answered_request_or_recovered_task_not_reopened(self):
        desktop.configure(self.ledger, True)
        self.change('blocked')
        record = self.records()[0]
        self.change('running')
        desktop_window.show(desktop.directory(self.ledger), record['id'])
        self.assertEqual(self.records()[0]['status'], 'superseded')
        desktop.retry(self.ledger, record['id'])
        self.assertEqual(self.launch.call_count, 1)

    def test_question_is_read_only_and_deduped_across_waiting_blocked(self):
        desktop.configure(self.ledger, True)
        state = self.run.state(self.task)[1]
        profile = self.run.control.status(self.task)['configuration']['profile']
        self.run._tool(self.task, state, 'ask', dict(question='Which version?', reason='Need choice',
            options=[{'id':'a','label':'A'}, {'id':'b','label':'B'}], recommendation='a'), profile)
        self.change('waiting'); self.change('blocked')
        self.assertEqual(self.launch.call_count, 1)
        self.assertEqual(len(self.ledger.requests(self.task, pending=True)), 1)
        self.assertIn('Which version?', Path(self.records()[0]['report']).read_text(encoding='utf-8'))

    def test_conversation_question_includes_current_revision_without_reply(self):
        from onecrew.solution_gate import question
        # Use an approved task binding, the same contract used by the native worker.
        other = fixtures.OwnedTests(); other.setUp(); self.addCleanup(other.doCleanups)
        runtime, task, _ = other.runtime([], mode='change', image='sha256:'+'a'*64)
        with other.ledger.transaction() as conn:
            binding = conn.execute('SELECT * FROM solution_bindings WHERE task_id=?', (task,)).fetchone()
        desktop.configure(other.ledger, True)
        req = question(other.ledger, binding['conversation'], 'fixture-disk', 'Disk full?', 'Need space', [task], 'codex')
        seq, state = runtime.state(task); state.update(phase='blocked', message='Disk full')
        runtime.persist(task, seq, state)
        record = desktop.status(other.ledger)['records'][0]
        report = Path(record['report']).read_text(encoding='utf-8')
        self.assertIn(req['id'], report); self.assertIn(req['revision'], report)
        with other.ledger.transaction() as conn:
            self.assertEqual(conn.execute('SELECT state FROM conversation_questions WHERE id=?', (req['id'],)).fetchone()[0], 'pending')

    def test_report_redacts_secret_and_does_not_execute_text(self):
        desktop.configure(self.ledger, True)
        self.change('failed', report='token=never-display-this')
        report = Path(self.records()[0]['report']).read_text(encoding='utf-8')
        self.assertNotIn('never-display-this', report)
        self.assertIn('[sensitive content withheld]', report)

    def test_concurrent_checkpoints_claim_only_one_launch(self):
        from concurrent.futures import ThreadPoolExecutor
        desktop.configure(self.ledger, True)
        with patch.object(desktop, 'best_effort'):
            self.change('completed')
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: desktop.publish(self.ledger), range(2)))
        self.assertEqual(sum(len(result['launched']) for result in results), 1)
        self.assertEqual(self.launch.call_count, 1)

    def test_window_receipt_requires_mapping_and_close_does_not_approve(self):
        from types import SimpleNamespace
        desktop.configure(self.ledger, True)
        self.change('blocked')
        record = self.records()[0]
        test = self

        class Widget:
            def __init__(self, *args, **kwargs): pass
            def pack(self, **kwargs): pass
            def insert(self, *args): pass
            def configure(self, **kwargs): pass

        class Window(Widget):
            def title(self, *args): pass
            def geometry(self, *args): pass
            def attributes(self, *args): pass
            def after(self, *args): pass
            def destroy(self): pass
            def winfo_ismapped(self): return True
            def protocol(self, name, callback): self.close = callback
            def bind(self, name, callback): self.map = callback
            def mainloop(self):
                test.assertEqual(test.records()[0]['status'], 'claimed')
                self.map(SimpleNamespace(widget=self))
                self.map(SimpleNamespace(widget=self))
                shown = test.records()[0]
                test.assertEqual(shown['receipt'], 'tk-window-mapped')
                test.assertFalse(shown['user_attention_verified'])
                self.close()

        with patch.dict('sys.modules', {'tkinter':SimpleNamespace(Tk=Window, Label=Widget, Frame=Widget, Button=Widget),
                                       'tkinter.scrolledtext':SimpleNamespace(ScrolledText=Widget)}):
            desktop_window.show(desktop.directory(self.ledger), record['id'])
        self.assertEqual(self.records()[0]['status'], 'closed')
        self.assertFalse(self.records()[0]['answers_recorded'])
        self.assertEqual(self.run.state(self.task)[1]['phase'], 'blocked')
        desktop.publish(self.ledger)
        self.assertEqual(self.launch.call_count, 1)

    def test_ui_failure_before_mapping_is_pending_not_delivered(self):
        from types import SimpleNamespace
        desktop.configure(self.ledger, True)
        self.change('failed')
        record = self.records()[0]
        def fail(): raise RuntimeError('No desktop')
        with patch.dict('sys.modules', {'tkinter':SimpleNamespace(Tk=fail),
                                       'tkinter.scrolledtext':SimpleNamespace(ScrolledText=None)}):
            with self.assertRaisesRegex(RuntimeError, 'No desktop'):
                desktop_window.show(desktop.directory(self.ledger), record['id'])
        self.assertEqual(self.records()[0]['status'], 'pending')
        self.assertNotIn('shown_at', self.records()[0])


if __name__=='__main__':
    unittest.main()
