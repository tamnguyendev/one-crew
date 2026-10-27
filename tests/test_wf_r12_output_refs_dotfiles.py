"""R12 (Codex finding P1-C): repository paths whose last segment is a hidden file (`.gitignore:1`, `.editorconfig:2`,
`src/.env.example:3`) or that run through hidden directories (`.github/workflows/build.yml:5`, `.husky/pre-commit:2`) are
references and are judged against the candidate tree. Before R12 a dot-leading last segment was never scanned, so
`.gitignore:999999` passed with total=0. Negative controls (URLs, host:port, times, ratios, image tags, `e.g.:`, ellipses,
decimals, ordinary prose) stay neither references nor offenders."""
import unittest
from unittest import mock

from onecrew.v2.verifiers import output_refs
from tests import test_wf_r10_output_refs as r10

TREE = {'.gitignore': 1, '.editorconfig': 4, '.dockerignore': 2, '.env': 3, '.github/workflows/build.yml': 9,
        'src/.env.example': 5, '.config/x.toml': 6, '.vscode/settings.json': 7, '.husky/pre-commit': 4, 'README.md': 3}


def judge(text, tree=TREE, outputs=()):
    return output_refs.check(tree, output_refs.scan(text), list(outputs))


def summary(got):
    return got['result'], got['counts']['total'], got['counts']['resolved'], got['counts']['unresolvable'], got['counts']['unverifiable']


class DotfileReferences(unittest.TestCase):
    def test_a_counterexample_gitignore_beyond_eof_fails(self):
        got = judge('The ignore rule is at .gitignore:999999.', tree={'.gitignore': 1})
        self.assertEqual(summary(got), ('fail', 1, 0, 1, 0), got)
        self.assertEqual(got['reasons']['line_outside_file'], 1)
        self.assertIn('.gitignore:999999', got['offenders'][0])

    def test_b_gitignore_and_editorconfig_resolve_and_beyond_eof_fails(self):
        self.assertEqual(summary(judge('See .gitignore:1 and .editorconfig:2.')), ('pass', 2, 2, 0, 0))
        got = judge('See .gitignore:2 and .editorconfig:5.')
        self.assertEqual(summary(got), ('fail', 2, 0, 2, 0), got)

    def test_c_hidden_directory_paths_valid_and_wrong(self):
        self.assertEqual(summary(judge('Build at .github/workflows/build.yml:5 and `.github/workflows/build.yml:1-9`.')), ('pass', 2, 2, 0, 0))
        got = judge('Build at .github/workflow/build.yml:5 and .github/workflows/biuld.yml:5.')
        self.assertEqual((summary(got), got['reasons']['no_such_file']), (('fail', 2, 0, 2, 0), 2), got)

    def test_d_nonexistent_dotfiles_are_offenders_not_nothing(self):
        for text in ('.prettierrc:3', '.npmrc:1', '.nvmrc:1', 'src/.env.local:2', '.eslintrc.json:4', '.tool-versions:1'):
            with self.subTest(text):
                got = judge('Configured in ' + text + '.')
                self.assertEqual(summary(got)[:2], ('fail', 1), got)
                self.assertEqual(got['counts']['unresolvable'], 1, got)

    def test_e_extensionless_and_extension_files_inside_hidden_directories(self):
        self.assertEqual(summary(judge('.husky/pre-commit:2 .config/x.toml:6 src/.env.example:3')), ('pass', 3, 3, 0, 0))
        got = judge('.husky/pre-push:2 .config/y.toml:1 .husky/pre-commit:9', tree=TREE)
        self.assertEqual(summary(got), ('fail', 3, 0, 3, 0), got)
        # a hidden directory that is not in the tree still makes the token a repository path (never prose)
        got = judge('.circleci/config:3', tree={'README.md': 3})
        self.assertEqual(summary(got), ('fail', 1, 0, 1, 0), got)

    def test_f_other_names_of_the_same_class(self):
        self.assertEqual(summary(judge('.dockerignore:2, .env:3, .vscode/settings.json:7, .config/x.toml:1-6 and .editorconfig:4')),
                         ('pass', 5, 5, 0, 0))
        got = judge('.dockerignore:3 .env:4 .vscode/settings.json:8')
        self.assertEqual(summary(got), ('fail', 3, 0, 3, 0), got)

    def test_g_bare_hidden_file_that_lives_only_deeper_is_a_bare_basename(self):
        got = judge('.env.example:3 is cited bare.', tree={'src/.env.example': 5})
        self.assertEqual((got['result'], got['reasons']['bare_basename']), ('fail', 1), got)

    def test_h_malformed_dotfile_reference_is_unverifiable(self):
        for text in ('.gitignore:1:5', '.gitignore:line 1', '.gitignore:L1', '.editorconfig:2-x'):
            with self.subTest(text):
                got = judge(text)
                self.assertEqual((got['result'], got['counts']['unverifiable']), ('fail', 1), got)

    def test_i_uppercase_leading_dot_word_is_ambiguous_and_tree_anchored(self):
        # `.NET:8` is a product name in prose; an uppercase dot word is judged only when the tree anchors it
        got = judge('Runs on .NET:8 today.')
        self.assertEqual((got['result'], got['counts']['total'], got['ignored']['count']), ('pass', 0, 1), got)
        got = judge('.DS_Store:1 and .DS_Store:9', tree={'.DS_Store': 2})
        self.assertEqual(summary(got), ('fail', 2, 1, 1, 0), got)


class DotfileNegativeControls(unittest.TestCase):
    CONTROLS = ['https://github.com/o/r/blob/main/.gitignore:3', 'http://example.com:8080/.env', 'example.com:443',
                'localhost:8080', '127.0.0.1:5000', 'at 12:30 today', 'at 12:30:45', 'ratio 16:9', 'ratio .5:1',
                'scale 1.5:1', 'image: nginx:1.25', 'FROM node:18', 'e.g.:1 point', 'i.e.:2', 'etc.:3', 'Wait...:3 times',
                '...:1', '..:2', 'and so on…:3', 'Note: see .gitignore for more.', 'the .gitignore file: 3 rules', 'Lưu ý: 3 điều',
                'Bước 2: 5 phút', '.5:3', 'a .:3', 'C:\\Users\\NUC\\.config', 'D:/OneCrewRuns/.cache', 'v1.2:3', 'end.:4']

    def test_controls_are_not_references_and_not_offenders(self):
        for text in self.CONTROLS:
            with self.subTest(text):
                got = judge(text)
                self.assertEqual((got['result'], got['counts']['total'], got['offender_count']), ('pass', 0, 0), got)

    def test_r10_r11_corpus_unchanged(self):
        from tests.test_wf_r11_output_refs import NegativeControls
        for text in NegativeControls.CONTROLS:
            with self.subTest(text):
                got = judge(text)
                self.assertEqual((got['result'], got['counts']['total'], got['offender_count']), ('pass', 0, 0), got)


DOTFILES = {'.gitignore': 'build/\n', '.editorconfig': 'root = true\n[*]\nindent_style = space\n',
            '.github/workflows/build.yml': ''.join('step %d\n' % n for n in range(1, 8)), '.husky/pre-commit': 'npm test\n'}


class DotfilesThroughCandidateChecker(r10.OutputRefsFixture):
    def setUp(self):
        with mock.patch.dict(r10.FILES, DOTFILES):
            r10.OutputRefsFixture.setUp(self)

    def test_j_counterexample_gitignore_999999_fails_m1(self):
        out = self.assertOutFails(self.verify_reports({'docs/rep/K03.md': 'Ignored per .gitignore:999999.\n'}), '.gitignore:999999')
        self.assertEqual((out['counts']['total'], out['counts']['unresolvable']), (1, 1), out)

    def test_k_nonexistent_dotfile_and_wrong_hidden_path_fail_m1(self):
        out = self.assertOutFails(self.verify_reports({'docs/rep/K03.md': 'See .dockerignore:1 and .github/workflows/biuld.yml:2.\n'}),
                                  '.dockerignore:1', '.github/workflows/biuld.yml:2')
        self.assertEqual(out['counts']['unresolvable'], 2, out)

    def test_l_valid_dotfile_references_and_controls_pass_m1(self):
        text = ('Ignore at .gitignore:1, style at .editorconfig:2-3, CI at .github/workflows/build.yml:5, hook .husky/pre-commit:1.\n'
                'Server localhost:8080 at 12:30, ratio .5:1, image nginx:1.25, e.g.: see https://x.io/.gitignore:9 ...:3\n')
        result = self.verify_reports({'docs/rep/K03.md': text})
        out = result['observed']['output_check']
        self.assertEqual((result['result'], out['result'], out['counts']['total'], out['counts']['resolved']), ('pass', 'pass', 4, 4), out)


if __name__ == '__main__':
    unittest.main()
