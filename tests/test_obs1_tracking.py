"""OBS-1 tracking model (onecrew/v2/tracking.py): failure cases first, on a real temporary ledger with the real engine / Control.

What these tests pin: a missing or unreadable ledger is reported, never raised through the overview; every status carries its sources;
an attempt is running until ITS OWN settlement (a child task's checkpoint does not settle it); an attempt whose process outcome is unknown
is "chưa xác định", never running; a node of an older generation never changes the current state and the timeline says so; overlapping
attempts are joined by union, never summed; what the ledger does not hold (ETA without an estimate) is unknown, never a number; secrets
in a goal, a question or a receipt never reach the JSON or the text; tasks outside a plan and projects without a plan are "chưa được theo
dõi"; and the CLI JSON is the very dict the page reads.
"""
import datetime as dt
import json
import os
import threading
import time
from pathlib import Path
from unittest.mock import patch

from onecrew.ledger import LedgerError, Ledger
from onecrew.v2 import engine, executors, plan as plans, progress_track, tracking
from tests.test_v2_l1 import Fixture, plan_json
from tests.test_wf_engine import EngineFixture, node

QUESTION = {'schema_version': 1, 'question': 'Giữ CV trong bao lâu? (password=hunter2 must not show)', 'reason': 'Cần chốt thời hạn.',
            'impact': 'Phần lưu trữ chờ câu trả lời.', 'options': [{'id': 'seven', 'label': '7 ngày'}, {'id': 'thirty', 'label': '30 ngày'}],
            'recommendation': 'seven', 'action': {'type': 'clarify_retention', 'parameters': {'unit': 'days'}}}


def first_task(overview):
    return overview['projects'][0]['tasks'][0]


class _Blocking:
    """An executor whose attempt stays RUNNING until the test releases it (the engine step runs in a thread)."""
    def __init__(self, case):
        self.case, self.started, self.release = case, threading.Event(), threading.Event()
        self.result = {}

    def __call__(self, ledger, control, task, item, attempt):
        control.launched(attempt['id'], attempt['generation'], {'fixture': True})
        self.started.set()
        self.release.wait(20)
        store = self.case.store
        artifact, receipt = store.blob(('artifact-' + item['id']).encode()), store.blob(b'{"kind":"fixture-receipt","note":"api_key=sk-fixture-secret"}')
        control.finish(attempt['id'], attempt['generation'], {'fixture': True, 'artifact': artifact})
        return {'artifact': artifact, 'receipt': receipt}


class SourceTests(Fixture):
    def test_missing_ledger_is_reported_not_raised(self):
        root = Path(self.temp.name) / 'nowhere'
        value = tracking.overview(root)
        self.assertEqual(value['source']['status'], 'missing')
        self.assertEqual(value['projects'], [])
        self.assertIn('chưa được theo dõi', value['untracked']['statement'])
        with self.assertRaises(LedgerError): tracking.detail(root, 'P1')
        self.assertIn('nguồn: missing', tracking.render_overview(value))

    def test_garbage_ledger_is_unreadable_not_a_crash(self):
        root = Path(self.temp.name) / 'bad'; root.mkdir()
        (root / 'ledger.sqlite3').write_bytes(b'not a database at all' * 100)
        value = tracking.overview(root)
        self.assertEqual(value['source']['status'], 'unreadable', value['source'])
        self.assertTrue(value['source']['detail'])
        self.assertEqual(value['projects'], [])

    def test_proposed_root_waits_for_approval_and_needs_the_owner(self):
        self.propose('P1')
        t = first_task(tracking.overview(self.ledger.state_root))
        self.assertEqual(t['status']['kind'], 'waiting')
        self.assertEqual(t['root_status'], 'proposed')
        self.assertEqual([n['kind'] for n in t['needs_user']], ['approve'])
        self.assertEqual(t['status']['source'], ['plan.proposed:rev1'])
        self.assertEqual(t['elapsed']['seconds'], 'unknown')           # not approved: nothing has run
        self.assertEqual(t['tracking']['adapter'], 'milestones')

    def test_milestone_root_without_engine_says_so(self):
        self.approved()
        t = first_task(tracking.overview(self.ledger.state_root))
        self.assertEqual(t['status']['kind'], 'waiting')
        self.assertIn('không có engine', t['status']['reason'])
        self.assertEqual([m['id'] for m in t['milestones']], ['M1'])
        d = tracking.detail(self.ledger.state_root, 'P1')
        self.assertEqual(d['nodes'], {}); self.assertEqual(d['attempts'], [])
        self.assertIn('không có engine', d['measure']['note'])
        self.assertIsNone(d['eta']['remaining_seconds']); self.assertIn('chưa xác định', d['eta']['label']); self.assertNotIn('%', d['eta']['label'])


class EngineTests(EngineFixture):
    def overview(self):
        return tracking.overview(self.ledger.state_root)

    def detail(self, **kw):
        return tracking.detail(self.ledger.state_root, 'P1', **kw)

    def emit(self, nid, kind, **payload):
        with self.ledger.transaction(write=True) as conn:
            view = engine.state(self.ledger, 'P1', conn)
            engine._event(self.ledger, conn, view, nid, kind, **payload)

    def test_approved_but_not_started_is_waiting_not_running(self):
        self.revise([node('A'), node('I', ['A'], integration=True, write=())])
        t = first_task(self.overview())
        self.assertEqual(t['status']['kind'], 'waiting')
        self.assertIn('chưa có worker', t['status']['reason'])
        self.assertEqual(t['level']['kind'], 'none')
        self.assertEqual(t['active'], [])
        self.assertIsInstance(t['elapsed']['seconds'], float)

    def test_running_attempt_is_not_settled_by_its_child_task_completion(self):
        self.revise([node('A'), node('I', ['A'], integration=True, write=())])
        worker = _Blocking(self)
        thread = threading.Thread(target=self.step, args=(worker,), daemon=True); thread.start(); self.addCleanup(worker.release.set)
        self.assertTrue(worker.started.wait(10))
        t = first_task(self.overview())
        self.assertEqual(t['status']['kind'], 'running', t['status'])
        self.assertEqual(len(t['active']), 1); self.assertEqual(t['active'][0]['node'], 'A'); self.assertEqual(t['active'][0]['status'], 'running')
        self.assertTrue(t['status']['source'][0].startswith('attempt:'))
        self.assertIn('im lặng không phải', t['status']['reason'])     # no liveness observation yet: not inferred as stalled
        child = t['active'][0]
        d = self.detail()
        child_task = d['nodes']['A']['child']
        # the child task reports its own completion: the node's attempt is still not settled, so nothing is "done"
        with self.ledger.transaction(write=True) as conn:
            self.ledger._event(conn, child_task, 'workflow.checkpoint', {'phase': 'completed', 'message': 'child says done', 'verification': {}, 'acceptance': 'x', 'snapshot': None})
        t = first_task(self.overview())
        self.assertEqual(t['status']['kind'], 'running'); self.assertEqual(t['level']['kind'], 'none')
        self.assertEqual(self.detail()['nodes']['A']['phase'], 'running')
        worker.release.set(); thread.join(20)
        t = first_task(self.overview())
        self.assertEqual(t['status']['kind'], 'waiting'); self.assertEqual(t['level']['kind'], 'produced')
        self.assertIn('chờ kiểm', t['status']['reason'])
        self.assertEqual(t['last_evidence']['kind'], 'node.produced')
        d = self.detail()
        self.assertEqual(d['nodes']['A']['state'], 'produced')
        self.assertEqual([a['status'] for a in d['attempts']], ['settled'])
        self.assertIsInstance(d['measure']['attempts_wall_seconds'], float)
        self.assertNotIn('sk-fixture-secret', json.dumps(d, ensure_ascii=False))

    def test_unknown_attempt_outcome_is_unknown_or_blocked_never_running(self):
        self.revise([node('A'), node('I', ['A'], integration=True, write=())])
        def crash(ledger, control, task, item, attempt):
            control.launched(attempt['id'], attempt['generation'], {'fixture': True})
            raise RuntimeError('worker process vanished; token=sk-crash-secret-123')
        try: self.step(crash)
        except Exception: pass
        t = first_task(self.overview())
        self.assertIn(t['status']['kind'], ('blocked', 'unknown'))
        self.assertIn('unknown', t['status']['reason'])
        self.assertTrue(any(s.startswith('attempt:') for s in t['status']['source']), t['status'])
        self.assertNotIn('sk-crash-secret', json.dumps(t, ensure_ascii=False))
        self.assertNotIn('sk-crash-secret', tracking.render_overview(self.overview()))

    def test_old_generation_event_never_moves_the_current_state(self):
        self.revise([node('A'), node('I', ['A'], integration=True, write=())])
        self.step()                                                     # A produced, generation 0
        self.assertEqual(self.detail()['nodes']['A']['state'], 'produced')
        self.emit('A', 'node.resumed')                                  # the engine opens generation 1 (a retry / new generation)
        d = self.detail()
        self.assertEqual((d['nodes']['A']['generation'], d['nodes']['A']['phase'], d['nodes']['A']['state']), (1, 'pending', 'none'))
        with self.ledger.transaction(write=True) as conn:               # a late node.produced of generation 0 arrives after the resume
            view = engine.state(self.ledger, 'P1', conn)
            plans.emit(self.ledger, conn, view['root'], 'node.produced', {'plan': 'P1', 'revision': 1, 'internal_revision': view['internal_revision'],
                                                                           'node': 'A', 'generation': 0, 'artifact': 'a' * 64, 'receipt': 'b' * 64})
        d = self.detail()
        self.assertEqual((d['nodes']['A']['generation'], d['nodes']['A']['state']), (1, 'none'))
        late = [e for e in d['timeline'] if e['kind'] == 'node.produced' and e['generation'] == 0]
        self.assertTrue(late and late[-1]['stale_generation'] and 'thế hệ cũ' in late[-1]['note'])
        self.assertEqual(d['measure']['rework']['resumed'], 1)
        self.assertEqual(len({e['seq'] for e in d['timeline']}), len(d['timeline']))

    def test_held_node_is_blocked_with_its_reason_and_source(self):
        self.revise([node('A'), node('I', ['A'], integration=True, write=())])
        self.emit('A', 'node.held', reason='rounds exhausted after 3 model calls', classification='rounds_exhausted')
        t = first_task(self.overview())
        self.assertEqual(t['status']['kind'], 'blocked')
        self.assertIn('rounds exhausted', t['status']['reason'])
        self.assertEqual(t['status']['source'], ['node.held:A'])
        self.assertEqual(self.detail()['nodes']['A']['phase'], 'held')

    def test_pending_request_is_what_the_owner_must_decide_and_reading_does_not_answer(self):
        from tests.obs2_binding_fixture import bind
        bind(self, self.ledger)
        self.revise([node('A'), node('I', ['A'], integration=True, write=())])
        request = self.ledger.create_request(self.root_view['anchor_task'], 'retention', QUESTION)
        t = first_task(self.overview())
        self.assertEqual(t['status']['kind'], 'waiting')
        self.assertEqual(t['status']['source'], ['request:' + request['id']])
        need = t['needs_user'][0]
        self.assertEqual((need['kind'], need['id'], need['revision']), ('request', request['id'], request['revision']))
        self.assertIn('question answer ' + request['id'], need['reply_command'])
        self.assertEqual([o['id'] for o in need['options']], ['seven', 'thirty'])
        self.assertNotIn('hunter2', json.dumps(t, ensure_ascii=False))
        self.detail(); tracking.render_detail(self.detail())
        self.assertEqual(self.ledger.request(request['id'])['state'], 'pending')     # reading never answers

    def test_verified_nodes_wait_for_root_proof_and_accepted_is_accepted(self):
        self.revise([node('A'), node('I', ['A'], integration=True, write=())])
        self.step(); engine.verify(self.ledger, 'P1', 'A', self.checker)
        self.step(); engine.verify(self.ledger, 'P1', 'I', self.checker)
        t = first_task(self.overview())
        self.assertEqual((t['status']['kind'], t['level']['kind']), ('waiting', 'verified'))
        self.assertEqual(t['needs_user'], [])
        self.assertFalse(t['acceptance']['ready'])
        self.assertIn('M1',t['current_step'])
        self.assertEqual(t['last_evidence']['kind'], 'node.verification')
        with self.ledger.transaction(write=True) as conn:
            plans.emit(self.ledger, conn, self.root_view['anchor_task'], 'plan.accepted', {'plan': 'P1', 'revision': 1, 'by': 'owner', 'artifact_sha': 'x'})
        t = first_task(self.overview())
        self.assertEqual((t['status']['kind'], t['level']['kind'], t['root_status']), ('done', 'accepted', 'accepted'))
        self.assertEqual(t['needs_user'], [])
        self.assertIsNotNone(t['elapsed']['until'])

    def test_duplicate_observation_is_one_row_and_late_arrival_keeps_ledger_order(self):
        self.revise([node('A'), node('I', ['A'], integration=True, write=())])
        worker = _Blocking(self)
        thread = threading.Thread(target=self.step, args=(worker,), daemon=True); thread.start(); self.addCleanup(worker.release.set)
        self.assertTrue(worker.started.wait(10))
        attempt = first_task(self.overview())['active'][0]['attempt']
        class Managed(executors.Executor):
            declaration = executors.Declaration('fixture-managed', 'managed', ('measure',), ('time',))
        tool = {'kind': 'tool', 'action': 'read', 'args': {'path': 'a.txt'}, 'result': {'text': 'one'}, 'snapshot': 'snap-1'}
        early = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=5)).isoformat()
        progress_track.observe(self.ledger, 'P1', 'A', Managed(), attempt, 'k1', tool, source='tool_call', ref='call-1', at=None)
        progress_track.observe(self.ledger, 'P1', 'A', Managed(), attempt, 'k1', tool, source='tool_call', ref='call-1', at=None)    # same key: nothing written
        progress_track.observe(self.ledger, 'P1', 'A', Managed(), attempt, 'k2', tool, source='tool_call', ref='call-0', at=early)    # arrived late: observed earlier
        d = self.detail()
        rows = [e for e in d['timeline'] if e['kind'] == 'executor.observed']
        self.assertEqual(len(rows), 2)
        self.assertEqual([e['seq'] for e in rows], sorted(e['seq'] for e in rows))                   # ledger order, no reordering by observed time
        self.assertEqual(rows[1]['observed_at'], early)                                              # but the late arrival shows when it was observed
        self.assertEqual(d['last_evidence']['kind'], 'executor.observed')
        self.assertEqual(d['last_evidence']['seq'], rows[0]['seq'])                                  # the newest by OBSERVED time, not the last written
        self.assertEqual(d['progress']['A']['status'], 'progressing')
        t = first_task(self.overview())
        self.assertIn('quan sát gần nhất progressing', t['status']['reason'])
        worker.release.set(); thread.join(20)

    def test_secret_in_the_goal_never_reaches_json_or_text(self):
        value = plan_json()
        value['understanding']['restated_goal'] = 'Rotate the key Authorization: Bearer abc.def.ghi and update api_key=sk-live-123456 in config.'
        with self.ledger.transaction(write=True) as conn: pass
        plans.propose(self.ledger, 'P2', value, 'codex', workflow=True, capabilities=self.engine_caps)
        value_json = json.dumps(tracking.overview(self.ledger.state_root), ensure_ascii=False)
        text = tracking.render_overview(tracking.overview(self.ledger.state_root))
        for leak in ('abc.def.ghi', 'sk-live-123456'):
            self.assertNotIn(leak, value_json); self.assertNotIn(leak, text)
        self.assertIn('[withheld]', value_json)

    def test_eta_comes_from_the_recorded_estimate_and_is_a_range_never_a_percentage(self):
        self.revise([node('A'), node('I', ['A'], integration=True, write=())])
        d = self.detail()
        self.assertEqual(d['eta']['remaining_seconds'], [2, 4])                                 # the internal plan's own projection (estimate_seconds of the nodes)
        self.assertFalse(d['eta']['calibrated']); self.assertNotIn('%', d['eta']['label']); self.assertIn('không phải thời gian lịch', d['eta']['label'])
        bigger = node('A'); bigger['estimate_seconds'] = [1800, 3600]; bigger['execution_cap_seconds'] = 3600
        self.revise([bigger, node('I', ['A'], integration=True, write=())], reason='A is larger than thought')
        d = self.detail()                                                                       # the replan re-projects (internal_plan.revise observes it)
        self.assertEqual(d['eta']['remaining_seconds'], [1801, 3602])
        from onecrew.v2 import estimates
        estimates.observe_internal(self.ledger, 'P1', reason='re-projected after the replan', evidence=['a.txt:1'])
        d = self.detail()
        self.assertEqual(d['eta']['remaining_seconds'], [1801, 3602])
        self.assertIn('30m01s–1h00m', d['eta']['label']); self.assertIn('larger than thought', d['eta']['last_change'])   # the same basis reuses its record
        self.assertNotIn('%', json.dumps(d['eta'], ensure_ascii=False))

    def test_overlapping_attempts_are_joined_by_union_not_summed(self):
        from tests.test_wf_parallel_engine import ParallelFixture
        case = ParallelFixture('setUp'); case.setUp(); self.addCleanup(case.doCleanups)
        case.revise([node('A'), node('B', write=('b.txt',)), node('I', ['A', 'B'], integration=True, write=())])
        barrier = threading.Barrier(2)
        def together(ledger, control, task, item, attempt):
            control.launched(attempt['id'], attempt['generation'], {'fixture': True})
            barrier.wait(5); time.sleep(0.6)
            result = {'artifact': case.store.blob(('iso-' + item['id']).encode()), 'receipt': case.store.blob(b'fixture isolated result')}
            control.finish(attempt['id'], attempt['generation'], result)
            return result
        engine.run_batch(case.ledger, 'P1', case.isolated(together), slots=2)
        d = tracking.detail(case.ledger.state_root, 'P1')
        spans = [a['span_seconds'] for a in d['measure']['attempts'] if isinstance(a['span_seconds'], float)]
        self.assertEqual(len(spans), 2)
        self.assertLess(d['measure']['attempts_wall_seconds'], sum(spans))          # overlap counted once
        self.assertGreaterEqual(d['measure']['attempts_wall_seconds'], max(spans) - 0.01)
        self.assertEqual(d['nodes_summary']['produced'], 2)

    def test_tasks_outside_a_plan_and_projects_without_a_plan_are_not_tracked(self):
        self.revise([node('A'), node('I', ['A'], integration=True, write=())])
        self.step()
        from onecrew.task_intake import submit
        submit(self.ledger, 'A task outside any plan (v1-style)', 'v1-job')
        registry = Path(self.temp.name) / 'lad' / 'OneCrew'; registry.mkdir(parents=True)
        (registry / 'hook-projects.json').write_text(json.dumps({'projects': {str(Path(self.temp.name) / 'other-project'): str(self.ledger.state_root)}}), encoding='utf-8')
        with patch.dict(os.environ, {'LOCALAPPDATA': str(Path(self.temp.name) / 'lad')}):
            value = tracking.overview(self.ledger.state_root)
        other = value['untracked']['other_tasks']
        self.assertEqual([o['key'] for o in other], ['v1-job'])                                   # the engine's child task is NOT "untracked": its root is
        self.assertIn('chưa xác định', other[0]['phase'])
        self.assertEqual([r['project'] for r in value['untracked']['registry_projects_without_plan']], [str(Path(self.temp.name) / 'other-project')])
        self.assertIn('chưa được theo dõi', value['untracked']['registry_projects_without_plan'][0]['note'])
        self.assertIn('không biến một phiên chat', value['untracked']['statement'])
        self.assertEqual(value['tasks_total'], 1)

    def test_cli_json_is_the_same_model_and_text_lines_carry_the_sources(self):
        from onecrew.v2 import tracking_cli
        import io, contextlib
        self.revise([node('A'), node('I', ['A'], integration=True, write=())])
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = tracking_cli.main(['--project', str(self.root), '--state-root', str(self.ledger.state_root), 'track', 'list', '--json'])
        self.assertEqual(code, 0)
        cli = json.loads(out.getvalue()); direct = tracking.overview(self.ledger.state_root, project_id=self.ledger.project_id)
        for key in ('generated_at',): cli.pop(key); direct.pop(key)
        self.assertEqual(cli['projects'][0]['tasks'][0]['status'], direct['projects'][0]['tasks'][0]['status'])
        self.assertEqual(set(cli) - {'server'}, set(direct))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(tracking_cli.main(['--project', str(self.root), '--state-root', str(self.ledger.state_root), 'track', 'show', 'P1']), 0)
        self.assertIn('[plan.approved]', out.getvalue()); self.assertIn('Timeline', out.getvalue())
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(tracking_cli.main(['--project', str(self.root), '--state-root', str(self.ledger.state_root), 'track', 'show', 'NOPE']), 2)
        self.assertIn('error', out.getvalue())

    def test_evidence_only_for_keys_the_root_names_and_redacted(self):
        self.revise([node('A'), node('I', ['A'], integration=True, write=())])
        worker = _Blocking(self); worker.release.set()
        self.step(worker)
        d = self.detail()
        key = d['nodes']['A']['receipt']
        value = tracking.evidence(self.ledger.state_root, 'P1', key)
        self.assertIn('fixture-receipt', value['text']); self.assertNotIn('sk-fixture-secret', value['text']); self.assertIn('[withheld]', value['text'])
        foreign = self.store.blob(b'not referenced by any event of P1')
        with self.assertRaises(PermissionError): tracking.evidence(self.ledger.state_root, 'P1', foreign)
        with self.assertRaises(LedgerError): tracking.evidence(self.ledger.state_root, 'P1', 'zz')
