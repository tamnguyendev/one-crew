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
import unittest
import urllib.request
from pathlib import Path

from onecrew.ledger import Ledger
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
    def test_each_option_has_a_complete_template_with_project_state_root_and_reference(self):  # UX-03 + P2-B (dev8: the command lacked --reference)
        self.revise([node('A'), node('I', ['A'], integration=True, write=())])
        request = self.ledger.create_request(self.root_view['anchor_task'], 'retention', QUESTION)
        need = first_task(tracking.overview(self.ledger.state_root))['needs_user'][0]
        self.assertEqual([o['id'] for o in need['options']], ['seven', 'thirty'])
        for o in need['options']:
            self.assertTrue(o['reply_command'].endswith(f" --project '{self.ledger.project_path}' --state-root '{self.ledger.state_root}' question answer {request['id']} "
                                                        f"--revision {request['revision']} --choice {o['id']} --reference '{tracking.REFERENCE_PLACEHOLDER}'"), o['reply_command'])
            self.assertTrue(o['reply_command'].startswith("& '") or o['reply_command'].startswith('onecrew '))
        self.assertEqual(need['reply_shell'], 'PowerShell')
        self.assertEqual(need['placeholders'], ['reference']); self.assertIn('mẫu lệnh', need['reply_note'])
        self.assertIn('--reference', need['reply_command']); self.assertIn('<option-id>', need['reply_command'])
        self.assertEqual(need['recommendation'], 'seven'); self.assertEqual(need['reason'], 'Cần chốt thời hạn.')
        self.assertNotIn('hunter2', json.dumps(need, ensure_ascii=False))
        self.assertEqual(self.ledger.request(request['id'])['state'], 'pending')
        self.assertIn('chờ bạn trả lời câu hỏi ' + request['id'], first_task(tracking.overview(self.ledger.state_root))['current_step'])

    def test_the_template_is_what_the_real_parser_wants_and_the_placeholder_must_be_filled(self):   # P2-B through onecrew.console, from a cwd with a space
        self.revise([node('A'), node('I', ['A'], integration=True, write=())])
        request = self.ledger.create_request(self.root_view['anchor_task'], 'retention', QUESTION)
        need = first_task(tracking.overview(self.ledger.state_root))['needs_user'][0]
        template = need['options'][1]['reply_command']
        elsewhere = Path(self.temp.name) / 'terminal cua chu'; elsewhere.mkdir()
        env = {k: v for k, v in os.environ.items() if k not in ('ONECREW_ACTOR', 'CLAUDECODE', 'CLAUDE_CODE_CHILD_SESSION')}
        env['PYTHONPATH'] = str(Path(__file__).resolve().parents[1]) + os.pathsep + env.get('PYTHONPATH', '')
        def run(cmd):
            args = cmd.split(' --project ', 1)[1]
            script = elsewhere / f'lenh {len(os.listdir(elsewhere))}.ps1'
            script.write_text('$ErrorActionPreference = "Continue"\n& "' + sys.executable + '" -X utf8 -m onecrew.console --project ' + args + '\nexit $LASTEXITCODE\n', encoding='utf-8-sig')
            return subprocess.run(['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(script)], capture_output=True, text=True, encoding='utf-8', errors='replace', env=env, cwd=str(elsewhere), timeout=180)
        missing = run(template.split(' --reference ')[0])                     # dev8's command (no --reference): the wheel's parser refuses it before any write
        self.assertEqual(missing.returncode, 2, missing.stdout + missing.stderr); self.assertIn('--reference', missing.stderr + missing.stdout)
        self.assertEqual(self.ledger.request(request['id'])['state'], 'pending')
        filled = run(template.replace(tracking.REFERENCE_PLACEHOLDER, 'chủ chọn 30 ngày sau khi đọc hồ sơ'))
        self.assertEqual(filled.returncode, 0, filled.stdout[-600:] + filled.stderr[-600:])
        self.assertNotEqual(self.ledger.request(request['id'])['state'], 'pending')
        self.assertEqual(first_task(tracking.overview(self.ledger.state_root))['needs_user'], [])


class PowerShellTemplate(EngineFixture):
    """P2-B: the template is a PowerShell line; a path holding $SDK, a quote, a backtick, & and ( reaches the parser unchanged (dev9's double
    quotes let $SDK be interpolated). Run through the REAL powershell.exe, from a script file, with $SDK set to something else."""
    def test_hostile_path_survives_powershell_and_the_answer_is_recorded(self):
        from tests.obs1_ux_fixture import make_root
        hostile = Path(self.temp.name) / "demo$SDK 'q' (a)&b`t"; hostile.mkdir(); (hostile / 'a.txt').write_text('base\n')
        other = Ledger(hostile, self.ledger.state_root)
        make_root(self, 'PS', 'đường dẫn đặc biệt', ledger=other)
        with other.transaction() as conn:
            task = plans.anchor_events(other, conn, 'PS')['task_id']
        request = other.create_request(task, 'ps-q', QUESTION)
        need = next(t for p in tracking.overview(self.ledger.state_root)['projects'] for t in p['tasks'] if t['plan'] == 'PS')['needs_user'][0]
        template = need['options'][1]['reply_command']
        self.assertEqual(need['reply_shell'], 'PowerShell'); self.assertIn("--project 'd:\\", template.lower()); self.assertIn("''q''", template); self.assertIn('$sdk', template.lower())      # the project path is normcased; PowerShell variables are case-insensitive
        self.assertTrue(template.startswith("& '") or template.startswith('onecrew '), template)
        runtime = f'"{sys.executable}" -X utf8 -m onecrew.console'
        line = template.replace(tracking.REFERENCE_PLACEHOLDER, 'chủ chọn sau khi đọc (fixture)')
        # the checkout has no onecrew.exe: run the same arguments through the interpreter's console entry
        args = line.split(' --project ', 1)[1]
        script = Path(self.temp.name) / 'tra loi.ps1'
        script.write_text('$SDK = "CHANGED"\n$ErrorActionPreference = "Stop"\n& "' + sys.executable + '" -X utf8 -m onecrew.console --project ' + args + '\nexit $LASTEXITCODE\n', encoding='utf-8-sig')
        env = {k: v for k, v in os.environ.items() if k not in ('ONECREW_ACTOR', 'CLAUDECODE', 'CLAUDE_CODE_CHILD_SESSION')}
        env['PYTHONPATH'] = str(Path(__file__).resolve().parents[1]) + os.pathsep + env.get('PYTHONPATH', '')
        done = subprocess.run(['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(script)], capture_output=True, text=True, encoding='utf-8', errors='replace', env=env, cwd=self.temp.name, timeout=180)
        self.assertEqual(done.returncode, 0, done.stdout[-800:] + done.stderr[-800:])
        self.assertNotIn('CHANGED', done.stdout + done.stderr)
        self.assertNotEqual(other.request(request['id'])['state'], 'pending')
        # dev9's shape (double quotes) is what PowerShell interpolates: the same path arrives changed and the parser refuses
        bad = script.with_name('dev9 shape.ps1')
        bad.write_text('$SDK = "CHANGED"\n& "' + sys.executable + '" -X utf8 -m onecrew.console --project "' + str(hostile) + '" --state-root "' + str(self.ledger.state_root) + '" question list --plan PS\nexit $LASTEXITCODE\n', encoding='utf-8-sig')
        done2 = subprocess.run(['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(bad)], capture_output=True, text=True, encoding='utf-8', errors='replace', env=env, cwd=self.temp.name, timeout=180)
        self.assertNotEqual(done2.returncode, 0); self.assertIn('does not exist', done2.stdout + done2.stderr)       # $SDK was interpolated: the path no longer exists


class GanttSpans(EngineFixture):
    def test_rows_come_from_sourced_timestamps_and_a_running_attempt_has_an_unconfirmed_tail(self):
        import datetime as dt
        self.revise([node('A'), node('I', ['A'], integration=True, write=())])
        d = tracking.detail(self.ledger.state_root, 'P1'); g = d['gantt']
        self.assertEqual(g['rows'], []); self.assertEqual([m['kind'] for m in g['plan_marks']][:2], ['plan.approved', 'plan.revised']); self.assertFalse(g['axis']['extends_to_now'])
        worker = _Blocking(self); thread = threading.Thread(target=self.step, args=(worker,), daemon=True); thread.start(); self.assertTrue(worker.started.wait(10))
        now = dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=30)
        g = tracking.detail(self.ledger.state_root, 'P1', now=now)['gantt']
        row = g['rows'][0]; kinds = [s['kind'] for s in row['segments']]
        self.assertEqual(row['node'], 'A'); self.assertTrue(row['active']); self.assertIn('to_now', kinds); self.assertEqual(row['segments'][-1]['to'], g['axis']['now'])
        self.assertFalse(row['segments'][-1]['confirmed']); self.assertTrue(all(s['confirmed'] for s in row['segments'][:-1]))
        self.assertEqual(row['execution_seconds'], 'unknown'); self.assertTrue(g['axis']['extends_to_now']); self.assertEqual(g['axis']['end'], g['axis']['now'])
        self.assertEqual(row['reserved_at'], d['attempts'][0]['created_at'] if d['attempts'] else row['reserved_at'])
        worker.release.set(); thread.join(20)
        g = tracking.detail(self.ledger.state_root, 'P1')['gantt']; row = g['rows'][0]
        self.assertEqual([s['kind'] for s in row['segments']], ['reserved', 'execution']); self.assertIsInstance(row['execution_seconds'], float)
        self.assertEqual(row['settled_at'], row['segments'][-1]['to']); self.assertFalse(g['axis']['extends_to_now'])
        self.assertIn('đã tạo đầu ra', [m['label'] for m in row['marks']])
        self.assertLessEqual(g['axis']['start'], row['reserved_at']); self.assertGreaterEqual(g['axis']['end'], row['settled_at'])


class ElapsedClock(EngineFixture):
    def test_elapsed_follows_the_clock_given_to_the_model_and_stops_at_the_end(self):         # P2-A, model side with a fake clock
        self.revise([node('A'), node('I', ['A'], integration=True, write=())])
        import datetime as dt
        t0 = dt.datetime.now(dt.timezone.utc)
        a = first_task(tracking.overview(self.ledger.state_root, now=t0))['elapsed']
        b = first_task(tracking.overview(self.ledger.state_root, now=t0 + dt.timedelta(seconds=90)))['elapsed']
        self.assertAlmostEqual(b['seconds'] - a['seconds'], 90.0, delta=0.01); self.assertIsNone(a['until'])
        with self.ledger.transaction(write=True) as conn:
            plans.emit(self.ledger, conn, self.root_view['anchor_task'], 'plan.closed', {'revision': 1, 'reason': 'done'})
        c = first_task(tracking.overview(self.ledger.state_root, now=t0 + dt.timedelta(seconds=200)))['elapsed']
        d = first_task(tracking.overview(self.ledger.state_root, now=t0 + dt.timedelta(seconds=900)))['elapsed']
        self.assertIsNotNone(c['until']); self.assertEqual(c['seconds'], d['seconds'])          # ended: the clock no longer runs


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

    def test_marker_dir_env_keeps_the_state_root_untouched(self):
        outside = Path(self.temp.name) / 'markers'
        with __import__('unittest.mock', fromlist=['patch']).patch.dict(os.environ, {tracking_web.MARKER_DIR_ENV: str(outside)}):
            marker, lock = tracking_web.marker_paths(self.state)
            self.assertTrue(str(marker).startswith(str(outside))); self.assertFalse(str(marker).startswith(str(self.state)))
            srv = _Server(self.state); self.addCleanup(srv.stop)
            tracking_web._write_marker(marker, self.record(srv))
            self.assertTrue(self.open().get('reused'))
            self.assertEqual(tracking_web.status_page(self.state)['marker_file'], str(marker))
            self.assertFalse((self.state / 'tracking').exists())
            srv.stop(); result = tracking_web.stop_page(self.state)
            self.assertTrue(result['marker_removed']); self.assertFalse(marker.exists())

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

    def test_open_from_a_cwd_holding_a_decoy_onecrew_package_still_starts_the_real_server(self):
        decoy = Path(self.temp.name) / 'elsewhere' / 'onecrew'; decoy.mkdir(parents=True)
        (decoy / '__init__.py').write_text('raise RuntimeError("decoy onecrew imported from the cwd")\n')
        before = os.getcwd(); os.chdir(decoy.parent); self.addCleanup(os.chdir, before)
        result = tracking_web.open_page(self.state, browser=False, project=self.root, explicit_state_root=self.state, idle_exit=60, interval=1.0)
        try:
            self.assertTrue(result.get('url'), result)
            self.assertEqual(tracking_web.identity(result['url'])['instance'], result['instance'])
        finally:
            tracking_web.stop_page(self.state)

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


class TimelineClock(unittest.TestCase):
    """P2-C (Codex on dev10): the timeline layer compares instants, never ISO strings; an observation written with +07:00 and a `now` in UTC
    sort by value, the axis reaches the running attempt's now, and two strings of one instant give one geometry."""
    ATT = [{'id': 'ATT-1', 'task': 't', 'generation': 1, 'status': 'running', 'created_at': '2026-11-03T14:59:00+07:00', 'updated_at': '2026-11-03T14:59:30+07:00', 'unit': 'u', 'stage': 's'}]

    def spans(self, observed, now, launched='2026-11-02T23:59:20-08:00'):
        events = [(1, 'node.started', {'node': 'C', 'generation': 1, 'attempt': 'ATT-1'}, '2026-11-03T07:59:10+00:00'),
                  (2, 'attempt.launched', {'id': 'ATT-1', 'generation': 1}, launched),
                  (3, 'executor.observed', {'attempt': 'ATT-1', 'what': 'progress', 'checkpoint': {'status': 'progressing'}, 'observed_at': observed}, '2026-11-03T08:00:30+00:00')]
        return tracking._timeline_spans(events, self.ATT, ['C'], {'C': 'ATT-1'}, [], now)

    def test_mixed_offsets_sort_by_instant_and_the_axis_reaches_now(self):
        g = self.spans('2026-11-03T15:01:00+07:00', '2026-11-03T08:02:00+00:00')
        at = tracking._at
        self.assertEqual(at(g['axis']['end']), at('2026-11-03T08:02:00+00:00')); self.assertTrue(g['axis']['extends_to_now'])
        row = g['rows'][0]; kinds = [s['kind'] for s in row['segments']]
        self.assertEqual(kinds, ['reserved', 'execution', 'to_now'])
        self.assertEqual(at(row['segments'][1]['to']), at('2026-11-03T08:01:00+00:00'))            # the +07:00 observation is the latest confirmed mark
        self.assertEqual(at(row['segments'][2]['from']), at('2026-11-03T08:01:00+00:00')); self.assertEqual(at(row['segments'][2]['to']), at(g['axis']['now']))
        self.assertEqual(at(row['latest_mark_at']), at('2026-11-03T08:01:00+00:00'))
        self.assertEqual(at(g['axis']['start']), at('2026-11-03T07:59:00+00:00'))                   # reserved at 14:59+07 = 07:59Z
        self.assertAlmostEqual(g['axis']['seconds'], 180.0)
        for s in row['segments']: self.assertLessEqual(at(s['from']), at(s['to']))

    def test_two_strings_of_one_instant_give_the_same_geometry_and_a_negative_offset_crossing_midnight(self):
        a = self.spans('2026-11-03T15:01:00+07:00', '2026-11-03T08:02:00+00:00')
        b = self.spans('2026-11-03T08:01:00Z', '2026-11-03T03:02:00-05:00')
        norm = lambda g: [(s['kind'], tracking._at(s['from']), tracking._at(s['to'])) for s in g['rows'][0]['segments']]
        self.assertEqual(norm(a), norm(b)); self.assertEqual(a['axis']['seconds'], b['axis']['seconds'])
        self.assertEqual(tracking._at(a['axis']['end']), tracking._at(b['axis']['end']))
        self.assertEqual(tracking._at(a['rows'][0]['segments'][1]['from']), tracking._at('2026-11-03T07:59:20+00:00'))   # launched 23:59:20-08:00 the day before = 07:59:20Z

    def test_a_late_observation_counts_at_its_observed_time_and_bad_data_is_left_out(self):
        g = self.spans('2026-11-03T15:00:10+07:00', '2026-11-03T08:02:00+00:00')                     # observed 08:00:10Z, received 08:00:30Z: the mark is at 08:00:10
        self.assertEqual(tracking._at(g['rows'][0]['segments'][1]['to']), tracking._at('2026-11-03T08:00:10+00:00'))
        g = self.spans('not a time', '2026-11-03T08:02:00+00:00')                                      # a bad observed_at: the received time is used, nothing invented
        self.assertEqual(tracking._at(g['rows'][0]['segments'][1]['to']), tracking._at('2026-11-03T08:00:30+00:00'))
        g = self.spans('2026-11-03T15:01:00+07:00', '2026-11-03T08:02:00+00:00', launched='garbage')
        self.assertEqual([s['kind'] for s in g['rows'][0]['segments']], ['reserved', 'to_now']); self.assertIsNone(g['rows'][0]['launched_at'])


class EvidenceByGeneration(EngineFixture):
    """P2-B (Codex on dev10): evidence is attributed per generation and attempt; a current attempt without output has none of its own; what it
    inherits (node.resumed resume_artifact / continues_attempt) is listed apart with its origin."""
    def test_generation_on_every_entry_and_inheritance_with_provenance(self):
        self.revise([node('A'), node('I', ['A'], integration=True, write=())])
        worker = _Blocking(self); worker.release.set(); self.step(worker)
        d0 = tracking.detail(self.ledger.state_root, 'P1'); old = d0['nodes']['A']['attempt']; receipt0 = d0['nodes']['A']['receipt']
        partial = self.store.blob(b'artifact-A partial of generation 0')
        with self.ledger.transaction(write=True) as conn:
            view = engine.state(self.ledger, 'P1', conn); engine._event(self.ledger, conn, view, 'A', 'node.resumed', resume_artifact=partial, continues_attempt=old)
        worker = _Blocking(self); thread = threading.Thread(target=self.step, args=(worker,), daemon=True); thread.start(); self.assertTrue(worker.started.wait(10))
        d = tracking.detail(self.ledger.state_root, 'P1'); rows = d['gantt']['rows']
        self.assertTrue(all(isinstance(x['generation'], int) for x in d['evidence_index'] if x['node']), d['evidence_index'])   # task-level evidence (task.submitted) has no generation
        cur = next(r for r in rows if r['current']); prev = next(r for r in rows if r['attempt'] == old)
        self.assertEqual((cur['generation'], prev['generation']), (1, 0)); self.assertTrue(cur['active'])
        own = [x for x in d['evidence_index'] if (x['attempt'] == cur['attempt'] if x['attempt'] else (x['node'] == 'A' and x['generation'] == 1))]
        self.assertEqual([x for x in own if x['kind'] == 'node.produced'], [])                       # the running attempt has produced nothing
        old_out = [x for x in d['evidence_index'] if x['key'] == receipt0]
        self.assertEqual((old_out[0]['generation'], old_out[0]['node']), (0, 'A'))
        self.assertEqual(len(cur['inherits']), 1); inh = cur['inherits'][0]
        self.assertEqual((inh['kind'], inh['key'], inh['from_attempt'], inh['from_generation'], inh['source']), ('resume_artifact', partial, old, 0, 'nodes[A].resume_artifact'))
        self.assertEqual(prev['inherits'], []); self.assertIn(partial, d['evidence_keys'])
        worker.release.set(); thread.join(20)
        d = tracking.detail(self.ledger.state_root, 'P1'); cur = next(r for r in d['gantt']['rows'] if r['current'])
        receipt1 = d['nodes']['A']['receipt']; own = [x for x in d['evidence_index'] if x['key'] == receipt1]
        self.assertEqual(receipt1, receipt0)                                                        # content-addressed: the same bytes, the same key in both generations
        self.assertEqual(sorted((x['node'], x['generation']) for x in own), [('A', 0), ('A', 1)]); self.assertEqual(cur['inherits'][0]['key'], partial)
