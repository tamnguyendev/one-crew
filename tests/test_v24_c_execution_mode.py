"""2.4-C (T24-C): a recorded, reasoned choice of execution mode - continue the worker / overlap independent branches / run tools without a
model / wait - inside dependency, authority, capacity 1-2 slots and handover cost (ROADMAP-DESIGN 20261026 §2.2, §7 row 2.4-C).

Real temporary ledger, Git, Control attempts and budget group. The workers are fixtures (callables, the shared isolated fixture adapter,
and the real NativeExecutor / ManagedExecutor with a local worker process): they prove the choice, its record and its limits, not the
quality or speed of a real model. Both entry points are covered: `engine step` (NativeExecutor, 1 slot) and `engine batch`
(ManagedExecutor, 2 slots).
"""
import json
import os
import threading
import time
from pathlib import Path

from onecrew.budget_core import group
from onecrew.control_core import Control, migrate
from onecrew.ledger import LedgerError
from onecrew.snapshots import Snapshots
from onecrew.v2 import compat, engine, execution_mode, executors, internal_plan, namespaces, plan as plans
from tests.test_v2_l1 import Fixture, plan_json
from tests.test_wf_engine import EngineFixture, node

BASE_CAPS = ['namespaced-storage', 'root-budget', 'internal-plan', 'sequential-engine', 'parallel-engine']
OWNED = ['a.txt', 'b.txt', 'c.txt', 'api.py']
PIN = {'role': 'worker', 'provider': 'codex', 'model': 'fixture-model'}


def worker(nid, write, read=None, depends=(), estimate=(1, 2), resources=(), pin=False, requires='verified'):
    item = node(nid, depends, requires=requires, write=write)
    item.update(read=list(read if read is not None else write), resources=list(resources), estimate_seconds=list(estimate))
    if pin: item['executor'] = dict(PIN)
    return item


def integration(depends, pin=False):
    item = node('I', depends, integration=True, write=())
    item['read'] = []
    if pin: item['executor'] = dict(PIN)
    return item


class ModeFixture(EngineFixture):
    mode = True

    def setUp(self):
        Fixture.setUp(self)
        self.engine, self.ip = engine, internal_plan
        for name in OWNED[1:]: (self.root / name).write_text(name + '\n')
        self.caps = BASE_CAPS + (['execution-mode'] if self.mode else [])
        raw = plan_json(scope={'owned': list(OWNED)}, authority={'edit': True, 'commands': True, 'edit_tests': True,
                                                                  'self_decide': ['Q1', 'Q2', 'Q3', 'Q4', 'Q5', 'Q9', 'Q12']})
        self.root_view = plans.propose(self.ledger, 'P1', raw, 'codex', workflow=True, capabilities=self.caps)
        plans.approve(self.ledger, 'P1', 'owner', 'fixture 2.4-C approval')
        os.environ['ONECREW_ACTOR'] = 'codex'
        self.store = Snapshots(self.ledger.state_root); migrate(self.ledger); self.control = Control(self.ledger)

    def isolated(self, callback=None, capabilities=('start', 'isolate'), name='fixture-isolated-artifact'):
        case = self
        class Isolated(executors.Executor):
            declaration = executors.Declaration(name, 'managed', capabilities)
            control = case.control
            def start(self, *args): return (callback or case.execute)(*args)
            def isolate(self, attempt_id): return {'attempt': attempt_id, 'writes': 'scoped candidate only'}
        return Isolated()

    def payloads(self, kind):
        return [p for k, p in self.events() if k == kind]

    def started(self, nid=None):
        return [p for p in self.payloads('node.started') if nid is None or p['node'] == nid]

    def modes(self, nid='*'):
        return [p for p in self.payloads('workflow.mode') if nid == '*' or p['node'] == nid]

    def used(self):
        with self.ledger.transaction() as conn: return group(conn, self.root_view['anchor_task'])['used_calls']

    def tasks(self):
        with self.ledger.transaction() as conn: return conn.execute('SELECT COUNT(*) FROM tasks').fetchone()[0]

    def attempts(self):
        with self.ledger.transaction() as conn: return conn.execute('SELECT COUNT(*) FROM attempts').fetchone()[0]

    def q2(self, nid):
        return [p for p in self.payloads('decision.recorded') if p.get('scope') == nid and str(p.get('basis', '')).startswith('Q2')]

    def receipt(self, **body):
        return self.store.blob(json.dumps(dict({'kind': 'native-node-receipt'}, **body), sort_keys=True).encode())

    def slow_prep(self, seconds, prompt_chars):
        """A fixture worker whose preparation (reserved -> launched) takes `seconds` and whose receipt says it was given `prompt_chars`."""
        def run(ledger, control, task, item, attempt):
            time.sleep(seconds)
            control.launched(attempt['id'], attempt['generation'], {'fixture': True})
            artifact = self.store.blob(('artifact-' + item['id']).encode())
            control.finish(attempt['id'], attempt['generation'], {'fixture': True})
            return {'artifact': artifact, 'receipt': self.receipt(node=item['id'], prompt_chars=prompt_chars, producer_chars={})}
        return run


class IndependentOverlap(ModeFixture):
    # case 1: two independent nodes (different writes, no read of the other's write, no shared resource) overlap in the two slots
    def test_independent_branches_overlap_and_the_choice_is_on_node_started_and_q2(self):
        self.revise([worker('A', ['a.txt']), worker('B', ['b.txt']), integration(['A', 'B'])])
        barrier = threading.Barrier(2)
        def together(ledger, control, task, item, attempt):
            control.launched(attempt['id'], attempt['generation'], {'fixture': True})
            barrier.wait(5)                                    # both workers are running at once, or this times out
            result = {'artifact': self.store.blob(('isolated-' + item['id']).encode()), 'receipt': self.store.blob(b'fixture isolated')}
            control.finish(attempt['id'], attempt['generation'], result)
            return result
        out = engine.run_batch(self.ledger, 'P1', self.isolated(together), slots=2)
        self.assertEqual({r['node']: r['state'] for r in out['results']}, {'A': 'produced', 'B': 'produced'})
        rows = {p['node']: p for p in self.started()}
        self.assertEqual({rows['A']['mode'], rows['B']['mode']}, {'overlap'})
        self.assertIn('beside:B', rows['A']['mode_reasons']); self.assertIn('independent_branch', rows['B']['mode_reasons'])
        for nid in ('A', 'B'):
            decision = self.q2(nid)[-1]
            self.assertEqual(decision['key'], 'mode-' + rows[nid]['mode_inputs_sha'][:48])
            self.assertIn('"mode":"overlap"', decision['evidence'][0]['action'])
            self.assertFalse(rows[nid]['session']['reuse'])
        self.assertEqual(self.used(), 2)


class SmallTaskLargeHandover(ModeFixture):
    # case 2: a small node (1-2 s) whose input carries a large context does not take the second slot; merge is recommended
    def test_handover_larger_than_the_gain_keeps_the_second_slot_empty_and_recommends_a_merge(self):
        self.revise([worker('U', ['c.txt']), worker('X', ['a.txt']), worker('B', ['b.txt'], depends=['U'], estimate=(1, 2)), integration(['U', 'X', 'B'])])
        self.assertEqual(self.step(self.slow_prep(1.2, 60000))['node'], 'U')
        self.verify('U')
        before_used, before_tasks = self.used(), self.tasks()
        out = engine.run_batch(self.ledger, 'P1', self.isolated(), slots=2)
        states = {r.get('node'): r for r in out['results']}
        self.assertEqual(states['X']['state'], 'produced')
        self.assertEqual(states['B']['state'], 'waiting'); self.assertEqual(states['B']['mode'], 'run_now')
        self.assertIn('handover_exceeds_gain', states['B']['reasons'])
        self.assertIn('merge B into U at plan time', states['B']['recommendation'])
        record = self.modes('B')[-1]
        self.assertEqual(record['inputs']['handover']['chars'], 60000)
        self.assertGreaterEqual(record['inputs']['handover']['seconds'], record['inputs']['gain_seconds'])
        self.assertEqual([p['node'] for p in self.started()], ['U', 'X'])
        self.assertEqual((self.used(), self.tasks()), (before_used + 1, before_tasks + 1))     # B submitted nothing, spent nothing

    def test_an_unmeasured_handover_claims_no_gain(self):
        self.revise([worker('U', ['c.txt']), worker('X', ['a.txt']), worker('B', ['b.txt'], depends=['U']), integration(['U', 'X', 'B'])])
        self.step(); self.verify('U')                          # the fixture receipt is opaque: no prompt size, no preparation rate
        out = engine.run_batch(self.ledger, 'P1', self.isolated(), slots=2)
        b = next(r for r in out['results'] if r.get('node') == 'B')
        self.assertEqual((b['mode'], b['state']), ('run_now', 'waiting')); self.assertIn('handover_unknown', b['reasons'])
        self.assertEqual(self.modes('B')[-1]['inputs']['handover']['seconds'], 'unknown')


class ParallelTools(ModeFixture):
    # case 3: the model-free checks of a produced node run while a worker node is active, without a child task or an attempt
    def test_checks_of_a_produced_node_run_beside_an_active_worker_without_a_new_agent(self):
        self.revise([worker('A', ['a.txt']), worker('B', ['b.txt']), integration(['A', 'B'])])
        self.step(); tasks, attempts = self.tasks(), self.attempts()
        running, checked = threading.Event(), threading.Event()
        seen = {}
        def slow(ledger, control, task, item, attempt):
            control.launched(attempt['id'], attempt['generation'], {'fixture': True}); running.set()
            if not checked.wait(10): raise AssertionError('the checks never ran beside the worker')
            result = {'artifact': self.store.blob(b'B out'), 'receipt': self.store.blob(b'B receipt')}
            control.finish(attempt['id'], attempt['generation'], result); return result
        case = self
        class Free:
            model_free = True
            def __call__(self, item, artifact):
                running.wait(5)
                with case.ledger.transaction() as conn:
                    seen['active'] = conn.execute("SELECT COUNT(*) FROM attempts WHERE status='running'").fetchone()[0]
                result = case.checker(item, artifact); checked.set(); return result
        out = engine.run_batch(self.ledger, 'P1', self.isolated(slow), slots=2, checker=Free())
        by = {r['node']: r for r in out['results']}
        self.assertEqual((by['A']['mode'], by['A']['state']), ('tools', 'verified'))
        self.assertEqual(by['B']['state'], 'produced')
        self.assertEqual(seen['active'], 1)                                   # B's worker was running while A's checks ran
        self.assertEqual((self.tasks(), self.attempts()), (tasks + 1, attempts + 1))   # only B's child task and attempt
        self.assertEqual(self.modes('A')[-1]['mode'], 'tools')
        self.assertEqual(engine.state(self.ledger, 'P1')['nodes']['A']['state'], 'verified')

    def test_tools_never_replaces_a_review_that_needs_a_model_and_needs_a_declared_checker(self):
        self.revise([worker('A', ['a.txt']), integration(['A'])])
        self.step()
        view = engine.state(self.ledger, 'P1'); a = view['definition']['nodes'][0]
        class Free:
            model_free = True
            def __call__(self, item, artifact): raise AssertionError('not called')
        review = execution_mode.choose(a, view, slots=1, checker=Free(), check_types={'check-A': 'reviewer'})
        self.assertEqual(review['mode'], 'wait'); self.assertIn('review_needs_model:check-A', review['reasons'])
        undeclared = execution_mode.choose(a, view, slots=1, checker=lambda item, artifact: None, check_types={'check-A': None})
        self.assertEqual(undeclared['reasons'], ['checker_not_declared_model_free'])
        self.assertEqual(execution_mode.choose(a, view, slots=1, checker=Free(), check_types={'check-A': 'command'})['mode'], 'tools')
        self.assertIsNone(engine._tools(self.ledger, {'selector': 'plan-ns:P1'}, None, view, None, None))   # no checker: nothing


class ExclusiveResources(ModeFixture):
    # case 4 (red on the 2.3 code: ready_batch compares only writes): a read of a file the other writes, or a shared resource label
    def test_a_read_of_a_file_the_other_node_writes_is_not_independent(self):
        self.revise([worker('A', ['api.py']), worker('B', ['b.txt'], read=['api.py', 'b.txt']), integration(['A', 'B'])])
        view = engine.state(self.ledger, 'P1')
        self.assertEqual([c['id'] for c in engine._ready(view, 2)], ['A'])
        self.assertEqual(execution_mode.conflicts(view['definition']['nodes'][0], view['definition']['nodes'][1]), ['read_write'])
        out = engine.run_batch(self.ledger, 'P1', self.isolated(), slots=2)
        self.assertEqual([r['node'] for r in out['results']], ['A'])

    def test_a_shared_resource_label_is_exclusive_against_the_batch_and_an_active_node(self):
        self.revise([worker('A', ['a.txt'], resources=['db:dev']), worker('B', ['b.txt'], resources=['DB:dev']), integration(['A', 'B'])])
        self.assertEqual([c['id'] for c in engine.ready(self.ledger, 'P1', slots=2)], ['A'])
        started, release, result = threading.Event(), threading.Event(), {}
        def hold(ledger, control, task, item, attempt):
            control.launched(attempt['id'], attempt['generation'], {'fixture': True}); started.set()
            if not release.wait(10): raise AssertionError('release missing')
            out = {'artifact': self.store.blob(b'A out'), 'receipt': self.store.blob(b'A receipt')}
            control.finish(attempt['id'], attempt['generation'], out); return out
        executor = self.isolated(hold)
        thread = threading.Thread(target=lambda: result.update(engine.step(self.ledger, 'P1', executor, slots=2, _target='A')))
        thread.start()
        try:
            self.assertTrue(started.wait(5))
            waiting = engine.step(self.ledger, 'P1', executor, slots=2)
            self.assertEqual(waiting['state'], 'waiting')
            self.assertIn('B: no free slot or an exclusive resource is held', waiting['reasons'])
        finally:
            release.set(); thread.join(5)
        self.assertEqual(result['state'], 'produced')
        self.assertEqual([p['node'] for p in self.started()], ['A'])


class NoSessionReuse(ModeFixture):
    # case 5: no shipped adapter keeps a model session; the record says how the context is rebuilt
    def test_shipped_adapters_never_claim_a_session_and_name_the_restore_path(self):
        from onecrew.common_executor import NativeExecutor
        from onecrew.v2.managed_executor import ManagedExecutor
        self.revise([worker('A', ['a.txt']), worker('B', ['b.txt'], depends=['A']), integration(['A', 'B'])])
        view = engine.state(self.ledger, 'P1'); a, b = view['definition']['nodes'][:2]
        for declaration in (NativeExecutor.declaration, ManagedExecutor.declaration):
            self.assertFalse(declaration.supports('resume_session'))
            out = execution_mode.choose(a, view, slots=1, declaration=declaration)
            self.assertFalse(out['session']['reuse']); self.assertIsNone(out['session']['evidence'])
            self.assertEqual(out['context']['restored_from'], ['source_snapshot', 'knowledge'])
            self.assertEqual(execution_mode.restored_from(b, {'resume_artifact': 'x'}, declaration),
                             ['source_snapshot', 'input_artifacts', 'resume_artifact', 'knowledge'])
        self.assertNotIn('resume_pack', json.dumps(execution_mode.restored_from(b, {'resume_artifact': 'x'}, ManagedExecutor.declaration)))

    def test_an_adapter_claiming_a_session_gets_reuse_only_for_the_same_id_it_launched_with(self):
        self.revise([worker('A', ['a.txt']), worker('B', ['b.txt']), worker('C', ['c.txt']), integration(['A', 'B', 'C'])])
        returned = {'A': None, 'B': 'S-other', 'C': 'S-1'}
        def claims(ledger, control, task, item, attempt):
            control.launched(attempt['id'], attempt['generation'], {'fixture': True, 'session_id': 'S-1'})
            out = {'artifact': self.store.blob(item['id'].encode()), 'receipt': self.receipt(node=item['id'], session_id=returned[item['id']])}
            control.finish(attempt['id'], attempt['generation'], {'fixture': True}); return out
        executor = self.isolated(claims, capabilities=('start', 'resume_session'), name='fixture-session-claim')
        for _ in range(3): engine.step(self.ledger, 'P1', executor)
        produced = {p['node']: p['session'] for p in self.payloads('node.produced')}
        self.assertEqual({k: v['reuse'] for k, v in produced.items()}, {'A': False, 'B': False, 'C': True})
        self.assertEqual(produced['C']['evidence'], {'launched': 'S-1', 'returned': 'S-1'})
        self.assertTrue(all(p['session']['reuse'] is False for p in self.started()))       # never claimed before the adapter proves it


class ChangingTheDecision(ModeFixture):
    # case 6: the mode changes with capacity; nothing about budget, Control configuration or pins changes, and unknown work is never redone
    def other_root_attempts(self, count):
        from onecrew.task_intake import submit
        held = []
        self.tasks_held = getattr(self, 'tasks_held', [])
        for index in range(count):
            task = submit(self.ledger, 'Other work of this state root holding a slot', f'other-{index}-{len(self.tasks_held)}',
                          plan_selector='plan-ns:P1', max_calls=2, max_seconds=60, provider='codex', model='fixture-model')
            self.tasks_held.append(task['id'])
            execution = self.control.configure(task['id'], task['revision'], {'mode': 'fixture-other'})
            held.append(self.control.reserve(task['id'], execution['revision'], 'other', {'unit': 'root'}))
        return held

    def test_capacity_turns_overlap_into_one_slot_then_wait_without_touching_budget_or_pins(self):
        self.revise([worker('A', ['a.txt'], pin=True), worker('B', ['b.txt'], pin=True), integration(['A', 'B'], pin=True)])
        self.other_root_attempts(1)
        out = engine.run_batch(self.ledger, 'P1', self.isolated(), slots=2)
        by = {r.get('node'): r for r in out['results']}
        self.assertEqual(by['A']['state'], 'produced'); self.assertEqual(by['B']['mode'], 'run_now')
        self.assertIn('capacity_one_slot', by['B']['reasons'])
        self.other_root_attempts(1)                             # now this state root has no free slot at all
        tasks = self.tasks()
        waiting = engine.step(self.ledger, 'P1', self.isolated(), slots=2)
        self.assertEqual((waiting['state'], waiting['mode']), ('waiting', 'wait')); self.assertIn('capacity_full', waiting['reasons'])
        self.assertEqual(self.tasks(), tasks)                   # a capacity wait submits no child task
        self.assertEqual(self.modes('B')[-1]['mode'], 'wait')
        with self.ledger.transaction() as conn:
            rows = conn.execute("SELECT id,generation FROM attempts WHERE status='reserved'").fetchall()
        for row in rows: self.control.finish(row['id'], row['generation'], {'fixture': True}, not_started=True)
        before = self.used()
        self.assertEqual(engine.step(self.ledger, 'P1', self.isolated(), slots=2)['state'], 'produced')
        self.assertEqual(self.used(), before + 1)
        b = self.started('B')[-1]; self.assertEqual(b['mode'], 'run_now')
        child = self.ledger.task(b['child'], full=True)
        self.assertEqual({k: child['handoff']['owned_execution'][k] for k in ('provider', 'model')}, {'provider': 'codex', 'model': 'fixture-model'})
        with self.ledger.transaction() as conn:
            self.assertEqual(json.loads(conn.execute('SELECT configuration FROM executions WHERE task_id=?', (b['child'],)).fetchone()[0]),
                             {'mode': 'common-workflow-node', 'node': 'B'})

    def test_an_unknown_attempt_stays_held_and_a_continuation_keeps_its_budget(self):
        self.revise([worker('A', ['a.txt']), worker('B', ['b.txt']), integration(['A', 'B'])])
        calls = []
        def unsettled(ledger, control, task, item, attempt):
            calls.append(item['id']); control.launched(attempt['id'], attempt['generation'], {'fixture': True})
            return {'artifact': self.store.blob(b'unsettled'), 'receipt': self.store.blob(b'unsettled receipt')}
        self.assertEqual(self.step(unsettled)['state'], 'held')
        executor = self.isolated(self.partial_then_whole())
        for _ in range(2):
            engine.run_batch(self.ledger, 'P1', executor, slots=2)
        self.assertEqual(calls, ['A'])                                         # never redispatched
        view = engine.state(self.ledger, 'P1')
        self.assertEqual(view['nodes']['A']['phase'], 'held')
        resumed = self.payloads('node.resumed')
        self.assertTrue(resumed and all(p['budget_reset'] is False for p in resumed))
        b = self.started('B')
        self.assertEqual([p['mode'] for p in b], ['overlap', 'continue_worker'])     # beside A's unresolved attempt, which keeps its slot
        self.assertIn('independent_branch', b[0]['mode_reasons'])
        self.assertIn('not_a_model_session', b[-1]['mode_reasons']); self.assertIn('root_budget_not_reset', b[-1]['mode_reasons'])
        self.assertEqual(b[-1]['context']['restored_from'], ['source_snapshot', 'resume_artifact'])
        self.assertEqual(resumed[-1]['continues_attempt'], b[0]['attempt'])
        self.assertEqual(self.used(), 3)                                       # A once, B twice: spent calls stay spent, nothing is reset

    def partial_then_whole(self):
        seen = []
        def run(ledger, control, task, item, attempt):
            seen.append(item['id']); control.launched(attempt['id'], attempt['generation'], {'fixture': True})
            artifact = self.store.blob(('B-' + str(len(seen))).encode())
            control.finish(attempt['id'], attempt['generation'], {'fixture': True})
            partial = len(seen) == 1
            return {'artifact': artifact, 'receipt': self.receipt(node=item['id'], partial=partial, continuation={'remaining': 'rest'} if partial else None)}
        return run


class OptIn(ModeFixture):
    mode = False
    # case 7: a root without the capability chooses nothing, records nothing, and keeps the 2.3 event stream
    def test_without_the_capability_nothing_is_chosen_or_recorded(self):
        self.revise([worker('A', ['a.txt']), worker('B', ['b.txt'], read=['a.txt', 'b.txt']), integration(['A', 'B'])])
        self.assertEqual([c['id'] for c in engine.ready(self.ledger, 'P1', slots=2)], ['A', 'B'])     # the 2.3 readiness: writes only
        engine.run_batch(self.ledger, 'P1', self.isolated(), slots=2)
        self.assertEqual(engine.step(self.ledger, 'P1', self.isolated())['state'], 'waiting')
        self.assertNotIn('workflow.mode', self.kinds())
        keys = {'plan', 'revision', 'internal_revision', 'node', 'generation', 'attempt', 'child', 'early_dependencies', 'inputs', 'source', 'at'}
        for payload in self.started(): self.assertEqual(set(payload), keys)
        for decision in self.q2('A') + self.q2('B'):
            self.assertNotIn('key', decision); self.assertNotIn('mode', decision['evidence'][0]['action'])
        self.assertTrue(all('session' not in p for p in self.payloads('node.produced')))

    def test_the_capability_is_declared_classified_and_depends_on_the_sequential_engine(self):
        self.assertIn('execution-mode', namespaces.CAPABILITIES)
        self.assertEqual(namespaces.DEPENDENCIES['execution-mode'], {'namespaced-storage', 'root-budget', 'internal-plan', 'sequential-engine'})
        with self.assertRaisesRegex(LedgerError, 'requires'):
            namespaces.check_workflow({'workflow_version': 1, 'capabilities': ['namespaced-storage', 'root-budget', 'execution-mode']})
        self.assertEqual(compat.event_class('workflow.mode'), 'B')
        with self.assertRaisesRegex(LedgerError, 'class B'):
            compat.check_write('workflow.mode', {}, 'plan:legacy')


class EntryPoints(ModeFixture):
    """Both entry points with the shipped adapters: `engine step` = NativeExecutor (1 slot), `engine batch` = ManagedExecutor (2 slots)."""
    def setUp(self):
        super().setUp()
        previous = os.environ.get('ONECREW_HOST_HOME')
        os.environ['ONECREW_HOST_HOME'] = str(Path(self.temp.name) / 'host-home')
        self.addCleanup(lambda: os.environ.__setitem__('ONECREW_HOST_HOME', previous) if previous is not None else os.environ.pop('ONECREW_HOST_HOME', None))

    def factory(self, control, provider):
        import sys
        from onecrew.process_core import Supervisor, native_python
        from onecrew.subscription import environment
        case = self
        class LocalWorker:
            def capability(self): return {'provider': provider, 'mode': 'local-test-artifact-no-tools'}
            def run(self, attempt, prompt, schema, profile):
                directory = case.ledger.state_root / 'worker-io' / attempt['id']; directory.mkdir(parents=True)
                path = json.loads(prompt.split('\n', 1)[1])['node']['write'][0]
                value = {'summary': 'fixture', 'files': [{'path': path, 'content': 'candidate ' + path + '\n'}], 'backlog': []}
                script = 'import pathlib,sys\npathlib.Path("answer.json").write_text(sys.argv[1])\n'
                return Supervisor(control).run(attempt, [native_python(), '-c', script, json.dumps(value)], cwd=directory,
                                               timeout=min(20, profile['step_seconds']), env=environment())
            def result(self, attempt):
                return json.loads((case.ledger.state_root / 'worker-io' / attempt['id'] / 'answer.json').read_text()), []
        return LocalWorker()

    def test_engine_step_native_one_slot_and_engine_batch_managed_two_slots(self):
        from onecrew.common_executor import NativeExecutor
        from onecrew.v2.managed_executor import ManagedExecutor
        self.revise([worker('A', ['a.txt'], pin=True), worker('B', ['b.txt'], pin=True), worker('C', ['c.txt'], pin=True),
                     integration(['A', 'B', 'C'], pin=True)])
        native = engine.step(self.ledger, 'P1', NativeExecutor(self.ledger, worker_factory=self.factory))
        self.assertEqual(native['state'], 'produced', native)
        a = self.started('A')[0]
        self.assertEqual((a['mode'], a['mode_reasons'][-1]), ('run_now', 'single_slot'))
        self.assertEqual(a['context']['restored_from'], ['source_snapshot', 'knowledge']); self.assertFalse(a['session']['reuse'])
        batch = engine.run_batch(self.ledger, 'P1', ManagedExecutor(self.ledger, worker_factory=self.factory), slots=2)
        self.assertEqual({r['node']: r['state'] for r in batch['results']}, {'B': 'produced', 'C': 'produced'}, batch)
        self.assertEqual({p['mode'] for p in self.started() if p['node'] in ('B', 'C')}, {'overlap'})
        self.assertEqual(self.used(), 3)


class Measure(ModeFixture):
    def test_measurement_from_the_ledger_keeps_unknown_unknown_and_joins_overlap(self):
        self.revise([worker('U', ['c.txt']), worker('X', ['a.txt']), worker('B', ['b.txt'], depends=['U']), integration(['U', 'X', 'B'])])
        self.step(self.slow_prep(0.2, 1000)); self.verify('U')
        engine.run_batch(self.ledger, 'P1', self.isolated(), slots=2)       # X and B overlap (a small measured handover)
        self.assertEqual(self.step()['state'], 'waiting')                   # nothing ready: the wait is recorded, still open
        open_report = execution_mode.measure(self.ledger, 'P1')
        self.assertEqual(open_report['waits'][-1]['until'], 'unknown'); self.assertEqual(open_report['wait_seconds'], 'unknown')
        self.verify('X'); self.verify('B'); self.step()                      # I starts: the root wait ends
        report = execution_mode.measure(self.ledger, 'P1')
        self.assertIsInstance(report['time_to_first_useful_action_seconds'], float)
        u = next(a for a in report['attempts'] if a['node'] == 'U')
        self.assertGreaterEqual(u['preparation_seconds'], 0.2); self.assertEqual(u['prompt_chars'], 1000)
        self.assertIsInstance(u['admission_seconds'], float); self.assertEqual(u['mode'], 'run_now')
        self.assertEqual([v['node'] for v in report['verification']], ['U', 'X', 'B'])
        self.assertTrue(all(isinstance(v['seconds'], float) for v in report['verification']))
        self.assertIsInstance(report['waits'][-1]['seconds'], float); self.assertIsInstance(report['wait_seconds'], float)
        x = next(a for a in report['attempts'] if a['node'] == 'X')
        self.assertEqual(x['prompt_chars'], 'unknown')                       # an opaque receipt: not 0
        self.assertEqual({a['mode'] for a in report['attempts'] if a['node'] in ('X', 'B')}, {'overlap'})
        i = next(a for a in report['attempts'] if a['node'] == 'I')
        self.assertEqual(i['execution_seconds'], i['execution_seconds'])
        spans = [a['span_seconds'] for a in report['attempts']]
        self.assertTrue(all(isinstance(v, float) for v in spans))
        self.assertLessEqual(report['attempts_wall_seconds'], sum(spans) + 1e-6)   # union, never the sum of overlapping branches
        self.assertEqual(report['rework'], {'resumed': 0, 'verification_failed': 0, 'retained': 0})
        import contextlib, io
        from onecrew.v2 import engine_cli
        out, kinds = io.StringIO(), self.kinds()
        with contextlib.redirect_stdout(out):
            code = engine_cli.main(['--project', str(self.root), '--state-root', str(self.ledger.state_root), 'engine', 'measure', 'P1'])
        self.assertEqual(code, 0, out.getvalue())
        shown = json.loads(out.getvalue())
        self.assertEqual([a['attempt'] for a in shown['attempts']], [a['attempt'] for a in report['attempts']])
        self.assertEqual(self.kinds(), kinds)                                 # read-only
        (Path(self.temp.name) / 'measure-sample.json').write_text(out.getvalue(), encoding='utf-8')
        self.sample = shown


if __name__ == '__main__':
    import unittest
    unittest.main()
