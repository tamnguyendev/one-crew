"""Where the Git repository sits relative to the project root.

QC trial J6 found `project_not_a_repository` + `ref_unresolved`: the recipe's package (flutter_vimes) is the repository and
the project root is its PARENT. Recipe paths are relative to the project; Git paths to the repository. Three layouts:
  same   project == repository                       owned 'app/lib/main.dart'
  parent project is the PARENT of the repository     owned 'flutter_vimes/lib/main.dart' (repo-relative 'lib/main.dart')
  child  project is a sub-directory of the repository owned 'app/lib/main.dart' (repo-relative 'mobile/app/lib/main.dart')
"""
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from onecrew import qc_gate
from onecrew.qc_intake import intake, scope_check, candidate_files, evaluate

GOOD_MAIN = 'int add(int a,int b)=>a+b;\n'
GOOD_TEST = '// regression test for add\n'


def git(repo, *args):
    env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
    env.update(GIT_AUTHOR_NAME='t', GIT_AUTHOR_EMAIL='t@example.invalid', GIT_COMMITTER_NAME='t', GIT_COMMITTER_EMAIL='t@example.invalid')
    return subprocess.run(['git', '-c', 'core.autocrlf=false', '-C', str(repo), *args], capture_output=True, env=env,
                          check=True).stdout.decode().strip()


class Layout(unittest.TestCase):
    package = 'app'       # recipe package, relative to the project
    repo_down = ''        # repository root relative to the project root ('' = the project root or above it)
    project_sub = ''      # project root relative to the repository root

    @classmethod
    def setUpClass(cls):
        if cls is Layout: raise unittest.SkipTest('layout base')

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        top = Path(self.tmp.name)
        self.repo_root = top / self.repo_down if self.repo_down else top
        self.project = self.repo_root / self.project_sub if self.project_sub else self.repo_root
        if self.repo_down: self.project = top
        self.repo_root.mkdir(parents=True, exist_ok=True); self.project.mkdir(parents=True, exist_ok=True)
        subprocess.run(['git', 'init', '-q', '-b', 'master', str(self.repo_root)], check=True, capture_output=True)
        P = self.package
        self.main, self.util, self.other, self.test = (P + '/lib/main.dart', P + '/lib/util.dart', P + '/lib/other.dart', P + '/test/main_test.dart')
        self.recipe = {'package': P, 'owned': [self.main, self.util, self.test], 'tests': [self.test]}
        for name, text in ((self.main, 'int add(int a,int b)=>a-b;\n'), (self.util, 'int one()=>1;\n'),
                           (self.other, 'int two()=>2;\n'), (self.test, '// base test\n')):
            self.write(name, text)
        self.commit('base')
        self.base = git(self.repo_root, 'rev-parse', 'HEAD')

    def write(self, name, text):
        target = self.project / name
        target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(text.encode())

    def commit(self, message):
        git(self.repo_root, 'add', '-A'); git(self.repo_root, 'commit', '-q', '--allow-empty', '-m', message)

    def branch(self, name, files):
        git(self.repo_root, 'checkout', '-q', '-b', name, self.base)
        for path, text in files.items(): self.write(path, text)
        self.commit(name)
        head = git(self.repo_root, 'rev-parse', 'HEAD')
        git(self.repo_root, 'checkout', '-q', 'master')
        return head

    def good(self, name='cand'):
        return self.branch(name, {self.main: GOOD_MAIN, self.test: GOOD_TEST})

    def codes(self, reasons):
        return sorted({r['code'] for r in reasons})


class LayoutCases:
    def test_intake_resolves_the_ref_and_the_pinned_base(self):
        head = self.good()
        record = intake(self.project, 'cand', author='a', recipe=self.recipe)
        self.assertEqual(record['reasons'], [])
        self.assertEqual((record['head'], record['base'], record['merge_base']), (head, self.base, self.base))

    def test_a_good_candidate_passes_the_scope_check(self):
        head = self.good()
        self.assertEqual(scope_check(self.project, self.base, head, self.recipe), [])

    def test_a_path_outside_owned_is_rejected_with_its_project_relative_path(self):
        head = self.branch('cand', {self.main: GOOD_MAIN, self.test: GOOD_TEST, self.other: 'int two()=>22;\n'})
        reasons = scope_check(self.project, self.base, head, self.recipe)
        self.assertEqual(self.codes(reasons), ['path_outside_owned'])
        self.assertEqual(reasons[0]['path'], self.other)

    def test_missing_test_and_production_changes_are_found_in_this_layout_too(self):
        head = self.branch('cand', {self.util: 'int one()=>11;\n'})
        self.assertEqual(self.codes(scope_check(self.project, self.base, head, self.recipe)), ['no_test_change'])
        head = self.branch('cand2', {self.test: '// only a test\n'})
        self.assertEqual(self.codes(scope_check(self.project, self.base, head, self.recipe)), ['no_production_change'])

    def test_candidate_files_are_project_relative_as_install_candidate_needs(self):
        head = self.good()
        files = candidate_files(self.project, self.base, head, self.recipe)
        self.assertEqual(files, [{'path': self.main, 'text': GOOD_MAIN}, {'path': self.test, 'text': GOOD_TEST}])

    def test_unchanged_recipe_tests_are_still_supplied(self):
        recipe = dict(self.recipe, tests=[self.test, self.util], owned=self.recipe['owned'])
        head = self.good()
        names = [f['path'] for f in candidate_files(self.project, self.base, head, recipe)]
        self.assertEqual(names, sorted([self.main, self.test, self.util]))

    def test_evaluate_passes_a_good_candidate(self):
        self.good()
        report = Path(self.tmp.name) / 'r.md'; report.write_text('fixed', encoding='utf-8')
        record = evaluate(self.project, 'cand', self.recipe, report, 'a')
        self.assertEqual(record['reasons'], [])

    def test_precheck_uses_the_same_repository_and_notices_a_moved_head(self):
        head = self.good()
        runtime = SimpleNamespace(ledger=SimpleNamespace(project=self.project))
        qc = {'reasons': [], 'base': self.base, 'head': head}
        self.assertEqual(qc_gate.precheck(runtime, qc, self.recipe), ([], None))
        self.write(self.other, 'int two()=>3;\n'); self.commit('project moved on')
        reasons, where = qc_gate.precheck(runtime, qc, self.recipe)
        self.assertEqual(([r['code'] for r in reasons], where), (['base_moved'], 'base'))


class SameLayoutTests(LayoutCases, Layout):
    pass


class ParentLayoutTests(LayoutCases, Layout):
    package = 'flutter_vimes'
    repo_down = 'flutter_vimes'

    def test_the_repository_is_found_below_the_project_root(self):
        from onecrew.qc_intake import locate
        found = locate(self.project, self.recipe)
        self.assertEqual(found.root.resolve(), (self.project / 'flutter_vimes').resolve())

    def test_a_ref_that_lives_only_in_another_repository_is_still_unresolved(self):
        other = Path(self.tmp.name) / 'elsewhere'; other.mkdir()
        subprocess.run(['git', 'init', '-q', str(other)], check=True, capture_output=True)
        (other / 'f').write_text('x'); git(other, 'add', '-A'); git(other, 'commit', '-q', '-m', 'x')
        record = intake(self.project, git(other, 'rev-parse', 'HEAD'), recipe=self.recipe)
        self.assertEqual([r['code'] for r in record['reasons']], ['ref_unresolved'])


class ChildLayoutTests(LayoutCases, Layout):
    project_sub = 'mobile'

    def test_a_change_outside_the_project_directory_is_not_hidden(self):
        git(self.repo_root, 'checkout', '-q', '-b', 'cand', self.base)
        self.write(self.main, GOOD_MAIN); self.write(self.test, GOOD_TEST)
        (self.repo_root / 'README.md').write_text('outside the project'); self.commit('cand')
        git(self.repo_root, 'checkout', '-q', 'master')
        reasons = scope_check(self.project, self.base, 'cand', self.recipe)
        self.assertEqual(self.codes(reasons), ['path_outside_owned'])
        self.assertEqual(reasons[0]['path'], 'README.md')


class NoRepositoryTests(unittest.TestCase):
    def test_a_package_that_is_in_no_repository_is_a_reason_not_a_crash(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / 'app').mkdir()
            recipe = {'package': 'app', 'owned': ['app/lib/a.dart', 'app/test/a_test.dart'], 'tests': ['app/test/a_test.dart']}
            record = intake(tmp, 'master', recipe=recipe)
            self.assertEqual([r['code'] for r in record['reasons']], ['package_not_in_repository'])
            self.assertEqual([r['code'] for r in scope_check(tmp, 'a' * 40, 'b' * 40, recipe)], ['package_not_in_repository'])


if __name__ == '__main__':
    unittest.main()
