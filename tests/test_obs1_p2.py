"""OBS-1 — the four Codex P2 findings of 03/11/2026 (D:/OneCrewRuns/codex-obs1-review-20261103/probe.py), as red-before-green tests that
go through the real path: the ledger and the engine for P2-01..03 (plan.closed, progress_track.observe, executors.observe, engine.step),
HTTP for P2-04 (tracking_web.make_server with a project scope).

P2-01 closing a plan is not accepting it: the output level comes from the nodes' evidence, never from plan.closed.
P2-02 an observation of an older attempt never decides the current status; a valid observation of the current attempt still does.
P2-03 a wait that was closed (same attempt and ref, with `until`) is history, not a current wait; independent waits stay independent;
      a duplicate or late start of a closed wait does not reopen it; a wait of a settled attempt is not current.
P2-04 a request may narrow the project the server was started for, never widen it: overview, task and evidence alike; all-projects unchanged.
"""
import json
import subprocess
import threading
import urllib.error
import urllib.request

from onecrew.ledger import Ledger
from onecrew.snapshots import Snapshots
from onecrew.v2 import engine, executors, plan as plans, progress_track, tracking, tracking_web
from tests.test_obs1_tracking import _Blocking
from tests.test_v2_l1 import Fixture, plan_json
from tests.test_wf_engine import EngineFixture, node


class Managed(executors.Executor):
    declaration = executors.Declaration('fixture-managed', 'managed', ('measure',), ('time',))


class P2Fixture(EngineFixture):
    def detail(self):
        return tracking.detail(self.ledger.state_root, 'P1')

    def overview_task(self):
        return tracking.overview(self.ledger.state_root)['projects'][0]['tasks'][0]

    def two_nodes(self):
        self.revise([node('A'), node('I', ['A'], integration=True, write=())])

    def close(self, reason='owner cancelled the unfinished task'):
        with self.ledger.transaction(write=True) as conn:
            root = plans.anchor_events(self.ledger, conn, 'P1')
            plans.emit(self.ledger, conn, root['task_id'], 'plan.closed', {'revision': 1, 'reason': reason})

    def attempt_of(self, nid):
        return self.detail()['nodes'][nid]['attempt']

    def blocking_worker(self):
        worker = _Blocking(self)
        thread = threading.Thread(target=self.step, args=(worker,), daemon=True); thread.start()
        self.addCleanup(thread.join, 20); self.addCleanup(worker.release.set)
        self.assertTrue(worker.started.wait(10))
        return worker, thread

    def observe_command(self, attempt, key, elapsed=60):
        progress_track.observe(self.ledger, 'P1', 'A', Managed(), attempt, key, {'kind': 'command', 'elapsed_seconds': elapsed},
                               source='tool_call', ref='receipt-' + key, command_cap_seconds=60)

    def wait(self, attempt, ref, until=None, at='2026-11-03T00:00:00+00:00', reason='external_service'):
        return executors.observe(self.ledger, 'P1', Managed(), attempt, 'wait', source='tool_call', ref=ref, at=at, until=until, wait_reason=reason)


class ClosedIsNotAccepted(P2Fixture):
    def test_closing_an_unstarted_plan_shows_no_output_not_accepted(self):              # P2-01, the probe's case
        self.two_nodes(); self.close()
        d = self.detail()
        self.assertEqual(d['root_status'], 'closed')
        self.assertEqual(d['level']['kind'], 'none', d['level'])
        self.assertNotEqual(d['level']['label'], tracking.LEVEL_WORDS['accepted'])
        self.assertEqual(d['status']['kind'], 'done')
        self.assertIn('đóng', d['status']['reason']); self.assertIn('không phải nghiệm thu', d['status']['reason'])
        self.assertEqual(d['status']['source'], ['plan.closed'])
        self.assertEqual(d['needs_user'], [])
        self.assertEqual(self.overview_task()['level']['kind'], 'none')               # the list and the detail agree

    def test_closing_after_one_produced_node_keeps_the_produced_level(self):            # P2-01: the level is the nodes' evidence
        self.two_nodes(); self.step(); self.close()
        d = self.detail()
        self.assertEqual(d['nodes']['A']['state'], 'produced'); self.assertEqual(d['nodes']['I']['state'], 'none')
        self.assertEqual(d['level']['kind'], 'produced', d['level'])
        self.assertEqual(d['status']['kind'], 'done'); self.assertIn('đóng', d['status']['reason'])

    def test_accepting_is_still_accepted(self):                                        # the fix must not touch plan.accepted
        self.two_nodes(); self.step(); self.verify('A'); self.step(); self.verify('I')
        with self.ledger.transaction(write=True) as conn:
            plans.emit(self.ledger, conn, self.root_view['anchor_task'], 'plan.accepted', {'plan': 'P1', 'revision': 1, 'by': 'owner', 'artifact_sha': 'x'})
        d = self.detail()
        self.assertEqual((d['root_status'], d['level']['kind'], d['status']['kind']), ('accepted', 'accepted', 'done'))


class OldAttemptObservation(P2Fixture):
    def test_a_late_blocked_observation_of_the_old_attempt_does_not_block_the_new_one(self):    # P2-02, the probe's case
        self.two_nodes(); self.step()                                       # A produced by attempt 1 (generation 0)
        old = self.attempt_of('A')
        with self.ledger.transaction(write=True) as conn:
            view = engine.state(self.ledger, 'P1', conn); engine._event(self.ledger, conn, view, 'A', 'node.resumed')     # generation 1
        worker, thread = self.blocking_worker()                             # attempt 2 of A, running
        before = self.detail()
        new = before['nodes']['A']['attempt']
        self.assertNotEqual(old, new); self.assertEqual(before['status']['kind'], 'running')
        self.observe_command(old, 'late-old-command')                       # blocked (cap reached) — but of the OLD attempt, arriving now
        after = self.detail()
        self.assertEqual(after['status']['kind'], 'running', after['status'])
        self.assertEqual(after['nodes']['A']['attempt'], new)
        self.assertIsNone(after['nodes']['A']['progress'], 'the old attempt\u2019s observation is not the current node progress')
        self.assertNotIn('A', after['progress'])
        self.assertEqual(self.overview_task()['status']['kind'], 'running')
        row = [e for e in after['timeline'] if e['kind'] == 'executor.observed' and e['attempt'] == old]
        self.assertEqual(len(row), 1); self.assertTrue(row[0]['stale_attempt']); self.assertIn('attempt cũ', row[0]['note'])     # still visible as history
        self.observe_command(new, 'current-command')                        # the SAME observation of the CURRENT attempt still blocks
        now = self.detail()
        self.assertEqual(now['status']['kind'], 'blocked', now['status'])
        self.assertIn('executor.observed:', ' '.join(now['status']['source']))
        self.assertEqual(now['nodes']['A']['progress']['attempt'], new); self.assertEqual(now['progress']['A']['status'], 'blocked')
        current = [e for e in now['timeline'] if e['kind'] == 'executor.observed' and e['attempt'] == new]
        self.assertEqual(len(current), 1); self.assertFalse(current[0]['stale_attempt'])
        worker.release.set(); thread.join(20)

    def test_running_reason_quotes_only_the_current_attempts_observation(self):        # P2-02: "quan sát gần nhất" is the current attempt's
        self.two_nodes(); self.step()
        old = self.attempt_of('A')
        with self.ledger.transaction(write=True) as conn:
            view = engine.state(self.ledger, 'P1', conn); engine._event(self.ledger, conn, view, 'A', 'node.resumed')
        worker, thread = self.blocking_worker()
        self.observe_command(old, 'old-progress', elapsed=5)                # progressing, old attempt
        t = self.overview_task()
        self.assertEqual(t['status']['kind'], 'running'); self.assertIn('chưa có quan sát tiến độ', t['status']['reason'])
        worker.release.set(); thread.join(20)


class EndedWaits(P2Fixture):
    def test_a_closed_wait_is_history_and_the_verified_plan_is_done(self):              # P2-03, the probe's case
        self.two_nodes(); self.step(); att = self.attempt_of('A')
        self.wait(att, 'wait-receipt')
        self.wait(att, 'wait-receipt', until='2026-11-03T00:00:05+00:00')
        self.verify('A'); self.step(); self.verify('I')
        d = self.detail()
        self.assertEqual(d['level']['kind'], 'verified')
        self.assertEqual(d['status']['kind'], 'done', d['status'])
        self.assertEqual([w for w in d['waits'] if w['open']], [])
        closed = [w for w in d['waits'] if not w['open']]
        self.assertEqual(len(closed), 1); self.assertEqual(closed[0]['until'], '2026-11-03T00:00:05+00:00')   # kept as history
        self.assertEqual([w['until'] for w in d['measure']['executor_waits']], ['2026-11-03T00:00:05+00:00'])     # and measured (executors.summary)
        self.assertEqual([n['kind'] for n in d['needs_user']], ['accept'])

    def test_independent_waits_and_duplicate_or_late_events(self):                      # P2-03: several waits, duplicates, late arrivals
        self.two_nodes(); worker, thread = self.blocking_worker(); att = self.detail()['nodes']['A']['attempt']
        self.wait(att, 'w1'); self.wait(att, 'w2', at='2026-11-03T00:00:01+00:00', reason='resource')
        d = self.detail(); self.assertEqual(sorted(w['ref'] for w in d['waits'] if w['open']), ['w1', 'w2']); self.assertEqual(d['status']['kind'], 'waiting')
        self.wait(att, 'w1', until='2026-11-03T00:00:05+00:00')
        d = self.detail(); self.assertEqual([w['ref'] for w in d['waits'] if w['open']], ['w2']); self.assertIn('resource', d['status']['reason'])
        self.assertEqual(self.wait(att, 'w1')['written'], False)                      # the exact duplicate start is not written at all
        self.wait(att, 'w1', at='2026-11-02T23:59:59+00:00')                         # a late, differently-timed start of the closed wait
        d = self.detail(); self.assertEqual([w['ref'] for w in d['waits'] if w['open']], ['w2'], 'a closed wait is not reopened by a late start')
        self.wait(att, 'w2', at='2026-11-03T00:00:01+00:00', until='2026-11-03T00:00:09+00:00', reason='resource')
        d = self.detail(); self.assertEqual([w for w in d['waits'] if w['open']], []); self.assertEqual(d['status']['kind'], 'running')
        self.assertEqual(len(d['waits']), 2)                                           # both kept, by (attempt, ref), with no duplicate rows
        worker.release.set(); thread.join(20)

    def test_a_wait_of_a_settled_attempt_is_not_a_current_wait(self):                   # P2-03: the attempt ended; its open wait has an unknown end
        self.two_nodes(); self.step(); att = self.attempt_of('A')
        self.wait(att, 'never-closed')
        d = self.detail()
        self.assertEqual(d['attempts'][0]['status'], 'settled')
        self.assertEqual([w for w in d['waits'] if w['open']], [])
        self.assertEqual(d['waits'][0]['until'], 'unknown')
        self.assertEqual(d['status']['kind'], 'waiting'); self.assertIn('chờ kiểm', d['status']['reason'])   # produced, waiting for verification


class ProjectScope(Fixture):
    """P2-04 over HTTP: a server started for project A (--project-only) never serves project B, whatever the query says."""
    def setUp(self):
        super().setUp()
        self.propose('P1')
        other = self.root.parent / 'projectB'; other.mkdir(); (other / 'a.txt').write_text('test')
        for args in (('init', '-q'), ('config', 'user.name', 'T'), ('config', 'user.email', 't@local'), ('add', '.'), ('commit', '-qm', 'init')):
            subprocess.run(['git', '-C', str(other), *args], check=True, capture_output=True)
        self.ledger_b = Ledger(other, self.ledger.state_root)
        plans.propose(self.ledger_b, 'P2', plan_json(title='PROJECT B PRIVATE GOAL'), 'claude')
        self.key_b = Snapshots(self.ledger_b.state_root).blob(b'PROJECT B PRIVATE EVIDENCE')
        with self.ledger_b.transaction(write=True) as conn:
            root = plans.anchor_events(self.ledger_b, conn, 'P2')
            plans.emit(self.ledger_b, conn, root['task_id'], 'workflow.checkpoint', {'phase': 'review', 'message': 'test', 'evidence': self.key_b})

    def serve(self, project_id):
        server = tracking_web.make_server(self.ledger.state_root, project_id=project_id)
        thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': 0.2}, daemon=True); thread.start()
        def stop():
            server.shutdown(); server.server_close(); thread.join(5)
        self.addCleanup(stop)
        return tracking_web.url_of(server)

    @staticmethod
    def get(url):
        try:
            with urllib.request.urlopen(url, timeout=20) as r: return r.status, json.load(r)
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read().decode('utf-8'))

    def test_a_project_only_server_never_widens_to_another_project(self):
        a, b = self.ledger.project_id, self.ledger_b.project_id
        base = self.serve(a)
        self.assertEqual(self.get(base + 'api/overview')[1]['tasks_total'], 1)
        self.assertEqual(self.get(base + 'api/task?plan=P2')[0], 404)
        for path in ('api/overview?project_id=' + b, 'api/task?plan=P2&project_id=' + b, f'api/evidence?plan=P2&key={self.key_b}&project_id={b}',
                     'api/overview?project_id=' + 'f' * 64, 'api/task?plan=P1&project_id=' + 'f' * 64):
            status, body = self.get(base + path)
            self.assertEqual(status, 403, path); self.assertIn('phạm vi', body['error']); self.assertNotIn('PRIVATE', json.dumps(body))
        status, body = self.get(base + 'api/overview?project_id=' + a)                   # the server's own project may be named
        self.assertEqual(status, 200); self.assertEqual([p['tasks'][0]['plan'] for p in body['projects']], ['P1'])
        self.assertEqual(self.get(base + 'api/task?plan=P1&project_id=' + a)[0], 200)
        health = self.get(base + 'api/health')[1]; self.assertEqual(health['project_id'], a)

    def test_an_all_projects_server_narrows_but_still_serves_everything(self):
        a, b = self.ledger.project_id, self.ledger_b.project_id
        base = self.serve(None)
        self.assertEqual(self.get(base + 'api/overview')[1]['tasks_total'], 2)
        status, body = self.get(base + 'api/overview?project_id=' + b)
        self.assertEqual(status, 200); self.assertEqual(body['tasks_total'], 1); self.assertEqual(body['projects'][0]['tasks'][0]['plan'], 'P2')
        self.assertEqual(self.get(base + 'api/task?plan=P2&project_id=' + b)[0], 200)
        self.assertEqual(self.get(base + 'api/task?plan=P2')[0], 200)
        self.assertEqual(self.get(base + f'api/evidence?plan=P2&key={self.key_b}&project_id={b}')[1]['text'], 'PROJECT B PRIVATE EVIDENCE')
        self.assertEqual(self.get(base + 'api/task?plan=P1&project_id=' + b)[0], 404)   # narrowing to the wrong project finds nothing


if __name__ == '__main__':
    import unittest
    unittest.main()
