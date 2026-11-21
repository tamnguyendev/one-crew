"""VER60 MC, through the tracking CLI and HTTP routes on disposable ledgers."""
import contextlib
import io
import json
import sqlite3
import subprocess
import threading
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from onecrew.ledger import Ledger
from onecrew.v2 import plan, tracking, tracking_web, verdict
from onecrew.v2.cli import main
from tests.v2_fixture import Fixture, plan_json


def mtimes(root):
    return {p.relative_to(root): p.stat().st_mtime_ns for p in [root, *root.rglob('*')]}


class CopyView(Fixture):
    def setUp(self):
        super().setUp()
        base = Path(self.temp.name)
        self.clone = base / 'separate-clone'
        subprocess.run(['git', 'clone', '--quiet', '--no-local', str(self.root), str(self.clone)], check=True)
        self.scratch = base / 'scratch'
        self.scratch.mkdir()
        self.approved()

    def args(self, *, clone=None, scratch=None):
        return ['--project', str(self.root), '--state-root', str(self.ledger.state_root), 'track', 'copy-view',
                '--clone', str(clone or self.clone), '--scratch', str(scratch or self.scratch), '--no-browser']

    def view(self, read):
        def serve(root, *, project_id, port, browser, comparison, idle_exit):
            self.assertNotEqual(root, self.ledger.state_root)
            self.assertEqual(root.parent, self.scratch)
            self.assertTrue((root / 'ledger.sqlite3').is_file())
            self.assertFalse(browser)
            with tracking_web.make_server(root, project_id=project_id, port=port, comparison=comparison) as server:
                thread = threading.Thread(target=server.serve_forever)
                thread.start()
                try:
                    read(tracking_web.url_of(server), root)
                finally:
                    server.shutdown()
                    thread.join()
            return 0

        with patch.object(tracking_web, 'serve', side_effect=serve) as started:
            self.assertEqual(main(self.args()), 0)
            started.assert_called_once()
        self.assertEqual(list(self.scratch.iterdir()), [])

    def get(self, base, route, *, html=False):
        with urlopen(base + route, timeout=5) as reply:
            return reply.read().decode('utf-8') if html else json.load(reply)

    def test_copy_points_projects_to_clones(self):
        # The other project's rows stay available to resolve legacy revision ownership,
        # but the preview's HTTP scope may only disclose the selected project's records.
        other = Ledger(self.clone, self.ledger.state_root)
        plan.propose(other, 'OTHER', plan_json(), 'claude')

        def read(base, root):
            task = self.get(base, 'api/task?plan=P1')
            self.assertEqual(Path(task['project']), self.clone)
            self.assertEqual(task['goal'], 'Do the sample and prove it.')
            view = self.get(base, 'api/overview?list=1')
            self.assertEqual([Path(p['path']) for p in view['projects']], [self.clone])
            with self.assertRaises(HTTPError) as error:
                self.get(base, 'api/task?plan=OTHER&project_id=' + other.project_id)
            self.assertEqual(error.exception.code, 403)

        self.view(read)
        with self.ledger.transaction() as conn:
            row = conn.execute('SELECT project_path FROM tasks WHERE project_id=?', (self.ledger.project_id,)).fetchone()
        self.assertEqual(Path(row['project_path']), self.root)

    def test_no_server_on_real_state_root(self):
        marker = self.ledger.state_root / 'tracking' / 'server.json'
        marker.parent.mkdir()
        marker.write_text('existing marker')

        def read(base, root):
            health = self.get(base, 'api/health')
            self.assertEqual(Path(health['state_root']), root)
            self.assertNotEqual(health['state_root_id'], tracking_web.root_id(self.ledger.state_root))
            self.assertTrue(health['read_only'])
            with self.assertRaises(HTTPError) as error:
                urlopen(Request(base + 'api/task?plan=P1', data=b'{}'), timeout=5)
            self.assertEqual(error.exception.code, 405)

        self.view(read)
        self.assertEqual(marker.read_text(), 'existing marker')

    def test_git_mtimes_unchanged(self):
        git_dirs = [self.root / '.git', self.clone / '.git']
        before = [mtimes(path) for path in git_dirs]
        self.view(lambda base, root: self.get(base, 'api/task?plan=P1'))
        self.assertEqual([mtimes(path) for path in git_dirs], before)

    def test_state_mtimes_unchanged(self):
        state = self.ledger.state_root
        before = mtimes(state)
        self.view(lambda base, root: self.get(base, 'api/overview?list=1'))
        self.assertEqual(mtimes(state), before)

    def test_compare_off_mode_said(self):
        receipt, evidence = self.receipt()
        self.issue(receipt)
        verdict.record(self.ledger, 'P1', 'M1', 'pass', 'command', receipt, evidence['artifact_sha'])

        def read(base, root):
            self.assertEqual(self.get(base, 'api/health')['comparison'], 'off')
            for route in ('', 'overview', 'direction?plan=P1', 'sessions?plan=P1'):
                self.assertIn(tracking_web.COPY_NOTE, self.get(base, route, html=True))
            task = self.get(base, 'api/task?plan=P1')
            self.assertEqual(task['validity']['kind'], 'not_compared')
            self.assertFalse(task['validity']['compared'])
            self.assertIn(receipt, task['evidence_keys'])
            self.assertEqual(self.get(base, 'api/evidence?plan=P1&key=' + receipt)['key'], receipt)

        with (patch.object(tracking, '_live_views', side_effect=AssertionError('compared a project')),
              patch.object(tracking, '_runtime_binding', side_effect=AssertionError('read live hook binding'))):
            self.view(read)

    def test_refuses_source_paths_as_clone_or_scratch(self):
        before = mtimes(self.ledger.state_root)
        with contextlib.redirect_stdout(io.StringIO()), patch.object(tracking_web, 'serve') as serve:
            self.assertEqual(main(self.args(clone=self.root)), 2)
            self.assertEqual(main(self.args(scratch=self.ledger.state_root)), 2)
            serve.assert_not_called()
        self.assertEqual(mtimes(self.ledger.state_root), before)

    def test_refuses_wal_without_creating_sidecars(self):
        state = self.ledger.state_root
        with contextlib.closing(sqlite3.connect(state / 'ledger.sqlite3')) as conn:
            self.assertEqual(conn.execute('PRAGMA journal_mode=WAL').fetchone()[0], 'wal')
        before = mtimes(state)
        with contextlib.redirect_stdout(io.StringIO()), patch.object(tracking_web, 'serve') as serve:
            self.assertEqual(main(self.args()), 2)
            serve.assert_not_called()
        self.assertEqual(mtimes(state), before)
        self.assertEqual(list(self.scratch.iterdir()), [])
