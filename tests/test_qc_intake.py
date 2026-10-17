"""QC MVP-1 intake and 0-call scope check, against throw-away Git repositories."""
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from onecrew.qc_intake import intake, scope_check, evaluate, MAX_FILE

OWNED = ['app/lib/main.dart', 'app/lib/util.dart', 'app/test/main_test.dart']
TESTS = ['app/test/main_test.dart']
RECIPE = {'owned': OWNED, 'tests': TESTS}


def run(repo, *args, stdin=None):
    env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
    env.update(GIT_AUTHOR_NAME='t', GIT_AUTHOR_EMAIL='t@example.invalid', GIT_COMMITTER_NAME='t',
               GIT_COMMITTER_EMAIL='t@example.invalid')
    done = subprocess.run(['git', '-c', 'core.autocrlf=false', '-C', str(repo), *args], capture_output=True, env=env,
                          input=stdin, check=True)
    return done.stdout.decode().strip()


class Repo:
    """A repository whose master holds the pinned base; `branch` makes candidate commits on top of it."""
    def __init__(self, root, sub=''):
        self.root = Path(root)
        subprocess.run(['git', 'init', '-q', '-b', 'master', str(self.root)], check=True, capture_output=True)
        self.sub = sub
        self.links = []
        self.project = self.root / sub if sub else self.root
        self.write('app/lib/main.dart', b'int add(int a,int b)=>a-b;\n')
        self.write('app/lib/util.dart', b'int one()=>1;\n')
        self.write('app/lib/other.dart', b'int two()=>2;\n')
        self.write('app/test/main_test.dart', b'// base test\n')
        self.commit('base')
        self.base = run(self.root, 'rev-parse', 'HEAD')

    def path(self, name):
        return self.root / (self.sub + '/' + name if self.sub else name)

    def write(self, name, data):
        target = self.path(name)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)

    def commit(self, message):
        run(self.root, 'add', '-A')
        for entry in self.links:  # after add -A, which would drop an index-only entry whose file is not on disk
            run(self.root, 'update-index', '--add', '--cacheinfo', entry)
        self.links = []
        run(self.root, 'commit', '-q', '--allow-empty', '-m', message)

    def branch(self, name, edit):
        run(self.root, 'checkout', '-q', '-b', name, self.base)
        edit(self)
        self.commit(name)
        head = run(self.root, 'rev-parse', 'HEAD')
        run(self.root, 'checkout', '-q', 'master')
        return head

    def link(self, name, target=b'x'):
        """Record a symlink entry in the index without needing symlink support from the file system."""
        sha = run(self.root, 'hash-object', '-w', '--stdin', stdin=target)
        self.links.append('120000,' + sha + ',' + (self.sub + '/' if self.sub else '') + name)


def good(repo):
    repo.write('app/lib/main.dart', b'int add(int a,int b)=>a+b;\n')
    repo.write('app/test/main_test.dart', b'// regression test for add\n')


class IntakeBase(unittest.TestCase):
    sub = ''

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = Repo(Path(self.tmp.name) / 'repo', self.sub)

    def codes(self, reasons):
        return sorted({r['code'] for r in reasons})

    def check(self, edit, name='cand'):
        head = self.repo.branch(name, edit)
        return scope_check(self.repo.project, self.repo.base, head, RECIPE)


class ScopeCheckTests(IntakeBase):
    def test_a_clean_candidate_passes_with_no_reasons(self):
        self.assertEqual(self.check(good), [])

    def test_path_outside_owned_is_rejected_with_its_path(self):
        def edit(repo):
            good(repo); repo.write('app/lib/other.dart', b'int two()=>22;\n')
        reasons = self.check(edit)
        self.assertEqual(self.codes(reasons), ['path_outside_owned'])
        self.assertEqual(reasons[0]['path'], 'app/lib/other.dart')

    def test_new_file_outside_owned_is_rejected(self):
        def edit(repo):
            good(repo); repo.write('docs/note.md', b'hi\n')
        self.assertEqual(self.codes(self.check(edit)), ['path_outside_owned'])

    def test_deleted_file_is_rejected_even_if_owned(self):
        def edit(repo):
            good(repo); repo.path('app/lib/util.dart').unlink()
        reasons = self.check(edit)
        self.assertEqual(self.codes(reasons), ['deleted'])
        self.assertEqual(reasons[0]['path'], 'app/lib/util.dart')

    def test_rename_is_rejected(self):
        def edit(repo):
            good(repo)
            repo.path('app/lib/util.dart').rename(repo.path('app/lib/util_renamed.dart'))
        reasons = self.check(edit)
        codes = self.codes(reasons)
        self.assertIn('renamed', codes)
        self.assertIn('path_outside_owned', codes)  # the new name is not owned either
        detail = [r['detail'] for r in reasons if r['code'] == 'renamed'][0]
        self.assertIn('Git detected a rename', detail)  # tell the author why an identical delete+add is refused
        self.assertIn('edits to owned files', detail)

    def test_type_change_to_symlink_is_rejected(self):
        def edit(repo):
            good(repo); repo.path('app/lib/util.dart').unlink(); repo.link('app/lib/util.dart')
        self.assertEqual(self.codes(self.check(edit)), ['type_changed'])

    def test_added_symlink_to_an_owned_path_is_rejected(self):
        # an owned path that does not exist at base, added as a link
        recipe = {'owned': OWNED + ['app/lib/linked.dart'], 'tests': TESTS}
        head = self.repo.branch('cand', lambda r: (good(r), r.link('app/lib/linked.dart')))
        reasons = scope_check(self.repo.project, self.repo.base, head, recipe)
        self.assertEqual(self.codes(reasons), ['symlink'])

    def test_binary_content_is_rejected(self):
        def edit(repo):
            good(repo); repo.write('app/lib/util.dart', b'int one()=>1;\n\x00\x01\x02')
        self.assertEqual(self.codes(self.check(edit)), ['binary'])

    def test_non_utf8_text_is_rejected(self):
        def edit(repo):
            good(repo); repo.write('app/lib/util.dart', b'// caf\xe9 \xff\xfe\nint one()=>1;\n')
        self.assertEqual(self.codes(self.check(edit)), ['non_utf8'])

    def test_file_over_the_limit_is_rejected_and_the_limit_itself_is_accepted(self):
        def over(repo):
            good(repo); repo.write('app/lib/util.dart', b'a' * (MAX_FILE + 1))
        self.assertEqual(self.codes(self.check(over, 'over')), ['file_too_large'])

        def exact(repo):
            good(repo); repo.write('app/lib/util.dart', b'a' * MAX_FILE)
        self.assertEqual(self.check(exact, 'exact'), [])

    def test_missing_test_change_is_rejected(self):
        def edit(repo):
            repo.write('app/lib/main.dart', b'int add(int a,int b)=>a+b;\n')
        self.assertEqual(self.codes(self.check(edit)), ['no_test_change'])

    def test_missing_production_change_is_rejected(self):
        def edit(repo):
            repo.write('app/test/main_test.dart', b'// only a test\n')
        self.assertEqual(self.codes(self.check(edit)), ['no_production_change'])

    def test_empty_candidate_reports_both_missing_parts(self):
        self.assertEqual(self.codes(self.check(lambda repo: None)), ['no_production_change', 'no_test_change'])

    def test_every_reason_is_reported_not_just_the_first(self):
        def edit(repo):
            repo.write('app/lib/other.dart', b'int two()=>22;\n')       # outside owned
            repo.write('app/lib/util.dart', b'\x00binary')              # binary
            repo.path('app/lib/main.dart').unlink()                     # deleted (and so no production change)
        reasons = self.check(edit)
        self.assertEqual(self.codes(reasons), ['binary', 'deleted', 'no_test_change', 'path_outside_owned'])
        for item in reasons:
            self.assertEqual(sorted(item), ['code', 'detail', 'path'])

    def test_recipe_test_absent_from_the_candidate_is_reported(self):
        recipe = {'owned': OWNED + ['app/test/extra_test.dart'], 'tests': TESTS + ['app/test/extra_test.dart']}
        head = self.repo.branch('cand', good)
        reasons = scope_check(self.repo.project, self.repo.base, head, recipe)
        self.assertEqual([(r['code'], r['path']) for r in reasons], [('test_missing_at_ref', 'app/test/extra_test.dart')])


class SubdirectoryProjectTests(IntakeBase):
    sub = 'flutter_vimes'

    def test_owned_paths_are_relative_to_the_project_directory(self):
        self.assertEqual(self.check(good), [])

    def test_a_change_outside_the_project_directory_is_not_hidden(self):
        def edit(repo):
            good(repo)
            (repo.root / 'elsewhere.txt').write_bytes(b'outside the project\n')
        reasons = self.check(edit)
        self.assertEqual(self.codes(reasons), ['path_outside_owned'])
        self.assertEqual(reasons[0]['path'], 'elsewhere.txt')


class IntakeTests(IntakeBase):
    def report(self, data=b'Fixed add and added a regression test.\n'):
        path = Path(self.tmp.name) / 'report.md'
        path.write_bytes(data)
        return path

    def test_pins_author_head_base_and_report_hash(self):
        head = self.repo.branch('cand', good)
        report = self.report()
        record = intake(self.repo.project, 'cand', report, 'claude-code')
        self.assertEqual(record['reasons'], [])
        self.assertEqual((record['head'], record['base'], record['merge_base']), (head, self.repo.base, self.repo.base))
        self.assertEqual((record['author'], record['branch']), ('claude-code', 'cand'))
        import hashlib
        self.assertEqual(record['report_sha'], hashlib.sha256(report.read_bytes()).hexdigest())
        self.assertIn('regression test', record['report'])

    def test_unknown_ref_is_rejected(self):
        record = intake(self.repo.project, 'no-such-branch', self.report(), 'a')
        self.assertEqual([r['code'] for r in record['reasons']], ['ref_unresolved'])

    def test_ref_from_another_repository_is_rejected(self):
        other = Repo(Path(self.tmp.name) / 'other')
        other.base_head = other.branch('cand', good)
        for ref in (other.base_head, str(other.root), str(other.root / '.git')):
            with self.subTest(ref=ref):
                record = intake(self.repo.project, ref, self.report(), 'a')
                self.assertEqual([r['code'] for r in record['reasons']], ['ref_unresolved'])

    def test_option_like_ref_is_not_passed_to_git(self):
        record = intake(self.repo.project, '--output=evil', self.report(), 'a')
        self.assertEqual([r['code'] for r in record['reasons']], ['ref_unresolved'])
        self.assertFalse((self.repo.project / 'evil').exists())

    def test_candidate_not_built_on_project_head_is_rejected(self):
        self.repo.branch('cand', good)
        self.repo.write('app/lib/other.dart', b'int two()=>3;\n')
        self.repo.commit('project moved on')
        record = intake(self.repo.project, 'cand', self.report(), 'a')
        self.assertEqual([r['code'] for r in record['reasons']], ['base_not_head'])

    def test_missing_or_non_utf8_report_is_a_reason_not_an_exception(self):
        self.repo.branch('cand', good)
        gone = intake(self.repo.project, 'cand', Path(self.tmp.name) / 'nope.md', 'a')
        self.assertEqual([r['code'] for r in gone['reasons']], ['report_unreadable'])
        bad = intake(self.repo.project, 'cand', self.report(b'\xff\xfe\x00bad'), 'a')
        self.assertEqual([r['code'] for r in bad['reasons']], ['report_not_utf8'])
        self.assertIsNotNone(bad['report_sha'])

    def test_evaluate_unions_intake_and_scope_reasons(self):
        self.repo.branch('cand', lambda repo: repo.write('app/lib/other.dart', b'int two()=>3;\n'))
        record = evaluate(self.repo.project, 'cand', RECIPE, self.report(), 'a')
        self.assertEqual(sorted({r['code'] for r in record['reasons']}),
                         ['no_production_change', 'no_test_change', 'path_outside_owned'])

    def test_evaluate_passes_a_good_candidate_and_never_touches_the_project(self):
        self.repo.branch('cand', good)
        before = run(self.repo.root, 'status', '--porcelain=v1') + run(self.repo.root, 'rev-parse', 'HEAD', 'cand')
        record = evaluate(self.repo.project, 'cand', RECIPE, self.report(), 'a')
        self.assertEqual(record['reasons'], [])
        after = run(self.repo.root, 'status', '--porcelain=v1') + run(self.repo.root, 'rev-parse', 'HEAD', 'cand')
        self.assertEqual(before, after)


if __name__ == '__main__':
    unittest.main()
