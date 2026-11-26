"""VER60B. The verifier template measures red tests on a base tree in the same run; plan lint notes a saved baseline file."""
import subprocess
import sys
import tempfile
import unittest
from importlib.resources import files
from pathlib import Path

from onecrew.v2 import lint
from tests.test_ui33_task_first import Project, milestone, plan_json
from tests.test_ver60_lint import example

PASS = 'pass'
FAIL = 'self.fail("broken")'
SKIP = 'self.skipTest("missing fixture")'
SUSPECT = 'nền nghi lỗi'


def module(**cases):
    """A test module with one method per name; the value is the body of the method."""
    methods = ''.join(f'    def {name}(self):\n        {body}\n' for name, body in cases.items())
    return 'import unittest\nclass Sample(unittest.TestCase):\n' + (methods or '    pass\n')


class TestVer60b(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(tmp.cleanup)
        self.top = Path(tmp.name)
        self.script = self.top / 'checks' / 'verify.py'
        self.script.parent.mkdir()
        self.script.write_text(example('python'), encoding='utf-8')

    def tree(self, name, **modules):
        root = self.top / name
        (root / 'tests').mkdir(parents=True)
        (root / 'tests' / '__init__.py').touch()
        for stem, source in modules.items():
            (root / 'tests' / f'{stem}.py').write_text(source, encoding='utf-8')
        return root

    def verify(self, candidate, *args):
        done = subprocess.run([sys.executable, '-I', '-B', str(self.script), *map(str, args)], cwd=candidate, capture_output=True,
                              encoding='utf-8', errors='replace', timeout=120)
        return done.returncode, done.stdout, done.stderr

    def test_template_base_excuses_red_that_is_red_on_base(self):
        source = module(test_old=FAIL, test_good=PASS)
        base, candidate = self.tree('base', test_sample=source), self.tree('new', test_sample=source)
        for target in ('tests.test_sample', '--all'):
            with self.subTest(target=target):
                code, out, err = self.verify(candidate, '--base', base, target)
                self.assertEqual(code, 0, out + err)
                self.assertIn('Đỏ nền', out)
                self.assertIn('tests.test_sample.Sample.test_old', out)
                self.assertNotIn('test_good', out)
                self.assertIn('Ran 2 tests', err)

    def test_template_base_fails_red_not_on_base(self):
        base = self.tree('base', test_sample=module(test_old=FAIL, test_new=PASS))
        candidate = self.tree('new', test_sample=module(test_old=FAIL, test_new=FAIL))
        code, out, err = self.verify(candidate, '--base', base, 'tests.test_sample')
        self.assertEqual(code, 1, out + err)
        self.assertIn('test_new', out + err)

    def test_template_base_that_ran_nothing_fails(self):
        candidate = self.tree('new', test_sample=module(test_find=PASS))
        bases = {'no case': self.tree('empty', test_sample=module()),
                 'module missing': self.tree('missing'),
                 'crashed': self.tree('crashed', test_sample='import os\nos._exit(3)\n'),
                 'only skips': self.tree('skips', test_sample=module(test_find=SKIP)),
                 'not a folder': self.top / 'nowhere',
                 'the candidate itself': candidate}
        for label, base in bases.items():
            with self.subTest(base=label):
                code, out, err = self.verify(candidate, '--base', base, 'tests.test_sample')
                self.assertEqual(code, 1, out + err)
                self.assertIn(SUSPECT, out)

    def test_template_base_mostly_red_fails(self):
        three = module(test_a=FAIL, test_b=FAIL, test_c=FAIL, test_good=PASS)
        four = module(test_a=FAIL, test_b=FAIL, test_c=FAIL, test_d=FAIL, test_good=PASS)
        for label, source, extra, expected in (('three of default', three, [], 0), ('four of default', four, [], 1),
                                               ('four allowed', four, ['--base-red-max', '4'], 0),
                                               ('three, two allowed', three, ['--base-red-max', '2'], 1)):
            with self.subTest(label):
                base = self.tree(f'base {label}', test_sample=source)
                candidate = self.tree(f'new {label}', test_sample=source)
                code, out, err = self.verify(candidate, 'tests.test_sample', '--base', base, *extra)
                self.assertEqual(code, expected, out + err)
                self.assertEqual(SUSPECT in out, bool(expected), out)

    def test_template_base_skip_still_fails(self):
        for label, base_body in (('skipped on both', SKIP), ('red on base', FAIL), ('green on base', PASS)):
            with self.subTest(label):
                base = self.tree(f'base {label}', test_sample=module(test_find=base_body, test_good=PASS))
                candidate = self.tree(f'new {label}', test_sample=module(test_find=SKIP, test_good=PASS))
                for args in (['--base', base], []):
                    code, out, err = self.verify(candidate, *args, 'tests.test_sample')
                    self.assertEqual(code, 1, out + err)

    def test_template_without_base_unchanged(self):
        candidate = self.tree('new')
        source = candidate / 'tests' / 'test_search.py'
        for body, expected in ((PASS, 0), (SKIP, 1), (FAIL, 1), (None, 1)):
            source.write_text(module(test_find=body) if body else '', encoding='utf-8')
            for target in ('tests.test_search', '--all'):
                with self.subTest(body=body, target=target):
                    code, out, err = self.verify(candidate, target)
                    self.assertEqual(code, expected, out + err)
                    self.assertIn('Ran ', err)
        self.assertEqual(self.verify(candidate)[0], 1)

    def test_template_base_never_excuses_cases_that_did_not_run(self):
        good = module(test_find=PASS)
        broken = {'import error': 'import no_such_module_ver60b\n',
                  'class set-up': 'import unittest\nclass Sample(unittest.TestCase):\n    @classmethod\n    def setUpClass(cls):\n'
                                  '        raise RuntimeError("no server")\n    def test_find(self):\n        pass\n',
                  'module set-up': 'def setUpModule():\n    raise RuntimeError("no server")\n' + good}
        for label, source in broken.items():
            with self.subTest(label):
                base = self.tree(f'base {label}', test_good=good, test_other=source)
                candidate = self.tree(f'new {label}', test_good=good, test_other=source)
                code, out, err = self.verify(candidate, '--base', base, 'tests.test_good', 'tests.test_other')
                self.assertEqual(code, 1, out + err)
                self.assertIn('không bao giờ là đỏ nền', out)
                self.assertNotIn(SUSPECT, out)

    def test_template_base_compares_subtests_one_by_one(self):
        def source(bad):
            return module(test_each=f'for i in (1, 2):\n            with self.subTest(i=i):\n                self.assertNotEqual(i, {bad})')
        base = self.tree('base', test_sample=source(1))
        self.assertEqual(self.verify(self.tree('same', test_sample=source(1)), '--base', base, 'tests.test_sample')[0], 0)
        code, out, err = self.verify(self.tree('other', test_sample=source(2)), '--base', base, 'tests.test_sample')
        self.assertEqual(code, 1, out + err)
        self.assertIn('(i=2)', out)

    def test_template_base_candidate_that_stops_early_fails(self):
        base = self.tree('base', test_sample=module(test_find=PASS))
        for label, source in (('crashed', 'import os\nos._exit(0)\n'), ('no case', module())):
            with self.subTest(label):
                code, out, err = self.verify(self.tree(f'new {label}', test_sample=source), '--base', base, 'tests.test_sample')
                self.assertEqual(code, 1, out + err)
                self.assertIn('không có ca nào', out)

    def test_template_base_tree_is_left_as_it_was(self):
        source = module(test_write='open("written.txt", "w").close()')
        base, candidate = self.tree('base', test_sample=source), self.tree('new', test_sample=source)
        before = sorted(p.relative_to(base).as_posix() for p in base.rglob('*'))
        code, out, err = self.verify(candidate, '--base', base, 'tests.test_sample')
        self.assertEqual(code, 0, out + err)
        self.assertEqual(sorted(p.relative_to(base).as_posix() for p in base.rglob('*')), before)
        self.assertTrue((candidate / 'written.txt').is_file())

    def test_template_text_names_base_and_same_run(self):
        text = files('onecrew.templates').joinpath('command-inputs.vi.md').read_text(encoding='utf-8')
        for words in ('--base', '--base-red-max', 'đỏ nền', 'cùng lượt', SUSPECT):
            self.assertIn(words, text)

    def lint_warnings(self, *milestones):
        if not hasattr(self, 'project'):
            self.state = self.top / 'state'
            self.project = Project(self.top, 'repo', self.state)
        reasons, warnings = lint.check(lint.ReadOnlyLedger(self.project.root, self.state), plan_json(list(milestones)))
        self.assertEqual(reasons, [])
        return [text for code, text in warnings if code == 'command_saved_baseline']

    def checker(self, name, source):
        path = self.script.parent / name
        path.write_text(source, encoding='utf-8')
        return [sys.executable, '-I', str(path)]

    def test_lint_warns_saved_baseline_file(self):
        argv = self.checker('kiem.py', "from pathlib import Path\nBASE = Path(__file__).parent / 'baseline-red.json'\n")
        found = self.lint_warnings(milestone('M1', argv + ['L']), milestone('M2', argv + ['R']))
        self.assertEqual(len(found), 1, found)
        for words in ('M1, M2:', 'kiem.py', 'baseline-red.json', '--base'):
            self.assertIn(words, found[0])
        for number, name in enumerate(('red-BASELINE.txt', 'baseline_{key}.yml', 'out/baseline-r2.jsonl')):
            with self.subTest(name):
                argv = self.checker(f'k{number}.ps1', f'Get-Content "D:/checks/{name}"\n')
                self.assertEqual(len(self.lint_warnings(milestone('M1', argv))), 1)

    def test_lint_quiet_without_baseline_file(self):
        quiet = ("# the baseline is measured in this run, on the base tree\nimport tests.test_baseline\n"
                 "MODULES = ['tests.test_baseline', 'measure_baseline.py']\nDATA = 'expected.json'\n")
        argv = self.checker('plain.py', quiet)
        self.assertEqual(self.lint_warnings(milestone('M1', argv)), [])
        missing = [sys.executable, '-I', str(self.script.parent / 'baseline-missing.py')]
        self.assertEqual(self.lint_warnings(milestone('M1', missing)), [])
        self.assertEqual(self.lint_warnings(milestone('M1', [sys.executable, '-c', "print('baseline-red.json')"])), [])


if __name__ == '__main__':
    unittest.main()
