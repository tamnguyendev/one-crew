"""Codex review of P4b (14/10/2026) on 55448b8: the two branches P4b left open.

R3 (migration): a supervision file written before P4b (no reconciliation map) marked every launch record as handled, so a
runner admitted and launched by the old host whose supervision write had failed was never supervised after the upgrade. A
release must now be shown by durable evidence (the ledger since that launch), not assumed for every record.
R4 (progress guard): the guard took an unchanged but incomplete workspace key as proof that nothing changed, while the
failed-command check and the failed-read replay did not: three same-size rewrites of .venv/lib/dep.py, each followed by the
same listing, ended with "nothing changed". One trust rule now serves all three.

Fixtures are temporary (no task, host or ledger of the machine): the real scan with real Windows locks, the real runtime with
real commands in the isolated workspace. Controls keep the guards: no duplicate runner, released, waiting, cancelled and
paused tasks stay released (also when that state was already there at the launch), a read loop and no-op churn are still
stopped. Tests marked "Adversarial review" come from the review of the first draft of this fix (14/10/2026): cases that draft
got wrong (a state in force at the launch, an admission recorded as not launched, a background process started before the
failed command, an upgrade right after a change, the reason of an immediate repeat)."""
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from onecrew.control import Control
from onecrew.owned import Owned
from tests.test_host import HostFixture
from tests import test_review_p3
from tests.test_review_p3 import Locked
from tests.test_work_boundary import PY, program
from tests.test_work_contract import WorkFixture, action

QUESTION = {'schema_version': 1, 'question': 'Proceed?', 'reason': 'Decision required', 'impact': 'The task waits',
            'options': [{'id': 'a', 'label': 'A'}, {'id': 'b', 'label': 'B'}], 'recommendation': 'a',
            'action': {'type': 'noop', 'parameters': {}}}


# --- R3: a supervision file written before P4b ------------------------------------------------------------------------------

class LegacySupervisionTests(HostFixture):
    dispatched = test_review_p3.HostQueueTests.dispatched

    def supervised(self):
        return Path(self.ledger.state_root) / 'host' / 'supervised.json'

    def admitted_without_supervision(self):
        """On disk exactly what the host before P4b leaves when an admission succeeded and its supervision write failed: a
        supervision file without a reconciliation map and without the task, a 'launched' record, host.admitted in the ledger."""
        path = self.supervised(); path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({'tasks': {}}))  # as written by 198a640 and earlier
        self.dispatched()
        with Locked(path, share=0x1):  # readable; the write after the launch fails
            self.scan(0)
        self.assertEqual(json.loads(path.read_text()), {'tasks': {}}, 'fixture: the supervision was not saved')
        self.assertTrue(self.events('host.admitted')[-1]['launched'])

    def launches(self):
        return self.launched.count(self.task)

    def test_a_runner_admitted_before_the_upgrade_whose_supervision_was_never_saved_is_recovered_once(self):
        self.admitted_without_supervision()
        actions = self.scan(5) + self.scan(40)  # the upgraded host; the runner launched before is gone
        actions += self.scan(60, status='alive') + self.scan(200, status='alive')  # the restarted runner runs
        self.assertEqual([a.get('action') for a in actions if a.get('task') == self.task].count('restarted'), 1,
                         'RED-R3b: the launched runner was never supervised after the upgrade: ' + str(actions))
        self.assertEqual(self.launches(), 2, 'one launch before the upgrade, exactly one restart after it')
        saved = json.loads(self.supervised().read_text())
        self.assertIn(self.task, saved['tasks']); self.assertIn(self.task, saved['reconciled'])

    def test_a_runner_still_running_at_the_upgrade_is_recovered_even_after_an_answered_question(self):
        self.admitted_without_supervision()
        question = self.ledger.create_request(self.task, 'q-answered', QUESTION)
        self.ledger.reply(question['id'], question['revision'], 'a')
        with patch('onecrew.supervisor.probe', return_value='alive'):  # the runner launched before the upgrade still runs
            self.assertEqual(self.scan(5, status='alive'), [])  # supervised, nothing to do: no second runner
        actions = self.scan(40) + self.scan(60) + self.scan(200, status='alive')  # then it dies
        self.assertEqual([a.get('action') for a in actions if a.get('task') == self.task].count('restarted'), 1,
                         'RED-R3b: a running task was left unsupervised after the upgrade: ' + str(actions))
        self.assertEqual(self.launches(), 2)

    def test_a_task_released_before_the_upgrade_is_not_revived(self):
        self.admitted_without_supervision()
        # The old host released it when it blocked and its runner ended; later it was set running again outside the host.
        runtime = Owned(self.ledger)
        seq, state = runtime.state(self.task); state['phase'] = 'blocked'; runtime.persist(self.task, seq, state)
        seq, state = runtime.state(self.task); state['phase'] = 'running'; runtime.persist(self.task, seq, state)
        for second in (5, 40, 100, 400, 900): self.scan(second)
        self.assertEqual(self.launches(), 1, 'a task released before the upgrade was revived')
        self.assertNotIn(self.task, json.loads(self.supervised().read_text())['tasks'])

    def test_waiting_cancelled_and_paused_tasks_are_not_restarted_after_the_upgrade(self):
        tasks = {}
        for kind in ('question', 'cancel', 'pause'):
            self.task = self.job(self.contract(local_branches=['b-' + kind]), [], key='legacy-' + kind)[1]
            self.admitted_without_supervision(); tasks[kind] = self.task
        self.ledger.create_request(tasks['question'], 'q-pending', QUESTION)
        Control(self.ledger).cancel(tasks['cancel']); Control(self.ledger).pause(tasks['pause'])
        for second in (5, 40, 100, 400, 900): self.scan(second)
        self.assertEqual(sorted(self.launched), sorted(tasks.values()), 'a waiting, cancelled or paused task was restarted')

    def test_a_task_waiting_already_at_its_launch_is_not_revived_after_the_upgrade(self):
        # Adversarial review: _admit does not refuse a blocked, paused or questioning task; the old host released it once its
        # runner was gone, with no event after the launch. Each state is then cleared outside the host.
        tasks = {}
        for kind in ('question', 'blocked', 'pause'):
            self.task = self.job(self.contract(local_branches=['w-' + kind]), [], key='at-launch-' + kind)[1]
            runtime = Owned(self.ledger)
            if kind == 'question': question = self.ledger.create_request(self.task, 'q-before-launch', QUESTION)
            if kind == 'blocked':
                seq, state = runtime.state(self.task); state['phase'] = 'blocked'; runtime.persist(self.task, seq, state)
            if kind == 'pause': Control(self.ledger).pause(self.task)
            self.admitted_without_supervision(); tasks[kind] = self.task
            if kind == 'question': self.ledger.reply(question['id'], question['revision'], 'a')
            seq, state = runtime.state(self.task); state['phase'] = 'running'
            runtime.persist(self.task, seq, state, unpause=kind == 'pause')
        for second in (5, 40, 100, 400, 900): self.scan(second)
        self.assertEqual(sorted(self.launched), sorted(tasks.values()), 'a task released for its state at launch was revived')

    def test_an_alive_runner_whose_admission_was_recorded_as_not_launched_is_recovered(self):
        # Adversarial review: the ledger write of host.admitted failed after the launch; the retry found the runner as owner
        # and recorded launched=False; the supervision write failed. The runner still runs at the upgrade.
        import sqlite3
        from onecrew import host
        path = self.supervised(); path.parent.mkdir(parents=True, exist_ok=True); path.write_text(json.dumps({'tasks': {}}))
        self.dispatched(); real, calls = host._event, []
        def flaky(ledger, task, kind, payload):
            if kind == 'host.admitted' and not calls: calls.append(kind); raise sqlite3.OperationalError('database is locked')
            return real(ledger, task, kind, payload)
        with Locked(path, share=0x1):
            with patch('onecrew.host._event', side_effect=flaky): self.scan(0)
            self.scan(3, status='alive')
        self.assertEqual([a['launched'] for a in self.events('host.admitted')], [False], 'fixture')
        with patch('onecrew.supervisor.probe', return_value='alive'): self.scan(10, status='alive')
        self.assertIn(self.task, json.loads(path.read_text())['tasks'], 'RED-R3b: an alive runner missing supervision was '
                      'not recovered')
        self.assertEqual(self.launches(), 1, 'no second runner')

    def test_a_runner_that_ended_by_itself_after_its_question_was_answered_is_recovered(self):
        # Adversarial review: the question was asked and answered while the runner ran (nothing could be released then);
        # the runner then ended by itself with the task running.
        self.admitted_without_supervision()
        from onecrew import host
        record = json.loads(host._launch_record(self.ledger.state_root, self.task).read_text())
        question = self.ledger.create_request(self.task, 'q-while-running', QUESTION)
        self.ledger.reply(question['id'], question['revision'], 'a')
        with self.ledger.transaction(write=True) as conn:
            self.ledger._event(conn, self.task, 'runner.stopped', {'identity': record['identity'], 'outcome': 'interrupted'})
        actions = self.scan(5) + self.scan(40) + self.scan(60, status='alive') + self.scan(200, status='alive')
        self.assertEqual([a.get('action') for a in actions if a.get('task') == self.task].count('restarted'), 1,
                         'RED-R3b: ' + str(json.loads(self.supervised().read_text()).get('not_revived')))
        self.assertEqual(self.launches(), 2)

    def test_a_record_unread_during_the_first_scan_after_the_upgrade_is_judged_by_the_same_evidence(self):
        self.admitted_without_supervision()
        runtime = Owned(self.ledger)
        seq, state = runtime.state(self.task); state['phase'] = 'blocked'; runtime.persist(self.task, seq, state)
        seq, state = runtime.state(self.task); state['phase'] = 'running'; runtime.persist(self.task, seq, state)
        from onecrew import host
        with Locked(host._launch_record(self.ledger.state_root, self.task)):  # the record cannot be read in the first scan
            self.scan(5)
        self.assertIn('reconciled', json.loads(self.supervised().read_text()), 'fixture: the first scan wrote the new format')
        for second in (40, 100, 400): self.scan(second)
        self.assertEqual(self.launches(), 1, 'RED-R3b: a record read only after the upgrade revived a released task')


# --- R4: one trust rule for the workspace key ---------------------------------------------------------------------------------

@unittest.skipIf(PY is None, 'needs a real Python interpreter on PATH')
class ProgressTrustTests(WorkFixture):
    CHECK = ("import sys\ntry: value = open('.venv/lib/dep.py').read()\nexcept OSError: value = None\n"
             "print('dependency', value)\nsys.exit(0 if value == 'correct' else 1)\n")

    def setUp(self):
        super().setUp()
        (self.root / '.gitignore').write_text('.venv/\ngenerated/\n__pycache__/\n*.log\n')
        (self.root / 'check.py').write_text(self.CHECK)
        self.git('add', '.gitignore', 'check.py'); self.git('commit', '-q', '-m', 'check')

    def job_of(self, responses):
        runtime, task, _ = self.job(self.contract(edit=True, commands=True), responses, key='r4b-' + os.urandom(3).hex())
        return runtime, task

    def results(self, runtime, task):
        state = runtime.state(task)[1]
        return [json.loads(runtime.store.read_blob(r['blob']))['result'] for r in state['receipts']], state

    def dep(self, content):
        """A command that rewrites the Git-ignored dependency file (exit 0); every content used here has 5 characters."""
        return action('run', argv=[PY, '-c', program("import os\nos.makedirs('.venv/lib', exist_ok=True)\n"
                                                     f"open('.venv/lib/dep.py', 'w').write({content!r})\n")])

    def listing(self):
        return action('list', directory='')

    def run_all(self, responses):
        runtime, task = self.job_of(responses)
        runtime.run(task, steps=len(responses))
        return self.results(runtime, task)

    def test_same_size_dependency_changes_between_identical_listings_are_not_called_unchanged(self):
        # Codex: wrong -> list -> right -> list -> final -> list; three contents of the same size, every write exit 0.
        results, state = self.run_all([self.dep('wrong'), self.listing(), self.dep('right'), self.listing(),
                                       self.dep('final'), self.listing()])
        self.assertEqual([r.get('exit_code') for r in results[0::2]], [0, 0, 0])
        self.assertEqual(state['phase'], 'running', 'RED-R4b: ' + str(state.get('message')))
        self.assertNotIn('error', results[5])

    def test_real_changes_beyond_the_bound_are_stopped_without_claiming_nothing_changed(self):
        values = ['aaaaa', 'bbbbb', 'ccccc', 'ddddd', 'eeeee', 'fffff']
        responses = [step for value in values for step in (self.dep(value), self.listing())]
        results, state = self.run_all(responses)
        self.assertEqual(state['phase'], 'blocked', 'unbounded: real changes the key cannot see were allowed forever')
        self.assertNotIn('with nothing changed in between', state['message'],
                         'RED-R4b: the guard claims nothing changed although the dependency was rewritten: ' + state['message'])
        self.assertIn('cannot show', state['message'])
        self.assertLessEqual(len(results), 10, 'the bound is the limit plus INPUT_RERUNS repeats of the same result')

    def test_identical_listings_with_nothing_run_in_between_are_still_a_repeat(self):
        results, state = self.run_all([self.dep('wrong'), self.listing(), self.listing(), self.listing()])
        self.assertEqual(state['phase'], 'blocked'); self.assertIn('with nothing changed in between', state['message'])

    def test_no_op_churn_between_identical_listings_is_still_bounded(self):
        churn = action('run', argv=[PY, '-c', program("open('run.log', 'a').write('x')\n")])
        results, state = self.run_all([self.dep('wrong'), self.listing(), churn, self.listing(), churn, self.listing(),
                                       churn, self.listing(), churn, self.listing()])
        self.assertEqual(state['phase'], 'blocked', 'no-op churn made an identical listing look like progress')
        self.assertLessEqual(len(results), 8)

    def test_an_older_checkpoint_keeps_its_counters_and_a_later_change_is_not_called_unchanged(self):
        runtime, task = self.job_of([self.dep('wrong'), self.listing(), self.listing(), self.dep('right'), self.listing(),
                                     self.listing()])
        runtime.run(task, steps=3)
        seq, state = runtime.state(task)
        for name in ('observed_at', 'observed_from', 'unproven'): state['progress'].pop(name, None)  # as written by 55448b8
        counts = dict(state['progress']['results']); runtime.persist(task, seq, state)
        state = runtime.run(task, steps=2)
        self.assertEqual(state['phase'], 'running', 'RED-R4b: ' + str(state.get('message')))
        self.assertTrue(all(state['progress']['results'][k] >= v for k, v in counts.items()), 'a counter was reset')
        state = runtime.run(task, steps=1)  # the same listing again with nothing run in between: the kept counter stops it
        self.assertEqual(state['phase'], 'blocked', str(state.get('message')))

    def test_an_older_checkpoint_upgraded_right_after_a_change_does_not_call_the_next_listing_unchanged(self):
        # Adversarial review: Codex's sequence with the runtime upgraded between the last rewrite and the listing.
        runtime, task = self.job_of([self.dep('wrong'), self.listing(), self.dep('right'), self.listing(), self.dep('final'),
                                     self.listing()])
        # 55448b8 trusted the incomplete key (create=True: on 55448b8 itself the helper does not exist and is not needed)
        with patch('onecrew.work_tools.key_unproven', return_value=False, create=True):
            runtime.run(task, steps=5)
        seq, state = runtime.state(task)
        for name in ('observed_at', 'unproven'): state['progress'].pop(name, None)  # as written by 55448b8
        self.assertEqual(max(state['progress']['results'].values()), 2, 'fixture: the old runtime counted the second listing')
        runtime.persist(task, seq, state)
        state = runtime.run(task, steps=1)
        self.assertEqual(state['phase'], 'running', 'RED-R4b: ' + str(state.get('message')))

    def test_an_immediate_repeat_is_named_as_such_after_a_real_change_used_one_allowance(self):
        # Adversarial review: the block reason follows the last repeat (nothing ran in between), not an earlier allowance.
        results, state = self.run_all([self.dep('wrong'), self.listing(), self.listing(), self.dep('right'), self.listing(),
                                       self.listing()])
        self.assertEqual(len(results), 6, 'RED-R4b: the listing after a real change was counted as unchanged: '
                         + str(state.get('message')))
        self.assertEqual(state['phase'], 'blocked'); self.assertIn('with nothing changed in between', state['message'])

    def test_a_background_process_started_before_the_failed_command_is_a_possible_change(self):
        # Adversarial review: the background process rewrites the dependency (same size) after the check failed; nothing
        # else ran in between. The rerun must not be refused as "nothing changed".
        import time
        from onecrew import work_tools as wt
        (self.root / '.gitignore').write_text('.venv/\ngenerated/\n__pycache__/\n*.log\ntmp/\n')
        self.git('add', '.gitignore'); self.git('commit', '-q', '-m', 'tmp')
        later = action('run', argv=[PY, '-c', program("import os, time\nwhile not os.path.exists('tmp/go'): time.sleep(0.05)\n"
                                                      "open('.venv/lib/dep.py', 'w').write('correct')\nopen('tmp/done', 'w').write('1')\n")],
                       background=True)
        check = action('run', argv=[PY, 'check.py'])
        runtime, task = self.job_of([self.dep('wrong!!'), later, check, check])
        def stop():
            for child, job, record, out, err in wt._RUNNING.pop(task, {}).values():
                try: job.stop()
                finally: job.close(); out.close(); err.close()
        self.addCleanup(stop)
        state = runtime.run(task, steps=3)
        workspace = wt.ws_root(state); (workspace / 'tmp').mkdir(exist_ok=True); (workspace / 'tmp' / 'go').write_text('1')
        for _ in range(200):
            if (workspace / 'tmp' / 'done').exists(): break
            time.sleep(0.05)
        runtime.run(task, steps=1)
        results, _ = self.results(runtime, task)
        self.assertEqual(results[2].get('exit_code'), 1)
        self.assertEqual(results[3].get('exit_code'), 0, str(results[3])[:300])

    def test_one_rule_with_nothing_run_in_between_an_incomplete_key_refuses_like_a_complete_one(self):
        results, _ = self.run_all([self.dep('wrong'), action('run', argv=[PY, 'check.py']), action('run', argv=[PY, 'check.py']),
                                   action('read', path='generated/missing.txt'), action('read', path='generated/missing.txt')])
        self.assertEqual(results[1].get('exit_code'), 1)
        self.assertIn('Nothing changed', results[2].get('error', ''),
                      'RED-R4b: the failed-command check reran on an incomplete key with nothing run in between: ' + str(results[2])[:300])
        self.assertIn('Identical to receipt', results[4].get('error', ''), str(results[4])[:300])

    def test_one_rule_after_a_same_size_change_the_check_and_the_read_run_again_bounded(self):
        fix = action('run', argv=[PY, '-c', program("import os\nos.makedirs('.venv/lib', exist_ok=True)\n"
                                                    "open('.venv/lib/dep.py', 'w').write('correct')\n")])
        check = action('run', argv=[PY, 'check.py'])
        results, state = self.run_all([self.dep('wrong!!'), check, fix, check])
        self.assertEqual(results[3].get('exit_code'), 0, str(results[3])[:300])


if __name__ == '__main__':
    unittest.main()
