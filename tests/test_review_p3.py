"""Codex deep review P3 (14/10/2026) on 63f51cd: A host queue reads, B paging, C ignored inputs, D resume as recovery.

Each class reproduces the reviewed failure through the public runtime (a real Windows lock, the real Kiro prompt cap and
_fit, real commands in the isolated workspace, the official resume) and holds the controls that must not change. Repro
scripts for the baseline: D:\\OneCrewEvals\\gxp4-20261014\\repro\\."""
import ctypes
from ctypes import wintypes as w
import json
import os
from pathlib import Path
import sqlite3
import unittest
from unittest.mock import patch

from onecrew import host
from onecrew import work_tools as wt
from onecrew.ledger import canonical
from onecrew.owned import Owned
from onecrew.owned_intake import submit
from tests.test_host import HostFixture, at
from tests.test_work_boundary import PY, program
from tests.test_work_contract import WorkFixture, action
from tests.test_workflow import FixtureWorker

CAP = Owned.PROMPT_LIMITS['kiro']

# --- a real Windows lock: an open handle that denies reading while allowing rename/delete (the case that lost requests) ----
k32 = ctypes.WinDLL('kernel32', use_last_error=True)
k32.CreateFileW.restype = w.HANDLE
k32.CreateFileW.argtypes = [w.LPCWSTR, w.DWORD, w.DWORD, ctypes.c_void_p, w.DWORD, w.DWORD, w.HANDLE]
k32.CloseHandle.argtypes = [w.HANDLE]


class Locked:
    """Holds `path` open with share mode DELETE only: other processes cannot read it (sharing violation) but can rename it."""
    def __init__(self, path, share=0x4):
        self.path, self.share = Path(path), share

    def __enter__(self):
        self.handle = k32.CreateFileW(str(self.path), 0x80000000, self.share, None, 3, 0x80, None)
        if self.handle in (None, ctypes.c_void_p(-1).value): raise ctypes.WinError(ctypes.get_last_error())
        try: self.path.read_bytes()
        except OSError: return self  # the lock is real: reading fails while it is held
        if self.share & 0x1: return self  # a write lock: readable on purpose, writing and replacing fail
        k32.CloseHandle(self.handle)
        raise AssertionError('fixture: the lock does not deny reading')

    def __exit__(self, *exc):
        k32.CloseHandle(self.handle)


class HostQueueTests(HostFixture):
    """A: a dispatch request that cannot be read for a moment is never dropped, decided twice or launched twice."""

    def dispatched(self):
        """What host.dispatch does: the ledger event first, then the queue file."""
        from onecrew.ledger import utcnow
        request = {'id': 'HD-' + os.urandom(16).hex(), 'task': self.task, 'project': str(self.root.resolve()),
                   'state_root': str(Path(self.ledger.state_root).resolve()), 'runtime': str(Path(host.__file__).resolve().parents[1]),
                   'initiator': 'fixture', 'at': utcnow()}
        with self.ledger.transaction(write=True) as conn: self.ledger._event(conn, self.task, 'host.dispatch', request)
        path = host.queue_dir(self.ledger.state_root) / (request['id'] + '.json'); host._write(path, request)
        return request, path

    def test_a_locked_queue_file_is_admitted_from_the_ledger_once(self):
        request, path = self.dispatched()
        with Locked(path):
            first = self.scan(0)
        self.assertEqual(self.launched, [self.task], 'RED-A: the locked request was dropped: ' + str(first))
        self.assertEqual(first[0]['source'], 'ledger')
        self.assertEqual(len(self.events('host.admitted')), 1)
        later = self.scan(30, status='alive') + self.scan(60, status='alive')  # the runner lives: no supervision restart
        self.assertEqual(self.launched, [self.task], 'decided twice after the lock was released')
        self.assertFalse(path.exists(), 'the decided request stays in the queue: ' + str(later))

    def test_restart_between_retries_keeps_the_request_and_admits_it_once(self):
        request, path = self.dispatched()
        busy = sqlite3.OperationalError('database is locked')
        with Locked(path), patch('onecrew.host._dispatched', side_effect=busy):
            first = self.scan(0)
        self.assertEqual(first[0]['action'], 'retrying'); self.assertEqual(self.launched, [])
        self.assertTrue(path.exists(), 'RED-A: the request left the queue while it could not be read')
        # A new host process: only the durable queue and retry record remain. Before the backoff ends nothing happens.
        self.assertEqual([a for a in self.scan(1) if a.get('request') == request['id']], [])
        self.scan(10)
        self.assertEqual(self.launched, [self.task])
        self.scan(40, status='alive'); self.scan(100, status='alive')
        self.assertEqual(self.launched, [self.task], 'a second runner')

    def test_real_malformed_json_without_a_ledger_record_is_ended_and_with_one_is_admitted(self):
        stray = host.queue_dir(self.ledger.state_root) / ('HD-' + 'ab' * 16 + '.json')
        stray.write_bytes(b'{"id": "HD-\xff\xfe broken')
        self.assertEqual(self.scan(0)[0]['action'], 'failed'); self.assertFalse(stray.exists())
        request, path = self.dispatched(); path.write_bytes(b'{not json')
        self.scan(1)
        self.assertEqual(self.launched, [self.task], 'a damaged queue file whose request is in the ledger was dropped')

    def test_an_unreadable_launch_record_never_allows_a_second_runner_or_a_false_block(self):
        record = host._launch_record(self.ledger.state_root, self.task); record.parent.mkdir(parents=True, exist_ok=True)
        host._write(record, {'task': self.task, 'request': 'HD-earlier', 'state': 'launching', 'at': at(0).isoformat()})
        request, _ = self.dispatched()
        with Locked(record):
            self.scan(5)
        self.assertEqual(self.launched, [], 'RED-A: launched while the record of a launch in progress could not be read')
        self.assertEqual(self.phase()['phase'], 'running', 'RED-A: blocked by a transient lock: ' + str(self.phase().get('message')))
        self.scan(10)  # readable again, still inside LAUNCH_GRACE of the recorded launch: not launched either
        self.assertEqual(self.launched, [])

    def test_a_launch_record_that_cannot_be_written_defers_instead_of_blocking(self):
        record = host._launch_record(self.ledger.state_root, self.task); record.parent.mkdir(parents=True, exist_ok=True)
        host._write(record, {'task': self.task, 'request': 'HD-old', 'state': 'failed', 'at': at(-3600).isoformat()})
        request, _ = self.dispatched()
        with Locked(record, share=0x1):  # readable, but neither writable nor replaceable
            first = self.scan(0)
        self.assertEqual(first[0]['action'], 'retrying', str(first))
        self.assertEqual(self.phase()['phase'], 'running', 'RED-A: a record that could not be written blocked the task')
        self.scan(10)
        self.assertEqual(self.launched, [self.task])

    def test_an_unreadable_supervision_file_is_neither_overwritten_nor_lost(self):
        request, _ = self.dispatched()
        self.scan(0)
        supervised = Path(self.ledger.state_root) / 'host' / 'supervised.json'
        before = supervised.read_bytes()
        with Locked(supervised):
            deferred = self.scan(30)
        self.assertEqual(deferred[0]['action'], 'deferred')
        self.assertEqual(supervised.read_bytes(), before, 'RED-A: supervision rewritten from an unread file')
        actions = self.scan(60)  # the runner is gone: the supervision restarts it
        self.assertIn('restarted', [a.get('action') for a in actions], str(actions))


class HostReviewTests(HostFixture):
    """Second round (adversarial review of the P4 diff, 14/10/2026): the ledger itself, supervision writes and rebuilds."""
    dispatched = HostQueueTests.dispatched

    def test_a_locked_ledger_never_ends_a_request(self):
        request, path = self.dispatched()
        with Locked(Path(self.ledger.state_root) / 'ledger.sqlite3', share=0):
            first = self.scan(0)
        self.assertTrue(path.exists(), 'the request left the queue while the ledger could not be opened: ' + str(first))
        self.assertNotEqual(first[0]['action'], 'failed')
        self.scan(10)
        self.assertEqual(self.launched, [self.task])

    def test_a_supervision_file_that_cannot_be_replaced_still_supervises_the_launched_runner(self):
        self.scan(0)  # creates supervised.json
        other = self.job(self.contract(local_branches=['other']), [], key='second')[1]
        self.task = other; request, _ = self.dispatched()
        supervised = Path(self.ledger.state_root) / 'host' / 'supervised.json'
        with Locked(supervised, share=0x1):
            self.scan(5)
        self.assertEqual(self.launched, [other])
        actions = self.scan(40) + self.scan(100)  # the runner is gone: it must be restarted, so it is supervised
        self.assertIn('restarted', [a.get('action') for a in actions if a.get('task') == other], str(actions))

    def test_a_corrupt_supervision_file_is_rebuilt_with_restarted_tasks_and_their_restarts(self):
        self.dispatched(); self.scan(0)
        self.scan(20)  # the runner is gone: restart 1 (its launch record now names a restart, not the dispatch)
        supervised = Path(self.ledger.state_root) / 'host' / 'supervised.json'
        supervised.write_bytes(b'{broken')
        self.scan(30, status='alive')
        rebuilt = json.loads(supervised.read_text())
        self.assertIn(self.task, rebuilt['tasks'], 'a restarted task dropped out of the rebuilt supervision')
        self.assertEqual(len(rebuilt['tasks'][self.task]['restarts']), 1, 'the restart bound was reset')
        self.assertTrue(list(supervised.parent.glob('supervised.corrupt-*.json')))

    def test_exhausted_retries_with_an_unreadable_launch_record_do_not_stall_the_root(self):
        record = host._launch_record(self.ledger.state_root, self.task); record.parent.mkdir(parents=True, exist_ok=True)
        host._write(record, {'task': self.task, 'request': 'HD-old', 'state': 'failed', 'at': at(-3600).isoformat()})
        self.dispatched()
        other = self.job(self.contract(local_branches=['other']), [], key='second')[1]
        with Locked(record):
            for second in (0, 3, 9, 20, 41, 82, 200):
                self.scan(second)
            first_task = self.task; self.task = other; self.dispatched(); self.task = first_task
            self.scan(300)  # must not raise; the other task is admitted
        self.assertIn(other, self.launched)

    def test_a_damaged_foreign_request_is_kept_aside_with_its_reason(self):
        stray = host.queue_dir(self.ledger.state_root) / ('HD-' + 'cd' * 16 + '.json'); stray.write_bytes(b'\x00\x01 not json')
        self.scan(0)
        rejected = Path(self.ledger.state_root) / 'host' / 'rejected'
        self.assertTrue((rejected / stray.name).exists())
        self.assertIn('corrupt', (rejected / (stray.stem + '.reason.json')).read_text())


class PagingUnitTests(unittest.TestCase):
    """paging.view on records the runtime stores."""

    def test_git_show_continues_with_its_own_cursor(self):
        from onecrew.paging import view
        record = {'action': 'git_show', 'arguments': {'directory': '', 'commit': 'a' * 40, 'path': 'big.txt'},
                  'result': {'commit': 'a' * 40, 'diff': 'd' * 3000, 'next_cursor': 3000}}
        value, pages = view(record, 1200, index=7)
        last = pages[-1]
        while 'next' in last and last['next']['action'] == 'receipt':
            value, pages = view(record, 1200, index=7, field='diff', offset=last['next']['arguments']['offset']); last = pages[-1]
        self.assertFalse(last['eof'])
        self.assertEqual(last['next'], {'action': 'git_show', 'arguments': {'directory': '', 'commit': 'a' * 40, 'path': 'big.txt',
                                                                           'cursor': 3000}})

    def test_a_cut_read_continues_by_receipt_and_a_list_without_directory_by_its_cursor(self):
        from onecrew.paging import view
        read = {'action': 'read', 'arguments': {'path': 'a.txt'}, 'result': {'path': 'a.txt', 'cursor': 0, 'text': 'x' * 5000, 'next_cursor': None}}
        self.assertEqual(view(read, 1500, index=3)[1][0]['next'], {'action': 'receipt', 'arguments': {'index': 3, 'field': 'text', 'offset': view(read, 1500, index=3)[1][0]['delivered']}})
        listing = {'action': 'list', 'request': {}, 'result': {'entries': [{'path': f'f{i}', 'kind': 'file'} for i in range(40)], 'next_cursor': 40}}
        value, pages = view(listing, 900, index=1)
        end = pages[0]
        while 'next' in end and end['next']['action'] == 'receipt':
            value, pages = view(listing, 900, index=1, field='entries', offset=end['next']['arguments']['offset']); end = pages[0]
        self.assertEqual(end['next'], {'action': 'list', 'arguments': {'directory': '', 'cursor': 40}})

    def test_a_scalar_field_is_delivered_whole(self):
        from onecrew.paging import view
        record = {'action': 'read', 'result': {'path': 'a.txt', 'cursor': 0, 'text': 'x' * 5000, 'next_cursor': None}}
        value, pages = view(record, 1500, index=0, field='cursor', offset=0)
        self.assertEqual(value['result']['cursor'], 0)


# --- B: paging ---------------------------------------------------------------------------------------------------------

def context(prompt):
    return json.loads(prompt[prompt.rindex('\n{') + 1:])


class Follower(FixtureWorker):
    """A worker that obeys the paging contract: scripted first actions, then the `next` (or `from_start`) of the latest
    result's page, until every page is at its end. It records the prompts and every delivered piece."""
    def __init__(self, ledger, first, want_start=False):
        super().__init__(ledger, [])
        self.first, self.want_start, self.prompts, self.pieces, self.done = list(first), want_start, [], [], False

    def run(self, attempt, prompt, schema, profile):
        self.prompts.append((prompt, canonical(schema)))
        latest = context(prompt).get('latest_result') or {}
        result, pages = latest.get('result') or {}, latest.get('page') or []
        for page in pages:
            self.pieces.append({'action': latest.get('action'), 'field': page['field'], 'offset': page['offset'],
                                'value': result.get(page['field']), 'cursor': result.get('cursor'), 'page': page,
                                'path': result.get('path')})
        whole = None
        if not pages and latest.get('result') is not None and latest.get('action') in ('read', 'list'):
            # Delivered whole: the tool's own cursor is accurate and is the continuation.
            field = 'text' if latest['action'] == 'read' else 'entries'
            whole = {'action': latest['action'], 'arguments': {**{k: v for k, v in (latest.get('arguments') or {}).items() if k != 'cursor'},
                                                                'cursor': result.get('next_cursor')}} if result.get('next_cursor') is not None else None
            self.pieces.append({'action': latest['action'], 'field': field, 'offset': 0, 'value': result.get(field),
                                'cursor': result.get('cursor'), 'page': {'eof': whole is None, 'whole': True},
                                'path': result.get('path')})
        if self.first: value = self.first.pop(0)
        else:
            follow = next((p.get('next') for p in pages if p.get('next')), None) or whole
            if self.want_start:
                start = next((p.get('from_start') for p in pages if p.get('from_start')), None)
                if start: follow, self.want_start = start, False
            if follow is None:
                self.done = True; follow = {'action': 'git_status', 'arguments': {}}
            value = {'plan': 'Follow the page continuation.', 'action': follow['action'], 'arguments': json.dumps(follow['arguments'])}
        self.calls.append('owned')
        self.control.launched(attempt['id'], attempt['generation'], {'fixture': True})
        self.control.finish(attempt['id'], attempt['generation'], {'fixture': value})


class PagingFixture(WorkFixture):
    def commit(self, files):
        for name, text in files.items():
            path = self.root / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(text.encode())
        self.git('add', *files); self.git('commit', '-q', '-m', 'fixture files')

    def follow(self, first, steps=60, want_start=False, **authority):
        task = submit(self.ledger, None, 'paging', mode='work', provider='kiro', model='claude-sonnet-5',
                      contract=self.contract(**(authority or {'commands': True})))['id']
        worker = Follower(self.ledger, first, want_start)
        runtime = Owned(self.ledger, worker); runtime.enable(task)
        for _ in range(steps):
            state = runtime.run(task, steps=1)
            if worker.done or state['phase'] != 'running': break
        for prompt, schema in worker.prompts:  # the real _fit kept every prompt within Kiro's cap
            self.assertLessEqual(len(prompt) + len(schema) + 40, CAP)
        return runtime, task, worker, state

    def text_of(self, worker, field='text', path=None):
        """Rebuild the delivered characters by position; every page must start exactly where the previous one ended."""
        pieces = [p for p in worker.pieces if p.get('field') == field and (path is None or p.get('path') == path)]
        out, position = [], None
        for piece in pieces:
            base = (piece['cursor'] or 0) + piece['offset'] if field == 'text' else piece['offset']  # text: file positions
            if position is not None and base != position and piece['action'] != 'run':
                self.fail(f'page gap or overlap: expected {position}, got {base}')
            out.append(piece['value']); position = base + len(piece['value'])
        return ''.join(out), pieces


class PagingTests(PagingFixture):
    """B: whatever the prompt can carry, the model gets every character through the advertised continuation; cursor/eof
    describe what it received."""

    def big(self, size, marker):
        lines, total = [], 0
        while total < size:
            line = f'line {len(lines):05d} ' + 'x' * 60 + '\n'; lines.append(line); total += len(line)
        return ''.join(lines) + marker + '\n'

    def workspace_text(self, runtime, task, name):
        return (wt.ws_root(runtime.state(task)[1]) / name).read_bytes().decode('utf-8-sig')

    def test_a_9kb_file_is_delivered_to_its_last_line(self):
        self.commit({'docs/big.txt': self.big(9000, 'END-MARKER-9K')})
        # A long history first, so the evidence packet is at its minimum under the cap.
        smalls = {f'docs/s{i:02d}.txt': f'small {i}\n' * 30 for i in range(20)}
        self.commit(smalls)
        first = [action('read', path=name) for name in smalls] + [action('read', path='docs/big.txt')]
        runtime, task, worker, state = self.follow(first)
        delivered, pieces = self.text_of(worker, path='docs/big.txt')
        self.assertTrue(pieces, 'RED-B: the 9 KB read was never paged: the model saw a cut record with next_cursor=null')
        self.assertEqual(delivered, self.workspace_text(runtime, task, 'docs/big.txt'))
        self.assertIn('END-MARKER-9K', delivered)
        self.assertTrue(pieces[-1]['page']['eof']); self.assertTrue(all(not p['page']['eof'] for p in pieces[:-1]))

    def test_a_file_larger_than_one_read_page_is_delivered_without_a_gap(self):
        text = self.big(20000, 'END-MARKER-20K'); text = text[:9052] + 'GAP-MARKER' + text[9062:]
        self.commit({'docs/huge.txt': text})
        runtime, task, worker, state = self.follow([action('read', path='docs/huge.txt')])
        delivered, _ = self.text_of(worker)
        self.assertEqual(delivered, self.workspace_text(runtime, task, 'docs/huge.txt'))
        self.assertIn('GAP-MARKER', delivered); self.assertIn('END-MARKER-20K', delivered)

    @unittest.skipIf(PY is None, 'needs a real Python interpreter on PATH')
    def test_the_middle_of_a_long_command_log_is_reachable(self):
        out = program("import sys\nfor i in range(400): print('row %04d ' % i + 'y' * 60 + (' MID-MARKER' if i == 200 else ''))\n"
                      "print('END-OF-RUN')\n")
        runtime, task, worker, state = self.follow([action('run', argv=[PY, '-c', out])], want_start=True)
        stdout = [p for p in worker.pieces if p.get('field') == 'stdout']
        self.assertTrue(stdout, 'RED-B: the long log reached the model as a cut excerpt only')
        run = stdout[0]
        self.assertEqual(run['action'], 'run'); self.assertEqual(run['page']['source'], 'full command log')
        self.assertIn('END-OF-RUN', run['value'], 'the outcome (the end of the log) comes first')
        pages = stdout[1:]; position = 0
        for page in pages:
            self.assertEqual(page['offset'], position, 'page gap or overlap'); position += len(page['value'])
        log = (wt.home(runtime, task) / 'logs' / (json.loads(runtime.store.read_blob(runtime.state(task)[1]['receipts'][0]['blob']))
                                                    ['result']['log'] + '.out')).read_bytes().decode('utf-8', 'replace')
        self.assertEqual(''.join(p['value'] for p in pages), log, 'the full log is not reachable page by page')
        self.assertIn('MID-MARKER', ''.join(p['value'] for p in pages))
        self.assertTrue(pages[-1]['page']['eof'])

    def test_a_long_listing_is_paged_by_items_and_then_by_the_tool_cursor(self):
        self.commit({f'many/f{i:03d}.txt': 'x\n' for i in range(260)})
        runtime, task, worker, state = self.follow([action('list', directory='many')], steps=80, commands=False)
        names = [e['path'] for piece in worker.pieces if piece.get('field') == 'entries' for e in piece['value']]
        self.assertEqual(names, [f'many/f{i:03d}.txt' for i in range(260)])

    def test_receipt_refuses_arguments_outside_its_contract(self):
        self.commit({'docs/a.txt': 'a\n'})
        runtime, task, worker, state = self.follow([action('read', path='docs/a.txt'), action('receipt', index=0, limit=2000)],
                                                    steps=2, commands=False)
        last = json.loads(runtime.store.read_blob(runtime.state(task)[1]['receipts'][-1]['blob']))['result']
        self.assertIn('receipt takes {index, field, offset}', last.get('error', ''), 'RED-B: limit is silently ignored')


# --- C: one notion of "the workspace changed" ---------------------------------------------------------------------------

@unittest.skipIf(PY is None, 'needs a real Python interpreter on PATH')
class IgnoredInputTests(WorkFixture):
    CHECK = ("import sys\ntry: value = open('generated/value.txt').read()\nexcept OSError: value = None\n"
             "print('generated value', value)\nsys.exit(0 if value == '5' else 1)\n")

    def setUp(self):
        super().setUp()
        (self.root / '.gitignore').write_text('generated/\n.cache/\n__pycache__/\n')
        (self.root / 'check.py').write_text(self.CHECK)
        self.git('add', '.gitignore', 'check.py'); self.git('commit', '-q', '-m', 'check')

    def results(self, responses):
        runtime, task, _ = self.job(self.contract(edit=True, commands=True), responses, key='c-' + os.urandom(3).hex())
        state = runtime.run(task, steps=len(responses))
        return [json.loads(runtime.store.read_blob(r['blob']))['result'] for r in state['receipts']], state

    def build(self, text="'5'"):
        return action('run', argv=[PY, '-c', program(f"import os\nos.makedirs('generated', exist_ok=True)\n"
                                                     f"open('generated/value.txt','w').write({text})\n")])

    def check(self, *flags):
        return action('run', argv=[PY, *flags, 'check.py'])

    def test_a_retest_runs_after_the_build_generated_the_missing_ignored_input(self):
        results, state = self.results([self.check(), self.build(), self.check()])
        self.assertEqual(results[0]['exit_code'], 1)
        self.assertNotIn('error', results[2], 'RED-C: the retest was refused: ' + str(results[2].get('error')))
        self.assertEqual(results[2]['exit_code'], 0)

    def test_a_content_change_of_an_existing_ignored_input_counts(self):
        results, _ = self.results([self.build("'4'"), self.check(), self.build(), self.check()])
        self.assertEqual(results[3].get('exit_code'), 0, str(results[3]))

    def test_with_nothing_changed_the_failed_command_is_still_refused(self):
        results, _ = self.results([self.check(), self.check()])
        self.assertIn('Nothing changed', results[1].get('error', ''))

    def test_a_rewritten_log_or_cache_is_not_a_change(self):
        noise = action('run', argv=[PY, '-c', program("import os, time\nos.makedirs('.cache', exist_ok=True)\n"
                                                      "open('.cache/run.log','a').write(str(time.time()))\nopen('run.log','a').write('x')\n")])
        (self.root / '.gitignore').write_text('generated/\n.cache/\n__pycache__/\n*.log\n')
        self.git('add', '.gitignore'); self.git('commit', '-q', '-m', 'logs')
        results, _ = self.results([self.check(), noise, self.check()])
        self.assertIn('Nothing changed', results[2].get('error', ''), str(results[2]))

    def test_retests_after_only_ignored_inputs_changed_are_bounded(self):
        stamp = action('run', argv=[PY, '-c', program("import os, time\nos.makedirs('generated', exist_ok=True)\n"
                                                      "open('generated/value.txt','w').write(str(time.time()))\n")])
        results, _ = self.results([self.check(), stamp, self.check(), stamp, self.check(), stamp, self.check()])
        self.assertEqual([r.get('exit_code') for r in results[2:5:2]], [1, 1])
        self.assertIn('more times on these files after only Git-ignored inputs changed', results[6].get('error', ''))

    def test_a_cosmetic_argv_change_of_a_failing_command_is_a_repeat(self):
        _, state = self.results([self.check(), self.check('-B'), self.check('-X', 'utf8')])
        self.assertEqual(state['phase'], 'blocked'); self.assertIn('Repeated equivalent', state['message'])

    def test_different_silent_failing_probes_are_not_one_repeated_result(self):
        probe = lambda code: action('run', argv=[PY, '-c', program(f'import sys\nsys.exit({code})\n')])
        _, state = self.results([probe(1), probe(2), probe(3)])
        self.assertEqual(state['phase'], 'running', str(state.get('message')))

    def test_a_large_ignored_dependency_tree_does_not_hide_the_generated_input(self):
        (self.root / '.gitignore').write_text('generated/\n.cache/\n__pycache__/\n.venv/\n')
        self.git('add', '.gitignore'); self.git('commit', '-q', '-m', 'venv')
        venv = action('run', argv=[PY, '-c', program("import os\nfor i in range(2600):\n    d = '.venv/lib/p%03d' % (i // 100)\n"
                                                       "    os.makedirs(d, exist_ok=True)\n    open(d + '/m%04d.py' % i, 'w').write('x')\n")])
        results, _ = self.results([venv, self.check(), self.build(), self.check()])
        self.assertEqual(results[3].get('exit_code'), 0, str(results[3]))

    def test_a_file_written_by_a_background_command_is_read_after_it_failed(self):
        import time
        runtime, task, _ = self.job(self.contract(edit=True, commands=True),
                                    [action('read', path='generated/late.txt'),
                                     action('run', argv=[PY, '-c', program("import os\nos.makedirs('generated', exist_ok=True)\n"
                                                                           "open('generated/late.txt','w').write('late')\n")], background=True),
                                     action('read', path='generated/late.txt')], key='bg')
        def stop():
            for child, job, record, out, err in wt._RUNNING.pop(task, {}).values():
                try: job.stop()
                finally: job.close(); out.close(); err.close()
        self.addCleanup(stop)
        runtime.run(task, steps=2); time.sleep(2)
        state = runtime.run(task, steps=1)
        last = json.loads(runtime.store.read_blob(state['receipts'][-1]['blob']))['result']
        self.assertEqual(last.get('text'), 'late', str(last))

    def test_the_failed_read_replay_follows_the_same_key(self):
        results, _ = self.results([action('read', path='generated/value.txt'), self.build(), action('read', path='generated/value.txt'),
                                   action('read', path='missing.txt'), action('list'), action('read', path='missing.txt')])
        self.assertEqual(results[2].get('text'), '5')
        self.assertTrue(results[5].get('error', '').startswith('Identical to receipt 3'), str(results[5]))


# --- D: resume is recovery -----------------------------------------------------------------------------------------------

class Recorder(FixtureWorker):
    def __init__(self, ledger, responses):
        super().__init__(ledger, responses); self.prompts = []

    def run(self, attempt, prompt, schema, profile):
        self.prompts.append(prompt)
        return super().run(attempt, prompt, schema, profile)


class ResumeTests(WorkFixture):
    def setUp(self):
        super().setUp()
        self.desktop = Path(self.temp.name) / 'desktop'
        os.environ['ONECREW_DESKTOP_HOME'] = str(self.desktop); self.addCleanup(os.environ.pop, 'ONECREW_DESKTOP_HOME', None)
        self.windows = []
        launcher = patch('onecrew.desktop_notifications.launch', side_effect=lambda root, key: self.windows.append(key))
        launcher.start(); self.addCleanup(launcher.stop)

    def blocked(self, before=(), after=()):
        from onecrew.desktop_notifications import configure
        responses = list(before) + [action('list')] * 3 + list(after)
        task = submit(self.ledger, None, 'resume', mode='work', provider='kiro', model='claude-sonnet-5',
                      contract=self.contract(edit=True, commands=True, local_branches=['fix/resume']))['id']
        worker = Recorder(self.ledger, responses)
        runtime = Owned(self.ledger, worker); runtime.enable(task)
        configure(self.ledger, True)
        state = runtime.run(task, steps=len(before) + 3)
        return runtime, task, worker, state

    def edit(self):
        text = 'def add_fixed(a, b):\n    return a + b\n'
        from tests.test_review_07d7ad6 import sha
        return action('write', path='added.py', expected_sha256=None, text=text), sha(text)

    def test_the_worker_is_warned_before_the_guard_stops_the_task(self):
        runtime, task, worker, state = self.blocked()
        third = context(worker.prompts[2])['recovery']['repeats']
        self.assertEqual(third[-1]['status'], 'warning: the next identical result stops the task', 'RED-D: no warning')
        self.assertEqual(third[-1]['action'], 'list')

    def test_a_block_writes_a_core_blocker_handover_and_notifies_once_from_the_checkpoint(self):
        runtime, task, worker, state = self.blocked()
        self.assertEqual(state['phase'], 'blocked')
        report = Path(state['report_file'])
        self.assertTrue(report.is_file(), 'RED-D: no blocker handover')
        summary = json.loads(report.with_suffix('.json').read_text(encoding='utf-8'))
        self.assertEqual(summary['repeated']['action'], 'list'); self.assertEqual(summary['kind'], 'no_progress')
        self.assertIn('job resume', summary['to_continue'])
        self.assertEqual(len(self.windows), 1, 'one Windows result window from the checkpoint of the blocked job')
        window = next(self.desktop.rglob(self.windows[0] + '.txt')).read_text(encoding='utf-8')
        self.assertIn(str(report), window)

    def test_resume_rebuilds_the_context_keeps_counters_budget_and_work_and_bounds_the_loop(self):
        write, digest = self.edit()
        runtime, task, worker, state = self.blocked(before=[write], after=[action('list')])
        budget = runtime.control.status(task)['budget']; counts = dict(state['progress']['results'])
        receipts = len(state['receipts']); changes = runtime._workspace_changes(state)
        resumed = runtime.resume(task)
        self.assertEqual(resumed['progress']['results'], counts, 'a resume must not reset the guard')
        self.assertEqual(runtime.control.status(task)['budget'], budget, 'a resume must not change the budget')
        self.assertEqual(len(resumed['receipts']), receipts, 'a resume runs no action')
        self.assertTrue(resumed['message'].startswith('Resumed after a block'))
        after = runtime.run(task, steps=1)
        prompt = context(worker.prompts[-1])
        recovery = prompt['recovery']
        self.assertIn('Repeated equivalent tool result', recovery['blocked_before']['reason'], 'RED-D: the block is not explained')
        self.assertEqual(recovery['blocked_before']['repeated']['action'], 'list')
        self.assertTrue(any(r['status'].startswith('exhausted') for r in recovery['repeats']))
        self.assertEqual(prompt['workspace_changes'], changes, 'the existing edit is part of the rebuilt context')
        self.assertEqual(changes['paths'], ['A added.py'])
        self.assertIsNotNone(recovery['deadline']['at'])
        self.assertEqual(after['phase'], 'blocked', 'the exhausted repeat stops the task again (bounded loop)')
        self.assertEqual(len(self.windows), 2, 'one window per block')
        self.assertNotEqual(after['report_file'], state['report_file'], 'the second block has its own blocker handover')
        self.assertTrue(Path(after['report_file']).is_file())
        self.assertLessEqual(len(canonical(runtime._recovery(after, runtime.control.status(task), compact=True))), 1800)

    def test_resume_never_repeats_a_finished_effect(self):
        write, _ = self.edit()
        before = [write, action('workspace_commit', message='fix add'), action('export_branch', name='fix/resume')]
        runtime, task, worker, state = self.blocked(before=before, after=[action('git_status')])
        branch = self.git('rev-parse', 'refs/heads/fix/resume').strip()
        runtime.resume(task); after = runtime.run(task, steps=1)
        self.assertEqual(self.git('rev-parse', 'refs/heads/fix/resume').strip(), branch)
        self.assertEqual([r['action'] for r in after['receipts']].count('export_branch'), 1)
        self.assertEqual(context(worker.prompts[-1])['branches'], [{'name': 'fix/resume', 'status': 'verified'}])

    def test_resume_respects_cancel_and_the_deadline(self):
        import datetime as dt
        runtime, task, worker, state = self.blocked(after=[action('git_status')])
        calls = len(worker.prompts)
        later = dt.datetime.fromisoformat(runtime.control.status(task)['deadline']) + dt.timedelta(seconds=1)
        runtime.resume(task)
        with patch.object(runtime.control, 'clock', return_value=later):
            runtime.run(task, steps=1)
        self.assertEqual(len(worker.prompts), calls, 'a worker call after the deadline')
        runtime.control.cancel(task)
        with self.assertRaisesRegex(Exception, 'cancelled'): runtime.resume(task)
        runtime.run(task, steps=1)
        self.assertEqual(len(worker.prompts), calls, 'a worker call after cancel')
        self.assertEqual(runtime.control.status(task)['status'], 'cancelled')


if __name__ == '__main__':
    unittest.main()
