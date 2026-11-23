"""The tracking viewer when the browser goes away mid-answer (owner, 23/11: "sua luon loi terminal truoc roi nghiem thu").

Seen on the owner's terminal with the trial package: a browser that closed a tab or aborted a fetch while the viewer was writing made
_send raise ConnectionAbortedError (WinError 10053); the request's `except OSError` took it for a source error, counted it in
stats['errors'] and tried to send a 503 on the closed connection, which raised again and printed a traceback on the console.

Reproduced here without timing: the handler's socket writer refuses every write the way a closed connection does."""
import contextlib
import io
import json
import re
import socket
import struct
import tempfile
import time
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

from onecrew.v2 import tracking_web


class _Gone:
    """A socket writer whose peer has closed: every write raises, like WinError 10053 on Windows."""
    def __init__(self, error):
        self.error, self.writes, self.closed = error, 0, False

    def write(self, data):
        self.writes += 1
        raise self.error

    def flush(self):
        pass

    def close(self):
        self.closed = True


class ClientGoneTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='tw-gone-')
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name) / 'state'; root.mkdir()
        self.server = tracking_web.make_server(root, interval=1.0)
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={'poll_interval': 0.1}, daemon=True)
        self.thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        host, port = self.server.server_address[:2]
        self.address = (host, port)

    def _ask_with_writer(self, error, path='/api/health'):
        writers = []
        original = self.server.RequestHandlerClass.setup

        def setup(handler):
            original(handler)
            handler.wfile = _Gone(error)
            writers.append(handler.wfile)

        console = io.StringIO()
        with mock.patch.object(self.server.RequestHandlerClass, 'setup', setup), contextlib.redirect_stderr(console):
            with socket.create_connection(self.address, timeout=10) as client:
                client.sendall(f'GET {path} HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n'.encode('ascii'))
                try:
                    while client.recv(4096):        # the server closes once the request is handled (after any error report)
                        pass
                except (ConnectionResetError, ConnectionAbortedError):
                    pass
        return writers, console.getvalue()

    def test_a_browser_that_goes_away_mid_answer_is_not_a_source_error(self):
        for error in (ConnectionAbortedError(10053, 'aborted'), ConnectionResetError(10054, 'reset'), BrokenPipeError(32, 'broken pipe')):
            with self.subTest(error=type(error).__name__):
                before = self.server.track_stats['errors']
                writers, console = self._ask_with_writer(error)
                self.assertEqual(len(writers), 1, writers)
                self.assertEqual(writers[0].writes, 1, 'one answer attempted, no second (503) answer on the closed connection')
                self.assertEqual(self.server.track_stats['errors'], before, 'a browser that left is not counted as a source error')
                self.assertNotIn('Traceback', console, console)

    def test_a_real_source_error_still_answers_503_and_is_counted(self):
        before = self.server.track_stats['errors']
        console = io.StringIO()
        with mock.patch('onecrew.v2.tracking.overview', side_effect=OSError('disk gone')), contextlib.redirect_stderr(console):
            with self.assertRaises(urllib.error.HTTPError) as caught:
                urllib.request.urlopen(f'http://{self.address[0]}:{self.address[1]}/api/overview', timeout=10)
        self.assertEqual(caught.exception.code, 503)
        body = json.loads(caught.exception.read().decode('utf-8'))
        self.assertIn('disk gone', body['error'])
        self.assertEqual(self.server.track_stats['errors'], before + 1)
        self.assertNotIn('Traceback', console.getvalue())


class ClientGoneWhileReadingTests(unittest.TestCase):
    """Owner 23/11 ("sua not"): the console also printed a traceback when the browser dropped a connection while the viewer was READING a
    request or waiting on an idle keep-alive connection for the next one (socketserver.handle_error). Reproduced with a real socket closed
    with a reset (SO_LINGER 0), which is what a closed tab does; the test waits for the server to finish that connection (shutdown_request)."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='tw-read-')
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name) / 'state'; root.mkdir()
        self.server = tracking_web.make_server(root, interval=1.0)
        self.done = threading.Event()
        original = self.server.shutdown_request

        def shutdown_request(request):                 # called after handle_error, for every connection the server handled
            try:
                original(request)
            finally:
                self.done.set()
        self.server.shutdown_request = shutdown_request
        threading.Thread(target=self.server.serve_forever, kwargs={'poll_interval': 0.1}, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.address = self.server.server_address[:2]

    @staticmethod
    def _reset(client):
        client.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack('ii', 1, 0))
        client.close()

    def _console_of(self, act):
        console = io.StringIO()
        self.done.clear()
        with contextlib.redirect_stderr(console):
            act()
            self.assertTrue(self.done.wait(10), 'the server finished the connection')
            time.sleep(0.2)                            # anything handle_error prints is written before shutdown_request; a margin all the same
        return console.getvalue()

    def test_a_browser_that_leaves_while_the_request_is_being_read_prints_nothing(self):
        before = self.server.track_stats['errors']

        def act():
            client = socket.create_connection(self.address, timeout=10)
            client.sendall(b'GET /api/health HTTP/1.1\r\nHost: 127.0.0.1\r\n')     # half a request: the server is reading the headers
            time.sleep(0.3)
            self._reset(client)
        console = self._console_of(act)
        self.assertNotIn('Traceback', console, console)
        self.assertEqual(self.server.track_stats['errors'], before)

    def test_a_browser_that_drops_an_idle_keep_alive_connection_prints_nothing(self):
        before = self.server.track_stats['errors']

        def act():
            client = socket.create_connection(self.address, timeout=10)
            client.sendall(b'GET /api/health HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n')
            data = b''
            while b'\r\n\r\n' not in data or len(data.split(b'\r\n\r\n', 1)[1]) < int(re.search(rb'Content-Length: (\d+)', data).group(1)):
                data += client.recv(65536)
            self.assertIn(b' 200 ', data.split(b'\r\n', 1)[0])
            time.sleep(0.3)                            # the server now waits on this keep-alive connection for the next request
            self._reset(client)
        console = self._console_of(act)
        self.assertNotIn('Traceback', console, console)
        self.assertEqual(self.server.track_stats['errors'], before)

    def test_any_other_error_is_still_printed(self):
        def act():
            with mock.patch('onecrew.v2.tracking.overview', side_effect=RuntimeError('control: a real bug')):
                client = socket.create_connection(self.address, timeout=10)
                client.sendall(b'GET /api/overview HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n')
                try:
                    while client.recv(65536):
                        pass
                except OSError:
                    pass
                client.close()
                self.assertTrue(self.done.wait(10))
        console = self._console_of(act)
        self.assertIn('Traceback', console)
        self.assertIn('RuntimeError: control: a real bug', console)


if __name__ == '__main__':
    unittest.main()
