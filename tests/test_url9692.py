"""URL9692 (25/11/2026): a fixed address for the OneCrew tracking page.

Rev 3 (owner 21:56, option 1): a ledger with <state root>/tracking.json ({"port": N}) opens `track open` and `track serve` on N; a ledger
without that file keeps a free port of the system as before (191a58f); `--port` still wins and `--port 0` still takes a free port. A fixed
port that is taken is reused only when this ledger's own tracking server answers there; anything else is reported with the port and nothing
else is started. A server that `track open` starts on a fixed port does not exit when idle; on port 0 it keeps the 1800-second idle exit.
The host stays 127.0.0.1.

No test opens a browser and none uses 9692 (the M1 checker holds it while the tests run): every fixed port here is a free port of the
system chosen by the test and written to tracking.json, and a case that needs a real listener closes it in tearDown. A started server is
replaced by a fake child process (no detached process is left behind).
"""
import contextlib
import io
import json
import os
import socket
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from onecrew.v2 import tracking_cli, tracking_web


def free_port():
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        return probe.getsockname()[1]


class _FakeChild:
    """Stands in for the detached server `track open` starts: it has 'exited' at once, so open_page gives up without a real process."""
    pid = 0
    returncode = 1

    def poll(self):
        return 1

    def wait(self, timeout=None):
        return 1

    def kill(self):
        pass


class TestUrl9692(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name)
        self.state = self.base / 'state'
        self.state.mkdir()
        self.project = self.base / 'project'
        self.project.mkdir()
        env = mock.patch.dict(os.environ, {tracking_web.MARKER_DIR_ENV: str(self.base / 'markers')})
        env.start()
        self.addCleanup(env.stop)
        self.spawned = []

    # ---- helpers -----------------------------------------------------------------------------------------------------------------------
    def cli(self, *args, state=None):
        out = io.StringIO()
        with mock.patch.object(tracking_cli, '_state_root', return_value=((state or self.state).resolve(), None)), contextlib.redirect_stdout(out):
            code = tracking_cli.main(['--project', str(self.project), '--state-root', str(state or self.state), 'track', *args])
        return code, out.getvalue()

    def called_with(self, verb, *args):
        """The keyword arguments the CLI hands to tracking_web.serve / open_page (both replaced: nothing listens, nothing starts)."""
        with mock.patch.object(tracking_web, 'serve', return_value=0) as serve, \
                mock.patch.object(tracking_web, 'open_page', return_value={'url': 'http://127.0.0.1:1/'}) as open_page:
            code, out = self.cli(verb, *(('--no-browser',) if verb == 'open' else ()), *args)
        self.assertEqual(code, 0, out)
        return (serve if verb == 'serve' else open_page).call_args.kwargs

    def fake_popen(self, args, **kw):
        self.spawned.append({'args': list(args), 'env': dict(kw.get('env') or {})})
        return _FakeChild()

    def open_spawning_nothing(self, **kw):
        """open_page with the detached start replaced by a fake child that exits at once; returns its result (self.spawned records the start)."""
        with mock.patch.object(tracking_web.subprocess, 'Popen', side_effect=self.fake_popen), \
                mock.patch.object(tracking_web, '_abandon', return_value={'ended': [], 'still_running': [], 'marker_removed': False}):
            return tracking_web.open_page(self.state, browser=False, project=self.project, explicit_state_root=self.state, wait=2, **kw)

    def cli_spawning_nothing(self, *args, state=None):
        with mock.patch.object(tracking_web.subprocess, 'Popen', side_effect=self.fake_popen), \
                mock.patch.object(tracking_web, '_abandon', return_value={'ended': [], 'still_running': [], 'marker_removed': False}):
            return self.cli(*args, state=state)

    def listener(self):
        """A plain socket that holds a free port of the system and never answers HTTP: 'another program'. Closed in tearDown."""
        holder = socket.socket()
        holder.bind(('127.0.0.1', 0))
        holder.listen()
        self.addCleanup(holder.close)
        return holder.getsockname()[1]

    def live_server(self, state, port=0, project_id=None, marker=True):
        """A real tracking server of `state` in this process (no idle exit), shut down in tearDown; with `marker`, announced as `serve` does."""
        server = tracking_web.make_server(state, port=port, project_id=project_id)
        thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': 0.1}, daemon=True)
        thread.start()

        def stop():
            server.shutdown(); server.server_close(); thread.join(5)
        self.addCleanup(stop)
        record = {'url': tracking_web.url_of(server), 'pid': os.getpid(), 'instance': server.track_identity['instance'],
                  'version': server.track_identity['version'], 'state_root': str(Path(state).resolve()), 'state_root_id': server.track_identity['state_root_id'],
                  'project_id': project_id, 'poll_seconds': 2.0, 'read_only': True, 'started_at': server.track_stats['started_at']}
        if marker:
            tracking_web._write_marker(tracking_web.marker_paths(state)[0], record)
        return server, record

    def set_port(self, port, state=None):
        ((state or self.state) / 'tracking.json').write_text(json.dumps({'port': port}), encoding='utf-8')

    # ---- A: new behaviour -----------------------------------------------------------------------------------------------------------------
    def test_state_root_tracking_json_sets_port(self):
        port, other = free_port(), free_port()
        self.set_port(port)
        self.assertEqual(self.called_with('serve')['port'], port)
        self.assertEqual(self.called_with('open')['port'], port)
        self.assertEqual(self.called_with('open', '--port', str(other))['port'], other, '--port still wins over tracking.json')
        self.assertEqual(self.called_with('serve', '--port', '0')['port'], 0)

    def test_busy_port_of_another_program_stops_with_message(self):
        port = self.listener()
        code, out = self.cli_spawning_nothing('open', '--no-browser', '--port', str(port))
        self.assertEqual(self.spawned, [], 'no server is started when the fixed port is taken')
        self.assertNotEqual(code, 0, out)
        self.assertIn(f'cổng {port} đang bị chương trình khác giữ', json.loads(out)['error'])
        self.set_port(port)                                      # the same through the ledger's own port, and for `serve`
        code, out = self.cli_spawning_nothing('open', '--no-browser')
        self.assertEqual((code != 0, self.spawned), (True, []), out)
        self.assertIn(f'cổng {port} đang bị chương trình khác giữ', json.loads(out)['error'])
        code, out = self.cli('serve')
        self.assertNotEqual(code, 0, out)
        self.assertIn(f'cổng {port} đang bị chương trình khác giữ', json.loads(out)['error'])

    def test_fixed_port_open_starts_server_without_idle_exit(self):
        port = free_port()
        self.set_port(port)
        self.cli_spawning_nothing('open', '--no-browser')
        self.assertEqual(len(self.spawned), 1, 'track open starts one server')
        args, env = self.spawned[0]['args'], self.spawned[0]['env']
        self.assertEqual(args[args.index('--port') + 1], str(port))
        self.assertEqual(env.get('ONECREW_TRACK_IDLE_EXIT') or None, None, 'a server on a fixed port does not exit when idle')
        self.spawned.clear()
        self.open_spawning_nothing(port=port)
        self.assertEqual(self.spawned[0]['env'].get('ONECREW_TRACK_IDLE_EXIT') or None, None)

    # ---- B: must pass on the candidate ------------------------------------------------------------------------------------------------------
    def test_reopen_same_state_root_gives_same_url(self):
        port = free_port()
        server, record = self.live_server(self.state, port=port)
        self.set_port(port)
        urls = []
        for _ in range(2):
            code, out = self.cli_spawning_nothing('open', '--no-browser')
            self.assertEqual(code, 0, out)
            value = json.loads(out)
            self.assertTrue(value['reused'], value)
            self.assertEqual(value['instance'], record['instance'])
            urls.append(value['url'])
        self.assertEqual(urls, [f'http://127.0.0.1:{port}/'] * 2)
        self.assertEqual(self.spawned, [])

    # ---- C: controls (same on the base) -------------------------------------------------------------------------------------------------------
    def test_explicit_port_zero_still_picks_a_free_port(self):
        self.assertEqual(self.called_with('serve', '--port', '0')['port'], 0)
        self.assertEqual(self.called_with('open', '--port', '0')['port'], 0)
        server = tracking_web.make_server(self.state, port=0)
        try:
            self.assertNotEqual(server.server_address[1], 0)
        finally:
            server.server_close()
        self.open_spawning_nothing(port=0)
        args, env = self.spawned[0]['args'], self.spawned[0]['env']
        self.assertEqual(args[args.index('--port') + 1], '0')
        self.assertEqual(env.get('ONECREW_TRACK_IDLE_EXIT'), '1800', 'port 0 keeps the 1800-second idle exit')

    def test_no_tracking_json_keeps_free_port(self):
        self.assertFalse((self.state / 'tracking.json').exists())
        self.assertEqual(self.called_with('serve')['port'], 0)
        self.assertEqual(self.called_with('open')['port'], 0)
        code, out = self.cli_spawning_nothing('open', '--no-browser')     # the started server: a free port and the 1800-second idle exit, as before
        self.assertEqual(len(self.spawned), 1, out)
        args, env = self.spawned[0]['args'], self.spawned[0]['env']
        self.assertEqual(args[args.index('--port') + 1], '0')
        self.assertEqual(env.get('ONECREW_TRACK_IDLE_EXIT'), '1800')
        self.assertFalse((self.state / 'tracking.json').exists(), 'nothing writes the file')

    def test_host_default_stays_localhost(self):
        self.assertEqual(self.called_with('serve')['host'], '127.0.0.1')
        self.assertEqual(self.called_with('open')['host'], '127.0.0.1')
        self.open_spawning_nothing(port=0)
        args = self.spawned[0]['args']
        self.assertEqual(args[args.index('--host') + 1], '127.0.0.1')

    # ---- other new cases -------------------------------------------------------------------------------------------------------------------
    def test_busy_port_of_same_ledger_server_without_marker_is_reused(self):
        port = free_port()
        server, record = self.live_server(self.state, port=port, marker=False)
        self.set_port(port)
        code, out = self.cli_spawning_nothing('open', '--no-browser')
        self.assertEqual(code, 0, out)
        value = json.loads(out)
        self.assertEqual((value['url'], value['instance'], value['reused']), (f'http://127.0.0.1:{port}/', record['instance'], True))
        self.assertEqual(self.spawned, [])
        self.assertTrue(tracking_web.status_page(self.state)['reusable'], 'the marker now names that server')
        code, out = self.cli('serve')
        self.assertEqual(code, 0, out)
        self.assertEqual((json.loads(out)['url'], json.loads(out)['reused']), (f'http://127.0.0.1:{port}/', True))

    def test_busy_port_of_another_ledger_server_stops_with_message(self):
        other = self.base / 'other-state'
        other.mkdir()
        port = free_port()
        self.live_server(other, port=port)
        code, out = self.cli_spawning_nothing('open', '--no-browser', '--port', str(port))
        self.assertEqual((code != 0, self.spawned), (True, []), out)
        self.assertIn(f'cổng {port} đang do server theo dõi OneCrew của sổ khác giữ', json.loads(out)['error'])

    def test_bad_tracking_json_is_reported(self):
        for text in ('{"port": "x"}', '{"port": 0}', '{"port": true}', 'not json', '[9693]'):
            (self.state / 'tracking.json').write_text(text, encoding='utf-8')
            code, out = self.cli_spawning_nothing('open', '--no-browser')
            self.assertEqual(code, 2, out)
            self.assertIn('tracking.json', json.loads(out)['error'])
        self.assertEqual(self.spawned, [])

    def test_no_tracking_json_is_written(self):
        self.called_with('open'); self.called_with('serve')
        self.assertFalse((self.state / 'tracking.json').exists())


if __name__ == '__main__':
    unittest.main()
