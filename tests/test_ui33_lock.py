"""UI3 (P1 of 19/11): an open task page must not lock the owner out of the ledger.

The ledger is SQLite in rollback-journal mode. A tracking read that keeps its read transaction (a SHARED lock) while it hashes the project, or that
opens a second ledger connection while it holds the first, starves or deadlocks every writer (`plan advise`, `plan approve`, `verdict run`): the
writer takes PENDING and waits for the SHARED lock, the second reader waits behind PENDING, and the writer gives up with "database is locked".
These tests run on a real temporary ledger and project (the smallest contract of tests/test_ui58_status, self-contained so they run against the
installed wheel):
  - a writer gets the ledger within 2 s while a task page is read in a loop;
  - no project observation (artifact identity, scoped tree of inputs) happens while a ledger read transaction is open, and a read never holds two;
  - with a reuse window (the server's), two polls hash once; a new ledger event for the root, or the window's end, makes a new comparison."""
import contextlib
import datetime as dt
import io
import os
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from onecrew.ledger import Ledger
from onecrew.v2 import plan as plans, report, tracking, tracking_list, verdict
from onecrew.v2.verifiers import artifact as identities, command

OK = [sys.executable, '-c', 'print("ok")']


def plan_json(milestones):
    return {'schema_version': 2, 'title': 'Sample', 'size': 'S',
            'understanding': {'restated_goal': 'Do the sample and prove it.', 'target': {'repo': '.', 'ref': 'HEAD', 'paths': ['a.txt']},
                              'assumptions': [], 'confidence': 'high', 'unknowns': []},
            'preconditions': [{'id': 'P1', 'check': 'path_exists', 'args': {'path': 'a.txt'}, 'why': 'the file to work on is there'}],
            'output': ['The sample exists'], 'scope': {'owned': ['a.txt']}, 'non_goals': ['Nothing else'],
            'items': [{'id': 'I1', 'title': 'Do it', 'tier': 'must', 'milestone': 'M1'}],
            'milestones': milestones, 'budget': {'max_calls': 100, 'time': 120}, 'attention': {'questions': 1}, 'profile_version': None}


def milestone(mid='M1', argv=OK, **extra):
    return dict({'id': mid, 'title': 'Milestone ' + mid, 'verifier': {'type': 'command', 'config': {'argv': argv}}, 'covers': ['O1']}, **extra)


class Fixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        self.root = base / 'project'; self.root.mkdir()
        self.git('init', '-q'); self.git('config', 'user.name', 'T'); self.git('config', 'user.email', 't@localhost')
        (self.root / 'a.txt').write_text('one\n'); self.git('add', '.'); self.git('commit', '-q', '-m', 'base')
        self.ledger = Ledger(self.root, base / 'state')
        env = patch.dict(os.environ); env.start(); self.addCleanup(env.stop)
        for name in ('ONECREW_ACTOR', 'ONECREW_V2_REQUIRE_PLAN', 'CLAUDECODE', 'CLAUDE_CODE_CHILD_SESSION'): os.environ.pop(name, None)
        with contextlib.redirect_stderr(io.StringIO()):
            plans.propose(self.ledger, 'P1', plan_json([milestone('M1')]), 'claude', workflow=True)
            os.environ.pop('ONECREW_ACTOR', None)
            plans.approve(self.ledger, 'P1', 'owner', 'test fixture')
        verdict.run(self.ledger, 'P1', 'M1')                       # a passed command milestone: live views, and the acceptance check, compare
        self.path = self.ledger.state_root / 'ledger.sqlite3'
        with self.ledger.transaction() as conn:
            self.task_id = plans.derive(self.ledger, conn, 'P1')['task_id']

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.root), *args], stderr=subprocess.PIPE).decode().strip()

    def free(self):
        """Can a writer take the whole ledger right now (no reader holds a SHARED lock)? BEGIN EXCLUSIVE with no wait, then ROLLBACK."""
        conn = sqlite3.connect(self.path.as_uri() + '?mode=rw', uri=True, timeout=0, isolation_level=None)
        try:
            conn.execute('BEGIN EXCLUSIVE'); conn.execute('ROLLBACK')
            return True
        except sqlite3.OperationalError:
            return False
        finally:
            conn.close()

    def write_event(self, timeout=2.0):
        """A real small ledger write (an event on the root, as any writer makes one), giving up after `timeout` seconds as a busy writer does."""
        conn = sqlite3.connect(self.path.as_uri() + '?mode=rw', uri=True, timeout=timeout, isolation_level=None)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute('BEGIN IMMEDIATE')
            plans.emit(self.ledger, conn, self.task_id, 'test.ping', {'n': 1})
            conn.execute('COMMIT')
        finally:
            conn.close()


class Lock(Fixture):
    def test_detail_poll_does_not_starve_writer(self):
        stop, polls, errors = threading.Event(), [0], []

        def poll():
            while not stop.is_set():
                try: tracking.detail(self.ledger.state_root, 'P1'); polls[0] += 1
                except Exception as error: errors.append(repr(error))      # a read refused under a writer is not what is measured here
        thread = threading.Thread(target=poll, daemon=True); thread.start()
        try:
            deadline = time.monotonic() + 60
            while polls[0] < 1 and not errors and time.monotonic() < deadline: time.sleep(0.05)     # the page is open and has read once
            before = polls[0]
            exclusive, writes, tries = [], [], [0, 0]
            deadline = time.monotonic() + 120
            # keep trying until the page has read at least twice meanwhile (a slow machine reads slowly), at least 10 tries of each kind
            while (tries[0] < 10 or polls[0] - before < 2) and time.monotonic() < deadline:
                conn = sqlite3.connect(self.path.as_uri() + '?mode=rw', uri=True, timeout=2.0, isolation_level=None)
                started = time.monotonic(); tries[0] += 1
                try:
                    conn.execute('BEGIN EXCLUSIVE'); conn.execute('ROLLBACK'); exclusive.append(time.monotonic() - started)
                except sqlite3.OperationalError:
                    pass
                finally:
                    conn.close()
                time.sleep(0.25)
                started = time.monotonic(); tries[1] += 1
                try: self.write_event(timeout=2.0); writes.append(time.monotonic() - started)
                except sqlite3.OperationalError: pass
                time.sleep(0.25)
            during = polls[0] - before
        finally:
            stop.set(); thread.join(60)
        self.assertGreaterEqual(during, 2, errors[:3])                               # the page really polled meanwhile (each read compares the project)
        self.assertGreaterEqual(len(exclusive), 0.8 * tries[0], f'BEGIN EXCLUSIVE within 2 s: {len(exclusive)}/{tries[0]} while {polls[0]} task reads ran')
        self.assertGreaterEqual(len(writes), 0.8 * tries[1], f'event write within 2 s: {len(writes)}/{tries[1]} while {polls[0]} task reads ran')

    def test_no_observation_inside_a_transaction(self):
        """Every project observation finds the ledger free (no read transaction of ours is open), and a read never holds two transactions."""
        seen, open_now, most = [], [0], [0]
        real_identity, real_scoped, real_txn = identities.identity, command.scoped_tree, report._Reader.transaction

        def identity(directory):
            seen.append(('identity', self.free())); return real_identity(directory)

        def scoped(*args, **kwargs):
            seen.append(('scoped_tree', self.free())); return real_scoped(*args, **kwargs)

        @contextlib.contextmanager
        def txn(reader, write=False):
            open_now[0] += 1; most[0] = max(most[0], open_now[0])
            try:
                with real_txn(reader, write) as conn: yield conn
            finally:
                open_now[0] -= 1
        with patch.object(identities, 'identity', identity), patch.object(command, 'scoped_tree', scoped), patch.object(report._Reader, 'transaction', txn):
            d = tracking.detail(self.ledger.state_root, 'P1')
            tracking.overview(self.ledger.state_root)
            tracking_list.page(self.ledger.state_root, {'list': '1'})
        self.assertEqual(d['compared'], 'compared')
        self.assertEqual(d['validity']['kind'], 'valid')
        self.assertTrue(seen, 'the task page compared the project')
        self.assertEqual([s for s in seen if not s[1]], [], 'a project observation ran while a ledger read transaction was open')
        self.assertEqual(most[0], 1, 'a read opened a second ledger connection while it held one')

    def test_comparison_reused_until_new_event(self):
        calls = []
        real_identity = identities.identity

        def identity(directory):
            calls.append(directory); return real_identity(directory)
        t0 = dt.datetime(2026, 11, 19, 10, 0, tzinfo=dt.timezone.utc)
        read = lambda seconds: tracking.detail(self.ledger.state_root, 'P1', now=t0 + dt.timedelta(seconds=seconds), reuse_seconds=20)
        with patch.object(identities, 'identity', identity):
            first = read(0)
            hashed = len(calls)
            self.assertGreater(hashed, 0)
            second = read(5)                                            # a poll within the window, nothing new in the ledger: no new hash
            self.assertEqual(len(calls), hashed)
            self.assertEqual(second['compared_at'], first['compared_at'])      # shown with the time it was made
            self.assertEqual(second['validity'], first['validity'])
            self.write_event()                                          # a new ledger event for the root: compared again
            third = read(8)
            self.assertGreater(len(calls), hashed)
            self.assertEqual(third['compared_at'], (t0 + dt.timedelta(seconds=8)).isoformat())
            hashed = len(calls)
            read(15)
            self.assertEqual(len(calls), hashed)
            fourth = read(30)                                           # the window (20 s from the comparison at 8 s) ended: compared again
            self.assertGreater(len(calls), hashed)
            self.assertEqual(fourth['compared_at'], (t0 + dt.timedelta(seconds=30)).isoformat())
            hashed = len(calls)
            tracking.detail(self.ledger.state_root, 'P1', now=t0 + dt.timedelta(seconds=31))     # no window (CLI, tests): every read compares
            self.assertGreater(len(calls), hashed)
        (self.root / 'a.txt').write_text('changed after the pass\n')
        self.assertEqual(tracking.detail(self.ledger.state_root, 'P1')['validity']['kind'], 'recheck')   # the default read sees the edit at once


if __name__ == '__main__':
    unittest.main()
