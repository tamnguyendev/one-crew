"""VER60 ML. Exercise plan lint and the example shipped with the package."""
import contextlib
import copy
import io
import json
import subprocess
import sys
import tempfile
import unittest
from importlib.resources import files
from pathlib import Path

from onecrew.v2 import contract, lint, plan_cli
from tests.test_ui33_task_first import Project, milestone, plan_json


def example(language):
    guide = files('onecrew.templates').joinpath('command-inputs.vi.md').read_text(encoding='utf-8')
    return guide.split('```' + language + '\n', 1)[1].split('\n```', 1)[0]


class CommandLint(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name)
        self.state = self.base / 'state'
        self.project = Project(self.base, 'repo', self.state)
        self.script = self.base / 'outside tools' / 'verify.py'
        self.argv = [sys.executable, '-I', str(self.script)]

    def check(self, *milestones):
        raw = plan_json(list(milestones))
        before = copy.deepcopy(raw)
        reasons, warnings = lint.check(lint.ReadOnlyLedger(self.project.root, self.state), raw)
        self.assertEqual(reasons, [])
        self.assertEqual(raw, before)
        return warnings

    def test_warns_command_milestone_without_inputs(self):
        first = milestone('M1', self.argv + ['tests.test_first'])
        second = milestone('M2', self.argv + ['tests.test_second'])
        second['verifier']['config']['inputs'] = ['tests']
        for item in (first, second):
            item['verifier']['config']['env_inputs'] = [str(self.script)]
        path = self.base / 'contract.json'
        path.write_text(json.dumps(plan_json([first, second])), encoding='utf-8')
        before = path.read_bytes()
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = plan_cli.main(['--project', str(self.project.root), '--state-root', str(self.state),
                                  'plan', 'lint', '--file', str(path), '--ack-criteria'])
        self.assertEqual(code, 0)
        self.assertIn('command_inputs_missing', output.getvalue())
        self.assertIn('M1:', output.getvalue())
        self.assertNotIn('M2:', output.getvalue())
        self.assertEqual(path.read_bytes(), before)
        self.assertFalse(self.state.exists())

    def test_no_warning_single_milestone(self):
        self.assertEqual(self.check(milestone('M1', self.argv)), [])

    def test_warning_names_tests_and_imports(self):
        warnings = self.check(milestone('M1', self.argv + ['A']), milestone('M2', self.argv + ['B']))
        messages = [msg for code, msg in warnings if code == 'command_inputs_missing']
        self.assertEqual(len(messages), 2)
        for msg in messages:
            for word in ('inputs', 'test', 'import', 'dựng gói'):
                self.assertIn(word, msg)

    def test_warns_path_outside_repo_not_in_env_inputs(self):
        first = milestone('M1', self.argv + ['--baseline=' + str(self.base / 'outside tools old' / 'base.json'),
                                             str(self.project.root / 'a.txt')])
        first['verifier']['config']['env_inputs'] = [str(self.script.parent)]
        second = milestone('M2', [sys.executable, '-c', 'print(1)'])
        warnings = self.check(first, second)
        external = [msg for code, msg in warnings if code == 'command_env_input_missing']
        self.assertEqual(len(external), 1)
        self.assertIn('base.json', external[0])
        self.assertIn('M1:', external[0])

    def test_relative_external_path_uses_command_working_directory(self):
        first = milestone('M1', [sys.executable, '../a.txt', '../../outside.json'])
        first['verifier']['config']['cwd'] = 'subdir'
        warnings = self.check(first, milestone('M2'))
        external = [msg for code, msg in warnings if code == 'command_env_input_missing']
        self.assertEqual(len(external), 1)
        self.assertIn(str(self.base / 'outside.json'), external[0])

    def test_same_files_and_different_verbosity_do_not_suggest_splitting(self):
        first = milestone('M1', [sys.executable, 'tests/test_a.py'])
        second = milestone('M2', [sys.executable, '-v', 'tests/test_a.py'])
        self.assertEqual(self.check(first, second), [])


class Template(unittest.TestCase):
    def test_template_has_inputs_and_env_inputs(self):
        plan = contract.validate(json.loads(example('json')))
        mid, final = [m['verifier']['config'] for m in plan['milestones']]
        self.assertEqual(mid['env_inputs'], [mid['argv'][2]])
        self.assertIn('catalog', mid['inputs'])
        self.assertIn(mid['argv'][-1].replace('.', '/') + '.py', mid['inputs'])
        self.assertEqual(final['argv'][-1], '--all')
        self.assertNotIn('inputs', final)

    def test_skip_counts_as_failure_in_template(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runner = root / 'verify.py'
            runner.write_text(example('python'), encoding='utf-8')
            tests = root / 'tests'
            tests.mkdir()
            (tests / '__init__.py').touch()
            test = tests / 'test_search.py'
            for body, expected in [('pass', 0), ('self.skipTest("missing fixture")', 1),
                                   ('self.fail("broken")', 1), (None, 1)]:
                with self.subTest(body=body):
                    source = ''
                    if body:
                        source = 'import unittest\nclass Sample(unittest.TestCase):\n    def test_find(self):\n        ' + body
                    test.write_text(source, encoding='utf-8')
                    for target in ('tests.test_search', '--all'):
                        result = subprocess.run([sys.executable, '-I', '-B', str(runner), target], cwd=root,
                                                capture_output=True, text=True, timeout=30)
                        self.assertEqual(result.returncode, expected, result.stderr)
                        self.assertIn('Ran ', result.stderr)
