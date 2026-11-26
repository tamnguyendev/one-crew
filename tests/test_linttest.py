"""LINTTEST: existing tests are not changed unless the contract says so.

`plan lint` warns owned_covers_existing_tests (a warning, never a refusal) when scope.owned covers a test file already in HEAD and the contract does
not grant authority {edit, edit_tests}; it is silent for a test file that is new, when edit_tests is granted, and outside git. Option
canh-bao-va-chan: the exported active plan lists those files (frozen_tests, taken when the approved revision is first exported) and the hook refuses
to change one (rule existing_test; log mode records it); a new test file stays writable; an active plan exported before this change (no
frozen_tests) is judged as before; a project copy that drops the list is a changed copy.

Rule of these cases (contract LINTTEST, checker kiem-linttest.py): a case of new behaviour fails BY ASSERTION on the base 2.5.0.dev34 (a532cf9).
Real temporary repositories and ledgers (tests.v2_fixture); the hook runs as a real subprocess (tests.test_v2_l2.HookFixture).
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))          # test_v2_l2 imports test_v2_l1 by its plain name
from test_v2_l2 import REPO, HookFixture, owned_plan                # noqa: E402

from onecrew.ledger import Ledger                                   # noqa: E402
from onecrew.v2 import active_plan, hook_cli, lint, namespaces      # noqa: E402
from tests.v2_fixture import AUTHOR, plan_json, sourced             # noqa: E402

CODE = 'owned_covers_existing_tests'
GRANT = {'edit': True, 'commands': True, 'edit_tests': True, 'self_decide': ['Q1', 'Q2', 'Q3', 'Q4', 'Q5', 'Q9', 'Q12']}


class TestLintTest(HookFixture):
    def setUp(self):
        super().setUp()
        (self.root / 'tests').mkdir()
        (self.root / 'tests' / 'test_a.py').write_text('def test_a():\n    assert True\n', encoding='utf-8')
        (self.root / 'src' / 'b_test.py').write_text('x = 1\n', encoding='utf-8')
        self.git('add', '.'); self.git('commit', '-qm', 'existing tests')

    def contract(self, owned, **extra):
        return sourced(plan_json(scope={'owned': owned}, **extra))

    def lint_of(self, value, project=None, state=None):
        reader = lint.ReadOnlyLedger(project or self.root, state or self.ledger.state_root)
        reasons, warnings = lint.check(reader, value, AUTHOR)
        return reasons, warnings, [code for code, _ in warnings]

    def document(self):
        return json.loads((self.root / '.onecrew' / 'active-plan.json').read_text(encoding='utf-8'))

    # ---- I1, I2: plan lint -----------------------------------------------------------------------------------------------------------
    def test_lint_warns_owned_directory_with_existing_tests(self):
        _, warnings, codes = self.lint_of(self.contract(['a.txt', 'tests/']))
        self.assertIn(CODE, codes, warnings)
        text = dict(warnings)[CODE]
        self.assertIn('1 tệp', text); self.assertIn('tests/test_a.py', text)
        self.assertIn('edit_tests', text)                                       # how to resolve it
        _, warnings, codes = self.lint_of(self.contract(['a.txt', 'src/**', 'tests/*.py']))
        self.assertIn(CODE, codes)                                              # a glob, and a test named *_test in a folder that is not tests/
        self.assertIn('2 tệp', dict(warnings)[CODE])

    def test_lint_warns_owned_names_existing_test_file(self):
        _, warnings, codes = self.lint_of(self.contract(['a.txt', 'tests/test_a.py']))
        self.assertIn(CODE, codes, warnings)
        self.assertIn('tests/test_a.py', dict(warnings)[CODE])

    def test_lint_warning_does_not_fail_lint(self):
        value = self.contract(['a.txt', 'tests/'])
        reasons, _, codes = self.lint_of(value)
        self.assertIn(CODE, codes)
        self.assertEqual(reasons, [], 'the warning must not be a refusal')
        path = Path(self.temp.name) / 'contract.json'
        path.write_text(json.dumps(value), encoding='utf-8')
        done = subprocess.run([sys.executable, '-X', 'utf8', '-m', 'onecrew', '--project', str(self.root), '--state-root', str(self.state),
                               'plan', 'lint', '--file', str(path), '--author', AUTHOR], capture_output=True, cwd=REPO, timeout=120)
        out = done.stdout.decode('utf-8', 'replace') + done.stderr.decode('utf-8', 'replace')
        self.assertEqual(done.returncode, 0, out)
        self.assertIn(CODE, out)

    def test_lint_quiet_for_new_test_file_only(self):
        _, warnings, codes = self.lint_of(self.contract(['a.txt', 'tests/test_new.py']))
        self.assertNotIn(CODE, codes, warnings)

    def test_lint_quiet_when_edit_tests_granted(self):
        _, warnings, codes = self.lint_of(self.contract(['a.txt', 'tests/'], authority=dict(GRANT)))
        self.assertNotIn(CODE, codes, warnings)

    def test_lint_quiet_outside_git(self):
        for git in (False, True):                                               # no repository; a repository with no commit
            with self.subTest(git=git), tempfile.TemporaryDirectory() as folder:
                project = Path(folder) / 'p'; project.mkdir()
                (project / 'a.txt').write_text('one\n'); (project / 'tests').mkdir()
                (project / 'tests' / 'test_a.py').write_text('x = 1\n')
                if git: subprocess.run(['git', '-C', str(project), 'init', '-q'], check=True)
                state = Path(folder) / 'state'
                Ledger(project, state)
                _, warnings, codes = self.lint_of(self.contract(['a.txt', 'tests/']), project=project, state=state)
                self.assertNotIn(CODE, codes, warnings)

    # ---- I3 (option canh-bao-va-chan): the exported list and the hook ---------------------------------------------------------------
    def test_export_lists_existing_tests_when_edit_tests_not_granted(self):
        self.enforce(value=owned_plan(scope={'owned': ['a.txt', 'src/', 'tests/']}))
        self.assertEqual(self.document().get('frozen_tests'), ['src/b_test.py', 'tests/test_a.py'])
        (self.root / 'tests' / 'test_new.py').write_text('x = 2\n', encoding='utf-8')
        self.git('add', '.'); self.git('commit', '-qm', 'a new test written by the work')
        active_plan.export(self.ledger, 'P1')                                   # a refresh of the same approved revision keeps the list
        self.assertEqual(self.document().get('frozen_tests'), ['src/b_test.py', 'tests/test_a.py'])
        state_copy = json.loads(namespaces.active_file(self.ledger, 'P1').read_text(encoding='utf-8'))
        self.assertEqual(state_copy.get('frozen_tests'), self.document().get('frozen_tests'))

    def test_export_lists_nothing_when_edit_tests_granted(self):
        self.enforce(value=owned_plan(scope={'owned': ['a.txt', 'src/', 'tests/']}, authority=dict(GRANT)))
        self.assertEqual(self.document().get('frozen_tests') or [], [])

    def test_hook_refuses_edit_of_existing_test(self):
        self.enforce(value=owned_plan(scope={'owned': ['a.txt', 'src/', 'tests/']}))
        code, out, err = self.run_hook('check', self.edit('tests/test_a.py'))
        self.assertEqual(code, 2, 'an existing test was changed: ' + out + err)
        self.assertEqual(self.violations()[-1]['rule'], 'existing_test')
        self.assertEqual(self.run_hook('check', self.shell('echo x > tests/test_a.py'))[0], 2)    # a shell write it can read
        for allowed in ('tests/test_new.py', 'src/x.py', 'a.txt'):              # a new test file, and the rest of owned
            with self.subTest(path=allowed):
                code, out, err = self.run_hook('check', self.edit(allowed))
                self.assertEqual(code, 0, out + err)
        active_plan.set_mode(self.ledger, 'log'); active_plan.export(self.ledger, 'P1')
        code, out, err = self.run_hook('check', self.edit('tests/test_a.py'))
        self.assertEqual(code, 0, out + err)                                    # log mode records, never blocks
        self.assertEqual((self.violations()[-1]['rule'], self.violations()[-1]['event']), ('existing_test', 'logged'))

    def test_hook_old_export_without_frozen_tests_unchanged(self):
        self.enforce(value=owned_plan(scope={'owned': ['a.txt', 'src/', 'tests/']}))
        for path in (self.root / '.onecrew' / 'active-plan.json', namespaces.active_file(self.ledger, 'P1')):   # as an older build exported it
            document = json.loads(Path(path).read_text(encoding='utf-8')); document.pop('frozen_tests', None)
            Path(path).write_text(json.dumps(document), encoding='utf-8')
        for path in ('tests/test_a.py', 'tests/test_new.py', 'src/x.py'):
            with self.subTest(path=path):
                code, out, err = self.run_hook('check', self.edit(path))
                self.assertEqual(code, 0, out + err)

    def test_tampered_when_frozen_tests_dropped(self):
        copy = {'plan': 'P1', 'revision': 1, 'frozen_tests': ['tests/test_a.py']}
        self.assertTrue(hook_cli.tampered({'plan': 'P1', 'revision': 1}, copy), 'a copy without the frozen tests is not the same plan')
        self.assertFalse(hook_cli.tampered(dict(copy), copy))
        self.enforce(value=owned_plan(scope={'owned': ['a.txt', 'src/', 'tests/']}))
        inside = self.root / '.onecrew' / 'active-plan.json'
        document = json.loads(inside.read_text(encoding='utf-8')); document.pop('frozen_tests', None)
        inside.write_text(json.dumps(document), encoding='utf-8')
        code, out, err = self.run_hook('check', self.edit('src/x.py'))
        self.assertEqual(code, 2, 'the project copy dropped the frozen tests and the hook still trusted it: ' + out + err)
