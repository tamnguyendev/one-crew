"""Codex review of 07d7ad6 (14/10/2026): R1 progress in work mode, R2 failure replay, R3 transient admission, R4 priority.

The three Codex probes (D:\\TamNT\\Workspace\\9.VMAgent\\review-07d7ad6-probes.py) are reproduced here as regressions; the
negative controls keep real loops, no-op/failed writes and timestamp-only output from counting as progress. Red on 07d7ad6
by behaviour, green after the fix."""
import hashlib
import json
from pathlib import Path
import sqlite3
import unittest
from unittest.mock import patch

from onecrew import host
from onecrew import work_tools as wt
from onecrew.ledger import LedgerError
from onecrew.progress import observe
from tests.test_host import HostFixture, at
from tests.test_work_boundary import PY, program
from tests.test_work_contract import WorkFixture, action


def sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


def on_disk(path):
    """Exact bytes as text (no newline translation: the checkout may use CRLF) and their sha256."""
    data = Path(path).read_bytes()
    return data.decode('utf-8'), hashlib.sha256(data).hexdigest()


class ProgressFixture(WorkFixture):
    def open(self, responses=(), **authority):
        runtime, task, worker = self.job(self.contract(edit=True, commands=True, **authority), list(responses))
        return runtime, task, worker

    def invoke(self, runtime, task, state, profile, name, args):
        """The Codex probe's way of driving one tool call (no model): tool, receipt, observe."""
        try: result = runtime._tool(task, state, name, args, profile)
        except (ValueError, OSError) as error: result = {'error': str(error)}
        record = {'action': name, 'arguments': args, 'request': args, 'result': result}
        state['receipts'].append({'index': len(state['receipts']), 'action': name, 'successful': 'error' not in result,
                                  'blob': runtime.store.blob(json.dumps(record).encode())})
        observe(state, name, args, result)
        return result

    def driven(self):
        runtime, task, _ = self.open()
        state = runtime.state(task)[1]; state['phase'] = 'running'
        return runtime, task, state, runtime.control.status(task)['configuration']['profile']

    def calc(self, state):
        return Path(state['work']['workspace']['path']) / 'calc.py'


@unittest.skipIf(PY is None, 'needs a real Python interpreter on PATH')
class ProgressTests(ProgressFixture):
    """R1: the same tool result after a real change of the workspace is new evidence; with nothing changed it is a repeat."""

    def test_codex_probe_lists_between_real_edits_are_progress(self):
        runtime, task, state, profile = self.driven()
        for index in range(3):
            self.invoke(runtime, task, state, profile, 'list', {})
            if index < 2:
                _, digest = on_disk(self.calc(state))
                self.invoke(runtime, task, state, profile, 'write', {'path': 'calc.py', 'expected_sha256': digest,
                                                                     'text': f'def add(a,b):\n    return a + b + {index}\n'})
        self.assertEqual(state['phase'], 'running', 'RED-R1: real edits between identical lists were called no progress: '
                         + str(state.get('message')))

    def test_the_runner_reaches_past_the_m2_block_point(self):
        """The M2 shape through the real runner: list, edit, list, edit, list, edit, list."""
        runtime, task, _ = self.open()
        _, original = on_disk(self.calc(runtime.state(task)[1]))
        texts = [f'def add(a, b):\n    return a + b + {i}\n' for i in range(3)]
        digests = [original] + [sha(t) for t in texts]
        responses = []
        for i, text in enumerate(texts):
            responses += [action('list'), action('write', path='calc.py', expected_sha256=digests[i], text=text)]
        responses.append(action('list'))
        runtime, task, _ = self.job(self.contract(edit=True, commands=True), responses, key='m2-shape')
        state = runtime.run(task, steps=len(responses))
        self.assertEqual(state['phase'], 'running', 'RED-R1: ' + str(state.get('message')))
        self.assertEqual(state['step'], len(responses))

    def test_a_real_loop_without_changes_is_still_stopped(self):
        runtime, task, state, profile = self.driven()
        for _ in range(3): self.invoke(runtime, task, state, profile, 'list', {})
        self.assertEqual(state['phase'], 'blocked')
        self.assertIn('Repeated equivalent tool result', state['message'])

    def test_no_op_and_failed_writes_are_not_progress(self):
        for mode in ('no-op', 'failed'):
            runtime, task, state, profile = self.driven()
            for index in range(3):
                self.invoke(runtime, task, state, profile, 'list', {})
                if index < 2:
                    current, digest = on_disk(self.calc(state))
                    args = ({'path': 'calc.py', 'expected_sha256': digest, 'text': current} if mode == 'no-op' else
                            {'path': 'calc.py', 'expected_sha256': '0' * 64, 'text': 'x = 1\n'})
                    self.invoke(runtime, task, state, profile, 'write', args)
            self.assertEqual(state['phase'], 'blocked', mode + ' write was counted as progress')

    def test_timestamps_and_rewritten_caches_are_not_progress(self):
        (self.root / '.gitignore').write_text('.cache/\n'); self.git('add', '.gitignore'); self.git('commit', '-q', '-m', 'ignore')
        runtime, task, state, profile = self.driven()
        noisy = program("import datetime, os, time\nos.makedirs('.cache', exist_ok=True)\n"
                        "open('.cache/run.log', 'a').write(str(time.time()))\n"
                        "print('finished at', datetime.datetime.now().isoformat(), 'in 12ms')\n")
        for _ in range(3): self.invoke(runtime, task, state, profile, 'run', {'argv': [PY, '-c', noisy]})
        self.assertEqual(state['phase'], 'blocked', 'a command that only rewrites a cache and prints a timestamp is progress')

    def test_a_generated_ignored_output_is_progress(self):
        (self.root / '.gitignore').write_text('generated/\n'); self.git('add', '.gitignore'); self.git('commit', '-q', '-m', 'ignore')
        runtime, task, state, profile = self.driven()
        build = program("import os\nos.makedirs('generated', exist_ok=True)\nopen('generated/out.txt', 'w').write('1')\n")
        self.invoke(runtime, task, state, profile, 'list', {})
        self.invoke(runtime, task, state, profile, 'list', {})
        self.invoke(runtime, task, state, profile, 'run', {'argv': [PY, '-c', build]})
        self.invoke(runtime, task, state, profile, 'list', {})  # the candidate listing is unchanged; generated/ is new
        self.assertEqual(state['phase'], 'running', str(state.get('message')))

    def test_progress_state_survives_restart(self):
        runtime, task, _ = self.open()
        state = runtime.state(task)[1]
        state['phase'] = 'running'; profile = runtime.control.status(task)['configuration']['profile']
        self.invoke(runtime, task, state, profile, 'list', {})
        self.invoke(runtime, task, state, profile, 'list', {})
        runtime.persist(task, runtime.state(task)[0], state)
        restored = runtime.state(task)[1]  # what a restarted runner reads
        self.assertEqual(restored['work']['progress_state'], state['work']['progress_state'])
        self.invoke(runtime, task, restored, profile, 'list', {})
        self.assertEqual(restored['phase'], 'blocked', 'the repeat count was lost across the restart')


@unittest.skipIf(PY is None, 'needs a real Python interpreter on PATH')
class FailureReplayTests(ProgressFixture):
    """R2: a failed read is replayed only while nothing that changes files has succeeded since."""

    def test_codex_probe_a_file_created_after_a_failed_read_is_read(self):
        runtime, task, state, profile = self.driven()
        first = self.invoke(runtime, task, state, profile, 'read', {'path': 'generated.txt'})
        self.invoke(runtime, task, state, profile, 'write', {'path': 'generated.txt', 'text': 'now exists\n', 'expected_sha256': None})
        second = self.invoke(runtime, task, state, profile, 'read', {'path': 'generated.txt'})
        self.assertIn('error', first)
        self.assertEqual(second.get('text'), 'now exists\n', 'RED-R2: the earlier failure was replayed after the file was created')

    def test_a_build_output_created_by_a_command_is_read(self):
        (self.root / '.gitignore').write_text('generated/\n'); self.git('add', '.gitignore'); self.git('commit', '-q', '-m', 'ignore')
        runtime, task, state, profile = self.driven()
        build = program("import os\nos.makedirs('generated', exist_ok=True)\nopen('generated/currencies.json', 'w').write('{}')\n")
        self.assertIn('error', self.invoke(runtime, task, state, profile, 'read', {'path': 'generated/currencies.json'}))
        self.invoke(runtime, task, state, profile, 'run', {'argv': [PY, '-c', build]})
        again = self.invoke(runtime, task, state, profile, 'read', {'path': 'generated/currencies.json'})
        self.assertEqual(again.get('text'), '{}', 'RED-R2: ' + str(again))

    def test_with_nothing_changed_the_failure_is_replayed(self):
        runtime, task, state, profile = self.driven()
        self.invoke(runtime, task, state, profile, 'read', {'path': 'missing.txt'})
        self.invoke(runtime, task, state, profile, 'list', {})
        replay = self.invoke(runtime, task, state, profile, 'read', {'path': 'missing.txt'})
        self.assertTrue(replay.get('error', '').startswith('Identical to receipt 0'), 'control: the unchanged failure is replayed')

    def test_restore_counts_as_a_change(self):
        runtime, task, state, profile = self.driven()
        self.invoke(runtime, task, state, profile, 'write', {'path': 'notes.md', 'text': 'x\n', 'expected_sha256': None})
        self.invoke(runtime, task, state, profile, 'restore', {'paths': ['notes.md']})
        missing = self.invoke(runtime, task, state, profile, 'read', {'path': 'notes.md'})
        self.assertIn('error', missing)
        self.invoke(runtime, task, state, profile, 'write', {'path': 'notes.md', 'text': 'y\n', 'expected_sha256': None})
        self.assertEqual(self.invoke(runtime, task, state, profile, 'read', {'path': 'notes.md'}).get('text'), 'y\n')


@unittest.skipIf(PY is None, 'needs a real Python interpreter on PATH')
class VerificationFeedbackTests(ProgressFixture):
    """Live M1 resume (14/10/2026): a clean-checkout failure must tell the worker why, not only 'exit code 1'."""

    def test_a_missing_generated_file_in_the_checkout_points_to_setup(self):
        (self.root / '.gitignore').write_text('generated/\n')
        (self.root / 'test_generated.py').write_text(
            'import unittest\n\n\nclass G(unittest.TestCase):\n    def test_value(self):\n'
            "        self.assertEqual(open('generated/value.txt').read(), '5')\n")
        self.git('add', '.gitignore', 'test_generated.py'); self.git('commit', '-q', '-m', 'generated fixture')
        runtime, task, state, profile = self.driven()
        contract = profile['contract']
        build = program("import os\nos.makedirs('generated', exist_ok=True)\nopen('generated/value.txt', 'w').write('5')\n")
        wt.run(runtime, task, state, contract, {'argv': [PY, '-c', build]}, lambda: None)  # the workspace has it, ignored
        result = wt.verify(runtime, task, state, contract, {'verification': [{'argv': [PY, '-m', 'unittest', '-v']}]}, lambda: None)
        finding = next(f for f in result['findings'] if f.startswith('core re-run failed'))
        self.assertIn('clean checkout', finding, 'RED-M1: the worker is not told why the clean re-run failed: ' + finding)
        self.assertIn('generated/', finding); self.assertIn('setup', finding); self.assertIn('output tail', finding)


@unittest.skipIf(PY is None, 'needs a real Python interpreter on PATH')
class LatestResultTests(ProgressFixture):
    """Live M2 resume (14/10/2026): a receipt the worker asked for must reach its next prompt under Kiro's cap."""

    def test_the_last_result_reaches_the_worker_even_when_the_packet_is_at_its_minimum(self):
        runtime, task, state, profile = self.driven()
        # Created by one command, so no other receipt names these files: only the listing can show them.
        make = program("import os\nos.makedirs('reports', exist_ok=True)\n"
                       "for i in range(18): open('reports/report_%02d.py' % i, 'w').write('VALUE = %d\\n' % i)\n")
        self.invoke(runtime, task, state, profile, 'run', {'argv': [PY, '-c', make]})
        listing = self.invoke(runtime, task, state, profile, 'list', {'directory': 'reports'})
        self.invoke(runtime, task, state, profile, 'receipt', {'index': len(state['receipts']) - 1})
        from onecrew.ledger import canonical
        size = len(canonical({'action': 'list', 'result': listing}))
        self.assertTrue(1200 < size <= 1500, 'fixture: the listing must exceed the minimum packet and fit the latest result: %d' % size)
        from onecrew.owned import contract as tools
        prompt, schema, _ = tools(profile)
        # What Kiro's cap forced in live M2: the smallest evidence packet (limit 1200, manifest 8).
        with patch.object(type(runtime), '_fit', lambda self, profile, schema, build: build(1200, 8)):
            text = runtime._work_prompt(task, state, profile, runtime.control.status(task), prompt, schema, [])
        self.assertIn('reports/report_17.py', text[len(prompt):], 'RED-M2: the worker never sees the receipt it asked for')
        latest = json.loads(text[len(prompt):]).get('latest_result') or {}
        listed = len(state['receipts']) - 2
        self.assertEqual(latest.get('shows_receipt'), listed, 'the worker is not told which receipt it is looking at')
        self.assertIn('do not request it again', latest.get('note', ''))

    def test_the_worker_sees_which_files_it_has_changed(self):
        runtime, task, state, profile = self.driven()
        from onecrew.owned import contract as tools
        prompt, schema, _ = tools(profile)
        def changes():
            with patch.object(type(runtime), '_fit', lambda self, profile, schema, build: build(1200, 8)):
                text = runtime._work_prompt(task, state, profile, runtime.control.status(task), prompt, schema, [])
            return json.loads(text[len(prompt):]).get('workspace_changes') or {}
        self.invoke(runtime, task, state, profile, 'list', {'directory': ''})
        self.assertEqual(changes().get('count'), 0, 'control: nothing changed yet')
        text, digest = on_disk(self.calc(state))
        self.invoke(runtime, task, state, profile, 'write', {'path': 'calc.py', 'expected_sha256': digest, 'text': text + '# fixed\n'})
        self.invoke(runtime, task, state, profile, 'write', {'path': 'notes/added.py', 'expected_sha256': None, 'text': 'X = 1\n'})
        self.assertEqual(sorted(changes().get('paths', [])), ['A notes/added.py', 'M calc.py'],
                         'RED-M2: the worker cannot tell which files it already changed')
        self.invoke(runtime, task, state, profile, 'restore', {'paths': ['calc.py']})
        self.assertEqual(changes().get('paths'), ['A notes/added.py'], 'a restored file is no longer listed')
        self.assertIn('plan is your only memory', prompt)


class AdmissionRetryTests(HostFixture):
    """R3: a transient ledger error never loses a dispatch, never launches twice, and ends with a reason when it persists."""

    def test_codex_probe_a_busy_ledger_keeps_the_request_and_admits_later(self):
        request = self.request()
        with patch('onecrew.host._task_view', side_effect=sqlite3.OperationalError('database is locked')):
            first = self.scan(0)
        queued = list(host.queue_dir(self.ledger.state_root).glob('HD-*.json'))
        self.assertEqual([a['action'] for a in first], ['retrying'], 'RED-R3: ' + str(first))
        self.assertEqual(len(queued), 1, 'RED-R3: the request was moved to done after a transient error')
        self.assertEqual(self.scan(1), [])  # backing off
        self.scan(3)
        self.assertEqual(self.launched, [self.task])
        self.assertTrue((Path(self.ledger.state_root) / 'host' / 'done' / (request['id'] + '.json')).exists())
        self.assertFalse(host._retry_path(self.ledger.state_root, request['id']).exists())

    def test_busy_while_recording_the_outcome_after_a_launch_does_not_launch_again(self):
        self.request()
        original = host._event
        calls = {'n': 0}
        def flaky(ledger, task, kind, payload):
            if kind == 'host.admitted' and calls['n'] == 0:
                calls['n'] += 1; raise sqlite3.OperationalError('database is locked')
            return original(ledger, task, kind, payload)
        with patch('onecrew.host._event', side_effect=flaky), patch('onecrew.supervisor.probe', return_value='alive'):
            self.scan(0)
            self.scan(10)
        self.assertEqual(self.launched, [self.task], 'RED-R3: the runner was launched again after its outcome was not recorded')
        admitted = self.events('host.admitted')
        self.assertEqual(len(admitted), 1); self.assertFalse(admitted[0]['launched'])

    def test_a_persistently_busy_ledger_ends_with_a_block_and_the_reason(self):
        request = self.request()
        with patch('onecrew.host._task_view', side_effect=sqlite3.OperationalError('database is locked')):
            for second in range(0, 400, 7): self.scan(second)
        self.assertEqual(self.launched, [])
        state = self.phase()
        self.assertEqual(state['phase'], 'blocked', 'RED-R3: the task stays running with no runner')
        self.assertIn('could not admit', state['message']); self.assertIn('database is locked', state['message'])
        self.assertTrue((Path(self.ledger.state_root) / 'host' / 'done' / (request['id'] + '.json')).exists())
        self.assertEqual(len(self.events('host.admission_failed')), 1)

    def test_a_malformed_request_is_still_ended_at_once(self):
        path = host.queue_dir(self.ledger.state_root) / 'HD-bad.json'; path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{"id": "HD-bad"}')
        self.assertEqual(self.scan(0)[0]['action'], 'failed')
        self.assertFalse(path.exists())

    def test_the_entry_retries_a_busy_ledger_and_reports_a_lasting_one(self):
        from onecrew import owned_cli
        argv = ['--project', str(self.root), '--state-root', str(self.ledger.state_root), 'job', 'start', self.task]
        busy = sqlite3.OperationalError('database is locked')
        with patch('onecrew.owned.Owned.enable', side_effect=[busy, busy, None]), \
                patch('onecrew.runner.start', return_value={'status': 'queued'}), patch('time.sleep'):
            self.assertEqual(owned_cli.main(argv), 0)
        with patch('onecrew.owned.Owned.enable', side_effect=busy), patch('time.sleep'):
            self.assertEqual(owned_cli.main(argv), 2)
        log = Path(self.ledger.state_root) / 'diagnostics' / 'entry-errors.jsonl'
        record = json.loads(log.read_text(encoding='utf-8').splitlines()[-1])
        self.assertIn('stayed busy', record['error']); self.assertIn('Traceback', record['trace'])


class PriorityTests(unittest.TestCase):
    """R4: the host task and the runners it starts run at Normal priority, never inheriting below-normal."""

    def test_the_host_task_runs_at_normal_priority(self):
        self.assertIn('<Priority>5</Priority>', host.task_xml(Path(host.__file__).resolve().parents[1], user='D\\u'))

    def test_runners_are_started_at_normal_priority(self):
        captured = {}
        class Process:
            pid = 4321
        def popen(*args, **kwargs):
            captured.update(kwargs); return Process()
        request = {'task': 'TASK-x', 'project': 'P', 'state_root': str(Path(__file__).resolve().parent / '_unused_state'),
                   'runtime': str(Path(host.__file__).resolve().parents[1]), 'id': 'HD-x'}
        with patch('subprocess.Popen', side_effect=popen), patch('onecrew.supervisor.identity', return_value={'pid': 4321}), \
                patch('pathlib.Path.mkdir'), patch('pathlib.Path.open', unittest.mock.mock_open()):
            host._launch(request)
        self.assertTrue(captured['creationflags'] & 0x20, 'RED-R4: the runner inherits the host priority class')
        self.assertFalse(captured['creationflags'] & (0x80 | 0x100), 'never High or Realtime')


if __name__ == '__main__':
    unittest.main()
