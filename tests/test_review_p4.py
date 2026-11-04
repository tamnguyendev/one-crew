"""Codex deep review of P4 (14/10/2026) on 198a640: R1 repeat-warning order, R2 a page that cannot advance, R3 supervision lost
after successive I/O errors, R4 a workspace key that misses information but is trusted.

Each class reproduces the reviewed failure through the public runtime with temporary fixtures (no task or host of the machine):
the runner's persist/reload of the checkpoint, the real _work_prompt/_fit under the Kiro cap, real Windows locks, real commands in
the isolated workspace. Controls keep the guards intact (a real loop is still stopped, no duplicate runner, released tasks stay
released, no-op/log churn is not progress)."""
import json
import os
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

from onecrew import host
from onecrew import work_tools as wt
from onecrew.ledger import canonical
from onecrew.owned import Owned
from onecrew.owned_intake import submit
from onecrew.progress import observe
from tests.test_host import HostFixture, at
from tests import test_review_p3
from tests.test_review_p3 import CAP, Locked, context
from tests.test_work_boundary import PY, program
from tests.test_work_contract import WorkFixture, action
from tests.test_workflow import FixtureWorker


# --- R1: the order of repeat warnings survives the checkpoint -------------------------------------------------------------

class RepeatOrderTests(WorkFixture):
    """U1 step 13 (14/10/2026): the warning for the action about to be stopped was not in the prompt, because the checkpoint
    (canonical JSON, sorted keys) does not keep the order in which repeats happened."""

    def setUp(self):
        super().setUp()
        for i in range(10): (self.root / f'r{i}.txt').write_text(f'repeat source {i}\n')
        self.git('add', '.'); self.git('commit', '-q', '-m', 'sources')
        task = submit(self.ledger, None, 'repeats', mode='work', provider='kiro', model='claude-sonnet-5',
                      contract=self.contract(edit=True, commands=True))['id']
        self.runtime = Owned(self.ledger, FixtureWorker(self.ledger, [])); self.runtime.enable(task); self.task = task
        self.profile = self.runtime.control.status(task)['configuration']['profile']

    def step(self, name, args):
        """One tool call the way the runner does it: tool, observe, receipt, persist; the next step starts from the stored
        checkpoint (as after every runner step or a restart)."""
        seq, state = self.runtime.state(self.task); state['phase'] = 'running'
        try: result = self.runtime._tool(self.task, state, name, args, self.profile)
        except (ValueError, OSError) as error: result = {'error': str(error)}
        observe(state, name, args, result)
        state['receipts'].append({'index': len(state['receipts']), 'action': name, 'successful': 'error' not in result,
                                  'blob': self.runtime.store.blob(canonical({'action': name, 'arguments': args, 'result': result}).encode())})
        state['step'] += 1
        self.runtime.persist(self.task, seq, state)

    def repeated(self, files):
        for i in files:
            self.step('read', {'path': f'r{i}.txt'}); self.step('read', {'path': f'r{i}.txt'})
        return self.runtime.state(self.task)[1]

    def paths(self, entries):
        return [e['arguments']['path'] for e in entries]

    def test_the_most_recent_repeats_are_kept_and_shown_across_checkpoints(self):
        state = self.repeated(range(10))  # r9 repeated last
        kept = sorted(state['progress']['repeats'].values(), key=lambda e: e['step'])
        self.assertEqual(self.paths(kept), [f'r{i}.txt' for i in range(2, 10)], 'RED-R1: the oldest repeats were not the ones dropped')
        control = self.runtime.control.status(self.task)
        full = self.runtime._recovery(state, control)['repeats']
        self.assertEqual(self.paths(full), [f'r{i}.txt' for i in range(5, 10)], 'RED-R1: full prompt shows repeats in key order')
        compact = self.runtime._recovery(state, control, compact=True)['repeats']
        self.assertEqual(self.paths(compact), ['r8.txt', 'r9.txt'], 'RED-R1: the compact prompt dropped the latest warning')

    def test_the_latest_warning_reaches_the_real_prompt_after_a_restart(self):
        self.repeated(range(10))
        restarted = Owned(self.ledger, FixtureWorker(self.ledger, []))  # a new runner process reads the stored checkpoint
        state = restarted.state(self.task)[1]
        from onecrew.owned import contract as tools
        prompt, schema, _ = tools(self.profile)
        text = restarted._work_prompt(self.task, state, self.profile, restarted.control.status(self.task), prompt, schema, [])
        self.assertLessEqual(len(text) + len(canonical(schema)) + 40, CAP)
        repeats = context(text)['recovery']['repeats']
        self.assertEqual(repeats[-1]['arguments']['path'], 'r9.txt', 'RED-R1: the last warning is not the latest repeat')
        self.assertTrue(repeats[-1]['status'].startswith('warning'))

    def test_an_older_checkpoint_without_sequence_numbers_is_ordered_by_step(self):
        state = self.repeated(range(4))
        for entry in state['progress']['repeats'].values(): entry.pop('seq', None)  # as written by 198a640
        state['progress'].pop('repeat_seq', None)
        seq = self.runtime.state(self.task)[0]; self.runtime.persist(self.task, seq, state)
        self.repeated([5])
        state = self.runtime.state(self.task)[1]
        shown = self.runtime._recovery(state, self.runtime.control.status(self.task))['repeats']
        self.assertEqual(self.paths(shown), ['r0.txt', 'r1.txt', 'r2.txt', 'r3.txt', 'r5.txt'])
        self.assertEqual(state['progress']['results'] and max(state['progress']['results'].values()), 2, 'counters kept')

    def test_a_real_loop_is_still_stopped(self):
        for _ in range(3): self.step('read', {'path': 'r1.txt'})
        state = self.runtime.state(self.task)[1]
        self.assertEqual(state['phase'], 'blocked'); self.assertIn('r1.txt', state['message'])


# --- R2: a page always advances ------------------------------------------------------------------------------------------

class PageFollower(FixtureWorker):
    """Obeys the paging contract: scripted first actions, then always the first page.next; records what was delivered."""
    def __init__(self, ledger, first):
        super().__init__(ledger, []); self.first, self.prompts, self.latest, self.done = list(first), [], [], False

    def run(self, attempt, prompt, schema, profile):
        self.prompts.append((prompt, canonical(schema)))
        latest = context(prompt).get('latest_result') or {}
        self.latest.append(latest)
        if self.first: value = self.first.pop(0)
        else:
            follow = next((p.get('next') for p in latest.get('page') or [] if p.get('next')), None)
            if follow is None: self.done = True; follow = {'action': 'git_status', 'arguments': {}}
            value = {'plan': 'Follow page.next.', 'action': follow['action'], 'arguments': json.dumps(follow['arguments'])}
        self.calls.append('owned')
        self.control.launched(attempt['id'], attempt['generation'], {'fixture': True})
        self.control.finish(attempt['id'], attempt['generation'], {'fixture': value})


class PageProgressTests(WorkFixture):
    """Codex: git_log with three 500-character subjects and ~5,200 characters of extra context under the real _fit: a page of zero
    items pointed next at its own offset; a worker that followed next three times was stopped by the guard."""
    CONTEXT = ' '.join(['The acceptance of this fixture is long on purpose.'] * 104)  # ~5,200 characters of contract text

    def follow(self, first, steps=40):
        contract = dict(self.contract(commands=True), goal='Fixture goal. ' + self.CONTEXT)
        task = submit(self.ledger, None, 'pages', mode='work', provider='kiro', model='claude-sonnet-5', contract=contract)['id']
        worker = PageFollower(self.ledger, first)
        runtime = Owned(self.ledger, worker); runtime.enable(task)
        for _ in range(steps):
            state = runtime.run(task, steps=1)
            if worker.done or state['phase'] != 'running': break
        for prompt, schema in worker.prompts: self.assertLessEqual(len(prompt) + len(schema) + 40, CAP)
        return runtime, task, worker, state

    def test_list_items_larger_than_the_page_are_delivered_and_the_continuation_advances(self):
        # P5 (14/10/2026): with RESULT_RESERVE these items (git_log keeps 500 characters of a subject) can now arrive whole with
        # their list; the collector below takes both forms. Item paging itself stays covered by test_view_never_returns_a_page...
        subjects = [(f'commit {i} ' + 'long subject words ' * 40)[:500] for i in range(3)]
        for subject in subjects:
            self.git('commit', '-q', '--allow-empty', '-m', subject)
        runtime, task, worker, state = self.follow([action('git_log', directory='')])
        self.assertEqual(state['phase'], 'running', 'RED-R2: following next was stopped as a repeat: ' + str(state.get('message')))
        items, texts, offsets = {}, {}, []
        for latest in worker.latest:
            if latest.get('complete') and isinstance(latest.get('result'), dict):  # delivered whole (P5: room permitting)
                for n, item in enumerate(latest['result'].get('commits') or []): items.setdefault(n, item)
            for page in latest.get('page') or []:
                if page['field'] != 'commits': continue
                offsets.append((page['offset'], (page.get('item') or {}).get('offset')))
                if page.get('item'):
                    texts.setdefault(page['item']['index'], []).append((page['item']['offset'], page['item']['text']))
                else:
                    for n, item in enumerate(latest['result'].get('commits') or []): items[page['offset'] + n] = item
        self.assertEqual(len(offsets), len(set(offsets)), 'a continuation pointed back at a page already delivered')
        for index, pieces in texts.items():
            text = ''.join(t for _, t in sorted(pieces)); items[index] = json.loads(text)
        delivered = [items[i]['subject'] for i in sorted(items)]
        self.assertEqual([s for s in subjects[::-1]], delivered[:3], 'RED-R2: commit subjects not delivered whole')

    def test_a_long_single_line_is_delivered_with_the_same_extra_context(self):
        line = 'x' * 15000 + 'END-OF-LINE'
        (self.root / 'line.txt').write_text(line); self.git('add', 'line.txt'); self.git('commit', '-q', '-m', 'line')
        runtime, task, worker, state = self.follow([action('read', path='line.txt')])
        self.assertEqual(state['phase'], 'running', str(state.get('message')))
        got = {}
        for latest in worker.latest:
            for page in latest.get('page') or []:
                if page['field'] == 'text': got[(latest['result'].get('cursor') or 0) + page['offset']] = latest['result']['text']
            if latest.get('action') == 'read' and not latest.get('page') and latest.get('result'):
                got[latest['result'].get('cursor') or 0] = latest['result'].get('text', '')
        text = ''.join(v for _, v in sorted(got.items()))
        self.assertTrue(text.endswith('END-OF-LINE'))
        self.assertEqual(len(text), len(line))

    def test_view_never_returns_a_page_that_does_not_advance(self):
        from onecrew.paging import view
        record = {'action': 'git_log', 'request': {'directory': ''},
                  'result': {'commits': [{'commit': 'a' * 40, 'subject': 's' * 500}] * 3, 'next_cursor': None}}
        from onecrew.ledger import LedgerError
        served = 0
        for budget in (500, 700, 900, 1500):
            try: value, pages = view(record, budget, index=4)
            except LedgerError: continue  # too small to advance: refused, so _fit makes room (never an empty page)
            served += 1; page = pages[0]
            moved = page['delivered'] > 0 or (page.get('item') or {}).get('delivered', 0) > 0
            self.assertTrue(moved, f'RED-R2: budget {budget}: a page that delivers nothing')
            self.assertNotEqual((page.get('next') or {}).get('arguments'), {'index': 4, 'field': 'commits', 'offset': page['offset']})
        self.assertGreaterEqual(served, 2)


# --- R3: supervision is never lost to successive I/O errors -----------------------------------------------------------------

class SupervisionReconcileTests(HostFixture):
    dispatched = test_review_p3.HostQueueTests.dispatched

    def test_successive_io_errors_never_lose_the_supervision_of_a_launched_runner(self):
        self.scan(0)  # an empty scan writes supervised.json
        supervised = Path(self.ledger.state_root) / 'host' / 'supervised.json'
        request, _ = self.dispatched()
        with Locked(supervised, share=0x1):  # launch succeeds, its supervision cannot be written
            self.scan(1)
        self.assertEqual(self.launched, [self.task])
        record = host._launch_record(self.ledger.state_root, self.task)
        old = record.stat().st_mtime - 60; os.utime(record, (old, old))  # the lock below lasted longer than a scan or two
        with Locked(record):  # next scan: the launch record cannot be read; supervised.json is written without the task
            self.scan(2, status='alive')
        actions = self.scan(40) + self.scan(60) + self.scan(80)  # the runner is gone
        self.assertIn('restarted', [a.get('action') for a in actions if a.get('task') == self.task],
                      'RED-R3: the launched runner lost its supervision: ' + str(actions))
        self.assertEqual(self.launched, [self.task, self.task], 'exactly one restart')

    def test_a_released_task_is_not_supervised_again(self):
        self.dispatched(); self.scan(0)
        from onecrew.owned import Owned as O
        runtime = O(self.ledger); seq, state = runtime.state(self.task)
        state['phase'] = 'completed'; runtime.persist(self.task, seq, state)
        self.assertIn('released', [a.get('action') for a in self.scan(10)])
        for second in (20, 40, 80):
            self.assertNotIn(self.task, json.loads((Path(self.ledger.state_root) / 'host' / 'supervised.json').read_text())['tasks'])
            self.scan(second)
        self.assertEqual(self.launched, [self.task])

    def test_an_older_supervision_file_does_not_revive_launch_records_it_had_released(self):
        record = host._launch_record(self.ledger.state_root, self.task); record.parent.mkdir(parents=True, exist_ok=True)
        host._write(record, {'task': self.task, 'request': 'HD-old', 'state': 'launched', 'at': at(-7200).isoformat(),
                             'identity': {'pid': 1, 'created': 1, 'host': 'gone'}})
        supervised = Path(self.ledger.state_root) / 'host' / 'supervised.json'; supervised.parent.mkdir(parents=True, exist_ok=True)
        host._write(supervised, {'tasks': {}})  # written by 198a640: no reconciliation state
        os.utime(record, None)  # even a record that looks newer than the supervision file
        for second in (0, 30, 90): self.scan(second)
        self.assertEqual(self.launched, [], 'a task released before the upgrade was revived')


# --- R4: an incomplete workspace key is never trusted as complete -------------------------------------------------------------

@unittest.skipIf(PY is None, 'needs a real Python interpreter on PATH')
class IncompleteKeyTests(WorkFixture):
    CHECK = ("import sys\ntry: value = open('.venv/lib/dep.py').read()\nexcept OSError: value = None\n"
             "print('dependency', value)\nsys.exit(0 if value == 'correct-value' else 1)\n")

    def setUp(self):
        super().setUp()
        (self.root / '.gitignore').write_text('.venv/\ngenerated/\n__pycache__/\n*.log\n')
        (self.root / 'check.py').write_text(self.CHECK)
        self.git('add', '.gitignore', 'check.py'); self.git('commit', '-q', '-m', 'check')

    def results(self, responses):
        runtime, task, _ = self.job(self.contract(edit=True, commands=True), responses, key='r4-' + os.urandom(3).hex())
        state = runtime.run(task, steps=len(responses))
        return [json.loads(runtime.store.read_blob(r['blob']))['result'] for r in state['receipts']], state, runtime, task

    def write(self, path, content):
        return action('run', argv=[PY, '-c', program(f"import os\nos.makedirs(os.path.dirname({path!r}), exist_ok=True)\n"
                                                        f"open({path!r}, 'w').write({content})\n")])

    def check(self):
        return action('run', argv=[PY, 'check.py'])

    def test_a_dependency_fix_allows_the_retest(self):
        results, _, _, _ = self.results([self.write('.venv/lib/dep.py', "'wrong'"), self.check(),
                                         self.write('.venv/lib/dep.py', "'correct-value'"), self.check()])
        self.assertEqual(results[1]['exit_code'], 1)
        self.assertNotIn('error', results[3], 'RED-R4: ' + str(results[3].get('error')))
        self.assertEqual(results[3]['exit_code'], 0)

    def test_a_same_size_dependency_change_allows_a_bounded_retest(self):
        check = action('run', argv=[PY, '-c', program("import sys\nsys.exit(0 if open('.venv/lib/dep.py').read() == 'right' else 1)\n")])
        results, _, _, _ = self.results([self.write('.venv/lib/dep.py', "'wrong'"), check,
                                         self.write('.venv/lib/dep.py', "'right'"), check])
        self.assertEqual(results[3].get('exit_code'), 0, 'RED-R4: ' + str(results[3]))

    def test_a_same_size_change_of_a_large_generated_file_allows_a_bounded_retest(self):
        size = 2_000_001
        make = lambda fill: action('run', argv=[PY, '-c', program(
            f"import os\nos.makedirs('generated', exist_ok=True)\nopen('generated/big.bin','w').write({fill!r} * {size})\n")])
        check = action('run', argv=[PY, '-c', program("import sys\nsys.exit(0 if open('generated/big.bin').read(1) == 'B' else 1)\n")])
        results, _, runtime, task = self.results([make('A'), check, make('B'), check])
        self.assertEqual(results[3].get('exit_code'), 0, 'RED-R4: ' + str(results[3]))
        self.assertTrue(runtime.state(task)[1]['work']['progress_state'].get('truncated'),
                        'an unhashed file must mark the key incomplete')

    def test_a_failed_read_is_retried_after_a_same_size_change_of_an_unhashed_file(self):
        # Four 2 MB files use up the 8 MB hash budget of generated/: the small file after them is described by its size only,
        # so a same-size rewrite leaves the key unchanged (dependency trees are not readable by the worker at all).
        binary = action('run', argv=[PY, '-c', program(
            "import os\nos.makedirs('generated', exist_ok=True)\n"
            "for i in range(4): open('generated/a%d.bin' % i, 'wb').write(b'x' * 2000000)\n"
            "open('generated/z.txt','wb').write(bytes(1) * 100)\n")])
        text = action('run', argv=[PY, '-c', program("open('generated/z.txt','w').write('t' * 100)\n")])
        results, _, _, _ = self.results([binary, action('read', path='generated/z.txt'), text, action('read', path='generated/z.txt')])
        self.assertIn('error', results[1])
        self.assertNotIn('Identical to receipt', results[3].get('error', ''), 'RED-R4: the old failure was replayed')
        self.assertTrue(results[3].get('text', '').startswith('ttt'), str(results[3])[:300])

    def test_no_op_churn_with_an_incomplete_key_is_still_bounded(self):
        churn = action('run', argv=[PY, '-c', program("open('run.log','a').write('x')\n")])
        results, state, _, _ = self.results([self.write('.venv/lib/dep.py', "'wrong'"), self.check(), churn, self.check(), churn,
                                             self.check(), churn, self.check()])
        refused = [r for r in results if 'Nothing changed' in r.get('error', '') or 'more times' in r.get('error', '')]
        self.assertTrue(refused or state['phase'] == 'blocked', 'an incomplete key allowed unbounded retests: '
                        + str([r.get('exit_code', r.get('error', '')[:60]) for r in results]))


if __name__ == '__main__':
    unittest.main()
