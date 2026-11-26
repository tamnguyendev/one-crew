"""BANXUAT: the active plan exported for the hooks must agree with the ledger.

`onecrew doctor` FAILS (WARN in log mode) when the file still holds the project (approved, stopped_with_report, closed) although the ledger says the plan
was accepted or closed by the owner. Option doctor-va-tu-lanh: `hook check` lets a call through when its export has EXPIRED and the ledger says this very
plan (anchor, plan_sha) is over; anything else blocks as before. A stale export is what a runtime older than dev33 left behind (it did not export on
accept): here the ledger is moved on and the old file is put back. Real temporary ledgers and Git (tests.v2_fixture); the hook runs as a real subprocess
(tests.test_v2_l2.HookFixture). Only what the base has is imported, so a new behaviour is red BY ASSERTION there.
"""
import contextlib
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))          # test_v2_l2 imports test_v2_l1 by its plain name
from test_v2_l2 import HookFixture, owned_plan                      # noqa: E402

from onecrew.ledger import Ledger                                   # noqa: E402
from onecrew.v2 import active_plan, cli, hook_cli, install, plan as plans, verdict   # noqa: E402
from tests.v2_fixture import BAD, milestone, plan_json               # noqa: E402

PAST = '2020-01-01T00:00:00+00:00'
REPO = Path(__file__).resolve().parents[1]


class TestBanXuat(HookFixture):
    # ---- helpers -----------------------------------------------------------------------------------------------------------------

    def files(self):
        return active_plan.project_file(self.root), hook_cli.state_copy(self.ledger.state_root, self.root)

    def snapshot(self):
        return [(path, path.read_bytes()) for path in self.files()]

    def documents(self):
        return [json.loads(path.read_text(encoding='utf-8')) for path in self.files()]

    def rewrite(self, paths=None, **changes):
        for path in paths or self.files():
            body = json.loads(path.read_text(encoding='utf-8'))
            path.write_text(json.dumps(dict(body, **changes)), encoding='utf-8')

    def accept(self, name='P1'):
        """The accepted event of the owner, written as an older runtime did: no export follows."""
        with self.ledger.transaction(write=True) as conn:
            state = plans.derive(self.ledger, conn, name)
            plans.emit(self.ledger, conn, state['task_id'], 'plan.accepted',
                       {'plan': name, 'revision': state['approved']['revision'], 'sha': state['approved']['sha'], 'by': 'owner', 'reference': 'fixture',
                        'artifact_sha': self.tree()})

    def stale(self, mode='enforce', end='accepted', expires=PAST, name='P1'):
        """A file that says approved while the ledger says the plan is over."""
        self.enforce(name, mode=mode)
        old = self.snapshot()
        if end == 'accepted': self.accept(name)
        else: plans.close(self.ledger, name, 'owner', 'fixture close')
        for path, data in old: path.write_bytes(data)
        self.rewrite(expires=expires)

    def doctor(self):
        with patch.dict(os.environ, {'ONECREW_LANG': 'vi'}):
            return next((level, detail) for level, name, detail in install.doctor_facts(self.root, self.ledger.state_root, claude=None)
                        if name == install.t('doctor.plan'))

    def hook(self, rel='docs/x.md', command=None):
        return self.run_hook('check', self.shell(command) if command else self.edit(rel))[0]

    def export(self, name='P1'):
        output = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            code = cli.main(['--project', str(self.root), '--state-root', str(self.ledger.state_root), 'hook', 'export', name])
        self.assertEqual(code, 0, output.getvalue())

    def passed_plan(self, mode='enforce'):
        """An approved plan whose only milestone has a passing verdict, ready to accept."""
        self.enforce(mode=mode)
        view = verdict.run(self.ledger, 'P1', 'M1')
        self.assertEqual(view['milestones'][0]['state'], 'passed')
        return view['milestones'][0]['last_verdict']['artifact_sha']

    def ledger_bytes(self):
        return hashlib.sha256((Path(self.ledger.state_root) / 'ledger.sqlite3').read_bytes()).hexdigest()

    # ---- I2: doctor reads the exported file against the ledger -----------------------------------------------------------------------

    def test_doctor_fails_when_export_holds_but_ledger_accepted(self):
        self.stale()
        level, text = self.doctor()
        self.assertEqual(level, 'FAIL', text)
        for term in ('approved', '2020-01-01', 'đã nghiệm thu', 'hook export P1'): self.assertIn(term, text)

    def test_doctor_warns_in_log_mode_when_export_is_stale(self):
        self.stale(mode='log')
        level, text = self.doctor()
        self.assertEqual(level, 'WARN', text)
        self.assertIn('hook export P1', text)

    def test_doctor_fails_when_export_holds_but_ledger_closed_by_owner(self):
        self.stale(end='closed')
        level, text = self.doctor()
        self.assertEqual(level, 'FAIL', text)
        for term in ('chủ đã đóng', 'hook export P1'): self.assertIn(term, text)

    def test_doctor_flags_copies_that_disagree_on_status(self):
        self.stale(expires='2999-01-01T00:00:00+00:00')
        self.rewrite([self.files()[0]], status='accepted')                # the project copy only: the hook follows the state-root copy
        level, text = self.doctor()
        self.assertEqual(level, 'FAIL', text)
        for term in ('Hai bản xuất khác nhau', 'accepted', 'approved', 'hook export P1'): self.assertIn(term, text)

    def test_doctor_stale_export_after_fix_passes(self):
        self.stale()
        self.assertEqual(self.doctor()[0], 'FAIL')
        self.export()
        level, text = self.doctor()
        self.assertEqual(level, 'PASS', text)
        self.assertEqual(self.hook(), 0)

    # ---- I1 and controls: what must not change ---------------------------------------------------------------------------------------

    def test_accept_exports_accepted_in_both_places(self):
        artifact = self.passed_plan()
        plans.accept(self.ledger, 'P1', 'owner', 'fixture acceptance', artifact)
        self.assertEqual([d['status'] for d in self.documents()], ['accepted', 'accepted'])
        self.rewrite(expires=PAST)
        self.assertEqual(self.hook(), 0)

    def test_repeat_accept_refreshes_a_stale_export(self):
        artifact = self.passed_plan()
        old = self.snapshot()
        plans.accept(self.ledger, 'P1', 'owner', 'fixture acceptance', artifact)
        for path, data in old: path.write_bytes(data)
        plans.accept(self.ledger, 'P1', 'owner', 'again', artifact)
        self.assertEqual([d['status'] for d in self.documents()], ['accepted', 'accepted'])

    def test_doctor_passes_when_export_says_accepted(self):
        artifact = self.passed_plan()
        plans.accept(self.ledger, 'P1', 'owner', 'fixture acceptance', artifact)
        level, text = self.doctor()
        self.assertEqual(level, 'PASS', text)
        self.assertIn('đã nghiệm thu', text)

    def test_open_plan_expired_still_blocks_and_doctor_fails(self):
        self.enforce()
        self.rewrite(expires=PAST)
        self.assertEqual(self.hook('a.txt'), 2)
        level, text = self.doctor()
        self.assertEqual(level, 'FAIL', text)
        self.assertIn('hết hạn', text)

    def test_stopped_plan_export_matches_ledger(self):
        self.approved('P1', owned_plan(milestones=[milestone(argv=BAD, max_repairs=0)]))
        active_plan.set_mode(self.ledger, 'enforce')
        active_plan.export(self.ledger, 'P1')
        verdict.run(self.ledger, 'P1', 'M1')
        self.assertEqual(plans.show(self.ledger, 'P1')['status'], 'stopped_with_report')
        self.assertEqual([d['status'] for d in self.documents()], ['stopped_with_report'] * 2)
        self.assertEqual(self.hook('a.txt'), 2)
        level, text = self.doctor()
        self.assertEqual(level, 'WARN', text)
        self.assertIn('stopped_with_report', text)

    def test_amended_and_approved_revision_export_matches_ledger(self):
        self.enforce()
        plans.amend(self.ledger, 'P1', owned_plan(scope={'owned': ['a.txt', 'src/', 'more.txt']}), 'need more.txt', 'claude')
        plans.approve(self.ledger, 'P1', 'owner', 'ok')
        sha = plans.show(self.ledger, 'P1')['sha']
        self.assertEqual([(d['revision'], d['status'], d['plan_sha']) for d in self.documents()], [(2, 'approved', sha)] * 2)
        self.assertEqual(self.doctor()[0], 'PASS')

    def test_accepting_one_plan_never_replaces_the_governing_plan(self):
        artifact = self.passed_plan()
        self.approved('P2', owned_plan(scope={'owned': ['other.txt']}))
        active_plan.export(self.ledger, 'P2', take_over=True)              # P2 governs now
        plans.accept(self.ledger, 'P1', 'owner', 'fixture acceptance', artifact)
        self.assertEqual([(d['plan'], d['status']) for d in self.documents()], [('P2', 'approved')] * 2)
        self.rewrite(expires=PAST)
        self.assertEqual(self.hook('other.txt'), 2)                        # P1 being over releases nothing for P2

    # ---- I3, option doctor-va-tu-lanh: the expired export of a finished plan --------------------------------------------------------

    def test_hook_passes_expired_export_when_ledger_accepted(self):
        self.stale()
        self.assertEqual(self.hook(), 0)
        self.assertEqual(self.hook(command='git status'), 0)

    def test_hook_passes_expired_export_when_ledger_closed_by_owner(self):
        self.stale(end='closed')
        self.assertEqual(self.hook(), 0)
        self.assertEqual(self.hook(command='git status'), 0)

    def test_hook_still_blocks_expired_open_plan(self):
        self.enforce()
        self.rewrite(expires=PAST)
        self.assertEqual(self.hook('a.txt'), 2)
        self.assertEqual(self.hook(command='git status'), 2)

    def test_hook_blocks_when_ledger_cannot_be_read(self):
        self.stale()
        ledger = Path(self.ledger.state_root) / 'ledger.sqlite3'
        kept = ledger.read_bytes()
        ledger.write_bytes(b'not a database' * 200)
        try:
            self.assertEqual(self.hook(), 2)
        finally:
            ledger.write_bytes(kept)
        self.rewrite(state_root=str(Path(self.ledger.state_root) / 'gone'))
        self.assertEqual(self.hook(), 2)

    def test_hook_blocks_when_ledger_names_another_plan_sha(self):
        self.stale()
        self.rewrite(plan_sha='0' * 64)
        self.assertEqual(self.hook(), 2)

    def test_hook_blocks_when_export_names_another_ledger(self):
        """Review I7 Q2: the export may not choose the ledger that releases it. The hook's ledger says open; the file points at one that says accepted."""
        self.enforce()
        other = Path(self.ledger.state_root).parent / 'other-state'
        other.mkdir()
        shutil.copy2(Path(self.ledger.state_root) / 'ledger.sqlite3', other / 'ledger.sqlite3')
        elsewhere = Ledger(self.root, other)
        with elsewhere.transaction(write=True) as conn:
            state = plans.derive(elsewhere, conn, 'P1')
            plans.emit(elsewhere, conn, state['task_id'], 'plan.accepted',
                       {'plan': 'P1', 'revision': 1, 'sha': state['approved']['sha'], 'by': 'owner', 'reference': 'fixture', 'artifact_sha': self.tree()})
        self.rewrite(state_root=str(other.resolve()), expires=PAST)
        self.assertEqual(self.hook(), 2)

    def test_hook_passes_with_the_configured_ledger_when_the_hook_names_none(self):
        """The form `onecrew init` installs: `hook check` without --state-root takes the ledger from .onecrew/config.json."""
        self.stale()
        (self.root / '.onecrew' / 'config.json').write_text(json.dumps({'state_root': str(self.ledger.state_root)}), encoding='utf-8')
        home = Path(self.ledger.state_root).parent / 'home'
        env = dict({k: v for k, v in os.environ.items() if k not in ('CLAUDE_CODE_CHILD_SESSION', 'CLAUDECODE')},
                   PYTHONUTF8='1', LOCALAPPDATA=str(home), CLAUDE_PROJECT_DIR=str(self.root))
        done = subprocess.run([sys.executable, '-X', 'utf8', '-m', 'onecrew', 'hook', 'check'], input=json.dumps(self.edit('docs/x.md')).encode('utf-8'),
                              capture_output=True, cwd=REPO, timeout=120, env=env)
        self.assertEqual(done.returncode, 0, done.stderr.decode('utf-8', 'replace'))

    def test_hook_heal_writes_nothing_to_the_ledger(self):
        self.stale()
        before = self.ledger_bytes(), [path.read_bytes() for path in self.files()]
        self.hook()
        self.hook(command='git status')
        self.assertEqual((self.ledger_bytes(), [path.read_bytes() for path in self.files()]), before)
