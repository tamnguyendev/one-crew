"""2.4-S1 / SF-02: `support bundle FB` collects a local diagnostic bundle from an allow-list derived from the report's refs only.

Counterexamples (ROADMAP-DESIGN §7, S1/SF-02): a missing, truncated or withheld log is never shown as complete; a version or hash that cannot be
read is `unknown`; a link, a traversal or another project's attempt never enters the bundle; a secret in a log or a credential URL is withheld
line by line while the rest stays; an image is never in the shareable export; an oversize bundle is cut and says so; nothing is uploaded, no
model or other program is run, the environment is not dumped; the export cannot go inside the state root.
"""
import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import unittest
from importlib import metadata
from pathlib import Path
from unittest.mock import patch

from onecrew import task_intake
from onecrew.ledger import Ledger, LedgerError
from tests.test_v24_s1_intake import FailedNodeFixture

BIG = 300 * 1024


def diagnostics():
    from onecrew.v2 import diagnostics as module
    return module


def link_dir(link, target):
    """A directory link the test can make without privileges: a symlink, else (Windows) a junction."""
    try:
        os.symlink(target, link, target_is_directory=True)
    except OSError:
        import _winapi
        _winapi.CreateJunction(str(target), str(link))


class BundleTests(FailedNodeFixture):
    def setUp(self):
        super().setUp()
        self.logs = self.ledger.state_root / 'attempts' / self.attempt
        self.logs.mkdir(parents=True, exist_ok=True)
        lines = [f'progress line {i:06d} ' + 'x' * 40 for i in range(BIG // 55)]
        (self.logs / 'stdout.txt').write_text('\n'.join(lines) + '\nlast line of the run\n', encoding='utf-8')
        self.out = Path(self.temp.name) / 'export'

    def make(self, *extra):
        code, made = self.report('--text', 'Node C failed for a correct file', '--attempt', self.attempt, *extra)
        self.assertEqual(code, 0, made)
        return made['id']

    def bundle(self, fb, out=None):
        args = ['support', 'bundle', fb] + (['--out', str(out)] if out else [])
        code, made = self.cli(*args)
        self.assertEqual(code, 0, made)
        return made

    def sources(self, made):
        return {(s['source'], s.get('ref')): s for s in made['manifest']['sources']}

    def exported(self, made):
        folder = Path(made['export'])
        return {p.relative_to(folder).as_posix(): p.read_bytes() for p in folder.rglob('*') if p.is_file()}

    def test_manifest_marks_missing_truncated_withheld_not_applicable(self):
        image = Path(self.temp.name) / 'screen.png'; image.write_bytes(b'\x89PNG fixture image')
        fb = self.make('--image', str(image))
        made = self.bundle(fb)
        found = self.sources(made)
        stdout = found[('attempt.stdout', self.attempt)]
        self.assertEqual(stdout['status'], 'truncated')
        self.assertGreater(stdout['bytes_total'], diagnostics().FILE_CAP)
        self.assertLessEqual(stdout['bytes_included'], diagnostics().FILE_CAP)
        self.assertEqual(stdout['sha256_original'], hashlib.sha256((self.logs / 'stdout.txt').read_bytes()).hexdigest())
        self.assertEqual(found[('attempt.stderr', self.attempt)]['status'], 'missing')
        self.assertEqual(found[('runner.logs', None)]['status'], 'not_applicable')
        self.assertEqual(found[('host.log', None)]['status'], 'not_applicable')
        self.assertEqual(found[('image', None)]['status'], 'withheld')
        self.assertIn('not a guarantee', made['manifest']['redaction'])
        self.assertTrue(made['manifest']['coverage_note'])
        for entry in made['manifest']['sources']:
            self.assertIn(entry['status'], ('included', 'missing', 'truncated', 'withheld', 'unreadable', 'not_applicable', 'unknown'), entry)
            for field in ('source', 'ref', 'status', 'bytes_total', 'bytes_included', 'sha256_original', 'redaction', 'reason'):
                self.assertIn(field, entry)
        self.assertEqual(len(self.support_events('support.bundle')), 1)
        (self.logs / 'stdout.txt').unlink()
        again = self.sources(self.bundle(fb))
        self.assertEqual(again[('attempt.stdout', self.attempt)]['status'], 'missing')         # a deleted log is missing, not "no error"

    def test_version_hash_unknown_when_not_installed(self):
        fb = self.make()
        def absent(name):
            raise metadata.PackageNotFoundError(name)
        with patch.object(metadata, 'distribution', absent):
            made = self.bundle(fb)
        runtime = next(s for s in made['manifest']['sources'] if s['source'] == 'runtime')
        probe = made['manifest']['runtime']
        self.assertEqual(probe['dist_version'], 'unknown'); self.assertTrue(probe['dist_version_reason'])
        self.assertEqual(probe['record_sha256'], 'unknown')
        self.assertRegex(probe['tree'], r'^[0-9a-f]{64}$')
        self.assertTrue(probe['checkout'])                                   # these tests run the checkout's code
        self.assertEqual(runtime['status'], 'included')

    def test_path_traversal_link_and_out_of_project_refused(self):
        # another project of the same state root: its attempt and its log exist, but they are not this project's
        other = Path(self.temp.name) / 'other'; other.mkdir()
        foreign = Ledger(other, self.ledger.state_root)
        task = task_intake.submit(foreign, 'Other work', 'other-job', mode='audit')['id']
        with foreign.transaction(write=True) as conn:
            conn.execute("INSERT INTO executions VALUES(?,?,?,?,0,0,0)", (task, '{}', 'r1', 'running'))
            conn.execute("INSERT INTO attempts VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                         ('ATT-' + 'f' * 32, task, 'k', '{}', 'h', 1, 'settled', 0, None, None, 'now', 'now'))
        (self.ledger.state_root / 'attempts' / ('ATT-' + 'f' * 32)).mkdir(parents=True)
        (self.ledger.state_root / 'attempts' / ('ATT-' + 'f' * 32) / 'stdout.txt').write_text('FOREIGN-PROJECT-MARKER\n')
        code, made = self.report('--text', 'look at that attempt', '--attempt', 'ATT-' + 'f' * 32)
        self.assertEqual(code, 0, made)
        self.assertNotIn('task', made['refs']); self.assertIn('attempt', made['refs_unresolved'])
        bundle = self.bundle(made['id'], self.out)
        self.assertNotIn(b'FOREIGN-PROJECT-MARKER', b''.join(self.exported(bundle).values()))
        # this project's attempt folder replaced by a link to a folder outside the state root
        outside = Path(self.temp.name) / 'outside'; outside.mkdir()
        (outside / 'stdout.txt').write_text('OUTSIDE-LINK-MARKER\n')
        shutil.rmtree(self.logs)
        link_dir(self.logs, outside)
        fb = self.make()
        linked = self.bundle(fb, Path(self.temp.name) / 'export2')
        entry = self.sources(linked)[('attempt.stdout', self.attempt)]
        self.assertEqual(entry['status'], 'withheld', entry); self.assertIn('link', entry['reason'])
        self.assertNotIn(b'OUTSIDE-LINK-MARKER', b''.join(self.exported(linked).values()))
        # an export folder given through a link or with '..' is refused
        code, refused = self.cli('support', 'bundle', fb, '--out', str(self.out / '..' / 'x'))
        self.assertEqual(code, 2, refused)

    def test_secret_in_log_and_credential_url_withheld_rest_kept(self):
        (self.logs / 'stdout.txt').write_text('line ok one\nAPI_KEY=abcdefghijk1234567\nclone https://bob:hunter22@git.example/x.git\n'
                                              'line ok two\n', encoding='utf-8')
        fb = self.make()
        made = self.bundle(fb, self.out)
        entry = self.sources(made)[('attempt.stdout', self.attempt)]
        self.assertEqual(entry['status'], 'included')
        self.assertGreaterEqual(entry['redaction']['lines_withheld'], 2)
        text = next(v for k, v in self.exported(made).items() if 'stdout' in k).decode('utf-8')
        self.assertIn('line ok one', text); self.assertIn('line ok two', text)
        self.assertIn('API_KEY=[withheld]', text); self.assertIn('clone https://[withheld]@git.example/x.git', text)
        whole = b''.join(self.exported(made).values())
        self.assertNotIn(b'abcdefghijk1234567', whole); self.assertNotIn(b'hunter22', whole)

    def test_image_not_in_shareable_export(self):
        image = Path(self.temp.name) / 'screen.png'; image.write_bytes(b'\x89PNG IMAGE-BYTES-MARKER')
        fb = self.make('--image', str(image))
        made = self.bundle(fb, self.out)
        entry = self.sources(made)[('image', None)]
        self.assertEqual(entry['status'], 'withheld'); self.assertIn('not scanned', entry['reason'])
        self.assertEqual(entry['sha256_original'], hashlib.sha256(image.read_bytes()).hexdigest())
        self.assertNotIn(b'IMAGE-BYTES-MARKER', b''.join(self.exported(made).values()))

    def test_bundle_over_cap_is_truncated_and_says_so(self):
        (self.logs / 'stderr.txt').write_text('error line\n' * (BIG // 11), encoding='utf-8')
        fb = self.make()
        with patch.object(diagnostics(), 'BUNDLE_CAP', 400 * 1024):
            made = self.bundle(fb, self.out)
        self.assertLessEqual(made['total_bytes'], 400 * 1024)
        dropped = [s for s in made['manifest']['sources'] if 'bundle cap' in (s.get('reason') or '')]
        self.assertTrue(dropped, made['manifest']['sources'])
        self.assertTrue(all(s['status'] == 'truncated' for s in dropped))
        self.assertEqual(made['manifest']['caps']['bundle_bytes'], 400 * 1024)
        self.assertLessEqual(sum(len(v) for k, v in self.exported(made).items() if k != 'manifest.json'), 400 * 1024)

    def test_no_upload_no_model_no_env_dump(self):
        (self.root / 'secret_source.py').write_text('SOURCE-FILE-MARKER = 1\n')
        fb = self.make()
        os.environ['S1_FIXTURE_ENV_VALUE'] = 'ENVIRONMENT-VALUE-MARKER'
        def refuse(*args, **kwargs):
            raise AssertionError('the bundle started a program or opened a socket')
        with patch.object(subprocess, 'Popen', refuse), patch.object(subprocess, 'run', refuse), \
                patch.object(socket, 'socket', refuse), patch.object(socket, 'create_connection', refuse):
            made = self.bundle(fb, self.out)
        whole = b''.join(self.exported(made).values())
        self.assertNotIn(b'ENVIRONMENT-VALUE-MARKER', whole)
        self.assertNotIn(b'SOURCE-FILE-MARKER', whole)
        blobs = self.ledger.state_root / 'snapshots' / 'blobs'
        self.assertFalse(any(b'ENVIRONMENT-VALUE-MARKER' in p.read_bytes() for p in blobs.iterdir()))

    def test_export_inside_state_root_refused(self):
        fb = self.make()
        code, refused = self.cli('support', 'bundle', fb, '--out', str(self.ledger.state_root / 'export'))
        self.assertEqual(code, 2, refused); self.assertIn('state root', refused['error'])
        self.assertFalse((self.ledger.state_root / 'export').exists())
        with self.assertRaises(LedgerError):
            diagnostics().bundle(self.ledger, fb, out=self.ledger.state_root / 'snapshots')

    def test_events_and_rows_come_only_from_the_referenced_root(self):
        os.environ.pop('ONECREW_ACTOR', None)
        self.approved('P2')                                             # another root of the same project, not referenced
        fb = self.make()
        made = self.bundle(fb, self.out)
        refs = {s['ref'] for s in made['manifest']['sources'] if s['source'] == 'ledger.events'}
        self.assertIn(self.root_task, refs); self.assertIn(self.child, refs)
        with self.ledger.transaction() as conn:
            p2 = conn.execute("SELECT id FROM tasks WHERE request_key IN ('plan:P2','plan-ns:P2')").fetchone()[0]
        self.assertNotIn(p2, refs)
        events = [s for s in made['manifest']['sources'] if s['source'] == 'ledger.events']
        self.assertTrue(all(s['bytes_included'] > 0 for s in events))


if __name__ == '__main__':
    unittest.main()
