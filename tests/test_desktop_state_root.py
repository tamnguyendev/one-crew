"""One Windows notice per outcome for every runner of a state root (synthesis §3.8): the outbox lives under the state
root, launches break away like runner.start, the title follows the completion level and the report carries the reply
command. Windows windows are fixtures; nothing is shown."""
import os
from pathlib import Path
import unittest
from unittest.mock import MagicMock, patch

from onecrew import desktop_notifications as desktop
from onecrew.ledger import Ledger
from tests import test_owned as fixtures


def item(state, phase='completed', questions=()):
    return dict(id='a'*32, task='TASK-'+'1'*32, project='D:/work/project', state_root='C:/state/OneCrew',
                checkpoint=7, phase=phase, state=state, questions=list(questions))


def root(kinds, criteria=None, receipts=None, verification='passed'):
    """A completed delivery-root checkpoint with one node per kind."""
    nodes = [{'id': kind, 'kind': kind} for kind in kinds]
    rows = {n['id']: {'phase': 'passed', 'receipt': dict({'passed': True}, **(receipts or {}).get(n['id'], {}))} for n in nodes}
    return {'phase': 'completed', 'verification': verification, 'plan': {'nodes': nodes},
            'delivery': {'nodes': rows, 'criteria': criteria or {'AC1': 'passed'}, 'technical_verified': verification == 'passed'}}


FULL = ('change', 'regression', 'review', 'node_build', 'e2e_mock', 'e2e_live', 'commit', 'handover')
QUESTION = {'id': 'REQ-'+'b'*32, 'revision': 'c'*64, 'question': 'Thử lại hay dừng?', 'reason': 'runtime_bug',
            'options': [{'id': 'retry', 'label': 'Thử lại'}, {'id': 'stop', 'label': 'Dừng'}]}


class StateRootOutboxTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.OwnedTests(); self.f.setUp(); self.addCleanup(self.f.doCleanups)
        self.base = Path(self.f.temp.name)
        self.old_home = self.base/'install'/'.onecrew'/'desktop'
        env = patch.dict(os.environ, ONECREW_DESKTOP_HOME=str(self.old_home)); env.start(); self.addCleanup(env.stop)
        launcher = patch.object(desktop, 'launch'); self.launch = launcher.start(); self.addCleanup(launcher.stop)
        self.run, self.task, _ = self.f.runtime([])
        self.ledger = self.f.ledger

    def change(self, phase, ledger=None):
        runtime = self.run if ledger is None else type(self.run)(ledger, self.run.worker)
        seq, state = runtime.state(self.task)
        state.update(phase=phase, message='Fixture '+phase)
        runtime.persist(self.task, seq, state)

    def test_outbox_under_state_root(self):
        config = desktop.configure(self.ledger, True)
        folder = self.ledger.state_root.resolve()/'desktop'
        self.assertEqual(Path(config['directory']), folder)
        self.assertTrue((folder/'config.json').is_file())
        self.assertFalse(self.old_home.exists())  # the per-install location is only read for migration
        self.change('blocked')
        [record] = desktop.status(self.ledger)['records']
        self.assertEqual(Path(record['report']).parent, folder)
        with patch.dict(os.environ, ONECREW_DESKTOP_HOME=str(self.base/'other-worktree')):
            self.assertEqual(desktop.directory(Ledger(self.f.root, self.ledger.state_root)), folder)

    def test_keeper_and_reply_share_dedup(self):
        desktop.configure(self.ledger, True)
        keeper_side = Ledger(self.f.root, self.ledger.state_root)  # e.g. the keeper's process: no desktop env at all
        with patch.dict(os.environ):
            os.environ.pop('ONECREW_DESKTOP_HOME')
            self.change('blocked', keeper_side)
            self.assertEqual(desktop.publish(keeper_side)['launched'], [])
        # A reply typed in another shell, through another worktree's runtime, sees the same flag and dedup set.
        with patch.dict(os.environ, ONECREW_DESKTOP_HOME=str(self.base/'reply-shell')):
            reply_side = Ledger(self.f.root, self.ledger.state_root)
            self.assertTrue(desktop.status(reply_side)['config']['enabled'])
            self.assertEqual(desktop.publish(reply_side, self.task)['launched'], [])
        self.assertEqual(self.launch.call_count, 1)
        self.assertEqual(len(desktop.status(self.ledger)['records']), 1)

    def test_one_time_migration_keeps_flag_and_dedup(self):
        desktop.configure(self.ledger, True)
        self.change('blocked')
        folder = desktop.directory(self.ledger)
        # Rebuild the pre-12/10 layout: <install>/.onecrew/desktop/<state-root hash>/ with a shown receipt.
        from onecrew.ledger import content_hash
        old = self.old_home/content_hash(str(self.ledger.state_root.resolve()).casefold())[:16]
        old.mkdir(parents=True)
        files = sorted(p for p in folder.glob('*') if p.is_file())
        for path in files: (old/path.name).write_bytes(path.read_bytes())
        [record] = [p for p in old.glob('*.json') if len(p.stem) == 32]
        shown = desktop.read(record); shown.update(status='shown', report=str(old/(record.stem+'.txt'))); desktop.write(record, shown)
        before = {p.name: p.read_bytes() for p in old.glob('*')}
        for path in folder.glob('*.*'): path.unlink()
        self.assertEqual(desktop.status(self.ledger)['config']['enabled'], True)  # migrated on first use
        migrated = desktop.read(folder/'config.json')
        self.assertEqual(migrated['migrated_from'], str(old))
        [copy] = desktop.status(self.ledger)['records']
        self.assertEqual((copy['status'], Path(copy['report'])), ('shown', folder/(record.stem+'.txt')))
        self.assertTrue(Path(copy['report']).is_file())
        desktop.publish(self.ledger, self.task)
        self.assertEqual(self.launch.call_count, 1)  # the outcome shown before migration is not shown again
        self.assertEqual({p.name: p.read_bytes() for p in old.glob('*')}, before)  # old files untouched
        desktop.write(old/'config.json', dict(desktop.read(old/'config.json'), enabled=False))
        self.assertTrue(desktop.status(self.ledger)['config']['enabled'])  # one time only

    def test_partial_title_not_done(self):
        cases = [
            (root(FULL), 'Hoàn thành trọn luồng'),
            (root(FULL, criteria={'AC1': 'passed', 'AC4': 'not_run'}, receipts={'e2e_live': {'skipped': True}}, verification='partial'),
             'Hoàn thành một phần (not_run: AC4, e2e_live)'),
            (root(FULL, verification='pending'), 'Hoàn thành một phần (not_run: chưa kiểm chứng)'),
            (root(('change', 'regression', 'review', 'handover')), 'Hoàn thành theo kế hoạch (không có: build, E2E)'),
            (root(('change', 'regression', 'review', 'build', 'apk_audit', 'handover')), 'Hoàn thành theo kế hoạch (không có: E2E)'),
            ({'phase': 'completed', 'verification': {'passed': True}}, 'Hoàn thành job đơn lẻ (không phải trọn luồng)'),
        ]
        for state, expected in cases:
            with self.subTest(expected=expected):
                self.assertEqual(desktop.title(item(state)), expected)
                self.assertTrue(desktop.text_report(item(state)).startswith('OneCrew — '+expected+'\n'))
        self.assertEqual(desktop.title(item({'phase': 'blocked'}, 'blocked')), 'Bị chặn')
        self.assertEqual(desktop.title(item({'phase': 'waiting'}, 'waiting', [QUESTION])), 'Cần anh trả lời')
        self.assertEqual(desktop.title(item({'phase': 'blocked'}, 'blocked', [QUESTION])), 'Cần anh trả lời')
        desktop.configure(self.ledger, True)
        self.change('blocked')
        self.assertEqual(desktop.status(self.ledger)['records'][0]['title'], 'Bị chặn')

    def test_window_shows_level_title(self):
        from types import SimpleNamespace
        from onecrew import desktop_window
        desktop.configure(self.ledger, True)
        self.change('blocked')
        [record] = desktop.status(self.ledger)['records']
        seen = []

        class Widget:
            def __init__(self, *args, **kwargs): seen.append(kwargs.get('text'))
            def pack(self, **kwargs): pass
            def insert(self, *args): pass
            def configure(self, **kwargs): pass

        class Window(Widget):
            def title(self, text): seen.append(text)
            def geometry(self, *args): pass
            def attributes(self, *args): pass
            def after(self, *args): pass
            def destroy(self): pass
            def protocol(self, name, callback): self.close = callback
            def bind(self, name, callback): pass
            def mainloop(self): self.close()

        with patch.dict('sys.modules', {'tkinter': SimpleNamespace(Tk=Window, Label=Widget, Frame=Widget, Button=Widget),
                                       'tkinter.scrolledtext': SimpleNamespace(ScrolledText=Widget)}):
            desktop_window.show(desktop.directory(self.ledger), record['id'])
        self.assertIn('OneCrew — Bị chặn — '+self.task, seen)

@unittest.skipUnless(os.name == 'nt', 'creation flags are Windows-only')
class LaunchTests(unittest.TestCase):
    def test_launch_breakaway(self):
        import subprocess
        folder, key = Path('C:/state/OneCrew/desktop'), 'a'*32
        with patch('onecrew.desktop_notifications.subprocess.Popen') as popen:
            desktop.launch(folder, key)
        argv, options = popen.call_args.args[0], popen.call_args.kwargs
        self.assertEqual(argv[-4:], ['-m', 'onecrew.desktop_window', str(folder), key])
        self.assertEqual(options['creationflags'], 0x8 | 0x200 | 0x01000000)  # same as runner.start
        self.assertEqual((options['stdin'], options['stdout'], options['stderr']), (subprocess.DEVNULL,)*3)
        with patch('onecrew.desktop_notifications.subprocess.Popen', side_effect=[PermissionError(13, 'Access is denied'), MagicMock()]) as popen:
            desktop.launch(folder, key)  # a Job that forbids breakaway still gets a detached window
        self.assertEqual([c.kwargs['creationflags'] for c in popen.call_args_list], [0x8 | 0x200 | 0x01000000, 0x8 | 0x200])
        with patch('onecrew.desktop_notifications.subprocess.Popen', side_effect=OSError('no interactive desktop')):
            with self.assertRaises(OSError): desktop.launch(folder, key)  # publish keeps the entry pending


class ReportTests(unittest.TestCase):
    def test_report_has_reply_command(self):
        text = desktop.text_report(item({'phase': 'waiting', 'message': 'Cần quyết định'}, 'waiting', [QUESTION]))
        launcher = str(Path(desktop.__file__).resolve().parents[1]/'onecrew.ps1')
        for choice in ('retry', 'stop'):
            self.assertIn("$env:ONECREW_ACTOR='user'; & '"+launcher+"' --project 'D:/work/project' --state-root 'C:/state/OneCrew'"
                          ' request reply '+QUESTION['id']+' --revision '+QUESTION['revision']+' --choice '+choice+' --decided-by user', text)
        creq = dict(QUESTION, id='CREQ-'+'d'*32)
        text = desktop.text_report(item({'phase': 'waiting'}, 'waiting', [creq]))
        self.assertIn('conversation reply --file', text); self.assertIn(creq['id'], text)
        quoted = desktop.text_report(dict(item({'phase': 'waiting'}, 'waiting', [QUESTION]), project="D:/anh's project"))
        self.assertIn("--project 'D:/anh''s project'", quoted)

    def test_generic_artifact_e2e_git_fields(self):
        state = root(FULL, receipts={
            'node_build': {'dist_tree_sha256': 'e'*64, 'manifest_version': '0.6.11', 'variant': 'uat', 'log': 'L'},
            'e2e_mock': {'checks': {'passed': 17, 'total': 17}, 'runs': 3},
            'e2e_live': {'skipped': True, 'detail': 'login window expired'},
            'commit': {'commit': 'f'*40, 'branch': 'claude/linh-thuoc', 'pushed': False}})
        state['delivery']['git'] = {'head': 'a'*40, 'branch': 'claude/linh-thuoc'}
        text = desktop.text_report(item(state))
        self.assertIn('Artifact (node_build): {"dist_tree_sha256":"'+'e'*64+'","manifest_version":"0.6.11","passed":true,"variant":"uat"}', text)
        self.assertIn('E2E (e2e_mock): {"checks":{"passed":17,"total":17},"passed":true,"runs":3}', text)
        self.assertIn('E2E (e2e_live): {"detail":"login window expired","passed":true,"skipped":true}', text)
        self.assertIn('Git (commit): {"branch":"claude/linh-thuoc","commit":"'+'f'*40+'","passed":true,"pushed":false}', text)
        self.assertIn('Git baseline: ', text)
        self.assertNotIn('APK', text)  # no Android wording when there is no APK evidence
        apk = desktop.text_report(item({'phase': 'completed', 'native_change': {'apk_build': {'artifact': 'app.apk'}}}))
        self.assertIn('APK artifact: "app.apk"', apk)


if __name__ == '__main__':
    unittest.main()
