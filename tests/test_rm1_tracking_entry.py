"""RM1 ML: the same public command opens a task across local viewer lifetimes."""
import contextlib
import io
import json
import os
from pathlib import Path
import socket
import tempfile
import time
import unittest
from unittest import mock
from urllib.parse import parse_qs, urlsplit
import urllib.request

import onecrew
from onecrew.ledger import Ledger
from onecrew.v2 import tracking_cli, tracking_web


class TrackingEntry(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.project = Path(temp.name) / 'project'
        self.project.mkdir()
        self.root = Path(temp.name) / 'ledger'
        self.project_id = Ledger(self.project, self.root).project_id
        env = mock.patch.dict(os.environ, {
            'PYTHONPATH': str(Path(onecrew.__file__).resolve().parents[1]),
            'ONECREW_TRACK_MARKER_DIR': str(Path(temp.name) / 'markers'),
        })
        env.start()
        self.addCleanup(env.stop)
        self.addCleanup(tracking_web.stop_page, self.root)

    def open(self, *args, code=0):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = tracking_cli.main(['--project', str(self.project), '--state-root', str(self.root),
                                    'track', 'open', '--plan', 'P1', '--no-browser', *args])
        self.assertEqual(rc, code, out.getvalue())
        return json.loads(out.getvalue())

    def test_reopen_after_idle_restores_saved_task(self):
        real = tracking_web.open_page
        with mock.patch.object(tracking_web, 'open_page', side_effect=lambda *a, **kw: real(*a, **kw, idle_exit=0.15)):
            first = self.open()
        marker, _ = tracking_web.marker_paths(self.root)
        deadline = time.monotonic() + 15
        while marker.exists() and time.monotonic() < deadline:
            time.sleep(0.1)
        self.assertFalse(marker.exists())
        second = self.open()
        self.assertNotEqual(first['instance'], second['instance'])
        for result in (first, second):
            self.assertEqual(parse_qs(urlsplit(result['task_url']).query), {'project_id': [self.project_id], 'plan': ['P1']})
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(second['task_url']) as page:
            self.assertEqual(page.status, 200)

    def test_live_matching_viewer_reused(self):
        started = self.open()
        reopened = self.open()
        self.assertTrue(reopened['reused'])
        self.assertEqual((reopened['instance'], reopened['task_url']), (started['instance'], started['task_url']))

    def test_wrong_scope_or_busy_port_never_adopted(self):
        with socket.socket() as unrelated:
            unrelated.bind(('127.0.0.1', 0))
            unrelated.listen()
            self.assertNotIn('task_url', self.open('--port', str(unrelated.getsockname()[1]), code=2))
        first = self.open()
        self.project = self.project.parent / 'other'
        self.project.mkdir()
        refused = self.open('--port', str(urlsplit(first['url']).port), code=2)
        self.assertNotIn('task_url', refused)
        self.assertEqual(tracking_web.identity(first['url'])['instance'], first['instance'])
        self.assertEqual(tracking_web.status_page(self.root)['marker']['instance'], first['instance'])

    def test_explicit_port_and_loopback_preserved(self):
        with socket.socket() as available:
            available.bind(('127.0.0.1', 0))
            port = available.getsockname()[1]
        started = self.open('--port', str(port))
        self.assertEqual(urlsplit(started['url']).port, port)
        refused = self.open('--host', '0.0.0.0', code=2)
        self.assertNotIn('task_url', refused)

    def test_reconnect_never_resumes_worker(self):
        self.open()
        again = self.open()
        self.assertTrue(again['read_only'])
        self.assertFalse((self.root / 'ledger.sqlite3').exists())
