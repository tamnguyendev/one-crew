"""QSAT (B): a session whose own project (the hook process directory) is registered with an active plan stays bound to that plan when it reads,
edits or runs a command in another registered project that has a plan; a plan switch in its own project, a session outside every registered
project that touches two plans, and a binding an older release marked ambiguous (no cause) all stay unbound (owner option giu-ban-ghi-cu).

Two projects A and B on one state root, each with its own approved, exported plan (PA, PB). The fixture follows tests/test_obs3_observe.py, copied
here so that no test class of that module is imported (and run twice)."""
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from onecrew.v2 import active_plan, hook_cli, install, session_observe, where
from tests.test_ui33_task_first import Project, milestone


class TestQsatGan(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        base = Path(temp.name)
        env = patch.dict(os.environ)
        env.start()
        self.addCleanup(env.stop)
        for key in ('CLAUDE_CODE_ENTRYPOINT', 'ONECREW_ACTOR', 'ONECREW_V2_REQUIRE_PLAN', 'CLAUDECODE', 'CLAUDE_CODE_CHILD_SESSION'):
            os.environ.pop(key, None)
        self.home = base / 'home'
        self.other = base / 'unrelated'
        self.other.mkdir()
        self.a = Project(base, 'project-a', base / 'state')
        self.b = Project(base, 'project-b', base / 'state')
        os.environ.update(HOME=str(self.home), USERPROFILE=str(self.home), CLAUDE_CONFIG_DIR=str(self.home / '.claude'),
                          LOCALAPPDATA=str(base / 'local'), APPDATA=str(base / 'roaming'))
        os.environ.pop('CLAUDE_PROJECT_DIR', None)
        for project, name in ((self.a, 'PA'), (self.b, 'PB')):
            project.plan(name, [milestone()])
            active_plan.export(project.ledger, name, strict=True)
            where.register_project(project.root, project.ledger.state_root)
        self.observe_args = self.install_fixture_observer(base)
        self.home_dir = self.a.root          # the session's own folder (the hook process directory); a test may move it

    @staticmethod
    def install_fixture_observer(base):
        """`hook user install --observe` writes the handlers (with their install key) into a fixture settings file; returns the observe args."""
        program = base / 'fixture-bin' / ('onecrew.cmd' if os.name == 'nt' else 'onecrew')
        program.parent.mkdir(parents=True, exist_ok=True)
        program.write_text('@exit /b 0\r\n' if os.name == 'nt' else '#!/bin/sh\nexit 0\n', encoding='ascii')
        program.chmod(0o755)
        settings = base / 'fixture-profile' / 'settings.json'
        with contextlib.redirect_stdout(io.StringIO()) as out:
            if install.user_hook('install', settings, program, observe=True) != 0: raise AssertionError(out.getvalue())
        hooks = json.loads(settings.read_text(encoding='utf-8'))['hooks']
        args, = [h['args'] for entry in hooks['UserPromptSubmit'] for h in entry['hooks'] if h['args'][:2] == ['hook', 'observe']]
        return args

    def call(self, name, **extra):
        event = dict({'hook_event_name': name, 'cwd': str(self.home_dir), 'session_id': 'session-1'}, **extra)
        stdin = type('Input', (), {'buffer': io.BytesIO(json.dumps(event).encode())})()
        with patch.object(Path, 'cwd', return_value=self.home_dir), patch.object(sys, 'stdin', stdin), \
                contextlib.redirect_stdout(io.StringIO()) as out, contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertEqual(hook_cli.main(self.observe_args), 0)
        self.assertEqual(out.getvalue(), '')
        return err.getvalue()

    def observed(self, project, name):
        task = project.state(name)['task_id']
        return [e['payload'] for e in project.ledger.events(task) if e['kind'] == 'hook.observed']

    def binding(self):
        """(status, plan of the target) of session-1's binding record; (None, None) when there is none."""
        items = session_observe.bindings()
        if not items: return None, None
        item, = items
        return item.get('status'), (item.get('target') or {}).get('plan')

    def stays_bound(self, **reach):
        """Bind in A, reach B with one call, end the turn: still bound to PA, the reaching call is in A's ledger, B's ledger has no row."""
        self.call('PreToolUse', tool_name='Read', tool_use_id='own-read', tool_input={'file_path': str(self.a.root / 'a.txt')})
        self.assertEqual(self.binding(), ('bound', 'PA'))
        self.call('PreToolUse', tool_use_id='reach-b', **reach)
        self.call('UserPromptSubmit', prompt='tiếp')
        self.call('Stop')
        self.assertEqual(self.binding(), ('bound', 'PA'))
        rows = self.observed(self.a, 'PA')
        self.assertEqual([r['tool_use_id'] for r in rows if r['hook'] == 'PreToolUse'], ['own-read', 'reach-b'])
        self.assertEqual([r['observation'] for r in rows][-2:], ['owner_prompt', 'turn_end'])
        self.assertEqual(self.observed(self.b, 'PB'), [])

    def test_session_project_stays_bound_after_reading_other_plan(self):
        self.stays_bound(tool_name='Read', tool_input={'file_path': str(self.b.root / 'a.txt')})

    def test_session_project_stays_bound_after_shell_in_other_plan(self):
        self.stays_bound(tool_name='Bash', tool_input={'command': 'cd "' + self.b.root.as_posix() + '" && git status'})

    def test_session_project_stays_bound_after_edit_in_other_plan(self):
        self.stays_bound(tool_name='Edit', tool_input={'file_path': str(self.b.root / 'a.txt'), 'old_string': 'one', 'new_string': 'two'})

    def test_plan_switch_in_same_project_still_ambiguous(self):
        self.call('PreToolUse', tool_name='Read', tool_use_id='own-read', tool_input={'file_path': str(self.a.root / 'a.txt')})
        self.assertEqual(self.binding(), ('bound', 'PA'))
        self.a.plan('PA2', [milestone()])
        active_plan.export(self.a.ledger, 'PA2', take_over=True, strict=True)
        self.call('UserPromptSubmit', prompt='ambiguous private text')
        self.call('Stop')
        item, = session_observe.bindings()
        self.assertEqual((item['status'], item['reason'], item['ambiguous']), ('unbound', 'multiple plans', True))
        self.assertNotIn('private text', str(self.observed(self.a, 'PA')) + str(self.observed(self.a, 'PA2')))

    def test_unregistered_session_touching_two_plans_stays_unbound(self):
        self.home_dir = self.other
        self.call('PreToolUse', tool_name='Edit', tool_use_id='edit-a', tool_input={'file_path': str(self.a.root / 'a.txt')})
        self.assertEqual(self.binding(), ('bound', 'PA'))
        self.call('PreToolUse', tool_name='Read', tool_use_id='read-b', tool_input={'file_path': str(self.b.root / 'a.txt')})
        self.call('UserPromptSubmit', prompt='ambiguous private text')
        self.call('Stop')
        item, = session_observe.bindings()
        self.assertEqual((item['status'], item['reason'], item['ambiguous']), ('unbound', 'multiple plans', True))
        session_observe.flush(self.a.ledger, self.observe_args[3])
        self.assertNotIn('private text', str(self.observed(self.a, 'PA')))
        self.assertEqual(self.observed(self.b, 'PB'), [])

    def test_session_project_from_claude_project_dir_survives_cd(self):
        # Claude was started in A (CLAUDE_PROJECT_DIR); a `cd` that persists in its shell moved the hook process directory to B, which has a plan
        os.environ['CLAUDE_PROJECT_DIR'] = str(self.a.root)
        self.call('PreToolUse', tool_name='Read', tool_use_id='own-read', tool_input={'file_path': str(self.a.root / 'a.txt')})
        self.assertEqual(self.binding(), ('bound', 'PA'))
        self.home_dir = self.b.root
        self.call('PreToolUse', tool_name='Bash', tool_use_id='after-cd', tool_input={'command': 'git status'})
        self.call('Stop')
        item, = session_observe.bindings()
        self.assertEqual((item['status'], item['ambiguous'], (item.get('target') or {}).get('plan')), ('bound', False, 'PA'))
        self.assertIn('after-cd', [r['tool_use_id'] for r in self.observed(self.a, 'PA')])
        self.assertEqual(self.observed(self.b, 'PB'), [])

    def test_plan_switch_cause_is_plan_changed(self):
        self.call('PreToolUse', tool_name='Read', tool_use_id='own-read', tool_input={'file_path': str(self.a.root / 'a.txt')})
        self.a.plan('PA2', [milestone()])
        active_plan.export(self.a.ledger, 'PA2', take_over=True, strict=True)
        self.call('Stop')
        item, = session_observe.bindings()
        self.assertEqual((item['status'], item.get('cause')), ('unbound', 'plan_changed'))

    def test_unregistered_two_plans_cause_is_places(self):
        self.home_dir = self.other
        self.call('PreToolUse', tool_name='Edit', tool_use_id='edit-a', tool_input={'file_path': str(self.a.root / 'a.txt')})
        self.call('PreToolUse', tool_name='Read', tool_use_id='read-b', tool_input={'file_path': str(self.b.root / 'a.txt')})
        item, = session_observe.bindings()
        self.assertEqual((item['status'], item.get('cause')), ('unbound', 'places'))

    def test_session_project_without_approved_plan_keeps_old_rule(self):
        # the session's own project is registered, but its plan is not approved: no own plan, so the earlier rule decides (A, then B: ambiguous)
        c = Project(self.a.root.parent, 'project-c', self.a.ledger.state_root)
        c.plan('PC', [milestone()], approve=False)
        where.register_project(c.root, c.ledger.state_root)
        self.home_dir = c.root
        self.call('PreToolUse', tool_name='Edit', tool_use_id='edit-a', tool_input={'file_path': str(self.a.root / 'a.txt')})
        self.assertEqual(self.binding(), ('bound', 'PA'))
        self.call('PreToolUse', tool_name='Read', tool_use_id='read-b', tool_input={'file_path': str(self.b.root / 'a.txt')})
        item, = session_observe.bindings()
        self.assertEqual((item['status'], item['reason'], item.get('cause')), ('unbound', 'multiple plans', 'places'))

    def test_own_plan_after_binding_elsewhere_is_ambiguous(self):
        # bound to B first (from a folder outside every project); then the hook runs from A, whose plan is the session's own: two projects
        self.home_dir = self.other
        self.call('PreToolUse', tool_name='Edit', tool_use_id='edit-b', tool_input={'file_path': str(self.b.root / 'a.txt')})
        self.assertEqual(self.binding(), ('bound', 'PB'))
        self.home_dir = self.a.root
        self.call('PreToolUse', tool_name='Read', tool_use_id='own-read', tool_input={'file_path': str(self.a.root / 'a.txt')})
        item, = session_observe.bindings()
        self.assertEqual((item['status'], item['reason'], item.get('cause')), ('unbound', 'multiple plans', 'places'))

    def test_old_ambiguous_record_stays_unbound(self):
        folder = session_observe._sessions()
        folder.mkdir(parents=True, exist_ok=True)
        record = {'session': 'session-1', 'target': None, 'ambiguous': True, 'status': 'unbound', 'reason': 'multiple plans'}      # an older release's: no cause
        path = folder / (session_observe._digest('session-1') + '.json')
        path.write_text(json.dumps(record), encoding='utf-8')
        self.call('PreToolUse', tool_name='Read', tool_use_id='own-read', tool_input={'file_path': str(self.a.root / 'a.txt')})
        self.call('UserPromptSubmit', prompt='old private text')
        self.call('Stop')
        self.assertEqual(json.loads(path.read_text(encoding='utf-8')), record)
        self.assertEqual(self.observed(self.a, 'PA'), [])
        self.assertEqual(self.observed(self.b, 'PB'), [])


if __name__ == '__main__':
    unittest.main()
