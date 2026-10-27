"""R13 (Codex finding P1-H): a reference to a path that exists in the candidate tree is always checked, whatever its name shape.
Before R13 `_one` discarded a hidden name whose rest starts with a digit (`.1password`) or whose dotted tail is not a letter
extension (`.v1.2`) while scanning, before the tree could be consulted, so `.1password:999999` and `.v1.2:999999` passed with
total=0 and ignored=0 although both files exist. Rule under test (module docstring "R13 tree anchoring wins"): such a token is kept
as WEAK; check() judges it like any other reference when the tree anchors it (the exact path is a tree file, it has a separator and
its first segment is a top-level directory of the tree, a directory segment is a lowercase hidden name, or it is a bare basename of a
tree file) and otherwise drops it silently (not counted, not an offender, not in `ignored`). Negative controls with no such tree
file (URLs, host:port, times, ratios, versions, image tags, decimals, ellipses, `e.g.:`, prose) stay uncounted."""
import unittest
from unittest import mock

from onecrew.v2.verifiers import output_refs
from tests import test_wf_r10_output_refs as r10

TREE = {'.1password': 1, '.v1.2': 1, '.2fa-codes': 3, '.v2': 2, '.9front': 2, 'tools/.1x': 4, 'README.md': 3}
PLAIN = {'README.md': 3, 'src/a.cs': 2, 'tools/run.sh': 5}   # no file of the digit / version / numeric-tail shape


def judge(text, tree=TREE, outputs=()):
    return output_refs.check(tree, output_refs.scan(text), list(outputs))


def summary(got):
    return got['result'], got['counts']['total'], got['counts']['resolved'], got['counts']['unresolvable'], got['counts']['unverifiable']


class TreeNamedReferences(unittest.TestCase):
    def test_a_digit_and_version_hidden_files_resolve(self):
        self.assertEqual(summary(judge('Vault at .1password:1 and pin .v1.2:1.')), ('pass', 2, 2, 0, 0))

    def test_b_codex_counterexample_beyond_eof_fails(self):
        got = judge('Secrets at .1password:999999 and .v1.2:999999.', tree={'.1password': 1, '.v1.2': 1})
        self.assertEqual(summary(got), ('fail', 2, 0, 2, 0), got)
        self.assertEqual(got['reasons']['line_outside_file'], 2, got)
        self.assertIn('.1password:999999', got['offenders'][0])
        self.assertIn('.v1.2:999999', got['offenders'][1])

    def test_c_other_names_of_the_same_class(self):
        self.assertEqual(summary(judge('.2fa-codes:3, .v2:2, .9front:1-2 and tools/.1x:4')), ('pass', 4, 4, 0, 0))
        got = judge('.2fa-codes:4 .v2:3 .9front:3 tools/.1x:5 .9front:2-3')
        self.assertEqual(summary(got), ('fail', 5, 0, 5, 0), got)

    def test_d_bare_basename_of_a_deeper_tree_file_is_an_offender(self):
        got = judge('Cited bare as .1x:1.', tree={'tools/.1x': 4})
        self.assertEqual((got['result'], got['reasons']['bare_basename']), ('fail', 1), got)

    def test_e_directory_anchored_wrong_paths_are_offenders(self):
        # the first segment is a top-level directory of the tree: a wrong citation, not prose
        got = judge('tools/.1y:1 and tools/v1.2:3', tree=TREE)
        self.assertEqual((summary(got), got['reasons']['no_such_file']), (('fail', 2, 0, 2, 0), 2), got)
        # a lowercase hidden directory segment anchors the path even when that directory is absent
        got = judge('.config/.1x:2 and .cache/v1.2:3', tree=PLAIN)
        self.assertEqual(summary(got), ('fail', 2, 0, 2, 0), got)

    def test_f_unanchored_digit_and_version_names_are_not_counted(self):
        for text in ('.1password:1', '.v1.2:3', '.9front:2', '1.2.3:4', '.v1.2.3:4', 'other/.1x:2', 'nope/v1.2:3'):
            with self.subTest(text):
                got = judge('See ' + text + ' here.', tree=PLAIN)
                self.assertEqual((summary(got), got['offender_count'], got['ignored']['count']), (('pass', 0, 0, 0, 0), 0, 0), got)

    def test_g_extension_only_and_numeric_tails_are_checked_when_the_file_exists(self):
        tree = {'.5': 1, '1.2.3': 3, 'notes.2024': 2, 'data/run.01': 1}
        self.assertEqual(summary(judge('.5:1 1.2.3:3 notes.2024:1-2 data/run.01:1', tree=tree)), ('pass', 4, 4, 0, 0))
        got = judge('.5:2 1.2.3:4 notes.2024:3 data/run.01:2 data/run.02:1', tree=tree)
        self.assertEqual(summary(got), ('fail', 5, 0, 5, 0), got)

    def test_h_malformed_tail_on_a_tree_file_is_unverifiable(self):
        for text in ('.1password:1:5', '.v1.2:L1', '.1password:line 1', '.v1.2:1-x'):
            with self.subTest(text):
                got = judge(text)
                self.assertEqual((got['result'], got['counts']['unverifiable']), ('fail', 1), got)

    def test_i_output_of_the_node_itself_is_skipped(self):
        got = judge('.1password:999', outputs=['.1password'])
        self.assertEqual((got['result'], got['counts']['total'], got['counts']['skipped_outputs']), ('pass', 0, 1), got)


class TreeNamedNegativeControls(unittest.TestCase):
    CONTROLS = ['https://example.com/.1password:3', 'http://h:80/.v1.2:9', 'example.com:443', '127.0.0.1:5000', '10.0.0.1:22',
                'localhost:8080', 'nginx-1.2:3', 'python3.12:1', 'image: nginx:1.25', 'FROM node:18.04', 'at 12:30', '12:30:45',
                'ratio 16:9', 'ratio .5:1', 'scale 1.5:1', 'v1.2:3', '.v1.2:3', '1.2.3:4', 'v2.2.0:1', '.NET8.0:1', 'e.g.:1', 'i.e.:2',
                'etc.:3', 'Wait...:3', '...:1', '..:2', '.-x:3', '.+1:2', 'Bước 2: 5 phút', 'Note:3 in prose', '.1password: 1 entry']

    def test_controls_without_such_tree_files_are_not_counted(self):
        for text in self.CONTROLS:
            with self.subTest(text):
                got = judge(text, tree=PLAIN)
                self.assertEqual((got['result'], got['counts']['total'], got['offender_count']), ('pass', 0, 0), got)

    def test_earlier_corpora_unchanged(self):
        from tests.test_wf_r11_output_refs import NegativeControls
        from tests.test_wf_r12_output_refs_dotfiles import DotfileNegativeControls
        for text in NegativeControls.CONTROLS + DotfileNegativeControls.CONTROLS:
            for tree in (PLAIN, TREE):
                with self.subTest(text=text, tree=sorted(tree)):
                    got = judge(text, tree=tree)
                    self.assertEqual((got['result'], got['counts']['total'], got['offender_count']), ('pass', 0, 0), got)

    def test_tree_anchoring_wins_for_a_ratio_shaped_name(self):
        # documented residual: when a file literally named `.5` exists, `.5:1` is a citation of it, never a ratio
        self.assertEqual(summary(judge('ratio .5:1', tree={'.5': 1})), ('pass', 1, 1, 0, 0))
        self.assertEqual(summary(judge('ratio .5:3', tree={'.5': 1}))[:4], ('fail', 1, 0, 1))


TREE_FILES = {'.1password': 'vault\n', '.v1.2': 'pin\n'}


class TreeNamesThroughCandidateChecker(r10.OutputRefsFixture):
    def setUp(self):
        with mock.patch.dict(r10.FILES, TREE_FILES):
            r10.OutputRefsFixture.setUp(self)

    def test_j_codex_counterexample_fails_m1(self):
        out = self.assertOutFails(self.verify_reports({'docs/rep/K03.md': 'Secrets at .1password:999999 and .v1.2:999999.\n'}),
                                  '.1password:999999', '.v1.2:999999')
        self.assertEqual((out['counts']['total'], out['counts']['unresolvable']), (2, 2), out)

    def test_k_valid_tree_names_and_controls_pass_m1(self):
        text = ('Vault .1password:1, pin .v1.2:1. Server 127.0.0.1:5000, nginx-1.2:3, python3.12:1, ratio .5:1, '
                'version 1.2.3:4, image nginx:1.25 at 12:30, e.g.: ...:3\n')
        result = self.verify_reports({'docs/rep/K03.md': text})
        out = result['observed']['output_check']
        self.assertEqual((result['result'], out['result'], out['counts']['total'], out['counts']['resolved']), ('pass', 'pass', 2, 2), out)


if __name__ == '__main__':
    unittest.main()
