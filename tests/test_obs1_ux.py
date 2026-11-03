"""OBS-1 UX/server-identity round of 03/11/2026 (docs/obs1/UX-OBS-1.vi.md): the FUNCTIONAL layer, on the real ledger/engine and over HTTP.

UX-05 the three "done" are three words (accepted / verified-awaiting-acceptance / closed) and the elapsed figure says what it measures;
UX-03 every option of an owner question carries its own ready reply command (text; nothing here runs it);
UX-07 every evidence blob a root names has a label, a kind and a time (`evidence_index`), and the list has a `current_step` line;
P2 server identity: `track open` reuses a server only when the marker's URL answers with the marker's instance, this wheel's version, the same
state root and scope — a marker without instance (older wheel), a port answered by another server (other ledger), a dead server or a different
scope is refused, nothing is killed; two concurrent opens start ONE server and keep its marker; `track stop` stops only the matching server.
The interaction layer (clicks, keyboard, polls, viewports) is tests/test_obs1_browser.py.
"""
import json
import os
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

from onecrew.v2 import engine, plan as plans, tracking, tracking_web
from tests.test_obs1_tracking import QUESTION, _Blocking, first_task
from tests.test_v2_l1 import Fixture
from tests.test_wf_engine import EngineFixture, node


class OutcomeWords(EngineFixture):
    def two(self):
        self.revise([node('A'), node('I', ['A'], integration=True, write=())])

    def test_closed_verified_and_accepted_are_three_different_words_and_badges(self):           # UX-05
        self.two()
        with self.ledger.transaction(write=True) as conn:
            plans.emit(self.ledger, conn, self.root_view['anchor_task'], 'plan.closed', {'revision': 1, 'reason': 'cancelled'})
        t = first_task(tracking.overview(self.ledger.state_root))
        self.assertEqual((t['status']['kind'], t['status']['outcome'], t['status']['label']), ('done', 'closed', 'đã đóng'))
        self.assertEqual(t['current_step'], 'kết thúc: plan đã đóng')
        self.assertIn('[đã đóng] P1', tracking.render_overview(tracking.overview(self.ledger.state_root)))

    def test_verified_awaits_acceptance_in_its_own_word(self):
        self.two(); self.step(); self.verify('A'); self.step(); self.verify('I')
        t = first_task(tracking.overview(self.ledger.state_root))
        self.assertEqual((t['status']['kind'], t['status']['outcome'], t['status']['label']), ('done', 'verified', 'đã kiểm, chờ nghiệm thu'))
        self.assertEqual(t['current_step'], 'mọi phần việc đã kiểm: chờ bạn nghiệm thu')
        with self.ledger.transaction(write=True) as conn:
            plans.emit(self.ledger, conn, self.root_view['anchor_task'], 'plan.accepted', {'plan': 'P1', 'revision': 1, 'by': 'owner', 'artifact_sha': 'x'})
        t = first_task(tracking.overview(self.ledger.state_root))
        self.assertEqual((t['status']['outcome'], t['status']['label']), ('accepted', 'đã nghiệm thu'))
        self.assertIsNone(first_task(tracking.overview(self.ledger.state_root))['needs_user'] or None)

    def test_running_and_waiting_keep_the_plain_words_and_the_elapsed_label_names_its_measure(self):
        self.two()
        t = first_task(tracking.overview(self.ledger.state_root))
        self.assertEqual((t['status']['label'], t['status']['outcome']), ('đang chờ', None))
        self.assertEqual(t['elapsed']['label'], tracking.ELAPSED_LABEL)
        self.assertIn('lịch', t['elapsed']['label']); self.assertIn('chờ', t['elapsed']['label'])
        self.assertEqual(t['current_step'], 'chưa bắt đầu phần việc A, I')
        worker = _Blocking(self); thread = threading.Thread(target=self.step, args=(worker,), daemon=True); thread.start()
        self.assertTrue(worker.started.wait(10))
        t = first_task(tracking.overview(self.ledger.state_root))
        self.assertEqual(t['status']['label'], 'đang thực hiện'); self.assertEqual(t['current_step'], 'đang chạy phần việc A')
        worker.release.set(); thread.join(20)
        t = first_task(tracking.overview(self.ledger.state_root))
        self.assertEqual(t['current_step'], 'chờ kiểm phần việc A')


class QuestionCommands(EngineFixture):
    def test_each_option_has_its_own_reply_command_and_the_question_context(self):             # UX-03
        self.revise([node('A'), node('I', ['A'], integration=True, write=())])
        request = self.ledger.create_request(self.root_view['anchor_task'], 'retention', QUESTION)
        need = first_task(tracking.overview(self.ledger.state_root))['needs_user'][0]
        self.assertEqual([o['id'] for o in need['options']], ['seven', 'thirty'])
        for o in need['options']:
            self.assertEqual(o['reply_command'], f"question answer {request['id']} --revision {request['revision']} --choice {o['id']}")
        self.assertEqual(need['recommendation'], 'seven'); self.assertEqual(need['reason'], 'Cần chốt thời hạn.')
        self.assertNotIn('hunter2', json.dumps(need, ensure_ascii=False))
        self.assertEqual(self.ledger.request(request['id'])['state'], 'pending')
        self.assertIn('chờ bạn trả lời câu hỏi ' + request['id'], first_task(tracking.overview(self.ledger.state_root))['current_step'])


class EvidenceIndex(EngineFixture):
    def test_every_evidence_key_has_a_label_a_kind_and_a_time(self):                            # UX-07
        self.revise([node('A'), node('I', ['A'], integration=True, write=())])
        worker = _Blocking(self); worker.release.set(); self.step(worker); self.verify('A')
        d = tracking.detail(self.ledger.state_root, 'P1')
        index = {x['key']: x for x in d['evidence_index']}
        self.assertEqual(set(index), set(d['evidence_keys']))
        receipt = d['nodes']['A']['receipt']
        self.assertEqual(index[receipt]['kind'], 'node.produced'); self.assertEqual(index[receipt]['node'], 'A')
        self.assertTrue(index[receipt]['at']); self.assertIn('đã tạo đầu ra', index[receipt]['label'])
        self.assertEqual([x for x in d['evidence_index'] if x['seq'] is not None], sorted((x for x in d['evidence_index'] if x['seq'] is not None), key=lambda x: x['seq']))
        self.assertNotIn('sk-fixture-secret', json.dumps(d, ensure_ascii=False))


class _Server:
    """An in-process tracking server of a state root (any instance), on a free or a given port."""
    def __init__(self, state_root, port=0, instance=None, project_id=None):
        self.server = tracking_web.make_server(state_root, port=port, interval=1.0, instance=instance, project_id=project_id)
        self.url = tracking_web.url_of(self.server); self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={'poll_interval': 0.2}, daemon=True); self.thread.start()

    def stop(self):
        try: self.server.shutdown(); self.server.server_close()
        except OSError: pass


class ServerIdentity(Fixture):
    """P2 (03/11): the reuse decision of `track open`, with real servers answering /api/health, and the marker as `track serve` writes it."""
    def setUp(self):
        super().setUp()
        self.state = self.ledger.state_root
        self.marker = self.state / tracking_web.MARKER
        self.here = tracking_web.version()

    def record(self, server, **more):
        rec = {'url': server.url, 'pid': os.getpid(), 'instance': server.server.track_identity['instance'], 'version': self.here, 'state_root': str(self.state),
               'project_id': None, 'poll_seconds': 1.0, 'read_only': True, 'started_at': 'x'}
        rec.update(more); return rec

    def write(self, rec):
        tracking_web._write_marker(self.marker, rec)

    def open(self, **kw):
        return tracking_web.open_page(self.state, browser=False, spawn=False, **kw)

    def test_health_carries_the_identity_and_the_marker_of_serve_matches_it(self):
        srv = _Server(self.state); self.addCleanup(srv.stop)
        health = tracking_web.identity(srv.url)
        self.assertEqual((health['instance'], health['version'], health['state_root'], health['pid'], health['server']),
                         (srv.server.track_identity['instance'], self.here, str(self.state), os.getpid(), tracking_web.SERVER_NAME))
        self.assertTrue(tracking_web.reusable(self.record(srv), health, self.state, None)[0])

    def test_own_live_server_is_reused_and_reported_as_such(self):
        srv = _Server(self.state); self.addCleanup(srv.stop)
        self.write(self.record(srv))
        result = self.open()
        self.assertTrue(result.get('reused'), result); self.assertEqual(result['url'], srv.url); self.assertEqual(result['version_here'], self.here)

    def test_marker_of_an_older_wheel_without_instance_is_not_reused(self):                    # Codex reuse.py: a dev6 server was reused by dev7
        srv = _Server(self.state); self.addCleanup(srv.stop)
        old = self.record(srv); old.pop('instance'); old['version'] = '2.4.0.dev6+obs1'; self.write(old)
        result = self.open()
        self.assertIn('error', result); self.assertIn('wheel cũ', result['refused']['reason'])
        self.assertTrue(srv.thread.is_alive()); self.assertIsNotNone(tracking_web.identity(srv.url))      # nothing was killed

    def test_a_port_taken_over_by_a_server_of_another_ledger_is_not_opened_as_success(self):   # Codex wrong-state.py
        srv = _Server(self.state); port = srv.port; srv.stop()
        rec = self.record(srv)                                                                 # the marker of the server that died (its port is free now)
        other_root = Path(self.temp.name) / 'other state'; other_root.mkdir()
        other = _Server(other_root, port=port); self.addCleanup(other.stop)                   # another process took the port
        self.write(rec)
        result = self.open()
        self.assertIn('error', result); self.assertIn('định danh khác', result['refused']['reason'])
        health = tracking_web.identity(other.url)
        self.assertEqual(health['state_root'], str(other_root)); self.assertIsNotNone(health)        # the foreign server is untouched
        status = tracking_web.status_page(self.state)
        self.assertFalse(status['reusable']); self.assertIn('định danh khác', status['reason'])

    def test_same_instance_but_other_version_state_root_or_scope_is_refused(self):
        srv = _Server(self.state); self.addCleanup(srv.stop)
        health = tracking_web.identity(srv.url)
        rec = self.record(srv)
        self.assertIn('version khác', tracking_web.reusable(rec, health, self.state, None, here=self.here + '.x')[1])
        self.assertIn('state-root', tracking_web.reusable(rec, health, Path(self.temp.name) / 'elsewhere', None)[1])
        self.assertIn('phạm vi project', tracking_web.reusable(rec, health, self.state, 'abc')[1])
        self.assertIn('không trả lời', tracking_web.reusable(rec, None, self.state, None)[1])
        wrong_pid = dict(rec, pid=rec['pid'] + 1)
        self.assertIn('PID', tracking_web.reusable(wrong_pid, health, self.state, None)[1])

    def test_dead_server_marker_is_not_reused_and_stop_removes_it_without_killing(self):
        srv = _Server(self.state); rec = self.record(srv); srv.stop(); self.write(rec)
        self.assertIn('error', self.open())
        result = tracking_web.stop_page(self.state)
        self.assertFalse(result['stopped']); self.assertTrue(result['marker_removed']); self.assertFalse(self.marker.exists())

    def test_stop_refuses_a_foreign_server_on_the_markers_port(self):
        srv = _Server(self.state); port = srv.port; srv.stop(); rec = self.record(srv)
        other_root = Path(self.temp.name) / 'other state'; other_root.mkdir()
        other = _Server(other_root, port=port); self.addCleanup(other.stop); self.write(rec)
        result = tracking_web.stop_page(self.state)
        self.assertFalse(result['stopped']); self.assertIn('không dừng tiến trình lạ', result['reason'])
        self.assertIsNotNone(tracking_web.identity(other.url))

    def test_lock_held_by_another_open_waits_for_its_marker(self):
        lock = self.state / tracking_web.LOCK; lock.parent.mkdir(parents=True, exist_ok=True); lock.write_text('')
        srv = _Server(self.state); self.addCleanup(srv.stop)
        def later():
            time.sleep(0.8); self.write(self.record(srv)); lock.unlink()
        threading.Thread(target=later, daemon=True).start()
        result = self.open(wait=3)
        self.assertTrue(result.get('reused'), result); self.assertTrue(result.get('waited_for_other_open'))


class DetachedOpen(Fixture):
    """`track open` for real: the detached `track serve` child, two concurrent opens, status and stop through the CLI module."""
    def setUp(self):
        super().setUp()
        self.state = self.ledger.state_root
        self.env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1]) + os.pathsep + os.environ.get('PYTHONPATH', ''))

    def cli(self, *args):
        done = subprocess.run([sys.executable, '-X', 'utf8', '-m', 'onecrew.v2.tracking_cli', '--project', str(self.root), '--state-root', str(self.state), 'track', *args],
                              capture_output=True, text=True, encoding='utf-8', env=self.env, cwd=str(Path(__file__).resolve().parents[1]), timeout=60)
        return done.returncode, done.stdout

    def test_two_concurrent_opens_share_one_server_and_stop_ends_only_it(self):
        results = [None, None]
        env = self.env; original = os.environ.copy()
        os.environ.update(env)
        try:
            def go(i):
                results[i] = tracking_web.open_page(self.state, browser=False, project=self.root, explicit_state_root=self.state, idle_exit=120, interval=1.0)
            threads = [threading.Thread(target=go, args=(i,)) for i in range(2)]
            for t in threads: t.start()
            for t in threads: t.join(40)
        finally:
            os.environ.clear(); os.environ.update(original)
        try:
            self.assertTrue(all(r and r.get('url') for r in results), results)
            self.assertEqual(results[0]['url'], results[1]['url']); self.assertEqual(results[0]['instance'], results[1]['instance'])
            self.assertEqual(sorted(bool(r.get('reused')) for r in results), [False, True])
            marker = json.loads((self.state / tracking_web.MARKER).read_text(encoding='utf-8'))
            health = tracking_web.identity(results[0]['url'])
            self.assertEqual((marker['instance'], health['instance'], health['version']), (results[0]['instance'], results[0]['instance'], tracking_web.version()))
            code, out = self.cli('status'); status = json.loads(out)
            self.assertEqual(code, 0); self.assertTrue(status['reusable'], status)
            third = tracking_web.open_page(self.state, browser=False, spawn=False)
            self.assertTrue(third.get('reused'))
            code, out = self.cli('stop'); stopped = json.loads(out)
            self.assertEqual(code, 0, out); self.assertTrue(stopped['stopped']); self.assertEqual(stopped['pid'], results[0]['pid'])
            self.assertIsNone(tracking_web.identity(results[0]['url'])); self.assertFalse((self.state / tracking_web.MARKER).exists())
            code, out = self.cli('stop')
            self.assertEqual(code, 2); self.assertIn('không có marker', out)
        finally:
            for r in results:
                if r and r.get('pid'):
                    try: os.kill(r['pid'], 15)
                    except OSError: pass
